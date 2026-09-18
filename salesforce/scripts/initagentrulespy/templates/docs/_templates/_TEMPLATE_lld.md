<!--
  TEMPLATE: Low-Level Design (LLD)
  ================================
  Copy this file to docs/lld/<work-id>-<short-kebab-slug>.md and fill it in.
  Delete guidance comments, but KEEP the `9.1 Adversarial Gate A`
  section in full (heading, all three tables, and the bold summary lines).
  It is the review's audit trail, not guidance.
  Strip any section that genuinely does not apply (write "n/a — <reason>").

  Naming: <work-id>-<short-kebab-slug>.md
    Good: 1443813-deny-keeps-shared-parent-pending.md, add-bulk-import-pipeline.md
    Bad:  lld1.md, design.md, TICKET-123.md (id alone, no description)

  What an LLD is: the design record for a non-trivial change — what the system
  does TODAY, the precise gap the work closes, and the proposed minimal change,
  with alternatives and cascading impact. Author it BEFORE writing code (during
  the pre-coding analysis phase); it is the deeper design artifact that the
  changes/<slug>.md doc summarizes and links to. See .cursor/rules/documentation-workflow.mdc.

  Companion docs (OPTIONAL — create only when warranted, see the rule):
    - <work-id>-questions-and-kt.md  — open questions for stakeholders + reverse-KT
    - <work-id>-walkthrough.md       — session walkthrough + decision capture
-->

# LLD — <work-id>: <short title of the change>

**Date:** YYYY-MM-DD
**Environment (analysis):** `<env / sandbox / data store the analysis ran against>`
**Lead:** <Name> (<role>)
**Work item / ticket:** [<TRACKER-NNN>](<url>) — <one-line summary>
**Status:** Draft — design phase (no code yet) / In review / Approved for build / Superseded
**Adversarial Gate A:** Pending / PASS / PASS_WITH_FINDINGS / BLOCK
**Plan revision reviewed:** `<LLD path + base SHA / date the critics saw>`
**Related docs:** <links to the questions-and-kt doc, the walkthrough doc, and the changes/<slug>.md doc, when they exist>

> <One-paragraph summary: what this LLD covers, and explicitly call out any
> predicate or behavior still pending stakeholder confirmation — link to the
> questions-and-kt doc for those.>

---

## 1. Purpose & scope

**Goal:** <what the change must achieve, in 1-3 sentences tied to the AC.>

**In scope (code):** <the specific component(s) / path(s) this work changes.>

**Out of scope (documented as context):**

- <related work handled elsewhere — name it and link if possible.>
- <data remediation / sibling work / UX — explicitly excluded so it is not assumed.>

---

## 2. Intake — transcribed requirement & acceptance criteria

<!-- Paste the requirement + AC TEXT transcribed at intake. Never "see screenshot". -->

### 2.1 Description (the "why")

> <transcribed problem statement / user story, verbatim.>

<A concrete real-world example from the ticket, if one exists.>

### 2.2 Acceptance criteria (the "what")

> **AC1** — Given <precondition> / When <action> / Then <expected outcome>
> **AC2** — ...

### 2.3 Out of scope (explicitly)

- <non-goal called out in the ticket / intake.>

---

## 3. Domain mapping (business term -> system component)

<!-- Translate each business term into the concrete component / record / table /
     field the design touches. Keeps the rest of the doc unambiguous. -->

| Business term | System component | Key fields / attributes used |
|---|---|---|
| <term> | <object / table / service / module> | <fields / columns the change reads or writes> |

---

## 4. Current behavior (as built)

<!-- How the system behaves TODAY on the path you are about to change. Cite the
     concrete entry points, the engine/component, and what it does AND does not
     do.

     The diagram below follows docs/diagram-conventions.md: ONE SUBGRAPH PER
     COMPONENT (not per logical phase), a legend line immediately above the
     fence, colour for STATE only, and the defect in amber. Keep the node IDs
     identical to the §7.3 diagram so a reader can diff the two by eye. -->

### 4.1 Entry points

<how the path is triggered today — UI action, API call, scheduled job, event.>

### 4.2 The engine / component

<the single place the behavior lives (file / path); what it changes and what it
leaves untouched.>

**Legend — every dashed box is one component.** <only the symbols this diagram uses, e.g.> 🔷 this Flow · 🟣 Apex · 📄 org data (config, not code) · 👥 queue. Green = working, amber = the problem, red = dead end.

```mermaid
flowchart TD
    subgraph F1["🔷 FLOW · <ComponentName> — <one-line role, e.g. active screen flow, user context>"]
        A["<entry point>"] --> B["<b><the element that matters></b><br/><what it does · what it omits><br/>⚠ <why that is wrong>"]
        B --> C{"<decision element>"}
        C -->|"<real predicate value>"| OK["… the working path …"]
        C -->|"<other value — default>"| DEAD["<b><element></b><br/>NO CONNECTOR<br/><what happens instead>"]
    end

    subgraph D1["📄 ORG DATA · <Object__c> — config, not code"]
        T1["<row 1>"]
        T2["<row 2>"]
    end

    B -.->|"⚠ <what the reference relationship is>"| T1

    style B fill:#fff3cd,stroke:#b8860b,stroke-width:2px
    style C fill:#fff3cd,stroke:#b8860b,stroke-width:2px
    style DEAD fill:#ffd9d9,stroke:#c00,stroke-width:2px
    style OK fill:#d9f2d9,stroke:#080
```

---

## 5. Gap analysis — why the change is needed

<!-- The precise delta between current behavior (§4) and the AC (§2). Enumerate
     the specific gaps; this is the heart of the LLD. -->

1. <gap 1 — what today's logic misses, and why.>
2. <gap 2 ...>

**Conclusion:** <one sentence stating what must be added / changed to close the gap.>

---

## 6. Before-state evidence (read-only)

<!-- Prove the problem exists and gauge blast radius with READ-ONLY queries
     against real data. Paste the query + the headline result (counts, sample
     ids). This justifies the work AND sizes the bulk-safety requirement. -->

```sql
<read-only query>
```

- <headline finding — counts, max fan-out, a concrete sample record / id.>

---

## 7. Proposed design

### 7.1 Principle

<the guiding constraint — e.g. "surgical and additive; reuse the existing
mechanism; do not change what X does today.">

### 7.2 Mechanism

<the new detection / logic / data change. Pseudocode or a short snippet is fine;
keep it implementation-shaped, not the final code.>

### 7.3 Where it plugs in

<the exact insertion point(s) in the existing flow; what stays unchanged.>

<!-- Same conventions and the SAME NODE IDs as §4, so the amber node there is the
     green node here and the reader's eye tracks it. Mark elements ✨ new /
     🔧 modified / ♻️ reused-as-is, and grey out anything left deliberately
     unreachable rather than deleting it from the picture. -->

**Legend.** <symbols used> 🔷 this Flow · 🔒 permissions · 👥 queue. Markers: ✨ new element · 🔧 modified · ♻️ existing, reused · grey = left unreachable.

```mermaid
flowchart TD
    subgraph F1["🔷 FLOW · <ComponentName> — everything this story edits"]
        A["<entry point>"] -->|"(a) rewired"| B["<b><the element that matters></b> 🔧<br/><what it does now>"]
        B --> NEW["<b><new element></b> ✨<br/><what it guards>"]
        NEW -->|"<outcome>"| OK["… the working path …"]
        UNR["<retired element(s)><br/>(c) left in place, unreachable"]
    end

    subgraph P1["🔒 PERMISSIONS — (d)"]
        PERM["<grant needed to make the new filter readable>"]
    end

    PERM -.->|"<why the grant is required>"| B

    style B fill:#d9f2d9,stroke:#080,stroke-width:2px
    style NEW fill:#d9f2d9,stroke:#080
    style OK fill:#d9f2d9,stroke:#080
    style PERM fill:#e6d9f2,stroke:#63c
    style UNR fill:#eeeeee,stroke:#999,color:#777
```

### 7.4 Why this approach

<blast radius, bulk-safety, consistency with existing patterns.>

### 7.5 Alternatives considered

| Option | Pros | Cons | Why (not) chosen |
|---|---|---|---|
| <chosen> | <pros> | <cons> | (chosen) |
| <alternative> | <pros> | <cons> | <reason rejected> |

---

## 8. Affected components (touched surface)

<!-- The output of the pre-coding "identify the surface" step. One row per
     component the build will touch. -->

| Component | Path | Change |
|---|---|---|
| <name> | [`<path>`](<path>) | <add / modify / read-only reference> |

---

## 9. Cascading impact

<!-- Walk the downstream automation / effects the change triggers. Flag intended
     vs accidental. For data-heavy runtimes, note whether the change writes MORE
     or FEWER records than today. -->

- <effect 1 — intended / accidental, and why.>
- <effect 2 ...>

### 9.1 Adversarial Gate A

<!--
  Launch two defect critics plus one minimality critic in ONE parallel fan-out against the exact
  plan revision above. Follow .cursor/rules/adversarial-review.mdc. Do not edit
  source until this gate passes. When a revision triggers re-review, add rows —
  supersede the old verdict, never erase it.

  Keep this whole section in the finished doc; it is the review's audit trail.
-->

**Gate status:** `Ran` / `Not required — <which materiality condition failed>` / `Waived by the user on <date>`
**Scope contract:** `<owned surface (explicit paths) | blast radius | not owned | out of scope + reason>`
**Packaged surface:** `none` / `<packaged path + the public member added + the user's recorded confirmation>`
**Profile / change kind:** `<Salesforce delivery | agent-guidance | other>` / `<existing_modified | greenfield | retrieve_mirror>`
**Evidence pack:** `<base SHA, HEAD SHA, changed-path list, paths to any test / PMD / log output>`
**Parallel dispatch:** `<single timestamp proving all three launched together>`
**Minimality feed-forward:** `n/a (no accepted minimality finding)` / `<the accepted finding + its disposition, as supplied to both defect critics on revision N>`

| Critic / run | Independent lens | Revision reviewed | Verdict |
|---|---|---|---|
| `<id>` | Defect lens 1 — `<profile lens 1>` | `<revision>` | PASS / PASS_WITH_FINDINGS / BLOCK |
| `<id>` | Defect lens 2 — `<profile lens 2>` | `<revision>` | PASS / PASS_WITH_FINDINGS / BLOCK |
| `<id>` | **Minimality** — fewer components, fewer changes | `<revision>` | PASS / PASS_WITH_FINDINGS / BLOCK |

| Attack category | Result | Evidence / finding IDs |
|---|---|---|
| `<profile lens 1 categories>` | Pass / findings / N/A | <evidence> |
| `<profile lens 2 categories>` | Pass / findings / N/A | <evidence> |
| `<profile lens 3 categories>` | Pass / findings / N/A | <evidence> |
| Explicit out-of-scope categories | N/A | <why they do not apply to this artifact> |

<!--
  Verified? is mandatory before any disposition — never auto-apply a finding,
  and never drop one without a recorded rebuttal round. Rounds counts rebuttal
  rounds used; at 3 unresolved the finding escalates to the user (see below).
-->

| Finding | Severity | Failure scenario + evidence | Verified? | Disposition | Rounds | Fix / test / owner |
|---|---|---|---|---|---|---|
| `<AR-A-001>` | Critical/High/Medium/Low | <concrete failure> | Yes / No — <how you confirmed or refuted it> | **Critical/High: `Fixed` or `Rejected with evidence` ONLY.** Medium/Low may also be `Accepted risk` (explicit user approval) or `Deferred` (owner + ticket). Also valid: `N/A with evidence`, `Out of scope — outside declared ownership`. | `<n>/3` | <change + test, or ticket> |

**Escalated to the user:** <none, or: finding IDs, both positions, the decision, and who made it>
**Residual/accepted risk:** <none, or explicit user-approved risk + rationale>.

---

## 10. Draft test scenarios

<!-- The scenarios the build must cover, derived from the ACs + gap analysis.
     Finalize after any open questions are answered. -->

| # | Scenario | Expected |
|---|---|---|
| 1 | <happy path> | <expected> |
| 2 | <negative / edge case> | <expected> |
| 3 | <regression: existing behavior unchanged> | <unchanged> |
| 4 | <profile-specific stress/compatibility case> | <expected> |
| 5 | <second profile-specific failure mode, or evidence-backed N/A> | <expected> |
| 6 | <scenario derived from adversarial finding AR-A-...> | <failure prevented> |

Coverage target: <the project's required coverage>.

---

## 11. Open questions & reverse-KT

<!-- The design assumptions that need stakeholder confirmation. If there are
     several, or a live session is warranted, spin them out into the companion
     <work-id>-questions-and-kt.md (and <work-id>-walkthrough.md for the session). -->

The design above assumes, pending confirmation:

- <assumption 1 — link to the matching question in the questions-and-kt doc.>
- <assumption 2.>

---

## 12. Pre-implementation checklist (gated)

<!-- The steps before / at build time. Pull the latest source (the org / repo is
     the source of truth), reproduce the gap, implement, test, document. -->

1. Pull the latest version of the components in §8 and re-validate §4-§5 against the fresh copy.
2. Reproduce the exact failing condition; capture before / after.
3. Run Gate A against this exact LLD revision; resolve/re-review all blockers and record explicit disposition for every finding.
4. Confirm Gate A is `PASS` or eligible `PASS_WITH_FINDINGS`; no Critical/High and every Medium resolved or user-accepted.
5. Implement the design in §7; add every required test derived from §9.1 to §10.
6. Run implementation Gate B before any deploy/mutation/commit, then deploy, run targeted tests, and inspect logs.
7. Finalize the changes/<slug>.md doc and follow the two-commit strategy.

---

## 13. References

- <engine / component paths.>
- <related rules / docs / sibling work.>
