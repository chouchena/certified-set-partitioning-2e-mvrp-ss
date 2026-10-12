"""
blockA_cpsat.py — CP-SAT (OR-Tools) model of block A (street + synchronisation),
built as a VALID LOWER BOUND on z_A via floored integer costs.

The diagnostic question: block A's CPLEX B&B plateaus at ~46 % of its
incumbent on the wide-TW |C|=20 cells (C203 bound 286.5 vs incumbent ~615).
Is that a big-M artifact? CP-SAT has NO big-M — timing implications are
half-reified (`OnlyEnforceIf`), routing is `AddMultipleCircuit`. If CP-SAT
closes far more of block A's own gap, the reported exact-intractability is
a formulation artifact (-> the reframing contribution). If CP-SAT also
plateaus low, big-M is not the whole story.

Validity: every distance is floored after scaling by SCALE, so each cost
term under-estimates the true one; CP-SAT's optimum / SCALE is a valid
lower bound on block A's true FleetStreet+TravelStreet, hence on z_A.
Adding Karademir's (also floored) water LB gives a valid block-relaxation
bound.

NOT integrated into dual_bound_harness (different engine, different model
shape). Standalone probe; fold in if it pans out.
"""
from __future__ import annotations
import argparse
import math
import sys
import time

sys.path.insert(0, ".")
from ortools.sat.python import cp_model
from build_instance import build
from runlog import RunLogger

SCALE = 1000  # times/distances -> milli-units; floored for a valid LB


def water_lb_scaled(p):
    D, CDC = p.DistMatrix, p.CDC
    L = math.ceil(sum(p.nodes[c].demand for c in p.customers) / p.VesselCapacity)
    minTr = min(2 * D[CDC][s] for s in p.satellites)
    w = p.travelcostwater * minTr * L + L * p.penaltyVessels
    return math.floor(SCALE * w), L


class _Progress(cp_model.CpSolverSolutionCallback):
    def __init__(self, lg, t0):
        super().__init__()
        self.lg, self.t0 = lg, t0
        self.trace = []

    def on_solution_callback(self):
        t = round(time.time() - self.t0, 1)
        obj = self.ObjectiveValue() / SCALE
        bb = self.BestObjectiveBound() / SCALE
        self.trace.append((t, bb, obj))
        if self.lg:
            self.lg.bound(round(bb, 3), trigger="cpsat_progress",
                          extra={"t": t, "incumbent": round(obj, 3)})


def solve_blockA_cpsat(name, size, *, time_limit=1200, workers=4, log=True, drop=None):
    """`drop`: a set of customer node ids to REMOVE from block A (the
    'easy customer' reduction). z_A(H)* + w(total demand) is still a valid
    LB on z_joint (subset relaxation + Karademir water LB). The water LB
    ALWAYS uses the full demand (via `p.customers`), not H's."""
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=time_limit)
    D, nd = p.DistMatrix, p.nodes
    drop = set(drop or [])
    C_all = list(p.customers)
    C = [c for c in C_all if c not in drop]
    S = list(p.satellites); CDC = p.CDC
    TD = int(p.TransferDuration)
    SetCd = [0] + C
    _alln = range(len(D))
    di = {(i, j): math.floor(SCALE * D[i][j]) for i in _alln for j in _alln if i != j}

    lg = (RunLogger(f"blockA_cpsat_{name}_n{size}" + (f"_drop{len(drop)}" if drop else ""),
                    instance=name, size=size,
                    config={"engine": "blockA_cpsat", "scale": SCALE, "time_limit": time_limit,
                            "wls": 0.1, "tau": "formula", "proximity": 0.0,
                            "n_dropped": len(drop), "dropped": sorted(drop)})
          if log else None)
    if lg:
        lg.phase("build")

    m = cp_model.CpModel()

    arcs = [(i, j) for i in SetCd for j in SetCd if i != j
            and nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest]
    x = {(i, j): m.NewBoolVar(f"x_{i}_{j}") for (i, j) in arcs}
    v = {i: m.NewBoolVar(f"v_{i}") for i in C}
    vip = {(i, pp): m.NewBoolVar(f"vip_{i}_{pp}") for i in C for pp in S}
    nofCars = m.NewIntVar(1, len(C), "nofCars")

    h = {i: m.NewIntVar(SCALE * int(nd[i].earliest), SCALE * int(nd[i].latest), f"h_{i}") for i in SetCd}
    mload = {i: m.NewIntVar(int(nd[i].demand), int(p.CarCapacity), f"m_{i}") for i in C}
    u = {i: m.NewIntVar(SCALE * int(nd[CDC].earliest), SCALE * int(nd[CDC].latest), f"u_{i}") for i in C}
    ac = {(i, j): m.NewIntVar(0, 10 * SCALE * int(max(D[a][b] for a in SetCd + S for b in SetCd + S if a != b)),
                              f"ac_{i}_{j}") for (i, j) in arcs}

    # ---- routing: multi-vehicle circuit through the depot ----
    # AddMultipleCircuit needs contiguous 0..n-1 node ids; when customers are
    # dropped SetCd is sparse, so remap for this constraint only (x stays
    # keyed by original ids).
    _rm = {orig: new for new, orig in enumerate(SetCd)}
    m.AddMultipleCircuit([(_rm[i], _rm[j], x[i, j]) for (i, j) in arcs])
    m.Add(nofCars == sum(x[0, j] for j in C if (0, j) in x))
    for i in C:                                   # Const4
        if (i, 0) in x:
            m.Add(v[i] >= x[i, 0])
    for i in C:                                   # Const12
        m.Add(sum(vip[i, pp] for pp in S) == v[i])

    # ---- load flow (Const5) ----
    for (i, j) in arcs:
        if i in C and j in C:
            m.Add(mload[j] >= mload[i] + int(nd[j].demand)).OnlyEnforceIf([x[i, j], v[i].Not()])

    # ---- time windows (Const7) ----
    for i in C:
        m.Add(h[i] >= SCALE * int(nd[0].earliest) + di[0, i])
        m.Add(h[i] <= SCALE * (int(nd[0].latest) - int(nd[i].serviceTime) - TD) - di[i, 0])

    # ---- street timing (Const8/Const14) -- NO big-M, half-reified ----
    # matches the joint model: Const8 is looped `for i in Customers` only, so
    # depot-departure arcs (0,j) carry NO timing link -- h[0] is just a
    # return-time ceiling (via the (i,0) arcs below). Const7's lower bound
    # `h[i] >= earliest_0 + t_0i` is the only depot-departure timing.
    for (i, j) in arcs:
        if i == 0:
            continue
        si = SCALE * int(nd[i].serviceTime)
        m.Add(h[j] >= h[i] + si + di[i, j]).OnlyEnforceIf([x[i, j], v[i].Not()])
        for pp in S:
            m.Add(h[j] >= h[i] + si + SCALE * TD + di[i, pp] + di[pp, j]).OnlyEnforceIf([x[i, j], vip[i, pp]])

    # ---- synchronisation (Const13/Const15) ----
    for i in C:
        si = SCALE * int(nd[i].serviceTime)
        m.Add(u[i] >= h[i] + si + sum(di[i, pp] * vip[i, pp] for pp in S))
        m.Add(u[i] >= SCALE * int(nd[CDC].earliest) + sum(di[CDC, pp] * vip[i, pp] for pp in S))
        m.Add(u[i] + sum((SCALE * TD + di[pp, CDC]) * vip[i, pp] for pp in S) <= SCALE * int(nd[CDC].latest))

    # ---- arc cost (floored -> under-estimate) ----
    for (i, j) in arcs:
        m.Add(ac[i, j] >= di[i, j]).OnlyEnforceIf(x[i, j])
        m.Add(ac[i, j] == 0).OnlyEnforceIf(x[i, j].Not())
        if i in C:
            for pp in S:
                m.Add(ac[i, j] >= di[i, pp] + di[pp, j]).OnlyEnforceIf([x[i, j], vip[i, pp]])

    pen_car = math.floor(SCALE * p.penaltyCars)
    tcs = p.travelcoststreet  # == 1 for our config
    obj = pen_car * nofCars + int(round(tcs)) * sum(ac[i, j] for (i, j) in arcs)
    m.Minimize(obj)

    if lg:
        lg.phase("cpsat_solve")
        lg.event(None, trigger="model_size",
                 extra={"n_arcs": len(arcs), "n_bool": len(x) + len(v) + len(vip),
                        "n_int": len(h) + len(mload) + len(u) + len(ac) + 1})

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.log_search_progress = False
    t0 = time.time()
    cb = _Progress(lg, t0)
    status = solver.Solve(m, cb)
    wall = round(time.time() - t0, 1)

    sname = solver.StatusName(status)
    proven = status == cp_model.OPTIMAL
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    zA_lb = solver.BestObjectiveBound() / SCALE          # valid LB on z_A (always)
    zA_inc = solver.ObjectiveValue() / SCALE if feasible else None
    wlb, L = water_lb_scaled(p)
    block_relax = zA_lb + wlb / SCALE

    demH = sum(nd[c].demand for c in C)
    demAll = sum(nd[c].demand for c in C_all)
    res = {"cell": f"{name}/{size}", "status": sname, "proven": proven,
           "blockA_lb": round(zA_lb, 2), "blockA_incumbent": round(zA_inc, 2) if zA_inc else None,
           "internal_gap_pct": (round(100 * (zA_inc - zA_lb) / zA_inc, 1) if zA_inc else None),
           "water_lb": round(wlb / SCALE, 2), "block_relax_bound": round(block_relax, 2),
           "wall_s": wall, "n_solutions": len(cb.trace),
           "n_dropped": len(drop), "n_customers_H": len(C),
           "car_lb_H": math.ceil(demH / p.CarCapacity), "car_lb_all": math.ceil(demAll / p.CarCapacity),
           "vessel_lb_H": math.ceil(demH / p.VesselCapacity), "vessel_lb_all": L,
           "curve": {f"t{int(t)}": round(bb, 1) for (t, bb, _) in cb.trace}}
    if lg:
        lg.close(status=sname, run_valid=True, verified=proven,
                 final_incumbent=zA_inc, final_bound=zA_lb)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C203,C204,RC203,R205")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=float, default=1200)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    # Karademir |C|=20 published (BK, gap%) -> Gurobi bound = BK*(1-gap/100)
    # from paper/paper-reference-data.md
    K = {"C201": (697.7, 0), "C202": (678.7, 22), "C203": (682.7, 54), "C204": (683.5, 57),
         "C205": (685.2, 0), "C206": (680.8, 0), "C207": (681.8, 23), "C208": (678.1, 0),
         "R201": (821.7, 0), "R202": (757.0, 19), "R203": (638.4, 37), "R204": (605.7, 42),
         "R205": (642.2, 0), "R206": (612.9, 31), "R207": (601.7, 36), "R208": (549.9, 37),
         "R209": (626.3, 6), "R210": (647.1, 11), "R211": (669.1, 48),
         "RC201": (981.2, 0), "RC202": (906.4, 44), "RC203": (754.3, 56), "RC204": (642.4, 50),
         "RC205": (935.5, 15), "RC206": (885.2, 28), "RC207": (885.0, 26), "RC208": (881.6, 65)}
    print(f"{'cell':>10} {'status':>12} {'blkA_LB':>9} {'blkA_inc':>9} {'intgap%':>8} "
          f"{'blkRelax':>9} {'K_bound':>8} {'xK':>5} {'wall':>7}", flush=True)
    rows = []
    for nm in [c.strip() for c in a.cells.split(",")]:
        r = solve_blockA_cpsat(nm, a.size, time_limit=a.tl, workers=a.workers)
        bk, g = K.get(nm, (None, None))
        kb = round(bk * (1 - g / 100), 1) if bk is not None else None
        xk = round(r["block_relax_bound"] / kb, 2) if kb else None
        rows.append({**r, "k_bound": kb, "xK": xk})
        print(f"{r['cell']:>10} {r['status']:>12} {r['blockA_lb']:>9} "
              f"{str(r['blockA_incumbent']):>9} {str(r['internal_gap_pct']):>8} "
              f"{r['block_relax_bound']:>9} {str(kb):>8} {str(xk):>5} {r['wall_s']:>7}", flush=True)
        print(f"           curve: {r['curve']}", flush=True)
        import json
        json.dump(rows, open("crossfeed/blockA_cpsat_results.json", "w"), indent=2, default=str)

    print("\n=== read ===")
    for r in rows:
        if r["proven"]:
            print(f"  {r['cell']}: PROVEN blkA={r['blockA_lb']} -> block-relax {r['block_relax_bound']} "
                  f"({r['xK']}x Karademir bound)")
        else:
            print(f"  {r['cell']}: {r['status']} blkA_LB={r['blockA_lb']} inc={r['blockA_incumbent']} "
                  f"(internal gap {r['internal_gap_pct']}%) -> block-relax {r['block_relax_bound']} ({r['xK']}x)")
