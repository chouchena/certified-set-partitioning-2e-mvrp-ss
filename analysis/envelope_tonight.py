"""Post-hoc envelope check of the night of 2026-09-23/24 (d245/d250: per cell LB wall + primal
wall <= 14400 / 2.5 = 5760 our-seconds; the LB wall is deducted first; d383: one instrument set
per family, S1 = {AB, MILP descent} or S2 = {AB, CG}; BOTH as sensitivity).

Primal wall per cell = the TEP portfolio census (both compositions: Gurobi chaining + CPLEX
re-timing, parsed from logs/assembly_census.out and logs/assembly_c1.out) + the C2 polish wall on
C cells (runs/trial_C2/C2_<cell>.json _run_wall_s, else 744 s). LB wall: MILP descent
(run_full_grid.lb_cell_seconds) and CG (runs/oracle/tep_cg_bound_<cell>.json secs; the finer
run's secs where the finer value is the one cited).

    python analysis/envelope_tonight.py
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import run_full_grid as G
import bks_n100 as B

CAP = G.K_CAP_THEIR_SECONDS / G.HW_FACTOR_ENVELOPE


def census_walls(paths):
    """cell -> seconds spent in chaining + re-timing over both compositions."""
    out = {}
    cell = None
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in io.open(p, encoding="utf-8", errors="replace"):
            m = re.match(r"^(RC\d{3}|R\d{3}|C\d{3})\s+incumbent", line)
            if m:
                cell = m.group(1); out.setdefault(cell, 0.0); continue
            if cell is None:
                continue
            m = re.search(r"chained into .*?status \S+, (\d+)s\)", line)
            if m:
                out[cell] += float(m.group(1)); continue
            m = re.search(r"re-timing .*? in (\d+)s ->", line)
            if m:
                out[cell] += float(m.group(1)); continue
            m = re.search(r"trips: .*?\((\d+)s\)", line)
            if m and "chained" not in line:
                out[cell] += float(m.group(1))
    return out


def main():
    cw = census_walls([os.path.join(ROOT, "logs", "assembly_census.out"), os.path.join(ROOT, "logs", "assembly_c1.out")])
    print("envelope %.0f our-s per cell; primal = census (both compositions) + C2 polish on C" % CAP)
    print("%-6s %7s %7s %7s | %7s %7s | %8s %8s %8s" % ("cell", "census", "polish", "primal", "milp", "cg", "S1_tot", "S2_tot", "BOTH"))
    over = {"S1": [], "S2": [], "BOTH": []}
    for c in B.CELLS:
        cen = cw.get(c, 0.0)
        pol = 0.0
        f = os.path.join(ROOT, "runs", "trial_C2", "C2_%s.json" % c)
        if os.path.exists(f):
            a = json.load(io.open(f, encoding="utf-8")); pol = float(a.get("_run_wall_s") or a.get("_wall_s") or 744.0)
        primal = cen + pol
        milp = G.lb_cell_seconds(c, 100) or 0.0
        cg = None
        g = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s.json" % c)
        if os.path.exists(g):
            r = json.load(io.open(g, encoding="utf-8")); cg = float(r["secs"]) if r.get("proven") else None
        for tag in ("_d10", "_d30"):
            h = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s.json" % (c, tag))
            if os.path.exists(h):
                q = json.load(io.open(h, encoding="utf-8"))
                if q.get("proven"):
                    cg = (cg or 0.0) + float(q["secs"])          # the cited finer value costs both runs
        s1 = milp + primal; s2 = (cg or 0.0) + primal; both = milp + (cg or 0.0) + primal
        for k, v in (("S1", s1), ("S2", s2), ("BOTH", both)):
            if v > CAP: over[k].append(c)
        print("%-6s %7.0f %7.0f %7.0f | %7.0f %7s | %8.0f %8.0f %8.0f%s" % (c, cen, pol, primal, milp, "%.0f" % cg if cg is not None else "-", s1, s2, both,
                                                                          "  OVER: " + ",".join(k for k, v in (("S1", s1), ("S2", s2), ("BOTH", both)) if v > CAP) if max(s1, s2, both) > CAP else ""))
    print("\ncells over the envelope: S1 %s | S2 %s | BOTH %s" % (over["S1"] or "none", over["S2"] or "none", over["BOTH"] or "none"))
    print("NOTE: no driver tonight enforced the envelope as a stop rule; the budgets were the calibration figures. This is the post-hoc accounting.")


if __name__ == "__main__":
    main()
