"""WHEN can (26) bind at all? A structural answer, by enumeration.

WHY THIS EXISTS. Every measurement so far prices (26) at exactly +0.000: L3 on all 8 proven
cells, FR1 on 0 of 200 instances at |P|=1 and 0 of 120 at |P|=2, and a search over instances
built specifically to force collisions found none in 8 attempts. A constant zero across that many
independent measurements is not a null -- it is a structure nobody had identified.

THE STRUCTURE. (20) sequences consecutive tasks on ONE vessel:

    u_j >= u_i + tau + D[p_i][p_j]

When both tasks sit at the SAME satellite that distance is zero, leaving u_j >= u_i + tau --
which is exactly what (26) demands. So for a same-satellite pair served by the SAME VESSEL,
(26) IS ALREADY IMPLIED BY (20) and adds nothing.

(26) therefore has force in one case only: a same-satellite pair served by DIFFERENT VESSELS.

WHY THAT MAKES THE PRICE ZERO WITHOUT MAKING (26) VACUOUS. Cross-vessel same-satellite pairs
are common among STRUCTURES -- this script counts them -- but rare at the OPTIMUM, because each
extra vessel costs penaltyVessels. The optimiser consolidates transfers onto few vessels, and on
those (20) already orders them. So (26) constrains a large part of the space the optimiser never
visits.

WHAT THIS DOES NOT SAY, and the distinction matters for L4. A zero PRICE is not a zero VIOLATION
COUNT. Where several schedules share the optimal cost, nothing in the vacuous arm prefers the
(26)-compliant one -- so K's model can return a violating timetable at no objective penalty.
That is precisely why L4's primary outcome is a COUNT at the returned solution and not a price.

    python analysis/c26_when_binding.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import arbiter as A

OUT = os.path.join(ROOT, "runs", "oracle")


def census(t):
    """Over every feasible structure: same-satellite pairs, and how many are cross-vessel."""
    tot = same = cross = rel = 0
    for routes in A.ordered_partitions(t.customers):
        lasts = {r[-1] for r in routes}
        opt = [c for c in t.customers if c not in lasts]
        for mask in range(1 << len(opt)):
            tr = set(lasts)
            for b, c in enumerate(opt):
                if mask >> b & 1:
                    tr.add(c)
            if not A.load_ok(t, routes, tr):
                continue
            tl = A.trip_loads(t, routes, tr)
            for vr in A.ordered_partitions(sorted(tr)):
                if not A.vessel_load_ok(t, vr, tl):
                    continue
                tot += 1
                vof = {c: k for k, v in enumerate(vr) for c in v}
                ts = sorted(tr)
                has = False
                for i in range(len(ts)):
                    for j in range(i + 1, len(ts)):
                        same += 1
                        if vof[ts[i]] != vof[ts[j]]:
                            cross += 1
                            has = True
                if has:
                    rel += 1
    return tot, same, cross, rel


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    print("WHEN CAN (26) BIND? It adds force only where (20) does not already order the pair.")
    print()
    print("   (20)  u_j >= u_i + tau + D[p_i][p_j]     same vessel, consecutive tasks")
    print("   at ONE satellite D = 0, so this IS (26). Same-vessel pairs are already ordered.")
    print()
    print("   %5s %5s %12s %15s %14s %14s" % ("seed", "n", "structures", "same-sat pairs",
                                              "cross-vessel", "structures with"))
    rows = []
    for n in (4, 5):
        for s in (0, 1):
            t = A.Tiny(s, n, 1)
            tot, same, cross, rel = census(t)
            rows.append(dict(seed=s, n=n, structures=tot, same_sat_pairs=same,
                             cross_vessel=cross, structures_with_cross=rel))
            print("   %5d %5d %12d %15d %14d %14d" % (s, n, tot, same, cross, rel))
    print()
    sc = sum(r["cross_vessel"] for r in rows)
    ss = sum(r["same_sat_pairs"] for r in rows)
    sr = sum(r["structures_with_cross"] for r in rows)
    st = sum(r["structures"] for r in rows)
    print("   cross-vessel share of same-satellite pairs: %.0f%%" % (100.0 * sc / ss))
    print("   structures where (26) can bind at all:      %.0f%%" % (100.0 * sr / st))
    print()
    print("   So (26) is NOT structurally vacuous -- it constrains most of the space. It is")
    print("   near-vacuous AT THE OPTIMUM, because every extra vessel costs penaltyVessels, so")
    print("   the optimiser consolidates transfers onto few vessels, where (20) already orders")
    print("   them. (26) binds on structures the optimiser avoids for cost reasons anyway.")
    print()
    print("   AND A ZERO PRICE IS NOT A ZERO VIOLATION COUNT. Where several schedules share the")
    print("   optimal cost, nothing in the vacuous arm prefers the compliant one, so K's model")
    print("   can return a violating timetable at no objective penalty. That is why L4 counts")
    print("   violations at the returned solution instead of pricing them.")
    json.dump(stamped({"rows": rows, "cross_vessel_share_pct": round(100.0 * sc / ss, 1),
               "structures_binding_pct": round(100.0 * sr / st, 1)}, __file__),
              open(os.path.join(OUT, "c26_when_binding.json"), "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
