# ===================== RED FLAG -- TEP USE ONLY (2026-09-28) =====================
# This file REACHES K's FORMULATION (solver/engines/fixopt.py -> build_joint_model ->
# integratedJointModel). The standing constraint is that K's formulation is never part
# of our solution (d449, d451), and the fixopt-based work was archived and locked under
# archive/fixopt_locked/ on 2026-09-28.
#
# THIS FILE WAS NOT ARCHIVED because the admissible TEP path still depends on it.
# It is permitted ONLY where that dependency already exists. It must not be imported by
# new work, and no result derived from it may be reported without saying so.
#
# The load-bearing case: tep_cg_bound.master_ip calls assemble_precluster.retime, which
# builds K's joint model. So every master_ip result passes through K's formulation --
# which contradicts d451's claim that retime was replaced. Unresolved; see
# archive/fixopt_locked/LOCK.md.
# =================================================================================

"""ASSEMBLY TEST: pre-clustered trips (PRIO-ST / TIME-SLICE) -> Gurobi chaining (cars, times,
satellite booking, vessel-arrival bound) -> joint sub-MILP with xij/vi/vip fixed and the water
side free -> verifier3. The chaining probe's pipeline with the trip set swapped. Thread-light:
Gurobi 1 thread (cap 120 s), CPLEX 1 thread (cap 240 s).

Hubs: the pre-clustering ends each trip at the nearest satellite to its last customer; here the
hub is also let free among the 4 satellites inside the chaining model (a binary per trip x hub),
since the joint re-timing fixes vip. Vessel capacity and sequencing are NOT modelled in step 1
(only the arrival bound); step 2 decides them.
"""
import io
import json
import os
import sys
import time

import gurobipy as gp
from gurobipy import GRB

ROOT = r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)
import verifier3 as V
from build_instance import build
from precluster_trips import Ctx, prio_st, time_slice, full_pack

# K'S FORMULATION IS IMPORTED LAZILY, INSIDE retime() ALONE. (2026-09-28)
#
# `chain` and `decode` in this module are OURS -- chain builds its own Gurobi model with hub
# choice, car chains, transfer times, tau-spacing and both returns (d451). `retime` is the only
# function here that touches the predecessors' model. While `from joint_model_cplex import ...`
# sat at module scope, merely importing this module to use `chain` loaded K's formulation, so
# "the chaining route is K-free" was true of the call path and false of the import graph. It is
# now true of both: nothing below imports joint_model_cplex or fixopt until retime is called.


def chain(inst, trips, cap=120.0, work=None, seed=0, max_cars=None, water_surrogate=None):
    nd, D, tau, depot, CDC = inst.nodes, inst.D, float(inst.tau), inst.depot, inst.CDC
    sats = list(inst.satellites)
    H0, H1 = float(nd[depot].earliest), float(nd[depot].latest)
    pen, tc = float(inst.penalty_cars), float(inst.travelcoststreet)
    R = range(len(trips))
    M = (H1 - H0) + max(max(row) for row in D)
    m = gp.Model("assemble"); m.Params.OutputFlag = 0; m.Params.Threads = 1; m.Params.TimeLimit = cap; m.Params.Seed = int(seed)
    if work:
        m.Params.WorkLimit = float(work)      # deterministic primary stop; TimeLimit stays the safety cap
    a = {c: m.addVar(lb=float(nd[c].earliest), ub=float(nd[c].latest)) for t in trips for c in t}
    u = {r: m.addVar(lb=H0, ub=H1) for r in R}
    s = {r: m.addVar(lb=H0, ub=H1) for r in R}
    h = {(r, p): m.addVar(vtype=GRB.BINARY) for r in R for p in sats}
    y = {(r, q): m.addVar(vtype=GRB.BINARY) for r in R for q in R if r != q}
    yd = {r: m.addVar(vtype=GRB.BINARY) for r in R}
    ye = {r: m.addVar(vtype=GRB.BINARY) for r in R}
    # leg from hub of r to first customer of q: linearise y[r,q]*h[r,p] with z
    z = {(r, q, p): m.addVar(vtype=GRB.BINARY) for (r, q) in y for p in sats}
    for (r, q) in y:
        for p in sats:
            m.addConstr(z[r, q, p] <= y[r, q]); m.addConstr(z[r, q, p] <= h[r, p]); m.addConstr(z[r, q, p] >= y[r, q] + h[r, p] - 1)
    internal = {}
    for r in R:
        cs = trips[r]
        m.addConstr(gp.quicksum(h[r, p] for p in sats) == 1)
        m.addConstr(yd[r] + gp.quicksum(y[q, r] for q in R if q != r) == 1)
        m.addConstr(ye[r] + gp.quicksum(y[r, q] for q in R if q != r) == 1)
        m.addConstr(a[cs[0]] >= s[r] + yd[r] * D[depot][cs[0]] + gp.quicksum(z[q, r, p] * D[p][cs[0]] for q in R if q != r for p in sats))
        tot = 0.0
        for c1, c2 in zip(cs, cs[1:]):
            m.addConstr(a[c2] >= a[c1] + float(nd[c1].service) + D[c1][c2]); tot += D[c1][c2]
        last = cs[-1]
        m.addConstr(u[r] >= a[last] + float(nd[last].service) + gp.quicksum(h[r, p] * D[last][p] for p in sats))
        m.addConstr(u[r] >= H0 + gp.quicksum(h[r, p] * D[CDC][p] for p in sats))          # vessel arrival bound
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][depot] for p in sats) <= H1)
        # JOINT-MODEL BOUNDS the first cut lacked (joint_model_cplex.py:142 and Const15 :183):
        # every customer must still reach the depot with a transfer's worth of margin, and the
        # vessel serving the transfer must be back at the CDC by its latest.
        for c in cs:
            m.addConstr(a[c] <= H1 - D[c][depot] - float(nd[c].service) - tau)
        m.addConstr(u[r] + tau + gp.quicksum(h[r, p] * D[p][CDC] for p in sats) <= float(nd[CDC].latest))
        internal[r] = tot
        for q in R:
            if q != r:
                m.addConstr(s[q] >= u[r] + tau - M * (1 - y[r, q]))
    # booking: same hub -> tau apart
    for r in R:
        for q in R:
            if q > r:
                for p in sats:
                    o = m.addVar(vtype=GRB.BINARY)
                    both = m.addVar(vtype=GRB.BINARY)
                    m.addConstr(both >= h[r, p] + h[q, p] - 1)
                    m.addConstr(u[q] >= u[r] + tau - M * (1 - o) - M * (1 - both))
                    m.addConstr(u[r] >= u[q] + tau - M * o - M * (1 - both))
    cost = (pen * gp.quicksum(yd[r] for r in R)
            + tc * (gp.quicksum(internal[r] for r in R)
                    + gp.quicksum(h[r, p] * D[trips[r][-1]][p] for r in R for p in sats)
                    + gp.quicksum(yd[r] * D[depot][trips[r][0]] for r in R)
                    + gp.quicksum(z[r, q, p] * D[p][trips[q][0]] for (r, q, p) in z)
                    + gp.quicksum(ye[r] * gp.quicksum(h[r, p] * D[p][depot] for p in sats) for r in R)))
    if max_cars is not None:
        # d439 audit hook: cap the fleet to ask whether a partition is servable by fewer cars at
        # all, separately from whether doing so is cheaper. Default None leaves the model untouched.
        m.addConstr(gp.quicksum(yd[r] for r in R) <= int(max_cars), name="max_cars")
    if water_surrogate:
        # 2026-09-26, author asked three times whether water is co-optimised with the street. It is
        # not: every search objective is cars + street and water is solved post-hoc on committed
        # transfers. This is the CHEAPEST form of "together" -- price each trip's hub choice by a
        # share of the CDC round trip to that satellite, scaled by travelcostwater / expected
        # transfers per tour. It is a SURROGATE, not the water model; the exact stage still runs
        # after. Default None keeps the objective exactly as before. Smoke gate, fixed before any
        # run: adopted only if it beats the default on >= 2 of 3 cells by > 0.3 percent after the
        # exact water stage; d458 (hub re-pricing gains 0 on 26/27 post-hoc) predicts it will not.
        cw = float(inst.travelcostwater) / float(water_surrogate)
        cost = cost + cw * gp.quicksum(h[r, p] * (D[CDC][p] + D[p][CDC]) for r in R for p in sats)
    m.setObjective(cost, GRB.MINIMIZE)
    t0 = time.time(); m.optimize()
    if m.SolCount == 0:
        return None
    succ = {r: q for (r, q) in y if y[r, q].X > 0.5}
    chains = []
    for r in R:
        if yd[r].X > 0.5:
            ch = [r]
            while ch[-1] in succ: ch.append(succ[ch[-1]])
            chains.append(ch)
    hub = {r: next(p for p in sats if h[r, p].X > 0.5) for r in R}
    # d451: the service times are computed here and were never returned, so any consumer had
    # to re-derive them or hand the street to another solver. Returning them lets our OWN
    # water stage replace the K-model re-timing entirely.
    return dict(cars=len(chains), street=m.ObjVal, bound=m.ObjBound, secs=time.time() - t0, chains=chains, hub=hub, status=m.Status,
                a={c: a[c].X for c in a}, s={r: s[r].X for r in R},
                u={r: u[r].X for r in R}, gurobi=dict(version=".".join(map(str, gp.gurobi.version())), threads=1, seed=m.Params.Seed, time_limit=cap, work_limit=work, work_used=m.Work, status=m.Status, obj=m.ObjVal, bound=m.ObjBound, nodes=m.NodeCount, secs=time.time() - t0))


def decode(trips, res, depot=0):
    xij, vi, hubs = [], [], []
    for ch in res["chains"]:
        prev = depot
        for r in ch:
            for c in trips[r]:
                xij.append([prev, c]); prev = c
            vi.append(trips[r][-1]); hubs.append(res["hub"][r])
        xij.append([prev, depot])
    return dict(xij=xij, vi=vi, hubs=hubs, yij=[], nCars=len(res["chains"]))


def retime(cell, cand, cap=240.0, size=100, proximity=None):
    """Re-time a fixed street exactly. SIZE AND PROXIMITY ARE NOT ALWAYS 100 AND 0.1 (d439).

    They were literals here until 2026-09-25, which is correct at n100 and wrong everywhere else:
    K publish proximity 0.1 at n100 and 0.0 at n10, n20, n30 and n50, so at any smaller size this
    built a 100-customer instance at the wrong proximity and the verification that followed was
    meaningless. The defaults reproduce the old behaviour exactly, so no banked n100 result moves.
    """
    # K'S FORMULATION, IMPORTED HERE AND NOWHERE ELSE IN THIS MODULE. Moving these out of module
    # scope is what makes `chain` and `decode` importable without loading the predecessors' model
    # at all. Deleting them from module scope WITHOUT adding them here broke retime with a
    # NameError for the few minutes between the two edits -- caught by auditing the claim that the
    # import had been "made lazy", when it had only been removed. (2026-09-28)
    from joint_model_cplex import build_joint_model, _extract_solution
    import solver.engines.fixopt as FX

    from k_comparison import k_proximity
    prox = k_proximity(size) if proximity is None else float(proximity)
    p = build(cell, size, tau="formula", proximity=prox)
    # PRODUCTION ARM (d243, fixopt.py:1527-1531): post (26) and the valid big-M. Without these
    # the re-timing ignores satellite booking and the verifier rejects the result (d344).
    p.hardSingleTransfer = True
    p.validBigM = True
    H = build_joint_model(p); m = H.m
    best = FX._canonical(cand, H.Customers, H.Satellites, H.CDC)
    FX._freeze_street_only(m, H, best, H.Customers, H.Satellites, H.CDC)
    m.parameters.timelimit = cap; m.parameters.threads = 1
    t0 = time.time(); s = m.solve(log_output=False); det = m.solve_details
    if s is None:
        return None, (det.status if det else "none"), time.time() - t0
    out = _extract_solution(H); out["objVal"] = round(s.objective_value, 4)
    out["_cplex"] = dict(threads=1, time_limit=cap, status=str(det.status), secs=round(time.time() - t0, 1), det_time=getattr(det, "deterministic_time", None), best_bound=getattr(det, "best_bound", None), posts_26=True, valid_bigm=True)
    out["hi"] = {str(k): v for k, v in out["hi"].items()}; out["ui"] = {str(k): v for k, v in out["ui"].items()}
    return out, det.status, time.time() - t0


def main():
    cells = sys.argv[1].split(",") if len(sys.argv) > 1 else ["R204", "RC204", "C204"]
    which = sys.argv[2].split(",") if len(sys.argv) > 2 else ["prio", "ts"]
    print("ASSEMBLY TEST -- pre-clustered trips -> chaining (Gurobi) -> joint re-timing (CPLEX, water free) -> verifier3\n", flush=True)
    results = {}
    for cell in cells:
        inst = V.load_instance(cell, 100, 0.1); ctx = Ctx(inst)
        sol = json.load(io.open(os.path.join(ROOT, "runs", "grid", "g_%s_n100_p0.1_s0.json" % cell), encoding="utf-8"))
        print("%s incumbent obj %.1f cars %d trips %d" % (cell, sol["objVal"], sol["nCars"], len(sol["vi"])), flush=True)
        for name in which:
            trips = prio_st(ctx) if name == "prio" else (full_pack(ctx) if name == "fp" else time_slice(ctx))
            res = chain(inst, trips)
            if res is None:
                print("   %-4s %d trips: chaining found no solution" % (name, len(trips)), flush=True); continue
            print("   %-4s %d trips: chained into %d cars, street %.1f (bound %.1f, status %s, %.0fs)" % (name, len(trips), res["cars"], res["street"], res["bound"], res["status"], res["secs"]), flush=True)
            cand = decode(trips, res)
            out, status, secs = retime(cell, cand)
            if out is None:
                print("        re-timing: %s after %.0fs" % (status, secs), flush=True)
                results["%s_%s" % (cell, name)] = dict(cars=res["cars"], street=res["street"], retime=str(status)); continue
            run = V.verify_solution(inst, out, cell=cell, size=100, proximity=0.1, label=name)
            bad = [x for x in run.findings if x.severity != "TOLERANCE"]; ok = (not bad) and (not run.blocking)
            rec = run.objective.get("recomputed")
            print("        re-timing %s in %.0fs -> obj %.1f cars %d vessels %d | verifier3 %s%s | vs incumbent %+.2f%%"
                  % (status, secs, out["objVal"], out["nCars"], out["nVessel"], "PASS" if ok else "FAIL " + (bad[0].cls if bad else "blk"),
                     (" recomputed %.1f" % rec) if rec else "", 100.0 * (out["objVal"] - sol["objVal"]) / sol["objVal"]), flush=True)
            results["%s_%s" % (cell, name)] = dict(cars=out["nCars"], obj=out["objVal"], verify="PASS" if ok else "FAIL", retime=str(status), vs_pct=100.0 * (out["objVal"] - sol["objVal"]) / sol["objVal"])
            if ok:
                # bank in runs/postpass with provenance (the census and C2 read from there)
                from analysis.stamp import stamped
                out["_source"] = "analysis/assemble_precluster.py %s %s ((26) posted; pre-clustering -> Gurobi chaining 1 thread 120 s -> joint sub-MILP structure fixed, water free, CPLEX 1 thread 240 s) -> verifier3 PASS; instance %s n100 proximity 0.1; not a production-pipeline run" % (cell, name, cell)
                out["_verifier_recomputed"] = rec
                out["_params"] = dict(composition=name, MAXLEN=(5 if name == "fp" else 4), Q=50.0, CLOSE=10.0, trips=len(trips),
                                      chaining=res.get("gurobi"), chains=res.get("chains"), hub=res.get("hub"), u=res.get("u"), cplex=out.get("_cplex"))
                dst = os.path.join(ROOT, "runs", "postpass", "assembled_%s_n100_%s.json" % (cell, name))
                prev = None
                if os.path.exists(dst):
                    try: prev = json.load(io.open(dst, encoding="utf-8")).get("objVal")
                    except Exception: prev = None
                if prev is None or out["objVal"] < float(prev) - 1e-9:
                    json.dump(stamped(out, "analysis/assemble_precluster.py", "analysis/precluster_trips.py"), io.open(dst, "w", encoding="utf-8"), default=str)
                    print("        banked %s" % os.path.relpath(dst, ROOT), flush=True)
                else:
                    print("        not banked: existing %.1f <= %.1f" % (float(prev), out["objVal"]), flush=True)
        print(flush=True)
    json.dump(results, io.open(os.path.join(S, "assemble_precluster.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("wrote assemble_precluster.json")


if __name__ == "__main__":
    main()
