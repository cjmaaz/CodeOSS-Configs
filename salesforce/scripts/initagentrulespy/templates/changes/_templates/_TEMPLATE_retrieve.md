<!--
  TEMPLATE: Retrieve audit doc
  ============================
  Auto-generated after every full org-wide retrieve described in
  `docs/sf-org-mirror-retrieve.md`. The agent should copy this file to:

    changes/git/retrieve-<YYYY-MM-DD>-<HHMM>-<sandbox-alias>.md

  …then fill in every section with concrete values from the just-completed
  retrieve. Delete every <!-- ... --> guidance comment as you go. Strip
  sections that genuinely don't apply (write `n/a` with a one-line reason
  rather than deleting the heading entirely).

  This is not a development-work doc (use _TEMPLATE_bugfix.md / _story.md /
  _refactor.md for that). It is a snapshot record: what did the org look
  like at the moment we mirrored it, what changed since the last mirror,
  and which of those changes deserve a closer look.

  Why this doc exists: in a Salesforce repo where teammates deploy directly
  to the org (often via a VDI pipeline that commits later, or not at all),
  the local repo is rarely the source of truth. When something breaks in
  the org weeks from now, this audit lets you bisect by retrieve date and
  pinpoint roughly when a component shifted.

  ─────────────────────────────────────────────────────────────────────
  ASSUMES PLAN-FIRST WORKFLOW
  ─────────────────────────────────────────────────────────────────────

  This template is only filled in AFTER the agent has completed the
  multi-phase retrieve described in `docs/sf-org-mirror-retrieve.md`
  Phase 0 through Phase 2.22. That runbook (Phase 0.0) requires the
  agent to spawn an EXPLICIT TodoWrite plan covering every phase + the
  audit sub-phases + both git commits BEFORE running any `sf` command.

  If you arrived at this template without having spawned that plan, STOP
  and read `docs/sf-org-mirror-retrieve.md` § Phase 0.0 first — the
  plan-first discipline makes the long-running sequence resumable on
  partial failure (transient org timeouts, sandbox restarts, agent
  crashes). Skipping it means a mid-run failure is ambiguous about what
  actually finished, and the resuming agent often re-does Phase 1 from
  the top unnecessarily.

  ─────────────────────────────────────────────────────────────────────
  EXEMPTION FROM THE GENERAL STAGING RULE
  ─────────────────────────────────────────────────────────────────────

  The general "selective staging" rule in `.cursor/rules/changes-doc-mandatory.mdc`
  (name every file explicitly, never `git add force-app/`) DOES NOT APPLY
  to the retrieve audit workflow.

  By design, the retrieve mirror commits the entire mirrored `force-app/`
  snapshot as ONE commit (subject: `mirror(<alias>): sync from <alias> @ ...`),
  then this audit doc as the second commit (subject: `docs(retrieve): audit ...`).
  That whole-org snapshot IS the unit of work — splitting it would defeat
  the bisect-by-retrieve-date purpose of the audit.

  Follow Phase 3 of `docs/sf-org-mirror-retrieve.md` for the exact staging
  + commit pattern; do NOT try to apply selective staging here.

  Similarly, this template does NOT carry a "Revision log" or
  "Key changes — diff highlights" section (each retrieve is its own
  immutable snapshot; the §6 "What changed since the last mirror"
  section already serves that audit purpose). The same-thread →
  same-doc reuse pattern from the general rule also doesn't apply —
  every retrieve gets a fresh doc with a date-stamped filename.
-->

# Retrieve audit: `<sandbox-alias>` @ YYYY-MM-DD HH:MM

**Date (local):** YYYY-MM-DD HH:MM (UTC±HH:MM)
**Org alias:** `<sandbox-alias>`
**Org ID:** `<00D...>` (from `sf org display -o <sandbox-alias>`)
**Triggered by:** <user> (manual / scheduled / agent on request)
**Phases run:** <N> of <total> (e.g. "23 of 23" or "22 of 23 — Phase 1.4 skipped, see §7")
**Wall-clock:** ~XX min
**Outcome:** Succeeded / Partial (M failures, see §7) / Failed
**Mirror commit:** [`<short-hash>`](#9-mirror-commit-reference) (this doc references the metadata-snapshot commit; see §9)
**Doc commit:** (this commit — the audit doc itself)

<!--
  For "Outcome": be honest. If even one of the 23 phases finished with
  warnings that you weren't sure about, mark it Partial and explain in §7.
-->

---

## 1. TL;DR

<!--
  3-6 sentences. Plain English. Anyone on the team should be able to read
  this and understand: was the org busy or quiet since the last mirror,
  did anything obvious break, what (if anything) deserves immediate
  attention. No jargon, no acronyms without expansion.

  Good example:
    "Quiet weekend on `<sandbox-alias>` — only 1 new Apex class (`OrderProcessor`)
    and 2 IPs touched. The IP `OrderProcessing_Procedure_3` had a >50% line
    churn (flagged in §6.4); worth a look before tomorrow's QA push. No
    security or active/status flips. All 23 phases succeeded in ~21 min."

  Bad example:
    "Retrieve done. Some files changed. No errors."
-->

---

## 2. Per-phase status

<!--
  Table of the 23 phases (or however many were run). Carry over the status
  + wall-clock from the summary the runbook produces. If a phase needed a
  retry, mark it with an asterisk and explain in §7.
-->

| # | Phase | Status | Wall-clock |
|---|---|---|---|
| 0 | Pre-flight (`sf org list --all`) | OK | ~Xs |
| 1.1 | integration shard | Succeeded | Xs |
| 1.2 | community shard | Succeeded | Xs |
| 1.3 | content (filtered) | Succeeded | Xs |
| 1.4 | translations (filtered) | Succeeded | Xs |
| 1.5 | omnistudio small | Succeeded | Xs |
| 1.6 | code small | Succeeded | Xs |
| 1.7 | schema small | Succeeded | Xs |
| 1.8 | ui small | Succeeded | Xs |
| 1.9 | automation small | Succeeded | Xs |
| 1.10 | security small | Succeeded | Xs |
| 1.11 | modern auth + Apex notifications | Succeeded | Xs |
| 2.11 | AuraDefinitionBundle | Succeeded | Xs |
| 2.12 | Flow | Succeeded | Xs |
| 2.13 | FlexiPage | Succeeded | Xs |
| 2.14 | LightningComponentBundle | Succeeded | Xs |
| 2.15 | Layout | Succeeded | Xs |
| 2.16 | ApexClass | Succeeded | Xs |
| 2.17 | CustomObject | Succeeded | Xs |
| 2.18 | CustomField | Succeeded | Xs |
| 2.19 | OmniScript | Succeeded | Xs |
| 2.20 | OmniIntegrationProcedure | Succeeded | Xs |
| 2.21 | OmniDataTransform (DRs) | Succeeded | Xs |
| 2.22 | Profile | Succeeded | Xs |

---

## 3. Source-count deltas vs previous mirror

<!--
  Compare the post-retrieve count of each high-traffic type to the count
  in the *previous* retrieve audit (the last file under changes/git/).
  This is the headline number — at a glance: was this a quiet day or a
  busy one?

  If this is the first audit (no previous file), write "first mirror —
  no baseline" in the Delta column and leave Previous as `—`.
-->

| Metadata type | Previous | Current | Delta |
|---|---:|---:|---:|
| ApexClass | NNN | NNN | +N / -N / 0 |
| ApexTrigger | NN | NN | +N |
| LightningComponentBundle | NNN | NNN | +N |
| AuraDefinitionBundle | NN | NN | 0 |
| OmniScript | NNN | NNN | +N |
| OmniIntegrationProcedure | N,NNN | N,NNN | +N |
| OmniDataTransform (DRs) | N,NNN | N,NNN | +N |
| Layout | NNN | NNN | +N |
| FlexiPage | NNN | NNN | 0 |
| Flow | NN | NN | 0 |
| Profile | NN | NN | 0 |
| PermissionSet | NN | NN | 0 |
| CustomObject folders | NNN | NNN | +N |
| CustomField | N,NNN | N,NNN | +N |
| ExternalCredential | N | N | 0 |
| ExternalClientApplication | N | N | 0 |
| ApexEmailNotifications | N | N | 0 |

---

## 4. Changes by metadata type

<!--
  One subsection per metadata type that actually changed. Skip the types
  with zero changes (don't write empty subsections). Each subsection shows:

    - File count changed / created / deleted
    - Up to ~10 file paths inline. If more, link to `git diff --stat`
      output in `.retrieve-logs/current/_session.txt` instead of dumping
      200 lines.
    - One-line "what to look at first" suggestion if any file stands out

  ============================================================================
  HOW TO FILL §4 (mandatory workflow — runbook Phase 3.4.1 + 3.4.2)
  ============================================================================

  §4.1–§4.10 are NOT filled in a single pass. The runbook's Phase 3.4.1
  prescribes a TODO-driven, magnitude-ordered analysis: spawn one TodoWrite
  entry per metadata type that actually changed, ordered by descending
  line-churn (with tie-break by blast-radius weight — Apex / triggers /
  schema / security beats LWC / OmniStudio beats Profiles / FlexiPages /
  mechanical types). Work each todo end-to-end before moving on, so the
  per-type findings land deeply and you don't conflate types.

  As you work each per-type todo, ALSO:

    - For OmniStudio types (OmniScript, OmniIntegrationProcedure,
      OmniDataTransform) — when the diff includes a NEW `<Name>_<vN+1>.*`
      file AND a deactivation flip of the existing `<Name>_<vN>.*`,
      RUN a version-pair diff:

          git diff --no-index force-app/.../<Name>_<vN>.* \
                              force-app/.../<Name>_<vN+1>.*

      and summarize the substantive delta (added/removed elements, changed
      conditionals, DR/remote-action bundle swaps) in the §4.X row. Without
      this, "new version" reads as `+N lines from nothing` and the actual
      change is invisible.

    - For ApexClass / ApexTrigger — scan the class-declaration lines on
      both sides of the diff. A class-name change inside the same file
      (e.g. a casing flip like `XMLService -> XmlService`, OR a wholesale
      rename refactor) OR a filename-vs-declaration mismatch is a RENAME.
      Record both names inline in §4.1 AND flag it in §6.1 — these are
      easy to miss because the file path looks unchanged.

    - Record cross-type leads as you go (new Apex method names, new field
      API names, new IP UniqueNames, new LWC `@salesforce/apex/...` imports,
      new PermissionSet object/field grants paired with FlexiPage edits).
      You'll use these in §4.11 (cross-type synthesis) below.

  After every per-type todo is `completed`, spawn ONE FINAL synthesis todo
  per Phase 3.4.2 — that fills §4.11. Then update §1 TL;DR to LEAD with the
  holistic stories from §4.11, not just the headline counts from §3.

  Order roughly by blast radius (this matches the runbook's tie-break
  weights): ApexClass → triggers → LWC → OmniStudio → data model
  (objects, fields, layouts) → security → everything else.
-->

### 4.1 ApexClass — N changed, N created, N deleted

```
<paste from: git diff --stat HEAD~1 -- force-app/main/default/classes/ | head -30>
```

<!--
  Inline highlights (delete if none stand out):
    - `<ClassName>.cls`: <one-line note — "added new method foo()" / "removed test method bar()" / etc>
-->

### 4.2 ApexTrigger — N changed

<!-- Same shape -->

### 4.3 LightningComponentBundle — N bundles touched

<!-- For LWC, list bundle names (folder names under lwc/) rather than individual files -->

### 4.4 OmniScript — N changed

<!-- Use sub-bullets if a particular subType (e.g. InitialCredentialAppReview) saw multiple version bumps -->

### 4.5 OmniIntegrationProcedure — N changed

### 4.6 OmniDataTransform (DataRaptors) — N changed

### 4.7 CustomObject / CustomField — N changed

<!-- Bucket by object: list the parent object once, then the fields touched under it -->

### 4.8 Layout / FlexiPage — N changed

### 4.9 Profile / PermissionSet — N changed

### 4.10 Other types

<!-- Anything else: workflows, validation rules, named credentials, etc. -->

### 4.11 Cross-type synthesis

<!--
  Holistic findings that span TWO OR MORE §4.X subsections — coherent
  feature ships, paired security + UI changes, service+test+LWC trios,
  cross-class coordination flags, etc. This section is filled by the
  ONE FINAL synthesis todo from Phase 3.4.2 of the runbook, AFTER all
  per-type todos are completed.

  Connection signals to check (see runbook §3.4.2 for full table + worked
  examples):
    - New Apex method (§4.1) referenced by new/modified LWC import (§4.3)
    - New CustomField (§4.7) appearing in new picklist values on RecordTypes
      AND consumed by a new DataRaptor (§4.6)
    - New IP version (§4.5) paired with a new DR (§4.6) on the same domain
      (Order / Address / Account / Case / Activity Log / etc. — substitute
      your project's domain words)
    - PermissionSet object / field grants (§4.9) paired with FlexiPage
      updates (§4.8) on the SAME sObject (coherent feature enablement)
    - New `*Test.cls` + relaxed visibility on the source class (e.g.
      `private` -> `public`, or new `@TestVisible`)
    - Cross-class coordination flag (new `static Boolean` field on class A
      assigned by class B's batch / trigger logic to suppress a downstream
      side-effect)

  One row per coherent thread. If nothing crosses types, write `n/a — all
  diffs were independent / mechanical`. Don't pad.
-->

| Connection | Types involved | Holistic finding |
|---|---|---|
| [Short name of the thread] | §4.1 + §4.3 (e.g. ApexClass + LWC) | [One paragraph: what feature ships when these are read together, what to confirm with the owner, whether to expect downstream callers to migrate] |

---

## 5. Diff context (for cross-reference)

<!--
  Three useful artifacts a future investigator will want, without having
  to re-run anything. Keep these concise — link out to the full output
  rather than pasting thousands of lines.
-->

**Pre-retrieve HEAD:** `<full SHA>` — `<commit subject>` (captured at start of run, before any files were touched)

**`git diff --stat` total:**

```
<paste output of: git diff --stat <pre-retrieve-HEAD>..<mirror-commit> | tail -5>
```

(Total: N files changed, NNN insertions(+), NNN deletions(-))

**Full per-file diff:** see commit `<short-hash>` in §9. To reproduce:

```bash
git show --stat <short-hash>          # quick file list
git show <short-hash> -- force-app/main/default/classes/<ClassName>.cls   # focused view
```

---

## 6. Suspicion analysis

<!--
  Heuristic-driven flags. Each item below was generated mechanically by
  the agent from the diff; none of them BLOCKS the commit. They exist so
  a human can scan and ask "is this intentional?" If everything in a
  sub-bucket is benign, write "no flags" and move on.
-->

### 6.1 Possibly-breaking changes

<!--
  Detection patterns:
    - Apex test class lost a `@isTest` method or `static testMethod void` signature
    - Apex class flipped `with sharing` <-> `without sharing`
    - CustomField `<type>` element changed
    - CustomObject `<deploymentStatus>` flipped Deployed/InDevelopment
-->

| File | Flag | Detection signal |
|---|---|---|
| [`<path>`](<path>) | <short label> | <git diff snippet or 1-line cause> |

### 6.2 Security / access drift

<!--
  Anything under permissionsets/, profiles/, sharingRules/, roles/, groups/.
  These are the changes most likely to break authorization silently.
-->

| File | Type | Change summary |
|---|---|---|
| [`<path>`](<path>) | PermissionSet | <summary — "added FLS read on X.Y" / "removed object permission Z"> |

### 6.3 Active / status flips

<!--
  Detection patterns:
    - Flow `<status>Active</status>` <-> `<status>Draft</status>` / `<status>Obsolete</status>`
    - OmniScript `<IsActive>true</IsActive>` <-> `<IsActive>false</IsActive>`
    - OmniIntegrationProcedure same as above
    - ValidationRule `<active>true</active>` <-> `<active>false</active>`
    - Trigger `<status>Active</status>` flip
-->

| Component | Before | After |
|---|---|---|
| [`<path>`](<path>) | Active | Draft |

### 6.4 Structural overhauls (high blast radius)

<!--
  Detection patterns:
    - LWC `.js-meta.xml` changed (exposed API surface, isExposed, targets — affects deploy + page-layout placements)
    - IP / OmniScript with >50% line churn vs file size (suggests architectural rewrite, not a small edit)
    - ApexClass deleted
    - New CustomObject folder appeared
-->

| Component | Type of overhaul | Indicator |
|---|---|---|
| [`<path>`](<path>) | Large IP churn | <line count: was N, now M, +N% / -N%> |

---

## 7. WIP impact

<!--
  What was the state of the working tree BEFORE the retrieve started, and
  what happened to that WIP. Fill in whichever applies:
-->

- **WIP detected before retrieve:** yes / no
- **Action taken:** none / stashed (`git stash push -u -m 'pre-retrieve-<TS>'`) / user aborted
- **Pop result after retrieve:** clean / N conflicts (listed below) / n/a
- **Files that conflicted on pop:**
  - [`<path>`](<path>) — <one-line conflict description, e.g. "both modified force-app/main/default/classes/Foo.cls">

<!--
  If WIP was not stashed but exists in the same diff as the retrieve, call
  it out here explicitly so reviewers know not all changes are from the org.
-->

---

## 8. Retrieve warnings (non-fatal)

<!--
  Skim `.retrieve-logs/current/*.log` for `Warnings` blocks. Most are
  recurring Salesforce-side noise (listed in `docs/sf-org-mirror-retrieve.md`
  "Known non-fatal warnings"). If you see anything NEW (not in that list),
  flag it here. Otherwise write "all known recurring warnings, no new
  surprises".
-->

| Phase log | New warning fragment | Investigated? |
|---|---|---|
| `.retrieve-logs/current/19-omniscript.log` | `<warning text>` | yes — known issue, see runbook §Known non-fatal warnings |

---

## 9. Mirror commit reference

<!--
  This is the commit that ACTUALLY contains the metadata snapshot — the
  one this audit doc is about. It exists in the git history one commit
  before this doc's commit. Carry over the exact strings emitted by:
    git log -1 --format='%H%n%h%n%s' <mirror-commit>
-->

| Field | Value |
|---|---|
| **Full SHA** | `<full SHA>` |
| **Short SHA** | `<short SHA>` |
| **Subject** | `<commit subject>` |
| **Author** | `<git author>` |
| **Committed at** | YYYY-MM-DD HH:MM:SS (UTC±HH:MM) |
| **Files changed** | NNN |
| **Insertions / deletions** | +N,NNN / -N,NNN |

Quick verification:

```bash
git show --stat <short-hash>
git show <short-hash> -- changes/git/      # confirm this doc not yet in mirror commit
```

---

## 10. Open follow-ups

<!--
  Numbered list. Each item is concrete and actionable. If you've flagged
  anything in §6 that needs a human to look at, copy it here with a name
  or "owner: TBD". Empty list is acceptable: write "n/a — quiet retrieve,
  nothing to chase".
-->

1. <Concrete next step — e.g. "Confirm with @backend-team that the IP `OrderProcessing_Procedure_3` rewrite is intentional before tomorrow's QA push.">
2. <Concrete next step — e.g. "Diff the new PermissionSet against UAT to make sure no FLS regression.">
3. <Concrete next step — e.g. "If `<flagged ApexClass>` change came from a teammate, ping them in #salesforce-dev to confirm and pull the matching `changes/<slug>.md` doc if one exists.">

---

<!--
  Reminder: this doc is committed AFTER the metadata-snapshot commit
  referenced in §9. The two-commit pattern is mandatory and matches the
  rule in `.cursor/rules/changes-doc-mandatory.mdc`. The runbook
  `docs/sf-org-mirror-retrieve.md` (Phase 3) lays out the exact git
  commands to use.
-->
