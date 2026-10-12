"""One cell of the arbiter panel: ground truth against both pricers, at a matched DELTA (d437).

For a single cell and size this computes three things on the SAME master and the SAME bucket
width (`tep_cg_bound.default_delta`, which is where the width now lives so the two cannot drift):

  E        the exact optimum of the elementary master, by enumerating every feasible trip and
           every variant of each and solving the LP once -- no pricer is involved
  G_old    the value the column generation converges to with the original pricer
  G_new    the value it converges to with start-state pricing (d437)

and, for each of the two converged masters, an EXHAUSTIVE check of the optimality certificate:
the exact reduced cost of all enumerated columns at that run's own converged duals. A negative
one is a witness that the certificate is false.

The reading is fixed by the mathematics, not by taste. The elementary master's columns are a
subset of what either pricer may return, so a converged value strictly ABOVE E is refuted: the
run stopped at a point where a column with negative reduced cost existed. A value at or below E
is not refuted by this test.

    python analysis/tep_arbiter_cell.py R211 --size 10
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


def exact_lp(inst, delta, seqs, customers=None):
    M = T.Master(inst, delta, customers=customers)
    n = 0
    for s in seqs:
        for (L, b, p, ba) in M.variants(s):
            if M.add_column(s, L, b, p, ba):
                n += 1
    M.m.Params.Threads = 1
    M.m.optimize()
    if M.m.Status != 2:
        return None, n, None
    return M.m.ObjVal, n, sum(v.X for v in M.slack.values())


def certificate_negatives(M, seqs, top=8):
    pi, mu_src, mu_pre, mu_post = M.duals()
    neg = []
    for s in seqs:
        base = -sum(pi[c] for c in s)
        for (L, b, p, ba) in M.variants(s):
            rc = M.cost(s, L, p) + base + (mu_src if L == M.g else mu_post[(L, b)]) - mu_pre[(p, ba)]
            if rc < -1e-6:
                neg.append((rc, list(s), L, b, p, ba))
    neg.sort()
    return len(neg), neg[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--ng", type=int, default=10); ap.add_argument("--delta", type=float, default=None)
    ap.add_argument("--drop", type=int, default=0,
                    help="drop the k EASIEST customers and validate on the reduced set (d448)")
    ap.add_argument("--max-variants", type=int, default=3_000_000,
                    help="refuse the cell rather than thrash if the enumeration is too big")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = a.delta if a.delta else T.default_delta(inst)
    keep = None
    if a.drop:
        from tep_easy_reduction import easiest_first
        keep = sorted(set(easiest_first(a.cell, a.size)[a.drop:]))
        print('  reduced: dropping the %d easiest, keeping %d customers' % (a.drop, len(keep)), flush=True)
    M0 = T.Master(inst, delta, customers=keep)
    t0 = time.time()
    seqs = enumerate_trips(M0)
    nvar = sum(len(M0.variants(s)) for s in seqs)
    print("  %s n%d DELTA %.0f: %d trips, %d variants (%.0fs)" % (a.cell, a.size, delta, len(seqs), nvar, time.time() - t0), flush=True)
    if nvar > a.max_variants:
        print("  SKIPPED: %d variants exceeds the cap %d" % (nvar, a.max_variants), flush=True)
        rec = dict(cell=a.cell, size=a.size, delta=delta, skipped=True, trips=len(seqs), variants=nvar)
    else:
        t0 = time.time(); E, ncol, slack = exact_lp(inst, delta, seqs, customers=keep); t_e = time.time() - t0
        print("  exact elementary LP %.4f over %d columns (%.0fs)" % (E, ncol, t_e), flush=True)
        rows = {}
        for tag, ss in (("old", False), ("new", True)):
            t0 = time.time()
            r = T.run(a.cell, delta, 400, ["prio", "ts"], a.ng, 1000, False, 3_000_000, size=a.size,
                      start_states=ss, proximity=prox, return_master=True, customers=keep)
            nneg, worst = certificate_negatives(r["master"], seqs)
            rows[tag] = dict(value=r["lp_street"], proven=bool(r["proven"]), cols=r["cols"],
                             secs=round(time.time() - t0, 1), negatives=nneg,
                             over_exact=r["lp_street"] - E, refuted=bool(r["lp_street"] > E + 1e-6),
                             worst=[dict(rc=w[0], seq=w[1], L=w[2], b=w[3], p=w[4], ba=w[5]) for w in worst])
            print("  %-3s %12.4f  proven %-5s  vs exact %+9.4f  negatives %-5d  %s (%.0fs)"
                  % (tag, r["lp_street"], r["proven"], r["lp_street"] - E, nneg,
                     "REFUTED" if rows[tag]["refuted"] else "not refuted", rows[tag]["secs"]), flush=True)
        rec = dict(cell=a.cell, size=a.size, proximity=prox, delta=delta, ng=a.ng, trips=len(seqs),
                   variants=nvar, exact_elementary_lp=E, exact_columns=ncol, exact_slack=slack,
                   exact_secs=round(t_e, 1), old=rows["old"], new=rows["new"], skipped=False)
    out = os.path.join(ROOT, "runs", "oracle", "arbiter", "arb_%s_n%d%s.json" % (a.cell, a.size, ("_k%d" % a.drop) if a.drop else ""))
    if not os.path.isdir(os.path.dirname(out)):
        os.makedirs(os.path.dirname(out))
    json.dump(stamped(rec), io.open(out, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(out, ROOT), flush=True)


if __name__ == "__main__":
    main()
