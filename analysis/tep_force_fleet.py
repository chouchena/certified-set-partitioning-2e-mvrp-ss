"""Force the fleet down on a cell and ask whether the partition can be served at all. (d461)

WHY ONLY TWO CELLS. After ceil rounding landed at n30 (d460), 25 of 27 cells carry the RIGHT car
count -- their residual gap to the predecessors is 0.12 to 0.33 of one car, i.e. street-routing
quality. Exactly two cells still have a fleet-sized gap: R201 at 1.13 cars and RC202 at 0.91. They
are also the two worst cells, at +15.81 and +14.44 percent. This targets those and nothing else.

THE QUESTION IS FEASIBILITY, NOT COST. `assemble_precluster.chain` already prices cars at
inst.penalty_cars, so it is not choosing three cars because it cannot see the penalty. Either two
is infeasible for the partition it was handed, or the search did not find it. `chain(max_cars=k)`
-- the d439 audit hook -- separates those: it caps the fleet and asks whether ANY chaining exists.

  * a capped chain that realises and verifies, cheaper than the banked value -> a search failure,
    and the fix is to cap the fleet in production on cells where the gap is a car;
  * infeasible at every cap -> the partition genuinely needs that many cars, and the remaining gap
    is in the PARTITION, which sends the work back to the master rather than the chaining;
  * feasible but MORE expensive -> the extra car is buying more street than it costs, the fleet is
    already right, and the gap is street quality after all.

Both trip sources are tried, because floor and ceil produce different partitions and the fleet
question is about the partition.

    python analysis/tep_force_fleet.py R201 RC202 --size 30
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
from assemble_precluster import chain, decode
from tep_chain_own_water import water_tours, objective
from greedy26 import TOL
from stamp import stamped


PRUNED = {"dominance": 0, "scored": 0}   # d477: how often the lossless street-dominance prune fires


def build(inst, trips, res, exact_water=True, incumbent=None, margin=0.0):
    """chain() output -> a full solution through OUR water stage, or None if it cannot be timed.

    exact_water uses the capacitated path cover of `tep_water_opt` rather than the greedy
    insertion of `water_tours`. It defaults ON because the banked artifacts it is compared
    against already carry the exact stage -- scoring a candidate with the greedy stage against
    an exact-water incumbent is not a like-for-like comparison and silently understates the
    candidate. Falls back to greedy if the cover finds nothing inside its budget.
    """
    cand = decode(trips, res, depot=inst.depot)
    nd = inst.nodes
    if incumbent is not None:
        # d477 (author): drop a candidate whose STREET PART alone already reaches the incumbent's
        # total. Water travel and the vessel penalty are >= 0, so cars*pen + street >= incumbent
        # means it cannot win -- LOSSLESS at margin 0, and it skips the exact water solve (~60 s at
        # n100). margin > 0 is the author's "significantly higher" heuristic, off by default.
        D, dep = inst.D, inst.depot
        hub_of0 = dict(zip(cand["vi"], cand["hubs"])); tset = set(cand["vi"])
        street = sum((D[i][hub_of0[i]] + D[hub_of0[i]][j]) if i in tset else D[i][j]
                     for i, j in ((int(a), int(b)) for a, b in cand["xij"]))
        street_part = int(cand["nCars"]) * float(inst.penalty_cars) + float(inst.travelcoststreet) * street
        PRUNED["scored"] += 1
        if street_part >= float(incumbent) * (1.0 + margin) - 1e-6:
            PRUNED["dominance"] += 1
            return None
    ui = {trips[r][-1]: res["u"][r] for ch in res["chains"] for r in ch}
    tload = {trips[r][-1]: sum(float(nd[c].demand) for c in trips[r]) for ch in res["chains"] for r in ch}
    yij, nves, hub_of = water_tours(inst, cand["vi"], cand["hubs"], ui, tload)
    if exact_water and cand["vi"]:
        from tep_water_opt import optimal_tours
        ex = optimal_tours(inst, [int(x) for x in cand["vi"]], dict(zip(cand["vi"], cand["hubs"])),
                           ui, tload, cap=60.0, work=30.0)
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
    ap.add_argument("cells", nargs="+"); ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--cap", type=float, default=600.0); ap.add_argument("--work", type=float, default=300.0)
    ap.add_argument("--down", type=int, default=2, help="try this many cars below the baseline")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    out = []
    for cell in a.cells:
        inst = V.load_instance(cell, a.size, prox)
        kb, which = k_best_incumbent(cell, a.size)
        banked = None
        for sub in ("", "ceil", "selchain", "forced", "diverse", "refine", "alns", "masterip"):  # d469/d475/d582
            p = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, a.size))
            if os.path.exists(p):
                v = float(json.load(io.open(p, encoding="utf-8"))["objVal"])
                banked = v if banked is None else min(banked, v)
        # kb is None at |C| = 50 and 100, where K publish no per-cell incumbent; the unguarded "%.1f"
        # is what crashed tep_master_fleet_cap and stopped the campaign at S3b (d569).
        print("\n%s n%d: banked %.3f | their best %s"
              % (cell, a.size, banked, ("%.1f (%s)" % (kb, which)) if kb else "not published at this size"), flush=True)
        best = None
        for tag, suf in (("floor", ""), ("ceil", "_primal")):
            sp = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s_ip%s.json"
                              % (cell, "" if a.size == 100 else "_n%d" % a.size, suf))
            if not os.path.exists(sp):
                print("  %-5s no selection artifact" % tag, flush=True); continue
            trips = [list(t) for t in json.load(io.open(sp, encoding="utf-8"))["ip"]["trips"]]
            base = chain(inst, trips, cap=a.cap, work=a.work)
            if base is None:
                print("  %-5s baseline chaining infeasible" % tag, flush=True); continue
            n0 = base["cars"]
            sol0 = build(inst, trips, base)
            print("  %-5s %d trips | baseline %d cars -> %s" % (tag, len(trips), n0,
                  ("%.3f" % sol0["objVal"]) if sol0 else "not timeable"), flush=True)
            for k in range(n0 - 1, max(0, n0 - 1 - a.down), -1):
                t0 = time.time()
                r = chain(inst, trips, cap=a.cap, work=a.work, max_cars=k)
                if r is None:
                    print("        cap %d cars: INFEASIBLE (%.0fs) -- the partition needs more"
                          % (k, time.time() - t0), flush=True)
                    break
                s = build(inst, trips, r)
                if s is None:
                    print("        cap %d cars: chained but NOT TIMEABLE through the water stage" % k, flush=True)
                    continue
                run = V.verify_solution(inst, s, cell=cell, size=a.size, proximity=prox, label="force_fleet")
                bad = [x for x in run.findings if x.severity != "TOLERANCE"]
                ok = (not bad) and (not run.blocking)
                print("        cap %d cars: obj %.3f | verifier3 %s | vs banked %+.2f%% | vs theirs %s"
                      % (k, s["objVal"], "PASS" if ok else "FAIL(%s)" % (bad[0].cls if bad else "blocking"),
                         100.0 * (s["objVal"] / banked - 1),
                         ("%+.2f%%" % (100.0 * (s["objVal"] / kb - 1))) if kb else "not published"), flush=True)
                if ok and (best is None or s["objVal"] < best[0]):
                    best = (s["objVal"], s, tag, k)
        if best is not None and best[0] < banked - 1e-6:
            v, s, tag, k = best
            dst = os.path.join(ROOT, "runs", "postpass", "forced")
            if not os.path.isdir(dst):
                os.makedirs(dst)
            s["size"] = a.size; s["_proximity"] = prox; s["_verified"] = True
            s["selection"] = "forced-fleet(%s, cap %d)" % (tag, k); s["superseded_objVal"] = banked
            json.dump(stamped(s, "analysis/tep_force_fleet.py", "analysis/assemble_precluster.py"),
                      io.open(os.path.join(dst, "ownwater_%s_n%d.json" % (cell, a.size)), "w", encoding="utf-8"),
                      indent=1, default=str)
            print("  => IMPROVED to %.3f (%s, cap %d cars)%s | banked under runs/postpass/forced/"
                  % (v, tag, k, (" | %+.2f%% vs their best" % (100.0 * (v / kb - 1))) if kb else ""), flush=True)
            out.append(dict(cell=cell, improved=True, obj=v, cap=k, src=tag, banked=banked, theirs=kb))
        else:
            print("  => no capped solution beats the banked value; the fleet is not the lever here", flush=True)
            out.append(dict(cell=cell, improved=False, banked=banked, theirs=kb))
    json.dump(stamped(dict(size=a.size, cells=out)),
              io.open(os.path.join(ROOT, "runs", "oracle", "tep_force_fleet_n%d.json" % a.size), "w",
                      encoding="utf-8"), indent=1, default=str)
    print("\n  wrote runs/oracle/tep_force_fleet_n%d.json" % a.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
