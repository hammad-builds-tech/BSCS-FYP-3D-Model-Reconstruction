# Setting up a fresh clone

This file was previously empty (0 bytes). It is the step-by-step procedure
for getting a new clone running on a new machine, written so it does not
depend on any one developer's laptop. The root [`../SETUP.md`](../SETUP.md)
is an older baseline note and is not a procedure.

Verified on Ubuntu 26.04.1 / ROS 2 Lyrical / Gazebo 10.5.0 on two different
machines (see `CLAUDE.md` section 6).

## 0. What is and is not in Git

Not committed, so a fresh clone must create them:

| Path | How to get it |
|---|---|
| `venv/` | Step 2 below |
| `MiDaS/` | Step 3 (gitignored third-party code) |
| `MiDaS/weights/dpt_hybrid_384.pt` | Step 3 (492,757,791 bytes) |
| `ros2_ws/build,install,log` | Step 4 |

`run_backend.sh` checks for `MiDaS/` and the weights and prints the exact
commands if either is missing.

## 1. System prerequisites

```bash
ros2 --version && colcon version-check && gz sim --version
```

The ROS-side packages must already be installed; this project does not
install them. Required and checked on both machines: the Nav2 stack
(`nav2_amcl`, `nav2_controller`, `nav2_planner`, `nav2_behaviors`,
`nav2_bt_navigator`, `nav2_map_server`, `nav2_lifecycle_manager`,
`nav2_costmap_2d`, `nav2_navfn_planner`, `dwb_core`, `dwb_critics`,
`dwb_plugins`), plus `ros_gz_sim`, `ros_gz_bridge`, `tf2_ros`, `cv_bridge`,
`sensor_msgs_py` and `rviz2`.

### Extra package required for Phase 3

`nav2_collision_monitor` is **not** part of the base install and is **not**
needed for Phase 1 or Phase 2. Phase 3 puts it in the velocity command
chain, so install it before running any Phase 3 bring-up:

```bash
sudo apt-get install -y ros-lyrical-nav2-collision-monitor
```

Notes:

- The candidate is **1.5.2** while the rest of the Nav2 stack here is
  **1.5.1**. `apt` installs it as a single new package with no upgrades to
  any other Nav2 package, and the 1.5.2 binary links the 1.5.1 shared
  libraries cleanly (`ldd` resolves, and the node reaches `active`). This
  pairing is verified only on the two machines in `CLAUDE.md` section 6.
- `nav2_common` is **not** installed. The launch file shipped *inside*
  `nav2_collision_monitor` imports `nav2_common.launch.RewrittenYaml` and
  therefore **cannot run here**; the project's own
  `phase3_navigation.launch.py` does not use it.
- `scripts/phase3/run_system_phase3.sh` refuses to start if the package is
  missing, rather than silently bringing up the unguarded Phase 2 chain.

Phase 3 background and limitations:
[`PHASE3_COLLISION_MONITOR.md`](PHASE3_COLLISION_MONITOR.md),
[`PHASE3_COMMAND_WATCHDOG.md`](PHASE3_COMMAND_WATCHDOG.md).

**Keep conda out of ROS terminals.** `rclpy` and `cv_bridge` are built
against the *system* python, numpy and OpenCV. An active conda environment
puts its own python first on `PATH` and `import rclpy` then fails with the
misleading `ModuleNotFoundError: No module named 'em'`. Installing `empy`
into conda does not fix it — the numpy/OpenCV ABI differs too. Either:

```bash
conda deactivate                                  # per terminal
conda config --set auto_activate_base false       # once, permanent
```

`scripts/fyp_env.sh` warns when it sees `CONDA_PREFIX` set.

## 2. Backend virtual environment

Create it with the **system** interpreter, not conda's, so the backend does
not silently depend on a conda installation:

```bash
/usr/bin/python3 -m venv venv
venv/bin/pip install -r backend/requirements.lock.txt
```

About 3 GB of downloads, ~5.7 GB installed. Use
`backend/requirements.txt` instead if the lock file will not resolve on
your platform, then record your own lock with `venv/bin/pip freeze`.
Details and the compatibility scope: [`BACKEND_SETUP.md`](BACKEND_SETUP.md).

## 3. MiDaS code and weights

See [`BACKEND_SETUP.md`](BACKEND_SETUP.md) section 2. Phase 0/1 used
`isl-org/MiDaS` commit `4545977`. Verify the weights:

```bash
sha256sum MiDaS/weights/dpt_hybrid_384.pt
# 501f0c75b3bca7daec6b3682c5054c09b366765aef6fa3a09d03a5cb4b230853
```

## 4. Build the ROS 2 workspace

In a terminal with **no** backend venv active:

```bash
cd ros2_ws
source /opt/ros/lyrical/setup.bash
colcon build --symlink-install
colcon test && colcon test-result --all
cd ..
```

Expected: 3/3 packages build. `colcon test` reports **49 tests, 5 failures,
3 skipped**. All 5 failures are pre-existing code-style checks (`flake8` in
3 packages, `pep257` in 2) and the 3 skips are missing licence headers.
Every functional test passes. A functional failure means something is
wrong; the 5 style failures are the expected baseline.

## 5. Verify the GPU

```bash
venv/bin/python scripts/smoke_test_midas_gpu.py
```

Expect `RESULT: PASS`. Do **not** pass `--fp16` without checking your GPU
first: on the Quadro T2000 FP16 is ~4.7x *slower* than FP32
([`BACKEND_SETUP.md`](BACKEND_SETUP.md)).

## 6. Run it

Backend and ROS belong in separate terminals; they talk over HTTP only.

```bash
./run_backend.sh                      # terminal 1
curl http://127.0.0.1:8000/health     # expect "device":"cuda"
```

```bash
export FYP_DEPTH_SOURCE=gazebo        # terminal 2: simulated depth camera
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
./run_system.sh                       # ends with "SYSTEM UP"
./send_test_goal.sh
```

`run_system.sh` prints false `"/odom NOT ready"` and `"map->odom missing"`
warnings; both are known and harmless (Phase 1 report section 13.10). Wait
for `SYSTEM UP — all lifecycle nodes active`.

To enable the Phase 2 reactive obstacle layer, also export
`FYP_REACTIVE_OBSTACLES=1` — read
[`PHASE2_REACTIVE_OBSTACLES.md`](PHASE2_REACTIVE_OBSTACLES.md) first, it is
not complete.

## 7. Paths

Nothing should be hard-coded to a home directory. `scripts/fyp_env.sh` sets
`FYP_ROOT` from the clone's own location and `FYP_PY` to `venv/bin/python`,
warning if it has to fall back to another interpreter.
