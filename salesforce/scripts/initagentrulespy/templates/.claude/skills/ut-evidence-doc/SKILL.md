---
name: ut-evidence-doc
description: Create UT / UAT test-evidence documentation as a minimal, screenshot-heavy before/after walkthrough that proves each acceptance criterion end-to-end against a REAL run of the process under test (a batch/scheduled job, a queue or cron worker, an ETL pipeline, an API endpoint, or a UI flow). Use when the user asks for a UT doc, UAT doc, test evidence, QA walkthrough, or screenshot proof that each AC works. Stack-agnostic — name no specific org, language, or framework.
---

# UT / test-evidence documentation (before -> after walkthrough)

Produce a doc that PROVES each acceptance criterion (AC) works by running the real process and screenshotting state before and after. Evidence beats prose: minimal text, many screenshots.

Stack-agnostic vocabulary used below:
- **process under test** — whatever transforms the data: batch/scheduled job, queue/cron worker, ETL pipeline, API endpoint, UI flow.
- **record** — the entity the process consumes (input) or produces (output).
- **report/list** — the downstream view where a produced record should appear.
- **query** — a read against the data store (SQL, SOQL, API GET, etc.).

Companion rule: `.cursor/rules/ut-evidence-doc.mdc` (keep the two in sync).

## When to invoke

The user asks to create a "UT doc", "UAT doc", "test evidence", "QA walkthrough", or "screenshot proof that each AC works". Often follows finishing a feature.

## Output shape

`docs/ut/<work-id>/<slug>.md` + a sibling `assets/` folder of screenshots (+ optional `<slug>.pdf`). Screenshot names are predictable: `ac1-before-assessment.png`, `ac1-after-record.png`, etc.

Doc template — keep it this minimal (NO purpose / components / reproduce / summary sections):

```markdown
# UT <id> — <feature>

Each scenario uses a real <record> staged so the <process> picks it up. Screenshots show the before state (the record + the deciding detail) and the after state once the <process> ran (the record it created, the output or logged error, and that record in the downstream report/list).

---

## AC1 — <happy path, one sentence: condition -> expected outcome>

Before — the record picked up by the <process>, and its deciding detail:

![AC1 record staged](assets/ac1-before-record.png)
![AC1 deciding detail](assets/ac1-before-detail.png)

After running the <process> — the record created, the output produced, and that record in the report:

![AC1 created record](assets/ac1-after-record.png)
![AC1 output](assets/ac1-after-output.png)
![AC1 in the report](assets/ac1-after-report.png)

---

## AC2 — <next scenario, one sentence>
...
```

Each `![...]` caption should name the concrete IDs/values visible (record id, output id, error code) so the doc reads without opening the image.

## Workflow

Copy this checklist and track progress:

```
- [ ] 1. Identify the scenarios (one AC each: happy paths + negative/exception cases)
- [ ] 2. Find or stage a real record per scenario; snapshot anything modified
- [ ] 3. Verify eligibility + blast radius with a query (only intended records will be processed)
- [ ] 4. Capture ALL before screenshots
- [ ] 5. Run the process ONCE; verify outcomes with a query
- [ ] 6. Capture ALL after screenshots
- [ ] 7. Write the doc (+ optional PDF); commit (two-commit); roll back staged/forced changes
```

### Step 1 — Identify scenarios

One AC per scenario. Cover the happy path(s) AND the negative/exception cases the code handles (missing required data, out-of-range values, etc.). Confirm the AC list with the user if ambiguous (e.g. "AC1 in-territory, AC2 out-of-territory, AC3-5 the three missing-data errors").

### Step 2 — Find or stage a real record per scenario

- FIND a real record the process will pick up. Prefer real records over synthetic test data — they are more convincing evidence.
- If none qualifies, MODIFY one so it does (set the due/eligibility field the process filters on).
- For a negative scenario with no natural record, FORCE the gap on a real record (deactivate/blank the required data).
- **Snapshot first.** Before any modification, persist the original values somewhere durable (a snapshot record, a log row, or a file) so Step 7 can restore them. Capture: which records, which fields, their original values, and the ids of anything you deactivated.

### Step 3 — Verify eligibility + blast radius

Run the process's own selection query (or an equivalent) and confirm ONLY your intended records match. If the process runs org/system-wide, check how many other records share the trigger condition so the run does not balloon. Read the process's source to learn its exact filter (due date, status, "no existing child", etc.) rather than guessing.

### Step 4 — Capture ALL before screenshots

Open each input record and its deciding detail; screenshot full-page. Do this for every scenario BEFORE running, so the "before" set is internally consistent.

### Step 5 — Run the process ONCE; verify

Invoke the ACTUAL process the user ships (the batch/job/endpoint), not the underlying function directly — the point is to prove the real path. Wait for completion, then query the results: created records, outputs, error/exception rows, with their ids and codes. Only proceed once the data matches expectations.

### Step 6 — Capture ALL after screenshots

For each scenario: the created record, its output (or the logged error for a negative case), and the record appearing in the downstream report/list.

### Step 7 — Write, commit, roll back

Write the doc from the template, export a PDF if asked, then commit and restore (below).

## Screenshot capture (tool-agnostic)

- Open the app via an auto-login/session URL (most apps expose one), navigate to each record's URL, take a full-page screenshot, save with the predictable name.
- Screenshots often land in a temp directory; copy them into the repo `assets/` folder before committing.
- Prefer a real browser/automation session so the screenshots are the genuine app UI.

### Virtualized or iframed lists (the tricky bit)

Reports, dashboards, and infinite-scroll grids frequently render inside an iframe or virtualize their rows, so their in-app search/sort/scroll are NOT reachable by accessibility refs.

- If the list iframe is same-origin, scroll its internal scroll container programmatically (set `scrollTop`) until the target row renders, then screenshot. Virtualized lists only render near-visible rows, so scroll to the right position first.
- Sort direction helps: a newest-first sort surfaces a just-created record at the top of its group, so you scroll to the group header rather than hunting the whole list.
- If you cannot surface the exact row after a few attempts, fall back to a screenshot that shows the total count increased plus the record's own page — and say so. Do not fake it.

## Commit (two-commit) + rollback

Only commit when the user asks. Stage each path explicitly — never blanket-add a directory (another agent or the user may have unrelated changes in flight).

```bash
# Commit 1 — artifacts: staging/rollback scripts + UT doc + screenshots + PDF
git add scripts/<stage>.* scripts/<rollback>.* docs/ut/<id>/
git commit -m "docs(ut): <feature> test evidence (before/after walkthrough)"
git log -1 --format='%h'   # capture the short hash

# Commit 2 — backfill: link the UT doc + PDF from the living/feature doc, referencing commit 1
git add <living-feature-doc>
git commit -m "docs: backfill <feature> UT evidence (refs <hash-from-commit-1>)"
```

Then ROLL BACK the staging: restore the snapshot from Step 2 (re-activate/restore the forced-gap fields, restore eligibility fields). LEAVE the process-created records (the evidence) in place so they keep matching the screenshots.

## Anti-patterns

- "Purpose / Components / How to reproduce / Results summary" sections. Keep it to AC header + one sentence + screenshots.
- Synthetic dummy data when a real eligible record exists.
- Modifying real records with no snapshot/rollback.
- Calling the underlying function directly instead of running the real process — it does not prove the shipped path.
- A report screenshot that does not actually contain the target row (e.g. a 1000-row list scrolled to the wrong place). Surface the row first.
- "See attached screenshot" as the only AC description. State the condition + expected outcome in words too.
- One giant commit mixing the doc, the artifacts, and the living-doc backfill. Use the two-commit split.

## Adapting to other projects

Map the generic terms to your stack: process under test -> your batch/job/endpoint; record -> your entity/row/document; report/list -> your downstream view; query -> your DB/API read; auto-login URL -> your app's session link. Keep `docs/ut/` at the repo root (or change the path consistently here and in the companion rule). Nothing here assumes a specific org, language, or framework.
