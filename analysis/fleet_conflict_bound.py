"""Fleet lower bound from a TIME-WINDOW CONFLICT GRAPH -- "is k-1 infeasible by construction?"

Motivation (user, 2026-09-14): do not spend budget forcing nofCars <= k-1 on cells
where a smaller fleet is impossible anyway.

analysis/fleet_lb_arithmetic.py failed at this: it compares total work against the
DEPOT window and returns fleet_lb = 1 everywhere (work/W = 0.24-0.57), because
aggregate time is nowhere near binding at |C| = 20. Its own recorded diagnosis was
that the difficulty lives in the PER-CUSTOMER time windows, which that relaxation
discards. This bound captures exactly those.

THE BOUND. Customers i and j cannot share a vehicle if NEITHER order is schedulable:

    i before j is impossible when   earliest_i + service_i + D[i][j] > latest_j
    j before i is impossible when   earliest_j + service_j + D[j][i] > latest_i

Both impossible => i and j need DIFFERENT vehicles. The conflict graph's CLIQUE
NUMBER is then a valid lower bound on nCars, and any clique found gives a valid
bound (we use a greedy clique, so the bound is conservative).

WHY D[i][j] IS THE RIGHT (CONSERVATIVE) TRAVEL TERM: a vehicle may detour via a
satellite to reload, which only ADDS time. Using the direct distance therefore
understates travel and so understates conflict -- the bound stays valid.

The bound ignores capacity and reloads entirely, so it is a pure schedulability
argument and cannot be confounded by them.
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis.stamp import stamped
from build_instance import build                      # noqa: E402
from lp_component_anatomy import harvest              # noqa: E402


def conflict_fleet_lb(cell, size, tau="formula"):
    p = build(cell, size, tau=tau)
    D, nd, C = p.DistMatrix, p.nodes, list(p.customers)

    def can_follow(i, j):                      # can a vehicle serve i then j?
        return nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest + 1e-9

    adj = {i: set() for i in C}
    for a in range(len(C)):
        for b in range(a + 1, len(C)):
            i, j = C[a], C[b]
            if not can_follow(i, j) and not can_follow(j, i):
                adj[i].add(j); adj[j].add(i)

    # greedy clique from the highest-degree vertex (valid bound, not necessarily max)
    best = []
    for start in sorted(C, key=lambda v: -len(adj[v])):
        clique = [start]
        cand = set(adj[start])
        while cand:
            nxt = max(cand, key=lambda v: len(adj[v] & cand))
            clique.append(nxt)
            cand &= adj[nxt]
        if len(clique) > len(best):
            best = clique
    return dict(cell=cell, n_conflicts=sum(len(v) for v in adj.values()) // 2,
                fleet_lb=max(1, len(best)), clique=sorted(best))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/fleet_conflict_bound.json")
    a = ap.parse_args()

    kref = json.load(open("data/karademir2025/k_reference.json"))
    per = kref["table3"]["per_instance"][str(a.size)]
    cells = [c.strip() for c in a.cells.split(",") if c.strip()] or sorted(per)
    best = harvest(set(cells), a.size)

    print(f"{'cell':7s} {'conflicts':>9s} {'fleet LB':>8s} {'our nCars':>9s}  verdict")
    rows, skip, worth = [], [], []
    for c in cells:
        r = conflict_fleet_lb(c, a.size)
        nc = (best.get(c) or {}).get("nCars")
        r["our_cars"] = nc
        if nc is None:
            v = "(no incumbent)"
        elif nc <= 1:
            v = "already at 1 car -- nothing to drop"
        elif r["fleet_lb"] >= nc:
            v = f"PROVED k-1 INFEASIBLE (needs >= {r['fleet_lb']}) -- DO NOT TRY"
            skip.append(c)
        else:
            v = f"k-1 not ruled out -- worth trying"
            worth.append(c)
        r["verdict"] = v
        rows.append(r)
        print(f"{c:7s} {r['n_conflicts']:9d} {r['fleet_lb']:8d} {str(nc):>9s}  {v}")

    print(f"\nSKIP (k-1 provably infeasible): {skip or 'none'}")
    print(f"WORTH TRYING:                   {worth or 'none'}")
    os.makedirs("runs", exist_ok=True)
    json.dump(stamped(rows, __file__), open(a.out, "w"), indent=1)
    print("wrote", a.out)
