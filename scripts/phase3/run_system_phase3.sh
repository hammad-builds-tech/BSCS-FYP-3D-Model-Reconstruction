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

# ---- Phase A: Gazebo world + robot + bridge (Phase 2 file, unchanged) ----
info "Phase A: Gazebo + robot + ros_gz_bridge (log: /tmp/fyp_p3_sim.log)"
setsid nohup ros2 launch indoor_nav_gazebo simulation.launch.py \
    > /tmp/fyp_p3_sim.log 2>&1 < /dev/null &
wait_for "/clock flowing" 90 bash -c \
  "source /opt/ros/lyrical/setup.bash && source $FYP_ROOT/ros2_ws/install/setup.bash \
   && timeout 12 ros2 topic hz /clock --window 10 2>/dev/null | grep -q 'average rate'"

# ---- Phase B: depth -> scan + map server + AMCL (Phase 2 file, unchanged) ----
info "Phase B: depth bridge + depth_to_scan + map_server + AMCL (log: /tmp/fyp_p3_loc.log)"
setsid nohup ros2 launch indoor_nav_costmap localization.launch.py \
    > /tmp/fyp_p3_loc.log 2>&1 < /dev/null &
wait_for "/scan flowing" 90 bash -c \
  "source /opt/ros/lyrical/setup.bash && source $FYP_ROOT/ros2_ws/install/setup.bash \
   && timeout 12 ros2 topic hz /scan --window 5 2>/dev/null | grep -q 'average rate'"

# ---- Phase C: Nav2 behind Collision Monitor (Phase 3 file) ----
info "Phase C: Nav2 + Collision Monitor (log: /tmp/fyp_p3_nav.log)"
setsid nohup ros2 launch indoor_nav_costmap phase3_navigation.launch.py \
    > /tmp/fyp_p3_nav.log 2>&1 < /dev/null &

for n in controller_server planner_server behavior_server bt_navigator collision_monitor; do
    wait_for "lifecycle: $n active" 90 bash -c \
      "source /opt/ros/lyrical/setup.bash && source $FYP_ROOT/ros2_ws/install/setup.bash \
       && timeout 10 ros2 lifecycle get /$n 2>/dev/null | grep -q '^active'"
done

# ---- Verify the chain really is gated, not just configured ----
echo
info "Verifying the command chain"
NAV_SUBS=$(timeout 12 ros2 topic info /cmd_vel_nav   2>/dev/null | grep -oP 'Subscription count: \K\d+')
SAFE_SUBS=$(timeout 12 ros2 topic info /cmd_vel_safe 2>/dev/null | grep -oP 'Subscription count: \K\d+')
OUT_PUBS=$(timeout 12 ros2 topic info /cmd_vel       2>/dev/null | grep -oP 'Publisher count: \K\d+')
info "  /cmd_vel_nav  subscribers : ${NAV_SUBS:-0}  (expect 1: collision_monitor)"
info "  /cmd_vel_safe subscribers : ${SAFE_SUBS:-0}  (expect 1: cmd_vel_watchdog)"
info "  /cmd_vel      publishers  : ${OUT_PUBS:-0}  (expect 1: cmd_vel_watchdog)"
if pgrep -f "phase3/cmd_vel_watchdo[g]\.py" >/dev/null 2>&1; then
    info "  cmd_vel_watchdog         : RUNNING"
else
    err "  cmd_vel_watchdog         : NOT RUNNING — a lost publisher will leave the robot driving"
fi

if timeout 10 ros2 node list 2>/dev/null | grep -qx "/collision_monitor"; then
    info "  collision_monitor node   : RUNNING ($(timeout 8 ros2 lifecycle get /collision_monitor 2>/dev/null))"
else
    err "  collision_monitor node   : NOT RUNNING — the chain is UNPROTECTED"
fi

echo
info "PHASE 3 UP."
info "  Send a goal:   ./send_test_goal.sh"
info "  Monitor state: ros2 topic echo /collision_monitor_state"
info "  Logs: /tmp/fyp_p3_sim.log /tmp/fyp_p3_loc.log /tmp/fyp_p3_nav.log"
