"""
Helpers for emitting per-object `fields.toon` in TOON tabular form.

Used by:
  - split_schema_by_object.py (Step 8) — initial emission from XML metadata
  - enrich_schema_with_picklists.py (Step 9) — re-emission after merging
    `sf sobject describe` data into existing rows

Tabular invariants (TOON spec §9.3):
  - Every row has exactly the same set of keys.
  - Every cell is a primitive (no nested arrays/objects).
  - Every column has a uniform value type.

To satisfy invariant 3 we stringify EVERY cell. The resulting columns
are uniformly strings; consumers decode per the conventions documented
in `metadata.cell_value_decoding`:
  - empty string  -> not present / null
  - "true"/"false" -> bool
  - decimal digits -> int
  - "A|B|C"        -> list of strings (used for polymorphic
                       reference_to / reference_path)
  - everything else -> string

For Lookup / MasterDetail fields we automatically compute a
`reference_path` cell that points at the parent object's
`schema.toon` (relative to `config/schema/`), pipe-joined for
polymorphic refs.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import dump_toon  # noqa: E402


POLY_SEP = '|'

# Keys that NEVER live on fields.toon — they belong elsewhere or are
# placeholders we no longer emit.
EXCLUDED_FIELD_KEYS = ('picklist_values', 'formula', '_note')

# Column-order priority. Anything not listed lands at the end,
# alphabetised.
COLUMN_PRIORITY = (
    'api_name', 'type', 'label', 'help_text', 'description',
    'required', 'unique', 'external_id',
    'length', 'precision', 'scale',
    'reference_to', 'reference_path', 'relationship_name',
    'relationship_label', 'delete_constraint',
    'default_value', 'controlling_field', 'is_dependent_picklist',
)

LOOKUP_TYPES = ('Lookup', 'MasterDetail', 'reference')


def stringify(value: Any) -> str:
    """Coerce any value into the uniform string column form."""
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return POLY_SEP.join('' if x is None else str(x) for x in value)
    return str(value)


def build_reference_path(
    reference_to: Any,
    present_objects: Set[str],
) -> str:
    """Return one or pipe-joined paths to the parent object schema.toon
    files. Empty string when no slot resolves to a known folder."""
    if not reference_to:
        return ''
    if isinstance(reference_to, str):
        # May already be pipe-separated from a previous tabular round-trip.
        targets = reference_to.split(POLY_SEP) if POLY_SEP in reference_to else [reference_to]
    elif isinstance(reference_to, list):
        targets = [str(t) for t in reference_to]
    else:
        return ''
    paths = []
    for t in targets:
        t = t.strip()
        if t and t in present_objects:
            paths.append(f"objects/{t}/schema.toon")
        else:
            paths.append('')
    if all(p == '' for p in paths):
        return ''
    return POLY_SEP.join(paths)


def union_columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Compute the canonical column order across all rows.

    Always promotes `reference_path` into the column set when any row is
    a Lookup/MasterDetail, so the column exists even when no input dict
    carries it explicitly (Step 8 case, before describe runs).
    """
    present_keys = {k for row in rows for k in row.keys()}
    if any(row.get('type') in LOOKUP_TYPES for row in rows):
        present_keys.add('reference_path')

    cols: List[str] = []
    seen: Set[str] = set()
    for k in COLUMN_PRIORITY:
        if k in present_keys:
            cols.append(k)
            seen.add(k)
    extras = sorted(present_keys - seen)
    extras = [k for k in extras if k not in EXCLUDED_FIELD_KEYS]
    cols.extend(extras)
    return cols


def normalise_row(
    field: Dict[str, Any],
    columns: List[str],
    present_objects: Set[str],
) -> Dict[str, str]:
    """Build a fully-padded, fully-stringified row aligned to `columns`.
    Computes `reference_path` from `reference_to` for Lookup-typed
    fields."""
    row: Dict[str, str] = {}
    for k in columns:
        if k == 'reference_path':
            if field.get('type') in LOOKUP_TYPES:
                row[k] = build_reference_path(field.get('reference_to'), present_objects)
            else:
                row[k] = ''
        else:
            row[k] = stringify(field.get(k))
    return row


def emit_fields_file(
    output_file: Path,
    obj_name: str,
    fields: List[Dict[str, Any]],
    present_objects: Set[str],
    gen_date: Optional[str] = None,
) -> None:
    """Write fields.toon in the canonical tabular form. `fields` is a
    list of dicts (any keys/types). The function strips excluded keys,
    computes the union column set + reference_path for lookups, and
    stringifies every cell so the encoder produces a single tabular
    block."""
    if gen_date is None:
        gen_date = datetime.now().isoformat()

    # Defensive: drop excluded keys before column union
    filtered_fields = [
        {k: v for k, v in f.items() if k not in EXCLUDED_FIELD_KEYS}
        for f in fields
    ]
    columns = union_columns(filtered_fields)
    rows = [normalise_row(f, columns, present_objects) for f in filtered_fields]

    doc = {
        'fields': rows,
        'metadata': {
            'object': obj_name,
            'generated_date': gen_date,
            'field_count': len(rows),
            'columns': columns,
            'null_encoding': 'empty_string',
            'polymorphic_separator': POLY_SEP,
            'cell_value_decoding': (
                'All cells are strings on the wire. Empty string == '
                'absent/null. "true"/"false" decode to bool. Digit-only '
                'cells decode to int. Pipe-separated cells decode to '
                'list of strings (used for polymorphic reference_to / '
                'reference_path).'
            ),
        },
    }
    dump_toon(doc, output_file)


def discover_present_objects_from_dir(objects_dir: Path) -> Set[str]:
    """Build the set of known object api_names by listing `objects_dir`
    folders. Used by Step 9 (and any other consumer that doesn't already
    have the combined schema in memory)."""
    if not objects_dir.exists():
        return set()
    return {
        p.name for p in objects_dir.iterdir()
        if p.is_dir() and not p.name.startswith('_')
    }
