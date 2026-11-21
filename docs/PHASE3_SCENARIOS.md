# Phase 3 — obstacle scenario results

**Status: all five scenarios run. 24 runs, ZERO collisions.**

| Scenario | Result |
|---|---|
| 1 — multiple static obstacles (`s1_slalom`) | **3/3 PASS** |
| 2 — narrow passages | minimum navigable passage **1.20 m** (corrected 21 Nov 2026) |
| 3 — blocked route | **2/2 PASS** |
| 4 — moving obstacle (experimental) | **2/3 PASS**, no collisions |
| 5 — recovery | **3/3 PASS** |

The central engineering result is a measured capability limit, not a defect:
with the approved envelope the robot **cannot pass an obstacle it must
approach head-on within 0.60 m**. Scenario 1 was redesigned around that
limit under **Option A** and then passed 3/3.

> **CORRECTION, 21 Nov 2026.** This document previously reported a minimum
> navigable passage of **0.70 m** on the strength of a single run per gap.
> The 21 Nov audit flagged that as a statistical weakness, and the follow-up
> repeat (6 runs per gap, under two independent methods) **did not
> reproduce it**: 0.70 m and 0.90 m failed 0/6 each, while 1.20 m passed
> 6/6. The reproducible figure is **1.20 m**. The true threshold lies
> between 0.90 m and 1.20 m and has **not** been measured. See section 3.

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
| `s2a_gap_120` | 1.20 m | yes | **SUCCEEDED** | **0.069 m** | 0.349 m | ✅ PASS (confirmed 7/7) |
| `s2b_gap_090` | 0.90 m | yes | **SUCCEEDED** | **0.066 m** | 0.199 m | ⚠️ SUPERSEDED — 0/6 on repeat (§3) |
| `s2d_gap_070` | 0.70 m | yes | **SUCCEEDED** | **0.068 m** | 0.099 m | ⚠️ SUPERSEDED — 0/6 on repeat (§3) |
| `s2e_gap_055` | 0.55 m | yes | TIMEOUT | 1.649 m | **0.0006 m** | ❌ FAIL |
| `s2c_gap_045` | 0.45 m | no | TIMEOUT | 1.953 m | 0.166 m | ✅ PASS |
| `s3_blocked` run 1 | sealed | no | TIMEOUT | 2.165 m | 0.315 m | ✅ PASS |
| `s3_blocked` run 2 | sealed | no | TIMEOUT | 2.166 m | 0.316 m | ✅ PASS |

One `s2a_gap_120` row in the evidence file is marked `UNKNOWN` with a 3.1 s
duration and 8 samples: the goal action returned before the stack had
settled and the robot never moved. It is a harness artifact, **not** a
navigation failure, and was re-run (the PASS row above).

## 3. Scenario 2 — minimum navigable passage: **1.20 m**

### 3.1 Corrected result (21 Nov 2026)

Each gap was re-run **six** times: three sharing one stack, and three with a
**guaranteed-fresh stack per run** (full teardown, bring-up, and an assertion
that `gz-sim-main` is alive and `collision_monitor` is `active` before the
goal is sent). Both methods agree.

| Gap | shared-stack | fresh-stack | original (1 run) | **total** |
|---|---|---|---|---|
| **1.20 m** | 3/3 PASS | 3/3 PASS | 1/1 PASS | **7/7 PASS** |
| 0.90 m | 0/3 | 0/3 | 1/1 PASS | 1/7 |
| 0.70 m | 0/3 | 0/3 | 1/1 PASS | 1/7 |

At 1.20 m the result is tight and repeatable: goal error **0.058–0.074 m**,
clearance 0.341–0.348 m, path ratio 0.999–1.002 (straight through).

At 0.90 m and 0.70 m every repeat failed with goal error **≈2.1 m** and
clearance 0.26–0.32 m — i.e. the obstacle surface sitting **0.51–0.57 m**
from `base_link`, inside the approved 0.60 m stop zone. That is the same
mechanism as the Scenario 1 failures in section 4: at a 0.70 m gap each wall
face is only 0.35 m lateral against a ±0.30 m polygon half-width, so a small
heading error is enough to bring a wall inside the zone.

**The single original passes at 0.70 m and 0.90 m are therefore treated as
outliers and must not be quoted.** Raw data, with full trajectories, is in
[`evidence/phase3/scenario_runs_s2_repeat.jsonl`](evidence/phase3/README.md)
and every row is recomputable with
`scripts/phase3/verify_scenario_runs.py` (18/18 reproduce).

### 3.2 What the earlier single-run table showed

Kept for the record. These are the rows now known to be non-reproducible:

| Gap | Single-run outcome |
|---|---|
| 1.20 m | passes, 0.069 m goal error (**confirmed** by the repeat) |
| 0.90 m | passed once, 0.066 m — **not reproducible** (0/6) |
| 0.70 m | passed once, 0.068 m — **not reproducible** (0/6) |
| 0.55 m | enters the gap and wedges, 0.0006 m clearance (1 run) |
| 0.45 m | refuses before entering, stops 0.547 m short (1 run) |

0.55 m and 0.45 m were **not** repeated and remain single observations.

### 3.3 0.55 m is still the dangerous case

At 0.45 m the robot **stops before entering** (0.547 m travelled). At 0.55 m
it **drives in and gets stuck**, ending with 0.0006 m clearance — the
inscribed circle grazing the wall. Not scored as a collision, but
effectively in contact and unable to recover. A gap wide enough to enter but
too narrow to pass is worse than one the robot refuses outright. **Based on
one run only**, so treat it as an indication, not a measurement.

### 3.4 Nav2 reported success while 2.4 m from the goal

Several repeat runs returned `SUCCEEDED` with a ground-truth error of
**≈2.4 m** and a path ratio near 0.50. Nav2 believed it had arrived while
AMCL was mislocalised. No collision occurred.

This is the sharpest available justification for the project rule that
**`SUCCEEDED` is never acceptable as evidence on its own** — a run judged on
the action result alone would have been recorded as a pass.

### 3.5 Caveat on machine load

During the repeat, load average sat at **10.7–12.5 on 12 threads**, with
only one stack running. The four depth-pipeline Python nodes alone account
for roughly **364 % CPU**, and `/smartphone_map` and `/camera/depth/points`
have **no subscribers** (section 9). Sensor rates still measured normal
(depth 15.05 Hz, `/scan` 10.5 Hz, RTF 0.9997), so saturation is **not**
demonstrated to be the cause of the narrow-gap failures — but it is not
excluded either, and it is the most obvious candidate for why a single early
run behaved differently.

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

This applies most strongly to **head-on approaches**. A lateral pass with
enough margin is unaffected, which is why Scenario 2 succeeds at 1.20 m
(each wall 0.60 m to the side). An early hypothesis that lateral passes were
*always* the binding case was **disproved** at 1.20 m — but the 21 Nov
repeat showed the margin matters: at 0.90 m (0.45 m to the side) and 0.70 m
(0.35 m to the side) the pass fails, because a small heading error brings a
wall inside the ±0.30 m polygon. The lateral mechanism is therefore real but
only tolerant above roughly 0.60 m of side clearance.

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
below B is **1.10 m**, and the robot never has to point at an obstacle from
inside the 0.60 m zone.

> **Note on the 1.10 m lane vs the 1.20 m Scenario 2 minimum.** The lane
> here is *narrower* than the narrowest reproducible corridor in section 3,
> yet `s1_slalom` passes 3/3. The two are not directly comparable: Scenario
> 2's gap is formed by two **2.0 m-long walls**, so the robot is flanked for
> its whole transit, whereas the slalom gap is between two **0.4 m-deep
> boxes** it passes in a moment. The Scenario 2 figure is therefore the
> conservative one, and the slalom result does not contradict it. Neither
> number should be generalised to the other geometry without testing.

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
2. **The 1.20 m minimum is specific to this envelope and geometry.** The
   mechanism is the ±0.30 m polygon half-width, so it changes if the polygon
   changes, and it was measured against 2.0 m-long walls (see the note in
   section 6 on the shorter slalom obstacles).
3. **Run counts are uneven.** `s1_slalom`, `s5_recovery` and `s4_crossing`
   have 3 runs each; `s3_blocked` has 2. Scenario 2's 1.20 / 0.90 / 0.70 m
   gaps now have **7, 7 and 7** runs; **0.55 m and 0.45 m still have 1 each**
   and should be repeated before being quoted.
4. **The threshold between 0.90 m and 1.20 m is unmeasured.** 1.20 m is the
   narrowest *reproducible* passage, not the narrowest passable one.
5. **The 24 runs in `scenario_runs.jsonl` carry no raw trajectory** and
   cannot be independently recomputed (audit finding). Only
   `scenario_runs_s2_repeat.jsonl` is verifiable. Re-running the other
   scenarios under the fixed harness would close this.
6. **`run_system_phase3.sh` can report a false "ready".** Its `/clock` and
   `/scan` gates passed in 0 s against a *stale* stack while Nav2 never
   activated, producing three bogus runs that were discarded. The gates do
   not check freshness. Not yet fixed.
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
2. ~~Repeat each Scenario 2 gap >=3 times~~ — **DONE 21 Nov 2026**, and it
   overturned the 0.70 m figure (section 3). Still outstanding: repeat the
   **0.55 m and 0.45 m** gaps, which remain single observations, and measure
   the real threshold between 0.90 m and 1.20 m.
3. **Sweep Scenario 4 obstacle speed** (0.1 / 0.2 / 0.4 m/s) to find where
   detection latency breaks down.
4. **Address Nav2's weak failure reporting** (§5): a blocked goal never
   returns an abort, so a consumer waits indefinitely.

The earlier polygon options are retained for the record:

| Option | Effect |
|---|---|
| **A** Keep 0.60 m × ±0.30 m | Scenario 1 stays blocked; minimum passage is **1.20 m** (as corrected). Safest, least capable. Document as the system's limit. **This is the option that was chosen.** |
| **B** Narrow half-width to ~±0.26 m, keep front 0.60 m | Preserves head-on protection; minimum passage drops toward ~0.52 m. Does **not** fix Scenario 1, which is a head-on case. |
| **C** Reduce front edge to 0.50 m (the detectability floor) | Closest to the 0.45 m inflation radius, so planner and monitor stop fighting. Leaves **zero** margin above the sensor's 0.500 m head-on minimum, so the zone becomes only marginally detectable. |

**DECIDED 20 Nov 2026: Option A.** The approved envelope stands
(0.60 m front, +/-0.30 m half-width). The 0.60 m head-on approach limit is
recorded as a measured characteristic of the system, not a defect, and
Scenario 1 was redesigned so its route never requires the robot to point at
an obstacle from inside that zone (see `s1_slalom` in
`scripts/phase3/scenario_runner.py` and section 9 below).
