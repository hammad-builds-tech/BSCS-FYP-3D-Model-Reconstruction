#!/usr/bin/env python3
"""Phase 3 — run one obstacle scenario and record it from Gazebo ground truth.

Scenarios are declared in SCENARIOS below: obstacle set, goal, and the pass
criteria that apply. Each run:

  1. spawns the scenario's obstacles at runtime (no world file is modified,
     so the static map never contains them);
  2. resets the robot to the Phase 1/2 start pose and re-initialises AMCL;
  3. sends the goal and samples Gazebo ground truth throughout;
  4. reports Nav2's result code AND the ground-truth outcome, because Nav2
     reporting SUCCEEDED is never accepted as evidence on its own.

Usage:
    scenario_runner.py --scenario s1_three_boxes --run 1
    scenario_runner.py --list

Obstacles are removed again at the end so the next run starts clean. The
robot is NOT reset here if the run ended in contact -- restart the whole
stack in that case (reset_robot.sh alone does not recover AMCL).
"""

import argparse
import json
import math
import os
import subprocess
import time

REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODELS = os.path.join(REPO, "scripts", "phase3", "scenarios")
WORLD = "indoor_world"
START = (0.0, -2.0)

#: Robot geometry, from the committed footprint [[0.35,0.25],...]:
#: half-length 0.35 m, half-width 0.25 m.
HALF_LEN, HALF_WID = 0.35, 0.25

#: Phase 1/2 acceptance limit for a reachable goal, unchanged.
GOAL_TOLERANCE = 0.15

SCENARIOS = {
    # ---- Scenario 1: multiple static obstacles -----------------------
    "s1_three_boxes": {
        "doc": "Three unmapped 0.4 m boxes at different ranges and bearings",
        "obstacles": [
            ("box_040", 1.00, -1.00),
            ("box_040", 1.60, 0.60),
            ("box_040", 0.20, -0.60),
        ],
        "goal": (2.50, 1.00),
        "reachable": True,
    },
    # Same capability, but with a route that the APPROVED 0.60 m stop zone
    # can actually fit through. s1_three_boxes above is retained because it
    # documents a real limit: three obstacles at that density halt the robot
    # (3/3 runs), the monitor firing with the obstacle surface ~0.57-0.60 m
    # from base_link, i.e. exactly at the approved zone boundary.
    # Here A and B leave a 1.60 m gap and C sits off the route.
    "s1_spaced": {
        "doc": "Three 0.4 m boxes leaving a 1.60 m gap plus one off-route",
        "obstacles": [
            ("box_040", 1.20, -2.00),
            ("box_040", 1.20, 0.00),
            ("box_040", 2.00, -2.60),
        ],
        "goal": (2.50, -1.00),
        "reachable": True,
        "gap_m": 1.60,
    },
    # Option A redesign (decided 20 Nov 2026). The approved 0.60 m stop zone
    # halts any head-on approach, so this layout offsets every obstacle
    # laterally from the route: the straight line to the goal intersects B,
    # forcing a detour, but the free lane below B is 1.10 m wide (> the
    # measured 0.70 m minimum) and the robot never has to point at an
    # obstacle from inside the zone.
    "s1_slalom": {
        "doc": "Three 0.4 m boxes, lateral offsets, 1.10 m lane, detour forced",
        "obstacles": [
            ("box_040", 1.00, -2.75),
            ("box_040", 2.00, -1.25),
            ("box_040", 3.00, -2.75),
        ],
        "goal": (3.20, -1.00),
        "reachable": True,
        "gap_m": 1.10,
    },
    # ---- Scenario 2: narrow passages ---------------------------------
    # Two walls facing each other along y, leaving a gap the robot must
    # thread. Robot width is 0.50 m; inflation is 0.45 m per side, so a
    # fully cost-free corridor would need ~1.40 m.
    # wall_020x200 is 2.0 m long in y, so its facing edge is at pose_y +/- 1.0.
    # For a gap G centred on yc: y = yc -/+ (G + 2.0)/2. The corridor is put on
    # the start line y = -2.0 so the robot drives straight through it.
    "s2a_gap_120": {
        "doc": "1.20 m gap: wider than the robot, narrower than 2x inflation",
        "obstacles": [("wall_020x200", 1.00, -3.600), ("wall_020x200", 1.00, -0.400)],
        "goal": (2.50, -2.00),
        "reachable": True,
        "gap_m": 1.20,
    },
    "s2b_gap_090": {
        "doc": "0.90 m gap: 0.20 m clearance per side. Outcome unknown",
        "obstacles": [("wall_020x200", 1.00, -3.450), ("wall_020x200", 1.00, -0.550)],
        "goal": (2.50, -2.00),
        "reachable": True,
        "gap_m": 0.90,
    },
    "s2c_gap_045": {
        "doc": "0.45 m gap: narrower than the 0.50 m robot. Must refuse",
        "obstacles": [("wall_020x200", 1.00, -3.225), ("wall_020x200", 1.00, -0.775)],
        "goal": (2.50, -2.00),
        "reachable": False,
        "gap_m": 0.45,
    },
    # Bracket the predicted threshold. PolygonStop is +/-0.30 m wide, so a
    # centred pass trips it when G/2 <= 0.30, i.e. G <= 0.60 m. The robot
    # itself is only 0.50 m wide, so the monitor -- not the chassis -- sets
    # the minimum navigable passage. These two pin it experimentally.
    "s2d_gap_070": {
        "doc": "0.70 m gap: just above the predicted 0.60 m polygon threshold",
        "obstacles": [("wall_020x200", 1.00, -3.350), ("wall_020x200", 1.00, -0.650)],
        "goal": (2.50, -2.00),
        "reachable": True,
        "gap_m": 0.70,
    },
    "s2e_gap_055": {
        "doc": "0.55 m gap: fits the robot but inside the polygon. Predicted block",
        "obstacles": [("wall_020x200", 1.00, -3.275), ("wall_020x200", 1.00, -0.725)],
        "goal": (2.50, -2.00),
        "reachable": True,
        "gap_m": 0.55,
    },
    # ---- Scenario 3: completely blocked ------------------------------
    "s3_blocked": {
        "doc": "Five walls sealing x=1.0 across the full room width: no route exists",
        "obstacles": [
            ("wall_020x200", 1.00, -4.00),
            ("wall_020x200", 1.00, -2.00),
            ("wall_020x200", 1.00, 0.00),
            ("wall_020x200", 1.00, 2.00),
            ("wall_020x200", 1.00, 4.00),
        ],
        "goal": (2.50, -2.00),
        "reachable": False,
    },
    # ---- Scenario 4: moving obstacle (EXPERIMENTAL) ------------------
    # One box is translated across the route with gz service set_pose while
    # the robot drives. Treated as an experimental extension, NOT part of
    # the static-environment core scope.
    "s4_crossing": {
        "doc": "EXPERIMENTAL: box crosses the route at 0.20 m/s while driving",
        "obstacles": [("box_040", 2.00, -3.20)],
        "goal": (3.20, -2.00),
        "reachable": True,
        "motion": {"index": 0, "to_y": -0.80, "speed": 0.20, "start_delay": 2.0},
    },
    # ---- Scenario 5: recovery ----------------------------------------
    # The route is sealed, then the blocking wall is REMOVED mid-run. The
    # robot must stop safely, then complete once a route exists.
    "s5_recovery": {
        "doc": "Route sealed, blocker removed mid-run; must recover and finish",
        "obstacles": [
            ("wall_020x200", 1.00, -4.00),
            ("wall_020x200", 1.00, -2.00),
            ("wall_020x200", 1.00, 0.00),
        ],
        "goal": (2.50, -2.00),
        "reachable": True,
        "remove_mid_run": {"index": 1, "after_s": 25.0},
    },
}


def set_pose(name, x, y):
    subprocess.run(
        ["gz", "service", "-s", "/world/%s/set_pose" % WORLD,
         "--reqtype", "gz.msgs.Pose", "--reptype", "gz.msgs.Boolean",
         "--timeout", "3000",
         "--req", 'name: "%s", position: {x: %f, y: %f, z: 0.6}, '
                  'orientation: {w: 1.0}' % (name, x, y)],
        capture_output=True, text=True, timeout=12,
    )


def gz(args, timeout=20):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout
    ).stdout


def truth():
    """Gazebo ground-truth (x, y) of fyp_robot, or None."""
    out = gz(["gz", "topic", "-e", "-t", "/world/%s/pose/info" % WORLD, "-n", "1"])
    block = out.split('name: "fyp_robot"', 1)
    if len(block) < 2:
        return None
    nums = []
    for line in block[1].splitlines():
        line = line.strip()
        for key in ("x:", "y:"):
            if line.startswith(key):
                try:
                    nums.append(float(line.split(":", 1)[1]))
                except ValueError:
                    pass
        if len(nums) >= 2:
            break
    return (nums[0], nums[1]) if len(nums) >= 2 else None


def spawn(model, x, y, name):
    subprocess.run(
        ["ros2", "run", "ros_gz_sim", "create",
         "-world", WORLD, "-file", os.path.join(MODELS, model + ".sdf"),
         "-name", name, "-x", str(x), "-y", str(y), "-z", "0.6"],
        capture_output=True, text=True, timeout=60,
    )


def remove(name):
    subprocess.run(
        ["gz", "service", "-s", "/world/%s/remove" % WORLD,
         "--reqtype", "gz.msgs.Entity", "--reptype", "gz.msgs.Boolean",
         "--timeout", "5000", "--req", 'name: "%s", type: MODEL' % name],
        capture_output=True, text=True, timeout=20,
    )


#: Half-extents (x, y) of each scenario model, from its SDF <size>.
MODEL_HALF = {
    "box_040": (0.20, 0.20),
    "box_060": (0.30, 0.30),
    "wall_020x200": (0.10, 1.00),
}


def clearance(path, obstacles, removed_at=None, removed_index=None):
    """Minimum gap between the robot body and the nearest obstacle surface.

    Distance is taken to the obstacle's SURFACE, not its centre: a 2 m wall
    is nowhere near a point mass, and centre-to-centre would wildly
    overstate clearance. The robot is approximated by its inscribed radius
    (0.25 m), which is conservative for a frontal approach where the true
    half-extent is 0.35 m -- so a reported clearance near zero should be
    read as "touching", and the frontal case is pessimistic by up to 0.10 m.

    Negative means the inscribed circle overlapped the obstacle.
    """
    worst = None
    for i, (model, ox, oy) in enumerate(obstacles):
        hx, hy = MODEL_HALF.get(model, (0.20, 0.20))
        for (t, x, y) in path:
            # An obstacle deleted mid-run must not be scored against the part
            # of the path that happened AFTER it was deleted -- the robot is
            # then driving through empty space, not through a wall. Scoring it
            # produced a false collision (clearance exactly -HALF_WID) on the
            # first Scenario 5 runs.
            if (removed_index is not None and i == removed_index
                    and removed_at is not None and t > removed_at):
                continue
            dx = max(abs(x - ox) - hx, 0.0)
            dy = max(abs(y - oy) - hy, 0.0)
            d = math.hypot(dx, dy) - HALF_WID
            if worst is None or d < worst:
                worst = d
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario")
    ap.add_argument("--run", default="1")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--json")
    args = ap.parse_args()

    if args.list or not args.scenario:
        for key, cfg in SCENARIOS.items():
            print("%-16s reachable=%-5s %s" % (key, cfg["reachable"], cfg["doc"]))
        return

    cfg = SCENARIOS[args.scenario]
    names = []

    # Reset first so the obstacles are not spawned on top of the robot.
    subprocess.run(["bash", os.path.join(REPO, "docs/evidence/phase1/scripts/reset_robot.sh")],
                   capture_output=True, text=True, timeout=60)
    time.sleep(4)

    for i, (model, x, y) in enumerate(cfg["obstacles"]):
        name = "p3_%s_%s_%d" % (args.scenario, args.run, i)
        spawn(model, x, y, name)
        names.append(name)
    time.sleep(4)

    path = []
    t0 = time.time()
    goal = cfg["goal"]
    proc = subprocess.Popen(
        ["ros2", "action", "send_goal", "/navigate_to_pose",
         "nav2_msgs/action/NavigateToPose",
         "{pose: {header: {frame_id: map}, pose: {position: {x: %f, y: %f, z: 0.0}, "
         "orientation: {w: 1.0}}}}" % goal],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    motion = cfg.get("motion")
    removal = cfg.get("remove_mid_run")
    events = []
    removed = False
    while proc.poll() is None and time.time() - t0 < args.timeout:
        now = time.time() - t0

        # Scenario 4: translate one obstacle across the route.
        if motion and now >= motion["start_delay"]:
            model, ox, oy = cfg["obstacles"][motion["index"]]
            travelled = (now - motion["start_delay"]) * motion["speed"]
            target_y = oy + min(travelled, motion["to_y"] - oy) \
                if motion["to_y"] > oy else oy - min(travelled, oy - motion["to_y"])
            set_pose(names[motion["index"]], ox, target_y)
            if not events or events[-1][0] != "moving":
                events.append(("moving", round(now, 1)))

        # Scenario 5: remove the blocker partway through.
        if removal and not removed and now >= removal["after_s"]:
            remove(names[removal["index"]])
            removed = True
            events.append(("blocker_removed", round(now, 1)))

        p = truth()
        if p:
            path.append((now, p[0], p[1]))
        time.sleep(0.25)
    if proc.poll() is None:
        proc.kill()
        nav_result = "TIMEOUT"
    else:
        out = proc.stdout.read() or ""
        nav_result = "UNKNOWN"
        for token in ("SUCCEEDED", "ABORTED", "CANCELED"):
            if token in out:
                nav_result = token
                break
        for line in out.splitlines():
            if "error_code" in line:
                nav_result += "/" + line.strip().replace(" ", "")
                break
    duration = time.time() - t0

    for p in (truth(),):
        if p:
            path.append((time.time() - t0, p[0], p[1]))
    for name in names:
        remove(name)

    final = (path[-1][1], path[-1][2]) if path else (float("nan"),) * 2
    err = math.hypot(goal[0] - final[0], goal[1] - final[1])
    removed_at = next((t for (tag, t) in events if tag == "blocker_removed"), None)
    clr = clearance(path, cfg["obstacles"], removed_at,
                    removal["index"] if removal else None) if path else None
    executed = sum(math.hypot(path[i + 1][1] - path[i][1], path[i + 1][2] - path[i][2])
                   for i in range(len(path) - 1)) if len(path) > 1 else 0.0
    straight = math.hypot(final[0] - START[0], final[1] - START[1])

    collided = clr is not None and clr < 0.0
    if cfg["reachable"]:
        verdict = "PASS" if (err <= GOAL_TOLERANCE and not collided) else "FAIL"
        if removal and not removed:
            # The blocker was never removed within the window, so the goal was
            # unreachable for the whole run: judge it as a blocked route.
            verdict = "PASS(blocked)" if not collided else "FAIL"
    else:
        # Blocked/too-narrow: must NOT collide and must NOT claim success.
        claimed = nav_result.startswith("SUCCEEDED") and err > GOAL_TOLERANCE
        verdict = "PASS" if (not collided and not claimed) else "FAIL"

    row = {
        "scenario": args.scenario, "run": args.run,
        "reachable": cfg["reachable"],
        "goal_x": goal[0], "goal_y": goal[1],
        "final_x": round(final[0], 4), "final_y": round(final[1], 4),
        "goal_error_m": round(err, 4),
        "min_clearance_m": round(clr, 4) if clr is not None else None,
        "collided": collided,
        "executed_m": round(executed, 3),
        "straight_m": round(straight, 3),
        "ratio": round(executed / straight, 3) if straight > 0.01 else None,
        "nav_result": nav_result,
        "duration_s": round(duration, 1),
        "samples": len(path),
        "verdict": verdict,
        "events": events,
        # Unique per invocation. --run alone is not unique: a re-run of the
        # same scenario after a harness artifact reused run id "1", which made
        # two rows indistinguishable except by nav_result (audit finding,
        # 21 Nov 2026).
        "run_key": "%s/%s/%d" % (args.scenario, args.run, int(t0)),
        "started_unix": round(t0, 3),
        # Raw ground-truth trajectory, so goal_error_m, min_clearance_m,
        # executed_m and ratio can all be INDEPENDENTLY RECOMPUTED from this
        # file. Without it the summary numbers had to be taken on trust
        # (audit finding, 21 Nov 2026). (t_since_goal_s, x, y), 4 dp.
        "path": [[round(t, 3), round(x, 4), round(y, 4)] for (t, x, y) in path],
        # Everything needed to re-derive clearance without reading the code.
        "obstacles": [
            {"model": m, "x": ox, "y": oy,
             "half_x": MODEL_HALF.get(m, (0.20, 0.20))[0],
             "half_y": MODEL_HALF.get(m, (0.20, 0.20))[1]}
            for (m, ox, oy) in cfg["obstacles"]
        ],
        "removed_index": removal["index"] if removal else None,
        "removed_at_s": removed_at,
        "robot_half_width_m": HALF_WID,
        "goal_tolerance_m": GOAL_TOLERANCE,
    }
    print(json.dumps({k: v for k, v in row.items() if k != "path"}))
    if args.json:
        with open(args.json, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
