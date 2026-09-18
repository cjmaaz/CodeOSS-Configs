# Salesforce Scripts

Three self-contained kits live under this directory. Each ships its own
detailed README — start there once you know which one you want.

| Kit | Purpose | README |
|---|---|---|
| [`schemapy/`](schemapy/) | **(Python)** 12-step pipeline that retrieves Salesforce metadata, generates a TOON-encoded ER schema (`config/salesforce-er-schema.toon`), splits it into per-object folders under `config/schema/`, enriches every field with picklist values / formulas / lookups, then layers in live record-count usage stats, junction detection, and an `ER.md` diagram. | [`schemapy/README.md`](schemapy/README.md) |
| [`initagentrulespy/`](initagentrulespy/) | **(Python)** Bootstrap kit that materializes a curated AI-agent rule, skill, doc, script, manifest, and config set (~58 files) into any new Salesforce repo. Auto-detects `target-org`, API version, Java home, and PMD binary path and substitutes those into the generated files so the rules work out of the box on macOS, Linux, and Windows. | [`initagentrulespy/README.md`](initagentrulespy/README.md) |
| [`git-change-viewer/`](git-change-viewer/) | **(Node + Vite)** Local-only web app that combines git changes from two sources — ticked `changes/*.md` docs (auto-extracting their referenced commit hashes) and hand-picked commits from history — into one GitHub-style diff view, then exports the changed files to a Salesforce `package.xml` (with optional `destructiveChanges.xml`). | [`git-change-viewer/README.md`](git-change-viewer/README.md) |

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
python3 /path/to/initagentrulespy/init.py --org-name 'Your Project Name'
```

Drops `.cursor/rules/`, `.cursor/permissions.json`, `.cursor/sandbox.json`,
`.cursor/mcp.json`, `.claude/skills/`, `.claude/settings.json`, `docs/`,
`changes/_templates/`, `.vscode/settings.json`, `.mcp.json`, `.gitignore`,
`manifest/` (master + 11 shards), and `config/` (`pmd-ruleset.xml` +
`schema/README.md`) into the current directory, plus an
`.initagentrulespy-manifest.json` marker recording what was installed.

`docs/` carries the design-doc templates (LLD, questions-and-KT, walkthrough,
step-by-step AC test), the `docs/diagram-conventions.md` mermaid style those
diagrams follow, the OmniStudio references, and `docs/org-mirror/` — a full-org
retrieve runbook plus three shell scripts that land executable (`755`) and are
re-checked on every run.

Files you own are respected rather than clobbered. `.gitignore` is merged
append-only and `.vscode/settings.json` property-by-property, while
`.cursor/rules/org-data-model.mdc` and `docs/omnistudio/org-conventions.md`
are seeded once and never overwritten afterwards. If a managed file differs on
a re-run, the default run stops instead of half-upgrading — pick `--force` to
re-baseline, `--update` to stage merge candidates, or `--ignore-conflicts` to
install only what's missing. `--reset` returns the target to pristine kit
state, and `--dry-run` previews any of them.

It never touches the target project's `scripts/` directory; install the
standalone `schemapy/` and other script tooling separately.

### Combine git changes and export a package.xml

```bash
# Run from inside the git repo you want to inspect
cd salesforce/scripts/git-change-viewer
npm install
npm run dev          # Vite UI on :5173, API on :3001 — open http://localhost:5173
```

## Requirements

- Salesforce CLI (`sf`) installed and authenticated
- Python 3.9+ (for `schemapy` and `initagentrulespy`)
- Node.js 20.11+ (for `git-change-viewer`)
- Per-kit deps:
  - `schemapy`: `pip install -r salesforce/scripts/schemapy/requirements.txt`
  - `initagentrulespy`: stdlib only — no external dependencies
  - `git-change-viewer`: `npm install` (inside the kit folder)

## See Also

- [PMD Rulesets](../pmd/README.md) — static code analysis rulesets for Apex
- [`docs/SALESFORCE_TOOLS.md`](../../docs/SALESFORCE_TOOLS.md) — repo-wide overview of all Salesforce tooling in this repo
