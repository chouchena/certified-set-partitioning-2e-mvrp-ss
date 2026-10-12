"""
easy_reduction_descend.py -- descend protocol for the easy-reduction bound.

Rationale (validated 2026-09-02, 4 cells): among PROVEN k the block-relax bound
is strictly monotone DECREASING in k (z_A(H_k)* increases as fewer customers
are dropped; w constant; nested greedy prefixes).  So:

    argmax_k [ block_relax(k) : proven within budget ]  ==  smallest provable k.

No interior optimum -> no need to sweep low k (they only ever cap unproven and
are discarded).  Start at a k that proves in seconds, walk DOWN by 1 while it
keeps proving, stop at the first k that fails (one-step lookahead tolerance for
a non-monotone provability island).  Same per-k budget as the ascending sweep
-> identical frontier and identical reported bound, ~7 min/cell faster.

If k_hi itself does not prove (reach_frac ~ 1 cells), escalate UP until something
proves, then descend from there -- more robust than the ascending sweep, which
caps at max_drop and can return NO proven bound for the hardest cells.

!! 2026-09-10 REPAIR -- k_cap MUST EXCEED k_hi.
k_cap defaulted to 14 while the n30 batch passed k_hi=15, so `while not proven and k < k_cap`
was FALSE on entry and the escalate-up safety net above never ran even once. Ten n30 cells
(C204, R203, R204, R207, R208, R210, R211, RC204, RC207, RC208) returned a single unproven
record and were reported as if the method had been given its full protocol. It had not.
k_cap is now DERIVED from k_hi (k_hi + K_CAP_HEADROOM) instead of being an independent
default that can silently contradict it, and a contradiction is a fatal assertion at launch
rather than a silent no-op. Size-relative quantities use `size`, never a literal 20.
"""
from __future__ import annotations
import argparse, json, math, sys, time
sys.path.insert(0, ".")
import time as _time
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
from crossfeed.bound_tracer import BoundTracer
import hashlib, os, platform, subprocess


K_CAP_HEADROOM = 5          # escalation steps allowed above k_hi before giving up


def _provenance(**kw):
    """Stamped into EVERY record. An artifact that cannot say which code and which settings
    produced it cannot be compared against another artifact, and this project has already
    lost one campaign to an unnoticed code_hash change mid-run."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    h = hashlib.sha256()
    for rel in ("crossfeed/block_a.py", "crossfeed/easy_reduction.py",
                "crossfeed/blockA_cpsat.py", "crossfeed/easy_reduction_descend.py",
                "build_instance.py"):
        fp = os.path.join(root, rel)
        if os.path.exists(fp):
            h.update(open(fp, "rb").read())
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                    capture_output=True, text=True, timeout=10).stdout.strip())
    except Exception:
        sha, dirty = None, None
    try:
        import docplex.mp
        dpx = docplex.mp.__version__
    except Exception:
        dpx = None
    try:
        import cplex as _cx
        cpx = _cx.__version__
    except Exception:
        cpx = None
    d = dict(code_hash=h.hexdigest()[:8], git_sha=sha, git_dirty=dirty,
             host=platform.node(), ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
             python=platform.python_version(), platform=platform.platform(),
             docplex=dpx, cplex=cpx,
             pythonhashseed=os.environ.get("PYTHONHASHSEED"),
             cplex_parallel="deterministic(1)")
    d.update(kw)
    return d


def _bound_ws(name, size, drop, tl, workers, prev_x=None, readd=None, proximity=0.0,
              tracer=None, seed=20260910, det_tl=None):
    """block-A(H) via CPLEX big-M, optionally warm-started from the previous
    (higher-k) routing with `readd` cheapest-inserted.  Returns the routing
    solution so the next (lower-k) solve can chain off it.  A MIP start only
    seeds the incumbent -> the proven z_A(H)* is identical, it just proves
    sooner."""
    # proximity is a PARAMETER, not a constant: K's Table 6 (n=100) is proximity 0.1
    # while Tables 3/4 (n<=50) are 0. Comparing an n100 bound computed at 0.0 against
    # Table 6 would be comparing different problems.
    p = build(name, size, wls=0.1, tau="formula", proximity=proximity, time_limit=tl)
    D = p.DistMatrix
    ba = BlockA(p, integral=True, timing_mode="bigM", drop=drop)
    # REPLICABILITY (user requirement 2026-09-10). A truncated dual bound is REPORTED as our
    # LB (proof Step 0), and a truncated bound is whatever the search happened to reach -- so
    # it depends on the seed and on parallel race outcomes in a way a PROVEN optimum does not.
    # Three settings make it reproducible:
    #   threads     fixed -- deterministic parallel MIP reproduces only at the same thread count
    #   parallel=1  CPLEX deterministic parallel mode (default "auto" may pick opportunistic)
    #   randomseed  fixed -- otherwise CPLEX varies its own RNG per run
    # The remaining non-determinism is that `timelimit` is WALL-CLOCK, so a loaded machine stops
    # at a different point. That is why det_ticks is recorded below: a replicator can set
    # dettimelimit to the logged tick count and reproduce the number exactly on any machine.
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    try:
        ba.m.parameters.parallel = 1               # 1 = deterministic
    except Exception as _ex:
        print(f"  [parallel mode not set: {_ex}]", flush=True)
    try:
        ba.m.parameters.randomseed = int(seed)
    except Exception as _ex:
        print(f"  [randomseed not set: {_ex}]", flush=True)
    # DETERMINISTIC TIME LIMIT -- the actual fix for replicability, measured 2026-09-10.
    # Pinning the seed alone was NOT enough: two identical R203/n30 runs at a 40 s WALL limit
    # returned 551.81 and 544.23 at k=16, because a wall limit stops the search after a
    # different amount of deterministic WORK each time (det_ticks 39440 vs 37020). Ticks are
    # machine- and load-independent, so limiting on them makes the truncated bound -- which we
    # publish as a valid LB under proof Step 0 -- reproducible on any hardware.
    # `timelimit` stays as a generous BACKSTOP only; if it ever binds, the record says so and
    # that record is not tick-reproducible.
    if det_tl:
        try:
            ba.m.parameters.dettimelimit = float(det_tl)
        except Exception as _ex:
            print(f"  [dettimelimit not set: {_ex}]", flush=True)
    ws_x = None
    if prev_x and readd is not None:
        ws_x = dict(prev_x)
        for c in ([readd] if isinstance(readd, int) else list(readd)):
            used = [(i, j) for (i, j), v in ws_x.items() if v == 1]
            best, bd = None, 1e18
            for (i, j) in used:
                delta = D[i][c] + D[c][j] - D[i][j]
                if delta < bd:
                    bd, best = delta, (i, j)
            if best is None:
                ws_x[(0, c)] = 1
                ws_x[(c, 0)] = 1
            else:
                i, j = best
                ws_x[(i, j)] = 0
                ws_x[(i, c)] = 1
                ws_x[(c, j)] = 1
    # PURE-OBSERVER trace. track_progress stays False on purpose: passing True would install
    # a StallStopper, which ABORTS on plateau and would change `proven` -- see bound_tracer.py.
    if tracer is not None:
        try:
            ba.m.add_progress_listener(tracer)
        except Exception as _ex:
            print(f"  [bound trace unavailable: {_ex}]", flush=True)
    t0 = _time.time()
    r = ba.solve(time_limit=tl, track_progress=False, mip_start_x=ws_x)
    demH = sum(p.nodes[cc].demand for cc in p.customers if cc not in set(drop or []))
    try:
        det = ba.m.solve_details.deterministic_time
    except Exception:
        det = None
    wall_used = _time.time() - t0
    limit_hit = ("proved" if r.get("proven")
                 else "det" if (det_tl and det is not None and det >= 0.995 * float(det_tl))
                 else "wall" if wall_used >= 0.98 * tl
                 else "other")
    return {"lb": r["value"], "inc": r.get("incumbent"), "proven": bool(r.get("proven")),
            "det_ticks": round(det, 2) if det is not None else None,
            "det_tl": det_tl, "limit_hit": limit_hit,
            "status": r.get("status", ""), "wall": round(_time.time() - t0, 1),
            "carLB_H": math.ceil(demH / p.CarCapacity),
            "nH": len(p.customers) - len(set(drop or [])),
            "xij_sol": r.get("xij_sol")}


def descend(name, size, *, k_hi=9, k_cap=None, tl=450, workers=8, bounder="cplex",
            proximity=0.0, cell_budget=5400.0, out=None, allow_overwrite=False,
            seed=20260910, det_tl=None, selection="easiness", no_warm=False):
    # DERIVED, not an independent default that can silently contradict k_hi (see header).
    if k_cap is None:
        k_cap = k_hi + K_CAP_HEADROOM
    k_cap = min(k_cap, size - 4)          # keep |H| >= 4 so the sub-instance stays meaningful
    # EVERY coupled pair gets an explicit invariant. The k_cap/k_hi defect was not a typo, it
    # was an UNASSERTED RELATIONSHIP between two independently-defaulted parameters. Any other
    # such pair can fail the same silent way, so they are all checked here.
    if cell_budget is not None and tl > cell_budget:
        raise SystemExit(f"FATAL {name}/n{size}: wall backstop tl={tl}s exceeds the whole cell "
                         f"budget {cell_budget}s -- a single solve could consume the cell and "
                         f"the descend would report one record, the damaged-cell signature.")
    if det_tl and tl and det_tl / 1000.0 > tl:
        print(f"  [warn {name}: det_tl={det_tl:.0f}tk needs ~{det_tl/1000:.0f}s at ~1000 tk/s "
              f"but the wall backstop is {tl}s, so WALL will bind and the bound will not be "
              f"tick-reproducible; limit_hit will say 'wall']", flush=True)
    if not k_cap > k_hi:
        raise SystemExit(
            f"FATAL {name}/n{size}: k_cap={k_cap} must exceed k_hi={k_hi}, otherwise the "
            f"escalate-up safety net is dead code and a non-proving k_hi silently returns a "
            f"single unproven record. This exact contradiction damaged 10 n30 cells.")
    p = build(name, size, wls=0.1, tau="formula", proximity=proximity, time_limit=tl)
    s, w, ctx = scarcity_and_weights(p)
    order = sorted(easiness(ctx, w), key=lambda c: -easiness(ctx, w)[c])
    # ABLATION (2026-09-14). The retained-set policy is the claimed methodological
    # contribution, so it must be falsifiable: `random` is the neutral baseline and
    # `reverse` is adversarial (drop the HARDEST first). Both are deterministic given
    # `seed`, so every arm stays tick-reproducible. `easiness` is the shipped policy
    # and reproduces the banked artifacts bit-for-bit.
    if selection == "random":
        import random as _r
        _rng = _r.Random(seed)
        order = list(order)
        _rng.shuffle(order)
    elif selection == "reverse":
        order = list(order)[::-1]
    elif selection != "easiness":
        raise SystemExit(f"FATAL: unknown --selection {selection!r} "
                         f"(expected easiness|random|reverse)")
    wlb = water_lb_scaled(p)[0] / SCALE
    out = out or f"crossfeed/easy_reduction_descend_{name}_n{size}.json"
    # OVERWRITE GUARD. The artifact name is a pure function of (cell, size), so a throwaway
    # smoke run at a short tl silently REPLACES a banked campaign result -- which is exactly
    # what happened on 2026-09-10: a tl=60 smoke on C204/n20 cut its banked 6-record 512.08
    # artifact down to 3 records / 482.38, recovered only because it was in git. Being more
    # careful is not a fix; refusing by default is.
    if os.path.exists(out) and not allow_overwrite:
        raise SystemExit(
            f"REFUSING to overwrite existing artifact {out}\n"
            f"  A descend artifact is named only by (cell, size), so this run would "
            f"destroy whatever protocol produced the file already there.\n"
            f"  If you MEANT to replace it: pass --allow-overwrite (snapshot first).\n"
            f"  If this is a smoke/scratch run: pass --out <scratch path>.")

    print(f"\n=== {name}/{size}  DESCEND  bounder={bounder} tl={tl} ===", flush=True)
    print(f"scarcity: " + "  ".join(f"{k}={v:.3f}" for k, v in s.items()), flush=True)
    print(f"drop order [{selection}] (dropped first -> last): {order}", flush=True)
    print(f"water LB (full demand) = {wlb:.2f}", flush=True)

    rows, proven = [], {}
    _last_x = {"k": None, "x": None}   # routing of the most recent solve
    prov = _provenance(name=name, size=size, tl=tl, k_hi=k_hi, k_cap=k_cap, threads=workers,
                       proximity=proximity, bounder=bounder, cell_budget=cell_budget,
                       water_lb=round(wlb, 4), seed=seed, det_tl=det_tl,
                       selection=selection, no_warm=no_warm)
    _cum = {"wall": 0.0}               # cell-global seconds, for the anytime curve and budget

    def solve_k(k, warm=False):
        drop = set(order[:k])
        prev_x = _last_x["x"] if (warm and _last_x["x"]) else None
        readd = order[k] if prev_x is not None else None   # H_k = H_{k+1} + order[k]
        tracer = BoundTracer(offset=_cum["wall"])
        t0 = time.time()
        r = _bound_ws(name, size, drop, tl, workers, prev_x=prev_x, readd=readd,
                      proximity=proximity, tracer=tracer, seed=seed, det_tl=det_tl)
        br = (r["lb"] + wlb) if r["lb"] is not None else None
        rec = {"k": k, "nH": r["nH"], "carLB_H": r["carLB_H"], "status": r["status"],
               "zA_lb": r["lb"], "block_relax": round(br, 2) if br is not None else None,
               "proven": bool(r["proven"]), "wall": r["wall"], "warm": bool(prev_x),
               "t_start": round(_cum["wall"], 2), "det_ticks": r.get("det_ticks"),
               "det_tl": r.get("det_tl"), "limit_hit": r.get("limit_hit"),
               "lb_curve": tracer.curve(wlb), "n_improve": tracer.n_improvements(),
               "drop": sorted(drop)}
        rec.update(prov)
        _cum["wall"] += r["wall"]
        rows.append(rec)
        json.dump(rows, open(out, "w"), indent=2, default=str)
        if r.get("xij_sol"):
            _last_x["k"], _last_x["x"] = k, r["xij_sol"]
        print(f"  descend k={k:>2} |H|={r['nH']:>3} {str(r['status'])[:20]:>20} "
              f"br={str(rec['block_relax']):>9} proven={str(r['proven']):>5} "
              f"warm={'Y' if prev_x else '-'} {r['wall']:>7.1f}s "
              f"[{rec['limit_hit']} {rec['det_ticks']}tk]", flush=True)
        return rec

    # 1. locate a starting proven k (escalate UP, no warm start)
    k = k_hi
    rec = solve_k(k)
    while not rec["proven"] and k < k_cap and _cum["wall"] < cell_budget:
        k += 1
        rec = solve_k(k)
    if not rec["proven"]:
        why = ("cell_budget" if _cum["wall"] >= cell_budget else f"k_cap={k_cap}")
        # REPORT MEASURED STATE, NEVER RECOMPUTED INTENT. The original message printed
        # "NO proven bound up to k={k_cap} (|H|={20 - k_cap})" -- it named a k the loop had
        # NEVER TRIED (k_cap=14 < k_hi=15, so the loop body never ran) and an |H| from a
        # hardcoded size. At n30 it printed "k=14 (|H|=6)" when the truth was k=15, |H|=15,
        # zero escalations. That reads as a plausible DOMAIN result -- "we dropped to 6
        # customers and still could not prove it" -- so it disguised a control-flow bug as a
        # hard instance, and three separate readers went past it. k and nH are now read back
        # from the record that was actually solved.
        ks = [x["k"] for x in rows]
        print(f"{name}: NO proven bound. tried k={min(ks)}..{max(ks)} "
              f"({len(rows)} solve(s), |H|={rows[-1]['nH']} at the last one); stopped on {why}. "
              f"best un-proven block_relax={max((x['block_relax'] or 0) for x in rows):.2f} "
              f"(STILL A VALID LB -- proof Step 0)", flush=True)
        if len(rows) == 1:
            print(f"{name}: !! ONLY ONE SOLVE RAN. The escalate-up path did not execute. "
                  f"Check k_cap({k_cap}) > k_hi({k_hi}) and the cell budget.", flush=True)
        return rows
    proven[k] = rec["block_relax"]

    # 2. descend, warm-started from k+1, tolerating one isolated non-proving k
    skipped = False
    while k > 0:
        if _cum["wall"] >= cell_budget:
            print(f"{name}: cell budget {cell_budget:.0f}s reached at k={k}; stopping descend "
                  f"(every record already written is a valid LB).", flush=True)
            break
        k -= 1
        rec = solve_k(k, warm=not no_warm)
        if rec["proven"]:
            proven[k] = rec["block_relax"]
            skipped = False
        elif skipped:
            break
        else:
            skipped = True

    kf = min(proven)
    print(f"{name}: FRONTIER k={kf}  block_relax={proven[kf]}  PROVEN  "
          f"(|H|={size - kf}, drop={[x['drop'] for x in rows if x['k'] == kf][0]})", flush=True)
    print(f"{name}: proven curve " +
          "  ".join(f"k{k}={proven[k]}" for k in sorted(proven)), flush=True)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="R207")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--k-hi", type=int, default=9)
    ap.add_argument("--k-cap", type=int, default=None,
                    help="max escalation k; DEFAULT k_hi+%d. Must exceed --k-hi." % K_CAP_HEADROOM)
    ap.add_argument("--cell-budget", type=float, default=5400.0,
                    help="cell-global wall ceiling (s); stops cleanly, keeps all records")
    ap.add_argument("--out", default=None, help="override artifact path (use for smoke runs)")
    ap.add_argument("--det-tl", type=float, default=None,
                    help="CPLEX dettimelimit in TICKS -- the replicable budget. --tl becomes a "
                         "generous wall backstop. ~1000 ticks/s at 4 threads on this host.")
    ap.add_argument("--seed", type=int, default=20260910,
                    help="CPLEX randomseed; stamped into every record for replication")
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="permit replacing an existing artifact; snapshot it first")
    ap.add_argument("--tl", type=int, default=450)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--bounder", default="cplex")
    ap.add_argument("--selection", default="easiness",
                    choices=["easiness", "random", "reverse"],
                    help="retained-set policy. ABLATION ARM -- recorded in provenance.")
    ap.add_argument("--no-warm", action="store_true",
                    help="ablate the warm descent: solve each k cold. ABLATION ARM.")
    ap.add_argument("--proximity", type=float, default=0.0,
                    help="0.0 for K Tables 3/4 (n<=50); 0.1 for Table 6 (n=100)")
    a = ap.parse_args()
    for nm in a.cells.split(","):
        t0 = time.time()
        descend(nm.strip(), a.size, k_hi=a.k_hi, k_cap=a.k_cap, tl=a.tl,
                workers=a.workers, bounder=a.bounder, proximity=a.proximity,
                cell_budget=a.cell_budget, out=a.out,
                allow_overwrite=a.allow_overwrite, seed=a.seed, det_tl=a.det_tl,
                selection=a.selection, no_warm=a.no_warm)
        print(f"{nm.strip()}: cell wall {time.time() - t0:.0f}s\n", flush=True)
