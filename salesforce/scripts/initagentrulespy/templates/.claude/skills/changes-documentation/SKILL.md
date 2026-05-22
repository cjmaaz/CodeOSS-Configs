---
name: changes-documentation
description: Capture a Salesforce piece of work at BOTH ends — intake and wrap-up. At INTAKE, confirm the ticket number with the user and transcribe any AC screenshot to plain text BEFORE writing any code. At WRAP-UP, author a structured changes/<slug>.md doc with a two-commit strategy. INVOKE PROACTIVELY at intake when the user attaches an AC screenshot, says "let's start <ticket>", or opens a new feature/bug/refactor; INVOKE PROACTIVELY at wrap-up when work appears done — deploy succeeded, tests pass, the user said "done" / "looks good" / "ready". Three templates ship under changes/_templates/ for bug-fix, story, and refactor work.
---

# Changes workflow — intake + wrap-up (mandatory)

This skill covers TWO chronological touchpoints in every Salesforce piece of work:

1. **Intake** — at work start, run Step 0 below to confirm the ticket number and transcribe any AC screenshot to text. The transcription feeds §3 of the wrap-up doc.
2. **Wrap-up** — at work end, run Steps 1-7 to author `changes/<slug>.md` and commit it after the code commit it documents.

**Be proactive at both ends.** Pause at intake before writing any code; surface wrap-up the moment work appears done. Do not wait to be asked at either point.

## When to invoke at INTAKE (proactive triggers)

Run Step 0 below the FIRST time any of these happen in a conversation:

- The user **attaches a screenshot** of acceptance criteria, a Jira / ADO panel, an email with requirements, a Figma / wireframe link, a Slack thread, a slide, or any other visual source of requirements.
- The user says "let's start <ticket>", "build me <feature>", "I need a fix for <bug>", "new story / requirement / change", "kicking off <story>".
- The user mentions a ticket / story / case number that's new to the conversation.
- A new chat opens with a feature, bug, or refactor request without an established ticket context.

When in doubt about whether it's a fresh intake, treat it as one. Asking "confirming this is for <ticket>?" costs nothing; building the wrong scope costs hours.

## When to invoke at WRAP-UP (proactive triggers)

Run Steps 1-7 the moment any of these happen — don't wait for the user to ask:

- A `sf project deploy start` came back `Succeeded` with all targeted Apex tests passing.
- A real-commit OmniStudio / Integration Procedure / DataRaptor run produced the expected records and the user confirmed it.
- A `git commit` just completed for `force-app/` changes that close out a piece of work.
- The user said "looks good", "works now", "all green", "ready", "done", "ship it", "wrap this up".
- A pull request is being prepared for the work.

If you're unsure whether the work is "done", ask the user directly — don't skip the doc.

## Step 0 — Intake protocol (run at work START, not at wrap-up)

When an intake trigger fires, you MUST run **all four sub-steps below** before writing any code, opening any file for editing, or running any `sf` command. Treat the intake as a mandatory checklist; do not collapse it into a single message.

### 0a. Confirm the ticket / story / case number explicitly

State a read-back to the user and wait for confirmation:

> _"Confirming this is for ticket **<TRACKER-NNN>** — _<one-line summary from the screenshot or ask>_. Is that right?"_

Acceptable reference forms:

| Source | Example | Use in doc |
|---|---|---|
| Jira-style | `PROJ-1234`, `STORY-12345` | `**Story / ticket:** [PROJ-1234](<url>) — <summary>` |
| Azure DevOps | `Bug 567890`, `User Story 567890` | `**Story / ticket:** [User Story 567890](<url>) — <summary>` |
| Salesforce Case Id | `500Ov000000XYZ` | `**Source case:** 500Ov000000XYZ — <summary>` |
| Ad-hoc, no tracker | "Sandbox cleanup requested by John on 2026-04-10 over Slack" | `**Source:** Slack request from John (Account Lead), 2026-04-10` |

Rules:
- Do NOT proceed without a confirmed reference.
- If the user contradicts your read-back, STOP and re-ask. Never silently move forward with a guessed ticket number.
- If there's genuinely no ticket (rare — usually ad-hoc cleanup), capture a non-tracker reference and confirm THAT.

### 0b. Transcribe any AC screenshot / visual source to TEXT

Screenshots and other visual sources are unsearchable, rot when trackers migrate, and don't survive PR review tooling that strips images. The doc must read a year from now without re-opening Jira.

If ANY visual source of requirements was provided, you MUST:

1. **Read every AC, bullet, or requirement off the image** and write them as numbered plain text — `AC1`, `AC2`, `AC3`, etc.
2. **Post the transcription back to the user** in chat for confirmation: _"Here's what I read off the screenshot — correct me before I start. **AC1**: ... **AC2**: ..."_
3. **Hold the confirmed text in working memory** through the entire piece of work. At wrap-up, it goes verbatim into §3 of the story template (or its equivalent table in bugfix / refactor templates).

What counts as a visual source: Jira / ADO screenshot, Figma frame, wireframe / mockup image, slide-deck snippet, Lucidchart / whiteboard photo, email with embedded image, Salesforce list view showing expected fields, a screenshot of a comment thread. If it conveys requirements and isn't already plain text, transcribe it.

A transcription is not optional even if the screenshot looks "obvious"; the doc still needs the text form.

### 0c. Capture explicit out-of-scope items

If the ticket / screenshot / spec lists items that are explicitly NOT part of this work ("nice to have, but not now", "follow-up story", "won't fix in this round"), transcribe those into a separate list too. They become the `### Out of scope (explicitly)` block in §3.

If no out-of-scope items were called out, ASK: _"Anything I should explicitly mark as out-of-scope so it doesn't get bundled into this story by mistake?"_

### 0d. Stash the intake bundle for wrap-up time

The confirmed ticket + transcribed ACs + out-of-scope items form your **intake bundle**. Carry it through the work. At wrap-up (Step 5 below), drop it into:

- Header block → `**Story / ticket:** ...`
- §3 In scope → one row per transcribed AC (Source column = visual / ticket that originated it)
- §3 Out of scope → bullet list
- §7 Acceptance criteria + verification → one row per AC with `yes/no` evidence after the work is done

The §3 ACs in the final doc MUST be the transcribed text from 0b — **never** "see attached screenshot". A reader of `changes/` should not need any external system open to understand what was agreed to.

## Step 1 — Pick a template (wrap-up starts here)

Once work is done and a wrap-up trigger has fired, pick the matching template. The intake bundle from Step 0 (confirmed ticket + transcribed ACs + out-of-scope) flows into the doc starting at Step 5.

Three templates ship at `changes/_templates/`. Pick the one closest to the work; if it's a hybrid (e.g. a story that fixed bugs along the way), use the closer-fitting template and add subsections inline.

| Work type | Template | When to use |
|---|---|---|
| Bug fix | `changes/_templates/_TEMPLATE_bugfix.md` | Defect, regression, production incident, unexpected behavior. Heavy on root-cause + symptom timeline. |
| Story / feature / requirement | `changes/_templates/_TEMPLATE_story.md` | New functionality, ticket-driven work, business-requested capability. Heavy on requirements + acceptance criteria. |
| Refactor / tech-debt / optimization | `changes/_templates/_TEMPLATE_refactor.md` | Internal restructuring, performance work, code cleanup, no user-visible behavior change. Heavy on functional-parity proof + behavioral invariants. |

Copy the template to a new doc:

```bash
cp changes/_templates/_TEMPLATE_<type>.md changes/<short-kebab-slug>.md
```

### Naming convention

Short, kebab-case, descriptive of the work itself — NOT the ticket number.

| Good | Bad |
|---|---|
| `account-trigger-recursion-fix.md` | `fix1.md` |
| `add-bulk-import-omniscript.md` | `STORY-12345.md` |
| `hfn-creation-async-batch-migration.md` | `refactor.md` |

The ticket reference belongs inside the doc (header block or §3 Requirements), not in the filename.

## Step 2 — Fill the header block

Every doc starts with this block (same shape across all four templates):

```markdown
**Date:** YYYY-MM-DD
**Sandbox:** `{{ORG_ALIAS}}`
**Lead:** <Name> (<role — e.g. developer, sysadmin, sysadmin + developer>)
**Story / ticket:** [<TRACKER-NNN>](<url>) — <one-line summary>
**Code commit(s):** [`<short-hash>`](#deploy-ids-and-commit-references) (latest; full list in section X)
**Manifest:** [`manifest/<feature>.xml`](../manifest/<feature>.xml) (deploy manifest used; XML inlined in section X)
**Status:** Resolved / Delivered / In progress / Pending observation on <list>
```

Line-by-line:

- **Sandbox** for this repo is `{{ORG_ALIAS}}`. Confirm via `sf config get target-org` or `sf org list --all`.
- **Story / ticket** is the value confirmed in Step 0a (intake protocol).
- **Code commit(s)** is singular for one-shot work, comma-separated list for iterative threads (see "Same thread, same doc" section below). `<short-hash>` comes from Step 4.
- **Manifest** is REQUIRED whenever the work involved `sf project deploy start ... --manifest <file>` or the same with retrieve. Inline the manifest's full XML into the "Deploy IDs and commit references" section so reviewers don't have to open another file.

## Step 3 — Stage code only and commit it FIRST (selective staging — parallel-agent safe)

Two-commit strategy is mandatory: code first, doc second. Code commit gives the hash that the doc references.

**Stage ONLY the files you intentionally modified.** Another agent (or the user, or scheduled automation) might be working in the same repo. Blanket-adding whole dirs silently grabs their in-flight changes and mangles their commits.

```bash
# ❌ FORBIDDEN — sweeps in other agents' work.
git add force-app/ scripts/ manifest/ config/

# ✓ DO THIS — name every file explicitly.
git add force-app/main/default/classes/MyClass.cls \
        force-app/main/default/classes/MyClass.cls-meta.xml \
        manifest/my-feature.xml

# Sanity-check: ONLY your files should be staged.
git status -s
```

If `git status` shows other modified files you don't recognise, leave them alone — they belong to another piece of work. If you've lost track of what you touched, recover the list:

```bash
git diff --name-only               # working-tree changes (everything you've edited)
git diff --name-only --cached      # already-staged
git diff --name-only HEAD          # both
```

Cross-reference against the manifest you're about to deploy and the chat history. When in doubt, ask the user.

**Exception — org-wide retrieve audit:** the retrieve workflow (`docs/sf-org-mirror-retrieve.md` Phase 3) commits the whole mirrored `force-app/` as one snapshot commit; that's by design, don't try to subdivide. For every OTHER kind of work, the selective-staging rule is non-negotiable.

Then commit with a multi-line message via HEREDOC:

```bash
git commit -m "$(cat <<'EOF'
<subject line, max 72 chars, imperative mood, no period>

<paragraph 1: what changed and why, in plain English>

<bullet list of every meaningful sub-change, e.g.
  - <File or component>: <one-line change>
>

<paragraph 2 if needed: caveats, temporary changes, drift>
EOF
)"
```

## Step 4 — Capture the code commit hash

```bash
git log -1 --format='%H%n%h%n%s'
```

The short hash (line 2 of output) is the value to embed in the doc's header block and in the doc's "Deploy IDs and commit references" section.

## Step 5 — Author the doc

Open the new `changes/<slug>.md`, fill it in:

- **Header block:** Paste the confirmed ticket reference from Step 0a into `**Story / ticket:** ...`. Fill `**Manifest:**` with the deploy manifest path if applicable (REQUIRED for any `--manifest`-based deploy/retrieve).
- **§3 Requirements (story template):** Paste the transcribed AC text from Step 0b verbatim into the In-scope table — one row per AC, with the Source column referencing the original ticket / screenshot / Slack thread. Paste out-of-scope items from Step 0c into the Out-of-scope bullet list. **Never** write "see attached screenshot" here.
- **Revision log (new section near the top of each template):** Add the first row — date, commit hash from Step 4, what was done, why. Future iterations on the same thread append new rows here (see "Same thread, same doc" below).
- **Key changes — diff highlights (new section after Implementation summary):** For OmniScripts / IPs / DRs / FlexiPages / page layouts / validation rules / formula fields / new Apex classes, paste a diff snippet OR cite line ranges + key method names. The raw `git diff` for those metadata types is unreadable; this section surfaces the meaningful change. Skip for 1-2 line trivial changes where `git diff` alone is clear.
- **Deploy IDs section:** Inline the full XML of the manifest used (not just a path link).
- Replace every other `<...>` placeholder with real content.
- Delete every `<!-- ... -->` HTML guidance comment as you go.
- Embed the short hash from Step 4 in the header block and in the deploy/commit table.
- For sections that genuinely don't apply, write `n/a` with a one-line reason — don't leave stub headings.
- For diagrams, mermaid is encouraged. Follow this project's mermaid syntax rules (camelCase node IDs, no spaces, no colors).

### Diff highlights — two patterns

For SMALL / MEDIUM changes (visible diff fits in ~30 lines), paste the diff inline:

````markdown
### N.1 — `<component>` — <one-line summary>

**File:** [`<path>`](<path>) — Type of change: Modified

```diff
- <old line>
+ <new line>
```
````

For LARGE changes (whole new file, full class rewrite, > ~100 lines), cite line ranges + key method names instead. Don't paste a 500-line code dump.

```markdown
### N.2 — `MyNewClass.cls` — NEW (348 lines)

Key sections:
- Lines 1-25: header + class declaration with `@SuppressWarnings`.
- Lines 27-78: public `activate(...)` — only public method.
- Lines 80-145: private validation / load helpers.
- Lines 147-260: private `applyEffectiveDates(...)` — the meat.

See commit `<short-hash>` for the full file.
```

## Same thread, same doc — iterative wrap-ups

When a thread iterates on the SAME flow / class / OmniScript — _"fix the IP"_ → committed → _"found another issue"_ → committed → _"now this edge case"_ → committed — use ONE `changes/<slug>.md`, not three.

**Pattern:**

1. **First wrap-up:** Create the doc as usual. Commit code (`<hash-A>`), then doc (`<hash-B>`).
2. **Second wrap-up in same thread:** Commit the new code (`<hash-C>`). Then EDIT the existing `changes/<slug>.md`:
   - Append `<hash-C>` to header `**Code commit(s):**` line.
   - Add a row to the Revision log section.
   - Add a new sub-section to "Key changes — diff highlights".
   - Update §1 TL;DR to describe the CUMULATIVE state.
   - Add a row to the Deploys table.
   - Commit the doc edits (`<hash-D>`).
3. **N-th wrap-up:** Same pattern. By thread end the doc has N code commits + N doc commits in the Revision log.

**When to start a NEW doc anyway:**
- The work shifts to a clearly different feature / object — not iterations of the same problem.
- The user explicitly says _"new ticket"_ / _"new story"_ and the intake protocol confirms it.
- The previous doc has merged to `main` and is now immutable history.

**If iteration N+1 invalidates iteration N:** restate §1 (TL;DR) and §7 (verification) to describe the LATEST stable state. Keep the Revision-log row for the superseded approach, marked `(superseded by <hash> — see row N+M)`. Never delete it; the path matters to the next person.

## Step 6 — Commit the doc separately

```bash
git add changes/<slug>.md
git commit -m "$(cat <<'EOF'
docs: <short-title-of-the-work> (refs <short-hash-from-step-4>)

<one-paragraph summary of what the doc covers>

Saved at changes/<slug>.md.
Code commit referenced: <short-hash>.
EOF
)"
```

## Step 7 — Verify both commits and clean tree

```bash
git log -2 --format='%H%n  %h  %s%n'
git status -s
```

Report both hashes back to the user.

## What goes in each section (quick reference)

These are the substance hints for filling each template. Full inline guidance lives in the templates themselves.

### Bug-fix template — substance hints

- **Trigger (§3):** Tie the regression to a concrete event — package upgrade, seasonal release, merged PR, config change. Cite version diffs.
- **Symptom timeline (§4):** One row per observable failure mode. Useful when fixing one symptom revealed another (cascade).
- **Root cause (§5):** One subsection per error family. Always include field/component metadata, why the prior state tolerated it, why the new state rejects it.
- **Diagnostic methodology (§6):** Reproducible runbook for the next person who hits a similar bug. Cite Tooling API queries, anonymous Apex, Apex log retrieval.
- **Permanent fixes (§7):** Each row proves safety — why does the change have zero functional impact, or why is the new behavior provably correct?
- **Diagnostic / temporary changes (§8):** EXPLICIT WARNING block. Include removal commands. If you added zero temporary instrumentation, delete the entire section.
- **Verification matrix (§9):** Side-by-side expected vs actual. Include baseline numbers if a "before" run exists.
- **Scenario coverage (§10):** Be explicit about which sub-types/RecordTypes/scenarios were verified vs. pending.

### Story template — substance hints

- **Header block:** The `**Story / ticket:**` line is the ticket reference confirmed in Step 0a, with a URL where possible.
- **Background (§2):** Product voice — explain to a stakeholder who has never seen the codebase.
- **Requirements (§3):** PASTE the Step 0b transcription verbatim — one row per AC in the In-scope table, numbered AC1, AC2, etc. The Source column points back to the original visual / ticket. Out-of-scope items from Step 0c go in the bullet list below. NEVER reference a screenshot in this section.
- **Design decisions (§4):** For each non-obvious decision, list alternatives considered with pros/cons table.
- **Implementation summary (§6):** Per-component subsection. Reader should know which file does what without opening any.
- **Acceptance criteria + verification (§7):** Walk through each AC from §3 with concrete evidence (record IDs, log IDs, paths to screenshots committed under `docs/` if visual proof helps). Each AC in §7 must reference the same AC number used in §3.
- **Test coverage (§8):** Apex test class + method counts + coverage %. Manual scenarios + negative/edge cases.
- **Rollback / feature-flag plan (§10):** Salesforce metadata is hard to "uninstall" — plan for runtime disable (custom metadata flag, profile revoke, FlexiPage hide) before falling back to git revert + redeploy.

### Refactor template — substance hints

- **Motivation (§2):** Be concrete about pain. Avoid "code smell" language. Cite metrics (SOQL counts, governor limits, file lines, copy-paste counts).
- **Before/after architecture (§4):** Mermaid diagrams strongly encouraged. Quantitative table comparing before/after metrics.
- **Behavioral invariants preserved (§5):** THE most important section of a refactor doc. List every observable behavior that must remain identical and prove each preservation. Call out intentional behavior changes separately.
- **Migration steps (§6):** One-time operations, caller migrations. Skip if not applicable.
- **Verification — functional parity (§7):** Apex test results + side-by-side input/output comparison. If perf-motivated, cite actual numbers (CPU ms, SOQL queries, elapsed time).
- **Risk assessment (§8):** Refactors are high blast radius. Honest table of risks × likelihood × impact × mitigation.

## Generic adaptation notes (for use in other Salesforce orgs)

This skill is portable. When dropping it (and the templates) into a different Salesforce repo:

1. **Sandbox alias:** templates use `<sandbox-alias>` placeholder. Set per-project from `sf config get target-org`.
2. **Lead name:** customize `<Name>` per author. Some teams pre-fill in templates.
3. **No org-specific terminology** is baked in. Universal Salesforce concepts only: Apex, LWC, Aura, OmniStudio, flows, validation rules, profiles, permission sets, custom metadata, `sf` CLI.
4. **`changes/` folder:** assumes `changes/` at repo root. If the project uses `docs/changes/` or similar, update this skill and the templates' relative paths together.
5. **Two-commit strategy:** universal — works in any git repo. The HEREDOC commit-message format is bash/zsh; PowerShell users adjust.
6. **Test coverage thresholds, deploy commands, retrieval rules:** unchanged — defer to the project's other Salesforce skills/rules.

For a real worked example of the bug-fix template applied to a real production issue in this repo, see `changes/practitioner-creation-flow-issues.md`. (That example is {{ORG_NAME}}-specific in content; read it for the **structure**, not the domain content. It will not exist in repos that adopt this skill fresh.)

## Anti-patterns

### Intake-time (Step 0) anti-patterns

- **Starting code without a confirmed ticket number.** Even if the user "just wants this small thing", run Step 0a first. Two minutes of confirmation beats two hours of misbuilt scope.
- **Treating a screenshot as the source of truth.** Screenshots break — when trackers migrate, when PR review tools strip images, when reviewers don't open Jira. Transcribe to text immediately (Step 0b) and have the user confirm the transcription.
- **Letting "see attached screenshot" land in the changes doc.** §3 must contain the actual AC text. If you find yourself about to write "see attached image", go back and finish Step 0b.
- **Silently fixing the ticket number after a typo / wrong read.** Re-read-back to the user, don't paper over.
- **Skipping the out-of-scope question** when the user gives ACs without explicit non-goals. Always ask (Step 0c).

### Wrap-up-time (Steps 1-7) anti-patterns

- **Skipping the doc because "the commit message says it all."** Commit messages don't have rollback procedures, verification matrices, or open follow-ups.
- **Inlining the doc into the same commit as the code.** Breaks the two-commit guarantee; reviewers can't separate code review from doc review.
- **Stub sections** — `<TODO>` or `<...>` placeholders left in a finished doc. If a section truly doesn't apply, write `n/a` with a one-line reason.
- **Renaming the templates** — keep `_TEMPLATE_<type>.md` so they sort to the top of the folder and are clearly distinct from real docs.
- **Forgetting to delete `<!-- ... -->` guidance comments** when filling in a template. The final doc should be clean prose.
- **Using a ticket number as the doc filename.** Ticket trackers migrate; filenames must read well a year from now.
- **Asking the user "should I create a doc?"** when work is clearly wrapped. Just propose it concretely: "Work looks done. I'll create `changes/<slug>.md` from the bug-fix template — confirm?"
- **Rewriting ACs from memory at wrap-up** instead of pasting the intake transcription verbatim. The whole point of Step 0b was to lock the agreed text down before code touched the keyboard.

### Parallel-agent / staging anti-patterns

- **`git add force-app/`** (blanket-add a top-level dir) when another agent or human might be active in the repo. Use selective staging — name every file explicitly. The only documented exception is the org-wide retrieve workflow.
- **Including someone else's file in your commit "because it was already modified".** If you didn't touch it, leave it.
- **Quietly reverting another agent's in-flight edit** by checking out HEAD on files you don't recognise. If files are dirty when you arrive, ask the user — never silently revert.

### Doc-content / package-manifest anti-patterns

- **Missing `**Manifest:**` line in the header block** when the work involved a `--manifest` deploy/retrieve. The doc must name the manifest file and inline its XML in the Deploy IDs section. Reviewers shouldn't have to open a second file.
- **Skipping the "Key changes — diff highlights" section** for OmniScripts / IPs / DRs / FlexiPages / layouts. The raw `git diff` for those is unreadable; the doc must surface the meaningful change.
- **Pasting a 500-line Apex file into a diff fence.** For changes that big, use line-range + method-name commentary, not a code dump.

### Same-thread / multi-doc anti-patterns

- **Spawning a new `changes/<slug>.md` for each iteration** of the same fix. Use ONE doc for the thread; update the Revision log + add a new Diff-highlights row + append the new commit hash to the header.
- **Letting the doc's TL;DR fall behind reality** when iterating. After each new code commit on the same thread, restate §1 to describe the CUMULATIVE state.
- **Deleting a superseded approach from the Revision log** so the doc "reads cleaner". Mark it `(superseded by <hash>)` and leave it; the path matters to the next person.
