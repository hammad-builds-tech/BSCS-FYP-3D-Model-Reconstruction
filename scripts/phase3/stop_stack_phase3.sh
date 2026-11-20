#!/bin/bash
# Phase 3 teardown.
#
# docs/evidence/phase1/scripts/stop_stack.sh predates Phase 3 and does not
# know about the Collision Monitor or the command watchdog, so running it
# alone leaves those two orphaned. An orphaned watchdog keeps publishing on
# /cmd_vel and fights the next bring-up; an orphaned Collision Monitor holds
# a stale lifecycle node name.
#
# ORDERING IS DELIBERATE -- DO NOT WRAP stop_stack.sh IN A SUBSHELL
# -----------------------------------------------------------------
# stop_stack.sh kills by PID from a pattern list that includes the very broad
# "nav2_", and it protects only $$ (itself) and $PPID (its direct caller).
# Any shell further up the chain is fair game. So if this script merely
# *called* it, the terminal that ran this script would be two levels up,
# unprotected, and would be killed whenever its command line happened to
# contain "nav2_" -- which is exactly what happened during Phase 3 testing.
#
# The Phase 3 kills therefore run FIRST, and stop_stack.sh is reached with
# `exec` LAST, so this script's process is replaced and stop_stack.sh's
# $PPID is the real caller. stop_stack.sh itself is a Phase 1 evidence file
# and is not modified.
#
# Usage: scripts/phase3/stop_stack_phase3.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || exit 1

# Protect this script and every ancestor, so a pattern that happens to match
# a parent's command line cannot take down the terminal.
protected=" $$ "
pid=$PPID
while [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$pid" != "1" ]; do
    protected="$protected$pid "
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
done

# Patterns match installed or absolute paths, never a bare word.
#
# ORDER MATTERS: the launch file runs the watchdog with respawn=True, so the
# launch must die FIRST or it immediately restarts the watchdog and leaves it
# orphaned once the launch is killed afterwards. Observed during testing: one
# watchdog survived teardown for exactly this reason.
#
# The launch pattern must NOT be anchored on "launch/": the real command line
# is `ros2 launch indoor_nav_costmap phase3_navigation.launch.py`, with no
# such prefix, so an anchored pattern silently matched nothing and the
# watchdog went on respawning through two teardown sweeps.
phase3_patterns=(
    "phase3_navigation\.launch\.py"
    "phase3/cmd_vel_watchdog\.py"
    "nav2_collision_monitor/collision_monitor"
)

echo "[P3] Phase 3 processes"
victims=()
for pat in "${phase3_patterns[@]}"; do
    while read -r p; do
        [ -n "$p" ] && [[ "$protected" != *" $p "* ]] && victims+=("$p")
    done < <(pgrep -f -- "$pat" 2>/dev/null)
done

if [ ${#victims[@]} -eq 0 ]; then
    echo "  none running"
else
    mapfile -t victims < <(printf '%s\n' "${victims[@]}" | sort -un)
    echo "  stopping ${#victims[@]} process(es): ${victims[*]}"
    kill -INT "${victims[@]}" 2>/dev/null; sleep 2
    kill -TERM "${victims[@]}" 2>/dev/null; sleep 1
    kill -KILL "${victims[@]}" 2>/dev/null; sleep 1
fi

# Second sweep: anything respawned between the launch dying and now.
sleep 1
second=()
for pat in "${phase3_patterns[@]}"; do
    while read -r p; do
        [ -n "$p" ] && [[ "$protected" != *" $p "* ]] && second+=("$p")
    done < <(pgrep -f -- "$pat" 2>/dev/null)
done
if [ ${#second[@]} -gt 0 ]; then
    mapfile -t second < <(printf '%s\n' "${second[@]}" | sort -un)
    echo "  second sweep (respawned): ${second[*]}"
    kill -KILL "${second[@]}" 2>/dev/null; sleep 1
fi

remaining=0
for pat in "${phase3_patterns[@]}"; do
    while read -r p; do
        [ -n "$p" ] && [[ "$protected" != *" $p "* ]] && remaining=$((remaining + 1))
    done < <(pgrep -f -- "$pat" 2>/dev/null)
done
echo "[P3] Phase 3 processes remaining: $remaining"

echo "[P3] handing over to the Phase 2 teardown (exec)"
exec bash docs/evidence/phase1/scripts/stop_stack.sh
