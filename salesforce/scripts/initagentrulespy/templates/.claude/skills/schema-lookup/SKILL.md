---
name: schema-lookup
description: Look up Salesforce object/field/picklist/RecordType definitions in `config/schema/` using the strict 7-file read sequence. INVOKE before writing SOQL, Apex DML, OmniStudio DataRaptors, or any code that names a field, type, picklist value, or RecordType. The full enforceable policy lives in `.cursor/rules/salesforce-schema-validation.mdc` (always-applied) — this skill is the operational quick-start.
---

# Schema lookup (7-file split per object)

The org's schema lives under `config/schema/objects/<ApiName>/`, split into up to 7 small focused TOON files. The strict reading order is enforced by [`.cursor/rules/salesforce-schema-validation.mdc`](.cursor/rules/salesforce-schema-validation.mdc) (`alwaysApply: true`). This skill is the operational summary.

```
config/schema/
├── _index.toon                  master index of every object + companion files
├── _search_index.toon           lightweight cross-object field search
├── _junctions.toon              detected junctions: object -> parent FKs, record_count, confidence
├── objects/<ApiName>/
│   ├── schema.toon              ALWAYS — slim index: object meta + counts + file pointers
│   ├── fields.toon              ALWAYS — every field as one tabular row; lookups carry reference_path
│   ├── record_types.toon        optional — RecordTypes (api_name, label, description, active, record_count)
│   ├── validation_rules.toon    optional — validation rules + error formulas
│   ├── related_relationships.toon optional — incoming references (parent -> child)
│   ├── picklists.toon           optional — TWO blocks: picklists: (single-select) + multipicklists: (multi-select)
│   └── formulas.toon            optional — calculated field expressions
└── categories/                  objects grouped by domain
ER.md (project root)             mermaid ER diagram of every detected junction
```

## Field-driven mandatory reads (the strictest trigger)

Whenever you SEE one of these on a row in `fields.toon`, you MUST open the named file BEFORE writing or referencing that field in any way (read or write):

| Field shape | MUST open |
|---|---|
| `type: Picklist` | `objects/<X>/picklists.toon` — find the field name in the `picklists:` block. NEVER use a value not listed there. |
| `type: MultiselectPicklist` | `objects/<X>/picklists.toon` — find the field name in the `multipicklists:` block. NEVER use a value not listed there. |
| `api_name: RecordTypeId` | `objects/<X>/record_types.toon` — use `api_name` (DeveloperName) at runtime; never hardcode the Id. |
| `type: Lookup` or `MasterDetail` | follow the `reference_path` cell to the parent's `schema.toon` and re-enter from the top. |

## The reading pattern (general)

1. **Always start with `objects/<X>/schema.toon`.** Slim index — tells you what other files exist for this object and how many entries each contains.
2. **Open `objects/<X>/fields.toon`** whenever you reference a field by name, type, or constraint. Apply the field-driven triggers above as you scan.
3. **Open `objects/<X>/picklists.toon`** triggered by `type: Picklist` or `type: MultiselectPicklist`. Two blocks: `picklists:` for single-select, `multipicklists:` for multi-select. See "Count semantics" below.
4. **Open `objects/<X>/record_types.toon`** triggered by `api_name: RecordTypeId`. Use `api_name` as the lookup key.
5. **Open `objects/<X>/validation_rules.toon`** only after a deploy fails on a validation error.
6. **Open `objects/<X>/related_relationships.toon`** to traverse parent → child.
7. **Open `objects/<X>/formulas.toon`** only when a calculated field's behavior is surprising.
8. **For cross-object relationships** read `_junctions.toon` (programmatic) or `ER.md` (visual).

## Count semantics (read this BEFORE using picklist or RecordType data)

### picklists.toon

Two blocks:
- `picklists:` — single-select fields. Status in `metadata.picklists_usage_status`.
- `multipicklists:` — multi-select fields. Status is ALWAYS `metadata.multipicklists_usage_status: not_applicable` because SOQL cannot `GROUP BY` multi-select picklists.

Every value-row in either block carries BOTH `label` and `value`. They commonly differ (`value: PCP`, `label: Primary Care Physician`). Use `value` in code/SOQL/DML; `label` is for display.

States for `picklists:` block:
- `live_counts` — `values[N]{label,value,count}:` form. `count: 0` = declared but ZERO records use it (deprecated candidate). `count > 0` = active.
- `not_collected` — `values[N]{label,value}:` form (no count column). NEVER infer "deprecated" from absence of a count. `metadata.picklists_usage_not_collected_reason` (optional): `pending`, `no_query_access`, `empty_object`, `query_error`.
- `not_applicable` — only when there are no single-select picklists.

`metadata.picklists_with_query_errors: [...]` (optional) lists fields where the query failed; their sub-block falls back to `{label,value}` form even when the file overall is `live_counts`.

### record_types.toon

Shape `record_types[N]{api_name,label,description,active,record_count}:`. `api_name` is the DeveloperName (the "value" half).

States:
- `live_counts` — `record_count` column present. `record_count: 0` = deprecated. `record_count > 0` = active.
- `not_collected` — `record_count` column absent. Same reason enum as picklists.

## fields.toon decoding rules

Every cell is a string on the wire (so the file stays in TOON tabular form). Decode per `metadata.cell_value_decoding`:

- empty `""` — absent / null
- `"true"` / `"false"` — boolean
- digit-only — integer
- `"A|B|C"` — list of strings (polymorphic `reference_to` / `reference_path`)
- everything else — string

## When you don't know the object name

```bash
grep -i "<keyword>" config/schema/_index.toon              # candidate objects
grep -i "<FieldApiName>" config/schema/_search_index.toon  # any object with this field
```

Then read the matching `objects/<X>/schema.toon`.

## Worked example (generic)

You're writing Apex that creates a `Case` with a Contact reference, sets `Type` (a Picklist), and uses a specific RecordType.

1. Open `config/schema/objects/Case/schema.toon` — confirm exists, see counts.
2. Open `config/schema/objects/Case/fields.toon` — locate:
   - `ContactId` row (Lookup → Contact) — note `reference_path`.
   - `Type` row (`type: Picklist`) — **field-driven trigger fires.**
   - `RecordTypeId` row (`api_name: RecordTypeId`) — **field-driven trigger fires.**
3. Open `config/schema/objects/Contact/schema.toon` to confirm the parent.
4. Open `config/schema/objects/Case/picklists.toon` → `picklists:` block → `Type` sub-block. Read `metadata.picklists_usage_status`. Pick a `value` (use the value column, not label) with `count > 0` if `live_counts`.
5. Open `config/schema/objects/Case/record_types.toon`. Find your intended RecordType by `api_name`. Resolve the Id at runtime via `Schema.SObjectType.Case.getRecordTypeInfosByDeveloperName().get('<api_name>').getRecordTypeId()`.
6. Now write the code.

## Stale-schema test

If a field/picklist/RecordType you expect isn't in the schema files, regenerate before guessing:

```bash
python3 scripts/schemapy/auto_generate_schema.py             # full re-pull + split (~50 min)
python3 scripts/schemapy/collect_usage_stats.py --org {{ORG_ALIAS}} --objects Account,Case  # targeted count refresh
```

## When NOT to use

- Pure UI/markup work (LWC HTML/CSS) that doesn't touch field API names.
- Reading existing Apex that already references fields you can `grep` to confirm.
