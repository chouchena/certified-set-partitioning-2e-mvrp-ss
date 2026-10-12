"""Which paper-relevant analyses cover n50, and which do not.

WHY. n50 was systematically skipped -- not for a data reason (K publish MORE n50 reference
data than n100: Table 4, Fig 4, Fig 5, versus Table 6 alone) but as an unexamined choice.
The cost was real: a complete 27-cell n50 analysis sat in runs/n50_final.json giving 1.4133x
K's derived dual bound while the register carried no n50 headline at all, and a STANDING claim
asserted the arithmetic bound beats our MILP "at n100 ONLY" when n50 has 8/27 crossovers.

This makes the coverage mechanical instead of remembered.
"""
import json, os, glob, csv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sizes_in(path, key="size"):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p))
    except Exception:
        return None
    it = d.values() if isinstance(d, dict) else d
    return sorted({r.get(key) for r in it if isinstance(r, dict) and r.get(key) is not None})


def descend_sizes():
    out = {}
    for s in (10, 20, 30, 40, 50, 100):
        n = len([f for f in glob.glob(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_*_n{s}.json"))
                 if not any(x in f for x in ("noprov", "kcapbug", "tl450", "detl"))])
        if n:
            out[s] = n
    return out


def primal_sizes():
    c = {}
    p = os.path.join(ROOT, "runs/summary.csv")
    if not os.path.exists(p):
        return c
    for r in csv.DictReader(open(p)):
        if r.get("engine") in ("fixopt", "joint_milp_cplex", "joint_milp_gurobi", "lbbd"):
            c[r.get("size")] = c.get(r.get("size"), 0) + 1
    return c


ROWS = [
    ("LB descend (headline bound)", lambda: descend_sizes()),
    ("AB4 grid", lambda: sizes_in("runs/ab4_grid_results.json")),
    ("AB WLS sweep", lambda: sizes_in("runs/ab_wls_sweep.json")),
    ("AB vs MILP", lambda: sizes_in("runs/ab_vs_milp.json")),
    ("n50 rollup (best2 vs K)", lambda: [50] if os.path.exists(os.path.join(ROOT, "runs/n50_final.json")) else []),
    ("primal (fixopt/exact)", lambda: primal_sizes()),
    ("fleet certificate", lambda: [20, 30]),
    ("S3a selection ablation", lambda: [20]),
]

if __name__ == "__main__":
    print("n50 COVERAGE MATRIX\n")
    print(f"{'analysis':32s} {'sizes covered':38s} n50?")
    gaps = []
    for name, fn in ROWS:
        try:
            s = fn()
        except Exception as e:
            s = f"ERROR {e}"
        if isinstance(s, dict):
            disp = ", ".join(f"n{k}({v})" for k, v in sorted(s.items(), key=lambda x: int(x[0])))
            has = 50 in s or "50" in s
        elif isinstance(s, list):
            disp = ", ".join(f"n{x}" for x in s) or "(none)"
            has = 50 in s
        else:
            disp, has = str(s), False
        if not has:
            gaps.append(name)
        print(f"{name:32s} {disp:38s} {'YES' if has else '**NO**'}")
    print(f"\n  analyses WITHOUT n50: {len(gaps)}")
    for g in gaps:
        print(f"    - {g}")
