"""Close the LB coverage gap at |C|=20: run easy_reduction_descend on the cells never tried.

WHY THIS IS THE HIGHEST-VALUE RUN AVAILABLE. Extending the crossing table from 11 to 17 cells
cost zero compute (K's paper LB is derivable as Joint BK * (1 - Gap%/100), verified 11/11
against the hardcoded values). Doing so exposed a clean selection effect:

  cells ALREADY tested (11/11 beaten):   K Joint Gap 36-65%
  cells NEVER tested but LOOSE (9):      K Joint Gap  6-31%
  cells added by the zero-compute pass:  K Joint Gap  0%  (K PROVED OPTIMALITY -- 0/6, and
                                          that is arithmetic, not failure; we reach 0.97-0.98
                                          of a proven optimum there in 0.5-491s)

The two ranges do not overlap. The 11/11 headline is 11 of the ELEVEN LOOSEST cells in the
benchmark. Whether the dominance survives on tighter-but-still-loose cells (6-31%) is exactly
what a referee will ask, and it has never been measured.

SINGLE TENANCY: this waits for the kick ablation. That ablation's protocol clause (i) requires
one solver process at a time; starting LB work alongside it would reintroduce the co-tenancy
confound that invalidated the whole n30 campaign.
"""
import argparse, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# the 9 untested LOOSE cells, plus C208 (gap 0, completes the grid) -- loose first
LOOSE = ["R206", "RC206", "RC207", "C207", "C202", "R202", "RC205", "R210", "R209"]
TIGHT = ["C208"]


def say(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def busy():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { "
         "$_.CommandLine -like '*fixopt.py*' -or $_.CommandLine -like '*kick_ablation*' -or "
         "$_.CommandLine -like '*calib_run*' }).Count"],
        capture_output=True, text=True).stdout.strip()
    try:
        return int(out or 0) > 0
    except ValueError:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default=",".join(LOOSE + TIGHT))
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=int, default=450)
    # SOLVER THREADS -- maps straight to m.parameters.threads (easy_reduction_descend.py:40).
    # Default 4 = K's basis (4 CPUs, Xeon Gold 5218). The existing 17-cell artifacts were
    # produced at the script default of 8, so THEIR wall times are R13 screens and cannot
    # appear in a timing table; they need a 4-thread re-run before any timing is published.
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--per-cell-timeout", type=int, default=3600)
    ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()
    cells = [c.strip() for c in a.cells.split(",") if c.strip()]

    if a.wait:
        say("waiting for the kick ablation (single-tenancy protocol) ...")
        while busy():
            time.sleep(300)
        say("cores free")

    say(f"LB coverage: {len(cells)} cells at n{a.size}, loose-first, one at a time, "
        f"workers={a.workers} (K basis = 4)")
    for i, cell in enumerate(cells, 1):
        say(f"[{i}/{len(cells)}] {cell} ...")
        t0 = time.time()
        try:
            subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                            "--cells", cell, "--size", str(a.size), "--tl", str(a.tl),
                            "--workers", str(a.workers)],
                           cwd=ROOT, timeout=a.per_cell_timeout)
        except subprocess.TimeoutExpired:
            say(f"  {cell} TIMEOUT after {a.per_cell_timeout}s -- recorded as not-proven")
        except Exception as e:
            say(f"  {cell} ERROR {e}")
        say(f"  {cell} done in {time.time()-t0:.0f}s")
        subprocess.run([PY, os.path.join(ROOT, "analysis", "lb_coverage.py")], cwd=ROOT)
    say("LB COVERAGE RUN COMPLETE")


if __name__ == "__main__":
    main()
