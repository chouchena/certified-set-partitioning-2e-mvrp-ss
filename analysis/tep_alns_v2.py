"""v2 ALNS: grow-k-on-stall (kick ladder) + helpless early-abort (Rule B), in a NEW module so the
frozen v1 tep_alns.alns stays BYTE-UNTOUCHED (d647/d662/d670). All operators/scoring are the frozen
v1 helpers, imported unchanged.

alns_growk is a FAITHFUL MIRROR of tep_alns.alns with exactly two gated additions:
  * GROW-K (grow_max>0): the destroy size k escalates with the stall counter `since` -- rung =
    min(since//grow_step + 1, grow_max), k drawn from (2+3*rung, +1, +2), capped at |C|-1 and reset
    to the {2,3,4} base on improvement (since=0). The kick-ladder that targets the fleet-basin cells
    (d670: R201/R202/R203/RC201). ONE rng.choice per iter either way, so the RNG stream for every
    other decision is preserved.
  * HELPLESS EARLY-ABORT (helpless_probe>0): if after `helpless_probe` iterations NO feasible
    neighbour was ever produced (distinct==0), stop -- the C205-degenerate case (d649) where ALNS
    burns its budget finding nothing. Rule B: do not keep running a helpless stage.

BIT-EXACT CONTRACT: alns_growk(grow_max=0, helpless_probe=0) == tep_alns.alns on the same inputs/seed
(the k draw is identical rng.choice((2,3,4)); no abort). This is the validation anchor.
"""
import math
import random
import time

from tep_alns import DESTROY, REPAIR, destroy, remove, repair, complete_hubs
from tep_refine import score


def alns_growk(inst, chains, hub, incumbent_val, iters, stall, wall, seed, sats, surrogate=False,
               grow_max=0, grow_step=150, helpless_probe=0):
    rng = random.Random(seed)
    cache = {}
    cur = score(inst, chains, hub, cache, exact=not surrogate)
    cur_val = cur[0] if cur else float("inf")
    best_val, best = float(incumbent_val), None
    best_sur = cur_val; exact_calls = 0
    best_ops = []
    cur_chains, cur_hub = chains, hub
    w = {(d, r): 1.0 for d in DESTROY for r in REPAIR}
    sc = {k: 0.0 for k in w}; used = {k: 0 for k in w}
    T0 = 0.005 * incumbent_val; alpha = (0.01) ** (1.0 / max(1, iters))
    T = T0
    it = since = accepted = improved = infeasible = identical = distinct = 0
    ncust = sum(len(tr) for ch in chains for tr in ch)             # |C| served -- the grow-k cap
    kmax = max(2, ncust - 1)                                       # destroy needs len(cust) > k
    maxrung = 0                                                    # audit: deepest kick rung reached
    t0 = time.time()
    while it < iters and since < stall and time.time() - t0 < wall:
        it += 1
        if helpless_probe and it >= helpless_probe and distinct == 0:
            break                                                 # Rule B: no feasible neighbour -> helpless, abort
        keys = list(w); probs = [w[k] for k in keys]
        dk, rk = rng.choices(keys, weights=probs, k=1)[0]
        if grow_max > 0 and since > 0:                            # GROW-K: escalate the kick on stall
            rung = min(since // grow_step + 1, grow_max)
            maxrung = max(maxrung, rung)
            lo = 2 + 3 * rung
            k = min(rng.choice((lo, lo + 1, lo + 2)), kmax)
        else:
            k = rng.choice((2, 3, 4))                             # v1 base kick (bit-exact when grow_max=0)
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
            infeasible += 1; continue
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
            if val < best_sur - 1e-6:
                exact_calls += 1; rx = score(inst, N, H, cache, exact=True)
                best_sur = val
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
        if it % 50 == 0:
            for key in w:
                if used[key]:
                    w[key] = 0.8 * w[key] + 0.2 * (sc[key] / used[key])
                sc[key] = 0.0; used[key] = 0
    return best_val, best, dict(iters=it, accepted=accepted, improved=improved, infeasible=infeasible,
                                identical=identical, distinct_feasible=distinct,
                                stall_hit=since >= stall, wall_hit=time.time() - t0 >= wall,
                                surrogate=bool(surrogate), exact_calls=exact_calls, best_ops=best_ops,
                                grow_max=grow_max, max_rung=maxrung,
                                helpless_abort=(bool(helpless_probe) and distinct == 0 and it >= (helpless_probe or 1)),
                                secs=round(time.time() - t0, 1), weights={"%s+%s" % k: round(v, 3) for k, v in w.items()})


def alns_multistart(inst, starts, incumbent_val, iters, stall, restart_wall, total_wall, seed, sats,
                    surrogate=False, grow_max=5, grow_step=100, helpless_probe=0):
    """Internal multi-restart grow-k (d672 follow-up, for RC201-type cyclers): run grow-k from each
    DIVERSE warm start in `starts` (restart 0 = the inherited/ws incumbent; others = fresh greedy
    constructions with varied seeds), each capped at restart_wall, anchored on the running global
    best so every restart tries to beat it, within total_wall. ONE run, deterministic (seed+i) ->
    a legitimate restart algorithm, NOT external best-of-k (RULE_restart_accounting). Returns the
    global best over restarts + a trail of per-restart outcomes.
    """
    best_val, best = float(incumbent_val), None
    t0 = time.time()
    trail = []
    for i, (chains, hub) in enumerate(starts):
        remain = total_wall - (time.time() - t0)
        if remain <= 0:
            break
        anchor = best_val                                       # anchor each restart on the running best
        bv, bsol, st = alns_growk(inst, chains, hub, anchor, iters, stall, min(restart_wall, remain),
                                  seed + i, sats, surrogate=surrogate, grow_max=grow_max,
                                  grow_step=grow_step, helpless_probe=helpless_probe)
        improved = bsol is not None and bv < best_val - 1e-6
        if improved:
            best_val, best = bv, bsol
        trail.append(dict(restart=i, val=round(bv, 3), improved=improved,
                          max_rung=st.get("max_rung", 0), secs=st.get("secs")))
    return best_val, best, dict(restarts=len(trail), best=round(best_val, 3), trail=trail,
                                secs=round(time.time() - t0, 1))
