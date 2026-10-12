"""THE PRIMAL SEARCH TARGET — the objective every configuration is ranked by.

AUTHOR SPECIFICATION, 2026-09-17:

    "best Beat K count and depth, shortest time to beat whenever measurable - both meanwise,
     smallest std as secondary, best BestOfAll as third"

read as a strict lexicographic hierarchy:

    1. BEAT-K COUNT   how many cells our MEAN beats K's best-known on
    2. BEAT-K DEPTH   by how much, on the mean
    3. TIME TO TIE-OR-BEAT  how fast, on the mean, on the cells that achieve it
    4. SD             consistency, secondary
    5. BEST-OF-ALL    the portfolio statistic, third and last

MEANWISE IS THE WHOLE POINT, and it is what makes 1-3 different from what we used to report.
`decision 66` demoted best-of because a best-of grows with compute and therefore compares our
BUDGET with K's ALGORITHM. This target keeps best-of visible -- it is informative -- but ranks it
LAST, behind two statistics it cannot flatter.

WHY COUNT BEFORE DEPTH. A configuration that wins hugely on one cell and loses on twenty is worth
less to this paper than one that wins narrowly on twelve: K's incumbents are quasi-optimal (median
spread 0.99%, standing), so depth is bounded everywhere while count is not.

TIME-TO-BEAT IS CONDITIONAL AND ITS DENOMINATOR MUST TRAVEL WITH IT. It exists only on cells that
cross at all, so it is reported WITH the never-crossed count, never alone (decision 75). And it is
an ABSOLUTE time, never a ratio -- RT_COMPARABILITY leaves O1/O2/O3 open and marks a bare
"N times faster" indefensible (decision 74).

THE COMPARATOR IS min(joint_bk, lbbd_bk), the rule settled in AUDIT_comparator_asymmetry
(decision 1): K's reference is a MIN over their two methods because they are incumbents.

Usage:  python analysis/primal_target.py --size 20 [--variant cal_baseline]
"""
import argparse, collections, glob, json, os, re, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
import analysis.manuscript_numbers as M                      # noqa: E402


DEADBAND = 0.05     # K publish BK to 1 dp; a "win" below this is not a win (s2_close.py:73)


def is_proved(cell, size):
    """K PROVED optimality here, so the best attainable outcome is a TIE, never a beat.

    Counting a proven cell in the beat-K denominator is a structural error: the optimum cannot be
    beaten, and a "win" there is a floating-point artifact or an invalid solution. The first
    version of this file made exactly that mistake -- C206 (proven) appeared among the beats at
    -0.0%. `analysis/s2_close.py` had solved this already with is_proved/proved_as_tie/DEADBAND
    and was not consulted.
    """
    r = M._K()["table3"]["per_instance"].get(str(size), {}).get(cell)
    return bool(r) and abs(r["joint_gap"]) < 1e-9


def k_bk(cell, size):
    r = M._K()["table3"]["per_instance"].get(str(size), {}).get(cell)
    return None if not r else min(r["joint_bk"], r.get("lbbd_bk", r["joint_bk"]))


def runs_for(size, variant=None):
    """cell -> list of (final_incumbent, first_cross_time_or_None)."""
    out = collections.defaultdict(list)
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_*_n%d_*.jsonl" % size)):
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n\d+_s\d+_(.+?)_\d+\.jsonl$", os.path.basename(f))
        if not m:
            continue
        cell, var = m.group(1), m.group(2)
        if variant and var != variant:
            continue
        kb = k_bk(cell, size)
        if kb is None:
            continue
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        pts = [(r.get("wall_s"), r.get("best_incumbent")) for r in rows
               if isinstance(r.get("wall_s"), (int, float))
               and isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0]
        if not pts:
            continue
        final = min(o for _, o in pts)
        # TIME TO TIE-OR-BEAT (author, 2026-09-17): the threshold is reaching K's published
        # value within its own rounding, not strictly bettering it. This makes term 3 consistent
        # with term 1, which counts BEAT+TIE cells -- previously term 1 counted ties and term 3
        # ignored them, so the hierarchy measured two different achievements.
        hit = [w for w, o in pts if o <= kb + DEADBAND]
        wall = max(w for w, _ in pts)
        out[cell].append((final, min(hit) if hit else None, wall))
    return out


def score(size, variant=None):
    """The five-level target, computed from banked runs."""
    R = runs_for(size, variant)
    per, beat, depth, ttb, sds, bests = [], 0, [], [], [], []
    never, proven_ties, proven_n, unproven_n = [], 0, 0, 0
    tie_count, proven_beats = 0, 0
    ttb_runs, ttb_beat_no_cross = [], []
    for cell in sorted(R):
        kb = k_bk(cell, size)
        objs = [o for o, _, _ in R[cell]]
        if len(objs) < 2:
            continue
        mu, sd, bo = st.mean(objs), st.stdev(objs), min(objs)
        d_mean = 100.0 * (mu - kb) / kb          # negative = we beat K on the mean
        d_best = 100.0 * (bo - kb) / kb
        crossed = [t for _, t, _ in R[cell] if t is not None]
        agg_rt = sum(w for _, _, w in R[cell])
        max_run_rt = max(w for _, _, w in R[cell])
        # THREE-WAY CLASSIFICATION, ALL OUTSIDE THE ROUNDING ERROR (author, 2026-09-17).
        # K publish BK to 1 dp, so anything inside +/-DEADBAND is indistinguishable at their
        # printed precision and is a TIE, not a win and not a loss. A TIE counts as a success on
        # EVERY cell, not only proven ones: matching their best-known is a real outcome, and on a
        # PROVEN cell it is the ceiling -- nothing better exists.
        if mu < kb - DEADBAND:
            outcome = "BEAT"
        elif mu <= kb + DEADBAND:
            outcome = "TIE"
        else:
            outcome = "LOSE"
        wins = outcome == "BEAT"
        ties = outcome == "TIE"
        beat += wins
        tie_count += ties
        if is_proved(cell, size):
            proven_n += 1
            proven_ties += bool(ties)
            proven_beats += bool(wins)
        else:
            unproven_n += 1
        depth.append(d_mean)
        sds.append(100.0 * sd / kb)
        bests.append(d_best)
        # TIME-TO-BEAT EXISTS ONLY ON CELLS WE ACTUALLY BEAT (author, 2026-09-17).
        # Averaging over every cell where SOME run transiently crossed measures
        # time-to-transient-crossing, which is a different and flattering quantity: on a cell
        # whose MEAN loses, there is no time at which we beat K. DEPTH, by contrast, is over ALL
        # cells including losses -- restricting depth to wins would make it a selected statistic.
        if outcome in ("BEAT", "TIE"):
            if crossed:
                ttb.append(st.mean(crossed))
                ttb_runs.append((len(crossed), len(R[cell])))
            else:
                ttb_beat_no_cross.append(cell)
        if not crossed:
            never.append(cell)
        per.append(dict(cell=cell, n=len(objs), mean=mu, sd=sd, k=kb,
                        mean_dpc=d_mean, sd_pct=100.0 * sd / kb, best_dpc=d_best,
                        outcome=outcome, beats=bool(wins), ties=bool(ties),
                        proved=is_proved(cell, size),
                        mean_ttb=st.mean(crossed) if crossed else None,
                        crossed_runs=len(crossed), agg_rt_s=agg_rt,
                        max_run_rt_s=max_run_rt))
    return dict(size=size, variant=variant, cells=len(per), per_cell=per,
                t1_beat_count=beat,
                t2_beat_depth_median=st.median(depth) if depth else None,
                t3_ttb_mean_s=st.mean(ttb) if ttb else None,
                t3_ttb_cells=len(ttb), t3_never=never,
                t3_runs_crossing=sum(a for a, _ in ttb_runs),
                t3_runs_total=sum(b for _, b in ttb_runs),
                t3_beat_but_no_cross=ttb_beat_no_cross,
                t4_sd_median_pct=st.median(sds) if sds else None,
                t1_denominator_unproven=unproven_n,
                t1_tie_count=tie_count, t1_beat_or_tie=beat + tie_count,
                proven_beats=proven_beats,
                proven_cells=proven_n, proven_ties=proven_ties,
                t5_bestofall_median=st.median(bests) if bests else None,
                t5_agg_rt_median_s=st.median([p["agg_rt_s"] for p in per]) if per else None,
                max_run_rt_s=max([p["max_run_rt_s"] for p in per]) if per else None,
                k_budget_s=14400.0)


def report(s):
    print("PRIMAL TARGET  |C| = %d%s   cells = %d"
          % (s["size"], ("  variant=%s" % s["variant"]) if s["variant"] else "", s["cells"]))
    print("  ranked lexicographically; 1-3 are MEANWISE, 5 is the demoted portfolio statistic\n")
    print("  1  BEAT / TIE COUNT, outside the rounding error (+/-%.2f, K publish to 1 dp)" % DEADBAND)
    print("       BEAT + TIE                           %d of %d cells"
          % (s["t1_beat_or_tie"], s["cells"]))
    print("         of which BEAT (mean < K - %.2f)    %d   (%d on UNPROVEN, %d on proven)"
          % (DEADBAND, s["t1_beat_count"], s["t1_beat_count"] - s["proven_beats"],
             s["proven_beats"]))
    print("         of which TIE  (within +/-%.2f)     %d   (%d on proven, where TIE is the ceiling)"
          % (DEADBAND, s["t1_tie_count"], s["proven_ties"]))
    print("       unproven cells (BEAT is possible)    %d" % s["t1_denominator_unproven"])
    print("       proven cells  (TIE is the ceiling)   %d" % s["proven_cells"])
    if s["proven_beats"]:
        print("       !! %d BEAT on a PROVEN cell -- impossible; check the solution or the comparator"
              % s["proven_beats"])
    print("  2  BEAT-K DEPTH   (median mean d%%)       %+.2f%%   negative = we are ahead"
          % s["t2_beat_depth_median"])
    print("  3  TIME TO TIE-OR-BEAT (mean, on BEAT+TIE cells) %s   on %d of %d such cells"
          % (("%.1f s" % s["t3_ttb_mean_s"]) if s["t3_ttb_mean_s"] else "n/a",
             s["t3_ttb_cells"], s["t1_beat_or_tie"]))
    print("       threshold: incumbent <= K + %.2f, i.e. reaching their published value" % DEADBAND)
    if s["t3_runs_total"]:
        print("       within those cells, %d of %d runs actually cross"
              % (s["t3_runs_crossing"], s["t3_runs_total"]))
    if s["t3_beat_but_no_cross"]:
        print("       !! BEAT/TIE on the mean but no run reached it: %s -- inspect"
              % ", ".join(s["t3_beat_but_no_cross"]))
    print("  4  SD             (median, %% of K)       %.2f%%" % s["t4_sd_median_pct"])
    agg, mx, K = s["t5_agg_rt_median_s"], s["max_run_rt_s"], s["k_budget_s"]
    print("  5  BEST-OF-ALL    (median best d%%)       %+.2f%%" % s["t5_bestofall_median"])
    print("")
    print("  BUDGET, and WHICH CONSTRAINT BINDS WHICH STATISTIC:")
    print("     a MEAN does not improve with more seeds, it becomes better ESTIMATED, so the")
    print("     budget binds PER RUN:      worst run %6.0f s = %3.0f%% of K's %.0f s   %s"
          % (mx, 100.0 * mx / K, K, "OK" if mx <= K else "OVER"))
    print("     a BEST-OF does improve with more seeds, so for it the AGGREGATE binds:")
    print("                                per cell %7.0f s = %3.0f%% of K's %.0f s   %s"
          % (agg, 100.0 * agg / K, K, "OK -- best-of quotable" if agg <= K
             else "OVER -- best-of NOT quotable at this size"))
    print("\n  never crossing: %s" % (", ".join(s["t3_never"]) if s["t3_never"] else "none"))
    print("  time-to-beat is an ABSOLUTE time, never a ratio (d74), and its denominator")
    print("  travels with it (d75). Best-of is ranked last because it grows with compute (d66).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20,30")
    ap.add_argument("--variant", default=None)
    ap.add_argument("--out", default="runs/primal_target.json")
    a = ap.parse_args()
    out = {}
    for size in [int(x) for x in a.sizes.split(",")]:
        s = score(size, a.variant)
        if s["cells"]:
            report(s)
            print()
            out[str(size)] = s
    json.dump(stamped(out, __file__), open(os.path.join(ROOT, a.out), "w"), indent=1, default=str)
    print("wrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
