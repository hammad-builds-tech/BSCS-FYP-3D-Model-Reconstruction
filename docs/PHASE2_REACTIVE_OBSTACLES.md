# Phase 2: reactive obstacle avoidance from live depth

**Status: complete and verified in simulation.** The robot detects an
obstacle that is **not in the static map**, replans around it, and still
reaches the goal inside the Phase 1 accuracy limit. 5/5 runs.

**Machine:** HP ZBook 15 G6, Quadro T2000 4 GB, Ubuntu 26.04.1, ROS 2
Lyrical, Gazebo 10.5.0. **Date:** 18 November 2026.
**Mode:** `FYP_DEPTH_SOURCE=gazebo` (metric depth).
**Evidence:** [`evidence/phase2/`](evidence/phase2/README.md).

Everything below is measured. Limitations are in section 9.

## 1. What Phase 2 set out to do

[`RUN_NAVIGATION.md`](RUN_NAVIGATION.md) defines Phase 2 as "live WebSocket
depth + reactive obstacle layer + real-time replanning".

Phase 1 ran with both costmaps' `obstacle_layer` **disabled**, and the
depth-derived `/smartphone_map` had no subscriber, so Nav2 could only avoid
obstacles already baked into the static map (Phase 1 limitation 13.5).

Real-time replanning needed no new work: `bt_navigator` uses Nav2's default
`NavigateToPoseWReplanningAndRecovery` tree, which already re-runs
`ComputePathToPose` at 1 Hz. The missing piece was a costmap that could see
anything.

## 2. How it is enabled

```bash
export FYP_DEPTH_SOURCE=gazebo
export FYP_REACTIVE_OBSTACLES=1
./run_system.sh
```

Unset, nothing changes: `indoor_nav_costmap/params_overlay.py` returns the
committed `nav2_params.yaml` path itself, so Phase 1 bring-up is
bit-identical (pinned by
`test_phase1_path_returns_the_committed_file_unchanged`, and confirmed at
runtime in section 8).

With the flag set, a patched **copy** is written to a temp file and the Nav2
servers are pointed at it. `nav2_params.yaml` is never edited — verified
with `git diff` after full runs.

### Why an overlay rather than editing the YAML

The costmaps are not standalone launch nodes: `global_costmap` runs inside
`planner_server` and `local_costmap` inside `controller_server`. A parameter
appended to those nodes in the launch description — the trick Phase 1 used
for the goal checker — cannot reach a costmap, because the costmap reads its
own `<name>.<name>.ros__parameters` block from the file. Writing a patched
copy is the only way to change it without touching the committed file.

## 3. The root cause: a silently discarded height window

This was the hard part and is the main technical result of the phase.

With `obstacle_layer` enabled **identically** in both costmaps, the local
costmap marked an unmapped box (111–218 lethal cells within 0.5 m, sustained)
while the **global costmap marked zero**, confirmed through
`/global_costmap/get_costmap`. The global plan therefore ran straight through
the obstacle (closest approach of `/plan` to the box centre: **0.01 m**), and
DWB then correctly refused to follow its own plan, deadlocking with
`error 106 "No valid trajectories out of 419"`.

**Cause.** `ObstacleLayer` discards any observation point whose height, *in
the costmap's own global frame*, falls outside
`[min_obstacle_height, max_obstacle_height]`. The defaults are `0.0 .. 2.0`,
which assume a gravity-aligned lidar referenced to the floor. This sensor is
neither:

- the scan originates **0.18 m** up, on a camera, and
- in the **`map`** frame it appears pitched about **−4.35°**, because AMCL's
  `map → odom` is 2-D and absorbs the robot's nose-down rest attitude
  (Phase 1 report section 9).

A beam at range *r* therefore sits at `z = 0.18 − r·sin(4.35°)`, which
crosses `0.0` at **r = 2.37 m**. Past that, every return was dropped — in the
global costmap only. The local costmap's global frame is `odom`, where the
levelled scan stays at a constant +0.18 m, so it was unaffected. One default,
two frames, completely different behaviour.

**Fix.** Set the window explicitly to `−1.0 .. 2.0`, at both layer and
per-source scope. This cannot invent floor obstacles: `depth_to_scan` already
rejects floor returns geometrically with its elevation filter before a range
is ever emitted. Pinned by `test_height_window_accommodates_the_pitched_scan`.

**Result:** global costmap went from **0** to **17** lethal cells at the box
(face cell 254), and a 1.754 m goal failure became 5/5 successes.

### What was ruled out first, by measurement

Recorded because each of these is a plausible cause that cost time:

| Hypothesis | How it was excluded |
|---|---|
| TF unavailable | `map → sim_depth_scan` resolves; every scan stamp has an exact matching transform; 2 message-filter drops in a full run; no TF exceptions |
| QoS mismatch | `ros2 topic info /scan -v`: publisher and both costmap subscriptions all BEST_EFFORT |
| Costmap not updating | `/global_costmap/costmap_updates` publishes at 1 Hz |
| Static layer wiping marks | `/map` is published once, transient local |
| Recovery behaviours clearing | Reproduced with no goal active, so nothing could issue a clear |
| `track_unknown_space` | Set to `false` on the global costmap; **changed nothing**. Reverted |
| Stale published grid | `global_costmap` lacks `always_send_full_costmap`, so the topic *was* stale — but `/global_costmap/get_costmap` confirmed the grid itself was genuinely empty |

`/global_costmap/get_obstacle_layer` returns an all-zero grid even for the
*local* costmap, which demonstrably works, so that service cannot be used to
inspect layer state here.

## 4. What the overlay changes, and why

| Key | Phase 1 | Phase 2 | Reason |
|---|---|---|---|
| `obstacle_layer.enabled` (both) | `false` | `true` | The point of the phase |
| `min_obstacle_height` / `max_obstacle_height` | (default 0.0 / 2.0) | **−1.0 / 2.0** | Section 3 — the root cause |
| `combination_method` | — | `1` (maximum) | Live returns can only *add* cost, never clear a mapped wall |
| `scan.inf_is_valid` | — | `true` | `depth_to_scan` emits `+inf` for empty bins (REP 117); without this the layer discards them and free space is never cleared |
| `scan.expected_update_rate` | — | `0.0` | Depth arrives at 5–10 Hz; the staleness warning would flood the log |
| `obstacle_max_range` / `raytrace_max_range` | — | 3.0 / 8.0 metric; 2.5 / 3.5 relative | Never assert geometry beyond what the data supports; relative mode is uncalibrated and capped at 3.5 m |
| `FollowPath.BaseObstacle.scale` | `0.10` | `32.0` | Below |
| `FollowPath.max_vel_x`, `max_speed_xy` | `0.85` | `0.45` | Below |
| `global_costmap.always_send_full_costmap` | — | `true` | Observability only; no planning effect |

**Not changed, deliberately:** inflation radius (0.45 m), the
`collision_monitor` stop polygon, the footprint, AMCL, the planner, the goal
checker. `test_overlay_changes_only_its_documented_keys` fails if anything
else moves.

### Why DWB had to be re-weighted

`nav2_params.yaml` ships `BaseObstacle.scale: 0.10` against
`PathAlign.scale`/`PathDist.scale` of `32.0` — a 320:1 bias towards following
the global path over avoiding obstacles. That is rational while
`obstacle_layer` is disabled, because the critic then scores nothing but
static cells the planner already routed around.

With live returns it is actively harmful. Measured with the layer enabled and
the critic left at 0.10: the robot **drove into** the box and came to rest
with its own centre cell marked lethal, aborting with `error 105 "Failed to
make progress"`.

### Why the cruise speed was halved

Depth reaches the costmap about **0.4 s** after the image on this hardware
(measured scan-stamp lag against `/clock`) and arrives at only 5–10 Hz. At
0.85 m/s the robot covers ~0.35 m before an obstacle is even representable,
before DWB's 1.2 s horizon is considered.

## 5. Acceptance test

A 0.4 × 0.4 × 1.2 m static box spawned at map (1.0, −1.0) **at runtime**, so
no world file is modified and the static map does not contain it:

```bash
ros2 run ros_gz_sim create -world indoor_world \
  -file docs/evidence/phase2/unmapped_box.sdf \
  -name phase2_unmapped_box -x 1.0 -y -1.0 -z 0.6
```

At the start pose it is ~45° off the robot's heading, **outside the 69°
camera FOV**, so it is only discovered once the robot turns toward the goal.
That makes this a genuine reactive test, not a pre-seeded one.

Goal (2.0, 0.0) from the Phase 1 start pose (0, −2). Pass requires **both**:
ground-truth final position within **0.15 m** of the goal (the Phase 1 limit,
unchanged) **and** never closer than **0.55 m** to the box centre — the box
half-width 0.20 m plus the robot's 0.35 m half-length, i.e. the head-on
contact distance.

## 6. Results

| Run | Config | Box | Final (truth) | Goal error | Min dist to box | exec/straight | Pass |
|---|---|---|---|---|---|---|---|
| 1 | reactive | yes | (1.929, −0.098) | **0.121 m** | 0.669 m | 1.168 | ✅ |
| 2 | reactive | yes | (1.923, −0.103) | **0.129 m** | 0.682 m | 1.173 | ✅ |
| 3 | reactive | yes | (1.914, −0.105) | **0.136 m** | 0.668 m | 1.172 | ✅ |
| 4 | reactive | yes | (1.923, −0.099) | **0.126 m** | 0.672 m | 1.170 | ✅ |
| 5 | reactive | yes | (1.924, −0.096) | **0.122 m** | 0.679 m | 1.174 | ✅ |
| ctrlA | **flag off** | yes | (0.445, −0.811) | **1.754 m** | 0.567 m | 1.937 | ❌ |
| b1 | flag off | no | (1.919, −0.095) | 0.125 m | — | 1.038 | ✅ |
| b2 | flag off | no | (1.923, −0.093) | 0.121 m | — | 1.039 | ✅ |

Source: [`evidence/phase2/results.csv`](evidence/phase2/results.csv),
trajectories in `evidence/phase2/trajectories/`.

| Metric | Value |
|---|---|
| Success rate, reactive with obstacle | **5 / 5 (100 %)** |
| Goal error: mean / min / max | **0.127 m** / 0.121 / **0.136 m** (limit 0.15) |
| Clearance from box: mean / min | 0.674 m / **0.668 m** (threshold 0.55) |
| Detour ratio with obstacle | 1.168–1.174 |
| Detour ratio, no obstacle (b1/b2) | 1.038–1.039 |

Two things make this convincing:

1. **Control A is the A/B.** Same box, same goal, reactive layer off: the
   robot stalls 1.754 m from the goal having closed to 0.567 m of the box
   centre — head-on that puts its nose ~0.02 m off the box face. The layer
   is what produces the difference, not tuning luck.
2. **The detour is real, not noise.** 1.17 with the obstacle against 1.04
   without it, consistent to ±0.003 across five runs, while the goal error
   stays inside Phase 1's band.

## 7. Mirrored relative-mode scan (also fixed)

Phase 1 limitation 13.4 recorded that the phone-mode scan was mirrored
left/right. Cause: `ranges_from_relative_depth` returns one value per image
column, ordered left → right, but a `LaserScan` runs `angle_min` →
`angle_max`, which is counter-clockwise in REP 103 — index 0 is the
**rightmost** bearing. Publishing column order directly mirrors the scan.

Fixed at the publish site in `depth_callback` (`ranges[::-1]`), not in the
conversion: `ranges_from_relative_depth` is a pure image-space function and
its existing test documents column order. The `metric` path bins by bearing
and was never affected.

Pinned by `test_relative_scan_is_not_mirrored_left_right`, which asserts the
published orientation matches the metric path's
`test_rolled_camera_keeps_left_obstacle_on_the_left`.

This fix is **not** gated behind the Phase 2 flag — the previous behaviour
was simply wrong. It affects phone/relative mode only, which Phase 1 did not
validate for navigation.

## 8. Phase 1 regression (passes)

With `FYP_REACTIVE_OBSTACLES` unset, read back from the running nodes:

```
obstacle_layer.enabled (local)  = False
obstacle_layer.enabled (global) = False
FollowPath.BaseObstacle.scale   = 0.1
FollowPath.max_vel_x            = 0.85
general_goal_checker.xy_goal_tolerance = 0.05
amcl alpha1                     = 0.02
```

Acceptance runs b1/b2 (no box): `SUCCEEDED`, **0.125 m** and **0.121 m** —
both inside Phase 1's own measured band of 0.106–0.144 m (mean 0.123 m).

`colcon test`: **51 tests, 5 failures, 3 skipped**. The failure count is
unchanged from the Phase 1 baseline of 5, and all 5 are pre-existing style
checks (`flake8` ×3, `pep257` ×2); the 3 skips are missing licence headers.
26 tests were added by this phase and all pass.

## 9. Limitations

1. **Simulation only, metric depth only.** Validated with
   `FYP_DEPTH_SOURCE=gazebo`. In `relative` (phone) mode the ranges come from
   MiDaS inverse relative depth anchored by a heuristic, so they are not
   calibrated distances; ranges are capped accordingly but the layer should
   not be trusted there until depth is metrically scaled.
2. **One obstacle, one route.** A single static box, one start pose, one
   goal, one world. No moving obstacles, no multi-obstacle or corridor cases,
   and no test of an obstacle that fully blocks the only route — the
   behaviour when no detour exists is untested.
3. **Narrow accuracy margin, inherited.** Worst goal error 0.136 m against
   the 0.15 m limit. Phase 1's own worst was 0.144 m; this does not improve
   it, and the systematic ~7 cm localization bias of Phase 1 section 12 is
   unchanged.
4. **Reduced cruise speed is not free.** 0.45 m/s invalidates Phase 1's
   12.6–20.7 s durations, and the phase did not re-time navigation.
5. **A collision leaves AMCL mislocalised.** After control A wedged the
   robot, `reset_robot.sh` alone did not restore correct localization — a
   following run ended 0.93 m from the goal having overshot in +y. A full
   stack restart was required. Treat post-collision runs as invalid.
6. **5.3 fps depth is the ceiling** on this GPU, and the backend's inference
   worker is latest-frame-wins, so depth rate does not improve with a faster
   stream. On slower hardware the 0.45 m/s cruise may need to come down
   further.
7. **Nothing tested with a real phone.** The Android app still does not
   compile (Phase 1 limitation 13.3).
