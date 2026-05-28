# Sequential Org-Wide Metadata Retrieve — Runbook

A repeatable, hybrid-shard strategy for pulling **the entire metadata footprint** of a Salesforce org into local source while staying under the Metadata API limits and surviving slow orgs.

> **Why this doc exists:** A naive `sf project retrieve start --metadata '*'` (or even a single 127-type manifest) blows past the **10,000-component limit** on any non-trivial org and locks up for hours when the org is slow. The {{ORG_NAME}} sandbox has ~14k+ components in `force-app/`, so we split the retrieve into ~23 sequential calls plus a Phase 3 audit + 2 commits, sized so each call fits under the limit and finishes in a bounded time.

This runbook is **org-agnostic** — every command uses a `$ORG_ALIAS` shell variable so you can copy-paste them as-is in any project. **Set it once at the start of your session** (see the [Setup](#setup-set-your-org-alias-once) section below).

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

2. **An SFDX project rooted at the repo.** `sfdx-project.json` should point at `force-app` (or your equivalent package dir) and use the same API version your org supports (this repo uses `66.0`).

3. **Pre-sharded manifest files at `manifest/fullpackage/`.** This repo ships 11 shards covering all 127 metadata types listed in `manifest/fullpackage.xml`. The runbook below uses 6 of them as bundled shards and treats the other 5 as per-type pulls. If your repo does not have these shards, copy them from this repo first or build your own.

4. **A clean spot to capture logs.** The runbook writes the active run's per-phase logs to `.retrieve-logs/current/` and rotates previous runs to `.retrieve-logs/archive/<TS>/`. Both subdirs are covered by the single `.retrieve-logs/` gitignore entry.

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

**Alternative (no env var):** Set the org as your global default once and drop the `-o "$ORG_ALIAS"` flag from every command:

```bash
sf config set target-org=YourAlias --global
```

The runbook below uses the env-var form because it's safer when you work across multiple orgs in the same shell session.

---

## The strategy in one paragraph

We split the org's 127 metadata types into two passes:

- **Phase 1 — small bundled shards.** 11 calls, each pulling a logical group of low-volume admin / config types (NamedCredential, RemoteSiteSetting, PermissionSet, Workflow, modern-auth types, etc.). Either the existing `manifest/fullpackage/*.xml` or a single `--metadata <Type1> --metadata <Type2> …` invocation. Each shard is sized so total component count stays comfortably under 10k.

- **Phase 2 — heavy types one at a time.** 12 calls, one per high-volume type (`AuraDefinitionBundle`, `Flow`, `FlexiPage`, `LightningComponentBundle`, `Layout`, `ApexClass`, `CustomObject`, `CustomField`, `OmniScript`, `OmniIntegrationProcedure`, `OmniDataTransform`, `Profile`). These are the types that, by themselves, can approach or exceed the 10k limit on a mature org.

We run **strictly sequentially** — one retrieve in flight at a time. Slow orgs penalise concurrency badly; back-to-back parallel retrieves end up taking longer than serial ones because the org throttles. We also order Phase 2 **lightest-first** so any fatal errors surface in the first 5 minutes rather than after 20.

Skip noisy / non-code types (Translations, Reports, Dashboards, EmailTemplates, Documents, StaticResources, Letterhead, ContentAsset, Prompt) by default — they're large, change rarely in a code workflow, and rarely matter for development.

---

## Sizing rationale (why the heavy types are split out)

Local component counts on this repo as of the last full mirror:

| Type | Count | Notes |
|---|---:|---|
| `CustomField` | ~8,900 | Closest to the 10k limit — must be solo |
| `OmniDataTransform` | ~1,710 | DataRaptors. **Files use `.rpt-meta.xml`** — easy to miss when sizing by glob |
| `OmniIntegrationProcedure` | ~1,670 | Heaviest IP — wall-clock king |
| `OmniScript` | ~765 | Slow due to per-script element traversal |
| `CustomObject` | ~670 folders | Must precede CustomField |
| `ApexClass` | ~683 | |
| `Layout` | ~495 | |
| `LightningComponentBundle` | ~304 | |
| `FlexiPage` | ~108 | |
| `Flow` | ~52 | |
| `Profile` | ~29 | Tiny count but FLS-heavy → slow per record |
| `AuraDefinitionBundle` | ~12 | |

> **Sizing trap (caught the hard way):** When sizing OmniStudio types by globbing local files, **DataRaptors use `.rpt-meta.xml`, not `.odt-meta.xml`**. If you glob the wrong extension you get 0 and bundle them into a small-types call where they silently fail to retrieve. Always cross-check against `manifest/fullpackage.xml` for the canonical list of types and their counts via `find force-app/main/default/<folder> -type f`.

Anything bundled with one of these would push the call past 10k or extend its runtime past sane timeouts.

`CustomObject` **must run before** `CustomField` so that the `force-app/main/default/objects/<Object>/` folder exists when the field-meta files arrive.

---

## Phase 0 — pre-flight (1 read-only check)

### 0.0 Spawn the explicit plan FIRST (mandatory)

**Before running any `sf` command, before any retrieve writes to disk, the agent MUST spawn an explicit `TodoWrite` plan covering the entire end-to-end sequence.** A full retrieve is a long-running multi-stage operation (~20–45 min wall-clock across ~23 SF MDAPI calls plus an audit doc and two git commits), and any single phase can stall, hit a transient org error, or get interrupted. A plan up front makes the run **resumable** — if Phase 2.17 fails, the agent can re-read its todo list and know exactly which phases still need to run, which already-succeeded phases can be skipped, and where in the audit/commit workflow it left off.

Minimum required todo entries (one per concrete step — agent may add more, but must not collapse any of these into a single sweep):

```
[ ] Phase 0 — pre-flight (org auth + WIP check + HEAD capture + .retrieve-logs/ rotation)
[ ] Phase 1.1  → 1.11   (11 bundled / small-type retrieves, sequential)
[ ] Phase 2.11 → 2.22   (12 single-type heavy retrieves, sequential lightest→heaviest)
[ ] Phase 3.4.1 — per-type analysis todos (one TodoWrite entry per type that changed; spawned later, after Phase 2 completes)
[ ] Phase 3.4.2 — cross-type synthesis todo
[ ] Phase 3.4.3 — fill remaining audit-doc sections (header, §1, §2, §3, §5, §6, §7, §8, §10)
[ ] Phase 3.5 — Commit 1: mirror snapshot (force-app/ + manifest/ + config/, doc held back)
[ ] Phase 3.5 — Embed mirror hash in audit doc §9
[ ] Phase 3.5 — Commit 2: audit doc only
[ ] Phase 3.6 — pop WIP (only if stashed in 3.1) + verify clean tree
```

Mark each as `in_progress` before starting it and `completed` only after it actually finishes successfully (per `Status: Succeeded` in the log for retrieves, per the `git log -1` hash for commits). Do NOT batch-complete todos retroactively — losing the running-todo signal makes a mid-sequence failure ambiguous about what was actually finished.

If the run was interrupted (org timeout, user `Ctrl-C`, agent crash, transient `sf` hang, sandbox restart), the FIRST thing the resuming agent does is read the todo list and identify the most recent `in_progress` entry — that's where work resumes. Don't restart from Phase 1.1 unless the resume-point todo logic is unrecoverably ambiguous.

### 0.1 Org authentication check

```bash
sf org list --all
```

Confirm the target org is `Connected`. Abort and re-auth if expired.

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
```

> **Tip:** Add `.retrieve-logs/` to `.gitignore` if it isn't already. The single umbrella entry covers both the active subdir (`.retrieve-logs/current/`) and every archived prior run (`.retrieve-logs/archive/<TS>/`).

---

## Phase 1 — small / medium bundled shards (11 calls)

Run **strictly in order**, lightest first. Each call writes its full output to a numbered log so you can audit afterwards.

> **All commands use `$ORG_ALIAS`** — make sure you exported it in the [Setup](#setup-set-your-org-alias-once) section above. Run `echo "$ORG_ALIAS"` to confirm before starting.

### 1.1 Integration shard — 17 admin types

Pulls NamedCredential, RemoteSiteSetting, ConnectedApp, Certificate, AuthProvider, etc.

```bash
sf project retrieve start \
  --manifest manifest/fullpackage/fullpackage-integration.xml \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/01-integration.log | grep -E "Status: (Succeeded|Failed)"
```

Expected wall-clock: **~30s – 8 min** (varies wildly by org load).

### 1.2 Community shard — 15 community/site types

```bash
sf project retrieve start \
  --manifest manifest/fullpackage/fullpackage-community.xml \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/02-community.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~20s – 2 min**.

### 1.3 Content (filtered) — only 3 useful types

We deliberately skip `Document`, `DocumentFolder`, `EmailTemplate`, `EmailFolder`, `Letterhead`. They're large and rarely interesting for code development.

```bash
sf project retrieve start \
  --metadata PostTemplate \
  --metadata ManagedContentType \
  --metadata ActionLinkGroupTemplate \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/03-content-filtered.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~15s – 6 min**.

### 1.4 Translations (filtered) — `CustomObjectTranslation` only

We deliberately skip `Translations` (the user-facing language pack). `CustomObjectTranslation` is what carries field-level translation overrides we sometimes want.

```bash
sf project retrieve start \
  --metadata CustomObjectTranslation \
  -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/04-translations-filtered.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~4 – 12 min** (this is one of the slowest single-type retrieves).

### 1.5 OmniStudio small types — only the lightweight ones

OmniUiCard, OmniInteractionConfig, OmniInteractionAccessConfig.

`OmniScript`, `OmniIntegrationProcedure`, and `OmniDataTransform` (DataRaptors) are **deliberately excluded** here — they're heavy and each gets its own Phase 2 call.

```bash
sf project retrieve start \
  --metadata OmniUiCard \
  --metadata OmniInteractionConfig \
  --metadata OmniInteractionAccessConfig \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/05-omnistudio-small.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~20s – 4 min**.

### 1.6 Code small types

ApexComponent / ApexPage / ApexTestSuite / ApexTrigger / LightningMessageChannel.

```bash
sf project retrieve start \
  --metadata ApexComponent \
  --metadata ApexPage \
  --metadata ApexTestSuite \
  --metadata ApexTrigger \
  --metadata LightningMessageChannel \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/06-code-small.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~15s – 2 min**.

### 1.7 Schema small types — everything in `fullpackage-schema.xml` except CustomObject and CustomField

```bash
sf project retrieve start \
  --metadata RecordType \
  --metadata BusinessProcess \
  --metadata CompactLayout \
  --metadata FieldSet \
  --metadata ListView \
  --metadata ValidationRule \
  --metadata WebLink \
  --metadata CustomMetadata \
  --metadata CustomLabels \
  --metadata GlobalValueSet \
  --metadata GlobalValueSetTranslation \
  --metadata StandardValueSet \
  --metadata StandardValueSetTranslation \
  --metadata TopicsForObjects \
  --metadata DuplicateRule \
  --metadata MatchingRules \
  --metadata CleanDataService \
  -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/07-schema-small.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~40s – 3 min**.

### 1.8 UI small types — everything in `fullpackage-ui.xml` except Layout, FlexiPage, Prompt

```bash
sf project retrieve start \
  --metadata QuickAction \
  --metadata PathAssistant \
  --metadata CustomApplication \
  --metadata CustomApplicationComponent \
  --metadata CustomTab \
  --metadata CustomPageWebLink \
  --metadata HomePageComponent \
  --metadata HomePageLayout \
  --metadata NavigationMenu \
  --metadata AppMenu \
  --metadata LightningBolt \
  --metadata LightningExperienceTheme \
  --metadata LightningOnboardingConfig \
  --metadata BrandingSet \
  --metadata RecordActionDeployment \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/08-ui-small.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~40s – 90s**.

### 1.9 Automation small types — everything in `fullpackage-automation.xml` except Flow

```bash
sf project retrieve start \
  --metadata FlowDefinition \
  --metadata FlowCategory \
  --metadata Workflow \
  --metadata WorkflowAlert \
  --metadata WorkflowFieldUpdate \
  --metadata WorkflowRule \
  --metadata WorkflowTask \
  --metadata ApprovalProcess \
  --metadata AssignmentRules \
  --metadata AutoResponseRules \
  --metadata EscalationRules \
  --metadata MilestoneType \
  --metadata NotificationTypeConfig \
  --metadata CustomNotificationType \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/09-automation-small.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~15s – 90s**.

### 1.10 Security small types — everything in `fullpackage-security.xml` except Profile

```bash
sf project retrieve start \
  --metadata PermissionSet \
  --metadata PermissionSetGroup \
  --metadata MutingPermissionSet \
  --metadata CustomPermission \
  --metadata Role \
  --metadata Group \
  --metadata Queue \
  --metadata SharingCriteriaRule \
  --metadata SharingOwnerRule \
  --metadata SharingRules \
  --metadata SharingSet \
  --metadata UserCriteria \
  --metadata DelegateGroup \
  --metadata Skill \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/10-security-small.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~30s – 90s**.

### 1.11 Modern auth + Apex notifications — 3 types not in `manifest/fullpackage.xml`

These three types are silently absent from the master manifest but matter:

- `ExternalCredential` — the modern auth attached to `NamedCredential`. Salesforce is migrating username/password and OAuth flows here, away from the older fields inside the NamedCredential itself.
- `ExternalClientApplication` — Salesforce's official replacement for `ConnectedApp`. New OAuth integrations should land here.
- `ApexEmailNotifications` — routes uncaught Apex exceptions to a list of recipients. Drift here means production errors silently stop alerting whoever should hear about them.

```bash
sf project retrieve start \
  --metadata ExternalCredential \
  --metadata ExternalClientApplication \
  --metadata ApexEmailNotifications \
  -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/11-modern-auth-apex.log | grep -E "Status: (Succeeded|Failed)"
```

Expected: **~10s – 30s**.

> **Why these and not other gaps?** A full audit (`sf org list metadata-types -o $ORG_ALIAS`) shows the org reports **284** metadata types vs the 127 in `manifest/fullpackage.xml`. Most of the delta is licensed-but-unused industry features (Field Service, CRM Analytics, classic Communities, Health Cloud `Care*`). The three above are the only **active, customised, infrastructure-critical** types that aren't already covered. Other "missing" types in this org (ExperienceBundle for the LWR site, ModerationRule, NetworkBranding, WaveAnalyticAssetCollection, EmailServicesFunction, EntitlementProcess, BusinessProcessTypeDefinition, IdentityVerificationProcDef) are owned by other teams or do not affect the credentialing code paths — intentionally not tracked here.

---

## Phase 2 — heavy types, strictly one type per call (12 calls)

Order is **lightest → heaviest** so failures surface early.

```bash
# 2.11 — AuraDefinitionBundle (~12 bundles)
sf project retrieve start --metadata AuraDefinitionBundle -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/11-aura.log | grep -E "Status: (Succeeded|Failed)"

# 2.12 — Flow (~50)
sf project retrieve start --metadata Flow -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/12-flow.log | grep -E "Status: (Succeeded|Failed)"

# 2.13 — FlexiPage (~108)
sf project retrieve start --metadata FlexiPage -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/13-flexipage.log | grep -E "Status: (Succeeded|Failed)"

# 2.14 — LightningComponentBundle (~300)
sf project retrieve start --metadata LightningComponentBundle -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/14-lwc.log | grep -E "Status: (Succeeded|Failed)"

# 2.15 — Layout (~495)
sf project retrieve start --metadata Layout -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/15-layout.log | grep -E "Status: (Succeeded|Failed)"

# 2.16 — ApexClass (~680)
sf project retrieve start --metadata ApexClass -o "$ORG_ALIAS" --wait 60 \
  2>&1 | tee .retrieve-logs/current/16-apexclass.log | grep -E "Status: (Succeeded|Failed)"

# 2.17 — CustomObject (~670 folders) — MUST precede CustomField
sf project retrieve start --metadata CustomObject -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/17-customobject.log | grep -E "Status: (Succeeded|Failed)"

# 2.18 — CustomField (~8,900) — closest to 10k limit
sf project retrieve start --metadata CustomField -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/18-customfield.log | grep -E "Status: (Succeeded|Failed)"

# 2.19 — OmniScript (~765)
sf project retrieve start --metadata OmniScript -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/19-omniscript.log | grep -E "Status: (Succeeded|Failed)"

# 2.20 — OmniIntegrationProcedure (~1,670) — second heaviest
sf project retrieve start --metadata OmniIntegrationProcedure -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/20-omniip.log | grep -E "Status: (Succeeded|Failed)"

# 2.21 — OmniDataTransform / DataRaptors (~1,710) — heaviest single retrieve
sf project retrieve start --metadata OmniDataTransform -o "$ORG_ALIAS" --wait 180 \
  2>&1 | tee .retrieve-logs/current/21-omnidatatransform.log | grep -E "Status: (Succeeded|Failed)"

# 2.22 — Profile (~29) — small count, slow per record (FLS-heavy); runs LAST
sf project retrieve start --metadata Profile -o "$ORG_ALIAS" --wait 120 \
  2>&1 | tee .retrieve-logs/current/22-profile.log | grep -E "Status: (Succeeded|Failed)"
```

Expected per-call wall-clock (varies 3-10x by org load):

| Step | Type | Best-case | Slow org |
|---|---|---:|---:|
| 2.11 | AuraDefinitionBundle | 13s | 60s |
| 2.12 | Flow | 30s | 90s |
| 2.13 | FlexiPage | 50s | 90s |
| 2.14 | LightningComponentBundle | 35s | 100s |
| 2.15 | Layout | 45s | 90s |
| 2.16 | ApexClass | 25s | 75s |
| 2.17 | CustomObject | 220s | 360s |
| 2.18 | CustomField | 35s | 90s |
| 2.19 | OmniScript | 235s | 320s |
| 2.20 | OmniIntegrationProcedure | 150s | 200s |
| 2.21 | OmniDataTransform (DataRaptors) | 100s | 200s |
| 2.22 | Profile | 35s | 100s |

---

## Phase 3 — Audit + commit (mandatory)

Every retrieve run ends with a persistent audit doc under `changes/git/`, committed via the same two-commit pattern as [`changes-doc-mandatory.mdc`](../.cursor/rules/changes-doc-mandatory.mdc) (mirror commit first, doc commit second referencing the mirror commit hash).

**Why this matters:** in a Salesforce repo where teammates deploy directly to the org — often via a VDI pipeline that commits later, or sometimes never — the local repo is rarely the source of truth. Most of the diff in any retrieve is someone else's work. The audit doc lets a future investigator bisect by retrieve date and pinpoint when a given component shifted, even if no commit ever landed in the repo from the person who shipped it.

### 3.1 Pre-flight WIP check (interactive)

Before any retrieve writes to disk, check for uncommitted work and ask the user how to handle it:

```bash
wip_count=$(git status --short | wc -l | tr -d ' ')
if [ "$wip_count" -gt 0 ]; then
  echo "WIP detected: $wip_count modified or untracked files."
  git status --short | head -20
  # Ask the user: stash+pop / continue / abort
fi
```

Three valid responses:

| Response | What happens |
|---|---|
| **stash + pop** | `git stash push -u -m "pre-retrieve-$(date +%Y%m%d-%H%M)"` runs now. After Phase 3.6, `git stash pop` runs and any conflicts are reported. |
| **continue** | Retrieve runs with WIP in the tree. The WIP files will appear in the same uncommitted set as the org diffs — be careful not to fold them into the mirror commit (use selective `git add` paths in 3.5). |
| **abort** | Stop. Nothing has changed yet. |

Capture the user's choice for §7 of the audit doc.

### 3.2 Capture pre-retrieve HEAD

```bash
PRE_HEAD=$(git rev-parse HEAD)
PRE_HEAD_SHORT=$(git rev-parse --short HEAD)
echo "Pre-retrieve HEAD: $PRE_HEAD_SHORT"
```

Stash this value (env var, scratch file under `.retrieve-logs/current/`, or in your head) — it goes into §5 of the audit doc as the "since" reference.

### 3.3 Run all 23 retrieve phases

Phases 0 through 2.22 as described above. The agent does these sequentially, recording per-phase wall-clock and any retries — that data feeds §2 of the audit doc.

### 3.4 Generate the audit doc

Once the last phase (2.22 Profile) finishes:

```bash
ALIAS="$ORG_ALIAS"
SLUG="retrieve-$(date '+%Y-%m-%d-%H%M')-$ALIAS"
DOC="changes/git/${SLUG}.md"
mkdir -p changes/git
cp changes/_templates/_TEMPLATE_retrieve.md "$DOC"
echo "Audit doc seeded at: $DOC"
```

The audit doc is THEN filled in three explicit phases — **do not collapse them into a single sweep**. On heavy days (>50 files changed), reading the whole diff at once silently misses cross-type connections (a new Apex method added for an LWC that calls it; a new field that a new DataRaptor reads; a permset grant that pairs with a FlexiPage update). The per-type-first → synthesize → fill-the-rest order below prevents those misses.

### 3.4.1 Per-type analysis (todo-driven, magnitude-ordered)

**Mandatory.** Spawn one `TodoWrite` entry per metadata type that ACTUALLY changed (skip the empty types — don't pre-populate the full 23-type list). Each todo is worked end-to-end before moving to the next.

#### Compute magnitude

```bash
DIFF_RANGE="$PRE_HEAD..HEAD"

# Total churn per type (modifications only, doesn't count untracked yet):
for dir in classes triggers lwc aura omniScripts omniIntegrationProcedures \
           omniDataTransforms layouts flexipages flows objects \
           profiles permissionsets customMetadata \
           externalCredentials namedCredentials apexEmailNotifications \
           cleanDataServices siteDotComSites; do
  churn=$(git diff --numstat "$DIFF_RANGE" -- "force-app/main/default/$dir/" \
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

For each per-type todo, in order:

1. **List the changed files** under that type:

   ```bash
   git diff --name-only "$DIFF_RANGE" -- "force-app/main/default/<dir>/"
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
   | `.flow-meta.xml` | `<status>Active|Draft|Obsolete</status>` |
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
git diff "$DIFF_RANGE" -- 'force-app/main/default/classes/*.cls' \
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
| §5 Diff context | `$PRE_HEAD` and `git diff --stat "$PRE_HEAD"..HEAD \| tail -5` |
| §6 Suspicion analysis | Run the four heuristic sets below |
| §7 WIP impact | Carry over the choice + outcome from 3.1 / 3.6 |
| §8 Retrieve warnings | `grep -hE "Warning|Problem" .retrieve-logs/current/*.log` cross-checked against the "Known non-fatal warnings" table |
| §9 Mirror commit reference | Filled in *after* 3.5 — leave `<short-hash>` placeholder until then |
| §10 Open follow-ups | Anything from §6 that needs human review, plus anything the agent noticed |

#### Suspicion-analysis heuristics

Run all four in sequence. Each is a read-only diff inspection — none of them blocks the commit.

```bash
DIFF_RANGE="$PRE_HEAD..HEAD"

# 6.1 Possibly-breaking
git diff "$DIFF_RANGE" -- 'force-app/main/default/classes/*Test.cls' \
  | grep -E '^-\s+(@isTest|static testMethod void)' || true
git diff "$DIFF_RANGE" -- 'force-app/main/default/classes/*.cls' \
  | grep -E '^-(public|private|global) (with|without|inherited) sharing class' || true
git diff "$DIFF_RANGE" -- 'force-app/main/default/objects/*/fields/*.field-meta.xml' \
  | grep -E '^[-+]\s*<type>' || true

# 6.2 Security / access drift
git diff --stat "$DIFF_RANGE" -- 'force-app/main/default/permissionsets/' \
  'force-app/main/default/profiles/' \
  'force-app/main/default/sharingRules/' \
  'force-app/main/default/roles/' \
  'force-app/main/default/groups/' || true

# 6.3 Active / status flips
git diff "$DIFF_RANGE" -- 'force-app/main/default/flows/*.flow-meta.xml' \
  | grep -E '^[-+]\s*<status>' || true
git diff "$DIFF_RANGE" -- 'force-app/main/default/omniScripts/*.os-meta.xml' \
  'force-app/main/default/omniIntegrationProcedures/*.oip-meta.xml' \
  | grep -E '^[-+]\s*<IsActive>' || true
git diff "$DIFF_RANGE" -- 'force-app/main/default/objects/*/validationRules/*.validationRule-meta.xml' \
  | grep -E '^[-+]\s*<active>' || true

# 6.4 Structural overhauls
git diff --diff-filter=D --name-only "$DIFF_RANGE" -- 'force-app/main/default/classes/*.cls' || true
git status --short -- 'force-app/main/default/objects/' \
  | grep -E '^\?\?\s.*objects/[^/]+/$' || true
git diff --stat "$DIFF_RANGE" -- 'force-app/main/default/lwc/*/lwc/*.js-meta.xml' || true
# >50% line churn for IPs / OmniScripts — compare diff lines to wc -l:
for f in $(git diff --name-only "$DIFF_RANGE" -- \
    'force-app/main/default/omniIntegrationProcedures/*.oip-meta.xml' \
    'force-app/main/default/omniScripts/*.os-meta.xml'); do
  churn=$(git diff --numstat "$DIFF_RANGE" -- "$f" | awk '{print $1+$2}')
  size=$(wc -l < "$f" 2>/dev/null || echo 0)
  if [ -n "$churn" ] && [ "$size" -gt 0 ]; then
    pct=$((churn * 100 / size))
    [ "$pct" -gt 50 ] && echo "STRUCTURAL: $f ($pct% churn, $churn/$size lines)"
  fi
done
```

Pipe each into a scratch file and reference the relevant entries inside §6.x of the doc.

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

Org-wide metadata retrieve via the 23-phase plan in docs/sf-org-mirror-retrieve.md.
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
git add "$DOC"
git status -s   # should show only this one file

git commit -m "$(cat <<EOF
docs(retrieve): audit <sandbox-alias> mirror @ YYYY-MM-DD HH:MM (refs ${MIRROR_SHORT})

Snapshot record of the org-wide retrieve described in
docs/sf-org-mirror-retrieve.md. References mirror commit ${MIRROR_SHORT}.

Saved at: ${DOC}
Wall-clock: ~XX min.  Phases: 23 of 23 (or M of 23, see doc §2).
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

### 3.6 Pop WIP (if stashed in 3.1)

```bash
if git stash list | grep -q "pre-retrieve-"; then
  git stash pop
  # If conflicts surface, list them:
  git status --short | grep '^UU' || echo "Pop clean."
fi
```

Update §7 of the audit doc with the pop result (clean / conflict list). If conflicts appeared, this is a `git commit --amend` to the doc commit only — not a new commit.

### Total Phase 3 wall-clock

- Audit-doc generation: ~30s – 2 min (depending on how big the diff is for §4)
- Both commits + verifications: ~10s
- WIP stash/pop: ~5s each
- **Total Phase 3 overhead per run: ~1 – 3 min on top of the retrieve itself**

---

## CustomField fallback — only if step 2.18 hits the 10k limit

If a single `--metadata CustomField` retrieve fails with `LIMIT_EXCEEDED` or returns truncated results, shard by object family. Top folders by `.field-meta.xml` count are typically the standard high-volume objects (Account, Contact, Case) plus your custom `*__c` ones.

```bash
sf project retrieve start \
  --metadata 'CustomField:Account.*' \
  --metadata 'CustomField:Contact.*' \
  --metadata 'CustomField:Case.*' \
  -o "$ORG_ALIAS" --wait 120
```

Then repeat in batches of ~6 objects until you've covered them all. To list candidates:

```bash
find force-app/main/default/objects -name '*.field-meta.xml' \
  | awk -F/ '{print $5}' | sort | uniq -c | sort -rn | head -30
```

---

## Validating the run

After all 23 calls finish, check for failures:

```bash
echo "=== Failures (none expected) ==="
grep -l "Status: Failed" .retrieve-logs/current/*.log 2>/dev/null || echo "None"

echo "=== Real errors ==="
grep -hE "(LIMIT_EXCEEDED|MalformedQueryException|FATAL|too large)" \
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

If you see anything **other than** these — particularly `LIMIT_EXCEEDED`, `MalformedQueryException`, `FATAL`, `too large`, or `Status: Failed` — that's a real failure. Re-run that single type with a longer wait:

```bash
sf project retrieve start --metadata <Type> -o "$ORG_ALIAS" --wait 240 \
  2>&1 | tee .retrieve-logs/current/<NN>-<type>-retry.log | grep -E "Status: (Succeeded|Failed)"
```

If it still fails on size, fall back to the per-object sharding pattern from the **CustomField fallback** section above.

---

## Skipped types (intentional, per this runbook)

These are **not** retrieved by the runbook because they're large, change rarely, and rarely matter for code work:

- `Translations` (the user-facing language pack — distinct from `CustomObjectTranslation`)
- `Report`, `ReportFolder`, `ReportType`, `Dashboard`, `DashboardFolder`, `AnalyticSnapshot`
- `EmailTemplate`, `EmailFolder`, `Letterhead`
- `Document`, `DocumentFolder`
- `StaticResource`, `ContentAsset`
- `Prompt`

If you specifically need any of these (e.g. you're auditing report folders or rolling out a new `EmailTemplate`), add it as a one-off retrieve:

```bash
sf project retrieve start --metadata <SkippedType> -o "$ORG_ALIAS" --wait 120
```

---

## Total wall-clock estimates

| Org load | Total time | Per-call median |
|---|---:|---:|
| Fast org (early morning, no batch jobs) | **~20 min** | ~30s |
| Typical sandbox during business hours | **~30 – 60 min** | ~90s |
| Slow / loaded org (large package install in progress, Apex jobs running) | **~60 – 90 min** | ~3 min |
| Severely degraded org | **2 – 3 hours** | ~5 min |

The runbook is **background-friendly** — start it and keep working. It writes Status to terminal in real time and full output to `.retrieve-logs/current/` (with the previous run rotated to `.retrieve-logs/archive/<TS>/` during pre-flight).

---

## Pre-flight WIP handling

The default flow lives in [Phase 3.1](#31-pre-flight-wip-check-interactive) (stash + pop / continue / abort). Two additional patterns for cases the default doesn't cover:

**Commit WIP to a temporary branch first** — best when you want to diff your edits against org state afterwards:

```bash
git checkout -b pre-retrieve-$(date +%F)
git add -A && git commit -m "WIP before full retrieve"
git checkout -    # back to your working branch
# ... run retrieve ...
# use: git diff pre-retrieve-<date> -- <path>  to see what got overwritten
```

**Accept overwrite** — fine if your WIP is committed locally on a feature branch you can recover from `git reflog`. Pick the **continue** option in Phase 3.1, then use selective `git add` paths during Phase 3.5 so your WIP files don't end up in the mirror commit.

To audit afterwards (works for any of the three approaches):

```bash
git status --short | wc -l                          # total churn
git diff HEAD --stat | tail -20                     # breakdown
git log --oneline HEAD@{1}..HEAD 2>/dev/null        # any commits during retrieve
```

---

## Adapting this runbook to a different org

1. **Set your `ORG_ALIAS` env var** in the new shell (see [Setup](#setup-set-your-org-alias-once)). All commands in this runbook will then work as-is — no editing needed.
   ```bash
   export ORG_ALIAS=YourAliasHere
   echo "$ORG_ALIAS"     # confirm it printed what you expected
   ```
2. **Confirm the manifest shards exist** at `manifest/fullpackage/`. If not, copy them from a repo that has them (e.g. this one), or build your own from the canonical 127-type list in `manifest/fullpackage.xml`. The 11 shard files are pure metadata-name lists; they're not org-specific.
3. **Recheck local counts before the first run** — if your org has dramatically different sizes (e.g. 20k CustomFields), re-shard heavy types accordingly. See the [CustomField fallback](#customfield-fallback--only-if-step-218-hits-the-10k-limit) for the per-object pattern.
4. **First-run timing** will be longer than reruns because every component is `Created` rather than `Changed`. Budget 2–3x the typical estimates above.
5. **Add `.retrieve-logs/` to `.gitignore`** in the new repo.
6. **Don't run two retrieves to the same org concurrently** — they serialize on the org side and frequently fail with timeouts.
7. **Open a fresh shell per org** (or re-export `ORG_ALIAS`) — the env var doesn't follow you across terminals.

---

## Related references

- `.cursor/rules/sf-cli-commands.mdc` — canonical `sf` CLI reference (every flag, every command).
- `.cursor/rules/test-deploy-ruleset.mdc` — Apex deploy + test workflow (the inverse direction).
- `manifest/fullpackage.xml` — master manifest of all 127 metadata types this org cares about.
- `manifest/fullpackage/` — pre-sharded versions of the master manifest.

---

## Quick checklist (TL;DR)

```text
[ ]  Phase 0.0 — Spawn the explicit TodoWrite plan FIRST (mandatory; see runbook §0.0). Long-running, resumable on failure.
[ ]  export ORG_ALIAS=YourAlias            → set once at top of shell
[ ]  echo "$ORG_ALIAS"                     → confirm it printed
[ ]  sf org list --all                     → confirm Connected
[ ]  Rotate prior .retrieve-logs/current/ → .retrieve-logs/archive/<TS>/ (see Pre-flight)
[ ]  mkdir -p .retrieve-logs/current changes/git
[ ]  Phase 3.1 — WIP check (interactive)   → stash+pop / continue / abort
[ ]  Phase 3.2 — capture PRE_HEAD          → git rev-parse HEAD
[ ]  Phase 1 — 11 sequential calls   (~5–20 min total)
       1.1  fullpackage-integration.xml
       1.2  fullpackage-community.xml
       1.3  PostTemplate, ManagedContentType, ActionLinkGroupTemplate
       1.4  CustomObjectTranslation
       1.5  OmniUiCard, OmniInteractionConfig, OmniInteractionAccessConfig
       1.6  ApexComponent, ApexPage, ApexTestSuite, ApexTrigger, LightningMessageChannel
       1.7  RecordType, ValidationRule, WebLink, CustomMetadata, … (17 types)
       1.8  QuickAction, CustomApplication, CustomTab, … (15 types)
       1.9  Workflow*, ApprovalProcess, … (14 types, no Flow)
       1.10 PermissionSet*, Role, Group, Queue, … (14 types, no Profile)
       1.11 ExternalCredential, ExternalClientApplication, ApexEmailNotifications
[ ]  Phase 2 — 12 single-type calls  (~17–65 min total)
       2.11 AuraDefinitionBundle
       2.12 Flow
       2.13 FlexiPage
       2.14 LightningComponentBundle
       2.15 Layout
       2.16 ApexClass
       2.17 CustomObject              ← MUST precede CustomField
       2.18 CustomField
       2.19 OmniScript
       2.20 OmniIntegrationProcedure
       2.21 OmniDataTransform         ← DataRaptors (.rpt-meta.xml)
       2.22 Profile                   ← LAST
[ ]  grep -l "Status: Failed" .retrieve-logs/current/*.log    → expect "None"
[ ]  Phase 3.4 — generate audit doc        → cp template → changes/git/retrieve-<date>-<time>-<alias>.md, fill in §1-§10
[ ]  Phase 3.5 — commit 1 (mirror)         → git add force-app/ … ; commit; capture $MIRROR_SHORT
[ ]  Phase 3.5 — embed hash in doc         → replace <short-hash> in header + §9
[ ]  Phase 3.5 — commit 2 (audit doc)      → git add changes/git/<file>; commit referencing $MIRROR_SHORT
[ ]  Phase 3.6 — pop WIP if stashed        → git stash pop; report conflicts (if any) in doc §7
[ ]  Report both commit hashes back to user
[ ]  Snapshot final source counts; diff vs previous mirror
[ ]  Pop / merge WIP back if you stashed
```
