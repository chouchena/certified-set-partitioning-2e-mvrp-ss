r"""Area 4 (true floor relaxation) -- map a REAL continuous-time incumbent into the floor model (d802).

The earlier floor_map_check only showed LP <= IP for the same floor model. The referee's point: that
is not the relaxation claim. Lemma teprelax says every feasible ORIGINAL (continuous-time) street
solution maps to a floor-model point of EQUAL cost, so LP^s <= z^s. This checks that on an actual
verified incumbent:

  1. decode the incumbent (tep_refine.decode) into chains of trips, with the hub (satellite) of each
     trip; tep_refine._pass confirms the continuous-time timeline is feasible and gives z^s.
  2. for each trip, with its start node L (garage, or the previous trip's hub) and its hub p both
     FIXED by the decode, add every feasible floor-model placement (bucket) of that trip as a column;
     require exactly one placement per trip.
  3. solve the floor model so the solver must satisfy EVERY row -- covering, source/fleet, pre/post
     flow conservation, and transfer-spacing packing -- using only the incumbent's trips.
  4. if it is feasible, the incumbent maps into the floor model, and its objective equals the
     incumbent's street cost z^s (the trip costs are bucket-independent), so LP^s <= z^s is witnessed
     on a real solution rather than inferred.

Run on a full small cell (|C|=10): the floor model is small enough to solve exactly.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gurobipy as gp
import verifier3 as V
from k_comparison import k_proximity
from tep_cg_bound import Master, default_delta
from tep_refine import decode, _pass
from reverify_reported import reported_row

TOL = 1e-4


def street_cost(inst, chains, hub):
    D, tc, pen = inst.D, inst.travelcoststreet, inst.penalty_cars
    g = inst.depot
    total = pen * len(chains)
    for ch in chains:
        prev = g
        for trip in ch:
            p = hub[trip[-1]]
            total += tc * (D[prev][trip[0]] + sum(D[a][b] for a, b in zip(trip, trip[1:])) + D[trip[-1]][p])
            prev = p
        total += tc * D[prev][g]   # last hub -> garage return
    return total


def check_cell(cell, size):
    inst = V.load_instance(cell, size, k_proximity(size))
    row, tag, src = reported_row(cell, size)
    if row is None or row.get("solution") is None:
        return {"cell": cell, "size": size, "skip": "no incumbent"}
    sol = row["solution"]
    chains, hub = decode(inst, sol)
    timed = _pass(inst, chains, hub, {})
    if timed is None:
        return {"cell": cell, "size": size, "skip": "decode timeline infeasible"}
    zs = street_cost(inst, chains, hub)

    delta = default_delta(inst)
    M = Master(inst, delta, threads=1, primal=False, customers=list(inst.customers))
    groups = []
    ok_cols = True
    g = inst.depot
    for ch in chains:
        prev = g
        for trip in ch:
            p = hub[trip[-1]]
            variants = [(L, b, pp, ba) for (L, b, pp, ba) in M.variants(list(trip))
                        if L == prev and pp == p]
            cols = []
            for (L, b, pp, ba) in variants:
                if M.add_column(list(trip), L, b, pp, ba):
                    cols.append(M.cols[(tuple(trip), L, b, pp)])
            # existing columns for this (trip,L,p) across buckets
            cols = [v for k, v in M.cols.items() if k[0] == tuple(trip) and k[1] == prev and k[3] == p]
            if not cols:
                ok_cols = False
            groups.append((tuple(trip), prev, p, cols))
            prev = p
    M.m.update()
    if not ok_cols:
        return {"cell": cell, "size": size, "skip": "a trip has no feasible floor placement"}
    # require exactly one placement per trip
    for (trip, L, p, cols) in groups:
        M.m.addConstr(gp.quicksum(cols) == 1, name="pick_%s_%d" % ("_".join(map(str, trip)), L))
    M.m.update()
    M.solve()
    status = M.m.Status
    feasible = status == gp.GRB.OPTIMAL
    obj = M.m.ObjVal if feasible else None
    match = feasible and abs(obj - zs) < TOL * max(1.0, abs(zs))
    return {"cell": cell, "size": size, "source": src, "n_chains": len(chains),
            "n_trips": sum(len(c) for c in chains), "street_cost_zs": round(zs, 6),
            "floor_obj": round(obj, 6) if feasible else None, "feasible": feasible,
            "obj_matches": match}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C201,R201,RC201,C204,R205")
    ap.add_argument("--size", type=int, default=10)
    a = ap.parse_args()
    rows, problems = [], []
    for cell in a.cells.split(","):
        r = check_cell(cell, a.size)
        rows.append(r)
        if r.get("skip"):
            problems.append("%s n%d: %s" % (cell, a.size, r["skip"]))
            print("  %-5s n%d  SKIP: %s" % (cell, a.size, r["skip"]))
            continue
        if not r["feasible"]:
            problems.append("%s n%d: floor model INFEASIBLE on the incumbent's trips" % (cell, a.size))
        if not r["obj_matches"]:
            problems.append("%s n%d: floor obj %s != street cost %.4f" % (cell, a.size, r["floor_obj"], r["street_cost_zs"]))
        print("  %-5s n%d  trips=%d  z^s=%.4f  floor_obj=%s  feasible=%s  matches=%s"
              % (cell, a.size, r["n_trips"], r["street_cost_zs"], r["floor_obj"], r["feasible"], r["obj_matches"]))

    lines = ["# Area 4 -- true floor-relaxation check on real incumbents", "",
             "> Evidence for the referee's \"construct original schedules, map to floor variables, check",
             "> every row and the objective\" requirement (d802). Each verified incumbent is decoded into",
             "> chains of trips (with hubs); its trips, at their decode-fixed start node and hub, are added",
             "> to the floor model, one placement required per trip, and the model is solved so every row",
             "> (covering, source/fleet, pre/post flow, transfer-spacing packing) must hold. Feasibility",
             "> with objective equal to the incumbent's street cost z^s witnesses LP^s <= z^s on a real",
             "> continuous-time solution, not by inference.", "",
             "| cell | source | trips | street cost z^s | floor obj | feasible | obj = z^s |",
             "|------|--------|-------|-----------------|-----------|----------|-----------|"]
    for r in rows:
        if r.get("skip"):
            lines.append("| %s | --- | --- | --- | --- | SKIP (%s) | --- |" % (r["cell"], r["skip"]))
        else:
            lines.append("| %s | %s | %d | %.3f | %s | %s | %s |"
                         % (r["cell"], r.get("source", "?"), r["n_trips"], r["street_cost_zs"],
                            ("%.3f" % r["floor_obj"]) if r["floor_obj"] is not None else "---",
                            "yes" if r["feasible"] else "**NO**", "yes" if r["obj_matches"] else "**NO**"))
    lines += ["", ("**Every tested incumbent maps into the floor model, feasibly, at objective equal to "
                   "its street cost -- LP^s <= z^s witnessed on real solutions.**" if not problems
                   else "**ISSUES:**")]
    for p in problems:
        lines.append("- " + p)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "validation", "AREA4_FLOOR_RELAXATION.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\nwrote %s (%d cells, %d issue(s))" % (os.path.relpath(out, os.getcwd()), len(rows), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
