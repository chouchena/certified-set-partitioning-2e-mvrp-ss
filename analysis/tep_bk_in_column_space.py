"""Is the banked best-known solution expressible in our master's column space? (d589)

WHY THIS IS THE FIRST THING TO RUN. The author's third constraint on the cut trials is that they
be "wired over baseline outcome (BK incumbent)". Every design for that wiring -- warm-starting the
master IP at BK, or constraining it to improve on BK -- presumes that BK's trips ARE columns our
master can hold. If any BK trip has no feasible variant, the presumption is false and every design
built on it is wasted. That check costs no solve at all: it builds the master and asks.

It is also the cheap explanation for something already measured. On RC208 n30 the cut arm reached
1315.038 while the banked BK is 1295.975 (from ALNS). Either BK lies outside the pool we generate,
or it lies inside and our master IP simply did not find it in 60 work units. Those two have
completely different consequences and nothing so far distinguishes them. This does.

WHAT A TRIP IS, read off the artifact rather than assumed. A banked solution stores `xij` as street
arcs over customers plus the garage, `vi` as the customers at which a transfer occurs and `hubs` as
the satellite serving each, parallel to `vi`. Walking the tours from the garage on RC208 n30 gives
two cars and the transfer pattern T..TT..T..T.T..TT. A trip is the maximal customer segment ENDING
at a transfer customer: the car serves it and then goes to hubs[i] to reload. Either reading gives
14 trips covering 30 of 30 customers, so the trip count does NOT settle the convention -- capacity
does. Splitting the other way put 4 of 14 trips over Q, one at 80 against Q = 50; this way the
maximum load is exactly 50 and nothing is over. BK is verifier3-clean, so the decomposition that
breaks capacity is the wrong decomposition.

WHAT IS TESTED, per trip:
  feasible variant   Master.variants(seq) non-empty -- some (start, bucket, end satellite) works
  capacity           sum of demands on the trip <= Q, the street vehicle capacity
  coverage           the trips partition the customers, which is the TEP hypothesis itself

A trip failing the first is fatal to the wiring. A trip failing the second means the decomposition
is wrong, not the solution -- BK was verified by verifier3 and its capacity holds by construction.

    python analysis/tep_bk_in_column_space.py                    # every live cut cell
    python analysis/tep_bk_in_column_space.py --cells RC208 --sizes 30
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import instance_view
import verifier3 as V
import tep_cg_bound as T
from best_known import best_solution
from k_comparison import k_proximity
from stamp import stamped

Q = float(instance_view.LEFV_CAPACITY)


def banked(cell, size):
    """THE banked best-known, from the one accessor. Returns (solution dict, stage) or None.

    This delegated to a glob of its own for about twenty minutes and that was a mistake of a kind
    this project keeps making: a second copy of a lookup, drifting from the first. Two faults, both
    measured before anything ran on it. It returned a WORSE solution than the accessor on 2 of 22
    live cells (C204 n50 1445.034 against 1434.073, R211 n30 907.458 against 903.350) because it
    globbed every stage directory rather than taking the minimum the accessor takes. Worse, it
    never checked `_verified`, which best_solution() requires -- so it could have seeded the master
    with the trips of an UNVERIFIED solution and then reported a gain measured against it.
    """
    got = best_solution(cell, size)
    if not got:
        return None
    value, stage, relpath = got
    try:
        d = json.load(io.open(os.path.join(ROOT, relpath), encoding="utf-8"))
    except Exception:
        return None
    if abs(float(d.get("objVal", -1)) - value) > 1e-6:
        return None                      # the accessor and the file disagree; refuse rather than guess
    return d, stage


def trips_of(sol):
    """Decompose into TEP trips: maximal customer segments beginning at a transfer customer."""
    arcs = [(int(a), int(b)) for a, b in (sol.get("xij") or [])]
    succ = {}
    for a, b in arcs:
        succ.setdefault(a, []).append(b)
    vi = {int(x) for x in (sol.get("vi") or [])}
    depot = 0
    trips, tours = [], []
    for first in succ.get(depot, []):
        seq, cur, guard = [], first, 0
        while cur != depot and guard < 10000:
            seq.append(cur)
            nxt = succ.get(cur, [])
            if not nxt:
                break
            cur = nxt[0]; guard += 1
        tours.append(seq)
    # The transfer customer ENDS its trip: the car serves it, then goes to hubs[i] to reload.
    # Settled by capacity, not by reading. Splitting the other way (transfer STARTS the trip) put
    # 4 of 14 trips over Q on RC208 n30, one of them at 80 against Q = 50; this way the maximum
    # load is exactly 50 and nothing is over. BK is verifier3-clean, so a decomposition that
    # violates capacity is a wrong decomposition, not a wrong solution.
    for seq in tours:
        cur = []
        for c in seq:
            cur.append(c)
            if c in vi:
                trips.append(cur); cur = []
        if cur:
            trips.append(cur)
    return trips, tours, vi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="*", default=None)
    ap.add_argument("--sizes", nargs="*", type=int, default=None)
    a = ap.parse_args()

    # the live cells are the cut campaign's denominator; no point asking about a waived cell
    w = json.load(io.open(os.path.join(ROOT, "runs", "oracle", "tep_cut_waiver_ceil.json"), encoding="utf-8"))
    live = [(r["cell"], r["size"]) for r in w["rows"] if not r.get("waive")]
    if a.cells:
        live = [x for x in live if x[0] in a.cells]
    if a.sizes:
        live = [x for x in live if x[1] in a.sizes]

    print("IS THE BANKED BEST-KNOWN INSIDE OUR MASTER'S COLUMN SPACE?\n")
    print("  %-6s %-5s %10s %6s %6s %7s %8s %9s  %s"
          % ("cell", "size", "BK", "cars", "trips", "covered", "cap ok", "variants", "verdict"))
    rows, fatal = [], 0
    for cell, size in sorted(live, key=lambda t: (t[1], t[0])):
        got = banked(cell, size)
        if not got:
            print("  %-6s n%-4d %10s -- no banked solution found" % (cell, size, "-"))
            continue
        sol, src = got
        trips, tours, vi = trips_of(sol)
        prox = k_proximity(size)
        inst = V.load_instance(cell, size, prox)
        M = T.Master(inst, T.default_delta(inst))
        cov = sorted({c for t in trips for c in t})
        all_cust = sorted(int(c) for c in inst.customers)
        n_ok, bad_seq, bad_cap = 0, [], []
        for t in trips:
            if M.variants(t):
                n_ok += 1
            else:
                bad_seq.append(t)
            if sum(float(inst.nodes[c].demand) for c in t) > Q + 1e-6:
                bad_cap.append(t)
        covered = (cov == all_cust)
        ok = (n_ok == len(trips)) and covered and not bad_cap
        if not ok:
            fatal += 1
        verdict = ("every trip is a legal column" if ok else
                   "%d trip(s) have NO feasible variant" % len(bad_seq) if bad_seq else
                   "coverage mismatch" if not covered else "capacity exceeded on %d trip(s)" % len(bad_cap))
        print("  %-6s n%-4d %10.3f %6s %6d %7s %8s %5d/%-3d  %s"
              % (cell, size, sol["objVal"], sol.get("nCars"), len(trips),
                 "%d/%d" % (len(cov), len(all_cust)), "no" if bad_cap else "yes",
                 n_ok, len(trips), verdict))
        rows.append(dict(cell=cell, size=size, objVal=sol["objVal"], source=src, cars=sol.get("nCars"),
                         trips=len(trips), transfers=len(vi), covered=covered, n_variant_ok=n_ok,
                         bad_sequences=bad_seq, bad_capacity=len(bad_cap), expressible=ok))
    print()
    print("  %d cell(s) examined | %d where the banked best-known is NOT expressible as our columns"
          % (len(rows), fatal))
    if fatal == 0 and rows:
        print("  So wiring the cut run over BK is feasible: BK's trips can be inserted into the pool\n"
              "  and the master IP can start at BK rather than wherever its own pool happens to reach.")
    elif fatal:
        print("  The wiring as designed is NOT possible on those cells. Do not build on it.")
    p = os.path.join(ROOT, "runs", "oracle", "tep_bk_in_column_space.json")
    json.dump(stamped(dict(rows=rows, Q=Q, fatal=fatal)), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
