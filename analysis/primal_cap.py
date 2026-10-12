"""Per-cell primal hard cap = 5760 + 20 - dual_RT(cell), per PREREG_n100_primal_capped_variants.md
(d661). dual_RT = the certified submission wall of the frzdual2 dual leg (envelope-denominated,
d245/d246/d250). Emits shell-evalable assignments so the runner does no float arithmetic itself:

    eval "$(python analysis/primal_cap.py C204 100)"
    # -> CAP=... ALNS_FULL=... REFINE_SPLIT=... ALNS_SPLIT=... SELECT_SPLIT=...

Refuses (exit 2, prints nothing evalable) if the cell has no frzdual2 record -- its cap is
undefined and it must not be run (PREREG s2).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLACK = 20.0
ENVELOPE = 5760.0
# V2 split of the cap across the three primal stages; ALNS gets the bulk (basin-escape mechanism).
F_REFINE, F_ALNS, F_SELECT = 0.10, 0.70, 0.20
OVERHEAD = 15.0   # ws construct + verify headroom kept out of the stage budgets


def dual_rt(cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    rt = d.get("_rt") or {}
    w = rt.get("wall_s")
    if w is None:
        r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
        w = r.get("wall_s")
    return w


def main(argv):
    cell = argv[1]
    size = int(argv[2]) if len(argv) > 2 else 100
    drt = dual_rt(cell, size)
    if drt is None:
        sys.stderr.write("primal_cap: %s n%d has no frzdual2 record -- cap undefined, do not run\n" % (cell, size))
        return 2
    cap = ENVELOPE + SLACK - float(drt)
    usable = max(0.0, cap - OVERHEAD)
    print("CAP=%.1f ALNS_FULL=%.1f REFINE_SPLIT=%.1f ALNS_SPLIT=%.1f SELECT_SPLIT=%.1f DUAL_RT=%.1f"
          % (cap, usable, usable * F_REFINE, usable * F_ALNS, usable * F_SELECT, float(drt)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
