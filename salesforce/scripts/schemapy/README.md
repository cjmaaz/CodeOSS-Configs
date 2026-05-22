# schemapy — Salesforce schema pipeline (TOON)

A 12-step Python pipeline that retrieves your org's metadata, generates a
[TOON](https://github.com/toon-format/spec/blob/main/SPEC.md)-encoded
ER schema, splits it into per-object folders, enriches every field
with active picklist values and metadata, layers in live record-count
usage stats, structurally detects junction objects, and renders a single
`ER.md` Mermaid diagram at the project root.

> **Encoding change.** Earlier versions of this pipeline emitted YAML.
> The output is now TOON (Token-Oriented Object Notation, v3.0). TOON is
> ~2-3× more token-efficient than YAML, which matters when feeding the
> schema into AI agents. All consumers (rules, skills, agent prompts)
> have been updated to load `.toon` files. See
> [`_toon_io.py`](_toon_io.py) for the small shim around the
> `toon-format` Python package.

---

## TL;DR

```bash
# 1. Install deps (one-time)
pip install -r salesforce/scripts/schemapy/requirements.txt

# 2. Make sure your default org is set
sf org login web --alias MyOrg
sf config set target-org=MyOrg

# 3. Run the pipeline (no inputs required)
python3 salesforce/scripts/schemapy/auto_generate_schema.py
```

That single command runs all 12 steps end-to-end. Output:

- `config/salesforce-er-schema.toon` — combined intermediate (Step 7)
- `config/schema/_index.toon` — master object index (Step 8)
- `config/schema/_search_index.toon` — flat field search index (Step 8)
- `config/schema/categories/*.toon` — objects grouped by category (Step 8)
- `config/schema/objects/<Object>/{schema,picklists,formulas}.toon` — per-object enriched data (Steps 8 + 9)
- `config/schema/_junctions.toon` — detected junction objects + parents (Step 11)
- `ER.md` (project root) — Mermaid ER diagram of every detected junction (Step 12)

---

## The 12 steps

| # | Owned by | What it does |
|---|---|---|
| 1 | `auto_generate_schema.py` | Detect default org from `.sf/config.json` (or `.sfdx/sfdx-config.json`) |
| 2 | `auto_generate_schema.py` | Detect the local objects directory (`force-app/main/default/objects` or first project entry in `sfdx-project.json`) |
| 3 | `auto_generate_schema.py` | Query the org for every sObject |
| 4 | `auto_generate_schema.py` | Filter system objects (History, Share, Feed, ChangeEvent, etc.) |
| 5 | `auto_generate_schema.py` | Cross-check against locally retrieved object metadata |
| 6 | `auto_generate_schema.py` | `sf project retrieve start` for any missing objects |
| 7 | [`generate_sf_er_schema.py`](generate_sf_er_schema.py) | Parse every `*.object-meta.xml` and emit `config/salesforce-er-schema.toon` (the combined intermediate) |
| 8 | [`split_schema_by_object.py`](split_schema_by_object.py) | Shard the combined intermediate into per-object folders + indexes |
| 9 | [`enrich_schema_with_picklists.py`](enrich_schema_with_picklists.py) | `sf sobject describe` per object — merge picklist values (ACTIVE only), default values, formulas, lookups, field dependencies, length/precision/scale, required/unique/externalId flags |
| 10 | [`collect_usage_stats.py`](collect_usage_stats.py) | Composite REST `composite/batch` queries (up to 25 SOQL queries per HTTP call) to pull per-picklist-value record counts + per-RecordType counts |
| 11 | [`detect_junctions.py`](detect_junctions.py) | Structurally classify objects as junctions (2+ real-business lookup parents + at least one promotion signal). Confidence tier (`high` / `medium` / `low` / `schema_only`) is derived from record counts collected in Step 10 |
| 12 | [`generate_er.py`](generate_er.py) | Render `ER.md` from `_junctions.toon` — markdown tables + per-tier Mermaid `erDiagram` blocks |

Steps 1–9 are mandatory; steps 10–12 add usage-aware classification and
the human-readable ER diagram. The orchestrator continues past a failure
in steps 10–12 (and prints a warning) because the per-object schema files
from steps 1–9 are still usable on their own.

---

## File layout

```
salesforce/scripts/schemapy/
├── README.md                          ← this file
├── requirements.txt                   ← toon-format>=0.9.0b1, certifi>=2024.0.0
│
├── auto_generate_schema.py            ← Steps 1-6 + orchestrator for 7-12
├── generate_sf_er_schema.py           ← Step 7: parse XML → combined TOON
├── split_schema_by_object.py          ← Step 8: shard + indexes
├── enrich_schema_with_picklists.py    ← Step 9: describe-based enrichment
├── collect_usage_stats.py             ← Step 10: record counts via composite/batch
├── detect_junctions.py                ← Step 11: structural junction detection
├── generate_er.py                     ← Step 12: ER.md renderer
│
├── _toon_io.py                        ← TOON dump/load + find_project_root
├── _sf_session.py                     ← Cached access token + composite/batch helper
└── _fields_tabular.py                 ← TOON tabular emission (per-object fields.toon)
```

### Helper modules

- **`_toon_io.py`** — wraps the `toon-format` PyPI package. Exposes
  `dump_toon`, `load_toon`, and `find_project_root` (walks up from the
  script's own location, so the pipeline works no matter where it is
  invoked from — not cwd-relative).
- **`_sf_session.py`** — fetches access token + instance URL + API
  version once via `sf org display --verbose --json`, then issues SOQL
  queries via Salesforce's `composite/batch` endpoint (25 queries per
  HTTP call). Used by `collect_usage_stats.py` and the count-fetch step
  of `detect_junctions.py`. Falls back to `certifi`'s CA bundle when the
  stdlib trust store is empty (python.org macOS builds, many venvs).
- **`_fields_tabular.py`** — emits per-object `fields.toon` in TOON's
  tabular form (every row has the same set of columns; every cell is a
  primitive). Stringifies every cell to satisfy uniform-column-type;
  consumers decode per the conventions documented inline in
  `metadata.cell_value_decoding`. Automatically computes a
  `reference_path` cell for Lookup / MasterDetail fields pointing at the
  parent object's `schema.toon`.

---

## Per-script CLI reference

### `auto_generate_schema.py` ⭐ orchestrator

```bash
python3 salesforce/scripts/schemapy/auto_generate_schema.py
```

Zero inputs. Auto-detects the org from `.sf/config.json` and walks all 12
steps. Re-run any time the org changes — it diffs the local metadata
against the org and only retrieves what's new.

### `generate_sf_er_schema.py` — Step 7

```bash
python3 salesforce/scripts/schemapy/generate_sf_er_schema.py \
  [--objects-path PATH] \
  [--output-path PATH]
```

Auto-detected:
- `--objects-path` — `force-app/main/default/objects` or the first
  project entry in `sfdx-project.json`.
- `--output-path` — `<project-root>/config/salesforce-er-schema.toon`.

### `split_schema_by_object.py` — Step 8

```bash
python3 salesforce/scripts/schemapy/split_schema_by_object.py \
  [--input PATH] \
  [--output-dir PATH]
```

Auto-detected:
- `--input` — `<project-root>/config/salesforce-er-schema.toon`
- `--output-dir` — `<project-root>/config/schema`

### `enrich_schema_with_picklists.py` — Step 9

```bash
# All objects (auto-detect org)
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py

# Explicit org
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --org MyOrg

# Specific objects only
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --objects Account,Contact,HealthcareProviderNpi

# Dry run (preview changes; nothing written to disk)
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --dry-run

# Custom schema-objects directory
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --schema-dir custom/schema/objects
```

| Flag | Default | Notes |
|---|---|---|
| `--org` / `-o` | auto-detect | From `.sf/config.json` then `.sfdx/sfdx-config.json` |
| `--objects` | all under `config/schema/objects/` | Comma-separated |
| `--schema-dir` | `<project-root>/config/schema/objects` | |
| `--dry-run` | off | |

> Inactive picklist values are **never** emitted — this is intentional
> so AI agents and developers cannot accidentally suggest stale values.

**SF CLI command used per object:**
```bash
sf sobject describe --sobject <ObjectName> --target-org <org> --json
```

### `collect_usage_stats.py` — Step 10

```bash
# All queryable objects (auto-detect org)
python3 salesforce/scripts/schemapy/collect_usage_stats.py

# Explicit org
python3 salesforce/scripts/schemapy/collect_usage_stats.py --org MyOrg

# Specific objects only
python3 salesforce/scripts/schemapy/collect_usage_stats.py --objects Account,Case
```

| Flag | Default |
|---|---|
| `--org` / `-o` | auto-detect |
| `--objects` | all under `config/schema/objects/` |
| `--schema-dir` | `<project-root>/config/schema` |

Skipped automatically:
- `MultiselectPicklist` fields (cannot `GROUP BY` cleanly in SOQL)
- Objects with no read access (caught per-query)
- Objects with zero records

Results are merged into `picklists.toon` (switches to tabular
`{value,count}` form when usage data is available) and `schema.toon`
(`record_types[]` gains a `record_count` column).

> ~10× faster than per-call CLI usage. A 670-object org runs in
> 20-30 minutes.

### `detect_junctions.py` — Step 11

```bash
# Default (with record-count enrichment)
python3 salesforce/scripts/schemapy/detect_junctions.py

# Schema-only (skip SOQL — faster, lower-confidence classification)
python3 salesforce/scripts/schemapy/detect_junctions.py --no-counts

# Explicit org
python3 salesforce/scripts/schemapy/detect_junctions.py --org MyOrg
```

| Flag | Default |
|---|---|
| `--input` | `<project-root>/config/salesforce-er-schema.toon` |
| `--output` | `<project-root>/config/schema/_junctions.toon` |
| `--org` / `-o` | auto-detect |
| `--no-counts` | off (counts on) |

Confidence tiers:
- `high` — junction record count ≥ 50% of the larger parent's count
- `medium` — junction populated but sparser than parents
- `low` — junction object has zero records in this org
- `schema_only` — `--no-counts` was used, or count fetch failed

Detection is purely structural — no IBX / Health-Cloud / Vlocity-specific
name patterns. Works in any Salesforce org.

### `generate_er.py` — Step 12

```bash
python3 salesforce/scripts/schemapy/generate_er.py
```

| Flag | Default |
|---|---|
| `--input` | `<project-root>/config/schema/_junctions.toon` |
| `--output` | `<project-root>/ER.md` |

Pure offline — no SOQL, no `sf` calls. Emits per-confidence-tier markdown
tables plus Mermaid `erDiagram` blocks (skipped for tiers with > 80
junctions, where the diagram becomes unreadable).

---

## Common workflows

### Full regeneration (recommended)

```bash
python3 salesforce/scripts/schemapy/auto_generate_schema.py
```

### Pick up new picklist values for one object

```bash
# Preview
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py \
  --objects HealthcareProviderNpi --dry-run

# Apply
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py \
  --objects HealthcareProviderNpi

# Review + commit
git diff config/schema/objects/HealthcareProviderNpi/
git add config/schema/objects/HealthcareProviderNpi/
git commit -m "Update HealthcareProviderNpi picklist values"
```

### Refresh just the usage counts (skip describe)

```bash
python3 salesforce/scripts/schemapy/collect_usage_stats.py
python3 salesforce/scripts/schemapy/detect_junctions.py
python3 salesforce/scripts/schemapy/generate_er.py
```

This is the right combination when picklist *definitions* haven't
changed but record volumes have moved enough that the high/medium/low
classification might drift.

### Schema-only run (no SOQL — works offline against retrieved metadata)

```bash
python3 salesforce/scripts/schemapy/generate_sf_er_schema.py
python3 salesforce/scripts/schemapy/split_schema_by_object.py
python3 salesforce/scripts/schemapy/detect_junctions.py --no-counts
python3 salesforce/scripts/schemapy/generate_er.py
```

Useful when you have local metadata but no org connection (e.g. CI
without a sandbox).

---

## Output shape

Each object gets its own folder under `config/schema/objects/`:

```
config/schema/objects/HealthcareProviderNpi/
├── schema.toon       ← object header, fields[] (tabular), record_types[], validation_rules[]
├── picklists.toon    ← one block per Picklist field; tabular {value,count} when Step 10 ran
└── formulas.toon     ← one block per Formula field, including the formula expression
```

`fields.toon` cell decoding (documented inline as
`metadata.cell_value_decoding`):

| Cell | Decode as |
|---|---|
| empty string | not present / null |
| `true` / `false` | bool |
| decimal digits | int |
| `A\|B\|C` | list of strings (polymorphic `reference_to` / `reference_path`) |
| anything else | string |

---

## Requirements

- Salesforce CLI (`sf`) authenticated to at least one org
- Python 3.9+
- Python deps (in [`requirements.txt`](requirements.txt)):
  - [`toon-format`](https://pypi.org/project/toon-format/) ≥ 0.9.0b1 — currently in beta, `--pre` required if installing manually
  - [`certifi`](https://pypi.org/project/certifi/) ≥ 2024.0.0 — trust store for the direct HTTPS calls in `collect_usage_stats.py` (stdlib's default trust store is empty on python.org macOS builds and many venvs)

```bash
pip install -r salesforce/scripts/schemapy/requirements.txt
```

---

## Troubleshooting

**`sf command not found`** — install Salesforce CLI (`brew install sf` on macOS, or [download](https://developer.salesforce.com/tools/salesforcecli)).

**`This org hasn't been authenticated`** — `sf org login web --alias MyOrg` then `sf config set target-org=MyOrg`.

**`toon-format module not found`** — `pip install -r salesforce/scripts/schemapy/requirements.txt` (or `pip install --pre toon-format` directly).

**`certifi` SSL errors in Step 10** — `pip install certifi`. The stdlib trust store is empty on python.org macOS builds; `_sf_session.py` prefers `certifi`'s bundled CA list.

**Step 10 takes >30 minutes** — that's expected for a 600+ object org. It batches up to 25 SOQL queries per HTTP call via `composite/batch`, but a full picklist-and-RecordType census still touches thousands of queries. Use `--objects` to scope to a smaller set.

**`_junctions.toon` shows everything as `schema_only`** — Step 10 was skipped or failed. Re-run `collect_usage_stats.py` then `detect_junctions.py`. To intentionally skip count enrichment, pass `--no-counts` to `detect_junctions.py`.

**`Permission denied: ./script.py`** — `chmod +x salesforce/scripts/schemapy/*.py`. Or always invoke with `python3 path/to/script.py`.

---

## See Also

- [`initagentrulespy/README.md`](../initagentrulespy/README.md) — bootstrap kit for AI-agent rules / skills / docs / manifests
- [PMD Rulesets](../../pmd/README.md) — static code analysis rulesets for Apex
- [`docs/SALESFORCE_TOOLS.md`](../../../docs/SALESFORCE_TOOLS.md) — repo-wide overview of all Salesforce tooling
- [TOON spec](https://github.com/toon-format/spec/blob/main/SPEC.md) — Token-Oriented Object Notation v3.0
- [Salesforce CLI Reference](https://developer.salesforce.com/docs/atlas.en-us.sfdx_cli_reference.meta/sfdx_cli_reference/) — official `sf` docs
