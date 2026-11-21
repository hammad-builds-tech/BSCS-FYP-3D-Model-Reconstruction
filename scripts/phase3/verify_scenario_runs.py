#!/usr/bin/env python3
"""Phase 3 — recompute every scenario summary from its raw trajectory.

The 21 Nov 2026 audit found that `scenario_runs.jsonl` carried only summary
statistics, so goal_error_m / min_clearance_m / executed_m / ratio could not
be checked without trusting the harness. `scenario_runner.py` now stores the
raw ground-truth path and the obstacle geometry in each record; this script
re-derives the summary from that raw data and reports any disagreement.

It reads only, and exits non-zero if any record fails to reproduce.

    scripts/phase3/verify_scenario_runs.py [path/to/scenario_runs.jsonl]

Records written before the audit fix have no "path" field and are reported
as UNVERIFIABLE rather than as failures -- that is the honest status: their
numbers cannot be checked, which is exactly why the fix was made.
"""

import json
import math
import sys

#: Pointwise fields must reproduce to the stored rounding (4 dp on the path).
TOL_POINT = 1e-3

#: Path-integral fields (executed_m, ratio) sum ~200 samples that were each
#: rounded to 4 dp, so the sum carries up to N x 1e-4 of accumulated rounding.
#: A fixed 1e-3 bound is therefore not a valid criterion for them -- it
#: flagged 6 of 18 valid runs on the first pass. Allowance scales with the
#: sample count, plus a small relative term.
def tol_for(field, n_samples, magnitude):
    if field in ("executed_m", "ratio"):
        return max(TOL_POINT, n_samples * 2e-4 + 0.002 * abs(magnitude))
    return TOL_POINT


def recompute(rec):
    """Return (derived_dict, notes) from the raw path in one record."""
    path = [(t, x, y) for (t, x, y) in rec["path"]]
    goal = (rec["goal_x"], rec["goal_y"])
    final = (path[-1][1], path[-1][2])

    goal_error = math.hypot(goal[0] - final[0], goal[1] - final[1])

    executed = sum(
        math.hypot(path[i + 1][1] - path[i][1], path[i + 1][2] - path[i][2])
        for i in range(len(path) - 1)
    )
    straight = math.hypot(final[0] - 0.0, final[1] - (-2.0))  # START = (0,-2)

    half_w = rec["robot_half_width_m"]
    removed_i = rec.get("removed_index")
    removed_at = rec.get("removed_at_s")
    worst = None
    for i, ob in enumerate(rec["obstacles"]):
        for (t, x, y) in path:
            # Mirror the harness: an obstacle deleted mid-run must not be
            # scored against the path after its removal.
            if removed_i is not None and i == removed_i and \
                    removed_at is not None and t > removed_at:
                continue
            dx = max(abs(x - ob["x"]) - ob["half_x"], 0.0)
            dy = max(abs(y - ob["y"]) - ob["half_y"], 0.0)
            d = math.hypot(dx, dy) - half_w
            if worst is None or d < worst:
                worst = d

    return {
        "goal_error_m": goal_error,
        "min_clearance_m": worst,
        "executed_m": executed,
        "ratio": (executed / straight) if straight > 0.01 else None,
        "collided": (worst is not None and worst < 0.0),
        "samples": len(path),
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "docs/evidence/phase3/scenario_runs.jsonl"
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

    ok = unverifiable = failed = 0
    print("%-19s %-6s %-26s %s" % ("scenario", "run", "field", "stored vs derived"))
    for rec in rows:
        tag = "%-19s %-6s" % (rec["scenario"], rec["run"])
        if "path" not in rec or not rec["path"]:
            print("%s UNVERIFIABLE  (no raw path - predates the audit fix)" % tag)
            unverifiable += 1
            continue
        got = recompute(rec)
        bad = []
        for field, derived in got.items():
            stored = rec.get(field)
            if stored is None or derived is None:
                if stored != derived:
                    bad.append((field, stored, derived))
                continue
            if isinstance(stored, bool) or isinstance(derived, bool):
                if bool(stored) != bool(derived):
                    bad.append((field, stored, derived))
            else:
                tol = tol_for(field, got["samples"], derived)
                if abs(float(stored) - float(derived)) > tol:
                    bad.append((field, stored, derived))
        if bad:
            failed += 1
            for field, stored, derived in bad:
                print("%s FAIL  %-20s stored=%s derived=%s" % (tag, field, stored, derived))
        else:
            ok += 1
            print("%s OK    all %d fields reproduce" % (tag, len(got)))

    print("\nreproduced: %d   unverifiable: %d   FAILED: %d   (total %d)"
          % (ok, unverifiable, failed, len(rows)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
