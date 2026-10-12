"""
S2f close-out — what did the n50 timing probe actually cost, and did it plateau?

Applies validation/PREREG_S2f_n50_timing_probe.md. This is a COST probe on n=2 runs. It can
report feasibility, timing and plateau shape, and nothing else. It carries no comparison to K,
because K publish only a POOLED average at |C|=50 (Table 4) and never per-instance values.

The registered expectation: last-improvement/wall was 0.36 at n20 and 0.77 at n30, so n50 should
still be improving at the 900s cap (ratio near 1.0). If it plateaus early the size trend reverses
and the "size-scale the budget" position in ROADMAP_to_frozen_variant.md weakens.

    python analysis/s2f_close.py
"""
import os, sys, csv, json, glob, re, statistics as st
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "validation", "s2f_n50_probe.csv")
IMP = re.compile(r"\+improve obj=([0-9.]+) mode=(\w+) verify=(\w+).*?t=([0-9.]+)s")
FIN = re.compile(r"final best \(verified\)\s*=\s*([0-9.]+)\s+wall=([0-9.]+)s")


def main():
    if not os.path.exists(CSV):
        print("no validation/s2f_n50_probe.csv -- S2f has not run. NOT a pass.")
        return 1
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    print("=" * 78)
    print("S2f CLOSE-OUT — n50 primal timing probe   (COST probe, n=2; not a measurement)")
    print("=" * 78)

    out = []
    for r in rows:
        sp = os.path.join(ROOT, (r.get("stdout_path") or "").replace("\\", os.sep))
        txt = open(sp, encoding="utf-8", errors="replace").read() if os.path.exists(sp) else ""
        ev = [(float(t), float(o), m) for o, m, v, t in IMP.findall(txt) if v == "OK"]
        fm = FIN.search(txt)
        wall = float(fm.group(2)) if fm else None
        first = min((t for t, _, _ in ev), default=None)
        tlast = max((t for t, _, _ in ev), default=None)
        out.append({"cell": r["cell"], "best": (r.get("best_obj") or "").strip(),
                    "exit": r.get("exit_code"), "wall": wall, "n_imp": len(ev),
                    "t_first": first, "t_last": tlast,
                    "ratio": (tlast / wall) if (wall and tlast is not None) else None})

    print(f"{'cell':8}{'exit':>6}{'best':>12}{'wall':>8}{'#impr':>7}{'t_first':>9}{'t_last':>9}{'last/wall':>11}")
    for o in out:
        f = lambda x, w, p=1: (f"{x:>{w}.{p}f}" if isinstance(x, float) else f"{str(x):>{w}}")
        print(f"{o['cell']:8}{str(o['exit']):>6}{o['best'] or '--':>12}"
              f"{f(o['wall'],8)}{o['n_imp']:>7}{f(o['t_first'],9)}{f(o['t_last'],9)}{f(o['ratio'],11,2)}")

    ok = [o for o in out if o["best"]]
    print(f"\ncompleted with an incumbent: {len(ok)}/{len(out)}")
    if not ok:
        print("NO run produced an incumbent at n50. That is the finding: the primal leg does not")
        print("reach a feasible solution at this size within 900s. Report it as a scope limit.")
        return 0

    ratios = [o["ratio"] for o in ok if o["ratio"] is not None]
    if ratios:
        m = st.mean(ratios)
        print(f"last-improvement / wall: {[round(r,2) for r in ratios]}  mean {m:.2f}")
        print("\nAgainst the measured trend (n20 0.36, n30 0.77) and the registered expectation:")
        if m >= 0.85:
            print(f"  CONFIRMED at {m:.2f}: runs are still improving at the cap. A fixed 400s budget")
            print("  is unusable at n50, and the frozen variant MUST size-scale its budget.")
            print("  The probe answers 'at least 900s', NOT 'how much' -- that needs a longer run.")
        elif m <= 0.6:
            print(f"  REVERSED at {m:.2f}: n50 plateaus EARLIER than n30. The monotone size trend")
            print("  does not hold, and the 'size-scale the budget' position weakens. Two runs")
            print("  cannot settle this; treat it as a flag to re-measure, not as a refutation.")
        else:
            print(f"  INTERMEDIATE at {m:.2f}: consistent with the trend but not decisive on n=2.")
    print("\nNO comparison to K is made or possible: K publish only a pooled average at |C|=50.")
    json.dump(stamped(out, __file__), open(os.path.join(ROOT, "runs", "s2f_final.json"), "w"), indent=1)
    print("-> runs/s2f_final.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
