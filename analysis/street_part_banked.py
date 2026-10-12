"""Street part (penalty_cars * nCars + travelcoststreet * street) of every banked, verified n100
artifact of a cell -- the necessary check for the TEP CG street bound (TEP_cg_bound_n100.md
section 3.2): a valid bound is <= every one of them.

    python analysis/street_part_banked.py R204
"""
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V


def main(cell):
    inst = V.load_instance(cell, 100, 0.1)
    pen, tc = float(inst.penalty_cars), float(inst.travelcoststreet)
    pats = [os.path.join(ROOT, "runs", "postpass", "assembled_%s_n100_*.json" % cell),
            os.path.join(ROOT, "runs", "postpass", "chain_%s_n100_*.json" % cell),
            os.path.join(ROOT, "runs", "tep", "*%s*.json" % cell),
            os.path.join(ROOT, "runs", "tsc", "*%s*.json" % cell)]
    rows = []
    for pat in pats:
        for f in sorted(glob.glob(pat)):
            try:
                d = json.load(io.open(f, encoding="utf-8"))
            except Exception:
                continue
            # FleetStreet = penalty_cars * nCars, TravelStreet = travelcoststreet * street; the
            # artifact's objVal was recomputed by verifier3 (_verifier_recomputed) from the routes,
            # and the four components sum to it, so the split is the verified one.
            fs, ts, ncars, obj = d.get("FleetStreet"), d.get("TravelStreet"), d.get("nCars"), d.get("objVal")
            if fs is None or ts is None or ncars is None or d.get("_verifier_recomputed") is None:
                continue
            if abs(float(fs) - pen * float(ncars)) > 1e-3:
                print("  WARNING %s: FleetStreet %.2f != penalty_cars * nCars %.2f" % (f, float(fs), pen * float(ncars)))
            rows.append((float(fs) + float(ts), float(obj), int(ncars), float(ts) / tc, os.path.relpath(f, ROOT)))
    rows.sort()
    print("%s n100: penalty_cars %.2f, travelcoststreet %.2f; %d banked artifacts with a verifier street figure" % (cell, pen, tc, len(rows)))
    for sp, obj, n, st, f in rows:
        print("  street part %8.1f  (obj %8.1f, %d cars, street %7.1f)  %s" % (sp, obj, n, st, f))
    if rows:
        print("  MINIMUM street part %.1f -- a valid street bound must not exceed it" % rows[0][0])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "R204")
