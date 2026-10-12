"""Envelope accounting for the TEP column-generation bound (d245: per cell, LB wall + primal wall
= K_CAP / HW_FACTOR = 5760 our-seconds at factor 2.5; the LB wall is deducted before the primal).

Per n100 cell: the MILP descent's wall (run_full_grid.lb_cell_seconds, today's dual leg), the CG
bound's wall (runs/oracle/tep_cg_bound_<cell>.json, `secs`), and the primal spend as run
(--budget 744 s, the calibration figure the day's primal runs used).  Three instrument sets:
  S1 = {AB, MILP descent}   (today's budgeted dual leg; AB costs milliseconds and is ignored)
  S2 = {AB, CG}             (the CG replaces the descent)
  BOTH = {AB, MILP, CG}     (conservative: every instrument whose value is reported is charged)
For each: primal envelope = 5760 - LB wall, and whether the 744 s primal fits.

    python analysis/envelope_with_cg.py [--primal 744] [--factor 2.5]
"""
import argparse
import glob
import io
import json
import os
import sys
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import run_full_grid as G

CELLS = ["R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208", "R209", "R210", "R211",
         "RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208",
         "C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--primal", type=float, default=744.0); ap.add_argument("--factor", type=float, default=G.HW_FACTOR_ENVELOPE)
    a = ap.parse_args()
    cap = G.K_CAP_THEIR_SECONDS / a.factor
    print("envelope %.0f our-s per cell (K %.0f / factor %.1f); primal as run %.0f s" % (cap, G.K_CAP_THEIR_SECONDS, a.factor, a.primal))
    print("%-6s %8s %8s %8s | %8s %8s %8s | %s" % ("cell", "milp_s", "cg_s", "cg_bound", "env_S1", "env_S2", "env_BOTH", "primal fits S1/S2/BOTH"))
    rows = []
    for c in CELLS:
        milp = G.lb_cell_seconds(c, 100) or 0.0
        f = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s.json" % c)
        cg = None
        if os.path.exists(f):
            d = json.load(io.open(f, encoding="utf-8"))
            cg = d if d.get("proven") else None
        cg_s = cg["secs"] if cg else None
        e1 = cap - milp
        e2 = cap - (cg_s if cg_s is not None else 0.0) if cg_s is not None else None
        eb = cap - milp - cg_s if cg_s is not None else None
        fits = lambda e: "-" if e is None else ("yes" if e >= a.primal else "NO")
        print("%-6s %8.0f %8s %8s | %8.0f %8s %8s | %s / %s / %s" % (
            c, milp, "%.0f" % cg_s if cg_s is not None else "-", "%.1f" % cg["composed"] if cg else "-",
            e1, "%.0f" % e2 if e2 is not None else "-", "%.0f" % eb if eb is not None else "-", fits(e1), fits(e2), fits(eb)))
        rows.append(dict(cell=c, milp_s=milp, cg_s=cg_s, env_S1=e1, env_S2=e2, env_BOTH=eb))
    have = [r for r in rows if r["cg_s"] is not None]
    if have:
        print("\n%d cells with a proven CG bound: CG wall median %.0f s, max %.0f s; primal %.0f s fits under S2 on %d, under BOTH on %d"
              % (len(have), st.median(r["cg_s"] for r in have), max(r["cg_s"] for r in have), a.primal,
                 sum(1 for r in have if r["env_S2"] >= a.primal), sum(1 for r in have if r["env_BOTH"] >= a.primal)))
    json.dump(dict(cap=cap, factor=a.factor, primal=a.primal, rows=rows), io.open(os.path.join(ROOT, "runs", "oracle", "envelope_with_cg.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
