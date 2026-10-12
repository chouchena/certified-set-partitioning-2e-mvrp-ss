"""Re-run the CORRECT solver over every cell tonight's grid produced, and rule on each one.

    python analysis/refuted_recheck.py              # run what is missing, then report
    python analysis/refuted_recheck.py --report     # report from artifacts already on disk

THE QUESTION. `analysis/tep_cg_banked.py` reproduces committed 15f739c, which prices without
start states -- the configuration d436 refuted on 14 of 27 cells at |C| = 10, over-stating by up
to 1.141 per cent while printing PROVEN True. Tonight it produced 65 artifacts. Each one is
either BELOW the valid bound, in which case it is a weaker but sound bound, or ABOVE it, in
which case it is not a bound at all. This decides which, cell by cell.

  APPROVED  grid lp_street <= tep_cg_bound lp_street. Valid, possibly weaker.
  REFUTED   grid lp_street >  tep_cg_bound lp_street. Over-stated; not a lower bound.

IT NEVER OVERWRITES. A target that already exists is READ, never re-run -- even when it is not
usable, in which case the cell is reported unresolved and the reason is printed. On 2026-09-30 a
single diagnostic invocation of tep_cg_bound.py destroyed the 2026-09-25 corpus artifact for
R202 n30; it was recoverable from git only because it was tracked. Most of tonight's are not.

RUNTIME IS REPORTED FOR BOTH ARMS AND NEITHER IS QUOTABLE. The grid ran at threads=1, the
correct solver at threads=4, so the two walls are not comparable to each other and neither is
comparable to K's. Both artifacts carry rt_class=diagnostic and say so; see analysis/rt_class.py
and d47. The walls are here to size the work, not to support a claim.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORACLE = os.path.join(ROOT, "runs", "oracle")
sys.path.insert(0, os.path.join(ROOT, "analysis"))


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def target_path(cell, size):
    return os.path.join(ORACLE, "tep_cg_bound_%s%s.json"
                        % (cell, "" if size == 100 else "_n%d" % size))


def grid_cells():
    out = []
    for f in sorted(os.listdir(ORACLE)):
        m = re.match(r"^tep_cg_banked_([A-Z]+\d+)(?:_n(\d+))?\.json$", f)
        if not m:
            continue
        d = load(os.path.join(ORACLE, f))
        if d and d.get("lp_street") is not None:
            out.append((m.group(1), int(m.group(2) or 100), d))
    out.sort(key=lambda r: (r[1], r[0]))
    return out


def usable(c, g):
    """Is this existing tep_cg_bound artifact a valid counterpart for the grid run `g`?"""
    if not c:
        return False, "absent"
    if not c.get("start_states"):
        return False, "no start-state pricing: d436 refuted that configuration"
    if c.get("delta") != g.get("delta"):
        return False, "delta %s vs the grid's %s" % (c.get("delta"), g.get("delta"))
    if not c.get("proven"):
        return False, "status %s, unproven" % c.get("status")
    if c.get("valid_bound") is False:
        return False, "valid_bound false"
    return True, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="do not run anything; report on disk")
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=2400.0)
    a = ap.parse_args()

    from rt_class import regime, banner, tenancy
    print(banner(regime(None, tenancy()), "per cell"))
    cells = grid_cells()
    print("tonight's grid artifacts: %d\n" % len(cells))

    ran = 0
    for cell, size, g in cells:
        tp = target_path(cell, size)
        if os.path.exists(tp) or a.report:
            continue
        cmd = [sys.executable, os.path.join(ROOT, "analysis", "tep_cg_bound.py"), cell,
               "--size", str(size), "--ng", str(a.ng), "--iters", str(a.iters),
               "--proximity", str((g.get("params") or {}).get("proximity", 0.0))]
        t0 = time.time()
        print("  running %-6s n%-4d ..." % (cell, size), end="", flush=True)
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=a.timeout)
            print(" %.0fs rc=%d" % (time.time() - t0, r.returncode), flush=True)
        except subprocess.TimeoutExpired:
            print(" TIMEOUT after %.0fs" % (time.time() - t0), flush=True)
        ran += 1

    print("\n%s" % ("=" * 118))
    print("  %-6s %5s %12s %12s %11s %9s %8s %8s  %s"
          % ("cell", "size", "grid lp", "valid lp", "grid-valid", "over %", "grid s", "valid s", "verdict"))
    print("  %s" % ("-" * 114))
    app = ref = uns = 0
    for cell, size, g in cells:
        c = load(target_path(cell, size))
        ok, why = usable(c, g)
        gs = g.get("secs")
        if not ok:
            uns += 1
            print("  %-6s %5d %12.4f %12s %11s %9s %8s %8s  UNRESOLVED -- %s"
                  % (cell, size, g["lp_street"], "-", "-", "-", gs, "-", why))
            continue
        d = g["lp_street"] - c["lp_street"]
        verdict = "REFUTED" if d > 1e-6 else "approved"
        app += verdict == "approved"
        ref += verdict == "REFUTED"
        print("  %-6s %5d %12.4f %12.4f %+11.4f %9.3f %8s %8s  %s"
              % (cell, size, g["lp_street"], c["lp_street"], d,
                 100.0 * d / c["lp_street"], gs, c.get("secs"), verdict))
    print("  %s" % ("-" * 114))
    print("  approved %d | REFUTED %d | unresolved %d | of %d" % (app, ref, uns, len(cells)))
    print("  walls are threads=1 (grid) against threads=4 (valid); rt_class=diagnostic on both,")
    print("  so neither is comparable to the other or to K -- see analysis/rt_class.py, d47.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
