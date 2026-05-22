"""
Shared Salesforce session + REST helpers for the schema pipeline.

Used by:
  - collect_usage_stats.py (Step 10)
  - detect_junctions.py (Step 11)

Provides:
  - SfSession: cached access token / instance URL / API version, fetched
    once via `sf org display --verbose --json`.
  - composite_batch_query: run up to 25 SOQL queries per HTTP call via
    Salesforce's `composite/batch` endpoint. We deliberately use
    `composite/batch` (not `composite`) because the regular `composite`
    endpoint hard-caps query subrequests at 5 per call; `composite/batch`
    permits up to 25.

SSL: stdlib's default trust store is empty on many Python installs
(notably python.org macOS builds and many venvs). We prefer `certifi`'s
bundled CA list when available; falls back to the system default.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


try:
    import certifi  # type: ignore
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _SSL_CONTEXT = ssl.create_default_context()


# Composite/batch limits documented by Salesforce
COMPOSITE_BATCH_SIZE = 25
COMPOSITE_TIMEOUT_S = 120
SF_DISPLAY_TIMEOUT_S = 30


def resolve_sf_exe() -> str:
    """Locate the `sf` CLI executable, with Windows fallbacks."""
    exe = shutil.which('sf')
    if exe:
        return exe
    if platform.system() == 'Windows':
        for c in [
            r'C:\Program Files\Salesforce CLI\bin\sf.cmd',
            rf'{os.environ.get("USERPROFILE", "")}\AppData\Roaming\npm\sf.cmd',
        ]:
            if c and os.path.isfile(c):
                return c
    print("Error: Salesforce CLI (sf) not found in PATH.")
    sys.exit(1)


@dataclass
class SfSession:
    """A cached Salesforce session: token, instance URL, API version."""

    org_alias: str
    sf_exe: str = field(default_factory=resolve_sf_exe)
    access_token: Optional[str] = None
    instance_url: Optional[str] = None
    api_version: str = 'v66.0'
    errors: List[str] = field(default_factory=list)

    def initialise(self) -> None:
        """Fetch the access token + instance URL once via `sf org display`."""
        result = subprocess.run(
            [self.sf_exe, 'org', 'display', '--verbose',
             '--target-org', self.org_alias, '--json'],
            capture_output=True, text=True, check=True,
            timeout=SF_DISPLAY_TIMEOUT_S,
        )
        data = json.loads(result.stdout)
        info = data.get('result') or {}
        self.access_token = info.get('accessToken')
        self.instance_url = info.get('instanceUrl')
        if not self.access_token or not self.instance_url:
            print("Error: could not extract accessToken / instanceUrl from sf org display.")
            sys.exit(1)
        api_v = info.get('apiVersion') or '66.0'
        self.api_version = f"v{api_v}" if not api_v.startswith('v') else api_v

    def composite_batch_query(
        self, queries: List[str]
    ) -> List[Optional[List[Dict[str, Any]]]]:
        """
        Run up to COMPOSITE_BATCH_SIZE SOQL queries in one HTTP call via
        the `/services/data/<v>/composite/batch` endpoint.

        Returns a list of equal length: each element is either the
        `records[]` for that query, or None if that sub-request errored.
        Sub-request errors are appended to `self.errors` for diagnostics.

        Larger query lists are automatically split across multiple HTTP
        calls.
        """
        if not queries:
            return []
        urls = [f"{self.api_version}/query?q={urllib.parse.quote(q)}" for q in queries]
        raw = self.composite_batch_get(urls, query_log=queries)
        # For query results, unwrap the `records[]` envelope.
        out: List[Optional[List[Dict[str, Any]]]] = []
        for r in raw:
            if r is None:
                out.append(None)
            else:
                out.append((r or {}).get('records', []))
        return out

    def composite_batch_get(
        self,
        urls: List[str],
        query_log: Optional[List[str]] = None,
    ) -> List[Optional[Dict[str, Any]]]:
        """
        GET multiple Salesforce REST endpoints in one HTTP call. Each URL
        must be relative (e.g. `v66.0/query?q=...` or
        `v66.0/sobjects/Account/describe`). Returns a parallel list of
        result bodies, with None for any failed sub-request.

        `query_log` is an optional parallel list used solely for richer
        diagnostic messages (e.g. the SOQL string behind a /query URL).
        """
        if not urls:
            return []
        if not self.access_token:
            self.initialise()

        results: List[Optional[Dict[str, Any]]] = []
        for i in range(0, len(urls), COMPOSITE_BATCH_SIZE):
            chunk = urls[i:i + COMPOSITE_BATCH_SIZE]
            log_chunk = (query_log[i:i + COMPOSITE_BATCH_SIZE]
                         if query_log is not None else chunk)
            results.extend(self._one_batch(chunk, log_chunk))
        return results

    def _one_batch(
        self,
        urls: List[str],
        log_for_diag: List[str],
    ) -> List[Optional[Dict[str, Any]]]:
        # composite/batch URLs are RELATIVE without leading slash.
        sub_requests = [{"method": "GET", "url": u} for u in urls]
        payload = {"batchRequests": sub_requests}
        req = urllib.request.Request(
            f"{self.instance_url}/services/data/{self.api_version}/composite/batch",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=COMPOSITE_TIMEOUT_S, context=_SSL_CONTEXT) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode('utf-8', errors='replace')
            except Exception:
                err_body = str(e)
            self.errors.append(f"composite/batch HTTP {e.code}: {err_body[:200]}")
            return [None] * len(urls)
        except Exception as e:
            self.errors.append(f"composite/batch request failed: {e}")
            return [None] * len(urls)

        # composite/batch results come back in request order; no referenceId.
        results = body.get('results', [])
        out: List[Optional[Dict[str, Any]]] = [None] * len(urls)
        for idx, sub in enumerate(results):
            if idx >= len(out):
                break
            if sub.get('statusCode') == 200:
                out[idx] = sub.get('result')
            else:
                err_body = sub.get('result') or {}
                err_code = (err_body[0].get('errorCode', '?')
                            if isinstance(err_body, list) and err_body else '?')
                err_msg = (err_body[0].get('message', '?')[:120]
                           if isinstance(err_body, list) and err_body
                           else str(err_body)[:120])
                self.errors.append(
                    f"sub-request idx={idx} status={sub.get('statusCode')} "
                    f"code={err_code} msg={err_msg} | url={log_for_diag[idx][:120]}"
                )
                out[idx] = None
        return out
