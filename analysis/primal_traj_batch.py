"""First wide PRIMAL trajectory batch (orchestrator, NOT a value-determining source; --no-bank so
tep_solve writes no artifact -- the full OV(t)+event trajectory is in logs/<run_id>.out).

Same RT policy as the dual: envelope 5760 (full, to measure the primal leg standalone), external
guillotine 5760*1.2 = 6912 s (+240 margin) via subprocess timeout. SINGLE-TENANT sequential (the
RT axis is wall, so no co-tenancy). Greedy-constructed WS = tep_solve's 1-6 TEP construction (the
settled pipeline; a greedy-construct-only CG-free variant is a fast-follow). 2 seeds each.

QUARANTINE STOPS THE BATCH: tep_solve refuses to start on untriaged quarantine (exit 2) and halts
on a new one mid-run (exit 3). Either exit code stops this batch immediately for an inquiry into
cause and blast, per CLAUDE.md section 1 and the author's instruction.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = ["C203", "C204", "R207", "R211", "RC204"]   # 2C / 2R / 1RC, incl. the hard outlier C204; cheapest-RT first
SIZES = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else [20, 30, 50]
SEEDS = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [0, 1]
GUILL, MARGIN = 6912, 240


def precompile():
    """OUT-OF-RT: compile every tree tep_solve imports from BEFORE any timed run, so no .pyc
    compilation ever lands inside a measured trajectory (the standard: no compile in RTs)."""
    print("[compileall out-of-RT] %s" % time.strftime("%H:%M:%S"), flush=True)
    subprocess.run([sys.executable, "-m", "compileall", "-q",
                    os.path.join(ROOT, "analysis"), os.path.join(ROOT, "solver"),
                    os.path.join(ROOT, "crossfeed"), os.path.join(ROOT, "build_instance.py")],
                   cwd=ROOT, check=False)
    print("[compileall done] %s" % time.strftime("%H:%M:%S"), flush=True)


def main():
    precompile()
    for n in SIZES:
        for seed in SEEDS:
            for cell in CELLS:
                tag = "%s n%d seed%d" % (cell, n, seed)
                print("=== %s START %s ===" % (tag, time.strftime("%H:%M:%S")), flush=True)
                t0 = time.time()
                try:
                    r = subprocess.run(
                        [sys.executable, os.path.join("analysis", "tep_solve.py"), cell,
                         "--size", str(n), "--seed", str(seed), "--envelope", "5760",
                         "--no-bank", "--tag", "primtraj"],
                        cwd=ROOT, timeout=GUILL + MARGIN)
                    rc = r.returncode
                except subprocess.TimeoutExpired:
                    rc = 124
                print("=== %s EXIT=%d  (%.0fs, %s) ===" % (tag, rc, time.time() - t0,
                                                           time.strftime("%H:%M:%S")), flush=True)
                if rc in (2, 3):
                    print("!!! QUARANTINE (rc=%d) at %s -- STOPPING BATCH for inquiry into cause "
                          "and blast (CLAUDE.md s1)." % (rc, tag), flush=True)
                    return rc
                if rc not in (0, 124):
                    print("!!! ERROR (rc=%d) at %s -- STOPPING BATCH." % (rc, tag), flush=True)
                    return rc
    print("[primal traj batch done] %s" % time.strftime("%H:%M:%S"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
