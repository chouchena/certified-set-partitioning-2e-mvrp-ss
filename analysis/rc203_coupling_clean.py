"""
rc203_coupling.py -- opt B: does starting the joint solve in block-A(H)'s
optimal routing basin fix RC203?

  1. solve block-A(H) for RC203's frontier (drop the 6 easiest) -> proven-optimal
     street routes over the 14-customer core
  2. cheapest-insert the 6 dropped customers into those routes
  3. warm-start the FULL joint MILP (all 20) with that street skeleton
  4. solve; report incumbent + dual bound + fleet/travel decomposition
"""
from __future__ import annotations
import sys, time, copy
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
from joint_model_cplex import build_joint_model, _extract_solution
from instance_view import VInstance
# 2026-09-20: verifier3 replaces verify2 -- it checks K's PUBLISHED (1)-(30) in original form.
from analysis.verifier3 import verify_for_engine as verify_solution

NAME, SIZE, K = "RC203", 20, 6
TL_BLOCKA, TL_JOINT, WORKERS = 700, 3000, 8


def main():
    p = build(NAME, SIZE, wls=0.1, tau="formula", proximity=0.0, time_limit=TL_JOINT)
    D = p.DistMatrix
    s, w, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, w)
    order = sorted(_e, key=lambda c: -_e[c])
    E = order[:K]
    H = [c for c in p.customers if c not in set(E)]
    wlb = water_lb_scaled(p)[0] / SCALE
    print(f"[coupling] {NAME}  E={sorted(E)}  |H|={len(H)}  wlb={wlb:.1f}", flush=True)

    ba = BlockA(p, integral=True, timing_mode="bigM", drop=set(E))
    try:
        ba.m.parameters.threads = WORKERS
    except Exception:
        pass
    t0 = time.time()
    r = ba.solve(time_limit=TL_BLOCKA, track_progress=False)
    xs = r.get("xij_sol") or {}
    print(f"[coupling] block-A(H): zA(H)*={r['value']} proven={r['proven']} "
          f"{time.time()-t0:.0f}s  block_relax={ (r['value'] or 0)+wlb:.1f}", flush=True)

    ws = dict(xs)
    for c in E:  # cheapest insertion into the H routes
        used = [(i, j) for (i, j), v in ws.items() if v == 1]
        best_arc, bd = None, 1e18
        for (i, j) in used:
            dlt = D[i][c] + D[c][j] - D[i][j]
            if dlt < bd:
                bd, best_arc = dlt, (i, j)
        if best_arc is None:
            ws[(0, c)] = 1; ws[(c, 0)] = 1
        else:
            i, j = best_arc
            ws[(i, j)] = 0; ws[(i, c)] = 1; ws[(c, j)] = 1

    JH = build_joint_model(p)  # FULL model, all 20
    jm = JH.m
    try:
        jm.parameters.threads = WORKERS
    except Exception:
        pass
    seeded = 0
    try:
        st = jm.new_solution()
        for (i, j), xv in JH.xij.items():
            if (i, j) in ws:
                st.add_var_value(xv, int(round(ws[(i, j)])))
                seeded += 1
        jm.add_mip_start(st, effort_level=4)
    except Exception as ex:
        print(f"[coupling] warm-start FAILED: {ex}", flush=True)
    print(f"[coupling] joint model: seeded {seeded} street arcs, solving {TL_JOINT}s", flush=True)

    jm.parameters.timelimit = TL_JOINT
    t0 = time.time()
    sol = jm.solve()
    det = jm.solve_details
    inc = round(sol.objective_value, 2) if sol else None
    db = getattr(det, "best_bound", None)
    print(f"[coupling] RESULT  incumbent={inc}  dual_bound={round(db,2) if db else None}  "
          f"status={det.status if det else '?'}  {time.time()-t0:.0f}s", flush=True)

    # Rule 3: independent verifier on the final incumbent
    if sol is not None:
        try:
            s = _extract_solution(JH)
            vinst = VInstance(NAME, SIZE, wls=0.1, tau="formula", proximity=0.0)
            vd = verify_solution(vinst, s, expect="any")  # d243: verifies pre-existing artifacts
            print(f"[coupling] VERIFIER  ok={vd.ok}  recomputed={vd.recomputed_obj}  "
                  f"claimed={inc}  violations={vd.violations[:2]}", flush=True)
        except Exception as ex:
            print(f"[coupling] VERIFIER errored: {ex}", flush=True)
    print(f"[coupling] vs: fixopt 834.64 | Karademir 754.3 | our LB {(r['value'] or 0)+wlb:.1f}", flush=True)


if __name__ == "__main__":
    main()
