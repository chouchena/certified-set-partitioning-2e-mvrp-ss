"""Derive validation/GRID_CALIBRATION.json from the envelope, rather than writing it by hand.

WHY THIS FILE EXISTS. The calibration was hand-written on 2026-09-21 and its two derived
quantities were silently welded to the hardware factor in force that day:

    per_run_s   = envelope_s(factor) / seeds
    det_budget  = per_run_s x clean_rate x 0.9

At factor 2.5 that gave n100 per_run_s = 3721/5 = 744 and det = 744 x 1204 x 0.9 = 806,000.
Those are not independent ceilings -- they ARE the factor-2.5 per-seed share, frozen into a file
the grid then treats as authority. run_cell applies per_run_s as a CEILING (min of fair share and
ceiling), so moving --hw-factor alone changes NOTHING on any cell whose fair share was already
above the ceiling. The factor becomes inert exactly where it matters most.

That is the defect this file closes: the derived numbers now regenerate FROM the factor, and the
measured ones do not move.

MEASURED (carried through untouched, never recomputed here):
    clean_rate_ticks_per_s   per size, from runs/calib/*.json, 2026-09-21
    seeds                    N=5, and its rationale -- see N_rationale in the JSON

DERIVED (recomputed here, from --factor):
    envelope_s, per_run_s

det_budget IS NO LONGER DERIVED OR USED (2026-09-22). The grid stopped passing --det-budget
under primal-harness-blocking-defects-v3: wall clock is the declared stop rule, because the
tick budget bound on a minority of runs and because our budget claim is denominated in wall
seconds. The field is left in the JSON as history and nothing reads it. The FLAG still exists
in fixopt and is still right for analysis/explore_lane.py, which may run under co-tenancy --
there a wall limit measures the machine mood rather than the idea. Single-tenant production
runs are a different case and take the wall.

DECLARED, and NOT derived -- n10 keeps per_run_s = 300 s against a ~6,000 s share. Every n10 cell
is a K-proven optimum, so the question there is ATTAINMENT, not depth, and spending a full share
on it would buy nothing the grid reports. Overriding it is the point.

    python analysis/grid_calibration.py                 # dry run, prints the diff
    python analysis/grid_calibration.py --write         # writes it
"""
import argparse
import copy
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

from run_full_grid import CALIB, HW_FACTOR_ENVELOPE, envelope

# n10 is deliberately under-budgeted; see the module docstring. Keyed by size so an added
# override is visible here rather than buried in the JSON.
DECLARED_PER_RUN_S = {10: 300.0}


def derive(factor):
    """Recompute the derived fields in place, leaving every measured field alone."""
    cal = json.load(io.open(CALIB, encoding="utf-8"))
    before = copy.deepcopy(cal["by_size"])
    for key, row in cal["by_size"].items():
        size = int(key)
        env = envelope(size, factor)
        row["envelope_s"] = round(env, 1)
        row["per_run_s"] = DECLARED_PER_RUN_S.get(size, round(env / row["seeds"], 1))
        # det_budget deliberately NOT recomputed -- see the module docstring. Whatever is in
        # the file is history; the grid does not read it.
    cal["hw_factor"] = factor
    cal["derived_by"] = "analysis/grid_calibration.py"
    cal["derived_rationale"] = (
        "per_run_s and det_budget are DERIVED from the envelope at hw_factor, not measured. "
        "They were hand-written at factor 2.5 on 2026-09-21, which welded them to that factor "
        "and made --hw-factor inert wherever the ceiling bound. clean_rate_ticks_per_s, seeds "
        "and the 0.9 headroom are measured or declared and are NOT recomputed here. n10 keeps a "
        "declared 300 s because its cells are K-proven optima and the question is attainment.")
    return cal, before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", type=float, default=HW_FACTOR_ENVELOPE)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    cal, before = derive(a.factor)
    print("GRID CALIBRATION at hw_factor %.1f  (K's 14400 s -> %.0f s of ours)"
          % (a.factor, 14400.0 / a.factor))
    print()
    print("   %5s %9s %9s %9s %9s  %s"
          % ("n", "env was", "env now", "run was", "run now", "note"))
    for key in sorted(cal["by_size"], key=int):
        o, n = before[key], cal["by_size"][key]
        note = "DECLARED, not derived" if int(key) in DECLARED_PER_RUN_S else ""
        print("   %5s %9.0f %9.0f %9.0f %9.0f  %s"
              % (key, o["envelope_s"], n["envelope_s"], o["per_run_s"], n["per_run_s"], note))
    print()
    gains = [100.0 * (cal["by_size"][k]["per_run_s"] - before[k]["per_run_s"])
             / before[k]["per_run_s"] for k in cal["by_size"]
             if int(k) not in DECLARED_PER_RUN_S]
    if gains:
        print("   per-run wall change on derived sizes: %s"
              % "  ".join("%+.1f%%" % g for g in sorted(gains)))
    print()
    print("   NOTE the ceiling is not the only binding rule. run_cell takes")
    print("   min(per-CELL fair share, per_run_s), so a high-LB cell still gets less than this.")

    if not a.write:
        print()
        print("   --dry run; nothing written. Re-run with --write.")
        return 0
    json.dump(stamped(cal, __file__), io.open(CALIB, "w", encoding="utf-8"),
              indent=1, default=str)
    print()
    print("   written -> %s" % CALIB)
    return 0


if __name__ == "__main__":
    sys.exit(main())
