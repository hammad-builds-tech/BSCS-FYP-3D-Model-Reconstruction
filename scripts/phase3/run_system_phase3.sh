#!/bin/bash
# Phase 3 bring-up: the Phase 2 stack with Nav2 Collision Monitor in the
# velocity command chain.
#
# run_system.sh hard-codes `ros2 launch indoor_nav_costmap
# navigation.launch.py` (line ~191) with no way to substitute a different
# navigation layer, and it is a Phase 2 file that must not be modified. This
# script therefore reuses Phase 2's simulation and localization phases
# unchanged and swaps only the navigation phase for
# phase3_navigation.launch.py.
#
# Usage:
#   export FYP_DEPTH_SOURCE=gazebo          # metric depth (Phase 1/2 verified path)
#   export FYP_REACTIVE_OBSTACLES=1         # Phase 2 reactive obstacle layer
#   scripts/phase3/run_system_phase3.sh
#
# Stop with:
#   bash docs/evidence/phase1/scripts/stop_stack.sh
#
# Phase 2 is reproduced by running ./run_system.sh instead; nothing here
# changes it.

# No `set -u`: /opt/ros/lyrical/setup.bash dereferences
# AMENT_TRACE_SETUP_FILES unconditionally and aborts the script under
# nounset. run_system.sh does not use it either.
set -o pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../fyp_env.sh"
cd "$FYP_ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[P3]${NC} $*"; }
warn() { echo -e "${YELLOW}[P3]${NC} $*"; }
err()  { echo -e "${RED}[P3]${NC} $*"; }

source /opt/ros/lyrical/setup.bash
source "$FYP_ROOT/ros2_ws/install/setup.bash"

: "${FYP_DEPTH_SOURCE:=gazebo}"
export FYP_DEPTH_SOURCE
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"

echo "==============================================="
echo " FYP Phase 3 — navigation behind Collision Monitor"
echo "==============================================="
info "Depth source      : $FYP_DEPTH_SOURCE"
info "Reactive obstacles: ${FYP_REACTIVE_OBSTACLES:-0}"

# Fail early rather than silently bringing up the unprotected Phase 2 chain.
if ! ros2 pkg prefix nav2_collision_monitor >/dev/null 2>&1; then
    err "nav2_collision_monitor is NOT installed."
    err "  sudo apt-get install -y ros-lyrical-nav2-collision-monitor"
    err "Refusing to start: without it this would be the unguarded Phase 2 chain."
    exit 1
fi
info "nav2_collision_monitor $(ros2 pkg xml nav2_collision_monitor | grep -oPm1 '(?<=<version>)[^<]+') present"

wait_for() {
    local label="$1" limit="$2"; shift 2
    local waited=0
    while [ "$waited" -lt "$limit" ]; do
        if "$@" >/dev/null 2>&1; then
            info "$label ready (${waited}s)"; return 0
        fi
        sleep 2; waited=$((waited + 2))
    done
    warn "$label NOT ready after ${limit}s"; return 1
}

# Fatal variant. The 21 Nov 2026 incident was caused by wait_for's return
# value being IGNORED by every caller: a gate printed "NOT ready after 90s"
# and the script went on to announce "PHASE 3 UP" anyway, after which three
# scenario runs executed against a dead simulator. Readiness gates must
# abort the bring-up, never warn and continue.
require() {
    local label="$1"
    if ! wait_for "$@"; then
        err "ABORTING: $label never became ready."
        err "Refusing to announce PHASE 3 UP with an unverified stack --"
        err "scenario results from such a stack are worthless."
        teardown_and_die
    fi
}

teardown_and_die() {
    err "Tearing down the partial stack."
    bash "$FYP_ROOT/scripts/phase3/stop_stack_phase3.sh" >/dev/null 2>&1 || true
    exit 1
}

# A previous stack still serving /clock and /scan is what made the stale
# gates pass. Refuse to start until the machine is actually clear.
assert_no_stale_stack() {
    local n_gz n_nav n_cm n_wd
    # Bracketed first character so the pattern cannot match this script's
    # own command line (or the shell that launched it) -- the same
    # self-match that has repeatedly killed terminals in this project.
    # `pgrep -fc` prints "0" AND exits 1 when nothing matches, so the
    # idiom `$(pgrep -fc ... || echo 0)` yields the two-line string "0\n0"
    # and every [ -gt ] below fails with "integer expected" -- which bash
    # treats as false, silently disabling this guard. Counting lines instead
    # always yields exactly one integer.
    n_gz=$(pgrep -f '[g]z-sim-main' 2>/dev/null | wc -l)
    n_nav=$(pgrep -f '[n]av2_controller/controller_server' 2>/dev/null | wc -l)
    n_cm=$(pgrep -f '[n]av2_collision_monitor/collision_monitor' 2>/dev/null | wc -l)
    n_wd=$(pgrep -f '[p]hase3/cmd_vel_watchdog' 2>/dev/null | wc -l)
    if [ "$n_gz" -gt 0 ] || [ "$n_nav" -gt 0 ] || [ "$n_cm" -gt 0 ] || [ "$n_wd" -gt 0 ]; then
        err "Stale processes still running after teardown:"
        err "  gz-sim-main=$n_gz controller_server=$n_nav collision_monitor=$n_cm watchdog=$n_wd"
        err "A leftover stack keeps serving /clock and /scan, which is exactly"
        err "how a previous bring-up passed its gates against a dead simulator."
        err "Run scripts/phase3/stop_stack_phase3.sh and retry."
        exit 1
    fi
    info "No stale project processes -- clean slate confirmed"
}

info "Stopping any stale project processes"
# Patterns are deliberately specific. A bare `pkill -f collision_monitor`
# also matches any shell whose command line merely mentions the string --
# including the terminal you launch this from -- and kills it. Matching the
# installed executable path cannot collide that way.
pkill -f "ros2 launch indoor_nav"                              2>/dev/null
pkill -f "launch/simulation\.launch\.py"                       2>/dev/null
pkill -f "launch/localization\.launch\.py"                     2>/dev/null
pkill -f "launch/navigation\.launch\.py"                       2>/dev/null
pkill -f "launch/phase3_navigation\.launch\.py"                2>/dev/null
pkill -f "nav2_collision_monitor/collision_monitor"            2>/dev/null
sleep 3
assert_no_stale_stack

# ---- Phase A: Gazebo world + robot + bridge (Phase 2 file, unchanged) ----
info "Phase A: Gazebo + robot + ros_gz_bridge (log: /tmp/fyp_p3_sim.log)"
setsid nohup ros2 launch indoor_nav_gazebo simulation.launch.py \
    > /tmp/fyp_p3_sim.log 2>&1 < /dev/null &
# Check the simulator PROCESS first: /clock alone proved nothing.
require "gz-sim-main process" 90 bash -c "pgrep -f '[g]z-sim-main' >/dev/null"
require "robot spawned (ground truth readable)" 90 bash -c \
  "timeout 10 gz topic -e -t /world/indoor_world/pose/info -n 1 2>/dev/null \
   | grep -q 'fyp_robot'"

# ---- Phase B: depth -> scan + map server + AMCL (Phase 2 file, unchanged) ----
info "Phase B: depth bridge + depth_to_scan + map_server + AMCL (log: /tmp/fyp_p3_loc.log)"
setsid nohup ros2 launch indoor_nav_costmap localization.launch.py \
    > /tmp/fyp_p3_loc.log 2>&1 < /dev/null &
require "AMCL publishing map->odom" 90 bash -c \
  "source /opt/ros/lyrical/setup.bash && source $FYP_ROOT/ros2_ws/install/setup.bash \
   && timeout 12 ros2 run tf2_ros tf2_echo map odom 2>/dev/null | grep -q Translation"

# ---- Phase C: Nav2 behind Collision Monitor (Phase 3 file) ----
info "Phase C: Nav2 + Collision Monitor (log: /tmp/fyp_p3_nav.log)"
setsid nohup ros2 launch indoor_nav_costmap phase3_navigation.launch.py \
    > /tmp/fyp_p3_nav.log 2>&1 < /dev/null &

for n in controller_server planner_server behavior_server bt_navigator collision_monitor; do
    require "lifecycle: $n active" 90 bash -c \
      "source /opt/ros/lyrical/setup.bash && source $FYP_ROOT/ros2_ws/install/setup.bash \
       && timeout 10 ros2 lifecycle get /$n 2>/dev/null | grep -q '^active'"
done

# ---- Final readiness gate: FATAL, and based on measured properties ----
#
# Everything above confirms processes and lifecycle states. This last gate
# confirms the stack is actually *working*: the sim clock advancing, sensor
# stamps fresh against that clock, the full TF chain resolvable, and the
# command pipeline wired end to end. It is the check that would have caught
# the 21 Nov 2026 stale-stack incident, where /clock and /scan both existed
# but Gazebo was dead.
echo
info "Final readiness verification (clock / sensors / TF / command chain)"
if ! /usr/bin/python3 "$FYP_ROOT/scripts/phase3/check_stack_ready.py" --window 6; then
    err "Stack failed final readiness verification."
    err "NOT announcing PHASE 3 UP. Do not run scenarios against this stack."
    teardown_and_die
fi

# Watchdog is a plain process, not a lifecycle node, so check it separately.
if ! pgrep -f "phase3/cmd_vel_watchdo[g]\.py" >/dev/null 2>&1; then
    err "cmd_vel_watchdog is NOT running."
    err "Without it, a lost publisher leaves the robot driving on the last"
    err "command (gz VelocityControl latches indefinitely: measured 2.78-2.81 m)."
    teardown_and_die
fi
info "  cmd_vel_watchdog         : RUNNING"
info "  collision_monitor        : $(timeout 8 ros2 lifecycle get /collision_monitor 2>/dev/null)"

echo
info "PHASE 3 UP."
info "  Send a goal:   ./send_test_goal.sh"
info "  Monitor state: ros2 topic echo /collision_monitor_state"
info "  Logs: /tmp/fyp_p3_sim.log /tmp/fyp_p3_loc.log /tmp/fyp_p3_nav.log"
