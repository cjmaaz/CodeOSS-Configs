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
| `omniScripts/<Type_SubType_Lang>.os-meta.xml` | `OmniScript` | `<Type_SubType_Lang>` |
| `omniIntegrationProcedures/<Name>.oip-meta.xml` | `OmniIntegrationProcedure` | `<Name>` |
| `omniDataTransforms/<Name>.rpt-meta.xml` | `OmniDataTransform` | `<Name>` |
| `objects/<SObj>/fields/<F>.field-meta.xml` | `CustomField` | `<SObj>.<F>` |
| `objects/<SObj>/webLinks/<W>.webLink-meta.xml` | `WebLink` | `<SObj>.<W>` |
| `objects/<SObj>/validationRules/<R>.validationRule-meta.xml` | `ValidationRule` | `<SObj>.<R>` |
| `objects/<SObj>/recordTypes/<RT>.recordType-meta.xml` | `RecordType` | `<SObj>.<RT>` |
| `objects/<SObj>/listViews/<L>.listView-meta.xml` | `ListView` | `<SObj>.<L>` |
| `objects/<SObj>.object-meta.xml` | `CustomObject` | `<SObj>` |
| `flexipages/<Name>.flexipage-meta.xml` | `FlexiPage` | `<Name>` |
| `layouts/<SObj>-<Layout>.layout-meta.xml` | `Layout` | `<SObj>-<Layout>` |
| `permissionsets/<Name>.permissionset-meta.xml` | `PermissionSet` | `<Name>` |
| `flows/<Name>.flow-meta.xml` | `Flow` | `<Name>` |
| `customMetadata/<Type>.<Record>.md-meta.xml` | `CustomMetadata` | `<Type>.<Record>` |

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

## Scope

- Default org alias is `{{ORG_ALIAS}}` (sandbox).
- This skill is about **single-file or scoped** retrieves in the normal edit loop. For full-org refreshes, see `manifest/fullpackage/` (11 pre-sharded manifests) — don't run a single org-wide `*` retrieve, it hits the 10k component limit.
- Schema TOON files under `config/schema/` are regenerated separately via `python3 scripts/schemapy/auto_generate_schema.py`, not by this retrieve flow.

## When NOT to use

- Files outside `force-app/main/default/` (docs, scripts, manifests, schema YAMLs).
- Read-only inspection — only required before **edits**.
- Brand-new components you are creating from scratch (nothing to retrieve).
