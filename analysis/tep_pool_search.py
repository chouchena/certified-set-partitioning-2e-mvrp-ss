"""Score the master's SOLUTION POOL by the real objective instead of trusting its proxy (d457).

THE PROBLEM THIS TARGETS. The master ranks trip partitions by a bucketed street cost with a
floor-rounded fleet term and NO WATER AT ALL. We then take its argmin on trust. Against the
predecessors' published Table 6 split at n100 we beat them on cars in all three families and on
street travel in two, and lose on WATER TRAVEL in all three by 12 to 21 percent -- exactly the
component the ranking cannot see.

THE FIX IS NOT A NEW MODEL. Ask the solver for its top-k integer solutions, push each through the
REAL pipeline -- our chaining model, our vessel-tour consolidation -- and keep the one that is
genuinely cheapest. The proxy becomes a candidate generator and the exact evaluation becomes the
ranking. At n30 the chaining solved to proven optimality in 0-1 s on every bad cell, so scoring k
candidates costs a handful of seconds.

WHAT THE RESULT MEANS, fixed before running:
  * some candidate materially beats the proxy's pick -> the RANKING is the problem and the fix is
    a few lines of wiring
  * every candidate is worse -> the POOL is the limit, re-ranking cannot help, and the next move is
    the formulation (water into the master, or a corrected fleet term)

    python analysis/tep_pool_search.py R211 --size 30 --pool 12
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
from k_comparison import k_proximity, k_best_incumbent
import tep_cg_bound as T
from assemble_precluster import chain, decode
from tep_chain_own_water import water_tours, objective
from greedy26 import TOL
from stamp import stamped


PRUNED = {"dominance": 0, "scored": 0}   # d477


def realise(inst, trips, cap, work, incumbent=None, margin=0.0):
    """The exact pipeline for one candidate partition: chain, consolidate vessels, score, verify."""
    res = chain(inst, trips, cap=cap, work=work)
    if res is None:
        return None
    cand = decode(trips, res, depot=inst.depot)
    nd = inst.nodes
    if incumbent is not None:                              # d477: lossless street-dominance prune (see tep_force_fleet.build)
        D = inst.D; hub_of0 = dict(zip(cand["vi"], cand["hubs"])); tset = set(cand["vi"])
        street = sum((D[i][hub_of0[i]] + D[hub_of0[i]][j]) if i in tset else D[i][j]
                     for i, j in ((int(a), int(b)) for a, b in cand["xij"]))
        PRUNED["scored"] += 1
        if int(cand["nCars"]) * float(inst.penalty_cars) + float(inst.travelcoststreet) * street >= float(incumbent) * (1.0 + margin) - 1e-6:
            PRUNED["dominance"] += 1
            return None
    ui = {trips[r][-1]: res["u"][r] for ch in res["chains"] for r in ch}
    tload = {trips[r][-1]: sum(float(nd[c].demand) for c in trips[r]) for ch in res["chains"] for r in ch}
    yij, nves, hub_of = water_tours(inst, cand["vi"], cand["hubs"], ui, tload)
    # 2026-09-26, author: "street then water after each street and keep best combined". This
    # function is what tep_diverse_primal ranks candidates with, and it was still GREEDY water
    # after d466 wired the exact stage everywhere else -- so d459's refutation of forced diversity
    # tested ranking by street + greedy water, not by the true objective. Exact water here makes
    # the ranking the author asked for; the d459 sample and gates are re-run unchanged.
    if cand["vi"]:
        from tep_water_opt import optimal_tours
        ex = optimal_tours(inst, [int(x) for x in cand["vi"]], hub_of, ui, tload, cap=60.0, work=30.0)
        if ex is not None:
            yij, nves = ex[0], ex[1]
    H = {int(c): float(v) for c, v in res["a"].items()}
    h0 = float(nd[inst.depot].earliest)
    for last in {int(x[0]) for x in cand["xij"] if int(x[1]) == inst.depot}:
        if last in hub_of:
            h0 = max(h0, ui[last] + float(inst.tau) + inst.D[hub_of[last]][inst.depot])
        else:
            h0 = max(h0, H[last] + float(nd[last].service) + inst.D[last][inst.depot])
    if h0 > float(nd[inst.depot].latest) + TOL:
        return None
    H[0] = h0
    sol = dict(xij=[list(map(int, x)) for x in cand["xij"]], vi=[int(x) for x in cand["vi"]],
               hubs=[int(x) for x in cand["hubs"]], yij=yij, nCars=int(cand["nCars"]), nVessel=nves,
               hi={str(k): float(v) for k, v in H.items()}, ui={str(k): float(v) for k, v in ui.items()})
    sol["objVal"] = objective(inst, sol, hub_of)
    return sol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--pool", type=int, default=12)
    ap.add_argument("--diversify", type=int, default=0,
                    help="after each solution, FORBID that exact column set and re-solve, N times. "
                         "The pool returned 3 distinct partitions of 12 on R211 n30, so a pool test "
                         "alone cannot show whether the formulation or the search is the limit (d457).")
    ap.add_argument("--ip-time", type=float, default=300.0)
    ap.add_argument("--cap", type=float, default=120.0); ap.add_argument("--work", type=float, default=60.0)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = T.default_delta(inst)

    # converge the master, then solve its IP with a SOLUTION POOL rather than for one answer
    r = T.run(a.cell, delta, 400, ["prio", "ts"], 10, 1000, False, 3_000_000, size=a.size,
              start_states=True, proximity=prox, return_master=True, max_secs=300.0)
    M = r["master"]
    import gurobipy as gp
    from gurobipy import GRB
    for v in M.cols.values(): v.VType = GRB.BINARY
    for v in M.z.values(): v.VType = GRB.BINARY
    M.N.VType = GRB.INTEGER
    for row in M.cov.values(): row.Sense = GRB.EQUAL
    M.m.Params.Threads = 1
    M.m.Params.TimeLimit = a.ip_time
    M.m.Params.PoolSearchMode = 2                  # find the k best, not just any k
    M.m.Params.PoolSolutions = a.pool
    t0 = time.time(); M.m.optimize(); ip_s = time.time() - t0
    n = M.m.SolCount
    print("%s n%d: master IP returned %d pooled solution(s) in %.0f s" % (a.cell, a.size, n, ip_s), flush=True)
    if n == 0:
        print("  no integer solution"); return 1

    kb, which = k_best_incumbent(a.cell, a.size)
    rows = []

    if a.diversify:
        # forced-diversity arm: solve, forbid that exact column set, solve again. This produces
        # STRUCTURALLY different partitions rather than the near-duplicates a solution pool returns
        # under degeneracy.
        M.m.Params.PoolSearchMode = 0; M.m.Params.PoolSolutions = 1
        M.m.Params.TimeLimit = min(a.ip_time, 60.0)
        for rnd in range(a.diversify):
            if rnd:
                M.m.optimize()
                if M.m.SolCount == 0:
                    print("  round %d: no further partition" % rnd, flush=True); break
            used = [k for k, v in M.cols.items() if v.X > 0.5]
            trips = [list(k[0]) for k in used]
            cov = [c for t in trips for c in t]
            proxy = float(M.m.ObjVal)
            if len(set(cov)) == len(list(inst.customers)) and len(cov) == len(set(cov)):
                sol = realise(inst, trips, a.cap, a.work)
                rows.append(dict(i=rnd, proxy=proxy, obj=(float(sol["objVal"]) if sol else None),
                                 cars=(sol["nCars"] if sol else None), vessels=(sol["nVessel"] if sol else None),
                                 trips=len(trips), why=None if sol else "did not realise", sol=sol))
            else:
                rows.append(dict(i=rnd, proxy=proxy, obj=None, why="not a partition"))
            M.m.addConstr(gp.quicksum(M.cols[k] for k in used) <= len(used) - 1,
                          name="nogood_%d" % rnd)                      # forbid exactly this set
            M.m.update()
        print("  forced-diversity arm: %d distinct partitions" % len(rows), flush=True)
    else:
     for i in range(n):
        M.m.Params.SolutionNumber = i
        used = [k for k, v in M.cols.items() if v.Xn > 0.5]
        trips = [list(k[0]) for k in used]
        cov = [c for t in trips for c in t]
        if len(set(cov)) != len(list(inst.customers)) or len(cov) != len(set(cov)):
            rows.append(dict(i=i, proxy=M.m.PoolObjVal, obj=None, why="not a partition")); continue
        sol = realise(inst, trips, a.cap, a.work)
        if sol is None:
            rows.append(dict(i=i, proxy=M.m.PoolObjVal, obj=None, why="did not realise")); continue
        rows.append(dict(i=i, proxy=float(M.m.PoolObjVal), obj=float(sol["objVal"]),
                         cars=sol["nCars"], vessels=sol["nVessel"], trips=len(trips), sol=sol))
    ok = [x for x in rows if x.get("obj")]
    print("\n  %-4s %12s %12s %6s %8s   %s" % ("rank", "proxy street", "REAL obj", "cars", "vessels", "vs their best"))
    for x in rows:
        if x.get("obj"):
            print("  %-4d %12.1f %12.1f %6d %8d   %+.2f%%"
                  % (x["i"], x["proxy"], x["obj"], x["cars"], x["vessels"],
                     100.0 * (x["obj"] / kb - 1) if kb else float("nan")))
        else:
            print("  %-4d %12.1f %12s %6s %8s   %s" % (x["i"], x["proxy"], "-", "-", "-", x["why"]))
    if not ok:
        print("\n  nothing realised"); return 1
    proxy_pick = min(ok, key=lambda x: x["proxy"])
    best = min(ok, key=lambda x: x["obj"])
    print("\n  the proxy would pick rank %d -> real %.1f" % (proxy_pick["i"], proxy_pick["obj"]))
    print("  the best in the pool is rank %d -> real %.1f  (%+.2f%%)"
          % (best["i"], best["obj"], 100.0 * (best["obj"] / proxy_pick["obj"] - 1)))
    if best["i"] != proxy_pick["i"]:
        print("  *** THE RANKING IS THE PROBLEM: exact scoring finds a better partition in the same pool ***")
    else:
        print("  the proxy already picked the best of %d candidates -- the POOL is the limit, not the ranking" % len(ok))
    rec = dict(cell=a.cell, size=a.size, pool=a.pool, their_best=kb, their_method=which,
               candidates=[{k: v for k, v in x.items() if k != "sol"} for x in rows],
               proxy_pick=proxy_pick["i"], proxy_obj=proxy_pick["obj"], best=best["i"], best_obj=best["obj"])
    p = os.path.join(ROOT, "runs", "oracle", "tep_pool_search_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped(rec), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
