# ===================== RED FLAG -- TEP USE ONLY (2026-09-28) =====================
# This file REACHES K's FORMULATION (solver/engines/fixopt.py -> build_joint_model ->
# integratedJointModel). The standing constraint is that K's formulation is never part
# of our solution (d449, d451), and the fixopt-based work was archived and locked under
# archive/fixopt_locked/ on 2026-09-28.
#
# THIS FILE WAS NOT ARCHIVED because the admissible TEP path still depends on it.
# It is permitted ONLY where that dependency already exists. It must not be imported by
# new work, and no result derived from it may be reported without saying so.
#
# The load-bearing case: tep_cg_bound.master_ip calls assemble_precluster.retime, which
# builds K's joint model. So every master_ip result passes through K's formulation --
# which contradicts d451's claim that retime was replaced. Unresolved; see
# archive/fixopt_locked/LOCK.md.
# =================================================================================

"""Budget-matched primal over one family, with a gate that refuses to launch on a broken primal.

Pre-run audit: validation/runaudits/budget_matched_C_n100.md (d229).

THE COMPARISON. K's run time buys a bound and an incumbent together. Ours separates them, so a
like-for-like comparison gives the primal the remainder of their budget after our bound is paid:

    primal budget = 14400 (K's uniform cap, verified at source) - 0.087 (our AB bound) = 14399.9 s

Both sides then spend the same clock producing the same two products, which is what
RT_LEG_DESIGN section 4.1 says the naive ratio fails to do. Time is a CONSTANT here, not a
quantity being compared. No speed claim is made.

THE GATE. A 16-hour batch on an unvalidated primal is exactly the waste this exists to prevent.
It refuses unless ALL hold:

    * runs/oracle/v4smoke.json verdict == PASS   (19/19 PRODUCTION and verifier3-ACCEPT)
    * release gate G21 passes  (oracle L2 current and not stale)
    * release gate G22 passes  (code agrees with the ambiguity register)
    * solver/ and joint_model_gurobi.py are CLEAN in git, so the batch runs the validated code
      and not an uncommitted edit

Any failure is written to the log and the script exits WITHOUT launching.

    python analysis/launch_budget_matched.py --family C --size 100 [--dry-run]
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

OUT = os.path.join(ROOT, "runs", "budget_matched")
K_CAP = 14400.0
LB_SECONDS = 0.087                 # AB bound, mean per cell -- see bigm/ab4 timings
FAMILIES = {"C": ["C20%d" % i for i in range(1, 9)],
            "R": ["R2%02d" % i for i in range(1, 12)],
            "RC": ["RC20%d" % i for i in range(1, 9)]}


def gate():
    """Every reason not to launch. Returns a list of failures; empty means go."""
    bad = []
    v4 = os.path.join(ROOT, "runs", "oracle", "v4smoke.json")
    if not os.path.exists(v4):
        bad.append("runs/oracle/v4smoke.json missing -- the alignment smoke has not finished")
    else:
        d = json.load(open(v4, encoding="utf-8"))
        if d.get("verdict") != "PASS":
            bad.append("v4 smoke verdict is %s, not PASS (%s)"
                       % (d.get("verdict"), "; ".join(d.get("failures", []))[:160]))
        elif d.get("production") != d.get("runs") or d.get("accept") != d.get("runs"):
            bad.append("v4 smoke: %s/%s PRODUCTION, %s/%s ACCEPT -- not all clean"
                       % (d.get("production"), d.get("runs"), d.get("accept"), d.get("runs")))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis", "release_gate.py")],
                       capture_output=True, text=True, cwd=ROOT)
    for g in ("G21", "G22"):
        line = [l for l in (r.stdout or "").splitlines() if (" %s " % g) in l]
        if not line:
            bad.append("%s did not report" % g)
        elif "**FAIL**" in line[0]:
            bad.append("%s FAILS: %s" % (g, line[0].strip()[:150]))
    st = subprocess.run(["git", "status", "--porcelain", "solver", "joint_model_gurobi.py"],
                        capture_output=True, text=True, cwd=ROOT)
    if (st.stdout or "").strip():
        bad.append("uncommitted changes in solver/ or joint_model_gurobi.py -- the batch would "
                   "not run the validated code: %s" % st.stdout.strip()[:140])
    return bad


def canary(cell, size, seed, threads, budget=120.0):
    """Run ONE cell at a tiny budget and validate the WHOLE output path before committing hours.

    Catches at first occurrence, not at batch end: a dump written to the wrong name or not at
    all, a dump the verifier rejects, a dump whose provenance is not PRODUCTION because a flag
    did not reach the engine, an objective that is absent or absurd. Each of those would
    otherwise surface after 16 hours of solving.
    """
    import verifier3
    dump = os.path.join(OUT, "canary_%s_n%d.json" % (cell, size))
    log = os.path.join(ROOT, "logs", "canary_%s_n%d.out" % (cell, size))
    if os.path.exists(dump):
        os.remove(dump)
    cmd = [sys.executable, os.path.join(ROOT, "solver", "engines", "fixopt.py"),
           "--instance", cell, "--size", str(size), "--seed", str(seed),
           "--budget", str(budget), "--threads", str(threads),
           "--variant", "canary", "--dump-best", dump]
    with open(log, "w", encoding="utf-8") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
    bad = []
    if r.returncode != 0:
        bad.append("engine exited %d -- see %s" % (r.returncode, os.path.relpath(log, ROOT)))
    if not os.path.exists(dump):
        bad.append("NO DUMP at the expected path %s -- a filename or write problem that would "
                   "have surfaced only at batch end" % os.path.relpath(dump, ROOT))
        return bad
    try:
        sol = json.load(open(dump, encoding="utf-8"))
    except Exception as e:
        bad.append("dump is not readable JSON (%s)" % type(e).__name__)
        return bad
    if not isinstance(sol.get("objVal"), (int, float)) or sol["objVal"] <= 0:
        bad.append("objVal is %r -- absent or absurd" % sol.get("objVal"))
    run = verifier3.verify(dump)
    if run.verdict() != verifier3.ACCEPT:
        bad.append("verifier3 says %s on the canary incumbent" % run.verdict())
    if run.meta.get("provenance") != "PRODUCTION":
        bad.append("provenance is %s, not PRODUCTION (%s) -- a flag did not reach the engine"
                   % (run.meta.get("provenance"), "; ".join(run.meta.get("provenance_reasons") or [])))
    txt = open(log, encoding="utf-8", errors="replace").read()
    if "+improve" not in txt:
        bad.append("the log shows no improvement line -- the search may not be running")
    return bad


def spool_ok(logs, wait=120):
    """After launch, confirm every log is actually GROWING. A silent process is a dead one."""
    first = {p: (os.path.getsize(p) if os.path.exists(p) else -1) for p in logs}
    time.sleep(wait)
    stalled = []
    for p in logs:
        now = os.path.getsize(p) if os.path.exists(p) else -1
        if now <= 0:
            stalled.append("%s is empty %ds after launch" % (os.path.basename(p), wait))
        elif now == first[p]:
            stalled.append("%s has not grown in %ds" % (os.path.basename(p), wait))
    return stalled


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="C", choices=sorted(FAMILIES))
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--concurrent", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    budget = K_CAP - LB_SECONDS

    print("BUDGET-MATCHED PRIMAL -- family %s, |C| = %d" % (a.family, a.size))
    print("   budget = %.1f - %.3f = %.1f s per cell   threads %d   concurrent %d"
          % (K_CAP, LB_SECONDS, budget, a.threads, a.concurrent))
    print()
    bad = gate()
    if bad:
        print("   REFUSING TO LAUNCH -- %d gate failure(s):" % len(bad))
        for b in bad:
            print("      %s" % b)
        print()
        print("   A 16-hour batch on an unvalidated primal is the waste this gate exists for.")
        json.dump(stamped({"launched": False, "gate_failures": bad,
                   "when": time.strftime("%Y-%m-%dT%H:%M:%S")}, __file__),
                  open(os.path.join(OUT, "launch_%s_n%d.json" % (a.family, a.size)), "w"),
                  indent=1)
        return 1
    print("   gate: v4 smoke PASS, G21 PASS, G22 PASS, solver tree clean")

    from solver.engines.fixopt import k_setting
    prox, exhibit, basis = k_setting(a.size)
    cells = FAMILIES[a.family]
    print("   proximity %s from %s (%s) -- never a literal" % (prox, exhibit, basis))
    print("   %d cells, est %.1f h wall" % (len(cells), len(cells) * budget / a.concurrent / 3600))
    print()
    if a.dry_run:
        print("   --dry-run: not launching")
        return 0

    # CANARY FIRST. 2 minutes to validate the whole output path, rather than discovering a
    # filename, provenance or verifier problem after 16 hours of solving.
    print("   canary: %s at 120s, validating dump path / verifier / provenance ..." % cells[0],
          flush=True)
    cbad = canary(cells[0], a.size, a.seed, a.threads)
    if cbad:
        print("   CANARY FAILED -- not launching the batch:")
        for b in cbad:
            print("      %s" % b)
        json.dump(stamped({"launched": False, "canary_failures": cbad,
                   "when": time.strftime("%Y-%m-%dT%H:%M:%S")}, __file__),
                  open(os.path.join(OUT, "launch_%s_n%d.json" % (a.family, a.size)), "w"),
                  indent=1)
        return 1
    print("   canary OK: dump written, verifier3 ACCEPT, provenance PRODUCTION, search active")
    print()

    running, logs = [], []
    for cell in cells:
        while len([p for p in running if p.poll() is None]) >= a.concurrent:
            time.sleep(10)
        dump = os.path.join(OUT, "bm_%s_n%d_s%d.json" % (cell, a.size, a.seed))
        log = os.path.join(ROOT, "logs", "bm_%s_n%d_s%d.out" % (cell, a.size, a.seed))
        cmd = [sys.executable, os.path.join(ROOT, "solver", "engines", "fixopt.py"),
               "--instance", cell, "--size", str(a.size), "--seed", str(a.seed),
               "--budget", str(budget), "--threads", str(a.threads),
               "--variant", "budgetmatched", "--dump-best", dump]
        fh = open(log, "w", encoding="utf-8")
        running.append(subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT))
        logs.append(log)
        print("   launched %s  (%d running)" % (cell, len([p for p in running if p.poll() is None])),
              flush=True)
        if len(logs) == a.concurrent:
            # SPOOL CHECK on the first wave only -- a silent log is a dead process, and finding
            # that out now costs 2 minutes instead of 16 hours.
            st = spool_ok(logs)
            if st:
                print("   SPOOL CHECK FAILED -- killing the batch:")
                for x in st:
                    print("      %s" % x)
                for pr in running:
                    pr.terminate()
                json.dump(stamped({"launched": False, "spool_failures": st,
                           "when": time.strftime("%Y-%m-%dT%H:%M:%S")}, __file__),
                          open(os.path.join(OUT, "launch_%s_n%d.json" % (a.family, a.size)), "w"),
                          indent=1)
                return 1
            print("   spool check OK: both logs growing", flush=True)
    for p in running:
        p.wait()
    print()
    print("   all %d cells finished. Read the dumps with verifier3 before any mean is taken --"
          % len(cells))
    print("   a mean over fewer than %d VERIFIED cells is not comparable to K's %d-cell mean."
          % (len(cells), len(cells)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
