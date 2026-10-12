"""What data is ACTUALLY missing? Verify before running, because "it doesn't exist" keeps being wrong.

WHY THIS EXISTS. Twice in one day I proposed work that already existed or was already answered:
the s2_close comparator defect was FIXED three days before I "discovered" the register said
otherwise, and I wrote an RT-fairness audit without opening RT_COMPARABILITY.md, whose metric
table already rated the two metrics the author then proposed. Both were cheap to check and I did
not check. This file makes the check mechanical.

IT REPORTS PRESENCE, NOT QUALITY. A cell that has an artifact may still have a BAD one -- stale,
wall-limited, or at the wrong proximity. Presence is the precondition for "do not re-run", not a
certificate. Where a known quality gate exists it is applied and named; where it does not, the
column says PRESENT and nothing stronger.

Usage:  python analysis/missing_data_inventory.py
"""
import collections, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import analysis.manuscript_numbers as M                      # noqa: E402

SIZES = (10, 20, 30, 50, 100)


def _cells(size):
    try:
        return sorted(M._cells(size))
    except Exception:
        return []


def probe(label, fn, note=""):
    """fn(size) -> set of cells that HAVE the thing."""
    print("\n%-46s %s" % (label, note))
    print("  %-6s %9s %9s   %s" % ("size", "have", "of", "missing (first 6)"))
    out = {}
    for s in SIZES:
        cells = _cells(s)
        if not cells:
            continue
        have = fn(s)
        miss = [c for c in cells if c not in have]
        out[s] = (len(have & set(cells)), len(cells), miss)
        print("  n%-5d %9d %9d   %s" % (s, len(have & set(cells)), len(cells),
                                        ", ".join(miss[:6]) + (" ..." if len(miss) > 6 else "")))
    return out


def have_glob(pattern):
    def f(size):
        got = set()
        for p in glob.glob(os.path.join(ROOT, pattern.format(size=size))):
            m = re.search(r"((?:C|R|RC)\d{3})", os.path.basename(p))
            if m:
                got.add(m.group(1))
        return got
    return f


def main():
    print("=" * 84)
    print("MISSING-DATA INVENTORY -- presence only. Verify before running.")
    print("=" * 84)

    probe("PRIMAL: a banked verified solution",
          have_glob("published_artifacts/solutions/best_{size}.json".replace("{size}", "*_n{size}")),
          "-> published_artifacts/solutions/best_<cell>_n<size>.json")

    probe("PRIMAL: any fixopt run at all",
          have_glob("runs/fixopt_*_n{size}_*.jsonl"),
          "-> the primal has been ATTEMPTED on this cell")

    probe("DUAL: a descend artifact",
          have_glob("crossfeed/easy_reduction_descend_*_n{size}.json"),
          "-> our lower bound exists for this cell")

    probe("DUAL: a same-machine LBBD reproduction",
          have_glob("runs/lbbd_*_n{size}_karademir.jsonl"),
          "-> K's method reproduced here (M6/M7 arms)")

    probe("RESTART POOL: diverse constructions banked",
          have_glob("runs/restart_pools/pool_*_n{size}.json"),
          "-> built 2026-09-17 for the escape ladder")

    # ---- things that are NOT per-cell ------------------------------------------------
    print("\n" + "=" * 84)
    print("NON-PER-CELL ITEMS")
    print("=" * 84)
    checks = [
        ("greedy blind-vs-aware grid, 20 seeds", "runs/greedy_blind_vs_aware_grid_s20.json"),
        ("greedy OV decomposition, 20 seeds", "runs/greedy_ov_decomp_s20.json"),
        ("M6 score (n20 matched-budget)", "runs/m6_score.json"),
        ("M7 score (n30 matched-budget)", "runs/m7_score.json"),
        ("n20 fleet total", "runs/n20_fleet_total.json"),
        ("path cover, n20", "runs/path_cover_n20.json"),
        ("greedy coverage census", "runs/greedy_coverage.json"),
        ("S2p Stage 1 fleet-floor proof", "runs/fleet_lb_solver_n20_stage1.json"),
        ("RT budget fairness audit", "runs/rt_budget_fairness.json"),
        ("primal mean-vs-K (new headline metric)", "runs/primal_mean_vs_k.json"),
        ("M6-table arm: OUR method at K's budget", "runs/m6table_equal_budget.json"),
        ("M5-primal: time-to-beat K, primal", "runs/m5_primal_time_to_beat.json"),
    ]
    for label, path in checks:
        p = os.path.join(ROOT, path)
        print("  %-42s %-10s %s" % (label, "PRESENT" if os.path.exists(p) else "MISSING", path))

    print("\n" + "=" * 84)
    print("READ THIS BEFORE PROPOSING A RUN")
    print("=" * 84)
    print("  * PRESENT means an artifact exists, NOT that it is good. Check proximity, thread")
    print("    count, budget and whether it is wall-limited before reusing it.")
    print("  * A cell with a fixopt run but no banked solution may still have a recoverable")
    print("    incumbent -- or may be a scaleprobe with NO solution payload, as C203 n30 is.")
    print("  * The falsifier register is a separate backlog: python analysis/claims.py check.")
    print("  * Governing documents: python analysis/session_state.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
