"""Figure 3 (task #52): optimality gap (OV-LB)/OV by instance size, ours vs K, open+proven split.

The headline gap-reduction exhibit. Two series against instance size:
  ours : mean of per-cell opt-gap on the OPEN (competition) cells -- the same aggregation the
         manuscript reports (optgap.n50-competition-mean 15.4, n100 13.1).
  K    : mean of K's published gaps on the same open set. At n20/n30 per-cell (table3, open
         subset); at n50 the single pooled gap (table4 1:10); at n100 the mean of K's three
         published family gaps (Table 6) -- which is optgap.n100-k-mean = 71.0.

PRE-REGISTERED SPLIT (d742): open and proven are never pooled. Proven (calibration) cells sit at
zero for K by construction (K prove them); at |C| = 10 all 27 are proven, so the competition
series begins at n20. The proven region is shown as a calibration band at zero with its per-size
count, and the text reports the primal's attainment of the known optima there (slip, not this gap).

Aggregation matches analysis/manuscript_numbers.py @optgap exactly (mean of per-cell gaps), so the
figure and the \num values cannot drift: this script asserts its n50/n100 points against them.
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
from matplotlib.lines import Line2D
import recap_grid_vs_k as R
import k_comparison as K
from kref_build import TABLE6

SIZES = [20, 30, 50, 100]
NUMS = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))["optgap"]["value"]


def g(ov, lb):
    return 100.0 * (ov - lb) / ov


def open_set(n):
    pc = R.k_percell(n)
    return {c for c, v in pc.items() if g(v[0], v[1]) > 1e-9}


def ours_gap(n):
    u = R.our_union(n)
    oc = open_set(n) if n in (20, 30) else set(u)
    return st.mean([g(u[c][0], u[c][1]) for c in u if c in oc])


def k_gap(n):
    if n in (20, 30):
        pc = R.k_percell(n)
        oc = open_set(n)
        return st.mean([g(pc[c][0], pc[c][1]) for c in oc])
    if n == 50:
        # K's PUBLISHED joint optimality gap at n50 (table4 1:10), the only optimality gap K print
        # at this size -- matches _k_n50_pool element 2 (d784, reviewer 3B). NOT the old hybrid that
        # divided the Joint-reconstructed dual by the LBBD incumbent (that printed 57.0, unpublished).
        t4 = {r["method"]: r for r in K._kref()["table4"]
              if r.get("size") == 50 and r.get("wls") == "1:10"}
        return float(t4["Joint"]["gap_imp"])
    # n100: n-weighted mean of K's published family gaps (families: C=8, R=11, RC=8) -- _k_n100_fam
    tot = sum(TABLE6[f]["n"] for f in TABLE6)
    return sum(TABLE6[f]["gap_joint"] * TABLE6[f]["n"] for f in TABLE6) / tot


ours = [ours_gap(n) for n in SIZES]
kk = [k_gap(n) for n in SIZES]

# guard: the reported points must equal the registered \num values (no drift figure<->text)
assert abs(ours[SIZES.index(50)] - float(NUMS["n50-competition-mean"])) < 0.1, ours
assert abs(ours[SIZES.index(100)] - float(NUMS["n100-competition-mean"])) < 0.1, ours
assert abs(kk[SIZES.index(50)] - float(NUMS["n50-k-mean"])) < 0.1, kk
assert abs(kk[SIZES.index(100)] - float(NUMS["n100-k-mean"])) < 0.6, kk

OUR = "#1b6ca8"
KC = "#5a5a5a"
X = list(range(len(SIZES)))

fig, ax = plt.subplots(figsize=(6.8, 4.3))
# calibration band at zero (proven cells); n10 is entirely proven
ax.axhspan(-1.5, 1.5, color="#e8efd6", zorder=0)
ax.text(len(SIZES) - 0.98, 0.2, "calibration band (proven cells: K gap = 0, our incumbent attains "
        "the optimum)", ha="right", va="bottom", fontsize=6.3, color="#6a7a4a")

ax.plot(X, kk, marker="o", ms=7, color=KC, lw=2.0, label="K (published)", zorder=3)
ax.plot(X, ours, marker="D", ms=7, color=OUR, lw=2.2, label="Ours (certified)", zorder=4)
for x, y in zip(X, ours):
    ax.annotate("%.1f%%" % y, (x, y), textcoords="offset points", xytext=(0, -14),
                ha="center", fontsize=7.5, color=OUR, fontweight="bold")
for x, y in zip(X, kk):
    ax.annotate("%.0f%%" % y, (x, y), textcoords="offset points", xytext=(0, 8),
                ha="center", fontsize=7.5, color=KC)

# mark that n10 sits in the proven band (no open series)
ax.annotate("n10: all 27 proven\n(calibration)", xy=(-0.0, 0), xytext=(-0.02, 10),
            textcoords="offset points", ha="left", va="bottom", fontsize=6.3, color="#6a7a4a")

ax.set_xticks(X)
ax.set_xticklabels(["n=%d" % n for n in SIZES])
ax.set_xlabel(u"Number of customers  n = |C|")
ax.set_ylabel(u"Optimality gap  (OV − LB) / OV   (%)")
ax.set_ylim(-3, max(kk) * 1.12)
ax.set_title(u"Optimality gap by instance size, open cells: ours vs K", pad=8)
ax.legend(loc="center left", frameon=True)
ax.annotate("Open (competition) cells; gap is the mean of per-cell gaps, matching the reported "
            "values.\nn20/30 per-cell; n50 K pooled; n100 K family-level (Table 6).",
            xy=(0, 0), xytext=(0.0, -0.19), textcoords="axes fraction",
            fontsize=6.5, color="#777777")

figstyle.save(fig, "optgap_vs_k_by_size",
              sources=["runs/oracle/tep_solve_pu_ng*_n{20,30,50,100}.json (our union)",
                       "runs/oracle/tep_solve_frzdual2_*_n100.json (d744 derived R204/R208)",
                       "data/karademir2025/k_reference.json (K n20/30/50)",
                       "analysis/kref_build.py:TABLE6 (K n100 family gaps)",
                       "paper/numbers.json:optgap (asserted equal)"])
print("ours:", [round(x, 1) for x in ours], " K:", [round(x, 1) for x in kk])
print("saved paper/figures/optgap_vs_k_by_size.{pdf,eps,png}")
