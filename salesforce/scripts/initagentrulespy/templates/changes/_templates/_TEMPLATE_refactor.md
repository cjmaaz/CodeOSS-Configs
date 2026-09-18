<!--
  TEMPLATE: Refactor / tech-debt / optimization changes doc
  =========================================================
  Copy this file to changes/<short-kebab-slug>.md and fill it in.
  Delete guidance comments, but KEEP the `Adversarial Gate B`
  section in full (heading, all three tables, and the bold summary lines).
  It is the review's audit trail, not guidance.
  Strip any sections that genuinely do not apply.

  Naming: short kebab-case describing the refactor or perf win.
    Good: account-trigger-handler-extraction.md, hfn-creation-async-batch-migration.md
    Bad:  refactor1.md, cleanup.md, perf-fix.md
-->

# <Short title — what was refactored or optimized>

**Date:** YYYY-MM-DD
**Sandbox:** `<sandbox-alias>`
**Lead:** <Name> (<role>)
**Story / ticket:** [<TRACKER-NNN>](<url>) — <one-line summary> (or "internal tech-debt cleanup" if no ticket)
**Code commit(s):** [`<short-hash>`](#13-deploy-ids-and-commit-references) (latest; full list in section 13)
**Manifest:** [`manifest/<feature>.xml`](../manifest/<feature>.xml) (the deploy manifest used; XML inlined in section 13)
**Step-by-step test evidence:**
- `<test-org-alias>` — [`docs/ut/<work-id>/<test-slug>-<alias-slug>-step-by-step-test.md`](../docs/ut/<work-id>/<test-slug>-<alias-slug>-step-by-step-test.md) · initial `<hash / pending>` · verified `<hash / pending tester>`
- `<additional-org-alias>` — `<guide + initial/verified hashes, repeat as needed>` / n/a
**Status:** Delivered / Functional parity verified, perf gain pending measurement / In progress
**Adversarial Gate B:** Pending / PASS / PASS_WITH_FINDINGS / BLOCK
**Implementation revision reviewed:** `<base SHA..HEAD + explicit changed-path list>`

<!--
  **Code commit(s)** — singular hash for a one-shot refactor; comma-separated
  list when this thread iterated and the same doc grew over multiple commits
  (see the "Revision log" section below).

  **Manifest** — REQUIRED when the refactor involved `sf project deploy start
  --manifest <file>`. If you didn't use a manifest, write "n/a — used
  `--metadata` flags only" and list those flags in section 13.
-->

---

## 1. TL;DR + status

<!--
  3-6 sentences. Plain English. What was the technical problem, what's the new
  shape, what got measurably better, and what's left to verify in higher
  environments.

  If this thread spans multiple commits, this section describes the CUMULATIVE
  state of the refactor as of the latest commit — not just the latest patch.
-->

---

## 2. Revision log

<!--
  ONE row per code commit on this thread. New commits APPEND a row here
  rather than spawning a new doc. See `.cursor/rules/documentation-workflow.mdc`
  "Same thread, same doc" for the rule.

  - For a one-shot refactor that ships in a single commit, this section is
    a one-row table — that's fine.
  - If an iteration superseded a previous approach, mark the older row
    "(superseded by <hash> — see row N)". Don't delete superseded rows.
-->

| # | Date (UTC) | Code commit | What was done | Why |
|---|---|---|---|---|
| 1 | YYYY-MM-DD HH:MM | [`<short-hash>`](#13-deploy-ids-and-commit-references) | <one-line plain English> | <initial refactor / follow-up callsite migration / perf-regression fix> |

---

## 3. Motivation — what was wrong

<!--
  Be specific about the pain. Avoid vague "code smell" language. Concrete
  examples of motivations:
    - "Same 80-line block of FLS-check logic copy-pasted across 7 controllers."
    - "Trigger handler runs 14 SOQL queries per record; bulk insert of 200 hits
      governor limits at row ~140."
    - "OmniScript's synchronous HFN creation step takes 18 seconds for a
      typical Par Form, blocking the user; needs to be async."
    - "DataRaptor returns nested JSON requiring 3 manual flatten steps in every
      caller."

  If a metric was measured, cite it (record IDs, log IDs, debug log lines).
-->

| Pain point | Concrete evidence |
|---|---|
| <one-line pain> | <metric / file / log id> |
| <one-line pain> | <metric / file / log id> |

---

## 4. Scope

<!--
  Crisp in/out lists. Refactors are notorious for creep — pin it down.
-->

### In scope

- <one-line item>
- <one-line item>

| AC / invariant | Verbatim requirement / behavior to preserve | Source |
|---|---|---|
| AC1 | <confirmed text; never “see screenshot”> | <ticket/design/comment> |
| INV1 | <existing observable behavior that must remain unchanged> | <source/test> |

### Out of scope (explicitly)

- <one-line non-goal — note follow-up ticket if applicable>
- <one-line non-goal>

---

## 5. Before / after architecture

> Full design — current state, target state, and the alternatives weighed — lives in the LLD at [`docs/lld/<work-id>-<slug>.md`](../docs/lld/<work-id>-<slug>.md). Keep this section a before/after summary that links there.

<!--
  ──────────────────────────────────────────────────────────────────────
  FILL UP FRONT (per `.cursor/rules/documentation-workflow.mdc` Step E6 — keep it a summary that links to the LLD)
  ──────────────────────────────────────────────────────────────────────
  Both halves of this diagram belong UP FRONT, before any code edit.
    - The BEFORE half is the output of Step E1 + Step E2 from the
      pre-coding analysis (surface map + dependency chain — accurate
      reflection of the current org state, NOT a pretty version of it).
    - The AFTER half is the intended post-refactor shape, designed
      while you still have time to push back on it. Refactors that
      draw the after-diagram for the first time at wrap-up tend to
      retro-fit the diagram to the code that happened to land —
      defeating the "is this shape actually better?" review purpose
      of the section.
  Update the AFTER half at wrap-up if the implementation diverged, but
  never start with the section blank.

  Node labels, legends, and the colour palette follow
  docs/diagram-conventions.md. Use separate before/after diagrams and one
  subgraph per deployable component — never state-named BEFORE/AFTER subgraphs.
  Keep unchanged node IDs identical across both diagrams.
-->

**Before legend.** <only the symbols used> 🟣 Apex · 🟢 LWC renderer. Amber = the shape being retired.

```mermaid
flowchart TD
    subgraph C1["🟣 APEX · <CallerClass> — entry point"]
        CALL["<CallerMethod>"]
    end
    subgraph M1["🟣 APEX · <MonolithClass> — responsibilities being separated"]
        MONO["<b><MonolithMethod></b><br/><what it conflates>"]
    end
    subgraph F1["🟣 APEX · <SideEffectClass> — downstream behavior"]
        FX["<SideEffectMethod>"]
    end

    CALL --> MONO --> FX

    style MONO fill:#fff3cd,stroke:#b8860b,stroke-width:2px
```

**After legend.** <only the symbols used> 🟣 Apex · 🟢 LWC renderer. Markers: ✨ new · 🔧 modified · ♻️ reused. Green = the target shape.

```mermaid
flowchart TD
    subgraph C1["🟣 APEX · <CallerClass> — entry point"]
        CALL["<CallerMethod> ♻️<br/>unchanged contract"]
    end
    subgraph S1["🟣 APEX · <ServiceClass> — focused orchestration"]
        SVC["<b><ServiceMethod></b> ✨"]
    end
    subgraph R1["🟣 APEX · <RepositoryClass> — data access"]
        REPO["<RepositoryMethod> ✨"]
    end
    subgraph F1["🟣 APEX · <SideEffectClass> — downstream behavior"]
        FX["<SideEffectMethod> ♻️"]
    end

    CALL --> SVC --> REPO --> FX

    style SVC fill:#d9f2d9,stroke:#080,stroke-width:2px
    style REPO fill:#d9f2d9,stroke:#080
```

| Aspect | Before | After |
|---|---|---|
| <Aspect — e.g. number of classes> | <value> | <value> |
| <Aspect — e.g. SOQL queries per call> | <value> | <value> |
| <Aspect — e.g. file lines / cyclomatic> | <value> | <value> |
| <Aspect — e.g. coupling shape> | <description> | <description> |

---

## 6. Behavioral invariants preserved

<!--
  THE most important section of a refactor doc. The whole point of refactoring
  is "no behavior change" — prove it. List every observable behavior that must
  remain identical, and show how you confirmed each.

  If you intentionally changed any behavior (e.g. fixed a latent bug along the
  way), call it out separately so reviewers don't miss it.

  ──────────────────────────────────────────────────────────────────────
  FILL UP FRONT (per `.cursor/rules/documentation-workflow.mdc` Step E6 — keep it a summary that links to the LLD)
  ──────────────────────────────────────────────────────────────────────
  The invariant list is itself the output of Step E3 (intended-vs-
  accidental side-effect classification). Every INTENDED row from E3
  becomes an "Invariant" row here BEFORE you start coding — that way
  you know exactly what your test plan must cover. The "How preserved"
  + "Evidence" columns get filled progressively during coding (you
  write the test, then paste its name as evidence). The "Intentional
  behavior changes" subsection below is for INTENDED-but-deliberately-
  CHANGED behaviors that came out of an E3 conversation with the user.
-->

| Invariant | How preserved | Evidence |
|---|---|---|
| <e.g. "trigger fires before insert and before update only"> | <e.g. "kept BeforeInsert/BeforeUpdate context check in handler"> | <e.g. "TriggerHandlerTest.testContextRouting"> |
| <e.g. "AccountHistory entries written for X, Y, Z fields"> | <how> | <evidence> |

### Intentional behavior changes (if any)

<!--
  If you fixed a latent bug or removed a feature flag, note it here. Otherwise
  delete this subsection.
-->

| Behavior | Old | New | Why changed |
|---|---|---|---|
| <description> | <old> | <new> | <reason — link to bug ticket if applicable> |

---

## 7. Migration steps

<!--
  Only relevant if the refactor requires data migration, callout updates,
  custom-metadata changes, or any one-time operation. Skip otherwise.
-->

### One-time operations

| # | Step | Command / runbook | Reversible? |
|---|---|---|---|
| 1 | <e.g. "Backfill new field from formula"> | `<command>` | <yes/no> |
| 2 | <e.g. "Update Custom Metadata records to point at new endpoint"> | `<command>` | <yes/no> |

### Caller migration (if API surface changed)

<!--
  If you renamed/relocated a method or changed a signature, list every caller
  and confirm it was updated.
-->

| Caller | Path | Updated in this commit? |
|---|---|---|
| `<class>` | [`<path>`](<path>) | yes |
| `<class>` | [`<path>`](<path>) | yes |

---

## 8. Key changes — diff-style highlights

<!--
  Refactors are inherently large — even a "small" extraction touches many
  files. `git diff` rarely tells a reviewer "what's the point". Use this
  section to surface the meaningful before/after for the parts that aren't
  obvious from a callsite-by-callsite diff.

  Two patterns by change size:

  ▸ SMALL / MEDIUM change (the meaningful diff fits in ~30 lines):
    Paste the relevant snippet in a `diff` fence with a one-line
    commentary above it. Trim noise — only the lines that matter.

  ▸ LARGE change (new file, full rewrite, > ~100 lines):
    Cite line ranges + key method names. DO NOT paste a 500-line code dump.

  ▸ TRIVIAL change (1-2 line callsite update repeated across N files):
    Show ONE example diff and write "Same pattern applied to N callers — see commit `<hash>`".

  See `.cursor/rules/documentation-workflow.mdc` "Diff-style highlights"
  for the full guidance.

  Add one sub-section per significant change. On iterative threads
  (multiple commits in this doc), each new commit gets a new sub-section
  here — do NOT overwrite the previous ones.
-->

### 8.1 — <component / file> — <one-line summary>

**File:** [`<path>`](<path>)
**Type of change:** Extracted / Inlined / Renamed / Rewritten
**Commit:** [`<short-hash>`](#13-deploy-ids-and-commit-references)

```diff
- <old line>
+ <new line>
```

### 8.2 — <component / file> — <one-line summary>

**File:** [`<path>`](<path>)
**Type of change:** Created (lines 1-N) / Whole-file rewrite
**Commit:** [`<short-hash>`](#13-deploy-ids-and-commit-references)

Whole file is too long to paste inline. Key sections:

- Lines 1-50: <description>
- Lines 51-180: <description of the meat>
- Lines 181-N: <description of the rest>

See commit `<short-hash>` for the full file.

---

## 9. Verification — functional parity

<!--
  Prove the refactor didn't break anything. Common approaches:
    - Run the full test suite (or a targeted subset) and show pass/fail counts
    - Compare snapshot outputs between old and new implementations
    - Run the same input through both and diff record counts/states
    - Spot-check critical user flows manually
-->

### Apex test results

```bash
sf apex run test --class-names <TestClass1>,<TestClass2> -o <sandbox-alias> \
  --synchronous --code-coverage --result-format human --wait 10
```

| Test class | Pass | Fail | Coverage % |
|---|---|---|---|
| `<TestClass>` | <count> | 0 | <percent>% |

### Acceptance criteria / invariant evidence

| AC / invariant | Verification | Evidence | Pass? |
|---|---|---|---|
| AC1 | <test/scenario> | <result/log/snapshot> | yes/no |
| INV1 | <old-vs-new comparison> | <evidence> | yes/no |

### Acceptance-criteria visual delta

<!--
  Use this only for visually observable ACs/invariants. A refactor normally
  proves parity: real before/current screenshots should match even if internal
  component ownership changed. Link to the detailed guide. Use separate,
  component-scoped Mermaid excerpts with stable node IDs; never BEFORE/AFTER
  state subgraphs. Data-only invariants stay in the table above.
-->

<a id="<scenario-anchor>-visual-delta"></a>
#### <scenario-id> — <visible behavior preserved>

[Run the detailed `<scenario-id>` checklist](../docs/ut/<work-id>/<test-slug>-<alias-slug>-step-by-step-test.md#<scenario-anchor>-test). Full diagrams: [current](../docs/lld/<work-id>-<slug>.md#4-current-behavior-as-built) · [proposed](../docs/lld/<work-id>-<slug>.md#73-where-it-plugs-in).

Choose a real screenshot or `n/a — source-backed baseline only`:

![Before — <test-org-alias>, <record label/id>, <visible value>](../docs/ut/<work-id>/assets/<alias-slug>/<scenario-anchor>-before-<what>.png)

**Before excerpt. Legend:** 🟣 Apex · 🟢 LWC. Amber = old internal route; the visible outcome is the parity target.

```mermaid
flowchart TD
    subgraph C1["<SYMBOL> <TYPE> · <ComponentName> — <scenario-id> excerpt"]
        ENTRY["<entry>"] --> ROUTE["<b><old internal route></b>"] --> OUTCOME["<visible outcome><br/><parity value>"]
    end

    style ROUTE fill:#fff3cd,stroke:#b8860b,stroke-width:2px
    style OUTCOME fill:#d9f2d9,stroke:#080
```

![Current — <test-org-alias>, <record label/id>, <same visible value>](../docs/ut/<work-id>/assets/<alias-slug>/<scenario-anchor>-after-<what>.png)

**Current excerpt. Legend:** 🟣 Apex · 🟢 LWC. Green = verified parity.

```mermaid
flowchart TD
    subgraph C1["<SYMBOL> <TYPE> · <ComponentName> — <scenario-id> excerpt"]
        ENTRY["<entry>"] --> ROUTE["<b><new internal route></b> 🔧"] --> OUTCOME["<visible outcome> ♻️<br/><same parity value>"]
    end

    style ROUTE fill:#d9f2d9,stroke:#080,stroke-width:2px
    style OUTCOME fill:#d9f2d9,stroke:#080,stroke-width:2px
```

### Side-by-side comparison (if possible)

| Input | Old output | New output | Match |
|---|---|---|---|
| <input description> | <output> | <output> | yes |
| <input description> | <output> | <output> | yes |

### Performance measurement (if perf-motivated)

<!--
  Cite the actual numbers. Apex log SOQL counts, batch elapsed time, OmniScript
  step duration — whatever metric the refactor was supposed to improve.
-->

| Metric | Before | After | Delta |
|---|---|---|---|
| <e.g. "SOQL queries per insert"> | <value> | <value> | <delta> |
| <e.g. "Apex CPU ms"> | <value> | <value> | <delta> |
| <e.g. "OmniScript step elapsed"> | <value> | <value> | <delta> |

---

## 10. Risk assessment

<!--
  Refactors are high-blast-radius by nature. Be honest about what could go
  wrong in higher environments. Reviewers will use this section to scope
  their review effort.
-->

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| <e.g. "missed caller in another package"> | low/med/high | low/med/high | <e.g. "global search confirmed zero references"> |
| <e.g. "subtle semantics drift in null-handling"> | low/med/high | low/med/high | <e.g. "added test case TestX.testNullPath"> |

### Adversarial Gate B

<!--
  Two defect critics plus one minimality critic in ONE parallel fan-out; see
  .cursor/rules/adversarial-review.mdc. Keep this whole section in the finished
  doc — it is the review's audit trail, not guidance.
-->

**Gate status:** `Ran` / `Not required — <which materiality condition failed>` / `Waived by the user on <date>`
**Scope contract:** `<owned surface (explicit paths) | blast radius | not owned | out of scope + reason>`
**Packaged surface:** `none` / `<packaged path + the public member added + the user's recorded confirmation>`
**Profile / change kind:** `<Salesforce delivery | agent-guidance | other>` / `<existing_modified | greenfield | retrieve_mirror>`
**Evidence pack:** `<base SHA, HEAD SHA, changed-path list, validation job id, test/coverage + PMD output, operation-bound log IDs, freshness recheck>`
**Parallel dispatch:** `<single timestamp proving all three launched together>`
**Minimality feed-forward:** `n/a (no accepted minimality finding)` / `<the accepted finding + its disposition, as supplied to both defect critics on revision N>`

| Critic / run | Lens | Revision reviewed | Verdict |
|---|---|---|---|
| `<id>` | Defect lens 1 — `<profile lens 1>` | `<revision>` | PASS / PASS_WITH_FINDINGS / BLOCK |
| `<id>` | Defect lens 2 — `<profile lens 2>` | `<revision>` | PASS / PASS_WITH_FINDINGS / BLOCK |
| `<id>` | **Minimality** — fewer components, fewer changes | `<revision>` | PASS / PASS_WITH_FINDINGS / BLOCK |

| Mandatory attack category | Result | Evidence / finding IDs |
|---|---|---|
| `<profile lens 1 categories>` | Pass / findings / N/A | <evidence> |
| `<profile lens 2 categories>` | Pass / findings / N/A | <evidence> |
| `<profile lens 3 categories>` | Pass / findings / N/A | <evidence> |
| Requirements/correctness + shared-dependency/regression | Pass / findings / N/A | <evidence> |
| Explicit out-of-scope categories | N/A | <why they do not apply> |

<!--
  Verified? is mandatory before any disposition — never auto-apply a finding,
  and never drop one without a recorded rebuttal round. Rounds counts rebuttal
  rounds used; at 3 unresolved the finding escalates to the user (see below).
-->

| Finding | Severity | Evidence + failure scenario | Verified? | Disposition | Rounds | Fix / test / owner |
|---|---|---|---|---|---|---|
| `<AR-B-001>` | Critical/High/Medium/Low | <path/line + triggering shape> | Yes / No — <how you confirmed or refuted it> | **Critical/High: `Fixed` or `Rejected with evidence` ONLY.** Medium/Low may also be `Accepted risk` (explicit user approval) or `Deferred` (owner + ticket). Also valid: `N/A with evidence`, `Out of scope — outside declared ownership`. | `<n>/3` | <change + parity/regression test or ticket> |

**Escalated to the user:** <none, or: finding IDs, both positions, the decision, and who made it>
**Caller/shared-dependency inventory:** <all callers/callees/config/metadata consumers searched and outcome>.
**Old-vs-new parity proof:** <snapshot/diff/tests proving unchanged behavior, including sibling/legacy paths>.
**Residual/accepted risk:** <none, or explicit user-approved risk + rationale>.

---

## 11. Untouched assets (explicit non-changes)

<!--
  Components in the refactor's adjacency that you intentionally did NOT touch,
  with a one-line reason. Helps reviewers understand the scope boundary.
-->

| Asset | Reason untouched |
|---|---|
| [`<path>`](<path>) | <one-line reason> |

---

## 12. Rollback procedures

### Full rollback (deploy required)

```bash
git checkout HEAD~1 -- force-app/main/default/<paths>

sf project deploy start \
  --metadata "<Type1>:<Name1>" \
  --metadata "<Type2>:<Name2>" \
  -o <sandbox-alias> --ignore-conflicts
```

### Migration rollback (if section 7 had any one-time ops)

| Migration step | Reversible? | Reversal command |
|---|---|---|
| <step from 7> | yes | `<command>` |
| <step from 7> | no | <explanation: e.g. "data backfilled, would need fresh dump from prod"> |

---

## 13. Deploy IDs and commit references

### Manifest used

<!--
  REQUIRED whenever the refactor involved `sf project deploy start
  --manifest`. Inline the FULL XML of the manifest below — reviewers
  shouldn't have to open another file to know what got deployed. The path
  link to the file is in the header block.

  If the deploy used `--metadata` flags only, write:
    "n/a — used `--metadata` flags only. Flags: `--metadata ApexClass:Foo
    --metadata CustomObject:Bar`."
-->

**Manifest path:** [`manifest/<feature>.xml`](../manifest/<feature>.xml)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members><member-name></members>
        <name><MetadataType></name>
    </types>
    <version>{{API_VERSION}}</version>
</Package>
```

### Deploys to `<sandbox-alias>`

| # | Deploy ID | Components | Time (UTC) | Code commit | Purpose |
|---|---|---|---|---|---|
| 1 | `0Af<...>` | <count> | YYYY-MM-DD HH:MM:SS | [`<short-hash>`](#) | <one-line purpose> |

<!--
  On iterative threads, add one row per code commit on the thread.
  Cross-reference the Revision log in §2.
-->

### Commit references

| Commit | What | When |
|---|---|---|
| **`<short-hash>`** (initial code change) | <one-line summary of all files in the commit> | YYYY-MM-DD |
| **`<short-hash>`** (this doc — initial) | `changes/<slug>.md` documenting the above | YYYY-MM-DD |

<!--
  On iterative threads, append rows here for every additional code/doc
  commit. Keep them paired and in chronological order.
-->

Confirm a commit:

```bash
git show --stat <short-hash>
```

---

## 14. Open follow-ups

<!--
  Numbered list. Concrete and actionable. Include perf-monitoring tasks,
  follow-up refactors, deletion of any deprecated-but-still-present code.
-->

1. <e.g. "Delete deprecated `OldHelper` class after one release of soak time in Prod.">
2. <e.g. "Apply same extraction pattern to `OtherTrigger` (follow-up story).">
3. <e.g. "Add Custom Metadata to expose the new flag in Setup for ops team.">
4. <e.g. "Update architecture doc at `<docs path>`.">
