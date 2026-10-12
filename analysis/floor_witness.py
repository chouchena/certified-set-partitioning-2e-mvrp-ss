r"""Recompute the floor-relaxation witness BY HAND for the appendix (referee round, 2026-10-11).

Lemma teprelax maps each trip of a feasible street solution to a floor-model column. A hub-started
trip's literal floor departure bucket b_k = bkt(T_k) need not be a column the generator keeps:
Master.variants retains, per (start node, hub, arrival bucket), only the LARGEST departure bucket
reaching that arrival bucket (tep_cg_bound.py:181). The proof therefore substitutes the retained
representative b'_k >= b_k with the SAME arrival bucket, reached by free post-layer waiting, at
unchanged cost. This script exhibits that substitution on a real incumbent (default C201, |C|=10),
so the appendix carries a checkable example rather than an assertion.

For each hub-started trip it prints: start node L, hub p, true departure T_k, literal bucket b_k,
arrival bucket ba_k, and the retained representative b'_k found in M.variants for (L, p, ba_k). It
also prints the street objective z^s, which the substitution leaves unchanged (trip cost is
bucket-independent).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verifier3 as V
from k_comparison import k_proximity
from tep_cg_bound import Master, default_delta
from tep_refine import decode, _pass
from reverify_reported import reported_row
from floor_relax_check import street_cost


def witness(cell, size):
    inst = V.load_instance(cell, size, k_proximity(size))
    row, tag, src = reported_row(cell, size)
    if row is None or row.get("solution") is None:
        return None
    sol = row["solution"]
    chains, hub = decode(inst, sol)
    timed = _pass(inst, chains, hub, {})
    if timed is None:
        return None
    a, u, tload = timed
    zs = street_cost(inst, chains, hub)

    M = Master(inst, delta=default_delta(inst), threads=1, primal=False, customers=list(inst.customers))
    tau = float(inst.tau)
    H0, dl, D = M.H0, M.delta, M.D
    subs = []
    for ch in chains:
        prev_last = None
        for ti, trip in enumerate(ch):
            L = inst.depot if ti == 0 else hub[prev_last]
            p = hub[trip[-1]]
            if ti >= 1:                                   # hub-started: has a departure bucket
                Tk = u[prev_last] + tau                   # leaves the previous hub U after its transfer
                bk = M.bucket(Tk)
                end = M.simulate(list(trip), H0 + bk * dl + D[L][trip[0]])
                bak = M.bucket(end + D[trip[-1]][p]) if end is not None else None
                # retained representative for (L, p, bak): the largest departure bucket M keeps
                reps = [b for (LL, b, pp, ba) in M.variants(list(trip))
                        if LL == L and pp == p and ba == bak]
                brep = max(reps) if reps else None
                subs.append((L, p, round(Tk, 3), bk, bak, brep, bk == brep))
            prev_last = trip[-1]
    return {"cell": cell, "size": size, "zs": round(zs, 3), "subs": subs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="C201")
    ap.add_argument("--size", type=int, default=10)
    a = ap.parse_args()
    w = witness(a.cell, a.size)
    if w is None:
        print("no incumbent / infeasible decode for", a.cell, a.size); return 1
    print("cell=%s |C|=%d  delta=%.0f  street objective z^s = %.3f"
          % (w["cell"], w["size"], default_delta(V.load_instance(a.cell, a.size, k_proximity(a.size))), w["zs"]))
    print("  hub-started trips: start L -> hub p | true departure T_k | literal bucket b_k -> retained b'_k (arrival bucket ba_k)")
    for (L, p, Tk, bk, bak, brep, same) in w["subs"]:
        print("    %3d -> %3d | T_k=%8.3f | b_k=%s -> b'_k=%s  (ba_k=%s)%s"
              % (L, p, Tk, bk, brep, bak, "  [already retained]" if same else "  [SUBSTITUTED]"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
