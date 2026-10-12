"""
phase_a_deep.py -- the Phase A decision analysis.

Reads every results/portfolio/trace/*bA_s*.jsonl (4 cells x 2 seeds x 3 islands)
and produces the evidence for:
  1. keep/drop merge  (does it ever sole-win? is route_merge unique+load-bearing?)
  2. the 2/1/1 thread assignment  (per-island sub-MILP solve time + does more
     iterations -> better final?)
  3. stall tuning  (inter-improvement gap distribution; kick success rate + gap
     between successful kicks)
  4. Phase B budget  (which islands still improving at the cap, at what rate;
     4-thread slowdown factor from 3t/2t solve times)

  python -m analysis.phase_a_deep
"""
from __future__ import annotations
import json, glob, statistics as st
from collections import Counter, defaultdict

CFG_THREADS = {"merge": 3, "seg": 2, "kick": 3}


def load(f):
    return [json.loads(l) for l in open(f) if l.strip()]


def solve_gaps(evs):
    """wall-time between consecutive rotation/kick solve events == sub-MILP times."""
    ts = [e["wall_s"] for e in evs
          if e.get("trigger") and (e["trigger"].startswith("fixopt:")
                                   or e["trigger"].startswith("fixopt_noimprove:")
                                   or e["trigger"].startswith("fixopt_cur_improve:")
                                   or e["trigger"] in ("fixopt_kick",))]
    return [b - a for a, b in zip(ts, ts[1:]) if 0 < b - a < 600]


def main():
    runs = defaultdict(dict)   # (cell,seed) -> island -> evs
    for f in sorted(glob.glob("results/portfolio/trace/*bA_s*.jsonl")):
        base = f.split("trace/")[-1].replace(".jsonl", "")
        # C204_n20_s1__bA_s1__kick
        parts = base.split("__")
        cell = parts[0].split("_")[0]
        seed = parts[0].split("_s")[-1]
        isl = parts[-1]
        runs[(cell, seed)][isl] = load(f)

    print(f"=== Phase A deep analysis  ({len(runs)} runs) ===\n")

    # ---- 1. winners + sole-win test ----
    print("--- winners (island producing the run's best incumbent) ---")
    sole_win = Counter()
    for (cell, seed), isls in sorted(runs.items()):
        finals = {i: (min((e["best_incumbent"] for e in ev if e.get("best_incumbent")), default=None))
                  for i, ev in isls.items()}
        finals = {i: v for i, v in finals.items() if v is not None}
        if not finals:
            continue
        best = min(finals.values())
        winners = [i for i, v in finals.items() if abs(v - best) < 0.05]
        tag = "SOLE" if len(winners) == 1 else "tie"
        if len(winners) == 1:
            sole_win[winners[0]] += 1
        print(f"  {cell} s{seed}: best={best:8.2f}  {'/'.join(f'{i}={v:.1f}' for i,v in sorted(finals.items()))}"
              f"   -> {tag} {winners}")
    print(f"  sole-wins: {dict(sole_win)}\n")

    # ---- 2. per-island: iters, solve times, still-improving, route_merge ----
    print("--- per-island profile (pooled over runs) ---")
    agg = defaultdict(lambda: dict(iters=[], solve_med=[], solve_p90=[], last_gain=[],
                                   final=[], ran=[], rm_gains=[], rm_solves=[],
                                   kick_ok=0, kick_fail=0, kick_ok_gaps=[]))
    for (cell, seed), isls in runs.items():
        for i, ev in isls.items():
            if not ev:
                continue
            a = agg[i]
            a["ran"].append(ev[-1]["wall_s"])
            a["iters"].append(max((e.get("extra", {}) or {}).get("iter", 0) for e in ev))
            g = solve_gaps(ev)
            if g:
                a["solve_med"].append(st.median(g))
                a["solve_p90"].append(sorted(g)[int(len(g) * 0.9)])
            imps = [(e["wall_s"], e["incumbent"]) for e in ev if e.get("incumbent") is not None]
            if imps:
                a["last_gain"].append(imps[-1][0])
                a["final"].append(imps[-1][1])
            # route_merge
            rm = [e for e in ev if e.get("trigger") == "fixopt:route_merge"]
            a["rm_gains"].append(len(rm))
            # kicks
            ko = [e["wall_s"] for e in ev if e.get("trigger") == "fixopt:kick"]
            kf = [e for e in ev if e.get("trigger") == "fixopt_kick"]
            a["kick_ok"] += len(ko)
            a["kick_fail"] += len(kf)
            a["kick_ok_gaps"] += [b - x for x, b in zip(ko, ko[1:])]

    for i in ("merge", "seg", "kick"):
        a = agg[i]
        def m(x): return round(st.mean(x), 1) if x else None
        print(f"  {i:6} (cfg {CFG_THREADS[i]}t):  iters~{m(a['iters'])}  "
              f"solve_med~{m(a['solve_med'])}s p90~{m(a['solve_p90'])}s  "
              f"last_gain~{m(a['last_gain'])}s of ran~{m(a['ran'])}s  "
              f"route_merge_gains~{m(a['rm_gains'])}  "
              f"kicks {a['kick_ok']}ok/{a['kick_fail']}fail "
              f"(gap between ok kicks ~{m(a['kick_ok_gaps'])}s)")

    # ---- 3. still-improving-at-cap: gain in last 400s ----
    print("\n--- still improving near the 1500s cap? (gain in final 400s) ---")
    for (cell, seed), isls in sorted(runs.items()):
        for i, ev in isls.items():
            imps = [(e["wall_s"], e["best_incumbent"]) for e in ev if e.get("best_incumbent")]
            if not imps:
                continue
            tN = imps[-1][0]
            at = next((o for (t, o) in imps if t >= tN - 400), imps[-1][1])
            late = at - imps[-1][1]
            if late > 1.0:
                print(f"  {cell} s{seed} {i:6}: +{late:.1f} in last 400s (ended {imps[-1][1]:.1f} @ {tN:.0f}s)")

    # ---- 4. inter-improvement gap distribution (for stall patience) ----
    print("\n--- inter-improvement gaps (informs stall patience) ---")
    for i in ("merge", "seg", "kick"):
        gaps = []
        for (cell, seed), isls in runs.items():
            ev = isls.get(i, [])
            imps = [e["wall_s"] for e in ev if e.get("incumbent") is not None]
            gaps += [b - a for a, b in zip(imps, imps[1:])]
        if gaps:
            gaps.sort()
            print(f"  {i:6}: median gap {st.median(gaps):.0f}s  p75 {gaps[int(len(gaps)*.75)]:.0f}s  "
                  f"p90 {gaps[int(len(gaps)*.9)]:.0f}s  max {gaps[-1]:.0f}s")


if __name__ == "__main__":
    main()
