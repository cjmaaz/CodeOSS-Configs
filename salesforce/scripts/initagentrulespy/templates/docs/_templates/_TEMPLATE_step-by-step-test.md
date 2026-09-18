<!--
  TEMPLATE: Post-implementation step-by-step AC test
  =================================================
  Copy to docs/ut/<work-id>/<slug>-<alias-slug>-step-by-step-test.md after
  implementation for delivery work with manually testable acceptance criteria.

  Keep this guide executable by a human tester:
  - use one `##` section per AC/scenario;
  - state exact records, inputs, UI actions, and expected values;
  - provide at least one deterministic query or UI path for every created
    record, and both when the surface supports both;
  - capture real before/after screenshots;
  - leave all tester checkboxes unchecked initially;
  - after the tester says verification is complete, independently verify their
    entered IDs/results read-only, fill gaps, and leave anything unproved
    unchecked.

  Delete these comments when creating a real guide. Never carry example IDs,
  aliases, object names, or values from another project into this template.
-->

# <work-id> — <feature> step-by-step test (`<test-org-alias>`)
Run this post-implementation checklist in `<test-org-alias>`; see the [AC visual delta](../../../changes/<change-slug>.md#acceptance-criteria-visual-delta) and full implementation record in the linked change document.

**Environment ledger**

| Item | Value |
|---|---|
| Test org alias | `<test-org-alias>` |
| Alias slug / assets directory | `<alias-slug>` / `assets/<alias-slug>` |
| Org ID | `<org-id-from-read-only-org-display>` |
| Deployment/version under test | `<deploy-id / version / commit>` |
| Test mode | `<read-only verification / approved process execution>` |
| Mutation authorization | `<read-only, or exact create/update/delete/external actions + record scope + approver + UTC timestamp>` |
| Run start (UTC) | `<YYYY-MM-DDTHH:MM:SSZ>` |
| Tester | `<name>` |
| Agent verifier | `<name/model or n/a until verification>` |

This guide represents exactly one environment. If the user supplies another alias, create a separate `docs/ut/<work-id>/<slug>-<alias-slug>-step-by-step-test.md` and `assets/<alias-slug>/` evidence set. Confirm its Org ID, rediscover records there, and never reuse IDs from another environment. Treat the added environment as read-only until the user authorizes exact process actions, record scope, side effects, cleanup, and timestamp.

**Test-record ledger**

| Scenario | Record purpose | Record label/number | Record ID | Eligibility evidence | Original values snapshot | Restore required? |
|---|---|---|---|---|---|---|
| AC1 | Fresh positive path | `<label>` | `<record-id>` | `<query/result proving every filter>` | `n/a — unmodified` | No |
| AC2 | Negative/edge path | `<label>` | `<record-id>` | `<query/result>` | `<path to snapshot or exact values>` | Yes/No |

**Exact input ledger**

Use distinctive, non-sensitive values that can be queried later. Prefer a marker such as `<work-id>-<scenario-id>-<run-utc>` over generic values like `test`.

| Input/form label | Exact value to enter | Why this value is identifiable | Restore after run? |
|---|---|---|---|
| `<field label>` | `<exact value>` | `<unique marker/date/reference>` | Yes/No |
| `<date field>` | `<YYYY-MM-DD>` | `<expected value for persistence check>` | Yes/No |
| `<picklist/radio>` | `<declared value>` | `<branch selected>` | No |

**Pre-run checklist**

- [ ] Confirm the alias and Org ID: `<read-only command or UI path>`.
- [ ] Confirm the deployment/version under test is active.
- [ ] Query every candidate record and prove it meets the production filters.
- [ ] Confirm only intended records can be affected.
- [ ] Confirm no other tester/job owns the same record or process.
- [ ] Record the exact mutation authorization: actions, record scope, external side effects, cleanup, approver, and UTC timestamp; use `read-only` only when no mutation will occur.
- [ ] Persist original values for anything staged or forced.
- [ ] Confirm every picklist, RecordType, lookup, and writable field against the target environment's schema.
- [ ] Capture all real before screenshots using `assets/<alias-slug>/<scenario-anchor>-before-<what>.png`.
- [ ] If runtime-before evidence cannot safely be captured, label it `source-backed baseline only`; never present a reconstruction as a screenshot.
- [ ] Record the UTC run-start time used by every creation-discovery query.
- [ ] Confirm stop conditions that prevent accidental external calls, orders, payments, notifications, or other irreversible actions.

<a id="<scenario-anchor>-test"></a>
## <scenario-id> — <acceptance-criterion or invariant title>
Given `<condition>`, when `<tester action>`, then `<concrete visible and persisted outcome>`.

**Earlier behavior**

- Version/baseline: `<previous version, commit, or dated source evidence>`.
- What the tester previously saw: `<exact screen/message/route/value>`.
- Why this is the defect or baseline behavior to preserve: `<one sentence>`.

Choose exactly one and delete the other:

![Before — <environment>, <record>, <visible value>](assets/<alias-slug>/<scenario-anchor>-before-<what>.png)

`n/a — source-backed baseline only: <version/commit/path and exact earlier behavior>; no real before screenshot was captured.`

**Step-by-step checklist**

- [ ] Open `<record label/number>` (`<record-id>`) in `<test-org-alias>`.
- [ ] Navigate: `<app/workspace>` → `<tab>` → `<action>` → `<screen>`.
- [ ] Confirm prerequisite `<label>` shows `<expected value>`.
- [ ] Enter/select the exact values below.

| Form/screen field | Enter/select | Expected immediate behavior |
|---|---|---|
| `<field label>` | `<exact value from input ledger>` | `<validation/branch/UI effect>` |
| `<field label>` | `<exact value>` | `<effect>` |

- [ ] Click `<button/action>`.
- [ ] Confirm the current implementation shows `<exact screen/message/value>`.
- [ ] Confirm it does not show `<old or forbidden behavior>`.
- [ ] Stop at `<safe boundary>` if completing the next action would create an unintended external side effect.
- [ ] Mark tester result: **Pass / Fail:** `<tester fills>`
- [ ] Tester notes/error text: `<tester fills or n/a>`

**Created-record discovery — required whenever this scenario creates anything**

Use the query below when the object is queryable. Otherwise replace it with the exact UI discovery path. Include both when available; do not rely only on `ORDER BY CreatedDate DESC LIMIT 1`.

```bash
sf data query -o <test-org-alias> -q "SELECT Id, <display-field>, <asserted-fields>, CreatedDate FROM <CreatedObject__c> WHERE <ParentLookup__c> = '<parent-record-id>' AND <MarkerField__c> = '<distinctive-input>' AND CreatedDate >= <run-start-utc> ORDER BY CreatedDate"
```

UI discovery path: open `<parent record>` → **Related** → `<related-list label>` → sort newest first → open the row whose `<marker/display field>` equals `<distinctive-input>` → copy the record ID from the URL/details.

- [ ] Record count expected: `<n>`.
- [ ] Record count found: `<tester/agent fills>`.
- [ ] Created record ID(s): `<tester/agent fills>`.
- [ ] Related/child record ID(s): `<tester/agent fills or n/a>`.
- [ ] Persisted field/value checks: `<tester/agent fills>`.
- [ ] Confirm no sibling/hidden/duplicate record was created.

**Current behavior and evidence**

![Current — <environment>, <record>, <visible value/result ID>](assets/<alias-slug>/<scenario-anchor>-after-<what>.png)

- Current visible result: `<exact value/message>`.
- Current persisted result: `<query/UI evidence and concrete ID>`.
- Change-doc diagram: [`<scenario-id> visual delta`](../../../changes/<change-slug>.md#<scenario-anchor>-visual-delta).

**Agent verification after the tester says “done”**

- [ ] Read the tester's checked steps, exact entered values, notes, and IDs.
- [ ] Re-run the recorded read-only discovery/assertion method against the declared alias: query and/or exact UI discovery path.
- [ ] Verify each created ID belongs to the intended parent, time window, marker, and record type.
- [ ] Verify exact values, counts, relationships, negative assertions, and absence of hidden/duplicate records.
- [ ] Fill any blank IDs/results the recorded discovery method proves.
- [ ] Correct stale or mistyped tester entries with the query/UI evidence.
- [ ] Leave unproved steps unchecked; do not convert a tester checkmark into agent verification without evidence.
- [ ] If verification requires re-running or mutating the process, stop and ask first.
- [ ] Agent verdict: **Pass / Fail / Blocked:** `<agent fills>`
- [ ] Evidence timestamp (UTC): `<agent fills>`

Duplicate the scenario section above for every acceptance criterion/invariant and for each accepted Gate finding that requires negative, bulk, concurrency, permission, or regression evidence.

**Final tester handoff**

- [ ] Every manually testable AC/invariant and required Gate scenario has its own completed section.
- [ ] Every created record has a deterministic discovery query or exact UI discovery path; both are included when available.
- [ ] Every form value entered is recorded exactly.
- [ ] Before and after evidence is real and correctly labelled.
- [ ] Staged/forced source records were restored from the snapshot.
- [ ] Process-created evidence records were left in place unless the user explicitly approved cleanup.
- [ ] Tester: `<name>`
- [ ] Tester completion time (UTC): `<timestamp>`
- [ ] Agent verification complete: Yes/No
- [ ] Agent verifier: `<name/model>`
- [ ] Final unresolved mismatches: `<none or explicit list>`

**Commit only when asked**

1. Commit the guide, staging/rollback artifacts, screenshots, and optional PDF with explicit paths.
2. Backfill the living `changes/<change-slug>.md` with the guide link and commit hash; commit that doc separately.
3. After the tester says “done”, commit the independently verified/finalized guide.
4. Backfill the living change doc with the verified-results hash and commit that update separately.
