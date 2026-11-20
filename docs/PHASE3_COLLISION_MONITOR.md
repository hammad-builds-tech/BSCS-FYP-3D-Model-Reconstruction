# Phase 3 — Nav2 Collision Monitor integration

**Status: integrated and working as a command gate. NOT a fail-safe.**

> **Follow-up:** the two fail-safe gaps found here (tests F and G) were
> investigated in
> [`PHASE3_COMMAND_WATCHDOG.md`](PHASE3_COMMAND_WATCHDOG.md). Test G's
> runaway is now bounded from 4.4 m to ~0.17 m by a command watchdog; test
> F's direct-publish bypass remains open but no longer persists. Read that
> document alongside this one.

The official Nav2 Collision Monitor now sits in the velocity command chain
and demonstrably blocks Nav2 from driving into an obstacle it can see. It
does **not** provide an emergency stop: it can be bypassed by any publisher,
and if it dies the robot keeps moving at its last commanded velocity
(section 6). Both limits are measured, not assumed.

**Machine:** HP ZBook 15 G6, Quadro T2000, Ubuntu 26.04.1, ROS 2 Lyrical,
Gazebo 10.5.0. **Date:** 19 November 2026.
**Mode:** `FYP_DEPTH_SOURCE=gazebo`, `FYP_REACTIVE_OBSTACLES=1`.
**Branch:** `phase-3-validation`. Phase 2 (`phase-2-node`, `1c23f6f`) untouched.

## 1. Why this was needed

The Phase 3 audit found `nav2_params.yaml` configures a `collision_monitor`
block, and the project's own comments call its `PolygonStop` "the safety
net". In reality:

- `nav2_collision_monitor` **was not installed at all** (`ros2 pkg prefix`
  → "Package not found"), so the node could never have run;
- it is referenced by **no launch file** and not by `run_system.sh`;
- `/cmd_vel_smoothed` did not exist;
- commands went `controller_server`/`behavior_server` → `/cmd_vel` →
  `ros_gz_bridge` → Gazebo, unguarded.

`ros-lyrical-nav2-collision-monitor` 1.5.2 has since been installed manually.

## 2. Version compatibility

| Component | Version |
|---|---|
| `nav2_collision_monitor` | **1.5.2**-2resolute |
| `nav2_costmap_2d`, `nav2_msgs`, `nav2_util`, `nav2_controller`, `nav2_behaviors` | **1.5.1**-1resolute |

The 1.5.2 binary links the 1.5.1 shared libraries. `ldd` shows **no
unresolved libraries**, and the node **starts, configures and reaches
`active`** under the project's lifecycle manager, with no symbol-lookup
errors. Compatibility is therefore demonstrated by execution, not inferred
from a successful `apt` install.

Note: `nav2_common` is **not** installed, so the launch file shipped inside
`nav2_collision_monitor` (which imports `nav2_common.launch.RewrittenYaml`)
**cannot run here**. The Phase 3 launch does not use it.

## 3. Coordinate-frame verification

Phase 2 was broken by a frame/height assumption, so this was checked before
any safety test.

Measured with `tf2_echo`:

| Transform | Translation | Rotation |
|---|---|---|
| `odom → base_link` | (0.014, −2.000, 0.000) | pitch **+4.350°** (robot rests nose-down) |
| `odom → sim_depth_scan` | (0.370, −2.000, 0.073) | **RPY (0, 0, 0)** — scan frame is level in odom |
| `base_link → sim_depth_scan` | **(0.350, 0, 0.100)** | pitch **−4.350°** |

The polygon is defined in `base_link` (the robot base frame, as required).
Collision Monitor transforms scan points into that frame and does a **2-D
point-in-polygon test**; z is projected away and there is no height gate, so
**Phase 2's `min_obstacle_height` rejection cannot recur here**. The residual
error from transforming a level scan into the pitched `base_link` is a
horizontal shortening of `1 − cos(4.35°)` = **0.3 %** (≈3 mm at 1 m) — a
rounding error against a 0.05 m costmap.

## 4. Two committed parameter values had to be overridden

Both were intended to be reused verbatim. Measurement showed each makes the
monitor non-functional. `nav2_params.yaml` is **not edited**; the overrides
live in the Phase 3 launch.

### 4.1 `PolygonStop` front edge 0.45 m → 0.60 m — the committed zone is unreachable

The camera sits **0.35 m forward** of `base_link` and `depth_to_scan`
enforces `min_range` **0.15 m**. The nearest point the sensor can report is
therefore:

| Bearing | Nearest reportable x in `base_link` | Inside 0.45 m zone? |
|---|---|---|
| 0° (head-on) | **0.500 m** | no |
| 20° | 0.491 m | no |
| 34° (FOV edge) | **0.474 m** | no |

Every reachable point lies **beyond** the committed 0.45 m front edge, so no
scan return can ever fall inside it and `PolygonStop` **can never fire**.
Wiring the monitor in with the committed polygon produces an `active`,
correctly-subscribed node that is permanently blind — exactly the failure
mode this phase exists to remove.

0.60 m clears the 0.500 m head-on floor and leaves a 0.10 m band of
detectable depth inside the zone, 0.25 m beyond the chassis front (0.35 m).

> **APPROVED 20 Nov 2026** as the project's stop-polygon front edge.
> Recorded rationale: 0.60 m is the derived detectability minimum (0.500 m
> head-on floor + 0.10 m usable band), not a tuned safety margin. The known
> consequence is accepted: Phase 2's verified runs came within 0.580 m
> centre-to-centre of a 0.4 m box (a face 0.38 m from `base_link`), so a
> close pass of that kind can trip the monitor. Phase 3 scenarios must
> report any such trip rather than treat it as a defect.

### 4.2 `scan.source_timeout` 0.5 s → 1.0 s — the committed value fires spuriously

Measured scan stamp lag against `/clock`, 249 samples:

| Metric | Value |
|---|---|
| median | 0.403 s |
| p95 | 0.487 s |
| **max** | **0.591 s** |
| inter-scan gap (median / max) | 0.066 s / 0.264 s |

The maximum **exceeds** the committed 0.5 s timeout. Result with 0.5 s: the
monitor declared `STOP | "invalid source"` **7 times in 45 s of clear-path
navigation** and emitted 15 zero commands. That is a nuisance stop, not a
safety response.

With 1.0 s: **0 invalid-source events** over the same test. The explicit
trade-off is that a genuinely dead sensor is now detected in up to 1.0 s
instead of 0.5 s.

## 5. Architecture

**Before (Phase 2, unchanged and still reproducible):**
```
controller_server ─┐
behavior_server  ──┴──> /cmd_vel ──> ros_gz_bridge ──> Gazebo
```

**After (Phase 3, as built at the end of Task 2):**
```
controller_server ─┐
behavior_server  ──┴──> /cmd_vel_nav ──> collision_monitor ──> /cmd_vel ──> ros_gz_bridge ──> Gazebo
                                               ^
                                          /scan  (~9.8 Hz, sim_depth_scan)
```

> **Superseded.** Task 3 inserted a command watchdog between the monitor and
> the bridge, because the Gazebo plugin latches the last command. The chain
> is now `collision_monitor -> /cmd_vel_safe -> cmd_vel_watchdog ->
> /cmd_vel`. See [`PHASE3_COMMAND_WATCHDOG.md`](PHASE3_COMMAND_WATCHDOG.md) §2.

Verified topic graph at the end of Task 2:

| Topic | Publishers | Subscribers |
|---|---|---|
| `/cmd_vel_nav` | `controller_server`, `behavior_server` | **`collision_monitor` only** |
| `/cmd_vel` | **`collision_monitor` only** | `ros_gz_bridge` |

`behavior_server` is remapped too: the recovery behaviours (`spin`, `backup`,
`drive_on_heading`) drive the robot, and leaving them on `/cmd_vel` would be
an unprotected bypass during exactly the situations where the robot is
already in trouble.

### Velocity smoother: deliberately not added

`nav2_velocity_smoother` 1.5.1 is installed and configured in
`nav2_params.yaml`, but it is **not** wired in:

1. it provides no collision protection, so adding it would make motion look
   smoother without changing safety;
2. DWB already enforces this robot's acceleration limits (`acc_lim_x` 2.5,
   `decel_lim_x` −3.0), as does the Gazebo drive;
3. placement matters — the committed block expects
   `cmd_vel_in_topic: cmd_vel_smoothed`, i.e. controller → smoother →
   monitor. That ordering is the only safe one. A smoother placed *after*
   the monitor would **ramp down the emergency stop** instead of applying
   it. If one is added later it must sit upstream of the monitor.

## 6. Safety and fail-safe test results

| Test | Setup | Result | Verdict |
|---|---|---|---|
| **A** Clear path | goal (1.2, −1.8), no obstacle | 69 cmds in → **69 out** (68 non-zero both ways); 0 invalid-source; `SUCCEEDED`; scan 9.81 Hz | ✅ no interference |
| **B** Obstacle in zone | 0.4 m box, face 0.55 m from `base_link` | **305 non-zero cmds in → 0 out**; state `STOP \| PolygonStop`; ground truth moved **0.0003 m** | ✅ stops |
| **C** Obstacle remains | same, 40 s | **352 non-zero cmds in → 0 out**; ground truth **identical** to B | ✅ stays stopped |
| **D** Obstacle removed | box deleted at t+8 s | state → `DO_NOTHING`; 86 cmds passed; robot drove to (1.917, −1.946) = **0.099 m** from goal | ✅ resumes |
| **E** Sensor dead | `depth_to_scan` killed, `/scan` 0 Hz | **117 non-zero cmds in → 0 out**; "invalid source" logged | ✅ gates on stale data |
| **F** Direct bypass | publish 0.3 m/s straight to `/cmd_vel` | robot moved **1.886 m** | ❌ **bypass possible** |
| **G** Monitor killed mid-motion | `kill -9` while confirmed moving | x 0.487 → 1.442 (+2 s) → 2.764 (+5 s) → **4.892 (+10 s)**; travelled **4.4 m** | ❌ **no fail-safe** |

Measured rates during tests: depth 15.0 Hz, `/scan` 9.5–11.4 Hz, local
costmap 10 Hz, global costmap 2 Hz.

### Why test G fails

`fyp_robot.sdf` loads the Gazebo `VelocityControl` plugin on `/cmd_vel` with
**no command timeout** (`grep -c cmd_vel_timeout` → 0). The last velocity
command therefore persists indefinitely, so when the monitor dies the robot
coasts at whatever it was last told. The system does **not** silently revert
to the Phase 2 chain — it is worse than that: it continues executing a
single stale command with nothing watching.

A first run of test G was **inconclusive** and is reported as such: the
robot had already stopped (after the test F bypass left it at x=5.31 with
AMCL mislocalised) when the monitor was killed, so no motion could be
observed. The run above was repeated with motion confirmed by two
successive differing ground-truth samples before the kill.

## 7. Honest assessment of the safety claim

**What is demonstrated:** when the monitor is alive and the sensor is
healthy, no Nav2 velocity command reaches Gazebo while an obstacle occupies
the stop polygon, and the robot provably does not move (0.3 mm over 75 s
across tests B and C). Stale sensor data gates commands too.

**What is NOT demonstrated, and is false:**

1. **Requirement "no direct unprotected command bypass" is not achievable
   by remapping.** ROS 2 topics are open; any node may publish to
   `/cmd_vel`. Test F moved the robot 1.886 m. Remapping redirects
   *cooperating* publishers; it enforces nothing.
2. **This is not an emergency stop.** Test G shows a monitor crash leaves
   the robot running. A real E-stop must be the last element in the chain
   and must fail to a safe state.
3. This is a **Gazebo software mechanism**, not a certified physical
   emergency stop, and should never be described as one in the report.

## 8. Phase 2 regression

- `colcon test`: **51 tests, 5 failures, 3 skipped** — identical to the
  Phase 2 baseline. All 5 failures are pre-existing style checks
  (`flake8` ×3, `pep257` ×2); the 3 skips are missing licence headers.
- `./run_system.sh` (Phase 2 bring-up) re-checked after the Phase 3 work:
  `collision_monitor` running = **0**, `/cmd_vel_nav` existing = **0**,
  `/cmd_vel` published directly by `controller_server` + `behavior_server`.
  The Phase 2 chain is byte-for-byte what it was.
- `nav2_params.yaml`, `navigation.launch.py`, `localization.launch.py`,
  `simulation.launch.py`, `run_system.sh`, `fyp_robot.sdf` and `setup.py`:
  **unmodified**.

## 9. Limitations

1. **Not a fail-safe** (tests F, G). The two gaps are independent: an open
   topic and a missing command timeout.
2. **The stop polygon needs sign-off.** 0.60 m is a derived detectability
   minimum. Its interaction with legitimate close passes (Phase 2 came
   within 0.38 m of an obstacle face) is untested.
3. **Only `action_type: stop` is configured.** No `slowdown`, `limit` or
   `approach` zone, so behaviour is binary: full speed or halted.
4. **`source_timeout` 1.0 s is driven by pipeline latency, not by safety.**
   On slower hardware the 0.591 s lag will grow and this may need raising
   again, which further delays dead-sensor detection.
5. **Metric/Gazebo depth only.** In relative (phone) mode the ranges are
   uncalibrated, so the stop distance would not correspond to a real
   distance.
6. **Single stop polygon, single source.** The point-cloud path
   (`/camera/depth/points`) remains unsubscribed and is not used.
7. **Test F left the robot mislocalised**, confirming the Phase 2 finding
   that `reset_robot.sh` alone does not recover AMCL after an anomaly. A
   full stack restart was required.

## 10. Recommended next task

**Close the two fail-safe gaps before any Phase 3 obstacle experiment**, in
this order:

1. **Add a command timeout to the Gazebo drive.** This is the single
   highest-value fix: it converts "monitor dies → robot runs away" into
   "monitor dies → robot stops in ≤ timeout". It requires editing
   `fyp_robot.sdf`, a Phase 1/2 file, so it needs approval and should be
   done as a Phase 3-only robot model copy if the Phase 2 model must stay
   untouched.
2. **Decide the stop-polygon envelope** (section 4.1) so the monitor's
   behaviour during close passes is a deliberate choice.
3. Only then proceed to Scenarios 1–5. Scenario 4 (moving obstacles) is the
   one that most needs a working stop layer and should remain last.

Bypass via a direct `/cmd_vel` publish cannot be fixed at this level; it
would need the drive to accept commands only from an authenticated source,
which the Gazebo plugin does not support. Treat it as a known property of
the simulation rather than a defect to patch.
