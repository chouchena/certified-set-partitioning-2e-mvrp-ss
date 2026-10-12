"""
mfree_cuts.py -- can M-free timing + rounded-capacity street cuts prove block-A
over a LARGER H (smaller k) than plain big-M, recovering reduction tax?

ADAPTIVE calibration (so it transfers to |C|=30/50):
  * calibrate the per-solve budget from the FRONTIER solve's wall time:
        tl_descent = clamp(TL_MULT * frontier_wall, TL_MIN, TL_MAX)
        filter_budget = tl_descent / FILTER_DIV
  * projection-based abandonment: after the filter window, extrapolate the dual
    bound with its recent slope; abandon k (and lower) if
        bound + slope * remaining  <  PROJ_FRAC * target
  * adaptive descent depth: stop when a proven step gains < MIN_GAIN_FRAC of the
    bound (diminishing returns) OR k < DEPTH_FRAC * frontier.
  * RCC cluster sizes / subset count scale with |H|.

Typical ~4-7 solves/cell; the budgets grow with instance size on their own.
"""
from __future__ import annotations
import argparse, math, sys, time
import numpy as np
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
from analysis.ledger import emit as _emit

TL_MULT, TL_MIN, TL_MAX = 2.5, 300, 1800
FILTER_DIV = 5
PROJ_FRAC = 0.90            # projected bound must reach this * target to continue
MIN_GAIN_FRAC = 0.01       # stop descent when a proven step gains < 1% of the bound
DEPTH_FRAC = 0.45          # never descend below this * frontier


def add_rcc(ba, p, H):
    """PROBLEM-AWARE valid cuts for the MULTI-TRIP block-A.

    The model: each customer has 1 in/1 out arc; `nofCars` = # routes (0->..->0);
    each route holds multiple TRIPS separated by vi=1 transfers where the load
    resets. So capacity bounds the # of trips (Sum vi), NOT nofCars; and route
    length is bounded by the garage/depot horizon -> time bounds nofCars.
    """
    m, x, Q, nd, TD = ba.m, ba.xij, p.CarCapacity, p.nodes, p.TransferDuration
    D = p.DistMatrix
    Sats = list(ba.Sats)
    arcset = set(ba.arcList)
    n = 0
    demH = sum(nd[c].demand for c in H)
    trips_lb = math.ceil(demH / Q)

    # (1) trip count: every trip carries <= Q and ends in a transfer
    m.add_constraint(m.sum(ba.vi[i] for i in H) >= trips_lb); n += 1

    # (2) route count from TIME. total work spread over nofCars routes, each
    #     bounded by the horizon.  work >= service + a spanning-tree travel LB
    #     + trip transfer time.
    horizon = nd[0].latest - nd[0].earliest
    svc = sum(nd[c].serviceTime for c in H)
    # 1-tree-ish travel LB over H u {0}: sum of each node's cheapest incident edge / 2
    nodes = [0] + list(H)
    dmin = 0.0
    for a in nodes:
        cheapest = min(D[a][b] for b in nodes if b != a)
        dmin += cheapest
    travel_lb = dmin / 2.0
    work_lb = svc + travel_lb + trips_lb * TD
    routes_lb = max(1, math.ceil(work_lb / horizon))
    if routes_lb >= 2:
        m.add_constraint(ba.nofCars >= routes_lb); n += 1

    # (3) forced transfer: a customer with no time-feasible in-trip successor
    #     must end its trip (vi = 1)
    for i in H:
        succ_ok = any(
            (i, j) in arcset and
            nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest
            for j in H if j != i)
        if not succ_ok:
            m.add_constraint(ba.vi[i] == 1); n += 1

    # (4) time-window infeasible triples: if no ordering of {i,j,k} fits one
    #     trip window, forbid the 3-cycle among them
    Hl = list(H)
    def reach(a, b):
        return nd[a].earliest + nd[a].serviceTime + D[a][b] <= nd[b].latest
    cnt = 0
    for a in range(len(Hl)):
        for b in range(a + 1, len(Hl)):
            i, j = Hl[a], Hl[b]
            if (i, j) not in arcset and (j, i) not in arcset:
                continue
            for c in Hl[b + 1:]:
                perms = [(i, j, c), (i, c, j), (j, i, c), (j, c, i), (c, i, j), (c, j, i)]
                if not any(reach(p1, p2) and reach(p2, p3) for (p1, p2, p3) in perms):
                    tri = [t for t in [(i, j), (j, c), (c, i), (j, i), (c, j), (i, c)]
                           if t in arcset]
                    if len(tri) >= 3:
                        m.add_constraint(m.sum(x[t] for t in tri) <= 1); n += 1; cnt += 1
            if cnt > 200:
                break
        if cnt > 200:
            break

    # (5) route-count lower bound from a TIME-COMPATIBILITY clique.  Two
    #     customers cannot share a route (any # of trips) if serving one then
    #     the other is time-infeasible in BOTH orders AND the second's window
    #     closes before the first's even opens (no wait can fix it).  A clique
    #     of pairwise-incompatible customers => that many routes.
    Hl2 = list(H)
    incomp = {c: set() for c in Hl2}
    for a in range(len(Hl2)):
        for b in range(a + 1, len(Hl2)):
            i, j = Hl2[a], Hl2[b]
            ij = nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest
            ji = nd[j].earliest + nd[j].serviceTime + D[j][i] <= nd[i].latest
            if not ij and not ji:
                incomp[i].add(j); incomp[j].add(i)
    # greedy clique
    clique, cand = [], sorted(Hl2, key=lambda c: -len(incomp[c]))
    for c in cand:
        if all(c in incomp[q] for q in clique):
            clique.append(c)
    if len(clique) >= 2:
        m.add_constraint(ba.nofCars >= len(clique)); n += 1
    return n


def solve_variant(name, size, k, timing, cuts, tl, workers, order, wlb, track=False):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl)
    E = set(order[:k])
    H = [c for c in p.customers if c not in E]
    ba = BlockA(p, integral=True, timing_mode=timing, drop=E)
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    nc = add_rcc(ba, p, H) if cuts else 0
    t0 = time.time()
    r = ba.solve(time_limit=tl, track_progress=True if track else None)
    wall = time.time() - t0
    br = round((r["value"] or 0) + wlb, 2) if r["value"] is not None else None
    tag = f"{timing}{'+rcc' if cuts else ''}"
    print(f"  k={k} {tag:16} zA={r['value']} proven={r['proven']} "
          f"block_relax={br} ({nc}c) {wall:.0f}s", flush=True)
    _emit("mfree_cuts", name, size,
          config=dict(timing_mode=timing, cuts=bool(cuts), k=k, tl=tl, workers=workers),
          metrics=dict(zA=r["value"], proven=bool(r["proven"]), block_relax=br,
                       n_cuts=nc, wlb=round(wlb, 2)),
          wall_s=wall, verified=None,
          notes=f"drop={sorted(order[:k])}")
    return r, br, wall


def _slope(trace):
    """(bound units)/s over the last third of the progress trace."""
    pts = [(t, bb) for (t, bb, _o) in (trace or []) if bb is not None]
    if len(pts) < 3:
        return 0.0
    tail = pts[max(0, len(pts) * 2 // 3):]
    if tail[-1][0] <= tail[0][0]:
        return 0.0
    return (tail[-1][1] - tail[0][1]) / (tail[-1][0] - tail[0][0])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--frontier", type=int, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tl-cap", type=int, default=TL_MAX)
    a = ap.parse_args()

    p0 = build(a.cell, a.size, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
    s, w, ctx = scarcity_and_weights(p0)
    _e = easiness(ctx, w)
    order = sorted(_e, key=lambda c: -_e[c])
    wlb = water_lb_scaled(p0)[0] / SCALE
    print(f"=== {a.cell}  M-free+RCC adaptive descend  frontier k*={a.frontier}  "
          f"wlb={wlb:.1f} ===", flush=True)

    # 1. frontier -- calibrates budgets
    print(f"--- k={a.frontier} (frontier: calibrate) ---", flush=True)
    r0, fb, fw = solve_variant(a.cell, a.size, a.frontier, "indicator", True,
                               min(a.tl_cap, TL_MAX), a.workers, order, wlb)
    tl_desc = int(min(a.tl_cap, max(TL_MIN, TL_MULT * fw)))
    filt = max(45, tl_desc // FILTER_DIV)
    print(f"  calibrated: frontier_wall={fw:.0f}s -> tl_descent={tl_desc}s  filter={filt}s",
          flush=True)
    best = (fb, a.frontier, "indicator+rcc") if (r0["proven"] and fb) else None
    target = best[0] if best else (fb or 0)
    kmin = max(1, math.ceil(DEPTH_FRAC * a.frontier))

    # 2-4. adaptive descend
    prev = target
    for k in range(a.frontier - 1, kmin - 1, -1):
        print(f"--- k={k}  (drop {sorted(order[:k])}) ---", flush=True)
        rf, bf, _ = solve_variant(a.cell, a.size, k, "indicator", True,
                                  filt, a.workers, order, wlb, track=True)
        if not rf["proven"]:
            sl = _slope(rf.get("progress_trace"))
            proj = (bf or 0) + sl * (tl_desc - filt)
            print(f"  filter: bound={bf} slope={sl:.2f}/s proj@{tl_desc}s={proj:.1f} "
                  f"(need {PROJ_FRAC*target:.1f})", flush=True)
            if proj < PROJ_FRAC * target:
                print(f"  -> projected miss, abandon k<= {k}", flush=True)
                break
            rf, bf, _ = solve_variant(a.cell, a.size, k, "indicator", True,
                                      tl_desc, a.workers, order, wlb)
        if rf["proven"] and bf and (best is None or bf > best[0]):
            gain = (bf - prev) / max(1.0, bf)
            best = (bf, k, "indicator+rcc"); prev = bf
            print(f"      >>> NEW BEST proven = {bf} at k={k}  (step gain {gain:.1%})",
                  flush=True)
            for (tm, ct) in (("indicator", False), ("bigM", True), ("bigM", False)):
                solve_variant(a.cell, a.size, k, tm, ct, tl_desc, a.workers, order, wlb)
            if gain < MIN_GAIN_FRAC:
                print(f"  step gain {gain:.1%} < {MIN_GAIN_FRAC:.0%} -> diminishing, stop",
                      flush=True)
                break
        elif rf["proven"]:
            print(f"  proved {bf} <= best {best[0] if best else fb} (monotone) -> stop",
                  flush=True)
            break
        else:
            print(f"  k={k} did not prove at full budget -> stop", flush=True)
            break

    print(f"\n{a.cell}: best proven block_relax = {best}  (frontier baseline {fb})",
          flush=True)
