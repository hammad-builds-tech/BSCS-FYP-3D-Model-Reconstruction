# Phase 3 test evidence

Raw evidence behind
[`docs/PHASE3_COLLISION_MONITOR.md`](../../PHASE3_COLLISION_MONITOR.md) and
[`docs/PHASE3_COMMAND_WATCHDOG.md`](../../PHASE3_COMMAND_WATCHDOG.md).

Recorded 19–20 November 2026 on HP ZBook 15 G6 / Quadro T2000 /
Ubuntu 26.04.1 / ROS 2 Lyrical / Gazebo 10.5.0, with
`FYP_DEPTH_SOURCE=gazebo` and `FYP_REACTIVE_OBSTACLES=1`.

## Files

| File | Content |
|---|---|
| `watchdog_results.csv` | One row per watchdog experiment. **Primary result file.** Includes the rows that are INVALID and why — see below. |
| `wd_<case>_<run>.trace` | Raw Gazebo ground-truth pose samples (~10 Hz) for one run: `x y z qx qy qz qw @unix_time`. Velocity in the CSV is differentiated from these. |
| `scenario_runs.jsonl` | One JSON object per obstacle-scenario run (Scenarios 1-5). **Primary scenario result file.** |

## Reading `scenario_runs.jsonl`

24 runs. `verdict` already accounts for whether the goal was reachable.
Rows that must NOT be cited:

| Row | Why |
|---|---|
| `s2a_gap_120` with `nav_result: UNKNOWN` (3.1 s, 8 samples) | Harness artifact: the goal was sent before the stack settled and the robot never moved. Re-run as the PASS row. |
| `s5_recovery` runs `1` and `2` (`min_clearance_m: -0.25`) | **False collisions.** `clearance()` still counted the wall that had been deleted mid-run, so driving through the now-empty space scored as driving through a wall. Superseded by `1f`/`2f`/`3f` after the check was made time-aware. |
| `s1_three_boxes`, `s1_spaced` | Genuine FAILs, kept deliberately: they document the 0.60 m head-on limit of the approved envelope. Superseded as a *capability* test by `s1_slalom`. |

**Zero real collisions occurred across all 24 runs.**

## Reading `watchdog_results.csv`

The `watchdog` column says which build produced the row, and this matters:

| `watchdog` value | Meaning |
|---|---|
| `absent` | No watchdog at all — the baseline latch measurement |
| `fixed` | The corrected watchdog. **These are the valid results.** |
| `buggy-crashpath` | **INVALID.** An earlier watchdog build called `get_logger().warn()`, which does not exist in this rclpy (`warning` does). The node therefore crashed the instant it first detected silence, and `respawn=True` restarted it; the fresh instance published zeros from its "nothing ever received" branch. The robot did stop, but by crash-and-respawn, not by the designed timeout. Kept for the record, not for citation. |
| `invalid` | **INVALID.** `collision_monitor` was already dead from a previous run (it has no `respawn`), so no command could reach the robot and it never moved (`peak_v 0.000`). |

Only rows with `watchdog == fixed` (plus the `absent` baseline) support any
claim in the write-up.

## Method

- **Ground truth only.** Pose comes from
  `/world/indoor_world/pose/info`, never from `/odom` or `/cmd_vel`, so the
  measurement does not depend on the ROS topics under test.
- **Velocity** is differentiated from consecutive pose samples.
- **`t_to_zero_s`** is the time from the event until speed stays below
  0.02 m/s for three consecutive samples. `NOT_STOPPED` means that never
  happened within the observation window.
- **`displacement_after_loss_m`** is the straight-line distance travelled
  from the event to the end of the window.
- Each case was run **three times**. `collision_monitor` does not respawn,
  so case C (kill the monitor) requires a **full stack restart between
  runs** — the first attempt at C runs 2–3 without a restart produced the
  `invalid` rows above.

## Reproducing

```bash
export FYP_DEPTH_SOURCE=gazebo FYP_REACTIVE_OBSTACLES=1
scripts/phase3/run_system_phase3.sh        # wait for "PHASE 3 UP"

scripts/phase3/watchdog_trial.sh A 1       # normal continuous commands
scripts/phase3/watchdog_trial.sh B 1       # publisher stops while moving
scripts/phase3/watchdog_trial.sh C 1       # kill collision_monitor while moving
scripts/phase3/watchdog_trial.sh D 1       # hard-kill the publisher while moving

scripts/phase3/stop_stack_phase3.sh        # NOT the Phase 1 stop script alone
```

Traces are written to `${TMPDIR:-/tmp}/fyp_phase3_traces` by default
(override with `WATCHDOG_TRACE_DIR`), deliberately outside the clone.

**Use `scripts/phase3/stop_stack_phase3.sh` to tear down.** The Phase 1
`stop_stack.sh` knows nothing about the Collision Monitor or the watchdog
and leaves both orphaned; an orphaned watchdog keeps publishing on
`/cmd_vel` and fights the next bring-up.

**Restart the whole stack between case C runs**, and after any run that
ended in contact — `reset_robot.sh` alone does not recover AMCL (Phase 2
limitation, re-confirmed here).
