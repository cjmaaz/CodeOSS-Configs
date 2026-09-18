# initagentrulespy — bootstrap AI-agent rules into a new Salesforce repo

A self-contained Python kit that materializes a curated AI-agent rule, skill, doc, script, manifest, and config set into any new Salesforce repo. The script auto-detects the target workspace's `target-org` alias, API version, Java home, and PMD binary path, and substitutes those values into the generated files so they work out of the box on macOS, Linux, and Windows (including locked-down Windows where editing PATH/env-vars isn't allowed).

The bundled `templates/` folder uses `{{...}}` placeholder tokens (e.g. `{{ORG_ALIAS}}`, `{{ORG_NAME}}`, `{{JAVA_HOME}}`) instead of any real org-specific values, so nothing personal or org-specific leaks through the kit when you share it with colleagues. The human-readable project / org name (`{{ORG_NAME}}`) defaults to `CURR ORG` — pass `--org-name 'Your Project Name'` to substitute something nicer.

## `templates/` is the single source of truth

Content flows in exactly one direction:

```
templates/**  ──(init.py substitutes tokens)──>  your repo's .cursor/, .claude/, docs/, …
```

The installed files are **generated output**. To change a rule, edit the file under `templates/`, then re-run `init.py <target> --force` and commit both sides. Do not hand-edit the generated copies — `init.py <target> --status` exists to catch it if you do.

This direction matters. An earlier version of the kit worked backwards: a generator read the *installed* files and find-replaced the source project's literals into `{{...}}` tokens. That forced it to hard-code one specific project's vocabulary (its alias, its brand name), which stopped matching the instant the kit was copied to a different project — and then silently wrote the new project's real values into `templates/` instead of tokens. Generating forwards removes the failure mode entirely: there is no reverse conversion to go stale.

Run the leak gate **from your project root** before sharing the kit:

```bash
python3 scripts/initagentrulespy/init.py . --verify-templates --org-name 'Your Org'
```

It fails on absolute machine paths and on the literal values your own tokens resolve to, deriving that list from the live repo rather than from a hard-coded denylist — which is what keeps it working after the kit moves to a new project. It reads `target_dir` to find those values, so running it from the kit folder leaves the org checks with nothing to look for; in that case it exits non-zero rather than reporting a false all-clear.

It cannot detect what it cannot derive: your org's object, field, and component names are invisible to it. Keep those out of `templates/` by hand.

### File classes

| Class | Behaviour | Examples |
|---|---|---|
| **Kit-managed** | Regenerated on every `--force` run | The rules, skills, docs, doc templates, manifests |
| **Kit-seeded** | Installed when absent, then never overwritten or deleted — your filled-in version wins, even under `--force`. Pass `--replace-seeded` to reset to the blank scaffold. | `.cursor/rules/org-data-model.mdc`, `docs/omnistudio/org-conventions.md` |
| **Merged** | Combined with your existing file instead of replacing it, even under `--force`. Pass `--replace-merged` to overwrite instead. | `.vscode/settings.json` (property-by-property), `.gitignore` (append-only) |
| **Project-only** | The kit never reads or writes these | `force-app/`, `config/schema/*.toon`, `changes/`, `docs/lld/`, `docs/ut/`, `scripts/`, org-measured manifests such as the `fullpackage-customfield-shard-*.xml` files |

Org-measured artifacts stay project-only on purpose. The CustomField shard manifests, for instance, list well over a thousand literal object API names from one specific org — shipping them would be the single largest leak in the kit. `docs/org-mirror/README.md` documents how to generate them for whatever org you are pointed at.

A fifth class sits outside all of this: files that appear in `templates/` without anyone adding them. `.DS_Store`, `Thumbs.db`, `desktop.ini`, `__pycache__/`, `.pytest_cache/`, `.ipynb_checkpoints/`, and `*.pyc` are skipped by the template walk. They are gitignored, so they never surface in a diff or a review, but the walk is filesystem-based rather than git-based — without the filter they would be materialized into every bootstrapped project and inflate the file count.

---

## TL;DR — for end users

1. Copy the entire `scripts/initagentrulespy/` folder to your machine. The folder is fully self-contained — you do NOT need to clone the source repo.
2. From inside your new Salesforce repo, run:

   ```bash
   python3 /path/to/initagentrulespy/init.py
   ```

   That's it. The script writes ~58 files (the 57-file kit plus an `.initagentrulespy-manifest.json` install-tracking marker) into the current directory and reports a summary.

3. Open `.cursor/rules/sf-cli-commands.mdc` in your editor — that's the canonical entry point for the rules.

### What gets generated

| Path                             |                              Count | What it is                                                                                                                                                                                                                                       |
| -------------------------------- | ---------------------------------: | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `.cursor/rules/`                 |                                  9 | Cursor rules (always-applied + on-demand). Consolidated set: `adversarial-review.mdc` (mandatory parallel multi-critic Gate A/Gate B review protocol), `apex-development.mdc` (deploy / validate / test / PMD / log-verify / formatting), `documentation-workflow.mdc` (intake → LLD → wrap-up + step-by-step AC test evidence), `retrieve-before-edit.mdc` (org-is-source-of-truth mandate), plus `omnistudio-deploy-cache-bust`, `salesforce-schema-validation`, `sf-cli-commands`, `python-selenium-automation`, and a stub `org-data-model.mdc` you fill in for your own org.                |
| `.cursor/permissions.json`       |                                  1 | Cursor IDE terminal command allowlist (`terminalAllowlist`) — read-only `sf` / `git` / shell command prefixes that auto-run without approval. Mirrors the Claude-side `.claude/settings.json` allowlist.                                         |
| `.cursor/sandbox.json`           |                                  1 | Cursor agent sandbox config — workspace read/write plus both home-level and workspace-local `.sf`, `.sfdx`, `.config/sf`, and `.cache` paths, with a deny-by-default network policy that allowlists Salesforce domains. Paths are auto-filled at init. |
| `.claude/skills/`                | 6 skills + `.claude/settings.json` | Claude Code skills mirroring the rules (`adversarial-review`, `apex-development`, `documentation-workflow`, `retrieve-before-edit`, `omnistudio-deploy-cache-bust`, `schema-lookup`), plus the Claude Code allowlist (`permissions.allow`) in `settings.json`. Excludes machine-local `settings.local.json`.                                                                                   |
| `docs/`                          |                                 17 | Reference docs plus templates and the org-mirror runbook. `docs/_templates/` holds 4 design-doc templates (LLD, open-questions-and-KT, session walkthrough, step-by-step AC test) used by the `documentation-workflow` rule; `docs/diagram-conventions.md` defines the component-scoped mermaid style those diagrams must follow; `docs/org-mirror/` is the full-org retrieve runbook plus its 3 executable shell scripts; `docs/omnistudio/` (7) and `docs/schema-quickref.md` are reference material. Includes a stub `docs/omnistudio/org-conventions.md`. |
| `changes/_templates/`            |                                  4 | Bug-fix / story / refactor / retrieve-audit doc templates referenced by the `documentation-workflow` rule.                                                                                                                                       |
| `config/schema/`                 |                                  1 | `README.md` documenting the per-object TOON schema-file layout that a separately provisioned `scripts/schemapy/` pipeline generates and `salesforce-schema-validation` reads. The schema TOON files themselves are generated per-org, not shipped. |
| `.vscode/`                       |                                  1 | `settings.json` only (with detected Java home). Existing top-level properties are merged: missing properties are appended, while matching properties are replaced and their previous values retained as comments. `extensions.json` and `launch.json` are not generated. |
| `.mcp.json` + `.cursor/mcp.json` |                   2 (same content) | MCP server config. Same file content is written to BOTH paths so Claude Code (reads project-root `.mcp.json`) and Cursor (reads `.cursor/mcp.json`) share the same server set. The filesystem-MCP path is auto-set to your repo's absolute path. |
| `manifest/`                      |                     12 (1 + 11) | Master `fullpackage.xml` plus 11 pre-sharded `fullpackage/` full-org retrieve manifests (each shard fits under the 10k-component metadata-API limit).                                                                                            |
| `config/pmd-ruleset.xml`         |                                  1 | Sensible default Apex PMD ruleset. Tune thresholds for your project.                                                                                                                                                                             |
| `.gitignore`                     |                                  1 | Salesforce/LWC/Node/OS noise plus the paths this workflow generates (`.retrieve-logs/`, `.sf-ops/`, Vlocity build temp, and this kit's own install state). **Append-only merge** — an existing `.gitignore` keeps every entry, ordering, and comment it already had; only missing patterns are added. |
| `.initagentrulespy-manifest.json` |                                 1 | Install-tracking marker: kit protocol version, status, managed file paths, and the values substituted — so later runs can spot obsolete files and recover a value whose detection fails on a given machine. **Gitignore it**; it records the JDK and PMD paths of whoever ran the install. |

The bootstrapper never installs, updates, inventories, or removes anything under
the target's `scripts/` directory. Provision `schemapy` separately when the
generated guidance requires it; existing project scripts remain untouched.

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
  --api-version VER       Override API version detection (default: sourceApiVersion
                          from the target's sfdx-project.json). Example: 66.0
  --verify-templates      Scan templates/ for org-specific leakage and exit.
                          Writes nothing. Run this before sharing the kit.
  --status                Report which generated files are missing or hand-edited
                          relative to templates/, then exit. Writes nothing.
  --force                 Overwrite all managed files (default: fail on a differing collision).
                          Merged files are still merged, not replaced.
  --replace-merged        Replace .gitignore and .vscode/settings.json with the kit
                          version instead of merging into them. DESTRUCTIVE. Combine
                          with --force to write; alone, a differing file is still
                          reported as a conflict.
  --replace-seeded        Reset the seed-once scaffolds (org-data-model.mdc,
                          org-conventions.md) to the kit's blank version.
                          DESTRUCTIVE. Combine with --force to write.
  --reset                 Restore the target to pristine kit state. Shorthand for
                          --force --replace-merged --replace-seeded. DESTRUCTIVE.
  --update                Stage changed/new kit files under .initagentrulespy-updates/<gen>/
                          instead of overwriting; never clobbers a customized target.
  --ignore-conflicts      Install missing files in the target, leave conflicting files
                          unchanged, and list every conflict at the end.
  --missing-only          Backward-compatible alias for --ignore-conflicts.
  --dry-run               Print what would be written; do not touch the filesystem.
  --no-prompt             Never prompt; fall back to sentinel placeholders.
```

`--force`, `--update`, and `--ignore-conflicts` are mutually exclusive. `--replace-merged` and `--replace-seeded` are orthogonal and compose with any of them.

### Putting a mangled target back to pristine kit state

`--force` alone already restores every ordinary managed file — rules, skills, doc templates, docs, manifests, `config/pmd-ruleset.xml`. Edit them freely; a bad edit is one command away from being undone.

Two classes survive `--force` on purpose, because they are yours rather than the kit's, and each has an explicit opt-out:

| Class | Why `--force` spares it | Opt out with |
|---|---|---|
| **Merged** — `.gitignore`, `.vscode/settings.json` | Shared files the project owns; re-baselining the kit is no reason to drop your ignore rules or editor settings | `--replace-merged` |
| **Seed-once** — `org-data-model.mdc`, `org-conventions.md` | Blank scaffolds you fill in; the filled-in data model is often the longest file in the repo | `--replace-seeded` |

So the complete reset — everything, no exceptions — is `--reset`, shorthand for all three:

```bash
python3 init.py <target> --reset
# identical to: --force --replace-merged --replace-seeded
```

`--reset` implies `--force`, so it cannot be combined with `--update` or `--ignore-conflicts`.

Each destructive flag names every file it is about to discard before anything is written, and neither writes on its own: without `--force` a differing file is still reported as a conflict. They are kept separate rather than folded into `--force` so that refreshing the kit and destroying your own content are never the same keystroke.

### What gets substituted

`templates/` ships with seven placeholder tokens. `init.py` replaces each of them with a runtime-detected (or CLI-supplied) value:

| Placeholder in `templates/`                                    | Becomes (at init time)                                 | Detection chain                                                                                                                                                                                             | Fallback if detection / CLI flag missing                                   |
| -------------------------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `{{ORG_ALIAS}}`                                                | Your `target-org` alias                                | `<target>/.sf/config.json` → `target-org`, then `<target>/.sfdx/sfdx-config.json` → `defaultusername`, then `--alias` flag, then interactive prompt                                                         | `<TARGET_ORG_ALIAS>` (sentinel)                                            |
| `{{ORG_NAME}}`                                                 | Human-readable project / org name (e.g. "Acme Health") | `--org-name` CLI flag, then whatever a previous install recorded in `.initagentrulespy-manifest.json`. No machine source exists for a prose label.                                                          | `CURR ORG` (deliberate readable default; grep + replace later if you want) |
| `{{JAVA_HOME}}` (in `.vscode/settings.json`)                   | Detected JDK home                                      | `/usr/libexec/java_home -v 21\|17\|11` (macOS), `$JAVA_HOME`, `/usr/lib/jvm/java-*` glob (Linux), `where java` parent (Windows)                                                                             | `<JAVA_HOME>` (sentinel)                                                   |
| `{{PMD_PATH}}` (in `.cursor/rules/apex-development.mdc` etc.)  | Absolute pmd binary path                               | `shutil.which("pmd")`, then OS-specific install paths and `pmd-bin-*` glob, then `$PMD_HOME`. **The full absolute path is baked in** so Windows users without PATH-edit access still get a working command. | `<PMD_PATH>` (sentinel)                                                    |
| `{{WORKSPACE_PATH}}` (in MCP filesystem `args` and `.cursor/sandbox.json`) | Target dir absolute path                               | `os.path.abspath(target_dir)`                                                                                                                                                                               | n/a (always available)                                                     |
| `{{HOME_PATH}}` (in `.cursor/sandbox.json`)                    | The current user's home directory                      | `Path.home()`                                                                                                                                                                                               | n/a (always available)                                                     |
| `{{API_VERSION}}` (in manifests, REST paths, rule prose)       | Salesforce API version                                 | `--api-version` flag, then `<target>/sfdx-project.json` → `sourceApiVersion`                                                                                                                                | `<API_VERSION>` (sentinel)                                                 |

If detection falls back to a sentinel, the script prints a warning at the end of the run with instructions on how to fix it.

Only text files are substituted (`.md`, `.mdc`, `.json`, `.xml`, `.txt`, `.yml`, `.yaml`). The shell scripts under `docs/org-mirror/` are deliberately excluded: they ship byte-identical, reading their org alias from the environment and everything else from the run's generated files, so there is nothing in them to replace.

> **Why `{{...}}` tokens instead of literal values?** The kit is meant to be shared. Carrying real values like a specific sf alias, an absolute workspace path, or the source org's brand name through the templates would leak personal/org info into anything a colleague clones or zips. So `templates/` ships pre-tokenized with `{{...}}` placeholders, and `init.py` substitutes them at write time using values it detects in (or are passed to) the colleague's own workspace.

### Existing files & re-runs

A fresh run into an empty (or kit-free) directory just writes every file. On a **re-run** the behaviour depends on whether existing managed files still match this release:

- **Missing files** are always installed.
- **Identical files** are left alone (counted as skipped).
- **`.gitignore` is merged append-only.** Missing kit entries are appended with
  their explanatory comments; your own entries, ordering, and comments are never
  rewritten. A pattern already present is skipped, and a trailing slash counts as
  the same rule (`.sf-ops` and `.sf-ops/` do not both get added). Re-running adds
  nothing.
- **`.vscode/settings.json` is merged property-by-property** instead of treated
  as a normal conflict. Missing template properties are appended. A property
  with a different existing value is replaced, with the previous property
  commented immediately above it.
- If any managed file **differs** from this release (you customized it, or you're on an older kit), the default run **fails** rather than silently clobbering or half-upgrading. Pick one:
  - `--update` — stages the changed/new/obsolete candidates under `.initagentrulespy-updates/<generation>/` with a merge manifest, leaving your live files untouched so you can diff and merge deliberately.
  - `--force` — overwrites all managed files and deletes now-obsolete ones (clean re-baseline; discards local edits).
  - `--ignore-conflicts` — writes missing files directly into the target, leaves every conflicting existing path unchanged, and prints a consolidated conflict list at the end. `--missing-only` remains as an alias.

Use `--dry-run` first to preview any of these.

**Executable bits are repaired every run.** The `docs/org-mirror/*.sh` scripts must land at mode `755`. The mode is applied to the temp file *before* the atomic replace, so the visible path never briefly exists as non-executable. Because a file whose content already matches is skipped by the write planner, permissions are then re-checked across every managed path rather than only the ones written — a script that lost its executable bit to a zip round-trip, a copy through a filesystem without mode support, or a stray `chmod` is repaired and reported as `✓ mode 755:`. Mode is not content, so this runs outside the content transaction and is idempotent. The runbook still invokes the scripts through `bash`, so they work even where the bit did not survive.

**Install safety.** Writes are atomic and transactional — a target lock (`.initagentrulespy.lock`) blocks concurrent runs, a journal (`.initagentrulespy-transactions/`) rolls the whole run back on any failure or interruption, and the `.initagentrulespy-manifest.json` marker records what was installed so later `--update` runs can distinguish your edits from stale kit files.

---

## Sharing with colleagues

The shareable kit is just two things: `init.py` and the sibling `templates/` folder. That's all a colleague needs.

Three options, in order of preference:

1. **Git repo** — push `scripts/initagentrulespy/` (the whole folder, including `templates/`) and have your colleague `git clone`. They run `python3 path/to/initagentrulespy/init.py /path/to/their/new-repo`.
2. **Zip + send** — `cd scripts && zip -r initagentrulespy.zip initagentrulespy/` and share via Slack / email / shared drive.
3. **Copy via scp / rsync** — for a one-off bootstrap.

The script has zero runtime dependencies on the source repo. As long as your colleague has Python 3.9+ and the `templates/` folder, it works.

> Run `python3 init.py <project-root> --verify-templates --org-name '<Your Org>'` before sharing. It must exit 0.

---

## Troubleshooting

**"templates/ folder not found"** — You ran `init.py` without the sibling `templates/` folder. Copy the whole `initagentrulespy/` folder (both `init.py` and `templates/`), not just the `.py` file.

**Sentinel `<TARGET_ORG_ALIAS>` left in files** — The script couldn't find a `target-org` for your repo. Run:
```bash
sf config set target-org=<your-alias>
python3 init.py --force
```

**Sentinel `<PMD_PATH>` left in apex-development.mdc** — PMD isn't installed (or installed in a non-standard location). Either install via Homebrew (`brew install pmd`) / Chocolatey (`choco install pmd`) and re-run, or pass `--pmd-path /absolute/path/to/pmd` directly.

**Sentinel `<JAVA_HOME>` in .vscode/settings.json** — Same idea: install a JDK or set `JAVA_HOME` and re-run, or pass `--java-home /absolute/path/to/jdk`.

**Files I want are getting skipped** — They already exist in the target. Pass `--force` to overwrite.

**Want to see what would happen first** — Pass `--dry-run`.
