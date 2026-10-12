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

"""
check_cuts.py -- guard: do any of our verified feasible incumbents VIOLATE the
problem-aware valid inequalities from mfree_cuts.add_rcc?

An invalid "valid" cut silently pushes the bound ABOVE the true optimum. Every
cut must hold for every feasible solution. We test against fixopt incumbents
(re-run briefly, independently verified) on the FULL customer set (the cut logic
is not H-specific).

Cuts checked (over customer set S = all customers):
  (1) sum_i vi[i] >= ceil(demand(S)/Q_car)          -- trip count
  (2) nofCars >= ceil(work_lb / horizon)            -- time route count
  (3) vi[i] == 1  for i with no time-feasible in-trip successor
  (5) nofCars >= |time-incompatibility clique|
"""
from __future__ import annotations
import argparse, math, sys, time, random
import numpy as np
sys.path.insert(0, ".")
from build_instance import build
from solver.config import InstanceSpec
from solver.problem import SolverProblem
from solver.engines.fixopt import FixOptPrimal
from analysis.ledger import emit as _emit


def cut_bounds(p, S):
    """the RHS values the cuts assert, computed from instance data only."""
    D, nd, Q, TD = p.DistMatrix, p.nodes, p.CarCapacity, p.TransferDuration
    demS = sum(nd[c].demand for c in S)
    trips_lb = math.ceil(demS / Q)
    horizon = nd[0].latest - nd[0].earliest
    svc = sum(nd[c].serviceTime for c in S)
    nodes = [0] + list(S)
    dmin = sum(min(D[a][b] for b in nodes if b != a) for a in nodes)
    work_lb = svc + dmin / 2.0 + trips_lb * TD
    routes_lb_time = max(1, math.ceil(work_lb / horizon))
    # incompatibility clique
    Sl = list(S)
    incomp = {c: set() for c in Sl}
    for a in range(len(Sl)):
        for b in range(a + 1, len(Sl)):
            i, j = Sl[a], Sl[b]
            ij = nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest
            ji = nd[j].earliest + nd[j].serviceTime + D[j][i] <= nd[i].latest
            if not ij and not ji:
                incomp[i].add(j); incomp[j].add(i)
    clique = []
    for c in sorted(Sl, key=lambda c: -len(incomp[c])):
        if all(c in incomp[q] for q in clique):
            clique.append(c)
    # forced-transfer customers
    forced = [i for i in Sl if not any(
        nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest
        for j in Sl if j != i)]
    return dict(trips_lb=trips_lb, routes_lb_time=routes_lb_time,
                clique=len(clique), forced=forced)


def check_cell(cell, size, budget):
    spec = InstanceSpec(cell, size)
    prob = SolverProblem(spec)
    p = prob._p
    S = list(p.customers)
    cb = cut_bounds(p, S)

    rng = random.Random(0)
    eng = FixOptPrimal(iter_tl=20.0, threads=2, route_segment=True)
    s0 = eng.construct(prob, rng)
    vd0 = prob.verify(s0)
    s0["objVal"] = vd0.recomputed_obj
    best, bestvd = s0, vd0
    t0 = time.time()
    for better in eng.improve(prob, s0, rng, t0 + budget):
        vb = prob.verify(better)
        if vb.ok:
            best, bestvd = better, vb

    n_vi = len(best.get("vi", []))
    n_cars = best.get("nCars") or best.get("nofCars") or 0
    vi_set = set(best.get("vi", []))

    viol = []
    if n_vi < cb["trips_lb"]:
        viol.append(f"(1) sum vi = {n_vi} < ceil(dem/Q) = {cb['trips_lb']}")
    if n_cars < cb["routes_lb_time"]:
        viol.append(f"(2) nofCars = {n_cars} < time route LB = {cb['routes_lb_time']}")
    if n_cars < cb["clique"]:
        viol.append(f"(5) nofCars = {n_cars} < clique = {cb['clique']}")
    miss = [i for i in cb["forced"] if i not in vi_set]
    if miss:
        viol.append(f"(3) forced-transfer customers not transferred: {miss}")

    ok = bestvd.ok and not viol
    _emit("check_cuts", cell, size,
          config=dict(budget_s=budget),
          metrics=dict(obj=round(bestvd.recomputed_obj, 2), n_vi=n_vi, n_cars=n_cars,
                       trips_lb=cb["trips_lb"], time_routes=cb["routes_lb_time"],
                       clique=cb["clique"], n_forced=len(cb["forced"]),
                       violations=len(viol), holds=ok),
          wall_s=budget, verified=bool(bestvd.ok),
          notes="; ".join(viol) if viol else "all cuts hold")
    print(f"{cell:6} obj={bestvd.recomputed_obj:8.1f} verify={bestvd.ok}  "
          f"vi={n_vi} cars={n_cars}  | trips_lb={cb['trips_lb']} "
          f"time_routes={cb['routes_lb_time']} clique={cb['clique']} "
          f"forced={len(cb['forced'])}  -> {'OK' if ok else 'VIOLATION: ' + '; '.join(viol)}",
          flush=True)
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C203,C204,R203,R207,RC203,RC208")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--budget", type=int, default=150)
    a = ap.parse_args()
    print("=== cut-validity check: do verified incumbents violate the cuts? ===", flush=True)
    allok = True
    for c in a.cells.split(","):
        try:
            allok &= check_cell(c.strip(), a.size, a.budget)
        except Exception as ex:
            print(f"{c}: ERROR {ex}", flush=True); allok = False
    print(f"\n{'ALL CUTS HOLD on every tested incumbent' if allok else '>>> CUT VIOLATION FOUND -- do not adopt'}",
          flush=True)
