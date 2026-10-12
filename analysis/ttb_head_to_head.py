"""OUR (LB TTB + primal TTB) against THEIRS — same target, same machine, both methods.

AUTHOR, 2026-09-17: *"Alternatively or on top of it we can compare our (LB TTB + primal TTB) vs
theirs."*

WHY THIS IS THE STRONGEST FORM AVAILABLE. `analysis/rt_normalize.py` ranks three routes to
comparability and puts this first: *"ELIMINATE the hardware term — compare against OUR OWN
reproduction of K's LBBD, run on this machine. The hardware cancels exactly instead of being
estimated."* M6/M7 produced exactly that, and the artifacts carry TIMED bound AND incumbent
trajectories (`runs/lbbd_<cell>_n<size>_karademir.jsonl`).

So both sides can be asked the SAME question on the SAME hardware:

    how long to reach K's published bound, and how long to reach K's published incumbent?

    ours   = t_dual(our descent)      + t_primal(our fixopt)
    theirs = t_dual(their LBBD repro) + t_primal(their LBBD repro)

No budget ratio, no hardware factor, no normalisation — which is the point, since
`RT_COMPARABILITY` M3 rejects benchmark normalisation outright and §2.1 rejects budget comparison
because the deliverables differ.

THE CAVEAT THAT GOVERNS EVERY NUMBER HERE, and it is not small. The comparator is OUR
REIMPLEMENTATION of their method. M6/M7 measured it at 0.92–1.18 of K's published LB (median 0.99
at n20, 1.03 at n30) with **0 of 12 converging at either size**. `rt_normalize` states the rule:
a time-limited reproduction is NOT "K's method on our machine". So this is a comparison against
our best reconstruction of their algorithm, and every figure must say so. It is evidence about
reimplementations, not a claim about their software.

TIME-TO-REACH IS MORE FORGIVING THAN BOUND-QUALITY, which is why this is usable where M6/M7's
headline was not: asking WHEN a trajectory crosses a level does not require the run to have
converged, only to have crossed. A run that never crosses contributes to the denominator, not a
missing value.
"""
import glob, json, os, re, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import analysis.manuscript_numbers as M                      # noqa: E402
from analysis.time_to_parity import (DEADBAND, k_lb, k_bk,          # noqa: E402
                                     dual_time_to_parity, primal_time_to_parity)


def has_repro(cell, size):
    """Does a reproduction artifact exist at all? ABSENCE IS NOT A FAILURE.

    The M6/M7 arm covered 12 of 27 cells. Treating the other 15 as cells where their method
    "did not reach parity" would read as a 15-cell failure by their algorithm when there is
    simply no comparator. That mistake was caught before this was reported and is guarded here.
    """
    return os.path.exists(os.path.join(ROOT, "runs",
                                       "lbbd_%s_n%d_karademir.jsonl" % (cell, size)))


def their_times(cell, size):
    """From our same-machine reproduction: (t_bound, t_incumbent) to reach K's published levels."""
    p = os.path.join(ROOT, "runs", "lbbd_%s_n%d_karademir.jsonl" % (cell, size))
    if not os.path.exists(p):
        return None, None
    try:
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except Exception:
        return None, None
    lb, bk = k_lb(cell, size), k_bk(cell, size)
    tb = ti = None
    for r in rows:
        w = r.get("wall_s")
        if not isinstance(w, (int, float)):
            continue
        b = r.get("best_bound")
        if tb is None and isinstance(b, (int, float)) and lb is not None and b >= lb - DEADBAND:
            tb = w
        i = r.get("best_incumbent")
        if ti is None and isinstance(i, (int, float)) and bk is not None and i <= bk + DEADBAND:
            ti = w
    return tb, ti


def main():
    for size in (20, 30):
        rows, only_ours, only_theirs, neither, no_comparator = [], [], [], [], []
        for c in sorted(M._cells(size)):
            if k_lb(c, size) is None:
                continue
            if not has_repro(c, size):
                no_comparator.append(c)
                continue
            od = dual_time_to_parity(c, size)
            op, _, _ = primal_time_to_parity(c, size)
            td, ti = their_times(c, size)
            ours = (od + op) if (od is not None and op is not None) else None
            theirs = (td + ti) if (td is not None and ti is not None) else None
            if ours is not None and theirs is not None:
                rows.append(dict(cell=c, our_dual=od, our_primal=op, ours=ours,
                                 their_dual=td, their_primal=ti, theirs=theirs))
            elif ours is not None:
                only_ours.append(c)
            elif theirs is not None:
                only_theirs.append(c)
            else:
                neither.append(c)
        if not rows:
            print("\n=== |C| = %d : no cell has BOTH sides ===" % size)
            continue
        print("\n=== HEAD TO HEAD, |C| = %d — time to reach K's published bound AND incumbent ===" % size)
        print("    both sides on THIS machine; theirs is OUR REPRODUCTION of their LBBD")
        print("%-7s | %8s %9s %9s | %8s %9s %9s | %8s" %
              ("cell", "our_LB", "our_prim", "OURS", "their_LB", "their_pr", "THEIRS", "ratio"))
        for r in rows:
            print("%-7s | %8.1f %9.1f %9.1f | %8.1f %9.1f %9.1f | %7.2fx" %
                  (r["cell"], r["our_dual"], r["our_primal"], r["ours"],
                   r["their_dual"], r["their_primal"], r["theirs"],
                   r["ours"] / r["theirs"] if r["theirs"] else float("nan")))
        o = [r["ours"] for r in rows]
        t = [r["theirs"] for r in rows]
        faster = sum(1 for r in rows if r["ours"] < r["theirs"])
        print("-" * 86)
        print("  cells where BOTH sides reach parity : %d" % len(rows))
        print("  our median total   : %8.1f s" % st.median(o))
        print("  their median total : %8.1f s   (our reproduction of their method)" % st.median(t))
        print("  we are faster on   : %d of %d cells" % (faster, len(rows)))
        print("  only WE reach it   : %d  %s   (of cells WITH a comparator)"
              % (len(only_ours), ", ".join(only_ours[:8]) or "-"))
        print("  only THEY reach it : %d  %s" % (len(only_theirs), ", ".join(only_theirs[:8]) or "-"))
        print("  neither            : %d  %s" % (len(neither), ", ".join(neither[:8]) or "-"))
        print("  NO COMPARATOR      : %d  %s"
              % (len(no_comparator), ", ".join(no_comparator[:8]) or "-"))
        print("     -- the M6/M7 arm covered 12 of 27 cells. These are EXCLUDED, not counted as")
        print("        a failure by their method: absence of a reproduction is not a result.")
        print("\n  THE COMPARATOR IS OUR REIMPLEMENTATION. M6/M7 reached 0.92-1.18 of K's published")
        print("  LB with 0 of 12 converging, so this is evidence about reimplementations, not a")
        print("  claim about K's software. Report it that way or not at all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
