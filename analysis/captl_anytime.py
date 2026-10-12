"""Adversary finding #3: cap-TL has been judged ONLY on final OV at 2400s, but the paper's
primal claim is RT-domination (time-to-good), not OV-at-budget. This recomputes the paired
comparison as an ANYTIME profile from traces already on disk -- no new compute (capture-
everything: traces are the source of truth).

Reports, per (cell,seed): OV at a time grid, and t_cross = the wall-clock at which cap-TL
first reaches the baseline's FINAL 2400s objective (the RT-domination question: does cap-TL
get to baseline-final quality in a fraction of the time, even when final OV ties?)."""
import json, os, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID = [300, 600, 900, 1200, 1500, 1800, 2100, 2400]
PAIRS = {  # (cell, seed): (baseline_run_id_stamp, captl_run_id_stamp)  -- banked baseline
    ("R203", 0): (1788863481, 1788878689), ("R203", 1): (1788865884, 1788881093),
    ("R203", 2): (1788868286, 1788883495), ("R211", 0): (1788863491, 1788878697),
    ("R211", 1): (1788865894, 1788881101), ("R211", 2): (1788868295, 1788883503),
}


def curve(cell, seed, variant, stamp):
    """-> sorted [(wall_s, best_so_far)] monotone incumbent trace."""
    p = os.path.join(ROOT, "runs", f"fixopt_{cell}_n30_s{seed}_cal_{variant}_{stamp}.jsonl")
    pts, best = [], None
    for l in open(p, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        inc = r.get("best_incumbent") if r.get("best_incumbent") is not None else r.get("incumbent")
        w = r.get("wall_s")
        if isinstance(inc, (int, float)) and isinstance(w, (int, float)):
            if best is None or inc < best:
                best = inc
                pts.append((w, best))
    return pts


def at(pts, t):
    v = None
    for w, b in pts:
        if w <= t:
            v = b
        else:
            break
    return v


def t_reach(pts, target):
    """first wall_s at which the curve is <= target; None if never."""
    for w, b in pts:
        if b <= target + 1e-9:
            return w
    return None


def main():
    print("=== cap-TL ANYTIME (paired, from disk) ===")
    print("t_cross = when cap-TL first reaches BASELINE'S FINAL OV; ratio = t_cross / 2400\n")
    ratios = []
    for (cell, seed), (bs, cs) in sorted(PAIRS.items()):
        bp = curve(cell, seed, "baseline", bs)
        cp = curve(cell, seed, "captl", cs)
        bfin, cfin = bp[-1][1], cp[-1][1]
        tc = t_reach(cp, bfin)
        tb = t_reach(bp, cfin)
        r = f"{tc/2400:.2f}" if tc else "never"
        if tc:
            ratios.append(tc / 2400)
        print(f"{cell} s{seed}: base_final={bfin:.1f} captl_final={cfin:.1f}")
        print(f"   captl reaches base-final at t={tc if tc else float('nan'):.0f}s (ratio {r})"
              f" | base reaches captl-final at t={tb if tb else float('nan'):.0f}s"
              if tc and tb else
              f"   captl reaches base-final at t={tc}s (ratio {r}) | base reaches captl-final: {tb}")
        row = "   OV@t "
        for t in GRID:
            bv, cv = at(bp, t), at(cp, t)
            if bv is None or cv is None:
                continue
            mark = "+" if cv < bv else ("=" if abs(cv - bv) < 1e-6 else "-")
            row += f"| {t}: {cv:.0f}v{bv:.0f}{mark} "
        print(row)
    if ratios:
        print(f"\nmean t_cross ratio = {st.mean(ratios):.2f} of budget (n={len(ratios)} of 6 crossed)")


if __name__ == "__main__":
    main()
