"""PROVABLY VALID, TIGHTER big-M for the corrected constraint (26), by LP bound tightening.

THE OBLIGATION. The disjunction posts, for each pair i<j and satellite p:

    u_j >= u_i + tau - M(1 - o_ij) - M(2 - v_ip - v_jp)
    u_i >= u_j + tau - M·o_ij      - M(2 - v_ip - v_jp)

Whenever a row is meant to be INACTIVE its M-term must dominate, so validity requires

    M_ij  >=  sup{ u_i - u_j : feasible }  +  tau       (and symmetrically)

An M at or above that supremum cuts nothing; an M below it removes feasible points, and THAT
FAILURE IS INVISIBLE TO THE VERIFIER -- an over-tight model returns solutions that genuinely
satisfy (26), so verify2 accepts them. What breaks is optimality: the reported optimum inflates.
That is exactly the false positive `c26_attainability.py` is designed not to manufacture, which is
why this is derived rather than tested.

WHY LP RELAXATION IS A PROOF. The relaxation's feasible set is a SUPERSET of the integer-feasible
set: integrality is dropped and v goes continuous on [0,1], which is strictly more permissive than
any assignment -- including the v_i = 0 case that broke an earlier hand-derived bound, where every
vip-weighted term in Const13/Const15 collapses and u_i is left free across the CDC window. So

    max{ u_i : LP }  >=  max{ u_i : any true solution }

and the resulting M dominates the supremum by construction. The projected feasible set of the
model with these M values EQUALS the true (26)-feasible set. Set containment, not sampling.

NO CIRCULARITY. The bounding LP is built with hardSingleTransfer=False, so the (26) rows we are
sizing are ABSENT from it. Including them would use the quantity being derived. Removing them only
enlarges the region, which keeps the bound conservative -- the safe direction.

COST is 2n LPs, not n^2: one max and one min per u_i, combined pairwise afterwards. 60 at |C|=30,
200 at |C|=100.

    python analysis/obbt_bigm.py --cell C201 --size 30
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


def box_bounds(p):
    """The bounds derivable WITHOUT an LP, valid for every customer whether or not it transfers.

    Every vip-weighted term in Const13 and Const15 vanishes at v_i = 0, so nothing satellite-
    dependent may appear here. These are kept as an independent cross-check on the LP: an LP bound
    may never be looser than its box counterpart, and if it is, the LP is wrong or the (26) rows
    were not actually removed.
    """
    nd, CDC = p.nodes, p.CDC
    ub = {i: nd[CDC].latest for i in p.customers}
    lb = {i: max(nd[CDC].earliest, nd[i].earliest + nd[i].serviceTime) for i in p.customers}
    return lb, ub


def lp_bounds(p, threads=1, verbose=False):
    """(lb, ub) per u_i from the LP relaxation of the model WITHOUT the (26) rows."""
    from gurobipy import GRB
    from joint_model_gurobi import build_joint_model_gurobi

    p.hardSingleTransfer = False          # the rows being sized are absent from the bounding LP
    H = build_joint_model_gurobi(p)
    m = H["m"]
    # FLUSH PENDING CHANGES BEFORE RELAXING. The builder calls update() at :210 and then adds the
    # objective-linking constraint and the objective itself at :211-212, so relax() would copy a
    # STALE model and Gurobi warns about it. Dropping a constraint only enlarges the region, so
    # the bound would still have been conservative -- but "still valid by luck" is not the
    # standard this file exists to meet.
    m.update()
    r = m.relax()                          # integrality dropped -> superset of the true region
    r.Params.OutputFlag = 0
    r.Params.Threads = threads

    lb, ub = {}, {}
    t0 = time.time()
    for n, i in enumerate(H["Customers"], 1):
        v = r.getVarByName("u[%d]" % i)
        if v is None:
            raise RuntimeError("u[%d] not found in the relaxed model" % i)
        for sense, store in ((GRB.MAXIMIZE, ub), (GRB.MINIMIZE, lb)):
            r.setObjective(v, sense)
            r.optimize()
            if r.Status != GRB.OPTIMAL:
                # An unbounded or failed direction means NO valid bound was proved. Refuse rather
                # than fall back to something that looks like one.
                raise RuntimeError("bounding LP for u[%d] returned status %s" % (i, r.Status))
            store[i] = r.ObjVal
        if verbose and n % 10 == 0:
            print("   %d/%d u-bounds  (%.0fs)" % (n, len(H["Customers"]), time.time() - t0),
                  flush=True)
    return lb, ub


def build_M(p, lp_lb, lp_ub):
    """M_ij = max(ub_i - lb_j, ub_j - lb_i) + tau, over the LP-proved bounds."""
    TD = p.TransferDuration
    C = list(p.customers)
    M = {}
    for a in range(len(C)):
        for b in range(a + 1, len(C)):
            i, j = C[a], C[b]
            M[(i, j)] = max(lp_ub[i] - lp_lb[j], lp_ub[j] - lp_lb[i]) + TD
    return M


def assert_valid(M, lp_lb, lp_ub, box_lb, box_ub, TD):
    """Refuse to hand back anything that cannot be shown to dominate the supremum."""
    errs = []
    for (i, j), v in M.items():
        need = max(lp_ub[i] - lp_lb[j], lp_ub[j] - lp_lb[i]) + TD
        if v < need - 1e-9:
            errs.append("M[%s,%s] = %.6f < required %.6f" % (i, j, v, need))
    for i in lp_ub:
        if lp_ub[i] > box_ub[i] + 1e-6:
            errs.append("u[%s] LP ub %.6f exceeds box ub %.6f -- LP is wrong or (26) rows "
                        "were not removed" % (i, lp_ub[i], box_ub[i]))
        if lp_lb[i] < box_lb[i] - 1e-6:
            errs.append("u[%s] LP lb %.6f below box lb %.6f" % (i, lp_lb[i], box_lb[i]))
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="C201")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--threads", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)

    from analysis.k_comparison import k_proximity
    from build_instance import build
    import statistics as st

    prox = k_proximity(a.size)
    p = build(a.cell, a.size, wls=0.1, tau="formula", proximity=prox)
    nd, CDC, TD = p.nodes, p.CDC, p.TransferDuration
    M_global = (nd[CDC].latest - nd[CDC].earliest) + TD + 1.0

    print("cell %s  n%d  proximity %s  tau %s" % (a.cell, a.size, prox, TD))
    print("global M currently in use: %.2f" % M_global)
    print()

    box_lb, box_ub = box_bounds(p)
    M_box = build_M(p, box_lb, box_ub)

    print("solving %d bounding LPs (2 per customer), (26) rows ABSENT ..."
          % (2 * len(p.customers)), flush=True)
    t0 = time.time()
    lp_lb, lp_ub = lp_bounds(p, threads=a.threads, verbose=True)
    lp_s = time.time() - t0
    M_lp = build_M(p, lp_lb, lp_ub)

    errs = assert_valid(M_lp, lp_lb, lp_ub, box_lb, box_ub, TD)
    print()
    if errs:
        print("REFUSING -- validity assertions failed:")
        for e in errs[:10]:
            print("   " + e)
        return 3
    print("VALIDITY ASSERTIONS PASSED: every M_ij dominates its LP-proved supremum, and every LP "
          "bound lies inside its box counterpart.")
    print()

    def stats(M):
        v = list(M.values())
        return max(v), st.median(v), min(v)

    for tag, M in (("box  ", M_box), ("LP   ", M_lp)):
        mx, md, mn = stats(M)
        print("%s M_ij: max %9.2f  median %9.2f  min %9.2f   | vs global: median %5.1f%% tighter"
              % (tag, mx, md, mn, (M_global - md) / M_global * 100))
    print()
    print("LP solve time: %.1fs for %d LPs" % (lp_s, 2 * len(p.customers)))

    out = os.path.join(OUTDIR, "obbt_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped({"cell": a.cell, "size": a.size, "proximity": prox, "tau": TD,
               "M_global": M_global,
               "u_lb_lp": lp_lb, "u_ub_lp": lp_ub,
               "u_lb_box": box_lb, "u_ub_box": box_ub,
               "M_lp_stats": dict(zip(("max", "median", "min"), stats(M_lp))),
               "M_box_stats": dict(zip(("max", "median", "min"), stats(M_box))),
               "lp_seconds": round(lp_s, 1),
               "validity": "every M_ij >= max(ub_i-lb_j, ub_j-lb_i) + tau over LP-proved bounds; "
                           "LP relaxation is a superset of the integer-feasible set, so the bound "
                           "dominates the true supremum and the disjunction cuts nothing"}, __file__),
              open(out, "w"), indent=1, default=str)
    print("-> %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
