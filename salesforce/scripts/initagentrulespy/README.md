# initagentrulespy — bootstrap AI-agent rules into a new Salesforce repo

A self-contained Python kit that materializes a curated AI-agent rule, skill, doc, manifest, and config set into any new Salesforce repo. The script auto-detects the target workspace's `target-org` alias, Java home, and PMD binary path, and substitutes those values into the generated files so they work out of the box on macOS, Linux, and Windows (including locked-down Windows where editing PATH/env-vars isn't allowed).

The bundled `templates/` folder uses `{{...}}` placeholder tokens (e.g. `{{ORG_ALIAS}}`, `{{ORG_NAME}}`, `{{JAVA_HOME}}`) instead of any real org-specific values, so nothing personal or org-specific leaks through the kit when you share it with colleagues. The human-readable project / org name (`{{ORG_NAME}}`) defaults to `CURR ORG` — pass `--org-name 'Your Project Name'` to substitute something nicer.

---

## TL;DR — for end users

1. Copy the entire `scripts/initagentrulespy/` folder to your machine. The folder is fully self-contained — you do NOT need to clone the source repo.
2. From inside your new Salesforce repo, run:

   ```bash
   python3 /path/to/initagentrulespy/init.py
   ```

   That's it. The script writes ~46 files into the current directory and reports a summary.

3. Open `.cursor/rules/sf-cli-commands.mdc` in your editor — that's the canonical entry point for the rules.

### What gets generated

| Path                             |                              Count | What it is                                                                                                                                                                                                                                       |
| -------------------------------- | ---------------------------------: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `.cursor/rules/`                 |                                 10 | Cursor rules (always-applied + on-demand). Includes a stub `org-data-model.mdc` you fill in for your own org.                                                                                                                                    |
| `.cursor/permissions.json`       |                                  1 | Cursor IDE terminal command allowlist (`terminalAllowlist`) — read-only `sf` / `git` / shell command prefixes that auto-run without approval. Mirrors the Claude-side `.claude/settings.json` allowlist.                                         |
| `.claude/skills/`                | 5 skills + `.claude/settings.json` | Claude Code skills mirroring the rules, plus the Claude Code allowlist (`permissions.allow`) in `settings.json`. Excludes machine-local `settings.local.json`.                                                                                   |
| `docs/`                          |                                  9 | Reference docs (OmniStudio guides, sf retrieve playbook, schema-quickref). Includes a stub `docs/omnistudio/org-conventions.md`.                                                                                                                 |
| `changes/_templates/`            |                                  3 | Bug-fix / story / refactor doc templates referenced by the `changes-doc-mandatory` rule.                                                                                                                                                         |
| `.vscode/`                       |                                  1 | `settings.json` only (with detected Java home). `extensions.json` and `launch.json` are intentionally NOT generated — leave those to per-project preference.                                                                                     |
| `.mcp.json` + `.cursor/mcp.json` |                   2 (same content) | MCP server config. Same file content is written to BOTH paths so Claude Code (reads project-root `.mcp.json`) and Cursor (reads `.cursor/mcp.json`) share the same server set. The filesystem-MCP path is auto-set to your repo's absolute path. |
| `manifest/fullpackage/`          |                                 11 | Pre-sharded full-org retrieve manifests (each shard fits under the 10k-component metadata-API limit).                                                                                                                                            |
| `config/pmd-ruleset.xml`         |                                  1 | Sensible default Apex PMD ruleset. Tune thresholds for your project.                                                                                                                                                                             |

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

| Placeholder in `templates/`                                    | Becomes (at init time)                                 | Detection chain                                                                                                                                                                                             | Fallback if detection / CLI flag missing                                   |
| -------------------------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `{{ORG_ALIAS}}`                                                | Your `target-org` alias                                | `<target>/.sf/config.json` → `target-org`, then `<target>/.sfdx/sfdx-config.json` → `defaultusername`, then `--alias` flag, then interactive prompt                                                         | `<TARGET_ORG_ALIAS>` (sentinel)                                            |
| `{{ORG_NAME}}`                                                 | Human-readable project / org name (e.g. "Acme Health") | `--org-name` CLI flag only — no auto-detect                                                                                                                                                                 | `CURR ORG` (deliberate readable default; grep + replace later if you want) |
| `{{JAVA_HOME}}` (in `.vscode/settings.json`)                   | Detected JDK home                                      | `/usr/libexec/java_home -v 21\|17\|11` (macOS), `$JAVA_HOME`, `/usr/lib/jvm/java-*` glob (Linux), `where java` parent (Windows)                                                                             | `<JAVA_HOME>` (sentinel)                                                   |
| `{{PMD_PATH}}` (in `.cursor/rules/pmd-ruleset.mdc` etc.)       | Absolute pmd binary path                               | `shutil.which("pmd")`, then OS-specific install paths and `pmd-bin-*` glob, then `$PMD_HOME`. **The full absolute path is baked in** so Windows users without PATH-edit access still get a working command. | `<PMD_PATH>` (sentinel)                                                    |
| `{{WORKSPACE_PATH}}` (in `.mcp.json` filesystem-server `args`) | Target dir absolute path                               | `os.path.abspath(target_dir)`                                                                                                                                                                               | n/a (always available)                                                     |

If detection falls back to a sentinel, the script prints a warning at the end of the run with instructions on how to fix it.

> **Why `{{...}}` tokens instead of literal values?** The kit is meant to be shared. Carrying real values like a specific sf alias, an absolute workspace path, or the source org's brand name through the templates would leak personal/org info into anything a colleague clones or zips. So `templates/` ships pre-tokenized with `{{...}}` placeholders, and `init.py` substitutes them at write time using values it detects in (or are passed to) the colleague's own workspace.

### Existing files

By default, the script **skips** any file that already exists in the target dir (and logs the skip). Pass `--force` to overwrite. Use `--dry-run` first if you're unsure.

---

## Sharing with colleagues

The shareable kit is just two things: `init.py` and the sibling `templates/` folder. That's all a colleague needs.

Three options, in order of preference:

1. **Git repo** — push `scripts/initagentrulespy/` (the whole folder, including `templates/`) and have your colleague `git clone`. They run `python3 path/to/initagentrulespy/init.py /path/to/their/new-repo`.
2. **Zip + send** — `cd scripts && zip -r initagentrulespy.zip initagentrulespy/` and share via Slack / email / shared drive.
3. **Copy via scp / rsync** — for a one-off bootstrap.

The script has zero runtime dependencies on the source repo. As long as your colleague has Python 3.9+ and the `templates/` folder, it works.

> The template generator that produced `templates/` is intentionally local-only and not part of the shareable kit — `templates/` ships pre-tokenized with `{{...}}` placeholders that `init.py` substitutes at the colleague's end.

---

## Troubleshooting

**"templates/ folder not found"** — You ran `init.py` without the sibling `templates/` folder. Copy the whole `initagentrulespy/` folder (both `init.py` and `templates/`), not just the `.py` file.

**Sentinel `<TARGET_ORG_ALIAS>` left in files** — The script couldn't find a `target-org` for your repo. Run:
```bash
sf config set target-org=<your-alias>
python3 init.py --force
```

**Sentinel `<PMD_PATH>` left in pmd-ruleset.mdc** — PMD isn't installed (or installed in a non-standard location). Either install via Homebrew (`brew install pmd`) / Chocolatey (`choco install pmd`) and re-run, or pass `--pmd-path /absolute/path/to/pmd` directly.

**Sentinel `<JAVA_HOME>` in .vscode/settings.json** — Same idea: install a JDK or set `JAVA_HOME` and re-run, or pass `--java-home /absolute/path/to/jdk`.

**Files I want are getting skipped** — They already exist in the target. Pass `--force` to overwrite.

**Want to see what would happen first** — Pass `--dry-run`.
