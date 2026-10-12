"""Why is the corrected (26) free on L3's cells? Two different findings look identical.

L3 measures `z*_corr - z*_vac`. Where that is +0.000 there are TWO possible worlds, and the paper
must not conflate them:

  A  (26) IS NEVER VIOLATED at the vacuous optimum. The constraint is inert on this instance:
     transfers assigned to the same satellite are already >= tau apart, so correcting the
     linearization changes nothing anyone could observe. "(26) does not bite here."

  B  (26) IS VIOLATED at the vacuous optimum, but a reshuffle repairs it at ZERO cost. The
     vacuous model returns an INFEASIBLE schedule; the corrected model returns a different,
     genuinely feasible one at the same objective. "(26) bites, and the price is zero."

Both print +0.000. Only B is evidence that the vacuous linearization admits infeasible schedules
at this size -- which is the project's whole claim -- and only A would license saying the
constraint is irrelevant at n20.

THE MEASUREMENT. Re-solve the vacuous arm to optimality, take the returned (u, v_ip), and count
same-satellite transfer pairs with |u_i - u_j| < tau. Zero -> world A. Non-zero -> world B, and
the count is how badly K's own published model is violated by its own optimum.

    python analysis/oracle_L3_diag.py [--tl 2400] [--threads 8]
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import instance_view
import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")


def posts_26(sol, tau):
    """Same-satellite transfer pairs closer than tau, at the solution's own (u, hub)."""
    tset = [int(c) for c in sol["vi"]]
    hubs = [int(q) for q in sol["hubs"]]
    u = {int(k): float(v) for k, v in (sol.get("ui") or {}).items()}
    hub = dict(zip(tset, hubs))
    bad, checked = [], 0
    for a in range(len(tset)):
        for b in range(a + 1, len(tset)):
            i, j = tset[a], tset[b]
            if hub.get(i) != hub.get(j):
                continue
            if i not in u or j not in u:
                continue
            checked += 1
            gap = abs(u[i] - u[j])
            if gap < tau - 1e-6:
                bad.append((i, j, hub[i], round(gap, 4), round(tau, 4)))
    return checked, bad


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=2400.0)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()

    src = os.path.join(OUT, "L3.jsonl")
    if not os.path.exists(src):
        print("L3 has not produced results yet (%s missing)" % src)
        return 2
    cells = []
    for line in open(src, encoding="utf-8"):
        r = json.loads(line)
        if r.get("vac_proven"):
            cells.append(r)

    from build_instance import build
    from joint_model_gurobi import joint_synchronized_gurobi
    from gurobipy import GRB

    print("L3 DIAGNOSTIC -- is the corrected (26) free because it never bites, or because the")
    print("                 repair is costless? Those are different findings.")
    print()
    print("   %-7s %4s %8s %9s %12s %11s %s"
          % ("cell", "n", "tau", "sat-pairs", "VIOLATING", "worst gap", "world"))
    rows, tot_viol = [], 0
    for r in cells:
        cell, size, prox = r["cell"], r["size"], r["proximity"]
        p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
        p.hardSingleTransfer = False                       # K's own published arm
        res = joint_synchronized_gurobi(p, time_limit=a.tl, mip_gap=0.0, threads=a.threads,
                                        log_output=False)
        if res["status"] != GRB.OPTIMAL or res.get("solution") is None:
            print("   %-7s %4d   re-solve did not prove optimality -- skipped" % (cell, size))
            continue
        sol = dict(res["solution"])
        tau = float(p.TransferDuration)
        checked, bad = posts_26(sol, tau)
        tot_viol += len(bad)
        world = ("A: (26) never violated" if not bad
                 else "B: (26) VIOLATED at K's own optimum")
        worst = min((g for _i, _j, _q, g, _t in bad), default=None)
        print("   %-7s %4d %8.2f %9d %12d %11s %s"
              % (cell, size, tau, checked, len(bad),
                 "-" if worst is None else "%.3f" % worst, world))
        for i, j, q, gap, t in bad[:3]:
            print("        customers %s and %s both transfer at satellite %s, %.3f apart, tau %.3f"
                  % (i, j, q, gap, t))
        rows.append(dict(cell=cell, size=size, tau=tau, same_sat_pairs=checked,
                         violating=len(bad), worst_gap=worst,
                         price=r.get("c26_price"), world="A" if not bad else "B",
                         examples=bad[:5]))

    print()
    nA = sum(1 for r in rows if r["world"] == "A")
    nB = len(rows) - nA
    print("   world A (inert) %d   world B (violated, repair free) %d   cells measured %d"
          % (nA, nB, len(rows)))
    print()
    if nB:
        print("   At least one cell's VACUOUS optimum -- the optimum of K's own published model --")
        print("   violates (26). Zero price does NOT mean the constraint is irrelevant: it means")
        print("   the repair happens to cost nothing at this size.")
    elif rows:
        print("   On every measured cell the vacuous optimum already satisfies (26). At this size")
        print("   the constraint is INERT, and a zero price says nothing about larger instances")
        print("   where more transfers share a satellite.")
    json.dump(stamped({"rows": rows, "world_A": nA, "world_B": nB,
               "when": time.strftime("%Y-%m-%dT%H:%M:%S")}, __file__),
              open(os.path.join(OUT, "L3_diag.json"), "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
