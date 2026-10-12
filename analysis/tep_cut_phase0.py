"""PHASE 0 of the cut smoke test: can Oliveira et al.'s aggregate rounded-capacity cuts move our bound at all? (d564)

WHAT IS BEING TESTED. Oliveira, Ramos and de Sousa (Ann. Oper. Res. 361(2), 2026, 805-835,
doi 10.1007/s10479-026-07220-y) strengthen a three-index arc model with three families:

  SB1/SB2 (35)-(38)  lexicographic symmetry breaking on the vehicle index
  RC      (39)-(42)  first-echelon vehicles  >= ceil(total demand / Q_1)
  SRC     (43)-(44)  satellite visits        >= ceil(TD / Q_2)

SB is inapplicable to us: our master has no vehicle index, columns are trips and the fleet is a
count, so there is no vehicle-index symmetry to break. RC and SRC are what this script tests.

HOW, WITHOUT A SOLVER. In our master every trip ends in a transfer at a satellite and carries at most
Q = 50, so both RC and SRC become one inequality over the column variables:

    sum_r x_r  >=  ceil( sum_i q_i / Q )                                    (the trip-count cut)

Its UN-ROUNDED form is already implied: the covering rows force the carried load to be at least the
total demand, and each column carries at most Q, so sum_r x_r >= sum_i q_i / Q holds at every LP
solution. **Only the ceiling is new.** The most the cut can therefore add is

    delta_trips = ceil(sum q / Q) - sum q / Q          (zero when Q divides the demand)

extra trip mass, and every extra trip costs at least the cheapest possible out-and-back from a
satellite,  min over customers c of  min over satellites p of ( D[p][c] + D[c][p] ),  because a trip
leaves a satellite, serves at least one customer and returns to a satellite. So

    max possible LP lift  =  delta_trips * cheapest_trip_cost

is an OPTIMISTIC upper estimate of what the cut can buy, computed from the instance alone. It
over-states, because the LP will re-optimise rather than pay the cheapest trip at full price.

KILL RULE, fixed before the numbers are seen: if the optimistic lift is below 0.5 per cent of our
certified bound on every cell, the aggregate form cannot matter and Phase 1 tests only the SUBSET
form (trips covering S >= ceil(q(S)/Q)), which their paper does not use.

The vessel side of RC is checked too: their (39) is our ceil(total demand / vessel capacity), which
`instance_view.min_vessels` already computes and the water term already carries.

    python analysis/tep_cut_phase0.py [--sizes 10 20 30 50 100]
"""
import argparse
import io
import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import instance_view
import verifier3 as V
from bound_certificate import bound_class
from k_comparison import k_proximity
from stamp import stamped

CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
Q = float(instance_view.LEFV_CAPACITY)
QW = float(instance_view.VESSEL_CAPACITY)
KILL_PCT = 0.5


def certified_bound(cell, size):
    """The bound we actually report for this cell, whichever certificate class won."""
    import glob
    best = None
    pats = ["tep_cg_bound_%s_n%d*.json" % (cell, size)]
    if size == 100:
        pats += ["tep_cg_bound_%s.json" % cell, "tep_cg_bound_%s_d*.json" % cell,
                 "tep_easy_reduction_%s_n100_k*.json" % cell]
    for pat in pats:
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
            d = json.load(io.open(p, encoding="utf-8"))
            if (d.get("size") or 100) != size or not bound_class(d):
                continue
            v = d.get("composed") if d.get("composed") is not None else d.get("lp_composed")
            if v is None and d.get("lp_street") is not None:
                v = d["lp_street"]
            if v is not None and (best is None or float(v) > best):
                best = float(v)
    return best


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100])
    a = ap.parse_args()
    rows = []
    for n in a.sizes:
        prox = k_proximity(n)
        for c in CELLS:
            I = V.load_instance(c, n, prox)
            cust = list(I.customers); D = I.D
            dem = sum(float(I.nodes[i].demand) for i in cust)
            trips_lb = dem / Q
            delta = math.ceil(trips_lb - 1e-9) - trips_lb
            cheapest = min(min(D[p][i] + D[i][p] for p in I.satellites) for i in cust)
            lift = delta * cheapest
            lb = certified_bound(c, n)
            rows.append(dict(size=n, cell=c, demand=dem, trips_lb=trips_lb,
                             trips_cut=math.ceil(trips_lb - 1e-9), delta_trips=delta,
                             cheapest_trip=cheapest, est_lift=lift, our_bound=lb,
                             est_lift_pct=(100.0 * lift / lb) if lb else None,
                             vessels_cut=math.ceil(dem / QW - 1e-9), min_vessels=int(I.min_vessels)))
    print("PHASE 0 -- can their aggregate rounded-capacity cuts move our bound? Kill rule: %.1f%% of the bound.\n" % KILL_PCT)
    print("%-5s %-6s %9s %9s %8s %11s %10s %11s %8s" %
          ("size", "cell", "demand", "demand/Q", "cut at", "slack trips", "min trip", "est lift", "of bound"))
    for r in sorted(rows, key=lambda x: -(x["est_lift_pct"] or 0))[:12]:
        print("%-5d %-6s %9.0f %9.2f %8d %11.2f %10.1f %11.1f %7s"
              % (r["size"], r["cell"], r["demand"], r["trips_lb"], r["trips_cut"], r["delta_trips"],
                 r["cheapest_trip"], r["est_lift"], ("%.2f%%" % r["est_lift_pct"]) if r["est_lift_pct"] else "n/a"))
    print("  (the twelve cells with the largest optimistic lift, of %d)" % len(rows))
    pcts = [r["est_lift_pct"] for r in rows if r["est_lift_pct"] is not None]
    over = [r for r in rows if (r["est_lift_pct"] or 0) >= KILL_PCT]
    print()
    for n in sorted({r["size"] for r in rows}):
        rs = [r for r in rows if r["size"] == n]
        ps = [r["est_lift_pct"] for r in rs if r["est_lift_pct"] is not None]
        print("  n%-4d %2d cells | slack trips median %.2f max %.2f | optimistic lift median %s max %s"
              % (n, len(rs), st.median(r["delta_trips"] for r in rs), max(r["delta_trips"] for r in rs),
                 ("%.2f%%" % st.median(ps)) if ps else "n/a", ("%.2f%%" % max(ps)) if ps else "n/a"))
    bad = [r for r in rows if r["vessels_cut"] != r["min_vessels"]]
    print("\n  their RC on the first echelon is our ceil(demand / %d): matches instance_view.min_vessels on %d of %d cells%s"
          % (QW, len(rows) - len(bad), len(rows), "" if not bad else " -- MISMATCH on %s" % ", ".join("n%d %s" % (r["size"], r["cell"]) for r in bad[:5])))
    print("  cells where the optimistic lift reaches the %.1f%% kill threshold: %d of %d" % (KILL_PCT, len(over), len(rows)))
    print("  VERDICT: %s" % ("the aggregate form is NOT dead -- %d cell(s) clear the threshold, Phase 1 must test it too"
                             % len(over) if over else
                             "the aggregate form is DEAD on every cell. Phase 1 tests only the SUBSET form."))
    p = os.path.join(ROOT, "runs", "oracle", "tep_cut_phase0.json")
    json.dump(stamped(dict(kill_pct=KILL_PCT, Q=Q, QW=QW, rows=rows,
                           over_threshold=[dict(size=r["size"], cell=r["cell"], pct=r["est_lift_pct"]) for r in over])),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
