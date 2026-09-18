---
name: retrieve-before-edit
description: Retrieve the latest version of a Salesforce metadata component from `{{ORG_ALIAS}}` before editing it. INVOKE BEFORE any Edit/Write to files under `force-app/main/default/` — Apex (`classes/`, `triggers/`), LWC (`lwc/`), Aura (`aura/`), OmniStudio (`omniScripts/`, `omniIntegrationProcedures/`, `omniDataTransforms/`), `objects/` (fields, validation rules, web links, layouts), `flexipages/`, `permissionsets/`, `customMetadata/`, `flows/`, `staticresources/`. The local repo drifts from the org because teammates and admins deploy directly to `{{ORG_ALIAS}}`; editing a stale file silently overwrites newer org state on the next deploy.
---

# Retrieve before edit

`{{ORG_ALIAS}}` (sandbox) is the source of truth, not the local repo. **Always retrieve before editing.** Skipping this step silently overwrites newer org state on the next deploy.

## Step 1 — Identify the metadata type and API name

Map the file path to the metadata type:

| Path under `force-app/main/default/` | Metadata type | API name |
|---|---|---|
| `classes/<Name>.cls` | `ApexClass` | `<Name>` |
| `triggers/<Name>.trigger` | `ApexTrigger` | `<Name>` |
| `lwc/<bundle>/...` | `LightningComponentBundle` | `<bundle>` |
| `aura/<bundle>/...` | `AuraDefinitionBundle` | `<bundle>` |
| `omniScripts/<Type_SubType_Lang_Version>.os-meta.xml` | `OmniScript` | `<Type_SubType_Lang_Version>` |
| `omniIntegrationProcedures/<Name>.oip-meta.xml` | `OmniIntegrationProcedure` | `<Name>` |
| `omniDataTransforms/<Name>.rpt-meta.xml` | `OmniDataTransform` | `<Name>` |
| `objects/<SObj>/fields/<F>.field-meta.xml` | `CustomField` | `<SObj>.<F>` |
| `objects/<SObj>/webLinks/<W>.webLink-meta.xml` | `WebLink` | `<SObj>.<W>` |
| `objects/<SObj>/validationRules/<R>.validationRule-meta.xml` | `ValidationRule` | `<SObj>.<R>` |
| `objects/<SObj>/recordTypes/<RT>.recordType-meta.xml` | `RecordType` | `<SObj>.<RT>` |
| `objects/<SObj>/listViews/<L>.listView-meta.xml` | `ListView` | `<SObj>.<L>` |
| `objects/<SObj>/<SObj>.object-meta.xml` | `CustomObject` | `<SObj>` |
| `flexipages/<Name>.flexipage-meta.xml` | `FlexiPage` | `<Name>` |
| `layouts/<SObj>-<Layout>.layout-meta.xml` | `Layout` | `<SObj>-<Layout>` |
| `permissionsets/<Name>.permissionset-meta.xml` | `PermissionSet` | `<Name>` |
| `flows/<Name>.flow-meta.xml` | `Flow` | `<Name>` |
| `customMetadata/<Type>.<Record>.md-meta.xml` | `CustomMetadata` | `<Type>.<Record>` |
| `staticresources/<Name>.resource-meta.xml` | `StaticResource` | `<Name>` |

For multi-file bundles (LWC / Aura / OmniScripts), the API name is the **bundle / parent name**, not the inner file.

## Step 2 — Run the retrieve

Single component (preferred — fast and precise):

```bash
sf project retrieve start --metadata <Type>:<ApiName> -o {{ORG_ALIAS}}
```

Multiple related components — use a manifest under `manifest/<feature>.xml`:

```bash
sf project retrieve start --manifest manifest/<feature>.xml -o {{ORG_ALIAS}}
```

If you suspect the file no longer exists in the org, the retrieve will report `nothing retrieved`. Stop and confirm with the user before editing or recreating it.

## Step 3 — Compare and proceed

Re-read the file with the `Read` tool after retrieve completes. If git shows the retrieve modified the file, the local copy was stale — review the new contents before applying your edit so you don't reintroduce removed code.

**Read the diff for deletions too.** Two `sf` behaviours leave the tree wrong while the command reports success:

- **Retrieve never deletes.** A component removed in the org leaves its local file untouched, so the deletion never appears in the diff. Deploy that stale file back and you recreate what someone deliberately removed. A file count at or above baseline is not evidence of correctness — it is equally the signature of an undetected deletion. For a wildcard or whole-type retrieve, reconcile the org's `list metadata` fullNames against the on-disk component names.
- **A container and its child type share one file, and the later retrieve wins.** Retrieving a child type alone rewrites the shared file with only that child's members, silently dropping the container's. Worst with the rule-container types (sharing rules, workflow, matching/assignment/auto-response/escalation rules, custom labels). So: **retrieve the container, not the child** — and if you already retrieved a child type, re-retrieve its container and confirm the file is back to the union before editing or deploying.

## Step 4 — Recheck freshness before deploy

Immediately before deployment, compare intended components against the org again without retrieving over edited working files — query `LastModifiedDate` / `LastModifiedById` (Tooling API) or retrieve into a throwaway `--target-metadata-dir`, and diff against the timestamps captured at Step 2. Tooling covers Apex, fields, objects, layouts, FlexiPages, Flows, perm sets, LWC/Aura; the Omni types are **not** Tooling objects — use the standard data API, or `vlocity_cmt__*` on a Vlocity CMT org. Deploy promptly after a clean check; the shorter that gap, the smaller the overwrite race. Any drift requires merge, revalidation/tests, and rerunning the Gate B critics on the new revision. `--ignore-conflicts` never authorizes overwriting newer org work.

## Scope

- Default org alias is `{{ORG_ALIAS}}` (sandbox).
- This skill is about **single-file or scoped** retrieves in the normal edit loop. For a full-org refresh, follow `docs/org-mirror/README.md` — never a single org-wide `*` retrieve, which exceeds the per-call cap on any non-trivial org.
- Schema TOON files under `config/schema/` are regenerated separately via `python3 scripts/schemapy/auto_generate_schema.py`, not by this retrieve flow.

## When NOT to use

- Files outside `force-app/main/default/` (docs, scripts, manifests, schema YAMLs).
- Read-only inspection — only required before **edits**.
- Brand-new components you are creating from scratch (nothing to retrieve).
