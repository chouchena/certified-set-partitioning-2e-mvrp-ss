"""Figure 5 (task #52, d737/d767): what the primal leg adds -- dual-derived vs full-primal opt-gap.

The bound leg's master IP selection is a feasible verified incumbent at no extra cost; taking it
as the baseline and the full primal pipeline as the treatment isolates what the primal leg buys.
Two series of mean opt-gap (OV-LB)/OV by instance size, over the cells where the primal actually
ran (R204/R208 at n100 are refinement-not-applied, so excluded -- no treatment value):

  dual-derived (baseline) : gap of the frozen-dual incumbent (_frz) against the certified LB
  full primal (treatment) : gap of the budget-fit union incumbent against the same LB

Both use the SAME per-cell LB, so the vertical distance is exactly the primal's gap reduction.
It is positive at every size and narrows at |C| = 100 as the lower bound comes to carry the
result. The script asserts its pooled mean reduction equals manuscript_numbers @ablation
(mean-gap-gain-pp) so figure and text cannot drift.
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
import manuscript_numbers as M

SIZES = [10, 20, 30, 50, 100]
ABL = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))["ablation"]["value"]


def series(size):
    rows = M._tep_best_of(size) if size in (10, 20, 30) else M._cons(size)
    dd, fp, allpp = [], [], []
    for r in rows:
        if r.get("dual_derived"):
            continue
        frz = M._frz(r["cell"], size)
        lb = r.get("our_lb")
        if not frz or not lb:
            continue
        dov, fov = frz[0], r["best"]
        if dov <= 0 or fov <= 0:
            continue
        dgap, fgap = 100.0 * (dov - lb) / dov, 100.0 * (fov - lb) / fov
        dd.append(dgap)
        fp.append(fgap)
        allpp.append(dgap - fgap)
    return st.mean(dd), st.mean(fp), len(dd), allpp


D, F, N, POOL = [], [], [], []
for s in SIZES:
    d, f, n, pp = series(s)
    D.append(d)
    F.append(f)
    N.append(n)
    POOL += pp

# guard: pooled mean gap reduction must equal the registered @ablation value (no drift)
assert abs(st.mean(POOL) - float(ABL["mean-gap-gain-pp"])) < 0.1, st.mean(POOL)

BASE = "#b0801b"   # dual-derived baseline (amber)
TREAT = "#1b6ca8"  # full primal (blue)
X = list(range(len(SIZES)))

fig, ax = plt.subplots(figsize=(6.8, 4.3))
ax.fill_between(X, F, D, color="#cfe0ec", alpha=0.6, zorder=1, label="gap the primal leg closes")
ax.plot(X, D, marker="o", ms=7, color=BASE, lw=2.0, label="Dual-derived incumbent (baseline)", zorder=3)
ax.plot(X, F, marker="D", ms=7, color=TREAT, lw=2.2, label="Full primal pipeline (treatment)", zorder=4)
for x, d, f in zip(X, D, F):
    ax.annotate(u"−%.1f pp" % (d - f), (x, (d + f) / 2), ha="center", va="center",
                fontsize=7, color="#555555",
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.75))

ax.set_xticks(X)
ax.set_xticklabels(["n=%d\n(%d cells)" % (n, c) for n, c in zip(SIZES, N)])
ax.set_xlabel(u"Number of customers  n = |C|")
ax.set_ylabel(u"Optimality gap  (OV − LB) / OV   (%)")
ax.set_ylim(0, max(D) * 1.15)
ax.set_title(u"What the primal leg adds: optimality gap, dual-derived vs full primal", pad=8)
ax.legend(loc="upper right", frameon=True, fontsize=7.5)
ax.annotate("Over cells where the primal ran (R204/R208 refinement-not-applied, excluded at n100); "
            "same LB in both series.\nMean reduction %.1f pp; at n100, %.1f%% mean OV reduction."
            % (float(ABL["mean-gap-gain-pp"]), float(ABL["n100-ov-gain-pct"])),
            xy=(0, 0), xytext=(0.0, -0.19), textcoords="axes fraction", fontsize=6.5, color="#777777")

figstyle.save(fig, "ablation_primal_leg",
              sources=["runs/oracle/tep_uniform_n{50,100}.json + tep_best_of n{10,20,30} (_cons/_tep_best_of)",
                       "runs/oracle/tep_solve_frzdual2_*_n*.json (dual-derived baseline; _frz)",
                       "paper/numbers.json:ablation (mean-gap-gain-pp asserted equal)"])
print("dual-derived:", [round(x, 1) for x in D], " full-primal:", [round(x, 1) for x in F],
      " pooled dpp:", round(st.mean(POOL), 2))
print("saved paper/figures/ablation_primal_leg.{pdf,eps,png}")
