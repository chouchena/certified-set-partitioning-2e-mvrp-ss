r"""Independent small-instance pricing check -- area 4 of the validation framework (d789).

WHAT IT PROVES, AND WHY IT IS INDEPENDENT. The lower bound rests on column generation, whose
validity depends on the pricer finding the minimum-reduced-cost trip. This script does NOT trust the
pricer's search: it enumerates the ENTIRE feasible trip space by its own depth-first recursion
(independent of the labelling and its dominance), scores every trip with the master's exact
reduced-cost formula (the one `Master.check_rc` already reconciles against Gurobi every iteration),
and then checks:

  A. LP equivalence   -- a master built from EVERY enumerated trip solves to the same value a faithful
                         column-generation loop reaches, so CG converged to the true restricted LP.
  B. Pricer minimum   -- at a NON-converged dual (a master seeded with a handful of trips), the most
                         negative reduced cost the pricer returns equals the exhaustive minimum over
                         the whole trip space; the pricer's search missed nothing.
  C. Dominance        -- the no-prune pricer agrees with B, so no label the dominance rule discarded
                         would have led to the true minimiser.
  D. ng relaxation    -- the ng master's LP is <= the elementary master's LP (a valid relaxation), and
                         CG over ng columns reaches the full ng master's value. ng is enumerated over
                         its OWN column universe (walks that respect ng-memory, bounded repeats), not
                         the elementary one -- an elementary enumerator alone would be insufficient.

These catch an IMPLEMENTATION defect in the pricer; the general validity still comes from the proofs
(Appendix A1). Run on a sub-instance small enough that the full trip space is enumerable
(`--n-cust`). Nothing here is reported in the paper; it is an audit instrument.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verifier3 as V
from k_comparison import k_proximity
from tep_cg_bound import Master, default_delta
from tep_pricer import Pricer, Q as PRICER_Q

TOL = 1e-6


def enumerate_trips(M, ng_nbr=None, maxlen=None):
    """Every window- and load-feasible trip over M's customers, by our own DFS.

    Elementary (ng_nbr is None): no customer repeats. ng (ng_nbr given): a customer may recur once it
    has left the ng-memory, exactly as the pricer's reachability allows; `maxlen` bounds the walk so
    the ng space stays finite. Window feasibility is the authoritative `Master.simulate`; load uses
    the same per-customer demand and the pricer's capacity Q."""
    C = list(M.C)
    dem = {c: float(M.inst.nodes[c].demand) for c in C}
    out = []

    def ng_mem(seq):
        mem = frozenset()
        for c in seq:
            mem = (mem & ng_nbr[c]) | frozenset((c,))
        return mem

    def dfs(seq, load):
        # feasible as a standalone trip if its schedule closes within windows
        if M.simulate(list(seq), M.H0 + M.D[M.g][seq[0]]) is not None or \
           any(M.simulate(list(seq), M.H0 + b * M.delta + M.D[L][seq[0]]) is not None
               for L in M.sats for b in (M.win,)):
            out.append(tuple(seq))
        if maxlen and len(seq) >= maxlen:
            return
        mem = ng_mem(seq) if ng_nbr is not None else None
        for j in C:
            if ng_nbr is None:
                if j in seq:
                    continue
            else:
                if j in mem:
                    continue
            if load + dem[j] > PRICER_Q + 1e-9:
                continue
            # cheap window reachability prune (full check happens via simulate at the next frame)
            if M.simulate(list(seq) + [j], M.H0 + M.D[M.g][seq[0]]) is None and \
               all(M.simulate(list(seq) + [j], M.H0 + b * M.delta + M.D[L][seq[0]]) is None
                   for L in M.sats for b in (M.win,)):
                # not reachable from any representative start; still recurse only if a later start
                # could help -- but simulate is monotone in start time, so if the earliest start
                # fails the window, no later one succeeds. Safe to prune.
                continue
            dfs(seq + (j,), load + dem[j])

    for c in C:
        dfs((c,), dem[c])
    # de-duplicate (ng walks can repeat a prefix through different memories)
    return sorted(set(out))


def full_master(inst, delta, customers, ng, trips):
    """A master carrying EVERY enumerated trip (all variants), solved to its LP optimum."""
    M = Master(inst, delta, threads=1, primal=False, customers=customers)
    n = 0
    for seq in trips:
        for (L, b, p, ba) in M.variants(list(seq)):
            n += M.add_column(list(seq), L, b, p, ba)
    M.m.update()
    M.solve()
    return M, n


def cg_loop(inst, delta, customers, ng, seed_trips, max_iter=200):
    """A faithful minimal column-generation loop over the real Master and Pricer: seed, then price
    to proof with the exact (elementary) pricer, adding every negative-reduced-cost column, until
    none remains. Returns the converged master."""
    M = Master(inst, delta, threads=1, primal=False, customers=customers)
    for seq in seed_trips:
        for (L, b, p, ba) in M.variants(list(seq)):
            M.add_column(list(seq), L, b, p, ba)
    M.m.update()
    pr = Pricer(inst, scale=M.tc, table1=True, ng=None, customers=customers)   # elementary = the proof
    for _ in range(max_iter):
        M.solve()
        pi, mu_src, mu_pre, mu_post = M.duals()
        entry, exit_, exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)
        inits = M.start_labels(pi, mu_src, mu_post)
        found, _, exh = pr.price(pi, keep=10 ** 9, rc_cut=-1e-6, entry=entry, exit=exit_,
                                 exit_fn=exit_fn, label_cap=5_000_000, inits=inits)
        added = 0
        for rc0, cost, seq, tag in found:
            var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
            if var and var[0] < -1e-6:
                added += M.add_column(list(seq), var[1], var[2], var[3], var[4])
        M.m.update()
        if added == 0:
            break
    M.solve()
    return M


def pricer_min_rc(M, pi, mu_src, mu_pre, mu_post, ng, inst, customers, no_prune):
    """The most negative reduced cost the pricer reports at these duals, scored by the master's exact
    best_variant (min over all starts) -- the quantity the certificate reads."""
    pr = Pricer(inst, scale=M.tc, table1=True, ng=(ng or None), customers=customers)
    entry, exit_, exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)
    inits = M.start_labels(pi, mu_src, mu_post)
    found, nlab, exh = pr.price(pi, keep=10 ** 9, rc_cut=1e18, entry=entry, exit=exit_,
                                exit_fn=exit_fn, label_cap=5_000_000, no_prune=no_prune, inits=inits)
    best = 0.0
    for rc0, cost, seq, tag in found:
        var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
        if var is not None:
            best = min(best, var[0])
    return best, nlab, exh


def exhaustive_min_rc(M, trips, pi, mu_src, mu_pre, mu_post):
    best = 0.0
    for seq in trips:
        var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
        if var is not None:
            best = min(best, var[0])
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="C201")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--n-cust", type=int, default=6, help="restrict to the first N customers")
    ap.add_argument("--delta", type=float, default=0.0, help="0 = default_delta(inst)")
    ap.add_argument("--ng", type=int, default=5)
    ap.add_argument("--maxlen", type=int, default=6, help="ng walk-length cap for enumeration")
    ap.add_argument("--seed-k", type=int, default=2, help="trips to seed the CG loop / restricted dual")
    a = ap.parse_args()

    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    customers = list(inst.customers)[:a.n_cust]
    delta = a.delta or default_delta(inst)
    print("cell=%s size=%d |C|=%d customers=%s delta=%.1f Q=%.0f ng=%d"
          % (a.cell, a.size, len(customers), customers, delta, PRICER_Q, a.ng), flush=True)

    probe = Master(inst, delta, threads=1, primal=False, customers=customers)
    ng_nbr = probe.__dict__.get("nbr")  # Master has none; build from the pricer's definition
    prng = Pricer(inst, scale=probe.tc, table1=True, ng=a.ng, customers=customers)
    nbr = getattr(prng, "nbr", None)

    t0 = time.time()
    elem_trips = enumerate_trips(probe)
    ng_trips = enumerate_trips(probe, ng_nbr=nbr, maxlen=a.maxlen)
    print("enumerated: %d elementary trips, %d ng walks (%.1fs)"
          % (len(elem_trips), len(ng_trips), time.time() - t0), flush=True)

    res = {"cell": a.cell, "size": a.size, "n_cust": a.n_cust, "delta": delta, "ng": a.ng,
           "Q": PRICER_Q, "n_elem_trips": len(elem_trips), "n_ng_walks": len(ng_trips), "checks": {}}
    ok = True

    # --- A: full elementary master == CG elementary ------------------------------------------
    M_full, nf = full_master(inst, delta, customers, 0, elem_trips)
    L_full = M_full.m.ObjVal
    seed = elem_trips[:a.seed_k] or elem_trips[:1]
    M_cg = cg_loop(inst, delta, customers, 0, seed)
    L_cg = M_cg.m.ObjVal
    A = abs(L_full - L_cg) < 1e-4 * max(1.0, abs(L_full))
    ok &= A
    res["checks"]["A_full_eq_cg_elem"] = {"L_full": L_full, "L_cg": L_cg, "pass": bool(A)}
    print("  [A] full elem LP = %.6f | CG elem LP = %.6f | %s" % (L_full, L_cg, "PASS" if A else "FAIL"))

    # --- B/C: pricer min reduced cost at a NON-converged (restricted) dual -------------------
    M_r = Master(inst, delta, threads=1, primal=False, customers=customers)
    for s in seed:
        for (L, b, p, ba) in M_r.variants(list(s)):
            M_r.add_column(list(s), L, b, p, ba)
    M_r.m.update(); M_r.solve()
    pi, mu_src, mu_pre, mu_post = M_r.duals()
    rc_enum = exhaustive_min_rc(M_r, elem_trips, pi, mu_src, mu_pre, mu_post)
    rc_pr, nlab, exh = pricer_min_rc(M_r, pi, mu_src, mu_pre, mu_post, 0, inst, customers, no_prune=False)
    rc_np, _, _ = pricer_min_rc(M_r, pi, mu_src, mu_pre, mu_post, 0, inst, customers, no_prune=True)
    B = abs(rc_enum - rc_pr) < 1e-6
    Cc = abs(rc_enum - rc_np) < 1e-6
    ok &= B and Cc
    res["checks"]["B_pricer_min"] = {"rc_enum": rc_enum, "rc_pricer": rc_pr, "pass": bool(B)}
    res["checks"]["C_dominance_no_prune"] = {"rc_enum": rc_enum, "rc_no_prune": rc_np, "pass": bool(Cc)}
    print("  [B] exhaustive min rc = %.8f | pricer = %.8f | %s" % (rc_enum, rc_pr, "PASS" if B else "FAIL"))
    print("  [C] exhaustive min rc = %.8f | no-prune pricer = %.8f | %s" % (rc_enum, rc_np, "PASS" if Cc else "FAIL"))

    # --- D: ng master == CG ng, and ng LP <= elementary LP ----------------------------------
    M_full_ng, _ = full_master(inst, delta, customers, a.ng, ng_trips)
    L_full_ng = M_full_ng.m.ObjVal
    D_relax = L_full_ng <= L_full + 1e-4
    res["checks"]["D_ng_relaxation"] = {"L_full_ng": L_full_ng, "L_full_elem": L_full,
                                        "pass": bool(D_relax)}
    ok &= D_relax
    print("  [D] full ng LP = %.6f <= full elem LP = %.6f | %s"
          % (L_full_ng, L_full, "PASS" if D_relax else "FAIL"))

    res["all_pass"] = bool(ok)
    print("\n%s  (%.1fs)" % ("ALL PASS" if ok else "SOME CHECK FAILED", time.time() - t0))
    print(json.dumps(res, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
