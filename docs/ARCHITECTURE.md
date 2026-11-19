# Architecture: topic, frame and parameter contracts

This file was previously empty (0 bytes). The staged-pipeline overview and
component inventory live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (dated
2026-09-12); this file records the **interfaces that are actually verified
at runtime**, which is what breaks when something is changed.

Verified 18 Nov 2026 on `FYP_DEPTH_SOURCE=gazebo`.

## 1. Two processes, one HTTP boundary

```
Android phone  --WebSocket-->  FastAPI backend  --HTTP-->  ROS 2 nodes  -->  Gazebo
                               (project venv)             (system python)
```

The backend and the ROS nodes **must not share a python environment**:
`rclpy`/`cv_bridge` are built against system numpy 2.3.5 / OpenCV 4.10.0,
while the venv carries numpy 2.5.5 / OpenCV 5.0.0. Their only coupling is
HTTP, which is what makes that safe.

## 2. Backend endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | `device`, `midas`, `frames_received`, `depth_available`, `inference_active`, `discovery_port` |
| `WS /ws/video` | Phone pushes JPEG frames; acknowledged immediately |
| `GET /latest-frame` | Most recent RGB frame |
| `GET /latest-depth` | Most recent depth array |
| `GET /latest-depth-image` | Depth as a normalised PNG — what the ROS bridge polls |

**Inference is latest-frame-wins, not queued** (`backend/api/main.py`
`inference_worker`): `pending_frame` is overwritten, so stale frames are
dropped rather than backing up. The WebSocket therefore acknowledges in
~6 ms while depth is produced at the model's own rate. Depth throughput is
pinned to the model, not to the stream rate — about 5.3 fps on the Quadro
T2000 and 22–25 fps on the RTX 4050.

A UDP discovery responder already runs in the backend
(`discovery_responder`, port reported by `/health`). Only the Android
*client* side is missing.

## 3. Depth → scan contract

`depth_to_scan` has two modes and they are not interchangeable.

| | `relative` (default, phone) | `metric` (Gazebo) |
|---|---|---|
| Input | `/smartphone/depth` (MiDaS inverse relative depth) | `/rgbd_camera/depth_image`, 32FC1 metres |
| Ranges | **not calibrated** — normalised and anchored by `near_range_anchor` | true metres |
| Frame | `base_link` | `sim_depth_scan` (levelled, published per image) |
| Range limits | 0.15 … 3.5 m | 0.15 … 8.0 m |
| Beams | 120 | 160 |

`LaserScan` ordering follows REP 103: index 0 is `angle_min`, the
**rightmost** bearing, and the last index is `angle_max`, the robot's left.
The `relative` path builds its array in image-column order (left → right)
and so must be reversed before publishing — publishing column order
directly mirrors the scan left/right. The `metric` path bins by bearing and
is unaffected. Pinned by
`test_relative_scan_is_not_mirrored_left_right` and
`test_rolled_camera_keeps_left_obstacle_on_the_left`.

Empty angular bins are `+inf` (REP 117). Any consumer must handle that
explicitly — for `nav2_costmap_2d::ObstacleLayer` this means
`inf_is_valid: true`, or free space is never cleared.

## 4. TF chain (Gazebo mode)

```
map ──(AMCL, 2-D)──> odom ──(Gazebo odometry, true pose)──> base_link
base_link ──(static 0.35, 0, 0.10)──> sim_depth_camera
sim_depth_camera ──(per image: −roll, −pitch)──> sim_depth_scan
base_link ──(static 0.30, 0, 0.20)──> camera_depth_frame   (phone mount)
```

The robot rests pitched 4.35° nose-down, so the levelled `sim_depth_scan`
frame is what keeps the floor out of the scan. Measured: `/scan` and the
`sim_depth_scan` transform are published in the same callback and every
scan stamp has an exact matching TF stamp; scans lag `/clock` by ~0.4 s.

`/scan` is published **BEST_EFFORT**. A RELIABLE subscriber receives
nothing at all, silently except for a QoS warning.

## 5. Parameter contract

`ros2_ws/src/indoor_nav_costmap/config/nav2_params.yaml` is the **Phase 1
acceptance configuration and is not edited** by later phases. Variations are
applied as launch-time overlays keyed off environment variables:

| Variable | Effect |
|---|---|
| `FYP_DEPTH_SOURCE=gazebo` | Simulated depth camera; metric scan mode; tuned AMCL; 0.05 m goal checker |
| `FYP_REACTIVE_OBSTACLES=1` | Phase 2 reactive obstacle layer — see [`PHASE2_REACTIVE_OBSTACLES.md`](PHASE2_REACTIVE_OBSTACLES.md) |

Unset, both leave the committed file untouched, which is what keeps the
Phase 1 result reproducible.

The costmaps are **not standalone nodes**: `global_costmap` runs inside
`planner_server` and `local_costmap` inside `controller_server`. Appending
a parameter to those nodes in a launch file therefore cannot reach a
costmap — it reads its own `<name>.<name>.ros__parameters` block from the
YAML file. That is why `indoor_nav_costmap/params_overlay.py` writes a
patched copy instead.

## 6. Safety net (never relaxed)

| Item | Value |
|---|---|
| Costmap inflation radius | 0.45 m, both costmaps |
| `collision_monitor` `PolygonStop` | `[-0.20 … 0.45] x ±0.30` m, action `stop` |
| Footprint | 0.7 × 0.5 m, inscribed radius 0.25 m |

These are not traded for speed or for obstacle-avoidance tuning.
