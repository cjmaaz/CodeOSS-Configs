# initagentrulespy — bootstrap AI-agent rules into a new Salesforce repo

A self-contained Python kit that materializes a curated AI-agent rule, skill, doc, manifest, and config set into any new Salesforce repo. The script auto-detects the target workspace's `target-org` alias, Java home, and PMD binary path, and substitutes those values into the generated files so they work out of the box on macOS, Linux, and Windows (including locked-down Windows where editing PATH/env-vars isn't allowed).

The bundled `templates/` folder uses `{{...}}` placeholder tokens (e.g. `{{ORG_ALIAS}}`, `{{ORG_NAME}}`, `{{JAVA_HOME}}`) instead of any real org-specific values, so nothing personal or org-specific leaks through the kit when you share it with colleagues. The human-readable project / org name (`{{ORG_NAME}}`) defaults to `CURR ORG` — pass `--org-name 'Your Project Name'` to substitute something nicer.

---

## TL;DR — for end users (your colleagues)

1. Copy the entire `scripts/initagentrulespy/` folder to your machine. The folder is fully self-contained — you do NOT need to clone the source repo.
2. From inside your new Salesforce repo, run:

   ```bash
   python3 /path/to/initagentrulespy/init.py
   ```

   That's it. The script writes ~44 files into the current directory and reports a summary.

3. Open `.cursor/rules/sf-cli-commands.mdc` in your editor — that's the canonical entry point for the rules.

### What gets generated

| Path | Count | What it is |
|---|---:|---|
| `.cursor/rules/` | 10 | Cursor rules (always-applied + on-demand). Includes a stub `org-data-model.mdc` you fill in for your own org. |
| `.claude/skills/` | 5 skills + `.claude/settings.json` | Claude Code skills mirroring the rules. Excludes machine-local `settings.local.json`. |
| `docs/` | 9 | Reference docs (OmniStudio guides, sf retrieve playbook, schema-quickref). Includes a stub `docs/omnistudio/org-conventions.md`. |
| `changes/_templates/` | 3 | Bug-fix / story / refactor doc templates referenced by the `changes-doc-mandatory` rule. |
| `.vscode/` | 1 | `settings.json` only (with detected Java home). `extensions.json` and `launch.json` are intentionally NOT generated — leave those to per-project preference. |
| `.mcp.json` + `.cursor/mcp.json` | 2 (same content) | MCP server config. Same file content is written to BOTH paths so Claude Code (reads project-root `.mcp.json`) and Cursor (reads `.cursor/mcp.json`) share the same server set. The filesystem-MCP path is auto-set to your repo's absolute path. |
| `manifest/fullpackage/` | 11 | Pre-sharded full-org retrieve manifests (each shard fits under the 10k-component metadata-API limit). |
| `config/pmd-ruleset.xml` | 1 | Sensible default Apex PMD ruleset. Tune thresholds for your project. |

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

### What gets substituted

`templates/` ships with five placeholder tokens. `init.py` replaces each of them with a runtime-detected (or CLI-supplied) value:

| Placeholder in `templates/` | Becomes (at init time) | Detection chain | Fallback if detection / CLI flag missing |
|---|---|---|---|
| `{{ORG_ALIAS}}` | Your `target-org` alias | `<target>/.sf/config.json` → `target-org`, then `<target>/.sfdx/sfdx-config.json` → `defaultusername`, then `--alias` flag, then interactive prompt | `<TARGET_ORG_ALIAS>` (sentinel) |
| `{{ORG_NAME}}` | Human-readable project / org name (e.g. "Acme Health") | `--org-name` CLI flag only — no auto-detect | `CURR ORG` (deliberate readable default; grep + replace later if you want) |
| `{{JAVA_HOME}}` (in `.vscode/settings.json`) | Detected JDK home | `/usr/libexec/java_home -v 21\|17\|11` (macOS), `$JAVA_HOME`, `/usr/lib/jvm/java-*` glob (Linux), `where java` parent (Windows) | `<JAVA_HOME>` (sentinel) |
| `{{PMD_PATH}}` (in `.cursor/rules/pmd-ruleset.mdc` etc.) | Absolute pmd binary path | `shutil.which("pmd")`, then OS-specific install paths and `pmd-bin-*` glob, then `$PMD_HOME`. **The full absolute path is baked in** so Windows users without PATH-edit access still get a working command. | `<PMD_PATH>` (sentinel) |
| `{{WORKSPACE_PATH}}` (in `.mcp.json` filesystem-server `args`) | Target dir absolute path | `os.path.abspath(target_dir)` | n/a (always available) |

If detection falls back to a sentinel, the script prints a warning at the end of the run with instructions on how to fix it.

> **Why `{{...}}` tokens instead of literal values?** The kit is meant to be shared. Carrying real values like a specific sf alias, an absolute workspace path, or the source org's brand name through the templates would leak personal/org info into anything a colleague clones or zips. The maintainer-side `_sync.py` strips those literals when writing into `templates/`, and `init.py` substitutes the placeholders at write time using values it detects in (or are passed to) the colleague's own workspace.

### Existing files

By default, the script **skips** any file that already exists in the target dir (and logs the skip). Pass `--force` to overwrite. Use `--dry-run` first if you're unsure.

---

## For source-repo maintainers — keeping `templates/` in sync

> This fork of the kit is configured for the **IBX Provider Network** repo (alias `IBXMain`). The source-repo-specific literals live in the `PROJECT_CONFIG` block at the top of [`_sync.py`](_sync.py). If you fork this script for another repo, that block + the `SOURCES` table are the only two places you need to touch.

The folder structure is:

```
scripts/initagentrulespy/
├── README.md         ← this file
├── init.py           ← end-user script
├── _sync.py          ← maintainer-only helper
└── templates/        ← bundled file content (~44 files mirroring final paths)
    ├── .cursor/rules/...
    ├── .claude/...
    ├── docs/...
    ├── changes/_templates/...
    ├── .vscode/...
    ├── .mcp.json
    ├── manifest/fullpackage/...
    └── config/pmd-ruleset.xml
```

`templates/` is the script's source of truth at runtime. It is populated by `_sync.py`, which walks the source repo's actual rules, skills, docs, etc. and copies/transforms them into `templates/`. Crucially, `_sync.py` runs every file through a `_tokenize()` step that replaces source-repo-specific literals with placeholder tokens before writing. The substitution rules are built from the `PROJECT_CONFIG` block in [`_sync.py`](_sync.py); the current configuration (for the IBX fork) produces:

| Literal in source files | Placeholder in `templates/` | Notes |
|---|---|---|
| `/Users/maaz.rahman/Orgs/Work/IBX/IBXMain` | `{{WORKSPACE_PATH}}` | Must come before the alias rule (contains it as a substring) |
| `/Library/Java/JavaVirtualMachines/zulu-21.jdk/Contents/Home` | `{{JAVA_HOME}}` | |
| `ibx-conventions.md` | `org-conventions.md` | Cross-ref fix: the file itself is rename-and-stubbed to `org-conventions.md`, so links pointing at the old name (in `docs/omnistudio/README.md`, `omniscripts.md`, `patterns.md`) get rewritten too |
| `IBX Provider Network` | `{{ORG_NAME}}` | Longest brand literal — must run before the bare-brand catchall below |
| `IBXMain` | `{{ORG_ALIAS}}` | Must run before the bare-brand catchall (substring) |
| `IBX_UAT` / `IBX_QA` | `{{ORG_ALIAS}}_UAT` / `{{ORG_ALIAS}}_QA` | Sandbox alias slots — alias-shaped, not brand mentions |
| `IBX` (standalone) | `{{ORG_NAME}}` | Catchall for the org's brand name in prose; substituted at init time to whatever `--org-name` says (default `CURR ORG`) |
| `pmd check ` (with trailing space) | `{{PMD_PATH}} check ` | |

This is why you can edit `.cursor/rules/sf-cli-commands.mdc` (with `IBXMain` baked in for local use) and not have to think about how it lands in the templates — `_sync.py` does the swap for you, and `init.py` re-substitutes at the colleague's end.

### When to run `_sync.py`

Run it whenever you edit any of the following in the source repo:

- `.cursor/rules/*.mdc` (any of the 9 included rules — see the `SOURCES` table in [`_sync.py`](_sync.py))
- `.claude/skills/*/SKILL.md` (any of the 5 included skills)
- `.claude/settings.json`
- `docs/sf-org-mirror-retrieve.md`, `docs/schema-quickref.md`
- `docs/omnistudio/*.md`
- `changes/_templates/*.md`
- `.vscode/settings.json` (NOT `extensions.json` or `launch.json` — those are excluded)
- `.mcp.json`
- `manifest/fullpackage/*.xml`

You do NOT need to run `_sync.py` after editing the three excluded rules (`find-clean-test-account.mdc`, `ibx-credentialing-workflow.mdc`, `prm-datafix-script-migration.mdc`) or the excluded skill (`.claude/skills/omnistudio/`).

### Running `_sync.py`

```bash
python3 scripts/initagentrulespy/_sync.py            # write changes
python3 scripts/initagentrulespy/_sync.py --check    # CI-friendly: exit 1 if drift
python3 scripts/initagentrulespy/_sync.py --verbose  # log every file (incl. unchanged)
```

After it runs, review the diff under `templates/`, commit both the source change and the regenerated `templates/` files together, so reviewers see them in one PR.

### Per-file transforms

Most files are copied verbatim. Three need special handling, declared in the `SOURCES` table at the top of [`_sync.py`](_sync.py):

| Source | Target | Transform |
|---|---|---|
| `.cursor/rules/ibx-provider-network-data-model.mdc` | `.cursor/rules/org-data-model.mdc` | Rename + replace with stub (`ORG_DATA_MODEL_STUB` constant in `_sync.py`) |
| `docs/omnistudio/ibx-conventions.md` | `docs/omnistudio/org-conventions.md` | Rename + replace with stub (`ORG_CONVENTIONS_STUB`) |
| `.claude/skills/schema-lookup/SKILL.md` | (same path) | Strip the `## Org-specific gotchas (IBX Provider Network)` section to EOF (the anchor heading matches the IBX source; change to your repo's heading when forking) |
| `docs/schema-quickref.md` | (same path) | Strip the `## High-traffic objects for IBX Provider Network` section AND the `## Common field cheat sheet` section (same — anchors match IBX's source headings) |
| `config/pmd-ruleset.xml` | (same path) | Source file does not exist in this source repo; emit a sensible default Apex ruleset (`DEFAULT_PMD_RULESET`) |

All other entries use the `"verbatim"` transform — straight `shutil.copy` semantics with the IBXMain alias still in place (the alias is substituted at `init.py` runtime, not at sync time).

### Adding a new file to the kit

Edit [`_sync.py`](_sync.py)'s `SOURCES` list:

```python
SOURCES = [
    ...
    ("path/in/source/repo.mdc", "path/in/templates.mdc", "verbatim"),
]
```

Then re-run `_sync.py`. `init.py` automatically picks up everything under `templates/` at runtime, so it doesn't need any code change.

### Excluding content from a file

Use `("strip-section", anchor_heading, until_heading_or_None)`:

- `anchor_heading` — the `## Foo` line where stripping starts (matched by `lstrip().startswith()`).
- `until_heading` — the next `## Bar` to STOP stripping at (kept in output). Pass `None` to strip to EOF.

For multiple strips in one file: `("strip-section-multi", [(anchor1, until1), (anchor2, until2)])`.

### CI safeguard

To make sure `templates/` doesn't drift from the source rules, add this to your CI:

```yaml
- run: python3 scripts/initagentrulespy/_sync.py --check
```

It exits 1 if any template file is out of date.

---

## Sharing with colleagues

Three options, in order of preference:

1. **Git repo** — push `scripts/initagentrulespy/` (the whole folder, including `templates/`) and have your colleague `git clone`. They run `python3 path/to/initagentrulespy/init.py /path/to/their/new-repo`.
2. **Zip + send** — `cd scripts && zip -r initagentrulespy.zip initagentrulespy/` and share via Slack / email / shared drive.
3. **Copy via scp / rsync** — for a one-off bootstrap.

The script has zero runtime dependencies on the source repo. As long as your colleague has Python 3.9+ and the `templates/` folder, it works.

---

## Troubleshooting

**"templates/ folder not found"** — You ran `init.py` without the sibling `templates/` folder. Either you copied just the `.py` file (copy the whole `initagentrulespy/` folder instead), or the source-repo maintainer hasn't run `_sync.py` yet.

**Sentinel `<TARGET_ORG_ALIAS>` left in files** — The script couldn't find a `target-org` for your repo. Run:
```bash
sf config set target-org=<your-alias>
python3 init.py --force
```

**Sentinel `<PMD_PATH>` left in pmd-ruleset.mdc** — PMD isn't installed (or installed in a non-standard location). Either install via Homebrew (`brew install pmd`) / Chocolatey (`choco install pmd`) and re-run, or pass `--pmd-path /absolute/path/to/pmd` directly.

**Sentinel `<JAVA_HOME>` in .vscode/settings.json** — Same idea: install a JDK or set `JAVA_HOME` and re-run, or pass `--java-home /absolute/path/to/jdk`.

**Files I want are getting skipped** — They already exist in the target. Pass `--force` to overwrite.

**Want to see what would happen first** — Pass `--dry-run`.
