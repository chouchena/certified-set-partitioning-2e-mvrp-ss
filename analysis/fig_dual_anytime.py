"""
F1 — anytime dual bound against K's published bound. Publication draft, not a smoke test.

The figure carries one claim: our dual bound passes the bound K report after a four-hour run,
within seconds, and then keeps climbing. Design choices follow from that:

  * LOG time axis from 10 ms — the crossings happen across four decades (0.02 s to 22 s), so a
    linear axis would collapse every one of them onto the y-gutter.
  * K's bound as a horizontal reference with the crossing marked — the crossing IS the result.
  * The exceedance region shaded, so "how far past" is legible without reading gridlines.
  * One cell per family, chosen to span the range of crossing times rather than to flatter:
    R207 is the SLOWEST family's representative and takes 22.6 s, three decades worse than C203.

    python analysis/fig_dual_anytime.py --size 20
"""
import os, sys, json, glob, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import kref

OUT = os.path.join(ROOT, "paper", "figures")
FLOOR = 0.01          # seconds; the log axis cannot start at 0


def dual_curve(cell, size):
    pts = []
    for pat in (f"easy_reduction_descend_{cell}_n{size}.json",
                f"easy_reduction_descend_{cell}_n{size}_*.json"):
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            recs = json.load(open(f))
            for r in (recs if isinstance(recs, list) else [recs]):
                pts += (r.get("lb_curve") or [])
    pts.sort()
    out, best = [], None
    for t, b in pts:
        if best is None or b > best:
            best = b
            out.append((max(t, FLOOR), b))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--cells", default="C203,R207,RC203")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    cells = [c.strip() for c in a.cells.split(",")]
    klb = kref.derived_lb(a.size)

    plt.rcParams.update({"font.size": 9, "axes.labelsize": 9, "axes.titlesize": 10,
                         "legend.fontsize": 8, "axes.spines.top": False,
                         "axes.spines.right": False})
    fig, axes = plt.subplots(1, len(cells), figsize=(3.3 * len(cells), 3.0))
    if len(cells) == 1:
        axes = [axes]

    for ax, c in zip(axes, cells):
        cv = dual_curve(c, a.size)
        t = [x[0] for x in cv]; b = [x[1] for x in cv]
        K = klb[c]
        cross = next((tt for tt, bb in cv if bb > K), None)

        ax.fill_between(t, K, b, where=[x > K for x in b], step="post",
                        color="#2b7bba", alpha=.13, lw=0)
        ax.step(t, b, where="post", color="#1f4e79", lw=1.6, zorder=3,
                label="our dual bound")
        ax.axhline(K, color="#c0392b", ls=(0, (5, 3)), lw=1.3, zorder=2,
                   label=f"K published bound  {K:.0f}")

        if cross:
            ax.plot([cross], [K], "o", ms=5, color="#c0392b", zorder=5,
                    markerfacecolor="white", markeredgewidth=1.4)
            # Label in AXES fractions, not data coordinates: a crossing at 0.02 s sits hard
            # against the left spine, and a data-coordinate offset put the text off-canvas
            # and on top of the legend.
            ax.annotate("passes K at %.2f s" % cross,
                        xy=(cross, K), xycoords="data",
                        xytext=(0.28, 0.90), textcoords="axes fraction",
                        fontsize=8, color="#c0392b", ha="left", va="center",
                        arrowprops=dict(arrowstyle="->", color="#c0392b", lw=.9,
                                        connectionstyle="arc3,rad=-0.25"))

        ax.set_xscale("log")
        ax.set_xlim(FLOOR, max(t) * 1.6)
        ax.set_ylim(min(b) - (max(b) - min(b)) * .05, max(b) + (max(b) - min(b)) * .12)
        ax.xaxis.set_major_locator(LogLocator(base=10, numticks=6))
        ax.set_title(f"{c}   (|C| = {a.size})")
        ax.set_xlabel("seconds of descent (log)")
        ax.grid(alpha=.25, which="major", lw=.6)
        ax.set_axisbelow(True)
        gain = (b[-1] - K) / K * 100
        ax.text(.97, .08, "final bound +%.0f%% over K" % gain,
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=8, color="#1f4e79")

    axes[0].set_ylabel("lower bound on the optimum")
    # ONE shared legend below the panels. A per-panel legend sat in the same corner as the
    # crossing annotation and the gain label, and all three overlapped.
    h, _ = axes[0].get_legend_handles_labels()
    fig.legend(h, ["our dual bound", "bound reported by Karademir et al. (4 h limit)"],
               loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, -0.07))
    fig.suptitle("Anytime dual bound against the bound reported by Karademir et al. "
                 "after a 4-hour limit", fontsize=10.5, y=1.02)
    fig.tight_layout()
    p = os.path.join(OUT, f"F1_dual_anytime_n{a.size}.png")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    print(f"-> {os.path.relpath(p, ROOT)}")
    for c in cells:
        cv = dual_curve(c, a.size); K = klb[c]
        cross = next((tt for tt, bb in cv if bb > K), None)
        print(f"   {c}: passes K at {cross:.2f}s, final {cv[-1][1]:.1f} vs K {K:.1f} "
              f"(+{(cv[-1][1]-K)/K*100:.0f}%)")


if __name__ == "__main__":
    main()
