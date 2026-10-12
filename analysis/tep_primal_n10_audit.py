"""FULL AUDIT of the n10 cells the TEP primal route leaves more than 5% above K's proven optimum.

Author instruction, 2026-09-25: "vs K % note above 5% on n10 DEMAND full audit."

Five cells qualify: R201 +33.4, R202 +39.1, R203 +39.1, RC201 +27.7 (all two cars) and R204 +5.3
(one car). K prove all 27 cells optimal at n10, so the target is to MATCH, never to beat, and every
one of these five is a shortfall of ours.

The route has three stages that could each be responsible, and this separates them:

  selection   the master IP picks the trip partition, minimising a BUCKETED street cost whose car
              term is computed on the floor-rounded grid -- a car may be ready earlier than reality
  chaining    an exact continuous-time model chains the given trips, minimising
              penalty * cars + travel. Given the trips, it is optimal, so it cannot be the culprit
              unless it hit a cap
  re-timing   exact, with the street fixed; it can only move the water side

Four questions, each answered by a run rather than an argument:

  Q1  What does the bucketed selection claim, and by how much does its car count undercount?
  Q2  Is the selected partition servable by FEWER cars at all? (chaining with the fleet capped)
  Q3  If it is servable, is the cheaper option still worse than K? (the capped objective)
  Q4  Would a DIFFERENT partition -- the composition heuristic's -- chain into fewer cars on the
      same instance? That separates "the selection chose badly" from "the instance needs two cars"

    python analysis/tep_primal_n10_audit.py
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from assemble_precluster import chain, decode, retime
from precluster_trips import Ctx, prio_st
from stamp import stamped

CELLS = ["R201", "R202", "R203", "RC201", "R204"]


def k_inc(size, cell):
    d = json.load(io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"), encoding="utf-8"))["n%d" % size]
    for r in d["rows"]:
        if r["cell"] == cell:
            return float(r["k_inc"]), bool(r["proven"])
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default=",".join(CELLS)); ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--cap", type=float, default=300.0)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    out = {}
    for cell in a.cells.split(","):
        inst = V.load_instance(cell, a.size, prox)
        pen, tc = float(inst.penalty_cars), float(inst.travelcoststreet)
        ki, proven = k_inc(a.size, cell)
        ipf = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d_ip.json" % (cell, a.size))
        ip = json.load(io.open(ipf, encoding="utf-8"))["ip"]
        trips = [list(t) for t in ip["trips"]]
        sol = json.load(io.open(os.path.join(ROOT, "runs", "postpass", "ipchain_%s_n%d.json" % (cell, a.size)), encoding="utf-8"))
        print("\n=== %s n%d   K optimum %.2f (proven %s)   our verified %.3f with %d cars  (%+.2f%%)"
              % (cell, a.size, ki, proven, sol["objVal"], sol["nCars"], 100.0 * (sol["objVal"] / ki - 1)), flush=True)
        print("  objective split: fleet %.2f + street travel %.2f + water %.2f   (penalty per car %.1f)"
              % (float(sol.get("FleetStreet", 0)), float(sol.get("TravelStreet", 0)),
                 float(sol["objVal"]) - float(sol.get("FleetStreet", 0)) - float(sol.get("TravelStreet", 0)), pen), flush=True)

        # Q1 -------------------------------------------------------------------------------
        base = chain(inst, trips, cap=a.cap, work=120.0)
        print("  Q1 selection claimed %d car(s), bucketed street %.1f over %d trips; exact chaining of the SAME trips: %d car(s), street %.1f"
              % (ip["ip_cars"], ip["ip_street"], len(trips), base["cars"], base["street"]), flush=True)
        undercount = base["cars"] - int(round(ip["ip_cars"]))

        # Q2 and Q3 ------------------------------------------------------------------------
        capped = None
        if base["cars"] > 1:
            capped = chain(inst, trips, cap=a.cap, work=120.0, max_cars=base["cars"] - 1)
            if capped is None:
                print("  Q2 with the fleet capped at %d: INFEASIBLE -- the SELECTED PARTITION genuinely needs %d cars"
                      % (base["cars"] - 1, base["cars"]), flush=True)
            else:
                print("  Q2 with the fleet capped at %d: feasible, street %.1f (%.1f more than uncapped, against a car penalty of %.1f)"
                      % (base["cars"] - 1, capped["street"], capped["street"] - base["street"], pen), flush=True)
                print("  Q3 so the chaining preferred the extra car by %.1f; that is its own optimum, not a defect"
                      % (capped["street"] - base["street"] - pen), flush=True)

        # Q4 -------------------------------------------------------------------------------
        ctx = Ctx(inst)
        alt = prio_st(ctx)
        altres = chain(inst, alt, cap=a.cap, work=120.0)
        if altres is None:
            print("  Q4 the composition heuristic's %d trips do not chain at all" % len(alt), flush=True)
            alt_cars = None; alt_obj = None
        else:
            alt_cars = altres["cars"]
            print("  Q4 the composition heuristic's %d trips chain into %d car(s), street %.1f"
                  % (len(alt), altres["cars"], altres["street"]), flush=True)
            cand = decode(alt, altres, depot=inst.depot)
            o, st, secs = retime(cell, cand, cap=180.0, size=a.size, proximity=prox)
            if o is None:
                print("     and do not re-time (%s)" % st, flush=True); alt_obj = None
            else:
                run = V.verify_solution(inst, o, cell=cell, size=a.size, proximity=prox, label="alt")
                bad = [x for x in run.findings if x.severity != "TOLERANCE"]
                ok = (not bad) and (not run.blocking)
                alt_obj = float(o["objVal"])
                print("     re-timed to %.3f with %d car(s), verifier3 %s  (%+.2f%% vs K)"
                      % (alt_obj, o["nCars"], "PASS" if ok else "FAIL", 100.0 * (alt_obj / ki - 1)), flush=True)

        out[cell] = dict(k_inc=ki, proven=proven, ours=float(sol["objVal"]), our_cars=int(sol["nCars"]),
                         pct=100.0 * (sol["objVal"] / ki - 1), penalty=pen,
                         ip_cars=ip["ip_cars"], ip_street=ip["ip_street"], ip_trips=len(trips),
                         chain_cars=base["cars"], chain_street=base["street"], car_undercount=undercount,
                         capped_feasible=(capped is not None) if base["cars"] > 1 else None,
                         capped_street=(capped["street"] if capped else None),
                         alt_trips=len(alt), alt_cars=alt_cars, alt_obj=alt_obj)

    # ---- verdict ---------------------------------------------------------------------
    print("\n%-7s %9s %9s %8s %7s %7s %8s %9s %9s" %
          ("cell", "K opt", "ours", "vs K %", "IP cars", "real", "under", "alt cars", "alt obj"))
    for c, r in out.items():
        print("%-7s %9.2f %9.3f %+7.2f%% %7.0f %7d %8d %9s %9s" %
              (c, r["k_inc"], r["ours"], r["pct"], r["ip_cars"], r["chain_cars"], r["car_undercount"],
               r["alt_cars"] if r["alt_cars"] is not None else "-",
               ("%.3f" % r["alt_obj"]) if r["alt_obj"] else "-"))
    nu = sum(1 for r in out.values() if r["car_undercount"] > 0)
    print("\n  the bucketed selection UNDERCOUNTS the fleet on %d of %d audited cells" % (nu, len(out)))
    better = [c for c, r in out.items() if r["alt_obj"] and r["alt_obj"] < r["ours"] - 1e-6]
    print("  the composition heuristic's partition beats the master's on %d of %d: %s"
          % (len(better), len(out), ", ".join(better) if better else "none"))
    p = os.path.join(ROOT, "runs", "oracle", "tep_primal_n%d_audit.json" % a.size)
    json.dump(stamped(dict(size=a.size, cells=out)), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
