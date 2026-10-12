"""EXHAUSTIVE small-subset search for the k=1 infeasibility certificate.

The heuristic version (analysis/fleet_subset_infeasibility.py) searched three O(n^2)
families -- deadline prefixes, release suffixes, window slices -- and proved 6 of 27.
But EVERY witness it found was of size 5-7, and subsets that small are exhaustively
enumerable: sum_{m=2..8} C(20,m) = 263,950. So the "6 of 27" limit is a property of
the SEARCH, not of the argument.

THE CERTIFICATE (unchanged, TIER 1 form -- no geometry, valid at any proximity):
inside [min_{i in S} e_i, max_{i in S} (l_i + s_i)] one vehicle must perform, without
overlap, sum_{i in S} service_i plus tau * (ceil(demand(S)/Q) - 1) reloads. Service
happens at customers and reloads at satellites, so they cannot overlap. If that total
exceeds the span, no single vehicle exists.

Every conservatism runs the safe way: service of customers outside S is ignored, ALL
travel is ignored, and a vehicle arriving partially loaded would need MORE reloads.

A violating subset is a PROOF. More search can only find more proofs -- it cannot
create false ones -- so exhaustive enumeration is sound by construction. The built-in
soundness test remains: 13 n20 cells have a VERIFIED one-car solution and none may be
flagged.
"""
import sys, os, math, json, argparse
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
from build_instance import build                      # noqa: E402
from lp_component_anatomy import harvest              # noqa: E402


def best_certificate(cell, size, maxk, tau="formula"):
    p = build(cell, size, tau=tau)
    nd, C = p.nodes, list(p.customers)
    TD, Q = p.TransferDuration, p.CarCapacity
    svc = {i: nd[i].serviceTime for i in C}
    dem = {i: nd[i].demand for i in C}
    e = {i: nd[i].earliest for i in C}
    f = {i: nd[i].latest + nd[i].serviceTime for i in C}   # latest finish

    best = (0.0, None)
    for m in range(2, min(maxk, len(C)) + 1):
        for S in combinations(C, m):
            span = max(f[i] for i in S) - min(e[i] for i in S)
            if span <= 0:
                continue
            d = sum(dem[i] for i in S)
            work = sum(svc[i] for i in S) + TD * max(0, math.ceil(d / Q) - 1)
            r = work / span
            if r > best[0]:
                best = (r, (tuple(sorted(S)), work, span))
    return best


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--maxk", type=int, default=8)
    ap.add_argument("--cells", default="")
    ap.add_argument("--out", default="runs/fleet_exhaustive_subsets.json")
    a = ap.parse_args()

    kref = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
    per = kref["table3"]["per_instance"][str(a.size)]
    cells = [c.strip() for c in a.cells.split(",") if c.strip()] or sorted(per)
    best_inc = harvest(set(cells), a.size)

    prev = {"C201", "C202", "C203", "C205", "C206"}      # TIER 1 from the heuristic search
    print(f"exhaustive over |S| = 2..{a.maxk}  (assumption-free certificate, no geometry)\n")
    print(f"{'cell':7s} {'ratio':>7s} {'|S|':>4s} {'ours':>5s}  verdict")
    proved, new, rows = [], [], []
    for c in cells:
        r, wit = best_certificate(c, a.size, a.maxk)
        nc = (best_inc.get(c) or {}).get("nCars")
        ok = r > 1.0 + 1e-9
        if ok:
            proved.append(c)
            if c not in prev:
                new.append(c)
        tag = ("PROVED k=1 impossible" + ("  <== NEW" if c in new else "")) if ok else \
              ("already 1 car" if nc == 1 else "not proved")
        rows.append(dict(cell=c, ratio=r, witness=wit, our_cars=nc, proved=bool(ok)))
        print(f"{c:7s} {r:7.3f} {(len(wit[0]) if wit else 0):4d} {str(nc):>5s}  {tag}")

    print(f"\nPROVED: {len(proved)} of {len(cells)}  -> {sorted(proved)}")
    print(f"NEW vs the heuristic search: {sorted(new) or 'none'}")
    bad = [r["cell"] for r in rows if r["proved"] and r["our_cars"] == 1]
    print(f"SOUNDNESS -- flagged a cell where we HAVE a 1-car solution: {bad or 'none (good)'}")
    json.dump(stamped(rows, __file__), open(os.path.join(ROOT, a.out), "w"), indent=1)
