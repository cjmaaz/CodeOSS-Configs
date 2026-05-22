# Salesforce Scripts

Two self-contained Python kits live under this directory. Each ships its own
detailed README — start there once you know which one you want.

| Kit | Purpose | README |
|---|---|---|
| [`schemapy/`](schemapy/) | 12-step pipeline that retrieves Salesforce metadata, generates a TOON-encoded ER schema (`config/salesforce-er-schema.toon`), splits it into per-object folders under `config/schema/`, enriches every field with picklist values / formulas / lookups, then layers in live record-count usage stats, junction detection, and an `ER.md` diagram. | [`schemapy/README.md`](schemapy/README.md) |
| [`initagentrulespy/`](initagentrulespy/) | Bootstrap kit that materializes a curated AI-agent rule, skill, doc, manifest, and config set (~44 files) into any new Salesforce repo. Auto-detects `target-org`, Java home, and PMD binary path and substitutes those into the generated files so the rules work out of the box on macOS, Linux, and Windows. | [`initagentrulespy/README.md`](initagentrulespy/README.md) |

## Quick Start

### Generate a TOON schema for the current org

```bash
# From the project root (auto-detects org from .sf/config.json)
pip install -r salesforce/scripts/schemapy/requirements.txt
python3 salesforce/scripts/schemapy/auto_generate_schema.py
```

Outputs land under `config/schema/` (per-object folders), plus
`config/salesforce-er-schema.toon` and an `ER.md` at the project root.

### Bootstrap AI-agent rules into a new Salesforce repo

```bash
cd /path/to/new-sf-repo
python3 /path/to/initagentrulespy/init.py
```

Drops `.cursor/rules/`, `.claude/skills/`, `docs/`, `changes/_templates/`,
`.vscode/settings.json`, `.mcp.json`, `.cursor/mcp.json`,
`manifest/fullpackage/`, and `config/pmd-ruleset.xml` into the current
directory.

## Requirements

- Salesforce CLI (`sf`) installed and authenticated
- Python 3.9+
- Per-kit Python deps:
  - `schemapy`: `pip install -r salesforce/scripts/schemapy/requirements.txt`
  - `initagentrulespy`: stdlib only — no external dependencies

## See Also

- [PMD Rulesets](../pmd/README.md) — static code analysis rulesets for Apex
- [`docs/SALESFORCE_TOOLS.md`](../../docs/SALESFORCE_TOOLS.md) — repo-wide overview of all Salesforce tooling in this repo
