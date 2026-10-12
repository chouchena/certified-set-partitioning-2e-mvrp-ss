"""DUAL QUESTION, first instrument: a VALID trip set-covering LP bound on street travel.

Every customer is served by exactly one trip (<= 4 customers by capacity Q = 50 at these demands,
<= 5 allowed here to be safe), each trip starts at the depot or a satellite and ends at a satellite.
COMPLETE enumeration of feasible customer sets (time windows and capacity, any radius); for each
set the minimum over orders of: entry leg (min over depot and satellites to the first customer)
+ intra-trip travel + exit leg (min over satellites from the last customer). Dropping the
requirement that consecutive trips of one car connect only lowers the cost, and set COVERING
(>= 1) relaxes partitioning, so the LP value is a valid lower bound on the street travel of any
feasible solution -- comparable with the arithmetic bound's travel term (ab_grid_provenanced
best_travel). Gurobi LP, 1 thread.
"""
import io
import itertools
import json
import os
import sys
import time

import gurobipy as gp
from gurobipy import GRB

ROOT = r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V

Q = 50.0


def enumerate_sets(inst, maxlen):
    nd, D = inst.nodes, inst.D
    C = list(inst.customers)
    e = {c: float(nd[c].earliest) for c in C}; l = {c: float(nd[c].latest) for c in C}
    sv = {c: float(nd[c].service) for c in C}; dem = {c: float(nd[c].demand) for c in C}
    entry = {c: min([D[inst.depot][c]] + [D[p][c] for p in inst.satellites]) for c in C}
    exitc = {c: min(D[c][p] for p in inst.satellites) for c in C}
    succ = {i: [j for j in C if j != i and e[i] + sv[i] + D[i][j] <= l[j]] for i in C}
    best = {}                      # frozenset -> min travel over feasible orders

    def ext(seq, load, ready, travel):
        key = frozenset(seq)
        cost = entry[seq[0]] + travel + exitc[seq[-1]]
        if cost < best.get(key, float("inf")):
            best[key] = cost
        if len(seq) == maxlen:
            return
        last = seq[-1]
        for j in succ[last]:
            if j in seq or load + dem[j] > Q:
                continue
            arr = max(e[j], ready + D[last][j])
            if arr > l[j]:
                continue
            ext(seq + [j], load + dem[j], arr + sv[j], travel + D[last][j])

    for c in C:
        ext([c], dem[c], e[c] + sv[c], 0.0)
    return best


def lp_bound(inst, sets, covering=True):
    C = list(inst.customers)
    m = gp.Model("spp"); m.Params.OutputFlag = 0; m.Params.Threads = 1; m.Params.Method = 2   # barrier
    keys = list(sets.keys())
    x = m.addVars(len(keys), lb=0.0, obj=[sets[k] for k in keys])
    rows = {c: [] for c in C}
    for i, k in enumerate(keys):
        for c in k:
            rows[c].append(i)
    for c in C:
        expr = gp.quicksum(x[i] for i in rows[c])
        m.addConstr(expr >= 1 if covering else expr == 1)
    m.ModelSense = GRB.MINIMIZE
    t0 = time.time(); m.optimize()
    return m.ObjVal, time.time() - t0, len(keys)


def main():
    cells = sys.argv[1].split(",") if len(sys.argv) > 1 else ["R204", "C204", "RC204"]
    maxlen = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}
    print("TRIP SET-COVERING LP BOUND ON STREET TRAVEL (complete enumeration, <= %d customers) vs the arithmetic bound's travel term\n" % maxlen)
    for cell in cells:
        inst = V.load_instance(cell, 100, 0.1)
        t0 = time.time(); sets = enumerate_sets(inst, maxlen); te = time.time() - t0
        val, tl, ncol = lp_bound(inst, sets)
        r = ab[(cell, 100)]
        print("%-5s sets %8d (%.0f s)  LP %.1f in %.0f s  | AB travel term %.1f (%s)  -> %+.1f%%  | incumbent TravelStreet: census %s"
              % (cell, ncol, te, val, tl, r["best_travel"], r["which"], 100 * (val / r["best_travel"] - 1),
                 json.load(io.open(os.path.join(ROOT, "runs", "grid", "g_%s_n100_p0.1_s0.json" % cell), encoding="utf-8")).get("TravelStreet")), flush=True)


if __name__ == "__main__":
    main()
