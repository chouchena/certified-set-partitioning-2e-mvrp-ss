"""Win vs loss DEPTH on the complete 20-cell unproved arm.

P2 is a COUNT (5 beat, 10 lose). A count says nothing about magnitude: shallow
losses against deep wins would mean something very different from the reverse.

Reports depth in ABSOLUTE units and as a PERCENTAGE of K's value (cells differ
in scale, so absolute sums are dominated by the largest instances), with and
without the two known-bimodal outliers, plus the Wilcoxon signed-rank test that
PLAN_computational_analysis_leg names as the standard paired comparison
(Demsar 2006).

Sign convention throughout: NEGATIVE = we are better.
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def wilcoxon(diffs):
    """Two-sided Wilcoxon signed-rank on non-zero differences; normal approx."""
    d = [x for x in diffs if abs(x) > 1e-9]
    n = len(d)
    if n < 6:
        return None
    order = sorted(range(n), key=lambda i: abs(d[i]))
    rank = [0.0] * n
    i = 0
    while i < n:                                    # average tied ranks
        j = i
        while j + 1 < n and abs(abs(d[order[j + 1]]) - abs(d[order[i]])) < 1e-12:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            rank[order[k]] = avg
        i = j + 1
    wp = sum(rank[i] for i in range(n) if d[i] > 0)
    wm = sum(rank[i] for i in range(n) if d[i] < 0)
    w = min(wp, wm)
    mu = n * (n + 1) / 4.0
    sd = (n * (n + 1) * (2 * n + 1) / 24.0) ** 0.5
    z = (w - mu) / sd if sd > 0 else float("nan")
    return dict(n=n, w_plus=wp, w_minus=wm, w=w, z=z,
                sig05=abs(z) > 1.96)


def summarise(rows, label):
    wins = [r for r in rows if r["delta"] < -0.05]
    loss = [r for r in rows if r["delta"] > 0.05]
    tie = [r for r in rows if abs(r["delta"]) <= 0.05]
    aw = [-r["delta"] for r in wins]
    al = [r["delta"] for r in loss]
    pw = [-r["pct"] for r in wins]
    pl = [r["pct"] for r in loss]
    med = lambda v: (sorted(v)[len(v) // 2] if len(v) % 2
                     else (sorted(v)[len(v) // 2 - 1] + sorted(v)[len(v) // 2]) / 2) if v else 0.0
    print(f"\n=== {label}  ({len(rows)} cells: {len(wins)} win, {len(tie)} tie, {len(loss)} lose)")
    print(f"    {'':22s} {'ABSOLUTE':>22s}    {'PERCENT of K':>20s}")
    print(f"    {'':22s} {'mean':>10s} {'median':>10s}    {'mean':>9s} {'median':>9s}")
    if wins:
        print(f"    {'WIN depth':22s} {sum(aw)/len(aw):10.2f} {med(aw):10.2f}    "
              f"{sum(pw)/len(pw):8.2f}% {med(pw):8.2f}%")
    if loss:
        print(f"    {'LOSS depth':22s} {sum(al)/len(al):10.2f} {med(al):10.2f}    "
              f"{sum(pl)/len(pl):8.2f}% {med(pl):8.2f}%")
    if wins and loss:
        print(f"    loss/win ratio         {(sum(al)/len(al))/(sum(aw)/len(aw)):10.2f}x"
              f" (mean) {med(al)/med(aw):9.2f}x (median)")
    print(f"    NET total (neg = we win): {sum(r['delta'] for r in rows):+.2f} absolute, "
          f"{sum(r['pct'] for r in rows):+.2f} pct-points")
    w = wilcoxon([r["delta"] for r in rows])
    if w:
        print(f"    Wilcoxon signed-rank: n={w['n']} W+={w['w_plus']:.1f} W-={w['w_minus']:.1f} "
              f"z={w['z']:+.3f} -> {'SIGNIFICANT at 0.05' if w['sig05'] else 'not significant'}")
    return w


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="runs/p2_full_arm.json")
    a = ap.parse_args()
    d = json.load(open(a.src))
    rows = d["rows"]
    for r in rows:
        r["pct"] = r["delta"] / r["k_best"] * 100

    print("Sign convention: NEGATIVE = we are better.\n")
    print(f"{'cell':7s} {'K best':>8s} {'our median':>11s} {'delta':>9s} {'delta %':>9s}  verdict")
    for r in sorted(rows, key=lambda r: r["pct"]):
        print(f"{r['cell']:7s} {r['k_best']:8.1f} {r['median']:11.1f} {r['delta']:+9.2f} "
              f"{r['pct']:+8.2f}%  {r['verdict']}")

    summarise(rows, "ALL 20 CELLS")
    out = [r for r in rows if r["cell"] not in ("R203", "RC203")]
    summarise(out, "EXCLUDING the 2 known-bimodal cells (R203, RC203)")
    print("\nNOTE: the exclusion is DIAGNOSTIC, not a reported headline -- dropping your two")
    print("worst cells is not a result. It isolates how much of the deficit is variance.")
