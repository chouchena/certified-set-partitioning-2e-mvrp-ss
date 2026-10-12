"""A5 -- the rounding direction, floor against ceil, on every cell of every size. (d572)

WHY THIS IS THE FIRST ABLATION AND NOT THE FOURTH. It is the mechanism the paper turns on: one
discretisation read in two directions, floor giving a relaxation and ceil a restriction whose integer
solutions are timetable-feasible. It is also the only ablation in paper/ABLATION_PLAN.md with
complete coverage -- both arms exist on 27 of 27 cells at all five sizes -- and until today it had no
table of its own.

WHAT IT MEASURES, per cell:

  * the objective each direction reaches, and which wins;
  * the CAR COUNT each reaches, because that is the claimed mechanism: floor-rounded selection
    under-prices the fleet, so it can settle on a solution carrying a car that ceil removes. If the
    mechanism is real, the cells where ceil wins big are the cells where it uses FEWER cars, and the
    cells where floor wins are the ones where the car counts agree;
  * the gap to K's best incumbent where they publish one, so the direction's effect is visible in the
    comparison a referee reads, not only in our own units.

WHAT IT CANNOT SHOW. Both arms are configurations of one formulation and one pipeline; running both
and keeping the cheaper is a configuration choice, not a hybrid method (tep_n30_best_of.py says the
same). The table reports what each direction buys, not that either is a contribution on its own.

    python analysis/tep_direction_ablation.py [--sizes 10 20 30 50 100]
"""
import argparse
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from k_comparison import k_best_incumbent
from stamp import stamped

TOL = 0.05          # K publish to one decimal; a difference below this is not a difference


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def arms(size):
    """floor is runs/postpass/ownwater_*, ceil is runs/postpass/ceil/ownwater_* -- the two directions
    of the SAME selection, before any later stage touches them."""
    out = {}
    for tag, sub in (("floor", ""), ("ceil", "ceil")):
        for f in glob.glob(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_*_n%d.json" % size)):
            d = load(f)
            if not d:
                continue
            c = os.path.basename(f).split("_")[1]
            out.setdefault(c, {})[tag] = dict(obj=float(d["objVal"]), cars=int(d["nCars"]),
                                              vessels=int(d.get("nVessels") or 0))
    return {c: v for c, v in out.items() if "floor" in v and "ceil" in v}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    a = ap.parse_args()
    rows, per_size = [], {}
    for n in a.sizes:
        A = arms(n)
        for c, v in sorted(A.items()):
            kb, which = k_best_incumbent(c, n)
            d = v["ceil"]["obj"] - v["floor"]["obj"]
            win = "ceil" if d < -TOL else ("floor" if d > TOL else "tie")
            rows.append(dict(size=n, cell=c, floor=v["floor"]["obj"], ceil=v["ceil"]["obj"],
                             cars_floor=v["floor"]["cars"], cars_ceil=v["ceil"]["cars"],
                             delta=d, delta_pct=100.0 * d / v["floor"]["obj"], winner=win,
                             k_best=kb, k_method=which,
                             floor_vs_k=(100.0 * (v["floor"]["obj"] / kb - 1)) if kb else None,
                             ceil_vs_k=(100.0 * (v["ceil"]["obj"] / kb - 1)) if kb else None))
        rs = [r for r in rows if r["size"] == n]
        if rs:
            per_size[n] = rs
    print("A5 -- ROUNDING DIRECTION, floor against ceil, both arms on every cell\n")
    print("%-5s %6s %7s %7s %6s | %11s %11s | %s"
          % ("size", "cells", "ceil", "floor", "tie", "ceil gain", "floor gain", "car counts"))
    for n, rs in sorted(per_size.items()):
        cw = [r for r in rs if r["winner"] == "ceil"]
        fw = [r for r in rs if r["winner"] == "floor"]
        tw = [r for r in rs if r["winner"] == "tie"]
        fewer = sum(1 for r in cw if r["cars_ceil"] < r["cars_floor"])
        same = sum(1 for r in fw if r["cars_ceil"] == r["cars_floor"])
        print("%-5d %6d %7d %7d %6d | %10s %11s | ceil wins with fewer cars on %d of %d; floor wins at equal cars on %d of %d"
              % (n, len(rs), len(cw), len(fw), len(tw),
                 ("%.1f%%" % st.median(-r["delta_pct"] for r in cw)) if cw else "-",
                 ("%.1f%%" % st.median(r["delta_pct"] for r in fw)) if fw else "-",
                 fewer, len(cw), same, len(fw)))
    print("\n  THE MECHANISM, stated as the table supports it:")
    cw = [r for r in rows if r["winner"] == "ceil"]
    fw = [r for r in rows if r["winner"] == "floor"]
    if cw:
        big = [r for r in cw if r["cars_ceil"] < r["cars_floor"]]
        small = [r for r in cw if r["cars_ceil"] == r["cars_floor"]]
        print("    ceil wins on %d cells overall: %d of them with FEWER cars (median %.1f%%), %d at equal cars (median %.1f%%)"
              % (len(cw), len(big), st.median(-r["delta_pct"] for r in big) if big else 0.0,
                 len(small), st.median(-r["delta_pct"] for r in small) if small else 0.0))
    if fw:
        print("    floor wins on %d cells, median %.1f%%, and on %d of them the car counts are equal -- so the"
              % (len(fw), st.median(r["delta_pct"] for r in fw), sum(1 for r in fw if r["cars_ceil"] == r["cars_floor"])))
        print("    loss there is timetable slack, not fleet: ceil is a RESTRICTION and pays for it in travel")
    both = [r for r in rows if r["k_best"]]
    if both:
        print("\n  against K's best incumbent, where they publish one (%d cells): floor median %+.2f%%, ceil median %+.2f%%"
              % (len(both), st.median(r["floor_vs_k"] for r in both), st.median(r["ceil_vs_k"] for r in both)))
    p = os.path.join(ROOT, "runs", "oracle", "tep_direction_ablation.json")
    json.dump(stamped(dict(tol=TOL, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
