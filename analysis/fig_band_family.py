"""Figure 2b (tasks #51/#52): per-family LB->OV band at |C| = 100, ours vs K.

The companion to the pooled band (Figure 2a): at the largest size K publish by family, and every
cell is open, so the family split is both available and entirely competition. One group per family
(C, R, RC); two bars each spanning mean LB (square) to mean OV (triangle). Ours in blue, K in grey
and hatched (family-level, no per-instance data).

DATA (sourced, not hardcoded):
  ours : recap_grid_vs_k.our_union(100) family means; R204/R208 carry the d744 dual-derived
         incumbent so each family is complete.
  K    : kref_build.TABLE6 -- OV = min(joint,lbbd) zIP, LB = joint zIP*(1-gap_joint/100).

The script asserts the per-family LB ratio (ours/K) equals paper/numbers.json lb-vs-k
(n100-{C,R,RC}-ratio = 1.74/2.13/2.42), so the figure and the text cannot drift.
"""
import os
import sys
import json
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
from kref_build import TABLE6

LBVK = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))["lb-vs-k"]["value"]
FAMS = (("C", lambda c: c.startswith("C")),
        ("R", lambda c: c.startswith("R") and not c.startswith("RC")),
        ("RC", lambda c: c.startswith("RC")))


def data():
    u = R.our_union(100)
    rows = []
    for f, pred in FAMS:
        cs = [c for c in u if pred(c)]
        oov = st.mean([u[c][0] for c in cs])
        olb = st.mean([u[c][1] for c in cs])
        t = TABLE6[f]
        kov = min(t["joint"]["zIP"], t["lbbd"]["zIP"])
        klb = t["joint"]["zIP"] * (1 - t["gap_joint"] / 100.0)
        rows.append((f, len(cs), oov, olb, kov, klb))
    return rows


D = data()
for f, _, _, olb, _, klb in D:
    assert abs(olb / klb - float(LBVK["n100-%s-ratio" % f])) < 0.02, (f, olb / klb)

OUR = "#1b6ca8"
KC = "#5a5a5a"
w = 0.38
ymax = max(max(r[2], r[4]) for r in D)

fig, ax = plt.subplots(figsize=(6.8, 4.3))
for i, (f, nc, oov, olb, kov, klb) in enumerate(D):
    xo, xk = i - w / 2, i + w / 2
    ax.bar(xo, oov - olb, bottom=olb, width=w, color=OUR, alpha=0.85, zorder=2)
    ax.plot(xo, olb, marker="s", ms=6, color=OUR, mec="white", mew=0.5, ls="none", zorder=5)
    ax.plot(xo, oov, marker="^", ms=8, color=OUR, mec="white", mew=0.5, ls="none", zorder=5)
    ax.bar(xk, kov - klb, bottom=klb, width=w, color=KC, alpha=0.85, hatch="////", zorder=2)
    ax.plot(xk, klb, marker="s", ms=6, color=KC, mec="white", mew=0.5, ls="none", zorder=5)
    ax.plot(xk, kov, marker="^", ms=8, color=KC, mec="white", mew=0.5, ls="none", zorder=5)

ax.set_xticks(range(len(D)))
ax.set_xticklabels(["%s\n(%d cells)" % (r[0], r[1]) for r in D])
ax.set_xlabel(u"Instance family at  |C| = 100")
ax.set_ylabel(u"Objective value (family mean)")
ax.set_ylim(0, ymax * 1.16)
ax.set_title(u"Optimality-gap bracket (LB→OV) by family at |C| = 100: ours vs K", pad=8)
col_leg = ax.legend(handles=[Patch(facecolor=OUR, label="Ours"), Patch(facecolor=KC, label="K")],
                    loc="upper left", title="colour")
ax.add_artist(col_leg)
ax.legend(handles=[Line2D([0], [0], marker="s", color="#333333", ls="none", ms=6, label="LB (bottom)"),
                   Line2D([0], [0], marker="^", color="#333333", ls="none", ms=8, label="OV (top)")],
          loc="upper left", bbox_to_anchor=(0.0, 0.80), title="marker")
ax.annotate("All cells open at |C| = 100. K family-level (Table 6), hatched: no per-instance data. "
            "LB ratio ours/K = 1.74 / 2.13 / 2.42 for C / R / RC.",
            xy=(0, 0), xytext=(0.0, -0.17), textcoords="axes fraction", fontsize=6.5, color="#777777")

figstyle.save(fig, "band_family_n100",
              sources=["runs/oracle/tep_solve_pu_ng*_n100.json (our union)",
                       "runs/oracle/tep_solve_frzdual2_*_n100.json (d744 derived R204/R208)",
                       "analysis/kref_build.py:TABLE6 (K n100 family)",
                       "paper/numbers.json:lb-vs-k (LB ratios asserted equal)"])
print("families:", [(r[0], round(100 * (r[2] - r[3]) / r[2], 1), round(100 * (r[4] - r[5]) / r[4], 1)) for r in D])
print("saved paper/figures/band_family_n100.{pdf,eps,png}")
