#!/bin/bash
# Single-flight, wait-respecting, failure-gated retrieve executor.
#
# usage: run-phase.sh <logname> <wait_minutes> <expected_min_files|-> <sf args...>
#
# Must be invoked from the repo root: every path below is relative to it.
#
#   wait_minutes        -- sf's --wait is MINUTES, not seconds. Never pass seconds.
#   expected_min_files  -- integer floor for files this phase must write, or "-" to skip
#                          the volume check. "Status: Succeeded" is not evidence that
#                          anything was retrieved; the floor is what makes it falsifiable.
#
# The target org is read from $ORG_ALIAS and validated against the Org Id that Phase 0
# pinned in .retrieve-logs/current/_org-id.txt. Nothing is hardcoded, so the same script
# works against any org without editing.
#
# exit 0 = Succeeded and volume floor met      exit 2 = gate failed (do not advance)
# exit 1 = precondition/guard abort            exit 3 = lock refused (another run in flight)
set -u
set -o pipefail

L=.retrieve-logs/current
LOCKDIR="$L/.retrieve.lock.d"
PIN="$L/_org-id.txt"

: "${ORG_ALIAS:?ORG_ALIAS is not set. Run: export ORG_ALIAS=<your-alias>}"
[ $# -ge 4 ] || { echo "usage: $0 <logname> <wait_minutes> <expected_min_files|-> <sf args...>"; exit 1; }

NAME="$1"; WAIT_MIN="$2"; FLOOR="$3"; shift 3
LOG="$L/${NAME}.log"

[ -d force-app ] || { echo "ABORT: no ./force-app — run this from the repo root."; exit 1; }

case "$WAIT_MIN" in ''|*[!0-9]*) echo "ABORT: wait must be integer MINUTES, got '$WAIT_MIN'"; exit 1;; esac
# --wait is minutes. A seconds-style value silently turns a 20-minute wait into a
# 20-hour one and removes the run's only timeout, so a hung phase never fails.
[ "$WAIT_MIN" -gt 120 ] && { echo "ABORT: wait ${WAIT_MIN}min > 2h — looks like seconds were passed"; exit 1; }
# A non-integer floor (e.g. a thousands separator) makes the `-lt` test below error to
# stderr and evaluate false, silently disabling the volume gate. Reject it up front.
case "$FLOOR" in -) ;; ''|*[!0-9]*) echo "ABORT: floor must be an integer or '-', got '$FLOOR'"; exit 1;; esac

# The log dir is gitignored, so a fresh clone has none. A non-recursive mkdir of the lock
# would then fail and be misreported below as "another retrieve holds the lock".
mkdir -p "$L" || { echo "ABORT: cannot create $L"; exit 1; }

# --- Org identity guard: fails closed on sf error, null result, or lost auth ----------
# The alias is usually also the shell's default org, so a dropped -o is undetectable by
# an alias check alone. Compare against the Org Id Phase 0 pinned for THIS run.
if [ ! -s "$PIN" ]; then
  echo "ABORT: no pinned Org Id at $PIN"
  echo "       Run Phase 0.1/0.2 first — an unpinned run has no wrong-org protection."
  exit 1
fi
EXPECTED_ORG_ID=$(tr -d '[:space:]' < "$PIN")
ORG_ID=$(sf org display -o "$ORG_ALIAS" --json 2>/dev/null | jq -r '.result.id // empty' | cut -c1-15)
if [ "$ORG_ID" != "$EXPECTED_ORG_ID" ]; then
  echo "ABORT: '$ORG_ALIAS' resolved to Org Id '${ORG_ID:-<none>}', expected $EXPECTED_ORG_ID"
  echo "       Wrong alias, expired auth, or a pin left over from another org's run."
  echo "       Re-run Phase 0.1/0.2 to re-pin if you intended to target a different org."
  exit 1
fi

# --- Portable single-flight lock -----------------------------------------------------
# mkdir is atomic. flock is util-linux and absent on macOS, so a flock-based guard
# silently no-ops there. Two concurrent retrieves in one tree corrupt .git/index.
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  HOLDER=$(cat "$LOCKDIR/pid" 2>/dev/null || echo '')
  echo "ABORT: lock held ($LOCKDIR, pid ${HOLDER:-?})"
  if [ -z "$HOLDER" ]; then
    # The lock dir and its pid file are two separate writes, so a crash between them
    # leaves a pid-less lock. Unknown is not the same as alive.
    echo "       No pid recorded — holder cannot be identified."
    echo "       If no retrieve is running, this is stale: rm -rf $LOCKDIR"
  elif ! kill -0 "$HOLDER" 2>/dev/null; then
    echo "       pid $HOLDER is NOT running — stale lock from a crash or kill -9."
    echo "       Safe to clear: rm -rf $LOCKDIR"
  else
    echo "       pid $HOLDER is alive. Wait for it; do not clear the lock."
  fi
  # Never truncate the in-flight log on refusal — that destroys the running phase's evidence.
  echo "       Not truncating $LOG."
  exit 3
fi
echo $$ > "$LOCKDIR/pid"
trap 'rm -rf "$LOCKDIR"' EXIT INT TERM

# --- Marker file ---------------------------------------------------------------------
# A populated mirror OVERWRITES far more files than it adds, so a net-new count reads
# ~0 on a perfectly healthy retrieve. Compare mtimes against a marker instead, which
# counts files actually WRITTEN. The sleep guarantees a strictly later mtime on
# filesystems with coarse (1s) timestamp granularity.
MARKER="$L/.phase-marker"
rm -f "$MARKER"; touch "$MARKER"; sleep 1
echo "=== $(date -u +%FT%TZ)  $NAME  (wait ${WAIT_MIN}min, floor ${FLOOR}) ==="
START=$(date +%s)

sf project retrieve start "$@" -o "$ORG_ALIAS" --ignore-conflicts --wait "$WAIT_MIN" > "$LOG" 2>&1
RC=$?

ELAPSED=$(( $(date +%s) - START ))
if ! DELTA=$(find force-app -type f -newer "$MARKER" | wc -l | tr -d ' '); then
  echo "ABORT: could not enumerate force-app — file count is not trustworthy, gate cannot run."
  exit 1
fi

# -a is mandatory: retrieve logs contain NUL bytes, and without it grep prints
# "Binary file ... matches" instead of the line, gating a successful phase as failed.
STATUS=$(grep -aEo "Status: (Succeeded|Failed|In Progress|Pending)" "$LOG" | tail -1)
echo "  ${STATUS:-<no Status line>}  elapsed=${ELAPSED}s  rc=$RC  files_written=${DELTA}"

if [ "$STATUS" != "Status: Succeeded" ]; then
  echo "  GATE: phase did not report Succeeded — do NOT start the next phase."
  if [ -n "$STATUS" ]; then
    # A Status line means the CLI created a job, so resume attaches to the right one.
    echo "  A job WAS submitted. Recover with:"
    echo "    sf project retrieve resume --use-most-recent -o \"$ORG_ALIAS\" --wait 30"
  else
    # No Status line means the CLI failed before job creation; --use-most-recent would
    # attach to an unrelated earlier job and report its result as this phase's.
    echo "  No job was submitted (CLI failed before job creation) — resume would be WRONG here."
  fi
  grep -aE "LIMIT_EXCEEDED|MalformedQueryException|FATAL|too large|not found|ERROR" "$LOG" | head -8
  printf '%s\t%s\t%s\t%s\tGATE_FAIL\n' "$(date -u +%FT%TZ)" "$NAME" "$ELAPSED" "$DELTA" >> "$L/_progress.tsv"
  exit 2
fi

# --- Volume floor --------------------------------------------------------------------
# "Succeeded" means the call completed, not that components came back. A phase can
# report Succeeded while emitting thousands of "cannot be found" warnings.
# grep -c prints 0 AND exits 1 on no-match, so `|| echo 0` would emit two lines.
WARN=$(grep -ac "cannot be found" "$LOG" 2>/dev/null); WARN=${WARN:-0}
if [ "$FLOOR" != "-" ] && [ "$DELTA" -lt "$FLOOR" ]; then
  echo "  GATE: Succeeded but only ${DELTA} files written, floor is ${FLOOR} — materially short."
  echo "  Treat as the documented fallback trigger. warnings(cannot be found)=${WARN}"
  echo "  Diagnose per the runbook before touching the floor: stale wildcard members,"
  echo "  a parent phase that already wrote these files, container/child truncation, or a cap."
  printf '%s\t%s\t%s\t%s\tSHORT floor=%s warn=%s\n' "$(date -u +%FT%TZ)" "$NAME" "$ELAPSED" "$DELTA" "$FLOOR" "$WARN" >> "$L/_progress.tsv"
  exit 2
fi

printf '%s\t%s\t%s\t%s\tOK warn=%s\n' "$(date -u +%FT%TZ)" "$NAME" "$ELAPSED" "$DELTA" "$WARN" >> "$L/_progress.tsv"
[ "$WARN" -gt 0 ] && echo "  NOTE: ${WARN} 'cannot be found' warnings — reconcile in the audit doc."
exit 0
