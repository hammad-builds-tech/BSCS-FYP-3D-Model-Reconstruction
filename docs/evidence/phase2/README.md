# Phase 2 test evidence

Raw evidence behind
[`docs/PHASE2_REACTIVE_OBSTACLES.md`](../../PHASE2_REACTIVE_OBSTACLES.md).
Recorded 18 November 2026 on HP ZBook 15 G6 / Quadro T2000 / Ubuntu 26.04.1
/ ROS 2 Lyrical / Gazebo 10.5.0, with `FYP_DEPTH_SOURCE=gazebo`.

Trajectory logs were renamed from `.log` to `.txt` because the repository
`.gitignore` excludes `*.log`; their content is unchanged.

## Files

| File | Content |
|---|---|
| `results.csv` | One row per run: start and final ground-truth pose, goal error, minimum distance to the obstacle, executed vs straight-line path length, pass/fail. **Primary result file.** |
| `unmapped_box.sdf` | The test obstacle, spawned at runtime so no world file is modified and the static map never contains it |
| `trajectories/traj_N.txt` | Gazebo ground-truth pose of `fyp_robot`, sampled ~3 Hz for the whole run |

## Runs

| Run | Config | Box | Purpose |
|---|---|---|---|
| `1`–`5` | `FYP_REACTIVE_OBSTACLES=1` | yes | Acceptance: detect, replan around, reach the goal |
| `ctrlA` | flag unset | yes | **Control.** Same obstacle with the layer off — isolates the layer as the cause |
| `b1`, `b2` | flag unset | no | Phase 1 regression: the committed configuration still meets the 0.15 m limit |

## How the numbers were derived

- **Ground truth** is Gazebo's own pose for `fyp_robot`, read from
  `/world/indoor_world/pose/info`. Nav2 reporting `SUCCEEDED` does not count
  as success on its own, the same rule Phase 1 used.
- **Goal error** is the distance from the final ground-truth position to the
  goal (2.0, 0.0). Limit **0.15 m**, unchanged from Phase 1.
- **Minimum distance to box** is over the whole trajectory, robot centre to
  box centre at (1.0, −1.0). Threshold **0.55 m** = box half-width 0.20 m +
  the robot's 0.35 m half-length, i.e. head-on contact. Note this is *not*
  the 0.25 m inscribed radius, which applies side-on and would understate
  contact for a frontal approach.
- **exec/straight** is executed path length over the straight-line distance
  between first and last sample. With no obstacle it sits at 1.04; with the
  obstacle, 1.17. That gap is the detour.

## Reproducing

```bash
export FYP_DEPTH_SOURCE=gazebo FYP_REACTIVE_OBSTACLES=1
./run_system.sh                       # wait for "SYSTEM UP"

ros2 run ros_gz_sim create -world indoor_world \
  -file docs/evidence/phase2/unmapped_box.sdf \
  -name phase2_unmapped_box -x 1.0 -y -1.0 -z 0.6

bash docs/evidence/phase1/scripts/reset_robot.sh
./send_test_goal.sh
```

Read the obstacle back out of the costmaps with the service rather than the
topic — `global_costmap` publishes its full grid rarely, so the topic can be
stale:

```bash
ros2 service call /global_costmap/get_costmap nav2_msgs/srv/GetCostmap
```

**Restart the whole stack between runs if a run ended in contact.** A
collision leaves AMCL mislocalised and `reset_robot.sh` alone does not
recover it (see the Phase 2 document, limitation 5).
