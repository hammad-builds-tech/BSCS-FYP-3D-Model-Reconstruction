# Phase 1 Completion Report: Portability, ROS 2 Readiness and Simulated Navigation

**Project:** Smartphone-Based Real-Time 3D Indoor Mapping and Autonomous Navigation System
**Branch:** `fix/ros2-packaging` (changes uncommitted at the time of writing)
**Test period:** 16–17 November 2026
**Evidence:** [`docs/evidence/phase1/`](evidence/phase1/README.md)

> **Scope.** Phase 1 validated the ROS 2 / Nav2 / Gazebo side of the system
> **in simulation**. The navigation results below use the **simulated robot's
> RGB-D camera** as the localization sensor (`FYP_DEPTH_SOURCE=gazebo`).
> Navigation driven by **real smartphone camera depth** (`FYP_DEPTH_SOURCE=phone`,
> the default) was **not** validated in Phase 1 (see §13).

---

## 1. Objectives

1. Make the repository run from any clone location and any Linux user
   (no `/home/hammad/FYP` paths).
2. Check that the installed ROS 2 environment matches what the code needs.
3. Make the ROS 2 workspace build and test cleanly, with correct package
   dependencies.
4. Bring up the full simulated stack (Gazebo → depth → `/scan` → AMCL → Nav2)
   and show that the robot **physically** reaches a goal: the Gazebo
   ground-truth position must end within **0.15 m** of the goal. Nav2's
   `SUCCEEDED` alone does not count.
5. Show that result is repeatable (5 independent runs, 5 passes).

**Outcome:** objectives 1–5 met in simulation. 5/5 runs passed; worst
ground-truth error 0.144 m (§11).

---

## 2. Tested environment

| Component | Version |
|---|---|
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-43-generic, x86_64 |
| CPU / RAM | Intel Core i5-13420H (12 threads), 14 GiB |
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU, 6 GB, driver 595.99.02 |
| ROS 2 | **Lyrical** (`/opt/ros/lyrical`), `rclpy` 10.0.11, `tf2_ros` 0.45.10, `cv_bridge` 4.1.0 |
| Nav2 | 1.5.2 (`nav2_amcl`, `nav2_controller`, `nav2_bt_navigator`, `nav2_map_server`, `dwb_core`) |
| Gazebo | `gz sim` 10.5.0; `ros_gz_bridge` / `ros_gz_sim` 3.0.10 |
| colcon | colcon-core 0.21.3 |
| ROS-side Python | system `/usr/bin/python3` 3.14.4, numpy 2.3.5, OpenCV 4.10.0 |
| Backend Python | project `venv/`, Python 3.14.4, torch 2.15.0+cu132, torchvision 0.29.2+cu132, timm 0.6.13, numpy 2.5.5, FastAPI 0.163.1 (see `docs/BACKEND_SETUP.md`) |
| MiDaS | `isl-org/MiDaS` commit 4545977, DPT-Hybrid-384 weights |

The original proposal targeted Ubuntu 22.04 and ROS 2 Humble. The code in
this repository is written for **ROS 2 Lyrical** (scripts source
`/opt/ros/lyrical`, Gazebo is driven through `ros_gz`), so the tested
environment above is the reference platform. Other distributions were not
tested.

### Second verified platform (added 18 November 2026)

Phase 1 was later re-checked on a different machine. The build, the test
suite and the acceptance run all reproduce; only the GPU figures differ.

| Component | Machine A (above) | Machine B |
|---|---|---|
| Laptop | HP Victus | **HP ZBook 15 G6** |
| CPU / RAM | i5-13420H, 14 GiB | **i7-9850H, 22 GiB** |
| GPU | RTX 4050 Laptop, 6 GB | **Quadro T2000, 4 GB** (3716 MiB usable, sm_75) |
| Driver | 595.99.02 | 595.99.02 |
| OS / ROS 2 / Gazebo | 26.04.1 / Lyrical / 10.5.0 | identical |
| System Python | 3.14.4 | 3.14.4 |
| Nav2 | 1.5.2 | **1.5.1** |
| `ros_gz_*` | 3.0.10 | **3.0.9** |
| `tf2_ros` | 0.45.10 | **0.45.9** |

Reproduced on Machine B:

- `colcon build --symlink-install` 3/3; test suite at the same failure
  baseline (style checks only).
- Gazebo RGB-D camera at **15.18 Hz** (Machine A: 15.1 Hz).
- MiDaS smoke test `RESULT: PASS`, peak GPU memory **604 MiB** — identical
  to Machine A, so VRAM is not the constraint.
- Acceptance run, goal (2.0, 0.0) from (0, −2): `SUCCEEDED`, ground-truth
  final (1.9225, −0.0935), **0.121 m** from the goal — inside the 0.15 m
  limit and within the 0.106–0.144 m band of section 11.

**Not reproduced on Machine B:** the five-run repeatability study of
section 11 (one run only), and the GPU performance figures. MiDaS runs
**~177–188 ms/frame (~5.3–5.6 fps)** on Machine B against ~40–45 ms
(~22–25 fps) on Machine A — about 4x slower — and **FP16 is ~4.7x slower
than FP32** there, the opposite of Machine A. Every GPU timing in this
report and in `docs/BACKEND_SETUP.md` is therefore specific to Machine A
and must not be quoted as a property of the system.

The ROS nodes run on the system Python; the backend runs in its own venv.
They communicate only over HTTP. **Do not activate the backend venv in a ROS
terminal**: `rclpy` and `cv_bridge` are built against the system numpy and
OpenCV.

---

## 3. Repository portability

| Item | Before | After |
|---|---|---|
| Shell scripts | Hard-coded `/home/hammad/FYP` | Source `scripts/fyp_env.sh`, which sets `FYP_ROOT` from the clone's own location and picks `venv/bin/python` (commit `d9099f5`) |
| Backend / Python scripts | Hard-coded paths | `FYP_ROOT` environment variable, or a path relative to the file (`backend/core/paths.py`) |
| ROS launch files | — | Resolve files through `ament_index` / `__file__` |
| `realroom/capture_fresh/nav_targets.env` | `FYP_MAP` / `FYP_WORLD` = `/home/hammad/FYP/...` (bring-up failed; `fyp30_multi_goal_demo.py` silently fell back to the un-baked map) | `${FYP_ROOT}/realroom/capture_fresh/...`; `fyp30_multi_goal_demo.py` expands `${FYP_ROOT}` with `os.path.expandvars` |

**Verification.** The way each consumer loads `nav_targets.env`
(`run_navigation.sh`, `fyp30_fixrun.sh`, `fyp30_demo.sh` with `set -u`, the
guards in `fyp_realroom30_up.sh`, and both Python readers) was reproduced:
- from the repository root;
- from another working directory;
- from a simulated second clone under a different path.

All cases resolved the intended baked map and world inside that clone.
`bash -n` and `py_compile` passed.

**Remaining:**
- About 20 scripts source `/opt/ros/lyrical` directly, so they assume ROS 2 Lyrical.
- `~/FYP` still appears in comments and older Markdown documents.
- None of these is a path that active code uses.

---

## 4. ROS 2 environment check

Everything below was verified on the test machine without installing
anything:
- `ros2`, `colcon`, `gz` and `rosdep` are available.
- `~/.bashrc` sources Lyrical.
- All Nav2 packages and plugins named in `nav2_params.yaml` are installed: NavFn, DWB with
  `dwb_critics` / `dwb_plugins`, `costmap_2d`, the behaviors, the BT navigator and AMCL.
- `ros_gz_*`, `tf2_ros`, `cv_bridge`, `sensor_msgs_py`, `rviz2`, `slam_toolbox` and
  `robot_localization` are installed.

TurtleBot3 is **not** installed and **not** needed: the project uses its own
robot model, `fyp_robot`. `rosdep` is installed but not initialised (that
needs `sudo rosdep init`; not done).

---

## 5. Workspace build and package dependency corrections

| Package | Problem found | Correction |
|---|---|---|
| `indoor_nav_gazebo` | `setup.py` installed `glob('models/fyp_robot/*')`, which includes the **directory** `meshes/`. The build failed with `can't copy ... meshes: not a regular file` (both `colcon build` and `--symlink-install`). | Install files only, plus a separate entry for `models/fyp_robot/meshes/*` |
| `indoor_nav_gazebo` | `tests_require=['pytest']` is ignored by current setuptools, so `colcon test` ran **0** tests for the package. | `extras_require={'test': ['pytest']}`, as in the other packages |
| `indoor_nav_gazebo` | `package.xml` declared only `rclpy` and message packages | Added `exec_depend`: `ament_index_python`, `launch`, `launch_ros`, `ros_gz_sim`, `ros_gz_bridge`, `tf2_ros`, `indoor_nav_costmap` |
| `indoor_nav_costmap` | Missing dependencies for the nodes, the launch files and the Nav2 plugins named in the parameters | Added `exec_depend`: `python3-opencv`, `sensor_msgs_py`, `tf2_ros`, `launch`, `launch_ros`, `smartphone_depth_bridge`, `nav2_amcl`, `nav2_map_server`, `nav2_lifecycle_manager`, `nav2_planner`, `nav2_controller`, `nav2_behaviors`, `nav2_bt_navigator`, `nav2_costmap_2d`, `nav2_navfn_planner`, `dwb_core`, `dwb_critics`, `dwb_plugins` |
| `smartphone_depth_bridge` | — | Dependencies already complete |

**Results.**
- `colcon build --symlink-install` builds 3/3 packages, and so does a plain `colcon build`.
- `colcon graph` orders them `smartphone_depth_bridge` → `indoor_nav_costmap` → `indoor_nav_gazebo`.
- Every declared ROS dependency resolves.
- All 5 launch files load (`ros2 launch ... --show-args`).
- `gz sdf -k` reports the worlds and the robot as valid.

**`colcon test` (final state): 25 tests, 17 passed, 5 failed, 3 skipped.**
- All functional tests pass. That includes 10 `test_depth_to_scan` tests (3 for the original MiDaS mode and 7 new geometry-based tests for the metric mode), and `mypy` and `xmllint` in every package.
- The 5 failures are code-style checks only (`flake8` in 3 packages, `pep257` in 2), mostly quote style. They existed before Phase 1.
- The 3 skips are copyright checks; no licence headers have been added yet.

---

## 6. Simulation bring-up fixes

| Problem | Evidence | Fix |
|---|---|---|
| Robot odometry published under the wrong frame. `fyp_robot.sdf` used `<child_frame_id>`, which the gz-sim OdometryPublisher ignores, so it published `odom → fyp_robot/base_footprint` (its default). | `/tf` showed `child_frame_id: fyp_robot/base_footprint`. Nav2 failed with `transform from base_link to odom did not become available`. | `<robot_base_frame>base_link</robot_base_frame>` |
| `run_system.sh` reported "all lifecycle nodes active" while 4 of 6 were `inactive`. Its check `grep -q "active"` also matches `inactive`. | `ros2 lifecycle get` showed `inactive [2]` | `grep -q "^active"` |
| `indoor_world.sdf` did not load the `gz-sim-sensors-system` plugin, so the robot's RGB-D camera **never rendered or published**. | No publisher on `/rgbd_camera/depth_image` | Added the Sensors system (ogre2), the same as `realroom_world.sdf` |

---

## 7. Gazebo RGB-D camera integration (simulation only)

| Property | Value | How verified |
|---|---|---|
| Gazebo topics | `/rgbd_camera/{depth_image, camera_info, image, points}` | `gz topic -l` |
| ROS depth topic | `/rgbd_camera/depth_image`, `sensor_msgs/Image` | bridged |
| Encoding / size / units | `32FC1`, 640×480, **metres** along the optical axis | live message; the farthest value straight ahead (5.533 m) matches the right-hand wall's inner face (5.55 m) |
| `frame_id` | `rgbd_camera_optical` | live message |
| Intrinsics (`CameraInfo`) | fx = fy = 467.74, cx = 320, cy = 240, no distortion | live message; equals 320 / tan(1.2/2) |
| Rate | configured 15 Hz. Measured 15.1 Hz with the simulation alone; **2.0–9.4 Hz** with the full stack (CPU load) | `ros2 topic hz`, trial pre-checks |
| Mount (`base_link → sim_depth_camera`) | (0.35, 0, 0.10) m, body axes | from the SDF link and sensor poses |

The depth image and `CameraInfo` are bridged **only when
`FYP_DEPTH_SOURCE=gazebo`** (`simulation.launch.py`). The bridge is otherwise
unchanged.

---

## 8. Depth-to-LaserScan conversion and tilt correction (simulation only)

`depth_to_scan` gained a **`depth_mode: metric`** mode, used only in Gazebo
mode. The original MiDaS path (`depth_mode: relative`) is unchanged and
remains the default.

**Why tilt correction is needed.** The simulated robot rests **pitched 4.35°
nose-down** (quaternion y = 0.0380, identical in Gazebo and `/odom`). Its
camera's centre rows therefore look at the **floor about 3.3 m ahead**. A plain
row-band conversion reports that floor as a wall, which a unit test
reproduces.

**Method** (`DepthToScan.levelled_scan_from_depth`):
1. **Back-project every pixel.** Each pixel *(u, v)* with depth *z* goes through
   the pinhole model, using the intrinsics from `CameraInfo`. In the camera body
   frame that gives *x = z*, *y = −(u−cx)·z/fx*, *h = −(v−cy)·z/fy*.
2. **Read the camera's tilt at the image's own timestamp.** Roll and pitch come
   from TF `odom → sim_depth_camera`, looked up at the image stamp with a 0.2 s
   timeout. Gazebo's `odom` is gravity-aligned because the odometry plugin
   reports the true pose.
3. **Rotate into a level frame.** *p′ = R_y(pitch)·R_x(roll)·p* gives the
   **levelled frame `sim_depth_scan`**: the camera's position and heading, with
   roll and pitch removed and *z* aligned with gravity.
4. **Vertical filter.** A point is kept if its elevation above the horizontal
   lies in [**0.02, 0.15**] rad (1.1°–8.6°).
   - Accepted rays rise, so they **cannot hit the floor**.
   - At 5.5 m they sample 0.11–0.83 m above the camera (about 0.28 m above the
     floor), so walls (3 m) and obstacles (≥ 1 m) are seen.
   - Surfaces lower than camera height + *d*·tan(1.1°) are not seen.
5. **Bin by bearing.** Each angular bin keeps the **nearest** horizontal distance.
   Empty bins are `+inf` (REP 117).
6. **Publish.** The `LaserScan` goes out in `sim_depth_scan`, stamped with the
   image time, with the angular limits taken from the intrinsics
   (−0.5985 … +0.6000 rad), 160 beams, and ranges 0.15–8.0 m. The matching
   `sim_depth_camera → sim_depth_scan` transform is broadcast for every image.
   `pixel_stride` is 2.

**Threading fix.** `TransformListener(spin_thread=True)` adds the node to a
second executor in this rclpy version. That left the TF buffer 4–5 s stale, so
every lookup failed. The node now runs in a `MultiThreadedExecutor`, with the
depth callback in its own callback group.

**Accuracy against known geometry.** Every scan beam was compared with a 2-D
ray-cast of `indoor_world.sdf` from the true pose:

| Condition | Scans / beams | Median \|error\| | Within 0.10 m | Floor / phantom returns | Evidence |
|---|---|---|---|---|---|
| Stationary | 89 / 14,240 | 1.3 cm | 100 % | 0 | console output during development (not preserved as a file) |
| Driving (pitch 4.35°–5.43°) | 363 / 58,080 | 1.2 cm | 99.7 % | 36 (0.06 %) | `evidence/phase1/development/scan_vs_world_while_moving.txt` |
| Stationary at the goal, signed | 11,607 beams | scan − world: median −1.1 cm | 100 % | 0 | console output (not preserved) |

---

## 9. TF configuration (Gazebo mode)

```
map ──(AMCL)──> odom ──(Gazebo odometry, true pose)──> base_link
base_link ──(static 0.35, 0, 0.10)──> sim_depth_camera ──(per image: −roll, −pitch)──> sim_depth_scan
base_link ──(static 0.30, 0, 0.20)──> camera_depth_frame      (phone mount, unchanged)
```

AMCL's 2-D `map → odom` absorbs the odometry pitch. As a result,
`sim_depth_scan` appears pitched −4.35° when viewed in the *map* frame. AMCL
uses only x, y and heading from the laser pose, so this does not affect
localization.

---

## 10. AMCL and Nav2 configuration

### 10.1 How the simulation-only settings are applied

`nav2_params.yaml` is **unchanged**. When `FYP_DEPTH_SOURCE=gazebo`,
`localization.launch.py` and `navigation.launch.py` append parameter
overrides after it.

In phone mode (the default), the launch description was checked node by node
against the committed version: parameter values, remappings and arguments are
identical. A runtime check in phone mode showed:
- `/scan` comes from `/smartphone/depth`: `depth_mode: relative`, frame `base_link`.
- AMCL runs with its original values.
- The default goal checker is in place.
- No `/rgbd_camera` topics are bridged.

### 10.2 AMCL (Gazebo mode only)

| Parameter | Default (phone mode) | Gazebo mode | Reason |
|---|---|---|---|
| `alpha1`–`alpha4` | 0.2 | **0.02** | Gazebo odometry equals ground truth. The noise is reduced 10×, not zeroed, so the filter can still absorb residual error |
| `update_min_d` | 0.25 m | **0.05 m** | More frequent corrections |
| `update_min_a` | 0.2 rad | **0.05 rad** | More frequent corrections |
| `resample_interval` | 1 | **2** | Limits particle depletion at the higher update rate |
| `sigma_hit` | 0.2 m | **0.1 m** | Measured scan error is about 1 cm and the map resolution is 5 cm; 0.2 m was too flat |
| particles, `max_beams`, `z_hit`, `z_rand`, `alpha5` | 300–2000, 60, 0.5, 0.5, 0.2 | unchanged | — |

### 10.3 Nav2 goal checker

`nav2_params.yaml` defines **no** goal checker. Nav2 therefore uses its
default `goal_checker`, a `SimpleGoalChecker` with **xy 0.25 m** (verified at
runtime). The `FollowPath.xy_goal_tolerance: 0.15` in the file only feeds
DWB's critics.

In Gazebo mode: `general_goal_checker` (`SimpleGoalChecker`), **xy 0.05 m**,
yaw 0.25 rad, `stateful: true`, plus `FollowPath.xy_goal_tolerance 0.05`.

The robot stops as soon as the **AMCL estimate** is inside the tolerance, so
its true error is up to tolerance + localization error. At 0.10 m, two runs
ended **0.176 m** and **0.174 m** from the goal by ground truth, so 0.05 m was
used. The 0.15 m ground-truth acceptance limit was not changed.

---

## 11. Five-run repeatability validation (acceptance test)

**Protocol:**
- Every run restarted the complete stack, so Gazebo, AMCL and Nav2 had no state
  carried over. The robot spawned at its start pose with zero velocity, and
  AMCL was initialised at (0, −2) from the launch configuration.
- Before the goal was sent, each run confirmed: 6/6 Nav2 lifecycle nodes
  `active`, 4/4 TF links, depth / `/scan` / `/odom` / `/clock` publishing, and the
  AMCL and goal-checker parameters read back from the running nodes.
- Goal **(2.0, 0.0)** in `map`, sent with `send_test_goal.sh`.
- After the robot had stopped (|v|, |ω| < 0.01 for 3 s of simulation time), the
  **Gazebo ground-truth** position was read from `/world/indoor_world/pose/info`.

| Run | Start (truth) | Final (truth) | Final (AMCL) | **Truth distance from goal** | Localization error | AMCL 1-σ x / y / yaw | Duration | AMCL updates | Recoveries | Nav2 result | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | (0.014, −2.000) | (1.924, −0.094) | (1.963, −0.040) | **0.121 m** | 0.067 m | 0.050 / 0.057 m / 3.9° | 20.7 s | 16 | 0 | SUCCEEDED | ✅ |
| 2 | (0.014, −2.000) | (1.925, −0.092) | (1.969, −0.036) | **0.119 m** | 0.072 m | 0.029 / 0.047 m / 1.2° | 12.6 s | 15 | 0 | SUCCEEDED | ✅ |
| 3 | (0.014, −2.000) | (1.935, −0.084) | (1.975, −0.029) | **0.106 m** | 0.067 m | 0.030 / 0.035 m / 1.2° | 12.6 s | 17 | 0 | SUCCEEDED | ✅ |
| 4 | (0.014, −2.000) | (1.908, −0.112) | (1.966, −0.048) | **0.144 m** | 0.086 m | 0.033 / 0.044 m / 1.5° | 12.8 s | 14 | 0 | SUCCEEDED | ✅ |
| 5 | (0.014, −2.000) | (1.919, −0.095) | (1.970, −0.054) | **0.125 m** | 0.066 m | 0.031 / 0.037 m / 1.3° | 13.7 s | 15 | 0 | SUCCEEDED | ✅ |

Source: `evidence/phase1/repeatability/results.jsonl` (`summary.csv`).

### Statistics

| Metric | Value |
|---|---|
| Success rate (ground truth ≤ 0.15 m) | **5 / 5 (100 %)** |
| Nav2 `SUCCEEDED` | 5 / 5 |
| Ground-truth distance from goal: mean / min / max | **0.123 m** / 0.106 m / **0.144 m** |
| Ground-truth distance: sample standard deviation | 0.014 m (mean + 3σ = 0.165 m) |
| Localization error (AMCL vs truth): mean / max | 0.072 m / 0.086 m |
| Navigation duration: mean (range) | 14.5 s (12.6–20.7 s) |
| Recovery behaviours | 0 in all runs |

### Progress over the tuning iterations (same start and goal)

| Configuration | Truth distance from goal | AMCL error |
|---|---|---|
| MiDaS depth of the phone simulator's test images (desktop wallpapers) used for localization | ~1.9 m | ~2.2 m |
| Gazebo depth, default AMCL, default goal checker (0.25 m) | 0.339 m | 0.18 m (σ 0.23 / 0.34 m) |
| Tuned AMCL, goal tolerance 0.10 m (2 runs) | 0.176 / 0.174 m | 0.082 / 0.060 m |
| Tuned AMCL, goal tolerance 0.05 m: final configuration | 0.106–0.144 m (5 runs) | 0.066–0.086 m |

The first row is the first end-to-end run (16 Nov). Its numbers were recorded
from the console and are not preserved as a file.

---

## 12. Analysis of the remaining error

- **The error is systematic, not random.** In all five runs, AMCL's error
  points along the robot's final approach heading (39°–54°, approach about 50°).
  The true shortfall from the goal points the same way (49.5°–52.2°). AMCL
  ended 0.04–0.06 m from the goal, inside the 0.05 m checker give or take a final
  adjustment, while the robot was a further ~0.07 m short.
- **Two measured causes push the same way**, both making AMCL believe the robot
  is further along than it is:
  1. **Map scoring:** AMCL's likelihood-field model scores scan points against
     the *centres* of occupied map cells. Those sit **2.5 cm (half a 5 cm cell)
     behind** the true surfaces. The map's occupied edges match the world within
     1 mm.
  2. **Scan bias:** taking the nearest return in each bin reads short by a median
     of **1.1 cm** (signed scan − world).
- **Limited view near the goal:** the 69° camera often sees only a single wall
  there, which constrains position poorly along that wall.
- **Run 4**, the largest error, followed the same pattern; its AMCL error simply
  started growing earlier on the approach.

---

## 13. Known limitations

1. **About 7 cm systematic localization bias in simulation** (§12), and a
   **narrow accuracy margin**: worst run 0.144 m against the 0.15 m limit, mean +
   3σ = 0.165 m. A larger sample would probably include occasional runs over
   0.15 m. Five runs are too few to estimate that rate reliably.
2. **Phone-mode navigation with real smartphone camera data is unverified.**
   Phase 1 navigation used the simulated RGB-D camera. The smartphone path
   (Android → FastAPI → MiDaS → `/smartphone/depth` → `depth_to_scan` relative
   mode) was only checked to start and publish `/scan`, using a desktop-image
   phone simulator.
3. **The Android app cannot currently build or connect.** Its
   `app/build.gradle.kts` is empty, `MainActivity.kt` contains leftover
   shell-command lines, the `INTERNET` permission is missing, the server IP is
   hard-coded, and it has no discovery client. Out of Phase 1 scope.
4. **The phone-mode scan is mirrored** (left/right swapped) in the existing
   relative conversion. A unit probe confirmed this; it is not fixed.
5. **Live depth does not feed the costmaps.** Both costmaps' obstacle layers are
   disabled in `nav2_params.yaml`, and the `/smartphone_map` produced by the depth
   pipeline has no subscriber. Obstacle avoidance from live depth is therefore not
   part of these results.
6. **Simulation-specific tuning.** The Gazebo AMCL settings deliberately trust
   Gazebo's exact odometry; they are not suitable for real wheel odometry. Phone
   mode keeps the original settings, which remain untested on a real robot.
7. **Only one route was tested:** a single start pose, goal and world
   (`indoor_world.sdf`).
8. **Performance depends on load:** with the full stack, depth arrived at
   2.0–9.4 Hz. The goal tolerance of 0.05 m is close to the controller's
   precision: in one development run it needed recovery behaviours, because
   DWB settling conflicts with the progress checker
   (`required_movement_radius 0.15`, `movement_time_allowance 25 s`).
9. **The camera renders in phone-mode simulations too.** The world now loads the
   Sensors system, so the robot's RGB-D camera renders whenever this world runs,
   costing CPU even when it is not used.
10. **`run_system.sh` still shows false "NOT ready" warnings** for `/odom` and
    `map→odom`. Its probes use wall-clock time or run before AMCL is active.
    Direct checks show both working.
11. **Code style:** `flake8` / `pep257` failures (pre-existing quote and docstring
    style). There are no copyright headers. `rosdep` is not initialised.

---

## 14. Reproducing the Phase 1 tests

Prerequisites: the tested environment (§2), the backend venv and MiDaS
weights (`docs/BACKEND_SETUP.md`).

```bash
# 1. Build and test the workspace (in a terminal without the backend venv active)
cd ros2_ws
source /opt/ros/lyrical/setup.bash
colcon build --symlink-install
colcon test && colcon test-result --all
cd ..

# 2. Start the full simulated stack with Gazebo depth as the localization sensor
export FYP_DEPTH_SOURCE=gazebo
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST   # optional: keep ROS traffic on this PC
./run_system.sh
#   ignore its "/odom NOT ready" and "map->odom missing" warnings (§13.10);
#   it must end with "SYSTEM UP — all lifecycle nodes active".

# 3. Check that all six Nav2 nodes are genuinely active
for n in map_server amcl controller_server planner_server behavior_server bt_navigator; do
  ros2 lifecycle get /$n
done

# 4. Send the test goal (2.0, 0.0)
./send_test_goal.sh

# 5. Read the robot's true position from Gazebo after it stops
GZ_IP=127.0.0.1 gz topic -e -t /world/indoor_world/pose/info -n 1 | grep -A6 'name: "fyp_robot"'
```

Automated five-run validation: the harness in
`docs/evidence/phase1/scripts/` (`run_trial.sh`, `trial_probe.py`,
`tf_check.py`, `amcl_cov.py`, `phase1_amcl_trace.py`, `stop_stack.sh`) produced
the results in §11. Set `S` in each script to the folder holding the scripts and
`R` to the repository root, then run:

```bash
: > "$S/results.jsonl"
for i in 1 2 3 4 5; do bash "$S/run_trial.sh" "$i"; done
```

`stop_stack.sh` stops only the processes this test starts (by PID). It runs
before and after each trial.

---

## 15. Files changed in Phase 1 (uncommitted, branch `fix/ros2-packaging`)

| File | Change | Applies to |
|---|---|---|
| `ros2_ws/src/indoor_nav_gazebo/setup.py` | Install `meshes/` correctly; `extras_require` for tests | all modes |
| `ros2_ws/src/indoor_nav_gazebo/package.xml` | Missing run-time dependencies | all modes |
| `ros2_ws/src/indoor_nav_costmap/package.xml` | Missing run-time dependencies | all modes |
| `realroom/capture_fresh/nav_targets.env` | `${FYP_ROOT}`-based paths | all modes |
| `scripts/fyp30_multi_goal_demo.py` | Expand `${FYP_ROOT}` when reading `FYP_MAP` | all modes |
| `ros2_ws/src/indoor_nav_gazebo/models/fyp_robot/fyp_robot.sdf` | Odometry `robot_base_frame` = `base_link` | all modes |
| `run_system.sh` | Anchored lifecycle check; documents `FYP_DEPTH_SOURCE` | all modes |
| `ros2_ws/src/indoor_nav_gazebo/worlds/indoor_world.sdf` | Sensors system (camera rendering) | all modes (see §13.9) |
| `ros2_ws/src/indoor_nav_gazebo/launch/simulation.launch.py` | Depth and `CameraInfo` bridge; `sim_depth_camera` TF | **Gazebo mode only** |
| `ros2_ws/src/indoor_nav_costmap/launch/localization.launch.py` | Depth source switch; metric scan parameters; AMCL overrides | **Gazebo mode only** (phone mode identical to before) |
| `ros2_ws/src/indoor_nav_costmap/launch/navigation.launch.py` | Goal checker 0.05 m | **Gazebo mode only** |
| `ros2_ws/src/indoor_nav_costmap/indoor_nav_costmap/depth_to_scan.py` | `metric` mode with tilt correction; multi-threaded executor | metric mode in Gazebo only; relative (phone) conversion unchanged |
| `ros2_ws/src/indoor_nav_costmap/test/test_depth_to_scan.py` | 7 geometry-based tests for metric mode | tests |

---

## 16. Recommendation

Phase 1 meets its acceptance criterion **in simulation**:
- 5/5 independent runs reached the goal within 0.15 m by ground truth, with no
  recoveries.
- The workspace builds and its functional tests pass.
- The repository is portable.

Before relying on this accuracy margin, the following are recommended:
- **Reduce the systematic localization bias** (§12): for example a 2.5 cm map,
  or a median instead of the nearest return per scan bin.
- **Validate navigation with real smartphone depth**, after fixing the mirrored
  phone-mode scan and the Android app (§13.2–13.4).
- **Feed live depth into the costmaps** (§13.5).
