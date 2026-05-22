#!/usr/bin/env python3
"""
init.py — Bootstrap a Salesforce repo with the AI-agent rule/skill kit.

Reads the bundled `templates/` folder (sibling of this script) and writes
each file into a target directory, replacing five placeholder tokens:

  • {{ORG_ALIAS}}        → the workspace's target-org alias (sf CLI alias)
  • {{ORG_NAME}}         → human-readable project / org name (e.g. "Acme Health")
                            — defaults to "CURR ORG" if --org-name not passed
  • {{JAVA_HOME}}        → detected JDK home (used in .vscode/settings.json)
  • {{PMD_PATH}}         → detected PMD binary absolute path
  • {{WORKSPACE_PATH}}   → target dir absolute path (used in .mcp.json)

The placeholders are baked into templates/ by `_sync.py` (the maintainer
helper); end users never see the original literal values, so nothing
personal or org-specific leaks through the kit.

Detection strategy:
  - Alias mirrors `scripts/schemapy/auto_generate_schema.py` — read
    `<target>/.sf/config.json` first, fall back to
    `<target>/.sfdx/sfdx-config.json`, then `--alias`, then prompt.
  - Org name has no auto-detection; either supplied via `--org-name` or
    defaults to "CURR ORG" (an obviously-placeholder value users can grep
    for and replace project-wide later).
  - Java / PMD probe a sensible cross-platform list of install paths so
    locked-down Windows users (no PATH-edit access) still get full
    absolute paths baked into the generated rules.

Usage:
    python3 init.py [target_dir] [options]

Options:
    --alias NAME         Skip alias detection; use NAME as the target-org alias.
    --org-name NAME      Human-readable project/org name to substitute for
                         {{ORG_NAME}} placeholders. Default: "CURR ORG".
    --java-home PATH     Skip Java detection; use PATH as the JDK home.
    --pmd-path  PATH     Skip PMD detection; use PATH as the absolute pmd binary.
    --force              Overwrite existing files (default: skip with warning).
    --dry-run            Print what would be written; do not touch the filesystem.
    --no-prompt          Never prompt interactively; fall back to sentinels instead.

Run `python3 init.py --help` for the full CLI surface.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# Placeholder tokens (set by _sync.py when populating templates/) and the
# sentinel values that get baked in if runtime detection fails.
#
# The script does NOT carry any source-repo-specific literals — every
# personal / org-specific value lived in the maintainer's source files but
# was tokenized away by _sync.py before reaching templates/.
# ────────────────────────────────────────────────────────────────────────────

# Placeholder tokens that appear in templates/ files.
TOKEN_ORG_ALIAS = "{{ORG_ALIAS}}"
TOKEN_ORG_NAME = "{{ORG_NAME}}"
TOKEN_JAVA_HOME = "{{JAVA_HOME}}"
TOKEN_PMD_PATH = "{{PMD_PATH}}"
TOKEN_WORKSPACE = "{{WORKSPACE_PATH}}"

# Default for {{ORG_NAME}} when the user doesn't pass `--org-name`. Not a
# sentinel — this is a deliberate, human-readable placeholder ("CURR ORG"
# reads as "current org") so the generated docs stay readable even before
# the user customises them.
ORG_NAME_DEFAULT = "CURR ORG"

# Sentinel values left in place when runtime detection fails. Distinct from
# the placeholder tokens so users can grep for them and fix manually.
ALIAS_SENTINEL = "<TARGET_ORG_ALIAS>"
JAVA_SENTINEL = "<JAVA_HOME>"
PMD_SENTINEL = "<PMD_PATH>"

ALIAS_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")  # Conservative: alphanumerics + . _ -

IS_WINDOWS = os.name == "nt"

# ────────────────────────────────────────────────────────────────────────────
# Detection helpers
# ────────────────────────────────────────────────────────────────────────────


def detect_alias(target: Path, cli_alias: str | None, prompt_ok: bool) -> tuple[str, str]:
    """Return (alias, source_descriptor)."""
    if cli_alias:
        if not ALIAS_RE.match(cli_alias):
            raise SystemExit(f"✗ --alias '{cli_alias}' is not a valid alias "
                             f"(allowed chars: A-Z a-z 0-9 . _ -)")
        return cli_alias, "--alias flag"

    sf_config = target / ".sf" / "config.json"
    if sf_config.exists():
        try:
            data = json.loads(sf_config.read_text(encoding="utf-8"))
            alias = data.get("target-org")
            if alias:
                return alias, str(sf_config.relative_to(target))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠ Could not read {sf_config.relative_to(target)}: {e}")

    sfdx_config = target / ".sfdx" / "sfdx-config.json"
    if sfdx_config.exists():
        try:
            data = json.loads(sfdx_config.read_text(encoding="utf-8"))
            alias = data.get("defaultusername")
            if alias:
                return alias, str(sfdx_config.relative_to(target))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠ Could not read {sfdx_config.relative_to(target)}: {e}")

    if prompt_ok and sys.stdin.isatty():
        try:
            user_input = input(
                f"  No target-org found in {target}/.sf/config.json or "
                f"{target}/.sfdx/sfdx-config.json.\n"
                f"  Enter alias (or press Enter to use sentinel "
                f"{ALIAS_SENTINEL}): "
            ).strip()
        except EOFError:
            user_input = ""
        if user_input:
            if not ALIAS_RE.match(user_input):
                raise SystemExit(f"✗ '{user_input}' is not a valid alias.")
            return user_input, "interactive prompt"

    return ALIAS_SENTINEL, "sentinel (no alias detected)"


def detect_org_name(cli_org_name: str | None) -> tuple[str, str]:
    """Return (org_name, source_descriptor).

    Unlike alias/Java/PMD, org name has no auto-detection path. It's a
    human-readable label that goes into prose, not a machine-detectable
    value. If the user didn't pass --org-name, fall back to ORG_NAME_DEFAULT
    so the substituted templates stay readable.
    """
    if cli_org_name:
        return cli_org_name, "--org-name flag"
    return ORG_NAME_DEFAULT, f"default ('{ORG_NAME_DEFAULT}' — no --org-name flag)"


def detect_java_home(cli_java_home: str | None) -> tuple[str, str]:
    """Return (java_home_path, source_descriptor)."""
    if cli_java_home:
        return cli_java_home, "--java-home flag"

    # macOS: java_home utility
    if sys.platform == "darwin":
        for version in ("21", "17", "11"):
            try:
                result = subprocess.run(
                    ["/usr/libexec/java_home", "-v", version],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    path = result.stdout.strip()
                    if path:
                        return path, f"/usr/libexec/java_home -v {version}"
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

    env_jh = os.environ.get("JAVA_HOME")
    if env_jh and Path(env_jh).is_dir():
        return env_jh, "$JAVA_HOME"

    # Linux glob
    if sys.platform.startswith("linux"):
        candidates = []
        for pat in ("/usr/lib/jvm/java-21-*", "/usr/lib/jvm/java-17-*",
                    "/usr/lib/jvm/java-11-*", "/usr/lib/jvm/default-java"):
            from glob import glob
            candidates.extend(sorted(glob(pat), reverse=True))
        for c in candidates:
            if Path(c).is_dir():
                return c, f"glob match: {c}"

    # Windows: derive from `where java`
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["where", "java"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                first_line = result.stdout.strip().splitlines()[0]
                # Strip trailing \bin\java.exe to get JAVA_HOME
                jh = Path(first_line).parent.parent
                if jh.is_dir():
                    return str(jh), "`where java` parent"
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    return JAVA_SENTINEL, "sentinel (no JDK detected)"


def detect_pmd_path(cli_pmd_path: str | None) -> tuple[str, str]:
    """Return (pmd_absolute_path, source_descriptor).

    Returns the FULL absolute path to the pmd binary, NOT just `pmd`. This is
    intentional — bakes the path into rule examples so users on Windows
    without PATH-edit access still get a working command.
    """
    if cli_pmd_path:
        return cli_pmd_path, "--pmd-path flag"

    # which/where
    found = shutil.which("pmd")
    if found:
        return found, "shutil.which('pmd')"

    if IS_WINDOWS:
        candidates = [
            r"C:\pmd\bin\pmd.bat",
            r"C:\Program Files\pmd\bin\pmd.bat",
        ]
        # %USERPROFILE%\pmd-bin-*\bin\pmd.bat
        from glob import glob
        userprof = os.environ.get("USERPROFILE", "")
        if userprof:
            candidates.extend(sorted(glob(os.path.join(
                userprof, "pmd-bin-*", "bin", "pmd.bat")), reverse=True))
    else:
        candidates = [
            "/opt/homebrew/bin/pmd",
            "/usr/local/bin/pmd",
            "/usr/bin/pmd",
        ]
        from glob import glob
        home = os.environ.get("HOME", "")
        if home:
            candidates.extend(sorted(glob(os.path.join(
                home, "pmd-bin-*", "bin", "pmd")), reverse=True))

    for c in candidates:
        if Path(c).exists():
            return c, f"probed path: {c}"

    pmd_home = os.environ.get("PMD_HOME")
    if pmd_home:
        bin_name = "pmd.bat" if IS_WINDOWS else "pmd"
        candidate = Path(pmd_home) / "bin" / bin_name
        if candidate.exists():
            return str(candidate), "$PMD_HOME"

    return PMD_SENTINEL, "sentinel (no PMD detected)"


# ────────────────────────────────────────────────────────────────────────────
# Substitution helpers
# ────────────────────────────────────────────────────────────────────────────


def substitute_text(content: str, *, alias: str, org_name: str, pmd_path: str,
                    java_home: str, workspace_path: str) -> str:
    """Replace {{...}} placeholders with detected runtime values.

    The placeholders only appear in templates/ files where the relevant
    value belongs (e.g. {{JAVA_HOME}} only in .vscode/settings.json,
    {{WORKSPACE_PATH}} only in the two MCP configs — .mcp.json and
    .cursor/mcp.json — which share the same content), so unconditional
    global replacement is safe — nothing else collides with the {{...}}
    syntax.
    """
    out = content
    out = out.replace(TOKEN_ORG_ALIAS, alias)
    out = out.replace(TOKEN_ORG_NAME, org_name)
    out = out.replace(TOKEN_JAVA_HOME, java_home)
    out = out.replace(TOKEN_PMD_PATH, pmd_path)
    out = out.replace(TOKEN_WORKSPACE, workspace_path)
    return out


def is_text_file(rel: Path) -> bool:
    """Heuristic: files whose contents we should string-substitute."""
    return rel.suffix.lower() in {
        ".md", ".mdc", ".json", ".xml", ".txt", ".yml", ".yaml",
    }


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target_dir", nargs="?", default=os.getcwd(),
                        help="Directory to write into (default: current working dir).")
    parser.add_argument("--alias", help="Override target-org alias detection.")
    parser.add_argument("--org-name", dest="org_name",
                        help="Human-readable project / org name (e.g. 'Acme Health'). "
                             f"Substituted for {{{{ORG_NAME}}}} placeholders in rules / "
                             f"docs. Default: '{ORG_NAME_DEFAULT}'.")
    parser.add_argument("--java-home", dest="java_home",
                        help="Override Java home detection.")
    parser.add_argument("--pmd-path", dest="pmd_path",
                        help="Override PMD binary path detection.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files (default: skip).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written; do not touch the filesystem.")
    parser.add_argument("--no-prompt", action="store_true",
                        help="Never prompt interactively.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    templates_dir = script_dir / "templates"
    target = Path(args.target_dir).resolve()

    if not templates_dir.is_dir():
        raise SystemExit(
            f"✗ templates/ folder not found at {templates_dir}. "
            f"If you're the source-repo maintainer (the one running _sync.py), "
            f"run `python3 _sync.py` to populate it."
        )

    # Validate target dir.
    if not target.exists():
        if args.dry_run:
            print(f"  (dry-run) would create target dir: {target}")
        else:
            target.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"init.py — bootstrapping AI-agent rules in:")
    print(f"          {target}")
    print("=" * 72)

    # Detect everything up front so the user sees what's about to be substituted.
    alias, alias_src = detect_alias(target, args.alias, prompt_ok=not args.no_prompt)
    org_name, org_name_src = detect_org_name(args.org_name)
    java_home, java_src = detect_java_home(args.java_home)
    pmd_path, pmd_src = detect_pmd_path(args.pmd_path)
    workspace_path = str(target)

    print()
    print(f"  Alias:       {alias}    ({alias_src})")
    print(f"  Org name:    {org_name}    ({org_name_src})")
    print(f"  Java home:   {java_home}    ({java_src})")
    print(f"  PMD path:    {pmd_path}    ({pmd_src})")
    print(f"  Workspace:   {workspace_path}    (used for {{{{WORKSPACE_PATH}}}} in .mcp.json)")
    print()

    # Walk templates/ and write each file.
    template_files = sorted(p for p in templates_dir.rglob("*") if p.is_file())
    written = skipped = errors = 0

    for tpl in template_files:
        rel = tpl.relative_to(templates_dir)
        dst = target / rel

        try:
            if is_text_file(rel):
                content = tpl.read_text(encoding="utf-8")
                content = substitute_text(
                    content,
                    alias=alias,
                    org_name=org_name,
                    pmd_path=pmd_path,
                    java_home=java_home,
                    workspace_path=workspace_path,
                )
                new_bytes = content.encode("utf-8")
            else:
                new_bytes = tpl.read_bytes()

            exists = dst.exists()
            if exists and not args.force:
                print(f"  · skip (exists): {rel.as_posix()}")
                skipped += 1
                continue

            if args.dry_run:
                verb = "would overwrite" if exists else "would write"
                print(f"  · {verb}:        {rel.as_posix()}")
                written += 1
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(new_bytes)
            verb = "overwrote" if exists else "wrote"
            print(f"  ✓ {verb}:           {rel.as_posix()}")
            written += 1
        except Exception as e:
            print(f"  ✗ FAILED {rel.as_posix()}: {e}")
            errors += 1

    print()
    print("=" * 72)
    summary = f"Summary: {written} written, {skipped} skipped, {errors} errors"
    if args.dry_run:
        summary = "DRY RUN: " + summary
    print(summary)

    sentinels_used = []
    if alias == ALIAS_SENTINEL:
        sentinels_used.append(ALIAS_SENTINEL)
    if java_home == JAVA_SENTINEL:
        sentinels_used.append(JAVA_SENTINEL)
    if pmd_path == PMD_SENTINEL:
        sentinels_used.append(PMD_SENTINEL)

    if sentinels_used:
        print()
        print("  ⚠ The following sentinel(s) were left in place because")
        print("    detection failed. Replace them manually before relying")
        print("    on AI-agent rules that reference them:")
        for s in sentinels_used:
            print(f"      - {s}")
        print()
        if ALIAS_SENTINEL in sentinels_used:
            print("    Set the alias by running, in the target dir:")
            print("      sf config set target-org=<your-alias>")
            print(f"    Then re-run init.py with --force to refresh.")

    if org_name == ORG_NAME_DEFAULT:
        print()
        print(f"  ℹ Org name was not supplied; '{ORG_NAME_DEFAULT}' was substituted")
        print(f"    into all {{{{ORG_NAME}}}} placeholders. To customise, re-run with:")
        print(f"      python3 init.py --org-name 'Your Project Name' --force")
        print(f"    Or fix in place after the fact:")
        print(f"      grep -rl '{ORG_NAME_DEFAULT}' .cursor .claude docs changes/_templates")

    print()
    if errors:
        return 1
    print(f"  Next: open `.cursor/rules/sf-cli-commands.mdc` to see the canonical sf CLI reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
