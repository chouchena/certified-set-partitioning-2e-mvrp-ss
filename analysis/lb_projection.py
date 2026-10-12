"""What the dual leg costs to regenerate, projected from banked runtimes. Prints; writes nothing.

    python analysis/lb_projection.py [--cap 1500]

WHY IT EXISTS AS A FILE. The figures in validation/PRERUN_AUDIT_lb_grid_regen.md were first
computed inline, and the audit cited a script that did not exist. Every printed number has
generating code (CLAUDE.md section 1) and a citation to a missing file is worse than no
citation, because it reads as verified.

THE DENOMINATOR, which this project has now got wrong twice. There are 100 K-UNPROVEN cells --
the scope of any claim of ours -- and 96 of them have a banked artifact to extrapolate a runtime
from. 96 is the right denominator for the PROJECTION and the wrong one for the CLAIM. Both are
printed, side by side, every time.

IT IS A PROJECTION, NOT A MEASUREMENT. Each cell is charged min(its best banked wall, cap). A
re-run is not the same run: the code has changed (a deterministic clock was added), and a cell
that converged in 300 s before is only likely, not certain, to do so again.
"""
import argparse
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
from best_known import bound_artifacts
from bound_certificate import certified, ng_certified
from k_comparison import proven_cells
from lb_method_ablation import CELLS

SIZES = (10, 20, 30, 50, 100)


def best_wall(cell, size):
    """The longest banked wall among USABLE artifacts for this cell -- the pessimistic charge.

    Longest, not shortest: a re-run has to be budgeted for the configuration that actually
    produced the certificate we rely on, and the cheapest artifact is often a truncated one.
    """
    best = None
    for q, d in bound_artifacts(cell, size):
        if d.get("primal_rounding") or d.get("drop") or d.get("lp_street") is None:
            continue
        if not (certified(d) or ng_certified(d)):
            continue
        s = float(d.get("secs") or 0)
        if best is None or s > best:
            best = s
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=1500.0)
    a = ap.parse_args()

    tot = collections.Counter(); have = collections.Counter()
    capped = collections.Counter(); miss = collections.Counter(); scope = collections.Counter()

    print("SCOPE -- K-proven cells are excluded: we have no claim to make there")
    for size in SIZES:
        kp = set(proven_cells(size))
        scope[size] = len(CELLS) - len(kp)
        print("  n%-5d of %2d cells, K-proven %2d -> K-unproven %2d"
              % (size, len(CELLS), len(kp), scope[size]))
        for c in CELLS:
            if c in kp:
                continue
            w = best_wall(c, size)
            if w is None:
                miss[size] += 1
                continue
            have[size] += 1
            tot[size] += min(w, a.cap)
            if w > a.cap:
                capped[size] += 1

    print()
    print("PROJECTED WALL at a %.0f s hard cap, over K-unproven cells" % a.cap)
    print("  %-6s %7s %7s %8s %11s" % ("size", "priced", "hours", "hit cap", "no artifact"))
    T = 0.0
    for size in SIZES:
        if not scope[size]:
            continue
        T += tot[size]
        print("  n%-5d %7d %7.2f %8d %11d"
              % (size, have[size], tot[size] / 3600.0, capped[size], miss[size]))
    nmiss = sum(miss.values())
    print("  %-6s %7d %7.2f %8d %11d"
          % ("TOTAL", sum(have.values()), T / 3600.0, sum(capped.values()), nmiss))

    worst = T + nmiss * a.cap
    print()
    print("  cells in scope (the CLAIM denominator)   %d" % sum(scope.values()))
    print("  cells priced  (the PROJECTION denominator) %d" % sum(have.values()))
    print("  unpriced cells charged at the cap        %d  (+%.2f h)"
          % (nmiss, nmiss * a.cap / 3600.0))
    print("  serial  %.1f h   |   4 workers %.1f h   (worst case, unpriced at the cap)"
          % (worst / 3600.0, worst / 3600.0 / 4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
