"""Does a tighter big-M move the ROOT LP of the corrected (26) model? Pre-test, seconds.

WHY THIS COMES BEFORE ANY ABLATION. d231 banked OBBT big-M tightening as VALID but with its
benefit explicitly UNMEASURED and not to be inferred (the analogue of d9). An ablation of the
tightening would cost ~48 paired blocks to reach a 2% MDE against this project's measured 4.83%
paired-block SD (d145), and would very likely return a null. This test asks the prior question for
the cost of four LP solves: is the MECHANISM even present?

THE MECHANISM, and the prediction it makes. At the root, o_ij is free in [0,1], so the LP sets
o = 0.5 and both disjunction rows gain M/2 of slack. With tau = 180 and M = 3724 that is 1862 of
slack against a 180 requirement -- the rows cannot bind. The gate M(2 - v_ip - v_jp) does the same
independently whenever v is fractional, which it is at the root. For the LP to stop hiding the
constraint you need roughly M/2 < tau, i.e. M < 2*tau. PREDICTION: the tightened M (median 1769,
min 514 on C201/n30) is still far above 2*tau = 360, so the root LP should NOT move.

A null here kills the performance question without spending a single paired run, and leaves OBBT
where d231 puts it: correctness hygiene with a refuse-on-failure assertion, not a claimed speedup.
A non-null would make an ablation worth designing.

FOUR ARMS, all root LP only, no branching:
  vacuous          (26) rows absent          -- the baseline the arms are compared against
  corrected/global (26) with the global M    -- what ships today
  corrected/LP     (26) with OBBT M_ij       -- the candidate
  corrected/2tau   (26) with M = 2*tau       -- NOT VALID; included to show the test can detect
                                                movement at all. Its objective value is
                                                meaningless and is never reported as a bound.

    python analysis/rootlp_bigm_pretest.py --cell C201 --size 30
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
OUTDIR = os.path.join(ROOT, "runs", "obbt")


def root_lp(p, M_for_pair, threads=1):
    """Root LP objective of the model, with the (26) rows posted using M_for_pair(i, j).

    M_for_pair = None posts no (26) rows at all (the vacuous baseline).
    """
    from gurobipy import GRB
    from joint_model_gurobi import build_joint_model_gurobi

    p.hardSingleTransfer = False          # never let the builder post its own (26) rows
    H = build_joint_model_gurobi(p)
    m = H["m"]
    ui, vip = H["ui"], H["vip"]
    C, P, TD = list(H["Customers"]), list(H["Satellites"]), p.TransferDuration

    if M_for_pair is not None:
        o = {}
        for a in range(len(C)):
            for b in range(a + 1, len(C)):
                i, j = C[a], C[b]
                M = M_for_pair(i, j)
                o[i, j] = m.addVar(vtype=GRB.BINARY, name="o.%d.%d" % (i, j))
                for q in P:
                    gate = M * (2 - vip[i, q] - vip[j, q])
                    m.addConstr(ui[j] >= ui[i] + TD - M * (1 - o[i, j]) - gate)
                    m.addConstr(ui[i] >= ui[j] + TD - M * o[i, j] - gate)
    m.update()
    r = m.relax()
    r.Params.OutputFlag = 0
    r.Params.Threads = threads
    t0 = time.time()
    r.optimize()
    secs = round(time.time() - t0, 2)
    if r.Status == GRB.INFEASIBLE:
        # A LEGITIMATE OUTCOME for the deliberately-invalid 2*tau arm, and the strongest possible
        # demonstration that this test has power: an M that small does not merely tighten the
        # relaxation, it cuts the relaxation empty. Not an error -- report it.
        return None, secs, m.NumVars, m.NumConstrs
    if r.Status != GRB.OPTIMAL:
        raise RuntimeError("root LP status %s" % r.Status)
    return r.ObjVal, secs, m.NumVars, m.NumConstrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="C201")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--threads", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    from analysis.k_comparison import k_proximity
    from build_instance import build
    from analysis.obbt_bigm import lp_bounds, box_bounds, assert_valid, build_M

    prox = k_proximity(a.size)
    p = build(a.cell, a.size, wls=0.1, tau="formula", proximity=prox)
    nd, CDC, TD = p.nodes, p.CDC, p.TransferDuration
    M_global = (nd[CDC].latest - nd[CDC].earliest) + TD + 1.0

    print("cell %s  n%d  proximity %s  tau %s" % (a.cell, a.size, prox, TD))
    print("root-LP visibility threshold ~ M < 2*tau = %.0f" % (2 * TD))
    print()

    print("deriving OBBT bounds ...", flush=True)
    lp_lb, lp_ub = lp_bounds(p, threads=a.threads)
    box_lb, box_ub = box_bounds(p)
    M_lp = build_M(p, lp_lb, lp_ub)
    errs = assert_valid(M_lp, lp_lb, lp_ub, box_lb, box_ub, TD)
    if errs:
        print("REFUSING -- OBBT validity assertions failed:")
        for e in errs[:5]:
            print("   " + e)
        return 3
    import statistics as st
    print("   OBBT M_ij: median %.2f  min %.2f  (global %.2f)"
          % (st.median(M_lp.values()), min(M_lp.values()), M_global))
    print()

    arms = [
        ("vacuous          ", None),
        ("corrected/global ", lambda i, j: M_global),
        ("corrected/LP     ", lambda i, j: M_lp[(i, j)] if (i, j) in M_lp else M_lp[(j, i)]),
        ("corrected/2tau*  ", lambda i, j: 2.0 * TD),
    ]
    out = []
    base = None
    print("%-18s %14s %10s %8s %9s" % ("arm", "root LP", "delta", "LP s", "rows"))
    print("-" * 64)
    for tag, f in arms:
        val, secs, nv, nc = root_lp(p, f, threads=a.threads)
        if base is None:
            base = val
        if val is None:
            print("%-18s %14s %10s %8.2f %9d" % (tag, "INFEASIBLE", "--", secs, nc))
            out.append({"arm": tag.strip(), "root_lp": None, "delta_vs_vacuous": None,
                        "lp_seconds": secs, "n_rows": nc, "status": "INFEASIBLE"})
        else:
            print("%-18s %14.6f %10.6f %8.2f %9d" % (tag, val, val - base, secs, nc))
            out.append({"arm": tag.strip(), "root_lp": val, "delta_vs_vacuous": val - base,
                        "lp_seconds": secs, "n_rows": nc})
    print()
    print("* corrected/2tau is NOT a valid M. It is included only to show this test can detect")
    print("  movement when movement exists; its value is not a bound on anything.")
    print()

    d_global = out[1]["delta_vs_vacuous"]
    d_lp = out[2]["delta_vs_vacuous"]
    d_2tau = out[3]["delta_vs_vacuous"]
    moved = abs(d_lp - d_global) > 1e-6
    print("VERDICT")
    if not moved:
        print("  NULL. The tightened M moves the root LP by %.2e -- nothing. The mechanism is not"
              % abs(d_lp - d_global))
        print("  present at the root, so an ablation of the tightening would be measuring a")
        print("  channel that does not exist. OBBT stays where d231 puts it: correctness hygiene")
        print("  with a refuse-on-failure assertion, NOT a claimed speedup. Do not design an")
        print("  ablation on this evidence.")
    else:
        print("  NON-NULL. The tightened M moves the root LP by %.6f. The mechanism IS present;"
              % abs(d_lp - d_global))
        print("  an ablation becomes worth designing -- paired on (cell, seed), matched det")
        print("  budgets, >= 48 blocks for a 2%% MDE against the 4.83%% paired-block SD of d145.")
    if d_2tau is None:
        print("  POWER CONFIRMED, and more sharply than expected: at the invalid M = 2*tau the")
        print("  root LP is INFEASIBLE -- an M that small does not merely tighten the relaxation,")
        print("  it cuts it empty. The test can plainly detect an M that bites. Neither valid M")
        print("  does. The null above is INFORMATIVE.")
    elif abs(d_2tau - d_global) <= 1e-6:
        print("  CAVEAT: even the invalid M = 2*tau arm does not move the root, so this test")
        print("  could not have detected movement on this cell. The null above is UNINFORMATIVE.")
    else:
        print("  The invalid 2*tau arm DOES move the root (%.6f), so the test had the power to"
              % abs(d_2tau - d_global))
        print("  detect movement and the result above is informative.")

    path = os.path.join(OUTDIR, "rootlp_pretest_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped({"cell": a.cell, "size": a.size, "tau": TD, "M_global": M_global,
               "M_lp_median": st.median(M_lp.values()), "M_lp_min": min(M_lp.values()),
               "threshold_2tau": 2 * TD, "arms": out,
               "verdict": "NULL" if not moved else "NON-NULL"}, __file__),
              open(path, "w"), indent=1, default=str)
    print()
    print("-> %s" % os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
