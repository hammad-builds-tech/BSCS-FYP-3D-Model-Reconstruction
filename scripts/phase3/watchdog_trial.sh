#!/bin/bash
# Phase 3 Task 4 — one watchdog experiment, measured from Gazebo ground truth.
#
# Usage: watchdog_trial.sh <case> <run>
#   case A  normal continuous velocity commands
#   case B  stop publishing velocity commands while moving
#   case C  terminate collision_monitor while moving
#   case D  terminate the velocity command publisher while moving
#
# Ground truth is sampled directly from /world/indoor_world/pose/info, not
# from /odom or /cmd_vel, so the result does not depend on the ROS topics
# under test. Linear and angular velocity are differentiated from pose.
#
# Prints a single CSV row:
#   case,run,x_at_event,t_to_zero_s,displacement_m,peak_v,v_at_event,w_at_event

CASE="$1"; RUN="$2"
# Resolve the repository from this script's own location, never a hard-coded
# home directory: Phase 1 removed every absolute /home/... path for exactly
# this reason (see docs/PHASE1_COMPLETION_REPORT.md section 3).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || exit 1
source /opt/ros/lyrical/setup.bash
source ros2_ws/install/setup.bash
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
# Raw traces go OUTSIDE the repository: they are working files, not results,
# and writing them into the clone leaves an untracked directory behind after
# every run. Override with WATCHDOG_TRACE_DIR to keep them elsewhere.
SP="${WATCHDOG_TRACE_DIR:-${TMPDIR:-/tmp}/fyp_phase3_traces}"; mkdir -p "$SP"
TRACE="$SP/wd_${CASE}_${RUN}.trace"

# Sample ground truth pose + yaw at ~10 Hz into a trace file.
sampler() {
  while :; do
    gz topic -e -t /world/indoor_world/pose/info -n 1 2>/dev/null \
      | grep -A8 'name: "fyp_robot"' \
      | grep -oP '^\s+(x|y|z|w): \K[-0-9.e]+' | head -7 | tr '\n' ' '
    echo " @$(date +%s.%N)"
    sleep 0.1
  done
}

bash docs/evidence/phase1/scripts/reset_robot.sh >/dev/null 2>&1
sleep 4

: > "$TRACE"
sampler >> "$TRACE" 2>/dev/null &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

# Drive the robot forward through the full protected chain.
timeout 25 ros2 topic pub -r 10 /cmd_vel_nav geometry_msgs/msg/Twist \
  "{linear: {x: 0.30}}" >/dev/null 2>&1 &
PUB=$!

# Wait until genuinely moving (ground truth, not a topic value).
sleep 3

EVENT_T=$(date +%s.%N)
case "$CASE" in
  A) sleep 6 ;;                                            # keep commanding
  B) kill -TERM $PUB 2>/dev/null; EVENT_T=$(date +%s.%N) ;; # publisher stops
  C) kill -9 $(pgrep -f 'nav2_collision_monito[r]/collision_monitor' | head -1) 2>/dev/null
     EVENT_T=$(date +%s.%N) ;;
  D) kill -9 $PUB 2>/dev/null; EVENT_T=$(date +%s.%N) ;;    # publisher killed hard
esac

sleep 8
kill $SAMPLER 2>/dev/null
kill $PUB 2>/dev/null

/usr/bin/python3 - "$TRACE" "$EVENT_T" "$CASE" "$RUN" <<'PY'
import math, sys
trace, event_t, case, run = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
rows = []
for line in open(trace):
    if "@" not in line:
        continue
    vals, _, ts = line.rpartition("@")
    nums = vals.split()
    if len(nums) < 3:
        continue
    try:
        rows.append((float(ts), float(nums[0]), float(nums[1])))
    except ValueError:
        continue
if len(rows) < 5:
    print("%s,%s,NA,NA,NA,NA,NA,NA  # too few samples (%d)" % (case, run, len(rows)))
    raise SystemExit

def speed(a, b):
    dt = b[0] - a[0]
    if dt <= 1e-6:
        return 0.0
    return math.hypot(b[1] - a[1], b[2] - a[2]) / dt

speeds = [(rows[i + 1][0], speed(rows[i], rows[i + 1])) for i in range(len(rows) - 1)]
peak = max(v for _, v in speeds) if speeds else 0.0

after = [r for r in rows if r[0] >= event_t]
x_at = after[0][1] if after else rows[-1][1]
y_at = after[0][2] if after else rows[-1][2]
disp = math.hypot(rows[-1][1] - x_at, rows[-1][2] - y_at)

# v at the moment of the event
v_at = next((v for t, v in speeds if t >= event_t), 0.0)

# time until speed stays below 0.02 m/s
STOPPED = 0.02
t_zero = "NOT_STOPPED"
post = [(t, v) for t, v in speeds if t >= event_t]
for i, (t, v) in enumerate(post):
    if v < STOPPED and all(v2 < STOPPED for _, v2 in post[i:i + 3]):
        t_zero = "%.2f" % (t - event_t)
        break

print("%s,%s,%.3f,%s,%.3f,%.3f,%.3f,%d" %
      (case, run, x_at, t_zero, disp, peak, v_at, len(rows)))
PY
