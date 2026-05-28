# Salesforce Development Tools

> Automated Salesforce schema generation, enrichment scripts, and MCP wrapper for AI coding assistants.

[← Back to Main README](../README.md)

## Table of Contents

- [Overview](#overview)
- [Python Schema Scripts (`schemapy`)](#python-schema-scripts-schemapy)
- [AI-Agent Rules Bootstrap (`initagentrulespy`)](#ai-agent-rules-bootstrap-initagentrulespy)
- [PMD Rulesets for Apex](#pmd-rulesets-for-apex)
- [MCP Wrapper for Salesforce](#mcp-wrapper-for-salesforce)
- [IDE Integration](#ide-integration)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Documentation](#detailed-documentation)

---

## Overview

This repository contains powerful automation tools for Salesforce development:

### 1. Python Schema Scripts (`schemapy`)

12-step pipeline that retrieves your org's metadata, generates a [TOON](https://github.com/toon-format/spec/blob/main/SPEC.md)-encoded ER schema, shards it into per-object folders, enriches every field with active picklist values, layers in live record-count usage stats, structurally detects junction objects, and renders a Mermaid `ER.md` diagram at the project root.

### 2. AI-Agent Rules Bootstrap (`initagentrulespy`)

Self-contained Python kit that materializes a curated AI-agent rule, skill, doc, manifest, and config set (~44 files) into any new Salesforce repo. Auto-detects `target-org`, Java home, and PMD binary path and substitutes them in.

### 3. PMD Rulesets

Pre-configured static code analysis rulesets for Apex code quality, security, and best practices enforcement.

### 4. MCP Wrapper

Node.js wrapper for integrating Salesforce CLI with AI coding assistants (Cursor, Continue, etc.) via Model Context Protocol.

### 5. IDE Integration

Settings and configurations optimized for Salesforce development in Code OSS-based editors.

---

## Python Schema Scripts (`schemapy`)

### Location

[`salesforce/scripts/schemapy/`](../salesforce/scripts/schemapy/)

> **Encoding change.** Earlier versions of this pipeline emitted YAML. The output is now [TOON](https://github.com/toon-format/spec/blob/main/SPEC.md) (Token-Oriented Object Notation, v3.0). TOON is ~2-3× more token-efficient than YAML, which matters when feeding the schema into AI agents. All consumers (rules, skills, agent prompts) load `.toon` files. The single-`.yaml`-file fallback was removed.

### The 12-step pipeline

`auto_generate_schema.py` is the orchestrator — it walks all 12 steps end-to-end. Steps 1–9 are mandatory; steps 10–12 add usage-aware classification and the human-readable ER diagram and continue past failures (a warning is printed, but the per-object schema files from steps 1–9 are still usable on their own).

| #     | Owned by                          | What it does                                                                                                                                                                          |
| ----- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1–6   | `auto_generate_schema.py`         | Detect default org, locate the `objects/` directory, query all sObjects, filter system objects (History/Share/Feed/ChangeEvent), diff against local metadata, retrieve what's missing |
| 7     | `generate_sf_er_schema.py`        | Parse every `*.object-meta.xml` and emit `config/salesforce-er-schema.toon` (combined intermediate)                                                                                   |
| 8     | `split_schema_by_object.py`       | Shard the combined intermediate into per-object folders + a master index, a flat search index, and category groupings                                                                 |
| 9     | `enrich_schema_with_picklists.py` | `sf sobject describe` per object — merge in picklist values (ACTIVE only), default values, formulas, lookups, field dependencies, length/precision/scale, required/unique/externalId  |
| 10    | `collect_usage_stats.py`          | Composite REST `composite/batch` queries (25 SOQL queries per HTTP call) to pull per-picklist-value record counts + per-RecordType counts                                             |
| 11    | `detect_junctions.py`             | Structurally classify objects as junctions (2+ real-business lookup parents + at least one promotion signal). Confidence tier (`high`/`medium`/`low`/`schema_only`) uses Step 10 counts |
| 12    | `generate_er.py`                  | Render `ER.md` from `_junctions.toon` — markdown tables + per-tier Mermaid `erDiagram` blocks                                                                                          |

### Helper modules

Three small private modules sit next to the pipeline scripts:

- **`_toon_io.py`** — TOON dump/load + `find_project_root()` (walks up from the script's own location, so the pipeline is cwd-independent).
- **`_sf_session.py`** — fetches access token / instance URL / API version once via `sf org display --verbose --json`, then issues SOQL queries via `composite/batch` (25 queries per HTTP call). Uses `certifi`'s CA bundle when available — stdlib's default trust store is empty on many Python installs.
- **`_fields_tabular.py`** — emits per-object `fields.toon` in TOON's tabular form. Auto-computes a `reference_path` cell for Lookup / MasterDetail fields.

### Available Scripts

#### 1. `auto_generate_schema.py` ⭐ **Main Orchestrator**

```bash
# Zero inputs required — auto-detects org from .sf/config.json
python3 salesforce/scripts/schemapy/auto_generate_schema.py
```

**Output** (all under `config/`):

- `salesforce-er-schema.toon` — combined intermediate (Step 7)
- `schema/_index.toon` — master object index (Step 8)
- `schema/_search_index.toon` — flat field search index (Step 8)
- `schema/categories/*.toon` — objects grouped by category (Step 8)
- `schema/objects/<Object>/{schema,picklists,formulas}.toon` — per-object enriched data (Steps 8 + 9)
- `schema/_junctions.toon` — detected junction objects + parents (Step 11)
- `../ER.md` (project root) — Mermaid ER diagram of every detected junction (Step 12)

#### 2. `enrich_schema_with_picklists.py` — Step 9

Enriches per-object TOON files with `sf sobject describe` data.

**What it adds**:

- Picklist values (**ACTIVE ONLY** — inactive values excluded by design)
- Formula definitions
- Default values
- Field constraints (required, unique, externalId)
- Field length, precision, scale
- Lookup relationships (with auto-computed `reference_path`)
- Field dependencies (controlling/dependent picklists)

```bash
# All objects (auto-detect org)
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py

# Specific objects
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --objects Account,Contact

# Dry run (preview changes; nothing written to disk)
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --dry-run

# Explicit org
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --org MyOrgAlias
```

#### 3. `collect_usage_stats.py` — Step 10

For every queryable object, runs `composite/batch` aggregate queries against the org to gather per-picklist-value record counts + per-RecordType counts. Merges them back into `picklists.toon` (switches to tabular `{value,count}` form when usage data is available) and `schema.toon` (`record_types[]` gains a `record_count` column).

```bash
# All queryable objects
python3 salesforce/scripts/schemapy/collect_usage_stats.py

# Specific objects only
python3 salesforce/scripts/schemapy/collect_usage_stats.py --objects Account,Case
```

Skips `MultiselectPicklist` fields (cannot `GROUP BY` cleanly in SOQL), objects with no read access, and objects with zero records. A 670-object org runs in ~20-30 minutes (~10× faster than per-call CLI usage).

#### 4. `detect_junctions.py` — Step 11

Structurally identifies junction objects from the combined schema + record-count enrichment. Detection is purely structural — no IBX/Health-Cloud/Vlocity-specific name patterns — so it works in any org.

```bash
# Default (with org counts)
python3 salesforce/scripts/schemapy/detect_junctions.py

# Schema-only (faster, lower-confidence classification)
python3 salesforce/scripts/schemapy/detect_junctions.py --no-counts
```

Confidence tiers:

- `high` — junction record count ≥ 50% of the larger parent's count
- `medium` — junction populated but sparser than parents
- `low` — junction object has zero records in this org
- `schema_only` — `--no-counts` was used, or count fetch failed

#### 5. `generate_er.py` — Step 12

Pure offline (no SOQL, no `sf` calls). Reads `_junctions.toon` and emits a single `ER.md` at the project root with per-confidence-tier markdown tables and Mermaid `erDiagram` blocks. Mermaid rendering is skipped for tiers with > 80 junctions (the diagram becomes unreadable).

```bash
python3 salesforce/scripts/schemapy/generate_er.py
```

#### 6. `generate_sf_er_schema.py` — Step 7

Parses Salesforce metadata XML files and emits the combined `config/salesforce-er-schema.toon` intermediate. Typically invoked by the orchestrator; run manually if you want only the intermediate without sharding.

#### 7. `split_schema_by_object.py` — Step 8

Shards the combined intermediate into per-object folders + master index + search index + category groupings under `config/schema/`. Typically invoked by the orchestrator.

---

### Common Workflows

#### Workflow 1: Generate Complete Schema (RECOMMENDED) ⭐

```bash
python3 salesforce/scripts/schemapy/auto_generate_schema.py
```

Runs all 12 steps end-to-end. Result: complete, enriched, count-aware schema in `config/schema/` plus `ER.md` at the project root.

#### Workflow 2: Update Specific Objects Only

```bash
# Preview changes
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --objects HealthcareProviderNpi --dry-run

# Apply
python3 salesforce/scripts/schemapy/enrich_schema_with_picklists.py --objects HealthcareProviderNpi,Account

# Review + commit
git diff config/schema/objects/HealthcareProviderNpi/
git add config/schema/objects/HealthcareProviderNpi/
git commit -m "Update HealthcareProviderNpi picklist values"
```

#### Workflow 3: Refresh just the usage counts (skip describe)

```bash
python3 salesforce/scripts/schemapy/collect_usage_stats.py
python3 salesforce/scripts/schemapy/detect_junctions.py
python3 salesforce/scripts/schemapy/generate_er.py
```

Right combination when picklist definitions haven't changed but record volumes have moved enough that high/medium/low classification might drift.

#### Workflow 4: Schema-only run (no SOQL — works offline)

```bash
python3 salesforce/scripts/schemapy/generate_sf_er_schema.py
python3 salesforce/scripts/schemapy/split_schema_by_object.py
python3 salesforce/scripts/schemapy/detect_junctions.py --no-counts
python3 salesforce/scripts/schemapy/generate_er.py
```

Useful when you have local metadata but no org connection (e.g. CI without a sandbox).

---

### Output Format

Each object lands in its own folder:

```
config/schema/objects/HealthcareProviderNpi/
├── schema.toon       ← object header, fields[] (tabular), record_types[], validation_rules[]
├── picklists.toon    ← one block per Picklist field; tabular {value,count} when Step 10 ran
└── formulas.toon     ← one block per Formula field, including the formula expression
```

`fields.toon` is TOON-tabular (every row has the same set of columns; every cell is a primitive). Cells are stringified for uniform column types — consumers decode per the conventions documented inline as `metadata.cell_value_decoding`:

| Cell             | Decode as                                                    |
| ---------------- | ------------------------------------------------------------ |
| empty string     | not present / null                                           |
| `true` / `false` | bool                                                         |
| decimal digits   | int                                                          |
| `A\|B\|C`        | list of strings (polymorphic `reference_to` / `reference_path`) |
| anything else    | string                                                       |

---

### Requirements

- **Salesforce CLI**: `sf` command installed and authenticated
- **Python**: 3.9+
- **Python deps** (in [`requirements.txt`](../salesforce/scripts/schemapy/requirements.txt)):
  - [`toon-format`](https://pypi.org/project/toon-format/) ≥ 0.9.0b1 (currently in beta — `--pre` required if installing manually)
  - [`certifi`](https://pypi.org/project/certifi/) ≥ 2024.0.0 (CA bundle for the direct HTTPS calls in `collect_usage_stats.py`)

**Installation**:

```bash
# Install Salesforce CLI
brew install sf  # macOS
# OR download from: https://developer.salesforce.com/tools/sfdxcli

# Install Python dependencies
pip install -r salesforce/scripts/schemapy/requirements.txt

# Authenticate to org
sf org login web --alias MyOrg
sf config set target-org=MyOrg
```

---

### SF CLI Commands Reference

Comprehensive reference for Salesforce metadata extraction using SF CLI.

#### Get Field Metadata (Picklists, Formulas, Types)

```bash
# Method 1: Describe command (fastest, most complete) — used by Step 9
sf sobject describe --sobject Account --target-org MyOrg --json

# Method 2: Query FieldDefinition
sf data query --query "SELECT QualifiedApiName, DataType, Label FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = 'Account'" --target-org MyOrg --json
```

**Output includes**:

- Field names, types, labels
- **Picklist values (active and inactive)** — the pipeline filters to ACTIVE only on the way in
- Formula definitions
- Default values
- Length, precision, scale
- Required, unique, externalId flags
- Lookup relationships (referenceTo)

#### Get Validation Rules

```bash
sf data query --query "SELECT ValidationName, Active, ErrorConditionFormula, ErrorMessage FROM ValidationRule WHERE EntityDefinition.QualifiedApiName = 'Account'" --target-org MyOrg --json
```

#### Get Record Types

```bash
sf data query --query "SELECT DeveloperName, Name, IsActive, Description FROM RecordType WHERE SobjectType = 'Account'" --target-org MyOrg --json
```

For the complete pipeline reference + per-script CLI flags, see [`salesforce/scripts/schemapy/README.md`](../salesforce/scripts/schemapy/README.md).

---

## AI-Agent Rules Bootstrap (`initagentrulespy`)

### Location

[`salesforce/scripts/initagentrulespy/`](../salesforce/scripts/initagentrulespy/)

### What it does

Self-contained Python kit (no third-party dependencies) that materializes a curated AI-agent rule / skill / doc / manifest / config set into any new Salesforce repo. The script auto-detects the target workspace's `target-org` alias, Java home, and PMD binary path, and substitutes those values into the generated files so they work out of the box on macOS, Linux, and Windows.

### TL;DR for end users

```bash
# 1. Copy the entire scripts/initagentrulespy/ folder to your machine.
#    (Fully self-contained — no need to clone the source repo.)

# 2. From inside your new Salesforce repo, run:
python3 /path/to/initagentrulespy/init.py
# Writes ~44 files into the current directory and prints a summary.

# 3. Open .cursor/rules/sf-cli-commands.mdc — the canonical entry point.
```

### What gets generated

| Path                           | Count                                | What it is                                                                                                                                                                                                                                                            |
| ------------------------------ | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.cursor/rules/`               | 10                                   | Cursor rules (always-applied + on-demand). Includes a stub `org-data-model.mdc` you fill in for your own org. `changes-doc-mandatory.mdc` enforces a **three-touchpoint workflow** (intake → pre-coding analysis → wrap-up); the pre-coding analysis step maps cascading sObject / trigger / flow / validation-rule impact BEFORE any code edit.                                                                                                                                  |
| `.claude/skills/`              | 5 skills + `.claude/settings.json`   | Claude Code skills mirroring the rules. Excludes machine-local `settings.local.json`. `changes-documentation/SKILL.md` mirrors the rule's three touchpoints as Step 0 / Step 0.5 / Steps 1-7.                                                                                                                                                                                                                                                                                  |
| `docs/`                        | 9                                    | Reference docs (OmniStudio guides, sf-retrieve playbook, schema-quickref). `docs/sf-org-mirror-retrieve.md` is a plan-first runbook: Phase 0.0 spawns an explicit `TodoWrite` plan covering all 23 retrieve phases + 3 audit sub-phases + 2 git commits BEFORE any `sf` command runs, so a mid-run failure is resumable. Logs rotate on every run (`.retrieve-logs/current/` for the active run, `.retrieve-logs/archive/<TS>/` for prior runs). Includes a stub `docs/omnistudio/org-conventions.md`. |
| `changes/_templates/`          | 4                                    | Bug-fix / story / refactor / retrieve-audit doc templates referenced by `changes-doc-mandatory`. The bug-fix / story / refactor templates carry inline `FILL UP FRONT` callouts on the architecture / design-decisions / before-after sections — those sections are spawned with the doc during pre-coding analysis (rule Step E4), not at wrap-up. The retrieve template is filled per Phase 3.4.1 (per-type todos, magnitude-ordered) + Phase 3.4.2 (cross-type synthesis with `§4.11`) of the runbook. |
| `.vscode/`                     | 1                                    | `settings.json` only (with detected Java home). `extensions.json` and `launch.json` intentionally NOT generated — leave those to per-project preference.                                                                                                               |
| `.mcp.json` + `.cursor/mcp.json` | 2 (same content)                   | MCP server config. Same content written to both paths so Claude Code (reads `.mcp.json`) and Cursor (reads `.cursor/mcp.json`) share the same server set. Filesystem-MCP path is auto-set to your repo's absolute path.                                                |
| `manifest/fullpackage/`        | 11                                   | Pre-sharded full-org retrieve manifests (each shard fits under the 10k-component metadata-API limit).                                                                                                                                                                  |
| `config/pmd-ruleset.xml`       | 1                                    | Sensible default Apex PMD ruleset. Tune thresholds for your project.                                                                                                                                                                                                   |

### CLI reference

```bash
python3 init.py [target_dir] [options]

Positional:
  target_dir              Where to write (default: current working directory).

Options:
  --alias NAME            Override target-org detection.
  --org-name NAME         Human-readable project / org name. Default: 'CURR ORG'.
  --java-home PATH        Override Java JDK home detection.
  --pmd-path PATH         Override PMD binary path detection.
  --force                 Overwrite existing files (default: skip).
  --dry-run               Print what would be written; do not touch the filesystem.
  --no-prompt             Never prompt; fall back to sentinel placeholders.
```

### Placeholder substitution

`templates/` ships with five `{{...}}` placeholder tokens. `init.py` replaces each of them with a runtime-detected (or CLI-supplied) value:

| Placeholder         | Becomes                            | Detection chain                                                                                                          |
| ------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `{{ORG_ALIAS}}`     | Your `target-org` alias            | `.sf/config.json` → `.sfdx/sfdx-config.json` → `--alias` flag → interactive prompt → sentinel `<TARGET_ORG_ALIAS>`        |
| `{{ORG_NAME}}`      | Human-readable project / org name  | `--org-name` CLI flag only (default `CURR ORG`)                                                                          |
| `{{JAVA_HOME}}`     | Detected JDK home                  | `/usr/libexec/java_home -v 21\|17\|11` (macOS), `$JAVA_HOME`, `/usr/lib/jvm/java-*` glob (Linux), `where java` (Windows) |
| `{{PMD_PATH}}`      | Absolute pmd binary path           | `shutil.which("pmd")`, then OS-specific install paths and `pmd-bin-*` glob, then `$PMD_HOME`                              |
| `{{WORKSPACE_PATH}}`| Target dir absolute path           | `os.path.abspath(target_dir)`                                                                                            |

If detection falls back to a sentinel, the script prints a warning at the end of the run with instructions on how to fix it.

> **Why placeholders?** The kit is meant to be shared. Carrying real values like a specific sf alias, an absolute workspace path, or the source org's brand name through the templates would leak personal/org info into anything a colleague clones or zips.

### Source-repo maintenance

The kit also ships `_sync.py` — a maintainer-only helper that walks the source repo's actual rules / skills / docs / manifests / configs and copies them into `templates/`, running every file through a tokenization step that replaces source-repo-specific literals with the `{{...}}` placeholders.

```bash
python3 salesforce/scripts/initagentrulespy/_sync.py            # write changes
python3 salesforce/scripts/initagentrulespy/_sync.py --check    # CI-friendly: exit 1 if drift
python3 salesforce/scripts/initagentrulespy/_sync.py --verbose  # log every file (incl. unchanged)
```

For full maintainer details (`SOURCES` table, `_tokenize` rules, per-file transforms), see [`salesforce/scripts/initagentrulespy/README.md`](../salesforce/scripts/initagentrulespy/README.md).

---

## PMD Rulesets for Apex

### Location

[`salesforce/pmd/`](../salesforce/pmd/)

### What is PMD?

**PMD** is a static source code analyzer that finds common programming flaws like unused variables, empty catch blocks, unnecessary object creation, and more. For Salesforce development, PMD helps enforce:

- **Code Quality**: Detect complexity, bad practices, and maintainability issues
- **Security**: Identify CRUD/FLS violations, SOQL injection risks, and weak cryptography
- **Performance**: Find inefficient loops, unnecessary debug statements, and governor limit risks
- **Best Practices**: Enforce proper test assertions, naming conventions, and documentation

### Available Rulesets

This repository includes two PMD rulesets optimized for different use cases:

#### 1. `main-ruleset.xml` - **Balanced Ruleset** (Recommended for Most Projects)

**Purpose**: Comprehensive ruleset focusing on critical issues without being overly strict.

**Best For**:

- Production codebases
- Teams prioritizing critical issues
- Projects with existing code that may not pass strict standards
- Continuous integration pipelines

**Categories Covered**:

- ✅ **Best Practices** (4 rules): Assertions, test coverage, finalizers, logging
- ✅ **Code Style** (3 rules): Braces for control structures
- ✅ **Design** (4 rules): Complexity metrics, nesting depth
- ✅ **Error Prone** (5 rules): Hardcoded IDs, empty blocks, CSRF, trigger maps
- ✅ **Performance** (3 rules): Debug statements, operations in loops
- ✅ **Security** (4 rules): Bad crypto, CRUD violations, sharing, SOQL injection

**Total**: 23 rules across 6 categories

---

#### 2. `standard-ruleset.xml` - **Strict Ruleset** (For High-Quality Standards)

**Purpose**: Comprehensive ruleset enforcing strict coding standards and documentation.

**Best For**:

- New greenfield projects
- Teams with strict quality requirements
- Code requiring extensive documentation
- Enterprise-grade applications

**Additional Rules** (compared to main-ruleset):

- ✅ **AvoidGlobalModifier**: Prevents global keyword misuse
- ✅ **ClassNamingConventions**: Enforces proper class naming
- ✅ **MethodNamingConventions**: Enforces proper method naming
- ✅ **AvoidBooleanMethodParameters**: Discourages boolean parameters for clarity
- ✅ **ApexDoc**: Requires ApexDoc comments for classes and methods

**Total**: 28 rules across 7 categories (includes Documentation)

---

### Rule Categories Breakdown

#### Best Practices

| Rule                                 | Description                                       | Both Rulesets |
| ------------------------------------ | ------------------------------------------------- | ------------- |
| `ApexAssertionsShouldIncludeMessage` | Test assertions must include descriptive messages | ✅            |
| `ApexUnitTestClassShouldHaveAsserts` | Test classes must contain assertions              | ✅            |
| `AvoidGlobalModifier`                | Restrict use of global keyword                    | Standard only |
| `QueueableWithoutFinalizer`          | Detect missing finalizers in Queueable            | ✅            |
| `DebugsShouldUseLoggingLevel`        | Debug statements must specify log level           | ✅            |

#### Code Style

| Rule                       | Description                       | Both Rulesets |
| -------------------------- | --------------------------------- | ------------- |
| `IfElseStmtsMustUseBraces` | Enforce braces for if/else blocks | ✅            |
| `ForLoopsMustUseBraces`    | Enforce braces for for loops      | ✅            |
| `WhileLoopsMustUseBraces`  | Enforce braces for while loops    | ✅            |
| `ClassNamingConventions`   | Enforce PascalCase for classes    | Standard only |
| `MethodNamingConventions`  | Enforce camelCase for methods     | Standard only |

#### Design

| Rule                           | Description                         | Both Rulesets |
| ------------------------------ | ----------------------------------- | ------------- |
| `AvoidBooleanMethodParameters` | Discourage boolean parameters       | Standard only |
| `AvoidDeeplyNestedIfStmts`     | Limit nesting depth of conditionals | ✅            |
| `CyclomaticComplexity`         | Measure method complexity           | ✅            |
| `NcssMethodCount`              | Limit lines of code per method      | ✅            |
| `CognitiveComplexity`          | Measure code readability complexity | ✅            |

#### Documentation

| Rule      | Description                             | Both Rulesets |
| --------- | --------------------------------------- | ------------- |
| `ApexDoc` | Require ApexDoc for classes and methods | Standard only |

#### Error Prone

| Rule                          | Description                           | Both Rulesets |
| ----------------------------- | ------------------------------------- | ------------- |
| `AvoidHardcodingId`           | Prevent hardcoded Salesforce IDs      | ✅            |
| `EmptyCatchBlock`             | Detect empty catch blocks             | ✅            |
| `ApexCSRF`                    | Detect CSRF vulnerabilities           | ✅            |
| `AvoidDirectAccessTriggerMap` | Prevent direct Trigger.new/old access | ✅            |
| `EmptyIfStmt`                 | Detect empty if statements            | ✅            |

#### Performance

| Rule                          | Description                                | Both Rulesets |
| ----------------------------- | ------------------------------------------ | ------------- |
| `AvoidDebugStatements`        | Detect debug statements in production code | ✅            |
| `OperationWithHighCostInLoop` | Prevent expensive operations in loops      | ✅            |
| `OperationWithLimitsInLoop`   | Prevent governor limit violations in loops | ✅            |

#### Security

| Rule                    | Description                           | Both Rulesets |
| ----------------------- | ------------------------------------- | ------------- |
| `ApexBadCrypto`         | Detect weak cryptographic algorithms  | ✅            |
| `ApexCRUDViolation`     | Detect missing CRUD/FLS checks        | ✅            |
| `ApexSharingViolations` | Detect sharing rule violations        | ✅            |
| `ApexSOQLInjection`     | Detect SOQL injection vulnerabilities | ✅            |

---

### How to Use PMD Rulesets

#### Option 1: With Salesforce Code Analyzer (Recommended)

The **Salesforce Code Analyzer** extension integrates PMD directly into your IDE.

**Setup**:

1. **Install Extension**:

   - Open VS Code/Cursor
   - Install "Salesforce Code Analyzer" extension

2. **Configure Custom Ruleset**:
   - Open settings (JSON): `Cmd/Ctrl + Shift + P` → "Preferences: Open Settings (JSON)"
   - Add custom ruleset path:

```json
{
  "salesforce-code-analyzer.pmd.rulesets": ["/absolute/path/to/salesforce/pmd/main-ruleset.xml"],
  "salesforce-code-analyzer.engines": ["pmd"]
}
```

3. **Run Analysis**:
   - Right-click on a file/folder
   - Select "SFDX: Run Code Analyzer on Selected File(s)"
   - Or use Command Palette: `Salesforce: Run Code Analyzer`

**IDE Settings** (Already configured in this repo):

```json
{
  "salesforce-code-analyzer.pmd.enabled": true,
  "salesforce-code-analyzer.pmd.rulesets": ["<path-to-ruleset>"],
  "salesforce-code-analyzer.scanner.engines": ["pmd"],
  "salesforce-code-analyzer.scanner.categories": ["Design", "Performance", "Security"]
}
```

---

#### Option 2: Command Line (CI/CD Integration)

**Prerequisites**:

```bash
# Install PMD (requires Java 11+)
brew install pmd  # macOS
# OR download from: https://github.com/pmd/pmd/releases

# Verify installation
pmd --version
```

**Run Analysis**:

```bash
# Analyze single file
pmd check --dir force-app/main/default/classes/MyClass.cls \
  --rulesets salesforce/pmd/main-ruleset.xml \
  --format text

# Analyze entire project
pmd check --dir force-app/main/default/classes \
  --rulesets salesforce/pmd/standard-ruleset.xml \
  --format text

# Generate HTML report
pmd check --dir force-app/main/default/classes \
  --rulesets salesforce/pmd/main-ruleset.xml \
  --format html \
  --report-file pmd-report.html

# JSON output (for CI/CD parsing)
pmd check --dir force-app/main/default/classes \
  --rulesets salesforce/pmd/main-ruleset.xml \
  --format json \
  --report-file pmd-report.json
```

**Exit Codes**:

- `0`: No violations
- `4`: Violations found
- `1`: Error occurred

---

#### Option 3: Salesforce CLI Scanner

The Salesforce CLI includes a code scanner that supports PMD.

**Installation**:

```bash
# Install Salesforce CLI (if not already installed)
brew install sf  # macOS

# Install Code Analyzer plugin
sf plugins install @salesforce/sfdx-scanner
```

**Usage**:

```bash
# Run with custom ruleset
sf scanner run --target "force-app/**/*.cls" \
  --pmdconfig salesforce/pmd/main-ruleset.xml \
  --format table

# Generate detailed report
sf scanner run --target "force-app/**/*.cls" \
  --pmdconfig salesforce/pmd/standard-ruleset.xml \
  --format csv \
  --outfile violations.csv

# Set severity threshold (fail on priority 1-3 violations)
sf scanner run --target "force-app/**/*.cls" \
  --pmdconfig salesforce/pmd/main-ruleset.xml \
  --severity-threshold 3
```

---

### CI/CD Integration

#### GitHub Actions Example

```yaml
name: PMD Code Analysis

on: [push, pull_request]

jobs:
  pmd-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Java
        uses: actions/setup-java@v3
        with:
          distribution: 'temurin'
          java-version: '11'

      - name: Install PMD
        run: |
          wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.0.0/pmd-dist-7.0.0-bin.zip
          unzip pmd-dist-7.0.0-bin.zip

      - name: Run PMD Analysis
        run: |
          pmd-bin-7.0.0/bin/pmd check \
            --dir force-app/main/default/classes \
            --rulesets salesforce/pmd/main-ruleset.xml \
            --format text \
            --fail-on-violation true
```

#### GitLab CI Example

```yaml
pmd-scan:
  stage: test
  image: openjdk:11-jre-slim
  before_script:
    - wget https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.0.0/pmd-dist-7.0.0-bin.zip
    - unzip pmd-dist-7.0.0-bin.zip
  script:
    - pmd-bin-7.0.0/bin/pmd check --dir force-app/main/default/classes --rulesets salesforce/pmd/main-ruleset.xml --format text --fail-on-violation true
```

---

### Customizing Rulesets

Both rulesets can be customized to fit your project needs.

#### Add Rule Exceptions

Exclude specific rules from analysis:

```xml
<!-- In your ruleset file -->
<rule ref="category/apex/design.xml/CyclomaticComplexity">
  <properties>
    <property name="reportLevel" value="15" />  <!-- Default is 10 -->
  </properties>
</rule>
```

#### Exclude Files/Directories

Create a `.pmd-exclude` file:

```
force-app/main/default/classes/legacy/**
force-app/main/default/classes/ThirdPartyLib.cls
```

#### Suppress Warnings in Code

Use PMD suppression comments:

```apex
public class MyClass {
    // NOPMD - Legacy code, will be refactored in Q2
    @SuppressWarnings('PMD.AvoidGlobalModifier')
    global class GlobalUtil {
        // ...
    }
}
```

---

### Choosing the Right Ruleset

| Scenario                                     | Recommended Ruleset    |
| -------------------------------------------- | ---------------------- |
| Production codebase with existing violations | `main-ruleset.xml`     |
| New greenfield project                       | `standard-ruleset.xml` |
| CI/CD pipeline (fail on violations)          | `main-ruleset.xml`     |
| Enterprise-grade application                 | `standard-ruleset.xml` |
| Quick code review                            | `main-ruleset.xml`     |
| Team learning best practices                 | `standard-ruleset.xml` |

---

### PMD Version Compatibility

Both rulesets are based on **PMD 7.18.0** with Apex rules.

**Requirements**:

- PMD: 7.0.0+
- Java: 11+
- Salesforce Code Analyzer: 4.0.0+
- Salesforce CLI Scanner: 3.0.0+

---

### Common PMD Violations & Fixes

#### 1. ApexCRUDViolation

**Violation**: Missing CRUD/FLS checks before DML

**Fix**:

```apex
// Before (violation)
insert newAccount;

// After (fixed)
if (Schema.sObjectType.Account.isCreateable()) {
    insert newAccount;
}
```

#### 2. OperationWithLimitsInLoop

**Violation**: SOQL query inside a loop

**Fix**:

```apex
// Before (violation)
for (Account acc : accounts) {
    List<Contact> contacts = [SELECT Id FROM Contact WHERE AccountId = :acc.Id];
}

// After (fixed)
Set<Id> accountIds = new Set<Id>();
for (Account acc : accounts) {
    accountIds.add(acc.Id);
}
Map<Id, List<Contact>> contactsByAccount = new Map<Id, List<Contact>>();
for (Contact con : [SELECT Id, AccountId FROM Contact WHERE AccountId IN :accountIds]) {
    // Group contacts by account
}
```

#### 3. AvoidHardcodingId

**Violation**: Hardcoded Salesforce ID

**Fix**:

```apex
// Before (violation)
Id accountId = '001000000000000AAA';

// After (fixed)
Account acc = [SELECT Id FROM Account WHERE Name = 'Test Account' LIMIT 1];
Id accountId = acc.Id;
```

---

### Resources

- **PMD Official Docs**: [PMD Apex Rules](https://pmd.github.io/latest/pmd_rules_apex.html)
- **Salesforce Code Analyzer**: [Extension Marketplace](https://marketplace.visualstudio.com/items?itemName=salesforce.sfdx-code-analyzer-vscode)
- **PMD Downloads**: [GitHub Releases](https://github.com/pmd/pmd/releases)
- **Salesforce Scanner Plugin**: [CLI Plugin Docs](https://forcedotcom.github.io/sfdx-scanner/)

---

## MCP Wrapper for Salesforce

### Location

[`salesforce/mcp/`](../salesforce/mcp/)

### What is MCP?

**Model Context Protocol (MCP)** is an open protocol that enables AI coding assistants to interact with external tools and services. The MCP wrapper in this repository provides a bridge between AI assistants (like Cursor) and Salesforce CLI.

### Files

#### 1. `a4dwrapper.js`

**Purpose**: NPM package wrapper for executing Salesforce MCP server.

**Features**:

- Automatic npm package installation with retry logic
- Isolated cache directories to avoid conflicts
- Detailed debug logging
- Salesforce Node.js path detection
- Production-optimized execution

**Auto-generated**: This file is automatically generated and maintained by the A4D extension.

---

#### 2. `a4dwithSequencialThinkingConfig.json`

**Purpose**: MCP server configuration for AI coding assistants.

**Configured Servers**:

##### Salesforce MCP Server

```json
{
  "command": "node",
  "args": [
    "/path/to/a4d-mcp-wrapper.js",
    "@salesforce/mcp@latest",
    "--orgs",
    "ALLOW_ALL_ORGS",
    "--toolsets",
    "metadata",
    "--tools",
    "retrieve_metadata,deploy_metadata,run_apex_test,..."
  ]
}
```

**Enabled Tools**:

- `retrieve_metadata` - Retrieve metadata from orgs
- `deploy_metadata` - Deploy metadata to orgs
- `get_username` - Resolve org usernames
- `run_apex_test` - Execute Apex tests
- `run_soql_query` - Run SOQL queries
- `guide_lwc_development` - LWC development guidance
- `assign_permission_set` - Assign permission sets
- `list_all_orgs` - List configured orgs
- And more...

##### Sequential Thinking Server

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
}
```

**Purpose**: Enhances AI reasoning with step-by-step thinking.

##### Filesystem Server

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "<WORKING_DIRECTORY>"]
}
```

**Purpose**: Grants AI access to project files.

---

### How to Use MCP

#### 1. With Cursor

1. **Configure MCP**:

   - Copy `salesforce/mcp/a4dwithSequencialThinkingConfig.json`
   - Update `<WRAPPER_DIRECTORY>` to your actual path
   - Place in Cursor's MCP config directory

2. **Restart Cursor**: MCP servers auto-start

3. **Use AI Tools**:
   ```
   "Deploy my Apex class to the dev org"
   "Run tests for AccountTrigger"
   "Query all active Accounts"
   ```

#### 2. With Continue.dev

1. Configure MCP in Continue settings
2. Point to the wrapper and config files
3. Use AI commands for Salesforce operations

#### 3. With Other AI Assistants

Any MCP-compatible AI assistant can use this configuration:

- Claude Desktop
- Windsurf
- Custom MCP clients

---

### Prerequisites for MCP

- **Node.js**: 16+ installed
- **Salesforce CLI**: Authenticated orgs
- **AI Assistant**: Cursor, Continue, or MCP-compatible client

---

## IDE Integration

### Salesforce Extensions

When using Salesforce profiles, the following extensions are pre-configured:

- **Salesforce Extension Pack**: Complete Salesforce development toolkit
- **Apex Language Support**: IntelliSense for Apex
- **Lightning Web Components**: LWC tooling
- **Apex Replay Debugger**: Debug Apex with logs
- **Salesforce CLI Integration**: Run SF commands from IDE

### Optimal Settings

See [Settings Guide - Salesforce Development](SETTINGS_GUIDE.md#salesforce-development) for complete Salesforce settings.

**Key Settings**:

- Java 21 configured for Apex Language Server
- Test coverage retrieval enabled
- Conflict detection at sync
- Code Analyzer v5 enabled
- Telemetry disabled

---

## Prerequisites

### Python Scripts

```bash
# Install Salesforce CLI
brew install sf  # macOS
# OR: https://developer.salesforce.com/tools/sfdxcli

# Install Python
python3 --version  # Should be 3.9+

# Install dependencies for the schemapy pipeline
pip install -r salesforce/scripts/schemapy/requirements.txt
# (initagentrulespy is stdlib-only — no pip install needed)

# Authenticate to Salesforce
sf org login web --alias DevOrg
sf config set target-org=DevOrg
```

### PMD Rulesets

```bash
# Install PMD (requires Java 11+)
brew install pmd  # macOS
# OR download from: https://github.com/pmd/pmd/releases

# Verify Java version
java --version  # Should be 11+

# Verify PMD installation
pmd --version

# Optional: Install Salesforce Code Analyzer (for IDE integration)
# Via VS Code/Cursor extensions marketplace
# Search for: "Salesforce Code Analyzer"
```

### MCP Wrapper

```bash
# Install Node.js
node --version  # Should be 16+

# Verify Salesforce CLI
sf --version

# Authenticate orgs (if not done)
sf org login web --alias MyOrg
```

---

## Quick Start

### For Schema Generation

```bash
# 1. Clone/navigate to repo
cd /path/to/configs

# 2. Install Python deps + ensure Salesforce CLI is authenticated
pip install -r salesforce/scripts/schemapy/requirements.txt
sf org list

# 3. Run the full 12-step pipeline
python3 salesforce/scripts/schemapy/auto_generate_schema.py

# 4. Check output
ls config/schema/objects/
ls config/schema/_junctions.toon
cat ER.md | head -40
```

### For Bootstrapping AI-Agent Rules into a New Salesforce Repo

```bash
# From inside the new repo
python3 /path/to/initagentrulespy/init.py

# Preview first if you want
python3 /path/to/initagentrulespy/init.py --dry-run

# Overwrite existing files
python3 /path/to/initagentrulespy/init.py --force
```

### For PMD Code Analysis

```bash
# 1. Install PMD (if not already installed)
brew install pmd  # macOS

# 2. Run analysis on your Apex code
pmd check --dir force-app/main/default/classes \
  --rulesets salesforce/pmd/main-ruleset.xml \
  --format text

# 3. Or use with Salesforce CLI Scanner
sf scanner run --target "force-app/**/*.cls" \
  --pmdconfig salesforce/pmd/main-ruleset.xml \
  --format table
```

### For MCP Integration

```bash
# 1. Configure MCP in your AI assistant
# - Copy salesforce/mcp/a4dwithSequencialThinkingConfig.json
# - Update paths to match your system

# 2. Restart AI assistant

# 3. Test MCP connection
# In Cursor/Continue: "List all my Salesforce orgs"
```

---

## Detailed Documentation

For comprehensive documentation on each component:

- **Schema Pipeline**: See [`salesforce/scripts/schemapy/README.md`](../salesforce/scripts/schemapy/README.md)

  - The full 12-step pipeline (Steps 1-12, helper modules, output shape)
  - Per-script CLI flag reference
  - TOON cell-decoding conventions
  - Troubleshooting guide

- **AI-Agent Rules Bootstrap**: See [`salesforce/scripts/initagentrulespy/README.md`](../salesforce/scripts/initagentrulespy/README.md)

  - End-user TL;DR
  - Maintainer guide (`_sync.py`, `SOURCES` table, `_tokenize` rules)
  - Per-file transforms + how to add new files to the kit

- **Scripts Index**: See [`salesforce/scripts/README.md`](../salesforce/scripts/README.md)

  - Quick comparison of `schemapy` vs `initagentrulespy`

- **PMD Rulesets**: See [`salesforce/pmd/README.md`](../salesforce/pmd/README.md)

  - Quick reference for both rulesets
  - Common violations and fixes
  - Customization examples

- **MCP Configuration**: See MCP server documentation
  - [@salesforce/mcp](https://www.npmjs.com/package/@salesforce/mcp)
  - [Model Context Protocol](https://modelcontextprotocol.io/)

---

## Troubleshooting

### Python Scripts

#### Error: "sf command not found"

```bash
# Install Salesforce CLI
brew install sf  # macOS
# OR download from https://developer.salesforce.com/tools/sfdxcli

# Verify installation
sf --version
```

#### Error: "This org hasn't been authenticated"

```bash
sf org login web --alias MyOrg
sf config set target-org=MyOrg
```

#### Error: "toon-format module not found"

```bash
pip install -r salesforce/scripts/schemapy/requirements.txt
# OR install the beta directly
pip install --pre toon-format
```

#### Error: SSL / `CERTIFICATE_VERIFY_FAILED` in Step 10

```bash
# stdlib's default trust store is empty on python.org macOS builds and
# many venvs. _sf_session.py prefers certifi's bundled CA list when present.
pip install certifi
```

#### Step 10 (`collect_usage_stats.py`) takes >30 minutes

Expected on large orgs (600+ objects). `composite/batch` already batches up to 25 SOQL queries per HTTP call, but a full picklist-and-RecordType census still touches thousands of queries. Use `--objects` to scope to a smaller set.

#### `_junctions.toon` shows everything as `schema_only`

Step 10 was skipped or failed — re-run `collect_usage_stats.py` then `detect_junctions.py`. To intentionally skip count enrichment, pass `--no-counts` to `detect_junctions.py`.

### AI-Agent Rules Bootstrap (`initagentrulespy`)

#### "templates/ folder not found"

You ran `init.py` without the sibling `templates/` folder. Either you copied just the `.py` file (copy the whole `initagentrulespy/` folder instead), or the source-repo maintainer hasn't run `_sync.py` yet.

#### Sentinel `<TARGET_ORG_ALIAS>` / `<PMD_PATH>` / `<JAVA_HOME>` left in files

The script couldn't auto-detect that value. Either install/configure the underlying tool and re-run with `--force`, or pass the value explicitly:

```bash
python3 init.py --alias MyOrg --pmd-path /absolute/path/to/pmd --java-home /absolute/path/to/jdk --force
```

### MCP Wrapper

#### MCP Server Won't Start

1. Check Node.js version: `node --version` (needs 16+)
2. Verify paths in config file are correct
3. Check Salesforce CLI authentication: `sf org list`
4. Review MCP logs in AI assistant

#### Tools Not Available

1. Ensure `--tools` list in config matches available tools
2. Restart AI assistant
3. Check MCP server status

---

## Best Practices

### Schema Management

1. **Run the orchestrator regularly** (`auto_generate_schema.py`) when org metadata changes
2. **Use `--dry-run`** on `enrich_schema_with_picklists.py` before mass enrichment
3. **Version control** the `config/schema/` tree + `ER.md` to track changes over time
4. **Active values only** — pipeline intentionally excludes inactive picklist values
5. **Refresh counts independently** — re-run steps 10-12 (`collect_usage_stats.py` → `detect_junctions.py` → `generate_er.py`) without doing a full describe pass when only record volumes have changed
6. **Backup** original schemas before bulk operations

### PMD Code Analysis

1. **Start with main-ruleset** for existing codebases
2. **Run in CI/CD** to prevent new violations from being committed
3. **Fix critical issues first** - prioritize Security and Error Prone categories
4. **Customize thresholds** based on team standards and legacy code
5. **Document suppressions** - always comment why PMD warnings are suppressed
6. **Regular audits** - review suppressed warnings periodically

### MCP Usage

1. **Authenticate all orgs** before starting MCP
2. **Test connections** after configuration changes
3. **Review permissions** - MCP has full SF CLI access
4. **Monitor logs** - check for authentication issues

---

## Contributing

Improvements welcome! Areas for contribution:

1. **New Scripts**: Add schema validation, backup utilities
2. **PMD Enhancements**: Suggest additional rules or custom rulesets
3. **MCP Tools**: Request additional Salesforce CLI integrations
4. **Documentation**: Clarify setup steps, add examples
5. **Bug Fixes**: Report issues with scripts, PMD, or MCP

---

## Resources

- **Salesforce CLI**: [Official Docs](https://developer.salesforce.com/docs/atlas.en-us.sfdx_cli_reference.meta/sfdx_cli_reference/)
- **PMD**: [Official Website](https://pmd.github.io/) | [Apex Rules](https://pmd.github.io/latest/pmd_rules_apex.html) | [GitHub](https://github.com/pmd/pmd)
- **Salesforce Code Analyzer**: [Extension Marketplace](https://marketplace.visualstudio.com/items?itemName=salesforce.sfdx-code-analyzer-vscode) | [CLI Plugin](https://forcedotcom.github.io/sfdx-scanner/)
- **MCP Protocol**: [Model Context Protocol](https://modelcontextprotocol.io/)
- **Salesforce MCP**: [@salesforce/mcp](https://www.npmjs.com/package/@salesforce/mcp)
- **TOON Spec**: [Token-Oriented Object Notation v3.0](https://github.com/toon-format/spec/blob/main/SPEC.md) | [PyPI package](https://pypi.org/project/toon-format/)
- **certifi**: [PyPI](https://pypi.org/project/certifi/)

---

[← Back to Main README](../README.md) | [← Previous: Customization Guide](CUSTOMIZATION_GUIDE.md)
