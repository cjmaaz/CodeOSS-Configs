#!/usr/bin/env python3
"""
Step 11: Detect Junction Objects
================================

Reads `config/salesforce-er-schema.toon` (the combined intermediate
emitted by Step 7) and structurally identifies "junction" objects —
i.e. objects that bridge two (or more) other entities via Lookup /
MasterDetail relationships and serve as many-to-many connectors.

Detection is purely structural so the script works in any Salesforce
org: no IBX / Health-Cloud / Vlocity-specific name patterns are used.

Algorithm:
  1. Loose candidate filter — any object with 2+ Lookup/MasterDetail
     fields that are not audit-style names (OwnerId, CreatedById, ...).
  2. Fetch authoritative `referenceTo` info for each candidate via
     `composite/batch` describe calls (because Step 7's XML parser
     only sees `referenceTo` for custom fields; standard lookups like
     `AccountId` come back blank).
  3. Filter parents: drop system parents (User, Group, RecordType, ...),
     drop self-references, drop polymorphic FKs that point at >5 entities.
  4. Promote to "junction" if there are >= 2 distinct real-business
     parents AND at least one of:
       - exactly 2 distinct parents (classic bridge), OR
       - the object has 2+ RecordTypes (multi-mode junction), OR
       - non-FK field count <= 25 (thin connector), OR
       - any 2 of the parent FKs are non-nillable (junction with
         required parents — catches "fat" junctions like
         HealthcarePractitionerFacility that have many descriptive
         fields beyond the bridge itself).

Optional record-count enrichment (default on, controlled by
`--no-counts`) batches `SELECT COUNT(Id)` queries against the org via
the shared `_sf_session.SfSession` helper to upgrade confidence
classification:

  - high         — junction count >= 50% of the bigger parent's count
                   (the relationship is realised at scale)
  - medium       — junction populated but sparser than parents
  - low          — junction record_count == 0
  - schema_only  — no count data available (org access skipped)

Output: `config/schema/_junctions.toon`.

Usage
-----
    # Default (with org counts; auto-detects org alias)
    python3 scripts/schemapy/detect_junctions.py

    # Schema-only (no SOQL; faster, less accurate)
    python3 scripts/schemapy/detect_junctions.py --no-counts

    # Specific org
    python3 scripts/schemapy/detect_junctions.py --org <your-org-alias>

This script is automatically called by `auto_generate_schema.py` as
Step 11 of the pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Allow `from _toon_io import ...` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _toon_io import dump_toon, load_toon, find_project_root  # noqa: E402
from _sf_session import SfSession  # noqa: E402


# Parents we ignore when counting "real" relationships. These are
# system / config / audit references that almost every object has.
_SKIP_PARENT_OBJECTS: Set[str] = {
    'User', 'Group', 'Profile', 'UserRole', 'PermissionSet',
    'PermissionSetGroup', 'PermissionSetAssignment',
    'RecordType', 'BusinessHours', 'Site', 'Topic', 'Queue',
    'CollaborationGroup', 'ContentVersion', 'ContentDocument',
    'ContentDocumentLink', 'Attachment', 'Note', 'EmailMessage',
    'Task', 'Event', 'CalendarView', 'CronTrigger', 'AsyncApexJob',
    'ApexClass', 'ApexTrigger', 'Holiday',
}

# Field-name suffixes that indicate audit / system references.
_SKIP_FIELD_SUFFIXES: Tuple[str, ...] = (
    'OwnerId', 'CreatedById', 'LastModifiedById', 'ManagerId',
    'DelegatedApproverId',
)

# Maximum non-FK field count for a "thin junction" (objects with mostly
# relationship fields). Pure 2-FK bridges are accepted at any size.
_THIN_JUNCTION_FIELD_CAP = 25

# Cap on distinct parent entities: legitimate "fat" junctions in
# Health-Cloud-style schemas can bridge 10-12 entities (e.g.
# HealthcareFacilityNetwork). 15 leaves headroom while still excluding
# "fan-out" entities that just happen to reference everything.
_MAX_FK_PARENTS = 15


def _is_real_parent(obj_name: str, current_obj: str) -> bool:
    """Filter out system parents and self-references."""
    if not obj_name:
        return False
    if obj_name == current_obj:
        return False
    if obj_name in _SKIP_PARENT_OBJECTS:
        return False
    return True


def _is_skip_field(field_name: str) -> bool:
    """Filter out audit-style FK fields by name suffix."""
    return field_name.endswith(_SKIP_FIELD_SUFFIXES)


def _describe_url(api_version: str, object_name: str) -> str:
    """Build the relative composite/batch URL for an sObject describe."""
    return f"{api_version}/sobjects/{object_name}/describe"


class JunctionDetector:
    def __init__(
        self,
        combined_file: Optional[Path] = None,
        output_file: Optional[Path] = None,
        org_alias: Optional[str] = None,
        fetch_counts: bool = True,
    ):
        root = find_project_root()
        self.combined_file = Path(combined_file) if combined_file else root / 'config' / 'salesforce-er-schema.toon'
        self.output_file = Path(output_file) if output_file else root / 'config' / 'schema' / '_junctions.toon'
        self.fetch_counts = fetch_counts
        self.org_alias = org_alias if (org_alias or not fetch_counts) else self._detect_org_alias()
        self.session: Optional[SfSession] = None
        if fetch_counts:
            self.session = SfSession(org_alias=self.org_alias)

        # Populated by load()
        self.objects: List[Dict[str, Any]] = []
        self.objects_by_name: Dict[str, Dict[str, Any]] = {}

        # Populated by detect()
        self.candidates: List[Dict[str, Any]] = []

        # Populated by fetch_record_counts()
        self.record_counts: Dict[str, int] = {}

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
        print("Error: could not auto-detect target org. Pass --org or use --no-counts.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Phase 1 — load combined schema
    # ------------------------------------------------------------------

    def load(self) -> None:
        if not self.combined_file.exists():
            print(f"Error: combined schema not found: {self.combined_file}")
            print("Run Step 7 (`generate_sf_er_schema.py`) first.")
            sys.exit(1)
        print(f"Loading {self.combined_file}...")
        doc = load_toon(self.combined_file)
        sf = doc.get('salesforce_schema', {}) if isinstance(doc, dict) else {}
        self.objects = sf.get('objects', []) or []
        self.objects_by_name = {o.get('api_name'): o for o in self.objects if o.get('api_name')}
        print(f"  Loaded {len(self.objects)} objects")

    # ------------------------------------------------------------------
    # Phase 2 — loose candidate filter (any object with 2+ FK fields)
    # ------------------------------------------------------------------

    def _count_fk_like_fields(self, obj: Dict[str, Any]) -> int:
        """Count Lookup / MasterDetail fields that are not audit-style.
        We use this as a coarse pre-filter before paying for describe."""
        n = 0
        for f in obj.get('fields', []) or []:
            if f.get('type') not in ('Lookup', 'MasterDetail'):
                continue
            if _is_skip_field(f.get('api_name', '')):
                continue
            n += 1
        return n

    def detect_candidates(self) -> None:
        print("Phase 2: loose candidate detection (2+ non-audit FK fields)...")
        for obj in self.objects:
            obj_name = obj.get('api_name')
            if not obj_name:
                continue
            fk_count = self._count_fk_like_fields(obj)
            if fk_count < 2:
                continue
            self.candidates.append({
                'object': obj_name,
                'field_count': len(obj.get('fields', []) or []),
                'record_types': obj.get('record_types', []) or [],
                # Filled in by phase 3
                'parents': [],
                'distinct_parents': [],
                'non_fk_field_count': 0,
                'required_parent_count': 0,
            })
        print(f"  {len(self.candidates)} loose candidates")

    # ------------------------------------------------------------------
    # Phase 3 — fetch describes, extract authoritative FK parents
    # ------------------------------------------------------------------

    def fetch_describes_and_resolve_parents(self) -> None:
        """For each candidate, fetch its describe via composite/batch and
        rebuild its parent list using authoritative `referenceTo` data."""
        if not self.candidates or self.session is None:
            # If session is disabled (--no-counts implies no describes
            # either), fall back to whatever combined-schema reference_to
            # the candidate had, then prune to candidates with >=2 parents.
            self._fallback_parents_from_combined()
            return
        if not self.session.access_token:
            print(f"Fetching access token for {self.org_alias}...")
            self.session.initialise()
            print(f"  Instance: {self.session.instance_url}")

        names = [c['object'] for c in self.candidates]
        print(f"Phase 3: fetching {len(names)} describes via composite/batch...")
        urls = [_describe_url(self.session.api_version, n) for n in names]
        results = self.session.composite_batch_get(urls)

        kept: List[Dict[str, Any]] = []
        for cand, desc in zip(self.candidates, results):
            if desc is None:
                # Couldn't describe (no permission) — skip this candidate.
                continue
            parents = self._extract_parents_from_describe(cand['object'], desc)
            distinct = []
            seen = set()
            for p in parents:
                if p['object'] not in seen:
                    seen.add(p['object'])
                    distinct.append(p['object'])
            if not (2 <= len(distinct) <= _MAX_FK_PARENTS):
                continue
            cand['parents'] = parents
            cand['distinct_parents'] = sorted(distinct)
            cand['required_parent_count'] = sum(1 for p in parents if p.get('required'))
            cand['non_fk_field_count'] = max(
                0, cand['field_count'] - len(parents)
            )
            kept.append(cand)
        self.candidates = kept
        print(f"  {len(self.candidates)} candidates kept after describe-based filter")

    def _extract_parents_from_describe(
        self, current_obj: str, desc: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract real-business FK parents from a describe response."""
        out: List[Dict[str, Any]] = []
        for f in desc.get('fields', []) or []:
            if f.get('type') != 'reference':
                continue
            field_name = f.get('name', '')
            if _is_skip_field(field_name):
                continue
            refs = f.get('referenceTo') or []
            # Skip wide-polymorphic refs (Activity.WhatId etc) — they are
            # not stable bridge edges.
            if not refs or len(refs) > 3:
                continue
            for ref in refs:
                if not _is_real_parent(ref, current_obj):
                    continue
                out.append({
                    'field': field_name,
                    'object': ref,
                    'relationship_type': 'MasterDetail' if f.get('cascadeDelete') else 'Lookup',
                    'required': (f.get('nillable') is False),
                })
        return out

    def _fallback_parents_from_combined(self) -> None:
        """No-org fallback: derive parents from combined schema's
        reference_to (only populated for custom fields by Step 7)."""
        kept = []
        for cand in self.candidates:
            obj = self.objects_by_name.get(cand['object'])
            if obj is None:
                continue
            parents: List[Dict[str, Any]] = []
            seen = set()
            for f in obj.get('fields', []) or []:
                if f.get('type') not in ('Lookup', 'MasterDetail'):
                    continue
                if _is_skip_field(f.get('api_name', '')):
                    continue
                ref = f.get('reference_to')
                if not ref or not _is_real_parent(ref, cand['object']):
                    continue
                # Polymorphic refs come back as a list; skip wide ones.
                if isinstance(ref, list):
                    if len(ref) > 3:
                        continue
                    refs = ref
                else:
                    refs = [ref]
                for r in refs:
                    if not _is_real_parent(r, cand['object']):
                        continue
                    parents.append({
                        'field': f.get('api_name'),
                        'object': r,
                        'relationship_type': f.get('type'),
                        'required': bool(f.get('required')),
                    })
                    seen.add(r)
            if not (2 <= len(seen) <= _MAX_FK_PARENTS):
                continue
            cand['parents'] = parents
            cand['distinct_parents'] = sorted(seen)
            cand['required_parent_count'] = sum(1 for p in parents if p.get('required'))
            cand['non_fk_field_count'] = max(0, cand['field_count'] - len(parents))
            kept.append(cand)
        self.candidates = kept

    # ------------------------------------------------------------------
    # Phase 4 — promote candidates to junctions
    # ------------------------------------------------------------------

    def promote_junctions(self) -> None:
        kept: List[Dict[str, Any]] = []
        for c in self.candidates:
            n_parents = len(c['distinct_parents'])
            n_rt = len(c.get('record_types', []))
            if (
                n_parents == 2
                or n_rt >= 2
                or c['non_fk_field_count'] <= _THIN_JUNCTION_FIELD_CAP
                or c['required_parent_count'] >= 2
            ):
                kept.append(c)
        before = len(self.candidates)
        self.candidates = kept
        print(f"Phase 4: promoted {len(self.candidates)}/{before} candidates to junctions")

    # ------------------------------------------------------------------
    # Phase 3 — record counts (optional)
    # ------------------------------------------------------------------

    def fetch_record_counts(self) -> None:
        """Fetch COUNT(Id) for every junction candidate and every parent
        they reference, in a few composite/batch calls."""
        if not self.fetch_counts or self.session is None:
            return
        targets: Set[str] = set()
        for c in self.candidates:
            targets.add(c['object'])
            targets.update(c['distinct_parents'])

        names = sorted(targets)
        print(f"Phase 5: fetching record counts for {len(names)} candidate + parent objects...")
        # Session token is already cached from phase 3; only initialise
        # if we somehow got here without one.
        if not self.session.access_token:
            self.session.initialise()

        queries = [f"SELECT COUNT(Id) cnt FROM {n}" for n in names]
        results = self.session.composite_batch_query(queries)
        ok = 0
        for name, res in zip(names, results):
            if res is None:
                continue
            try:
                self.record_counts[name] = int((res[0] or {}).get('cnt', 0))
                ok += 1
            except Exception:
                pass
        print(f"  Got counts for {ok}/{len(names)} objects "
              f"({len(names) - ok} unreadable)")

    # ------------------------------------------------------------------
    # Phase 4 — confidence classification
    # ------------------------------------------------------------------

    def classify(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for c in self.candidates:
            junction_count = self.record_counts.get(c['object'])
            parent_counts = [self.record_counts.get(p) for p in c['distinct_parents']]
            has_counts = junction_count is not None and any(p is not None for p in parent_counts)

            if not has_counts:
                confidence = 'schema_only'
            elif junction_count == 0:
                confidence = 'low'
            else:
                pcs = [p for p in parent_counts if p is not None]
                bigger = max(pcs) if pcs else 0
                if bigger == 0:
                    confidence = 'low'
                elif junction_count >= bigger * 0.5:
                    confidence = 'high'
                else:
                    confidence = 'medium'

            note = self._derive_note(c)
            # Deduplicate parents in the emitted list (each parent
            # entity appears once even if multiple FKs point at it).
            seen = set()
            parents_out = []
            for p in c['parents']:
                key = (p['object'], p['field'])
                if key in seen:
                    continue
                seen.add(key)
                parents_out.append({
                    'object': p['object'],
                    'field': p['field'],
                    'relationship_type': p['relationship_type'],
                    'required': bool(p.get('required')),
                })
            out.append({
                'object': c['object'],
                'parents': parents_out,
                'record_count': junction_count if junction_count is not None else None,
                'confidence': confidence,
                'note': note,
            })
        # Sort: high → medium → low → schema_only, then by object name
        confidence_order = {'high': 0, 'medium': 1, 'low': 2, 'schema_only': 3}
        out.sort(key=lambda j: (confidence_order.get(j['confidence'], 9), j['object']))
        return out

    def _derive_note(self, c: Dict[str, Any]) -> str:
        parents = c['distinct_parents']
        rts = c.get('record_types') or []
        if len(parents) == 2:
            note = f"Bridges {parents[0]} and {parents[1]}"
        else:
            note = f"Bridges {len(parents)} entities: {', '.join(parents)}"
        if rts:
            rt_names = [rt.get('api_name') for rt in rts if rt.get('api_name')]
            if rt_names:
                note += f"; {len(rt_names)} RecordType(s): {', '.join(rt_names)}"
        return note + "."

    # ------------------------------------------------------------------
    # Phase 5 — emit _junctions.toon
    # ------------------------------------------------------------------

    def emit(self, junctions: List[Dict[str, Any]]) -> None:
        # Build a lighter "tabular" view alongside the rich one for AI
        # agents that just want a quick scan.
        summary_rows: List[Dict[str, Any]] = []
        for j in junctions:
            parents = j.get('parents') or []
            row = {
                'object': j['object'],
                'parent_a': parents[0]['object'] if len(parents) >= 1 else '',
                'parent_a_field': parents[0]['field'] if len(parents) >= 1 else '',
                'parent_b': parents[1]['object'] if len(parents) >= 2 else '',
                'parent_b_field': parents[1]['field'] if len(parents) >= 2 else '',
                'extra_parents': max(0, len(parents) - 2),
                'record_count': j['record_count'] if j['record_count'] is not None else -1,
                'confidence': j['confidence'],
            }
            summary_rows.append(row)

        notes = {j['object']: j['note'] for j in junctions}

        confidence_counts: Dict[str, int] = {}
        for j in junctions:
            confidence_counts[j['confidence']] = confidence_counts.get(j['confidence'], 0) + 1

        doc = {
            'summary': summary_rows,
            'junctions': junctions,
            'notes': notes,
            'metadata': {
                'generated_date': datetime.now().isoformat(),
                'total_junctions': len(junctions),
                'confidence_breakdown': confidence_counts,
                'source_file': str(self.combined_file),
                'uses_record_counts': self.fetch_counts and bool(self.record_counts),
                'note_about_record_count': "record_count == -1 means count was not collected (no org access or --no-counts)",
                'detection_signals': {
                    'thin_junction_field_cap': _THIN_JUNCTION_FIELD_CAP,
                    'max_fk_parents': _MAX_FK_PARENTS,
                    'system_parents_skipped': sorted(_SKIP_PARENT_OBJECTS),
                    'audit_field_suffixes_skipped': list(_SKIP_FIELD_SUFFIXES),
                },
            },
        }
        dump_toon(doc, self.output_file)
        print(f"\nWrote {self.output_file}")
        print(f"  Total junctions: {len(junctions)}")
        for conf in ('high', 'medium', 'low', 'schema_only'):
            cnt = confidence_counts.get(conf, 0)
            if cnt:
                print(f"    {conf:12s}: {cnt}")

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.load()
        self.detect_candidates()
        self.fetch_describes_and_resolve_parents()
        self.promote_junctions()
        self.fetch_record_counts()
        junctions = self.classify()
        self.emit(junctions)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Detect Salesforce junction objects from the combined schema',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--input',
        default=None,
        help='Combined schema file (default: <project-root>/config/salesforce-er-schema.toon)',
    )
    parser.add_argument(
        '--output',
        default=None,
        help='Output file (default: <project-root>/config/schema/_junctions.toon)',
    )
    parser.add_argument('--org', '-o', help='Salesforce org alias (auto-detected if omitted)')
    parser.add_argument(
        '--no-counts',
        action='store_true',
        help='Skip record-count enrichment (faster, less accurate confidence classification)',
    )
    args = parser.parse_args()

    detector = JunctionDetector(
        combined_file=Path(args.input) if args.input else None,
        output_file=Path(args.output) if args.output else None,
        org_alias=args.org,
        fetch_counts=not args.no_counts,
    )
    detector.run()


if __name__ == '__main__':
    main()
