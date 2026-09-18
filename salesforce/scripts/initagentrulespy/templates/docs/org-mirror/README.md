# Org Mirror Retrieve — Runbook

A repeatable, hybrid-shard strategy for pulling a **verified metadata footprint** of a Salesforce org into local source while staying under Metadata API limits and surviving slow orgs.

> **Why this doc exists:** A naive `sf project retrieve start --metadata '*'` (or even one all-types manifest) blows past the Metadata API's per-call cap on any non-trivial org, and locks up for hours when the org is slow. So we split the retrieve into a sequence of bounded, individually gated calls, then an audit and two commits.

**Nothing here hardcodes how big your org is.** The shipped manifests and the small/heavy split are a **seed**, not truth. Phase 0 measures your org and that measurement generates the run plan. Never copy another org's counts, another org's phase numbering, or another run's timings — discover them.

## What ships in this directory

The runbook explains *why*; the scripts beside it are the *executable* form, so a later run starts here instead of rebuilding the plan from prose.

| File | Role |
|---|---|
| `README.md` | This runbook. The only prose file — there is no second README anywhere. |
| `make-order-files.sh` | Phase 0.5. Turns the discovered footprint into per-run order files and manifests. |
| `run-phase.sh` | Executes **one** phase behind every guard in [Hazards](#hazards-the-guards-exist-for). |
| `run-all.sh` | Drives an order file end to end, stopping at the first failed gate. |

Scripts are invoked with `bash`, so they work whether or not the executable bit survived however you obtained this directory:

```bash
bash docs/org-mirror/run-all.sh <order-file> [resume-from-phase]
```

**Every generated artifact lands in `.retrieve-logs/current/` and is gitignored.** Order files carry measured floors and per-run manifests carry a specific org's type mix, so neither is ever committed — that is what stops one org's numbers from leaking into another's plan. The previous run survives in `.retrieve-logs/archive/<TS>/`.

---

## When to use

- **Initial mirror** of a new org into a fresh repo.
- **Periodic full re-sync** when you suspect significant local drift (different developers / admins deploying directly to the org bypassing your repo).
- **After major package installs** that add hundreds of fields/objects.
- **NOT for routine per-feature work** — for that, retrieve only the touched components (see `.cursor/rules/sf-cli-commands.mdc`).

---

## Prerequisites

1. **`sf` CLI installed and authed.**
   ```bash
   sf org list --all
   ```
   Confirm your target org appears with `Status: Connected`. If expired, re-auth:
   ```bash
   sf org login web -a <YourOrgAlias>
   ```

2. **An SFDX project rooted at the repo.** `sfdx-project.json` should point at `force-app` (or your equivalent package dir) and use the same API version your org supports (this repo uses `{{API_VERSION}}`).

3. **Seed manifests at `manifest/fullpackage.xml` and `manifest/fullpackage/`.** These are a starting point — a list of type names, with no org-specific members. Phase 0.3 reads them only to work out which types someone previously thought to ask for, so it can report what your org supports that they missed. The manifests this run actually retrieves with are **generated** in Phase 0.5. Never treat a seed manifest as proof of coverage.

4. **A clean spot to capture logs.** The runbook writes the active run's per-phase logs to `.retrieve-logs/current/` and rotates previous runs to `.retrieve-logs/archive/<TS>/`. Both subdirs are covered by the single `.retrieve-logs/` gitignore entry.

5. **`jq`**, **`python3`**, and **`bash`**. `jq` parses `--json` output throughout Phase 0; `python3` is used by `make-order-files.sh` to enforce the parent-before-child ordering; the scripts are bash, so invoke them with `bash <script>` rather than relying on the executable bit surviving however you obtained them. Check all three before you start — the generator failing halfway through Phase 0.5 is a worse place to discover a missing interpreter than the prerequisites list:

   ```bash
   for t in sf jq python3 bash; do
     command -v "$t" >/dev/null && echo "  OK   $t" || echo "  MISSING  $t"
   done
   ```

---

## Setup — set your org alias once

Every `sf` command in this runbook uses `$ORG_ALIAS`. Set it once at the top of your shell session and **leave the terminal open for the whole run**:

```bash
# Replace with YOUR org alias (whatever you used in `sf org login web -a <alias>`)
export ORG_ALIAS={{ORG_ALIAS}}          # {{ORG_NAME}} sandbox
# export ORG_ALIAS={{ORG_ALIAS}}_UAT        # {{ORG_NAME}} UAT
# export ORG_ALIAS=MyProjectDev   # any other org

# Confirm:
echo "Targeting: $ORG_ALIAS"
sf org display -o "$ORG_ALIAS" | grep -E "(Username|Status)"
```

> **If `$ORG_ALIAS` is empty when you run a command, `sf` will fall back to your default org** (the one with 🍁 in `sf org list --all`). That can silently target the wrong org. Always confirm `echo "$ORG_ALIAS"` prints what you expect before starting Phase 1.

**Do not substitute a global default org for the variable.** Setting `sf config set target-org=... --global` and dropping the `-o` flag makes a wrong-org retrieve undetectable: the command reads identically whichever org it hits. The scripts require the explicit alias, and Phase 0.1 pins the resolved Org Id so a mismatch aborts rather than mirroring the wrong org.

---

## The strategy in one paragraph

Phase 0 measures your org, then that measurement splits the supported types into two passes:

- **Phase 1 — small bundled shards.** Each call pulls a logical group of low-volume admin / config types (NamedCredential, RemoteSiteSetting, PermissionSet, Workflow, modern-auth types, and so on), either via an existing `manifest/fullpackage/*.xml` shard or a single `--metadata <Type1> --metadata <Type2> …` invocation. Each shard is sized so its total file count stays comfortably under the per-call cap.

- **Phase 2 — heavy types, one per call.** Every type whose live count is large enough to approach the limit on its own, or slow enough to dominate wall-clock, gets its own call.

**Which types land in which pass is an output of Phase 0, not a constant.** A type that is trivial in one org is the heaviest in another.

We run **strictly sequentially** — one retrieve in flight at a time. Slow orgs penalise concurrency badly; parallel retrieves finish later than serial ones because the org throttles. Order Phase 2 **lightest-first** so fatal errors surface in the first few minutes rather than at the end.

---

## Retrieve tiers — mirror what moves, not everything

A recurring mirror exists to keep pace with development. Most metadata types do not develop: they are authored once, or they are binaries that change when someone uploads a file. Re-pulling them every run costs the bulk of the wall-clock and buys nothing, and because they are the largest payloads they are also the ones that trip the size caps.

So classify every type Phase 0 discovers into one of two tiers, and record the classification in the audit doc.

**Tier A — retrieve every run.** Anything that changes on a development cadence, i.e. anything a developer or admin edits while shipping work:

- Apex classes, triggers, test classes
- Lightning web components, Aura bundles
- Flows and their definitions
- Objects, fields, record types, validation rules, list views, compact layouts, field sets
- Layouts, FlexiPages, quick actions
- Permission sets, permission set groups, profiles, sharing rules
- Custom metadata records and custom labels
- Named credentials, external credentials, remote sites, connected apps
- OmniStudio components **only when the org runs the standard runtime** (see below)

**Tier B — retrieve once, then only on demand.** Bulk and near-static content:

- Static resources, content assets, documents — binaries. The compressed-zip cap binds on these long before the file cap does.
- Reports, dashboards, report types, analytic snapshots
- Email templates, letterheads
- Translations and the user-facing language packs
- Experience Builder / digital-experience site content, which is largely not MDAPI-retrievable anyway

Pull Tier B when the repo is first mirrored, and thereafter only when a ticket touches one of those components. A Tier B type is not "skipped" — it is *already on disk from an earlier run*, which is a different and much more dangerous claim.

### Carry-forward must be dated, never counted as current

This is the rule the tier split exists to enforce. Tier B content sitting in the working tree was **not** retrieved this run. It is carry-forward, and the audit doc must say so with the date it actually came from:

> `staticresources/` (N files) and `contentassets/` (N) are **carry-forward from `<YYYY-MM-DD>`** — excluded from this run because the compressed-zip cap binds before the file cap. They are *not* current as of this mirror.

Counting carry-forward as covered is the single easiest way to make a mirror lie. The files are present, the counts look healthy, and nothing in a git diff reveals that the content is months stale. If you cannot state the date a Tier B type was last pulled, you cannot claim it at all.

### Deciding when to refresh Tier B

Refresh a Tier B type when any of these is true, and record which one triggered it:

- A ticket touches that content.
- The last pull predates a release, a package install, or a data-migration event.
- Someone reports a discrepancy that only stale content explains.

Otherwise leave it. A deliberately stale Tier B with a recorded date is honest; an accidentally stale one presented as current is not.

---

## Sizing rules (why some types must run alone)

Three rules decide the split. All three are properties of the Metadata API, not of any particular org:

1. **The cap is a *file* count per retrieve call, not a component count** — and there is a separate compressed-and-uncompressed size cap on the returned zip. Bundle types multiply: a Lightning web component averages several files per component, Aura similar, Apex two (`.cls` + `.cls-meta.xml`), most single-file types one. Multiply the unmanaged component count by the type's file ratio before comparing to the cap. Getting this wrong inverts the ranking — a type reporting a few thousand LWC bundles can sit near the cap while one reporting far more managed-heavy Apex classes retrieves a fraction of the files. The **size** cap, not the file cap, is what binds first on binary-heavy types.
2. **Some types are slow per record regardless of count.** The profile type is the classic case: a handful of records, but each carries the org's entire field-level-security matrix. Sort by *observed wall-clock*, not by count alone.
3. **A parent type must run before its child type**, because the child's files land inside folders the parent creates. The object-then-field pair is the one that always applies; check your footprint for others.
4. **A container type must not share a phase with — or follow — its own child type**, because they decompose into the same file. See [container/child truncation](#containerchild-truncation-silently-deletes).

**A child type that follows its parent needs a much lower floor than its own total.** When the parent phase runs first it already decomposes the child's files as part of its own retrieve, so the child phase legitimately writes only what changed. Sizing the child's floor from its own live count sets an unreachable floor and fails every healthy run. `make-order-files.sh` applies this automatically; if you hand-edit a floor, apply it yourself.

Fill this table from your own Phase 0 output and put it in the audit doc:

| Type | Live count (Phase 0) | Tier | Pass | Why |
|---|---:|---|---|---|
| `<Type>` | `<n>` | A / B | solo / bundled / excluded | near the cap / slow per record / trivial / carry-forward |

> **Sizing trap (caught the hard way):** when sizing OmniStudio types by globbing local files, **DataRaptors use `.rpt-meta.xml`, not `.odt-meta.xml`**. Glob the wrong extension and you get 0, bundle them into a small-types call, and they silently fail to retrieve. This is exactly why Phase 0 sizes from `sf org list metadata` (what the org reports) rather than from local file globs (what you think is there).

---

## Hazards the guards exist for

Every guard in `run-phase.sh` replaces an instruction that a previous run followed and still got wrong. Read this section before you edit a script or loosen a gate — each item is a failure that already happened, and prose alone did not prevent it.

### `Status: Succeeded` is not evidence of retrieval

The most dangerous line in the whole workflow. A phase can report `Status: Succeeded` while writing almost nothing, because "the API call completed" and "the components came back" are different claims. The observed shape is a `Succeeded` status alongside thousands of `cannot be found` warnings for members the manifest asked for.

So every phase carries a **file floor**: the minimum number of files it must actually write. Below the floor the phase fails its gate even though `sf` called it a success. Prose asking you to "check for a materially short result" cannot enforce this; an integer can.

### The floor must be measured by mtime, not by net-new files

A populated mirror **overwrites** far more than it adds. Count net-new files on a healthy refresh of an existing mirror and you get roughly zero — which is indistinguishable from a phase that did nothing. Touch a marker file before the retrieve and count files newer than it afterwards; that counts files actually *written*.

The floor must also be a **bare integer**. A thousands separator makes the numeric comparison error to stderr and evaluate false, silently disabling the gate — the worst possible failure mode, since the gate reports success.

### `--wait` is MINUTES

`sf`'s `--wait` takes minutes. Passing a seconds-style value turns an intended twenty-minute wait into twenty hours and removes the run's only timeout, so a hung phase blocks forever instead of failing. Anything above roughly two hours is therefore rejected as a probable seconds value.

### Two runners in one working tree corrupt the repo

Never launch two retrieves — or two agent runners — against the same working tree. Concurrent retrieves corrupt `.git/index` and cascade false failures across every later phase. A single-flight lock is mandatory.

Use an atomic `mkdir` for the lock, not `flock`: `flock` is util-linux and **absent on macOS**, so a `flock`-based guard silently no-ops there. Because the lock directory and its pid file are two separate writes, the lock has three distinguishable states, and conflating them either wedges the run or invites clearing a live lock:

| Lock state | Meaning | Action |
|---|---|---|
| pid recorded, process alive | A retrieve is genuinely running | Wait. Do not clear. |
| pid recorded, process dead | Stale lock from a crash or `kill -9` | Safe to clear |
| no pid recorded | Crash between the two writes; holder unidentifiable | Clear only after confirming no retrieve is running |

A lock refusal must never truncate the in-flight log — that would destroy the running phase's evidence.

### Retrieve logs contain NUL bytes

Retrieve output includes binary payload fragments, so plain `grep` decides the log is binary, prints `Binary file … matches` instead of the matching line, and the status gate false-negatives on a phase that actually succeeded. Read logs with `grep -a` everywhere, without exception.

### Container/child truncation silently deletes

The hazard that caused a false deletion, and the one most likely to bite again. When a **container** type and one of its **children** decompose into the *same* file on disk, the later phase rewrites that file with only its own members and silently drops the rest.

The observed case: a container type and a narrower child type both write the same per-object file. The child phase ran later, rewrote the file with just its own rule, and dropped several live rules that the container had provided. The phase reported `Status: Succeeded` and cleared its floor, so **no gate caught it** — only a manual scan for deletion-heavy diffs did.

Two mitigations, both required:

1. **Before adding any child type to a shard, check whether its container is retrieved in an earlier phase.** If so, they collide.
2. **Append a container-repair phase after the last child phase for that container**, re-retrieving it so the file is restored to the union. One repair at the end is enough — an earlier one would just be truncated again by the next sibling, and nothing reads the file mid-pass. `make-order-files.sh` places these automatically; preserve them if you hand-edit an order file.

### Retrieve is add-and-overwrite, never delete

`sf project retrieve start` writes and replaces. It never removes a local file whose component was deleted in the org. Deletions are therefore **invisible in the diff**: the mirror keeps serving schema the org no longer has, and a git-diff-based audit cannot see it. A real run found on-disk residue for a field that no longer existed in the org.

Never read "the file count is at or above the baseline" as proof of completeness. It is equally the signature of an undetected deletion. Detecting them requires the explicit reconciliation in [Phase 2.5](#phase-25--deletion-detection-sweep-mandatory).

### Enumerability is not existence

A count from `list metadata` is a statement about what the API will enumerate for your user, not about what exists. A parent type can enumerate a healthy number while its own child type enumerates zero.

Record such a type as **`enumerated-empty`** in the audit doc. Never as "covered" (you retrieved nothing) and never as "absent" (you do not know that).

### Some types reject wildcard members

A few types do not accept `<members>*</members>` and need an enumerated manifest instead. A wildcard against them fails, or worse, succeeds with nothing. Record them as **known gaps** with the reason, rather than letting the plan imply they were covered.

### Order-file arguments cannot contain spaces

`sf args` in an order-file row are split on whitespace. Any addressing form containing a space — layouts are the usual culprit — must go into a manifest and be referenced with `--manifest`, never placed inline on the row.

### Standing flags

- **Always pass `--ignore-conflicts`.** Without it, retrieves stall or fail on local/org drift noise when source tracking is not the source of truth.
- **Prefer source tracking OFF for large mirrors.** If SourceMember races appear, disable tracking for the retrieve window; re-enabling on a very large tree is optional and not required for the retrieve-before-edit workflow.

`run-phase.sh` applies both to every phase, so order-file rows carry only the addressing arguments.

---

## OmniStudio: standard runtime vs managed package (decide this in Phase 0)

Two different products wear the same name and they behave completely differently here, so the mirror treats them completely differently. **Detect the flavour on the installed namespace**, before you plan a single Omni phase:

```bash
# Is an OmniStudio managed package installed? Namespace is the reliable signal.
sf package installed list -o "$ORG_ALIAS" --json \
  | jq -r '.result[] | "\(.SubscriberPackageNamespace)\t\(.SubscriberPackageName)"'

# What does MDAPI claim to see? Recorded for the audit doc, NOT used to decide.
for T in OmniScript OmniIntegrationProcedure OmniDataTransform \
         OmniUiCard OmniInteractionConfig OmniInteractionAccessConfig; do
  printf "%-28s %s\n" "$T" \
    "$(sf org list metadata -m "$T" -o "$ORG_ALIAS" --json 2>/dev/null | jq '[.result[]?] | length')"
done
```

Detect on the namespace and not by probing the standard runtime objects, because on a managed-package org the standard `OmniProcess` object is empty **by design** — the content lives in the package's own objects. Probing `OmniProcess` for rows would report that the org has no OmniStudio at all, which is precisely the false-completeness claim this section exists to prevent. A partially-populated MDAPI Omni type is likewise not a signal in either direction.

### Managed package — never part of the recurring mirror

When the namespace is present, the components are **datapacks inside the package**, not source-backed metadata. Three independent reasons keep them out of the recurring mirror, and any one of them is sufficient:

1. **MDAPI cannot mirror them.** The Omni MDAPI types return zero on such an org, so those phases "succeed" with no files and manufacture a completeness claim out of nothing.
2. **The package's own export is slow** — it walks the datapack graph per component, so a full export is measured in hours, not the minutes a metadata phase takes.
3. **It writes to the org.** A full export creates org-side staging rows that consume Data storage (and File storage for attachment payloads). A recurring mirror that inflates org storage every run is a defect, not a sync.

So on a managed-package org:

- **Do not add any Omni MDAPI type to the run plan**, and skip the Omni shard entirely. Not just the heavy three — all of them.
- **Export the baseline once, at project initialization.** Export the active set a single time when the repo is first set up and commit it as the reference snapshot.
- **After that, export per ticket only.** When a ticket touches a specific OmniScript / IP / DataRaptor, export that component, work on it, commit it. Nothing else.
- **Never bulk-export inactive versions.** Pull a specific inactive one only when a ticket genuinely needs it.
- **Clean up staging rows after any large export.** The status field on the staging object is free text rather than a picklist, so enumerate what is actually present instead of filtering on a guessed value list. Deleting staging rows does not touch the component definitions themselves.

Record the branch explicitly in the audit doc, dated as carry-forward:

> Omni: managed package — out of recurring scope (baseline exported `<date>`, ref `<commit>`). MDAPI list-metadata = 0 by design; the Omni content on disk is **carry-forward, not a completeness claim**.

Why the date is mandatory: a phase logging `OmniScript … Succeeded` with 0 files is indistinguishable in the logs from a run against an org that genuinely has no OmniScripts. Months later nobody can tell whether the org has no Omni or the mirror silently skipped it — unless the doc says which, and as of when.

### Standard runtime — retrieve normally, and diff version-pairs

When there is no managed-package namespace and MDAPI reports real counts, the Omni types are ordinary metadata. Size them in Phase 0 and retrieve them like any other heavy type, in Tier A.

One extra step applies, because these types are **versioned in their file name**: a new version arrives as a brand-new file rather than as a change to the old one. A naive read of the diff then shows a large block of added lines "from nothing" and no indication that the previous version still exists beside it — so a substantive rewrite and a trivial version bump look identical.

For every Omni file added in this run, find its version siblings and diff against the highest previous version instead of against nothing:

```bash
# Group added Omni files by their name minus the trailing version number,
# then diff the new version against the highest previous one.
git diff --name-only --diff-filter=A "$DIFF_BASE" -- \
    'force-app/main/default/omniScripts/*' \
    'force-app/main/default/omniIntegrationProcedures/*' \
  | while read -r new; do
      stem=$(basename "$new" | sed -E 's/_[0-9]+\.(os|oip)-meta\.xml$//')
      prev=$(ls -1 "$(dirname "$new")" 2>/dev/null \
               | grep -E "^${stem}_[0-9]+\." | sort -t_ -k2 -n | tail -2 | head -1)
      [ -n "$prev" ] && [ "$(basename "$new")" != "$prev" ] \
        && echo "=== $stem: $prev -> $(basename "$new")" \
        && diff "$(dirname "$new")/$prev" "$new" | head -40
    done
```

Report the *delta between versions* in the audit doc, not the raw added-line count. "Version N+1 changes two conditional formulas and one DataRaptor mapping" is useful; "+1,400 lines" is noise that hides it.

---

## Phase 0 — pre-flight and discovery

Phase 0 is not read-only: it rotates logs, may stash WIP, and produces the footprint that every later phase depends on. Run all of it before the first retrieve.

### 0.0 Spawn the explicit plan FIRST (mandatory)

**Before running any `sf` command, before any retrieve writes to disk, the agent MUST spawn an explicit `TodoWrite` plan covering the entire end-to-end sequence.** A full retrieve is a long-running multi-stage operation — many MDAPI calls plus an audit doc and two git commits — and any single phase can stall, hit a transient org error, or get interrupted. A plan up front makes the run **resumable**: if a heavy phase fails, the agent re-reads its todo list and knows exactly which phases still need to run, which already succeeded, and where in the audit/commit workflow it left off.

Minimum required todo entries. The Phase 1 and Phase 2 entries are **filled in from Phase 0.3's footprint** — one todo per actual shard and per actual solo type, not a fixed count copied from this doc:

```
[ ] Phase 0.1 — org auth check + pin the Org Id for this run
[ ] Phase 0.2 — rotate .retrieve-logs/ + seed fresh current/
[ ] Phase 0.3 — footprint discovery (supported types + live counts + OmniStudio flavour)
[ ] Phase 0.4 — WIP check (interactive) + capture PRE_HEAD
[ ] Phase 0.5 — generate order files + per-run manifests from the footprint
[ ] Phase 1.<n>  — one todo per bundled small-type shard, sequential
[ ] Phase 2.<n>  — one todo per solo heavy type, sequential lightest→heaviest
[ ] Phase 2.5   — deletion-detection sweep (org fullNames vs on-disk names, per type)
[ ] Phase 3.4.1 — per-type analysis todos (one per type that changed; spawned after Phase 2)
[ ] Phase 3.4.2 — cross-type synthesis todo
[ ] Phase 3.4.3 — fill remaining audit-doc sections
[ ] Phase 3.4.B — adversarial Gate B on the finished audit doc (two parallel critics)
[ ] Phase 3.5 — Commit 1: mirror snapshot (force-app/ + manifest/ + config/, doc held back)
[ ] Phase 3.5 — Embed mirror hash in audit doc §9
[ ] Phase 3.5 — Commit 2: audit doc only
[ ] Phase 3.6 — pop WIP (only if stashed in 0.4) + verify clean tree
```

**There is no Gate A on a retrieve run.** The single gate is Gate B on the finished audit doc — see [Phase 3.4.B](#34b-adversarial-gate-b--review-the-finished-audit) for why the review sits there and what it covers.

Mark each `in_progress` before starting and `completed` only after it actually finishes successfully (per `Status: Succeeded` in the log for retrieves, per the `git log -1` hash for commits). Do NOT batch-complete todos retroactively — losing the running-todo signal makes a mid-sequence failure ambiguous about what was actually finished.

If the run was interrupted (org timeout, user `Ctrl-C`, agent crash, transient `sf` hang, sandbox restart), the FIRST thing the resuming agent does is read the todo list and identify the most recent `in_progress` entry — that's where work resumes. Don't restart from Phase 1 unless the resume point is unrecoverably ambiguous.

### 0.1 Org authentication check + pin the Org Id

```bash
sf org list --all
```

Confirm the target org is `Connected`. Abort and re-auth if expired.

Confirm too that the alias **resolves to the org you mean**, because an alias check alone is not protection. The target alias is usually also the shell's default org, so a dropped or empty `-o` flag resolves to the same place while you are testing and to whatever the default happens to be later — a silent wrong-org retrieve that looks entirely normal in the logs.

```bash
sf org display -o "$ORG_ALIAS" --json | jq -r '.result | "\(.alias)  \(.id)  \(.username)"'
```

Read that back and make sure it is the intended org. The Id gets **pinned to disk in 0.2**, after the log rotation, so the rotation cannot carry this run's pin into the archive.

### 0.2 Rotate previous run + seed fresh `current/` log dir

```bash
# Rotate any leftover .retrieve-logs/current/ from a previous run into
# .retrieve-logs/archive/<UTC-ts>/ so this run starts with a clean current/.
# (Skip the rotation cleanly if no prior current/ exists — first-ever run.)
if [ -d .retrieve-logs/current ] && [ -n "$(ls -A .retrieve-logs/current 2>/dev/null)" ]; then
  ARCHIVE_TS=$(date -u +"%Y-%m-%dT%H%M%SZ")
  mkdir -p .retrieve-logs/archive
  mv .retrieve-logs/current ".retrieve-logs/archive/${ARCHIVE_TS}"
  echo "  rotated previous run -> .retrieve-logs/archive/${ARCHIVE_TS}/"
fi
mkdir -p .retrieve-logs/current
date "+Started: %Y-%m-%d %H:%M:%S" > .retrieve-logs/current/_session.txt

# Pin the Org Id — AFTER the rotation, so this run's pin cannot end up in the
# archive. Resolve it HERE rather than reusing a variable from 0.1: a long run
# spans many shell invocations, and an unset variable would write an EMPTY pin
# that stalls every later phase. Every phase reads this file and fails closed on
# a mismatch, so nothing is hardcoded and the scripts move between orgs untouched.
ORG_ID=$(sf org display -o "$ORG_ALIAS" --json 2>/dev/null | jq -r '.result.id // empty' | cut -c1-15)
[ -n "$ORG_ID" ] || { echo "ABORT: could not resolve an Org Id for '$ORG_ALIAS' — re-auth and retry"; return 2>/dev/null || exit 1; }
printf '%s\n' "$ORG_ID" > .retrieve-logs/current/_org-id.txt
echo "Pinned: $ORG_ALIAS -> $(cat .retrieve-logs/current/_org-id.txt)"
```

If `_org-id.txt` is missing or empty when a phase starts, that phase aborts and points back here. An unpinned run has no wrong-org protection at all, so it is not allowed to proceed.

**Nothing in this runbook relies on a shell variable surviving between steps.** A full retrieve runs for a long time across many command invocations, and an agent driving it may not reuse one shell at all — so every value a later phase needs is written to `.retrieve-logs/current/`: the Org Id here, `PRE_HEAD` in 0.4, the audit-doc path in 3.4, the plan and floors in 0.5. `$ORG_ALIAS` is the one exception, and every script fails loudly when it is unset rather than falling back to a default org.

> **Tip:** Add `.retrieve-logs/` to `.gitignore` if it isn't already. The single umbrella entry covers the active subdir (`.retrieve-logs/current/`), every archived prior run (`.retrieve-logs/archive/<TS>/`), and the generated order files and manifests inside them.

### 0.3 Footprint discovery (MANDATORY — this drives everything downstream)

Measure the org. Do not skip this and do not substitute counts from a previous run or another org — a stale footprint is how a type silently exceeds the per-call cap or gets bundled into a call it should never have shared.

```bash
# a) Which types does THIS org actually support and expose to your user?
#    childXmlNames is NOT optional: CustomField, RecordType, ValidationRule,
#    ListView, WebLink, CompactLayout, FieldSet, BusinessProcess and the
#    Workflow* types are children of CustomObject/Workflow and never appear in
#    xmlName. Omit them and the single heaviest type in most orgs — CustomField —
#    is silently reported "unsupported" and never gets sized.
sf org list metadata-types -o "$ORG_ALIAS" --json \
  | jq -r '.result.metadataObjects[] | .xmlName, ((.childXmlNames // [])[])' \
  | sort -u > .retrieve-logs/current/_types-supported.txt

# Sanity gate: the two types with a hard ordering constraint must both be here.
for T in CustomObject CustomField; do
  grep -qx "$T" .retrieve-logs/current/_types-supported.txt \
    || echo "  !! $T missing from supported set — discovery is wrong, STOP"
done

# b) Which types does the seed manifest set ask for?
grep -ho '<name>[^<]*</name>' manifest/fullpackage.xml manifest/fullpackage/*.xml \
  | sed 's/<[^>]*>//g' | sort -u > .retrieve-logs/current/_types-requested.txt

# c) The gap in both directions — requested-but-unsupported, and supported-but-unrequested.
comm -13 .retrieve-logs/current/_types-supported.txt .retrieve-logs/current/_types-requested.txt \
  > .retrieve-logs/current/_types-unsupported.txt
comm -23 .retrieve-logs/current/_types-supported.txt .retrieve-logs/current/_types-requested.txt \
  > .retrieve-logs/current/_types-uncovered.txt

# d) Live component count per requested+supported type. This is the sizing input.
#    Four traps, all of which silently produce a wrong number rather than an error:
#      - A `<members>*</members>` retrieve returns ONLY unmanaged components, while
#        listMetadata counts managed-package ones too, so the raw total can be an order
#        of magnitude high on a package-heavy org. Size on unmanaged.
#      - BUT the filter MUST tolerate a null manageableState. Many types omit the field
#        entirely, so an equality-only test yields FALSE ZEROS on types that are plainly
#        populated — the exact failure that reported a heavily-used type as empty.
#      - Folder-based types need --folder; without it they report 0 however many exist.
#      - On any sf error there is no .result key, and `null | length` is 0 — so a failed
#        call is indistinguishable from an empty type. Record it, never count it as 0.
UNMANAGED='[.result[]? | select((.manageableState == null) or (.manageableState == "unmanaged"))] | length'
FOLDER_TYPES='Report|Dashboard|Document|EmailTemplate'
: > .retrieve-logs/current/_footprint.tsv
: > .retrieve-logs/current/_footprint-errors.tsv
while read -r T; do
  if printf '%s' "$T" | grep -qxE "$FOLDER_TYPES"; then
    n=0
    for F in $(sf org list metadata -m "${T}Folder" -o "$ORG_ALIAS" --json 2>/dev/null \
                 | jq -r '.result[]?.fullName'); do
      n=$(( n + $(sf org list metadata -m "$T" --folder "$F" -o "$ORG_ALIAS" --json 2>/dev/null \
                    | jq "$UNMANAGED") ))
    done
    printf "%s\t%s\n" "$n" "$T" >> .retrieve-logs/current/_footprint.tsv
    continue
  fi
  raw=$(sf org list metadata -m "$T" -o "$ORG_ALIAS" --json 2>&1)
  if ! printf '%s' "$raw" | jq -e 'has("result")' >/dev/null 2>&1; then
    printf "%s\t%s\n" "$T" "$(printf '%s' "$raw" | jq -r '.message // "unknown error"')" \
      >> .retrieve-logs/current/_footprint-errors.tsv
    continue
  fi
  printf "%s\t%s\n" "$(printf '%s' "$raw" | jq "$UNMANAGED")" "$T" \
    >> .retrieve-logs/current/_footprint.tsv
done < <(comm -12 .retrieve-logs/current/_types-supported.txt .retrieve-logs/current/_types-requested.txt)
sort -rn -o .retrieve-logs/current/_footprint.tsv .retrieve-logs/current/_footprint.tsv
column -t .retrieve-logs/current/_footprint.tsv

# The footprint is only usable if nothing failed. An error here is not a zero.
[ -s .retrieve-logs/current/_footprint-errors.tsv ] \
  && { echo "!! footprint incomplete — resolve these before Phase 0.5:"; \
       cat .retrieve-logs/current/_footprint-errors.tsv; }
```

Then run the **OmniStudio flavour detection** from the section above, and record which branch applies.

Step (d) is the slow part — it makes one list-metadata call per type. Let it finish; every later decision reads from `_footprint.tsv`.

**Sanity-check every zero before you trust it.** A zero in the footprint has four possible causes and only one of them is real:

| Zero cause | How to tell |
|---|---|
| Genuinely empty | Cross-check against on-disk files for that type; both empty agrees |
| Null `manageableState` filtered out | Re-count without the filter; a large raw total against a zero unmanaged count is the tell |
| Folder-based type queried without `--folder` | The type is in `FOLDER_TYPES` above |
| The call failed | The type appears in `_footprint-errors.tsv` |

```bash
# Any type reporting 0 that has files on disk is a discovery bug, not an empty type.
awk -F'\t' '$1==0 {print $2}' .retrieve-logs/current/_footprint.tsv
```

A type that reports zero while its parent or its own directory is plainly populated is **`enumerated-empty`**, not covered and not absent — record it that way and move on rather than silently accepting the zero.

Two known quirks of `_types-unsupported.txt`. Folder pseudo-types (`ReportFolder`, `DashboardFolder`, `DocumentFolder`, `EmailFolder`) are addressed through their parent type and legitimately never appear in the supported list. And if a type you *know* the org uses shows up there, suspect the discovery query before believing it — that is the symptom of the `childXmlNames` mistake above.

**Container types under-report.** `CustomLabels`, `SharingRules`, `Workflow`, `MatchingRules`, and `AssignmentRules` each count as **1** while carrying many children (`CustomLabel` alone can be five figures). They retrieve as a single file, so they are cheap in file terms — but do not read their `1` as "trivial component count" when reasoning about anything else.

Review `_types-uncovered.txt` deliberately rather than ignoring it. Most entries will be licensed-but-unused platform features, but this is exactly where an important type goes missing. For each uncovered type decide *cover it* or *exclude it with a reason*, and record both in the audit doc's **Type coverage & sizing** section. "We didn't notice it" is not a reason.

### 0.4 WIP check (interactive) + capture `PRE_HEAD`

Run this before any retrieve writes to disk, and record the decision — Gate B reviews it later against what actually landed in the mirror commit.

```bash
wip_count=$(git status --short | wc -l | tr -d ' ')
if [ "$wip_count" -gt 0 ]; then
  echo "WIP detected: $wip_count modified or untracked files."
  git status --short | head -20
  # Ask the user: stash+pop / continue / abort  (table in Phase 3.1-3.3)
fi

PRE_HEAD=$(git rev-parse HEAD)
echo "$PRE_HEAD" > .retrieve-logs/current/_pre-head.txt
echo "Pre-retrieve HEAD: $(git rev-parse --short HEAD)"
```

`PRE_HEAD` is persisted to a file, not just an env var — the shell may not survive a long run.

### 0.5 Generate the order files and manifests

The run plan is **generated from the footprint**, not written by hand. Hand-sizing is where transcribed floors and mis-ordered phases come from, and a generated plan is reproducible from evidence:

```bash
bash docs/org-mirror/make-order-files.sh
```

It reads `_footprint.tsv` (plus the exclusion list, if you wrote one) and emits into `.retrieve-logs/current/`:

| Output | Contents |
|---|---|
| `order-phase1.tsv` | Bundled small-type shards, each summed well under the file cap |
| `order-phase2.tsv` | Solo heavy types, ordered per the constraints below |
| `manifests/*.xml` | One manifest per shard, at the API version from `sfdx-project.json` |
| `_plan-notes.txt` | Every decision the generator made, and why — paste into the audit doc |
| `_cap-blocked.tsv` | Types whose estimate exceeds the cap. Empty file is the good case. |

**Declare exclusions before you generate.** One type per line with a reason after a tab; the generator honours the list and copies the reasons into `_plan-notes.txt` so Gate B can attack them:

```bash
cat > .retrieve-logs/current/_exclusions.tsv <<'EOF'
<Type>	Tier B binary — carry-forward from <YYYY-MM-DD>, size cap binds first
<Type>	Rejects wildcard members — known gap, needs an enumerated manifest
EOF
```

"We didn't notice it" is not a reason. Work `_types-uncovered.txt` from 0.3 before generating and decide *cover* or *exclude with a reason* for every entry.

The generator applies the ordering constraints so you cannot forget them:

- Lightest first within each pass, so fatal errors surface in the first minutes rather than at the end.
- Each parent type immediately before its child type.
- The bundle type with real cap exposure **first** in Phase 2, so a cap failure costs one short phase rather than the whole pass.
- The field-level-security-heavy profile type **last** — slowest per record, and the cheapest phase to retry.
- A **container-repair phase after the last child of each colliding container**, restoring the union.

Read `_plan-notes.txt` and confirm the ordering before running anything. Then turn each generated row into its own todo.

**A type over the cap ships as a commented-out row**, because a live row would buy a guaranteed failure after a long wait. The generator prints those types to the terminal as well as recording them, so you decide the split axis before the run rather than mid-incident — see [Cap fallback](#cap-fallback--when-a-single-type-exceeds-the-limit). A type merely *near* the cap stays live with a proximity warning attached. **A commented row is not retrieved**: until you shard it, that type is absent from the mirror and the audit doc must say so.

**A regenerated plan replaces the previous one.** If you re-run discovery mid-run, regenerate the order files too — a plan built from a stale footprint is exactly how a type silently exceeds the cap or gets bundled into a call it should never have shared.

---

## Phases 1 and 2 — execute the generated plan

Both passes run through the same driver. Phase 1 is the bundled small-type shards; Phase 2 is the heavy types, one per call. Nothing about the commands differs — only the order file does.

**Run from the repo root.** Every path in these scripts is relative to it, and `run-phase.sh` aborts if `./force-app` is not present.

```bash
export ORG_ALIAS=<your-alias>

bash docs/org-mirror/run-all.sh .retrieve-logs/current/order-phase1.tsv
bash docs/org-mirror/run-all.sh .retrieve-logs/current/order-phase2.tsv
```

`run-all.sh` **stops at the first phase that fails its gate** and prints the resume command. Nothing after a failure runs, so a partial mirror never silently becomes a commit. It also refuses to report completion when zero phases ran, and always prints `phases_run=N` so a no-work run cannot be mistaken for a full one.

### Resuming after a failure

```bash
bash docs/org-mirror/run-all.sh .retrieve-logs/current/order-phase1.tsv <phase-name>
```

A resume name matching no row **aborts and lists the valid names**, rather than skipping every phase and reporting success — which is what a typo would otherwise produce.

Where the failure was a submitted-but-incomplete job, `run-phase.sh` says so and gives you the `sf project retrieve resume` form. Where the CLI failed *before* creating a job, it says that instead, because resuming there would attach to an unrelated earlier job. Those two cases look nearly identical in the output and have opposite correct responses, which is why the script distinguishes them for you.

### If a run dies mid-phase

The lock is a directory, not a file descriptor, so a hard kill leaves it behind. `run-phase.sh` reports which of the [three lock states](#two-runners-in-one-working-tree-corrupt-the-repo) applies. Clear it only in the two safe cases:

```bash
rm -rf .retrieve-logs/current/.retrieve.lock.d
```

### Order-file format

```
logname <TAB> wait_MINUTES <TAB> file_floor|- <TAB> sf args
```

| Field | Meaning |
|---|---|
| `logname` | Log file name and phase identity. Numeric prefixes keep the pass in order. |
| `wait_MINUTES` | `--wait` in **minutes**. Values above roughly two hours are rejected as probable seconds. |
| `file_floor` | Minimum files the phase must write, or `-` to skip the check. Must be a **bare integer**. |
| `sf args` | Addressing arguments only — split on whitespace, so **no argument may contain a space**. |

`-o`, `--ignore-conflicts`, and `--wait` are supplied by the script; do not repeat them on the row. Rows beginning with `#` are comments, which is how the generator ships a row that needs a human decision before it fires.

### The per-phase ledger

Every phase appends one line to `.retrieve-logs/current/_progress.tsv`:

```
timestamp, phase, elapsed_seconds, files_written, OK|SHORT|GATE_FAIL, warn=N
```

This is the run's evidence trail, and audit-doc §2 is filled from it. **Record your own wall-clock per phase** — it becomes the baseline the *next* run compares against. Never copy timings from another org or another doc: they vary several-fold with org load, so a borrowed number tells you nothing about whether today's run is healthy. For a prior baseline, read the most recent audit doc in `changes/git/`.

### When a phase falls short of its floor

A short result is the documented fallback trigger, not a reason to lower the floor. Work through it in this order:

1. Read the log for `cannot be found` warnings. A high count against a wildcard means the org has fewer components than the manifest asks for — reconcile it in the audit doc.
2. Check whether an earlier phase already wrote those files. A child type following its parent legitimately writes far less than its own total; if the floor did not account for that, the floor is wrong.
3. Check for [container/child truncation](#containerchild-truncation-silently-deletes) — note that a *high* file count can accompany silent deletions inside a rewritten file.
4. If the type genuinely exceeds a cap, use the [enumerated fallback](#cap-fallback--when-a-single-type-exceeds-the-limit).

Only once one of those explains the shortfall may you adjust the floor, and the adjustment belongs in `_plan-notes.txt` where Gate B will see it.

---

## Phase 2.5 — deletion-detection sweep (mandatory)

Because [retrieve never deletes](#retrieve-is-add-and-overwrite-never-delete), the mirror can be perfectly current and still be wrong: every file the org has is present and correct, *plus* files for components the org no longer has. Reading the git diff cannot find those, because nothing about them changed.

Run this before the audit doc makes any coverage claim, for each Tier A type this run retrieved:

```bash
# Org side: what the org enumerates for this type.
sf org list metadata -m "$T" -o "$ORG_ALIAS" --json   | jq -r '.result[]? | select((.manageableState == null) or (.manageableState == "unmanaged")) | .fullName'   | sort > ".retrieve-logs/current/_del-org-${T}.txt"

# Disk side: the component names the mirror carries for the same type. The path-to-fullName
# mapping is type-specific: strip the metadata suffix, and for child types rebuild the
# Parent.Child form the API uses. Write the result to _del-disk-<T>.txt, then compare:
comm -13 ".retrieve-logs/current/_del-org-${T}.txt" ".retrieve-logs/current/_del-disk-${T}.txt"   > ".retrieve-logs/current/_del-residue-${T}.txt"
```

Anything in the residue file exists locally and not in the org. Each entry is one of:

| Cause | Action |
|---|---|
| Deleted in the org | Delete locally, and say so in the audit doc |
| Managed or packaged, filtered out of the org-side list | Leave it; note the filter |
| The type is [enumerated-empty](#enumerability-is-not-existence) | Leave it; record the type as enumerated-empty |
| Your path-to-fullName mapping is wrong | Fix the mapping — never delete on a bad comparison |

**Never bulk-delete from the residue list.** The mapping is the fragile part, and a wrong mapping deletes live metadata. Confirm a sample against the org before removing anything.

Record the sweep's outcome in the audit doc even when it is clean. Until it runs, a mirror can claim currency but never completeness — and "we didn't check" is indistinguishable in the record from "there was nothing to find".

---

## Phase 3 — Audit + commit (mandatory)

Every retrieve run ends with a persistent audit doc under `changes/git/`, committed via the same two-commit pattern as [`documentation-workflow.mdc`](../../.cursor/rules/documentation-workflow.mdc) (mirror commit first, doc commit second referencing the mirror commit hash).

**Why this matters:** in a Salesforce repo where teammates deploy directly to the org — often via a VDI pipeline that commits later, or sometimes never — the local repo is rarely the source of truth. Most of the diff in any retrieve is someone else's work. The audit doc lets a future investigator bisect by retrieve date and pinpoint when a given component shifted, even if no commit ever landed in the repo from the person who shipped it.

### 3.1–3.3 Already done in Phase 0 — do not re-run

| Step | Where it happened | Why it moved |
|---|---|---|
| WIP check (interactive) | **Phase 0.4** | Nothing may write to disk before the WIP decision is made and recorded. |
| Capture `PRE_HEAD` | **Phase 0.4** | Persisted to `.retrieve-logs/current/_pre-head.txt` so a long run surviving a shell restart still has its diff base. |
| Run the retrieve phases | **Phases 1 and 2** | Record per-phase wall-clock and any retries as you go; that data feeds §2 of the audit doc. |

WIP responses, for reference (captured in Phase 0.4, reported in §7):

| Response | What happens |
|---|---|
| **stash + pop** | `git stash push -u -m "pre-retrieve-$(date +%Y%m%d-%H%M)"` ran in Phase 0.4. After Phase 3.6, `git stash pop` runs and any conflicts are reported. |
| **continue** | Retrieve runs with WIP in the tree. The WIP files land in the same uncommitted set as the org diffs — do not fold them into the mirror commit; use selective `git add` paths in 3.5. |
| **abort** | Stop. Nothing has changed yet. |

### 3.4 Generate the audit doc

Once the last Phase 2 type finishes:

```bash
SLUG="retrieve-$(date '+%Y-%m-%d-%H%M')-$ORG_ALIAS"
DOC="changes/git/${SLUG}.md"
mkdir -p changes/git
cp changes/_templates/_TEMPLATE_retrieve.md "$DOC"

# Record the path. §3.5 commits this file many steps later, so it reads the path
# from here rather than from a variable that a restarted shell would have lost —
# and `git add ""` on an empty variable stages nothing while looking like it worked.
printf '%s\n' "$DOC" > .retrieve-logs/current/_doc-path.txt
echo "Audit doc seeded at: $DOC"
```

The audit doc is THEN filled in three explicit phases — **do not collapse them into a single sweep**. On heavy days (>50 files changed), reading the whole diff at once silently misses cross-type connections (a new Apex method added for an LWC that calls it; a new field that a new DataRaptor reads; a permset grant that pairs with a FlexiPage update). The per-type-first → synthesize → fill-the-rest order below prevents those misses.

### 3.4.1 Per-type analysis (todo-driven, magnitude-ordered)

**Mandatory.** Spawn one `TodoWrite` entry per metadata type that ACTUALLY changed — skip the empty types rather than pre-populating one todo per planned phase. Each todo is worked end-to-end before moving to the next.

#### Compute magnitude

```bash
# Read the base from disk, not from $PRE_HEAD — the shell that set it may be
# long gone. An empty base makes every `git diff` below return nothing, which
# reads exactly like "the org didn't change".
DIFF_BASE=$(cat .retrieve-logs/current/_pre-head.txt)
[ -n "$DIFF_BASE" ] || { echo "no PRE_HEAD recorded — cannot compute the diff"; exit 1; }

# Total churn per type (modifications only, doesn't count untracked yet):
for dir in classes triggers lwc aura omniScripts omniIntegrationProcedures \
           omniDataTransforms layouts flexipages flows objects \
           profiles permissionsets customMetadata \
           externalCredentials namedCredentials apexEmailNotifications \
           cleanDataServices siteDotComSites; do
  churn=$(git diff --numstat "$DIFF_BASE" -- "force-app/main/default/$dir/" \
            2>/dev/null | awk '{s+=$1+$2} END{print s+0}')
  [ "$churn" -gt 0 ] && printf "  %6d  %s\n" "$churn" "$dir"
done | sort -rn

# Add new-file lines for each type that has untracked files:
git ls-files --others --exclude-standard force-app/main/default/ \
  | awk -F/ '{print $4}' | sort | uniq -c | sort -rn
```

#### Order the todos

Sort by descending magnitude (sum of churn + new-file lines). **Tie-break by blast-radius weight** when two types are within ~20% of each other:

| Weight | Types |
|---|---|
| Highest (analyze first) | ApexClass, ApexTrigger, CustomField/CustomObject (schema), permissionsets, sharingRules |
| Medium | LightningComponentBundle, AuraDefinitionBundle, OmniScript, OmniIntegrationProcedure, OmniDataTransform, flows |
| Lowest (analyze last) | profiles (usually mechanical), layouts, flexipages, customMetadata, cleanDataServices, siteDotComSites |

A high-weight type with 50 lines of churn beats a low-weight type with 100 lines of churn — the security/Apex/schema flags are the ones that bite hardest if missed.

#### Per-todo workflow

Per-type analysis spans many steps, so re-establish the diff base from disk at the start of each one rather than trusting a variable set earlier — an empty `$DIFF_BASE` makes every `git diff` below fail:

```bash
DIFF_BASE=$(cat .retrieve-logs/current/_pre-head.txt)
[ -n "$DIFF_BASE" ] || { echo "no PRE_HEAD recorded — cannot compute the diff"; exit 1; }
```

For each per-type todo, in order:

1. **List the changed files** under that type:

   ```bash
   git diff --name-only "$DIFF_BASE" -- "force-app/main/default/<dir>/"
   git ls-files --others --exclude-standard "force-app/main/default/<dir>/"
   ```

2. **Diff each file** with per-extension hints (read the actual content, don't just stat):

   | Extension | What to look for |
   |---|---|
   | `.cls` / `.trigger` | Class/method signatures, sharing keyword, `@IsTest` count, sObject DML targets, callouts to other classes (record their names) |
   | `.js` / `.html` / `.css` (LWC) | `@api` properties (exposed API), `import` paths (Apex imports → record method names), wire adapters |
   | `.os-meta.xml` / `.oip-meta.xml` | `<isActive>` flips, `<propertySetConfig>` payload changes, new/removed elements, DR/remote-action bundle swaps |
   | `.rpt-meta.xml` (DataRaptor) | `<isManagedUsingStdDesigner>` (legacy vs std designer flip — different cache layer!), `<inputType>` / `<outputType>`, field mappings |
   | `.field-meta.xml` | `<type>` (changing this on an existing field is destructive), `<trackHistory>`, `<required>`, `<unique>` |
   | `.recordType-meta.xml` | `<picklistValues>` blocks (new field added to picklist set), `<active>` |
   | `.profile-meta.xml` / `.permissionset-meta.xml` | `<allowDelete>`, `<allowEdit>`, `<allowRead>` flips on `<objectPermissions>`; new `<fieldPermissions>` with `<editable>true</editable>`; new `<classAccesses>` with `<enabled>true</enabled>` (the `<enabled>false</enabled>` ones are mechanical awareness-list noise) |
   | `.flow-meta.xml` | `<status>Active\|Draft\|Obsolete</status>` |
   | `.flexipage-meta.xml` | Component additions/removals on record pages |
   | Anything else | Plain diff; ask yourself "what behaviour does this change?" |

3. **Write a one-line "what stood out" note** for each notable file into the matching §4.X subsection of the audit doc.

4. **Record cross-type leads** as you go — a side-list of names/refs that might tie to other types. The synthesis step (§3.4.2 below) will pick these up:
   - New Apex method names, new Apex class names
   - New CustomField API names, new RecordType picklist additions
   - New IP UniqueNames, new DataRaptor names, new OmniScript subType+version
   - New LWC bundle names and the Apex imports they make (`@salesforce/apex/<ClassName>.<methodName>`)
   - New PermissionSet object/field grants (and which object/field)
   - New FlexiPage record-page changes (and which sObject's record page)

   Keep this side-list in working memory or in a scratch `.retrieve-logs/current/_crosslinks.txt` — you'll re-read it in §3.4.2.

#### Special: OmniStudio version-pair diff

When the type is `OmniScript` / `OmniIntegrationProcedure` / `OmniDataTransform` AND the diff includes a NEW `<Name>_<vN+1>.os-meta.xml` (or `.oip-meta.xml` / `.rpt-meta.xml`) alongside a deactivation flip of the existing `<Name>_<vN>.*`, RUN a version-pair diff and summarize the substantive delta. Without this, the new version reads as "+N lines from nothing" and the actual change is invisible.

```bash
# Example for an IP version pair (works the same for OS / DR):
git diff --no-index \
  force-app/main/default/omniIntegrationProcedures/MyType_MySubType_Procedure_27.oip-meta.xml \
  force-app/main/default/omniIntegrationProcedures/MyType_MySubType_Procedure_28.oip-meta.xml \
  | head -200
```

Summarize in §4.X with: which elements were added/removed, which conditional formulas changed, which DR / remote-action bundles were swapped. Note "v_N → v_N+1 (paired)" inline.

#### Special: class / file rename detection

For modified `.cls` and `.trigger` files, scan the class-declaration line on both sides of the diff. A name change inside the same file (or a filename change vs class declaration mismatch) means a rename — easy to overlook because the file path looks unchanged:

```bash
git diff "$DIFF_BASE" -- 'force-app/main/default/classes/*.cls' \
  | grep -E '^[+-]\s*(public|private|global)( (with|without|inherited) sharing)? class\s+\w+' \
  | sort
```

If you see paired `-` / `+` lines with different class names, OR if the `+` class name differs from the filename basename, flag a rename in §6.1 of the audit doc with both names. This pattern catches:

- **Casing flips** (e.g. `XMLValidationService → XmlValidationService`) where the file basename stays uppercase but the class declaration changes case. Apex compiles fine because class lookup is case-insensitive, but downstream callers may have explicitly-cased references that break.
- **Wholesale renames** where someone refactored the class name in the org's Setup UI; the file basename keeps the old name (the `ApexClass.Id` didn't change), the declaration line moved.
- **Sharing-keyword flips** that often accompany renames (`public class` → `public with sharing class` or vice versa). The sharing change is the security-relevant half — flag separately in §6.1 even when the rename itself is cosmetic.

### 3.4.2 Cross-type synthesis (after all per-type todos complete)

**Mandatory.** Spawn ONE final synthesis todo after every per-type todo has been marked `completed`. This is where the "holistic story" emerges — a new Apex method is just a new Apex method until you notice the new LWC bundle that imports it.

#### Workflow

1. **Re-read every §4.X section** you just wrote. Re-load the cross-type leads side-list from §3.4.1.
2. **Search for connections** across types. Patterns to check:

| Connection signal | What to look for | Example finding (illustrative — substitute your project's domain words) |
|---|---|---|
| New Apex method + new LWC import | LWC `.js` `import X from '@salesforce/apex/SomeClass.method'` where `SomeClass.method` is a newly-added Apex method | "The new `OrderActivationService.activate()` method + the new `orderActivationButton` LWC bundle that calls it ship the OrderActivation feature." |
| New CustomField + new picklist values + new DataRaptor | A new `<CustomField>` appearing in a new `<picklistValues>` block on RecordTypes AND being read by a new/modified DR | "New field `Priority__c` + N RecordType updates + the DR `OrderPriorityExtract_1` together extend the order-intake form." |
| New IP + new DR on same domain | New `<Name>_Procedure_N.oip-meta.xml` and a new `<NameAdjacent>_1.rpt-meta.xml` whose names share a domain word (Order / Address / Account / Case / etc. — substitute your project's domain prefixes) | "New IP `FetchOrderAddresses_Procedure_2` + new DR `OrderAddressExtract_1` together back the order-address-screen rewrite." |
| PermissionSet grant + FlexiPage update | A new `<allowDelete>true</allowDelete>` or `<fieldPermissions>` grant + a FlexiPage edit on a record page for the SAME sObject | "Coherent ship: `OrderManagementAdmin` permset gained DELETE on `Order__c` paired with the `OrderRecordPage` FlexiPage updates." |
| New Test class + relaxed visibility | A new `*Test.cls` + corresponding source class methods flipped from `private` to `public` (or `@TestVisible` added) | "Service split: `AccountValidationService` shipped with paired `*Test` after relaxing `buildInput` / `parseOutput` from `private` to `public`." |
| Cross-class coordination flag | A new `static Boolean` field on class A + an assignment to it inside class B's batch/trigger logic | "`OrderTriggerHelper.RunningFromBatch` flag wires up so the trigger suppresses rollup recalc while `OrderBatchHandler` runs." |

3. **Write findings into a NEW `### 4.11 Cross-type synthesis`** section in the audit doc. Use the table shape: *Connection* / *Types involved* / *Holistic finding*. One row per coherent feature ship the per-type sections fragmented across.
4. **Update `## 1. TL;DR`** to lead with the holistic stories rather than just headline numbers. A reader should be able to glance at the TL;DR and know "ah, today's mirror was the OoO Log feature ship + an NPDB scheduler addition" rather than just "120 files changed".

> **Note on the worked examples below.** Component names (`AuditLogService`, `Activity_Log__c`, etc.) are deliberately generic — substitute your project's actual prefixes / sObjects when applying the pattern. The structural pattern is what matters: how an Apex change + an LWC change + a permset change + a FlexiPage change cohere into "one feature ship" rather than reading as four unrelated diffs.

#### Worked example 1 — `AuditLog*` service + LWC

§4.1 noted four new ApexClasses: `AuditLogSerializer + Test`, `AuditLogService + Test`. §4.3 noted modifications to `lwc/auditLogTable/auditLogTable.js`. The LWC's `.js` imports `@salesforce/apex/AuditLogService.fetchEntries`. **Synthesis:** the four classes + the LWC together back a new audit-log surface on the admin UI; ship-rank: feature complete (paired tests + functional UI).

#### Worked example 2 — `Activity_Log__c` DELETE grant + FlexiPage

§4.8 noted `flexipages/ActivityLogRecordPage` was modified. §4.9 noted `OrderManagementAdmin.permissionset-meta.xml` gained `allowDelete: false → true` on `Activity_Log__c` (the ONLY object-permission diff in the perm set — 4 diff lines total). **Synthesis:** coherent activity-log feature ship — admins carrying the perm set can now delete activity-log records, and the record page reflects the new UI affordances.

#### Worked example 3 — Per-sObject validation service split (with class rename)

§4.1 noted yesterday's new `AccountValidationService` and today's new `ContactValidationService` — paired with the renamed `XMLValidationService → XmlValidationService` (also flagged in §6.1 as a casing rename). **Synthesis:** the team is splitting the validation surface into per-sObject variants (Account-side, Contact-side); today's `Contact` completes a symmetry that started 2 days ago with `Account`. Worth a future-state check: are there callers still routing through the renamed `Xml` service that should be migrated to the new per-sObject services?

### 3.4.3 Fill remaining sections

After §3.4.2 finishes, fill the remaining sections (header / §1 TL;DR (now informed by the synthesis) / §2 Per-phase status / §3 Source-count deltas / §5 Diff context / §6 Suspicion analysis / §7 WIP impact / §8 Warnings / §10 Follow-ups). Use the live data per the table below:

| Section | Data source |
|---|---|
| Header block | `sf org display -o "$ORG_ALIAS"` for Org ID, wall-clock totals from the per-phase tee logs |
| §1 TL;DR | Agent writes 3-6 sentences, **leading with the holistic stories from §4.11 cross-type synthesis** (filled in §3.4.2), supported by what stands out in §3 and §6 |
| §2 Per-phase status | Read each `.retrieve-logs/current/NN-*.log` for status + elapsed time |
| §3 Source-count deltas | Compare current counts (per the "Validating the run" snippet below) against the §3 table of the *previous* file in `changes/git/` |
| §4 Changes by metadata type (§4.1–§4.10) | **Already filled in §3.4.1** (one per-type todo per non-empty type). Do not redo here. |
| §4.11 Cross-type synthesis | **Already filled in §3.4.2** (the synthesis todo). Do not redo here. |
| §5 Diff context | `DIFF_BASE=$(cat .retrieve-logs/current/_pre-head.txt)` then `git diff --stat "$DIFF_BASE"..HEAD \| tail -5` |
| §6 Suspicion analysis | Run the four heuristic sets below |
| §7 WIP impact | Carry over the choice from 0.4 and the outcome from 3.6 |
| §8 Retrieve warnings | `grep -hE "Warning\|Problem" .retrieve-logs/current/*.log` cross-checked against the "Known non-fatal warnings" table |
| §9 Mirror commit reference | Filled in *after* 3.5 — leave `<short-hash>` placeholder until then |
| §10 Open follow-ups | Anything from §6 that needs human review, plus anything the agent noticed |

#### Suspicion-analysis heuristics

Run all four in sequence. Each is a read-only diff inspection — none of them blocks the commit.

```bash
DIFF_BASE=$(cat .retrieve-logs/current/_pre-head.txt)   # pre-commit working-tree comparison
[ -n "$DIFF_BASE" ] || { echo "no PRE_HEAD recorded — cannot compute the diff"; exit 1; }

# 6.1 Possibly-breaking
git diff "$DIFF_BASE" -- 'force-app/main/default/classes/*Test.cls' \
  | grep -E '^-\s+(@isTest|static testMethod void)' || true
git diff "$DIFF_BASE" -- 'force-app/main/default/classes/*.cls' \
  | grep -E '^-(public|private|global) (with|without|inherited) sharing class' || true
git diff "$DIFF_BASE" -- 'force-app/main/default/objects/*/fields/*.field-meta.xml' \
  | grep -E '^[-+]\s*<type>' || true

# 6.2 Security / access drift
git diff --stat "$DIFF_BASE" -- 'force-app/main/default/permissionsets/' \
  'force-app/main/default/profiles/' \
  'force-app/main/default/sharingRules/' \
  'force-app/main/default/roles/' \
  'force-app/main/default/groups/' || true

# 6.3 Active / status flips
git diff "$DIFF_BASE" -- 'force-app/main/default/flows/*.flow-meta.xml' \
  | grep -E '^[-+]\s*<status>' || true
git diff "$DIFF_BASE" -- 'force-app/main/default/omniScripts/*.os-meta.xml' \
  'force-app/main/default/omniIntegrationProcedures/*.oip-meta.xml' \
  | grep -E '^[-+]\s*<IsActive>' || true
git diff "$DIFF_BASE" -- 'force-app/main/default/objects/*/validationRules/*.validationRule-meta.xml' \
  | grep -E '^[-+]\s*<active>' || true

# 6.4 Structural overhauls
git diff --diff-filter=D --name-only "$DIFF_BASE" -- 'force-app/main/default/classes/*.cls' || true
git status --short -- 'force-app/main/default/objects/' \
  | grep -E '^\?\?\s.*objects/[^/]+/$' || true
git diff --stat "$DIFF_BASE" -- 'force-app/main/default/lwc/*/*.js-meta.xml' || true
# >50% line churn for IPs / OmniScripts — compare diff lines to wc -l:
for f in $(git diff --name-only "$DIFF_BASE" -- \
    'force-app/main/default/omniIntegrationProcedures/*.oip-meta.xml' \
    'force-app/main/default/omniScripts/*.os-meta.xml'); do
  churn=$(git diff --numstat "$DIFF_BASE" -- "$f" | awk '{print $1+$2}')
  size=$(wc -l < "$f" 2>/dev/null || echo 0)
  if [ -n "$churn" ] && [ "$size" -gt 0 ]; then
    pct=$((churn * 100 / size))
    [ "$pct" -gt 50 ] && echo "STRUCTURAL: $f ($pct% churn, $churn/$size lines)"
  fi
done
```

Pipe each into a scratch file and reference the relevant entries inside §6.x of the doc.

### 3.4.B Adversarial Gate B — review the finished audit

Run after §3.4.3 fills the remaining sections, and before the commits in §3.5. **This is the only adversarial gate a retrieve run has.**

There is deliberately no plan-stage gate. A retrieve is read-only against the org, and the run plan is mechanically derived by `make-order-files.sh` from the measured footprint — so at plan time there is no design to critique, only arithmetic the generator already enforces. Nothing gets deployed either, so this gate is not approval to change anything. What it approves is a **record**, and a mirror audit that misses something is worse than no audit: it looks like diligence while hiding the thing that later breaks.

**This gate runs two critics.** A retrieve changes no components, so there is nothing to review for minimality.

Build the evidence pack: `PRE_HEAD` from `.retrieve-logs/current/_pre-head.txt` as the diff base, the per-type churn table, `_progress.tsv`, the Phase 2.5 residue files, and the `.retrieve-logs/current/` log set. Then launch both critics in one parallel fan-out:

1. **Did the doc record what actually happened, completely and accurately?** Anything present in the diff that the doc does not mention — a changed component with no note, a deletion, a structural rewrite, a new file. And the inverse: any claim the evidence does not support, such as a type reported `Succeeded` with no files being counted as covered, an enumerated-empty type recorded as covered, a skipped Phase 2.5 sweep, or dated carry-forward presented as current.
2. **Was the diff actually read?** Notes that restate a filename instead of naming the behaviour that changed and the risk it carries — a sharing-keyword flip, a field type change, an active-flag flip, a new field-permission grant. Plus a misread diff, a version-pair reported as bulk added lines, or a structural overhaul reduced to a line count. Connections the analysis should have linked across types belong here too.

**Org-wide coverage is out of scope for this gate.** "You should also have retrieved type X" is not a finding: we do not own the whole org, and what the run chose to pull is the operator's decision. Attack what the document *claims*, never what the run deliberately and datedly left alone.

Verify each finding against the actual diff and logs before acting on it, rebut rather than silently dropping, and escalate to the user after three unresolved rounds. Record critic IDs, the revision reviewed, verdicts, dispositions, and round counts in audit-doc §6.6. Critical and High findings block the commits until fixed or rejected with evidence; a failed or timed-out critic does not count.

### 3.5 Two-commit pattern

#### Commit 1 — the mirror snapshot

```bash
# Stage everything the retrieve touched, excluding the brand-new audit doc.
# Don't stage .retrieve-logs/ — it stays gitignored (raw output is noisy;
# the audit doc §8 carries the warning content inline).
git add force-app/ manifest/ config/  # adjust to what the retrieve touched
git reset -- changes/git/  # ensure the audit doc itself is NOT in this commit
git status -s

git commit -m "$(cat <<'EOF'
mirror(<sandbox-alias>): sync from <sandbox-alias> @ YYYY-MM-DD HH:MM

Org-wide metadata retrieve via the phase plan in docs/org-mirror/README.md.
Triggered by: <user>. Wall-clock: ~XX min. All phases Succeeded / Partial (see audit doc).

Source counts after retrieve:
  ApexClass: NNN  ApexTrigger: NN  LWC: NNN  OmniScript: NNN
  OmniIntegrationProcedure: N,NNN  OmniDataTransform: N,NNN
  CustomObject: NNN folders  CustomField: N,NNN

See accompanying audit doc (next commit) for full breakdown.
EOF
)"

MIRROR_SHORT=$(git log -1 --format='%h')
MIRROR_FULL=$(git log -1 --format='%H')
echo "Mirror commit: $MIRROR_SHORT"
```

If the user chose **continue** in 3.1 (WIP not stashed), use selective `git add` paths instead of `git add force-app/` — for example `git add $(git diff --name-only HEAD -- force-app/ | grep -v <wip-files>)`.

#### Embed the hash, then commit the doc

Open the audit doc and replace `<short-hash>` placeholders in the header block and §9 with `$MIRROR_SHORT`. The §9 table also needs `$MIRROR_FULL`, the commit subject, and the file-changed counts — pull those with:

```bash
git log -1 --format='%H%n%h%n%s%n%an%n%ad' --date=iso-local "$MIRROR_FULL"
git show --stat "$MIRROR_FULL" | tail -1
```

#### Commit 2 — the audit doc

```bash
# Re-read the path and the mirror hash from disk/git rather than trusting variables
# set many steps earlier. An empty $DOC would make `git add` stage nothing while
# exiting 0, producing an empty commit attempt instead of an obvious failure.
DOC=$(cat .retrieve-logs/current/_doc-path.txt)
[ -f "$DOC" ] || { echo "ABORT: audit doc path '$DOC' does not exist"; exit 1; }
MIRROR_SHORT=${MIRROR_SHORT:-$(git log -1 --format='%h')}

git add "$DOC"
git status -s   # should show only this one file

git commit -m "$(cat <<EOF
docs(retrieve): audit <sandbox-alias> mirror @ YYYY-MM-DD HH:MM (refs ${MIRROR_SHORT})

Snapshot record of the org-wide retrieve described in
docs/org-mirror/README.md. References mirror commit ${MIRROR_SHORT}.

Saved at: ${DOC}
Wall-clock: ~XX min.  Phases: <M> of <N planned> (see doc §2).
Notable: <one-line carried over from doc TL;DR>
EOF
)"

DOC_SHORT=$(git log -1 --format='%h')
echo "Audit-doc commit: $DOC_SHORT"
echo "Mirror commit:    $MIRROR_SHORT"
```

#### Verify clean tree

```bash
git log -2 --format='%H%n  %h  %s%n'
git status -s
```

Report both hashes back to the user.

### 3.6 Pop WIP (if stashed in 0.4)

```bash
if git stash list | grep -q "pre-retrieve-"; then
  git stash pop
  # If conflicts surface, list them:
  git status --short | grep '^UU' || echo "Pop clean."
fi
```

Update §7 of the audit doc with the pop result (clean / conflict list). If conflicts appeared, this is a `git commit --amend` to the doc commit only — not a new commit.

---

## Cap fallback — when a single type exceeds the limit

**Document the fallback for your cap-exposed types before you need it.** Discovering it mid-incident, with a half-finished mirror on disk and the lock still held, is how a run turns into an afternoon.

Two symptoms mean a single type has outgrown one call: an explicit limit error, or a `Succeeded` status with a truncated result — which is why the file floor exists, since only the floor catches the second one.

The fix is always the same shape: **split the type by a natural parent axis** into two or more enumerated calls, each comfortably under the cap. For a child type, shard by parent object; for a bundle type, shard by name prefix or by an explicit member list.

```bash
# Child type sharded by parent — batch a handful of parents per call.
sf project retrieve start \
  --metadata '<ChildType>:<ParentA>.*' \
  --metadata '<ChildType>:<ParentB>.*' \
  -o "$ORG_ALIAS" --ignore-conflicts --wait <minutes>

# Find the heaviest parents to decide the batches.
find force-app/main/default/objects -name '*.field-meta.xml' \
  | awk -F/ '{print $5}' | sort | uniq -c | sort -rn | head -30
```

Run the shards through `run-phase.sh` like any other phase, each with its own floor, so the gates still apply. Add the shard rows to the order file rather than running them by hand — an unlogged phase leaves no ledger entry and Gate B cannot see it.

Enumerated shard manifests name your org's real components, so they are **project-only**: keep them in the generated log dir or your own repo, and never ship them in a shared bootstrap kit.

---

## Validating the run

After every planned call finishes, check for failures:

```bash
echo "=== Failures (none expected) ==="
# -a is mandatory: retrieve logs contain NUL bytes, so plain grep reports
# "Binary file matches" instead of the line and the check silently under-reports.
grep -al "Status: Failed" .retrieve-logs/current/*.log 2>/dev/null || echo "None"

echo "=== Real errors ==="
grep -ahE "(LIMIT_EXCEEDED|MalformedQueryException|FATAL|too large)" \
  .retrieve-logs/current/*.log 2>/dev/null || echo "(none)"
```

Then snapshot final source counts (compare against the previous run to spot what changed in the org):

```bash
echo "=== Final source counts ==="
echo "ApexClass:"                $(ls force-app/main/default/classes/*.cls 2>/dev/null | wc -l)
echo "ApexTrigger:"              $(ls force-app/main/default/triggers/*.trigger 2>/dev/null | wc -l)
echo "LWC bundles:"              $(ls -d force-app/main/default/lwc/*/ 2>/dev/null | wc -l)
echo "Aura bundles:"             $(ls -d force-app/main/default/aura/*/ 2>/dev/null | wc -l)
echo "OmniScript:"               $(ls force-app/main/default/omniScripts/*.os-meta.xml 2>/dev/null | wc -l)
echo "OmniIntegrationProcedure:" $(ls force-app/main/default/omniIntegrationProcedures/*.oip-meta.xml 2>/dev/null | wc -l)
echo "OmniDataTransform (DRs):"  $(ls force-app/main/default/omniDataTransforms/*.rpt-meta.xml 2>/dev/null | wc -l)
echo "Layout:"                   $(ls force-app/main/default/layouts/*.layout-meta.xml 2>/dev/null | wc -l)
echo "FlexiPage:"                $(ls force-app/main/default/flexipages/*.flexipage-meta.xml 2>/dev/null | wc -l)
echo "Flow:"                     $(ls force-app/main/default/flows/*.flow-meta.xml 2>/dev/null | wc -l)
echo "Profile:"                  $(ls force-app/main/default/profiles/*.profile-meta.xml 2>/dev/null | wc -l)
echo "PermissionSet:"            $(ls force-app/main/default/permissionsets/*.permissionset-meta.xml 2>/dev/null | wc -l)
echo "CustomObject folders:"     $(ls -d force-app/main/default/objects/*/ 2>/dev/null | wc -l)
echo "CustomField:"              $(find force-app/main/default/objects -name '*.field-meta.xml' 2>/dev/null | wc -l)
echo "ExternalCredential:"        $(ls force-app/main/default/externalCredentials/*.externalCredential-meta.xml 2>/dev/null | wc -l)
echo "ExternalClientApplication:" $(ls force-app/main/default/externalClientApps/*.eca-meta.xml 2>/dev/null | wc -l)
echo "ApexEmailNotifications:"    $(ls force-app/main/default/apexEmailNotifications/*.notifications-meta.xml 2>/dev/null | wc -l)
```

---

## Known non-fatal warnings (do **not** re-run for these)

These appear as `Warnings` rows in the retrieve output. They're metadata API edge cases, not bugs in your retrieve, and don't affect the files that did come down.

| Warning fragment | Cause | Action |
|---|---|---|
| `Retrieve not allowed on channel ActivityEngagementVirtualChannel` | Salesforce internal channel that can't be retrieved unpackaged | Ignore |
| `Metadata API received improper input. … Load of metadata from db failed for … ConnectedApp … CPQIntegrationUserApp / Salesforce_CLI` | System ConnectedApps marked as packaged-only | Ignore |
| `Entity type 'LiveChatAgentConfig' / 'LiveChatButton' / 'LiveChatDeployment' is not available in this organization` | Live Agent not licensed in this org | Ignore |
| `A SiteDotCom site using template [Build Your Own (LWR)] does not support MD API Retrieval` | LWR sites are managed via Experience Cloud Build tools, not MD API | Ignore |
| `Entity of type 'CustomMetadata' named '<YourCMDT>.…' cannot be found` | Stale references in the master `fullpackage.xml` to CMDT entries that were deleted in the org | Ignore (or clean the manifest) |
| `Entity of type 'ListView' named '…' cannot be found` (~100 of these) | Installed-package objects whose stock list views aren't actually customized in the org | Ignore |
| `Can't retrieve non-customizable CustomObject named: DecisionTblFileImportData` | System object — by design not retrievable | Ignore |
| `Unable to retrieve file for id 0qhOv… of type OmniScript. Retrieving OmniProcessElement found more than 1000` | Vlocity OmniScript with >1000 child elements; known platform limit | Ignore — open the affected OmniScripts in OmniStudio Designer if you need them |
| `Metadata API received improper input. … Load of metadata from db failed for metadata of type:OmniScript and file name:<YourType>_<YourSubType>_English_<N>` | OmniScript with a name that breaks the metadata file naming rules (often happens to OmniScripts whose subType contains characters the MD API can't round-trip) | Ignore |
| `You do not have the proper permissions to access Layout.` (×2) | Managed-package layouts the running user can't see | Ignore (or run as a higher-privilege user) |
| `Entity of type 'QuickAction' named '<sObject>.<QuickActionApiName>' cannot be found` | Stale manifest reference (the QuickAction was deleted from the org but still listed in your `manifest/fullpackage.xml`) | Ignore (or clean the manifest) |

> **Exceeding `--wait` is not a failure, and re-running is harmful.** `--wait` bounds how long the CLI polls, nothing more — when it lapses the CLI hands back your terminal while **the retrieve keeps running server-side**. Starting the same type again puts two retrieves in flight against one working tree, which is the `.git/index` corruption that Hard lesson 1 warns about. Resume instead:
>
> ```bash
> sf project retrieve resume --use-most-recent -o "$ORG_ALIAS"
> ```

Only `LIMIT_EXCEEDED`, `MalformedQueryException`, `FATAL`, `too large`, or an explicit `Status: Failed` are real failures. For those, re-run that single type:

```bash
sf project retrieve start --metadata <Type> -o "$ORG_ALIAS" --ignore-conflicts --wait 240 \
  2>&1 | tee .retrieve-logs/current/<NN>-<type>-retry.log | grep -E "Status: (Succeeded|Failed)"
```

If it still fails on size, fall back to the per-parent sharding pattern in [Cap fallback](#cap-fallback--when-a-single-type-exceeds-the-limit).

---

## Tier B types and one-off pulls

The types a normal run leaves alone are listed in [Retrieve tiers](#retrieve-tiers--mirror-what-moves-not-everything). They are not "skipped" in the sense of forgotten — they are **carry-forward, dated in the audit doc**.

When a ticket genuinely needs one, pull it as a one-off outside the phase plan:

```bash
sf project retrieve start --metadata <TierBType> -o "$ORG_ALIAS" --ignore-conflicts --wait <minutes>
```

Then update that type's carry-forward date in the audit doc, otherwise the next run will still report the old one.

---

## How long it takes

There is no useful universal estimate. Total wall-clock is a product of your org's component count, its current load, and how many calls your shard plan needs — and it swings several-fold on the same org between a quiet morning and a business-hours window with batch jobs running.

Get your number the only way that works: read §2 of the most recent audit doc in `changes/git/`. That is your org's real baseline, measured on your org. The first mirror into an empty repo runs substantially longer than reruns because every component is `Created` rather than `Changed`.

The runbook is **background-friendly** — start it and keep working. It writes Status to the terminal in real time and full output to `.retrieve-logs/current/` (with the previous run rotated to `.retrieve-logs/archive/<TS>/` during pre-flight).

---

## Pre-flight WIP handling

The default flow lives in [Phase 0.4](#04-wip-check-interactive--capture-pre_head) (stash + pop / continue / abort). Two additional patterns for cases the default doesn't cover:

**Commit WIP to a temporary branch first** — best when you want to diff your edits against org state afterwards:

```bash
git checkout -b pre-retrieve-$(date +%F)
git add -A && git commit -m "WIP before full retrieve"
git checkout -    # back to your working branch
# ... run retrieve ...
# use: git diff pre-retrieve-<date> -- <path>  to see what got overwritten
```

**Accept overwrite** — fine if your WIP is committed locally on a feature branch you can recover from `git reflog`. Pick the **continue** option in Phase 0.4, then use selective `git add` paths during Phase 3.5 so your WIP files don't end up in the mirror commit.

To audit afterwards (works for any of the three approaches):

```bash
git status --short | wc -l                          # total churn
git diff HEAD --stat | tail -20                     # breakdown
git log --oneline HEAD@{1}..HEAD 2>/dev/null        # any commits during retrieve
```

---

## Adapting this runbook to a different org

1. **Set your `ORG_ALIAS` env var** in the new shell (see [Setup](#setup--set-your-org-alias-once)). All commands in this runbook will then work as-is — no editing needed.
   ```bash
   export ORG_ALIAS=YourAliasHere
   echo "$ORG_ALIAS"     # confirm it printed what you expected
   ```
2. **Run Phase 0.3 discovery — always.** This is the step that adapts the runbook to the new org, and Phase 0.1 pins the new org's Id so the guards protect you there too. Nothing else needs editing: the scripts read the alias from the environment and the Org Id from the log dir.
3. **Regenerate the order files** with `make-order-files.sh`. Never reuse another org's order file — its floors are that org's volumes and will misfire on an org of a different shape, either failing every healthy phase or passing a materially short one.
4. **Re-shard heavy types if the footprint demands it.** A type near the file cap needs the per-parent pattern in [Cap fallback](#cap-fallback--when-a-single-type-exceeds-the-limit).
5. **Expect the first run to be slower** than reruns — every component is `Created` rather than `Changed`.
6. **Add `.retrieve-logs/` to `.gitignore`** in the new repo.
7. **Don't run two retrieves to the same org concurrently** — they serialize on the org side and frequently fail with timeouts.
8. **Open a fresh shell per org** (or re-export `ORG_ALIAS`) — the env var doesn't follow you across terminals.

Org-measured artifacts stay with the project, never with the kit. Sharded manifests that enumerate real object API names (the `CustomField:<Object>.*` variety) are generated per-org by the fallback pattern below — they are not part of the shared bootstrap kit, because they would carry one org's entire object inventory into every other project.

---

## Related references

- `.cursor/rules/sf-cli-commands.mdc` — canonical `sf` CLI reference (every flag, every command).
- `.cursor/rules/apex-development.mdc` — Apex deploy + test workflow (the inverse direction).
- `.cursor/rules/adversarial-review.mdc` — the review protocol this runbook invokes. A retrieve run is `change_kind: retrieve_mirror`, which is **Gate B only**.
- `docs/org-mirror/make-order-files.sh` — generates this run's order files and manifests from the footprint.
- `docs/org-mirror/run-phase.sh` / `run-all.sh` — the gated executors.
- `changes/git/` — previous audit docs; the most recent one is your org's real baseline for counts and timings.

---

## Quick checklist (TL;DR)

```text
[ ]  Phase 0.0 — Spawn the explicit TodoWrite plan FIRST (mandatory; see §0.0). Long-running, resumable on failure.
[ ]  cd to the repo root                   → every script path is relative to it
[ ]  command -v sf jq python3 bash         → all four required; generator needs python3
[ ]  export ORG_ALIAS=<your-alias>         → set once at top of shell
[ ]  echo "$ORG_ALIAS"                     → confirm it printed (empty = silently hits your DEFAULT org)
[ ]  Phase 0.1 — sf org list --all         → confirm Connected; read back alias/Id/username
[ ]  Phase 0.2 — rotate .retrieve-logs/current/ → archive/<TS>/; seed current/; write _org-id.txt
[ ]  Phase 0.3 — FOOTPRINT DISCOVERY       → supported types, live counts (null-tolerant!), gap lists, Omni flavour
[ ]              sanity-check every zero    → genuinely empty vs filtered vs folder-type vs failed call
[ ]  Phase 0.4 — WIP check (interactive)   → stash+pop / continue / abort;  capture PRE_HEAD to a file
[ ]  Phase 0.5 — write _exclusions.tsv (reason per line), then make-order-files.sh
[ ]              read _plan-notes.txt       → confirm ordering + floors before running anything
[ ]  Phase 1 — run-all.sh order-phase1.tsv → bundled shards, stops at first gate failure
[ ]  Phase 2 — run-all.sh order-phase2.tsv → solo heavy types, lightest → heaviest
                 parent before child;  cap-exposed type first;  FLS-heavy type last
                 container-repair phase after the last child of each container
                 Omni: only on standard runtime — never on a managed-package org
[ ]  Phase 2.5 — deletion-detection sweep  → org fullNames vs on-disk names, per Tier A type
[ ]  grep -al "Status: Failed" .retrieve-logs/current/*.log   → expect "None"  (-a: logs contain NULs)
[ ]  Phase 3.4   — generate audit doc      → cp template → changes/git/retrieve-<date>-<time>-<alias>.md
[ ]  Phase 3.4.1 — per-type analysis       → one todo per type that ACTUALLY changed
[ ]  Phase 3.4.2 — cross-type synthesis    → §4.11
[ ]  Phase 3.4.3 — fill §1-§10             → YOUR counts and timings; Tier B carry-forward DATED
[ ]  Phase 3.4.B — adversarial Gate B      → the ONLY gate. 2 parallel critics:
                 doc records what happened / was the diff actually read
                 org-wide coverage is OUT of scope — attack the claim, not the omission
[ ]  Phase 3.5 — commit 1 (mirror)         → explicit git add paths; commit; capture $MIRROR_SHORT
[ ]  Phase 3.5 — embed hash in doc         → replace <short-hash> in header + §9
[ ]  Phase 3.5 — commit 2 (audit doc)      → git add changes/git/<file>; commit referencing $MIRROR_SHORT
[ ]  Phase 3.6 — pop WIP if stashed        → git stash pop; report conflicts (if any) in doc §7
[ ]  Report both commit hashes back to the user
```
