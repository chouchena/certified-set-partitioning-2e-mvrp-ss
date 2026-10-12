"""The easy-reduction idea, MIMICKED OVER OUR FORMULATION instead of the predecessors' (d448).

Author, 2026-09-25: "I wont drop the descent nor their compact model - rather try to mimic them
over our formulation."

WHAT THE DESCENT ACTUALLY DOES, and it is not what its name suggests. Its power is not the
Lagrangian step. It solves a REDUCED instance -- the full customer set less the k EASIEST, by their
scarcity-weighted easiness score -- to PROVEN INTEGER OPTIMALITY on the street-and-synchronisation
block, and adds the full-set water term. On C201 at n100 the frontier sits at k = 48, so it proves
52 customers and reports 2656.19. An integer optimum on 52 customers can exceed a linear
relaxation on 100, which is why it beats both the arithmetic bound and the relaxed exact model.

WHY IT TRANSPORTS. The reduction argument is about the PROBLEM, not the formulation: dropping
customers cannot raise the optimum under the triangle inequality, which this project has verified
exactly on all 27 instances. So a lower bound on the reduced instance is a lower bound on the full
one, whichever formulation produced it.

WHAT THIS PROBE MEASURES, AND WHAT IT IS NOT. It builds OUR master on the reduced set, runs the
column generation to convergence with start-state pricing, and then solves the master as an integer
program over the priced pool. Three numbers come out:

  LP(H)      the converged linear value on the reduced set. A VALID bound (plus water).
  IP(H)      the integer optimum OVER THE PRICED POOL. **NOT a valid bound** -- a pool is a
             restriction, so its integer optimum can exceed the true one. It is an ESTIMATE of
             what branch-and-price would deliver, and it is the number that decides whether
             building branch-and-price is worth it.
  gap        IP(H) - LP(H), which is what branching would have to close.

The honest reading is therefore: if IP(H) + water is far above the descent, the route is worth
building and needs branch-and-price to become rigorous. If it is not, the route is dead and we
have saved the build.

    python analysis/tep_easy_reduction.py C201 --size 100 --drop 48
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
import tep_cg_bound as T
from stamp import stamped


def easiest_first(cell, size):
    """The predecessors' own easiness order, reused as an IDEA so the sets are comparable."""
    from build_instance import build
    from crossfeed.easy_reduction import scarcity_and_weights, easiness
    p = build(cell, size, wls=0.1, tau="formula", proximity=0.0)
    s, w, ctx = scarcity_and_weights(p)
    E = easiness(ctx, w)
    return sorted(E, key=lambda c: -E[c])          # easiest first; drop a prefix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--drop", type=int, default=48)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--max-secs", type=float, default=1200.0)
    ap.add_argument("--ip-time", type=float, default=900.0)
    ap.add_argument("--no-ip", action="store_true", help="skip the pool-restricted master IP (an ESTIMATE the bound never uses; up to 900 s per run)")
    ap.add_argument("--proof-audit", action="store_true",
                    help="re-price at the converged duals with the completion-bound prune OFF and "
                         "elementary labelling: the strongest certificate check we have (d449)")
    a = ap.parse_args()

    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = T.default_delta(inst)
    order = easiest_first(a.cell, a.size)
    keep = sorted(set(order[a.drop:]))
    print("%s n%d: dropping the %d easiest, keeping %d customers, DELTA %.0f"
          % (a.cell, a.size, a.drop, len(keep), delta), flush=True)

    t0 = time.time()
    r = T.run(a.cell, delta, 400, ["prio", "ts"], a.ng, 1000, False, 3_000_000, size=a.size,
              start_states=True, proximity=prox, customers=keep, max_secs=a.max_secs,
              ip=(None if a.no_ip else dict(threads=1, timelimit=a.ip_time, work=0.0)), return_master=True,
              proof_audit=a.proof_audit)
    secs = time.time() - t0

    ab = {(x["cell"], x["size"]): x for x in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}
    water = float(ab[(a.cell, a.size)]["water"])
    import dual_vs_k as D
    descent = D.lb_frontier(a.cell, a.size) or D.lb_maxrec(a.cell, a.size)
    arith = float(ab[(a.cell, a.size)]["ab4"])

    lp = r["lp_street"]; ipv = (r.get("ip") or {}).get("ip_street")
    print("\n  converged %s in %.0f s over %d columns" % (r["proven"], secs, r["cols"]), flush=True)
    print("  LP(H) street %.2f  -> + water(full) %.1f = %.2f    %s"
          % (lp, water, lp + water, "VALID bound" if r["proven"] else "NOT a bound, unconverged"))
    if ipv is not None:
        print("  IP(H) street %.2f  -> + water(full) %.1f = %.2f    ESTIMATE ONLY (pool-restricted)"
              % (ipv, water, ipv + water))
        print("  branching would need to close %.2f of street (%.1f%% of LP)" % (ipv - lp, 100.0 * (ipv - lp) / lp))
    print("\n  against what we hold on this cell:")
    print("    descent (K's model, excluded from our method) %10.2f" % descent)
    print("    arithmetic (ours)                             %10.2f" % arith)
    if ipv is not None:
        print("    this route's ESTIMATE                         %10.2f   -> %.3fx descent, %.3fx arithmetic"
              % (ipv + water, (ipv + water) / descent, (ipv + water) / arith))
    # 2026-09-26 (d519): the artifact must carry its own certificate. proven is set by cg_loop only after an ELEMENTARY pass
    # that adds nothing, is not exhausted and leaves zero covering slack (d427); store that pass and the verdict so a reader
    # can check the certificate without re-running (the 2026-09-25 batch stored neither and had to be recomputed).
    hist = r.get("hist") or []
    elem = [h for h in hist if str(h.get("tag", "")).strip().upper().startswith("ELEM")]
    last = elem[-1] if elem else None
    certificate = bool(last) and last.get("added") == 0 and not last.get("exhausted") and float(last.get("slack", 1.0)) < 1e-6
    if bool(r["proven"]) != certificate:
        print("  WARNING: proven flag %s but elementary certificate %s -- the value is NOT reported as a bound" % (r["proven"], certificate), flush=True)
    rec = dict(cell=a.cell, size=a.size, drop=a.drop, kept=len(keep), delta=delta,
               lp_street=lp, ip_street=ipv, water=water, proven=bool(r["proven"]) and certificate,
               certificate=certificate, elementary_pass=last, status=r.get("status"), ng=a.ng, hist=hist,
               cols=r["cols"], secs=round(secs, 1), descent=float(descent), arithmetic=arith,
               lp_composed=lp + water, ip_composed=(ipv + water) if ipv is not None else None)
    p = os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_%s_n%d_k%d.json" % (a.cell, a.size, a.drop))
    json.dump(stamped(rec), io.open(p, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
