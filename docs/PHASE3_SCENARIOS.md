# Phase 3 — obstacle scenario results

**Status: all five scenarios run. 24 runs, ZERO collisions.**

| Scenario | Result |
|---|---|
| 1 — multiple static obstacles (`s1_slalom`) | **3/3 PASS** |
| 2 — narrow passages | minimum navigable passage **0.70 m** |
| 3 — blocked route | **2/2 PASS** |
| 4 — moving obstacle (experimental) | **2/3 PASS**, no collisions |
| 5 — recovery | **3/3 PASS** |

The central engineering result is a measured capability limit, not a defect:
with the approved envelope the robot navigates passages down to **0.70 m**
and refuses narrower ones, but it **cannot pass an obstacle it must approach
head-on within 0.60 m**. Scenario 1 was redesigned around that limit under
**Option A** and then passed 3/3.

**Machine:** HP ZBook 15 G6, Quadro T2000, Ubuntu 26.04.1, ROS 2 Lyrical,
Gazebo 10.5.0. **Date:** 20 November 2026.
**Config:** `FYP_DEPTH_SOURCE=gazebo`, `FYP_REACTIVE_OBSTACLES=1`, Phase 3
chain (Collision Monitor + command watchdog).
**Approved envelope:** stop polygon front **0.60 m**, half-width **0.30 m**;
watchdog timeout **0.50 s**. Both signed off 20 Nov 2026.
**Evidence:** [`evidence/phase3/scenario_runs.jsonl`](evidence/phase3/README.md).

## 1. Acceptance criteria used

Unchanged from Phase 1/2, with one addition for unreachable goals:

| Goal type | Pass requires |
|---|---|
| Reachable | ground-truth error **≤ 0.15 m** AND no collision |
| Unreachable | no collision AND **no false success** (never `SUCCEEDED` while far from the goal) |

`SUCCEEDED` from Nav2 is never accepted on its own. Every figure below is
Gazebo ground truth sampled at ~4 Hz throughout the run. Obstacles are
spawned at runtime, so no world file is modified and the static map never
contains them.

Clearance is measured from the obstacle **surface** to the robot's inscribed
circle (0.25 m). It is pessimistic by up to 0.10 m for a frontal approach,
where the true half-extent is 0.35 m. Negative would mean overlap.

## 2. Results

| Scenario | Gap | Reachable | Nav2 result | Goal error | Min clearance | Verdict |
|---|---|---|---|---|---|---|
| `s1_three_boxes` run 1 | — | yes | TIMEOUT | 3.285 m | 0.262 m | ❌ FAIL |
| `s1_three_boxes` run 2 | — | yes | TIMEOUT | 3.337 m | 0.318 m | ❌ FAIL |
| `s1_three_boxes` run 3 | — | yes | TIMEOUT | 3.341 m | 0.323 m | ❌ FAIL |
| `s1_spaced` run 1 | 1.60 m | yes | TIMEOUT | 2.296 m | 0.343 m | ❌ FAIL |
| `s1_spaced` run 2 | 1.60 m | yes | TIMEOUT | 2.208 m | 0.259 m | ❌ FAIL |
| `s2a_gap_120` | 1.20 m | yes | **SUCCEEDED** | **0.069 m** | 0.349 m | ✅ PASS |
| `s2b_gap_090` | 0.90 m | yes | **SUCCEEDED** | **0.066 m** | 0.199 m | ✅ PASS |
| `s2d_gap_070` | 0.70 m | yes | **SUCCEEDED** | **0.068 m** | 0.099 m | ✅ PASS |
| `s2e_gap_055` | 0.55 m | yes | TIMEOUT | 1.649 m | **0.0006 m** | ❌ FAIL |
| `s2c_gap_045` | 0.45 m | no | TIMEOUT | 1.953 m | 0.166 m | ✅ PASS |
| `s3_blocked` run 1 | sealed | no | TIMEOUT | 2.165 m | 0.315 m | ✅ PASS |
| `s3_blocked` run 2 | sealed | no | TIMEOUT | 2.166 m | 0.316 m | ✅ PASS |

One `s2a_gap_120` row in the evidence file is marked `UNKNOWN` with a 3.1 s
duration and 8 samples: the goal action returned before the stack had
settled and the robot never moved. It is a harness artifact, **not** a
navigation failure, and was re-run (the PASS row above).

## 3. Scenario 2 — minimum navigable passage: **0.70 m**

This is the clean quantitative result of the phase.

| Gap | Outcome |
|---|---|
| 1.20 m | passes, 0.069 m goal error, straight through (ratio 0.999) |
| 0.90 m | passes, 0.066 m goal error (ratio 1.000) |
| **0.70 m** | **passes, 0.068 m goal error — narrowest confirmed** |
| 0.55 m | **enters the gap and wedges**, 0.0006 m clearance |
| 0.45 m | refuses before entering, stops 0.547 m short |

**The limit is set by the Collision Monitor, not by the chassis.** The robot
is 0.50 m wide, so geometrically a 0.55 m gap fits. But `PolygonStop` is
±0.30 m wide, so a centred pass puts each wall face at `G/2` laterally and
trips the stop whenever `G ≤ 0.60 m`. Predicted threshold "just over
0.60 m"; measured between 0.55 m (blocked) and 0.70 m (passes).

### 0.55 m is the dangerous case

At 0.45 m the robot **stops before entering** (0.547 m travelled). At 0.55 m
it **drives in and gets stuck**, ending with 0.0006 m clearance — the
inscribed circle grazing the wall. It did not overlap, so it is not scored
as a collision, but it is effectively in contact and cannot recover.

A gap that is wide enough to enter but too narrow to pass is worse than one
the robot refuses outright. This is the main safety-relevant finding of the
scenario work and should be raised in the report.

## 4. Scenario 1 — why it fails, reproducibly

3/3 runs of the original layout and 2/2 of the spaced variant end in
`TIMEOUT` with no collision. The cause is the same every time:

```
collision_monitor: Robot to stop due to PolygonStop polygon
controller_server: Failed to make progress   (error_code 105, x5)
```

The halt positions are quantitatively consistent with the approved zone:

| Run | Obstacle surface distance from `base_link` at halt |
|---|---|
| `s1_three_boxes` 1 / 2 / 3 | 0.512 / 0.568 / 0.573 m |
| `s1_spaced` 1 / 2 | 0.593 / 0.508 m |

All five cluster at **0.51–0.59 m**, i.e. right at the 0.60 m polygon edge.
The Collision Monitor is the limiting factor, not the costmap.

### The underlying conflict

| Parameter | Value | Owner |
|---|---|---|
| costmap `inflation_radius` | 0.45 m | Phase 1/2, must not change |
| `PolygonStop` front edge | 0.60 m | Phase 3, approved |

The planner is free to route ~0.45 m from an obstacle, because that is where
inflation cost falls away. The monitor halts at 0.60 m. **So the monitor
vetoes paths the planner considers valid whenever the route approaches an
obstacle head-on.** Nav2 then retries, the controller reports "failed to
make progress", and the goal never completes.

This applies to **head-on approaches only**. Lateral passes are unaffected,
which is why Scenario 2 succeeds down to 0.70 m — an early hypothesis that
lateral passes were the binding case was tested and **disproved** by
`s2b_gap_090` passing with each wall 0.45 m to the side.

Both `s1_three_boxes` and `s1_spaced` are retained in the harness: they
document a real limit rather than a bad test.

## 5. Scenario 3 — blocked route: PASS

Five walls seal `x = 1.0` across the full room width, so no route exists.
2/2 runs: the robot advances 0.333 m, stops **0.565 m short of the wall
face**, never collides (clearance 0.315 m) and never reports `SUCCEEDED`.
Required behaviour met.

### But Nav2's failure reporting is weak

Nav2 does **not** return a definitive failure. Internally the controller
emits `error_code 105 "Failed to make progress"` and the behaviour tree
retries indefinitely; the action was still running when the harness timeout
expired at 100 s. So of the three Scenario 3 requirements — *do not drive
into the obstacle*, *do not claim success*, *report failure appropriately* —
the first two are met and the **third is only partially met**. A consumer
waiting on the action would wait forever rather than receive an abort.

This matters for Scenario 5 and should be treated as a finding, not a pass.

## 6. Scenario 1 redesigned under Option A — 3/3 PASS

`s1_slalom`: three 0.4 m boxes at (1.0, −2.75), (2.0, −1.25), (3.0, −2.75),
goal (3.20, −1.00). The straight line start→goal **intersects box B**, so a
detour is required, but every obstacle is offset laterally and the free lane
below B is **1.10 m** — above the measured 0.70 m minimum — so the robot
never has to point at an obstacle from inside the 0.60 m zone.

| Run | Nav2 | Goal error | Min clearance | exec/straight |
|---|---|---|---|---|
| 1 | SUCCEEDED | **0.094 m** | 0.227 m | 1.103 |
| 2 | SUCCEEDED | **0.097 m** | 0.226 m | 1.099 |
| 3 | SUCCEEDED | **0.111 m** | 0.246 m | 1.098 |

All three inside the 0.15 m limit, no collisions, and ratio ~1.10 confirms a
real detour rather than a straight run. **Scenario 1's objective — detect
multiple obstacles, plan around them, reach a reachable goal — is met**, with
the geometry respecting the approved envelope.

## 7. Scenario 5 — recovery: 3/3 PASS

Three walls seal `x = 1.0`; the middle one is deleted at **t+25 s**.

| Run | Nav2 | Goal error | Min clearance | Blocker removed | Duration |
|---|---|---|---|---|---|
| 1f | SUCCEEDED | **0.075 m** | 0.248 m | 25.2 s | 38.9 s |
| 2f | SUCCEEDED | **0.076 m** | 0.277 m | 25.2 s | 37.3 s |
| 3f | SUCCEEDED | **0.074 m** | 0.314 m | 25.3 s | 38.4 s |

The robot holds safely while blocked, then completes **12–14 s** after a
route appears. No collisions.

### A harness bug that produced two false collisions

The first two Scenario 5 runs reported `min_clearance = -0.2500` — exactly
`-HALF_WID` — and were scored FAIL. That was wrong: `clearance()` still
counted the wall that had been **deleted**, so when the robot drove through
the now-empty space it was scored as driving through a wall. The check is
now time-aware and ignores a removed obstacle for the part of the path after
its removal. The two bad rows are kept in the evidence file (runs `1`, `2`)
and superseded by `1f`/`2f`/`3f`. **No real collision occurred.**

## 8. Scenario 4 — moving obstacle (EXPERIMENTAL): 2/3 PASS

Outside the static-environment core scope, as agreed. One 0.4 m box is
translated from (2.0, −3.20) toward y = −0.80 at **0.20 m/s** from t+2 s,
crossing the route while the robot drives to (3.20, −2.00).

| Run | Nav2 | Goal error | Min clearance | exec/straight | Verdict |
|---|---|---|---|---|---|
| 1 | SUCCEEDED | **0.072 m** | 0.567 m | 1.179 | ✅ |
| 2 | TIMEOUT | **2.270 m** | 0.563 m | **2.065** | ❌ |
| 3 | SUCCEEDED | **0.071 m** | 0.560 m | 1.084 | ✅ |

**Safety held in all three runs**: no collision, and minimum clearance was a
consistent **0.56 m** — the stop polygon keeping the robot off the moving
box. **Goal completion did not**: run 2 was deflected to (1.265, −0.813),
2.27 m from the goal, with a path ratio of 2.065, and never recovered inside
110 s.

So with a moving obstacle the safety layer is reliable but **goal completion
is only ~67 %**. A likely contributor is costmap smearing: a moving obstacle
marks cells along its whole track, and those cells only clear when the
sensor re-observes them as free, which at 2 Hz global costmap updates and a
69° FOV may never happen for cells now behind the robot. **This is a
hypothesis, not a measured cause** — it was not confirmed, and confirming it
is the recommended next step.

## 7. Limitations

1. **The original Scenario 1 layouts remain blocked** by the approved
   envelope (§4). They are retained as evidence of a real limit. The
   redesigned `s1_slalom` passes 3/3 (§6).
2. **The 0.70 m minimum is specific to this envelope.** It is a function of
   the ±0.30 m polygon half-width, so it changes if the polygon changes.
3. **Run counts are uneven.** `s1_slalom`, `s5_recovery` and `s4_crossing`
   have 3 runs each; `s3_blocked` has 2; **each Scenario 2 gap has only 1**.
   The 0.70 m threshold should be repeated >=3 times per gap before being
   quoted as a specification.
4. **Scenario 4 is experimental and non-deterministic** (2/3). One obstacle,
   one speed (0.20 m/s), one crossing direction. No speed sweep was run, so
   nothing is known about the detection-latency limit.
4. **Clearance is approximated** by the inscribed circle (§1), pessimistic
   by up to 0.10 m frontally.
5. **Metric/Gazebo depth only**; relative/phone mode remains uncalibrated.
6. `s2e_gap_055` left the robot wedged in contact-adjacent state. Per the
   standing project rule, the stack was restarted before the next run —
   `reset_robot.sh` alone does not recover AMCL.

## 11. Recommended next step

Option A is decided and all five scenarios have run. The highest-value
remaining work, in order:

1. **Confirm or refute the costmap-smearing hypothesis** behind Scenario 4's
   run-2 failure (§8). This is the only unexplained failure left.
2. **Repeat each Scenario 2 gap >=3 times** so the 0.70 m minimum can be
   quoted as a specification rather than a single observation.
3. **Sweep Scenario 4 obstacle speed** (0.1 / 0.2 / 0.4 m/s) to find where
   detection latency breaks down.
4. **Address Nav2's weak failure reporting** (§5): a blocked goal never
   returns an abort, so a consumer waits indefinitely.

The earlier polygon options are retained for the record:

| Option | Effect |
|---|---|
| **A** Keep 0.60 m × ±0.30 m | Scenario 1 stays blocked; minimum passage stays 0.70 m. Safest, least capable. Document as the system's limit. |
| **B** Narrow half-width to ~±0.26 m, keep front 0.60 m | Preserves head-on protection; minimum passage drops toward ~0.52 m. Does **not** fix Scenario 1, which is a head-on case. |
| **C** Reduce front edge to 0.50 m (the detectability floor) | Closest to the 0.45 m inflation radius, so planner and monitor stop fighting. Leaves **zero** margin above the sensor's 0.500 m head-on minimum, so the zone becomes only marginally detectable. |

**DECIDED 20 Nov 2026: Option A.** The approved envelope stands
(0.60 m front, +/-0.30 m half-width). The 0.60 m head-on approach limit is
recorded as a measured characteristic of the system, not a defect, and
Scenario 1 was redesigned so its route never requires the robot to point at
an obstacle from inside that zone (see `s1_slalom` in
`scripts/phase3/scenario_runner.py` and section 9 below).
