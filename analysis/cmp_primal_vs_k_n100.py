"""Primal n100 arm vs K's Table 6 baseline. PRINTS ONLY (not a value-determining source).

GRANULARITY, stated so it is never mixed with the n20/n30 per-instance table: K publishes NO
per-instance n100 data. Table 6 is a FAMILY MEAN -- the per-instance average of z_IP over the
family's instances (C: 8, R: 11, RC: 8). So every n100 comparison here is one of OUR cells against
its FAMILY's K mean, and it is labelled that way. A single cell sitting below a family mean is not
a per-cell win over K's same cell (which K never published); it is a position relative to the only
granularity K reported at n100. The comparator direction follows d1 (PRIMAL takes the MIN over K's
two methods) and the LB side follows K's own published family gap.

OV comes from the cells' run logs (the primal traj batch ran --no-bank, so the value lives in the
`final best (verified)` line of logs/tep_solve_<cell>_n100_*.out, not in runs/). Each log line cited.
"""
import glob
import os
import re
import sys

sys.path.insert(0, "analysis")
import k_comparison as K

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = ["C203", "C204", "R207", "R211", "RC204"]
FAM = {"C203": "C", "C204": "C", "R207": "R", "R211": "R", "RC204": "RC"}


RT_CUT = 5760.0  # the RT policy truncates the full trajectory here (d245/d246/d250 envelope)


def final_ov(cell):
    """Parse the newest n100 log. Returns (ov_cut, t_cut, ov_full, wall, logname) where:
      ov_cut  = best verified OV reached AT t <= RT_CUT  (the policy-consistent value), with its t
      ov_full = the untruncated final (may rely on improvements that landed past RT_CUT)
    The trajectory is strictly improving, so ov_cut is the last `+improve` with t <= RT_CUT."""
    logs = sorted(glob.glob(os.path.join(ROOT, "logs", "tep_solve_%s_n100_*.out" % cell)),
                  key=os.path.getmtime)
    if not logs:
        return None, None, None, None, None
    log = logs[-1]
    ov_full, wall, ov_cut, t_cut = None, None, None, None
    with open(log, encoding="utf-8") as f:
        for ln in f:
            mi = re.search(r"\+improve obj=([\d.]+) mode=\S+ verify=OK t=(\d+)s", ln)
            if mi:
                obj, t = float(mi.group(1)), int(mi.group(2))
                if t <= RT_CUT and (ov_cut is None or obj < ov_cut):
                    ov_cut, t_cut = obj, t
            mf = re.search(r"final best \(verified\) = ([\d.]+)\s+wall=(\d+)s", ln)
            if mf:
                ov_full, wall = float(mf.group(1)), int(mf.group(2))
    return ov_cut, t_cut, ov_full, wall, os.path.basename(log)


def main():
    kref = K._kref()
    t6 = kref["table6"]
    print("=== primal n100 vs K Table 6 (FAMILY MEAN; K has no per-instance n100) ===")
    print("  RT policy truncates the trajectory at %.0fs; ov@cut is the headline, full is the "
          "untruncated final.\n" % RT_CUT)
    print("  %-6s %9s %7s | %9s %6s | %10s %6s %7s | %9s"
          % ("cell", "ov@cut", "t_cut", "ov_full", "wall", "K_fam_inc", "meth", "dOV%", "K_fam_LB"))
    for c in CELLS:
        ov_cut, t_cut, ov_full, wall, logname = final_ov(c)
        f = FAM[c]
        row = t6[f]
        j, l = row["joint"]["zIP"], row["lbbd"]["zIP"]
        k_inc = min(j, l)                                  # d1: MIN over K's two methods
        method = "lbbd" if l <= j else "joint"
        k_lb = row["joint"]["zIP"] * (1.0 - row["gap_joint"] / 100.0)   # K's own derived family LB
        if ov_cut is None:
            print("  %-6s %9s %7s | %9s %6s | %10.1f %6s %7s | %9.1f  (no +improve<=cut yet)"
                  % (c, "RUNNING", "-", "-", "-", k_inc, method, "-", k_lb))
            continue
        d = 100.0 * (ov_cut / k_inc - 1.0)                 # on the POLICY value; neg = below K fam mean
        tail = "" if abs(ov_full - ov_cut) < 1e-6 else "  (full gained post-cut)"
        print("  %-6s %9.2f %6ds | %9.2f %5ds | %10.1f %6s %+6.1f%% | %9.1f%s"
              % (c, ov_cut, t_cut, ov_full, wall, k_inc, method, d, k_lb, tail))
    print("\n  dOV% on ov@cut; < 0 => our cell is below K's family-mean incumbent (lower=cheaper).")
    print("  FAMILY-level position, NOT a per-cell beat (K published no per-cell n100).")


if __name__ == "__main__":
    main()
