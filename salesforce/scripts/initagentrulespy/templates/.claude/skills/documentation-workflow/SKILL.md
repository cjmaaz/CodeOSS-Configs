---
name: documentation-workflow
description: Runs the mandatory documentation lifecycle for Salesforce delivery work — every requirement, plan, bug, implementation, and wrap-up: intake, current-state/cascade analysis, LLD before code, blocking adversarial plan and implementation gates, changes documentation, and two commits. Scope matches the `adversarial-review` skill, which is the sole authority on which work needs a gate. Invoke proactively; mirrors `.cursor/rules/documentation-workflow.mdc`.
---

# Documentation workflow — intake + pre-coding/LLD + wrap-up + UT evidence

Three chronological touchpoints in every piece of Salesforce delivery work. **Be proactive at all three.** Retrieve before any edit (`retrieve-before-edit` skill); analysis on stale copies is wrong.

1. **Intake** (work starts) — confirm the ticket, transcribe any AC screenshot to text.
2. **Pre-coding analysis** — map cascading impact, author the **LLD**, then pass adversarial Gate A before editing.
3. **Implementation gate + wrap-up** — pass Gate B against the final diff/tests before deploy, mutation, commit, or handoff; then finalize the change doc and two commits.

The `adversarial-review` skill / `.cursor/rules/adversarial-review.mdc` is the sole authority for **which work needs a gate at all**, plus critic count, lenses, prompts, evidence, dispositions, the challenge loop, and re-review. This skill never widens or narrows that scope.

---

## Touchpoint 1 — Intake (run at work START)

Trigger the first time the user attaches a requirements screenshot, says "start/build/fix <ticket>", or names a new ticket. When unsure, treat it as intake. Run all five — don't collapse into one message:

1. **Get the ticket number — extract it, or PROACTIVELY ASK.** Pull the bug/story/case number from the message AND any attached screenshot/panel. If it's not there and the user didn't state it, proactively ASK before starting anything. Then read it back: _"Confirming this is for **<TRACKER-NNN>** — <summary>. Right?"_ Accept Jira / ADO / Salesforce Case Id / ad-hoc reference. Don't proceed without confirmation; if contradicted, re-ask — never guess.
2. **Name the chat after the ticket.** Once confirmed, rename the conversation to `<Bug/Story number> - <short description from what was shared>` (e.g. `Bug 567890 - PDA activation skips vendor effective date`). In Cursor, use the `cursor-app-control` `rename_chat` tool; in other tools set the conversation title equivalently. No ticket (rare ad-hoc)? Name it `<short description>`.
3. **Transcribe any visual requirement to TEXT** — read every AC off the image, write as numbered `AC1`, `AC2`, …, post back for confirmation, hold through the work. Mandatory even if "obvious"; screenshots rot and don't survive PR tooling.
4. **Capture explicit out-of-scope items**; if none stated, ASK.
5. **Stash the bundle** (ticket + ACs + out-of-scope) — it feeds the change-doc header, Requirements/In-scope/Out-of-scope, and AC-verification sections.

The final doc's ACs MUST be the transcribed text — never "see attached screenshot".

---

## Touchpoint 2 — Pre-coding analysis + LLD (after intake, BEFORE code)

Salesforce cascades hard: one insert → process builder → flow → trigger → another trigger touching a third sObject. Map it before coding. Run as a `TodoWrite` plan (one entry each):

- **E1 — Identify the touched surface:** sObjects (confirm shapes via `schema-lookup`), triggers (`grep -l "<sObject>" force-app/main/default/triggers/*.trigger`), flows, validation rules, OmniStudio (grep the IP/DR/OS dirs), Apex callers, custom metadata.
- **E2 — Map cascading impact:** for each create/update/delete, walk downstream (which triggers + flows fire, what DML, which other sObjects) recursively. Sketch a mermaid `flowchart` per `docs/diagram-conventions.md` — **one subgraph per component**, never per logical phase; legend line immediately above the fence; colour for state only (amber = the defect, red = dead end, grey = left unreachable). The LLD carries two such diagrams (current and proposed) sharing the same node IDs so a reader can diff them by eye.
- **E3 — Classify intended vs accidental:** tag each downstream effect. **Each ACCIDENTAL effect → a question to the user BEFORE coding.**
- **E4 — Author the draft LLD FIRST** (below). Don't edit source until current behavior, gap, and proposed design exist; reading current source is required.
- **E5 — Pass adversarial Gate A** via the `adversarial-review` skill. Record reviewer provenance, exact LLD revision, findings/dispositions, residual risk, and re-review. Resolve blockers before editing.
- **E6 — Spawn the preliminary `changes/<slug>.md`**, filling only architecture/design sections as a SHORT summary linking to the LLD. **Don't commit either yet.**

Tiny **in-scope** work may keep analysis concise but still runs Gate A with evidence-backed `N/A` entries. Work outside the delivery scope in `adversarial-review` needs no gate at all. Planning-only work ends only after Gate A passes.

### The LLD

Copy `docs/_templates/_TEMPLATE_lld.md` → `docs/lld/<work-id>-<short-kebab-slug>.md`. It proves you understand the system before touching it. Include current behavior, gap, evidence, design/alternatives, affected surface, cascading impact, Gate A reviewer evidence/dispositions, tests derived from findings, open questions, and a gated pre-implementation checklist.

Rules: read the LATEST source and cite paths/methods (don't guess); back the gap with read-only queries + headline numbers; design minimally (smallest additive change reusing existing mechanisms, list rejected alternatives); park unconfirmed assumptions in Open-questions — never bake them in as settled.

Two **conditional** companions (don't produce by reflex): `docs/lld/<work-id>-questions-and-kt.md` (only when assumptions need a stakeholder) and `docs/lld/<work-id>-walkthrough.md` (only when a live session is warranted). The change doc summarizes + links to the LLD — never duplicate the full design into both.

---

## Touchpoint 3 — Implementation gate + wrap-up (`changes/` doc + two-commit)

When implementation/validation tests are ready, run Gate B through `adversarial-review` — if the gate applies — before a real deploy/mutation/commit. Supply the evidence pack (base SHA, explicit changed-path list, `git diff --stat`) plus the profile's validation output. **The change doc does not get its own gate**: it records work the gates already reviewed, so reviewing the record adds cost without adding coverage. Finalize it after deploy verification and the code commit, then commit it.

### Template + name

Copy from `changes/_templates/` → `changes/<short-kebab-slug>.md`: `_TEMPLATE_bugfix.md`, `_TEMPLATE_story.md`, `_TEMPLATE_refactor.md`, or `_TEMPLATE_retrieve.md` (org-wide mirror retrieve → saves to `changes/git/retrieve-<date>-<time>-<alias>.md`; follow `docs/org-mirror/README.md`, plan-first; `change_kind: retrieve_mirror` = **Gate B only**, on the finished audit). Slug = kebab description, NOT the ticket number.

### Header block

```markdown
**Date:** YYYY-MM-DD
**Sandbox:** `{{ORG_ALIAS}}`
**Lead:** <Name> (<role>)
**Story / ticket:** [<TRACKER-NNN>](<url>) — <one-line summary>
**Code commit(s):** [`<short-hash>`](#deploy-ids-and-commit-references)
**Manifest:** [`manifest/<feature>.xml`](../manifest/<feature>.xml) (XML inlined in the Deploy-IDs section)
**Step-by-step test evidence:**
- `<test-org-alias>` — [`docs/ut/<work-id>/<slug>-<alias-slug>-step-by-step-test.md`](../docs/ut/<work-id>/<slug>-<alias-slug>-step-by-step-test.md) · initial `<hash / pending>` · verified `<hash / pending tester>`
- `<additional-org-alias>` — `<guide + initial/verified hashes, repeat as needed>` / n/a
**Status:** Resolved / Delivered / In progress
```

`**Manifest:**` is REQUIRED for any `--manifest` deploy; inline its full XML so reviewers don't open another file.

### Two-commit strategy: code first, doc second

Prerequisite where Gate B applied: `PASS` or `PASS_WITH_FINDINGS`; no Critical/High; every Medium resolved or explicitly accepted. Where it did not apply or the user waived it, the one-line record of that is the prerequisite instead.

Immediately before the code commit, re-run `git diff --name-only <base>` and confirm the changed-path list still matches what Gate B reviewed; a path appearing or vanishing is a new revision and reruns the gate. Before the doc commit the doc must be final — all IDs, hashes, and prose already filled in.

1. **Stage ONLY files you intentionally modified** — name each path. NEVER `git add force-app/` (blanket) — another agent/job may have in-flight changes. Sanity-check `git status -s`; recover with `git diff --name-only [--cached|HEAD]`. A dirty file that isn't yours: leave it. (Exception: the org-wide retrieve commits the whole mirror as one snapshot by design.)
   If unrelated dirty work prevents a complete Gate B snapshot, use an isolated worktree or stop/coordinate; never omit changed paths and claim complete review.
2. Commit the code with a multi-line HEREDOC message (subject ≤72 chars imperative; what/why; sub-changes).
3. Capture the hash: `git log -1 --format='%H%n%h%n%s'`.
4. Finalize the doc, fill in the Gate A/B outcome sections, then commit it SEPARATELY. The doc itself is not gated.
5. Verify: `git log -2` + `git status -s`; report both hashes.

### Filling the doc

- Header: paste the confirmed ticket from intake; fill `**Manifest:**` if used.
- Requirements: paste the transcribed AC text verbatim (one row per AC, Source column = origin); out-of-scope as a bullet list. Never "see attached screenshot".
- Revision log (top): first row = date, hash, what, why.
- Adversarial review: record Gate B status/revision, reviewer provenance, category coverage, findings/dispositions, residual risk, and re-review; link Gate A details from the LLD.
- **Key changes — diff highlights:** for OmniScripts / IPs / DataRaptors / FlexiPages / layouts / validation rules / formula fields / new Apex, paste a trimmed ```diff``` (small/medium) OR cite line ranges + key method names (large/new). Skip only for 1-2 line obvious changes.
- Link the step-by-step guide and add `### Acceptance-criteria visual delta`: paired component-scoped before/current Mermaid excerpts for visual ACs, each linked to the matching guide anchor. Data-only ACs state `n/a` and keep query/log evidence.
- Replace every `<...>`; delete the guidance comments; write `n/a` (+ reason) for inapplicable sections. Keep the **Gate A / Gate B outcome** sections — they are the review's audit trail, not guidance.

### Same thread, same doc

Iterating on the SAME flow/class/OmniScript → ONE doc. Append the new hash to the header, add a Revision-log row + a Diff-highlights sub-section, restate §1 (TL;DR) to the CUMULATIVE state. If iteration N+1 invalidates N, restate §1/§7 and mark the old Revision row `(superseded by <hash>)` — never delete. New doc only for a clearly different feature, or once the prior doc merged to `main`.

---

## Post-implementation step-by-step AC testing

Automatically create a guide after implementation when the delivery has manually testable ACs; also trigger on "UT/UAT doc", "test evidence", "QA walkthrough", or "screenshot proof". If none are manually testable, put `n/a` in the change doc.

Copy `docs/_templates/_TEMPLATE_step-by-step-test.md` to `docs/ut/<work-id>/<slug>-<alias-slug>-step-by-step-test.md` with `assets/<alias-slug>/` (+ optional PDF). Its intro links back to the change doc's `#acceptance-criteria-visual-delta`; each AC/scenario gets one detailed `##`.

1. Record the test alias + Org ID. Use the user-supplied alias or project default. For an additional/higher alias, create a separate alias-qualified guide/assets set, rediscover records there, and keep it read-only until exact actions, scope, side effects, cleanup, approver, and timestamp are authorized.
2. Find a real eligible record; snapshot/restore any staged fields. Carry accepted Gate negative/bulk/concurrency/regression cases.
3. Record exact, distinctive non-sensitive inputs and detailed UI steps: path, field label, value, button, expected result, safe stop.
4. Every created record needs at least one deterministic parent/marker/time-window query or exact UI discovery path; include both when available. Never leave an ID blank with no discovery method or rely only on "newest record".
5. Give each scenario stable `<scenario-anchor>-test` and `<scenario-anchor>-visual-delta` anchors with direct links both ways. Capture real before/current screenshots under `assets/<alias-slug>/`, named from the scenario anchor and captioned with alias, record ID, and values. If no safe runtime-before exists, replace the image with `source-backed baseline only`; never fake it.
6. Run the actual shipped process only after applicable Gate B, query outcomes, restore staged source values, and leave process-created evidence.
7. Hand the unchecked guide to the tester. When they say done, independently repeat the recorded read-only query and/or exact UI discovery path against the declared alias; verify IDs, parents, marker/time, exact values, counts, relationships, and no hidden/duplicate records. Fill proven blanks, correct errors, and leave unproved steps unchecked.
8. Never rerun/mutate solely to finish the guide; ask first.

Commit only when asked: guide/assets commit → living-doc link/hash backfill commit. After tester completion: verified-guide commit → verified-results hash backfill commit.

---

## Anti-patterns

- Starting code without a confirmed ticket (extract or ASK — never guess), or without renaming the chat `<ticket> - <description>`; treating a screenshot as the source of truth; "see attached screenshot" in §3.
- Writing the LLD AFTER coding; producing questions-and-kt / walkthrough by reflex; duplicating the full design into both LLD and change doc.
- Skipping a gate that applies, or gating work the review rule exempts; serializing or coaching reviewers; using fewer than the two defect critics plus the minimality critic; self-certifying when subagents are unavailable; majority-voting away blockers; relying on a verdict for a materially changed plan/diff; or informally re-running a gate the user waived.
- Inlining the doc into the code commit; `git add force-app/` (blanket) when another agent may be active; including a file you didn't touch.
- Missing the `**Manifest:**` line; skipping Diff-highlights for OmniScripts/IPs/DRs/layouts; pasting a 500-line file into a diff fence.
- UT/UAT: synthetic data when a real record exists; no snapshot/rollback; helper instead of shipped process; IDs reused across orgs; unspecified form values; no created-record discovery path; trusting checkmarks without queries; fake before screenshots; or screenshots that omit the target row.

## Adapting to other projects

Stack-agnostic. Map terms: process under test → batch/job/endpoint; record → entity/row; downstream automation → triggers/jobs/events; read-only query → DB/API read. Keep `changes/`, `docs/lld/`, `docs/ut/` at the repo root (or adjust consistently). Sandbox alias is `{{ORG_ALIAS}}`; set per-project from `sf config get target-org`.
