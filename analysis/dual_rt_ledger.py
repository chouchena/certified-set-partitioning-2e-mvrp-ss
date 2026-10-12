"""Dual-leg RT ledger across the n100 grid -- the instrumentation for directive (1):
"decide on RT cap for dual OR save effective RT for deduction from primal RT."

Two numbers per cell, kept apart on purpose:
  * certified dual WALL  (d._rt.wall_s, rt_class=submission, threads=4, tenancy=1, policy d47)
        -- this is the envelope-denominated figure. The budget is wall: LB + primal <= 14400/2.5
           = 5760 our-seconds/cell (CLAUDE.md s5; d245/d246/d250). So the dual leg is CHARGED in
           wall, and the primal's remaining budget is 5760 - dual_wall.
  * det WORK            (rows[0].work, Gurobi Work units)
        -- the deterministic reproducibility anchor. It covers the LP master + master_ip solves
           ONLY; the numba CG pricer is wall-bound Python and is NOT in Work (the handoff note
           says so). Work therefore UNDER-counts the dual leg and must not be used as the cap.
           Reported beside the wall, never instead of it.

Post-hoc this supports EITHER lever (both printed, choice deferred to data):
  (1a) a single dual cap  = max certified converged wall x headroom  (round up)
  (1b) per-cell deduction = 5760 - dual_wall  -> remaining primal budget per cell

Run SINGLE-TENANT. v1 (frzdual, exact pricer) records are included but FLAGGED -- their wall is
not comparable to the fast-pricer grid and must not enter the cap.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVELOPE = 5760.0          # our-seconds/cell (14400 / 2.5 HW), LB+primal (d245/d246/d250)
HEADROOM = 1.30            # cap = max converged wall x this, rounded up to 50s

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def _load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def _row(d):
    r = d.get("rows", [d])
    return r[0] if isinstance(r, list) else r


def cell_rt(cell, size=100):
    """Prefer the fast-pricer (frzdual2) record; fall back to v1 (frzdual) flagged not-comparable."""
    for tag, v1 in (("frzdual2", False), ("frzdual", True)):
        p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
        d = _load(p)
        if d is None:
            continue
        r = _row(d)
        rt = d.get("_rt") or {}
        return {
            "cell": cell, "tag": tag, "v1_not_comparable": v1,
            "cert": r.get("certificate"), "lb": r.get("lb"), "ov": r.get("ov"),
            "gap_pct": r.get("gap_pct"),
            "wall_s": rt.get("wall_s") or r.get("wall_s"),
            "work": r.get("work"), "det_work_total": r.get("det_work_total"),
            "rt_class": rt.get("rt_class"), "threads": rt.get("threads"), "tenancy": rt.get("tenancy"),
        }
    return None


def main(argv):
    size = int(argv[1]) if len(argv) > 1 else 100
    rows = [x for x in (cell_rt(c, size) for c in CELLS) if x]
    if not rows:
        print("no dual records found at n%d" % size); return 0

    print("=== Dual-leg RT ledger | n%d | %d / %d cells ===" % (size, len(rows), len(CELLS)))
    print("  %-7s %-9s %-5s %8s %9s %7s %6s   %s"
          % ("cell", "tag", "cert", "wall_s", "work_det", "gap%", "class", "note"))
    conv_walls = []
    for r in sorted(rows, key=lambda x: -(x["wall_s"] or 0)):
        note = "v1 EXACT-PRICER (not comparable)" if r["v1_not_comparable"] else ""
        gp = ("%.1f" % r["gap_pct"]) if r["gap_pct"] is not None else "n/a"
        print("  %-7s %-9s %-5s %8.1f %9.2f %7s %6s   %s"
              % (r["cell"], r["tag"], str(r["cert"]), r["wall_s"] or -1, r["work"] or -1,
                 gp, str(r["rt_class"]), note))
        if (not r["v1_not_comparable"]) and r["cert"] and r["wall_s"]:
            conv_walls.append((r["cell"], r["wall_s"]))

    fast = [r for r in rows if not r["v1_not_comparable"]]
    print("\n  fast-pricer cells: %d (%d certified)  |  v1-only cells: %d"
          % (len(fast), len(conv_walls), len(rows) - len(fast)))
    if conv_walls:
        mx_cell, mx = max(conv_walls, key=lambda t: t[1])
        cap = 50.0 * (int((mx * HEADROOM) / 50.0) + 1)
        print("\n  (1a) DUAL CAP recommendation:")
        print("       max certified fast-pricer wall = %.1fs (%s)" % (mx, mx_cell))
        print("       cap = ceil(%.2fx, 50s) = %.0fs   (vs current envelope 1500s)" % (HEADROOM, cap))
        print("\n  (1b) PRIMAL-BUDGET deduction (envelope %.0fs/cell, wall-denominated):" % ENVELOPE)
        print("       %-7s %8s %10s" % ("cell", "dual_s", "primal_left"))
        for c, w in sorted(conv_walls, key=lambda t: -t[1]):
            print("       %-7s %8.1f %10.1f" % (c, w, ENVELOPE - w))
        print("\n  NOTE: cap/deduction use CERTIFIED WALL (the envelope is wall, d245/d250).")
        print("        work_det is the reproducibility anchor only -- it excludes the numba")
        print("        CG pricer (wall-bound), so it under-counts the leg and is not the cap.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
