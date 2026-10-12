"""External ALNS, capped and deterministic, starting from the banked incumbent. (PREREG_alns_bad_boys.md)

Author, 2026-09-26: "take our worst bad boys' incumbents and wire on the incumbent an external ALNS
capped search." Pre-registered in validation/PREREG_alns_bad_boys.md before this file existed: the
sample (the 15 n30 cells still above K), the seed policy, the caps, and gates G1-G6.

WHAT IT REUSES, AND WHY THAT IS THE POINT. Solution object, decode, re-timer and scorer are
tep_refine's: `retime` is complete for same-hub booking (d488) and `score` is our re-timer plus the
exact water path cover. So every candidate this search produces is a feasible solution of OUR
formulation, scored by the TRUE objective, and nothing from the predecessors' model is anywhere in
the loop. Operators are textbook (Ropke & Pisinger 2006 style): random / worst / related removal of
k customers; cheapest-insertion / regret-2 repair over existing trips; simulated-annealing
acceptance; adaptive operator weights.

THREE THINGS THE EVIDENCE OF THE DAY FORCED INTO THE DESIGN.
  * Acceptance is anchored on the ARTIFACT's objective, not on our re-score of it: our re-timer
    makes 5 of 27 n30 incumbents look up to 0.50% worse than they are (d489). A candidate's score is
    an UPPER bound on its true best value; banking compares to the artifact and requires verifier3.
  * Repair never creates a car and deletes emptied trips, so the fleet cannot grow (G4); on the 13
    target cells at their proven car floor a fleet change would contradict a proven bound.
  * Insertion positions are chosen on a STREET delta proxy plus LEFV capacity, and the full re-time
    + water score runs ONCE per repaired solution. The exact water solve is 0.0-0.1 s at n30; the
    proxy keeps the inner loop cheap enough for 3000 iterations inside the 1500 s safety wall.

    python analysis/tep_alns.py R206 RC206 --size 30 --iters 3000 --stall 600
    python analysis/tep_alns.py R206 --size 30 --iters 0          # dry run: reproduce/anchor the incumbent, bank nothing
"""
import argparse
import io
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity, k_best_incumbent
from tep_refine import decode, retime, score, banked_best
from instance_view import LEFV_CAPACITY
from stamp import stamped

CELL_INDEX = {c: i for i, c in enumerate(["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
                                          + ["RC%d" % i for i in range(201, 209)])}
DESTROY = ("random", "worst", "related")
REPAIR = ("cheapest", "regret2")


def street_delta_remove(inst, chains, c):
    """Savings from removing customer c from its trip (street proxy)."""
    D, dep = inst.D, inst.depot
    for ch in chains:
        for tr in ch:
            if c in tr:
                i = tr.index(c); prev = tr[i - 1] if i > 0 else None; nxt = tr[i + 1] if i + 1 < len(tr) else None
                if prev is None and nxt is None:
                    return 0.0
                if prev is None:
                    return D[dep][c] + D[c][nxt] - D[dep][nxt]
                if nxt is None:
                    return D[prev][c]                      # the hub leg after c is charged elsewhere
                return D[prev][c] + D[c][nxt] - D[prev][nxt]
    return 0.0


def remove(chains, cs):
    N = [[[x for x in tr if x not in cs] for tr in ch] for ch in chains]
    N = [[tr for tr in ch if tr] for ch in N]
    return [ch for ch in N if ch]


def _chain_ok(inst, ch, hub, sats):
    """One-chain earliest-start feasibility (windows, capacity, depot/CDC returns; no booking)."""
    from tep_refine import _pass
    H = {tr[-1]: hub.get(tr[-1], sats[0]) for tr in ch}
    return _pass(inst, [ch], H, {}) is not None


def complete_hubs(inst, chains, hub, sats):
    """Hub map for a trial solution. A trip whose transfer customer changed has no hub yet; d492 run-1
    fell back to sats[0], which on booking-tight cells fails. Try each satellite and keep the first
    that re-times; deterministic (satellite order fixed). Returns (H, ok)."""
    H = {tr[-1]: hub[tr[-1]] for ch in chains for tr in ch if tr[-1] in hub}
    missing = [tr[-1] for ch in chains for tr in ch if tr[-1] not in hub]
    if not missing:
        return H, retime(inst, chains, H) is not None
    for c in missing:
        placed = False
        for p in sats:
            H[c] = p
            if retime(inst, chains, {**H, **{m: sats[0] for m in missing if m not in H}}) is not None:
                placed = True; break
        if not placed:
            return H, False
    return H, retime(inst, chains, H) is not None


def _solution_ok(inst, chains, hub, sats):
    """FULL feasibility of a trial solution under our re-timer, INCLUDING cross-chain same-hub booking
    and with hubless transfers assigned the best satellite (complete_hubs)."""
    return complete_hubs(inst, chains, hub, sats)[1]


def insert_positions(inst, chains, c, hub=None, sats=None):
    """All (chain, trip, pos, street delta) where c fits by LEFV capacity AND the chain still re-times.

    d492: run 1 screened on capacity only and 75-95 percent of repairs died at re-timing before the
    water solve -- time-blind insertion, not the identity cycle I first suspected, was the cause. Each
    tentative slot is now checked with a one-chain earliest-start pass (windows, depot/CDC returns);
    same-hub booking is left to the full retime() on the repaired solution.
    """
    D, nd = inst.D, inst.nodes
    out = []
    for i, ch in enumerate(chains):
        # new single-customer trip appended to the chain: a new TRANSFER, not a new car (G4 intact)
        if hub is not None:
            trial = [[list(t) for t in c2] for c2 in chains]; trial[i].append([c])
            if _solution_ok(inst, trial, hub, sats):
                out.append((D[ch[-1][-1]][c] * 1.5, i, len(ch), 0))     # proxy: leg from the previous trip's last customer, discounted for the hub detour it replaces
        for j, tr in enumerate(ch):
            if sum(float(nd[x].demand) for x in tr) + float(nd[c].demand) > LEFV_CAPACITY + 1e-9:
                continue
            for q in range(len(tr) + 1):
                if hub is not None:
                    trial = [[list(t) for t in c2] for c2 in chains]; trial[i][j].insert(q, c)
                    if not _solution_ok(inst, trial, hub, sats):
                        continue
                prev = tr[q - 1] if q > 0 else None; nxt = tr[q] if q < len(tr) else None
                if prev is None and nxt is None:
                    d = 0.0
                elif prev is None:
                    d = D[c][nxt]
                elif nxt is None:
                    d = D[prev][c]
                else:
                    d = D[prev][c] + D[c][nxt] - D[prev][nxt]
                out.append((d, i, j, q))
    return out


def _cands(inst, C, c, hub, sats, tabu, noise, rng):
    """Feasible slots for c, minus the slot it was removed from, with multiplicative proxy noise; sorted."""
    out = []
    for d, i, j, q in insert_positions(inst, C, c, hub, sats):
        if j < len(C[i]):
            tr = C[i][j]; prev = tr[q - 1] if q > 0 else None; nxt = tr[q] if q < len(tr) else None
            if (tabu or {}).get(c) == (prev, nxt):
                continue
        out.append((d * (1.0 + noise * (2 * rng.random() - 1)), i, j, q))
    return sorted(out)


def repair(inst, chains, removed, kind, rng, tabu=None, noise=0.15, hub=None, sats=None):
    """Re-insert removed customers over EXISTING trips only; never creates a car."""
    C = [[list(tr) for tr in ch] for ch in chains]
    pending = list(removed); tabu = tabu or {}
    while pending:
        if kind == "cheapest":
            c = pending[0]
            pos = _cands(inst, C, c, hub, sats, tabu, noise, rng)
            if not pos:
                return None
            d, i, j, q = pos[0]
        else:                                              # regret-2: place the customer that loses most if delayed
            best = None
            for c in pending:
                pos = _cands(inst, C, c, hub, sats, tabu, noise, rng)
                if not pos:
                    return None
                reg = (pos[1][0] - pos[0][0]) if len(pos) > 1 else 1e9
                if best is None or reg > best[0]:
                    best = (reg, c, pos[0])
            reg, c, (d, i, j, q) = best
        if j == len(C[i]):
            C[i].append([c])
        else:
            C[i][j].insert(q, c)
        pending.remove(c)
    return C


def destroy(inst, chains, hub, kind, k, rng):
    cust = [c for ch in chains for tr in ch for c in tr]
    if len(cust) <= k:
        return None
    if kind == "random":
        cs = rng.sample(cust, k)
    elif kind == "worst":
        sav = sorted(cust, key=lambda c: -street_delta_remove(inst, chains, c))
        cs = sav[:k]
    else:                                                  # related: a seed and its k-1 nearest
        s = rng.choice(cust); D = inst.D
        cs = [s] + sorted((c for c in cust if c != s), key=lambda c: D[s][c])[:k - 1]
    return set(cs)


def alns(inst, chains, hub, incumbent_val, iters, stall, wall, seed, sats, surrogate=False):
    rng = random.Random(seed)
    cache = {}
    cur = score(inst, chains, hub, cache, exact=not surrogate)
    cur_val = cur[0] if cur else float("inf")
    best_val, best = float(incumbent_val), None            # anchored on the artifact (d489)
    best_sur = cur_val; exact_calls = 0                    # surrogate mode (PREREG_uniform_pipeline S3): search on greedy water, confirm exact
    best_ops = []                                          # audit (2026-09-27): (iteration, destroy, repair, value) of every new best
    cur_chains, cur_hub = chains, hub
    w = {(d, r): 1.0 for d in DESTROY for r in REPAIR}
    sc = {k: 0.0 for k in w}; used = {k: 0 for k in w}
    T0 = 0.005 * incumbent_val; alpha = (0.01) ** (1.0 / max(1, iters))
    T = T0
    it = since = accepted = improved = infeasible = identical = distinct = 0
    t0 = time.time()
    while it < iters and since < stall and time.time() - t0 < wall:
        it += 1
        keys = list(w); probs = [w[k] for k in keys]
        dk, rk = rng.choices(keys, weights=probs, k=1)[0]
        k = rng.choice((2, 3, 4))
        cs = destroy(inst, cur_chains, cur_hub, dk, k, rng)
        if cs is None:
            since += 1; continue
        tabu = {}
        for ch in cur_chains:
            for tr in ch:
                for q, c in enumerate(tr):
                    if c in cs:
                        tabu[c] = (tr[q - 1] if q > 0 else None, tr[q + 1] if q + 1 < len(tr) else None)
        base = remove(cur_chains, cs)
        N = repair(inst, base, sorted(cs), rk, rng, tabu=tabu, hub=cur_hub, sats=sats)
        if N is None:
            infeasible += 1; continue                      # PREREG Amendment 1: not counted toward stall
        H, hok = complete_hubs(inst, N, cur_hub, sats)
        if not hok:
            infeasible += 1; continue
        if tuple(tuple(tuple(t) for t in ch) for ch in N) == tuple(tuple(tuple(t) for t in ch) for ch in cur_chains):
            identical += 1; continue
        r = score(inst, N, H, cache, exact=not surrogate)
        used[(dk, rk)] += 1
        if r is None:
            infeasible += 1; T *= alpha; continue
        val, sol = r
        distinct += 1
        new_best = False
        if surrogate:
            if val < best_sur - 1e-6:                      # the surrogate says improving: pay for the exact water stage once
                exact_calls += 1; rx = score(inst, N, H, cache, exact=True)
                best_sur = val                             # re-anchor the surrogate bar on every checked candidate (RC208 smoke: 273 checks, 0 confirmed)
                if rx is not None and rx[0] < best_val - 1e-6:
                    best_val, best = rx[0], rx[1]; new_best = True
        elif val < best_val - 1e-6:
            best_val, best = val, sol; new_best = True
        if new_best:
            cur_chains, cur_hub, cur_val = N, H, val
            sc[(dk, rk)] += 5.0; accepted += 1; improved += 1; since = 0
            best_ops.append(dict(it=it, destroy=dk, repair=rk, value=round(best_val, 3), secs=round(time.time() - t0, 1)))
        elif val < cur_val - 1e-6:
            cur_chains, cur_hub, cur_val = N, H, val; sc[(dk, rk)] += 2.0; accepted += 1; since += 1
        elif rng.random() < math.exp(-(val - cur_val) / max(T, 1e-9)):
            cur_chains, cur_hub, cur_val = N, H, val; sc[(dk, rk)] += 1.0; accepted += 1; since += 1
        else:
            since += 1
        T *= alpha
        if it % 50 == 0:                                   # adaptive weights
            for key in w:
                if used[key]:
                    w[key] = 0.8 * w[key] + 0.2 * (sc[key] / used[key])
                sc[key] = 0.0; used[key] = 0
    return best_val, best, dict(iters=it, accepted=accepted, improved=improved, infeasible=infeasible, identical=identical, distinct_feasible=distinct,
                                stall_hit=since >= stall, wall_hit=time.time() - t0 >= wall, surrogate=bool(surrogate), exact_calls=exact_calls,
                                best_ops=best_ops,
                                secs=round(time.time() - t0, 1), weights={"%s+%s" % k: round(v, 3) for k, v in w.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cells", nargs="+"); ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--iters", type=int, default=3000); ap.add_argument("--stall", type=int, default=600)
    ap.add_argument("--wall", type=float, default=1500.0); ap.add_argument("--tag", default="alns")
    ap.add_argument("--surrogate", action="store_true", help="search on the greedy water stage, confirm improving candidates with the exact one (PREREG_uniform_pipeline S3)")
    ap.add_argument("--no-bank", action="store_true", help="smoke mode: report, verify nothing into the production dirs")
    a = ap.parse_args()
    prox = k_proximity(a.size); out = []
    for cell in a.cells:
        inst = V.load_instance(cell, a.size, prox); sats = list(inst.satellites)
        kb, _ = k_best_incumbent(cell, a.size)
        bb = banked_best(cell, a.size)
        if bb is None:
            out.append(dict(cell=cell, skipped="no incumbent")); continue
        base, bp, bsol = bb
        chains, hub = decode(inst, bsol); cars0 = len(chains)
        seed = 1000 + CELL_INDEX.get(cell, 0)
        rs = score(inst, chains, hub, {})
        rescore = rs[0] if rs else None
        print("%s n%d: incumbent %.3f (%s, %d cars) | our re-score %s | K best %s | seed %d"
              % (cell, a.size, base, os.path.relpath(bp, ROOT), cars0, ("%.3f" % rescore) if rescore else "REJECTED", ("%.1f" % kb) if kb else "n/a", seed), flush=True)
        val, sol, stats = alns(inst, chains, hub, base, a.iters, a.stall, a.wall, seed, sats, surrogate=a.surrogate)
        rec = dict(cell=cell, incumbent=base, rescore=rescore, alns=val, cars_before=cars0, seed=seed, theirs=kb, **stats)
        if a.iters == 0:
            rec["dry_run"] = True; rec["reproduces"] = rescore is not None and abs(rescore - base) <= 1e-5 * max(1.0, base)
            print("  DRY RUN: re-score %s the artifact (%+.3f%%); anchor = artifact; nothing banked" % ("reproduces" if rec["reproduces"] else "does NOT reproduce", 100 * ((rescore or base) / base - 1)), flush=True)
            out.append(rec); continue
        print("  ALNS: best %.3f (%+.3f%%) | %d iters, %d accepted, %d improving, %d infeasible | stall %s wall %s | %.0fs"
              % (val, 100 * (val / base - 1), stats["iters"], stats["accepted"], stats["improved"], stats["infeasible"], stats["stall_hit"], stats["wall_hit"], stats["secs"]), flush=True)
        if sol is not None and val < base - 1e-6 and not a.no_bank:
            if kb and val < kb - 0.05:
                kt = None
                try:
                    kt = {r["cell"]: r for r in json.load(io.open(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json"), encoding="utf-8"))["n%d" % a.size]["rows"]}[cell]
                except Exception:
                    pass
                if kt and kt.get("proven"):
                    rec["result"] = "REFUSED: below a K-PROVEN optimum -- defect, not a win"; print("  " + rec["result"]); out.append(rec); continue
            run = V.verify_solution(inst, sol, cell=cell, size=a.size, proximity=prox, label="alns")
            bad = [x for x in run.findings if x.severity != "TOLERANCE"]
            if bad or run.blocking:
                rec["result"] = "REJECTED by verifier3"; rec["findings"] = [str(x.cls) for x in bad[:4]]
                print("  -> beats incumbent but FAILS verifier3: %s" % ", ".join(rec["findings"]), flush=True)
            else:
                dst = os.path.join(ROOT, "runs", "postpass", "alns"); os.makedirs(dst, exist_ok=True)
                sol["size"] = a.size; sol["_proximity"] = prox; sol["_verified"] = True
                sol["selection"] = "ALNS from incumbent (seed %d)" % seed; sol["superseded_objVal"] = base
                sol["superseded_from"] = os.path.relpath(bp, ROOT); sol["secs"] = stats["secs"]; sol["alns_iters"] = stats["iters"]
                sol["stats"] = stats            # d552: the operator trail (best_ops: iteration, destroy, repair, value, secs)
                sol["best_ops"] = stats.get("best_ops")   # lives at top level too, so the ledger need not know the stats shape
                json.dump(stamped(sol, "analysis/tep_alns.py"), io.open(os.path.join(dst, "ownwater_%s_n%d.json" % (cell, a.size)), "w", encoding="utf-8"), indent=1, default=str)
                rec["result"] = "IMPROVED"; rec["gain_pct"] = 100 * (1 - val / base); rec["cars_after"] = sol["nCars"]
                rec["flipped_below_k"] = bool(kb and val < kb - 0.05 <= base)
                print("  -> IMPROVED and banked under runs/postpass/alns/ | vs K %+.2f%%%s" % (100 * (val / kb - 1) if kb else float("nan"), "  FLIPPED below K" if rec["flipped_below_k"] else ""), flush=True)
        else:
            rec["result"] = "no improvement"
        out.append(rec)
        json.dump(stamped(dict(size=a.size, tag=a.tag, cells=out)), io.open(os.path.join(ROOT, "runs", "oracle", "tep_alns_%s_n%d.json" % (a.tag, a.size)), "w", encoding="utf-8"), indent=1, default=str)
    imp = [r for r in out if r.get("result") == "IMPROVED"]
    print("\n  %d cell(s): %d improved, %d flipped below K, wall hit on %d" % (len(out), len(imp), sum(1 for r in imp if r.get("flipped_below_k")), sum(1 for r in out if r.get("wall_hit"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
