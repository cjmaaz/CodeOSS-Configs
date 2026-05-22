---
name: omnistudio-deploy-cache-bust
description: Apply this skill BEFORE running `sf project deploy start` for ANY OmniStudio component (`*.oip-meta.xml`, `*.os-meta.xml`, FlexCard XML). OmniStudio caches its compiled runtime artifacts in `OmniProcessCompilation` rows and a plain redeploy frequently does NOT trigger recompilation — your changes (probes, fixed conditional formulas, swapped DR bundles, anything) sit in the org metadata while the runtime keeps executing the stale compiled version. INVOKE this skill whenever the user asks to deploy/redeploy an OmniScript, Integration Procedure, or FlexCard; whenever you've edited a file under `omniScripts/`, `omniIntegrationProcedures/`, or any FlexCard file; or whenever the user reports "I deployed but the change isn't taking effect" / "probes aren't firing" / "OmniScript still uses old logic". Encodes the canonical 5-step deactivate → swap-active → nuke-compilation → reactivate-and-redeploy sequence plus a minimal 3-step fast-path for low-risk edits, component-specific variants, dependency-handling fallbacks, and a verification self-check. Skip for DataRaptors (`*.rpt-meta.xml`) — they're interpreted, not compiled.
---

# OmniStudio deploys = mandatory cache-bust dance

> **One-line summary.** OmniStudio runs from compiled artifacts cached in `OmniProcessCompilation` rows, not from the metadata you just deployed. A vanilla `sf project deploy start` doesn't always invalidate that cache. **Either delete the compilation row OR perform the full 5-step deactivate/reactivate dance** before assuming your deploy "took effect".

By the time you notice a cache miss (probes don't fire, the new conditional doesn't gate, the swapped DR isn't invoked), you've already burned an hour assuming your code is broken. **Apply this for every OmniStudio deploy of an active version — not "when symptoms appear".**

---

## 1. The runtime cache model (the WHY)

OmniStudio represents every OmniScript, Integration Procedure, and FlexCard as a single sObject row: **`OmniProcess`** (keyed by `UniqueName = <Type>_<SubType>_<Language>_<Version>` for OmniScripts/FlexCards, or `<Type>_<SubType>_Procedure_<Version>` for IPs). Its child elements live in **`OmniProcessElement`** (one row per step / DataRaptor call / Remote Action / conditional block / etc.).

When an `OmniProcess` row is activated (`IsActive: false → true`), the package compiles its element tree into a runtime artifact and writes a single row to **`OmniProcessCompilation`** (keyed `OmniProcessId = <OmniProcess.Id>`). On every subsequent invocation, the runtime reads that compilation row, NOT the underlying metadata. Until that compilation row is invalidated, your edits are invisible.

For IPs, an additional sibling row exists in **`OmniIntegrationProcConfig`** (keyed by `DeveloperName = <OmniProcess.UniqueName>`). It's the registry record that other OmniScripts/IPs reference when they include a "Run Integration Procedure" step. This is why deleting an actively-called IP fails with `DEPENDENCY_EXISTS` — the upstream caller's element row points at this IPC row, not at the OmniProcess directly.

DataRaptors live in a different sObject (**`OmniDataTransform`**) and do NOT have an `OmniProcessCompilation` analogue (they're interpreted, not compiled). DataRaptor changes show up immediately on redeploy. The dance below applies only to OmniScripts / IPs / FlexCards.

> 🚨 **Caller-side cache: the trap that catches everyone.** When OmniProcess A calls OmniProcess B (via "Run Integration Procedure" step), A's `OmniProcessCompilation` blob embeds a reference (and possibly a snapshot) of B's compiled artifact. **Busting B's compilation alone is NOT enough** — A's cached compilation will still serve the *previous* B until A is also recompiled. If you've added probes to B and they don't fire, the stale compilation is almost certainly A (or A's parent), not B. **You must bust the entire caller chain from the entry point down to your edited component.** Section 5.1 covers this in detail.

| Component | Primary sObject | Has compilation cache? | Cache-bust required? |
|---|---|---|---|
| OmniScript (`*.os-meta.xml`) | `OmniProcess` | Yes (server-side compile + browser-side cache) | Yes — full dance + browser hard-refresh |
| Integration Procedure (`*.oip-meta.xml`) | `OmniProcess` | Yes (server-side compile) | Yes — full dance |
| FlexCard (`*.flexCard-meta.xml`) | `OmniProcess` (some versions) or `OmniUiCard__c` (older) | Yes | Yes — full dance |
| DataRaptor (`*.rpt-meta.xml`) | `OmniDataTransform` | No (interpreted at runtime) | No — plain `sf project deploy start` is sufficient |

---

## 2. When to apply / when to skip

### Always apply for these triggers

- About to run `sf project deploy start` and the manifest contains `OmniIntegrationProcedure`, `OmniScript`, or any `Omni*` type.
- The user just edited a file under `omniScripts/`, `omniIntegrationProcedures/`, or any FlexCard file.
- Symptoms reported (see Section 3).
- Adding diagnostic probes (`pingApex`, Set Values, Remote Actions) to an active version.
- Changing a conditional formula, additional input mapping, send/response JSON path, or remote action class on an active version.
- Renaming, reordering, or reparenting any element in the OmniProcess element tree.
- Swapping a DataRaptor `bundle`, an Apex `remoteClass`/`remoteMethod`, or the IP `bundle` on a step.
- Migrating a feature across orgs where the component already exists in the target.

### Skip when

- Deploying a brand-new version that has never existed in the org (e.g. `_Procedure_6` when the org only has `_1`–`_5`). First-time creation always recompiles.
- Deploying a version whose local file has `<isActive>false</isActive>` and that you know will remain inactive (the runtime never serves it anyway).
- Pure DataRaptor (`*.rpt-meta.xml`) changes — no compilation cache.
- Pure CustomField / ValidationRule / Layout / Apex changes that don't touch any `*.oip-meta.xml`, `*.os-meta.xml`, or FlexCard XML.
- Initial scratch-org / sandbox bootstrapping where everything is fresh.

---

## 3. Symptoms that the cache is stale

Reach for this skill the moment you see ANY of these:

| Symptom | What's actually happening |
|---|---|
| Probe / Set Values / Remote Action you just added isn't appearing in the IP's debug response | New `OmniProcessElement` row exists but `OmniProcessCompilation` still references the old element list — **OR** (more common) a parent IP is serving a stale compilation that embeds the previous version of your edited IP. See Section 5.1. |
| Conditional block fires/skips contrary to your edited `executionConditionalFormula` | Cache is serving the previous compiled formula |
| DR call uses old `bundle` even though `*.oip-meta.xml` shows the new `bundle` value | Cache holds the old bundle reference |
| Renamed step still appears under the old name in the IP debug log | Element rename hasn't propagated through compilation |
| `Schema.SObjectType.X` / `customMetadata` reference works in Apex but the OmniScript still calls the wrong one | Cached compilation has the stale RemoteClass binding |
| Two consecutive runs of the same input produce different outputs | A partial cache invalidation happened (e.g. some element rows replaced, some not) |
| Description tweak deploys as `Unchanged` | The description didn't actually mutate on disk; redo the byte-flip |

If you see any of these, run the dance. Don't try to debug your code first.

---

## 4. The two paths

### Path A — Minimal (3 steps, fast, low-risk edits)

Use when:
- You're confident no other component depends on the in-flight cache state.
- This is a small diagnostic edit (probe addition, conditional formula tweak, DR bundle swap on a single step).
- You have already done a successful Path-B for this component recently.

```bash
# 1. Find and delete the cached compilation
sf data query -o {{ORG_ALIAS}} --query "SELECT Id FROM OmniProcessCompilation WHERE OmniProcessId = '<Vcurrent.Id>'"
sf data delete record --sobject OmniProcessCompilation --record-id '<compilation.Id>' -o {{ORG_ALIAS}}

# 2. Tweak the top-level <description> (flip a "." or "," to force the byte change)
#    — edit the file in your IDE

# 3. Redeploy
sf project deploy start --manifest manifest/<feature>.xml -o {{ORG_ALIAS}} --ignore-conflicts --wait 5
```

Then run the self-check (Section 6). If the self-check passes, you're done. If not, escalate to Path B.

### Path B — Full 5-step dance (mandatory when Path A fails or for any non-trivial change)

This is the canonical procedure. Throughout, let:
- `Vcurrent` = the version you're working on / want to deploy as active.
- `Vold` = any older version of the same `UniqueName` that exists locally (so you can redeploy from local if needed). Prefer the highest version below Vcurrent.

> **Two OmniStudio constraints to know up-front (both enforced by the package, both throw `FIELD_INTEGRITY_EXCEPTION`):**
> 1. **You cannot update or delete an active OmniProcess record.** Must deactivate first.
> 2. **Only one version of a given Type/SubType/Language can be active at a time.** Trying to activate a second one throws `Another active Omniscript with the same Type, Subtype, and Language exists`.
>
> These two constraints dictate the order of Steps 2–4 — they're not interchangeable.

#### Step 1 — Survey & pick a Vold

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, UniqueName, IsActive, VersionNumber, LastModifiedDate FROM OmniProcess WHERE UniqueName LIKE '<Type>_<SubType>_%' ORDER BY VersionNumber DESC"
```

Capture both Ids — you'll use them in Steps 2–4.

#### Step 2 — Deactivate Vcurrent, then activate Vold (one Apex transaction, two sequential `update`s)

```bash
cat > /tmp/swap.apex <<'EOF'
update new OmniProcess(Id = '<Vcurrent.Id>', IsActive = false);
update new OmniProcess(Id = '<Vold.Id>',     IsActive = true);
System.debug('Vcurrent deactivated, Vold activated.');
EOF
sf apex run -o {{ORG_ALIAS}} --file /tmp/swap.apex
```

> Don't try `update new List<OmniProcess>{ ... }` — the constraint check is per-record and the package may evaluate them in arbitrary order, occasionally failing the second-active-check on Vold. **Sequential `update` statements** in the same Apex run is the safe pattern.
>
> Heredoc directly inside the `sf apex run` invocation has been known to mangle quoting on some shells (Windows Git Bash, certain zsh setups). Writing to a temp `.apex` file and using `--file` is portable.

Verify:

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, UniqueName, IsActive FROM OmniProcess WHERE UniqueName LIKE '<Type>_<SubType>_%' ORDER BY VersionNumber DESC"
```

Vold should be `IsActive=true`, Vcurrent `IsActive=false`. If not, stop and investigate.

#### Step 3 — Nuke the cached runtime artifact; attempt OmniProcess delete

> 🚨 **NEVER `rm` or `git rm` the local `.oip-meta.xml` / `.os-meta.xml` / `.rpt-meta.xml` file.** You'll redeploy from local in Step 5. Local must remain untouched.

**3a. Delete the compilation artifact (mandatory — this is the actual cached object).**

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, OmniProcessId FROM OmniProcessCompilation WHERE OmniProcessId = '<Vcurrent.Id>'"
sf data delete record --sobject OmniProcessCompilation --record-id '<compilation.Id>' -o {{ORG_ALIAS}}
```

If no compilation row exists for Vcurrent, that's fine — Vcurrent was either never invoked or already evicted. Skip to 3b.

**3b. Try to delete the `OmniIntegrationProcConfig` row for Vcurrent (optional, often fails for IPs).**

Each IP's `OmniProcess` has a sibling `OmniIntegrationProcConfig` row keyed by `DeveloperName = <Vcurrent.UniqueName>`. Salesforce blocks deletion if any other OmniScript/IP references this IP via a "Run Integration Procedure" step:

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, DeveloperName FROM OmniIntegrationProcConfig WHERE DeveloperName = '<Vcurrent.UniqueName>'"
sf data delete record --sobject OmniIntegrationProcConfig --record-id '<ipc.Id>' -o {{ORG_ALIAS}}
```

If this returns `DEPENDENCY_EXISTS: ... Omni Integration Procedure Configuration`, an upstream caller is referencing it. **Don't fight this** — modifying upstream callers just to delete a child IPC row is invasive and risky. Skip ahead; Step 3a is the cache-invalidation that actually matters.

**3c. Try to delete the `OmniProcess` row for Vcurrent (optional, often fails for IPs with upstream callers).**

```bash
sf data delete record --sobject OmniProcess --record-id '<Vcurrent.Id>' -o {{ORG_ALIAS}}
```

Same `DEPENDENCY_EXISTS` outcome is likely. **If this fails, accept it and move on.** The OmniProcess row will be `Updated` (not `Created`) on the Step 5 redeploy — same `Id`, fresh `LastModifiedDate`, all `OmniProcessElement` rows rewritten with NEW `Id`s. Combined with Step 3a, this is sufficient.

> **Why we even attempt 3b/3c:** when they *do* succeed (brand-new IPs with no upstream callers, dev-only OmniScripts, scratch orgs), Salesforce treats the Step 5 redeploy as `Created` not `Updated`, which fires more aggressive package-side post-create hooks. Cleaner when allowed; not worth fighting when blocked.

#### Step 4 — Deactivate Vold

```bash
cat > /tmp/deactivate-vold.apex <<'EOF'
update new OmniProcess(Id = '<Vold.Id>', IsActive = false);
EOF
sf apex run -o {{ORG_ALIAS}} --file /tmp/deactivate-vold.apex
```

Now no version is active for that UniqueName. The runtime registry has no compiled artifact to fall back on for that SubType. This guarantees a clean re-registration in Step 5 (otherwise activating Vcurrent in Step 5 would throw `FIELD_INTEGRITY_EXCEPTION` again).

#### Step 5 — Tweak description + redeploy Vcurrent

Open Vcurrent's local file. Find the top-level `<description>` element and add or remove a single `.` or `,`. The change must mutate the bytes so Salesforce treats the metadata as `Changed` not `Unchanged`:

```xml
<!-- Before -->
<description>v5: identical to v3. IFC creation moved up.</description>

<!-- After -->
<description>v5: identical to v3. IFC creation moved up..</description>
```

Confirm `<isActive>true</isActive>` is set in the file (the deploy will then recreate it as the active version).

```bash
sf project deploy start --manifest manifest/<feature>.xml -o {{ORG_ALIAS}} --ignore-conflicts --wait 5
```

The deploy summary should report `State: Changed` (or `Created` if 3b/3c succeeded). If it says `Unchanged`, the description tweak didn't make it to disk; redo Step 5.

---

## 5. Dependency-handling fallbacks

### 5.1 Caller-side cache — bust the entire caller chain

**This is the single most common reason "the dance worked but my probes still don't fire."** When you edit IP `B` and apply Path B to it, `B`'s `OmniProcessCompilation` is wiped and rebuilds correctly on next invocation. But if `B` is invoked from a parent IP `A` (via a "Run Integration Procedure" step in `A`'s element tree), then `A`'s own `OmniProcessCompilation` row contains a cached reference (and in some package versions, a snapshot blob) of `B`'s previous compiled state. Until `A` is recompiled, `A` keeps calling the *previous* `B`, and your probes in the new `B` are invisible.

**The fix:** apply Path A (compilation-delete only) to *every* OmniProcess in the caller chain from the entry point down to your edited component.

#### Identify the chain

Start from the entry point (whatever the user invokes — often a Case button or Lightning page launching an OmniScript). Walk down through every "Run Integration Procedure" step:

```bash
# Find IPs whose elements reference your edited IP's UniqueName
# (PropertySetConfig is a long-text field that holds the JSON with "integrationProcedureKey": "<callee>")
sf data query -o {{ORG_ALIAS}} --query "SELECT OmniProcess.UniqueName, OmniProcess.IsActive, Name, Type FROM OmniProcessElement WHERE PropertySetConfig LIKE '%<callee_short_name>%' AND Type = 'Integration Procedure Action' AND OmniProcess.IsActive = true"
```

Repeat upward until you find the entry point with no callers. The full chain might be 3–5 IPs deep.

#### Bust all caller compilations in one shot

```bash
cat > /tmp/nuke-chain.apex <<'EOF'
List<Id> chainIPIds = new List<Id>{
    '<entry-point.Id>',
    '<mid-tier-1.Id>',
    '<mid-tier-2.Id>',
    '<your-edited-IP.Id>'
};
List<OmniProcessCompilation> comps = [
    SELECT Id, OmniProcessId, OmniProcess.UniqueName
    FROM OmniProcessCompilation
    WHERE OmniProcessId IN :chainIPIds
];
for (OmniProcessCompilation c : comps) {
    System.debug('Deleting compilation for ' + c.OmniProcess.UniqueName);
}
delete comps;
System.debug('Deleted ' + comps.size() + ' compilation rows.');
EOF
sf apex run -o {{ORG_ALIAS}} --file /tmp/nuke-chain.apex
```

#### Verify all chain compilations are gone

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT OmniProcess.UniqueName, COUNT(Id) cnt FROM OmniProcessCompilation WHERE OmniProcessId IN ('<entry>','<mid-1>','<mid-2>','<edited>') GROUP BY OmniProcess.UniqueName"
```

Expect zero rows. The next invocation will rebuild every compilation in the chain, picking up the fresh callee with your probes.

#### Diagnostic signal: how to know caller-cache is your issue

After Path B on your edited component, query `OmniProcessCompilation.LastModifiedDate` for the parent IP:

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT OmniProcess.UniqueName, LastModifiedDate FROM OmniProcessCompilation WHERE OmniProcess.UniqueName = '<parent-ip>'"
```

If `LastModifiedDate` is from a previous day (or any time before your edited component's last activation), the parent is serving a stale compilation. That's your culprit.

**Why this is so common:** OmniStudio compiles each IP once on activation (or on first invocation post-eviction) and reuses that compilation across all subsequent calls until something explicitly evicts it. There's no automatic invalidation cascade — editing a callee does NOT invalidate caller compilations. You have to do it manually.

#### When in doubt, just nuke ALL same-day-active compilations

Aggressive but reliable cleanup:

```bash
cat > /tmp/nuke-all-stale.apex <<'EOF'
List<OmniProcessCompilation> stale = [
    SELECT Id, OmniProcess.UniqueName, LastModifiedDate
    FROM OmniProcessCompilation
    WHERE OmniProcess.IsActive = true
    AND LastModifiedDate < :Datetime.now().addHours(-2)
];
System.debug('Will delete ' + stale.size() + ' stale compilations.');
delete stale;
EOF
sf apex run -o {{ORG_ALIAS}} --file /tmp/nuke-all-stale.apex
```

Use sparingly — every active IP in the org will pay a recompile cost on its next invocation.

### When upstream callers block deletion

If 3b/3c fail with `DEPENDENCY_EXISTS`, identify the caller(s) — useful for understanding the blast radius even if you don't act on them:

```bash
# Look for Integration Procedure callers (steps with type 'Integration Procedure Action' or
# 'Remote Action' bound to omnistudio.IntegrationProcedureService)
sf data query -o {{ORG_ALIAS}} --query "SELECT OmniProcess.UniqueName, Name FROM OmniProcessElement WHERE PropertySetConfig LIKE '%<Vcurrent.UniqueName>%' AND OmniProcess.IsActive = true"
```

For OmniScripts called by FlexCards/Lightning pages, also check:

```bash
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, Type, SubType FROM OmniProcess WHERE PropertySetConfig LIKE '%<Vcurrent.UniqueName>%' AND IsActive = true"
```

Don't modify the callers just to enable deletion. Step 3a's compilation delete is the meaningful action.

### When even Step 5's deploy reports `Unchanged`

Most common cause: an editor/IDE auto-format silently reverted your description tweak on save. Double-check the file on disk:

```bash
grep "<description>" force-app/main/default/omniIntegrationProcedures/<file>.oip-meta.xml | head -1
```

If the punctuation didn't stick, re-edit in plain text mode and disable any "format on save" for `*.oip-meta.xml` / `*.os-meta.xml` files in your editor.

### When no Vold exists locally

Rare but possible for brand-new SubTypes where only one version has ever been created. Workaround:

1. `cp <file> /tmp/Vcurrent.xml` (snapshot)
2. Locally rename `_1.oip-meta.xml` → `_2.oip-meta.xml` (any unused number); update `<filenameSuffix>` and any embedded version reference.
3. Edit the renamed file: change `<isActive>true</isActive>` → `<isActive>false</isActive>`, optionally tweak description.
4. Deploy this synthetic Vold. Now the org has two versions.
5. Restore the original from `/tmp/Vcurrent.xml` and resume the standard 5-step dance.

Awkward enough that it's not the common path — most OmniProcesses accumulate versions over time.

### When you're cache-busting MULTIPLE components in one feature

For a feature touching N OmniScripts/IPs, do them in **dependency order, leaves first** (i.e. the IP that no one else calls → its callers → top-level OmniScript). Otherwise you'll hit `DEPENDENCY_EXISTS` cascades when trying to delete IPCs of mid-tree components.

If the dependency graph is complex, do a single bulk Step 3a (delete all `OmniProcessCompilation` rows for the affected versions in one Apex script) and then a single bulk Step 5 (deploy all components in one manifest). That collapses N dances into 1.

---

## 6. Self-check after the dance

Before declaring the deploy successful, verify ALL of these:

- [ ] `OmniProcess` query shows Vcurrent `IsActive=true` and `LastModifiedDate` within the last 60 seconds.
- [ ] `OmniProcessElement` query shows your new/changed elements with **NEW `Id`s** (different from before the dance):
  ```bash
  sf data query -o {{ORG_ALIAS}} --query "SELECT Id, Name, Type FROM OmniProcessElement WHERE OmniProcessId = '<Vcurrent.Id>' AND Name LIKE '<your new element pattern>%'"
  ```
- [ ] `OmniProcessCompilation` query returns **0 rows** for Vcurrent (the runtime will recompile fresh on first invocation):
  ```bash
  sf data query -o {{ORG_ALIAS}} --query "SELECT Id, OmniProcessId FROM OmniProcessCompilation WHERE OmniProcessId = '<Vcurrent.Id>'"
  ```
- [ ] If you added probes that write to a sink (e.g. `PRM_ExceptionLog__c`), trigger the IP/OmniScript and verify the probe label appears within ~30 seconds.
- [ ] `git diff <local file>` shows ONLY the description punctuation change plus your intended functional change — no accidental local mutations.
- [ ] For OmniScripts (UI components): browser hard-refresh (Cmd+Shift+R / Ctrl+Shift+R) on the launching Lightning page, or sign out/back in of the dev sandbox. Browser caches the OmniScript bundle separately from the server cache.

---

## 7. Common errors, literal strings & fixes

| Error string | Cause | Fix |
|---|---|---|
| `FIELD_INTEGRITY_EXCEPTION: You can't update or delete an active Omniscript record. Deactivate the record and try again.` | Tried to delete or change Vcurrent while `IsActive=true` | Run Step 2 (deactivate Vcurrent) first |
| `FIELD_INTEGRITY_EXCEPTION: Another active Omniscript with the same Type, Subtype, and Language exists.` | Tried to activate Vold while Vcurrent still active | Combine deactivate-Vcurrent + activate-Vold in one Apex script (Step 2 pattern) |
| `DEPENDENCY_EXISTS: ... Omni Integration Procedure Configuration` | An upstream OmniScript/IP references this IP's IPC row | Skip the deletion; rely on Step 3a (compilation delete) instead |
| `Status: Succeeded` + `State: Unchanged` in deploy summary | Your local file matches the org byte-for-byte | The description tweak didn't persist; re-edit and verify with `grep "<description>"` |
| `No source-backed components present in the package.` (deploy) | Manifest member uses `Type/SubType/Procedure/N` slash-syntax | Use underscore-syntax: `<Type>_<SubType>_Procedure_<N>` |
| `sObject type 'OmniProcess' is not supported.` (Tooling API query) | Used `--use-tooling-api` for an sObject that's available on the standard data API | Drop `--use-tooling-api` |
| Probe added but never appears in `PRM_ExceptionLog__c` | Either the IP isn't reaching your probe (wrong block), OR cache isn't busted | Add an unconditional top-level entry probe (no `executionConditionalFormula`) — if even THAT doesn't fire, it's a cache problem |
| Probe fires once then stops firing | Probe `failOnStepError: true` and Apex inserted a record but a downstream DR rolled the txn back | Set `failOnStepError: false` on the probe (probes shouldn't be allowed to halt the IP) |

---

## 8. Worked examples

### Example A — Integration Procedure with upstream callers (this repo, {{ORG_ALIAS}})

`PRM_PractitionerAddressCreation_Procedure_5` — called by `PRM_AddressLogicContainer_English_6`, so 3b/3c will fail. Path B with the IPC delete skipped:

```bash
# Step 1 — survey
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, UniqueName, IsActive, VersionNumber FROM OmniProcess WHERE UniqueName LIKE 'PRM_PractitionerAddressCreation_Procedure_%' ORDER BY VersionNumber DESC"
# → Vcurrent = 0jNOv000000ICkIMAW (v5, active), Vold = 0jNOv000000HadNMAS (v3, inactive)

# Step 2 — deactivate v5, activate v3 (one Apex script)
cat > /tmp/swap.apex <<'EOF'
update new OmniProcess(Id = '0jNOv000000ICkIMAW', IsActive = false);
update new OmniProcess(Id = '0jNOv000000HadNMAS', IsActive = true);
EOF
sf apex run -o {{ORG_ALIAS}} --file /tmp/swap.apex

# Step 3a — delete v5's compilation (THE actual cached artifact)
sf data query -o {{ORG_ALIAS}} --query "SELECT Id FROM OmniProcessCompilation WHERE OmniProcessId = '0jNOv000000ICkIMAW'"
sf data delete record --sobject OmniProcessCompilation --record-id '0k7Ov000000I4efIAC' -o {{ORG_ALIAS}}

# Step 3b/3c — both will fail with DEPENDENCY_EXISTS (PRM_AddressLogicContainer references v5).
# Acceptable per Section 5; skip.

# Step 4 — deactivate v3
cat > /tmp/deactivate.apex <<'EOF'
update new OmniProcess(Id = '0jNOv000000HadNMAS', IsActive = false);
EOF
sf apex run -o {{ORG_ALIAS}} --file /tmp/deactivate.apex

# Step 5 — tweak description (e.g. "(probes added.)" → "(probes added..)") and redeploy
sf project deploy start --manifest manifest/probes-v5-existing-group-debug.xml -o {{ORG_ALIAS}} --ignore-conflicts --wait 5

# Self-check
sf data query -o {{ORG_ALIAS}} --query "SELECT Id, UniqueName, IsActive, VersionNumber, LastModifiedDate FROM OmniProcess WHERE UniqueName LIKE 'PRM_PractitionerAddressCreation_Procedure_%' ORDER BY VersionNumber DESC"
sf data query -o {{ORG_ALIAS}} --query "SELECT COUNT(Id) cnt FROM OmniProcessCompilation WHERE OmniProcessId = '0jNOv000000ICkIMAW'"
# → v5 IsActive=true, fresh LastModifiedDate, compilation count = 0 ✓
```

### Example B — Standalone OmniScript with no upstream callers (generic Salesforce org)

`MyType_MySubType_English_3` is an OmniScript with no callers, which means full Path B works including the deletion:

```bash
ALIAS=mySandbox
TYPE=MyType
SUB=MySubType

# Step 1 — survey
sf data query -o $ALIAS --query "SELECT Id, UniqueName, IsActive, VersionNumber FROM OmniProcess WHERE UniqueName LIKE '${TYPE}_${SUB}_%' ORDER BY VersionNumber DESC"
# → Vcurrent = 0jX...3 (v3, active), Vold = 0jX...2 (v2, inactive)

# Step 2 — deactivate v3, activate v2
cat > /tmp/swap.apex <<'EOF'
update new OmniProcess(Id = '0jX...3', IsActive = false);
update new OmniProcess(Id = '0jX...2', IsActive = true);
EOF
sf apex run -o $ALIAS --file /tmp/swap.apex

# Step 3a — delete v3 compilation
sf data delete record --sobject OmniProcessCompilation --record-id '<v3-compilation-id>' -o $ALIAS

# Step 3b — delete IPC config for v3 (succeeds because no callers)
sf data delete record --sobject OmniIntegrationProcConfig --record-id '<v3-ipc-id>' -o $ALIAS

# Step 3c — delete OmniProcess v3 (succeeds because no callers)
sf data delete record --sobject OmniProcess --record-id '0jX...3' -o $ALIAS

# Step 4 — deactivate v2
cat > /tmp/deactivate.apex <<'EOF'
update new OmniProcess(Id = '0jX...2', IsActive = false);
EOF
sf apex run -o $ALIAS --file /tmp/deactivate.apex

# Step 5 — tweak description, redeploy. v3 will appear with a NEW OmniProcess.Id.
sf project deploy start --manifest manifest/<feature>.xml -o $ALIAS --ignore-conflicts --wait 5
```

---

## 9. Component-specific notes

### OmniScripts (UI-bearing)

- Same OmniProcess + OmniProcessCompilation model as IPs.
- **Additional cache layer: the browser.** After server-side cache-bust, also do Cmd+Shift+R / Ctrl+Shift+R on the Lightning page that hosts the OmniScript. In stubborn cases, log out and log back in (clears the per-session OmniScript bundle).
- The OmniScript step containing a "Run Integration Procedure" sub-step is the one creating the upstream dependency on an IP's IPC row.

### Integration Procedures

- The pattern this skill is primarily written for. See examples above.
- IPs called from Apex via `omnistudio.IntegrationProcedureService.runIntegrationService(...)` use the IPC row's `DeveloperName` to resolve the version, not the OmniProcess Id directly.

### DataRaptors

- **Skip this entire skill.** DataRaptors live in `OmniDataTransform` (not `OmniProcess`) and are interpreted at runtime — no compilation cache. A plain `sf project deploy start` is sufficient and immediate. The only caveat: DataRaptor changes can still be invisible if the OmniScript/IP that *calls* them is itself stale-cached; in that case bust the caller, not the DR.

### FlexCards

- Same `OmniProcess` model as OmniScripts in modern OmniStudio (post-package version 250).
- LWC compilation also caches per-user; same browser hard-refresh applies.
- Older Vlocity-namespaced FlexCards may live in `vlocity_*__OmniUiCard__c` instead — different cache, different procedure (legacy, not covered here).

---

## 10. When the dance still doesn't work

If you've completed Path B + the self-check passes but the runtime *still* serves stale logic:

1. **Check the parent caller — this is the #1 culprit.** Apply Path A (compilation-delete only) to every IP in the caller chain. See Section 5.1 for the full bust-the-chain procedure. Single-component cache-bust is usually NOT enough when the entry-point IP was compiled before your edit.
2. **Check the OmniProcess `IsManagedUsingStdDesigner` flag.** If `false`, the version was edited via the legacy Vlocity Designer and may have a separate cache layer (`vlocity_ins__OmniProcessAction__c` or similar — query and delete those too).
3. **Test in a fresh browser/incognito session.** Eliminates any browser-side OmniScript bundle cache.
4. **Wait 5–10 min.** Some package versions have a write-through cache with eventual consistency on activation events.
5. **Check Setup → Apex Test Execution → Recent Test Runs.** A failed Apex test that recompiles the IP can sometimes purge the cache as a side effect.
6. **Last resort:** create a new version (Vcurrent+1) from local, deploy that as active. New version = guaranteed fresh compile. Old Vcurrent stays in the org as a versioned artifact.

---

## 11. Common mistakes

| Mistake | Why wrong | Correct approach |
|---|---|---|
| `git rm` or `rm` the local `.oip-meta.xml` file | Loses the source you need for Step 5 | Org-side `sf data delete record` only |
| Skip Step 4 (leave Vold active) and just redeploy Vcurrent | Vold blocks Vcurrent's `IsActive=true` activation in Step 5 with `FIELD_INTEGRITY_EXCEPTION` | Always deactivate Vold before redeploying Vcurrent |
| Skip the description tweak | `sf project deploy start` reports `Unchanged` and OmniStudio doesn't recompile | Mandatory `.` or `,` flip in the top-level `<description>` |
| Activate via UI only (no Apex DML) | UI works but isn't reproducible/scriptable / can't be encoded in CI | Use anonymous Apex via `sf apex run --file` |
| Trust deploy `Status: Succeeded` without re-querying `OmniProcess` and `OmniProcessCompilation` | Deploy success ≠ runtime cache invalidated | Always run the post-deploy queries as the final check |
| Try to activate Vold while Vcurrent is still active | `FIELD_INTEGRITY_EXCEPTION: Another active Omniscript with the same Type, Subtype, and Language exists` | Deactivate Vcurrent first (combine both updates in one Apex script — Step 2 pattern) |
| Try to delete Vcurrent while it's still active | `FIELD_INTEGRITY_EXCEPTION: You can't update or delete an active Omniscript record` | Deactivate Vcurrent (Step 2) before trying to delete (Step 3) |
| Modify upstream callers to enable IPC deletion | High-blast-radius change just to enable a cleanup step | Skip 3b/3c; rely on 3a (compilation delete) |
| Use heredoc `<<'EOF'` directly inside `sf apex run` | Some shells (Git Bash on Windows, certain zsh setups) mangle quoting | Write to `/tmp/<name>.apex` first, use `--file` |
| Use slash-separated manifest member (`Type/SubType/Procedure/N`) | Not the SFDX convention for OmniIntegrationProcedure | Underscore-separated: `<Type>_<SubType>_Procedure_<N>` |
| Apply to a DataRaptor change | DataRaptors don't compile; no cache to bust | Skip — plain deploy is fine |
| Skip the entire dance "because it's a small change" | Cache misses are silent; you'll burn an hour assuming code is broken | Apply to every deploy of an active OmniProcess version (or use Path A minimum) |

---

## 12. Why this works (mechanism deep-dive)

OmniStudio's runtime is a singleton in-memory cache (the package's internal `OmniProcessRuntimeCache` or similar) keyed on `Type/SubType[/Language]`. The cache entry holds the deserialized representation of `OmniProcessCompilation.PayloadCompressed` (a binary blob built at activation time).

Cache invalidation triggers (in approximate order of reliability):

| Trigger | Reliability | Notes |
|---|---|---|
| Delete `OmniProcessCompilation` row directly (Step 3a) | Highest | The cache reads from this row; deleting it forces a recompile on next invocation |
| `IsActive: false → true` flip on `OmniProcess` (Step 5 redeploy with `<isActive>true</isActive>`) | High | Package trigger handler invalidates and recompiles |
| `IsActive: true → false` (Step 2 first half) | Low | Cache entry stays warm — still served until something replaces it |
| Plain metadata redeploy without Step 3a or `IsActive` change | Very low | Often does nothing — the metadata is updated but the trigger condition for cache invalidation isn't met |
| Element renames / additions without redeploy | Zero | Pure metadata API writes that bypass the package's lifecycle hooks |

The full 5-step dance combines BOTH the high-reliability mechanisms: it deletes the compilation row (Step 3a) AND forces an `IsActive: false → true` transition (Step 5). Either alone is *usually* enough; together they're bulletproof.

The description tweak is the secondary safety net — it ensures the metadata API actually emits `Changed` (not `Unchanged`), which is necessary for the package's post-deploy hooks to fire at all. Without a byte change, Salesforce's MDAPI may short-circuit the deploy entirely.

---

## 13. Companion rule (Cursor)

The Cursor-side equivalent of this skill lives at [`.cursor/rules/omnistudio-deploy-cache-bust.mdc`](../../../.cursor/rules/omnistudio-deploy-cache-bust.mdc). Both must stay in sync — if you update one, update the other in the same commit.
