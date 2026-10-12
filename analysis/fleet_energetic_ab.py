"""Energetic fleet bound with the VALIDATED travel relaxation substituted in.

analysis/fleet_energetic_bound.py priced travel with a plain assignment relaxation
and reached work/(W+tau) = 0.867 on the C family -- close to the 1.0 that would
PROVE two vehicles are required, but not over it.

This substitutes `Dist_LB = max(assignment, MST, FORCED)` from crossfeed/fullset_bound.py,
i.e. AB3 (ab3-mst-travel-v2) and AB4 (ab4-forced-terminal-accepted), both already
validated on the full 162-cell grid and both strictly stronger than assignment alone.

    k >= (service + Dist_LB + tau * ceil(D/Q)) / (W + tau)

VALIDITY. Dist_LB lower-bounds total DIRECT street distance; actual travel can only
be larger, since a route through a satellite adds detour. Distance and time are the
same units here (Const8 adds arcStreetCost directly to service start times). So
substituting it keeps the bound valid and can only raise it.

A result >= 2 PROVES one vehicle is impossible on that cell, which removes it from
the k-1 trial field for free -- no solver, no runs.
"""
import sys, os, math, json, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
from build_instance import build                                   # noqa: E402
from lp_component_anatomy import harvest                           # noqa: E402
from crossfeed.fullset_bound import (assignment_dist_lb,           # noqa: E402
                                     mst_dist_lb, forced_terminal_dist_lb)


def bound(cell, size, tau="formula"):
    p = build(cell, size, tau=tau)
    nd, C = p.nodes, list(p.customers)
    W = nd[0].latest - nd[0].earliest
    TD = p.TransferDuration
    service = sum(nd[i].serviceTime for i in C)
    dem = sum(nd[i].demand for i in C)
    trips = math.ceil(dem / p.CarCapacity)

    ap = assignment_dist_lb(p, C)
    try:
        mst = mst_dist_lb(p, C)
    except Exception:
        mst = 0.0
    try:
        forced = forced_terminal_dist_lb(p, C, trips_lb=trips)
    except Exception:
        forced = 0.0
    dist = max(ap, mst, forced)
    which = max((ap, "AP"), (mst, "MST"), (forced, "FORCED"))[1]

    ratio = (service + dist + TD * trips) / (W + TD)
    return dict(cell=cell, W=W, TD=TD, service=service, trips=trips,
                ap=ap, mst=mst, forced=forced, dist_lb=dist, winner=which,
                ratio=ratio, fleet_lb=max(1, math.ceil(ratio - 1e-9)))


if __name__ == "__main__":
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--cells", default="")
    ap_.add_argument("--size", type=int, default=20)
    ap_.add_argument("--out", default="runs/fleet_energetic_ab.json")
    a = ap_.parse_args()

    kref = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
    per = kref["table3"]["per_instance"][str(a.size)]
    cells = [c.strip() for c in a.cells.split(",") if c.strip()] or sorted(per)
    best = harvest(set(cells), a.size)

    print(f"{'cell':7s} {'AP':>7s} {'MST':>7s} {'FORCED':>7s} {'Dist_LB':>8s} {'win':>6s} "
          f"{'ratio':>6s} {'LB':>3s} {'ours':>5s}  verdict")
    rows, proved = [], []
    for c in cells:
        r = bound(c, a.size)
        nc = (best.get(c) or {}).get("nCars")
        r["our_cars"] = nc
        if nc is None:
            v = "(no incumbent)"
        elif nc <= 1:
            v = "already 1 car"
        elif r["fleet_lb"] >= nc:
            v = f"PROVED >= {r['fleet_lb']} -- k-1 IMPOSSIBLE"
            proved.append(c)
        else:
            v = "k-1 not ruled out"
        r["verdict"] = v
        rows.append(r)
        print(f"{c:7s} {r['ap']:7.1f} {r['mst']:7.1f} {r['forced']:7.1f} {r['dist_lb']:8.1f} "
              f"{r['winner']:>6s} {r['ratio']:6.3f} {r['fleet_lb']:3d} {str(nc):>5s}  {v}")

    print(f"\nPROVED k-1 impossible: {proved or 'none'}")
    prev = {"C": 0.867, "R": 0.452, "RC": 0.386}
    print("previous ratios with plain assignment travel: C 0.867, R 0.452, RC 0.386")
    os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
    json.dump(stamped(rows, __file__), open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("wrote", a.out)
