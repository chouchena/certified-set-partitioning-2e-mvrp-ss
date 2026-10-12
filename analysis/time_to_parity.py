"""TIME TO PARITY — our dual time-to-tie PLUS our primal time-to-tie, against K's compounded RT.

THE AUTHOR'S CONSTRUCTION, 2026-09-17:

    "We still can show Time to Tie for both and compare their sum vs K compounded RT"

WHY THIS IS THE RIGHT INSTRUMENT, and better than any budget ratio. `RT_COMPARABILITY.md` §2.1
rejects a budget comparison because the DELIVERABLES differ: K's one clock buys a bound AND an
incumbent, ours are separated. Every "% of K's budget" figure therefore compares unlike things.

This compares LIKE with LIKE. It asks how long WE need to reach parity on BOTH of their published
outputs -- their bound and their incumbent -- and sets that against the time THEY spent producing
both. The separation of our budgets stops being a liability and becomes the measurement: we can
say what each half cost.

    ours   = t_dual(reach K's bound) + t_primal(reach K's incumbent)
    theirs = their compounded RT

TWO READINGS OF "THEIR COMPOUNDED RT", BOTH REPORTED because they answer different questions:
  * the LIMIT, 14,400 s -- what their method was allowed. Generous to us.
  * their published Inc.Time -- when they actually reached the incumbent they report. Harsher,
    and arguably the fairer number, since comparing our time-to-parity against a budget they may
    not have needed flatters us.
Neither is asserted as THE answer; a claim that survives both is a claim.

CENSORING IS DOUBLE HERE AND MUST TRAVEL WITH THE NUMBER. A cell contributes only if we reach
parity on BOTH legs. Cells where either leg never arrives are excluded and counted, exactly as the
single-leg version already requires (decision 75). The denominator is not optional.

PARITY IS TIE-OR-BEAT on both legs, at K's own published precision (DEADBAND, decision 127):
  dual   : our bound  >= K's derived LB - DEADBAND
  primal : our incumbent <= K's best-known + DEADBAND
"""
import collections, glob, json, os, re, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import analysis.manuscript_numbers as M                      # noqa: E402

DEADBAND = 0.05
K_LIMIT = 14400.0


def k_row(cell, size):
    return M._K()["table3"]["per_instance"].get(str(size), {}).get(cell)


def k_lb(cell, size):
    r = k_row(cell, size)
    return None if not r else r["joint_bk"] * (1 - r["joint_gap"] / 100.0)


def k_bk(cell, size):
    r = k_row(cell, size)
    return None if not r else min(r["joint_bk"], r.get("lbbd_bk", r["joint_bk"]))


def dual_time_to_parity(cell, size):
    """Earliest wall second at which our bound reaches K's derived LB, over descend records."""
    target = k_lb(cell, size)
    if target is None:
        return None
    best = None
    for pat in ("easy_reduction_descend_%s_n%d.json", "easy_reduction_%s_n%d.json"):
        p = os.path.join(ROOT, "crossfeed", pat % (cell, size))
        if not os.path.exists(p):
            continue
        try:
            recs = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for r in (recs if isinstance(recs, list) else [recs]):
            if not isinstance(r, dict):
                continue
            for t, v in (r.get("lb_curve") or []):
                if v >= target - DEADBAND:
                    best = t if best is None else min(best, t)
                    break
        break
    return best


def primal_time_to_parity(cell, size):
    """Mean over runs of the earliest wall second at which our incumbent reaches K's best-known."""
    target = k_bk(cell, size)
    if target is None:
        return None, 0, 0
    hits, total = [], 0
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_%s_n%d_*.jsonl" % (cell, size))):
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        pts = [(r.get("wall_s"), r.get("best_incumbent")) for r in rows
               if isinstance(r.get("wall_s"), (int, float))
               and isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0]
        if not pts:
            continue
        total += 1
        h = [w for w, o in pts if o <= target + DEADBAND]
        if h:
            hits.append(min(h))
    return (st.mean(hits) if hits else None), len(hits), total


def main():
    for size in (20, 30):
        cells = sorted(M._cells(size))
        rows, miss_dual, miss_primal = [], [], []
        for c in cells:
            if k_row(c, size) is None:
                continue
            td = dual_time_to_parity(c, size)
            tp, nh, nt = primal_time_to_parity(c, size)
            if td is None:
                miss_dual.append(c)
            if tp is None:
                miss_primal.append(c)
            if td is not None and tp is not None:
                r = k_row(c, size)
                rows.append(dict(cell=c, t_dual=td, t_primal=tp, total=td + tp,
                                 runs_reaching=nh, runs=nt,
                                 k_joint_inct=r.get("joint_inc_time"),
                                 k_lbbd_inct=r.get("lbbd_inc_time")))
        if not rows:
            continue
        print("\n=== TIME TO PARITY, |C| = %d ===" % size)
        print("  parity = tie-or-beat within %.2f on BOTH legs" % DEADBAND)
        print("%-7s %10s %11s %11s | %11s %11s" %
              ("cell", "t_dual_s", "t_primal_s", "TOTAL_s", "K jointIncT", "K lbbdIncT"))
        for r in rows:
            print("%-7s %10.1f %11.1f %11.1f | %11s %11s" %
                  (r["cell"], r["t_dual"], r["t_primal"], r["total"],
                   r["k_joint_inct"], r["k_lbbd_inct"]))
        tot = [r["total"] for r in rows]
        kj = [r["k_joint_inct"] for r in rows if r["k_joint_inct"]]
        print("-" * 70)
        print("  cells reaching parity on BOTH legs : %d of %d" % (len(rows), len(cells)))
        print("  never reach parity: dual %d (%s), primal %d (%s)"
              % (len(miss_dual), ", ".join(miss_dual[:6]) or "none",
                 len(miss_primal), ", ".join(miss_primal[:6]) or "none"))
        print("  our TOTAL time to parity  : median %.1f s   (p90 %.1f s)"
              % (st.median(tot), sorted(tot)[int(0.9 * len(tot))]))
        print("  vs K's LIMIT      14400 s : %.1f%%" % (100.0 * st.median(tot) / K_LIMIT))
        if kj:
            print("  vs K's own joint IncT     : median %.0f s  ->  %.1f%%"
                  % (st.median(kj), 100.0 * st.median(tot) / st.median(kj)))
        print("\n  the denominator is not optional: this median is over the %d cells that reach"
              % len(rows))
        print("  parity on BOTH legs, and the cells that never do are counted above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
