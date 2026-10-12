"""
Smoke test + first validation for crossfeed #4 (optimized Lagrangian
dual of the satellite-assignment coupling) and #5 (multiplier warm-start).

For a FIXED (routing, transfer-set) decision — taken from the joint
model's optimal solution — compare, all for the same subproblem:

  z*            true integer subproblem optimum   (hubAssignment kept)
  L_LP          LP relaxation of that subproblem  (= Karademir's bound base)
  L_LD(lam=0)   Lagrangian at zero multipliers    (hubAssignment relaxed)
  L_LD(lam=piT) Lagrangian at Karademir's LP-dual read-off values
  L_LD(lam*)    optimized Lagrangian dual (subgradient ascent)   <-- #4

Validity (must hold):  every L_* <= z*.
Payoff of #4:  L_LD(lam*) - L_LP    and    L_LD(lam*) - L_LD(lam=piT).

#5: run the subgradient on a SECOND fixed decision, cold vs. warm-started
from the first decision's lam*, and compare iterations / bound-at-budget.

Usage:
  python -m crossfeed.smoke_45 --instance C201 --size 10
  python -m crossfeed.smoke_45 --instance R205 --size 20 --max-iter 40 --sub-tl 90
"""
import argparse
import json
import sys
import time

sys.path.insert(0, ".")
from build_instance import build
from joint_model_cplex import joint_synchronized_cplex
from crossfeed.lagrangian_subproblem import SubModel
from crossfeed.subgradient import subgradient_ascent


class _Fixed:
    def __init__(self, xij, vi):
        self.xij = [list(a) for a in xij]
        self.vi = list(vi)


def fixed_from_joint(problem, time_limit):
    r = joint_synchronized_cplex(problem, time_limit=time_limit, mip_gap=0.0)
    s = r["solution"]
    return _Fixed(s["xij"], s["vi"]), r["objVal"], r["status"]


def fixed_from_construct(problem, seed=0):
    """A feasible-but-SUBOPTIMAL fixed decision — the case where an LBBD
    cut actually has to provide a useful bound."""
    from feasible_construct import construct_feasible_decision
    arcs, transfers, _hubs = construct_feasible_decision(problem, seed=seed)
    return _Fixed(arcs, transfers), None, "construct"


def evaluate(problem, fixed, *, max_iter, sub_tl, lam0=None, verbose=True):
    T = list(fixed.vi)
    out = {"n_transfers": len(T)}

    # z* — true integer subproblem optimum
    t0 = time.time()
    m_star = SubModel(problem, fixed.xij, T, hubassign=True, integral=True)
    r_star = m_star.solve(time_limit=max(sub_tl, 120))
    out["z_star"] = r_star.value
    out["z_star_status"] = r_star.status
    out["z_star_s"] = round(time.time() - t0, 1)

    # L_LP — LP relaxation of the constrained subproblem + hub duals (piT)
    m_lp = SubModel(problem, fixed.xij, T, hubassign=True, integral=False)
    r_lp = m_lp.solve(time_limit=60)
    out["L_LP"] = r_lp.value
    piT = m_lp.hub_duals()
    out["piT"] = {str(k): round(v, 4) for k, v in piT.items()}

    # Lagrangian-relaxed subproblem (hubAssignment dropped), integer
    m_ld = SubModel(problem, fixed.xij, T, hubassign=False, integral=True)

    r0 = m_ld.solve(lam={i: 0.0 for i in T}, time_limit=sub_tl)
    out["L_LD_lam0"] = r0.value

    rp = m_ld.solve(lam=piT, time_limit=sub_tl)
    out["L_LD_piT"] = rp.value

    # #4 — optimize the dual
    ub = r_star.value if r_star.value is not None else (r_lp.value or 0) * 2 + 1e6
    t0 = time.time()
    dual = subgradient_ascent(m_ld, ub, lam0=lam0, max_iter=max_iter,
                              sub_time_limit=sub_tl, verbose=verbose)
    out["L_LD_star"] = round(dual.best_bound, 4)
    out["dual_iters"] = dual.n_iter
    out["dual_reason"] = dual.reason
    out["dual_s"] = round(time.time() - t0, 1)
    out["best_lam"] = {str(k): round(v, 4) for k, v in dual.best_lam.items()}

    # verdicts
    zs = out["z_star"]
    if zs is not None:
        eps = 1e-2
        out["valid_LP"] = out["L_LP"] is None or out["L_LP"] <= zs + eps
        out["valid_LD_star"] = out["L_LD_star"] <= zs + eps
        out["payoff_over_LP"] = (round(out["L_LD_star"] - out["L_LP"], 4)
                                 if out["L_LP"] is not None else None)
        out["payoff_over_piT"] = (round(out["L_LD_star"] - out["L_LD_piT"], 4)
                                  if out["L_LD_piT"] is not None else None)
        out["LD_closes_frac"] = (round((out["L_LD_star"] - (out["L_LP"] or 0))
                                       / max(zs - (out["L_LP"] or 0), 1e-9), 4))
    return out, dual.best_lam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="C201")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--wls", type=float, default=0.1)
    ap.add_argument("--proximity", type=float, default=0.0)
    ap.add_argument("--max-iter", type=int, default=50)
    ap.add_argument("--sub-tl", type=float, default=60.0)
    ap.add_argument("--joint-tl", type=float, default=600.0)
    ap.add_argument("--second-instance", default=None,
                    help="a 2nd instance for the #5 warm-start test (default: same instance, size)")
    ap.add_argument("--fixed", choices=["joint", "construct"], default="joint",
                    help="fixed decision source: joint optimum, or a suboptimal feasible_construct")
    a = ap.parse_args()

    print(f"=== #4 smoke: {a.instance} n={a.size} (tau=formula, prox={a.proximity}, fixed={a.fixed}) ===", flush=True)
    p = build(a.instance, a.size, wls=a.wls, tau="formula", proximity=a.proximity,
              time_limit=a.joint_tl)
    if a.fixed == "construct":
        fixed, jobj, jstat = fixed_from_construct(p)
    else:
        fixed, jobj, jstat = fixed_from_joint(p, a.joint_tl)
    print(f"fixed decision ({jstat}, joint obj {jobj}); {len(fixed.vi)} transfers", flush=True)

    res1, lam_star1 = evaluate(p, fixed, max_iter=a.max_iter, sub_tl=a.sub_tl)
    print("\n--- results ---")
    for k in ("n_transfers", "z_star", "L_LP", "L_LD_lam0", "L_LD_piT", "L_LD_star",
              "dual_iters", "dual_reason", "dual_s",
              "valid_LP", "valid_LD_star", "payoff_over_LP", "payoff_over_piT", "LD_closes_frac"):
        print(f"  {k:16} {res1.get(k)}")

    # ---- #5 : warm-start on a second decision --------------------
    si = a.second_instance or a.instance
    print(f"\n=== #5 warm-start test: {si} n={a.size} ===", flush=True)
    p2 = build(si, a.size, wls=a.wls, tau="formula", proximity=a.proximity, time_limit=a.joint_tl)
    if a.fixed == "construct":
        fixed2, _j, _s = fixed_from_construct(p2, seed=1)
    else:
        fixed2, _j, _s = fixed_from_joint(p2, a.joint_tl)
    cold, _ = evaluate(p2, fixed2, max_iter=a.max_iter, sub_tl=a.sub_tl, verbose=False)
    warm, _ = evaluate(p2, fixed2, max_iter=a.max_iter, sub_tl=a.sub_tl,
                       lam0=lam_star1, verbose=False)
    print(f"  cold:  L_LD*={cold['L_LD_star']}  iters={cold['dual_iters']}  {cold['dual_s']}s  ({cold['dual_reason']})")
    print(f"  warm:  L_LD*={warm['L_LD_star']}  iters={warm['dual_iters']}  {warm['dual_s']}s  ({warm['dual_reason']})")

    out = {"config": vars(a), "primary": res1,
           "warmstart": {"cold": cold, "warm": warm,
                         "iters_saved": cold["dual_iters"] - warm["dual_iters"],
                         "bound_delta": round((warm["L_LD_star"] or 0) - (cold["L_LD_star"] or 0), 4)}}
    fn = f"validation/smoke45_{a.instance}_n{a.size}.json"
    json.dump(out, open(fn, "w"), indent=2, default=str)
    print(f"\nwritten {fn}")


if __name__ == "__main__":
    main()
