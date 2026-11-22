# Phase 3 — Gazebo command watchdog

**Status: implemented and measured. Bounds runaway motion by ~16x. Still not
an emergency stop.**

Phase 3 Task 2 left two gaps: a direct publish to `/cmd_vel` bypassed the
Collision Monitor, and killing the monitor mid-motion let the robot travel
4.4 m. This document covers the investigation and what was actually fixed.

**Machine:** HP ZBook 15 G6, Quadro T2000, Ubuntu 26.04.1, ROS 2 Lyrical,
Gazebo 10.5.0. **Date:** 19–20 November 2026.
**Branch:** `phase-3-validation`. Phase 2 (`phase-2-node`, `1c23f6f`) untouched.
**Evidence:** [`evidence/phase3/`](evidence/phase3/README.md).

## 1. Task 1 — the plugin does not support a command timeout

| Question | Answer |
|---|---|
| Exact plugin name | `gz::sim::systems::VelocityControl` |
| SDF `filename` | `gz-sim-velocity-control-system` |
| Installed version | `libgz-sim-velocity-control-system.so.10.5.0` (Gazebo `gz sim` 10.5.0) |
| Configured in `fyp_robot.sdf` with | `<topic>/cmd_vel</topic>` only |
| Supported SDF parameters | `topic`, `link_name` (+ initial velocity elements) |
| **Command timeout supported?** | **No** |
| Does a timeout stop linear *and* angular? | N/A — no timeout exists |
| Default timeout behaviour | **None. The last command is latched indefinitely.** |
| Measured from last received command? | N/A |

Verification, not assumption:

- `strings libgz-sim-velocity-control-system.so.10.5.0 | grep -ci timeout`
  → **0**. A raw binary grep for `timeout` also returns nothing.
- `DiffDrive` has **no timeout either** — its elements are
  `wheel_separation`, `wheel_radius`, `max_linear_velocity`,
  `max_acceleration`, `odom_topic`, `tf_topic` and similar.
- Sweeping **every** `libgz-sim-*.so.10.5.0` for `cmd_vel_timeout` or
  `command_timeout` returns **no matches**: no gz-sim 10.5.0 plugin exposes
  one.

**Measured latch behaviour (3 runs, no watchdog):** commanded 0.30 m/s, then
stopped publishing. Displacement after the publisher stopped: **2.813 /
2.779 / 2.781 m**, and in every run the robot was **still moving** at t+10 s.

## 2. Task 2 — why there is no `fyp_robot_phase3.sdf`

The task said to create a Phase 3 robot model *if the plugin supports a
timeout*. It does not, and there is no SDF element to add, so a copy of the
model would be an identical file with a different name — churn with no
behavioural change. **No Phase 3 robot model was created**, and
`fyp_robot.sdf` is untouched.

The task's stated fallback was taken instead: a Phase 3-only watchdog, as
the last element before the bridge.

```
controller_server ─┐
behavior_server  ──┴─> /cmd_vel_nav ─> collision_monitor ─> /cmd_vel_safe
                                                                  │
                                                       cmd_vel_watchdog
                                                                  │
                                                             /cmd_vel ─> ros_gz_bridge ─> Gazebo
```

`scripts/phase3/cmd_vel_watchdog.py`:

- republishes every input message immediately (no added latency on the
  normal path);
- if the input is silent for longer than `--timeout`, publishes zero `Twist`
  at `--rate` Hz **continuously**, overwriting the plugin's latched command;
- keeps asserting zeros while the input stays silent, so a single dropped
  message cannot let a stale command resurface;
- publishes a zero at startup rather than inheriting whatever the plugin was
  last told.

**Timeout 0.50 s, zero-rate 20 Hz.** `/cmd_vel_nav` was measured at
**9.925 Hz** against a `controller_frequency` of 10.0 Hz (~0.10 s period), so
0.50 s tolerates five consecutive missed commands.

## 3. Task 3 — integration verified

| Check | Result |
|---|---|
| Robot spawns | ground truth (0.014, −2.000) ✓ |
| TF `base_link → sim_depth_scan` | (0.350, 0, 0.100) ✓ |
| TF `odom → base_link` | (0.014, −2.000, 0) ✓ |
| TF `map → odom` | present ✓ |
| Depth sensor | `/rgbd_camera/depth_image` **15.285 Hz** ✓ |
| Depth processing | `/scan` **11.923 Hz** ✓ |
| Collision Monitor in chain | `active [3]`, sole subscriber of `/cmd_vel_nav` ✓ |
| Watchdog in chain | sole publisher of `/cmd_vel` ✓ |
| **Nav2 navigation** | goal (2.0, 0.0) → `SUCCEEDED`, ground truth (1.930, −0.083) = **0.109 m** error ✓ |

`/smartphone/depth` is idle because `SIM_PHONE=0`; in Gazebo mode depth comes
from `/rgbd_camera`. Only the Phase 3 launch was changed — Phase 2's
`navigation.launch.py`, `nav2_params.yaml`, `localization.launch.py`,
`simulation.launch.py`, `fyp_robot.sdf`, `setup.py` and `run_system.sh` are
all unmodified.

## 4. Task 4 — watchdog test results

All figures from Gazebo ground truth, 3 runs per case, corrected watchdog.
Full data in [`evidence/phase3/watchdog_results.csv`](evidence/phase3/watchdog_results.csv).

| Case | What happens | t to zero velocity | Displacement after loss | Verdict |
|---|---|---|---|---|
| **baseline** | no watchdog, publisher stops | **never** | **2.779–2.813 m** | runaway |
| **A** | commands continuous | n/a (keeps moving, correctly) | 3.726–3.740 m travelled | ✅ no interference |
| **B** | publisher stops while moving | **1.02–1.18 s** (mean 1.11) | **0.102–0.172 m** (mean 0.147) | ✅ stops |
| **C** | `collision_monitor` killed while moving | **0.80–1.05 s** (mean 0.90) | **0.112–0.137 m** (mean 0.122) | ✅ stops |
| **D** | publisher hard-killed while moving | **0.89–1.07 s** (mean 0.98) | **0.072–0.132 m** (mean 0.103) | ✅ stops |
| **E** | monitor restarted after a timeout | — | resumed on command, moved 1.352 m | ✅ resumes |
| **F** | idle 10–12 s after a stop | — | drift **0.0032–0.0039 m** | ✅ no stale resume |

**Worst-case runaway reduced from 2.813 m to 0.172 m — a factor of ~16.**

Additional fail-safe result: with `collision_monitor` dead, commanding motion
moved the robot **0.0021 m** — the watchdog holds it immobile. A missing
monitor now means *no motion* rather than *unmonitored motion*.

Watchdog logs correctly on the designed path, e.g.
`input silent for 0.53 s (> 0.50 s timeout): publishing zero velocity.
Forwarded 23 commands before the gap.` Zero watchdog deaths across all
corrected runs.

### A bug found in the watchdog, and why the first results were discarded

The first implementation called `get_logger().warn()`. This rclpy has
`warning` but **not** `warn` (verified directly), so the node raised
`AttributeError` **the instant it first detected silence** — exactly when it
was needed. `respawn=True` restarted it within ~1 s and the fresh instance
published zeros from its "nothing ever received" branch.

The robot therefore did stop in the first B/C/D runs, but **by
crash-and-respawn, not by design**. Those nine runs are retained in the CSV
marked `buggy-crashpath` and are **not** cited. Every result above was
re-measured after the fix.

Five further runs are marked `invalid`: `collision_monitor` has no
`respawn`, so after case C killed it, subsequent runs had no monitor to
forward commands and the robot never moved (`peak_v 0.000`). Case C requires
a full stack restart between runs.

## 5. Task 5 — direct command bypass, honestly

**A direct publish to `/cmd_vel` still moves the robot. The bypass is not
closed.**

| Condition | Displacement |
|---|---|
| Direct publish, Task 2 (no watchdog) | **1.886 m** |
| Direct publish, with watchdog | **0.521 m** during a 6 s publish |
| 4 s after the direct publisher stopped | **0.000 m** |

Two things changed, one did not:

- **Not fixed:** a publisher that keeps publishing still drives the robot.
  ROS 2 topics are open; any node may publish to `/cmd_vel`. The watchdog
  competes (20 Hz zeros against a 10 Hz intruder, roughly halving effective
  speed) but cannot win reliably and is not designed to.
- **Fixed:** the *persistence*. Previously a single stale direct command
  latched forever; now zeros are reasserted within one watchdog period and
  the robot stops.

This cannot be solved at this level. The Gazebo plugin has no notion of an
authorised publisher, so topic-level access control would be required.
Treat it as a property of the simulation.

## 6. What this is and is not

**Demonstrated:** every observed realistic failure — Collision Monitor
crash, publisher crash, publisher stop — now produces a bounded stop within
~1 s and ~0.17 m, instead of unbounded motion. No stale command resurfaces.

**Not demonstrated, and false if claimed:**

1. **Not an emergency stop.** The watchdog is now the last element, so if
   *it* dies the latch problem returns. That cannot be fixed from ROS space:
   the simulator holds the last command it received, whoever sent it.
   `respawn=True` mitigates a crash (~1 s gap) but not a kill of the launch
   itself.
2. **The bypass is open** (section 5).
3. This is a **Gazebo software mechanism**, not a certified physical
   emergency stop, and must never be described as one in the report.
4. **Stop distance is not a tuned safety figure.** ~1 s to zero is the
   0.50 s timeout plus physical deceleration. The 0.50 s timeout was
   **APPROVED 20 Nov 2026**, derived from the measured 9.925 Hz command rate
   (five missed commands), not from a stopping-distance requirement. If a
   scenario later needs a tighter bound, this is the knob, and shortening it
   risks nuisance zeroing if the command rate dips.

## 7. Phase 2 regression

- `colcon test`: **51 tests, 5 failures, 3 skipped** — identical to the
  Phase 2 baseline, all five pre-existing style checks.
- Protected files verified `UNMODIFIED`: `nav2_params.yaml`,
  `navigation.launch.py`, `localization.launch.py`, `simulation.launch.py`,
  `fyp_robot.sdf`, `setup.py`, `run_system.sh`, `params_overlay.py`,
  and `docs/evidence/phase1/scripts/stop_stack.sh`.
- No commits, no pushes.

## 7a. Bring-up readiness (hardened 22 Nov 2026)

`run_system_phase3.sh` previously gated on `ros2 topic hz /clock` and
`ros2 topic hz /scan`. Both pass against a **stale** stack: on 21 Nov it
reported `/clock flowing ready (0s)` and `/scan flowing ready (0s)` while
Gazebo was not running and Nav2 never activated, then announced
`PHASE 3 UP`. Three scenario runs executed against a dead simulator before
the robot's total immobility gave it away. The root cause was that
`wait_for`'s return value was **ignored by every caller**.

Now:

* a `require` wrapper **aborts and tears down** on any failed gate -- no gate
  can warn and continue;
* a clean-slate assertion refuses to start while a previous stack is alive;
* Phase A checks the **`gz-sim-main` process** and that the robot's ground
  truth is readable, not merely that `/clock` exists;
* Phase B requires AMCL to publish `map -> odom`;
* all five lifecycle gates are fatal;
* a final `check_stack_ready.py` verifies **measured** properties: the sim
  clock advancing, `/scan` and depth stamps fresh against that clock, the
  full TF chain (`map->odom`, `odom->base_link`,
  `base_link->sim_depth_scan`), and the command pipeline wired end to end.
  It uses its own rclpy node, so it does **not** depend on the `ros2` CLI
  daemon.

Verified both ways: with nothing running it reports **9 failed checks** and
exits 1; on a healthy stack all nine pass.

### A stale ros2 CLI daemon blocks Nav2 activation

Found while validating the above. A `ros2-daemon` left running ~29 minutes
reported **ten phantom nodes** with no matching processes. With that cache
polluted, Nav2 would not activate: `controller_server` never reached
`active` and the hardened bring-up aborted **twice in a row** (correctly --
the old script would have announced success). `ros2 daemon stop` made the
node list correctly empty and the next bring-up succeeded with every gate
green. `stop_stack_phase3.sh` now stops the daemon as part of teardown.

Two pre-existing shell defects were also fixed: `pgrep -fc` prints `0` *and*
exits 1 when nothing matches, so `$(pgrep -fc ... || echo 0)` yielded the
two-line string `"0\n0"` and every `[ -gt ]` comparison failed with
"integer expected" -- silently disabling the clean-slate guard; and patterns
are now bracketed (`[g]z-sim-main`) so they cannot match the script's own
command line.

## 8. Teardown — use the Phase 3 script

`scripts/phase3/stop_stack_phase3.sh` was added because the Phase 1
`stop_stack.sh` knows nothing about the Collision Monitor or the watchdog and
leaves both orphaned. Two real defects were found building it:

1. **`stop_stack.sh` can kill your terminal.** It kills by PID from a
   pattern list including the very broad `"nav2_"`, protecting only `$$` and
   `$PPID`. A shell further up the chain is unprotected, so a wrapper that
   *calls* it gets its caller killed whenever that command line contains
   `nav2_`. The Phase 3 script therefore does its own kills first and reaches
   `stop_stack.sh` with `exec` last, so `$PPID` is the real caller. It also
   protects its whole ancestor chain. **`stop_stack.sh` itself is not
   modified.**
2. **Kill order matters.** The launch runs the watchdog with `respawn=True`,
   so the launch must die first or the watchdog is immediately restarted and
   orphaned. The first version also used the pattern
   `launch/phase3_navigation\.launch\.py`, which silently matched nothing —
   the real command line is
   `ros2 launch indoor_nav_costmap phase3_navigation.launch.py`, with no
   `launch/` prefix. Both fixed; a second sweep catches respawns.

## 9. Recommended next task

Both open parameters were **approved on 20 Nov 2026**: stop-polygon front
edge **0.60 m** and watchdog timeout **0.50 s**. The safety baseline is
therefore frozen, and Phase 3 Scenarios 1-5 proceed against it
(see [`PHASE3_SCENARIOS.md`](PHASE3_SCENARIOS.md)). Scenario 4 (moving
obstacles) remains last, as it is the one that most depends on the stop
layer.
