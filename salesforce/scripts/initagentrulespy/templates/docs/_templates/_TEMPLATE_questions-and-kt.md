<!--
  TEMPLATE: Open questions + reverse-KT
  =====================================
  Copy this file to docs/lld/<work-id>-questions-and-kt.md and fill it in.
  Delete guidance comments, but KEEP any adversarial Gate A/B content — it is
  the review's audit trail, not guidance.

  Use this when the LLD has design assumptions that need stakeholder / SME
  confirmation before building. OPTIONAL — create it only when there are real
  open questions (see .cursor/rules/documentation-workflow.mdc).

  Part 1 is the question set to take to the session (each question: why it
  matters, the options, and a recommended default so the meeting confirms-or-
  adjusts rather than starting from scratch). Part 2 is the reverse-KT — the
  shared mental model of how the system behaves today. Companion: the LLD
  (<work-id>-<slug>.md).
-->

# <work-id> — Open questions for stakeholders + reverse-KT

**Date:** YYYY-MM-DD
**Lead:** <Name> (<role>)
**Work item / ticket:** [<TRACKER-NNN>](<url>) — <one-line summary>
**Companion:** [`<work-id>-<slug>.md`](<work-id>-<slug>.md) (LLD)

> **How to use.** Part 1 is the question set for the stakeholder / SME session — each question states why it matters, the options, and the recommended default so the meeting can confirm-or-adjust rather than start from scratch. Part 2 is the reverse-KT: what you will walk stakeholders through so everyone shares the same mental model of how the system behaves today, and so wrong assumptions surface before coding.

---

## Part 1 — Open questions

<!-- Route unresolved adversarial-review findings that require business/SME
     decisions here. Preserve finding ID, severity, evidence, and the risk of
     each answer; do not copy the full review register from the LLD. -->

| Finding / question | Severity | Evidence / why it matters | Decision / answer | Approver | Date | Status |
|---|---|---|---|---|---|---|
| `<AR-A-001 / Q1>` | <severity> | <evidence + design impact> | <answer> | <name/role> | YYYY-MM-DD | Open / Decided |

Any answer that changes an assumption, scope, AC, or design makes the LLD a new revision — update it and rerun the Gate A critics against that revision before implementation.

### A. <theme — e.g. Definitions>

**Q1. <question>?**
- Why it matters: <impact on the design / the risk if it is encoded wrong.>
- Options: (a) <...>; (b) <...>; (c) <...>.
- **Recommended default:** <option> — <one-line reason>. <open sub-question, if any.>

**Q2. <question>?**
- Why it matters: <...>
- Options: <...>
- **Recommended default:** <...>

### B. <theme — e.g. Semantics / scope / edge cases>

**Q3. <question>?**
- Why it matters: <...>
- **Recommended default:** <...>

---

## Part 2 — Reverse-KT (what we will walk stakeholders through)

> Purpose: align everyone on how the system behaves **today** so the change is understood in context, and surface any wrong assumptions before building.

**KT-1. <headline fact about current behavior>.**
<plain-language explanation.>

**KT-2. <headline fact>.**
<explanation.>

**KT-3. What will and will not change.**
- Will change: <...>
- Will not change: <...>
