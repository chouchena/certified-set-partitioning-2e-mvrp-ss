"""The run queue, with the checks the shell queue did not have.

WHY IT REPLACES THE SHELL SCRIPT. The shell queue was eight commands each suffixed with a
swallow-the-error idiom. It had no idea whether a script could even be imported, whether it wrote
the file it was supposed to write, or whether what it wrote could be attributed to a code version.
On 2026-09-20 it died at line 5 on a quoting error and logged one line; separately, 26 of the
scripts it invokes were left syntactically broken for an hour, and the queue would have run every
one of them into a traceback and carried on. Both failures are the same failure: nothing looked.

WHAT THIS CHECKS, and when.

  BEFORE ANY STEP RUNS (preflight, seconds)
    every script in the plan compiles, and every script that declares a result actually contains
    a stamped writer. A plan that cannot produce provenanced output is refused whole -- not
    discovered at step six, after five hours.

  WHILE A STEP RUNS (watchdog)
    the step's log must grow within --spool-grace seconds of launch. A step that produces no
    output for that long is not working; it is reported at once rather than waiting out a
    timeout that may be hours away.

  AFTER EACH STEP (postcheck)
    every declared output exists, parses as JSON, and carries _provenance.code_hash. An
    unstamped result is a FAILURE here, not a warning -- an unattributable number is not a
    result. The step's dependents are then skipped, so nothing derives from it.

WAVES. Wave A is analysis only and runs a few at a time. Everything from wave B on is Gurobi-bound
on a four-thread machine, so it runs strictly one at a time; overlapping solves would make every
runtime in the queue meaningless.

    python analysis/queue_run.py --check            preflight and plan, run nothing
    python analysis/queue_run.py --waves A          run one wave
    python analysis/queue_run.py --waves A,B,C,D    run several, in order
"""
import argparse
import ast
import concurrent.futures as cf
import io
import json
import os
import subprocess
import sys
import threading
import time

import gate_importable as _g24
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOGS = os.path.join(ROOT, "logs")
ORACLE = os.path.join(ROOT, "runs", "oracle")
STATE = os.path.join(ROOT, "runs", "queue_state.json")


def S(name, wave, script, args=(), out=(), needs=(), timeout=3600, log=None, waits=None):
    return dict(name=name, wave=wave, script=script, args=[str(x) for x in args],
                out=list(out), needs=list(needs), timeout=timeout,
                log=log or (name + ".out"), waits=waits)


# --------------------------------------------------------------------------------------------
# THE PLAN. Ordered cheapest-first inside each wave, so the picture forms early and a defect
# surfaces on a two-minute step rather than a three-hour one.
# --------------------------------------------------------------------------------------------
PLAN = [
    # ---- wave A: no solving. Re-derives everything quarantined for want of a code stamp. ----
    S("L2", "A", "oracle_L2.py", out=["L2.json"], timeout=1800),
    S("L2_controls", "A", "oracle_L2_controls.py", out=["L2_controls.json"], timeout=1800),
    S("L2c", "A", "oracle_L2c.py", out=["L2c.json"], timeout=1200),
    S("L2d", "A", "oracle_L2d.py", out=["L2d.json"], timeout=1200),
    S("L1a", "A", "oracle_L1a.py", out=["L1a.json"], timeout=1800),
    S("L1a_mintr", "A", "oracle_L1a_mintransfers.py", out=["L1a_mintransfers.json"],
      timeout=1200),
    S("L0_L1b", "A", "oracle_L0_L1b.py", out=["L0.json", "L1b.json"], timeout=2400),
    S("power_slack", "A", "oracle_power_and_slack.py", out=["power_and_slack.json"],
      timeout=1800),
    S("residue", "A", "oracle_residue.py", out=["residue.json"], timeout=900),
    S("bigm_preval", "A", "bigm_prevalence.py", out=["bigm_prevalence.json"], timeout=2400),
    S("c26_binding", "A", "c26_when_binding.py", out=["c26_when_binding.json"], timeout=2400),

    # ---- wave B: cheap solves. step2 is RE-AGGREGATED, never re-solved: its fixopt dumps
    #      already carry full stamps, so five hours of solving does not happen twice. ----
    # step2_repair comes FIRST: an import-check gate reached kill_tree() on 2026-09-20 and
    # destroyed two of step 2's 36 dumps. Re-aggregating before repairing would bank a
    # 34-dump campaign as if it were the whole thing.
    S("step2_repair", "B", "step2_repair.py", out=["step2_repair.json"],
      timeout=3600, waits="step2_bigm_n50n100.py"),
    S("step2_reagg", "B", "step2_reaggregate.py", out=["step2_bigm.json"],
      needs=["step2_repair"], timeout=10800),
    S("v3smoke", "B", "smoke_grid_v3.py", out=[], timeout=3600),
    S("v4smoke", "B", "smoke_grid_v4.py", out=["v4smoke.json"], needs=["v3smoke"],
      timeout=3600),
    S("step1_n10", "B", "step1_validbigm.py", ["--sizes", "10", "--threads", "4"],
      out=["step1_validbigm_n10.json"], timeout=7200),
    S("arb_ctl_p1", "B", "arbiter_controls.py", ["--sats", "1"],
      out=["arbiter_controls_p1.json"], timeout=3600),
    S("arb_ctl_p2", "B", "arbiter_controls.py", ["--sats", "2"],
      out=["arbiter_controls_p2.json"], timeout=3600),
    S("FR1_p1", "B", "arbiter_vs_milp.py", ["--n", "4", "--sats", "1"],
      out=["FR1_arbiter_vs_milp_n4_p1.json"], needs=["arb_ctl_p1"], timeout=7200),
    S("FR1_p2", "B", "arbiter_vs_milp.py", ["--n", "4", "--sats", "2"],
      out=["FR1_arbiter_vs_milp_n4_p2.json"], needs=["arb_ctl_p2"], timeout=7200),

    # ---- wave B2: the paired big-M smoke, re-run with a CONTROL arm that is actually a
    #      control. The first run compared valid-big-M against itself, because smoke_grid_v3
    #      relied on an engine default that has since flipped, and reported +0.000 on all 15
    #      cells. v4smoke now voids a pairing whose two arms carry the same _valid_bigm. ----
    S("v3smoke_ctl", "B2", "smoke_grid_v3.py", out=[], timeout=3600, log="v3smoke_ctl.out"),
    S("v4smoke_paired", "B2", "smoke_grid_v4.py", out=["v4smoke.json"],
      needs=["v3smoke_ctl"], timeout=3600, log="v4smoke_paired.out"),

    # ---- wave C: moderate solves. ----
    S("c26_price", "C", "c26_price_exact.py",
      ["--cell", "C201", "--size", "40", "--threads", "4"],
      out=["c26_price_C201_n40.json"], timeout=7200),
    S("c26_structure", "C", "c26_structure_excluded.py",
      ["--cell", "C201", "--size", "40", "--threads", "4"],
      out=["c26_structure_C201_n40.json"], timeout=7200),
    S("greedy_grid", "C", "greedy_grid_full.py", out=["greedy_grid_full.json"], timeout=5400),
    S("L4", "C", "oracle_L4.py", ["--sizes", "40,50,100", "--tl", "300", "--threads", "4"],
      out=["L4.json"], timeout=14400),

    # ---- wave D: the expensive exact solves, and everything that reads them. ----
    S("L3", "D", "oracle_L3.py", ["--threads", "4"], out=["L3.json"], timeout=28800),
    S("L3_diag", "D", "oracle_L3_diag.py", ["--threads", "4"], out=["L3_diag.json"],
      needs=["L3"], timeout=14400),
    S("residuals", "D", "oracle_residuals.py", out=["residuals.json"],
      needs=["L3", "L0_L1b"], timeout=3600),
    S("L3b", "D", "oracle_L3b.py", out=["L3b.json"], timeout=14400),
    S("step1_n20n30", "D", "step1_validbigm.py", ["--sizes", "20,30", "--threads", "4"],
      out=["step1_validbigm_n20.json", "step1_validbigm_n30.json"], timeout=28800),
]

PARALLEL = {"A": 3}          # everything else is solver-bound and runs one at a time


def stamped_writer(path):
    """Does this script contain a writer that attaches provenance?"""
    try:
        return "json.dump(stamped(" in io.open(path, encoding="utf-8").read()
    except OSError:
        return False


def import_error(path):
    """Do this module's imports resolve, and does it do work merely by being imported?

    STATICALLY. An earlier version exec'd the module, on the reasoning that main() stays behind
    its __main__ guard. captl_ctrl_runner.py does its work in a module-level loop, so that
    version LAUNCHED four 2400-second calibration solves, twice. A preflight that can start a job
    is not a preflight. See analysis/gate_importable.py, which this delegates to.
    """
    import importlib.util as _ilu
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    sys.path[:] = ([os.path.join(ROOT, "analysis"), ROOT]
                   + [p for p in sys.path if p not in (os.path.join(ROOT, "analysis"), ROOT)])
    for name in sorted(_g24.top_level_imports(tree)):
        try:
            if _ilu.find_spec(name) is None:
                return "cannot resolve import %r" % name
        except Exception as e:
            return "cannot resolve import %r (%s)" % (name, type(e).__name__)
    work = _g24.work_at_import(tree)
    if work:
        return "does work at import time (%s) -- unsafe to import" % "; ".join(work)[:60]
    return None


def preflight(steps):
    print("PREFLIGHT -- a plan that cannot produce provenanced output is refused whole.")
    print()
    bad = []
    for s in steps:
        p = os.path.join(ROOT, "analysis", s["script"])
        if not os.path.exists(p):
            bad.append((s["name"], "script does not exist: analysis/" + s["script"]))
            continue
        try:
            ast.parse(io.open(p, encoding="utf-8").read(), filename=p)
        except SyntaxError as e:
            bad.append((s["name"], "will not parse: line %s %s" % (e.lineno, e.msg)))
            continue
        if s["out"] and not stamped_writer(p):
            bad.append((s["name"], "declares outputs but has no stamped writer"))
            continue
        # PARSING IS NOT IMPORTING. On 2026-09-20 a bulk patch inserted an import that resolves
        # only when ROOT is on sys.path, into 33 modules that never put it there. Every one
        # parsed; `compileall` passed on all of them; every one died on its import line. A
        # preflight that stops at ast.parse would have waved the whole plan through.
        err = import_error(p)
        if err:
            bad.append((s["name"], "parses but will not import: " + err))
    print("   steps %d   problems %d" % (len(steps), len(bad)))
    for n, why in bad:
        print("      REFUSED  %-14s %s" % (n, why))
    return not bad


def spool_grew(log, size0, grace):
    t = time.time()
    while time.time() - t < grace:
        if os.path.exists(log) and os.path.getsize(log) > size0:
            return True
        time.sleep(2)
    return False


def postcheck(s):
    """Every declared output must exist, parse, and name the code that made it."""
    problems = []
    for o in s["out"]:
        p = os.path.join(ORACLE, o)
        if not os.path.exists(p):
            problems.append(o + " was not written")
            continue
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except Exception as e:
            problems.append("%s is not readable JSON (%s)" % (o, type(e).__name__))
            continue
        ch = (d.get("_provenance") or {}).get("code_hash") if isinstance(d, dict) else None
        if not ch:
            problems.append(o + " carries no _provenance.code_hash -- unattributable")
    return problems


def run_step(s, grace, state, lock):
    log = os.path.join(LOGS, s["log"])
    size0 = os.path.getsize(log) if os.path.exists(log) else 0
    cmd = [PY, "-u", os.path.join("analysis", s["script"])] + s["args"]
    t0 = time.time()
    with io.open(log, "a", encoding="utf-8") as fh:
        fh.write("\n===== queue_run %s  %s =====\n"
                 % (s["name"], time.strftime("%Y-%m-%dT%H:%M:%S")))
        fh.flush()
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
        grew = spool_grew(log, size0, grace)
        if not grew and proc.poll() is None:
            print("   SPOOL SILENT  %-14s no output in %ds -- still running, flagged"
                  % (s["name"], grace), flush=True)
        try:
            rc = proc.wait(timeout=max(1.0, s["timeout"] - (time.time() - t0)))
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -9
    secs = round(time.time() - t0, 1)
    problems = postcheck(s) if rc == 0 else ["exit %d after %.0fs" % (rc, secs)]
    ok = (rc == 0) and not problems
    rec = dict(name=s["name"], wave=s["wave"], rc=rc, secs=secs, ok=ok, spooled=grew,
               problems=problems, log=os.path.relpath(log, ROOT), args=s["args"],
               when=time.strftime("%Y-%m-%dT%H:%M:%S"))
    with lock:
        state["steps"][s["name"]] = rec
        json.dump(stamped(state, __file__), io.open(STATE, "w", encoding="utf-8"), indent=1)
    print("   %-7s %-14s %8.1fs  %s" % ("OK" if ok else "FAILED", s["name"], secs,
                                        "" if ok else "; ".join(problems)[:110]), flush=True)
    return ok


def still_running(pattern):
    ps = ("(Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
          "Where-Object { $_.CommandLine -like '*" + pattern + "*' } | "
          "Measure-Object).Count")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    try:
        return int((r.stdout or "0").strip() or 0)
    except ValueError:
        return 0


def wait_for(pattern):
    """Never stop a running job -- wait it out. CLAUDE.md, standing rule."""
    shown = False
    while still_running(pattern):
        if not shown:
            print("   waiting for the running %s to finish -- it is never stopped" % pattern,
                  flush=True)
            shown = True
        time.sleep(30)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--waves", default="A,B,C,D")
    ap.add_argument("--spool-grace", type=int, default=120)
    a = ap.parse_args()
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(ORACLE, exist_ok=True)
    waves = [w.strip().upper() for w in a.waves.split(",") if w.strip()]
    steps = [s for s in PLAN if s["wave"] in waves]

    if not preflight(steps):
        print()
        print("QUEUE REFUSED. Nothing ran.")
        return 1
    print()
    for w in waves:
        n = len([s for s in PLAN if s["wave"] == w])
        how = ("up to %d at a time" % PARALLEL[w]) if w in PARALLEL else "one at a time"
        print("   wave %s  %2d step(s)  %s" % (w, n, how))
    if a.check:
        print()
        print("   --check only; nothing ran.")
        return 0

    lock = threading.Lock()
    # CARRY FORWARD. This used to start a fresh dict, so a later invocation erased every earlier
    # wave's record: wave B wiped wave A's measured seconds, and the only copy left was the
    # console log. A queue whose state file forgets the last run cannot answer "when did this
    # result's timing get measured", which is the question it exists to answer.
    prior = {}
    if os.path.exists(STATE):
        try:
            prior = (json.load(io.open(STATE, encoding="utf-8")) or {}).get("steps") or {}
        except Exception:
            prior = {}
    state = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "waves": waves, "steps": dict(prior)}
    print()
    for w in waves:
        todo = [s for s in steps if s["wave"] == w]
        print("WAVE %s -- %d step(s)" % (w, len(todo)), flush=True)
        pool = PARALLEL.get(w, 1)
        if pool == 1:
            for s in todo:
                done_ok = {k for k, v in state["steps"].items() if v["ok"]}
                unmet = [d for d in s["needs"] if d not in done_ok]
                if unmet:
                    print("   SKIPPED %-14s needs %s, which has not succeeded"
                          % (s["name"], ", ".join(unmet)), flush=True)
                    state["steps"][s["name"]] = dict(name=s["name"], wave=w, ok=False,
                                                     problems=["skipped: needs " +
                                                               ", ".join(unmet)])
                    continue
                if s.get("waits"):
                    wait_for(s["waits"])
                run_step(s, a.spool_grace, state, lock)
        else:
            with cf.ThreadPoolExecutor(max_workers=pool) as ex:
                list(ex.map(lambda st: run_step(st, a.spool_grace, state, lock), todo))
        print(flush=True)

    ok = [k for k, v in state["steps"].items() if v["ok"]]
    bad = [k for k, v in state["steps"].items() if not v["ok"]]
    print("QUEUE: %d ok, %d failed  -> %s" % (len(ok), len(bad), os.path.relpath(STATE, ROOT)))
    for k in bad:
        print("   FAILED %-14s %s" % (k, "; ".join(state["steps"][k]["problems"])[:100]))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
