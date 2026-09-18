#!/usr/bin/env python3
"""
init.py — Bootstrap a Salesforce repo with the AI-agent rule/skill kit.

Reads the bundled `templates/` folder (sibling of this script) and writes
each file into a target directory, replacing six placeholder tokens:

  • {{ORG_ALIAS}}        → the workspace's target-org alias (sf CLI alias)
  • {{ORG_NAME}}         → human-readable project / org name (e.g. "Acme Health")
                            — defaults to "CURR ORG" if --org-name not passed
  • {{JAVA_HOME}}        → detected JDK home (used in .vscode/settings.json)
  • {{PMD_PATH}}         → detected PMD binary absolute path
  • {{WORKSPACE_PATH}}   → target dir absolute path (used in MCP + sandbox config)
  • {{HOME_PATH}}        → the current user's home dir (used in .cursor/sandbox.json)

The placeholders are baked into templates/ ahead of time by the
maintainer; end users never see the original literal values, so nothing
personal or org-specific leaks through the kit.

Detection strategy:
  - Alias reads `<target>/.sf/config.json` first, falls back to
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
    --api-version VER    Skip sfdx-project.json detection; use VER (e.g. "66.0").
    --force              Overwrite all managed files (default: fail on differing collision).
                         Merged files (.gitignore, .vscode/settings.json) are still
                         merged, not replaced — see --replace-merged.
    --replace-merged     Replace .gitignore and .vscode/settings.json with the kit
                         version instead of merging into them. DESTRUCTIVE: discards
                         project-specific ignore rules and editor settings.
    --replace-seeded     Reset the seed-once scaffolds (org-data-model.mdc,
                         org-conventions.md) to the kit's blank version.
                         DESTRUCTIVE: discards your documented data model.
    --reset              Restore the target to pristine kit state. Shorthand for
                         --force --replace-merged --replace-seeded.
    --update             Stage safe merge candidates for an existing customized kit.
    --ignore-conflicts   Install missing files and leave conflicting files unchanged.
    --missing-only       Backward-compatible alias for --ignore-conflicts.
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
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# ────────────────────────────────────────────────────────────────────────────
# Placeholder tokens (baked into templates/ ahead of time by the
# maintainer) and the sentinel values that get used if runtime detection
# fails.
#
# This script does NOT carry any source-repo-specific literals — every
# personal / org-specific value lived in the maintainer's source files but
# was tokenized away into `{{...}}` placeholders before reaching
# templates/, so what ships to colleagues is fully generic.
# ────────────────────────────────────────────────────────────────────────────

# Placeholder tokens that appear in templates/ files.
TOKEN_ORG_ALIAS = "{{ORG_ALIAS}}"
TOKEN_ORG_NAME = "{{ORG_NAME}}"
TOKEN_JAVA_HOME = "{{JAVA_HOME}}"
TOKEN_PMD_PATH = "{{PMD_PATH}}"
TOKEN_WORKSPACE = "{{WORKSPACE_PATH}}"
TOKEN_HOME = "{{HOME_PATH}}"
TOKEN_API_VERSION = "{{API_VERSION}}"

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
# No angle brackets: this sentinel lands inside <version> elements in the
# manifest XML, where "<...>" would open a tag and make the file unparseable.
API_VERSION_SENTINEL = "API_VERSION_UNSET"

ALIAS_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")  # Conservative: alphanumerics + . _ -
API_VERSION_RE = re.compile(r"^\d{2,3}\.0$")  # Salesforce shape: "66.0", "100.0"

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


def read_install_marker(target: Path) -> dict:
    """Return the target's install manifest, or {} when absent/unreadable."""
    marker = target / ".initagentrulespy-manifest.json"
    if not marker.is_file():
        return {}
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def detect_org_name(cli_org_name: str | None, target: Path | None = None) -> tuple[str, str]:
    """Return (org_name, source_descriptor).

    Org name is the one value with no machine-detectable source — it's a
    human-readable label for prose. So after the CLI flag we fall back to
    whatever a previous install recorded, which keeps re-runs (and --status
    / --verify-templates) consistent without re-passing the flag.
    """
    if cli_org_name:
        return cli_org_name, "--org-name flag"
    if target is not None:
        recorded = read_install_marker(target).get("substitutions", {}).get("org_name")
        if isinstance(recorded, str) and recorded and recorded != ORG_NAME_DEFAULT:
            return recorded, "previous install (.initagentrulespy-manifest.json)"
    return ORG_NAME_DEFAULT, f"default ('{ORG_NAME_DEFAULT}' — no --org-name flag)"


def recall_substitution(target: Path, key: str, detected: str, sentinel: str,
                        detected_source: str) -> tuple[str, str]:
    """Prefer a previous install's recorded value over a failed detection.

    Detection depends on the machine (JDK layout, PATH, sf config). A colleague
    whose probe fails should not be told their files are hand-edited, nor have a
    sentinel written over a value that worked yesterday.
    """
    if detected != sentinel:
        return detected, detected_source
    recorded = read_install_marker(target).get("substitutions", {}).get(key)
    if isinstance(recorded, str) and recorded and recorded != sentinel:
        return recorded, "previous install (.initagentrulespy-manifest.json)"
    return detected, detected_source


def detect_api_version(target: Path, cli_api_version: str | None) -> tuple[str, str]:
    """Return (api_version, source_descriptor).

    The target repo's sfdx-project.json is authoritative: manifests and REST
    paths written by this kit must match the API version the project already
    builds against, otherwise deploys silently target a different version.
    """
    if cli_api_version:
        if not API_VERSION_RE.match(cli_api_version):
            raise SystemExit(f"✗ --api-version '{cli_api_version}' is not a valid "
                             f"Salesforce API version (expected e.g. '66.0')")
        return cli_api_version, "--api-version flag"

    project_json = target / "sfdx-project.json"
    if project_json.is_file():
        try:
            data = json.loads(project_json.read_text(encoding="utf-8"))
            found = data.get("sourceApiVersion")
            if isinstance(found, str) and API_VERSION_RE.match(found):
                return found, "sfdx-project.json sourceApiVersion"
        except (json.JSONDecodeError, OSError):
            pass

    return API_VERSION_SENTINEL, "sentinel (no sourceApiVersion detected)"


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
                    java_home: str, workspace_path: str, home_path: str,
                    api_version: str, json_escape: bool = False) -> str:
    """Replace {{...}} placeholders with detected runtime values.

    The placeholders only appear in templates/ files where the relevant
    value belongs (e.g. {{JAVA_HOME}} only in .vscode/settings.json,
    {{WORKSPACE_PATH}} in the two MCP configs plus .cursor/sandbox.json,
    and {{HOME_PATH}} only in .cursor/sandbox.json), so unconditional global
    replacement is safe — nothing else collides with the {{...}} syntax.
    """
    def rendered(value: str) -> str:
        return json.dumps(value)[1:-1] if json_escape else value

    out = content
    out = out.replace(TOKEN_ORG_ALIAS, rendered(alias))
    out = out.replace(TOKEN_ORG_NAME, rendered(org_name))
    out = out.replace(TOKEN_JAVA_HOME, rendered(java_home))
    out = out.replace(TOKEN_PMD_PATH, rendered(pmd_path))
    out = out.replace(TOKEN_WORKSPACE, rendered(workspace_path))
    out = out.replace(TOKEN_HOME, rendered(home_path))
    out = out.replace(TOKEN_API_VERSION, rendered(api_version))
    return out


# OS and tooling droppings that appear inside templates/ without anyone adding
# them. They are gitignored, so they never show up in a diff or a review — but
# the walk below is filesystem-based, not git-based, so without this filter they
# would be materialized into every bootstrapped project and counted as kit files.
TEMPLATE_JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
TEMPLATE_JUNK_DIRS = frozenset({"__pycache__", ".pytest_cache", ".ipynb_checkpoints"})


def iter_template_files(templates_dir: Path):
    """Every real template file, in a stable order, junk excluded.

    Single source of truth for the walk so the materializer, the leak gate, and
    the drift report can never disagree about what the kit contains.
    """
    for path in sorted(templates_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(templates_dir)
        if rel.name in TEMPLATE_JUNK_NAMES:
            continue
        if TEMPLATE_JUNK_DIRS.intersection(rel.parts):
            continue
        if rel.suffix == ".pyc":
            continue
        yield path


def is_text_file(rel: Path) -> bool:
    """Heuristic: files whose contents we should string-substitute.

    Shell scripts are deliberately absent: they ship byte-identical, reading
    their org alias from the environment and everything else from the run's
    generated files, so there is nothing in them to substitute.
    """
    return rel.suffix.lower() in {
        ".md", ".mdc", ".json", ".xml", ".txt", ".yml", ".yaml",
    }


# Suffixes whose files must land executable. Matched on suffix rather than an
# enumerated path list so a newly shipped script needs no code change here.
EXECUTABLE_SUFFIXES = frozenset({".sh"})


def desired_mode(rel: Path) -> int | None:
    """Permission bits a materialized file must end up with, or None for default."""
    return 0o755 if rel.suffix.lower() in EXECUTABLE_SUFFIXES else None


def is_managed_target_path(rel: Path) -> bool:
    """The bootstrapper never installs, updates, or removes target scripts."""
    return bool(rel.parts) and rel.parts[0] != "scripts"


# Files the kit ships as an empty scaffold for the project to fill in with its
# own content. They are installed when absent, but NEVER overwritten or deleted
# afterwards — not even by --force — because the target's version is the real
# work and the kit's is a placeholder. Without this, re-materializing after a
# rule edit would silently destroy a project's documented data model.
SEED_ONCE_PATHS = frozenset({
    Path(".cursor/rules/org-data-model.mdc"),
    Path("docs/omnistudio/org-conventions.md"),
})


def is_seed_once(rel: Path) -> bool:
    """True when the target's copy outranks the kit's and must be preserved.

    Consulted on BOTH mutation paths — the overwrite path and the obsolete-file
    tombstone path. Missing the second one would mean that dropping the stub
    from a future kit release silently deletes every project's filled-in copy.
    """
    return rel in SEED_ONCE_PATHS


# Merged property-by-property into the user's existing file rather than
# overwritten, so the target legitimately carries content the template does
# not (their own settings, plus the commented-out previous values init.py
# leaves behind). Divergence here is by design, not drift.
MERGED_PATHS = frozenset({
    Path(".vscode/settings.json"),
    Path(".gitignore"),
})


# ────────────────────────────────────────────────────────────────────────────
# Leak gate
#
# templates/ is the single source of truth and gets shared verbatim, so it must
# never contain a value belonging to whichever project last edited it. This is
# what structurally replaces the old reverse-tokenizer: instead of teaching a
# tool to recognize one specific org's spelling (which silently stops matching
# the moment the kit moves), we assert that no absolute machine path and no
# derivable org value reaches templates/. A miss is a hard failure, not a silent
# write — and a check with nothing to look for fails rather than reporting clean.
#
# Its reach is bounded: it cannot know your org's object or component names.
# Those still have to be kept out of templates/ by hand.
# ────────────────────────────────────────────────────────────────────────────

# Class 1 — shapes that are machine-specific in ANY project. Safe to hardcode
# because they describe a filesystem layout, not an org's vocabulary.
LEAK_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("absolute POSIX home path", re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+")),
    ("absolute Windows user path", re.compile(r"[A-Za-z]:\\+Users\\+[A-Za-z0-9._-]+")),
    ("absolute JDK path", re.compile(r"/(?:Library|usr/lib)/[A-Za-z0-9._/-]*"
                                     r"(?:jvm|JavaVirtualMachines)[A-Za-z0-9._/-]*")),
    ("absolute pmd binary path", re.compile(r"/[A-Za-z0-9._/-]+/bin/pmd\b")),
)


def scan_for_leaks(
    templates_dir: Path, derived: dict[str, str] | None = None
) -> list[tuple[Path, int, str, str]]:
    """Return [(relative_path, line_number, leak_kind, offending_line)].

    Two classes of finding:

    Class 1 (LEAK_PATTERNS) — absolute machine paths, universally wrong in a
    shared kit.

    Class 2 (`derived`) — the literal values THIS project's tokens resolve to.
    Deriving the denylist from the live repo instead of declaring it is the
    whole point: a declared list only ever knows the vocabulary of whichever
    project wrote it down, and goes silently blind the moment the kit moves.
    Generic placeholders in examples (`MyScratch`, `v62.0`) are untouched
    because they are not this project's values.
    """
    findings: list[tuple[Path, int, str, str]] = []
    derived = derived or {}
    for path in iter_template_files(templates_dir):
        rel = path.relative_to(templates_dir)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            hit = next(
                (kind for kind, pattern in LEAK_PATTERNS if pattern.search(line)),
                None,
            )
            if hit is None:
                hit = next(
                    (f"this project's {label} ({value!r})"
                     for label, value in derived.items() if value and value in line),
                    None,
                )
            if hit is not None:
                findings.append((rel, lineno, hit, line.strip()))
    return findings


def run_verify_templates(templates_dir: Path, derived: dict[str, str]) -> int:
    print(f"Scanning {templates_dir} for org-specific leakage")
    print("=" * 72)

    # A check with no value silently matches nothing. Reporting "clean" in that
    # state is worse than reporting nothing at all, because the caller acts on
    # it — so an undetectable value is a hard failure, not a skipped check.
    disarmed = [label for label, value in derived.items() if not value]
    print("  Armed checks (absolute machine paths are always checked):")
    for label, value in derived.items():
        state = value if value else "— NOT DETECTED —"
        print(f"    {label:<12} {state}")
    print()

    if disarmed:
        print(f"  ✗ cannot verify: {len(disarmed)} check(s) have no value to look for")
        for label in disarmed:
            print(f"      {label}")
        print()
        print("  Run this from the project root, or supply the values explicitly:")
        print("    python3 init.py <project-root> --verify-templates \\")
        print("        --org-name '<Your Org>' --alias <alias> --api-version <nn.0>")
        return 1

    findings = scan_for_leaks(templates_dir, derived)
    if not findings:
        total = sum(1 for _ in iter_template_files(templates_dir))
        print(f"  ✓ {total} template file(s) clean — no org-specific values found")
        print("    (detects absolute machine paths and the derived values above;")
        print("     it cannot know your org's object or component names)")
        return 0
    for rel, lineno, kind, line in findings:
        print(f"  ✗ {rel.as_posix()}:{lineno}  [{kind}]")
        print(f"      {line}")
    print()
    print(f"  {len(findings)} leak(s). templates/ must stay org-agnostic — replace")
    print("  each value with a {{TOKEN}} that init.py substitutes at install time.")
    return 1


def run_status(templates_dir: Path, target: Path, rendered: list[tuple[Path, bytes]]) -> int:
    """Report template->target drift without writing anything."""
    print(f"Comparing generated files in {target}")
    print("=" * 72)
    missing: list[Path] = []
    edited: list[Path] = []
    for rel, new_bytes in rendered:
        dst = target / rel
        if not dst.exists():
            missing.append(rel)
        elif is_seed_once(rel) or rel in MERGED_PATHS:
            continue
        elif dst.read_bytes() != new_bytes:
            edited.append(rel)

    for rel in missing:
        print(f"  ✗ missing:     {rel.as_posix()}")
    for rel in edited:
        print(f"  ✗ hand-edited: {rel.as_posix()}")

    print()
    if not missing and not edited:
        print(f"  ✓ in sync — all {len(rendered)} generated file(s) match templates/")
        return 0
    print(f"  {len(missing)} missing, {len(edited)} differ from templates/.")
    print("  Generated files are OUTPUT: edit the matching file under")
    print(f"  {templates_dir} and re-run with --force to regenerate.")
    print()
    print("  Before doing that, check the substitution values printed above. A")
    print("  value this run failed to detect (or an --org-name you didn't pass)")
    print("  produces the same report as a real hand-edit — and regenerating")
    print("  would then bake the wrong value in. Fix the value first.")
    return 1


@dataclass(frozen=True)
class JsoncProperty:
    key: str
    block_start: int
    key_start: int
    value_start: int
    value_end: int
    comma_index: int | None
    block_end: int


def skip_jsonc_string(content: str, start: int) -> int:
    index = start + 1
    while index < len(content):
        if content[index] == "\\":
            index += 2
        elif content[index] == '"':
            return index + 1
        else:
            index += 1
    raise ValueError("Unterminated string in .vscode/settings.json")


def skip_jsonc_comment(content: str, start: int) -> int:
    if content.startswith("//", start):
        newline = content.find("\n", start + 2)
        return len(content) if newline == -1 else newline + 1
    if content.startswith("/*", start):
        end = content.find("*/", start + 2)
        if end == -1:
            raise ValueError("Unterminated comment in .vscode/settings.json")
        return end + 2
    return start


def skip_jsonc_trivia(content: str, start: int) -> int:
    index = start
    while index < len(content):
        if content[index].isspace():
            index += 1
            continue
        comment_end = skip_jsonc_comment(content, index)
        if comment_end != index:
            index = comment_end
            continue
        break
    return index


def jsonc_property_tail_end(content: str, start: int) -> int:
    """Include an inline comment/newline without consuming the next property."""
    index = start
    while index < len(content) and content[index] in " \t\r":
        index += 1
    comment_end = skip_jsonc_comment(content, index)
    if comment_end != index:
        index = comment_end
    if index < len(content) and content[index] == "\n":
        index += 1
    return index


def parse_jsonc_properties(
    content: str,
) -> tuple[int, int, list[JsoncProperty]]:
    index = 1 if content.startswith("\ufeff") else 0
    index = skip_jsonc_trivia(content, index)
    if index >= len(content) or content[index] != "{":
        raise ValueError(".vscode/settings.json must contain a top-level object")
    object_start = index
    index += 1
    properties: list[JsoncProperty] = []

    while True:
        index = skip_jsonc_trivia(content, index)
        if index >= len(content):
            raise ValueError("Unterminated object in .vscode/settings.json")
        if content[index] == "}":
            return object_start, index, properties
        if content[index] != '"':
            raise ValueError(
                f"Expected a quoted setting name near character {index}"
            )

        key_start = index
        key_end = skip_jsonc_string(content, key_start)
        key = json.loads(content[key_start:key_end])
        colon = skip_jsonc_trivia(content, key_end)
        if colon >= len(content) or content[colon] != ":":
            raise ValueError(f"Expected ':' after setting {key!r}")
        value_start = skip_jsonc_trivia(content, colon + 1)

        cursor = value_start
        nested_depth = 0
        value_end = value_start
        comma_index: int | None = None
        while cursor < len(content):
            char = content[cursor]
            if char == '"':
                cursor = skip_jsonc_string(content, cursor)
                value_end = cursor
                continue
            comment_end = skip_jsonc_comment(content, cursor)
            if comment_end != cursor:
                cursor = comment_end
                continue
            if char in "[{":
                nested_depth += 1
                value_end = cursor + 1
            elif char in "]}":
                if char == "}" and nested_depth == 0:
                    break
                nested_depth -= 1
                if nested_depth < 0:
                    raise ValueError(
                        f"Unbalanced value for setting {key!r}"
                    )
                value_end = cursor + 1
            elif char == "," and nested_depth == 0:
                comma_index = cursor
                break
            elif not char.isspace():
                value_end = cursor + 1
            cursor += 1
        else:
            raise ValueError(f"Unterminated value for setting {key!r}")

        line_start = content.rfind("\n", 0, key_start) + 1
        block_start = (
            line_start
            if not content[line_start:key_start].strip()
            else key_start
        )
        tail_start = (
            comma_index + 1 if comma_index is not None else value_end
        )
        block_end = jsonc_property_tail_end(content, tail_start)
        properties.append(
            JsoncProperty(
                key=key,
                block_start=block_start,
                key_start=key_start,
                value_start=value_start,
                value_end=value_end,
                comma_index=comma_index,
                block_end=block_end,
            )
        )
        index = comma_index + 1 if comma_index is not None else cursor


def compact_jsonc(content: str) -> str:
    """Remove JSONC whitespace/comments while preserving string contents."""
    output: list[str] = []
    index = 0
    while index < len(content):
        if content[index] == '"':
            end = skip_jsonc_string(content, index)
            output.append(content[index:end])
            index = end
            continue
        comment_end = skip_jsonc_comment(content, index)
        if comment_end != index:
            index = comment_end
            continue
        if not content[index].isspace():
            output.append(content[index])
        index += 1
    return "".join(output)


def jsonc_property_block(
    content: str, prop: JsoncProperty, *, comma: bool
) -> str:
    prefix = content[prop.block_start:prop.value_end]
    if prop.comma_index is None:
        suffix = content[prop.value_end:prop.block_end]
    else:
        suffix = (
            content[prop.value_end:prop.comma_index]
            + content[prop.comma_index + 1:prop.block_end]
        )
    return prefix + ("," if comma else "") + suffix


def reindent_jsonc_block(
    block: str, source_indent: str, target_indent: str
) -> str:
    output: list[str] = []
    for line in block.splitlines(keepends=True):
        if line.startswith(source_indent):
            output.append(target_indent + line[len(source_indent):])
        elif line.strip():
            output.append(target_indent + line.lstrip())
        else:
            output.append(line)
    return "".join(output)


def comment_jsonc_block(block: str, indent: str) -> str:
    output: list[str] = []
    for line in block.rstrip("\n").splitlines():
        relative = line[len(indent):] if line.startswith(indent) else line.lstrip()
        output.append(f"{indent}// {relative.rstrip()}\n")
    return "".join(output)


def _gitignore_key(pattern: str) -> str:
    """Normalized form used only to decide 'is this pattern already ignored?'.

    A trailing slash changes git's meaning (directory-only), but `.sf-ops` and
    `.sf-ops/` in one file is noise rather than a second rule — so they compare
    equal here and we leave whichever the project already had.
    """
    return pattern.strip().rstrip("/")


def merge_gitignore(existing: str, template: str) -> str:
    """Append the kit's missing ignore rules, preserving everything already there.

    Purely additive. A project's own entries, ordering, and comments are never
    rewritten or reordered — we only append the template blocks whose patterns
    are absent, each still carrying its explanatory comment. Idempotent: a
    second run finds every pattern present and changes nothing.
    """
    if not existing.strip():
        return template

    have = {
        _gitignore_key(line)
        for line in existing.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    additions: list[str] = []
    comments: list[str] = []
    patterns: list[str] = []

    def flush() -> None:
        # A block is worth appending only if it carries a pattern we lack;
        # otherwise its comment would land with nothing under it.
        if patterns:
            additions.extend(comments + patterns)
            additions.append("")
        comments.clear()
        patterns.clear()

    for raw in template.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("#"):
            if patterns:
                flush()
            comments.append(raw)
        elif _gitignore_key(line) not in have:
            patterns.append(raw)
    flush()

    if not additions:
        return existing

    body = existing if existing.endswith("\n") else existing + "\n"
    return body + "\n" + "\n".join(additions).rstrip("\n") + "\n"


def merge_vscode_settings(existing: str, template: str) -> str:
    """Merge top-level JSONC settings, preserving previous values as comments."""
    _, _, template_properties = parse_jsonc_properties(template)
    _, _, existing_properties = parse_jsonc_properties(existing)
    existing_by_key = {prop.key: prop for prop in existing_properties}
    replacements: list[tuple[int, int, str]] = []
    missing: list[JsoncProperty] = []

    for template_prop in template_properties:
        existing_prop = existing_by_key.get(template_prop.key)
        if existing_prop is None:
            missing.append(template_prop)
            continue
        old_value = compact_jsonc(
            existing[existing_prop.value_start:existing_prop.value_end]
        )
        new_value = compact_jsonc(
            template[template_prop.value_start:template_prop.value_end]
        )
        if old_value == new_value:
            continue

        target_indent = existing[
            existing_prop.block_start:existing_prop.key_start
        ]
        source_indent = template[
            template_prop.block_start:template_prop.key_start
        ]
        new_block = jsonc_property_block(
            template,
            template_prop,
            comma=existing_prop.comma_index is not None,
        )
        new_block = reindent_jsonc_block(
            new_block, source_indent, target_indent
        )
        old_block = existing[
            existing_prop.block_start:existing_prop.block_end
        ]
        replacement = (
            f"{target_indent}// Previous value before initagentrulespy:\n"
            + comment_jsonc_block(old_block, target_indent)
            + new_block
        )
        replacements.append(
            (existing_prop.block_start, existing_prop.block_end, replacement)
        )

    merged = existing
    for start, end, replacement in sorted(replacements, reverse=True):
        merged = merged[:start] + replacement + merged[end:]

    if not missing:
        return merged

    _, object_end, merged_properties = parse_jsonc_properties(merged)
    if merged_properties:
        last = merged_properties[-1]
        last_block = jsonc_property_block(merged, last, comma=True)
        merged = (
            merged[:last.block_start]
            + last_block
            + merged[last.block_end:]
        )
        _, object_end, merged_properties = parse_jsonc_properties(merged)

    if merged_properties:
        first = merged_properties[0]
        target_indent = merged[first.block_start:first.key_start]
    else:
        target_indent = "  "

    additions = [
        f"{target_indent}// Added by initagentrulespy\n"
    ]
    for index, template_prop in enumerate(missing):
        source_indent = template[
            template_prop.block_start:template_prop.key_start
        ]
        block = jsonc_property_block(
            template,
            template_prop,
            comma=index < len(missing) - 1,
        )
        block = reindent_jsonc_block(
            block, source_indent, target_indent
        )
        if not block.endswith("\n"):
            block += "\n"
        additions.append(block)

    prefix = merged[:object_end].rstrip()
    separator = "\n" if prefix.endswith("{") else "\n\n"
    return (
        prefix
        + separator
        + "".join(additions)
        + merged[object_end:]
    )


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def backup_slot(transaction: Path, rel: Path) -> Path:
    """Where the rollback journal stores the prior contents of one target file.

    Flat and percent-encoded rather than mirroring the target's directory tree.
    Mirroring would recreate `.cursor/` and `.claude/` inside the journal, and
    some sandboxed environments — including Cursor's own agent sandbox — refuse
    to create directories with those names anywhere. That made `--force`
    unusable in the very repo that maintains this kit.
    """
    return transaction / "backup" / quote(rel.as_posix(), safe="")


def durable_unlink(path: Path) -> None:
    parent = path.parent
    path.unlink(missing_ok=True)
    fsync_directory(parent)


def durable_rmtree(path: Path) -> None:
    parent = path.parent
    shutil.rmtree(path)
    fsync_directory(parent)


def prune_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        fsync_directory(current.parent)
        current = current.parent


def assert_safe_target_paths(target: Path, paths: list[Path]) -> None:
    root = target.resolve()
    for rel in paths:
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe target-relative path: {rel}")
        current = target
        for part in rel.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError(f"Symlinked managed path is prohibited: {current}")
        try:
            current.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError(f"Managed path escapes target: {rel}") from error


def target_state(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(f"Symlinked managed path is prohibited: {path}")
    if not path.exists():
        return "missing"
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    raise ValueError(f"Unsupported managed path type: {path}")


def file_matches(path: Path, expected: bytes) -> bool:
    return target_state(path) == "file" and path.read_bytes() == expected


def target_shape_conflict(target: Path, rel: Path) -> Path | None:
    """Return the existing path that blocks a generated file, if any."""
    current = target
    for index, part in enumerate(rel.parts):
        current = current / part
        if not current.exists():
            return None
        if current.is_symlink():
            raise ValueError(f"Symlinked managed path is prohibited: {current}")
        is_leaf = index == len(rel.parts) - 1
        if not is_leaf and not current.is_dir():
            return Path(*rel.parts[: index + 1])
        if is_leaf and not current.is_file():
            return rel
    return None


def atomic_write(path: Path, content: bytes, mode: int | None = None) -> None:
    """Write one file atomically (temp sibling + os.replace).

    `mode` is applied to the temp file BEFORE the replace, so the visible path
    never exists with the wrong permissions — a script is never briefly
    non-executable at the moment another process might pick it up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.initagentrulespy.{os.getpid()}.tmp")
    try:
        with temp.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
        fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def enforce_modes(target: Path, rels) -> list[Path]:
    """Bring managed files to their required permissions; return what changed.

    Runs over every managed path, not just the ones written, because a file whose
    content already matched is skipped by the write planner — so a script that
    lost its executable bit (a zip round-trip, a copy through a filesystem
    without mode support, a stray chmod) would otherwise never be repaired.
    Mode is not content, so applying it outside the content transaction is safe
    and idempotent.
    """
    repaired: list[Path] = []
    for rel in rels:
        mode = desired_mode(rel)
        if mode is None:
            continue
        path = target / rel
        if not path.is_file() or path.is_symlink():
            continue
        if (path.stat().st_mode & 0o777) != mode:
            os.chmod(path, mode)
            repaired.append(rel)
    return repaired


def acquire_target_lock(target: Path) -> tuple[int, Path, str]:
    """Prevent concurrent init runs from interleaving different substitutions."""
    lock_path = target / ".initagentrulespy.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        owner = lock_path.read_text(encoding="utf-8", errors="replace").strip()
        raise SystemExit(
            f"✗ Another initagentrulespy run holds {lock_path}"
            + (f" ({owner})" if owner else "")
            + ". If no process is running, remove the stale lock and retry."
        )
    token = str(uuid.uuid4())
    os.write(fd, f"pid={os.getpid()}\ntoken={token}\n".encode("utf-8"))
    return fd, lock_path, token


def release_target_lock(fd: int, lock_path: Path, token: str) -> None:
    os.close(fd)
    if not lock_path.exists() or f"token={token}" not in lock_path.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise RuntimeError("Target lock ownership changed; refusing to unlink it")
    durable_unlink(lock_path)


def recover_incomplete_transactions(target: Path) -> None:
    """Restore any prepared transaction left by interruption/power loss."""
    parent = target / ".initagentrulespy-transactions"
    if not parent.exists():
        return
    for transaction in sorted(p for p in parent.iterdir() if p.is_dir()):
        manifest_path = transaction / "manifest.json"
        if not manifest_path.exists():
            shutil.rmtree(transaction)
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert_safe_target_paths(
            target, [Path(item["path"]) for item in manifest.get("files", [])]
        )
        if manifest.get("state") == "prepared":
            print(f"  ⚠ recovering interrupted transaction {transaction.name}")
            conflicts = []
            for item in reversed(manifest["files"]):
                dst = target / item["path"]
                current_state = target_state(dst)
                baseline_state = item.get(
                    "baseline_state", "file" if item["existed"] else "missing"
                )
                intended_state = item.get("intended_state", "missing")
                allowed_states = {baseline_state, intended_state}
                if {baseline_state, intended_state} == {"file", "directory"}:
                    allowed_states.add("missing")
                if current_state not in allowed_states:
                    conflicts.append(item["path"])
                    continue
                if item["existed"]:
                    if dst.is_dir():
                        prune_empty_parents(dst, target)
                    atomic_write(
                        dst,
                        backup_slot(transaction, Path(item["path"])).read_bytes(),
                    )
                else:
                    if dst.is_file():
                        durable_unlink(dst)
                        prune_empty_parents(dst.parent, target)
                    elif dst.is_dir() and current_state != "directory":
                        prune_empty_parents(dst, target)
            if conflicts:
                raise RuntimeError(
                    "Recovery conflict (transaction preserved): "
                    + ", ".join(conflicts)
                )
        durable_rmtree(transaction)
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        fsync_directory(parent.parent)


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
    parser.add_argument("--api-version", dest="api_version",
                        help="Override Salesforce API version detection "
                             "(default: sourceApiVersion from the target's "
                             "sfdx-project.json). Example: 66.0")
    parser.add_argument("--verify-templates", action="store_true",
                        help="Scan templates/ for org-specific leakage and exit. "
                             "Writes nothing, but DOES read target_dir to derive "
                             "this project's live values — run it from the project "
                             "root, or pass --alias / --org-name / --api-version.")
    parser.add_argument("--status", action="store_true",
                        help="Report which generated files are missing or "
                             "hand-edited relative to templates/, then exit. "
                             "Writes nothing.")
    parser.add_argument("--replace-merged", action="store_true",
                        dest="replace_merged",
                        help="Replace the merged files (.gitignore, "
                             ".vscode/settings.json) with the kit version instead of "
                             "merging into them. DESTRUCTIVE — discards project-specific "
                             "ignore rules and editor settings. Combine with --force to "
                             "actually write them; on its own an existing differing file "
                             "is still reported as a conflict.")
    parser.add_argument("--replace-seeded", action="store_true",
                        dest="replace_seeded",
                        help="Reset the seed-once scaffolds (.cursor/rules/"
                             "org-data-model.mdc, docs/omnistudio/org-conventions.md) "
                             "to the kit's blank version. DESTRUCTIVE — discards your "
                             "documented data model. Combine with --force to write.")
    parser.add_argument("--reset", action="store_true",
                        help="Restore the target to pristine kit state. Shorthand for "
                             "--force --replace-merged --replace-seeded. DESTRUCTIVE — "
                             "discards local edits to managed files, your .gitignore "
                             "and editor settings, and your filled-in data model.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite all managed files (default: fail on differing collisions).")
    parser.add_argument("--update", action="store_true",
                        help="Safely stage changed/new kit files under "
                             ".initagentrulespy-updates/<generation>/ when existing files differ; "
                             "never overwrite customized targets.")
    parser.add_argument("--ignore-conflicts", "--missing-only",
                        dest="ignore_conflicts", action="store_true",
                        help="Install missing files directly in the target, leave "
                             "conflicting existing files unchanged, and list those "
                             "conflicts at the end.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written; do not touch the filesystem.")
    parser.add_argument("--no-prompt", action="store_true",
                        help="Never prompt interactively.")
    args = parser.parse_args()

    # --reset is shorthand, not a fourth mode: expand it before the mutual-
    # exclusivity check so the messages below stay accurate. Checked against the
    # staging modes first, otherwise the user is told "--force conflicts with
    # --update" about a flag they never typed.
    if args.reset and (args.update or args.ignore_conflicts):
        parser.error(
            "--reset implies --force, so it cannot be combined with "
            "--update or --ignore-conflicts"
        )
    if args.reset:
        args.force = True
        args.replace_merged = True
        args.replace_seeded = True

    if sum(bool(flag) for flag in (args.force, args.update, args.ignore_conflicts)) > 1:
        parser.error(
            "--force, --update, and --ignore-conflicts are mutually exclusive"
        )

    script_dir = Path(__file__).resolve().parent
    templates_dir = script_dir / "templates"
    target = Path(args.target_dir).resolve()

    if not templates_dir.is_dir():
        raise SystemExit(
            f"✗ templates/ folder not found at {templates_dir}. "
            f"Make sure you copied the whole `initagentrulespy/` folder "
            f"(both init.py AND the sibling templates/ directory), not just "
            f"init.py on its own."
        )

    if args.verify_templates:
        # Derive the denylist from whatever this repo actually uses, so the gate
        # never needs to be told a project's vocabulary.
        probe_alias, _ = detect_alias(target, args.alias, prompt_ok=False)
        probe_org_name, _ = detect_org_name(args.org_name, target)
        probe_api, _ = detect_api_version(target, args.api_version)
        derived = {
            "org alias": "" if probe_alias == ALIAS_SENTINEL else probe_alias,
            "org name": "" if probe_org_name == ORG_NAME_DEFAULT else probe_org_name,
            "API version": "" if probe_api == API_VERSION_SENTINEL else probe_api,
            "workspace": str(target),
            "home": str(Path.home()),
        }
        return run_verify_templates(templates_dir, derived)

    # Read every bundled template directly. Older kits may still carry the
    # retired release-inventory file; it is metadata, not a target template.
    template_sources = []
    for path in iter_template_files(templates_dir):
        rel = path.relative_to(templates_dir)
        if (
            path.name == ".initagentrulespy-release.json"
            or not is_managed_target_path(rel)
        ):
            continue
        template_sources.append((rel, path.read_bytes()))

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
    org_name, org_name_src = detect_org_name(args.org_name, target)
    java_home, java_src = detect_java_home(args.java_home)
    java_home, java_src = recall_substitution(
        target, "java_home", java_home, JAVA_SENTINEL, java_src)
    pmd_path, pmd_src = detect_pmd_path(args.pmd_path)
    pmd_path, pmd_src = recall_substitution(
        target, "pmd_path", pmd_path, PMD_SENTINEL, pmd_src)
    api_version, api_version_src = detect_api_version(target, args.api_version)
    api_version, api_version_src = recall_substitution(
        target, "api_version", api_version, API_VERSION_SENTINEL, api_version_src)
    workspace_path = str(target)
    home_path = str(Path.home())

    print()
    print(f"  Alias:       {alias}    ({alias_src})")
    print(f"  Org name:    {org_name}    ({org_name_src})")
    print(f"  Java home:   {java_home}    ({java_src})")
    print(f"  PMD path:    {pmd_path}    ({pmd_src})")
    print(f"  API version: {api_version}    ({api_version_src})")
    print(
        f"  Workspace:   {workspace_path}    "
        f"(used for {{{{WORKSPACE_PATH}}}} in MCP + sandbox config)"
    )
    print(f"  Home:        {home_path}    (used for {{{{HOME_PATH}}}} in .cursor/sandbox.json)")
    print()

    # Render every file before mutating the target. This catches substitution /
    # read failures up front and gives update mode a complete comparison set.
    rendered: list[tuple[Path, bytes]] = []
    written = skipped = errors = update_conflicts = 0
    ignored_conflicts: list[Path] = []
    mergeable_existing: set[Path] = set()

    for rel, source_bytes in template_sources:
        try:
            if is_text_file(rel):
                content = source_bytes.decode("utf-8")
                content = substitute_text(
                    content,
                    alias=alias,
                    org_name=org_name,
                    pmd_path=pmd_path,
                    java_home=java_home,
                    workspace_path=workspace_path,
                    home_path=home_path,
                    api_version=api_version,
                    json_escape=rel.suffix.lower() == ".json",
                )
                rendered.append((rel, content.encode("utf-8")))
            else:
                rendered.append((rel, source_bytes))
        except Exception as e:
            print(f"  ✗ FAILED to render {rel.as_posix()}: {e}")
            errors += 1

    # Seed-once: where the target already has one of these, its content wins.
    # Swapping in the existing bytes (rather than dropping the entry) keeps the
    # file inside the managed set, so it neither registers as a conflict nor
    # gets tombstoned as obsolete on the next run.
    #
    # --replace-seeded opts out, restoring the kit's blank scaffold. That is the
    # only way back to a pristine target, so it exists — but it discards real
    # authored work (a filled-in data model is often the longest file in the
    # repo), which is why it is its own flag and announces every file it resets.
    preserved_seeds: list[Path] = []
    for index, (rel, _) in enumerate(rendered):
        if not is_seed_once(rel):
            continue
        existing = target / rel
        if not existing.is_file():
            continue
        if args.replace_seeded:
            print(f"  ⚠ --replace-seeded: {rel.as_posix()} will be RESET to the kit "
                  f"scaffold; your filled-in content is discarded")
            continue
        rendered[index] = (rel, existing.read_bytes())
        preserved_seeds.append(rel)

    if args.status:
        if errors:
            print(f"  ✗ {errors} template(s) failed to render; cannot report status")
            return 1
        return run_status(templates_dir, target, rendered)

    # A failed detection must never downgrade a value the target already has
    # working. Otherwise the documented `--force` re-materialize loop silently
    # replaces a real JDK/PMD path with a sentinel on any machine whose layout
    # the probes don't recognise.
    for token, value, sentinel, label in (
        (TOKEN_JAVA_HOME, java_home, JAVA_SENTINEL, "Java home"),
        (TOKEN_PMD_PATH, pmd_path, PMD_SENTINEL, "PMD path"),
    ):
        if value != sentinel:
            continue
        for index, (rel, new_bytes) in enumerate(rendered):
            if sentinel.encode("utf-8") not in new_bytes:
                continue
            dst = target / rel
            if not dst.is_file():
                continue
            existing = dst.read_bytes()
            if sentinel.encode("utf-8") in existing:
                continue
            rendered[index] = (rel, existing)
            print(f"  · kept existing {label} in {rel.as_posix()} "
                  f"(detection failed; refusing to overwrite a working value)")

    # --replace-merged opts out of merging entirely: the rendered template stays
    # as-is, so these files go through the normal conflict/overwrite path like any
    # other managed file. Announce it — silently discarding a project's ignore
    # rules or editor settings would be the worst possible surprise.
    if args.replace_merged:
        for rel in sorted(MERGED_PATHS, key=lambda p: p.as_posix()):
            if (target / rel).is_file():
                print(f"  ⚠ --replace-merged: {rel.as_posix()} will be REPLACED, "
                      f"not merged; its current contents are discarded")

    settings_rel = Path(".vscode/settings.json")
    settings_dst = target / settings_rel
    if not args.replace_merged and not errors and settings_dst.is_file():
        for index, (rel, new_bytes) in enumerate(rendered):
            if rel != settings_rel:
                continue
            try:
                merged = merge_vscode_settings(
                    settings_dst.read_text(encoding="utf-8"),
                    new_bytes.decode("utf-8"),
                )
                rendered[index] = (rel, merged.encode("utf-8"))
                mergeable_existing.add(rel)
            except Exception as error:
                print(
                    f"  ✗ FAILED to merge {settings_rel.as_posix()}: {error}"
                )
                errors += 1
            break

    gitignore_rel = Path(".gitignore")
    gitignore_dst = target / gitignore_rel
    if not args.replace_merged and not errors and gitignore_dst.is_file():
        for index, (rel, new_bytes) in enumerate(rendered):
            if rel != gitignore_rel:
                continue
            try:
                existing_text = gitignore_dst.read_text(encoding="utf-8")
                merged = merge_gitignore(existing_text, new_bytes.decode("utf-8"))
                rendered[index] = (rel, merged.encode("utf-8"))
                mergeable_existing.add(rel)
                if merged != existing_text:
                    added = len(merged.splitlines()) - len(existing_text.splitlines())
                    print(f"  · .gitignore: appending {added} line(s); "
                          f"existing entries untouched")
            except Exception as error:
                print(f"  ✗ FAILED to merge {gitignore_rel.as_posix()}: {error}")
                errors += 1
            break

    if errors:
        print("\nRendering failed; target was not modified.")
    elif args.dry_run:
        assert_safe_target_paths(
            target,
            [rel for rel, _ in rendered] + [Path(".initagentrulespy-manifest.json")],
        )
        dry_differing = [
            (rel, new_bytes)
            for rel, new_bytes in rendered
            if not file_matches(target / rel, new_bytes)
        ]
        dry_mergeable = {
            rel for rel, _ in dry_differing if rel in mergeable_existing
        }
        dry_conflicts = [
            rel
            for rel, _ in dry_differing
            if (target / rel).exists() and rel not in dry_mergeable
        ]
        dry_shape_conflicts = {
            rel: blocker
            for rel, _ in dry_differing
            if (blocker := target_shape_conflict(target, rel)) is not None
        }
        dry_conflicts.extend(dry_shape_conflicts.values())
        dry_obsolete: list[Path] = []
        dry_marker = target / ".initagentrulespy-manifest.json"
        if dry_marker.exists():
            prior = json.loads(dry_marker.read_text(encoding="utf-8"))
            prior_files = set(
                (
                    prior.get("installed_files")
                    or prior.get("rendered_files")
                    or {}
                ).keys()
            ) | set(prior.get("orphaned_managed_files", {}).keys())
            prior_files = {
                path
                for path in prior_files
                if is_managed_target_path(Path(path))
            }
            current_files = {rel.as_posix() for rel, _ in rendered}
            dry_obsolete = sorted(
                Path(path)
                for path in prior_files - current_files
                if (target / path).exists() and not is_seed_once(Path(path))
            )
            dry_conflicts.extend(dry_obsolete)
        dry_conflicts = sorted(
            set(dry_conflicts), key=lambda path: path.as_posix()
        )
        if (
            dry_conflicts
            and not (args.force or args.update or args.ignore_conflicts)
        ):
            print(
                "  ✗ would block: existing kit files differ; choose --update, "
                "--force, or --ignore-conflicts"
            )
            errors += 1
            skipped = len(rendered)
        elif args.update and dry_conflicts:
            for rel, _ in dry_differing:
                print(f"  · would stage update candidate: {rel.as_posix()}")
            for rel in dry_obsolete:
                print(f"  · would stage obsolete tombstone: {rel.as_posix()}")
            update_conflicts = len(dry_conflicts)
            skipped = len(rendered) - len(dry_differing)
        else:
            if args.ignore_conflicts:
                ignored_conflicts = dry_conflicts
            for rel, new_bytes in rendered:
                dst = target / rel
                if (
                    not args.force
                    and (
                        dst.exists()
                        or (
                            args.ignore_conflicts
                            and rel in dry_shape_conflicts
                        )
                    )
                    and rel not in dry_mergeable
                ):
                    reason = (
                        "conflict"
                        if rel in dry_shape_conflicts
                        else "exists"
                    )
                    print(f"  · skip ({reason}): {rel.as_posix()}")
                    skipped += 1
                else:
                    if rel in dry_mergeable:
                        verb = "would merge"
                    else:
                        verb = "would overwrite" if dst.exists() else "would write"
                    print(f"  · {verb}:        {rel.as_posix()}")
                    written += 1
            if args.force:
                for rel in dry_obsolete:
                    print(f"  · would delete obsolete: {rel.as_posix()}")
            marker = target / ".initagentrulespy-manifest.json"
            if args.force or not marker.exists():
                print("  · would write:        .initagentrulespy-manifest.json")
                written += 1
    else:
        lock_fd, lock_path, lock_token = acquire_target_lock(target)
        try:
            assert_safe_target_paths(
                target,
                [rel for rel, _ in rendered]
                + [
                    Path(".initagentrulespy-manifest.json"),
                    Path(".initagentrulespy-updates"),
                    Path(".initagentrulespy-transactions"),
                ],
            )
            recover_incomplete_transactions(target)
            # Safe update: if ANY existing target differs, stage every changed /
            # missing candidate separately and leave the live target untouched.
            differing = [
                (rel, new_bytes)
                for rel, new_bytes in rendered
                if not file_matches(target / rel, new_bytes)
            ]
            mergeable_differing = {
                rel for rel, _ in differing if rel in mergeable_existing
            }
            existing_conflicts = [
                rel
                for rel, _ in differing
                if (target / rel).exists()
                and rel not in mergeable_differing
            ]
            shape_conflicts_by_candidate = {
                rel: blocker
                for rel, _ in differing
                if (blocker := target_shape_conflict(target, rel)) is not None
            }
            shape_conflicts = sorted(
                set(shape_conflicts_by_candidate.values()),
                key=lambda path: path.as_posix(),
            )
            existing_conflicts.extend(shape_conflicts)
            marker_path = target / ".initagentrulespy-manifest.json"
            previous_files: set[str] = set()
            if marker_path.exists():
                previous_marker = json.loads(marker_path.read_text(encoding="utf-8"))
                previous_files = set(
                    (
                        previous_marker.get("installed_files")
                        or previous_marker.get("rendered_files")
                        or {}
                    ).keys()
                )
                previous_files.update(
                    previous_marker.get("orphaned_managed_files", {}).keys()
                )
                previous_files = {
                    path
                    for path in previous_files
                    if is_managed_target_path(Path(path))
                }
            current_files = {rel.as_posix() for rel, _ in rendered}
            obsolete = sorted(
                Path(path)
                for path in previous_files - current_files
                if (target / path).exists() and not is_seed_once(Path(path))
            )
            assert_safe_target_paths(target, obsolete)
            unsafe_shape_conflicts = [
                rel
                for rel in shape_conflicts
                if not any(
                    obsolete_path.as_posix().startswith(rel.as_posix() + "/")
                    for obsolete_path in obsolete
                )
            ]
            if unsafe_shape_conflicts and not args.ignore_conflicts:
                raise ValueError(
                    "Generated file path collides with an unmanaged directory: "
                    + ", ".join(rel.as_posix() for rel in unsafe_shape_conflicts)
                )
            existing_conflicts.extend(obsolete)
            existing_conflicts = sorted(
                set(existing_conflicts), key=lambda path: path.as_posix()
            )
            if args.ignore_conflicts:
                ignored_conflicts = existing_conflicts
            if (
                existing_conflicts
                and not (args.force or args.update or args.ignore_conflicts)
            ):
                raise ValueError(
                    "Existing kit files differ from the bundled templates. Use --update "
                    "to stage merge candidates, --force to replace everything, "
                    "or --ignore-conflicts to install only missing files."
                )
            if args.update and existing_conflicts:
                assert_safe_target_paths(
                    target, [Path(".initagentrulespy-updates")]
                )
                updates_root = target / ".initagentrulespy-updates"
                generation = str(uuid.uuid4())
                candidate_temp = updates_root / f".tmp-{generation}"
                candidate_root = updates_root / generation
                try:
                    for rel, new_bytes in differing:
                        atomic_write(candidate_temp / rel, new_bytes)
                    manifest = {
                        "status": "merge-required",
                        "generation": generation,
                        "created_unix": time.time(),
                        "conflicts": [p.as_posix() for p in existing_conflicts],
                        "obsolete": [
                            {
                                "path": rel.as_posix(),
                                "action": "delete",
                            }
                            for rel in obsolete
                        ],
                        "candidates": [
                            {
                                "path": rel.as_posix(),
                                "target_baseline_state": target_state(target / rel),
                            }
                            for rel, _ in differing
                        ],
                    }
                    atomic_write(
                        candidate_temp / "manifest.json",
                        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
                    )
                    updates_root.mkdir(parents=True, exist_ok=True)
                    os.replace(candidate_temp, candidate_root)
                    if os.name != "nt":
                        updates_fd = os.open(updates_root, os.O_RDONLY)
                        try:
                            os.fsync(updates_fd)
                        finally:
                            os.close(updates_fd)
                finally:
                    if candidate_temp.exists():
                        durable_rmtree(candidate_temp)
                update_conflicts = len(existing_conflicts)
                print(
                    f"  ⚠ update requires merge: {update_conflicts} existing "
                    f"file(s) differ; candidates staged at {candidate_root}"
                )
            else:
                planned = [
                    (rel, new_bytes)
                    for rel, new_bytes in rendered
                    # A file that already matches needs no write under any mode.
                    # Rewriting it churns mtimes, fills the rollback journal with
                    # no-ops, and can fail on a path the run did not need to touch.
                    if not file_matches(target / rel, new_bytes)
                    and (
                        args.force
                        or (
                            (
                                not (target / rel).exists()
                                or rel in mergeable_differing
                            )
                            and not (
                                args.ignore_conflicts
                                and rel in shape_conflicts_by_candidate
                            )
                        )
                    )
                ]
                planned_deletions = obsolete if args.force else []
                skipped = len(rendered) - len(planned)
                if skipped:
                    planned_paths = {rel for rel, _ in planned}
                    for rel, _ in rendered:
                        if rel not in planned_paths:
                            reason = (
                                "conflict"
                                if rel in shape_conflicts_by_candidate
                                else "exists"
                            )
                            print(f"  · skip ({reason}): {rel.as_posix()}")
                marker_rel = Path(".initagentrulespy-manifest.json")
                installed_files = {
                    rel.as_posix(): None for rel, _ in rendered
                }
                marker_bytes = (
                    json.dumps(
                        {
                            "kit_protocol_version": "1.0",
                            "status": (
                                "mixed-explicit"
                                if args.ignore_conflicts and existing_conflicts
                                else "complete"
                            ),
                            # Recorded so later --status / --verify-templates
                            # runs can rebuild the same values without the user
                            # re-passing flags that have no auto-detect path.
                            "substitutions": {
                                "org_alias": alias,
                                "org_name": org_name,
                                "api_version": api_version,
                                "pmd_path": pmd_path,
                                "java_home": java_home,
                            },
                            "installed_files": installed_files,
                            "orphaned_managed_files": (
                                {
                                    rel.as_posix(): None
                                    for rel in obsolete
                                }
                                if args.ignore_conflicts
                                else {}
                            ),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                if (
                    args.force
                    or not (target / marker_rel).exists()
                    or (target / marker_rel).read_bytes() != marker_bytes
                ):
                    planned.append((marker_rel, marker_bytes))
                transaction = (
                    target / ".initagentrulespy-transactions" / str(uuid.uuid4())
                )
                assert_safe_target_paths(
                    target, [Path(".initagentrulespy-transactions")]
                )
                transaction_files = []
                for rel, _ in planned:
                    dst = target / rel
                    baseline_state = target_state(dst)
                    existed = baseline_state == "file"
                    transaction_files.append(
                        {
                            "path": rel.as_posix(),
                            "existed": existed,
                            "baseline_state": baseline_state,
                            "write_precondition_state": (
                                "missing"
                                if baseline_state == "directory"
                                and any(
                                    obsolete_rel.as_posix().startswith(
                                        rel.as_posix() + "/"
                                    )
                                    for obsolete_rel in planned_deletions
                                )
                                else baseline_state
                            ),
                            "intended_state": "file",
                        }
                    )
                    if existed:
                        atomic_write(
                            backup_slot(transaction, rel),
                            dst.read_bytes(),
                        )
                for rel in planned_deletions:
                    dst = target / rel
                    replaced_by_directory = any(
                        planned_rel.as_posix().startswith(rel.as_posix() + "/")
                        for planned_rel, _ in planned
                    )
                    transaction_files.append(
                        {
                            "path": rel.as_posix(),
                            "existed": True,
                            "baseline_state": "file",
                            "intended_state": (
                                "directory" if replaced_by_directory else "missing"
                            ),
                        }
                    )
                    atomic_write(backup_slot(transaction, rel), dst.read_bytes())
                # Recovery iterates in reverse: restore/remove new-shape writes
                # before recreating obsolete file paths that may replace dirs.
                transaction_files.sort(
                    key=lambda item: item["intended_state"] == "file"
                )
                transaction_manifest = {
                    "state": "prepared",
                    "files": transaction_files,
                }
                atomic_write(
                    transaction / "manifest.json",
                    (json.dumps(transaction_manifest, indent=2) + "\n").encode(
                        "utf-8"
                    ),
                )
                fsync_directory(transaction)
                fsync_directory(transaction.parent)
                fsync_directory(target)
                try:
                    transaction_by_path = {
                        item["path"]: item for item in transaction_files
                    }
                    # Delete obsolete paths first so file↔directory renames can
                    # create the new shape. Rollback backups recreate parents.
                    for rel in planned_deletions:
                        dst = target / rel
                        current_state = target_state(dst)
                        if current_state != "file":
                            raise RuntimeError(
                                f"Obsolete target changed after backup: {rel.as_posix()}"
                            )
                        durable_unlink(dst)
                        prune_empty_parents(dst.parent, target)
                        print(f"  ✓ deleted obsolete: {rel.as_posix()}")
                    for rel, new_bytes in planned:
                        dst = target / rel
                        existed = dst.exists()
                        item = transaction_by_path[rel.as_posix()]
                        current_state = target_state(dst)
                        if current_state != item["write_precondition_state"]:
                            raise RuntimeError(
                                f"Target changed after backup: {rel.as_posix()}"
                            )
                        atomic_write(dst, new_bytes, mode=desired_mode(rel))
                        verb = (
                            "merged"
                            if existed and rel in mergeable_differing
                            else "overwrote" if existed else "wrote"
                        )
                        print(
                            f"  ✓ {verb}:           {rel.as_posix()}"
                        )
                        written += 1
                    for item in transaction_files:
                        dst = target / item["path"]
                        actual_state = target_state(dst)
                        if actual_state != item["intended_state"]:
                            raise RuntimeError(
                                f"Final target state check failed: {item['path']}"
                            )
                    transaction_manifest["state"] = "committed"
                    atomic_write(
                        transaction / "manifest.json",
                        (json.dumps(transaction_manifest, indent=2) + "\n").encode(
                            "utf-8"
                        ),
                    )
                except BaseException:
                    # Rollback can fail too — a path that blocked the write will
                    # usually block its restore. Say so explicitly: the difference
                    # between "nothing changed" and "half-written, journal kept for
                    # retry" is the only thing the operator actually needs to know.
                    try:
                        recover_incomplete_transactions(target)
                    except BaseException as rollback_error:
                        print(f"  ✗ ROLLBACK FAILED: {rollback_error}")
                        print("    The target is PARTIALLY WRITTEN. The transaction "
                              "journal is preserved at")
                        print(f"    .initagentrulespy-transactions/{transaction.name} "
                              "— re-run init.py to retry recovery,")
                        print("    or restore from version control.")
                    else:
                        print("  ✗ write failed; rolled back every file from this run")
                    raise
                else:
                    for rel in enforce_modes(target, [rel for rel, _ in rendered]):
                        print(f"  ✓ mode 755:        {rel.as_posix()}")
                    try:
                        durable_rmtree(transaction)
                    except OSError as cleanup_error:
                        print(
                            "  ⚠ install committed; transaction-journal cleanup "
                            f"deferred: {cleanup_error}"
                        )
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            errors += 1
        finally:
            release_target_lock(lock_fd, lock_path, lock_token)

    print()
    print("=" * 72)
    summary = f"Summary: {written} written, {skipped} skipped, {errors} errors"
    if update_conflicts:
        summary += f", {update_conflicts} update conflict(s)"
    if args.dry_run:
        summary = "DRY RUN: " + summary
    print(summary)
    if ignored_conflicts:
        print()
        print(
            f"  Ignored {len(ignored_conflicts)} conflicting path(s); "
            "existing content was left unchanged:"
        )
        for rel in ignored_conflicts:
            print(f"    - {rel.as_posix()}")

    if preserved_seeds:
        print()
        print(
            f"  Preserved {len(preserved_seeds)} seed-once file(s) — the kit ships "
            "these as\n  scaffolds only, so your filled-in version is never replaced:"
        )
        for rel in preserved_seeds:
            print(f"    - {rel.as_posix()}")

    sentinels_used = []
    if alias == ALIAS_SENTINEL:
        sentinels_used.append(ALIAS_SENTINEL)
    if java_home == JAVA_SENTINEL:
        sentinels_used.append(JAVA_SENTINEL)
    if pmd_path == PMD_SENTINEL:
        sentinels_used.append(PMD_SENTINEL)
    if api_version == API_VERSION_SENTINEL:
        sentinels_used.append(API_VERSION_SENTINEL)

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
    if errors or update_conflicts:
        return 1
    print(f"  Next: open `.cursor/rules/sf-cli-commands.mdc` to see the canonical sf CLI reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
