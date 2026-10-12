"""DSSR — decremental state-space relaxation, to earn the ELEMENTARY certificate on the nine
n50 R cells that exhaust the elementary pricer's label cap.

    python analysis/dssr_certify.py R202 --size 50          # smoke: logs/smoke/dssr_<cell>_n<size>.json
    python analysis/dssr_certify.py R202 --size 50 --bank --rt-class diagnostic
                                  # bank the bound at runs/oracle/tep_cg_bound_R202_n50.json; wall recorded, not quotable
    python analysis/dssr_certify.py R202 --size 50 --bank --rt-class submission
                                  # the RT pass: refuses to start unless solo at 4 threads; may replace the
                                  # diagnostic-class artifact only at the same value to 1e-6

WHY THIS AND NOT A BIGGER LABEL CAP. d558: the elementary pass keys labels on (last,
frozenset(visited)) and dominates only within the identical set, so it enumerates reachable
visited-sets and hits 3,000,001 on nine R cells at |C|=50. d615: releasing the cap certified six
of eight at 545 to 6,396 s -- two over the 1500 s budget -- and two died on memory, 17.9 GB
resident. "Raise the cap is over as a strategy on this host." OPEN_GAPS G1 names two fixes:
superset dominance, or DSSR. This is DSSR.

THE IDEA. The ng pricer converges on all nine cells cheaply -- they are ng-certified today -- but
ng admits routes that revisit a customer once it leaves the memory, so "no ng column prices out"
certifies only LP(R_ng) <= LP(R_e). DSSR keeps the ng pricer and grows a CRITICAL SET C* of
customers that are never forgotten: a customer in C* stays in every label's memory, so no route
may revisit it. Price; if the negative columns found are elementary, add them; if one repeats a
customer, put that customer in C* and price again at the SAME duals; stop when nothing prices
out. C* can only grow, to at most |C|, at which point the pricer IS elementary -- but d435
measured the critical set at n100 as two distinct customers among the top-50 candidates, so it
should stop long before.

WHY THE RESULT IS THE STRONG CERTIFICATE. At termination no ng(C*) column has rc < -eps, and
R_e is a subset of R_ng(C*), so no ELEMENTARY column prices out either. The master's pool is kept
ELEMENTARY-ONLY -- non-elementary columns from the ng phase are switched off (UB = 0) before
DSSR starts, and DSSR adds only elementary columns -- so the restricted LP is over R_e columns
and its duals are feasible for the complete R_e dual: LP_restricted = LP(R_e). That is exactly
L-TEP-cert's hypothesis, and bound_certificate.certified() accepts it through the explicit
`certificate` field, which this writes with the evidence beside it.

WHAT IS AND IS NOT TOUCHED. tep_pricer.py and tep_cg_bound.py are imported, never edited --
eight trial processes hold them open, and editing a module mid-run is what confounded the hard-
cell run this morning. The critical set is applied by widening each customer's ng neighbourhood
on the Pricer INSTANCE (nbr[i] |= C*), which is the definition of DSSR and needs no module change.

ACCEPTANCE, fixed before the first run. (1) On a cell that already holds an elementary
certificate -- RC204 n50, 233,583 states -- DSSR must return the SAME lp_street to 1e-6 with
fewer labels. A different value refutes this module, not the corpus. (2) On each of the nine, the
certified value may not sit BELOW the ng value on disk: a stronger certificate cannot lower a
bound, so a decrease is a defect and the run says so. (3) Under 1500 s solo at 4 threads, which
is the target.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

EPS = 1e-6


def is_elementary(seq):
    return len(set(seq)) == len(seq)


def repeated(seq):
    seen, rep = set(), set()
    for c in seq:
        if c in seen:
            rep.add(c)
        seen.add(c)
    return rep


def dssr(M, ng, label_cap, threads, log, max_rounds=200, verify_out=None):
    """Returns (certified, rounds, critical_set, labels_total, added_total, lp).

    `verify_out`, when a dict is passed, receives the exhaustive verification pass's evidence:
    how many candidates it saw, how many the PRUNED search had missed, its labels and its wall.
    """
    from tep_pricer import Pricer
    C = list(M.C)
    Cstar = set()
    labels_total = added_total = 0
    rounds = 0
    pr = None
    base_nbr = None

    def rebuild():
        nonlocal pr, base_nbr
        pr = Pricer(M.inst, scale=M.tc, table1=True, ng=ng, customers=None)
        if base_nbr is None:
            base_nbr = dict(pr.nbr)
        # DSSR: a critical customer is remembered by EVERY state, so it can never be revisited.
        pr.nbr = {i: base_nbr[i] | frozenset(Cstar) for i in C}

    rebuild()
    while rounds < max_rounds:
        rounds += 1
        M.solve()
        pi, mu_src, mu_pre, mu_post = M.duals()
        entry, exit_, exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)
        t0 = time.time()
        # START-STATE PRICING IS NOT OPTIONAL HERE, AND THE REASON IS DOMINANCE, NOT PRECISION.
        # Without `inits` the label cost carries the legacy entry leg -- a MINIMUM over every
        # start node -- so the pricer minimises an UNDERESTIMATE of the reduced cost while this
        # loop accepts or rejects candidates on the EXACT value from M.best_variant. The two
        # metrics disagree, and dominance is applied in the wrong one: a label that is dominated
        # on the understated cost can be the only one whose EXACT cost is negative. Its dominator
        # is then thrown away by the exact filter for having rc >= -EPS, the dominated route was
        # never generated, and the loop sees nothing and certifies.
        #
        # Witness, R206 n50 from an under-converged pool: the elementary route
        # [8, 18, 6, 40, 21, 41] has exact rc -8.7186 at the terminal duals, survives succ,
        # memory, window and capacity, and was not returned. DSSR certified 1220.373500 against
        # a true LP(R_e) of 1216.866234. Understating is safe for a FILTER and unsafe for
        # DOMINANCE; with `inits` the entry leg is exact (d437, and d626 measured the residual
        # slack at 0 on 19 of 19), so the pricer ranks labels by the same quantity the loop judges.
        inits = M.start_labels(pi, mu_src, mu_post)
        found, nlab, exhausted = pr.price(pi, maxlen=None, keep=10 ** 9, rc_cut=-EPS,
                                          entry=entry, exit=exit_, exit_fn=exit_fn,
                                          label_cap=label_cap, inits=inits)
        labels_total += nlab
        if exhausted:
            log("  round %d: EXHAUSTED at %d labels -- no certificate" % (rounds, nlab))
            return False, rounds, Cstar, labels_total, added_total, M.m.ObjVal
        neg_elem, neg_rep = [], set()
        for rc0, cost, seq, *_ in found:
            var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
            if not var or var[0] >= -EPS:
                continue
            if is_elementary(seq):
                neg_elem.append((var[0], list(seq), var))
            else:
                neg_rep |= repeated(seq)
        if not neg_elem and not neg_rep:
            # THE STOPPING TEST IS THE EXHAUSTIVE PASS, NOT THE PRUNED ONE. The pruned search
            # drives the iterations; it may not have reached a column that prices out, and
            # treating its silence as a proof is what produced certificates ABOVE LP(R_e) from
            # under-converged pools (see the module header's table).
            tv = time.time()
            found_v, nlab_v, exh_v = pr.price(pi, maxlen=None, keep=10 ** 9, rc_cut=-EPS,
                                              entry=entry, exit=exit_, exit_fn=exit_fn,
                                              label_cap=label_cap, no_prune=True, inits=inits)
            labels_total += nlab_v
            secs_v = time.time() - tv
            if exh_v:
                log("  round %d: VERIFICATION pass EXHAUSTED at %d labels -- no certificate "
                    "(an incomplete search establishes nothing)" % (rounds, nlab_v))
                if verify_out is not None:
                    verify_out.update(ran=True, exhausted=True, certified=False,
                                      labels=int(nlab_v), secs=round(secs_v, 2))
                return False, rounds, Cstar, labels_total, added_total, M.m.ObjVal
            for rc0, cost, seq, *_ in found_v:
                var = M.best_variant(list(seq), pi, mu_src, mu_pre, mu_post)
                if not var or var[0] >= -EPS:
                    continue
                if is_elementary(seq):
                    neg_elem.append((var[0], list(seq), var))
                else:
                    neg_rep |= repeated(seq)
            if not neg_elem and not neg_rep:
                log("  round %d: %d labels, %d candidates pruned / %d exhaustive, none prices out "
                    "-> CERTIFIED  |C*|=%d  (verification %.1fs)"
                    % (rounds, nlab, len(found), len(found_v), len(Cstar), secs_v))
                if verify_out is not None:
                    verify_out.update(ran=True, exhausted=False, certified=True,
                                      candidates_pruned=len(found), candidates_exhaustive=len(found_v),
                                      missed_by_prune=0, labels=int(nlab_v), secs=round(secs_v, 2))
                return True, rounds, Cstar, labels_total, added_total, M.m.ObjVal
            log("  round %d: the pruned search found nothing but the EXHAUSTIVE pass found %d "
                "elementary and %d repeating -- the pruned silence was not a proof (%.1fs)"
                % (rounds, len(neg_elem), len(neg_rep), secs_v))
            if verify_out is not None:
                verify_out.update(ran=True, exhausted=False, certified=False,
                                  candidates_pruned=len(found), candidates_exhaustive=len(found_v),
                                  missed_by_prune=len(neg_elem) + len(neg_rep),
                                  labels=int(nlab_v), secs=round(secs_v, 2))
        added = 0
        if neg_elem:
            neg_elem.sort(key=lambda x: x[0])
            for rc, seq, var in neg_elem[:1000]:
                if M.add_column(seq, var[1], var[2], var[3], var[4]):
                    added += 1
            added_total += added
        grew = neg_rep - Cstar
        if grew:
            Cstar |= grew
            rebuild()
        log("  round %d: %d labels, %d cand, +%d elementary cols, C* +%d -> |C*|=%d, best exact rc %.4f, %.1fs"
            % (rounds, nlab, len(found), added, len(grew), len(Cstar),
               min([x[0] for x in neg_elem] or [0.0]), time.time() - t0))
        if not added and not grew:
            log("  round %d: negatives found but nothing added and C* unchanged -- stalled" % rounds)
            return False, rounds, Cstar, labels_total, added_total, M.m.ObjVal
    return False, rounds, Cstar, labels_total, added_total, M.m.ObjVal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell")
    ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--delta", type=float, default=20.0)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--label-cap", type=int, default=3_000_000)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--bank", action="store_true", help="write the artifact under runs/oracle")
    ap.add_argument("--rt-class", choices=("diagnostic", "submission"), default=None,
                    help="required with --bank. submission: the wall may be quoted beside K's -- solo, "
                         "4 threads, refused otherwise (d47). diagnostic: a valid bound whose wall is "
                         "recorded and not quotable")
    a = ap.parse_args()

    import tep_cg_bound as T
    from k_comparison import k_proximity
    from stamp import stamped
    prox = k_proximity(a.size)
    lines = []

    def log(s):
        lines.append(s)
        print(s, flush=True)

    log("DSSR certify -- %s n%d, ng %d, cap %s, threads %d" % (a.cell, a.size, a.ng,
                                                              "{:,}".format(a.label_cap), a.threads))
    if a.bank:
        # THE CHEAPEST FALSIFIER FIRST. A submission-class artifact is refused by stamped() unless
        # threads == 4 and this is the only python process alive (d47); refusing at the END would
        # discard the run, so the same test runs here, before anything is computed.
        from rt_class import SUBMISSION_THREADS, tenancy
        if a.rt_class is None:
            log("  REFUSING TO START a --bank run without --rt-class: say whether this wall may be "
                "quoted (submission: solo, 4 threads) or not (diagnostic)")
            return 4
        ten = tenancy()
        if a.rt_class == "submission" and (a.threads != SUBMISSION_THREADS or ten != 1):
            log("  REFUSING TO START a submission-class run: threads %d (need %d), %s python processes "
                "alive (need 1). Wait for the machine to be solo, or bank as --rt-class diagnostic."
                % (a.threads, SUBMISSION_THREADS, ten))
            return 4
        log("  --bank as rt_class %s: %s python processes alive, %d threads" % (a.rt_class, ten, a.threads))
    t0 = time.time()
    r = T.run(a.cell, a.delta, a.iters, ["prio", "ts"], a.ng, 1000, False, a.label_cap,
              size=a.size, proximity=prox, start_states=True, return_master=True)
    M = r.pop("master")
    t_cg = time.time() - t0
    ng_lp = r["lp_street"]
    log("  ng phase: lp_street %.6f  status %s  %.0fs  cols %d" % (ng_lp, r.get("status"), t_cg, len(M.cols)))

    # ELEMENTARY-ONLY POOL: switch off every non-elementary column the ng phase generated.
    off = 0
    for key, var in M.cols.items():
        if not is_elementary(key[0]):
            var.UB = 0.0
            off += 1
    M.solve()
    log("  pool: %d columns, %d non-elementary switched off -> lp %.6f" % (len(M.cols), off, M.m.ObjVal))

    t1 = time.time()
    ok, rounds, Cstar, labels, added, lp = dssr(M, a.ng, a.label_cap, a.threads, log)
    t_dssr = time.time() - t1
    total = time.time() - t0
    slack = sum(v.X for v in M.slack.values())
    verdict = "CERTIFIED" if (ok and slack < 1e-6) else "NOT certified"
    log("  %s: lp_street %.6f (ng phase %.6f, delta %+.6f)  rounds %d  |C*|=%d  labels %s  +%d cols  dssr %.0fs  total %.0fs  slack %.2e"
        % (verdict, lp, ng_lp, lp - ng_lp, rounds, len(Cstar), "{:,}".format(labels), added, t_dssr, total, slack))
    if ok and lp < ng_lp - 1e-6:
        log("  *** DEFECT: certified value BELOW the ng value; a stronger certificate cannot lower a bound")
    if total > 1500:
        log("  *** over the 1500 s target (%.0f s); rt_class diagnostic regardless" % total)

    certified_now = bool(ok and slack < 1e-6)
    if certified_now:
        payload = dict(cell=a.cell, size=a.size, proximity=prox, delta=a.delta, ng=a.ng,
                       method="dssr", lp_street=lp, ng_lp_street=ng_lp, proven=True, status="proven",
                       certificate=True, certificate_class="elementary",
                       certificate_evidence=dict(rounds=rounds, critical_set=sorted(Cstar),
                                                 labels_total=labels, columns_added=added,
                                                 slack=slack, non_elementary_switched_off=off,
                                                 final_pass="ng(C*) pass returned no column with exact "
                                                            "rc < -eps; pool elementary-only"),
                       valid_bound=True)
    else:
        # THE INTERIM IS BANKED, THE UNCONVERGED LP IS NOT (design rule: bank any interim result
        # as a fallback). The ng phase converged on its own class, so its LP is exactly the
        # ng-class bound tep_cg_bound would have written -- proven/status/hist are the ng phase's
        # own, and ng_certified() reads them. The elementary-pool LP after a DSSR that did not
        # finish is a restricted master's value, not a bound; it is kept only as a diagnostic.
        payload = dict(cell=a.cell, size=a.size, proximity=prox, delta=a.delta, ng=a.ng,
                       method="dssr", lp_street=ng_lp, ng_lp_street=ng_lp,
                       proven=bool(r.get("proven")), status=r.get("status"),
                       certificate=False, certificate_class=None,
                       dssr_partial=dict(rounds=rounds, critical_set=sorted(Cstar),
                                         labels_total=labels, columns_added=added, slack=slack,
                                         elementary_pool_lp=lp,
                                         why="DSSR did not converge; the elementary-pool LP is a "
                                             "restricted master value, not a bound"),
                       valid_bound=bool(r.get("proven")))
    payload.update(start_states=True, threads=a.threads, cols=len(M.cols),
                   secs=round(total, 1), cg_secs=round(t_cg, 1), dssr_secs=round(t_dssr, 1),
                   det_ticks=dict(gurobi_work=round(float(M.det_work), 6),
                                  pricer_labels=int(labels), dssr_rounds=rounds),
                   log=lines, diagnostic_only=not a.bank,
                   # tep_cg_bound SHAPE, so every existing grid reader sees this artifact
                   primal_rounding=False, hist=r.get("hist"), iters=r.get("iters"), N=float(M.N.X),
                   method_note="DSSR over an elementary-only pool; see certificate_evidence or dssr_partial")
    # composed exactly as tep_cg_bound.main builds it, from the same ab_grid record
    ab = {(q["cell"], q["size"]): q for q in json.load(io.open(
        os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}[(a.cell, a.size)]
    payload["ab_street"] = float(ab["fleet_term"]) + float(ab["travel_term"])
    payload["ab4"] = float(ab["ab4"])
    payload["water_ab"] = float(ab["water"])
    payload["composed"] = payload["lp_street"] + float(ab["water"])
    payload["lp_composed"] = payload["composed"]
    payload["lb_reported"] = max(payload["composed"], payload["ab4"])
    payload["lb_carrier"] = "composed" if payload["composed"] >= payload["ab4"] else "ab4"
    log("  composed %.6f = lp_street + water %.3f; ab4 %.3f; reported %.6f (%s)"
        % (payload["composed"], payload["water_ab"], payload["ab4"], payload["lb_reported"],
           payload["lb_carrier"]))
    if not a.bank:
        payload["valid_bound"] = False
        payload["valid_bound_why"] = "smoke run; re-run with --bank to produce a citable artifact"
    h = hashlib.sha256(io.open(__file__, "rb").read()).hexdigest()[:8]
    supersede = False
    if a.bank:
        # THE CANONICAL PATH, because a tep_dssr_* prefix is invisible to every grid reader.
        p = os.path.join(ROOT, "runs", "oracle",
                         "tep_cg_bound_%s%s.json" % (a.cell, "" if a.size == 100 else "_n%d" % a.size))
        if os.path.exists(p):
            from bound_certificate import certified
            old = json.load(io.open(p, encoding="utf-8"))
            # A FILE IS REPLACED ONLY BY SOMETHING STRICTLY STRONGER. Two cases and no third: an
            # elementary certificate over an artifact that has none; or the SAME certified value to
            # 1e-6 with a solo, quotable wall where the old one was diagnostic (the RT step). A run
            # that did not certify never overwrites anything.
            old_rt = (old.get("_rt") or {}).get("rt_class")
            if not certified_now:
                log("  REFUSING to bank over %s: this run holds no elementary certificate and a file is "
                    "never replaced by something weaker" % os.path.basename(p))
                return 3
            if certified(old):
                same = abs(float(old.get("lp_street") or 0.0) - payload["lp_street"]) <= 1e-6
                if not (same and a.rt_class == "submission" and old_rt != "submission"):
                    log("  REFUSING to bank over %s: it carries an elementary certificate (lp %s, rt_class "
                        "%s); a certified artifact is replaced only by the same value to 1e-6 (here %s) "
                        "measured solo (here %s) where it was not"
                        % (os.path.basename(p), old.get("lp_street"), old_rt, same, a.rt_class))
                    return 3
                why = ("same certified value to 1e-6 (%.9f vs %.9f); wall re-measured solo -- rt_class "
                       "submission replaces %s" % (payload["lp_street"], float(old["lp_street"]), old_rt))
            else:
                why = "uncertified artifact of the same cell replaced by a DSSR elementary certificate"
            supersede = True
            payload["supersedes"] = dict(
                path=os.path.basename(p), lp_street=old.get("lp_street"), status=old.get("status"),
                certified=bool(certified(old)), rt_class=old_rt, wall_s=(old.get("_rt") or {}).get("wall_s"),
                finished=old.get("_finished") or (old.get("_provenance") or {}).get("when"),
                source_hash=(old.get("_provenance") or {}).get("source_hash"), why=why)
            log("  superseding %s %s (lp %s, status %s, %s)"
                % (("certified" if certified(old) else "uncertified"),
                   os.path.basename(p), old.get("lp_street"), old.get("status"),
                   payload["supersedes"]["finished"]))
        payload["_command"] = " ".join(sys.argv)
        payload["_finished"] = time.strftime("%Y-%m-%d %H:%M")
    else:
        os.makedirs(os.path.join(ROOT, "logs", "smoke"), exist_ok=True)
        p = os.path.join(ROOT, "logs", "smoke", "dssr_%s_n%d_%s.json" % (a.cell, a.size, h))
    doc = stamped(payload, "analysis/dssr_certify.py", "analysis/tep_cg_bound.py",
                  "analysis/tep_pricer.py", det=payload["det_ticks"], wall=payload["secs"],
                  rt_class=(a.rt_class if a.bank else "diagnostic"), path=p, supersede=supersede)
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, default=str)
    log("  wrote %s" % os.path.relpath(p, ROOT))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
