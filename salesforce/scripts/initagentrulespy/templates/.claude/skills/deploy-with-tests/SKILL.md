---
name: deploy-with-tests
description: Deploy Apex/metadata changes to `{{ORG_ALIAS}}` with the mandatory validate → manifest → test → log-verify sequence. INVOKE when the user asks to deploy, validate, run tests, or finalize an Apex change. Enforces zero-tolerance rules from `.cursor/rules/test-deploy-ruleset.mdc` — every deploy must run targeted tests AND retrieve the Apex log to grep for hidden trigger/flow/validation failures that don't surface in the deploy summary.
---

# Deploy with tests + log verification

Default target org is `{{ORG_ALIAS}}` (sandbox). Source API version is `66.0`. Every step here is mandatory — silent failures (caught exceptions, validation rules failing inside flows, hidden triggers) only show up in the Apex log, not the deploy summary.

## Step 1 — Retrieve before editing

If you haven't already, pull the current state of every component you're about to deploy. See the `retrieve-before-edit` skill. Editing a stale file then deploying overwrites newer org state.

## Step 2 — Validate syntax (single-class deploy)

Fast feedback loop — catches compile errors before you set up a manifest:

```bash
sf project deploy start --metadata ApexClass:<ClassName> -o {{ORG_ALIAS}} --ignore-conflicts
```

`--ignore-conflicts` is intentional: this repo doesn't use source tracking, so the manifest is the contract.

If validation fails, stop and fix syntax errors before continuing.

## Step 3 — Create a NEW manifest

**Never overwrite shared manifests** (`apex.xml`, `mainpackage.xml`, `ospackage.xml`, etc.). Create a new one named for the feature/fix:

```
manifest/<feature-or-fix-name>.xml
```

Include only the modified components:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>YourModifiedClass</members>
        <members>YourModifiedClassTest</members>
        <name>ApexClass</name>
    </types>
    <version>66.0</version>
</Package>
```

## Step 4 — Deploy with targeted tests

```bash
sf project deploy start \
  --manifest './manifest/<feature>.xml' \
  -o {{ORG_ALIAS}} \
  --test-level RunSpecifiedTests \
  --tests <TestClassName> \
  --ignore-conflicts \
  --wait 10
```

Requirements:
- Every Apex class must ship with a test class (convention: `<ClassName>Test`).
- Production deploys require ≥75% coverage.

If you need a true coverage report (the deploy summary lies sometimes), run the test class synchronously instead:

```bash
sf apex run test --class-names <TestClassName> -o {{ORG_ALIAS}} \
  --synchronous --code-coverage --result-format human --wait 10
```

## Step 5 — MANDATORY: retrieve and grep the Apex log

Deploy success ≠ org success. Triggers, flows, and validation rules can fail silently. **You MUST check the log after any test run, anonymous Apex, or batch execution.**

```bash
# Pull the most recent log
sf apex get log --log-id recent -o {{ORG_ALIAS}} > /tmp/apex_log.txt

# Grep for failure signals
grep -E "(EXCEPTION|ERROR|FATAL|DUPLICATE_VALUE|VALIDATION_RULE)" /tmp/apex_log.txt

# Inspect what fired
grep "CODE_UNIT_STARTED.*trigger" /tmp/apex_log.txt
grep "FLOW_START" /tmp/apex_log.txt
```

If anything matches, dig in:

```bash
grep -B 30 "EXCEPTION_THROWN" /tmp/apex_log.txt
```

## Step 6 — PMD static analysis (Apex only)

Must be clean before declaring done:

```bash
{{PMD_PATH}} check --dir force-app/main/default/classes/<Class>.cls -R config/pmd-ruleset.xml
```

## Final checklist

- [ ] Retrieved current versions of all touched components from `{{ORG_ALIAS}}`.
- [ ] Syntax validated (single-class deploy succeeded).
- [ ] New manifest created (descriptive name, only modified files).
- [ ] Test class ran and passed.
- [ ] Coverage ≥75% verified (synchronous run if uncertain).
- [ ] Apex log retrieved and grepped — no `EXCEPTION|ERROR|FATAL`.
- [ ] PMD clean.

## Common mistakes

| Mistake | Why wrong | Correct approach |
|---|---|---|
| Skip syntax validation | Tests fail later for trivial reasons | Validate single-class first |
| Overwrite shared manifest | Loses other features' scope | New manifest per feature |
| Skip the log check | Hidden trigger/flow/validation failures | Always grep the log |
| Trust deploy "success" | Caught exceptions never surface | Verify in the log |
| Use `--no-verify` / skip hooks | Hides real failures | Fix the root cause |

## When NOT to use

- Pure docs / schema YAML / manifest edits — no deploy needed.
- Read-only investigations.
- LWC/Aura UI changes without Apex — still deploy, but tests aren't required (Jest runs separately if present).
