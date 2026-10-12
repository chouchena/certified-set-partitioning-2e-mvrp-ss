"""
Subgradient ascent on the Lagrangian dual  max_lam L(lam)  of the
satellite-assignment coupling.  L(lam) is concave (a min of affine
functions of lam); its subgradient at lam is g_i = sum_p v*_ip - 1.
lam is free-sign (equality constraint).

Polyak step:  alpha_k = gamma_k * (UB - L(lam_k)) / ||g||^2,  gamma in (0,2].
Falls back to a diminishing step 1/(a+k) when the bound stalls.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

from crossfeed.lagrangian_subproblem import SubModel


@dataclass
class DualResult:
    best_bound: float
    best_lam: dict
    history: list = field(default_factory=list)   # (iter, L, ||g||, alpha, best)
    n_iter: int = 0
    reason: str = ""


def subgradient_ascent(sub: SubModel, ub: float, *, lam0: dict | None = None,
                       max_iter: int = 60, sub_time_limit: float = 60.0,
                       gamma0: float = 1.5, gamma_min: float = 0.05,
                       stall_patience: int = 6, tol: float = 1e-4,
                       verbose: bool = False) -> DualResult:
    T = list(sub.transferSet)
    lam = {i: 0.0 for i in T}
    if lam0:
        lam.update({i: float(lam0.get(i, 0.0)) for i in T})

    best_bound = -math.inf
    best_lam = dict(lam)
    hist = []
    gamma = gamma0
    stall = 0
    reason = "max_iter"

    for k in range(max_iter):
        res = sub.solve(lam=lam, time_limit=sub_time_limit)
        if res.value is None:
            reason = f"subproblem {res.status} at iter {k}"
            break
        Lk = res.value
        g = res.subgrad
        gnorm2 = sum(v * v for v in g.values())

        if Lk > best_bound + tol:
            best_bound = Lk
            best_lam = dict(lam)
            stall = 0
        else:
            stall += 1

        if verbose:
            print(f"  it {k:3d}  L={Lk:10.3f}  best={best_bound:10.3f}  "
                  f"||g||^2={gnorm2:7.3f}  gamma={gamma:.3f}  stall={stall}", flush=True)

        if gnorm2 < 1e-9:
            reason = f"converged (feasible dual point) at iter {k}"
            hist.append((k, Lk, 0.0, 0.0, best_bound))
            break
        if best_bound >= ub - tol:
            reason = f"reached UB at iter {k}"
            hist.append((k, Lk, gnorm2 ** 0.5, 0.0, best_bound))
            break

        if stall >= stall_patience:
            gamma = max(gamma_min, gamma / 2.0)
            stall = 0
        # Polyak step toward the UB; guard against UB < L (numerical)
        target = max(ub, Lk + 1.0)
        alpha = gamma * (target - Lk) / gnorm2
        # diminishing floor keeps motion when Polyak collapses
        alpha = max(alpha, 1.0 / (5.0 + k)) if gamma <= gamma_min + 1e-9 else alpha

        for i in T:
            lam[i] += alpha * g[i]          # ASCENT (maximising L)

        hist.append((k, Lk, gnorm2 ** 0.5, alpha, best_bound))
    else:
        reason = "max_iter"

    return DualResult(best_bound, best_lam, hist, len(hist), reason)
