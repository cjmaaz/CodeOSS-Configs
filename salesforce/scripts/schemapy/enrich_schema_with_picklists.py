#!/usr/bin/env python3
"""
Script to enrich Salesforce schema TOON files with picklist values and other metadata.

This script uses Salesforce CLI to extract complete field metadata including:
- Picklist values (ACTIVE ONLY - inactive values are excluded)
- Default values
- Field dependencies
- Controlling/dependent field relationships
- Formula definitions
- Validation rule details

IMPORTANT: Only ACTIVE picklist values are extracted to ensure AI agents
           and developers only use currently valid values.

Output format: TOON (Token-Oriented Object Notation, v3.0). The legacy
single-`.yaml`-file fallback was removed when the pipeline migrated to
TOON; this script now expects the per-object folder structure with
`schema.toon`, `picklists.toon`, `formulas.toon`.

WINDOWS COMPATIBLE: Properly resolves SF CLI path on Windows

Usage:
    # Enrich all objects (auto-detects org from .sf/config.json)
    python/python3 enrich_schema_with_picklists.py

    # Enrich all objects with explicit org
    python/python3 enrich_schema_with_picklists.py --org <your-org-alias>

    # Enrich specific objects
    python/python3 enrich_schema_with_picklists.py --objects Account,Contact,HealthcareProviderNpi

    # Dry run (show what would be changed)
    python/python3 enrich_schema_with_picklists.py --dry-run

Requirements:
    - Salesforce CLI (sf) installed
    - Authenticated org
    - Python deps: pip install -r scripts/schemapy/requirements.txt

Note: This script is automatically called by auto_generate_schema.py as Step 9.
"""

import subprocess
import json
import argparse
import platform
import shutil
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys

# Allow `from _toon_io import ...` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import dump_toon, load_toon, find_project_root  # noqa: E402
from _fields_tabular import (  # noqa: E402
    emit_fields_file as emit_fields_tabular,
    discover_present_objects_from_dir,
    POLY_SEP,
)

class SchemaEnricher:
    """Enriches Salesforce schema TOON files with complete metadata from org."""

    def __init__(self, org_alias: Optional[str] = None, schema_dir: Optional[str] = None):
        self.org_alias = org_alias or self._detect_org_alias()
        # Default schema_dir resolves against the project root (not cwd),
        # so the script works regardless of where it is invoked from.
        if schema_dir is None:
            schema_dir = str(find_project_root() / 'config' / 'schema' / 'objects')
        self.schema_dir = Path(schema_dir)
        self.sf_exe = self._resolve_sf()
        self.enrichment_stats = {
            'objects_processed': 0,
            'fields_enriched': 0,
            'picklists_added': 0,
            'formulas_added': 0,
            'validations_updated': 0,
            'errors': [],
            'picklist_files_created': 0,
            'formula_files_created': 0
        }
    
    def _resolve_sf(self) -> str:
        """
        Resolve the path to the sf executable, handling Windows nuances.
        Returns the full path to the sf executable.
        """
        exe = shutil.which('sf')
        if exe:
            print(f"✓ Found SF CLI: {exe}")
            return exe
        
        if platform.system() == 'Windows':
            # Common Windows install paths for sf
            candidates = [
                r'C:\Program Files\Salesforce CLI\bin\sf.cmd',
                r'C:\Program Files\sf\bin\sf.cmd',
                rf'{os.environ.get("USERPROFILE", "")}\AppData\Roaming\npm\sf.cmd',
                rf'{os.environ.get("LOCALAPPDATA", "")}\sf\bin\sf.cmd'
            ]
            for c in candidates:
                if c and os.path.isfile(c):
                    print(f"✓ Found SF CLI: {c}")
                    return c
        
        print("✗ Salesforce CLI (sf) not found. Install it or add it to PATH.")
        print("  See: https://developer.salesforce.com/tools/salesforcecli")
        sys.exit(1)
    
    def _detect_org_alias(self) -> str:
        """
        Automatically detect the target org from .sf/config.json or
        .sfdx/sfdx-config.json. Project root is resolved by walking up
        from this file's location, so the script works regardless of
        where it is invoked from.
        """
        project_root = find_project_root()

        # Try .sf/config.json (SF CLI v2)
        sf_config = project_root / '.sf' / 'config.json'
        if sf_config.exists():
            try:
                with open(sf_config, 'r') as f:
                    config = json.load(f)
                    org_alias = config.get('target-org')
                    if org_alias:
                        print(f"✓ Auto-detected org: {org_alias} (from .sf/config.json)")
                        return org_alias
            except Exception:
                pass
        
        # Try .sfdx/sfdx-config.json (legacy)
        sfdx_config = project_root / '.sfdx' / 'sfdx-config.json'
        if sfdx_config.exists():
            try:
                with open(sfdx_config, 'r') as f:
                    config = json.load(f)
                    org_alias = config.get('defaultusername')
                    if org_alias:
                        print(f"✓ Auto-detected org: {org_alias} (from .sfdx/sfdx-config.json)")
                        return org_alias
            except Exception:
                pass
        
        # Could not detect org
        print("✗ Could not auto-detect target org from .sf/config.json or .sfdx/sfdx-config.json")
        print("  Please either:")
        print("    1. Set a default org: sf config set target-org <your-org-alias>")
        print("    2. Provide --org parameter: python/python3 enrich_schema_with_picklists.py --org YourOrg")
        sys.exit(1)
    
    def get_object_metadata(self, object_name: str) -> Optional[Dict]:
        """
        Retrieve complete object metadata from Salesforce using CLI.
        
        SF CLI Commands Used:
        ---------------------
        # Method 1: Using describe (faster, JSON output)
        sf sobject describe --sobject <ObjectName> --target-org <org> --json
        
        # Method 2: Using metadata retrieve (more complete)
        sf project retrieve start --metadata CustomObject:<ObjectName> --target-org <org>
        
        Returns field metadata including:
        - type, label, length
        - picklist values (picklistValues[])
        - controlling/dependent fields
        - formula definitions
        - default values
        """
        try:
            # Use describe command for field-level metadata
            cmd = [
                self.sf_exe, 'sobject', 'describe',
                '--sobject', object_name,
                '--target-org', self.org_alias,
                '--json'
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=60  # 60 second timeout per object
            )
            metadata = json.loads(result.stdout)
            
            if metadata.get('status') == 0:
                return metadata.get('result', {})
            else:
                self.enrichment_stats['errors'].append(f"{object_name}: {metadata.get('message')}")
                return None
                
        except subprocess.TimeoutExpired:
            self.enrichment_stats['errors'].append(f"{object_name}: Timeout after 60 seconds")
            return None
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            self.enrichment_stats['errors'].append(f"{object_name}: CLI error - {error_msg}")
            return None
        except json.JSONDecodeError as e:
            self.enrichment_stats['errors'].append(f"{object_name}: JSON parse error - {str(e)}")
            return None
        except FileNotFoundError:
            print(f"✗ Error: Could not find SF CLI executable: {self.sf_exe}")
            print("  Please ensure Salesforce CLI is installed and in your PATH")
            sys.exit(1)
        except Exception as e:
            self.enrichment_stats['errors'].append(f"{object_name}: Unexpected error - {str(e)}")
            return None
    
    def extract_picklist_values(self, field_metadata: Dict) -> Optional[List[Dict[str, str]]]:
        """
        Extract picklist values from field metadata as {value, label} dicts.

        IMPORTANT: Returns ONLY ACTIVE picklist values. Inactive values
        are excluded to prevent invalid data in code.

        Each entry preserves both `value` (the API/DB string used in code,
        SOQL, DML) and `label` (the display string users see in the UI).
        They commonly differ (e.g. `value: PCP`, `label: Primary Care
        Physician`) and AI agents should never assume they are the same.
        """
        if field_metadata.get('type') not in ['picklist', 'multipicklist']:
            return None

        picklist_values = field_metadata.get('picklistValues', [])

        active_pairs = []
        for pv in picklist_values:
            if not pv.get('active', True):
                continue
            v = pv.get('value', '')
            l = pv.get('label') if pv.get('label') not in (None, '') else v
            active_pairs.append({'value': v, 'label': l})

        return active_pairs if active_pairs else None
    
    def _extract_non_picklist_formula_metadata(self, field_metadata: Dict) -> Dict[str, Any]:
        """
        Extract field metadata EXCLUDING picklists and formulas.
        (Those are handled separately in the new structure)
        """
        enriched_field = {}
        
        # Basic field info
        field_type = field_metadata.get('type')
        
        # Default value
        if field_metadata.get('defaultValue'):
            enriched_field['default_value'] = field_metadata['defaultValue']
        
        # Field constraints
        if field_metadata.get('nillable') is False:
            enriched_field['required'] = True
        
        if field_metadata.get('unique'):
            enriched_field['unique'] = True
        
        if field_metadata.get('externalId'):
            enriched_field['external_id'] = True
        
        # Lookup relationship
        if field_type == 'reference':
            reference_to = field_metadata.get('referenceTo', [])
            if reference_to:
                enriched_field['reference_to'] = reference_to[0] if len(reference_to) == 1 else reference_to
        
        # Field dependencies (controlling/dependent picklists)
        if field_metadata.get('controllerName'):
            enriched_field['controlling_field'] = field_metadata['controllerName']
        
        if field_metadata.get('dependentPicklist'):
            enriched_field['is_dependent_picklist'] = True
        
        # Field length
        if field_metadata.get('length'):
            enriched_field['length'] = field_metadata['length']
        
        # Precision and scale (for numbers)
        if field_metadata.get('precision'):
            enriched_field['precision'] = field_metadata['precision']
        if field_metadata.get('scale'):
            enriched_field['scale'] = field_metadata['scale']
        
        # Help text
        if field_metadata.get('inlineHelpText'):
            enriched_field['help_text'] = field_metadata['inlineHelpText']
        
        # Description
        if field_metadata.get('label'):
            enriched_field['label'] = field_metadata['label']
        
        return enriched_field
    
    def extract_field_metadata(self, field_metadata: Dict) -> Dict[str, Any]:
        """
        Extract comprehensive field metadata including:
        - Picklist values
        - Default values
        - Formula definitions
        - Dependencies
        - Constraints (required, unique, externalId)
        """
        enriched_field = {}
        
        # Basic field info
        field_name = field_metadata.get('name')
        field_type = field_metadata.get('type')
        
        # Picklist values
        if field_type in ['picklist', 'multipicklist']:
            picklist_values = self.extract_picklist_values(field_metadata)
            if picklist_values:
                enriched_field['picklist_values'] = picklist_values
                self.enrichment_stats['picklists_added'] += 1
        
        # Default value
        if field_metadata.get('defaultValue'):
            enriched_field['default_value'] = field_metadata['defaultValue']
        
        # Formula
        if field_metadata.get('calculated') and field_metadata.get('calculatedFormula'):
            enriched_field['formula'] = field_metadata['calculatedFormula']
            self.enrichment_stats['formulas_added'] += 1
        
        # Field constraints
        if field_metadata.get('nillable') is False:
            enriched_field['required'] = True
        
        if field_metadata.get('unique'):
            enriched_field['unique'] = True
        
        if field_metadata.get('externalId'):
            enriched_field['external_id'] = True
        
        # Lookup relationship
        if field_type == 'reference':
            reference_to = field_metadata.get('referenceTo', [])
            if reference_to:
                enriched_field['reference_to'] = reference_to[0] if len(reference_to) == 1 else reference_to
        
        # Field dependencies (controlling/dependent picklists)
        if field_metadata.get('controllerName'):
            enriched_field['controlling_field'] = field_metadata['controllerName']
        
        if field_metadata.get('dependentPicklist'):
            enriched_field['is_dependent_picklist'] = True
        
        # Field length
        if field_metadata.get('length'):
            enriched_field['length'] = field_metadata['length']
        
        # Precision and scale (for numbers)
        if field_metadata.get('precision'):
            enriched_field['precision'] = field_metadata['precision']
        if field_metadata.get('scale'):
            enriched_field['scale'] = field_metadata['scale']
        
        # Help text
        if field_metadata.get('inlineHelpText'):
            enriched_field['help_text'] = field_metadata['inlineHelpText']
        
        # Description
        if field_metadata.get('label'):
            enriched_field['label'] = field_metadata['label']
        
        return enriched_field
    
    def enrich_object_schema(self, object_name: str, dry_run: bool = False) -> bool:
        """
        Enrich a single object's schema files with metadata from the org.

        New 7-file layout (Step 8 emitted these; we update them in place):
          - schema.toon          (slim index — only metadata.enriched_date is bumped)
          - fields.toon          (rewritten with describe-merged data, kept tabular)
          - picklists.toon       (created/updated with picklist values)
          - formulas.toon        (created/updated with formula definitions)
          - record_types.toon    (untouched here; Step 10 adds record_count)
          - validation_rules.toon (untouched)
          - related_relationships.toon (untouched)

        Returns True if successful, False otherwise.
        """
        obj_folder = self.schema_dir / object_name
        schema_file = obj_folder / 'schema.toon'
        fields_file = obj_folder / 'fields.toon'

        if not schema_file.exists():
            self.enrichment_stats['errors'].append(
                f"{object_name}: schema.toon not found at {schema_file}"
            )
            return False
        if not fields_file.exists():
            self.enrichment_stats['errors'].append(
                f"{object_name}: fields.toon not found at {fields_file} "
                "(re-run Step 8 to create the new 7-file layout)"
            )
            return False

        # Get metadata from Salesforce
        print(f"📡 Retrieving metadata for {object_name}...")
        org_metadata = self.get_object_metadata(object_name)
        if not org_metadata:
            return False

        # Load existing slim schema + tabular fields file.
        try:
            schema = load_toon(schema_file)
            fields_doc = load_toon(fields_file)
        except Exception as e:
            self.enrichment_stats['errors'].append(
                f"{object_name}: failed to load schema/fields: {e}"
            )
            return False

        if not isinstance(schema, dict) or not isinstance(fields_doc, dict):
            self.enrichment_stats['errors'].append(
                f"{object_name}: schema/fields are not TOON objects"
            )
            return False

        existing_rows: List[Dict[str, Any]] = list(fields_doc.get('fields') or [])

        # Build name -> describe-field map
        org_fields = {f['name']: f for f in org_metadata.get('fields', [])}

        # Walk existing rows and merge enrichment data into the per-row
        # dict. Picklist values + formulas land in their dedicated files,
        # not in fields.toon. Picklists are partitioned by type so that
        # picklists.toon's two-block split (picklists: vs multipicklists:)
        # is preserved on rewrite.
        single_picklists_data: Dict[str, List[Dict[str, str]]] = {}
        multipicklists_data: Dict[str, List[Dict[str, str]]] = {}
        formulas_data: Dict[str, str] = {}
        enriched_count = 0
        merged_rows: List[Dict[str, Any]] = []

        for row in existing_rows:
            row = dict(row)  # don't mutate the loaded dict in-place
            field_name = row.get('api_name')
            org_field = org_fields.get(field_name) if field_name else None

            if org_field:
                # Picklists — partition by single-select vs multi-select
                # so picklists.toon's two-block layout is preserved.
                org_type = org_field.get('type')
                if org_type in ('picklist', 'multipicklist'):
                    pv = self.extract_picklist_values(org_field)
                    if pv:
                        if org_type == 'multipicklist':
                            multipicklists_data[field_name] = pv
                        else:
                            single_picklists_data[field_name] = pv
                        self.enrichment_stats['picklists_added'] += 1
                        enriched_count += 1

                # Formulas
                if org_field.get('calculated') and org_field.get('calculatedFormula'):
                    formulas_data[field_name] = org_field['calculatedFormula']
                    self.enrichment_stats['formulas_added'] += 1
                    enriched_count += 1

                # Other enrichment (length, reference_to, help_text, ...)
                enriched_data = self._extract_non_picklist_formula_metadata(org_field)
                for key, value in enriched_data.items():
                    # In the tabular round-trip every cell is a string,
                    # so empty == "" not None. Treat both as missing.
                    current = row.get(key)
                    if current in (None, ''):
                        row[key] = value
                        enriched_count += 1

            merged_rows.append(row)

        self.enrichment_stats['fields_enriched'] += enriched_count
        any_picklists = bool(single_picklists_data) or bool(multipicklists_data)

        if dry_run:
            print(f"  [DRY RUN] Would enrich {enriched_count} cells in {object_name}.fields.toon")
            if any_picklists:
                print(
                    f"  [DRY RUN] Would create picklists.toon with "
                    f"{len(single_picklists_data)} single + {len(multipicklists_data)} multi picklists"
                )
            if formulas_data:
                print(f"  [DRY RUN] Would create formulas.toon with {len(formulas_data)} formulas")
            return True

        # Re-emit fields.toon via the shared tabular helper. This keeps
        # the file in canonical TOON tabular form (single block, padded
        # columns, computed reference_path for every Lookup / MasterDetail).
        present_objects = discover_present_objects_from_dir(self.schema_dir)
        gen_date = datetime.now().isoformat()
        emit_fields_tabular(
            output_file=fields_file,
            obj_name=object_name,
            fields=merged_rows,
            present_objects=present_objects,
            gen_date=gen_date,
        )

        # Bump enriched_date and refresh counts on the slim schema.toon.
        if 'metadata' not in schema:
            schema['metadata'] = {}
        schema['metadata']['enriched_date'] = gen_date
        if 'counts' not in schema:
            schema['counts'] = {}
        schema['counts']['fields'] = len(merged_rows)
        schema['counts']['picklists'] = len(single_picklists_data) or schema['counts'].get('picklists', 0)
        schema['counts']['multipicklists'] = len(multipicklists_data) or schema['counts'].get('multipicklists', 0)
        schema['counts']['formulas'] = len(formulas_data) or schema['counts'].get('formulas', 0)
        # Maintain file pointers — picklists/formulas may now exist where they didn't before.
        if 'files' not in schema:
            schema['files'] = {}
        if any_picklists:
            schema['files']['picklists'] = 'picklists.toon'
        if formulas_data:
            schema['files']['formulas'] = 'formulas.toon'
        dump_toon(schema, schema_file)

        # picklists.toon — two top-level blocks (picklists: single-select,
        # multipicklists: multi-select). Step 10 may later upgrade the
        # picklists: block to the `{label,value,count}` form when usage
        # counts are merged in. The multipicklists: block always stays
        # in `{label,value}` form (per-value counts are not obtainable
        # for multi-select picklists via SOQL).
        if any_picklists:
            self._write_picklists_file(
                obj_folder / 'picklists.toon',
                object_name,
                single_picklists_data,
                multipicklists_data,
                gen_date,
            )
            self.enrichment_stats['picklist_files_created'] += 1

        # Formulas.toon
        if formulas_data:
            formulas_file = obj_folder / 'formulas.toon'
            formulas_content = {
                'formulas': formulas_data,
                'metadata': {
                    'object': object_name,
                    'generated_date': gen_date,
                    'formula_count': len(formulas_data),
                },
            }
            dump_toon(formulas_content, formulas_file)
            self.enrichment_stats['formula_files_created'] += 1

        print(
            f"  ✅ Enriched {object_name}: {enriched_count} cell-updates, "
            f"{len(single_picklists_data)} picklists, "
            f"{len(multipicklists_data)} multipicklists, "
            f"{len(formulas_data)} formulas"
        )
        self.enrichment_stats['objects_processed'] += 1
        return True

    def _write_picklists_file(
        self,
        picklists_file: Path,
        obj_name: str,
        single_picklists: Dict[str, List[Dict[str, str]]],
        multipicklists: Dict[str, List[Dict[str, str]]],
        gen_date: str,
    ) -> None:
        """Write picklists.toon with the canonical two-block layout.

        Mirrors the shape emitted by Step 8 (`split_schema_by_object._emit_picklists_file`)
        so re-running Step 9 after Step 8 produces a structurally
        identical file (just with describe-derived data instead of
        XML-derived).
        """
        doc: Dict[str, Any] = {}
        if single_picklists:
            doc['picklists'] = {
                fname: {
                    'values': [
                        {'label': p.get('label') or p.get('value', ''),
                         'value': p.get('value', '')}
                        for p in pairs
                    ],
                }
                for fname, pairs in single_picklists.items()
            }
        if multipicklists:
            doc['multipicklists'] = {
                fname: {
                    'values': [
                        {'label': p.get('label') or p.get('value', ''),
                         'value': p.get('value', '')}
                        for p in pairs
                    ],
                }
                for fname, pairs in multipicklists.items()
            }
        meta = {
            'object': obj_name,
            'generated_date': gen_date,
            'picklist_count': len(single_picklists),
            'multipicklist_count': len(multipicklists),
            'multipicklists_usage_status': 'not_applicable',
            'note': 'Only ACTIVE picklist values are included',
        }
        if single_picklists:
            meta['picklists_usage_status'] = 'not_collected'
            meta['picklists_usage_not_collected_reason'] = 'pending'
        else:
            meta['picklists_usage_status'] = 'not_applicable'
        doc['metadata'] = meta
        dump_toon(doc, picklists_file)
    
    def enrich_all_objects(self, object_names: Optional[List[str]] = None, dry_run: bool = False):
        """
        Enrich all objects in the schema directory, or a specific list of
        objects. Operates exclusively on the per-object TOON folder
        structure; the legacy single-`.yaml`-file fallback was removed
        when the pipeline migrated to TOON.
        """
        if object_names:
            objects_to_process = object_names
        else:
            objects_to_process = []
            if self.schema_dir.exists():
                for item in self.schema_dir.iterdir():
                    if item.is_dir() and not item.name.startswith('_'):
                        objects_to_process.append(item.name)
            objects_to_process = sorted(set(objects_to_process))
        
        print(f"\n🚀 Enriching {len(objects_to_process)} objects...")
        print(f"   Org: {self.org_alias}")
        print(f"   Schema Dir: {self.schema_dir}")
        if dry_run:
            print("   Mode: DRY RUN (no files will be modified)\n")
        else:
            print("   Mode: WRITE (files will be updated)\n")
        
        for obj_name in objects_to_process:
            self.enrich_object_schema(obj_name, dry_run)
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print enrichment summary statistics."""
        print("\n" + "="*60)
        print("📊 ENRICHMENT SUMMARY")
        print("="*60)
        print(f"Objects Processed:    {self.enrichment_stats['objects_processed']}")
        print(f"Fields Enriched:      {self.enrichment_stats['fields_enriched']}")
        print(f"Picklists Added:      {self.enrichment_stats['picklists_added']}")
        print(f"Formulas Added:       {self.enrichment_stats['formulas_added']}")
        print(f"Picklist Files:       {self.enrichment_stats['picklist_files_created']}")
        print(f"Formula Files:        {self.enrichment_stats['formula_files_created']}")
        print(f"Errors:               {len(self.enrichment_stats['errors'])}")
        
        if self.enrichment_stats['errors']:
            print("\n⚠️  ERRORS:")
            for error in self.enrichment_stats['errors'][:10]:  # Show first 10
                print(f"   - {error}")
            if len(self.enrichment_stats['errors']) > 10:
                print(f"   ... and {len(self.enrichment_stats['errors']) - 10} more")
        
        print("="*60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Enrich Salesforce schema TOON files with picklist values and metadata',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enrich all objects (auto-detects org)
  python/python3 enrich_schema_with_picklists.py

  # Enrich all objects with explicit org
  python/python3 enrich_schema_with_picklists.py --org <your-org-alias>

  # Enrich specific objects
  python/python3 enrich_schema_with_picklists.py --objects Account,HealthcareProviderNpi

  # Dry run to see what would change
  python/python3 enrich_schema_with_picklists.py --dry-run

SF CLI Commands Used:
  sf sobject describe --sobject <ObjectName> --target-org <org> --json
  
Note: Org alias is auto-detected from .sf/config.json (or .sfdx/sfdx-config.json).
      Use --org to override auto-detection.
        """
    )
    
    parser.add_argument(
        '--org', '-o',
        required=False,
        help='Salesforce org alias (e.g., <your-org-alias>). If not provided, auto-detects from .sf/config.json'
    )
    
    parser.add_argument(
        '--objects',
        help='Comma-separated list of object names to enrich (default: all objects in schema directory)'
    )
    
    parser.add_argument(
        '--schema-dir',
        default=None,
        help='Path to schema objects directory (default: <project-root>/config/schema/objects)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    
    args = parser.parse_args()
    
    # Parse objects list
    objects_to_enrich = None
    if args.objects:
        objects_to_enrich = [obj.strip() for obj in args.objects.split(',')]
    
    # Create enricher and run
    enricher = SchemaEnricher(args.org, args.schema_dir)
    enricher.enrich_all_objects(objects_to_enrich, args.dry_run)


if __name__ == '__main__':
    main()
