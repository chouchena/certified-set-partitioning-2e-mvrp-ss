"""Phase -1 breadth: the DAG arbiter's root bound and cost across every size.

    python analysis/dag_sweep.py --stream A

SMOKE, NOT A RESULT. Writes one line per cell to logs/smoke/dag_sweep_<stream>.tsv and nothing
under runs/. Author, 2026-09-30: "we are smoking and trying - we dont need to bank - just to log
for discussion and decision."

THE FIRST PASS MEASURED THE WRONG NUMBER. It ran --root-only for speed and reported the
pure LP relaxation as the arbiter's bound. It is not: Gurobi closes this model AT THE
ROOT NODE -- 5 of 5 cells tested, 0.4 to 4 work units -- and the integer optimum it
reaches there is much tighter than the LP. R211 n10 -32.76 against -11.56, RC204 n10
-40.29 against -11.51, C201 n20 -51.95 against -37.99. --root-only bought nothing,
because the branching it skipped costs about one work unit, and it understated the
instrument by up to 3.5x. The sweep now solves the MIP.

WHY BREADTH NOW. Everything so far is one cell, R202 n30, drilled through four formulations.
That settled which formulation to use and told us nothing about whether it SCALES, which is the
only question Phase -1 was opened to answer (d622). The root LP is seconds once the duals exist,
so a spread across all five sizes is cheap.

CELL CHOICE, and each is picked for a reason rather than at random:
  n10   the three cells that have enumerated ground truth, so the arbiter can be checked
        against a known answer rather than against itself
  n20   two with ground truth plus the two whose certified TEP bound is weakest (R207, R208 --
        the only two cells anywhere where AB4 beats TEP on a K-unproven cell)
  n30   the baseline and the three hardest by banked wall
  n50   the hardest by the refuted grid's wall (C204 224 s, R204 267 s) plus one mid cell
  n100  two cells, and the DUALS ARE PARTIAL by construction: start-state CG dies at 4 to 6
        iterations there, so --iters is capped and the verdict means nothing. The SIZE and COST
        columns are the point; they are what decides whether the arbiter is affordable at all.
"""
import argparse
import io
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))

# (size, cell, cg_iters_cap) -- None means run CG to convergence
STREAM = {
    "A": [(10, "C201", None), (10, "R211", None), (10, "RC204", None),
          (20, "C201", None), (20, "R202", None), (20, "R203", None), (20, "RC204", None),
          (30, "R202", None), (30, "C204", None)],
    "B": [(20, "R207", None), (20, "R208", None),
          (30, "R204", None), (30, "R208", None),
          (50, "R202", None), (50, "C204", None), (50, "R204", None),
          (100, "C204", 8), (100, "R211", 8)],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", choices=sorted(STREAM), required=True)
    ap.add_argument("--grid", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=2400.0)
    a = ap.parse_args()

    out = os.path.join(ROOT, "logs", "smoke", "dag_sweep_%s.tsv" % a.stream)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("size\tcell\tcg_iters\tcg_lp\tcg_proven\tcg_secs\tnodes\tarcs\troot_lp\twork\tsecs\n")
    print("stream %s, grid %.1f -> %s" % (a.stream, a.grid, os.path.relpath(out, ROOT)), flush=True)
    print("%5s %-7s %10s %8s %8s %9s %12s %8s %7s"
          % ("size", "cell", "cg_lp", "proven", "cg_s", "graph", "root_lp", "work", "secs"),
          flush=True)

    for size, cell, icap in STREAM[a.stream]:
        cmd = [sys.executable, os.path.join(ROOT, "analysis", "espprc_arbiter_dag.py"), cell,
               "--size", str(size), "--grid", str(a.grid), "--work", "3000"]
        if icap:
            cmd += ["--iters", str(icap)]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=a.timeout)
            txt = (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            txt = ""
        def grab(tag, cast=float, default=None):
            for ln in txt.splitlines():
                if tag in ln:
                    try:
                        return cast(ln.split(tag)[1].split()[0].strip("|,"))
                    except Exception:
                        return default
            return default
        cg_lp = grab("lp_street ")
        prov = "True" in (next((l for l in txt.splitlines() if "proven" in l), ""))
        nds = grab("graph: ", int)
        root = grab("dual bound ")
        work = grab("work ")
        secs = round(time.time() - t0, 1)
        arcs = None
        for ln in txt.splitlines():
            if "inner +" in ln:
                try:
                    parts = ln.replace(",", "").split()
                    arcs = sum(int(parts[i]) for i, w in enumerate(parts)
                               if w in ("inner", "start", "end") and parts[i].isdigit())
                except Exception:
                    pass
        print("%5d %-7s %10s %8s %8.0f %9s %12s %8s %7.0f"
              % (size, cell, ("%.2f" % cg_lp) if cg_lp else "-", prov, secs,
                 str(nds), ("%.2f" % root) if root is not None else "FAILED",
                 ("%.1f" % work) if work else "-", secs), flush=True)
        with io.open(out, "a", encoding="utf-8") as f:
            f.write("%d\t%s\t%s\t%s\t%s\t%.0f\t%s\t%s\t%s\t%s\t%.0f\n"
                    % (size, cell, icap or "conv", cg_lp, prov, secs, nds, arcs, root, work, secs))
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
