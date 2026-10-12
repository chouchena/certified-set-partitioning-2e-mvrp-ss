"""
F5 — the arithmetic/MILP crossover, and the mechanism behind it.

Two panels, because the second explains the first:

  (a) AB / MILP per cell against instance size, with the 1.0 line. The CLAIM IS THE TREND:
      the closed-form bound is strictly dominated at |C| <= 30, crosses at 50, and carries the
      portfolio at 100. A number cannot replace this -- the per-cell spread at each size is
      part of the claim (the crossover is per-CELL, not per-family).

  (b) Why, at |C| = 50: AB/MILP against how deep the MILP descent reached. The correlation is
      -0.716 and the separation is near-clean -- every AB win sits at |H| <= 16 of 50. This is
      the retained-set truncation mechanism, and it is a SCATTER claim: the separation is the
      evidence.

    python analysis/fig_crossover.py
"""
import os, sys, json, glob, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])
SIZES = [10, 20, 30, 50, 100]
COL = {"C": "#1f4e79", "R": "#c0392b", "RC": "#2e8b57"}


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def milp_and_depth(cell, size):
    best, depth = None, 0
    for pat in (f"easy_reduction_descend_{cell}_n{size}.json",
                f"easy_reduction_descend_{cell}_n{size}_*.json"):
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            recs = json.load(open(f))
            for r in (recs if isinstance(recs, list) else [recs]):
                v = r.get("block_relax")
                if isinstance(v, (int, float)) and (best is None or v > best):
                    best = v
                depth = max(depth, r.get("nH") or 0)
    return best, depth


def main():
    grid = {(r["cell"], r["size"]): r for r in
            json.load(open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json")))["records"]}
    plt.rcParams.update({"font.size": 9, "axes.labelsize": 9, "axes.titlesize": 10,
                         "legend.fontsize": 8, "axes.spines.top": False,
                         "axes.spines.right": False})
    fig, (axA, axB) = plt.subplots(1, 2, figsize=(9.2, 3.6))

    # ---------- (a) crossover vs size ----------
    meds = []
    for i, s in enumerate(SIZES):
        vals = []
        for c in CELLS:
            m, _ = milp_and_depth(c, s)
            g = grid.get((c, s))
            if m and g:
                r = g["ab4_full"] / m
                vals.append(r)
                axA.scatter(i + (hash(c) % 21 - 10) / 90, r, s=13, alpha=.55,
                            color=COL[fam(c)], lw=0, zorder=3)
        meds.append(st.median(vals) if vals else None)
    axA.plot(range(len(SIZES)), meds, "-o", color="#333", lw=1.6, ms=5, zorder=4,
             label="median")
    axA.axhline(1.0, color="#888", ls=(0, (5, 3)), lw=1.2, zorder=2)
    axA.text(0.02, 1.02, "AB exceeds the MILP bound above this line", transform=axA.get_yaxis_transform(),
             fontsize=7.5, color="#666", va="bottom")
    axA.set_xticks(range(len(SIZES)))
    axA.set_xticklabels([f"{s}" for s in SIZES])
    axA.set_xlabel("|C|  (instance size)")
    axA.set_ylabel("arithmetic bound / MILP block relaxation")
    axA.set_title("(a)  the crossover is per cell, not per family")
    axA.grid(alpha=.25, lw=.6); axA.set_axisbelow(True)
    for f, col in COL.items():
        axA.scatter([], [], s=18, color=col, lw=0, label=f)
    axA.legend(frameon=False, loc="upper left", ncol=2)

    # ---------- (b) mechanism at n50 ----------
    xs, ys, cs = [], [], []
    for c in CELLS:
        m, d = milp_and_depth(c, 50)
        g = grid.get((c, 50))
        if m and g and d:
            xs.append(d); ys.append(g["ab4_full"] / m); cs.append(COL[fam(c)])
    axB.scatter(xs, ys, s=26, c=cs, alpha=.75, lw=0, zorder=3)
    axB.axhline(1.0, color="#888", ls=(0, (5, 3)), lw=1.2, zorder=2)
    win = [x for x, y in zip(xs, ys) if y > 1]
    if win:
        axB.axvspan(min(xs) - 1, max(win) + 0.5, color="#2b7bba", alpha=.10, lw=0, zorder=1)
        axB.text(max(win) + 1, max(ys) * 0.98,
                 "every AB win sits at\n|H| <= %d of 50" % max(win),
                 fontsize=8, color="#1f4e79", va="top")
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** .5
    axB.set_xlabel("deepest retained set |H|  (of 50 customers)")
    axB.set_ylabel("arithmetic bound / MILP block relaxation")
    axB.set_title("(b)  why: the MILP descent truncates,  r = %.2f" % (num / den))
    axB.grid(alpha=.25, lw=.6); axB.set_axisbelow(True)

    fig.tight_layout()
    p = os.path.join(ROOT, "paper", "figures", "F5_crossover.png")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    print(f"-> {os.path.relpath(p, ROOT)}")
    print("   median AB/MILP by size: " +
          ", ".join(f"n{s} {m:.3f}" for s, m in zip(SIZES, meds) if m))
    print("   correlation(depth, AB/MILP) at n50 = %.3f" % (num / den))


if __name__ == "__main__":
    main()
