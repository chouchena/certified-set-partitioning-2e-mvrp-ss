"""
SMOKE TEST for the trajectory figures (F1 dual, F3 primal) — does the plotting path work
end-to-end on real logged data?

This is a smoke test, not the publication figure. It asks: can we read the trajectories, do
they look like trajectories, and does K's reference line land where the numbers say it should?
Styling, panel layout and float budget come later (SKELETON Part 7c).

  F1  anytime DUAL bound vs wall time, one panel per family, K's published bound as a
      horizontal reference. Source: lb_curve in the provenanced descend artifacts.
  F3  anytime PRIMAL incumbent vs wall time, same idea, K's BK as the reference.
      Source: best_incumbent trajectories in the fixopt run logs.

    python analysis/plot_trajectories.py --size 20

Writes paper/figures/smoke_F1_dual_n<size>.png and smoke_F3_primal_n<size>.png.
"""
import os, sys, json, glob, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import kref

OUT = os.path.join(ROOT, "paper", "figures")
FAM = ("C", "R", "RC")


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def dual_curve(cell, size):
    """(t, bound) over the whole descent. lb_curve timestamps are cell-global and continuous
    across records (verified 2026-09-13), so concatenating records is correct."""
    pts = []
    for pat in (f"easy_reduction_descend_{cell}_n{size}.json",
                f"easy_reduction_descend_{cell}_n{size}_*.json"):
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            recs = json.load(open(f))
            for r in (recs if isinstance(recs, list) else [recs]):
                pts += (r.get("lb_curve") or [])
    pts.sort()
    # running max: a dual bound never decreases
    out, best = [], None
    for t, b in pts:
        if best is None or b > best:
            best = b
            out.append((t, b))
    return out


def primal_curves(cell, size, limit=6, max_wall=None):
    """(t, incumbent) per run, from the fixopt logs.

    max_wall filters to ONE budget regime. Without it the panel overlays 290 s screen runs
    with 1400 s historical runs, which look like the same experiment and are not.
    """
    runs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "runs", f"fixopt_{cell}_n{size}_s*.jsonl")))[-limit:]:
        pts = []
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            inc = d.get("best_incumbent")
            if inc is not None and d.get("wall_s") is not None:
                pts.append((d["wall_s"], inc))
        if pts:
            if max_wall is not None and max(t for t, _ in pts) > max_wall:
                continue                      # different budget regime, not comparable
            runs.append(sorted(pts))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--cells", default="C203,R207,RC203")
    ap.add_argument("--max-wall", type=float, default=400.0,
                    help="keep only primal runs under this wall time, so one panel shows ONE "
                         "budget regime (screen runs are ~290s, historical ones ~1400s)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    cells = [c.strip() for c in a.cells.split(",")]
    klb = kref.derived_lb(a.size)
    kbk = kref.table3(a.size)

    # ---- F1 dual ----
    fig, axes = plt.subplots(1, len(cells), figsize=(4.2 * len(cells), 3.4), sharey=False)
    if len(cells) == 1:
        axes = [axes]
    ok = 0
    for ax, c in zip(axes, cells):
        cv = dual_curve(c, a.size)
        if not cv:
            ax.text(.5, .5, f"{c}: no data", ha="center"); continue
        ok += 1
        t = [x[0] for x in cv]; b = [x[1] for x in cv]
        ax.step(t, b, where="post", lw=1.4, label="our dual bound")
        ax.axhline(klb[c], color="crimson", ls="--", lw=1.2,
                   label=f"K bound {klb[c]:.0f}")
        ax.set_xscale("symlog", linthresh=1)
        ax.set_xlim(left=0)          # symlog is symmetric about 0 and was showing NEGATIVE
                                     # wall time; time cannot be negative.
        ax.set_title(f"{c}  (|C|={a.size})", fontsize=10)
        ax.set_xlabel("wall seconds (symlog)"); ax.set_ylabel("dual bound")
        ax.legend(fontsize=7, loc="lower right")
        ax.grid(alpha=.3)
    fig.suptitle("SMOKE F1 — anytime dual bound vs time, K's published bound as reference",
                 fontsize=11)
    fig.tight_layout()
    p1 = os.path.join(OUT, f"smoke_F1_dual_n{a.size}.png")
    fig.savefig(p1, dpi=130); plt.close(fig)
    print(f"F1: {ok}/{len(cells)} panels with data -> {os.path.relpath(p1, ROOT)}")

    # ---- F3 primal ----
    fig, axes = plt.subplots(1, len(cells), figsize=(4.2 * len(cells), 3.4))
    if len(cells) == 1:
        axes = [axes]
    ok = 0
    for ax, c in zip(axes, cells):
        budget_label = f"<={a.max_wall:.0f}s"
        runs = primal_curves(c, a.size, max_wall=a.max_wall)
        if not runs:
            ax.text(.5, .5, f"{c}: no runs", ha="center"); continue
        ok += 1
        for r in runs:
            ax.step([x[0] for x in r], [x[1] for x in r], where="post", lw=.9, alpha=.75)
        ax.axhline(kbk[c]["joint_bk"], color="crimson", ls="--", lw=1.2,
                   label=f"K BK {kbk[c]['joint_bk']:.0f}")
        # The constructive start is ~3x K's BK and squashes the only region that matters.
        # Clip to the neighbourhood of the reference; the descent from construction is not
        # the story and is visible in the first tick anyway.
        bk = kbk[c]["joint_bk"]
        lo = min(min(v for _, v in r) for r in runs)
        ax.set_ylim(lo - 0.02 * bk, bk * 1.35)
        ax.set_title(f"{c}  ({len(runs)} runs, budget {budget_label})", fontsize=10)
        ax.set_xlabel("wall seconds"); ax.set_ylabel("incumbent")
        ax.legend(fontsize=7); ax.grid(alpha=.3)
    fig.suptitle("SMOKE F3 — anytime primal incumbent vs time, K's best-known as reference",
                 fontsize=11)
    fig.tight_layout()
    p3 = os.path.join(OUT, f"smoke_F3_primal_n{a.size}.png")
    fig.savefig(p3, dpi=130); plt.close(fig)
    print(f"F3: {ok}/{len(cells)} panels with data -> {os.path.relpath(p3, ROOT)}")

    # ---- sanity checks the plot should satisfy ----
    print("\nSANITY CHECKS")
    for c in cells:
        cv = dual_curve(c, a.size)
        if not cv:
            continue
        mono = all(cv[i][1] >= cv[i-1][1] for i in range(1, len(cv)))
        cross = next((t for t, b in cv if b > klb[c]), None)
        print(f"  {c}: {len(cv)} dual points, monotone={mono}, "
              f"final={cv[-1][1]:.1f} vs K {klb[c]:.1f}, "
              f"crosses at {f'{cross:.2f}s' if cross else 'never'}")


if __name__ == "__main__":
    main()
