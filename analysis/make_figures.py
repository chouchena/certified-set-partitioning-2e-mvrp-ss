"""Build the manuscript's result figures from banked artifacts. No solver runs.

Build order follows paper/SKELETON.md Part 7c: F2 and F4 first, because they carry the central
claim and its mechanism and are pure replays of existing artifacts.

  F2  Closed share of K's closable gap vs |C|, one line per family.
      THE CENTRAL RESULT *and its honest decline*. Reported on the PORTFOLIO bound
      max(MILP, AB), which is what the manuscript reports; the MILP-only series is drawn
      faintly behind it so the reader can see what the arithmetic bound contributes.

  F4  Deepest PROVEN retained fraction |H|/|C| vs |C|.
      THE MECHANISM behind F2's decline: the bound falls away with size because the retained
      set must be truncated further to stay certifiable, not because the relaxation loosens.

AGGREGATION. Closed share is computed as sum(ours - K_LB) / sum(K_BK - K_LB) WITHIN a family,
never as a mean of per-cell ratios. Per-cell ratios have a vanishing denominator wherever K's
gap is small, which SKELETON Part 7c explicitly warns against.

K REFERENCE BASIS, and it is not uniform -- stated on the figure rather than hidden:
  n10       K prove every cell, so the closable gap is ZERO and the metric is undefined. Omitted.
  n20, n30  per-instance (their Table 3)
  n50       POOLED over all 27 cells (their Table 4 reports by WLS and method, not by family)
  n100      per family (their Table 6)
"""
import os, sys, json, glob, collections
import statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib.pyplot as plt
import figstyle as F
import lb_estimator

ROOT = F.ROOT
K = json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))
AB = {(r["cell"], r["size"]): r.get("ab4")
      for r in json.load(open(os.path.join(ROOT, "runs/ab4_grid_results.json"))).values()}


def cells_at(size):
    out = []
    for f in glob.glob(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_*_n{size}.json")):
        b = os.path.basename(f)
        if any(x in b for x in ("noprov", "kcapbug", "tl450", "detl")):
            continue
        out.append(b.split("descend_")[1].split(f"_n{size}")[0])
    return sorted(set(out))


def frontier(cell, size):
    """(bound, nH, certifies). ONE rule at every size -- see analysis/lb_estimator.py.

    The bound is the strongest REPRODUCIBLE valid lower bound, not the proven record at the
    smallest k. `certifies` means the cell proves its relaxation somewhere. For the proved
    frontier itself call `proved_frontier` below -- a different quantity, asked for by name.
    """
    r = json.load(open(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{cell}_n{size}.json")))
    b = lb_estimator.cell_bound(r, reproducible_only=True)
    rec = lb_estimator.bound_record(r, reproducible_only=True)
    if b is None:
        raise AssertionError(f"{cell}/n{size}: no reproducible record supplies a bound")
    return b, (rec or {}).get("nH"), lb_estimator.certifies(r)


def proved_frontier(cell, size):
    """(k, nH, certifies) at the smallest PROVEN k. The method's own headline quantity."""
    r = json.load(open(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{cell}_n{size}.json")))
    return lb_estimator.frontier(r)


def portfolio(cell, size):
    m, _, _ = frontier(cell, size)
    return max(m, AB.get((cell, size)) or 0), m


# --------------------------------------------------------------------------- F2
def f2():
    series = collections.defaultdict(list)      # family -> [(size, closed%_portfolio, closed%_milp)]
    pooled = []
    for size in (20, 30):
        per = K["table3"]["per_instance"][str(size)]
        agg = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for c in sorted(per):
            # Cells the exact method SOLVES are excluded, and not as a convenience. There the
            # published gap is zero, so the closable gap is zero: such a cell contributes
            # nothing to the denominator and a NEGATIVE amount to the numerator, because a
            # valid dual bound cannot exceed an optimum. It can only depress the share.
            # |C| = 10 was already dropped from this metric on exactly that argument; this
            # generalises it to the 7 solved cells at |C| = 20 and the 1 at |C| = 30, worth
            # 0.9-4.9 pp. See analysis/reference_set_audit.py, which quantifies it.
            if per[c]["joint_gap"] == 0.0:
                continue
            bk = per[c]["joint_bk"]
            klb = bk * (1 - per[c]["joint_gap"] / 100.0)
            p, m = portfolio(c, size)
            a = agg[F.family_of(c)]
            a[0] += p; a[1] += klb; a[2] += bk; a[3] += m
        for fam, (p, l, b, m) in agg.items():
            if b > l:
                series[fam].append((size, 100 * (p - l) / (b - l), 100 * (m - l) / (b - l)))

    # n50: K report pooled, so we can only place one pooled point. Said so on the figure.
    j = [r for r in K["table4"] if r["size"] == 50 and r["wls"] == "1:10" and r["method"] == "Joint"][0]
    cs = cells_at(50)
    bk, klb = j["bk"] * len(cs), j["bk"] * (1 - j["gap_imp"] / 100.0) * len(cs)
    p = sum(portfolio(c, 50)[0] for c in cs)
    pooled.append((50, 100 * (p - klb) / (bk - klb)))

    for fam, v in K["table6"].items():
        cs = [c for c in cells_at(100) if F.family_of(c) == fam]
        n = len(cs)
        bk, klb = v["joint"]["zIP"] * n, v["joint"]["zIP"] * (1 - v["gap_joint"] / 100.0) * n
        p = sum(portfolio(c, 100)[0] for c in cs)
        m = sum(portfolio(c, 100)[1] for c in cs)
        series[fam].append((100, 100 * (p - klb) / (bk - klb), 100 * (m - klb) / (bk - klb)))

    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    ax.axhline(0, color=F.GREY, lw=0.7, ls=(0, (4, 3)), zorder=1)
    for fam in ("C", "R", "RC"):
        pts = sorted(series[fam])
        xs = [p[0] for p in pts]
        # Restriction bound alone. IN THE FAMILY COLOUR, lightened -- drawn in a single grey
        # (as it was until 2026-09-15) three dashed lines are indistinguishable, so a reader
        # can see that a gap opens but not which family it opens for. That is the whole
        # content of this series.
        ax.plot(xs, [p[2] for p in pts], color=F.FAMILY[fam], lw=1.0, ls=(0, (2, 2)),
                alpha=0.45, zorder=2)
        ax.plot(xs, [p[1] for p in pts], color=F.FAMILY[fam], marker=F.MARKER[fam], zorder=4)
        ax.annotate(fam, (xs[-1], pts[-1][1]), textcoords="offset points",
                    xytext=(7, -2), color=F.FAMILY[fam], fontweight="bold")
    ax.plot([pooled[0][0]], [pooled[0][1]], marker="D", ms=5.5, mfc="white",
            mec=F.GREY, mew=1.2, ls="none", zorder=5)
    # Leader line into clear space, rather than text sitting on top of the R series.
    ax.annotate("pooled over all 27 cells\n(the published study reports\n$|C|=50$ by cost ratio,\nnot by family)",
                xy=(pooled[0][0], pooled[0][1]), xycoords="data",
                xytext=(21.5, 20), textcoords="data", ha="left", va="top",
                color=F.GREY, fontsize=7,
                arrowprops=dict(arrowstyle="-", color=F.GREY, lw=0.6,
                                shrinkA=2, shrinkB=4))
    ax.set_xscale("log")
    ax.set_xticks([20, 30, 50, 100])
    ax.set_xticklabels(["20", "30", "50", "100"])
    ax.set_xticks([], minor=True)          # suppress 4x10^1 / 6x10^1 leaking through
    ax.set_xlim(17, 132)
    ax.set_ylim(-6, 80)
    ax.set_xlabel("number of customers  |C|")
    ax.set_ylabel("share of the published optimality gap closed  (%)")
    # One legend entry only: families are labelled directly at the line ends.
    ax.plot([], [], color=F.GREY, lw=1.0, ls=(0, (2, 2)), alpha=0.6,
            label="dashed, family colour: restriction bound alone")
    ax.legend(loc="upper right", handlelength=2.2, borderpad=0.2)
    return F.save(fig, "F2_closed_share_vs_size",
                  sources=["crossfeed/easy_reduction_descend_*_n{20,30,50,100}.json",
                           "runs/ab4_grid_results.json", "data/karademir2025/k_reference.json"])


# --------------------------------------------------------------------------- F4
def f4():
    fig, ax = plt.subplots(figsize=(5.0, 3.3))
    for fam in ("C", "R", "RC"):
        xs, ys = [], []
        for size in (10, 20, 30, 50, 100):
            # THE PROVED FRONTIER, ASKED FOR BY NAME. This panel plots how large a retained set
            # the descent can PROVE, so it wants the proven record's nH -- not the nH of whichever
            # record happened to supply the strongest bound. Before 2026-09-16 one function served
            # both and the distinction was invisible here.
            fr = [proved_frontier(c, size) for c in cells_at(size) if F.family_of(c) == fam]
            fr = [f for f in fr if f[2] and f[1]]
            if not fr:
                continue
            xs.append(size)
            ys.append(100 * sum(f[1] for f in fr) / (len(fr) * size))
        ax.plot(xs, ys, color=F.FAMILY[fam], marker=F.MARKER[fam], zorder=4)
        if xs:
            ax.annotate(fam, (xs[-1], ys[-1]), textcoords="offset points",
                        xytext=(6, -1), color=F.FAMILY[fam], fontweight="bold")
    ax.axhline(100, color=F.GREY, lw=0.7, ls=(0, (4, 3)))
    ax.annotate("full instance retained", (11, 100), textcoords="offset points",
                xytext=(0, 4), color=F.GREY, fontsize=7)
    ax.set_xscale("log")
    ax.set_xticks([10, 20, 30, 50, 100])
    ax.set_xticklabels(["10", "20", "30", "50", "100"])
    ax.set_xticks([], minor=True)
    ax.set_xlim(9, 132)
    ax.set_ylim(0, 116)
    ax.set_xlabel("number of customers  |C|")
    # Families are labelled directly at the line ends, so no legend.
    # The fuller phrasing "retained fraction at the proven frontier, |H|/|C| (%)" overflowed
    # the axes and clipped its own "(%)". The qualifier belongs in the caption.
    ax.set_ylabel("retained fraction  $|H|/|C|$   (%)")
    return F.save(fig, "F4_retained_fraction_vs_size",
                  sources=["crossfeed/easy_reduction_descend_*_n{10,20,30,50,100}.json"])


# --------------------------------------------------------------------------- F1
def f1(size=20):
    """Anytime dual bound against wall time, normalised by K's published dual bound.

    NORMALISATION IS WHAT MAKES THIS READABLE. Cells differ by a factor of two in objective
    scale, so raw bounds do not overlay. Dividing by K's derived dual bound puts every cell on
    one axis and turns the reference into a single line at 1.0 -- the level K reach after their
    full run. Crossing it means our bound has overtaken theirs on that cell.

    RUNNING MAXIMUM, not the raw trace. Every recorded value is a VALID dual bound, and each
    new k restarts CPLEX's dual from a low value, so the raw concatenation saw-tooths downward.
    The best-so-far is the quantity that is actually available to a user at time t.

    NO SPEED CLAIM IS MADE OR IMPLIED. The x-axis is our own wall time on our own hardware
    against a published *level*, not against their time. Their runtimes are on different
    hardware and a different solver stack; see validation/RT_COMPARABILITY.md. The absolute
    time-to-reach statistic used here is metric M5, which that document clears as safe; no
    ratio is formed, which is the part that remains an open decision.

    CELLS PROVED OPTIMAL ARE DRAWN BUT NOT COUNTED, and this is not a cosmetic choice.
    A valid dual bound cannot exceed an optimum, so on a proved cell the ratio is bounded
    above by 1.0 BY CONSTRUCTION -- those curves can never cross, however good the method is.
    Counting them in the denominator turned 19 of 20 into 19 of 27 and made the figure
    understate its own result by 25 points; it also contradicted the registered number
    `lb-unproven-wins` without saying so. Separately, RT_COMPARABILITY.md section 6 forbids
    any speed claim on cells the exact method proves, so counting them was doubly wrong.
    They stay ON the figure, in grey, because hiding data to improve a statistic is the
    other way to get this wrong.
    """
    per = K["table3"]["per_instance"][str(size)]
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.9), sharey=True, sharex=True)
    for ax, fam in zip(axes, ("C", "R", "RC")):
        cross, n_open, n_proved = [], 0, 0
        for c in [x for x in cells_at(size) if F.family_of(x) == fam]:
            recs = json.load(open(os.path.join(
                ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json")))
            proved = per[c]["joint_gap"] == 0.0
            klb = per[c]["joint_bk"] * (1 - per[c]["joint_gap"] / 100.0)
            ts, ys, best = [], [], 0.0
            for rec in sorted(recs, key=lambda r: -r["k"]):
                for t, b in (rec.get("lb_curve") or []):
                    if b > best:
                        best = b
                    ts.append(max(t, 1e-3)); ys.append(best / klb)
            if not ts:
                continue
            if proved:
                n_proved += 1
                ax.plot(ts, ys, color=F.LIGHT, lw=0.7, alpha=0.9, zorder=2,
                        solid_joinstyle="round")
                continue
            n_open += 1
            ax.plot(ts, ys, color=F.FAMILY[fam], lw=0.7, alpha=0.45, zorder=3,
                    solid_joinstyle="round")
            hit = next((t for t, y in zip(ts, ys) if y >= 1.0), None)
            if hit:
                cross.append(hit)
        ax.axhline(1.0, color=F.GREY, lw=0.9, ls=(0, (4, 3)), zorder=5)
        ax.set_xscale("log")
        ax.set_title(fam, color=F.FAMILY[fam], fontweight="bold", pad=3)
        ax.set_xlabel("wall time (s)")
        if cross:
            cross.sort()
            med = st.median(cross)
            ax.plot([med], [1.0], marker="v", ms=5, color=F.GREY, ls="none", zorder=6)
            # "0 s" would be an artifact of the 1e-3 clamp on the first curve point.
            lab = "<0.1 s" if med < 0.1 else (f"{med:.1f} s" if med < 10 else f"{med:.0f} s")
            note = f"{len(cross)} of {n_open} unsolved cells overtake\nmedian at {lab}"
            if n_proved:
                note += f"\n{n_proved} solved cell{'s' if n_proved > 1 else ''} in grey"
            ax.annotate(note, xy=(0.04, 0.04), xycoords="axes fraction",
                        fontsize=6.5, color=F.GREY, ha="left", va="bottom")
    axes[0].set_ylabel("dual bound  /  published dual bound")
    axes[0].annotate("published dual bound", xy=(0.02, 1.0), xycoords=("axes fraction", "data"),
                     textcoords="offset points", xytext=(0, 6), fontsize=6.5, color=F.GREY)
    fig.subplots_adjust(wspace=0.08)
    return F.save(fig, f"F1_anytime_dual_n{size}",
                  sources=[f"crossfeed/easy_reduction_descend_*_n{size}.json (lb_curve)",
                           "data/karademir2025/k_reference.json (table3.per_instance)"])


# --------------------------------------------------------------------------- F5
def f5():
    """AB / MILP per cell and size. Above 1.0 the arithmetic bound carries the reported value.

    THE POINT IS THAT THE CROSSOVER IS PER-CELL, NOT PER-FAMILY. A family-mean would show a
    clean switch at n=100 and hide that individual instances cross much earlier while others
    never do. Plotting every cell is what makes that visible.
    """
    import numpy as np
    import statistics as _st
    sizes = [10, 20, 30, 50, 100]
    fams = ("C", "R", "RC")
    # FAMILIES ARE DODGED, NOT JITTERED. Random horizontal noise was hiding the one pattern
    # a reader asks about: R sits systematically above RC at every size (EXHIBIT_READINGS,
    # F5's open question). A fixed offset per family makes that directly comparable, and the
    # small residual jitter only separates coincident points WITHIN a family.
    DODGE = {f: d for f, d in zip(fams, (-0.22, 0.0, 0.22))}
    fig, ax = plt.subplots(figsize=(5.8, 3.5))
    rng = np.random.default_rng(20260915)          # seeded, so the figure is stable
    counts, byfam = {}, collections.defaultdict(list)
    for si, size in enumerate(sizes):
        above = 0
        for c in cells_at(size):
            ab = AB.get((c, size))
            m, _, _ = frontier(c, size)
            if not ab or not m:
                continue
            r = ab / m
            fam = F.family_of(c)
            above += r > 1.0
            byfam[(size, fam)].append(r)
            ax.plot([si + DODGE[fam] + rng.uniform(-0.055, 0.055)], [r],
                    marker=F.MARKER[fam], ms=3.6, mfc=F.FAMILY[fam], mec="white", mew=0.4,
                    ls="none", alpha=0.9, zorder=4)
        counts[size] = above
    # A median rule per family, so the family tendency is readable WITHOUT hiding the spread
    # that carries this figure's actual claim -- that the crossover is per cell, not per family.
    for si, size in enumerate(sizes):
        for fam in fams:
            v = byfam.get((size, fam))
            if not v:
                continue
            ax.plot([si + DODGE[fam] - 0.085, si + DODGE[fam] + 0.085],
                    [_st.median(v)] * 2, color=F.FAMILY[fam], lw=1.6, solid_capstyle="round",
                    alpha=0.85, zorder=6)
    ax.axhline(1.0, color=F.GREY, lw=0.9, ls=(0, (4, 3)), zorder=5)
    ax.set_yscale("log")
    ax.set_ylim(0.28, 3.4)
    ax.set_yticks([0.4, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0])
    ax.set_yticklabels(["0.4", "0.5", "0.7", "1.0", "1.5", "2.0", "3.0"])
    ax.set_yticks([], minor=True)
    ax.set_xticks(range(len(sizes)))
    ax.set_xticklabels([str(s) for s in sizes])
    ax.set_xlim(-0.5, len(sizes) - 0.5)
    ax.set_xlabel("number of customers  |C|")
    ax.set_ylabel("arithmetic bound  /  restriction bound")
    for si, size in enumerate(sizes):
        ax.annotate(f"{counts[size]}/27", xy=(si, 0.97), xycoords=("data", "axes fraction"),
                    ha="center", va="top", fontsize=7, color=F.GREY,
                    fontweight="bold" if counts[size] else "normal")
    ax.annotate("arithmetic bound carries", xy=(0.02, 1.0), xycoords=("axes fraction", "data"),
                textcoords="offset points", xytext=(0, 5), fontsize=6.5, color=F.GREY)
    for fam in fams:
        ax.plot([], [], marker=F.MARKER[fam], ls="none", ms=4, color=F.FAMILY[fam], label=fam)
    ax.plot([], [], color=F.GREY, lw=1.6, label="family median")
    ax.legend(loc="lower right", handlelength=1.2, ncol=4, columnspacing=0.9,
              handletextpad=0.4)
    return F.save(fig, "F5_ab_vs_restriction_crossover",
                  sources=["crossfeed/easy_reduction_descend_*.json", "runs/ab4_grid_results.json"])


# --------------------------------------------------------------------------- F3
# Arm colours are deliberately OUTSIDE the family palette: the series here are selection
# ARMS, not instance families, and reusing the family hues would imply a link that is not
# there. This pair is colour-blind safe and separates by lightness in greyscale.
ARM_STYLE = {"random":  ("#7b3294", "o", "random retention"),
             "reverse": ("#e66101", "D", "reverse easiness")}


def f3(size=20):
    """S3a ablation -- does the scarcity-weighted easiness ordering earn its place?

    ONE CLAIM: at the certified frontier the easiness ordering gives a stronger bound than
    either alternative on most cells, and the effect survives controlling for depth.

    Both panels plot ARM / EASINESS, so a point BELOW 1 means the banked ordering is stronger.
      (a) the PRE-REGISTERED PRIMARY measure: the bound at each arm's own certified frontier.
      (b) the pre-registered SECONDARY: the bound at the smallest k BOTH arms prove. This
          separates BOUND QUALITY from REACH -- if (b) looked like a wash, (a) would only be
          telling us the easiness arm descends further, which is a different claim.

    Cells whose BANKED descent reaches k = 0 are excluded: there H is the whole customer set
    and every arm returns the same bound by construction. That is the pre-registered
    denominator, not a post-hoc filter (validation/PREREG_S3a_bound_selection_ablation.md).

    Definitions are IMPORTED from analysis/s3a_ablation_compare.py so this figure and the
    ablation verdict agree BY CONSTRUCTION -- the same discipline as T1 against F2.
    """
    from s3a_ablation_compare import load, summarise, CELLS, EPS

    base = {c: summarise(load(os.path.join(
        ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json"))) for c in CELLS}
    arms = {}
    for a in ARM_STYLE:
        arms[a] = {c: summarise(load(os.path.join(
            ROOT, f"crossfeed/ablation_{a}_{c}_n{size}.json"))) for c in CELLS}

    keep = [c for c in CELLS
            if base[c] and base[c]["frontier"] is not None and base[c]["frontier_k"] != 0
            and all(arms[a][c] is not None for a in ARM_STYLE)]

    rows = {}
    for c in keep:
        b = base[c]
        rows[c] = {}
        for a in ARM_STYLE:
            s = arms[a][c]
            fr = (s["frontier"] / b["frontier"]) if s["frontier"] is not None else None
            mk = sorted(set(b["proven_at"]) & set(s["proven_at"]))
            mkr = (s["proven_at"][mk[0]] / b["proven_at"][mk[0]]) if mk else None
            rows[c][a] = dict(frontier=fr, matched=mkr, k=mk[0] if mk else None)

    def mean_fr(c):
        v = [rows[c][a]["frontier"] for a in ARM_STYLE if rows[c][a]["frontier"] is not None]
        return sum(v) / len(v) if v else 99.0

    order = sorted(keep, key=mean_fr)
    y = {c: i for i, c in enumerate(order)}

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 0.23 * len(order) + 2.0),
                             sharey=True, sharex=True)
    panels = [("frontier", "(a)  at each arm's certified frontier",
               r"$\times$  arm certified no $k$"),
              ("matched", "(b)  at matched $k$  (depth controlled)",
               r"$\times$  no certified $k$ in common")]

    allv = [rows[c][a][k] for c in order for a in ARM_STYLE
            for k in ("frontier", "matched") if rows[c][a][k] is not None]
    hi, lo = max(allv + [1.0]), min(allv + [1.0])
    pad = 0.06 * max(hi - lo, 0.02)
    base_pt = plt.rcParams["font.size"]

    for ax, (key, title, xnote) in zip(axes, panels):
        # No fill: almost every point lies below 1, so shading that side would colour the
        # panel rather than direct the eye. The rule line plus one directional cue is enough.
        ax.axvline(1.0, color=F.GREY, lw=0.9, zorder=2)
        for c in order:
            pts = [rows[c][a][key] for a in ARM_STYLE if rows[c][a][key] is not None]
            if len(pts) > 1:                       # connector, so the pair reads as one cell
                ax.plot([min(pts), max(pts)], [y[c], y[c]], color=F.LIGHT, lw=1.1, zorder=1)

        miss = False
        for i, (a, (col, mk, lab)) in enumerate(ARM_STYLE.items()):
            xs = [rows[c][a][key] for c in order if rows[c][a][key] is not None]
            ys = [y[c] for c in order if rows[c][a][key] is not None]
            ax.scatter(xs, ys, s=22, marker=mk, facecolor=col, edgecolor="white",
                       linewidth=0.5, zorder=3, label=lab if ax is axes[0] else None)
            # An absent point is a REAL difference -- the arm certified nothing comparable --
            # not a gap in the data, so it is drawn rather than dropped.
            for c in order:
                if rows[c][a][key] is None:
                    miss = True
                    ax.plot(hi + pad, y[c], marker="x", color=col, ms=5, mew=1.2,
                            zorder=3, clip_on=False)
            w = sum(1 for v in xs if v < 1.0 - EPS)
            ax.text(0.985, 0.995 - i * 0.032, f"{lab}: {w}/{len(xs)} weaker",
                    transform=ax.transAxes, ha="right", va="top", color=col,
                    fontsize=base_pt - 1.5)

        ax.set_title(title, fontsize=base_pt, loc="left", pad=6)
        ax.set_xlabel("bound ratio   arm / easiness")
        ax.grid(axis="y", visible=False)
        if miss:
            ax.text(0.985, 0.012, xnote, transform=ax.transAxes, ha="right", va="bottom",
                    color=F.GREY, fontsize=base_pt - 1.5)

    ax0 = axes[0]
    ax0.set_xlim(lo - pad, hi + pad)
    ax0.set_yticks(range(len(order)))
    ax0.set_yticklabels(order)
    for t in ax0.get_yticklabels():                # tick colour carries the family, as in F2
        t.set_color(F.FAMILY[F.family_of(t.get_text())])
    ax0.set_ylim(-0.7, len(order) - 0.3)
    ax0.invert_yaxis()
    ax0.annotate(r"$\leftarrow$ easiness ordering stronger", xy=(0.015, 0.012),
                 xycoords="axes fraction", ha="left", va="bottom", color=F.GREY,
                 fontsize=base_pt - 1.5)
    fig.legend(loc="upper left", bbox_to_anchor=(0.085, 1.0), ncol=2, frameon=False,
               fontsize=base_pt - 1, handletextpad=0.35, columnspacing=1.4)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return F.save(fig, f"F3_selection_ablation_n{size}",
                  ["crossfeed/easy_reduction_descend_*_n%d.json" % size,
                   "crossfeed/ablation_{random,reverse}_*_n%d.json" % size,
                   "validation/PREREG_S3a_bound_selection_ablation.md"])


if __name__ == "__main__":
    name = F.apply()
    print(f"font: {name}")
    which = sys.argv[1:] or ["f1", "f2", "f3", "f4", "f5"]
    if "f1" in which:
        print("F1 anytime dual bound"); f1()
    if "f2" in which:
        print("F2 closed share vs size"); f2()
    if "f3" in which:
        print("F3 selection ablation"); f3()
    if "f4" in which:
        print("F4 retained fraction vs size"); f4()
    if "f5" in which:
        print("F5 AB vs restriction crossover"); f5()
