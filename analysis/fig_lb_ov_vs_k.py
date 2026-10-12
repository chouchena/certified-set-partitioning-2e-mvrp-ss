"""Figure (tasks #51/#52): per-size floating bars LB->OV, ours vs K, OPEN (competition) cells.

Each (size, method) is a vertical bar spanning [mean LB, mean OV]; the bar HEIGHT is the absolute
mean opt-gap and its VERTICAL POSITION is the objective level. Ours and K in distinct colours;
square marks LB (bar bottom), triangle marks OV (top); the opt-gap % is annotated above each bar.

PRE-REGISTERED SPLIT (d742): this is a headline figure, so it is reported on the OPEN (competition)
cells only -- a cell is proven (calibration) when K report a zero gap, open otherwise, and the two
are NEVER pooled. At |C| = 10 all 27 cells are proven (K's exact B&B closes them), so n10 has no
open cell and does not appear here; the n10 calibration story is told in the text and in the
opt-gap-by-size figure. Open counts: 20 of 27 at n20, 26 at n30, all 27 at n50 and n100.

DATA (sourced in code, not hardcoded):
  ours : recap_grid_vs_k.our_union(n) -- the budget-fit union; n100 uses the d744 dual-derived
         fallback for R204/R208 (no primal artifact), so n100 is a full 27.
  K    : n20/30 per-cell (k_reference table3), restricted to the open set (K gap > 0); n50 POOL
         (table4, wls 1:10; all open); n100 Table 6 family-weighted (kref_build.TABLE6; all open).

CAVEATS carried on the figure: K n50/n100 bars are HATCHED because K publishes no PER-CELL data at
those sizes -- n50 is pooled, n100 is family-level (Table 6). Objective weighting is NOT an issue:
our grid and K's Table 6 are both WLS 1:10 (verified -- tep_solve builds wls=0.1 = 1:10).
"""
import os
import sys
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import figstyle
figstyle.apply(base=9)
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import recap_grid_vs_k as R
import k_comparison as K
from kref_build import TABLE6

SIZES = [20, 30, 50, 100]          # open-cell (competition) sizes; n10 is all-proven (d742)


def open_cells(n):
    """Cells open at size n = those K do NOT prove (reported gap > 0). n50/n100: all 27."""
    if n in (20, 30):
        pc = R.k_percell(n)
        return {c for c, v in pc.items() if R.optgap(v[0], v[1]) and R.optgap(v[0], v[1]) > 1e-9}
    return None                     # None = all cells (every cell open at n50/n100)


def ours_mean(n):
    u = R.our_union(n)
    oc = open_cells(n)
    cells = [c for c in u if oc is None or c in oc]
    return (st.mean([u[c][0] for c in cells]),
            st.mean([u[c][1] for c in cells]), len(cells))


def k_mean(n):
    if n in (20, 30):
        pc = R.k_percell(n)
        oc = open_cells(n)
        cells = [c for c in pc if c in oc]
        return (st.mean([pc[c][0] for c in cells]),
                st.mean([pc[c][1] for c in cells]), "per-cell")
    if n == 50:
        t4 = {r["method"]: r for r in K._kref()["table4"]
              if r.get("size") == 50 and r.get("wls") == "1:10"}
        kj, kl = float(t4["Joint"]["bk"]), float(t4["LBBD"]["bk"])
        return min(kj, kl), kj * (1.0 - float(t4["Joint"]["gap_imp"]) / 100.0), "pool"
    tot = sum(TABLE6[f]["n"] for f in TABLE6)
    kov = sum(min(TABLE6[f]["joint"]["zIP"], TABLE6[f]["lbbd"]["zIP"]) * TABLE6[f]["n"]
              for f in TABLE6) / tot
    klb = sum(TABLE6[f]["joint"]["zIP"] * (1.0 - TABLE6[f]["gap_joint"] / 100.0) * TABLE6[f]["n"]
              for f in TABLE6) / tot
    return kov, klb, "Table6"


OUR = "#1b6ca8"
KC = "#5a5a5a"
w = 0.38

data = []
for n in SIZES:
    oov, olb, nc = ours_mean(n)
    kov, klb, src = k_mean(n)
    data.append((n, oov, olb, nc, kov, klb, src))

ymax = max(max(d[1], d[4]) for d in data)

fig, ax = plt.subplots(figsize=(6.8, 4.3))
for i, (n, oov, olb, nc, kov, klb, src) in enumerate(data):
    xo, xk = i - w / 2, i + w / 2
    hatch = None if src == "per-cell" else "////"
    # ours: bar LB->OV, square at LB, triangle at OV
    ax.bar(xo, oov - olb, bottom=olb, width=w, color=OUR, alpha=0.85, zorder=2)
    ax.plot(xo, olb, marker="s", ms=6, color=OUR, mec="white", mew=0.5, ls="none", zorder=5)
    ax.plot(xo, oov, marker="^", ms=8, color=OUR, mec="white", mew=0.5, ls="none", zorder=5)
    # K: bar hatched where pooled/family, markers always
    kh = max(kov - klb, 0.0)
    ax.bar(xk, kh, bottom=klb, width=w, color=KC, alpha=0.85, edgecolor="white",
           linewidth=0.0, hatch=hatch, zorder=2)
    ax.plot(xk, klb, marker="s", ms=6, color=KC, mec="white", mew=0.5, ls="none", zorder=5)
    ax.plot(xk, kov, marker="^", ms=8, color=KC, mec="white", mew=0.5, ls="none", zorder=5)
    # No numeric opt-gap annotation here: the bar geometry is a pooled bracket (gap of the mean
    # LB and mean OV), whereas the opt-gap the paper reports is the mean of per-cell gaps -- these
    # differ (notably K at n100: 68 vs the reported 71). The precise opt-gap series, matching the
    # \num values, is Figure 3; this figure shows the LEVELS and the visual bracket only.

ax.set_xticks(range(len(SIZES)))
ax.set_xticklabels(["n=%d\n(%d open)" % (n, d[3]) for n, d in zip(SIZES, data)])
ax.set_xlabel(u"Number of customers  n = |C|")
ax.set_ylabel(u"Objective value (mean over open cells)")
ax.set_ylim(0, ymax * 1.16)
ax.set_title(u"Optimality-gap bracket (LB→OV) by instance size, open cells: ours vs K", pad=8)

# two legends: COLOUR -> method, MARKER -> metric
col_leg = ax.legend(handles=[Patch(facecolor=OUR, label="Ours"), Patch(facecolor=KC, label="K")],
                    loc="upper left", title="colour")
ax.add_artist(col_leg)
ax.legend(handles=[Line2D([0], [0], marker="s", color="#333333", ls="none", ms=6, label="LB (bottom)"),
                   Line2D([0], [0], marker="^", color="#333333", ls="none", ms=8, label="OV (top)")],
          loc="upper left", bbox_to_anchor=(0.0, 0.80), title="marker")
ax.annotate("Open (competition) cells only; n10 omitted (all 27 proven by K). "
            "K hatched: no per-cell K data (n50 pooled, n100 family-level).",
            xy=(0, 0), xytext=(0.0, -0.19), textcoords="axes fraction",
            fontsize=6.5, color="#777777")

figstyle.save(fig, "lb_ov_vs_k_by_size",
              sources=["runs/oracle/tep_solve_pu_ng*_n{20,30,50,100}.json (our budget-fit union)",
                       "runs/oracle/tep_solve_frzdual2_*_n100.json (d744 derived R204/R208)",
                       "data/karademir2025/k_reference.json (K n20/30 per-cell, n50 pool)",
                       "analysis/kref_build.py:TABLE6 (K n100 family)"])
print("saved paper/figures/lb_ov_vs_k_by_size.{pdf,eps,png}")
