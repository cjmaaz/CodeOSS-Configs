#!/bin/bash
# Drives a whole pass from an order file. Stops at the first phase that fails its gate.
#
#   usage: run-all.sh <order-file> [start-from-logname]
#
# Order row: logname <TAB> wait_MINUTES <TAB> file_floor|- <TAB> sf args
# Rows beginning with # are comments (that is how the generator ships a row that needs
# a human decision before it fires).
set -u

: "${ORG_ALIAS:?export ORG_ALIAS=<your-alias> first}"
ORDER="${1:?order file required}"; SKIP_TO="${2:-}"
EXEC="$(dirname "$0")/run-phase.sh"
[ -f "$ORDER" ] || { echo "ABORT: no such order file: $ORDER"; exit 1; }
[ -f "$EXEC" ]  || { echo "ABORT: cannot find run-phase.sh beside $0"; exit 1; }

# A SKIP_TO matching no row would skip every phase and still report completion —
# a partial mirror masquerading as a full one. Validate against real phase names only.
if [ -n "$SKIP_TO" ] && ! grep -v '^#' "$ORDER" | cut -f1 | grep -qxF "$SKIP_TO"; then
  echo "ABORT: '$SKIP_TO' is not a phase name in $ORDER. Valid names:"
  grep -v '^#' "$ORDER" | cut -f1 | grep -v '^$' | sed 's/^/  /'
  exit 1
fi

started=0
ran=0
# `|| [ -n "$name" ]` so a final row with no trailing newline is not silently dropped.
while IFS=$'\t' read -r name wait floor args || [ -n "${name:-}" ]; do
  [ -z "${name:-}" ] && continue
  case "$name" in \#*) continue;; esac
  if [ -n "$SKIP_TO" ] && [ "$started" -eq 0 ]; then
    if [ "$name" = "$SKIP_TO" ]; then started=1; else echo "-- skip $name"; continue; fi
  fi
  # shellcheck disable=SC2086  # args are intentionally word-split; rows may not contain spaces
  bash "$EXEC" "$name" "$wait" "$floor" $args
  rc=$?
  if [ $rc -ne 0 ]; then
    echo ""
    echo "STOPPED at '$name' (exit $rc). Nothing after this ran."
    echo "Fix, then resume with: $0 $ORDER $name"
    exit $rc
  fi
  ran=$((ran + 1))
done < "$ORDER"

# Zero phases run is never success: it means every row was a comment, the file was
# effectively empty, or the resume point was the last row.
if [ "$ran" -eq 0 ]; then
  echo "ABORT: no phase ran. Refusing to report completion."
  exit 1
fi
echo "ALL_PHASES_COMPLETE $(basename "$ORDER")  phases_run=$ran"
