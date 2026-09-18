---
name: apex-development
description: Runs the full Apex lifecycle on `{{ORG_ALIAS}}` for creating, modifying, debugging, reviewing, validating, testing, linting, or deploying classes/triggers/batches. Requires retrieve/schema evidence, PMD, validation-only compile/tests, the adversarial plan and implementation gates where they apply, real deploy, coverage, and Apex-log verification. Mirrors `.cursor/rules/apex-development.mdc`.
---

# Apex development: deploy, test, lint, verify, format

Default target org is `{{ORG_ALIAS}}` (sandbox), source API version `{{API_VERSION}}`. Every step below is required except the review gates, which apply per `adversarial-review` and can be waived by the user.

Use the `adversarial-review` skill for Gate A before editing and Gate B before every real deploy/commit — that skill decides whether the gates run at all, and the user may waive either one. Verify each finding before acting on it, rebut rather than silently dropping one, and escalate to the user after three unresolved rounds. Never add `global` Apex to packaged metadata without asking the user first: that surface cannot be removed once a package version ships.

## Step 1 — Retrieve before editing

Pull the current state of every component you'll touch (class + its test + factory). See the `retrieve-before-edit` skill. Editing a stale file then deploying overwrites newer org state.

## Step 2 — Author the test class (if writing tests)

- **Find a factory first:** `find force-app -name "*TestDataFactory*" -o -name "*TestFactory*" -o -name "*DataFactory*"`. Use it; never duplicate creation logic.
- **Schema-validate every field** via the `schema-lookup` skill. Never set formula fields, guess API names, or hardcode RecordType Ids.
- **Visibility:** test private methods through public callers; static via `ClassName.method()`.
- **Structure:** `<ClassName>Test`, `@isTest` class-level (never `SeeAllData=true`), `@testSetup` for shared data, 3-6 focused methods (Setup→Execute→Assert) wrapped in `Test.startTest()/stopTest()`. Test classes are PMD-scanned; suppressions require evidence and reviewer approval.
- **Match production filters:** read every SOQL `WHERE` and set all filter fields + lookups; create positive AND negative data. Zero coverage despite passing = test data misses a filter.
- **Assertions:** `Assert.areEqual(expected, actual, 'msg')` / `Assert.isNotNull` / `Assert.isTrue` with messages — never `System.assert()`, never assertion-free.
- **Adversarial coverage:** add tests for accepted findings: 1/200/mixed batches, recursion/idempotency, null/error/partial-failure paths, concurrency where applicable, and unchanged shared/sibling/legacy behavior.

## Step 3 — Create a NEW manifest

Never overwrite shared manifests (`apex.xml`, `mainpackage.xml`, …). Create `manifest/<feature-or-fix-name>.xml` with only the modified components (`<version>{{API_VERSION}}</version>`).

## Step 4 — PMD and validate without committing

```bash
{{PMD_PATH}} check --dir <changed-class-or-trigger-path> -R config/pmd-ruleset.xml
sf project deploy start --metadata ApexClass:<ClassName> -o {{ORG_ALIAS}} --dry-run --ignore-conflicts
sf project deploy validate --manifest './manifest/<feature>.xml' -o {{ORG_ALIAS}} \
  --test-level RunSpecifiedTests --tests <TestClassName> --wait 10
sf project deploy report --job-id <validation-job-id> -o {{ORG_ALIAS}} --json
sf apex list log -o {{ORG_ALIAS}} --json
```

Repeat PMD for every changed `.cls`/`.trigger`. Fix all findings first. The Salesforce commands compile/test without mutating the org; capture validation coverage and inspect every operation-bound test/async log before Gate B.

## Step 5 — Pass Gate B, then deploy with targeted tests

Run the `adversarial-review` implementation gate against the exact final diff plus validation/test/coverage/static-analysis and operation-bound log evidence. Resolve/re-review every blocker, recheck org freshness, then deploy:

```bash
sf project deploy start --manifest './manifest/<feature>.xml' -o {{ORG_ALIAS}} \
  --test-level RunSpecifiedTests --tests <TestClassName> --ignore-conflicts --wait 10
```

Every class ships with a `<ClassName>Test`. Production deploys need ≥75% coverage; target **90%+**. Use validation-job coverage before Gate B, then confirm runtime coverage synchronously after deploy. Any mismatch reopens Gate B before commit:

```bash
sf apex run test --class-names <TestClassName> -o {{ORG_ALIAS}} \
  --synchronous --code-coverage --result-format human --wait 10
```

## Step 6 — MANDATORY: retrieve and grep the Apex log

Deploy "Succeeded" ≠ org success. Establish a TraceFlag first; record time window, user, validation/test/AsyncApexJob IDs, and request context; query/correlate every `ApexLog`; poll async descendants; inspect every bound log. Never trust `recent` in a shared org.

```bash
sf apex list log -o {{ORG_ALIAS}} --json
sf apex get log --log-id <operation-log-id> -o {{ORG_ALIAS}}
# Repeat for every bound log; inspect errors, triggers/flows, and cumulative limits.
```

Two traps when checking `sf` output programmatically rather than by eye: logs contain NUL bytes, so use **`grep -a`** or plain `grep` reports `Binary file … matches` and your check silently under-reports; and `grep -c` **exits non-zero on no match while still printing `0`**, so `grep -c … || echo 0` emits two lines and breaks a numeric comparison — capture it and default with `${VAR:-0}`. Also remember `--wait` is **minutes**: a seconds-style value multiplies the timeout by sixty and removes the only timeout the command had.

## Step 7 — Formatting

- **Method params/args on ONE line** — never split, even if long.
- **SOQL on one line if ≤200 chars**; multi-line (split at SELECT/FROM/WHERE/AND/ORDER BY) only when it exceeds 200.

## Final checklist

- [ ] Retrieved all touched components from `{{ORG_ALIAS}}`.
- [ ] Gate A passed against the approved LLD, or one line records why it did not apply / that the user waived it.
- [ ] PMD clean before deployment.
- [ ] Validation-only compile/full manifest tests passed.
- [ ] Validation coverage and every operation-bound test/async log inspected before Gate B.
- [ ] NEW manifest (descriptive name, only modified files).
- [ ] Test data uses a factory where one exists; fields schema-validated.
- [ ] Tests cover adversarial findings plus bulk/null/error/dependency/concurrency risks; coverage verified (≥75%, target 90%+).
- [ ] Gate B passed against the final diff/evidence; every finding verified, rebutted, or escalated — nothing still in the challenge loop.
- [ ] Every post-deploy/test/async log inspected; no discrepancy that reopens Gate B.
- [ ] Params single-line; SOQL formatted per the 200-char rule.

## Common mistakes

| Mistake | Why wrong | Correct |
|---|---|---|
| Skip syntax validation | Tests fail later for trivial reasons | Validate single-class first |
| Overwrite shared manifest | Loses other features' scope | New manifest per feature |
| Skip the log check | Hidden trigger/flow/validation failures | Always grep the log |
| Trust deploy "success" coverage | Caught exceptions / stale coverage | Synchronous run |
| Assign a formula field in a test | `Field is not writeable` | Set the fields it derives from |
| Call a private method directly | `Method is not visible` | Exercise it via a public caller |
| Use `--no-verify` / skip hooks | Hides real failures | Fix the root cause |

## When NOT to use

- Pure docs / schema TOON / manifest edits — no deploy.
- Read-only investigations.
- LWC/Aura UI changes without Apex — still deploy, but Apex tests aren't required (Jest runs separately if present).
