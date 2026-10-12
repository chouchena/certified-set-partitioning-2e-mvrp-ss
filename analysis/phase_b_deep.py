"""
phase_b_deep.py -- Phase B analysis: indep vs xfeed, escape lottery, RT.

Reads results/portfolio/trace/*pB_{indep,xfeed}_s*.jsonl (4 tough cells x 2
arms x 2 seeds).  Produces:
  * per (cell, arm, seed): final, winner island, escaped?, time-to-best,
    time-to-beat-K, kick ok/fail, migrate_in count
  * per (cell, arm): best-of-2, mean, std
  * cross-feeding verdict (xfeed vs indep, per seed and aggregate)
  * escape-rate summary (the multi-kick target)
"""
from __future__ import annotations
import json, glob, statistics as st
from collections import defaultdict

K_INC   = {"RC203": 754.3, "R207": 601.7, "C204": 668.1, "RC208": 858.7}
K_INC_T = {"RC203": 2947, "R207": 2747, "C204": 380, "RC208": 1478}
# "escaped" threshold: below this = the good basin
ESCAPE  = {"RC203": 760.0, "R207": 595.0, "C204": 670.0, "RC208": 750.0}


def load_run(cell, arm, seed):
    fs = glob.glob(f"results/portfolio/trace/{cell}_n20_s{seed}__pB_{arm}_s{seed}__*.jsonl")
    if not fs:
        return None
    islands = {}
    for f in fs:
        isl = "kick" if "kick" in f else "seg"
        evs = [json.loads(l) for l in open(f) if l.strip()]
        islands[isl] = evs
    # portfolio best = min final over islands
    finals = {}
    for isl, evs in islands.items():
        imps = [(e["wall_s"], e["incumbent"]) for e in evs if e.get("incumbent") is not None]
        finals[isl] = (imps[-1][1], imps[-1][0]) if imps else (None, None)
    finals = {k: v for k, v in finals.items() if v[0] is not None}
    if not finals:
        return None
    winner = min(finals, key=lambda k: finals[k][0])
    best = finals[winner][0]
    ki = K_INC[cell]
    # time to first reach within 0.1% of portfolio best; time to first beat K
    t_best = t_beatK = None
    for isl, evs in islands.items():
        for e in evs:
            v = e.get("incumbent")
            if v is None:
                continue
            if v <= best * 1.001 and (t_best is None or e["wall_s"] < t_best):
                t_best = e["wall_s"]
            if v < ki and (t_beatK is None or e["wall_s"] < t_beatK):
                t_beatK = e["wall_s"]
    # kick stats on the winning island
    wev = islands[winner]
    ko = sum(1 for e in wev if e.get("trigger") == "fixopt:kick")
    kf = sum(1 for e in wev if e.get("trigger") == "fixopt_kick")
    mi = sum(1 for e in wev if e.get("trigger") == "migrate_in")
    return dict(cell=cell, arm=arm, seed=seed, best=round(best, 3), winner=winner,
                escaped=best <= ESCAPE[cell], t_best=round(t_best) if t_best else None,
                t_beatK=round(t_beatK) if t_beatK else None,
                kick_ok=ko, kick_fail=kf, migrate_in=mi)


def main():
    cells = ["RC203", "R207", "C204", "RC208"]
    runs = []
    for c in cells:
        for arm in ("indep", "xfeed"):
            for s in (0, 1):
                r = load_run(c, arm, s)
                if r:
                    runs.append(r)

    print("=== Phase B — per run ===")
    print(f"{'cell':6} {'arm':6} s {'best':9} {'win':5} esc {'t_best':7} {'t_beatK':8} "
          f"{'k_ok/fail':10} mig  vs_K")
    for r in runs:
        vk = (r["best"] - K_INC[r["cell"]]) / K_INC[r["cell"]] * 100
        print(f"{r['cell']:6} {r['arm']:6} {r['seed']} {r['best']:9.2f} {r['winner']:5} "
              f"{'Y' if r['escaped'] else 'n'}  {str(r['t_best'] or '-'):>7} "
              f"{str(r['t_beatK'] or 'never'):>8} {r['kick_ok']:>3}/{r['kick_fail']:<5} "
              f"{r['migrate_in']:>3}  {vk:+.1f}%")

    print("\n=== per (cell, arm): best-of-2 / mean / std vs K ===")
    by = defaultdict(list)
    for r in runs:
        by[(r["cell"], r["arm"])].append(r["best"])
    for c in cells:
        ki = K_INC[c]
        for arm in ("indep", "xfeed"):
            vs = by.get((c, arm), [])
            if not vs:
                continue
            bo, mn = min(vs), st.mean(vs)
            sd = st.pstdev(vs) if len(vs) > 1 else 0
            print(f"  {c:6} {arm:6}: bo2={bo:8.2f} ({(bo-ki)/ki*100:+.1f}%)  "
                  f"mean={mn:8.2f} ({(mn-ki)/ki*100:+.1f}%)  std={sd:5.1f}")

    print("\n=== cross-feeding: xfeed vs indep, per seed ===")
    idx = {(r["cell"], r["arm"], r["seed"]): r["best"] for r in runs}
    for c in cells:
        for s in (0, 1):
            i = idx.get((c, "indep", s)); x = idx.get((c, "xfeed", s))
            if i and x:
                d = (x - i) / i * 100
                print(f"  {c:6} s{s}: indep={i:8.2f}  xfeed={x:8.2f}  ({d:+.2f}%)")

    print("\n=== escape rate (indep, the multi-kick target) ===")
    for c in cells:
        es = [r["escaped"] for r in runs if r["cell"] == c and r["arm"] == "indep"]
        print(f"  {c:6}: {sum(es)}/{len(es)} escaped")


if __name__ == "__main__":
    main()
