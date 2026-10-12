"""Does the Lagrangian certificate survive START-STATE pricing? The measurement d626 asks for.

    python analysis/lagrangian_smoke.py R211 --size 20            # converged; reads the residual slack
    python analysis/lagrangian_smoke.py R211 --size 100 --iters 8 # truncated: budget in, bound out

Smoke only. Writes logs/smoke/lagr_<cell>_n<size>_<hash>.json and NEVER touches runs/**, because
tep_cg_bound.main would write the cell's canonical artifact and this is not a bound we are banking.

WHAT IS BEING TESTED, and why it is not a fishing expedition. d430 measured the certificate
z_RMP + |C| * rc_min on R211 n100 and got -16,870 against z_RMP 1966.22 -- worthless -- because
the pricer's reduced cost underestimates the truth on two legs: entry takes a MINIMUM over every
possible start node, exit a MAXIMUM over arrival buckets. d436 localised the -188.36 to those
legs and predicted, in writing, that start-state pricing "would revive option 2 as a by-product".
Start-state pricing was built the next day (d437) and is the default everywhere -- except inside
the certify block, which never passed `inits` and so has always priced on the legacy legs. So
d430's verdict was measured under conditions that no longer hold, and d626 names re-measuring it
as the reopen condition.

THE ONE NUMBER THAT DECIDES IT: residual_slack = rc_exact_min - rc0_min, the gap between the
best EXACT reduced cost among the candidates and the pricer's underestimate. It is the part of
d436's -188 that start-state pricing did NOT remove, i.e. the exit leg's share. At convergence
rc_exact_min is 0 by definition, so rc0_min IS the slack and the reading is direct.

PREDICTIONS, fixed before the first run (d436's, not mine):
  P1  residual_slack is far below d430's 188 -- if the entry leg carried most of it, under 20.
  P2  at convergence the bound is within kappa * slack of z_RMP, so a small slack means the
      certificate reproduces the converged LP with no convergence claim.
  P3  truncated at K iterations the bound is a useful fraction of the banked converged LP.
FALSIFIER: residual_slack still of order 100 at n100. Then the exit leg dominates, d430's
verdict stands on a new and better-localised reason, and this route closes for good -- which is
worth knowing for the same cost.

kappa = |C| is the honest multiplier (each trip serves at least one customer); d430 records that
the per-satellite spacing argument gives 233 and is worse. Nothing here tightens kappa.
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


def banked_lp(cell, size):
    """The converged LP on disk for this cell -- the control the truncated bound is read against."""
    from bound_certificate import certified, ng_certified
    from best_known import bound_artifacts
    best = None
    for p, d in bound_artifacts(cell, size):
        if "_primal" in os.path.basename(p) or d.get("primal_rounding") or d.get("drop"):
            continue
        if d.get("lp_street") is None or not (certified(d) or ng_certified(d)):
            continue
        v = float(d["lp_street"])
        if best is None or v > best[0]:
            best = (v, "elementary" if certified(d) else "ng", float(d.get("secs") or 0.0),
                    os.path.basename(p))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--delta", type=float, default=None, help="default: the driver's own default_delta")
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--iters", type=int, default=200, help="truncate CG here; the bound needs no convergence")
    ap.add_argument("--label-cap", type=int, default=3_000_000)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()

    import tep_cg_bound as T
    import verifier3 as V
    from k_comparison import k_proximity
    from stamp import stamped

    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = a.delta or T.default_delta(inst)
    print("Lagrangian smoke -- %s n%d, delta %g, ng %d, iters cap %d, threads %d"
          % (a.cell, a.size, delta, a.ng, a.iters, a.threads), flush=True)

    t0 = time.time()
    r = T.run(a.cell, delta, a.iters, ["prio", "ts"], a.ng, 1000, False, a.label_cap,
              size=a.size, proximity=prox, start_states=True, certify=True, threads=a.threads)
    secs = time.time() - t0
    lg = r.get("lagrangian") or {}
    ctrl = banked_lp(a.cell, a.size)

    row = dict(cell=a.cell, size=a.size, delta=delta, ng=a.ng, iters_cap=a.iters,
               cg_iters=r.get("iters"), cg_status=r.get("status"), cg_proven=bool(r.get("proven")),
               cg_lp=r.get("lp_street"), secs=round(secs, 1), lagrangian=lg,
               banked_lp=(ctrl[0] if ctrl else None), banked_class=(ctrl[1] if ctrl else None),
               banked_secs=(ctrl[2] if ctrl else None), banked_file=(ctrl[3] if ctrl else None))
    if ctrl and lg.get("bound") is not None and ctrl[0]:
        row["bound_over_banked"] = float(lg["bound"]) / ctrl[0]
        row["zrmp_over_banked"] = float(lg["z_rmp"]) / ctrl[0]
    print("  CG stopped at iteration %s (%s, proven %s), LP %.6f in %.0fs"
          % (r.get("iters"), r.get("status"), r.get("proven"), r.get("lp_street") or float("nan"), secs))
    if ctrl:
        print("  control (banked): LP %.6f  class %s  %s" % (ctrl[0], ctrl[1], ctrl[3]))
    if lg:
        print("  RESIDUAL SLACK %.4f   (rc exact %.4f - pricer rc %.4f)   kappa %d   penalty %.2f"
              % (lg.get("residual_slack", float("nan")), lg.get("rc_exact_min", float("nan")),
                 lg.get("rc0_min", float("nan")), lg.get("kappa", 0), lg.get("penalty", float("nan"))))
        print("  BOUND %.2f vs z_RMP %.2f%s   %s"
              % (lg.get("bound", float("nan")), lg.get("z_rmp", float("nan")),
                 ("  = %.3f of the banked LP" % row["bound_over_banked"]) if "bound_over_banked" in row else "",
                 "VALID" if lg.get("valid") else ("NOT VALID: %s" % lg.get("why_invalid"))))
    else:
        print("  NO lagrangian record -- the certify block did not run")

    doc = stamped(row, "analysis/lagrangian_smoke.py", "analysis/tep_cg_bound.py",
                  "analysis/tep_pricer.py", det=r.get("det_ticks"), wall=round(secs, 1),
                  rt_class="diagnostic")
    h = hashlib.sha256(io.open(__file__, "rb").read()).hexdigest()[:8]
    os.makedirs(os.path.join(ROOT, "logs", "smoke"), exist_ok=True)
    p = os.path.join(ROOT, "logs", "smoke", "lagr_%s_n%d_i%d_%s.json" % (a.cell, a.size, a.iters, h))
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
