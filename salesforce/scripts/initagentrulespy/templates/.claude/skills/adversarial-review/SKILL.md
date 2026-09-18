---
name: adversarial-review
description: Runs the adversarial review gate for Salesforce delivery work that carries real risk — changes to metadata that already has consumers, anything touching DML/SOQL/async/cascades, deploys and org data mutations, and retrieve audit docs. Invoke before the first source edit (Gate A) and before any deploy or commit (Gate B): declare a scope contract, launch two defect critics plus one minimality critic in parallel, then verify and challenge each finding rather than applying it. The user may waive any gate and that waiver is final. Mirrors `.cursor/rules/adversarial-review.mdc`.
---

# Adversarial review

Full policy in `.cursor/rules/adversarial-review.mdc`; this is its operational mirror.

## What it is for, and what it is not for

It catches the defect invisible from the authoring angle — almost always one reached **indirectly**. The canonical case: a loop calls `methodA`, which calls `methodB`, which runs SOQL or DML. Nothing on the changed line looks wrong; the query is three frames away in a file the diff never touches, and at 200 records it is a limit failure. So critics **trace call chains**, they do not survey diffs.

It is **not** for redesigning the ticket. A critic proposing unrequested work, or a refactor across seven files where three deliver the requirement, has failed rather than found something. In a shared org breadth is itself the risk: every extra component is another team's surface, another deploy conflict, another regression path.

## The user's word overrides this skill

If the user says skip the gate, shrink it, or stop reviewing — do it immediately, without arguing. Record one line naming the waived gate and that the user waived it, then continue. No informal version anyway, no re-raising it later, no quoting the rule back.

The agent may not waive its own gate. "Looks small", "I'm confident", and "it would take a while" are not waivers.

## When it runs

Required when **both**: (1) the work changes deployable metadata, mutates org data, deploys, or is a retrieve audit doc; **and** (2) it carries material risk — modifies metadata that already has consumers, involves DML/SOQL/async/batch or a trigger/flow/OmniStudio cascade, deploys or mutates org data, or adds irreversible public surface.

Not required: the user waived it; a self-contained new component with no consumers, no data access, and no packaged surface (a demo or dummy LWC); changes with no behavioural consequence (formatting, comments, labels); personal tooling under `scripts/`, the kit, and untracked notes.

A `scripts/` file that writes to the org is delivery work regardless of folder, as is config governing what deploys or gets analysed. On a genuinely borderline call, state in one line why you are not gating and proceed — do not spend the gate's cost deciding whether to spend it.

## Hard stop: irreversible public surface

**A user confirmation, not a critic finding, and it precedes any gate.**

Once a managed package version is released its public surface is permanent: a `global` Apex class/method/variable, an `@api` property or method on a packaged LWC, or a packaged object or field cannot be removed or renamed. Salesforce refuses it — there is no rollback and no later cleanup.

So **before adding public surface to anything that ships in a package, stop and ask the user**, naming the exact member and stating that it cannot be removed later. Wait for an answer; do not add it and mention it afterwards.

Spot packaged metadata first: a namespace prefix (`ns__Thing`) means an installed managed package; a path under a `packageDirectories` entry with a `package` key ships in your own; `sf package installed list -o {{ORG_ALIAS}}` lists namespaces. **Do not edit installed managed-package components** unless the ticket explicitly says to.

## Scope contract — declare before launching

- **Owned surface** — the exact edited path list. No globs.
- **Blast radius** — what already consumes it: Apex callers/callees, shared helpers, sibling RecordTypes, trigger/flow cascades, OmniScripts and IPs invoking a changed IP or DataRaptor (and the IPs invoking those), LWC/Aura importing a changed Apex method, FlexiPages/layouts surfacing a changed field, permission sets granting it, live legacy routes. Enumerate by searching for consumers, not recalling them.
- **Not owned** — components that merely coexist; other teams' code this change does not sit on.
- **Packaged surface** — any owned path that is packaged, and whether this adds public surface to it. `none` is the expected answer.
- **Profile** — `force-app/`/deploy/org mutation → Salesforce delivery; retrieve audit doc → retrieve; the kit → agent-guidance.
- **Change kind** — `existing_modified` | `greenfield` | `retrieve_mirror` (Gate B only).

A finding must land on the owned surface or blast radius; otherwise `Out of scope — outside declared ownership`. Equally binding in reverse: a shared path the edited component sits on is **always** in scope, and pre-existing-ness is no defence once this change makes the defect reachable.

## Gates

- **Gate A — plan/design:** before the first source edit, once current behaviour, the affected surface, and a draft design exist.
- **Gate B — implementation:** before any real deploy, org DML, cache-bust, version swap, commit, or handoff.

Nothing in the loop touches the live org — Gate B uses `--dry-run`, `sf project deploy validate`, PMD, and synchronous tests. Only a narrowly scoped, time-bounded TraceFlag with recorded cleanup may write before Gate B, never business data or metadata. Only the orchestrating agent launches critics; critics are read-only and never spawn critics.

## Evidence pack

Same snapshot to every critic, recorded in the LLD (Gate A) or `changes/<slug>.md` (Gate B):

```bash
BASE=$(git merge-base HEAD <target-branch>)   # or the pre-work HEAD
git rev-parse HEAD
git diff --stat "$BASE" -- <explicit-path-1> <explicit-path-2>
git diff --name-only "$BASE"; git status -s
```

- **Gate A** adds requirements/ACs, current behaviour, cascade map, assumptions, design, rejected alternatives, draft tests.
- **Gate B** adds confirmed ACs, the complete diff, callers/callees, validation output, tests/coverage, static analysis, operation-bound Apex log IDs, and a `LastModifiedDate` freshness recheck per touched component immediately before deploy.

Inapplicable evidence is `N/A` with a one-line reason.

## Two defect critics plus one minimality critic

One parallel fan-out. In round one they are fully independent — never serialized, never shown each other's output.

Critics 1 and 2 attack for defects using the profile's lenses. **Critic 3 is minimality**, and exists because the other two systematically pull toward doing more.

### Critic 3 — minimality

Its only question: **can the required outcome be achieved by touching fewer components and making fewer changes?** "Fewer components" means fewer of *any* component, not just other people's — a new class where an existing one serves, a schema change where an existing field or formula would do, a shared component edited where a local one sufficed, a broad refactor bundled into a narrow fix, files in the diff no AC requires.

It must name the component that could be left untouched and how the requirement is still met without it. "This could be cleaner" is not a finding; "AC2 is satisfied by the change in `X`, so the edits to `Y` and `Z` are not required" is. It may not demand a rewrite for elegance, nor propose additional work unless strictly smaller than what it removes.

### Feed-forward on the second run

When the orchestrator verifies and accepts a minimality finding the artifact shrinks, which is a revision. On that revision the **two defect critics receive the minimality finding and its disposition** with the reduced artifact — otherwise they review a narrowed design blind to why it narrowed and propose re-adding exactly what was removed.

This is the **one sanctioned exception** to independence: one-directional (minimality → defect critics, never the reverse), and only on a revision, never round one.

## Profiles

**Salesforce delivery**
1. Correctness and runtime: trace every call chain from loops and bulk entry points to its leaves — SOQL, DML, a callout, or any limit-consuming operation anywhere in the chain is a finding even when the diff shows none. Then recursion, 1/200/max/mixed bulk, nulls/exceptions/rollback, stale reads, async ordering, locks, overlapping jobs, retry/idempotency, transaction boundaries.
2. Regression on what already works: existing consumers, shared paths, sibling RecordTypes, live legacy routes, permissions/FLS, the new-path-succeeds-while-old-path-regresses case, and AC counterexamples the implementation gets wrong.
3. Minimality.

**Retrieve (`retrieve_mirror`, Gate B only)** — subject is the audit doc against the actual diff. **Two critics only**; minimality does not apply because a retrieve changes no components. Runtime, concurrency, limits, and deploy safety are `N/A` with that reason recorded.
1. Did the doc record what happened, completely and accurately? Anything in the diff the doc omits — a changed component with no note, a deletion, a structural rewrite, a new file — plus the inverse: any claim the evidence does not support, such as dated carry-forward presented as current.
2. Was the diff actually read? Notes restating a filename instead of naming the behaviour that changed and its risk; a misread diff; a version-pair reported as bulk added lines; a structural overhaul reduced to a line count.

**Org-wide coverage is out of scope for retrieve.** "You should also have retrieved type X" is not a finding — we do not own the whole org, and what to pull is the operator's decision. Attack what the doc *claims*, never what the run deliberately and datedly left alone.

**Agent-guidance (rules/skills/templates/bootstrap)**
1. Consistency and drift: contradictions, ordering, activation triggers, duplicate ownership, stale links, rule↔skill drift.
2. Usability and portability: unusable placeholders, missing tokens for org/machine-specific values, template↔generated parity, seed-once files that must never be overwritten, fresh-target reproducibility.
3. Minimality.

The bootstrapper is a delivery mechanism, not the subject — do not redesign its locking, durability, or performance unless a concrete defect breaks output.

## What is not a finding

- Work the ticket did not ask for; infrastructure, monitoring, or framework requirements the story never mentioned.
- A refactor not required to make this change correct.
- A pre-existing defect on a component this change does not sit on.
- Style, naming, or formatting with no behavioural consequence.
- A hypothetical with no data shape, volume, timing, or interleaving that triggers it.
- "Add tests for X" where X is outside the owned surface and blast radius.
- For retrieve: coverage the run deliberately excluded with a recorded date.

**One exception, always in scope: contract completeness.** A path in `git diff --name-only` missing from the owned surface, or a consumer of an edited component missing from the blast radius, IS a finding — an under-declared contract is the only way this gate is quietly defeated.

## Prompt contract

Carry the scope contract verbatim, the lens assignment, and:

> Attack this artifact for concrete defects. Find reasons it will fail or regress existing behaviour, and trace call chains rather than reading only the diff. Do not praise it, do not edit files, and do not propose work the ticket did not ask for. Return `BLOCK` for Critical/High, `PASS_WITH_FINDINGS` for Medium/Low only, otherwise `PASS`.
>
> Stay inside the supplied scope contract. A concern outside the declared surface is not a finding, except contract completeness, which always is.

Require: identity and lens; exact revision reviewed (base SHA + path list) and assumptions; overall verdict; per finding an ID, severity (`Critical`/`High`/`Medium`/`Low`), concrete evidence (path/line, method, transaction chain, query, metadata element), triggering data shape or timing, consequence and affected existing behaviour, and a recommended fix plus the test proving it.

A concern with no falsifiable failure scenario is not a finding. A failed, timed-out, or incomplete critic does not count.

## Disposition

Deduplicate, **verify each finding against the actual source and evidence**, then record exactly one of: `Fixed` (cite change + test), `Rejected with evidence` (cite proof), `Accepted risk` (Medium/Low, explicit user approval), `Deferred` (Medium/Low, owner + ticket), `N/A with evidence`, `Out of scope — outside declared ownership` (cite the contract).

Critical/High may only be Fixed or Rejected with evidence — a scope objection to one goes to the user, not the contract. Medium needs resolution or explicit acceptance; Low stays recorded. Disagreement is unresolved risk, not a majority vote. A full set of critics returning `PASS` is not a set of approvals — lens coverage and evidence are what count.

`PASS` when all passed with nothing outstanding; `PASS_WITH_FINDINGS` when none blocks and only resolved/accepted Medium and recorded Low remain; `BLOCK` otherwise.

## Challenge loop

Findings are hypotheses, not work orders. Applying a wrong one and dismissing a right one are equally serious.

1. **Never auto-apply** — read the cited code/query/log and confirm the failure is real first.
2. **Never silently drop** — to reject, write counter-evidence and send it back to that same lens as a rebuttal round. A finding that vanishes without a recorded rebuttal is a bypass.
3. **Unverifiable means unresolved** — rebuttal, not `Rejected`.
4. **Three rounds, then the user — always.** Stop; do not deploy, mutate, commit, or hand off, and do not downgrade a surviving Critical/High to escape. Present both positions and record the user's decision, attributed to them.
5. **Convenience is never a reason** to reject a valid finding.

## Re-review triggers

- **Rebuttal round** (unchanged artifact, counter-evidence added) → re-prompt only the disagreeing lens; other verdicts stand.
- **Revision** (artifact or evidence changed) → rerun all three critics in parallel, passing accepted minimality findings forward to the defect critics.

**Cap: two full revisions per gate.** Critics are told to attack and forbidden to praise, so a third revision reliably surfaces fresh findings and the gate loses its termination guarantee. Remaining findings go to the user; reaching the ceiling is normal.

Never mix verdicts across revisions or accept a late result from a superseded one.

## Capability failure

If parallel subagents are unavailable, report the gate as unfulfilled and blocked. Never substitute an unlabeled self-review or a single generic critic and claim compliance.
