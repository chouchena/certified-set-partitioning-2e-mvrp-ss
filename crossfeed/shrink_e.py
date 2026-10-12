"""
shrink_e.py -- recover the reduction tax: prove block-A(H) at a SMALLER |E| than
the greedy frontier, using a contention-guided E instead of the greedy prefix.

The greedy drops the k resource-lightest customers. If its k*-1 prefix doesn't
prove (-> frontier at k*), a DIFFERENTLY COMPOSED k*-1 set might -- one that
drops the customers actually blocking the proof (high spatial-weighted temporal
contention) rather than just the resource-light ones.

For k in {k*-1, k*-2}, try candidates:
  A  greedy prefix           order[:k]
  B  contention swap          order[:k] with its lowest-contention member
                              replaced by the highest-contention customer in H
  C  contention-among-easy    the k highest-contention customers among the
                              easiest ~k+4 by score
Each warm-started from the greedy frontier solution, 90s filter then full budget.
Report max proven block_relax. Monotone => any proof at k<k* strictly beats greedy.
"""
from __future__ import annotations
import argparse, math, sys, time
import numpy as np
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE


def contention(p):
    C = list(p.customers); n = len(C); nd = p.nodes
    e = np.array([nd[c].earliest for c in C], float)
    l = np.array([nd[c].latest for c in C], float)
    w = l - e
    D = np.array(p.DistMatrix, float)
    ds = float(np.median([D[C[i]][C[j]] for i in range(n) for j in range(n) if i != j]))
    con = {}
    for i in range(n):
        s = 0.0
        for j in range(n):
            if i == j:
                continue
            ov = max(0.0, min(l[i], l[j]) - max(e[i], e[j]))
            s += ov / max(1.0, w[i]) * math.exp(-D[C[i]][C[j]] / ds)
        con[C[i]] = s
    return con


def solve(p, drop, tl, workers, ws_x=None):
    ba = BlockA(p, integral=True, timing_mode="bigM", drop=set(drop))
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    r = ba.solve(time_limit=tl, track_progress=False, mip_start_x=ws_x)
    return r


def run(name, size, kstar, *, workers=4, tl_filter=90, tl_full=600):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl_full)
    D = p.DistMatrix
    s, wts, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, wts)
    order = sorted(_e, key=lambda c: -_e[c])
    con = contention(p)
    wlb = water_lb_scaled(p)[0] / SCALE
    print(f"\n=== {name}  shrink-E  frontier k*={kstar}  wlb={wlb:.1f} ===", flush=True)

    # greedy frontier solve -> warm-start routing for every trial
    gf = solve(p, order[:kstar], tl_full, workers)
    ws = gf.get("xij_sol") if gf.get("proven") else None
    gbr = round((gf["value"] or 0) + wlb, 2) if gf["value"] else None
    print(f"greedy k*={kstar}: zA={gf['value']} proven={gf['proven']} block_relax={gbr}", flush=True)

    best = (gbr, kstar, "greedy") if gf.get("proven") else (None, None, None)

    for k in (kstar - 1, kstar - 2):
        if k < 1:
            continue
        H0 = [c for c in p.customers if c not in set(order[:k])]
        cand = {"A_prefix": order[:k]}
        # B: swap lowest-contention in prefix for highest-contention in H
        pref = list(order[:k])
        lo = min(pref, key=lambda c: con[c])
        hi = max(H0, key=lambda c: con[c])
        cand["B_swap"] = [c for c in pref if c != lo] + [hi]
        # C: k highest-contention among the easiest k+4
        pool = order[:k + 4]
        cand["C_conteasy"] = sorted(pool, key=lambda c: -con[c])[:k]

        for tag, E in cand.items():
            E = list(dict.fromkeys(E))[:k]
            t0 = time.time()
            if tl_filter and tl_filter < tl_full:
                rf = solve(p, E, tl_filter, workers, ws_x=ws)
                # keep going unless the dual bound is hopelessly low
                proceed = rf["proven"] or best[0] is None or (
                    rf["value"] is not None and rf["value"] + wlb > 0.70 * best[0])
                r = rf if rf["proven"] or not proceed else solve(p, E, tl_full, workers, ws_x=ws)
            else:
                r = solve(p, E, tl_full, workers, ws_x=ws)
            br = round((r["value"] or 0) + wlb, 2) if r["value"] else None
            mark = ""
            if r.get("proven") and br and (best[0] is None or br > best[0]):
                best = (br, k, tag); mark = "  <<< NEW BEST"
            print(f"  k={k} {tag:12} E={sorted(E)}  zA={r['value']} "
                  f"proven={r['proven']} block_relax={br}  {time.time()-t0:.0f}s{mark}", flush=True)

    print(f"\n{name}: shrink-E best = {best[0]} at k={best[1]} ({best[2]})  "
          f"vs greedy {gbr}", flush=True)
    return best


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--kstar", type=int, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tl-filter", type=int, default=90)
    ap.add_argument("--tl-full", type=int, default=600)
    a = ap.parse_args()
    run(a.cell, a.size, a.kstar, workers=a.workers,
        tl_filter=a.tl_filter, tl_full=a.tl_full)
