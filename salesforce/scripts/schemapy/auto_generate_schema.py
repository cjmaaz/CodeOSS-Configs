#!/usr/bin/env python3
"""
Salesforce Schema Auto-Generator
=================================

Fully automated script that:
1. Detects your default Salesforce org from .sf/config.json
2. Retrieves all standard and custom objects (excluding History, Share, Feed, etc.)
3. Generates a complete ER schema in TOON (Token-Oriented Object Notation, v3.0)

NO INPUTS REQUIRED - Just run it!

Usage:
    python3 auto_generate_schema.py

That's it!
"""

import os
import sys
import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
import platform
import shutil

# Allow `from _toon_io import ...` regardless of cwd. The helper module
# sits next to this script under scripts/schemapy/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import find_project_root  # noqa: E402


class AutoSchemaGenerator:
    """Fully automated Salesforce schema generator."""

    def __init__(self):
        """Initialize by detecting project structure."""
        # Locate the project root by walking up from THIS file's location,
        # not from cwd, so the orchestrator works no matter where it is
        # invoked from.
        self.project_root = find_project_root()
        self.org_alias = None
        self.objects_path = None
        self.all_sobjects = []
        self.sf_exe = self.resolve_sf()
        
    def resolve_sf(self):
        """Resolve the path to the sf executable, handling Windows nuances."""
        exe = shutil.which('sf')
        if exe:
            return exe
        if platform.system() == 'Windows':
            # Common Windows install paths for sf
            candidates = [
                r'C:\Program Files\Salesforce CLI\bin\sf.cmd',
                rf'{os.environ.get("USERPROFILE", "")}\AppData\Roaming\npm\sf.cmd'
            ]
            for c in candidates:
                if c and os.path.isfile(c):
                    return c
        print("✗ Salesforce CLI (sf) not found. Install it or add it to PATH.")
        print("  See: https://developer.salesforce.com/tools/salesforcecli")
        return None
        
    def detect_org_alias(self):
        """Automatically detect the target org from .sf/config.json."""
        print("=" * 80)
        print("Step 1: Detecting Salesforce Org")
        print("=" * 80)
        
        # Try .sf/config.json (SF CLI v2)
        sf_config = self.project_root / '.sf' / 'config.json'
        if sf_config.exists():
            try:
                with open(sf_config, 'r') as f:
                    config = json.load(f)
                    self.org_alias = config.get('target-org')
                    if self.org_alias:
                        print(f"✓ Found target org: {self.org_alias}")
                        print(f"  Source: .sf/config.json")
                        return True
            except Exception as e:
                print(f"  Warning: Could not read .sf/config.json: {e}")
        
        # Try .sfdx/sfdx-config.json (legacy)
        sfdx_config = self.project_root / '.sfdx' / 'sfdx-config.json'
        if sfdx_config.exists():
            try:
                with open(sfdx_config, 'r') as f:
                    config = json.load(f)
                    self.org_alias = config.get('defaultusername')
                    if self.org_alias:
                        print(f"✓ Found target org: {self.org_alias}")
                        print(f"  Source: .sfdx/sfdx-config.json")
                        return True
            except Exception as e:
                print(f"  Warning: Could not read .sfdx/sfdx-config.json: {e}")
        
        print("✗ Could not find target org configuration")
        print("  Please set a default org using: sf config set target-org <your-org-alias>")
        return False
    
    def detect_objects_path(self):
        """Automatically detect the objects directory."""
        print("\n" + "=" * 80)
        print("Step 2: Detecting Objects Directory")
        print("=" * 80)
        
        possible_paths = [
            self.project_root / 'force-app' / 'main' / 'default' / 'objects',
            self.project_root / 'src' / 'objects',
            self.project_root / 'objects',
        ]
        
        for path in possible_paths:
            if path.exists() and path.is_dir():
                self.objects_path = path
                print(f"✓ Found objects directory: {path}")
                return True
        
        print("✗ Could not find objects directory")
        return False
    
    def get_all_sobjects(self):
        """Query the org for all sObjects."""
        print("\n" + "=" * 80)
        print("Step 3: Querying Org for All sObjects")
        print("=" * 80)
        
        if not self.sf_exe:
            print("✗ Cannot proceed: sf executable not found.")
            return False
            
        try:
            result = subprocess.run(
                [self.sf_exe, 'sobject', 'list', '--sobject', 'all', '--target-org', self.org_alias, '--json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                print(f"✗ Failed to query org: {result.stderr}")
                return False
            
            data = json.loads(result.stdout)
            
            if data.get('status') == 0 and 'result' in data:
                self.all_sobjects = data['result']
                print(f"✓ Found {len(self.all_sobjects)} sObjects in org")
                return True
            else:
                print(f"✗ Unexpected response format")
                return False
                
        except subprocess.TimeoutExpired:
            print("✗ Query timed out after 30 seconds")
            return False
        except json.JSONDecodeError as e:
            print(f"✗ Failed to parse JSON response: {e}")
            return False
        except Exception as e:
            print(f"✗ Error querying org: {e}")
            return False
    
    def should_retrieve_object(self, obj_name):
        """
        Determine if an object should be retrieved.
        
        Excludes:
        - Custom metadata types (__mdt)
        - Platform events (__e)
        - Big objects (__b)
        - External objects (__x)
        - History objects (*History)
        - Share objects (*Share)
        - Feed objects (*Feed)
        - Change events (*ChangeEvent)
        - Tag objects (*Tag)
        - Problematic system objects
        """
        # Exclude custom suffixes (except __c which we want)
        if obj_name.endswith('__mdt'):
            return False
        if obj_name.endswith('__e'):
            return False
        if obj_name.endswith('__b'):
            return False
        if obj_name.endswith('__x'):
            return False
        
        # Exclude common suffixes
        excluded_suffixes = ['History', 'Share', 'Feed', 'ChangeEvent', 'Tag']
        for suffix in excluded_suffixes:
            if obj_name.endswith(suffix):
                return False
        
        # Exclude specific problematic objects
        excluded_objects = [
            'AggregateResult',
            'ContentVersion',
            'ContentDocument',
            'FeedItem',
            'FeedComment',
            'ContentDocumentLink',
            'EmailMessage',
            'Attachment',
            'Document',
            'Note',
        ]
        if obj_name in excluded_objects:
            return False
        
        return True
    
    def filter_objects(self):
        """Filter objects to retrieve."""
        print("\n" + "=" * 80)
        print("Step 4: Filtering Objects to Retrieve")
        print("=" * 80)
        
        # Filter for objects we want
        objects_to_retrieve = [obj for obj in self.all_sobjects if self.should_retrieve_object(obj)]
        
        print(f"✓ Filtered {len(objects_to_retrieve)} objects to retrieve")
        print(f"  (Excluded {len(self.all_sobjects) - len(objects_to_retrieve)} objects)")
        
        return objects_to_retrieve
    
    def check_existing_objects(self, objects_to_retrieve):
        """Check which objects already exist locally."""
        print("\n" + "=" * 80)
        print("Step 5: Checking Existing Local Metadata")
        print("=" * 80)
        
        already_have = []
        need_retrieve = []
        
        for obj in objects_to_retrieve:
            obj_dir = self.objects_path / obj
            if obj_dir.exists() and obj_dir.is_dir():
                already_have.append(obj)
            else:
                need_retrieve.append(obj)
        
        print(f"✓ Already have local metadata for: {len(already_have)} objects")
        print(f"→ Need to retrieve: {len(need_retrieve)} objects")
        
        if len(need_retrieve) > 20:
            sample = ', '.join(need_retrieve[:20])
            print(f"  Sample: {sample}... (and {len(need_retrieve) - 20} more)")
        elif need_retrieve:
            print(f"  Objects: {', '.join(need_retrieve)}")
        else:
            print("  (All objects already present)")
        
        return need_retrieve
    
    def create_manifest(self, objects):
        """Create a temporary manifest file for retrieval."""
        root = ET.Element('Package')
        root.set('xmlns', 'http://soap.sforce.com/2006/04/metadata')
        
        types_elem = ET.SubElement(root, 'types')
        for obj in sorted(objects):
            member = ET.SubElement(types_elem, 'members')
            member.text = obj
        
        name_elem = ET.SubElement(types_elem, 'name')
        name_elem.text = 'CustomObject'
        
        version_elem = ET.SubElement(root, 'version')
        version_elem.text = '59.0'
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.xml',
            prefix='auto-retrieve-',
            delete=False
        )
        
        # Write XML with proper formatting
        tree = ET.ElementTree(root)
        ET.indent(tree, space='    ')
        tree.write(temp_file.name, encoding='UTF-8', xml_declaration=True)
        temp_file.close()
        
        return Path(temp_file.name)
    
    def retrieve_objects(self, objects):
        """Retrieve objects from Salesforce."""
        if not objects:
            print("\n✓ No objects to retrieve")
            return True
        
        print("\n" + "=" * 80)
        print(f"Step 6: Retrieving {len(objects)} Objects from Salesforce")
        print("=" * 80)
        
        if not self.sf_exe:
            print("✗ Cannot proceed: sf executable not found.")
            return False
            
        # Create manifest
        manifest_path = self.create_manifest(objects)
        print(f"✓ Created temporary manifest: {manifest_path}")
        
        try:
            # Run retrieval
            print(f"\n→ Running: sf project retrieve start...")
            print(f"  This may take a while for {len(objects)} objects...")
            
            result = subprocess.run(
                [
                    self.sf_exe, 'project', 'retrieve', 'start',
                    '--manifest', str(manifest_path),
                    '--target-org', self.org_alias,
                    '--wait', '10'
                ],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                print("\n✓ Retrieve completed successfully!")
                return True
            else:
                print(f"\n✗ Retrieve failed with exit code {result.returncode}")
                if result.stderr:
                    print(f"  Error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("\n✗ Retrieve timed out after 5 minutes")
            return False
        except Exception as e:
            print(f"\n✗ Error during retrieve: {e}")
            return False
        finally:
            # Clean up temporary manifest
            try:
                manifest_path.unlink()
                print(f"✓ Cleaned up temporary manifest")
            except Exception as e:
                print(f"⚠ Warning: Could not delete temporary manifest: {e}")
    
    def generate_schema(self):
        """Run the schema generator."""
        print("\n" + "=" * 80)
        print("Step 7: Generating ER Schema")
        print("=" * 80)
        
        try:
            # Run the schema generator script
            schema_script = Path(__file__).parent / 'generate_sf_er_schema.py'
            
            result = subprocess.run(
                [sys.executable, str(schema_script)],
                check=False
            )
            
            if result.returncode == 0:
                print("\n✓ Schema generation completed successfully!")
                return True
            else:
                print(f"\n✗ Schema generation failed with exit code {result.returncode}")
                return False
                
        except Exception as e:
            print(f"\n✗ Error running schema generator: {e}")
            return False
    
    def split_schema(self):
        """Run the schema splitter to optimize for AI agents."""
        print("\n" + "=" * 80)
        print("Step 8: Splitting Schema for AI Agent Consumption")
        print("=" * 80)
        
        try:
            # Run the schema splitter script
            splitter_script = Path(__file__).parent / 'split_schema_by_object.py'
            
            result = subprocess.run(
                [sys.executable, str(splitter_script)],
                check=False
            )
            
            if result.returncode == 0:
                print("\n✓ Schema splitting completed successfully!")
                return True
            else:
                print(f"\n✗ Schema splitting failed with exit code {result.returncode}")
                print("  Warning: Large schema file exists but not optimized")
                return False
                
        except Exception as e:
            print(f"\n✗ Error running schema splitter: {e}")
            return False
    
    def enrich_schema(self):
        """Run the schema enricher to add picklist values and metadata from org."""
        print("\n" + "=" * 80)
        print("Step 9: Enriching Schema with Picklist Values & Metadata")
        print("=" * 80)

        try:
            enricher_script = Path(__file__).parent / 'enrich_schema_with_picklists.py'
            result = subprocess.run(
                [sys.executable, str(enricher_script), '--org', self.org_alias],
                check=False,
            )
            if result.returncode == 0:
                print("\n✓ Schema enrichment completed successfully!")
                return True
            else:
                print(f"\n✗ Schema enrichment failed with exit code {result.returncode}")
                print("  Warning: Schemas exist but may lack picklist values")
                print("  You can manually run: python3 scripts/schemapy/enrich_schema_with_picklists.py --org <org-alias>")
                return False
        except Exception as e:
            print(f"\n✗ Error running schema enricher: {e}")
            print("  Warning: Schemas exist but may lack picklist values")
            return False

    def collect_usage_stats(self):
        """Step 10: Pull picklist + RecordType usage counts from the org."""
        print("\n" + "=" * 80)
        print("Step 10: Collecting Picklist + RecordType Usage Counts")
        print("=" * 80)
        try:
            script = Path(__file__).parent / 'collect_usage_stats.py'
            result = subprocess.run(
                [sys.executable, str(script), '--org', self.org_alias],
                check=False,
            )
            if result.returncode == 0:
                print("\n✓ Usage stats collection completed successfully!")
                return True
            print(f"\n✗ Usage stats collection failed with exit code {result.returncode}")
            print("  Warning: picklists.toon may lack per-value record counts")
            print("  You can manually run: python3 scripts/schemapy/collect_usage_stats.py --org <org-alias>")
            return False
        except Exception as e:
            print(f"\n✗ Error running usage-stats collector: {e}")
            return False

    def detect_junctions(self):
        """Step 11: Detect junction objects from the schema + record counts."""
        print("\n" + "=" * 80)
        print("Step 11: Detecting Junction Objects")
        print("=" * 80)
        try:
            script = Path(__file__).parent / 'detect_junctions.py'
            result = subprocess.run(
                [sys.executable, str(script), '--org', self.org_alias],
                check=False,
            )
            if result.returncode == 0:
                print("\n✓ Junction detection completed successfully!")
                return True
            print(f"\n✗ Junction detection failed with exit code {result.returncode}")
            print("  Warning: _junctions.toon may be missing or stale")
            print("  You can manually run: python3 scripts/schemapy/detect_junctions.py --org <org-alias>")
            return False
        except Exception as e:
            print(f"\n✗ Error running junction detector: {e}")
            return False

    def generate_er(self):
        """Step 12: Render ER.md from _junctions.toon (offline; no SOQL)."""
        print("\n" + "=" * 80)
        print("Step 12: Rendering ER.md")
        print("=" * 80)
        try:
            script = Path(__file__).parent / 'generate_er.py'
            result = subprocess.run(
                [sys.executable, str(script)], check=False
            )
            if result.returncode == 0:
                print("\n✓ ER.md rendered successfully!")
                return True
            print(f"\n✗ ER rendering failed with exit code {result.returncode}")
            print("  You can manually run: python3 scripts/schemapy/generate_er.py")
            return False
        except Exception as e:
            print(f"\n✗ Error running ER renderer: {e}")
            return False
    
    def run(self):
        """Main execution flow."""
        print("\n")
        print("╔" + "=" * 78 + "╗")
        print("║" + " " * 15 + "Salesforce Schema Auto-Generator" + " " * 31 + "║")
        print("║" + " " * 20 + "Fully Automated - No Inputs Needed" + " " * 24 + "║")
        print("╚" + "=" * 78 + "╝")
        print()
        
        # Step 1: Detect org
        if not self.detect_org_alias():
            return False
        
        # Step 2: Detect objects path
        if not self.detect_objects_path():
            return False
        
        # Step 3: Query org for all sObjects
        if not self.get_all_sobjects():
            return False
        
        # Step 4: Filter objects
        objects_to_retrieve = self.filter_objects()
        
        # Step 5: Check existing
        objects_needed = self.check_existing_objects(objects_to_retrieve)
        
        # Step 6: Retrieve missing objects
        if objects_needed:
            if not self.retrieve_objects(objects_needed):
                print("\n⚠ Warning: Object retrieval failed or incomplete")
                print("Continuing with schema generation using existing metadata...")
        
        # Step 7: Generate schema
        if not self.generate_schema():
            return False
        
        # Step 8: Split schema for AI consumption
        if not self.split_schema():
            print("  Warning: Schema was generated but not optimized for AI agents")
            print("  You can manually run: python3 scripts/schemapy/split_schema_by_object.py")

        # Step 9: Enrich schema with picklist values and metadata
        if not self.enrich_schema():
            print("  Warning: Schema files may be missing picklist values")
            print("  You can manually run: python3 scripts/schemapy/enrich_schema_with_picklists.py --org <org-alias>")

        # Step 10: Live usage counts (picklist values + RecordTypes)
        if not self.collect_usage_stats():
            print("  Warning: picklists.toon may lack per-value record counts")

        # Step 11: Detect junction objects from schema + counts
        if not self.detect_junctions():
            print("  Warning: _junctions.toon may be missing or stale")

        # Step 12: Render ER.md from junctions (offline)
        if not self.generate_er():
            print("  Warning: ER.md may be missing or stale")

        # Success!
        print("\n" + "=" * 80)
        print("✓ COMPLETE!")
        print("=" * 80)
        print()
        print("Summary:")
        print(f"  - Org: {self.org_alias}")
        print(f"  - Total sObjects in org: {len(self.all_sobjects)}")
        print(f"  - Objects retrieved: {len(objects_needed)}")
        print(f"  - Large schema file: config/salesforce-er-schema.toon")
        print(f"  - Optimized schemas: config/schema/ (USE THIS FOR AI AGENTS)")
        print(f"  - Encoding: TOON (Token-Oriented Object Notation, v3.0)")
        print()
        print("Schema Structure:")
        print("  - config/schema/_index.toon - Master index for quick lookup")
        print("  - config/schema/_search_index.toon - Search all fields")
        print("  - config/schema/_junctions.toon - Detected junction objects + parents (Step 11)")
        print("  - config/schema/objects/<Object>/{schema,picklists,formulas}.toon - Per-object (ENRICHED)")
        print("  - config/schema/categories/*.toon - Objects grouped by category")
        print("  - ER.md (project root) - Mermaid ER of every detected junction (Step 12)")
        print()
        print("Schema Enrichment:")
        print("  - Picklist values extracted from org (active values only)")
        print("  - Picklist + RecordType per-value record counts (Step 10)")
        print("  - Formula definitions included")
        print("  - Default values captured")
        print("  - Field constraints (required, unique, external_id) documented")
        print()
        print("Next steps:")
        print("  - AI agents should use config/schema/ directory")
        print("  - Review config/schema/README.md for usage guide")
        print("  - Skim ER.md at the project root for cross-object relationships")
        print("  - Re-run this script when metadata changes")
        print()
        
        return True


def main():
    """Entry point."""
    generator = AutoSchemaGenerator()
    
    try:
        success = generator.run()
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
