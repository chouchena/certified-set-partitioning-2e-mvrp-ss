"""The chaining route with OUR water stage instead of the predecessors' re-timing (d451).

WHAT THIS CHANGES, AND WHY IT IS SMALL. Reading `fixopt._freeze_street_only` settles a question I
had been answering wrongly: re-timing fixes the ENTIRE street decision, arcs and hub assignment
alike, and leaves only the water side free -- "CPLEX then returns the optimal vessel routing for
this street solution". So re-timing is not where the chaining route's street quality comes from.

`assemble_precluster.chain` is OURS: it builds its own Gurobi model with hub choice, car chains,
transfer times, the tau-spacing, and depot and CDC returns, and imports nothing from the
predecessors. The ONLY K-formulation dependency in the entire primal is `retime`, and all it does
is route vessels over transfers whose times are already committed.

Which is exactly what the guided constructor's tour consolidation does, and that already lands
within 27 to 62 units of re-timing's water cost on the three cells measured. So the route can be
made admissible by substitution rather than by reinvention:

    master IP -> our chaining model -> OUR tour consolidation -> verifier3

No predecessor model anywhere, and it keeps the chaining model's street, which is where the guided
constructor loses 384 to 1249.

WHAT IT CANNOT FIX. The chaining model carries no vessel capacity, so it can still emit a street no
vessel schedule can supply -- that is what killed C204 and C205. Our stage detects that explicitly
instead of discovering it inside a foreign solver, which improves the diagnosis and not the
availability. Those cells may still fail, and the guided constructor stays the answer there.

    python analysis/tep_chain_own_water.py RC204 --size 100
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
from assemble_precluster import chain, decode
from stamp import stamped
from instance_view import VESSEL_CAPACITY
from greedy26 import TOL


def water_tours(inst, vi, hubs, ui, tload):
    """Vessel tours over committed transfers -- verifier3's C20-WSEQ and C18-WLOAD, nothing else."""
    D, CDC, tau = inst.D, inst.CDC, float(inst.tau)
    hub_of = dict(zip(vi, hubs))
    tours = []
    for c in sorted(vi, key=lambda x: ui[x]):
        best = None
        for tr in tours:
            a = tr["seq"][-1]
            if ui[c] + 1e-9 < ui[a] + tau + D[hub_of[a]][hub_of[c]]:
                continue
            if tr["load"] + tload[c] > VESSEL_CAPACITY + TOL:
                continue
            add = D[hub_of[a]][hub_of[c]]
            if best is None or add < best[1]:
                best = (tr, add)
        if best is None:
            tours.append(dict(seq=[c], load=tload[c]))
        else:
            best[0]["seq"].append(c); best[0]["load"] += tload[c]
    yij = []
    for tr in tours:
        prev = CDC
        for c in tr["seq"]:
            yij.append([prev, c]); prev = c
        yij.append([prev, CDC])
    return yij, len(tours), hub_of


def objective(inst, sol, hub_of):
    D, CDC = inst.D, inst.CDC
    tset = set(sol["vi"])
    street = sum((D[i][hub_of[i]] + D[hub_of[i]][j]) if i in tset else D[i][j]
                 for i, j in ((int(a), int(b)) for a, b in sol["xij"]))
    water = 0.0
    for a, b in sol["yij"]:
        a, b = int(a), int(b)
        p = CDC if a == CDC else hub_of[a]
        q = CDC if b == CDC else hub_of[b]
        water += D[p][q]
    return (sol["nCars"] * float(inst.penalty_cars) + sol["nVessel"] * float(inst.penalty_vessels)
            + float(inst.travelcoststreet) * street + float(inst.travelcostwater) * water)


def admissible_solution(inst, trips, cap=120.0, work=None, water_surrogate=None, seed=0):
    """master IP trips -> OUR chaining -> OUR tour consolidation -> a solution dict. No K model.

    Extracted 2026-09-28 so that `tep_cg_bound.master_ip` can call the SAME code path this script
    already runs, instead of `decode` + `assemble_precluster.retime`. retime solves K's joint model
    (build_joint_model at assemble_precluster.py:179), so every master_ip result to date passed
    through the predecessors' formulation -- which d451 had reported as replaced, and which was
    replaced only here and never in master_ip.

    Returns (sol, info) or (None, info) if the chaining model is infeasible or the depot window
    is violated. `info` always carries `why` so a caller can report the failure rather than a None.
    """
    res = chain(inst, trips, cap=cap, work=work, seed=seed, water_surrogate=water_surrogate)
    if res is None:
        return None, dict(why="our chaining model INFEASIBLE", stage="chain")
    cand = decode(trips, res, depot=inst.depot)
    nd = inst.nodes
    ui = {trips[r][-1]: res["u"][r] for ch in res["chains"] for r in ch}
    tload = {trips[r][-1]: sum(float(nd[c].demand) for c in trips[r]) for ch in res["chains"] for r in ch}
    yij, nves, hub_of = water_tours(inst, cand["vi"], cand["hubs"], ui, tload)
    if cand["vi"]:
        from tep_water_opt import optimal_tours
        ex = optimal_tours(inst, [int(x) for x in cand["vi"]], hub_of, ui, tload, cap=120.0, work=60.0)
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
        return None, dict(why="depot return window violated (%.1f)" % h0, stage="depot")
    H[0] = h0
    sol = dict(xij=[list(map(int, x)) for x in cand["xij"]], vi=[int(x) for x in cand["vi"]],
               hubs=[int(x) for x in cand["hubs"]], yij=yij, nCars=int(cand["nCars"]), nVessel=nves,
               hi={str(k): float(v) for k, v in H.items()},
               ui={str(k): float(v) for k, v in ui.items()})
    sol["objVal"] = objective(inst, sol, hub_of)
    return sol, dict(why="ok", stage="done", cars=res["cars"], street=res["street"],
                     gurobi_status=res["gurobi"]["status"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--cap", type=float, default=300.0); ap.add_argument("--work", type=float, default=120.0)
    ap.add_argument("--primal-round", action="store_true",
                    help="take the selection from the CEIL-rounded master (..._ip_primal.json) and bank "
                         "to ownwater_ceil_*, leaving the floor route's artifact untouched. Ceil rounding "
                         "is a RESTRICTION whose integer solutions are timeable (d414); it was adopted at "
                         "n10 and n20 and rejected at n100 (P5), and was never tested at n30.")
    ap.add_argument("--delta", type=float, default=None,
                    help="take the selection from a master run at this bucket width (..._d<N>_ip.json) "
                         "and bank under runs/postpass/d<N>/. Finer buckets tightened the proven bound "
                         "3.4-3.5 percent on three n30 cells at d=10 (2026-09-26); this is the primal side.")
    ap.add_argument("--water-surrogate", type=float, default=None,
                    help="price hub choice INSIDE chain() by travelcostwater x CDC round trip / this many "
                         "transfers per tour (the n30 median is 4.7). The only untested form of street-water "
                         "co-optimisation; banks under runs/postpass/wsur/. Off by default.")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    dsuf = ("_d%d" % int(round(a.delta))) if a.delta else ""
    src = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s%s_ip%s.json"
                       % (a.cell, "" if a.size == 100 else "_n%d" % a.size, dsuf,
                          "_primal" if a.primal_round else ""))
    if not os.path.exists(src):
        print("  no selection at %s -- run tep_cg_bound.py %s --size %d --ip%s first"
              % (os.path.relpath(src, ROOT), a.cell, a.size, " --primal-round" if a.primal_round else ""))
        return 1
    trips = [list(t) for t in json.load(io.open(src, encoding="utf-8"))["ip"]["trips"]]
    print("%s n%d: %d trips from the master IP" % (a.cell, a.size, len(trips)), flush=True)

    t0 = time.time()
    res = chain(inst, trips, cap=a.cap, work=a.work, water_surrogate=a.water_surrogate)
    if res is None:
        print("  our chaining model: INFEASIBLE in %.0f s" % (time.time() - t0)); return 1
    print("  our chaining model: %d cars, street %.1f (status %s, %.0f s)"
          % (res["cars"], res["street"], res["gurobi"]["status"], time.time() - t0), flush=True)

    cand = decode(trips, res, depot=inst.depot)
    nd = inst.nodes
    ui = {trips[r][-1]: res["u"][r] for ch in res["chains"] for r in ch}
    tload = {trips[r][-1]: sum(float(nd[c].demand) for c in trips[r]) for ch in res["chains"] for r in ch}
    yij, nves, hub_of = water_tours(inst, cand["vi"], cand["hubs"], ui, tload)
    # d463: the exact capacitated path cover replaces greedy insertion at the SOURCE, so every
    # banked solution carries it without a separate post-pass. Greedy remains the fallback if the
    # cover finds nothing inside its budget.
    if cand["vi"]:
        from tep_water_opt import optimal_tours
        ex = optimal_tours(inst, [int(x) for x in cand["vi"]], hub_of, ui, tload, cap=120.0, work=60.0)
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
        print("  depot return window violated (%.1f) -- no solution" % h0); return 1
    H[0] = h0

    sol = dict(xij=[list(map(int, x)) for x in cand["xij"]], vi=[int(x) for x in cand["vi"]],
               hubs=[int(x) for x in cand["hubs"]], yij=yij, nCars=int(cand["nCars"]), nVessel=nves,
               hi={str(k): float(v) for k, v in H.items()},
               ui={str(k): float(v) for k, v in ui.items()})
    sol["objVal"] = objective(inst, sol, hub_of)
    run = V.verify_solution(inst, sol, cell=a.cell, size=a.size, proximity=prox, label="chain_own_water")
    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
    ok = (not bad) and (not run.blocking)
    print("  our water stage: %d vessel tour(s) | obj %.3f, %d cars | verifier3 %s"
          % (nves, sol["objVal"], sol["nCars"], "PASS" if ok else "FAIL"), flush=True)
    for f in (bad or [])[:3]:
        print("      %s %s" % (f.severity, f.cls))
    for tag, p in (("chaining + K re-timing", "runs/postpass/ipchain_%s_n%d.json" % (a.cell, a.size)),
                   ("guided constructor", "runs/postpass/guided_%s_n%d.json" % (a.cell, a.size))):
        if os.path.exists(p):
            d = json.load(io.open(p, encoding="utf-8"))
            print("    vs %-24s %9.3f (%d cars, %d vessels)   %+.2f%%"
                  % (tag, d["objVal"], d["nCars"], d["nVessel"], 100.0 * (sol["objVal"] / d["objVal"] - 1)))
    if ok:
        sol["size"] = a.size; sol["_proximity"] = prox; sol["_verified"] = True
        # d462: the primal never stamped its own wall, so the runtime envelope (d245/d246/d250)
        # could not be verified from artifacts -- only the LB leg carried `secs`. Record both the
        # chaining wall and the stage total so LB + primal is reconstructible per cell.
        sol["secs"] = round(time.time() - t0, 1)
        sol["chain_secs"] = round(float(res.get("secs", 0.0)), 1)
        sol["chain_work"] = res.get("gurobi", {}).get("work_used")
        sol["rounding"] = "ceil" if a.primal_round else "floor"
        # The ceil route banks into its OWN directory. A sibling name such as
        # ownwater_ceil_C203_n30.json would be read by tep_n30_table.py, which takes the cell as
        # basename.split("_")[1], as a cell literally called "ceil" -- the silent cell-name defect
        # CLAUDE.md section 4 records. A subdirectory cannot be reached by those globs at all.
        parts = []
        if a.water_surrogate:
            parts.append("wsur")                  # isolated dir: the table globs cannot reach it
        if a.delta:
            parts.append("d%d" % int(round(a.delta)))
        if a.primal_round:
            parts.append("ceil")
        sub = os.path.join(ROOT, "runs", "postpass", *parts) if parts else os.path.join(ROOT, "runs", "postpass")
        if parts and not os.path.isdir(sub):
            os.makedirs(sub)
        dst = os.path.join(sub, "ownwater_%s_n%d.json" % (a.cell, a.size))
        json.dump(stamped(sol, "analysis/tep_chain_own_water.py", "analysis/assemble_precluster.py"),
                  io.open(dst, "w", encoding="utf-8"), indent=1, default=str)
        print("  banked %s" % os.path.relpath(dst, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
