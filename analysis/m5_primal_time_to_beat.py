"""M5 for the PRIMAL: how long until our incumbent beats K's published OV?

METRIC AUTHORITY: `validation/RT_COMPARABILITY.md` metric **M5** -- "time for our bound to reach
K's final published bound" -- rated CANDIDATE: *well defined, checkable, already implemented*.
It is implemented for the DUAL as `lb-time-to-exceed-k` (median 1.84 s at n20, 3.31 s at n30).
This is the PRIMAL counterpart, which did not exist. Author endorsed the metric 2026-09-17.

AN ABSOLUTE TIME, NEVER A RATIO. RT_COMPARABILITY section 4 leaves the position OPEN (O1/O2/O3,
deferred by the author 2026-09-11) and O3 -- a bare "N times faster" -- is marked INDEFENSIBLE.
Whether M5 may be expressed as a ratio depends on that open decision. Every figure here is a time
in seconds on our hardware, with K's published value as a horizontal reference. No factor, no
conversion, no speedup.

CENSORING IS STRUCTURAL AND THE MEDIAN IS THE STATISTIC. Under the new headline metric our MEAN
beats K on only 4-5 of 24 cells at |C| = 20 (decision 67), so most cells never cross at all.
Averaging over the cells that DO cross would be a selection on the outcome -- the very thing the
best-of metric was demoted for. So: the median over crossing cells is reported WITH the
never-crossed count beside it, never one without the other. This is the convention the dual side
already forced, where R209 (n20) and R201 (n30) never cross.

ZERO NEW COMPUTE. Every figure comes from incumbent traces already on disk: each fixopt jsonl
carries (wall_s, best_incumbent) pairs. Nothing is re-run.

WHAT THIS IS NOT. It is not a claim that we are faster. It is "our incumbent passes their
published value at t seconds on this machine, on the N of 27 cells where it passes at all".
"""
import argparse, collections, glob, json, os, re, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
import analysis.manuscript_numbers as M                      # noqa: E402


def k_target(cell, size):
    r = M._K()["table3"]["per_instance"].get(str(size), {}).get(cell)
    return None if not r else min(r["joint_bk"], r.get("lbbd_bk", r["joint_bk"]))


def crossings(size, variant=None):
    """per cell -> list of times at which a run's incumbent first beat K, or None if never."""
    out = collections.defaultdict(list)
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_*_n%d_*.jsonl" % size)):
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n\d+_s\d+_(.+?)_\d+\.jsonl$", os.path.basename(f))
        if not m:
            continue
        cell, var = m.group(1), m.group(2)
        if variant and var != variant:
            continue
        kb = k_target(cell, size)
        if kb is None:
            continue
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        pts = [(r.get("wall_s"), r.get("best_incumbent")) for r in rows
               if isinstance(r.get("wall_s"), (int, float))
               and isinstance(r.get("best_incumbent"), (int, float))
               and r["best_incumbent"] > 0]
        if not pts:
            continue
        hit = [w for w, o in pts if o < kb - 1e-9]
        out[cell].append(min(hit) if hit else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10,20,30")
    ap.add_argument("--variant", default=None)
    ap.add_argument("--out", default="runs/m5_primal_time_to_beat.json")
    a = ap.parse_args()

    print("M5-PRIMAL: seconds until our incumbent beats K's published OV, on OUR hardware.")
    print("Absolute times only -- RT_COMPARABILITY O1/O2/O3 is OPEN and O3 is indefensible.\n")
    report = {}
    for size in [int(x) for x in a.sizes.split(",")]:
        C = crossings(size, a.variant)
        if not C:
            continue
        cell_med, never, runs_cross, runs_tot = {}, [], 0, 0
        for cell, times in sorted(C.items()):
            runs_tot += len(times)
            ok = [t for t in times if t is not None]
            runs_cross += len(ok)
            if ok:
                cell_med[cell] = st.median(ok)
            else:
                never.append(cell)
        print("=== |C| = %d ===" % size)
        print("  cells that EVER cross      : %d of %d" % (len(cell_med), len(C)))
        print("  cells that NEVER cross     : %d   %s"
              % (len(never), ", ".join(never[:10]) + (" ..." if len(never) > 10 else "")))
        print("  runs that cross            : %d of %d (%.0f%%)"
              % (runs_cross, runs_tot, 100.0 * runs_cross / runs_tot if runs_tot else 0))
        if cell_med:
            v = sorted(cell_med.values())
            print("  median time-to-beat, over crossing cells : %8.1f s" % st.median(v))
            print("  p25 / p75                                : %8.1f / %.1f s"
                  % (v[len(v) // 4], v[3 * len(v) // 4]))
            print("  slowest crossing cell                    : %8.1f s (%s)"
                  % (v[-1], max(cell_med, key=cell_med.get)))
        print("  !! the median is over CROSSING cells only. It is meaningless without the")
        print("     never-crossed count above it, and must never be quoted alone.\n")
        report[str(size)] = dict(cells_cross=len(cell_med), cells_total=len(C),
                                 never=never, runs_cross=runs_cross, runs_total=runs_tot,
                                 median_s=st.median(list(cell_med.values())) if cell_med else None,
                                 per_cell={k: round(v, 2) for k, v in cell_med.items()})
    json.dump(stamped(dict(metric="M5-primal, absolute seconds, no ratio",
                   authority="validation/RT_COMPARABILITY.md M5; O1/O2/O3 OPEN",
                   variant=a.variant, sizes=report), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("wrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
