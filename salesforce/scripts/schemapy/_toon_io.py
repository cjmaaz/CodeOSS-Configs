"""
Shared helpers for the schema-generation pipeline.

Provides:
  - dump_toon / load_toon — TOON file I/O
  - find_project_root — locates the project root (the directory holding
    .sf/config.json or sfdx-project.json) by walking up from this file's
    location, so callers can build absolute paths instead of cwd-relative
    ones. This makes the pipeline cwd-independent.

Used by:
  - generate_sf_er_schema.py  (writes the combined intermediate)
  - split_schema_by_object.py (reads combined, writes per-object + indexes)
  - enrich_schema_with_picklists.py (reads/writes per-object files)
  - auto_generate_schema.py    (orchestrator)

TOON (Token-Oriented Object Notation, v3.0) replaces the previous YAML
encoding. The format does not support comments, so any "header banner"
that the YAML versions emitted as `# ...` lines is intentionally
dropped. The same generation metadata is preserved inside the document
itself via the `metadata:` block that each producer already emits.

Reference: https://github.com/toon-format/spec/blob/main/SPEC.md
Python lib: https://pypi.org/project/toon-format/
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

try:
    from toon_format import encode as _toon_encode
    from toon_format import decode as _toon_decode
except ImportError:
    print(
        "Error: toon-format module not found.\n"
        "Install dependencies: pip install -r scripts/schemapy/requirements.txt\n"
        "  (or: pip install --pre toon-format)"
    )
    sys.exit(1)


# Markers (in priority order) that identify a Salesforce/SFDX project root.
# `.sf/config.json` is checked first because it carries the active org alias
# the schema pipeline needs; `sfdx-project.json` is the canonical SFDX
# marker; `.git/` is a final fallback when neither is present.
_ROOT_MARKERS = ('.sf/config.json', 'sfdx-project.json', '.git')


def find_project_root(start: Optional[Path] = None) -> Path:
    """
    Walk upward from `start` (default: this file's directory) and return
    the first ancestor that contains any of the project-root markers.

    Falls back to the current working directory if no marker is found —
    preserves the original behaviour for users who invoke the scripts
    from a project root that lacks SFDX config.
    """
    if start is None:
        start = Path(__file__).resolve().parent
    else:
        start = Path(start).resolve()

    candidate = start if start.is_dir() else start.parent
    while True:
        for marker in _ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate
        if candidate.parent == candidate:
            return Path.cwd()
        candidate = candidate.parent


def dump_toon(data: Any, path: Path) -> None:
    """
    Encode `data` (JSON-compatible value) to TOON and write to `path`.

    File is written as UTF-8 with LF line endings, no trailing newline,
    per the TOON v3.0 spec (§5, §12). Parent directories are created
    on demand.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _toon_encode(data)
    # toon-format already emits LF; write in binary mode to guarantee no
    # platform newline translation and no trailing newline append.
    with open(path, "wb") as f:
        f.write(encoded.encode("utf-8"))


def load_toon(path: Path) -> Any:
    """
    Read a TOON document from `path` and return the decoded Python value
    (dict / list / primitive). Raises on malformed input (strict mode is
    the toon-format default).
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return _toon_decode(text)
