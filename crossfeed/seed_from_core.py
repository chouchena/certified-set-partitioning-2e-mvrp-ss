"""
seed_from_core.py -- build a full feasible joint incumbent from a block-A(H)
proven core.

  1. block-A(H) at the given k  -> proven street routing over the |H| core
  2. cheapest-insert the k dropped customers into those routes
  3. keep the core's transfer set (vi) + satellite assignment (hubs); inserted
     customers are covered by the route's existing end-of-route transfer
  4. build the water side with ConstructivePrimal._route_vessels
  5. verify -> a self-contained joint incumbent (`seed_UB`)

Writes the solution dict to JSON for fixopt --warm-json to consume as its
initial incumbent (the coupling: core -> fixopt seed).
"""
from __future__ import annotations
import argparse, json, sys, time
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
from solver.config import InstanceSpec
from solver.problem import SolverProblem
from solver.engines.construct import ConstructivePrimal


def _routes_from_arcs(arcs, depot=0):
    succ = {}
    for i, j in arcs:
        succ.setdefault(i, []).append(j)
    routes = []
    for s in list(succ.get(depot, [])):
        r, cur, seen = [], s, set()
        while cur != depot and cur not in seen:
            r.append(cur); seen.add(cur)
            nx = [x for x in succ.get(cur, []) if x != cur]
            cur = nx[0] if nx else depot
        routes.append(r)
    return routes


def _trip_loads(p, core_arcs, transfers):
    """demand carried on the street trip that ENDS at each transfer customer."""
    nd = p.nodes
    succ = {}
    for i, j in core_arcs:
        succ[i] = j
    tset = set(transfers)
    loads = {}
    for s in [j for (i, j) in core_arcs if i == 0]:
        cur, acc = s, 0.0
        seen = set()
        while cur != 0 and cur not in seen:
            seen.add(cur)
            acc += nd[cur].demand
            if cur in tset:
                loads[cur] = acc
                acc = 0.0
            cur = succ.get(cur, 0)
    return loads


def _vessels_tw(p, transfers, hubs, ui_min, load_of):
    """capacity + CDC-time feasible vessel tours (verifier W-LOAD / W-TIMEFLOW).
    Greedy: transfers in u-order; a vessel takes the next transfer iff load fits
    and it is time-reachable from the vessel's last stop given CDC-return slack.
    """
    D, CDC, tau, cap = p.DistMatrix, p.CDC, p.TransferDuration, p.VesselCapacity
    latest = p.nodes[CDC].latest
    hub_of = {t: h for t, h in zip(transfers, hubs)}
    order = sorted(transfers, key=lambda t: ui_min.get(t, 0.0))
    yij, vroutes = [], []
    unassigned = list(order)
    while unassigned:
        vr, load, prev, prev_u = [], 0.0, CDC, p.nodes[CDC].earliest
        rest = []
        for t in unassigned:
            ht = hub_of[t]
            phub = CDC if prev == CDC else hub_of[prev]
            need = prev_u + (tau if prev != CDC else 0.0) + D[phub][ht]
            slack_ub = latest - tau - D[ht][CDC]
            lt = load_of.get(t, p.nodes[t].demand)
            if vr and (load + lt > cap + 1e-6 or need > slack_ub + 1e-6):
                rest.append(t); continue
            vr.append(t); load += lt
            prev, prev_u = t, max(ui_min.get(t, 0.0), need)
        vroutes.append(vr)
        unassigned = rest
    for vr in vroutes:
        prev = CDC
        for t in vr:
            yij.append([prev, t]); prev = t
        yij.append([prev, CDC])
    return yij, len(vroutes)


def build_seed(name, size, k, *, tl_blocka=450, workers=4):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl_blocka)
    D = p.DistMatrix
    s, w, ctx = scarcity_and_weights(p)
    _e = easiness(ctx, w)
    order = sorted(_e, key=lambda c: -_e[c])
    E = order[:k]
    wlb = water_lb_scaled(p)[0] / SCALE

    ba = BlockA(p, integral=True, timing_mode="bigM", drop=set(E))
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    t0 = time.time()
    r = ba.solve(time_limit=tl_blocka, track_progress=False)
    xs = r.get("xij_sol") or {}
    core_arcs = [list(a) for a, v in xs.items() if v == 1]
    LB = (r["value"] + wlb) if r["value"] is not None else None
    print(f"[seed] block-A(H) k={k} zA={r['value']} proven={r['proven']} "
          f"LB={LB and round(LB,2)}  {time.time()-t0:.0f}s", flush=True)

    # --- E customers as singleton routes; H exactly as the proven core ---
    # block-A's street solution is timing-feasible in block-A's own model
    # (satellite-detour timing incl.).  Any re-derivation of the schedule here
    # (naive TW checks, trip re-stitching) drifts and injects S-TW violations.
    # So: keep the core arcs / transfers / satellite assignment verbatim for H;
    # give each dropped customer its own route 0 -> c -> 0 (c is a transfer to
    # its nearest satellite -- always feasible since c's own window is).
    # fixopt's route_merge / fix_routing then fold the singletons into the core.
    nd, Q = p.nodes, p.CarCapacity
    vi_sol = r.get("vi_sol") or {}
    vip_sol = r.get("vip_sol") or {}
    sats = list(p.satellites)

    core_transfers = [i for i, v in vi_sol.items() if v > 0.5]
    core_hub = {}
    for i in core_transfers:
        pp = next((q for (ii, q), v in vip_sol.items() if ii == i and v > 0.5), None)
        core_hub[i] = pp if pp is not None else min(sats, key=lambda q: D[i][q])

    spec = InstanceSpec(name, size)
    prob = SolverProblem(spec)

    def assemble(mode):
        """mode='insert' weaves E into core trips; 'singleton' gives each its
        own route (always valid, but +1 vehicle each)."""
        arcs = [list(a) for a in core_arcs]
        transfers = list(core_transfers)
        hub = dict(core_hub)
        if mode == "singleton":
            for c in E:
                arcs.append([0, c]); arcs.append([c, 0])
                transfers.append(c); hub[c] = min(sats, key=lambda q: D[c][q])
            return arcs, transfers, [hub[t] for t in transfers]
        # 'insert': put each E customer on the cheapest existing arc whose tail
        # is NOT a transfer (don't cross a trip boundary).  Verified afterwards;
        # the caller falls back to 'singleton' if this doesn't pass.
        tset = set(transfers)
        for c in sorted(E, key=lambda c: -nd[c].demand):
            best, bd = None, 1e18
            for a in arcs:
                i, j = a
                if i in tset:
                    continue
                d = D[i][c] + D[c][j] - D[i][j]
                if d < bd:
                    bd, best = d, a
            if best is None:
                arcs.append([0, c]); arcs.append([c, 0]); transfers.append(c)
                hub[c] = min(sats, key=lambda q: D[c][q]); tset.add(c)
            else:
                i, j = best
                arcs.remove(best); arcs.append([i, c]); arcs.append([c, j])
        return arcs, transfers, [hub[t] for t in transfers]

    def water_and_verify(arcs, transfers, hubs):
        CDC = p.CDC
        ui_sol = r.get("ui_sol") or {}
        umin = {}
        for idx, i in enumerate(transfers):
            hb = hubs[idx]
            if i in ui_sol and ui_sol[i] > 0:
                umin[i] = ui_sol[i]
            else:
                h_i = max(nd[0].earliest + D[0][i], nd[i].earliest)
                umin[i] = max(h_i + nd[i].serviceTime + D[i][hb],
                              nd[CDC].earliest + D[CDC][hb])
        load_of = _trip_loads(p, [tuple(a) for a in arcs], transfers)
        for c in transfers:
            load_of.setdefault(c, nd[c].demand)
        yij, nv = _vessels_tw(p, transfers, hubs, umin, load_of)
        nv = max(nv, p.minVessels)
        ncars = sum(1 for i, j in arcs if i == 0)
        s = {"xij": [list(a) for a in arcs], "vi": list(transfers),
             "hubs": list(hubs), "yij": yij, "nCars": ncars,
             "nVessel": nv, "objVal": None}
        return s, prob.verify(s)

    arcs, transfers, hubs = assemble("insert")
    sol, vd = water_and_verify(arcs, transfers, hubs)
    if not vd.ok:
        print(f"[seed] insert invalid ({vd.violations[:1]}) -> singleton fallback", flush=True)
        arcs, transfers, hubs = assemble("singleton")
        sol, vd = water_and_verify(arcs, transfers, hubs)

    n_cars, n_vessel = sol["nCars"], sol["nVessel"]
    sol["objVal"] = vd.recomputed_obj
    print(f"[seed] seed_UB verify ok={vd.ok}  obj={vd.recomputed_obj}  "
          f"cars={n_cars} vessels={n_vessel}  viol={vd.violations[:2]}", flush=True)
    return sol, LB, vd


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--tl-blocka", type=int, default=450)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sol, LB, vd = build_seed(a.cell, a.size, a.k, tl_blocka=a.tl_blocka, workers=a.workers)
    out = a.out or f"crossfeed/seed_{a.cell}_n{a.size}.json"
    json.dump({"sol": sol, "LB": LB, "verify_ok": vd.ok,
               "seed_UB": vd.recomputed_obj}, open(out, "w"), indent=1, default=str)
    print(f"[seed] wrote {out}")
    if LB and vd.recomputed_obj:
        print(f"[seed] prov_LB% = {(vd.recomputed_obj - LB)/vd.recomputed_obj*100:.1f}%")
