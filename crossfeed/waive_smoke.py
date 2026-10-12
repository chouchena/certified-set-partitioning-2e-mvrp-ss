"""
waive_smoke.py -- smoke test of the "waive E" primal/dual idea.

From the easy-reduction frontier we have, for a chosen k:
  * E   = the k easiest customers (dropped)
  * H   = C \ E
  * a PROVEN-optimal block-A routing over H  (street echelon only)

Test: build the JOINT model but require only H to be served (E waived --
covering constraints for E simply absent), warm-start its street side from
the block-A(H) routes, and solve.

Two quantities come out:
  incumbent  = cost of a feasible "serve H" joint solution
               -> a real UPPER bound for the partial-coverage primal
  dual bound = CPLEX best bound on the E-waived joint
               -> waiving E is a RELAXATION of z_joint (feasible region
                  grows), so  dual_bound <= z_joint(serve H) <= z_joint
               -> a VALID lower bound on the full z_joint

Question the smoke answers: does the E-waived joint's dual bound beat our
block_relax = z_A(H)* + w ?  (It keeps the real water echelon + real
synchronization for H, which block-A drops -- but it also carries the full
big-M timing, so it may climb slowly.)
"""
from __future__ import annotations
import argparse, copy, sys, time
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
from joint_model_cplex import build_joint_model


def run(name, size, k, *, tl_blockA=250, tl_joint=900, workers=8):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl_joint)
    s, w, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, w)
    order = sorted(_e, key=lambda c: -_e[c])
    E = set(order[:k])
    H = [c for c in p.customers if c not in E]
    wlb = water_lb_scaled(p)[0] / SCALE
    print(f"\n=== {name}/{size}  WAIVE-E SMOKE  k={k} ===", flush=True)
    print(f"E (waived, {len(E)}): {sorted(E)}", flush=True)
    print(f"H (served, {len(H)}): {sorted(H)}", flush=True)
    print(f"water LB (full demand) w = {wlb:.2f}", flush=True)

    # 1. block-A(H) -> proven routes
    ba = BlockA(p, integral=True, timing_mode="bigM", drop=E)
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    t0 = time.time()
    r = ba.solve(time_limit=tl_blockA, track_progress=False)
    zA = r["value"]
    br = (zA + wlb) if zA is not None else None
    print(f"\n[1] block-A(H): zA(H)={zA}  proven={r['proven']}  {time.time()-t0:.0f}s"
          f"   block_relax = zA + w = {br:.2f}" if br else "", flush=True)
    xsol = r.get("xij_sol") or {}

    # 2. E-waived joint model (serve H only, full water echelon + sync)
    p2 = copy.copy(p)
    p2.customers = tuple(H)
    JH = build_joint_model(p2)
    jm = JH.m
    try:
        jm.parameters.threads = workers
    except Exception:
        pass
    print(f"[2] E-waived joint: {jm.number_of_variables} vars  "
          f"{jm.number_of_constraints} cons", flush=True)

    # 3. warm-start street arcs from block-A(H)
    seeded = 0
    try:
        ws = jm.new_solution()
        for (i, j), xv in JH.xij.items():
            if (i, j) in xsol:
                ws.add_var_value(xv, int(round(xsol[(i, j)])))
                seeded += 1
        jm.add_mip_start(ws, effort_level=4)
        print(f"[3] warm start: {seeded} street arcs seeded (water left free)", flush=True)
    except Exception as ex:
        print(f"[3] warm start FAILED: {ex}", flush=True)

    # 4. solve
    jm.parameters.timelimit = tl_joint
    t0 = time.time()
    sol = jm.solve()
    det = jm.solve_details
    st = det.status if det else "none"
    inc = round(sol.objective_value, 2) if sol else None
    db = getattr(det, "best_bound", None)
    gap = det.mip_relative_gap if det else None
    print(f"\n[4] E-WAIVED JOINT SOLVE  ({time.time()-t0:.0f}s)", flush=True)
    print(f"    status              : {st}", flush=True)
    print(f"    incumbent (serve-H)  : {inc}      <- UB for partial coverage", flush=True)
    print(f"    dual bound           : {round(db,2) if db is not None else None}"
          f"      <- VALID LB on z_joint", flush=True)
    print(f"    mip gap              : {round(gap,3) if gap is not None else None}", flush=True)
    print(f"\n[compare]  block_relax LB (zA(H)*+w) = {br:.2f}" if br else "", flush=True)
    if br and db:
        print(f"           E-waived dual bound      = {db:.2f}   "
              f"({'BETTER' if db > br else 'worse'} by {db-br:+.2f})", flush=True)
    return {"name": name, "k": k, "zA_H": zA, "block_relax": br,
            "waived_incumbent": inc, "waived_dualbound": db, "status": st}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="C203")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--k", type=int, required=True, help="frontier k for this cell")
    ap.add_argument("--tl-blocka", type=int, default=250)
    ap.add_argument("--tl-joint", type=int, default=900)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    run(a.cell, a.size, a.k, tl_blockA=a.tl_blocka, tl_joint=a.tl_joint, workers=a.workers)
