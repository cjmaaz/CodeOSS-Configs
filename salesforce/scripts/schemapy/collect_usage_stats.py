#!/usr/bin/env python3
"""
Step 10: Collect Usage Statistics
==================================

For every queryable object in `config/schema/`, run SOQL aggregate
queries against the org to gather:

  - per-picklist-value record counts
  - per-RecordType record counts

Results are merged back into:

  - `picklists.toon`  — switches to tabular `{value,count}` form when
                        usage data is available
  - `schema.toon`     — `record_types[]` gains a `record_count` column

Skipped:
  - MultiselectPicklist fields (cannot `GROUP BY` cleanly per SOQL)
  - Objects with no read access (caught at the per-query level)
  - Objects with zero records (no point counting)

Performance
-----------
Uses Salesforce's composite REST API (up to 25 sub-requests per HTTP
call) instead of one `sf data query` per query. The session is fetched
once via `sf org display --verbose --json`. This is ~10x faster than
the per-call CLI approach and brings 670-object runtime down to roughly
20-30 minutes.

Usage
-----
    # All objects (auto-detect org alias from .sf/config.json)
    python3 scripts/schemapy/collect_usage_stats.py

    # Specific org
    python3 scripts/schemapy/collect_usage_stats.py --org <your-org-alias>

    # Specific objects only
    python3 scripts/schemapy/collect_usage_stats.py --objects Account,Case

This script is automatically called by `auto_generate_schema.py` as
Step 10 of the pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow `from _toon_io import ...` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import dump_toon, load_toon, find_project_root  # noqa: E402
from _sf_session import SfSession  # noqa: E402


class UsageStatsCollector:
    """Pulls picklist + RecordType usage counts and merges into schema files."""

    def __init__(self, org_alias: Optional[str] = None, schema_dir: Optional[str] = None):
        self.org_alias = org_alias or self._detect_org_alias()
        if schema_dir is None:
            schema_dir = str(find_project_root() / 'config' / 'schema')
        self.schema_dir = Path(schema_dir)
        self.objects_dir = self.schema_dir / 'objects'

        # Salesforce session — token fetched lazily on first query.
        self.session = SfSession(org_alias=self.org_alias)

        # RecordTypeId -> (sobject, devname); built once via fetch_recordtype_map()
        self.recordtype_id_map: Dict[str, Tuple[str, str]] = {}

        self.stats = {
            'objects_processed': 0,
            'objects_with_picklist_data': 0,
            'objects_with_recordtype_data': 0,
            'picklist_queries_succeeded': 0,
            'picklist_queries_failed': 0,
            'recordtype_queries_succeeded': 0,
            'recordtype_queries_failed': 0,
            'objects_with_zero_records': 0,
            'objects_skipped_no_access': 0,
            'multipicklists_skipped': 0,
            'errors': [],
        }

    def _detect_org_alias(self) -> str:
        project_root = find_project_root()
        sf_config = project_root / '.sf' / 'config.json'
        if sf_config.exists():
            try:
                with open(sf_config, 'r') as f:
                    org = json.load(f).get('target-org')
                    if org:
                        print(f"Auto-detected org: {org} (from .sf/config.json)")
                        return org
            except Exception:
                pass
        sfdx_config = project_root / '.sfdx' / 'sfdx-config.json'
        if sfdx_config.exists():
            try:
                with open(sfdx_config, 'r') as f:
                    org = json.load(f).get('defaultusername')
                    if org:
                        print(f"Auto-detected org: {org} (from .sfdx/sfdx-config.json)")
                        return org
            except Exception:
                pass
        print("Error: could not auto-detect target org. Pass --org explicitly.")
        sys.exit(1)

    def fetch_recordtype_map(self) -> None:
        """One call to build a global RecordTypeId -> DeveloperName lookup."""
        records = self.session.composite_batch_query(
            ["SELECT Id, DeveloperName, SobjectType FROM RecordType LIMIT 2000"]
        )[0] or []
        for r in records:
            rid = r.get('Id')
            sobj = r.get('SobjectType') or ''
            dev = r.get('DeveloperName') or ''
            if rid and dev:
                self.recordtype_id_map[rid] = (sobj, dev)
        print(f"  Loaded {len(self.recordtype_id_map)} RecordTypes")

    # ------------------------------------------------------------------
    # Per-object processing
    # ------------------------------------------------------------------

    def _picklist_field_types_from_fields_file(self, fields_doc: Dict[str, Any]) -> Dict[str, str]:
        """Build {field_api_name: field_type} for picklist-typed fields only,
        sourcing from the new tabular fields.toon (Step 8/9 layout)."""
        out: Dict[str, str] = {}
        for f in fields_doc.get('fields', []) or []:
            t = f.get('type')
            api = f.get('api_name')
            if api and t in ('Picklist', 'MultiselectPicklist'):
                out[api] = t
        return out

    def process_object(self, object_name: str) -> None:
        obj_folder = self.objects_dir / object_name
        schema_file = obj_folder / 'schema.toon'
        fields_file = obj_folder / 'fields.toon'
        picklists_file = obj_folder / 'picklists.toon'
        record_types_file = obj_folder / 'record_types.toon'

        if not schema_file.exists():
            return

        try:
            schema = load_toon(schema_file)
        except Exception as e:
            self.stats['errors'].append(f"{object_name}: failed to load schema.toon: {e}")
            return

        # Field type lookup comes from fields.toon now (the new layout).
        type_map: Dict[str, str] = {}
        if fields_file.exists():
            try:
                fields_doc = load_toon(fields_file)
                if isinstance(fields_doc, dict):
                    type_map = self._picklist_field_types_from_fields_file(fields_doc)
            except Exception as e:
                self.stats['errors'].append(f"{object_name}: failed to load fields.toon: {e}")

        picklist_doc: Optional[Dict[str, Any]] = None
        picklist_field_names: List[str] = []
        if picklists_file.exists():
            try:
                picklist_doc = load_toon(picklists_file)
                declared = list((picklist_doc or {}).get('picklists', {}).keys())
                for f in declared:
                    if type_map.get(f) == 'MultiselectPicklist':
                        self.stats['multipicklists_skipped'] += 1
                        continue
                    picklist_field_names.append(f)
            except Exception as e:
                self.stats['errors'].append(f"{object_name}: failed to load picklists.toon: {e}")

        # RecordTypes from record_types.toon (new layout)
        record_types_doc: Optional[Dict[str, Any]] = None
        recordtype_devnames: List[str] = []
        if record_types_file.exists():
            try:
                record_types_doc = load_toon(record_types_file)
                if isinstance(record_types_doc, dict):
                    for rt in record_types_doc.get('record_types', []) or []:
                        api = rt.get('api_name')
                        if api:
                            recordtype_devnames.append(api)
            except Exception as e:
                self.stats['errors'].append(f"{object_name}: failed to load record_types.toon: {e}")

        if not picklist_field_names and not recordtype_devnames:
            return  # nothing to count for this object

        # Build query batch:
        #   q0: COUNT(Id) — short-circuit if zero records
        #   q1..qN: per-picklist GROUP BY
        #   q(N+1): RecordTypeId GROUP BY (only if recordtypes exist)
        queries: List[str] = [f"SELECT COUNT(Id) cnt FROM {object_name}"]
        for f in picklist_field_names:
            queries.append(
                f"SELECT {f} val, COUNT(Id) cnt FROM {object_name} "
                f"WHERE {f} != null GROUP BY {f}"
            )
        if recordtype_devnames:
            queries.append(
                f"SELECT RecordTypeId rtid, COUNT(Id) cnt FROM {object_name} "
                f"WHERE RecordTypeId != null GROUP BY RecordTypeId"
            )

        results = self.session.composite_batch_query(queries)
        # Surface any sub-request errors collected by the session helper
        # into our local stats so the summary print is accurate.
        if self.session.errors:
            self.stats['errors'].extend(self.session.errors)
            self.session.errors.clear()

        # Result 0 — total count / readability gate
        total_count_records = results[0]
        if total_count_records is None:
            # COUNT(Id) failed -> we have no read access. Surface the
            # reason on every relevant file before bailing.
            self.stats['objects_skipped_no_access'] += 1
            if picklist_doc is not None:
                self._set_picklists_not_collected_reason(
                    picklists_file, picklist_doc, 'no_query_access')
            if record_types_doc is not None:
                self._set_recordtypes_not_collected_reason(
                    record_types_file, record_types_doc, 'no_query_access')
            return
        total_count = (total_count_records[0].get('cnt', 0) if total_count_records else 0)
        if total_count == 0:
            # Object exists but has zero records — every count would be 0.
            # Mark explicitly so AI agents see the empty-org reason.
            self.stats['objects_with_zero_records'] += 1
            if picklist_doc is not None:
                self._set_picklists_not_collected_reason(
                    picklists_file, picklist_doc, 'empty_object')
            if record_types_doc is not None:
                self._set_recordtypes_not_collected_reason(
                    record_types_file, record_types_doc, 'empty_object')
            return

        # Picklist counts
        picklist_counts: Dict[str, Dict[str, int]] = {}
        picklists_with_query_errors: List[str] = []
        for i, fname in enumerate(picklist_field_names, start=1):
            res = results[i]
            if res is None:
                self.stats['picklist_queries_failed'] += 1
                picklists_with_query_errors.append(fname)
                continue
            counts: Dict[str, int] = {}
            for row in res:
                v = row.get('val')
                cnt = int(row.get('cnt', 0))
                key = v if v is not None else '_null'
                counts[key] = cnt
            picklist_counts[fname] = counts
            self.stats['picklist_queries_succeeded'] += 1

        # RecordType counts
        recordtype_counts: Dict[str, int] = {}
        recordtype_query_failed = False
        if recordtype_devnames:
            res = results[-1]
            if res is None:
                self.stats['recordtype_queries_failed'] += 1
                recordtype_query_failed = True
            else:
                for row in res:
                    rid = row.get('rtid')
                    cnt = int(row.get('cnt', 0))
                    mapping = self.recordtype_id_map.get(rid)
                    if mapping:
                        _, devname = mapping
                        if devname:
                            recordtype_counts[devname] = cnt
                self.stats['recordtype_queries_succeeded'] += 1

        # Merge back
        if picklist_counts and picklist_doc is not None:
            self._merge_picklist_counts(
                picklists_file, picklist_doc, picklist_counts,
                picklists_with_query_errors=picklists_with_query_errors,
            )
            self.stats['objects_with_picklist_data'] += 1
        elif picklist_doc is not None and picklists_with_query_errors:
            # All picklist queries failed but the object is otherwise readable.
            self._set_picklists_not_collected_reason(
                picklists_file, picklist_doc, 'query_error')

        # Merge RecordType counts whenever the query SUCCEEDED, even if
        # it returned zero rows (no records currently use any RT — every
        # row gets record_count: 0, status flips to live_counts).
        if (record_types_doc is not None
                and recordtype_devnames
                and not recordtype_query_failed):
            self._merge_recordtype_counts(record_types_file, record_types_doc, recordtype_counts)
            self._touch_schema_recordtype_stamp(schema_file, schema)
            self.stats['objects_with_recordtype_data'] += 1
        elif record_types_doc is not None and recordtype_query_failed:
            self._set_recordtypes_not_collected_reason(
                record_types_file, record_types_doc, 'query_error')

        self.stats['objects_processed'] += 1

    # ------------------------------------------------------------------
    # Mergers — write the augmented files
    # ------------------------------------------------------------------

    def _merge_picklist_counts(
        self,
        picklists_file: Path,
        picklist_doc: Dict[str, Any],
        counts_by_field: Dict[str, Dict[str, int]],
        picklists_with_query_errors: Optional[List[str]] = None,
    ) -> None:
        """Merge per-value record counts into the `picklists:` (single-
        select) block. NEVER touches the `multipicklists:` block — multi-
        select picklists cannot be GROUP BY'd in SOQL, so per-value
        counts are unobtainable.

        For each value-row, joins the existing `label` (preserved from
        Step 8 / Step 9) with the new `count` to produce a tabular
        `values[N]{label,value,count}:` block.
        """
        original = picklist_doc.get('picklists', {}) or {}
        new_picklists: Dict[str, Any] = {}
        for field_name, declared in original.items():
            if field_name in counts_by_field:
                counts = counts_by_field[field_name]
                rows: List[Dict[str, Any]] = []
                seen = set()

                def _row(label: str, value: str, count: int) -> Dict[str, Any]:
                    return {'label': label or value, 'value': value, 'count': count}

                # Preserve declared order + label from existing structure
                if isinstance(declared, list):
                    # Legacy bare-string list — label = value as fallback
                    for v in declared:
                        if isinstance(v, dict):
                            rows.append(_row(v.get('label', ''), v.get('value', ''),
                                             counts.get(v.get('value', ''), 0)))
                            seen.add(v.get('value', ''))
                        else:
                            rows.append(_row(v, v, counts.get(v, 0)))
                            seen.add(v)
                elif isinstance(declared, dict) and 'values' in declared:
                    for entry in declared.get('values', []):
                        if isinstance(entry, dict):
                            v = entry.get('value', '')
                            l = entry.get('label') or v
                            if v:
                                rows.append(_row(l, v, counts.get(v, 0)))
                                seen.add(v)
                        else:
                            rows.append(_row(entry, entry, counts.get(entry, 0)))
                            seen.add(entry)

                # Append values found in records but not in the declared
                # picklist (legacy / inactive values, or _null sentinel)
                for v, cnt in counts.items():
                    if v not in seen:
                        rows.append(_row(v, v, cnt))

                new_picklists[field_name] = {'values': rows}
            else:
                # Field couldn't be counted (query failed or wasn't queried);
                # keep the existing structure as-is so the {label,value} form
                # from Step 8 / 9 is preserved.
                new_picklists[field_name] = declared
        picklist_doc['picklists'] = new_picklists

        meta = picklist_doc.get('metadata', {}) or {}
        meta['picklists_usage_status'] = 'live_counts'
        meta.pop('picklists_usage_not_collected_reason', None)
        # Drop the old boolean marker if present (back-compat with pre-rename data).
        meta.pop('has_usage_counts', None)
        meta['picklists_usage_collected_date'] = datetime.now().isoformat()
        # multipicklists block (if present) stays not_applicable.
        meta.setdefault('multipicklists_usage_status', 'not_applicable')
        if picklists_with_query_errors:
            meta['picklists_with_query_errors'] = sorted(set(picklists_with_query_errors))
        else:
            meta.pop('picklists_with_query_errors', None)
        picklist_doc['metadata'] = meta

        dump_toon(picklist_doc, picklists_file)

    # Mirror of Step 8's column order so re-emit stays tabular.
    _RECORDTYPE_COLUMNS_BASE = ('api_name', 'label', 'description', 'active')

    def _merge_recordtype_counts(
        self,
        record_types_file: Path,
        record_types_doc: Dict[str, Any],
        counts: Dict[str, int],
    ) -> None:
        """Merge per-RecordType counts into record_types.toon. Re-emits
        every row with a uniform column set (including the new
        `record_count`) so TOON stays in tabular form regardless of
        which optional fields any individual RecordType is missing."""
        record_types = record_types_doc.get('record_types', []) or []
        if not record_types:
            return
        new_rows = []
        for rt in record_types:
            row = {}
            for k in self._RECORDTYPE_COLUMNS_BASE:
                v = rt.get(k, '')
                if v is None:
                    v = ''
                if isinstance(v, bool):
                    row[k] = 'true' if v else 'false'
                else:
                    row[k] = str(v) if v != '' else ''
            row['record_count'] = int(counts.get(rt.get('api_name'), 0))
            new_rows.append(row)
        record_types_doc['record_types'] = new_rows
        meta = record_types_doc.get('metadata', {}) or {}
        meta['usage_status'] = 'live_counts'
        meta.pop('usage_not_collected_reason', None)
        meta.pop('has_record_counts', None)  # back-compat with pre-rename data
        meta['record_type_counts_collected_date'] = datetime.now().isoformat()
        record_types_doc['metadata'] = meta
        dump_toon(record_types_doc, record_types_file)

    def _set_picklists_not_collected_reason(
        self,
        picklists_file: Path,
        picklist_doc: Dict[str, Any],
        reason: str,
    ) -> None:
        """When Step 10 cannot collect counts for an object's picklists
        (no_query_access / empty_object / query_error), surface the
        reason explicitly so AI agents see why."""
        meta = picklist_doc.get('metadata', {}) or {}
        # Only update when the picklists block exists (single-select).
        if meta.get('picklists_usage_status') in (None, 'not_collected'):
            meta['picklists_usage_status'] = 'not_collected'
            meta['picklists_usage_not_collected_reason'] = reason
            picklist_doc['metadata'] = meta
            dump_toon(picklist_doc, picklists_file)

    def _set_recordtypes_not_collected_reason(
        self,
        record_types_file: Path,
        record_types_doc: Dict[str, Any],
        reason: str,
    ) -> None:
        meta = record_types_doc.get('metadata', {}) or {}
        if meta.get('usage_status') in (None, 'not_collected'):
            meta['usage_status'] = 'not_collected'
            meta['usage_not_collected_reason'] = reason
            record_types_doc['metadata'] = meta
            dump_toon(record_types_doc, record_types_file)

    def _touch_schema_recordtype_stamp(
        self, schema_file: Path, schema: Dict[str, Any]
    ) -> None:
        """Bump `metadata.record_type_counts_collected_date` on schema.toon
        so AI agents can tell at a glance whether record_types.toon has
        live counts merged."""
        meta = schema.get('metadata', {}) or {}
        meta['record_type_counts_collected_date'] = datetime.now().isoformat()
        schema['metadata'] = meta
        dump_toon(schema, schema_file)

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def run(self, object_names: Optional[List[str]] = None) -> None:
        if not self.objects_dir.exists():
            print(f"Error: schema objects dir not found: {self.objects_dir}")
            sys.exit(1)
        print(f"Fetching access token for {self.org_alias}...")
        self.session.initialise()
        print(f"  Instance: {self.session.instance_url}")
        print(f"  API version: {self.session.api_version}")
        print("Building global RecordType map...")
        self.fetch_recordtype_map()

        if object_names is None:
            object_names = sorted(
                d.name for d in self.objects_dir.iterdir()
                if d.is_dir() and not d.name.startswith('_')
            )

        total = len(object_names)
        print(f"\nCollecting usage stats for {total} objects via composite REST API...")
        for i, obj_name in enumerate(object_names, 1):
            try:
                self.process_object(obj_name)
            except Exception as e:
                self.stats['errors'].append(f"{obj_name}: {e}")
            if i % 25 == 0 or i == total:
                print(
                    f"  [{i}/{total}] processed={self.stats['objects_processed']} "
                    f"picklists_ok={self.stats['picklist_queries_succeeded']} "
                    f"rt_ok={self.stats['recordtype_queries_succeeded']} "
                    f"no_access={self.stats['objects_skipped_no_access']} "
                    f"empty={self.stats['objects_with_zero_records']}"
                )

        self.print_summary()

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("USAGE STATS COLLECTION SUMMARY")
        print("=" * 60)
        for k, v in self.stats.items():
            if k == 'errors':
                continue
            print(f"  {k:36s}: {v}")
        print(f"  {'errors':36s}: {len(self.stats['errors'])}")
        if self.stats['errors']:
            print("\nFirst 10 errors:")
            for err in self.stats['errors'][:10]:
                print(f"  - {err}")
        print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Collect picklist + RecordType usage counts from the Salesforce org',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--org', '-o', help='Salesforce org alias (auto-detected if omitted)')
    parser.add_argument(
        '--objects',
        help='Comma-separated list of object API names (default: all under config/schema/objects/)',
    )
    parser.add_argument(
        '--schema-dir',
        default=None,
        help='Path to config/schema/ directory (default: <project-root>/config/schema)',
    )
    args = parser.parse_args()

    object_names = None
    if args.objects:
        object_names = [o.strip() for o in args.objects.split(',') if o.strip()]

    collector = UsageStatsCollector(org_alias=args.org, schema_dir=args.schema_dir)
    collector.run(object_names)


if __name__ == '__main__':
    main()
