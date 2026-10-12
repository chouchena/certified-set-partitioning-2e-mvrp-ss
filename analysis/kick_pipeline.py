"""The kick-calibration pipeline, end to end, gated on tonight's runs.

  0  GATE     wait until no solver/harness process is live, and surface the
              baseline-reproduction control's verdict (the extension result is only
              trustworthy if that control says "no code regression")
  1  PATCH    add --dump-kick-states to fixopt (changes code_hash -- hence the gate),
              then verify with a real 150s smoke that states actually appear
  2  HARVEST  full 2400s runs dumping kick states, stratified by run position
  3  BENCH-q  base-depth kicks across the corpus -> q(t). THE GATE QUESTION: breadth
              only works if q > 0 late, since H = 1-(1-q)^k
  4  BENCH-d  deeper re-solves of the SAME failed draws -> conversion curve. Settles
              escalate-on-miss, which the escalating design's own logs cannot (depth
              there was assigned BY the outcome: fixopt.py:454 breaks early on success,
              :463 resets the TL on success)
  5  REPORT   q(t), conversion curve, best-of-k surface, and the value(k,d) optimum

Stage 3 is deliberately first and cheap (~40 min): if q_late is ~0 it kills the breadth
idea before stage 4 spends an hour on depth.

Run:  python analysis/kick_pipeline.py            (full, gated)
      python analysis/kick_pipeline.py --from 3   (resume at a stage)
"""
import argparse, glob, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "kick_pipeline.log")
STATES = os.path.join(ROOT, "runs", "kickstates")
VALID = os.path.join(ROOT, "validation")


def say(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def live_solvers():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { "
             "$_.CommandLine -like '*fixopt.py*' -or $_.CommandLine -like '*calib_run*' -or "
             "$_.CommandLine -like '*captl_ext_driver*' -or $_.CommandLine -like '*captl_ctrl*' }).Count"],
            capture_output=True, text=True, timeout=60).stdout.strip()
        return int(out or 0)
    except Exception:
        return -1


def ctrl_finished():
    """The control must have RUN TO COMPLETION, not merely be absent from the process list.

    An idle process list is NOT sufficient: the control runner polls on a 120s sleep, so
    between the extension exiting and the control launching there is a window in which zero
    solvers are live. The first version of this gate fired in exactly that window, patched
    fixopt, and the control then started on the PATCHED code_hash (a2aba93c) instead of the
    extension's (aeca393c) -- which would have silently voided the one run that validates
    tonight's entire result. Wait for the completion marker instead.
    """
    p = os.path.join(ROOT, "runs", "captl_ctrl.log")
    if not os.path.exists(p):
        return False
    return "[ctrl] done" in open(p, encoding="utf-8", errors="replace").read()


def stage0_gate():
    say("STAGE 0: waiting for extension + control to clear (solver code must stay frozen)")
    while True:
        n, done = live_solvers(), ctrl_finished()
        if n == 0 and done:
            break
        say(f"  holding: {n} solver processes live, control finished={done}")
        time.sleep(120)
    say("  cores free AND control complete")
    p = os.path.join(ROOT, "runs", "captl_ctrl.log")
    if os.path.exists(p):
        tail = [l.rstrip() for l in open(p, encoding="utf-8") if l.strip()][-8:]
        say("  --- baseline-reproduction control verdict ---")
        for l in tail:
            say("   " + l)
        if any("CODE REGRESSION" in l for l in tail):
            say("  !! CONTROL SAYS CODE REGRESSION: the extension's 6/6 result is contaminated.")
            say("  !! Calibration still measures kicks correctly, but do NOT bank the cap-TL")
            say("  !! comparison on it. Flagging and continuing.")
    return True


def stage1_patch():
    say("STAGE 1: patch fixopt with --dump-kick-states + verify (150s smoke)")
    r = subprocess.run([PY, os.path.join(ROOT, "analysis", "kick_dump_patch.py")],
                       cwd=ROOT, capture_output=True, text=True)
    for l in (r.stdout + r.stderr).splitlines():
        say("   " + l)
    if r.returncode != 0:
        say("  PATCH/VERIFY FAILED -- stopping"); return False
    return True


def stage2_harvest():
    say("STAGE 2: harvest kick-state corpus (2 cells x 2 seeds x 2400s, ~2.7h)")
    r = subprocess.run([PY, os.path.join(ROOT, "analysis", "kick_harvest.py"),
                        "--cells", "R203,R211", "--seeds", "10,11"], cwd=ROOT)
    n = len(glob.glob(os.path.join(STATES, "*", "kickstate_*.json")))
    say(f"  corpus size: {n} states")
    return n > 0


def _bench(tag, cell, depths, draws, nshard=4):
    """Launch nshard 1-core workers per cell over the corpus."""
    procs = []
    for i in range(nshard):
        out = os.path.join(VALID, f"kickbench_{tag}_{cell}_{i}.jsonl")
        cmd = [PY, os.path.join(ROOT, "analysis", "kick_bench.py"),
               "--states", os.path.join(STATES, f"{cell}_s*", "kickstate_*.json"),
               "--cell", cell, "--draws", str(draws), "--depths", depths,
               "--cores", "1", "--shard", f"{i}/{nshard}", "--out", out]
        procs.append(subprocess.Popen(cmd, cwd=ROOT,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))
    return procs


def stage3_q():
    say("STAGE 3: q(t) at base depth -- 8 concurrent 1-core workers (~35-45 min)")
    ps = _bench("q", "R203", "20", 20) + _bench("q", "R211", "20", 20)
    for p in ps:
        p.wait()
    n = sum(1 for f in glob.glob(os.path.join(VALID, "kickbench_q_*.jsonl"))
            for _ in open(f, encoding="utf-8"))
    say(f"  {n} kick solves recorded")
    subprocess.run([PY, os.path.join(ROOT, "analysis", "kick_calibrate.py"),
                    "--bench", os.path.join(VALID, "kickbench_q_*.jsonl")], cwd=ROOT)
    return n > 0


def stage4_depth():
    say("STAGE 4: conversion curve -- same draws re-solved at 40/80/160s (~1-2h)")
    ps = _bench("d", "R203", "20,40,80,160", 12) + _bench("d", "R211", "20,40,80,160", 12)
    for p in ps:
        p.wait()
    say("  depth bench complete")
    return True


def stage5_report():
    say("STAGE 5: calibration report")
    subprocess.run([PY, os.path.join(ROOT, "analysis", "kick_calibrate.py"),
                    "--bench", os.path.join(VALID, "kickbench_*.jsonl")], cwd=ROOT)
    say("PIPELINE COMPLETE")
    return True


STAGES = [(0, stage0_gate), (1, stage1_patch), (2, stage2_harvest),
          (3, stage3_q), (4, stage4_depth), (5, stage5_report)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="end", type=int, default=5)
    a = ap.parse_args()
    say(f"=== kick-calibration pipeline: stages {a.start}..{a.end} ===")
    for idx, fn in STAGES:
        if idx < a.start or idx > a.end:
            continue
        if not fn():
            say(f"STOPPED at stage {idx}")
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
