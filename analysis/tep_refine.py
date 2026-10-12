"""Deterministic local search over OUR street representation, re-scored through the exact water stage.

PRE-REGISTERED in validation/PREREG_local_search_refine.md (2026-09-26 14:55) before this file
existed. Author: "Do we have headroom for search refining?" At n30 the whole method charges a median
76 s per cell against a 5760 s envelope and there is NO improvement heuristic anywhere in the route
(d465). This is that heuristic. It borrows nothing from the predecessors: the moves are textbook
relocate / swap / trip-move / hub-change over our own solution object; feasibility is our own
re-timing (windows, tau-spacing, depot and CDC windows, LEFV capacity); the score is the TRUE
objective via `tep_water_opt.optimal_tours`; acceptance is strict improvement; the loop is
deterministic (fixed move order, fixed caps, no RNG).

WHAT IT CANNOT DO. It polishes a solution inside its neighbourhood. RC202 needed a different
PARTITION found by a 55-trip pool (d467); relocate/swap will not re-partition from a 3-car start.
And on the 20 n30 cells AT their proven car floor it must never change the car count (gate G4): a
car change there contradicts a proven bound and is a defect, not a find.

SOLUTION OBJECT. chains: list of lists of trips; trip: list of customers; hub: per trip. The last
customer of every trip except a chain's last is a transfer. Re-timing walks each chain forward:
depot -> trip customers -> hub (transfer, tau wait) -> next trip's first customer ... -> depot.
Vessel arrival bound u >= H0 + D[CDC][hub] and the CDC return u + tau + D[hub][CDC] <= CDC.latest
mirror assemble_precluster.chain. Same-hub transfers must be tau apart (booking).

    python analysis/tep_refine.py C206 --size 30 --max-moves 2000 --stall 200
    python analysis/tep_refine.py C206 --size 30 --max-moves 0        # dry run: reproduces banked, banks nothing
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity, k_best_incumbent
from tep_chain_own_water import objective, water_tours
from tep_water_opt import optimal_tours
from instance_view import LEFV_CAPACITY, VESSEL_CAPACITY
from greedy26 import TOL
from stamp import stamped

DIRS = ("", "ceil", "selchain", "forced", "refine", "alns")


def banked_best(cell, size):
    best = None
    for sub in DIRS:
        p = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, size))
        if os.path.exists(p):
            d = json.load(io.open(p, encoding="utf-8"))
            if best is None or float(d["objVal"]) < best[0]:
                best = (float(d["objVal"]), p, d)
    return best


def decode(inst, sol):
    """Banked artifact -> (chains, hub). Walk each car's street path; a trip ends at a transfer."""
    dep = inst.depot
    nxt, starts = {}, []
    for a, b in sol["xij"]:
        a, b = int(a), int(b)
        if a == dep:
            starts.append(b)
        else:
            nxt[a] = b
    hub = {int(x): int(h) for x, h in zip(sol["vi"], sol["hubs"])}
    chains = []
    for s0 in sorted(starts):
        trips, cur, trip = [], s0, []
        while cur is not None and cur != dep:
            trip.append(cur)
            if cur in hub:
                trips.append(trip); trip = []
            cur = nxt.get(cur)
        if trip:
            trips.append(trip)
        chains.append(trips)
    return chains, hub


def _pass(inst, chains, hub, floor):
    """One forward timing pass. `floor` = per-transfer earliest u forced by booking. None if infeasible."""
    nd, D, tau, dep, CDC = inst.nodes, inst.D, float(inst.tau), inst.depot, inst.CDC
    H0, H1 = float(nd[dep].earliest), float(nd[dep].latest)
    a, u, tload = {}, {}, {}
    for ch in chains:
        t = H0; prev = dep
        for ti, trip in enumerate(ch):
            load = 0.0
            for c in trip:
                t = max(t + D[prev][c], float(nd[c].earliest))
                if t > float(nd[c].latest) + TOL:
                    return None
                if t > H1 - D[c][dep] - float(nd[c].service) - tau + TOL:
                    return None
                a[c] = t; t += float(nd[c].service); load += float(nd[c].demand); prev = c
            if load > LEFV_CAPACITY + TOL:
                return None
            last = trip[-1]
            if last not in hub:                             # EVERY trip ends at a satellite
                return None
            p = hub[last]
            ut = max(t + D[last][p], H0 + D[CDC][p], floor.get(last, H0))
            if ut + tau + D[p][dep] > H1 + TOL or ut + tau + D[p][CDC] > float(nd[CDC].latest) + TOL:
                return None
            u[last] = ut; tload[last] = load
            t = ut + tau; prev = p                          # the last trip returns hub -> depot inside the bound above
    return a, u, tload


def retime(inst, chains, hub, _floor=None, _depth=0):
    """Our own feasibility check with COMPLETE booking resolution.

    Same-hub transfers must sit tau apart. An earliest-start pass may put two closer than tau; the
    clash can be resolved by delaying EITHER one (chain() picks whichever keeps every downstream
    window). The first version only ever pushed the later transfer and rejected C203 (n30), whose
    verifier-clean artifact delays the EARLIER one past the later. Now both orders are tried, depth-
    first, deterministic by pair order, bounded at 8 clashes deep (2^8 leaves at worst). Times only
    increase and are bounded by H1, so every branch terminates.
    """
    from greedy26 import TOL as _T
    tau = float(inst.tau)
    floor = dict(_floor or {})
    r = _pass(inst, chains, hub, floor)
    if r is None:
        return None
    a, u, tload = r
    byhub = {}
    for c, ut in u.items():
        byhub.setdefault(hub[c], []).append((ut, c))
    for p, ts in sorted(byhub.items()):
        ts.sort()
        for (x, cx), (y, cy) in zip(ts, ts[1:]):
            if y < x + tau - _T:
                if _depth >= 8:
                    return None
                # option A: push the later transfer to earlier + tau
                fa = dict(floor); fa[cy] = max(fa.get(cy, 0.0), x + tau)
                ra = retime(inst, chains, hub, fa, _depth + 1)
                if ra is not None:
                    return ra
                # option B: push the EARLIER transfer past the later one
                fb = dict(floor); fb[cx] = max(fb.get(cx, 0.0), y + tau)
                return retime(inst, chains, hub, fb, _depth + 1)
    return a, u, tload


def score(inst, chains, hub, cache, exact=True):
    """True objective after the exact water stage; None if infeasible. Cached on structure.
    exact=False (2026-09-26, PREREG_uniform_pipeline S3): the GREEDY water stage instead -- a surrogate for search at sizes
    where the exact stage is work-limited; a value the search must confirm with exact=True before it is banked."""
    key = (bool(exact), tuple(tuple(tuple(t) for t in ch) for ch in chains), tuple(sorted(hub.items())))
    if key in cache:
        return cache[key]
    rt = retime(inst, chains, hub)
    if rt is None:
        cache[key] = None; return None
    a, u, tload = rt
    vi = [tr[-1] for ch in chains for tr in ch]          # every trip transfers
    hub_of = {c: hub[c] for c in vi}
    if vi and exact:
        ex = optimal_tours(inst, vi, hub_of, u, tload, cap=30.0, work=30.0)
        if ex is None:
            cache[key] = None; return None
        yij, nves, _ = ex
    elif vi:
        yij, nves, _ = water_tours(inst, vi, [hub_of[c] for c in vi], u, tload)
    else:
        yij, nves = [], 0
    xij, D, dep = [], inst.D, inst.depot
    for ch in chains:
        prev = dep
        for tr in ch:
            for c in tr:
                xij.append([prev, c]); prev = c
        xij.append([prev, dep])
    sol = dict(xij=xij, vi=vi, hubs=[hub_of[c] for c in vi], yij=yij, nCars=len(chains), nVessel=nves,
               hi={str(k): float(v) for k, v in a.items()}, ui={str(k): float(v) for k, v in u.items()})
    val = objective(inst, sol, hub_of)
    sol["objVal"] = val                                  # d487: was missing -> every improvement failed verifier3 A-OBJVAL
    cache[key] = (val, sol)
    return cache[key]


def neighbours(chains, hub, sats):
    """Deterministic move generator. Yields (name, new_chains, new_hub). Order is fixed."""
    C = [[list(t) for t in ch] for ch in chains]
    # relocate customer c from (i,j,k) to position q of trip (i2,j2)
    for i, ch in enumerate(C):
        for j, tr in enumerate(ch):
            for k in range(len(tr)):
                c = tr[k]
                for i2, ch2 in enumerate(C):
                    for j2, tr2 in enumerate(ch2):
                        if (i2, j2) == (i, j) and len(tr) == 1:
                            continue
                        for q in range(len(tr2) + 1):
                            if (i2, j2) == (i, j) and q in (k, k + 1):
                                continue
                            N = [[list(t) for t in c_] for c_ in C]
                            src = N[i][j]; src.pop(k)
                            dst = N[i2][j2]
                            qq = q if not ((i2, j2) == (i, j) and q > k) else q - 1
                            dst.insert(qq, c)
                            if not src:
                                del N[i][j]
                                if not N[i]:
                                    del N[i]
                            H = {t[-1]: hub.get(t[-1], sats[0]) for ch_ in N for t in ch_}
                            yield ("relocate", N, H)
    # swap two customers in different trips
    flat = [(i, j, k) for i, ch in enumerate(C) for j, tr in enumerate(ch) for k in range(len(tr))]
    for x in range(len(flat)):
        for y in range(x + 1, len(flat)):
            (i, j, k), (i2, j2, k2) = flat[x], flat[y]
            if (i, j) == (i2, j2):
                continue
            N = [[list(t) for t in c_] for c_ in C]
            N[i][j][k], N[i2][j2][k2] = N[i2][j2][k2], N[i][j][k]
            H = {t[-1]: hub.get(t[-1], sats[0]) for ch_ in N for t in ch_}
            yield ("swap", N, H)
    # move a whole trip to another chain position (keeps car count unless a chain empties)
    for i, ch in enumerate(C):
        for j in range(len(ch)):
            for i2, ch2 in enumerate(C):
                for q in range(len(ch2) + 1):
                    if i2 == i and q in (j, j + 1):
                        continue
                    N = [[list(t) for t in c_] for c_ in C]
                    tr = N[i].pop(j)
                    qq = q if not (i2 == i and q > j) else q - 1
                    N[i2].insert(qq, tr)
                    if not N[i]:
                        del N[i]
                    H = {t[-1]: hub.get(t[-1], sats[0]) for ch_ in N for t in ch_}
                    yield ("tripmove", N, H)
    # hub change on a transfer
    for i, ch in enumerate(C):
        for j, tr in enumerate(ch):
            for p in sats:
                if p != hub.get(tr[-1]):
                    H = dict(hub); H[tr[-1]] = p
                    yield ("hub", C, H)


def refine(inst, chains, hub, max_moves, stall, wall, incumbent_val=None, surrogate=False):
    sats = list(inst.satellites)
    cache = {}
    cur = score(inst, chains, hub, cache, exact=not surrogate)   # surrogate (PREREG_uniform_pipeline Amendment 2): greedy water during the sweep, exact before accepting
    if cur is None:
        # d488: never crash on an incumbent. Its artifact is verifier3-clean, so score it from its
        # own times and search from there; record that our re-timer disagreed so the gap is visible.
        print("  NOTE: our re-timer rejects the banked incumbent; scoring it from the artifact's own times", flush=True)
        if incumbent_val is None:
            raise RuntimeError("incumbent does not re-time and no incumbent_val was given for the fallback")
        cur = (float(incumbent_val), None)          # search proceeds from the artifact's value; any accepted move is re-timed and verified
    best_val, best = cur
    if incumbent_val is not None and best_val > float(incumbent_val) + 1e-6:
        # d489: our re-timer's schedule can make the water cover WORSE than the artifact's (n30: 0.0-0.5%),
        # so re-scoring the incumbent overstates its cost. Anchor acceptance on the artifact's TRUE value;
        # `best` stays None until a move genuinely beats it, and banking compares to the artifact anyway.
        best_val, best = float(incumbent_val), None
    evaluated = accepted = since = feasible = infeasible = 0
    by_type = {}
    best_sur = cur[0] if cur else float("inf"); exact_calls = 0
    t0 = time.time()
    improved = True
    while improved and evaluated < max_moves and since < stall and time.time() - t0 < wall:
        improved = False
        for name, N, H in neighbours(chains, hub, sats):
            if evaluated >= max_moves or since >= stall or time.time() - t0 >= wall:
                break
            evaluated += 1
            r = score(inst, N, H, cache, exact=not surrogate)
            if r is None:
                infeasible += 1
                continue                                   # PREREG Amendment 1: infeasible moves do NOT count toward stall
            feasible += 1
            if surrogate:
                if r[0] < best_sur - 1e-6:                    # surrogate says improving: confirm with the exact water stage, re-anchor the bar
                    exact_calls += 1; best_sur = r[0]; rx = score(inst, N, H, cache, exact=True)
                    r = rx if (rx is not None and rx[0] < best_val - 1e-6) else None
                else:
                    r = None
                if r is None:
                    since += 1
                    continue
            if r[0] < best_val - 1e-6:
                best_val, best = r; chains, hub = N, H
                accepted += 1; since = 0; by_type[name] = by_type.get(name, 0) + 1
                improved = True
                break                                      # first-improvement, restart the sweep
            since += 1                                     # feasible but not improving
    return best_val, best, dict(evaluated=evaluated, feasible=feasible, infeasible=infeasible, accepted=accepted, by_type=by_type,
                                secs=round(time.time() - t0, 1), cache=len(cache), surrogate=bool(surrogate), exact_calls=exact_calls)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+"); ap.add_argument("--size", type=int, default=30); ap.add_argument("--surrogate", action="store_true", help="greedy-water scoring during the sweep, exact confirmation before accepting (PREREG_uniform_pipeline Amendment 2)"); ap.add_argument("--no-bank", action="store_true", help="smoke mode: verify and report, write nothing into the production dirs")
    ap.add_argument("--max-moves", type=int, default=2000); ap.add_argument("--stall", type=int, default=200)
    ap.add_argument("--wall", type=float, default=600.0, help="safety only; the primary stops are the two caps")
    ap.add_argument("--tag", default="refine")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    out = []
    for cell in a.cells:
        inst = V.load_instance(cell, a.size, prox)
        kb, _ = k_best_incumbent(cell, a.size)
        bb = banked_best(cell, a.size)
        if bb is None:
            out.append(dict(cell=cell, skipped="no banked solution")); print("  %s: no banked solution" % cell); continue
        base, bp, bsol = bb
        chains, hub = decode(inst, bsol)
        cars0 = len(chains)
        print("%s n%d: banked %.3f (%s, %d cars) | their best %s" % (cell, a.size, base, os.path.relpath(bp, ROOT), cars0, ("%.1f" % kb) if kb else "n/a"), flush=True)
        obj, sol, stats = refine(inst, chains, hub, a.max_moves, a.stall, a.wall, incumbent_val=base, surrogate=a.surrogate)   # refine returns (value, sol_dict, stats)
        cars_after = sol["nCars"] if sol is not None else cars0      # sol is None when no move beat the ANCHORED incumbent (d489); crashed here on C207 n30, 2026-09-26
        rec = dict(cell=cell, banked=base, refined=obj, cars_before=cars0, cars_after=cars_after, **stats)
        print("  refined %.3f (%+.3f%%) | %d cars -> %d | %d evaluated (%d feasible), %d accepted %s | %.0fs"
              % (obj, 100 * (obj / base - 1), cars0, cars_after, stats["evaluated"], stats["feasible"], stats["accepted"], stats["by_type"], stats["secs"]), flush=True)
        if sol is None:                                 # fallback path with no accepted move
            print("  incumbent kept (re-timer disagreed, no accepted move)"); out.append(dict(cell=cell, banked=base, refined=base, result="no improvement", retimer_disagreed=True, **stats)); continue
        if a.max_moves == 0:
            rec["dry_run"] = True; rec["reproduces_banked"] = abs(obj - base) < 1e-5 * max(1.0, base)   # relative: the exact water re-score can return an equal-cost tour set differing in the 3rd decimal
            print("  DRY RUN: re-timed banked solution reproduces %.3f -> %s" % (base, "YES" if rec["reproduces_banked"] else "NO -- our re-timing disagrees with the artifact"), flush=True)
            out.append(rec); continue
        if obj < base - 1e-6:
            run = V.verify_solution(inst, sol, cell=cell, size=a.size, proximity=prox, label="refine")
            bad = [x for x in run.findings if x.severity != "TOLERANCE"]
            if bad or run.blocking:
                rec["result"] = "REJECTED by verifier3"; rec["findings"] = [str(x.cls) for x in bad[:4]]
                print("  -> beats banked but FAILS verifier3: %s" % ", ".join(rec["findings"]), flush=True)
            elif a.no_bank:
                rec["result"] = "verified, NOT banked (smoke mode)"; print("  -> beats banked, verifier3 PASS, not banked (--no-bank)", flush=True)
            else:
                dst = os.path.join(ROOT, "runs", "postpass", "refine")
                if not os.path.isdir(dst):
                    os.makedirs(dst)
                sol["size"] = a.size; sol["_proximity"] = prox; sol["_verified"] = True
                sol["selection"] = "local search (relocate/swap/tripmove/hub), exact water"
                sol["superseded_objVal"] = base; sol["superseded_from"] = os.path.relpath(bp, ROOT)
                sol["secs"] = stats["secs"]; sol["moves_evaluated"] = stats["evaluated"]
                sol["by_type"] = stats.get("by_type")     # d552: accepted moves per operator (relocate/swap/tripmove/hub)
                sol["stats"] = stats
                json.dump(stamped(sol, "analysis/tep_refine.py"), io.open(os.path.join(dst, "ownwater_%s_n%d.json" % (cell, a.size)), "w", encoding="utf-8"), indent=1, default=str)
                rec["result"] = "IMPROVED"; rec["gain_pct"] = 100 * (1 - obj / base)
                print("  -> IMPROVED and banked under runs/postpass/refine/ | vs their best %+.2f%%" % (100 * (obj / kb - 1) if kb else float("nan")), flush=True)
        else:
            rec["result"] = "no improvement"
        out.append(rec)
        json.dump(stamped(dict(size=a.size, tag=a.tag, cells=out)), io.open(os.path.join(ROOT, "runs", "oracle", "tep_refine_%s_n%d.json" % (a.tag, a.size)), "w", encoding="utf-8"), indent=1, default=str)
    imp = [r for r in out if r.get("result") == "IMPROVED"]
    print("\n  %d cell(s): %d improved | car count changed on %d" % (len(out), len(imp), sum(1 for r in out if r.get("cars_after") not in (None, r.get("cars_before")))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
