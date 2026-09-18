#!/bin/bash
# Generates this run's order files and manifests from the measured footprint.
#
#   usage: make-order-files.sh [--api-version N] [--cap N]
#
# Reads   .retrieve-logs/current/_footprint.tsv      (count <TAB> Type, from Phase 0.3)
#         .retrieve-logs/current/_exclusions.tsv     (Type <TAB> reason, optional)
# Writes  .retrieve-logs/current/order-phase1.tsv    bundled small-type shards
#         .retrieve-logs/current/order-phase2.tsv    solo heavy types, ordered
#         .retrieve-logs/current/manifests/*.xml     one manifest per shard
#         .retrieve-logs/current/_plan-notes.txt     every decision and its reason
#
# Everything it emits is DERIVED from this org's counts. Nothing is transcribed, so no
# other org's numbers can leak in, and the outputs live in the gitignored log dir so
# they are never committed.
set -u
set -o pipefail

L=.retrieve-logs/current
FOOT="$L/_footprint.tsv"
EXCL="$L/_exclusions.tsv"
MAN="$L/manifests"
NOTES="$L/_plan-notes.txt"

# API version comes from the project, not from this script, so a generated manifest can
# never disagree with what the project deploys and retrieves with.
API_VERSION=""
# Per-call file cap. Left as a tunable rather than a constant because a phase should be
# sized against the cap your API version actually enforces, not against a remembered one.
CAP=10000

while [ $# -gt 0 ]; do
  case "$1" in
    --api-version) API_VERSION="${2:?}"; shift 2;;
    --cap)         CAP="${2:?}"; shift 2;;
    *) echo "usage: $0 [--api-version N] [--cap N]"; exit 1;;
  esac
done

[ -d force-app ] || { echo "ABORT: no ./force-app — run this from the repo root."; exit 1; }

if [ -z "$API_VERSION" ]; then
  API_VERSION=$(jq -r '.sourceApiVersion // empty' sfdx-project.json 2>/dev/null)
fi
[ -n "$API_VERSION" ] || { echo "ABORT: no sourceApiVersion in sfdx-project.json — pass --api-version N"; exit 1; }
[ -s "$FOOT" ]   || { echo "ABORT: no footprint at $FOOT — run Phase 0.3 first."; exit 1; }
case "$API_VERSION" in ''|*[!0-9.]*) echo "ABORT: bad --api-version '$API_VERSION'"; exit 1;; esac

# A footprint with unresolved errors is not a sizing input: a failed call is
# indistinguishable from an empty type, so a phase would be sized against a false zero.
if [ -s "$L/_footprint-errors.tsv" ]; then
  echo "ABORT: $L/_footprint-errors.tsv is non-empty — resolve those types before generating."
  cat "$L/_footprint-errors.tsv"
  exit 1
fi

mkdir -p "$MAN"
: > "$NOTES"
note() { printf '%s\n' "$*" >> "$NOTES"; }

# --- Footprint parse + validation -----------------------------------------------------
# Take exactly the first two fields. A footprint carrying extra columns (an earlier
# format, an annotation like a managed-vs-unmanaged total) would otherwise fold that
# text into the type name and emit it as a manifest <name>, producing a manifest that
# sf rejects — or, worse, one that partially works while silently missing types.
NORM="$L/_footprint-normalized.tsv"
awk -F'\t' 'NF >= 2 { print $1 "\t" $2 }' "$FOOT" > "$NORM"

# Metadata type names are alphanumeric. Anything else means the file is not the
# two-column footprint this expects, and a plan built from it cannot be trusted.
BAD=$(awk -F'\t' '$2 !~ /^[A-Za-z][A-Za-z0-9]*$/ { print "    " $2 }' "$NORM")
if [ -n "$BAD" ]; then
  echo "ABORT: $FOOT has entries that are not metadata type names:"
  printf '%s\n' "$BAD" | head -10
  echo "  Expected two tab-separated columns: <count> <TAB> <Type>."
  echo "  Re-run Phase 0.3 discovery rather than adapting an older footprint by hand."
  exit 1
fi
if [ "$(awk 'END{print NR}' "$NORM")" != "$(awk 'NF{c++} END{print c+0}' "$FOOT")" ]; then
  echo "ABORT: $FOOT has non-empty rows with fewer than two columns — re-run Phase 0.3."
  exit 1
fi

note "Plan generated $(date -u +%FT%TZ)"
note "Footprint: $FOOT   API version: $API_VERSION   per-call file cap: $CAP"
note ""

# --- Type classification -------------------------------------------------------------
# Files per component. A bundle type multiplies: the cap counts FILES, not components,
# so a few thousand bundles can sit near the cap while far more single-file components
# do not. Anything not listed here is treated as 1 file per component.
files_per_component() {
  case "$1" in
    LightningComponentBundle) echo 6;;   # js + html + meta + css + tests, varies
    AuraDefinitionBundle)     echo 5;;
    ExperienceBundle|StaticResource|ContentAsset|Document) echo 2;;
    ApexClass|ApexTrigger|ApexComponent|ApexPage) echo 2;;  # source + -meta.xml
    *) echo 1;;
  esac
}

# Types whose per-record cost dominates wall-clock regardless of count. These go LAST:
# slowest each, and the cheapest phase to retry when something fails.
is_slow_per_record() {
  case "$1" in Profile|PermissionSet|PermissionSetGroup) return 0;; *) return 1;; esac
}

# Parent -> child. The child's files land inside folders the parent creates, so the
# parent must run first, and the child then legitimately writes far less than its own
# total because the parent already decomposed those files.
child_parent() {
  case "$1" in
    CustomField|RecordType|ValidationRule|ListView|WebLink|CompactLayout|FieldSet|BusinessProcess|SharingReason|Index)
      echo CustomObject;;
    WorkflowAlert|WorkflowFieldUpdate|WorkflowOutboundMessage|WorkflowTask|WorkflowRule|WorkflowSend|WorkflowKnowledgePublish)
      echo Workflow;;
    SharingCriteriaRule|SharingOwnerRule|SharingTerritoryRule|SharingGuestRule)
      echo SharingRules;;
    AssignmentRule)   echo AssignmentRules;;
    AutoResponseRule) echo AutoResponseRules;;
    EscalationRule)   echo EscalationRules;;
    MatchingRule)     echo MatchingRules;;
    CustomLabel)      echo CustomLabels;;
    *) echo "";;
  esac
}

# A container and its child decompose into the SAME file, so whichever runs later
# rewrites that file with only its own members and silently drops the rest. These
# containers therefore need a repair phase after any child-type phase.
is_container() {
  case "$1" in
    SharingRules|Workflow|CustomLabels|MatchingRules|AssignmentRules|AutoResponseRules|EscalationRules) return 0;;
    *) return 1;;
  esac
}

lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# --- Load exclusions -----------------------------------------------------------------
EXCLUDED=""
if [ -s "$EXCL" ]; then
  note "Exclusions (declared in $(basename "$EXCL")):"
  while IFS=$'\t' read -r xt xr || [ -n "${xt:-}" ]; do
    [ -z "${xt:-}" ] && continue
    case "$xt" in \#*) continue;; esac
    EXCLUDED="$EXCLUDED $xt"
    if [ -z "${xr:-}" ]; then
      # An unexplained exclusion is exactly what Gate B is told to attack, so refuse
      # to bake one into the plan.
      echo "ABORT: '$xt' is excluded with no reason. Add a reason after a TAB."
      exit 1
    fi
    note "  $xt — $xr"
  done < "$EXCL"
  note ""
else
  note "No exclusions declared. Every requested+supported type is in the plan."
  note ""
fi
is_excluded() { case " $EXCLUDED " in *" $1 "*) return 0;; *) return 1;; esac; }

# --- Size every type -----------------------------------------------------------------
# _sized.tsv: files <TAB> count <TAB> Type   (files = count x files-per-component)
SIZED="$L/_sized.tsv"
: > "$SIZED"
ZERO_TYPES=""
while IFS=$'\t' read -r n T || [ -n "${T:-}" ]; do
  [ -z "${T:-}" ] && continue
  case "$n" in ''|*[!0-9]*) note "SKIP $T — non-numeric count '$n' in footprint"; continue;; esac
  if is_excluded "$T"; then continue; fi
  if [ "$n" -eq 0 ]; then
    # Zero is not proof of emptiness. Carry it as enumerated-empty for the audit doc
    # rather than either retrieving it blindly or claiming it was covered.
    ZERO_TYPES="$ZERO_TYPES $T"
    continue
  fi
  printf '%s\t%s\t%s\n' "$(( n * $(files_per_component "$T") ))" "$n" "$T" >> "$SIZED"
done < "$NORM"

[ -s "$SIZED" ] || { echo "ABORT: nothing left to retrieve after exclusions."; exit 1; }

if [ -n "$ZERO_TYPES" ]; then
  note "Enumerated-empty (count 0 — record as such, NOT as covered):"
  for T in $ZERO_TYPES; do note "  $T"; done
  note ""
fi

# --- Split solo vs bundled -----------------------------------------------------------
# A type goes solo when its own file estimate is a material fraction of the cap, or when
# it is slow per record, or when it participates in a parent/child or container relation
# whose ordering a shard cannot express.
SOLO_THRESHOLD=$(( CAP / 10 ))
note "Solo threshold: ${SOLO_THRESHOLD} estimated files (cap/10). Above it, a type runs alone."
note ""

SOLO="$L/_solo.tsv"; BUNDLE="$L/_bundle.tsv"
: > "$SOLO"; : > "$BUNDLE"
while IFS=$'\t' read -r files n T; do
  reason=""
  [ "$files" -ge "$SOLO_THRESHOLD" ] && reason="est ${files} files >= ${SOLO_THRESHOLD}"
  is_slow_per_record "$T" && reason="${reason:+$reason; }slow per record"
  [ -n "$(child_parent "$T")" ] && reason="${reason:+$reason; }child of $(child_parent "$T")"
  is_container "$T" && reason="${reason:+$reason; }container type"
  # A parent of any solo child must itself be solo, so it can be ordered before it.
  while IFS=$'\t' read -r _f _n other; do
    [ "$(child_parent "$other")" = "$T" ] && reason="${reason:+$reason; }parent of $other"
  done < "$SIZED"
  if [ -n "$reason" ]; then
    printf '%s\t%s\t%s\t%s\n' "$files" "$n" "$T" "$reason" >> "$SOLO"
  else
    printf '%s\t%s\t%s\n' "$files" "$n" "$T" >> "$BUNDLE"
  fi
done < "$SIZED"

# --- Phase 1: bundle the remainder into cap-safe shards ------------------------------
# Ascending, so the lightest shards run first and a fatal error surfaces in the first
# minutes rather than after the heavy work.
: > "$L/order-phase1.tsv"
note "Phase 1 — bundled shards (ascending, each summed under the cap):"
shard=0; sum=0; members=""
flush_shard() {
  [ -z "$members" ] && return 0
  shard=$((shard + 1))
  local name file wait floor
  name=$(printf '%02d-shard' "$shard")
  file="$MAN/${name}.xml"
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<Package xmlns="http://soap.sforce.com/2006/04/metadata">'
    for m in $members; do
      printf '  <types>\n    <members>*</members>\n    <name>%s</name>\n  </types>\n' "$m"
    done
    printf '  <version>%s</version>\n' "$API_VERSION"
    echo '</Package>'
  } > "$file"
  # Wait scales with the shard's file estimate; a flat value is either wasteful or a
  # premature timeout. Floor is a fraction of the estimate, since a refresh rewrites
  # only what changed and a full-estimate floor would fail every healthy run.
  wait=$(( sum / 400 + 5 )); [ "$wait" -gt 120 ] && wait=120
  floor=$(( sum / 20 )); [ "$floor" -lt 1 ] && floor=1
  printf '%s\t%s\t%s\t--manifest %s\n' "$name" "$wait" "$floor" "$file" >> "$L/order-phase1.tsv"
  note "  $name  est_files=$sum  wait=${wait}m  floor=$floor  types:$(printf ' %s' $members)"
  sum=0; members=""
}
if [ -s "$BUNDLE" ]; then
  while IFS=$'\t' read -r files n T; do
    # Keep each shard well under the cap; half the cap leaves room for the estimate
    # being wrong, which it will be, since files-per-component is an average.
    if [ $(( sum + files )) -gt $(( CAP / 2 )) ] && [ -n "$members" ]; then flush_shard; fi
    members="$members $T"; sum=$(( sum + files ))
  done < <(sort -n "$BUNDLE")
  flush_shard
else
  note "  (none — every type qualified for a solo phase)"
fi
note ""

# --- Phase 2: solo types, ordered ----------------------------------------------------
# Ordering, in priority order:
#   1. the cap-exposed type first, so a cap failure costs one short phase not the pass
#   2. ascending file estimate otherwise, so failures surface early
#   3. each parent immediately before its child
#   4. slow-per-record types last
#   5. a container-repair phase after every colliding child-type phase
ORDERED="$L/_solo-ordered.txt"
: > "$ORDERED"

# Heaviest type with real cap exposure goes first, so a cap failure costs one short
# phase instead of the whole pass. It must be a type that CAN be first: never a child
# (its parent has to precede it) and never a slow-per-record type (those go last).
CAP_EXPOSED=""
while IFS=$'\t' read -r files n T reason; do
  is_slow_per_record "$T" && continue
  [ -n "$(child_parent "$T")" ] && continue
  CAP_EXPOSED="$T"; break
done < <(sort -rn "$SOLO")
[ -n "$CAP_EXPOSED" ] && echo "$CAP_EXPOSED" >> "$ORDERED"

# Then everything else, ascending, excluding slow types and the promoted one.
while IFS=$'\t' read -r files n T reason; do
  [ "$T" = "$CAP_EXPOSED" ] && continue
  is_slow_per_record "$T" && continue
  echo "$T" >> "$ORDERED"
done < <(sort -n "$SOLO")

# Then the slow-per-record types, ascending.
while IFS=$'\t' read -r files n T reason; do
  is_slow_per_record "$T" && echo "$T" >> "$ORDERED"
done < <(sort -n "$SOLO")

# Enforce parent-immediately-before-child by hoisting each parent to just above its child.
python3 - "$ORDERED" <<'PY'
import sys
path = sys.argv[1]
order = [l.strip() for l in open(path) if l.strip()]
PARENTS = {
    **{c: "CustomObject" for c in ("CustomField","RecordType","ValidationRule","ListView","WebLink",
                                   "CompactLayout","FieldSet","BusinessProcess","SharingReason","Index")},
    **{c: "Workflow" for c in ("WorkflowAlert","WorkflowFieldUpdate","WorkflowOutboundMessage",
                               "WorkflowTask","WorkflowRule","WorkflowSend","WorkflowKnowledgePublish")},
    **{c: "SharingRules" for c in ("SharingCriteriaRule","SharingOwnerRule","SharingTerritoryRule",
                                   "SharingGuestRule")},
    "AssignmentRule": "AssignmentRules", "AutoResponseRule": "AutoResponseRules",
    "EscalationRule": "EscalationRules", "MatchingRule": "MatchingRules",
    "CustomLabel": "CustomLabels",
}
changed = True
while changed:                      # repeat: hoisting one parent can displace another
    changed = False
    for child, parent in PARENTS.items():
        if child in order and parent in order:
            ci, pi = order.index(child), order.index(parent)
            if pi > ci:
                order.insert(ci, order.pop(pi))
                changed = True
open(path, "w").write("".join(f"{t}\n" for t in order))
PY

# For each container, the last of its children in execution order — the only point at
# which a repair phase is worth emitting.
last_child_of() {
  local container="$1" last=""
  while read -r candidate; do
    [ "$(child_parent "$candidate")" = "$container" ] && last="$candidate"
  done < "$ORDERED"
  printf '%s' "$last"
}

: > "$L/order-phase2.tsv"
: > "$L/_cap-blocked.tsv"
note "Phase 2 — solo types, in execution order:"
[ -n "$CAP_EXPOSED" ] && note "  (${CAP_EXPOSED} promoted to first: highest cap exposure, so a cap failure is cheap)"
NN=20
while read -r T; do
  NN=$((NN + 1))
  files=$(awk -F'\t' -v t="$T" '$3==t{print $1}' "$SOLO")
  n=$(awk -F'\t' -v t="$T" '$3==t{print $2}' "$SOLO")
  reason=$(awk -F'\t' -v t="$T" '$3==t{print $4}' "$SOLO")
  wait=$(( files / 400 + 5 )); [ "$wait" -gt 120 ] && wait=120
  is_slow_per_record "$T" && wait=$(( wait < 15 ? 15 : wait ))
  parent=$(child_parent "$T")
  if [ -n "$parent" ] && grep -qx "$parent" "$ORDERED"; then
    # The parent phase already decomposed this child's files, so this phase legitimately
    # writes only what changed — a small batch, not a proportion of the type's size.
    # A floor scaled to the child's own total would fail every healthy run.
    floor=$(( n / 50 )); [ "$floor" -lt 1 ] && floor=1
    note "  $(printf '%02d' $NN)-$(lc "$T")  count=$n  floor=$floor (LOW: $parent runs first and already writes these files)  wait=${wait}m"
  else
    floor=$(( files / 20 )); [ "$floor" -lt 1 ] && floor=1
    note "  $(printf '%02d' $NN)-$(lc "$T")  count=$n  est_files=$files  floor=$floor  wait=${wait}m  [$reason]"
  fi

  # --- Cap handling -----------------------------------------------------------------
  # Over the cap, one call cannot succeed, so shipping a live row just buys a guaranteed
  # failure after a long wait. Ship it COMMENTED, and make the required fallback loud
  # here rather than something to discover mid-incident.
  if [ "$files" -gt "$CAP" ]; then
    printf '%s\t%s\t%s\n' "$T" "$files" "$CAP" >> "$L/_cap-blocked.tsv"
    printf '#%s-%s\t%s\t%s\t--metadata %s\t# OVER CAP (est %s files > %s) — shard it, see runbook Cap fallback\n' \
      "$(printf '%02d' $NN)" "$(lc "$T")" "$wait" "$floor" "$T" "$files" "$CAP" >> "$L/order-phase2.tsv"
    note "    !! ACTION REQUIRED: est ${files} files exceeds the ${CAP} cap. Row is COMMENTED OUT."
    note "       Split $T by a parent axis into enumerated shards and add those rows, each"
    note "       with its own floor. Uncommenting this row as-is will fail after ${wait}m."
    if [ -n "$parent" ] && is_container "$parent"; then
      note "       When you add those shards, also add a ${parent} repair phase after the last"
      note "       one — the shards share a file with ${parent} and will truncate it."
    fi
    continue
  fi
  if [ "$files" -gt $(( CAP * 8 / 10 )) ]; then
    note "    ! cap proximity: est ${files} files is over 80% of the ${CAP} cap. If it fails,"
    note "      shard it per the runbook's Cap fallback — decide the split axis NOW, not later."
  fi

  printf '%s-%s\t%s\t%s\t--metadata %s\n' "$(printf '%02d' $NN)" "$(lc "$T")" "$wait" "$floor" "$T" \
    >> "$L/order-phase2.tsv"

  # Container repair: if this child collides with a container that ran earlier, the
  # container's file was just rewritten with only this child's members. Re-retrieve it
  # to restore the union — but only after the LAST child of that container, since an
  # earlier repair would just be truncated again by the next sibling. Nothing reads
  # the file mid-pass, so one repair at the end is both sufficient and cheaper.
  if [ -n "$parent" ] && is_container "$parent" && [ "$T" = "$(last_child_of "$parent")" ]; then
    NN=$((NN + 1))
    printf '%s-%s-repair\t%s\t-\t--metadata %s\n' "$(printf '%02d' $NN)" "$(lc "$parent")" 10 "$parent" \
      >> "$L/order-phase2.tsv"
    note "  $(printf '%02d' $NN)-$(lc "$parent")-repair  floor=- (repair)  re-retrieves $parent: it shares a file with $T and was truncated to $T's members"
  fi
done < "$ORDERED"
note ""

# --- Summary -------------------------------------------------------------------------
count_rows() { awk '!/^#/ && NF' "$1" 2>/dev/null | wc -l | tr -d ' '; }
p1=$(count_rows "$L/order-phase1.tsv")
p2=$(count_rows "$L/order-phase2.tsv")
note "Generated: ${p1} Phase 1 rows, ${p2} Phase 2 rows, $(ls -1 "$MAN" 2>/dev/null | wc -l | tr -d ' ') manifests."
note ""
note "Floors are DERIVED from this org's counts and are estimates. A phase that comes"
note "up short is a signal to diagnose, not to lower the floor — and any floor you do"
note "change belongs here, in this file, where Gate B will read it."

echo "Wrote:"
echo "  $L/order-phase1.tsv   ($p1 rows)"
echo "  $L/order-phase2.tsv   ($p2 rows)"
echo "  $MAN/                 ($(ls -1 "$MAN" 2>/dev/null | wc -l | tr -d ' ') manifests)"
echo "  $NOTES"

# Surface cap-blocked types on stdout too. Buried in a notes file, this is exactly the
# kind of thing that gets discovered mid-incident instead of before the run.
if [ -s "$L/_cap-blocked.tsv" ]; then
  echo ""
  echo "!! $(awk 'END{print NR}' "$L/_cap-blocked.tsv") type(s) exceed the per-call cap and are COMMENTED OUT of the plan:"
  while IFS=$'\t' read -r T files cap; do
    printf '     %-32s est %s files > cap %s\n' "$T" "$files" "$cap"
  done < "$L/_cap-blocked.tsv"
  echo "   They will NOT be retrieved until you shard them (runbook: Cap fallback)."
fi

echo ""
echo "Read $NOTES and confirm the ordering before running anything."
