"""
Lagrangian Decomposition — Candidate A coordinator.

L(lam) = z_A(lam) + z_B(lam)   is a valid lower bound on z_joint when each
block's contribution is a valid lower bound on that block's true min:
  * block A solved to optimality (fast, 0-90 s)  -> exact z_A(lam)
  * block B given a short limit; its CPLEX best_bound is a valid LB on
    z_B(lam), so L(lam) stays valid even when block B is truncated.
Subgradients use the blocks' incumbent solutions (approximate when B is
truncated -> slower ascent, still valid bound).

Subgradient (ascent, free-sign multipliers, maximising L):
    g_v[i,p] = v^A_ip - v^B_ip
    g_u[i]   = u^A_i  - u^B_i
    g_m[i]   = m^A_i  - m^B_i

Reported #4/#5-style: max_lam L(lam) vs joint LP relaxation vs z_joint.
"""
from __future__ import annotations
import math
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, ".")
from crossfeed.block_a import BlockA
from crossfeed.block_b import BlockB


@dataclass
class LDResult:
    best_bound: float
    history: list = field(default_factory=list)
    n_iter: int = 0
    reason: str = ""
    best_lam: dict = field(default_factory=dict)


def ld_bound(problem, *, ub, max_iter=40, blockA_tl=120, blockB_tl=20,
             gamma0=1.2, gamma_min=0.05, stall_patience=5, tol=1e-3,
             couplings=("v",), verbose=True):
    Customers = list(problem.customers)
    Sats = list(problem.satellites)
    A = BlockA(problem, integral=True)
    B = BlockB(problem, integral=True)
    use_v, use_u, use_m = ("v" in couplings), ("u" in couplings), ("m" in couplings)

    lam_v = {(i, p): 0.0 for i in Customers for p in Sats}
    lam_u = {i: 0.0 for i in Customers}
    lam_m = {i: 0.0 for i in Customers}

    best = -math.inf
    best_lam = None
    hist = []
    gamma = gamma0
    stall = 0
    reason = "max_iter"

    for k in range(max_iter):
        ra = A.solve(lam_v=lam_v if use_v else None, lam_u=lam_u if use_u else None,
                     lam_m=lam_m if use_m else None, time_limit=blockA_tl)
        rb = B.solve(lam_v=lam_v if use_v else None, lam_u=lam_u if use_u else None,
                     lam_m=lam_m if use_m else None, time_limit=blockB_tl)
        if ra["value"] is None or rb["value"] is None:
            reason = f"block solve failed at iter {k} (A={ra['status']} B={rb['status']})"
            break
        L = ra["value"] + rb["value"]

        # subgradient from incumbents
        vA = ra.get("vip_sol", {}); vB = rb.get("vB_sol", {})
        uA = ra.get("ui_sol", {});  uB = rb.get("uB_sol", {})
        mA = ra.get("mi_sol", {});  mB = rb.get("mB_sol", {})
        gv = {(i, p): (vA.get((i, p), 0.0) - vB.get((i, p), 0.0)) if use_v else 0.0
              for i in Customers for p in Sats}
        gu = {i: (uA.get(i, 0.0) - uB.get(i, 0.0)) if use_u else 0.0 for i in Customers}
        gm = {i: (mA.get(i, 0.0) - mB.get(i, 0.0)) if use_m else 0.0 for i in Customers}
        gnorm2 = (sum(x * x for x in gv.values())
                  + sum(x * x for x in gu.values())
                  + sum(x * x for x in gm.values()))

        if L > best + tol:
            best = L
            best_lam = ({k2: v for k2, v in lam_v.items()},
                        dict(lam_u), dict(lam_m))
            stall = 0
        else:
            stall += 1

        if verbose:
            print(f"  it {k:3d}  L={L:11.3f} (A={ra['value']:.1f}{'*' if ra['proven'] else '~'}"
                  f" B={rb['value']:.1f}{'*' if rb['proven'] else '~'})  best={best:11.3f}"
                  f"  ||g||2={gnorm2:8.2f}  gamma={gamma:.3f}", flush=True)
        hist.append((k, L, best, gnorm2, ra["value"], rb["value"], ra["wall_s"], rb["wall_s"]))

        if gnorm2 < 1e-6:
            reason = f"converged (blocks agree) at iter {k}"; break
        if best >= ub - tol:
            reason = f"reached UB at iter {k}"; break
        if stall >= stall_patience:
            gamma = max(gamma_min, gamma / 2.0); stall = 0

        target = max(ub, L + 1.0)
        alpha = gamma * (target - L) / gnorm2
        for key in lam_v:
            lam_v[key] += alpha * gv[key]
        for i in Customers:
            lam_u[i] += alpha * gu[i]
            lam_m[i] += alpha * gm[i]

    return LDResult(best, hist, len(hist), reason, best_lam or {})


if __name__ == "__main__":
    import argparse, json
    from build_instance import build
    from joint_model_cplex import joint_synchronized_cplex

    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="C201")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--max-iter", type=int, default=30)
    ap.add_argument("--blockB-tl", type=float, default=20)
    ap.add_argument("--couplings", default="v", help="subset of v,u,m to dualize")
    a = ap.parse_args()
    cpl = tuple(x.strip() for x in a.couplings.split(",") if x.strip())

    p = build(a.instance, a.size, wls=0.1, tau="formula", proximity=0.0, time_limit=300)
    jlp = joint_synchronized_cplex(p, time_limit=120, lp_relax=True)
    p2 = build(a.instance, a.size, wls=0.1, tau="formula", proximity=0.0, time_limit=300)
    zj = joint_synchronized_cplex(p2, time_limit=300, mip_gap=0.0)
    ub = zj["objVal"] if zj["objVal"] else 1e7

    print(f"=== LD Candidate A: {a.instance} n={a.size} ===")
    print(f"joint LP relax = {jlp['lp_bound']} ; z_joint = {zj['objVal']} ({zj['status']})", flush=True)
    r = ld_bound(p, ub=ub, max_iter=a.max_iter, blockB_tl=a.blockB_tl, couplings=cpl)
    print(f"\nLD bound max_lam L(lam) = {r.best_bound:.3f}  ({r.reason}, {r.n_iter} iters)")
    print(f"  vs joint LP relax {jlp['lp_bound']}  -> {r.best_bound - (jlp['lp_bound'] or 0):+.1f}")
    print(f"  vs z_joint {zj['objVal']}  -> closes "
          f"{100*(r.best_bound-(jlp['lp_bound'] or 0))/max((ub-(jlp['lp_bound'] or 0)),1e-9):.1f}% of the LP gap")
    json.dump({"instance": a.instance, "size": a.size, "joint_lp": jlp["lp_bound"],
               "z_joint": zj["objVal"], "z_joint_status": zj["status"],
               "ld_bound": r.best_bound, "reason": r.reason, "iters": r.n_iter,
               "history": r.history},
              open(f"validation/ld_candA_{a.instance}_n{a.size}.json", "w"), indent=2, default=str)
