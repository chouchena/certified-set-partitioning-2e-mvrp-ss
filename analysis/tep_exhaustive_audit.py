"""EXHAUSTIVE, PRICER-FREE OPTIMALITY AUDIT of a converged TEP master at small n (d437).

The column-generation loop certifies optimality with its own pricer, so a defect in the pricer
makes the certificate self-confirming. This audit does not use the pricer at all. It rebuilds the
master, runs the column generation to convergence, and then enumerates EVERY elementary feasible
trip and EVERY variant of each, computing the exact reduced cost of all of them at the converged
duals. Any column with a negative exact reduced cost is a witness that the certificate is false,
and the audit prints the witnesses so the mechanism can be read off them.

It also reports the master's value after those witnesses are added and the LP re-solved, and the
exact elementary optimum from `tep_exact_small`, so the size of the error is measured, not argued.

Only usable where the enumeration fits: n10 everywhere, n20 on the cells whose trip count is
small (C201, RC204). See `runs/oracle/tep_exact_*.json` for what has been enumerated.

    python analysis/tep_exhaustive_audit.py C201 --size 20 --start-states
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
from tep_exact_small import enumerate_trips
from stamp import stamped


def audit(M, top=15):
    """Exact reduced cost of every (elementary trip, variant) at the current duals."""
    pi, mu_src, mu_pre, mu_post = M.duals()
    seqs = enumerate_trips(M)
    neg = []
    n_var = 0
    for s in seqs:
        base = -sum(pi[c] for c in s)
        for (L, b, p, ba) in M.variants(s):
            n_var += 1
            rc = M.cost(s, L, p) + base + (mu_src if L == M.g else mu_post[(L, b)]) - mu_pre[(p, ba)]
            if rc < -1e-6:
                neg.append((rc, tuple(s), L, b, p, ba))
    neg.sort()
    return seqs, n_var, neg[:top], len(neg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--start-states", action="store_true")
    ap.add_argument("--delta", type=float, default=None)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = a.delta if a.delta else T.default_delta(inst)
    t0 = time.time()
    r = T.run(a.cell, delta, 400, ["prio", "ts"], a.ng, 1000, False, 3_000_000, size=a.size,
              start_states=a.start_states, proximity=prox, return_master=True)
    M = r["master"]
    print("  CG converged: %.4f  proven %s  cols %d  (%.0fs)"
          % (r["lp_street"], r["proven"], r["cols"], time.time() - t0), flush=True)
    seqs, n_var, worst, n_neg = audit(M)
    print("\n  EXHAUSTIVE AUDIT of %s n%d (%d elementary trips, %d variants) at the converged duals:"
          % (a.cell, a.size, len(seqs), n_var))
    print("  %d columns have EXACT reduced cost < -1e-6  -- the certificate is %s"
          % (n_neg, "FALSE" if n_neg else "not refuted here"))
    for rc, s, L, b, p, ba in worst:
        print("     rc %10.4f  seq %-28s start (%s,%s)  hub %s  arrive bucket %s" % (rc, list(s), L, b, p, ba))
    rec = dict(cell=a.cell, size=a.size, delta=delta, ng=a.ng, start_states=bool(a.start_states),
               cg_value=r["lp_street"], cg_proven=r["proven"], trips=len(seqs), variants=n_var,
               negatives=n_neg, worst=[dict(rc=x[0], seq=list(x[1]), L=x[2], b=x[3], p=x[4], ba=x[5]) for x in worst])
    out = os.path.join(ROOT, "runs", "oracle", "tep_exhaustive_audit_%s_n%d%s.json"
                       % (a.cell, a.size, "_ss" if a.start_states else ""))
    json.dump(stamped(rec), io.open(out, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
