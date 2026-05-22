#!/usr/bin/env python3
"""
Salesforce ER Schema Generator
==============================

A reusable utility to parse Salesforce metadata XML files and generate a
comprehensive TOON schema document for AI agents to understand data model
relationships.

Output format: TOON (Token-Oriented Object Notation, v3.0).
See: https://github.com/toon-format/spec/blob/main/SPEC.md

Usage:
    python3 generate_sf_er_schema.py [options]

Options:
    --objects-path PATH     Path to objects directory (auto-detected if not provided)
    --output-path PATH      Path for output TOON file (default: config/salesforce-er-schema.toon)
    --help                  Show this help message

Example:
    # Run from project root (auto-detects paths)
    python3 generate_sf_er_schema.py

    # Specify custom paths
    python3 generate_sf_er_schema.py --objects-path ./force-app/main/default/objects --output-path ./schema.toon

Requirements:
    pip install -r scripts/schemapy/requirements.txt
"""

import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import argparse

# Allow `from _toon_io import ...` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import dump_toon, find_project_root  # noqa: E402

# Salesforce metadata namespace
SF_NS = {'sf': 'http://soap.sforce.com/2006/04/metadata'}


class SalesforceSchemaParser:
    """Parser for Salesforce metadata files to generate ER schema."""
    
    def __init__(self, objects_path):
        """
        Initialize the parser.
        
        Args:
            objects_path: Path to the Salesforce objects directory
        """
        self.objects_path = Path(objects_path)
        self.schema = {
            'salesforce_schema': {
                'metadata': {
                    'generated_date': datetime.now().isoformat(),
                    'source_path': str(objects_path),
                    'total_objects': 0
                },
                'objects': [],
                'relationships': []
            }
        }
    
    def parse_all_objects(self):
        """Traverse objects directory and parse all object metadata."""
        print(f"Scanning objects directory: {self.objects_path}")
        
        if not self.objects_path.exists():
            print(f"Error: Objects path does not exist: {self.objects_path}")
            return False
        
        if not self.objects_path.is_dir():
            print(f"Error: Objects path is not a directory: {self.objects_path}")
            return False
        
        try:
            object_dirs = [d for d in self.objects_path.iterdir() if d.is_dir()]
        except PermissionError as e:
            print(f"Error: Permission denied reading directory {self.objects_path}: {e}")
            return False
        except Exception as e:
            print(f"Error: Could not read objects directory: {e}")
            return False
        
        if not object_dirs:
            print(f"Warning: No object directories found in {self.objects_path}")
            return True  # Not an error, just empty
        
        print(f"Found {len(object_dirs)} object directories")
        
        for obj_dir in sorted(object_dirs):
            obj_name = obj_dir.name
            print(f"Processing object: {obj_name}")
            
            try:
                obj_data = self.parse_object(obj_dir)
                if obj_data:
                    self.schema['salesforce_schema']['objects'].append(obj_data)
            except Exception as e:
                print(f"  Warning: Error parsing object {obj_name}: {str(e)}")
                # Continue processing other objects
        
        self.schema['salesforce_schema']['metadata']['total_objects'] = len(
            self.schema['salesforce_schema']['objects']
        )
        print(f"\nCompleted parsing {self.schema['salesforce_schema']['metadata']['total_objects']} objects")
        return True
    
    def parse_object(self, obj_dir):
        """
        Parse a single object directory.
        
        Args:
            obj_dir: Path to the object directory
            
        Returns:
            Dictionary containing object metadata
        """
        obj_name = obj_dir.name
        
        # Determine object type
        obj_type = 'Custom'
        if not obj_name.endswith('__c') and not obj_name.endswith('__mdt') and not obj_name.endswith('__e'):
            obj_type = 'Standard'
        elif obj_name.endswith('__mdt'):
            obj_type = 'CustomMetadata'
        elif obj_name.endswith('__e'):
            obj_type = 'PlatformEvent'
        
        obj_data = {
            'api_name': obj_name,
            'type': obj_type,
            'fields': [],
            'record_types': [],
            'validation_rules': []
        }
        
        # Parse object metadata file
        obj_meta_file = obj_dir / f"{obj_name}.object-meta.xml"
        if obj_meta_file.exists():
            try:
                tree = ET.parse(obj_meta_file)
                root = tree.getroot()
                label_elem = root.find('.//sf:label', SF_NS)
                if label_elem is not None and label_elem.text:
                    obj_data['label'] = label_elem.text
                else:
                    obj_data['label'] = obj_name
                
                description_elem = root.find('.//sf:description', SF_NS)
                if description_elem is not None and description_elem.text:
                    obj_data['description'] = description_elem.text
            except Exception as e:
                print(f"  Warning: Could not parse object metadata file: {e}")
                obj_data['label'] = obj_name
        else:
            obj_data['label'] = obj_name
        
        # Parse fields
        fields_dir = obj_dir / 'fields'
        if fields_dir.exists():
            field_files = list(fields_dir.glob('*.field-meta.xml'))
            if field_files:
                print(f"  Found {len(field_files)} fields")
            for field_file in sorted(field_files):
                try:
                    field_data = self.parse_field(field_file, obj_name)
                    if field_data:
                        obj_data['fields'].append(field_data)
                except Exception as e:
                    print(f"  Warning: Error parsing field {field_file.name}: {e}")
        
        # Parse record types
        rt_dir = obj_dir / 'recordTypes'
        if rt_dir.exists():
            rt_files = list(rt_dir.glob('*.recordType-meta.xml'))
            if rt_files:
                print(f"  Found {len(rt_files)} record types")
            for rt_file in sorted(rt_files):
                try:
                    rt_data = self.parse_record_type(rt_file)
                    if rt_data:
                        obj_data['record_types'].append(rt_data)
                except Exception as e:
                    print(f"  Warning: Error parsing record type {rt_file.name}: {e}")
        
        # Parse validation rules
        vr_dir = obj_dir / 'validationRules'
        if vr_dir.exists():
            vr_files = list(vr_dir.glob('*.validationRule-meta.xml'))
            if vr_files:
                print(f"  Found {len(vr_files)} validation rules")
            for vr_file in sorted(vr_files):
                try:
                    vr_data = self.parse_validation_rule(vr_file)
                    if vr_data:
                        obj_data['validation_rules'].append(vr_data)
                except Exception as e:
                    print(f"  Warning: Error parsing validation rule {vr_file.name}: {e}")
        
        return obj_data
    
    def parse_field(self, field_file, parent_object):
        """
        Parse a single field XML file.
        
        Args:
            field_file: Path to the field metadata file
            parent_object: API name of the parent object
            
        Returns:
            Dictionary containing field metadata, or None if parsing fails
        """
        try:
            tree = ET.parse(field_file)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"  Warning: XML parse error in {field_file.name}: {e}")
            return None
        except Exception as e:
            print(f"  Warning: Unexpected error reading {field_file.name}: {e}")
            return None
        
        try:
            field_name = root.find('.//sf:fullName', SF_NS)
            field_name = field_name.text if field_name is not None and field_name.text else field_file.stem
            
            field_data = {
                'api_name': field_name
            }
            
            # Extract basic field properties
            label = root.find('.//sf:label', SF_NS)
            if label is not None and label.text:
                field_data['label'] = label.text
            
            field_type = root.find('.//sf:type', SF_NS)
            if field_type is not None and field_type.text:
                field_data['type'] = field_type.text
            
            description = root.find('.//sf:description', SF_NS)
            if description is not None and description.text:
                field_data['description'] = description.text
            
            help_text = root.find('.//sf:inlineHelpText', SF_NS)
            if help_text is not None and help_text.text:
                field_data['help_text'] = help_text.text
            
            # Field properties
            required = root.find('.//sf:required', SF_NS)
            if required is not None and required.text:
                field_data['required'] = required.text.lower() == 'true'
            
            unique = root.find('.//sf:unique', SF_NS)
            if unique is not None and unique.text:
                field_data['unique'] = unique.text.lower() == 'true'
            
            external_id = root.find('.//sf:externalId', SF_NS)
            if external_id is not None and external_id.text:
                field_data['external_id'] = external_id.text.lower() == 'true'
            
            # Length for text fields (handle conversion errors)
            length = root.find('.//sf:length', SF_NS)
            if length is not None and length.text:
                try:
                    field_data['length'] = int(length.text)
                except (ValueError, TypeError) as e:
                    print(f"  Warning: Invalid length value in {field_name}: {length.text}")
            
            # Precision and scale for number/currency fields (handle conversion errors)
            precision = root.find('.//sf:precision', SF_NS)
            if precision is not None and precision.text:
                try:
                    field_data['precision'] = int(precision.text)
                except (ValueError, TypeError) as e:
                    print(f"  Warning: Invalid precision value in {field_name}: {precision.text}")
            
            scale = root.find('.//sf:scale', SF_NS)
            if scale is not None and scale.text:
                try:
                    field_data['scale'] = int(scale.text)
                except (ValueError, TypeError) as e:
                    print(f"  Warning: Invalid scale value in {field_name}: {scale.text}")
        
            
            # Relationship fields (Lookup, MasterDetail)
            if field_data.get('type') in ['Lookup', 'MasterDetail']:
                reference_to = root.find('.//sf:referenceTo', SF_NS)
                if reference_to is not None and reference_to.text:
                    field_data['reference_to'] = reference_to.text
                
                relationship_name = root.find('.//sf:relationshipName', SF_NS)
                if relationship_name is not None and relationship_name.text:
                    field_data['relationship_name'] = relationship_name.text
                
                relationship_label = root.find('.//sf:relationshipLabel', SF_NS)
                if relationship_label is not None and relationship_label.text:
                    field_data['relationship_label'] = relationship_label.text
                
                delete_constraint = root.find('.//sf:deleteConstraint', SF_NS)
                if delete_constraint is not None and delete_constraint.text:
                    field_data['delete_constraint'] = delete_constraint.text
                
                # Add to relationships list
                if 'reference_to' in field_data:
                    try:
                        self.schema['salesforce_schema']['relationships'].append({
                            'from_object': parent_object,
                            'from_field': field_name,
                            'to_object': field_data['reference_to'],
                            'relationship_type': field_data['type'],
                            'relationship_name': field_data.get('relationship_name', ''),
                            'delete_constraint': field_data.get('delete_constraint', '')
                        })
                    except Exception as e:
                        print(f"  Warning: Could not add relationship for {field_name}: {e}")
            
            # Picklist values — captured as {value, label} pairs so the
            # display label is preserved alongside the API value (they
            # commonly differ, e.g. value=PCP, label=Primary Care Physician).
            if field_data.get('type') in ['Picklist', 'MultiselectPicklist']:
                try:
                    picklist_values = []
                    value_set = root.find('.//sf:valueSet', SF_NS)
                    if value_set is not None:
                        for value_elem in value_set.findall('.//sf:value', SF_NS):
                            full_name_node = value_elem.find('sf:fullName', SF_NS)
                            label_node = value_elem.find('sf:label', SF_NS)
                            if full_name_node is not None and full_name_node.text:
                                v = full_name_node.text
                                # Salesforce custom-field XML uses <label>
                                # for the display string; some standard
                                # fields use <masterLabel>. Support both,
                                # fall back to value if neither present.
                                if label_node is None:
                                    label_node = value_elem.find('sf:masterLabel', SF_NS)
                                l = (label_node.text
                                     if label_node is not None and label_node.text
                                     else v)
                                picklist_values.append({'value': v, 'label': l})
                    if picklist_values:
                        field_data['picklist_values'] = picklist_values
                except Exception as e:
                    print(f"  Warning: Could not extract picklist values for {field_name}: {e}")
            
            # Formula field
            formula = root.find('.//sf:formula', SF_NS)
            if formula is not None and formula.text:
                field_data['formula'] = formula.text
            
            # Default value
            default_value = root.find('.//sf:defaultValue', SF_NS)
            if default_value is not None and default_value.text:
                field_data['default_value'] = default_value.text
            
            return field_data
        
        except Exception as e:
            print(f"  Warning: Error extracting field data from {field_file.name}: {e}")
            # Return minimal field data so parsing can continue
            return {'api_name': field_file.stem, 'parse_error': str(e)}
    
    def parse_record_type(self, rt_file):
        """
        Parse a single record type XML file.
        
        Args:
            rt_file: Path to the record type metadata file
            
        Returns:
            Dictionary containing record type metadata, or None if parsing fails
        """
        try:
            tree = ET.parse(rt_file)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"  Warning: XML parse error in {rt_file.name}: {e}")
            return None
        except Exception as e:
            print(f"  Warning: Unexpected error reading {rt_file.name}: {e}")
            return None
        
        try:
            rt_data = {}
            
            full_name = root.find('.//sf:fullName', SF_NS)
            if full_name is not None and full_name.text:
                rt_data['api_name'] = full_name.text
            else:
                rt_data['api_name'] = rt_file.stem
            
            label = root.find('.//sf:label', SF_NS)
            if label is not None and label.text:
                rt_data['label'] = label.text
            
            description = root.find('.//sf:description', SF_NS)
            if description is not None and description.text:
                rt_data['description'] = description.text
            
            active = root.find('.//sf:active', SF_NS)
            if active is not None and active.text:
                rt_data['active'] = active.text.lower() == 'true'
            
            return rt_data
        
        except Exception as e:
            print(f"  Warning: Error extracting record type data from {rt_file.name}: {e}")
            return {'api_name': rt_file.stem, 'parse_error': str(e)}
    
    def parse_validation_rule(self, vr_file):
        """
        Parse a single validation rule XML file.
        
        Args:
            vr_file: Path to the validation rule metadata file
            
        Returns:
            Dictionary containing validation rule metadata, or None if parsing fails
        """
        try:
            tree = ET.parse(vr_file)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"  Warning: XML parse error in {vr_file.name}: {e}")
            return None
        except Exception as e:
            print(f"  Warning: Unexpected error reading {vr_file.name}: {e}")
            return None
        
        try:
            vr_data = {}
            
            full_name = root.find('.//sf:fullName', SF_NS)
            if full_name is not None and full_name.text:
                vr_data['name'] = full_name.text
            else:
                vr_data['name'] = vr_file.stem
            
            active = root.find('.//sf:active', SF_NS)
            if active is not None and active.text:
                vr_data['active'] = active.text.lower() == 'true'
            
            description = root.find('.//sf:description', SF_NS)
            if description is not None and description.text:
                vr_data['description'] = description.text
            
            error_condition = root.find('.//sf:errorConditionFormula', SF_NS)
            if error_condition is not None and error_condition.text:
                vr_data['error_condition_formula'] = error_condition.text
            
            error_display_field = root.find('.//sf:errorDisplayField', SF_NS)
            if error_display_field is not None and error_display_field.text:
                vr_data['error_display_field'] = error_display_field.text
            
            error_msg = root.find('.//sf:errorMessage', SF_NS)
            if error_msg is not None and error_msg.text:
                vr_data['error_message'] = error_msg.text
            
            return vr_data
        
        except Exception as e:
            print(f"  Warning: Error extracting validation rule data from {vr_file.name}: {e}")
            return {'name': vr_file.stem, 'parse_error': str(e)}
    
    def save_toon(self, output_path):
        """
        Save the schema to a TOON file.

        TOON has no comment syntax (spec §1.4 / "Out of scope: comments"),
        so the previous YAML-style banner is intentionally omitted. The
        same generation metadata is preserved inside the document via the
        `salesforce_schema.metadata` block.

        Args:
            output_path: Path where the TOON file should be saved

        Returns:
            True if successful, False otherwise
        """
        try:
            output_path = Path(output_path)
        except Exception as e:
            print(f"\nError: Invalid output path {output_path}: {e}")
            return False

        print(f"\nSaving schema to: {output_path}")

        try:
            dump_toon(self.schema, output_path)
        except PermissionError as e:
            print(f"\nError: Permission denied writing to {output_path}: {e}")
            return False
        except IOError as e:
            print(f"\nError: I/O error writing to {output_path}: {e}")
            return False
        except Exception as e:
            print(f"\nError: Unexpected error saving schema: {e}")
            return False

        print(f"✓ Schema saved successfully!")
        print(f"  Total objects: {self.schema['salesforce_schema']['metadata']['total_objects']}")
        print(f"  Total relationships: {len(self.schema['salesforce_schema']['relationships'])}")
        return True


def find_objects_path():
    """
    Auto-detect the Salesforce objects directory from the project root
    (resolved by walking up from this script's location, not from cwd).

    Returns:
        Path to objects directory or None if not found
    """
    try:
        project_root = find_project_root()
    except Exception as e:
        print(f"Error: Could not determine project root: {e}")
        return None

    possible_paths = [
        project_root / 'force-app' / 'main' / 'default' / 'objects',
        project_root / 'src' / 'objects',
        project_root / 'objects',
    ]

    for path in possible_paths:
        try:
            if path.exists() and path.is_dir():
                return path
        except PermissionError:
            continue
        except Exception:
            continue

    return None


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Generate Salesforce ER Schema TOON from metadata files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect paths (run from project root)
  python3 generate_sf_er_schema.py

  # Specify custom objects directory
  python3 generate_sf_er_schema.py --objects-path ./force-app/main/default/objects

  # Specify custom output location
  python3 generate_sf_er_schema.py --output-path ./docs/schema.toon

Note:
  This script only generates schema from existing local metadata.
  To automatically retrieve objects first, use: python3 auto_generate_schema.py
        """
    )
    
    parser.add_argument(
        '--objects-path',
        help='Path to Salesforce objects directory (auto-detected if not provided)',
        type=str,
        default=None
    )
    
    parser.add_argument(
        '--output-path',
        help='Path for output TOON file (default: <project-root>/config/salesforce-er-schema.toon)',
        type=str,
        default=None
    )

    args = parser.parse_args()
    if args.output_path is None:
        args.output_path = str(find_project_root() / 'config' / 'salesforce-er-schema.toon')
    
    # Determine objects path
    if args.objects_path:
        objects_path = Path(args.objects_path)
        if not objects_path.exists():
            print(f"Error: Specified objects path does not exist: {objects_path}")
            sys.exit(1)
    else:
        print("Auto-detecting Salesforce objects directory...")
        objects_path = find_objects_path()
        if objects_path is None:
            print("Error: Could not find Salesforce objects directory.")
            print("Please run this script from your Salesforce project root,")
            print("or specify the path using --objects-path option.")
            sys.exit(1)
        print(f"✓ Found objects directory: {objects_path}")
    
    # Determine output path (relative to project root)
    output_path = Path(args.output_path)
    
    print("\n" + "=" * 80)
    print("Salesforce ER Schema Generator")
    print("=" * 80)
    print()
    
    # Create parser and process
    schema_parser = SalesforceSchemaParser(objects_path)
    success = schema_parser.parse_all_objects()
    
    if not success:
        print("\nError: Failed to parse objects.")
        sys.exit(1)
    
    # Cleanup: drop the old YAML intermediate if it still exists from a
    # previous YAML-era run. The TOON file at `output_path` is the new
    # source of truth.
    legacy_yaml = output_path.with_suffix('.yaml')
    if legacy_yaml.exists() and legacy_yaml != output_path:
        try:
            legacy_yaml.unlink()
            print(f"  Removed orphan YAML intermediate: {legacy_yaml}")
        except Exception as e:
            print(f"  Warning: could not remove orphan {legacy_yaml}: {e}")

    if not schema_parser.save_toon(output_path):
        print("\nError: Failed to save schema.")
        sys.exit(1)
    
    print()
    print("=" * 80)
    print("✓ Schema generation complete!")
    print("=" * 80)
    print()
    print(f"Next steps:")
    print(f"  - Review the generated schema: {output_path}")
    print(f"  - Use it as a reference for AI-assisted development")
    print(f"  - Re-run this script when your object metadata changes")
    print()


if __name__ == '__main__':
    main()
