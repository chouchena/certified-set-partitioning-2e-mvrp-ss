"""One-shot handoff: swap the running sequencer for the revised one at the stage-1 boundary.

The sequencer currently running holds the OLD stage list (no 1b DIVERS-SMOKE). Restarting it
now would re-run R206/RC206, which are already banked. So: wait for stage 1 to report DONE,
then replace the process with one that starts at 1b.

This is a ONE-SHOT handoff, not a recurring gate. The failure mode that bit us before -- a
poller firing inside another poller's sleep and patching solver code mid-comparison -- cannot
occur here: this touches no code, and the only thing it interrupts is SCALE-A, a 300s-per-run
screen whose partial results are disposable. Worst case we lose a couple of minutes of it.
"""
import argparse, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "master_sequence.log")


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] HANDOFF: {m}"
    print(line, flush=True)
    with open(os.path.join(ROOT, "runs", "seq_handoff.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def kill_tree():
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -like '*master_sequence*' -or "
                    "$_.CommandLine -like '*scale_screen*' -or "
                    "$_.CommandLine -like '*lb_coverage_run*' -or "
                    "$_.CommandLine -like '*easy_reduction*' -or "
                    "$_.CommandLine -like '*fixopt.py*' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True)



# Module-level code here is REACHABLE BY IMPORT. On 2026-09-20 an import-check gate
# exec'd this file; its body ran, kill_tree() force-killed every fixopt.py on the
# machine, and two runs of a live campaign were destroyed. Everything below is behind
# main() so that importing this module does nothing at all.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mark", default="STAGE 1 LB-COVERAGE DONE")
    ap.add_argument("--stages", default="1b,2,3,4,5")
    ARGS = ap.parse_args()
    MARK = ARGS.mark
    say("armed; waiting for stage 1 to finish")
    for _ in range(600):                      # 10h ceiling
        try:
            if os.path.exists(LOG) and MARK in open(LOG, encoding="utf-8", errors="replace").read():
                break
        except Exception:
            pass
        time.sleep(60)
    else:
        say("timed out waiting for stage 1; leaving the running sequencer alone"); sys.exit(1)

    say("stage 1 complete -- swapping in the revised sequence (1b onward)")
    time.sleep(5)
    kill_tree()
    time.sleep(5)
    out = open(os.path.join(ROOT, "runs", "master_sequence.out"), "a", encoding="utf-8")
    subprocess.Popen([PY, os.path.join(ROOT, "analysis", "master_sequence.py"),
                      "--stages", ARGS.stages],
                     cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    say(f"revised sequencer launched with stages: {ARGS.stages}")


if __name__ == "__main__":
    main()
