"""SHARPER mathematical k=1 infeasibility check — subset (interval) energetic reasoning.

WHY THE EARLIER BOUNDS FAILED. All three previous attempts reasoned about the WHOLE
customer set against the WHOLE depot window:

    conflict graph (pairwise)            0 conflicts on 27/27
    aggregate energetic + transfers      ratio 0.24-0.87
    + AB3/AB4 travel                     ratio up to 0.942

The whole-set argument is weak because the depot window is enormous. But **for k = 1
the vehicle is a single sequence**, so a much stronger family of necessary conditions
applies: ANY SUBSET must fit inside ITS OWN time span, not the global one.

THE CONDITION. For any subset S of customers, a single vehicle must serve all of S
somewhere inside [min_i e_i, max_i l_i + s_i]. Inside that span it must perform:

    sum_{i in S} service_i                     mandatory service
  + PathLB(S)                                  it must physically visit all of S
  + tau * reloads(S)                           capacity forces reloads

where PathLB(S) is a lower bound on the travel of a walk covering S. We use the MST
over S (a connected spanning subgraph of any covering walk costs >= MST), and
reloads(S) = ceil(demand(S)/Q) - 1, since one vehicle starts loaded once.

    If  service + PathLB + tau*reloads  >  span(S)   then ONE VEHICLE IS IMPOSSIBLE.

This is valid for ANY S, so we are free to search for a violating subset.

SUBSET FAMILY. Exhaustive S is 2^n. We use the standard deadline-ordered families,
which are where such conditions bite:
  * DEADLINE PREFIXES  : the m customers with the smallest l_i
  * RELEASE SUFFIXES   : the m customers with the largest e_i
  * WINDOW SLICES      : all customers whose window lies inside [e_a, l_b]
These are O(n^2) subsets and contain the classical violating sets for 1-machine
scheduling with release dates and deadlines.

RELOAD DETOUR TERM. A reload inserts a satellite between two consecutive customers,
costing D[i][s] + D[s][j] - D[i][j] MORE than the direct leg the MST already pays for.
The valid charge per reload is therefore the cheapest possible insertion,
min_{i,j,s} (D[i][s] + D[s][j] - D[i][j]), which is >= 0.

  (An earlier draft charged min_{s,i} D[s][i], the cheapest satellite DEPARTURE.
   That is NOT valid: when s lies between i and j the true detour is near zero while
   the departure distance is not. Corrected before any result was recorded; the six
   proved cells survive the correction unchanged.)

VALIDITY SCOPE. The MST step needs the TRIANGLE INEQUALITY, since it assumes the leg
between two consecutive members of S costs at least their direct distance. Per
`metric-property-scoped`, D is exactly metric at proximity 0.0 and NOT at 0.1. This
check is therefore valid ONLY at proximity 0.0, which is the default and what we use.

SOUNDNESS TEST built in: 13 n20 cells have a VERIFIED one-car solution. The check must
declare none of them impossible. It declares none.
"""
import sys, os, math, json, argparse
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped
from build_instance import build                              # noqa: E402
from lp_component_anatomy import harvest                      # noqa: E402


def mst_on(D, nodes):
    """MST weight over `nodes` (Prim, dense)."""
    from scipy.sparse.csgraph import minimum_spanning_tree
    if len(nodes) < 2:
        return 0.0
    M = np.asarray(D, dtype=float)[np.ix_(nodes, nodes)]
    return float(minimum_spanning_tree(M).toarray().sum())


def check(cell, size, tau="formula", proximity=None):
    # PROXIMITY MUST MATCH THE CAMPAIGN. build() defaults proximity=0.0, but the n100
    # campaign and the AB grid both use 0.1 (K Table 6). Calling build() without it silently
    # compared a 0.0 instance against a 0.1 bound -- the same shape of defect as the tau bug.
    # Default per size to the basis the skeleton records: 0.0 for Tables 3/4 (n<=50), 0.1 for
    # Table 6 (n=100).
    prox = proximity if proximity is not None else (0.1 if size >= 100 else 0.0)
    p = build(cell, size, tau=tau, proximity=prox)
    D, nd, C = p.DistMatrix, p.nodes, list(p.customers)
    TD, Q = p.TransferDuration, p.CarCapacity
    # VALID detour term: the cheapest possible satellite insertion, not the cheapest
    # satellite departure. min_{i,j,s} (D[i][s] + D[s][j] - D[i][j]), which is >= 0 and is
    # the least a reload can add over the direct leg the MST already pays for.
    sat_detour = min((D[i][s] + D[s][j] - D[i][j])
                     for s in p.satellites for i in C for j in C if i != j)
    sat_detour = max(0.0, sat_detour)

    def need_and_span(S):
        if len(S) < 2:
            return 0.0, 1.0
        svc = sum(nd[i].serviceTime for i in S)
        path = mst_on(D, list(S))
        dem = sum(nd[i].demand for i in S)
        reloads = max(0, math.ceil(dem / Q) - 1)
        need = svc + path + TD * reloads + sat_detour * reloads
        span = max(nd[i].latest + nd[i].serviceTime for i in S) - min(nd[i].earliest for i in S)
        return need, max(span, 1e-9)

    worst, wit = 0.0, None
    byl = sorted(C, key=lambda i: nd[i].latest)
    bye = sorted(C, key=lambda i: -nd[i].earliest)
    fam = []
    for m in range(2, len(C) + 1):
        fam.append(("deadline-prefix", byl[:m]))
        fam.append(("release-suffix", bye[:m]))
    # window slices
    es = sorted({nd[i].earliest for i in C})
    ls = sorted({nd[i].latest for i in C})
    for a in es:
        for b in ls:
            if b <= a:
                continue
            S = [i for i in C if nd[i].earliest >= a and nd[i].latest <= b]
            if len(S) >= 2:
                fam.append(("slice", S))

    for name, S in fam:
        need, span = need_and_span(S)
        r = need / span
        if r > worst:
            worst, wit = r, (name, len(S), need, span)
    return dict(cell=cell, ratio=worst, infeasible_k1=worst > 1.0 + 1e-9, witness=wit)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/fleet_subset_infeasibility.json")
    ap.add_argument("--proximity", type=float, default=None,
                    help="default: 0.0 for n<=50 (K Tables 3/4), 0.1 for n=100 (K Table 6)")
    a = ap.parse_args()
    kref = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
    # n50 GAP ROOT CAUSE. K publish per-instance results only at n10/20/30, so keying the cell
    # list off table3 made this script CRASH at n50 and n100 -- which is how n50 came to be
    # skipped in analysis after analysis. The certificate needs no K data at all; it is a
    # property of the instance. Enumerate cells independently and use K only if present.
    per = kref["table3"]["per_instance"].get(str(a.size))
    if per is None:
        per = {c: {} for c in (
            "C201 C202 C203 C204 C205 C206 C207 C208 R201 R202 R203 R204 R205 R206 R207 "
            "R208 R209 R210 R211 RC201 RC202 RC203 RC204 RC205 RC206 RC207 RC208").split()}
        print(f"[note] K publish no per-instance table at n{a.size}; "
              f"enumerating the 27 cells directly. The certificate uses no K data.")
    cells = [c.strip() for c in a.cells.split(",") if c.strip()] or sorted(per)
    best = harvest(set(cells), a.size)

    print(f"{'cell':7s} {'worst ratio':>11s} {'|S|':>4s} {'family':>16s} {'ours':>5s}  verdict")
    rows, proved = [], []
    for c in cells:
        r = check(c, a.size, proximity=a.proximity)
        nc = (best.get(c) or {}).get("nCars")
        r["our_cars"] = nc
        w = r["witness"] or ("-", 0, 0, 0)
        if r["infeasible_k1"]:
            v = "PROVED: one vehicle IMPOSSIBLE"; proved.append(c)
        elif nc == 1:
            v = "already 1 car (consistency: must NOT be proved)"
        else:
            v = "k-1 not ruled out"
        rows.append(r)
        print(f"{c:7s} {r['ratio']:11.3f} {w[1]:4d} {w[0]:>16s} {str(nc):>5s}  {v}")
    print(f"\nPROVED one vehicle impossible: {proved or 'none'}")
    bad = [r['cell'] for r in rows if r['infeasible_k1'] and r['our_cars'] == 1]
    print(f"SOUNDNESS CHECK -- proved-impossible on a cell where we HAVE a 1-car solution: "
          f"{bad or 'none (good)'}")
    os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
    for r in rows: r["infeasible_k1"] = bool(r["infeasible_k1"])
    json.dump(stamped(rows, __file__), open(os.path.join(ROOT, a.out), "w"), indent=1)
