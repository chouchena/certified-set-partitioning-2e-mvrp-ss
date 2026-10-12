"""
Big-M audit — is the 2E-MVRP-SS formulation carrying looser big-M constants
than integer-validity requires, and how much does that cost?

A big-M constraint  LHS <= RHS + M(1 - x)  only needs M large enough that
every INTEGER-feasible point with x=0 satisfies it. A smaller M cuts more
of the LP polytope (tighter relaxation, faster B&B) while keeping every
integer solution feasible.

Checks the three M families in `crossfeed/block_a.py` / `joint_model_cplex.py`:
  Const8  (street time-flow)      M = latest_i + s_i + TD + maxDetour_ij - earliest_j
  Const14 (sync time-flow)        same M
  Const22 (water time-flow)       M = latest_i + s_i + maxHub_i + TD + maxInterHub - (earliest_j + s_j + minHub_j)

For each, computes a tightened M using:
  * effective hi_i upper bound  = min(latest_i, depot_latest - t_{i,0} - s_i - TD)   (Const7)
  * effective hi_j lower bound  = max(earliest_j, depot_earliest + t_{0,j})           (Const7)
  * dropping the detour / inter-hub term entirely: when x=0 the arc-cost
    variable is 0 at any integer optimum, so that term is never needed.

Also audits the ARC-SURVIVAL filter (earliest_i + s_i + t_ij <= latest_j)
against a tighter one using the effective bounds.
"""
from __future__ import annotations
import sys
import numpy as np

sys.path.insert(0, ".")
from build_instance import build

CELLS = [("C203", 20), ("C204", 20), ("R205", 20), ("RC203", 20),
         ("C201", 20), ("R201", 20)]


def audit(name, size):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=20)
    D, nd = p.DistMatrix, p.nodes
    C = list(p.customers); S = list(p.satellites); CDC = p.CDC
    TD = p.TransferDuration
    dep_e, dep_l = nd[0].earliest, nd[0].latest
    setCd = [0] + C

    def hi_ub(i):   # Const7 effective latest departure from i
        if i == 0:
            return dep_l
        return min(nd[i].latest, dep_l - D[i][0] - nd[i].serviceTime - TD)

    def hi_lb(j):   # Const7 effective earliest at j
        if j == 0:
            return dep_e
        return max(nd[j].earliest, dep_e + D[0][j])

    # ---- arc filter ----
    raw_arcs = [(i, j) for i in setCd for j in setCd if i != j
                and nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest]
    tight_arcs = [(i, j) for (i, j) in raw_arcs
                  if hi_lb(i) + nd[i].serviceTime + D[i][j] <= hi_ub(j) + 1e-6]
    npairs = len(setCd) * (len(setCd) - 1)

    # ---- Const8 / Const14 M ----
    cur, tight = [], []
    for (i, j) in raw_arcs:
        if i not in C:
            continue
        mt = max(D[i][s1] + D[s1][j] for s1 in S)
        M_code = nd[i].latest + nd[i].serviceTime + TD + mt - nd[j].earliest
        # integer-valid tight M: worst (hi_i + s_i + TD) - hi_j, arc-cost = 0 at x=0
        M_tight = max(0.0, hi_ub(i) + nd[i].serviceTime + TD - hi_lb(j))
        cur.append(M_code); tight.append(M_tight)
    cur, tight = np.array(cur), np.array(tight)

    # ---- Const22 M (water) ----
    cwat, twat = [], []
    for i in C:
        for j in C:
            if i == j:
                continue
            maxHub_i = max(D[i][s1] for s1 in S)
            minHub_j = min(D[j][s1] for s1 in S)
            maxInter = max(D[s1][r] for s1 in S for r in S)
            M_code = (nd[i].latest + nd[i].serviceTime + maxHub_i + TD + maxInter
                      - (nd[j].earliest + nd[j].serviceTime + minHub_j))
            # ui is in [CDC.e, CDC.l]; tight: ui_i can be at most CDC.l - (TD + minHub_i back)
            ui_ub_i = min(nd[CDC].latest, nd[CDC].latest)  # (no extra Const7-style tightening on u here)
            ui_lb_j = nd[CDC].earliest + minHub_j
            M_tight = max(0.0, ui_ub_i + TD - ui_lb_j)
            cwat.append(M_code); twat.append(M_tight)
    cwat, twat = np.array(cwat), np.array(twat)

    return {
        "cell": f"{name}/{size}",
        "arcs_raw": len(raw_arcs), "arcs_tight": len(tight_arcs),
        "arc_survival_raw": round(len(raw_arcs) / npairs, 3),
        "arc_survival_tight": round(len(tight_arcs) / npairs, 3),
        "arcs_removed_pct": round(100 * (len(raw_arcs) - len(tight_arcs)) / max(1, len(raw_arcs)), 1),
        "M8_code_mean": round(cur.mean(), 0), "M8_tight_mean": round(tight.mean(), 0),
        "M8_reduction_pct": round(100 * (1 - tight.mean() / cur.mean()), 1),
        "M8_code_max": round(cur.max(), 0), "M8_tight_max": round(tight.max(), 0),
        "M22_code_mean": round(cwat.mean(), 0), "M22_tight_mean": round(twat.mean(), 0),
        "M22_reduction_pct": round(100 * (1 - twat.mean() / cwat.mean()), 1),
    }


if __name__ == "__main__":
    rows = [audit(n, s) for n, s in CELLS]
    import pandas as pd
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    df.to_csv("analysis/bigM_audit.csv", index=False)
    print("\nKey:")
    print("  M8_reduction_pct  : how much smaller the street/sync big-M could be (integer-valid)")
    print("  M22_reduction_pct : same for the water time-flow big-M")
    print("  arcs_removed_pct  : arcs the tighter feasibility filter eliminates")
