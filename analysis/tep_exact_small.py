"""GROUND TRUTH for the TEP master LP at small n, by exhaustive enumeration -- no pricer (d437).

Two convergence certificates disagree on R211 at n20: the old pricer settles at 433.95 and the
start-state pricer at 430.93, both reporting zero negative reduced costs. At most one can be the
LP optimum, so an arbiter is needed that does not use a pricer at all.

This enumerates EVERY elementary feasible trip by depth-first search over the customers, pruned by
capacity and by the earliest possible arrival (a sequence that cannot be timed from the earliest
available start cannot be timed from any later one), adds every variant of every such trip to the
same master `tep_cg_bound.Master` builds, and solves that LP once.

What the result is, and is not:

  * It is the exact optimum of the ELEMENTARY master -- call it E. Every column is a real trip.
  * The column-generation runs solve the ng-relaxed master, whose optimum G satisfies G <= E,
    because ng additionally admits non-elementary paths. So E does not by itself pick a winner.
  * What it does decide: any converged value ABOVE E is refuted outright, since the elementary
    columns are a subset of what the ng pricer may return and the ng master's optimum cannot
    exceed the elementary one.

Run with `--ng-exact` to also add every column the ng pricer could legally return? That is not
enumerable (ng memory admits cycles), which is exactly why E is the arbiter available.

    python analysis/tep_exact_small.py R211 --size 20
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
from tep_cg_bound import Master, default_delta
from stamp import stamped


def enumerate_trips(M, max_len=None, cap_paths=5_000_000):
    """Every elementary sequence of customers that can be timed from SOME start and fits Q.

    Pruning: capacity, and the earliest arrival. `earliest[c]` is the earliest time service at c
    can begin as the first customer of a trip, over the depot and over every satellite bucket the
    model offers. Extending a partial path can only push arrivals later, so a partial path whose
    earliest schedule already misses a window is dead for every start and every extension.
    """
    from tep_pricer import Q
    D, e, l, sv = M.D, M.e, M.l, M.sv
    dem = {c: float(M.inst.nodes[c].demand) for c in M.C}
    first = {}
    for c in M.C:
        best = None
        t = max(e[c], M.H0 + D[M.g][c])
        if t <= l[c] + 1e-9:
            best = t
        for L in M.sats:
            sb = M.H0 + M.win * M.delta
            t2 = max(e[c], sb + D[L][c])
            if t2 <= l[c] + 1e-9 and (best is None or t2 < best):
                best = t2
        if best is not None:
            first[c] = best
    out = []
    cust = sorted(first)
    npaths = [0]

    def dfs(seq, tail, load, ready):
        # ready = earliest time the car can LEAVE the last customer of seq
        out.append(list(seq))
        npaths[0] += 1
        if npaths[0] > cap_paths:
            raise RuntimeError("path cap hit at %d -- raise --cap or lower --max-len" % cap_paths)
        if max_len is not None and len(seq) >= max_len:
            return
        for c in cust:
            if c in seq or load + dem[c] > Q + 1e-9:
                continue
            t = max(e[c], ready + D[tail][c])
            if t > l[c] + 1e-9:
                continue
            seq.append(c)
            dfs(seq, c, load + dem[c], t + sv[c])
            seq.pop()

    for c in cust:
        dfs([c], c, dem[c], first[c] + sv[c])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--delta", type=float, default=None); ap.add_argument("--proximity", type=float, default=None)
    ap.add_argument("--max-len", type=int, default=None)
    ap.add_argument("--cap", type=int, default=5_000_000)
    a = ap.parse_args()
    prox = k_proximity(a.size) if a.proximity is None else float(a.proximity)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = a.delta if a.delta else default_delta(inst)
    M = Master(inst, delta)
    t0 = time.time()
    seqs = enumerate_trips(M, max_len=a.max_len, cap_paths=a.cap)
    t_enum = time.time() - t0
    print("  %d elementary feasible trips enumerated in %.0fs (max length %d)"
          % (len(seqs), t_enum, max(len(s) for s in seqs)), flush=True)
    t0 = time.time()
    added = 0
    for s in seqs:
        for (L, b, p, ba) in M.variants(s):
            if M.add_column(s, L, b, p, ba):
                added += 1
    print("  %d columns (every variant of every trip) added in %.0fs" % (added, time.time() - t0), flush=True)
    M.m.Params.Threads = 1
    t0 = time.time(); M.m.optimize(); t_lp = time.time() - t0
    slack = sum(v.X for v in M.slack.values())
    val = M.m.ObjVal
    print("\n  EXACT elementary master LP for %s n%d, DELTA %.0f: %.4f  (N %.3f cars, slack %.3g, %.0fs)"
          % (a.cell, a.size, delta, val, M.N.X, slack, t_lp), flush=True)
    rec = dict(cell=a.cell, size=a.size, proximity=prox, delta=delta, trips=len(seqs), columns=added,
               exact_elementary_lp=val, N=M.N.X, slack=slack, enum_secs=round(t_enum, 1),
               lp_secs=round(t_lp, 1), max_len=a.max_len)
    out = os.path.join(ROOT, "runs", "oracle", "tep_exact_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped(rec), io.open(out, "w", encoding="utf-8"), indent=1)
    print("  wrote %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
