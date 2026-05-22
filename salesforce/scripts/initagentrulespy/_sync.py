#!/usr/bin/env python3
"""
_sync.py — source-repo maintainer helper.

Walks the source repo's rules / skills / docs / manifests and refreshes the
bundled `templates/` folder that init.py reads at runtime.

Run this AFTER editing any of the source files listed in SOURCES below.
End users (colleagues running init.py) NEVER run this script.

While copying, every file goes through `_tokenize()` which strips
source-repo-specific literals (paths, sf CLI alias, project / org brand
name, broken filename refs from rename-and-stubs) and replaces them with
`{{...}}` placeholders. `init.py` then re-substitutes those placeholders
at the colleague's end using values either auto-detected from their
workspace or supplied via CLI flags (notably `--org-name`, which fills
`{{ORG_NAME}}` and defaults to `CURR ORG`).

If you fork this script for a different source repo, the only edits you
need are in the PROJECT_CONFIG block below. Everything else (tokenize
logic, transform implementations, SOURCES table, sync driver) is
repo-agnostic.

Usage:
    python3 scripts/initagentrulespy/_sync.py [--check] [--verbose]

    --check    Compare-only mode: exit 1 if templates/ is out of date.
               Useful in CI to ensure templates/ stays in sync with source.
    --verbose  Print every file written / unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# PROJECT_CONFIG — the ONLY block you need to edit when forking this script
# for a different source repo.
#
# Each entry is a source-repo literal that the maintainer has baked into the
# source files (paths in rules / docs, alias in command examples, brand name
# in prose, filenames that got rename-and-stubbed). Tokenization rewrites
# each to a `{{...}}` placeholder before files land in templates/; init.py
# then re-substitutes those placeholders at the colleague's end.
# ────────────────────────────────────────────────────────────────────────────

PROJECT_CONFIG = {
    # Absolute path to the source repo on this maintainer's machine.
    # Anywhere this string appears in a rule / doc gets replaced with the
    # colleague's own workspace path at init time.
    "workspace_path": "/Users/maaz.rahman/Orgs/Work/IBX/IBXMain",

    # JDK home baked into the source repo's .vscode/settings.json. Replaced
    # by init.py's auto-detected JDK on the colleague's machine.
    "java_home": "/Library/Java/JavaVirtualMachines/zulu-21.jdk/Contents/Home",

    # sf CLI alias baked into the source repo's rules / docs.
    "org_alias": "IBXMain",

    # Brand-name literals for this org, ordered longest-first. The first one
    # is the "long form" (e.g. "Acme Health Provider Network") and the last
    # is the bare acronym / short name (e.g. "IBX"). Each gets substituted
    # to `{{ORG_NAME}}` so init.py can swap in whatever the colleague
    # passes via `--org-name` (defaults to "CURR ORG").
    "org_name_literals": ["IBX Provider Network", "IBX"],

    # Filename rewrites that mirror rename-and-stub SOURCES entries. When a
    # source file gets renamed in templates/ (e.g. ibx-conventions.md →
    # org-conventions.md), every link to the OLD filename in other docs
    # would 404 in the bootstrapped repo unless we rewrite the link text
    # here too.
    "filename_rewrites": [
        ("ibx-conventions.md", "org-conventions.md"),
    ],

    # Sandbox alias slots — short-form alias-shaped tokens like "IBX_UAT" /
    # "IBX_QA" that appear in commented-out env-var examples. These are
    # alias slots, NOT brand mentions, so they map to "{{ORG_ALIAS}}_<env>"
    # — preserving the "fill in your alias here" intent without producing
    # weird "Acme Health_UAT" strings when --org-name is set.
    "alias_slot_suffixes": ["_UAT", "_QA"],
}


# ────────────────────────────────────────────────────────────────────────────
# Tokenize rules — built from PROJECT_CONFIG above. Order matters in two
# places (do not reorder unless you understand both):
#   • The workspace path contains the org alias as a substring (e.g.
#     ".../IBXMain"), so the workspace-path rule must run BEFORE the alias
#     rule.
#   • Each long-form brand literal must run BEFORE its short-form (e.g.
#     a full "Acme Health Provider Network" rule must come before a bare
#     "Acme" catchall), otherwise the short-form catchall eats the
#     long-form's prefix and the longer match never fires.
#   • The alias-slot rules (e.g. "Acme_UAT" → "{{ORG_ALIAS}}_UAT") must
#     also run BEFORE the bare-brand catchall for the same reason.
# ────────────────────────────────────────────────────────────────────────────

def _build_tokenize_rules(cfg: dict) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    # Workspace path first — it contains the alias as a substring.
    rules.append((cfg["workspace_path"], "{{WORKSPACE_PATH}}"))
    rules.append((cfg["java_home"], "{{JAVA_HOME}}"))
    # Filename rewrites for rename-and-stubbed files (cross-ref fix).
    for old, new in cfg["filename_rewrites"]:
        rules.append((old, new))
    # Long-form brand literals before the alias and bare-brand rules.
    # (Brand literals are ordered longest-first in PROJECT_CONFIG; we
    # consume all but the last here so the alias rule can slot in.)
    long_brands = cfg["org_name_literals"][:-1]
    short_brand = cfg["org_name_literals"][-1]
    for brand in long_brands:
        rules.append((brand, "{{ORG_NAME}}"))
    # Alias before the bare-brand catchall (so "IBXMain" isn't eaten).
    rules.append((cfg["org_alias"], "{{ORG_ALIAS}}"))
    # Alias-slot suffixes (short_brand + suffix) before the bare-brand
    # catchall — these are alias slots, not brand mentions.
    for suffix in cfg["alias_slot_suffixes"]:
        rules.append((short_brand + suffix, "{{ORG_ALIAS}}" + suffix))
    # Bare-brand catchall — last among brand-related rules.
    rules.append((short_brand, "{{ORG_NAME}}"))
    # Local pmd binary path (just the leading "pmd " token in commands).
    rules.append(("pmd check ", "{{PMD_PATH}} check "))
    return rules


_TOKENIZE_RULES = _build_tokenize_rules(PROJECT_CONFIG)


def _tokenize(content: str) -> str:
    """Replace source-repo-specific literals with placeholder tokens."""
    out = content
    for src_literal, placeholder in _TOKENIZE_RULES:
        out = out.replace(src_literal, placeholder)
    return out

# ────────────────────────────────────────────────────────────────────────────
# Stub bodies for files that get RENAMED + replaced with placeholder content
# (the source-repo-specific originals never end up in templates/).
# ────────────────────────────────────────────────────────────────────────────

ORG_DATA_MODEL_STUB = """\
---
description: Comprehensive guide to your org's data model — entity relationships, junction objects, business classification rules, lifecycle/termination logic, and credentialing or other domain workflows. Apply this rule when working with any of the project's primary objects so the AI agent has the schema-level context it needs before writing code.
alwaysApply: true
---

<!--
HEADS UP — This is a generated stub from `scripts/initagentrulespy/init.py`.

The original org-specific data-model rule (typically 1000+ lines documenting
each project's primary sObjects, junction objects, RecordTypes, and
lifecycle/termination logic) was deliberately replaced with this stub during
init, because each project's data model is unique and a generic version
would be misleading in a fresh project.

REPLACE this stub with your org's actual data-model documentation. Recommended
sections:

  1. Overview                — When to apply this rule + what it covers
  2. Terminology             — Project-specific glossary (e.g. "Vendor" vs "Practitioner")
  3. Core Entities           — Each primary sObject: purpose, schema link, critical fields
  4. Entity Relationship     — Mermaid diagram showing how objects connect
  5. Junction Objects        — How many-to-many relationships are modelled, RecordTypes,
                               key fields, validation rules
  6. Business Classification — Domain rules that derive from data (e.g. "active",
                               "delegated", "primary", etc.)
  7. Termination / Lifecycle — How records transition between states; soft-delete
                               vs hard-delete patterns; effective-date conventions
  8. Cascading Effects       — When changing one record automatically affects others
  9. Common Pitfalls         — Mistakes that lookups / junction objects invite
 10. Quick Reference         — RecordType IDs, key field-to-meaning cheat sheet

Cross-reference companion rules:
  - `.cursor/rules/salesforce-schema-validation.mdc` — schema-first read order
  - `.cursor/rules/sf-cli-commands.mdc`              — sf CLI reference

Once you've authored the real content, delete this comment block.
-->

# Org Data Model

## Overview

> _Replace with a 2-3 sentence summary of your org's data model and when to apply this rule._

## Core Entities

> _Document each primary sObject here._

## Entity Relationship Diagram

> _Replace with a mermaid diagram of your object relationships._

## Junction Objects

> _Document each junction here._

## Termination / Lifecycle Logic

> _Document the lifecycle and soft-delete patterns specific to your org._

## Common Pitfalls

> _Document common mistakes specific to your data model._
"""

DEFAULT_PMD_RULESET = """\
<?xml version="1.0" encoding="UTF-8"?>
<ruleset name="Apex PMD Ruleset"
         xmlns="http://pmd.sourceforge.net/ruleset/2.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://pmd.sourceforge.net/ruleset/2.0.0 https://pmd.sourceforge.io/ruleset_2_0_0.xsd">

  <description>
    Default Apex PMD ruleset, generated by scripts/initagentrulespy/init.py.
    Tune thresholds and add/remove rules per your project's conventions.
    Pairs with `.cursor/rules/pmd-ruleset.mdc` (the agent-facing usage guide).
  </description>

  <!-- ── Best practices ──────────────────────────────────────────────── -->
  <rule ref="category/apex/bestpractices.xml/ApexUnitTestClassShouldHaveAsserts"/>
  <rule ref="category/apex/bestpractices.xml/ApexUnitTestMethodShouldHaveIsTestAnnotation"/>
  <rule ref="category/apex/bestpractices.xml/ApexUnitTestShouldNotUseSeeAllDataTrue"/>
  <rule ref="category/apex/bestpractices.xml/AvoidGlobalModifier"/>
  <rule ref="category/apex/bestpractices.xml/AvoidLogicInTrigger"/>
  <rule ref="category/apex/bestpractices.xml/DebugsShouldUseLoggingLevel"/>
  <rule ref="category/apex/bestpractices.xml/UnusedLocalVariable"/>

  <!-- ── Code style ─────────────────────────────────────────────────── -->
  <rule ref="category/apex/codestyle.xml/ClassNamingConventions"/>
  <rule ref="category/apex/codestyle.xml/MethodNamingConventions"/>
  <rule ref="category/apex/codestyle.xml/IfStmtsMustUseBraces"/>
  <rule ref="category/apex/codestyle.xml/ForLoopsMustUseBraces"/>
  <rule ref="category/apex/codestyle.xml/WhileLoopsMustUseBraces"/>

  <!-- ── Performance ────────────────────────────────────────────────── -->
  <rule ref="category/apex/performance.xml/AvoidDmlStatementsInLoops"/>
  <rule ref="category/apex/performance.xml/AvoidSoqlInLoops"/>
  <rule ref="category/apex/performance.xml/AvoidSoslInLoops"/>
  <rule ref="category/apex/performance.xml/OperationWithLimitsInLoop"/>
  <rule ref="category/apex/performance.xml/EagerlyLoadedDescribeSObjectResult"/>

  <!-- ── Security ───────────────────────────────────────────────────── -->
  <rule ref="category/apex/security.xml/ApexBadCrypto"/>
  <rule ref="category/apex/security.xml/ApexCRUDViolation"/>
  <rule ref="category/apex/security.xml/ApexDangerousMethods"/>
  <rule ref="category/apex/security.xml/ApexInsecureEndpoint"/>
  <rule ref="category/apex/security.xml/ApexOpenRedirect"/>
  <rule ref="category/apex/security.xml/ApexSharingViolations"/>
  <rule ref="category/apex/security.xml/ApexSOQLInjection"/>
  <rule ref="category/apex/security.xml/ApexSuggestUsingNamedCred"/>
  <rule ref="category/apex/security.xml/ApexXSSFromEscapeFalse"/>
  <rule ref="category/apex/security.xml/ApexXSSFromURLParam"/>

  <!-- ── Error prone ────────────────────────────────────────────────── -->
  <rule ref="category/apex/errorprone.xml/ApexCSRF"/>
  <rule ref="category/apex/errorprone.xml/AvoidDirectAccessTriggerMap"/>
  <rule ref="category/apex/errorprone.xml/AvoidHardcodingId"/>
  <rule ref="category/apex/errorprone.xml/AvoidNonExistentAnnotations"/>
  <rule ref="category/apex/errorprone.xml/EmptyCatchBlock"/>
  <rule ref="category/apex/errorprone.xml/EmptyIfStmt"/>
  <rule ref="category/apex/errorprone.xml/EmptyStatementBlock"/>
  <rule ref="category/apex/errorprone.xml/EmptyTryOrFinallyBlock"/>
  <rule ref="category/apex/errorprone.xml/EmptyWhileStmt"/>
  <rule ref="category/apex/errorprone.xml/InaccessibleAuraEnabledGetter"/>
  <rule ref="category/apex/errorprone.xml/MethodWithSameNameAsEnclosingClass"/>

  <!-- ── Design (tune thresholds for your project) ──────────────────── -->
  <rule ref="category/apex/design.xml/AvoidDeeplyNestedIfStmts">
    <properties><property name="problemDepth" value="4"/></properties>
  </rule>
  <rule ref="category/apex/design.xml/CognitiveComplexity">
    <properties><property name="classReportLevel" value="120"/>
                <property name="methodReportLevel" value="20"/></properties>
  </rule>
  <rule ref="category/apex/design.xml/ExcessiveClassLength">
    <properties><property name="minimum" value="1500"/></properties>
  </rule>
  <rule ref="category/apex/design.xml/ExcessiveParameterList">
    <properties><property name="minimum" value="10"/></properties>
  </rule>
  <rule ref="category/apex/design.xml/StdCyclomaticComplexity">
    <properties><property name="reportLevel" value="20"/></properties>
  </rule>

</ruleset>
"""

ORG_CONVENTIONS_STUB = """\
# OmniStudio Conventions for This Org

<!--
HEADS UP — This is a generated stub from `scripts/initagentrulespy/init.py`.

The original org-specific OmniStudio appendix (Vlocity-namespace conventions,
project naming patterns, and any project-specific OmniScripts) was deliberately
replaced with this stub during init because each project's OmniStudio layer is
unique and a generic version would be misleading in a fresh project.

REPLACE this stub with your org's OmniStudio conventions. Recommended sections:

  1. Stack                   — Which Salesforce features are in play (Health Cloud /
                               Industries Cloud / Vlocity / etc.) and which OmniStudio
                               flavor (managed package vs unmanaged "OmniStudio for
                               Salesforce" SKU)
  2. Naming Conventions      — Prefixes for OmniScripts, IPs, DRs, FlexCards
  3. Deploy / Cache Bust     — Project-specific tweaks to the cache-bust dance in
                               `.cursor/rules/omnistudio-deploy-cache-bust.mdc`
  4. Org-specific Guardrails — Anything that the rest of `docs/omnistudio/` doesn't
                               cover and that AI agents need to know

The rest of `docs/omnistudio/` (README, dataraptors.md, omniscripts.md,
integration-procedures.md, formulas.md, patterns.md) is intentionally generic
and should NOT need editing.

Once you've authored the real content, delete this comment block.
-->

## Stack

> _Replace with your org's OmniStudio stack._

## Naming Conventions

> _Replace with your project's prefix and naming rules._

## Deploy / Cache-Bust Workflow Tweaks

> _Anything specific to your org that adjusts the canonical cache-bust dance._

## Org-Specific Guardrails

> _Anything else AI agents need to know about OmniStudio in this org._
"""

# ────────────────────────────────────────────────────────────────────────────
# SOURCES table — what to copy and how to transform each entry. This is
# the second of two source-repo-specific blocks (the first is
# PROJECT_CONFIG above). If you fork this script for another repo, expect
# to re-author the SOURCES list to match your repo's file layout — both
# the source paths (left column) and any strip-section anchor headings
# (which match literal headings in this source repo's files).
#
# Entry format:
#   (src_relative_to_repo_root, dst_relative_to_templates, transform)
#
# Transform values:
#   "verbatim"
#       -> shutil.copy
#   ("strip-section", anchor_heading, until_heading_or_None)
#       -> drop everything from anchor_heading line up to (but not including)
#          until_heading_or_None. If until_heading is None, strip to EOF.
#       NOTE: anchor / until strings must match LITERAL headings in the
#       source file. They are NOT tokenized — change them to match your
#       repo's heading text when forking.
#   ("strip-section-multi", [(anchor, until_or_None), ...])
#       -> apply multiple strip-section operations in order.
#   ("rename-and-stub", stub_content_string)
#       -> ignore source contents; write stub_content_string to dst.
# ────────────────────────────────────────────────────────────────────────────

SOURCES = [
    # ── .cursor/rules/ (10 entries; 3 excluded; 1 stubbed) ──
    (".cursor/rules/sf-cli-commands.mdc",
     ".cursor/rules/sf-cli-commands.mdc",
     "verbatim"),
    (".cursor/rules/salesforce-schema-validation.mdc",
     ".cursor/rules/salesforce-schema-validation.mdc",
     "verbatim"),
    (".cursor/rules/omnistudio-deploy-cache-bust.mdc",
     ".cursor/rules/omnistudio-deploy-cache-bust.mdc",
     "verbatim"),
    (".cursor/rules/changes-doc-mandatory.mdc",
     ".cursor/rules/changes-doc-mandatory.mdc",
     "verbatim"),
    (".cursor/rules/code-styling-format.mdc",
     ".cursor/rules/code-styling-format.mdc",
     "verbatim"),
    (".cursor/rules/pmd-ruleset.mdc",
     ".cursor/rules/pmd-ruleset.mdc",
     "verbatim"),
    (".cursor/rules/apex-test-class-creation.mdc",
     ".cursor/rules/apex-test-class-creation.mdc",
     "verbatim"),
    (".cursor/rules/test-deploy-ruleset.mdc",
     ".cursor/rules/test-deploy-ruleset.mdc",
     "verbatim"),
    (".cursor/rules/python-selenium-automation.mdc",
     ".cursor/rules/python-selenium-automation.mdc",
     "verbatim"),
    (".cursor/rules/ibx-provider-network-data-model.mdc",
     ".cursor/rules/org-data-model.mdc",
     ("rename-and-stub", ORG_DATA_MODEL_STUB)),

    # ── .claude/ (6 entries; settings.local.json + skills/omnistudio excluded) ──
    (".claude/settings.json",
     ".claude/settings.json",
     "verbatim"),
    (".claude/skills/changes-documentation/SKILL.md",
     ".claude/skills/changes-documentation/SKILL.md",
     "verbatim"),
    (".claude/skills/schema-lookup/SKILL.md",
     ".claude/skills/schema-lookup/SKILL.md",
     ("strip-section",
      "## Org-specific gotchas (IBX Provider Network)",
      None)),
    (".claude/skills/omnistudio-deploy-cache-bust/SKILL.md",
     ".claude/skills/omnistudio-deploy-cache-bust/SKILL.md",
     "verbatim"),
    (".claude/skills/retrieve-before-edit/SKILL.md",
     ".claude/skills/retrieve-before-edit/SKILL.md",
     "verbatim"),
    (".claude/skills/deploy-with-tests/SKILL.md",
     ".claude/skills/deploy-with-tests/SKILL.md",
     "verbatim"),

    # ── docs/ (9 entries) ──
    ("docs/sf-org-mirror-retrieve.md",
     "docs/sf-org-mirror-retrieve.md",
     "verbatim"),
    ("docs/schema-quickref.md",
     "docs/schema-quickref.md",
     ("strip-section-multi", [
         ("## High-traffic objects for IBX Provider Network",
          "## Record-type identifiers"),
         ("## Common field cheat sheet",
          "## Regenerating the schema"),
     ])),
    ("docs/omnistudio/README.md",
     "docs/omnistudio/README.md",
     "verbatim"),
    ("docs/omnistudio/dataraptors.md",
     "docs/omnistudio/dataraptors.md",
     "verbatim"),
    ("docs/omnistudio/omniscripts.md",
     "docs/omnistudio/omniscripts.md",
     "verbatim"),
    ("docs/omnistudio/integration-procedures.md",
     "docs/omnistudio/integration-procedures.md",
     "verbatim"),
    ("docs/omnistudio/formulas.md",
     "docs/omnistudio/formulas.md",
     "verbatim"),
    ("docs/omnistudio/patterns.md",
     "docs/omnistudio/patterns.md",
     "verbatim"),
    ("docs/omnistudio/ibx-conventions.md",
     "docs/omnistudio/org-conventions.md",
     ("rename-and-stub", ORG_CONVENTIONS_STUB)),

    # ── changes/_templates/ (4 entries) ──
    ("changes/_templates/_TEMPLATE_bugfix.md",
     "changes/_templates/_TEMPLATE_bugfix.md",
     "verbatim"),
    ("changes/_templates/_TEMPLATE_refactor.md",
     "changes/_templates/_TEMPLATE_refactor.md",
     "verbatim"),
    ("changes/_templates/_TEMPLATE_story.md",
     "changes/_templates/_TEMPLATE_story.md",
     "verbatim"),
    # Generic retrieve-audit template. Paired with docs/sf-org-mirror-retrieve.md
    # (also in this kit). Referenced by .cursor/rules/changes-doc-mandatory.mdc;
    # without it the rule would point at a missing file in the bootstrapped repo.
    ("changes/_templates/_TEMPLATE_retrieve.md",
     "changes/_templates/_TEMPLATE_retrieve.md",
     "verbatim"),

    # ── .vscode/ (1 entry; extensions.json + launch.json intentionally
    # excluded — leave those to per-project preference).
    (".vscode/settings.json", ".vscode/settings.json", "verbatim"),

    # ── root + manifest/fullpackage/ + config/ (14 entries) ──
    # MCP config goes to TWO destinations from the same source file so both
    # Claude Code (reads project-root `.mcp.json`) and Cursor (reads
    # `.cursor/mcp.json`) get the same server set. The Cursor copy drops
    # the leading dot in the filename.
    (".mcp.json", ".mcp.json", "verbatim"),
    (".mcp.json", ".cursor/mcp.json", "verbatim"),
    ("manifest/fullpackage/fullpackage-automation.xml",
     "manifest/fullpackage/fullpackage-automation.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-code.xml",
     "manifest/fullpackage/fullpackage-code.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-community.xml",
     "manifest/fullpackage/fullpackage-community.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-content.xml",
     "manifest/fullpackage/fullpackage-content.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-integration.xml",
     "manifest/fullpackage/fullpackage-integration.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-omnistudio.xml",
     "manifest/fullpackage/fullpackage-omnistudio.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-reports.xml",
     "manifest/fullpackage/fullpackage-reports.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-schema.xml",
     "manifest/fullpackage/fullpackage-schema.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-security.xml",
     "manifest/fullpackage/fullpackage-security.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-translations.xml",
     "manifest/fullpackage/fullpackage-translations.xml", "verbatim"),
    ("manifest/fullpackage/fullpackage-ui.xml",
     "manifest/fullpackage/fullpackage-ui.xml", "verbatim"),
    # config/pmd-ruleset.xml is referenced by the rules but not present in
    # this source repo. Generate a sensible Apex default so users have a
    # working starting point; they can tune thresholds and add/remove rules
    # per their project.
    ("config/pmd-ruleset.xml", "config/pmd-ruleset.xml",
     ("rename-and-stub", DEFAULT_PMD_RULESET)),
]


# ────────────────────────────────────────────────────────────────────────────
# Transform implementations (small + obvious).
# ────────────────────────────────────────────────────────────────────────────

def transform_verbatim(src: Path) -> bytes:
    # All source files in our SOURCES list are text (md/mdc/json/xml).
    # Tokenize before encoding back to bytes so personal info /
    # source-repo-specific literals never reach templates/.
    return _tokenize(src.read_text(encoding="utf-8")).encode("utf-8")


def _strip_one(text: str, anchor: str, until: str | None) -> str:
    """Drop everything from `anchor` line (inclusive) up to (but not including) `until`.

    If `until` is None, drop to EOF.
    Anchor and until are matched as `line.lstrip().startswith(value)` so the
    user can pass e.g. "## Foo" without worrying about trailing whitespace.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.lstrip().rstrip("\n").startswith(anchor):
            # Drop from here.
            j = i + 1
            if until is None:
                # Strip to EOF.
                # Trim trailing blank/separator lines from `out` for cleanliness.
                while out and out[-1].strip() in ("", "---"):
                    out.pop()
                # Append a single trailing newline if needed.
                if out and not out[-1].endswith("\n"):
                    out.append("\n")
                return "".join(out)
            while j < n and not lines[j].lstrip().rstrip("\n").startswith(until):
                j += 1
            # Skip lines i .. j-1 (j is the `until` line which we keep).
            i = j
            continue
        out.append(line)
        i += 1
    return "".join(out)


def transform_strip_section(src: Path, anchor: str, until: str | None) -> bytes:
    text = src.read_text(encoding="utf-8")
    return _tokenize(_strip_one(text, anchor, until)).encode("utf-8")


def transform_strip_section_multi(src: Path, ops: list[tuple[str, str | None]]) -> bytes:
    text = src.read_text(encoding="utf-8")
    for anchor, until in ops:
        text = _strip_one(text, anchor, until)
    return _tokenize(text).encode("utf-8")


def transform_rename_and_stub(_src: Path, stub: str) -> bytes:
    # Stub bodies are hand-authored as generic placeholder content, but run
    # them through _tokenize anyway so a future maintainer can't accidentally
    # bake a source-repo-specific literal into a stub.
    return _tokenize(stub).encode("utf-8")


# ────────────────────────────────────────────────────────────────────────────
# Sync driver.
# ────────────────────────────────────────────────────────────────────────────

def find_repo_root(start: Path) -> Path:
    """Walk up from `start` to find the source repo root (looks for sfdx-project.json)."""
    cur = start.resolve()
    for _ in range(10):
        if (cur / "sfdx-project.json").exists():
            return cur
        cur = cur.parent
    raise RuntimeError(
        f"Could not find source repo root (sfdx-project.json) starting from {start}"
    )


def apply_transform(src: Path, transform) -> bytes:
    if transform == "verbatim":
        return transform_verbatim(src)
    if isinstance(transform, tuple):
        kind = transform[0]
        if kind == "strip-section":
            _, anchor, until = transform
            return transform_strip_section(src, anchor, until)
        if kind == "strip-section-multi":
            _, ops = transform
            return transform_strip_section_multi(src, ops)
        if kind == "rename-and-stub":
            _, stub = transform
            return transform_rename_and_stub(src, stub)
    raise ValueError(f"Unknown transform: {transform!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Verify templates/ matches what _sync.py would produce; "
                             "exit 1 if drift detected (CI mode).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print every file processed.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    templates_dir = script_dir / "templates"
    repo_root = find_repo_root(script_dir)

    print(f"Repo root:     {repo_root}")
    print(f"Templates dir: {templates_dir}")
    print(f"Sources:       {len(SOURCES)} entries")
    print()

    drift_count = 0
    written_count = 0
    unchanged_count = 0
    missing_count = 0

    for src_rel, dst_rel, transform in SOURCES:
        src = repo_root / src_rel
        dst = templates_dir / dst_rel

        # For rename-and-stub the source doesn't need to exist; the stub is
        # baked in. But still warn so the maintainer notices if the source
        # file was renamed or removed without updating SOURCES.
        if not src.exists() and not (
            isinstance(transform, tuple) and transform[0] == "rename-and-stub"
        ):
            print(f"  ✗ MISSING source: {src_rel}")
            missing_count += 1
            continue

        new_bytes = apply_transform(src, transform)
        old_bytes = dst.read_bytes() if dst.exists() else None

        if old_bytes == new_bytes:
            unchanged_count += 1
            if args.verbose:
                print(f"  · unchanged: {dst_rel}")
            continue

        # Drift detected.
        if args.check:
            drift_count += 1
            print(f"  ✗ DRIFT: {dst_rel}")
            continue

        # Apply the change.
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(new_bytes)
        written_count += 1
        verb = "updated" if old_bytes is not None else "created"
        print(f"  ✓ {verb}:  {dst_rel}")

    print()
    print("─" * 60)
    if args.check:
        if drift_count:
            print(f"DRIFT: {drift_count} file(s) out of date in templates/.")
            print("Run `python3 scripts/initagentrulespy/_sync.py` to update.")
            return 1
        if missing_count:
            print(f"MISSING: {missing_count} source file(s) — fix SOURCES table.")
            return 1
        print(f"OK: {unchanged_count} file(s) up to date.")
        return 0

    summary = f"{written_count} written, {unchanged_count} unchanged"
    if missing_count:
        summary += f", {missing_count} missing source files"
    print(summary)
    return 0 if missing_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
