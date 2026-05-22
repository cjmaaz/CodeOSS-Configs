# Salesforce Schema Quick Reference

This is a pointer doc. The **canonical rules** for browsing the schema are:

- **How the schema is organized:** [`config/schema/README.md`](../config/schema/README.md)
- **How to validate before coding:** [`.cursor/rules/salesforce-schema-validation.mdc`](../.cursor/rules/salesforce-schema-validation.mdc) (`alwaysApply: true`)

Use this quick reference to jump to the most-used objects fast.

## Navigating the schema (7-file split per object)

```
config/schema/
├── _index.toon                  # Master index of every object + companion files
├── _search_index.toon           # Lightweight cross-object field search
├── _junctions.toon              # Detected junctions: object -> parent FKs + record counts
├── objects/<ApiName>/
│   ├── schema.toon              # ALWAYS — slim index: meta + counts + file pointers
│   ├── fields.toon              # ALWAYS — every field as one tabular row; lookups carry reference_path
│   ├── record_types.toon        # optional — RecordTypes (api_name, label, description, active, record_count)
│   ├── validation_rules.toon    # optional — validation rules + error formulas
│   ├── related_relationships.toon # optional — incoming references (parent -> child)
│   ├── picklists.toon           # optional — picklist values + per-value record counts
│   └── formulas.toon            # optional — calculated field expressions
└── categories/                  # Objects grouped by category

ER.md (project root)             # Mermaid ER of every detected junction (skim first for relationship overview)
```

**Reading workflow** (full strict policy in `.cursor/rules/salesforce-schema-validation.mdc`):

1. Open `schema.toon` for the object — slim index telling you which other files exist and their counts.
2. Open `fields.toon` for any code that names a field. Every Lookup row carries a `reference_path` cell pointing at the parent object's `schema.toon`.
2a. **WHEN you see a Picklist field in fields.toon, you MUST open** `objects/<X>/picklists.toon` and find that field name in the `picklists:` block. WHEN you see a MultiselectPicklist field, look in the `multipicklists:` block instead. Check `metadata.picklists_usage_status`: `live_counts` = treat `count: 0` as deprecated; `not_collected` = refresh if you need usage data. The multipicklists block is always inline `{label,value}` — per-value counts are not obtainable for multi-select. Use the `value` column in code (NOT `label`).
2b. **WHEN you see RecordTypeId on a field row, you MUST open** `objects/<X>/record_types.toon` and resolve via `api_name` (DeveloperName) at runtime. Check `metadata.usage_status` with the same conventions (`record_count: 0` means declared but unused).
3. Open `validation_rules.toon` after a deploy fails on a validation error.
4. Open `related_relationships.toon` to traverse parent → child.
5. Open `formulas.toon` only when a calculated field's behavior is surprising.
6. For cross-object overview, read `_junctions.toon` (programmatic) or `ER.md` (visual).

## Record-type identifiers

When you need a specific `RecordTypeId` without hitting the org:

```bash
rg "DeveloperName.*PRM_" config/schema/objects/<Object>/record_types.toon
```

`record_types.toon` is a tabular file with `api_name,label,description,active,record_count` columns. Use `api_name` (DeveloperName) as the lookup key in Apex; never hardcode the Id.

## Regenerating the schema

```bash
python3 scripts/schemapy/auto_generate_schema.py     # full regen (retrieves from org)
python3 scripts/schemapy/split_schema_by_object.py   # re-split an existing schema file
```

See [`config/schema/README.md`](../config/schema/README.md) for full details.
