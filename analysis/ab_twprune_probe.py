"""
READ-ONLY probe: does restricting AB's distance relaxations to K's OWN time-window-pruned
arc set tighten the bound?

Motivation (validation/AB_VALIDITY_VS_K_GUROBI.md section 2.2): K's model admits an arc only
when `e_i + s_i + D[i][j] <= l_j` (integratedJointModel.py:58). Our assignment / MST /
forced-terminal relaxations run on the COMPLETE digraph, so we minimise over a superset of
what any feasible solution can use. That is valid but slack.

VALIDITY OF THE TIGHTER FORM. In any feasible solution every customer's successor arc is
admitted by K's own rule, so the true successor map remains feasible for the restricted
assignment problem -- the restricted optimum is still a lower bound on the realised distance.
No new argument is needed beyond K's line 58. For the MST the pruning must be UNDIRECTED: an
edge {i,j} survives if EITHER direction is admitted, since the route may traverse it either
way.

Writes runs/ab_twprune_probe_n<sizes>.json. Touches NOTHING else -- the live grid is not
overwritten.

HISTORY (2026-09-14). This used to write one fixed filename. The n100 run therefore destroyed
the n20/n30 run's artifact -- `validation/REFACTOR_2026-09-12.md` still records the file as
having 54 records, which is the n20+n30 shape, while the surviving file has 27 (n100). When the
claim `ab-tw-pruning-tightens-bound` was re-derived, its "n20+n30 33/54 +3.35%" figure could not
be checked against anything, and re-running the probe gave **0/54 with no distance relaxation
changed**. The 33/54 figure is withdrawn. The cause of the discrepancy cannot be established
because the original artifact is gone -- which is the whole argument for size-keyed filenames.
"""
import os, sys, json, argparse
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

from scipy.optimize import linear_sum_assignment, linprog
from scipy.sparse import lil_matrix
from scipy.sparse.csgraph import minimum_spanning_tree
from build_instance import build
from crossfeed.check_cuts import cut_bounds
from crossfeed.fullset_bound import (assignment_dist_lb, mst_dist_lb,
                                     forced_terminal_dist_lb, max_triangle_excess)

# Solomon class-2 cells actually in the grid: C201-208, R201-211, RC201-208.
CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])


def admits(p, i, j):
    """K's own arc-admission rule, integratedJointModel.py:58."""
    n = p.nodes
    return n[i].earliest + n[i].serviceTime + p.DistMatrix[i][j] <= n[j].latest


def assignment_tw(p, cust):
    D, n = p.DistMatrix, len(cust)
    if n == 0:
        return 0.0
    BIG = 1e9
    M = np.full((n, 2 * n), BIG)
    for a, i in enumerate(cust):
        for b, j in enumerate(cust):
            if i != j and admits(p, i, j):
                M[a, b] = D[i][j]
        if admits(p, i, 0):
            for b in range(n):
                M[a, n + b] = D[i][0]
    r, c = linear_sum_assignment(M)
    tot = float(M[r, c].sum())
    return 0.0 if tot >= BIG / 2 else tot          # infeasible -> fall back, never claim


def mst_tw(p, cust):
    """Undirected pruning: keep {i,j} if EITHER direction is admitted."""
    if not cust:
        return 0.0
    idx = [0] + cust
    D = np.asarray(p.DistMatrix, dtype=float)[np.ix_(idx, idx)].copy()
    m = len(idx)
    for a in range(m):
        for b in range(a + 1, m):
            i, j = idx[a], idx[b]
            if not (admits(p, i, j) or admits(p, j, i)):
                D[a, b] = D[b, a] = 0.0            # 0 = absent edge for scipy MST
    t = minimum_spanning_tree(D).toarray()
    # disconnected => some component unreachable; that cannot happen for a feasible instance,
    # but guard rather than emit a wrong number.
    if (t > 0).sum() < m - 1:
        return -1.0
    return float(t.sum())


def forced_tw(p, cust, trips_lb):
    D = np.asarray(p.DistMatrix, dtype=float)
    n = len(cust)
    if n == 0:
        return 0.0
    T = max(0, min(int(trips_lb), n))
    sats = list(p.satellites)
    sub = D[np.ix_(cust, cust)].copy()
    np.fill_diagonal(sub, 1e7)
    for a, i in enumerate(cust):
        for b, j in enumerate(cust):
            if a != b and not admits(p, i, j):
                sub[a, b] = 1e7                    # arc unavailable to any feasible solution
    term = np.array([min(min(D[i][s] for s in sats), D[i][0]) for i in cust])
    cost = np.concatenate([sub.ravel(), term])
    Aeq = lil_matrix((n, n * n + n))
    for a in range(n):
        Aeq[a, a * n:(a + 1) * n] = 1
        Aeq[a, n * n + a] = 1
    Aub = lil_matrix((n + 1, n * n + n))
    bub = np.ones(n + 1)
    for j in range(n):
        Aub[j, [a * n + j for a in range(n)]] = 1
    Aub[n, n * n:] = -1
    bub[n] = -T
    r = linprog(cost, A_ub=Aub.tocsr(), b_ub=bub, A_eq=Aeq.tocsr(), b_eq=np.ones(n),
                bounds=(0, 1), method="highs")
    if not r.success or r.fun >= 1e6:
        return 0.0
    return float(r.fun)


def compose(p, cust, dist):
    """Same composition as fullset_bound, so the two variants differ ONLY in dist."""
    import math
    cb = cut_bounds(p, cust)
    metric = max_triangle_excess(p) <= 1e-9
    nd = p.nodes
    hz = nd[0].latest - nd[0].earliest
    work = sum(nd[c].serviceTime for c in cust) + dist + cb["trips_lb"] * p.TransferDuration
    routes = max(cb["routes_lb_time"], math.ceil(work / hz) if hz > 0 else 1)
    V = max(1, routes, cb["clique"] if metric else 1)
    from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
    w = water_lb_scaled(p)[0] / SCALE
    return V * p.penaltyCars + p.travelcoststreet * dist + w, V


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20,30")
    a = ap.parse_args()
    out = []
    for size in [int(x) for x in a.sizes.split(",")]:
        for cell in CELLS:
            # Proximity is 0.0 for |C| <= 50 (K Tables 3/4) and 0.1 at |C| = 100 (K Table 6).
            # Hardcoding 0.0 made the first n100 probe solve a DIFFERENT problem: it reported a
            # base crossover of 20/27 against the true 17/27. Not a better bound -- another
            # instance configuration.
            prox = 0.1 if size == 100 else 0.0
            p = build(cell, size, wls=0.1, tau="formula", proximity=prox, time_limit=60)
            cust = list(p.customers)
            tl = cut_bounds(p, cust)["trips_lb"]
            base = {"ap": assignment_dist_lb(p, cust), "mst": mst_dist_lb(p, cust),
                    "ft": forced_terminal_dist_lb(p, cust, tl)}
            tw = {"ap": assignment_tw(p, cust), "mst": mst_tw(p, cust),
                  "ft": forced_tw(p, cust, tl)}
            d0, d1 = max(base.values()), max(tw.values())
            # A tighter arc set can only RAISE each relaxation. A drop means a bug, not a result.
            bad = [k for k in base if tw[k] >= 0 and tw[k] < base[k] - 1e-6]
            b0, v0 = compose(p, cust, d0)
            b1, v1 = compose(p, cust, max(d0, d1))
            out.append({"cell": cell, "size": size, "prox": prox, "base": base, "tw": tw,
                        "dist_base": round(d0, 3), "dist_tw": round(d1, 3),
                        "ab_base": round(b0, 3), "ab_tw": round(b1, 3),
                        "V_base": v0, "V_tw": v1,
                        "gain": round(b1 - b0, 3),
                        "gain_pct": round((b1 - b0) / b0 * 100, 3) if b0 else 0.0,
                        "REGRESSION": bad})
            print(f"{cell:7} n{size}: dist {d0:9.2f} -> {d1:9.2f}   "
                  f"AB {b0:9.2f} -> {b1:9.2f}  ({(b1-b0)/b0*100:+.2f}%)"
                  f"{'  *** REGRESSION ' + str(bad) if bad else ''}", flush=True)
    # PROVENANCE DEFECT, fixed 2026-09-14: this wrote one fixed filename, so every run
    # destroyed the previous one. That is how the original n20/n30 evidence was lost -- the
    # n100 run overwrote it, and when the claim was later re-derived the 33/54 figure could not
    # be checked against anything. Output is now keyed by the sizes probed.
    tag = "_".join(str(x) for x in sorted(set(r["size"] for r in out)))
    dest = os.path.join(ROOT, "runs", f"ab_twprune_probe_n{tag}.json")
    if os.path.exists(dest):
        print(f"NOTE: overwriting {os.path.relpath(dest, ROOT)} (same sizes probed before)")
    json.dump(stamped(out, __file__), open(dest, "w"), indent=1)
    print(f"-> {os.path.relpath(dest, ROOT)}")
    reg = [r for r in out if r["REGRESSION"]]
    print(f"\n{len(out)} cells. regressions (must be 0): {len(reg)}")
    moved = [r for r in out if r["gain"] > 1e-6]
    print(f"cells where the tighter arc set raises AB: {len(moved)}")
    if moved:
        print(f"mean gain on moved cells: {sum(r['gain_pct'] for r in moved)/len(moved):+.2f}%  "
              f"max {max(r['gain_pct'] for r in moved):+.2f}%")


if __name__ == "__main__":
    main()
