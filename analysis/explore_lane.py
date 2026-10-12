"""EXPLORE LANE — run focused trials on the idle cores without waiting for the pipeline.

THE PROBLEM. The primary pipeline runs at 4 threads on an 8-core machine (4 P + 4 LPE, no SMT),
so measured utilisation is 47%: CPLEX saturates the 4 it was given and the other half idles. New
ideas then queue behind multi-hour pre-registered stages for no reason.

THE PROBLEM WITH THE OBVIOUS FIX. Just launching alongside can CORRUPT the primary run. A
pre-registered stage carries a wall BACKSTOP that must not bind, and Stage 1's measured headroom
is 339 s on 2400 s -- 14%. A co-tenant that slows it by more than ~16% pushes a probe past the
backstop, the outcome becomes TIMEOUT_WALL, and the prereg then EXCLUDES it as non-reproducible.
That trades an 8-hour pre-registered result for some idle cycles.

THE THREE GUARANTEES THIS LANE ENFORCES, rather than asks for:

  1. IT CANNOT CORRUPT THE PRIMARY RUN.
     * refuses to launch when a primary solver process is live and `--headroom-pct` has not been
       asserted by the caller as adequate (default: refuse);
     * pins itself to the LPE half of the machine, so it does not take P-cores from the primary;
     * runs at BelowNormal priority, so it yields rather than competes.
     Affinity and priority bound the interference; the headroom gate is what makes it SAFE.

  2. ITS RESULTS CANNOT LEAK INTO THE PAPER.
     Everything is written under `runs/explore/`, and every artifact carries `"lane": "explore"`.
     Release gate G18 fails if any manuscript number reads from that tree. An exploratory result
     is a reason to run a REAL experiment, never a number to print.

  3. ITS TIMINGS ARE NEVER VALID.
     A co-tenant, LPE-pinned, deprioritised run produces a meaningless wall clock. Artifacts are
     stamped `"wall_valid": false`. Decision 47: det budgets protect the RESULT, not the CLOCK --
     so a trial here may report a bound, an incumbent or a gap, and never a time.

WHY THIS IS SAFE FOR THE TRIAL'S OWN RESULT. Deterministic tick budgets are load-independent, so
a det-limited trial on the LPE cores returns the same bound it would have returned alone -- only
slower. Anything wall-limited is rejected outright, because under co-tenancy a wall limit measures
the machine's mood.

Usage:
    python analysis/explore_lane.py --status
    python analysis/explore_lane.py --headroom-pct 40 -- python analysis/some_trial.py --det-tl 200000
"""
import argparse, json, os, subprocess, sys, time
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPLORE_DIR = os.path.join(ROOT, "runs", "explore")

# Lunar Lake: 4 P-cores then 4 LPE cores. The LPE half is the idle half the primary does not use.
# If a future machine numbers them differently this mask is the one thing to change.
LPE_MASK = 0xF0          # cores 4-7
PCORE_MASK = 0x0F        # cores 0-3


def live_solvers():
    """Other python processes that are plausibly the primary pipeline."""
    out = []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process python -ErrorAction SilentlyContinue | "
             "Select-Object Id,CPU,StartTime | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30)
        d = json.loads(r.stdout or "[]")
        d = d if isinstance(d, list) else [d]
        me = os.getpid()
        for p in d:
            if p.get("Id") and p["Id"] != me:
                out.append(p)
    except Exception:
        pass
    return out


def status():
    procs = live_solvers()
    print("EXPLORE LANE STATUS")
    print("  primary python processes live : %d" % len(procs))
    for p in procs:
        cpu = p.get("CPU") or 0
        print("    pid %-8s cpu_s %-12.0f" % (p.get("Id"), cpu))
    print("  LPE mask 0x%02X (cores 4-7), P-core mask 0x%02X" % (LPE_MASK, PCORE_MASK))
    print("  explore tree : %s" % os.path.relpath(EXPLORE_DIR, ROOT))
    if procs:
        print("")
        print("  A primary run is LIVE. This lane will refuse to launch unless you assert its")
        print("  wall headroom with --headroom-pct. Headroom is (backstop - observed wall) /")
        print("  backstop for the primary's slowest completed unit. Below 25% the answer is no:")
        print("  a co-tenant that pushes a pre-registered probe past its backstop converts a")
        print("  valid result into TIMEOUT_WALL, which the prereg then excludes.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--headroom-pct", type=float, default=None,
                    help="asserted wall headroom of the LIVE primary run, in percent. Required "
                         "when anything else is running. Below --min-headroom the lane refuses.")
    ap.add_argument("--min-headroom", type=float, default=25.0)
    ap.add_argument("--label", default="trial", help="goes in the artifact path and the marker")
    ap.add_argument("--allow-no-det", action="store_true",
                    help="permit a command with no --det-tl/--det-budget. Off by default: a "
                         "wall-limited trial under co-tenancy measures the machine, not the idea.")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()

    if a.status:
        return status()

    cmd = [c for c in a.cmd if c != "--"]
    if not cmd:
        print("!! nothing to run. Pass the trial command after --")
        return 2

    # ---- GUARD 1: do not corrupt the primary run ------------------------------------------
    procs = live_solvers()
    if procs:
        if a.headroom_pct is None:
            print("!! REFUSING: %d primary process(es) live and --headroom-pct not asserted."
                  % len(procs))
            print("   A co-tenant that slows a pre-registered stage past its wall backstop turns")
            print("   a valid result into TIMEOUT_WALL, which the prereg excludes. Measure the")
            print("   primary's headroom first, then assert it. `--status` explains how.")
            return 3
        if a.headroom_pct < a.min_headroom:
            print("!! REFUSING: asserted headroom %.0f%% is below the %.0f%% floor."
                  % (a.headroom_pct, a.min_headroom))
            print("   Wait for the primary stage, or raise its wall backstop and re-launch IT")
            print("   -- never squeeze the trial in beside a stage that cannot absorb it.")
            return 3

    # ---- GUARD 2: det-limited only ---------------------------------------------------------
    joined = " ".join(cmd)
    if not a.allow_no_det and not any(k in joined for k in ("--det-tl", "--det-budget", "det_tl")):
        print("!! REFUSING: no deterministic budget in the command.")
        print("   Under co-tenancy a wall limit measures the machine's mood, not the idea.")
        print("   Add --det-tl, or pass --allow-no-det and accept that the result is not")
        print("   reproducible and cannot be compared with anything.")
        return 4

    # ---- GUARD 3: quarantine the output ----------------------------------------------------
    run_dir = os.path.join(EXPLORE_DIR, "%s_%d" % (a.label, int(time.time())))
    os.makedirs(run_dir, exist_ok=True)
    marker = dict(lane="explore", label=a.label, cmd=cmd,
                  started=time.strftime("%Y-%m-%dT%H:%M:%S"),
                  wall_valid=False,
                  affinity="LPE 0x%02X" % LPE_MASK, priority="BelowNormal",
                  co_tenant=len(procs),
                  warning="EXPLORATORY. Never cite from this tree; release gate G18 enforces it. "
                          "Timings are invalid by construction (co-tenant, LPE-pinned, "
                          "deprioritised). A result here is a reason to run a real experiment.")
    json.dump(stamped(marker, __file__), open(os.path.join(run_dir, "_EXPLORE_LANE.json"), "w"), indent=1)

    # ---- launch, pinned and deprioritised --------------------------------------------------
    log = os.path.join(run_dir, "trial.log")
    ps = ("$p = Start-Process -FilePath '%s' -ArgumentList '%s' -PassThru "
          "-RedirectStandardOutput '%s' -RedirectStandardError '%s' -WindowStyle Hidden; "
          "Start-Sleep -Milliseconds 300; "
          "try { $p.ProcessorAffinity = [IntPtr]%d; $p.PriorityClass = 'BelowNormal' } catch {}; "
          "$p.Id"
          % (cmd[0], "','".join(cmd[1:]), log, log + ".err", LPE_MASK))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    pid = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else "?"
    print("EXPLORE LANE launched")
    print("  pid       : %s" % pid)
    print("  affinity  : LPE cores 4-7 (0x%02X), priority BelowNormal" % LPE_MASK)
    print("  artifacts : %s" % os.path.relpath(run_dir, ROOT))
    print("  co-tenant : %d primary process(es) live, headroom asserted %s"
          % (len(procs), ("%.0f%%" % a.headroom_pct) if a.headroom_pct is not None else "n/a"))
    print("")
    print("  Timings from this run are INVALID and the tree is quarantined from the manuscript.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
