r"""Area 4 (production pricer) -- validate the numba FastPricer the frozen grid actually used (d799).

enum_price_check tested tep_pricer.Pricer; the reported grid ran tep_pricer_njit.FastPricer
(frzdual2 records carry fast_pricer.on = true). This script compares BOTH pricers against the
independent trip enumeration, checking the minimum REDUCED COST (scored by the master's exact
best_variant), not a final LP objective.

Round-2 referee asks, each addressed here (d806):
  * DOMINANCE ON vs OFF. The ESPPRC label dominance (tep_pricer_njit.py:172-191) is always on; the
    `no_prune` flag toggles the completion-bound prune (:139-148). We run BOTH settings against the
    independent enumeration at a tight rc_cut (1e-9) so the completion-bound prune is actually
    exercised, and check they agree with each other and with the enumeration -- so neither form of
    pruning discards an improving column.
  * EXHAUSTION IS A FAILURE, NOT A PASS. A run that hits its label cap proved nothing; it is recorded
    as a problem, never counted as agreement.
  * A GENUINELY EXTRA ng UNIVERSE. ng=2 admits non-elementary walks the elementary enumeration omits;
    the script asserts at least one tested ng config has strictly more walks than elementary trips,
    so the ng arm is not vacuously equal to the elementary one.
  * ABSOLUTE tolerance (1e-6), not relative: a relative test hides a 1e-6 miss on an rc of order 1.
  * DUALS NEAR THE -eps THRESHOLD. A uniform shift of the customer duals drives the minimum reduced
    cost to a sweep of targets straddling -1e-6, and agreement is checked there, where a
    certificate decision ("no column below -eps") is most delicate.

A tractable sub-instance keeps the enumeration exhaustive.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verifier3 as V
from k_comparison import k_proximity
from tep_cg_bound import Master, default_delta
from tep_pricer import Pricer
from tep_pricer_njit import FastPricer
from enum_price_check import enumerate_trips

TOL = 1e-6              # ABSOLUTE agreement, per the referee
LABEL_CAP = 5_000_000
RC_CUT = 1e-9          # tight: activates the completion-bound prune, still captures every rc < 0


def duals_from_seed(inst, delta, customers, seed_trips):
    M = Master(inst, delta, threads=1, primal=False, customers=customers)
    for s in seed_trips:
        for (L, b, p, ba) in M.variants(list(s)):
            M.add_column(list(s), L, b, p, ba)
    M.m.update(); M.solve()
    return M, M.duals()


def exhaustive(M, trips, duals):
    """(min reduced cost, achieving sequence, its length) over the given trip universe, via the
    master's exact best_variant. Min floored at 0.0 (no improving column -> 0)."""
    pi, mu_src, mu_pre, mu_post = duals
    best, arg, ln = 0.0, None, 0
    for seq in trips:
        var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
        if var is not None and var[0] < best:
            best, arg, ln = var[0], seq, len(seq)
    return best, arg, ln


def tight_col(M, trips, duals):
    """(reduced cost, sequence) of the lowest-rc column -- even if non-negative -- over the universe.
    Used to build near-threshold duals by perturbing a single customer dual of this column."""
    pi, mu_src, mu_pre, mu_post = duals
    best = None
    for seq in trips:
        var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
        if var is not None and (best is None or var[0] < best[0]):
            best = (var[0], seq)
    return best


def pricer_min(klass, M, inst, customers, duals, ng, inits_on, prune):
    """(min reduced cost, exhausted). prune=True runs the completion-bound prune ON (no_prune=False).
    The minimum is rescored from the returned sequences by the exact best_variant."""
    pi, mu_src, mu_pre, mu_post = duals
    pr = klass(inst, scale=M.tc, table1=True, ng=(ng or None), customers=customers)
    entry, exit_, exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)
    inits = M.start_labels(pi, mu_src, mu_post) if inits_on else None
    found, nlab, exh = pr.price(pi, keep=10 ** 9, rc_cut=RC_CUT, entry=entry, exit=exit_,
                                exit_fn=exit_fn, label_cap=LABEL_CAP, no_prune=(not prune), inits=inits)
    best = 0.0
    for rc0, cost, seq, tag in found:
        var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
        if var is not None and var[0] < best:
            best = var[0]
    return best, bool(exh)


def agree(a, b):
    return abs(a - b) < TOL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="R205")   # R205 admits non-elementary ng walks (the referee's example)
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--n-cust", type=int, default=6)
    ap.add_argument("--ng", default="3,2,1")    # several ng memories; >=1 must exceed elementary
    ap.add_argument("--maxlen", type=int, default=6)
    a = ap.parse_args()
    inst = V.load_instance(a.cell, a.size, k_proximity(a.size))
    customers = list(inst.customers)[:a.n_cust]
    delta = default_delta(inst)
    probe = Master(inst, delta, threads=1, primal=False, customers=customers)
    elem = enumerate_trips(probe)
    ng_vals = [int(x) for x in str(a.ng).split(",") if x]
    ng_univ = {}
    for g in ng_vals:
        prng = FastPricer(inst, scale=probe.tc, table1=True, ng=g, customers=customers)
        ng_univ[g] = enumerate_trips(probe, ng_nbr=getattr(prng, "nbr", None), maxlen=a.maxlen)
    extra = {g: len(w) for g, w in ng_univ.items() if len(w) > len(elem)}
    print("cell=%s |C|=%d delta=%.0f  elem=%d trips; ng-walks %s"
          % (a.cell, len(customers), delta, len(elem),
             ", ".join("ng%d=%d" % (g, len(w)) for g, w in ng_univ.items())), flush=True)

    rows, problems = [], []
    nchk = 0

    def record(arm, label, ex, py, py_exh, fa, fa_exh):
        """Compare a Pricer min (py, may be None) and a FastPricer min (fa) to the exhaustive ex."""
        nonlocal nchk
        ok = True
        for name, val, exh in (("Pricer", py, py_exh), ("FastPricer", fa, fa_exh)):
            if val is None:
                continue
            nchk += 1
            if exh:
                problems.append("%s/%s: %s EXHAUSTED its label cap -- inconclusive" % (arm, label, name))
                ok = False
            elif not agree(ex, val):
                problems.append("%s/%s: %s=%.8f != exhaustive=%.8f (abs %.1e)"
                                % (arm, label, name, val, ex, abs(ex - val)))
                ok = False
        rows.append((arm, label, ex, py, fa, ok))

    seeds = [elem[:1], elem[:2], elem[:3]]
    # ---- elementary arm: both pricers, dominance (completion-bound prune) on and off -------------
    for si, seed in enumerate(seeds):
        M, duals = duals_from_seed(inst, delta, customers, seed)
        ex, _, _ = exhaustive(M, elem, duals)
        for inits_on in (False, True):
            for prune in (True, False):
                py, pye = pricer_min(Pricer, M, inst, customers, duals, 0, inits_on, prune)
                fa, fae = pricer_min(FastPricer, M, inst, customers, duals, 0, inits_on, prune)
                record("elem", "seed%d inits=%s prune=%s" % (si, inits_on, prune), ex, py, pye, fa, fae)

    # ---- ng arm: FastPricer over each ng walk universe, prune on and off -------------------------
    for g in ng_vals:
        walks = ng_univ[g]
        for si, seed in enumerate(seeds):
            M, duals = duals_from_seed(inst, delta, customers, seed)
            exn, _, _ = exhaustive(M, walks, duals)
            for inits_on in (False, True):
                for prune in (True, False):
                    fan, fae = pricer_min(FastPricer, M, inst, customers, duals, g, inits_on, prune)
                    record("ng%d" % g, "seed%d inits=%s prune=%s" % (si, inits_on, prune),
                           exn, None, None, fan, fae)

    # ---- near-threshold arm: perturb one CONVERGED dual so the minimum rc straddles -eps ---------
    # Start from converged duals (all elementary columns in the master); at convergence the lowest rc
    # is ~0. Decreasing a single customer dual of that column by a tiny amount drops its rc to a
    # chosen target near -eps, without the length-dependent overshoot a uniform shift would cause.
    Mc, dc = duals_from_seed(inst, delta, customers, elem)
    tc = tight_col(Mc, elem, dc)
    if tc is not None:
        r_star, s_star = tc
        cstar = s_star[0]
        visits = list(s_star).count(cstar)
        for tgt in (-2.0e-6, -1.2e-6, -1.0e-6, -8.0e-7, -5.0e-7, 0.0, 5.0e-7):
            pi2 = dict(dc[0])
            # rc(s_star) = r_star - delta*visits when pi[cstar] rises by delta; set it to tgt
            pi2[cstar] = pi2[cstar] + (r_star - tgt) / visits
            d = (pi2, dc[1], dc[2], dc[3])
            ex, _, _ = exhaustive(Mc, elem, d)
            for prune in (True, False):
                py, pye = pricer_min(Pricer, Mc, inst, customers, d, 0, True, prune)
                fa, fae = pricer_min(FastPricer, Mc, inst, customers, d, 0, True, prune)
                record("thresh", "tgt=%+.1e min=%+.2e prune=%s" % (tgt, ex, prune), ex, py, pye, fa, fae)

    # ---- the ng arm must not be vacuous ----------------------------------------------------------
    if not extra:
        problems.append("ng arm VACUOUS: no tested ng memory (%s) admits more walks than the %d "
                        "elementary trips -- the ng dominance is never exercised beyond elementary"
                        % (ng_vals, len(elem)))

    for arm, label, ex, py, fa, ok in rows:
        print("  %-7s %-32s exhaustive=%+.6f  Pricer=%s  FastPricer=%+.6f  %s"
              % (arm, label, ex, ("%+.6f" % py) if py is not None else "   --   ", fa,
                 "OK" if ok else "FAIL"))

    lines = ["# Area 4 (production pricer) -- FastPricer validation", "",
             "> Evidence for the referee's \"validate the production implementation\" requirement",
             "> (d799; round-2 corrections d806). The frozen grid ran the numba `FastPricer`; here it is",
             "> compared, with the Python `Pricer`, against the independent trip enumeration, checking the",
             "> minimum reduced cost (via the exact `best_variant`), not an LP objective. Each run is made",
             "> with the completion-bound prune ON and OFF (`no_prune`), so neither it nor the",
             "> always-on label dominance may discard an improving column; a run that EXHAUSTS its label",
             "> cap is a failure, not a pass; agreement is ABSOLUTE to %.0e; and a separate arm shifts the" % TOL,
             "> duals so the minimum reduced cost straddles the $-\\varepsilon$ certificate threshold.", "",
             "cell %s, |C|=%d, delta=%.0f; %d elementary trips; ng walks %s."
             % (a.cell, len(customers), delta, len(elem),
                ", ".join("ng%d=%d" % (g, len(w)) for g, w in ng_univ.items())),
             "ng universes strictly larger than elementary: %s."
             % (", ".join("ng%d (%d walks)" % (g, n) for g, n in extra.items()) if extra else "NONE"),
             "",
             "| arm | configuration | exhaustive min rc | Pricer | FastPricer | agree |",
             "|-----|---------------|-------------------|--------|-----------|-------|"]
    for arm, label, ex, py, fa, ok in rows:
        lines.append("| %s | %s | %+.6f | %s | %+.6f | %s |"
                     % (arm, label, ex, ("%+.6f" % py) if py is not None else "---", fa,
                        "yes" if ok else "**NO**"))
    lines += ["", ("**FastPricer and Pricer match the independent exhaustive minimum reduced cost on "
                   "every dual vector, start-state, and prune setting tested -- including ng universes "
                   "strictly larger than elementary and duals at the $-\\varepsilon$ threshold -- with no "
                   "search exhausted.**" if not problems else "**DISCREPANCIES:**")]
    for p in problems:
        lines.append("- " + p)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "validation", "AREA4_FASTPRICER_AUDIT.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\nwrote %s (%d checks, %d problem(s))" % (os.path.relpath(out, os.getcwd()), nchk, len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
