"""Why does the master IP miss BK by 20.64 per cent on R208 n30 with BK's own columns in the pool? (d597)

THE OPEN ISSUE. tep_bk_in_column_space.py established that BK's trips are individually legal
columns on 22 of 22 live cells. The BK-wired smoke then reached 846.898 on R208 n30 against a
banked BK of 702.028. Having the columns is necessary; it is plainly not sufficient, and the
earlier "22 of 22 expressible" was a claim about TRIPS, not about SOLUTIONS.

FOUR HYPOTHESES, and this separates them by construction rather than by argument:

  H1 search      work=60 is simply too little; the selection is available and was not found.
  H2 infeasible  the nine trips are each legal but no feasible master solution uses exactly them
                 -- the booking rows, the transfer-arc structure or the car chain forbid the set.
  H3 accounting  the selection is feasible but the master prices it differently from the banked
                 objective, so "missing BK" is a units error and not a search failure.
  H4 not added   the columns never entered the pool -- add_column refused them as duplicates, or
                 variants() does not contain the (L, b, p, b_arr) the banked solution actually uses.

THE PROBE. Build the master, inject BK's trips, then FORCE the pool to exactly those trips: every
column whose customer sequence is not one of BK's is fixed to zero, every BK column is left free.
Then solve.

  infeasible            -> H2. The master cannot express BK's trip set at all.
  feasible, street ~ BK -> H1 or H3, separated by comparing the forced street to BK's own street
                           component; equal means H1 (pure search), different means H3.
  columns not added     -> H4, reported before anything is solved.

H4 is checked first and printed regardless, because a probe that silently tested an empty
injection would answer the wrong question convincingly.

    python analysis/tep_bk_handoff_probe.py R208 --size 30
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
import tep_cg_bound as T
import tep_bk_in_column_space as BK
from k_comparison import k_proximity
from stamp import stamped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--work", type=float, default=300.0)
    a = ap.parse_args()

    got = BK.banked(a.cell, a.size)
    if not got:
        print("no banked BK for %s n%d" % (a.cell, a.size)); return 2
    sol, src = got
    bk_obj = float(sol["objVal"])
    street_parts = {k: sol.get(k) for k in ("FleetStreet", "TravelStreet", "FleetWater", "TravelWater")}
    bk_street = None
    if sol.get("FleetStreet") is not None and sol.get("TravelStreet") is not None:
        bk_street = float(sol["FleetStreet"]) + float(sol["TravelStreet"])

    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    trips, tours, vi = BK.trips_of(sol)
    print("BK HAND-OFF PROBE -- %s n%d\n" % (a.cell, a.size))
    print("  banked BK %.3f from %s | nCars %s | %d trips" % (bk_obj, src, sol.get("nCars"), len(trips)))
    print("  banked components: %s" % street_parts)
    print("  BK street part (FleetStreet + TravelStreet): %s" % ("%.3f" % bk_street if bk_street is not None else "NOT RECORDED"))
    print()

    M = T.Master(inst, T.default_delta(inst))
    before = len(M.cols)
    added, already, novar = 0, 0, []
    bk_keys = set()
    for seq in trips:
        vs = M.variants(seq)
        if not vs:
            novar.append(seq); continue
        for (L, b, p, ba) in vs:
            key = (tuple(seq), L, b, p)
            if key in M.cols:
                already += 1
            elif M.add_column(seq, L, b, p, ba):
                added += 1
            bk_keys.add(key)
    M.m.update()
    print("  H4 CHECK -- did the columns enter the pool?")
    print("    pool %d -> %d | %d variants newly added | %d already present | %d trips with NO variant"
          % (before, len(M.cols), added, already, len(novar)))
    if novar:
        print("    *** H4 CONFIRMED: %d BK trip(s) have no feasible variant: %s" % (len(novar), novar[:3]))
        return 1
    if added + already == 0:
        print("    *** H4 CONFIRMED: nothing was injected; the probe below would be vacuous.")
        return 1
    print("    H4 rejected -- %d BK columns are in the pool.\n" % len(bk_keys))

    # force the pool to BK's trips only
    n_zero = 0
    for key, var in M.cols.items():
        if key not in bk_keys:
            var.ub = 0.0
            n_zero += 1
    M.m.update()
    print("  FORCING the pool to BK's trip set: %d of %d columns fixed to zero, %d left free"
          % (n_zero, len(M.cols), len(bk_keys)))

    r = T.master_ip(M, a.cell, a.size, threads=2, timelimit=1800.0, work=a.work)
    st = r.get("ip_street"); status = r.get("ip_status")
    print("    status %s | street %s | verified %s | objVal %s"
          % (status, ("%.3f" % st) if st is not None else "-", r.get("verified"), r.get("objVal")))
    print()
    verdict = None
    if st is None:
        verdict = ("H2 CONFIRMED -- the master is INFEASIBLE when restricted to BK's trip set. "
                   "The nine trips are each legal columns and no master solution uses exactly them, "
                   "so the hand-off is blocked by the booking/transfer/chain structure, not by search.")
    elif bk_street is not None and abs(st - bk_street) > 0.05:
        verdict = ("H3 LIKELY -- feasible, but the forced street %.3f differs from BK's own street "
                   "%.3f by %.3f. The master prices BK's selection differently, so the 20.64%% is at "
                   "least partly an accounting difference and not pure search." % (st, bk_street, st - bk_street))
    else:
        verdict = ("H1 CONFIRMED -- the selection is feasible and prices as BK does, so the master "
                   "COULD reach BK and the unrestricted run simply did not find it at work=60. "
                   "The hand-off works; the budget was the problem.")
    print("  VERDICT: %s" % verdict)
    p = os.path.join(ROOT, "runs", "oracle", "tep_bk_handoff_probe_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped(dict(cell=a.cell, size=a.size, bk_obj=bk_obj, bk_source=src, bk_street=bk_street,
                           components=street_parts, trips=len(trips), added=added, already=already,
                           no_variant=[list(s) for s in novar], forced_street=st, forced_status=status,
                           forced_verified=r.get("verified"), forced_objVal=r.get("objVal"),
                           verdict=verdict)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
