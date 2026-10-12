"""A WINDOWED work-conservation lower bound on the street fleet -- arithmetic only (d446).

THE INEQUALITY. Every customer i is served by exactly one street car, the service takes s_i, and
it must START inside [e_i, l_i]. So the whole of i's service lies inside [e_i, l_i + s_i]. Fix any
interval [a, b]. Every customer whose [e_i, l_i + s_i] is CONTAINED in [a, b] must be served
entirely inside [a, b], and a single car can perform at most (b - a) of work there. Hence

    V  >=  ceil( sum of s_i over those customers  /  (b - a) )

and the bound is the MAXIMUM over all intervals. Validity needs nothing but "one car, one customer
at a time"; no routing, no capacity, no triangle inequality.

WHY IT MIGHT MATTER. `crossfeed/fullset_bound` already computes the same argument ONCE, over the
whole depot horizon: `routes_lb_time = ceil(work_lb / horizon)`. That is the interval [H0, H1] and
nothing else. Where time windows cluster -- the R family, by construction -- a short interval can
be far busier than the day average, and the global version cannot see it. The record notes R at
n100 holds V_LB = 2 against roughly 9 street vehicles in practice, which is the weakest fleet
floor in the grid and, at 171 per car, the largest single identified component of the dual gap.

WHAT THIS IS NOT. It is service time only. The full energetic argument also charges travel inside
the interval and partial overlaps of windows that straddle the boundary, both of which can only
raise it. Those are deliberately left out so that validity is obvious by inspection.

    python analysis/fleet_energetic_bound.py --size 100
"""
import argparse
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped


def energetic_floor(inst):
    """max over intervals of ceil(contained service / interval length), and the witness."""
    nd = inst.nodes
    cust = list(inst.customers)
    span = [(float(nd[c].earliest), float(nd[c].latest) + float(nd[c].service), float(nd[c].service))
            for c in cust]
    pts = sorted(set([x[0] for x in span] + [x[1] for x in span]))
    best, wit = 1, None
    for ia in range(len(pts)):
        a = pts[ia]
        for ib in range(ia + 1, len(pts)):
            b = pts[ib]
            L = b - a
            if L <= 1e-9:
                continue
            work = sum(s for (e, l, s) in span if e >= a - 1e-9 and l <= b + 1e-9)
            if work <= 0:
                continue
            v = int(math.ceil(work / L - 1e-9))
            if v > best:
                best, wit = v, dict(a=a, b=b, length=L, work=work,
                                    customers=sum(1 for (e, l, s) in span if e >= a - 1e-9 and l <= b + 1e-9))
    return best, wit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100); ap.add_argument("--cells", default=None)
    a = ap.parse_args()
    cells = a.cells.split(",") if a.cells else (
        ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
        + ["RC%d" % i for i in range(201, 209)])
    prox = k_proximity(a.size)
    rows = []
    print("%-7s %8s %9s %8s %9s %s" % ("cell", "global", "windowed", "lift", "real cars", "witness interval"))
    for c in cells:
        inst = V.load_instance(c, a.size, prox)
        nd = inst.nodes
        H0, H1 = float(nd[inst.depot].earliest), float(nd[inst.depot].latest)
        glob = int(math.ceil(sum(float(nd[x].service) for x in inst.customers) / (H1 - H0) - 1e-9))
        win, wit = energetic_floor(inst)
        p = os.path.join(ROOT, "runs", "postpass", "ipchain_%s_n%d.json" % (c, a.size))
        real = int(json.load(io.open(p, encoding="utf-8"))["nCars"]) if os.path.exists(p) else None
        rows.append(dict(cell=c, global_floor=glob, windowed=win, real=real, witness=wit))
        print("%-7s %8d %9d %8s %9s %s"
              % (c, glob, win, ("+%d" % (win - glob)) if win > glob else "-",
                 real if real is not None else "-",
                 ("[%.0f, %.0f] len %.0f, %d customers, work %.0f" % (wit["a"], wit["b"], wit["length"], wit["customers"], wit["work"])) if wit else "-"))
    lifted = [r for r in rows if r["windowed"] > r["global_floor"]]
    print("\n  the windowed inequality lifts the service-time floor on %d of %d cells" % (len(lifted), len(rows)))
    bad = [r for r in rows if r["real"] is not None and r["windowed"] > r["real"]]
    if bad:
        print("  *** INVALID on %d cell(s): the bound exceeds a VERIFIED car count -- %s ***"
              % (len(bad), ", ".join("%s %d>%d" % (r["cell"], r["windowed"], r["real"]) for r in bad)))
    else:
        print("  not refuted: the bound is at or below every verified car count we hold")
    p = os.path.join(ROOT, "runs", "oracle", "fleet_energetic_n%d.json" % a.size)
    json.dump(stamped(dict(size=a.size, rows=rows)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
