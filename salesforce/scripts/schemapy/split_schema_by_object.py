#!/usr/bin/env python3
"""
Schema Splitter - Split Large Schema into Manageable Files
===========================================================

This script takes the large salesforce-er-schema.toon file and creates:
1. Individual object folders (schema/objects/<ObjectName>/{schema,picklists,formulas}.toon)
2. A master index file (schema/_index.toon)
3. Categorized schema files (schema/categories/*.toon)
4. A lightweight search index (schema/_search_index.toon)

All outputs are encoded in TOON (Token-Oriented Object Notation, v3.0)
for token efficiency. See https://github.com/toon-format/spec.

This makes the schema usable by AI agents within token limits.

Usage:
    python3 split_schema_by_object.py [--input PATH] [--output-dir PATH]

Options:
    --input PATH        Path to the large schema file (default: config/salesforce-er-schema.toon)
    --output-dir PATH   Path to output directory (default: config/schema)
    --help             Show this help message

The script is automatically called after schema generation by auto_generate_schema.py
"""

import os
import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Allow `from _toon_io import ...` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import dump_toon, load_toon, find_project_root  # noqa: E402
from _fields_tabular import emit_fields_file as emit_fields_tabular  # noqa: E402

# Salesforce managed-package namespaces follow `<Namespace>__<Rest>` where
# `<Namespace>` is purely alphanumeric. Non-namespaced custom objects end
# in `__c` / `__b` / `__e` / `__mdt` / `__x` (i.e. the part-before-`__`
# tail is a single suffix letter, NOT a namespace).
_NAMESPACE_RE = re.compile(r'^([A-Za-z][A-Za-z0-9]*)__([A-Za-z][A-Za-z0-9_]+)$')
_CUSTOM_OBJECT_SUFFIXES = ('c', 'b', 'e', 'mdt', 'x')


def _detect_namespace(obj_name: str) -> str:
    """Return the package namespace for an object, or '' if it is unnamespaced."""
    m = _NAMESPACE_RE.match(obj_name)
    if not m:
        return ''
    ns, rest = m.group(1), m.group(2)
    if rest in _CUSTOM_OBJECT_SUFFIXES:
        return ''
    return ns


class SchemaOptimizer:
    """Optimizes large schema files for AI agent consumption."""

    # Predefined categories for well-known standard Salesforce objects.
    # Anything else is auto-categorised by namespace (managed packages
    # become `ns_<namespace>`) or falls into `custom` / `other`. This
    # keeps the splitter usable in any Salesforce org without code edits.
    CATEGORIES = {
        'core': ['Account', 'Contact', 'Lead', 'User', 'Group', 'Profile'],
        'sales': ['Opportunity', 'Quote', 'Contract', 'Order', 'Product2', 'PricebookEntry',
                  'OpportunityLineItem', 'QuoteLineItem', 'OrderItem'],
        'service': ['Case', 'Solution', 'Entitlement', 'ServiceContract', 'WorkOrder',
                    'WorkOrderLineItem', 'ServiceAppointment'],
        'marketing': ['Campaign', 'CampaignMember', 'Lead'],
        'activities': ['Task', 'Event', 'EmailMessage'],
    }
    
    def __init__(self, input_file, output_dir):
        """
        Initialize the optimizer.
        
        Args:
            input_file: Path to the large schema TOON file
            output_dir: Path to the output directory for split files
        """
        self.input_file = Path(input_file)
        self.output_dir = Path(output_dir)
        self.schema_data = None
        self.objects = []
        self.relationships = []
        self.metadata = {}
        
    def load_schema(self):
        """Load the large schema file (TOON-encoded)."""
        print("=" * 80)
        print("Loading Large Schema File")
        print("=" * 80)
        print(f"Reading: {self.input_file}")

        if not self.input_file.exists():
            print(f"✗ Error: Schema file not found: {self.input_file}")
            return False

        try:
            self.schema_data = load_toon(self.input_file)

            # Extract components
            sf_schema = self.schema_data.get('salesforce_schema', {}) if isinstance(self.schema_data, dict) else {}
            self.metadata = sf_schema.get('metadata', {})
            self.objects = sf_schema.get('objects', [])
            self.relationships = sf_schema.get('relationships', [])

            print(f"✓ Loaded schema successfully")
            print(f"  Objects: {len(self.objects)}")
            print(f"  Relationships: {len(self.relationships)}")

            return True

        except Exception as e:
            print(f"✗ Error: Failed to load schema: {e}")
            return False
    
    def create_directories(self):
        """Create output directory structure and prune orphan YAML files
        from the previous YAML-era pipeline."""
        print("\n" + "=" * 80)
        print("Creating Directory Structure")
        print("=" * 80)

        dirs_to_create = [
            self.output_dir,
            self.output_dir / 'objects',
            self.output_dir / 'categories',
        ]

        for dir_path in dirs_to_create:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"✓ {dir_path}")
            except Exception as e:
                print(f"✗ Error creating {dir_path}: {e}")
                return False

        # Prune any leftover .yaml files inside the output directory.
        # Guarded to self.output_dir tree only, so we never touch other yaml
        # files in the workspace (sfdx-project.json siblings, manifests, etc).
        legacy_count = 0
        try:
            for yaml_file in self.output_dir.rglob('*.yaml'):
                yaml_file.unlink()
                legacy_count += 1
        except Exception as e:
            print(f"  Warning: error while pruning legacy .yaml files: {e}")
        if legacy_count:
            print(f"✓ Pruned {legacy_count} legacy .yaml file(s) from {self.output_dir}")

        return True
    
    # ------------------------------------------------------------------
    # Per-object file emission helpers (new 7-file layout)
    # ------------------------------------------------------------------

    # Field keys that always belong elsewhere — they DON'T go into
    # fields.toon. picklist_values -> picklists.toon, formula -> formulas.toon,
    # _note -> dropped entirely (the new strict instructions tell agents
    # where to look).
    _FIELDS_FILE_EXCLUDE_KEYS = ('picklist_values', 'formula', '_note')

    # Polymorphic separator used when reference_to / reference_path span
    # multiple parent entities (e.g. OwnerId -> Group|User). Documented in
    # both fields.toon metadata and the strict-read rule.
    _POLY_SEP = '|'

    def split_objects(self):
        """Split each object into up to 7 small focused TOON files.

        See `_emit_object_files` for the per-object file layout.
        """
        print("\n" + "=" * 80)
        print("Splitting Objects into Folder Structure (7-file layout)")
        print("=" * 80)

        objects_dir = self.output_dir / 'objects'
        success_count = 0
        for obj in self.objects:
            obj_name = obj.get('api_name', 'Unknown')
            try:
                obj_folder = objects_dir / obj_name
                obj_folder.mkdir(parents=True, exist_ok=True)
                # Drop any leftover files from the previous (1-3 file) layout
                # so a stale file never confuses an AI agent.
                for legacy in obj_folder.glob('*.toon'):
                    legacy.unlink()
                self._emit_object_files(obj_folder, obj)
                success_count += 1
                if success_count % 50 == 0:
                    print(f"  Progress: {success_count}/{len(self.objects)} objects...")
            except Exception as e:
                print(f"✗ Error creating files for {obj_name}: {e}")

        print(f"✓ Created {success_count} object folders")
        return True

    def _emit_object_files(self, obj_folder, obj):
        """Emit the per-object file set.

        Layout (all relative to <object-folder>/):
          - schema.toon              ALWAYS — slim index: object meta + counts + file pointers
          - fields.toon              ALWAYS — single tabular block; lookups carry reference_path
          - record_types.toon        only if record_types is non-empty
          - validation_rules.toon    only if validation_rules is non-empty
          - related_relationships.toon  only if there's at least one incoming reference
          - picklists.toon           only if any field has picklist_values OR multipicklist_values
          - formulas.toon            only if any field has a formula
        """
        obj_name = obj.get('api_name', 'Unknown')
        raw_fields = obj.get('fields', []) or []
        record_types = obj.get('record_types', []) or []
        validation_rules = obj.get('validation_rules', []) or []
        related_rels = self._get_relationships_for_object(obj_name)

        single_picklists, multipicklists, formulas, core_fields = self._partition_field_metadata(raw_fields)
        any_picklists = bool(single_picklists) or bool(multipicklists)

        # Generated-at stamp shared across this object's files
        gen_date = datetime.now().isoformat()
        files_present = {
            'fields': 'fields.toon',
            'record_types': 'record_types.toon' if record_types else None,
            'validation_rules': 'validation_rules.toon' if validation_rules else None,
            'related_relationships': 'related_relationships.toon' if related_rels else None,
            'picklists': 'picklists.toon' if any_picklists else None,
            'formulas': 'formulas.toon' if formulas else None,
        }

        self._emit_schema_index_file(
            obj_folder, obj, gen_date,
            counts={
                'fields': len(core_fields),
                'record_types': len(record_types),
                'validation_rules': len(validation_rules),
                'related_relationships': len(related_rels),
                'picklists': len(single_picklists),
                'multipicklists': len(multipicklists),
                'formulas': len(formulas),
            },
            files_present=files_present,
        )
        self._emit_fields_file(obj_folder, obj_name, core_fields, gen_date)
        if record_types:
            self._emit_record_types_file(obj_folder, obj_name, record_types, gen_date)
        if validation_rules:
            self._emit_validation_rules_file(obj_folder, obj_name, validation_rules, gen_date)
        if related_rels:
            self._emit_related_relationships_file(obj_folder, obj_name, related_rels, gen_date)
        if any_picklists:
            self._emit_picklists_file(obj_folder, obj_name, single_picklists, multipicklists, gen_date)
        if formulas:
            self._emit_formulas_file(obj_folder, obj_name, formulas, gen_date)

    def _emit_schema_index_file(self, obj_folder, obj, gen_date, counts, files_present):
        schema_data = {
            'object': {
                'api_name': obj.get('api_name'),
                'type': obj.get('type'),
                'label': obj.get('label'),
                'description': obj.get('description'),
            },
            'counts': counts,
            'files': files_present,
            'metadata': {
                'split_from': str(self.input_file),
                'generated_date': gen_date,
                'original_schema_date': self.metadata.get('generated_date', ''),
                'layout_version': 2,
            },
        }
        dump_toon(schema_data, obj_folder / 'schema.toon')

    def _emit_fields_file(self, obj_folder, obj_name, core_fields, gen_date):
        """Delegate to the shared `_fields_tabular.emit_fields_file`."""
        emit_fields_tabular(
            output_file=obj_folder / 'fields.toon',
            obj_name=obj_name,
            fields=core_fields,
            present_objects=self._present_objects_set(),
            gen_date=gen_date,
        )

    def _present_objects_set(self):
        """Cached set of object api_names known in this schema build."""
        if not hasattr(self, '_present_objects_cache'):
            self._present_objects_cache = {o.get('api_name') for o in self.objects}
        return self._present_objects_cache

    # Canonical column order for record_types tabular block.
    _RECORDTYPE_COLUMNS = ('api_name', 'label', 'description', 'active')

    def _emit_record_types_file(self, obj_folder, obj_name, record_types, gen_date):
        """Emit record_types.toon. Normalises every row to the same key
        set so TOON keeps it as a tabular `record_types[N]{...}:` block
        — without normalisation, a missing `description` on any one row
        causes the encoder to fall back to verbose expanded list form."""
        normalised = [self._normalise_recordtype_row(rt) for rt in record_types]
        rt_data = {
            'record_types': normalised,
            'metadata': {
                'object': obj_name,
                'generated_date': gen_date,
                'record_type_count': len(record_types),
                'usage_status': 'not_collected',
                'usage_not_collected_reason': 'pending',
            },
        }
        dump_toon(rt_data, obj_folder / 'record_types.toon')

    def _normalise_recordtype_row(self, rt):
        """Pad missing keys with empty string and stringify booleans so
        TOON tabular keeps a uniform column type across all rows."""
        out = {}
        for k in self._RECORDTYPE_COLUMNS:
            v = rt.get(k, '')
            if v is None:
                v = ''
            if isinstance(v, bool):
                v = 'true' if v else 'false'
            else:
                v = str(v) if v != '' else ''
            out[k] = v
        return out

    def _emit_validation_rules_file(self, obj_folder, obj_name, validation_rules, gen_date):
        vr_data = {
            'validation_rules': validation_rules,
            'metadata': {
                'object': obj_name,
                'generated_date': gen_date,
                'validation_rule_count': len(validation_rules),
            },
        }
        dump_toon(vr_data, obj_folder / 'validation_rules.toon')

    def _emit_related_relationships_file(self, obj_folder, obj_name, related_rels, gen_date):
        rr_data = {
            'related_relationships': related_rels,
            'metadata': {
                'object': obj_name,
                'generated_date': gen_date,
                'related_relationship_count': len(related_rels),
            },
        }
        dump_toon(rr_data, obj_folder / 'related_relationships.toon')

    def _emit_picklists_file(
        self, obj_folder, obj_name, single_picklists, multipicklists, gen_date,
    ):
        """Write picklists.toon with two top-level blocks:
          - `picklists:` — single-select picklist fields (countable via SOQL GROUP BY)
          - `multipicklists:` — multi-select picklist fields (NOT countable)

        Each picklist sub-block is rendered as a tabular `values[N]{label,value}:`
        block at Step 8 time (no count column). Step 10 may later upgrade
        the `picklists:` block to `values[N]{label,value,count}:` form when
        live counts are merged in. The `multipicklists:` block always stays
        in `{label,value}` form — multi-select picklists cannot be GROUP BY'd
        in SOQL, so per-value counts are unobtainable.

        Each value-row carries BOTH `label` (display text) and `value`
        (API/DB string) so AI agents and humans can immediately see the
        difference (e.g. value=PCP, label=Primary Care Physician).
        """
        doc = {}
        if single_picklists:
            doc['picklists'] = self._build_picklist_block(single_picklists)
        if multipicklists:
            doc['multipicklists'] = self._build_picklist_block(multipicklists)
        meta = {
            'object': obj_name,
            'generated_date': gen_date,
            'picklist_count': len(single_picklists),
            'multipicklist_count': len(multipicklists),
            'multipicklists_usage_status': 'not_applicable',
        }
        if single_picklists:
            meta['picklists_usage_status'] = 'not_collected'
            meta['picklists_usage_not_collected_reason'] = 'pending'
        else:
            # Object has only multi-select picklists; no single-select block exists.
            meta['picklists_usage_status'] = 'not_applicable'
        doc['metadata'] = meta
        dump_toon(doc, obj_folder / 'picklists.toon')

    def _build_picklist_block(self, fields_to_pairs):
        """Convert {field_name: [{value,label}, ...]} into the per-field
        sub-block shape consumed by TOON's tabular encoder.

        Each value: `{'values': [{'label': 'X', 'value': 'X'}, ...]}`
        which TOON emits as `values[N]{label,value}:` rows.
        """
        out = {}
        for field_name, pairs in fields_to_pairs.items():
            rows = []
            for entry in pairs:
                if isinstance(entry, dict):
                    v = entry.get('value', '')
                    l = entry.get('label') if entry.get('label') not in (None, '') else v
                else:
                    # Defensive: legacy bare-string values get label = value.
                    v = entry
                    l = entry
                rows.append({'label': l, 'value': v})
            out[field_name] = {'values': rows}
        return out

    def _emit_formulas_file(self, obj_folder, obj_name, formulas, gen_date):
        formulas_data = {
            'formulas': formulas,
            'metadata': {
                'object': obj_name,
                'generated_date': gen_date,
                'formula_count': len(formulas),
            },
        }
        dump_toon(formulas_data, obj_folder / 'formulas.toon')

    # ------------------------------------------------------------------
    # Field metadata partition + relationships fan-in
    # ------------------------------------------------------------------

    def _get_relationships_for_object(self, obj_name):
        """Return all relationships in which this object is FROM or TO."""
        related = []
        for rel in self.relationships:
            if rel.get('from_object') == obj_name or rel.get('to_object') == obj_name:
                related.append(rel)
        return related

    def _partition_field_metadata(self, fields):
        """Pull picklist_values + formula out of every field; the field
        kept in fields.toon never carries either of them.

        Single-select picklists (`Picklist`) and multi-select picklists
        (`MultiselectPicklist`) are returned in SEPARATE dicts so they
        can be emitted into different top-level blocks of picklists.toon.

        Returns (single_picklists_dict, multipicklists_dict, formulas_dict,
        core_fields_list). Each picklist dict maps field_name -> list of
        {value, label} dicts. Bare-string `picklist_values` (legacy
        intermediate shape) are defensively upgraded to {value:s, label:s}.
        """
        single_picklists = {}
        multipicklists = {}
        formulas = {}
        core_fields = []

        for field in fields:
            field_name = field.get('api_name', '')
            field_type = field.get('type')
            core_field = {k: v for k, v in field.items()
                          if k not in self._FIELDS_FILE_EXCLUDE_KEYS}

            raw = field.get('picklist_values')
            if raw:
                pairs = []
                for entry in raw:
                    if isinstance(entry, dict):
                        v = entry.get('value', '')
                        l = entry.get('label') if entry.get('label') not in (None, '') else v
                    else:
                        # Legacy bare-string entries — preserve as label==value.
                        v = entry
                        l = entry
                    pairs.append({'value': v, 'label': l})
                if field_type == 'MultiselectPicklist':
                    multipicklists[field_name] = pairs
                else:
                    single_picklists[field_name] = pairs

            if 'formula' in field and field['formula']:
                formulas[field_name] = field['formula']

            core_fields.append(core_field)

        return single_picklists, multipicklists, formulas, core_fields
    
    def create_index(self):
        """Create master index file (TOON)."""
        print("\n" + "=" * 80)
        print("Creating Master Index")
        print("=" * 80)

        index_file = self.output_dir / '_index.toon'

        index_data = {
            'schema_index': {
                'metadata': {
                    'generated_date': datetime.now().isoformat(),
                    'total_objects': len(self.objects),
                    'source_file': str(self.input_file),
                    'objects_directory': 'objects/',
                    'categories_directory': 'categories/',
                    'layout_version': 2,
                    'structure': (
                        'Each object has a folder with up to 7 files: '
                        'schema.toon (always; thin index), fields.toon (always; tabular), '
                        'record_types.toon, validation_rules.toon, related_relationships.toon, '
                        'picklists.toon, formulas.toon (last 5 are optional). '
                        'Lookup fields in fields.toon include a reference_path cell '
                        'pointing at the parent object schema.toon.'
                    ),
                },
                'companion_files': {
                    '_search_index.toon': 'Lightweight cross-object field index',
                    '_junctions.toon': 'Detected junction objects with parents + record counts (Step 11; may be missing if Step 11 has not been run)',
                    'ER.md (project root)': 'Mermaid ER diagram of every detected junction (Step 12)',
                },
                'objects': [],
            },
        }

        for obj in sorted(self.objects, key=lambda x: x.get('api_name', '')):
            obj_name = obj.get('api_name', '')
            fields = obj.get('fields', [])
            record_types = obj.get('record_types', []) or []
            validation_rules = obj.get('validation_rules', []) or []
            related_rels = self._get_relationships_for_object(obj_name)

            has_picklists = any('picklist_values' in f and f['picklist_values'] for f in fields)
            has_formulas = any('formula' in f and f['formula'] for f in fields)

            obj_entry = {
                'api_name': obj_name,
                'label': obj.get('label', obj_name),
                'type': obj.get('type', 'Unknown'),
                'folder': f"objects/{obj_name}/",
                'files': {
                    'schema': f"objects/{obj_name}/schema.toon",
                    'fields': f"objects/{obj_name}/fields.toon",
                    'record_types': f"objects/{obj_name}/record_types.toon" if record_types else None,
                    'validation_rules': f"objects/{obj_name}/validation_rules.toon" if validation_rules else None,
                    'related_relationships': f"objects/{obj_name}/related_relationships.toon" if related_rels else None,
                    'picklists': f"objects/{obj_name}/picklists.toon" if has_picklists else None,
                    'formulas': f"objects/{obj_name}/formulas.toon" if has_formulas else None,
                },
                'counts': {
                    'fields': len(fields),
                    'record_types': len(record_types),
                    'validation_rules': len(validation_rules),
                    'related_relationships': len(related_rels),
                    'picklists': sum(
                        1 for f in fields
                        if f.get('picklist_values') and f.get('type') != 'MultiselectPicklist'
                    ),
                    'multipicklists': sum(
                        1 for f in fields
                        if f.get('picklist_values') and f.get('type') == 'MultiselectPicklist'
                    ),
                    'formulas': sum(1 for f in fields if f.get('formula')),
                },
            }

            key_fields = []
            for field in fields[:10]:
                field_name = field.get('api_name', '')
                field_type = field.get('type', '')
                if field_name and field_type:
                    key_fields.append(f"{field_name} ({field_type})")

            if key_fields:
                obj_entry['sample_fields'] = key_fields

            index_data['schema_index']['objects'].append(obj_entry)

        try:
            dump_toon(index_data, index_file)
            print(f"✓ Created master index: {index_file}")
            print(f"  Contains {len(index_data['schema_index']['objects'])} object entries")
            return True

        except Exception as e:
            print(f"✗ Error creating index: {e}")
            return False
    
    def create_search_index(self):
        """Create lightweight search index with field metadata
        (no picklist values; references the per-object files instead)."""
        print("\n" + "=" * 80)
        print("Creating Search Index")
        print("=" * 80)

        search_index_file = self.output_dir / '_search_index.toon'

        search_data = {
            'search_index': {
                'metadata': {
                    'generated_date': datetime.now().isoformat(),
                    'description': 'Lightweight index for searching objects and fields across the org',
                    'layout_version': 2,
                    'usage': (
                        'Use this to quickly find objects and their key fields. '
                        'For complete field definitions read objects/<ObjectName>/fields.toon. '
                        'For picklist values: objects/<ObjectName>/picklists.toon. '
                        'For RecordTypes: objects/<ObjectName>/record_types.toon.'
                    ),
                },
                'objects': {},
            },
        }

        for obj in self.objects:
            obj_name = obj.get('api_name', '')
            fields_list = []

            has_picklists = False
            has_formulas = False

            for field in obj.get('fields', []):
                field_info = {
                    'name': field.get('api_name', ''),
                    'type': field.get('type', ''),
                    'required': field.get('required', False)
                }

                if 'picklist_values' in field and field['picklist_values']:
                    field_info['has_picklist_values'] = True
                    has_picklists = True

                if 'formula' in field and field['formula']:
                    field_info['has_formula'] = True
                    has_formulas = True

                if 'reference_to' in field:
                    field_info['reference_to'] = field['reference_to']

                if 'length' in field:
                    field_info['length'] = field['length']

                fields_list.append(field_info)

            record_types = obj.get('record_types', []) or []
            validation_rules = obj.get('validation_rules', []) or []
            related_rels = self._get_relationships_for_object(obj_name)
            search_data['search_index']['objects'][obj_name] = {
                'type': obj.get('type', 'Unknown'),
                'label': obj.get('label', obj_name),
                'folder': f"objects/{obj_name}/",
                'files': {
                    'schema': f"objects/{obj_name}/schema.toon",
                    'fields': f"objects/{obj_name}/fields.toon",
                    'record_types': f"objects/{obj_name}/record_types.toon" if record_types else None,
                    'validation_rules': f"objects/{obj_name}/validation_rules.toon" if validation_rules else None,
                    'related_relationships': f"objects/{obj_name}/related_relationships.toon" if related_rels else None,
                    'picklists': f"objects/{obj_name}/picklists.toon" if has_picklists else None,
                    'formulas': f"objects/{obj_name}/formulas.toon" if has_formulas else None,
                },
                'fields': fields_list,
            }

        try:
            dump_toon(search_data, search_index_file)
            print(f"✓ Created search index: {search_index_file}")
            return True

        except Exception as e:
            print(f"✗ Error creating search index: {e}")
            return False
    
    def create_categorized_schemas(self):
        """Create categorized schema files."""
        print("\n" + "=" * 80)
        print("Creating Categorized Schemas")
        print("=" * 80)
        
        categories_dir = self.output_dir / 'categories'
        
        # Auto-categorize objects
        categorized = defaultdict(list)
        
        for obj in self.objects:
            obj_name = obj.get('api_name', '')

            # 1) Predefined standard-Salesforce categories
            category_found = False
            for category, obj_list in self.CATEGORIES.items():
                if obj_name in obj_list:
                    categorized[category].append(obj)
                    category_found = True
                    break
            if category_found:
                continue

            # 2) Managed-package namespace -> ns_<namespace> (lowercased)
            ns = _detect_namespace(obj_name)
            if ns:
                categorized[f'ns_{ns.lower()}'].append(obj)
                continue

            # 3) Plain custom objects / metadata / events
            if obj_name.endswith(('__c', '__mdt', '__e', '__b', '__x')):
                categorized['custom'].append(obj)
                continue

            # 4) Everything else
            categorized['other'].append(obj)
        
        # Create category files
        for category, objects_list in categorized.items():
            if not objects_list:
                continue

            category_file = categories_dir / f"{category}.toon"

            category_data = {
                'category': category,
                'metadata': {
                    'generated_date': datetime.now().isoformat(),
                    'object_count': len(objects_list),
                    'description': f"Schema for {category} objects"
                },
                'objects': objects_list
            }

            try:
                dump_toon(category_data, category_file)
                print(f"✓ Created {category}.toon ({len(objects_list)} objects)")

            except Exception as e:
                print(f"✗ Error creating category file {category}: {e}")

        return True
    
    def create_readme(self):
        """Create README file explaining the schema structure."""
        print("\n" + "=" * 80)
        print("Creating README")
        print("=" * 80)
        
        readme_file = self.output_dir / 'README.md'
        
        readme_content = """# Salesforce Schema Reference

This directory contains the org's schema split into small, focused TOON
files for AI agent consumption. The strict reading sequence (which file
to open for what task) is enforced by the always-applied rule
[`.cursor/rules/salesforce-schema-validation.mdc`](../../.cursor/rules/salesforce-schema-validation.mdc) —
read that rule once and follow it every time.

> **Format:** TOON (Token-Oriented Object Notation, v3.0). All files in
> this directory are TOON-encoded — see
> [`https://github.com/toon-format/spec`](https://github.com/toon-format/spec)
> for the grammar. TOON encodes the JSON data model with explicit array
> lengths and a single tabular block per uniform array, achieving
> 30-60% token reduction vs JSON / YAML while staying human-readable.
> TOON has no comment syntax, so each document embeds a `metadata:`
> block at the bottom instead of a header banner.

## Layout (per object: 7 files max)

```
config/schema/
├── _index.toon                  # Master index of every object + companion files
├── _search_index.toon           # Lightweight cross-object field search
├── _junctions.toon              # Detected junctions + parent FKs + record counts (Step 11)
├── objects/<ObjectName>/
│   ├── schema.toon              # ALWAYS — slim index: object meta, counts, file pointers
│   ├── fields.toon              # ALWAYS — every field as one tabular row; lookups link to parent schema.toon
│   ├── record_types.toon        # only if record_types is non-empty
│   ├── validation_rules.toon    # only if validation_rules is non-empty
│   ├── related_relationships.toon  # only if there's at least one incoming reference
│   ├── picklists.toon           # only if any field has picklist values
│   └── formulas.toon            # only if any field is a calculated formula
└── categories/                  # Objects grouped by category
    ├── core.toon                # Account, Contact, Lead, User, Group, Profile
    ├── sales.toon               # Opportunity, Quote, Order, Product2, ...
    ├── service.toon             # Case, Entitlement, WorkOrder, ...
    ├── ns_<namespace>.toon      # One file per managed-package namespace (auto-detected)
    ├── custom.toon              # Plain custom (__c) objects with no namespace
    └── other.toon               # Everything else

ER.md (project root)             # Mermaid ER diagram of every detected junction (Step 12)
```

## Reading rules (the strict sequence)

The full enforceable version lives in
[`.cursor/rules/salesforce-schema-validation.mdc`](../../.cursor/rules/salesforce-schema-validation.mdc)
(`alwaysApply: true`). Summary:

1. ALWAYS open `schema.toon` first — it is the slim index. It tells you
   what other files exist for this object and how many entries each
   contains.
2. Open `fields.toon` whenever you reference a field by name, type, or
   constraint. It is one tabular block: one row per field, columns are
   the union of every key any field uses on this object. Empty cells
   mean "not applicable" (encoded as the empty string).
3. For every Lookup / MasterDetail row in `fields.toon`, the
   `reference_path` cell contains the relative path to the parent
   object's `schema.toon`. Open that file to traverse — never guess
   what the parent looks like.
4. Open `picklists.toon` whenever you reference a Picklist or
   MultiselectPicklist field — read or write. See "Field-driven
   mandatory reads" and "Count interpretation" below.
5. Open `record_types.toon` whenever you reference RecordTypeId or set
   RecordType behavior on an object. Use `api_name` (DeveloperName) at
   runtime; never hardcode the Id.
6. Open `validation_rules.toon` only after a deploy fails on a
   validation error.
7. Open `related_relationships.toon` to traverse parent → child (i.e. to
   answer "what objects point AT this one").
8. Open `formulas.toon` only when a calculated field's behavior is
   surprising.
9. For cross-object relationships at a glance, read
   [`_junctions.toon`](_junctions.toon) (programmatic) or
   [`../../ER.md`](../../ER.md) (mermaid).

## Field-driven mandatory reads

Whenever you SEE one of these on a row in `fields.toon`, you MUST open
the named file BEFORE writing or referencing that field in any way
(read or write):

| Field shape | MUST open |
|---|---|
| `type: Picklist` | `picklists.toon` — find the field name in the `picklists:` block. NEVER use a value not listed there. |
| `type: MultiselectPicklist` | `picklists.toon` — find the field name in the `multipicklists:` block. NEVER use a value not listed there. |
| `api_name: RecordTypeId` | `record_types.toon` — use `api_name` (DeveloperName) at runtime. Never hardcode the Id. |
| `type: Lookup` or `MasterDetail` | follow the `reference_path` cell to the parent's `schema.toon` and re-enter from the top. |

The full enforceable version of this trigger table lives in the
always-applied rule [`.cursor/rules/salesforce-schema-validation.mdc`](../../.cursor/rules/salesforce-schema-validation.mdc).

## File shapes

### `schema.toon` (slim index, always present)

```
object:
  api_name: <ObjectApiName>
  type: Standard|Custom|CustomMetadata|PlatformEvent
  label: <Object Label>
  description: <Object description or empty>
counts:
  fields: <N>
  record_types: <N>
  validation_rules: <N>
  related_relationships: <N>
  picklists: <N>          # number of fields that have picklist values
  formulas: <N>           # number of calculated fields
files:
  fields: fields.toon     # always present
  record_types: record_types.toon | null
  validation_rules: validation_rules.toon | null
  related_relationships: related_relationships.toon | null
  picklists: picklists.toon | null
  formulas: formulas.toon | null
metadata:
  generated_date: <ISO8601>
  layout_version: 2
```

### `fields.toon` (one tabular block, lookups linked to parent)

```
fields[N]{api_name,type,label,help_text,required,unique,external_id,length,precision,scale,reference_to,reference_path,relationship_name,delete_constraint,default_value,description,controlling_field}:
  AccountId,Lookup,Account ID,Account associated with this record.,false,false,false,18,,,Account,objects/Account/schema.toon,,,,,
  Name,Text,Name,Display name.,true,false,false,80,,,,,,,,,
  OwnerId,Lookup,Owner ID,,false,false,false,,,,Group|User,objects/Group/schema.toon|objects/User/schema.toon,,,,,
metadata:
  object: <ObjectApiName>
  field_count: <N>
  null_encoding: empty_string
  polymorphic_separator: "|"
```

Encoding rules:
- Polymorphic `reference_to` (multi-target) is pipe-separated. The
  parallel `reference_path` cell is also pipe-separated, slot-aligned
  with `reference_to`.
- Missing values are empty strings (TOON tabular requires every row to
  carry every column).
- All cells are primitives (no nested arrays / objects in cells).

### `picklists.toon` — two blocks, value + label always paired

`picklists.toon` carries TWO top-level blocks:

- `picklists:` — single-select picklist fields. Countable via SOQL `GROUP BY`.
- `multipicklists:` — multi-select picklist fields. NOT countable (no per-value counts ever).

Every value-row in either block has BOTH `label` (display text users see) and `value` (the API/DB string). They commonly differ (`value: PCP`, `label: Primary Care Physician`); use `value` in code/SOQL/DML and `label` for display.

When usage counts are available for the `picklists:` block (Step 10 has run):

```
picklists:
  Status:
    values[2]{label,value,count}:
      Open,Open,3421
      Closed,Closed,1892
  PRM_PractitionerRole__c:
    values[3]{label,value,count}:
      Primary Care Physician,PCP,897
      Specialist,Specialist,514
      Dual,Dual,215
multipicklists:
  Tags:
    values[3]{label,value}:
      Tag A,tag_a
      Tag B,tag_b
      Tag C,tag_c
metadata:
  object: <ObjectApiName>
  picklist_count: 2
  multipicklist_count: 1
  picklists_usage_status: live_counts
  multipicklists_usage_status: not_applicable
  picklists_usage_collected_date: <ISO8601>
```

When usage counts are NOT available for the `picklists:` block (Step 10 hasn't run yet, or queries failed):

```
picklists:
  Status:
    values[2]{label,value}:
      Open,Open
      Closed,Closed
multipicklists:
  Tags:
    values[3]{label,value}:
      Tag A,tag_a
      Tag B,tag_b
      Tag C,tag_c
metadata:
  object: <ObjectApiName>
  picklist_count: 1
  multipicklist_count: 1
  picklists_usage_status: not_collected
  picklists_usage_not_collected_reason: pending  # or no_query_access / empty_object / query_error
  multipicklists_usage_status: not_applicable
```

The inline `[N]: a,b,c` form is RETIRED entirely — every picklist sub-block is tabular so `label` and `value` are always visible. The `multipicklists:` block is always inline-equivalent (`{label,value}` form, no count column ever) because SOQL cannot `GROUP BY` a multi-select picklist field.

### `record_types.toon` — every row already has api_name + label + count

`api_name` is the DeveloperName — the stable identifier you use in Apex (`Schema.SObjectType.X.getRecordTypeInfosByDeveloperName().get('<api_name>').getRecordTypeId()`). Treat `api_name` as the "value" half of the value+label pair.

When usage counts are available (Step 10 has run):

```
record_types[N]{api_name,label,description,active,record_count}:
  StandardRecordType,Standard Record Type,...,true,1248
  DeprecatedRT,Deprecated RT,...,true,0
  ...
metadata:
  object: <ObjectApiName>
  record_type_count: <N>
  usage_status: live_counts
  record_type_counts_collected_date: <ISO8601>
```

When usage counts are NOT available:

```
record_types[N]{api_name,label,description,active}:
  StandardRecordType,Standard Record Type,...,true
  ...
metadata:
  object: <ObjectApiName>
  record_type_count: <N>
  usage_status: not_collected
  usage_not_collected_reason: pending  # or no_query_access / empty_object / query_error
```

## Count interpretation (the only sanctioned reading)

`metadata.picklists_usage_status` (in picklists.toon) and `metadata.usage_status` (in record_types.toon) carry the same enum:

- `live_counts` — count column is present and reflects real org counts as of `*_collected_date`.
  - `count: 0` (or `record_count: 0`) means the value/RecordType is DECLARED but ZERO records use it. Treat as deprecated unless seeding a brand-new picklist/RecordType.
  - `count > 0` (or `record_count > 0`) means the value is in active use.
- `not_collected` — count column is absent. NEVER infer "deprecated" from absence of a count. `*_not_collected_reason` (optional) explains: `pending` (Step 10 hasn't run), `no_query_access` (the org user can't query), `empty_object` (object has 0 records), `query_error` (other SOQL failure).
- `not_applicable` — only on picklists.toon's `picklists_usage_status` when there are no single-select picklists, OR on `multipicklists_usage_status` always (multi-select picklists can't be counted via SOQL).

To refresh stale counts: `python3 scripts/schemapy/auto_generate_schema.py` (full pipeline ~50 min) or `python3 scripts/schemapy/collect_usage_stats.py --org <alias> --objects <ObjA>,<ObjB>` (targeted, fast).

### `validation_rules.toon`

```
validation_rules[N]{name,active,description,error_condition_formula,error_message}:
  ...
metadata:
  object: <ObjectApiName>
  validation_rule_count: <N>
```

### `related_relationships.toon`

```
related_relationships[N]{from_object,from_field,to_object,relationship_type,relationship_name,delete_constraint}:
  ChildObject,ParentLookupField,<ObjectApiName>,Lookup,ChildRelName,SetNull
  ...
metadata:
  object: <ObjectApiName>
  related_relationship_count: <N>
```

### `formulas.toon`

```
formulas:
  FieldApiName: <formula expression as TOON-quoted string>
metadata:
  object: <ObjectApiName>
  formula_count: <N>
```

## Companion files (cross-object artifacts)

- [`_index.toon`](_index.toon): every object with `files: { ... }` block
  pointing at all 7 files (with `null` for missing optional ones).
- [`_search_index.toon`](_search_index.toon): lightweight cross-object
  field index for fuzzy lookups.
- [`_junctions.toon`](_junctions.toon): every detected junction object,
  its parent FKs, record counts, confidence tier, and an auto-derived
  one-line note. See Step 11 (`scripts/schemapy/detect_junctions.py`).
- [`../../ER.md`](../../ER.md): mermaid ER of every junction grouped by
  confidence. Read this first when modelling new relationships.

## File-size profile

- `schema.toon`: ~10-25 lines (always small)
- `fields.toon`: ~1 + N + 5 lines, dominated by N (one row per field)
- `record_types.toon`: ~1 + N + 4 lines (rare, usually small)
- `validation_rules.toon`: ~1 + N + 4 lines
- `related_relationships.toon`: ~1 + N + 4 lines
- `picklists.toon`: variable; smaller when usage counts merge same-line
- `formulas.toon`: ~1 + N + 4 lines

This 7-file split typically yields 70-90% fewer lines per object than
the prior single-`schema.toon` layout, because field metadata is no
longer repeated key-by-key on every row.

## Regeneration

This schema is auto-generated. To regenerate:

```bash
# Full regeneration (retrieves from org + generates schema + splits)
python3 scripts/schemapy/auto_generate_schema.py

# Just re-split existing schema
python3 scripts/schemapy/split_schema_by_object.py
```

Install Python dependencies first if needed:

```bash
pip install -r scripts/schemapy/requirements.txt
```

## Metadata

"""
        
        readme_content += f"- **Generated:** {datetime.now().isoformat()}\n"
        readme_content += f"- **Total Objects:** {len(self.objects)}\n"
        readme_content += f"- **Source:** {self.input_file}\n"
        readme_content += f"- **Format:** TOON (Token-Oriented Object Notation, v3.0)\n"
        readme_content += f"- **Layout version:** 2 (7-file split with tabular `fields.toon`)\n"
        
        try:
            with open(readme_file, 'w', encoding='utf-8') as f:
                f.write(readme_content)
            
            print(f"✓ Created README: {readme_file}")
            return True
            
        except Exception as e:
            print(f"✗ Error creating README: {e}")
            return False
    
    def run(self):
        """Main execution."""
        print("\n")
        print("╔" + "=" * 78 + "╗")
        print("║" + " " * 20 + "Schema Optimizer & Splitter" + " " * 32 + "║")
        print("║" + " " * 15 + "Making Large Schemas AI-Friendly" + " " * 33 + "║")
        print("╚" + "=" * 78 + "╝")
        print()
        
        # Load schema
        if not self.load_schema():
            return False
        
        # Create directories
        if not self.create_directories():
            return False
        
        # Split objects
        if not self.split_objects():
            return False
        
        # Create index
        if not self.create_index():
            return False
        
        # Create search index
        if not self.create_search_index():
            return False
        
        # Create categorized schemas
        if not self.create_categorized_schemas():
            return False
        
        # Create README
        if not self.create_readme():
            return False
        
        # Success summary
        total_with_picklists = sum(1 for obj in self.objects if any('picklist_values' in f and f['picklist_values'] for f in obj.get('fields', [])))
        total_with_formulas = sum(1 for obj in self.objects if any('formula' in f and f['formula'] for f in obj.get('fields', [])))
        total_with_recordtypes = sum(1 for obj in self.objects if obj.get('record_types'))
        total_with_validation = sum(1 for obj in self.objects if obj.get('validation_rules'))
        total_with_relations = sum(1 for obj in self.objects if self._get_relationships_for_object(obj.get('api_name', '')))

        print("\n" + "=" * 80)
        print("✓ SCHEMA SPLIT COMPLETE (7-file layout)")
        print("=" * 80)
        print()
        print("Summary:")
        print(f"  - Input file: {self.input_file}")
        print(f"  - Output directory: {self.output_dir}")
        print(f"  - Objects split: {len(self.objects)}")
        print(f"  - Per-object files written: schema.toon + fields.toon ALWAYS, others when present")
        print(f"  - Objects with record_types: {total_with_recordtypes}")
        print(f"  - Objects with validation_rules: {total_with_validation}")
        print(f"  - Objects with related_relationships: {total_with_relations}")
        print(f"  - Objects with picklists: {total_with_picklists}")
        print(f"  - Objects with formulas: {total_with_formulas}")
        print(f"  - Category files: Created in categories/")
        print(f"  - Index files: _index.toon, _search_index.toon")
        print()
        print("File Structure per Object (all files TOON-encoded):")
        print("  - schema.toon                ALWAYS  thin index: meta + counts + file pointers")
        print("  - fields.toon                ALWAYS  one tabular block; lookups link to parent schema.toon")
        print("  - record_types.toon          if any  RecordTypes (api_name, label, description, active, record_count)")
        print("  - validation_rules.toon      if any  validation rules + error formulas")
        print("  - related_relationships.toon if any  incoming references (parent->child)")
        print("  - picklists.toon             if any  picklist values (+ counts after Step 10)")
        print("  - formulas.toon              if any  calculated field expressions")
        print()
        print("AI-agent reading sequence is enforced by the always-applied rule:")
        print("  .cursor/rules/salesforce-schema-validation.mdc")
        print()
        
        return True


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description='Split large Salesforce schema into optimized files for AI agents',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--input',
        help='Path to large schema file (default: <project-root>/config/salesforce-er-schema.toon)',
        type=str,
        default=None
    )

    parser.add_argument(
        '--output-dir',
        help='Path to output directory (default: <project-root>/config/schema)',
        type=str,
        default=None
    )

    args = parser.parse_args()
    if args.input is None or args.output_dir is None:
        root = find_project_root()
        if args.input is None:
            args.input = str(root / 'config' / 'salesforce-er-schema.toon')
        if args.output_dir is None:
            args.output_dir = str(root / 'config' / 'schema')
    
    optimizer = SchemaOptimizer(args.input, args.output_dir)
    
    try:
        success = optimizer.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
