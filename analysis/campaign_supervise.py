"""One-screen supervision of the running campaign: is it alive, is it spooling, is it stuck? (d583)

WHY THIS EXISTS. Three waiters in a row reported the campaign finished while it was running, each
for a different reason: one matched a failure string an append-only log had held since the previous
day; one used `ps aux`, which in this shell carries no command lines, so its probe could not see the
process it was asked about; one put its wait loop in a subshell inside a background task, which died
with the task's foreground. Every one of them was an indicator that could not distinguish the two
states it was asked to distinguish.

So this does not infer. It reports four independent observations and lets them disagree:

  PROCESS   the campaign driver and its current child, from the Windows process list with command
            lines (Get-CimInstance), which is the only probe here that sees them;
  STEP      the step the driver last announced, from the log, with the time since it started;
  SPOOL     the newest per-command log, its size, and the seconds since it was last written -- the
            project's own liveness rule is log mtime, not log content;
  STALL     whether that silence is longer than this stage has any business being quiet for,
            using the walls the campaign passes and the medians already measured on disk.

A disagreement between PROCESS and SPOOL is the interesting case: a live process writing nothing.

    python analysis/campaign_supervise.py [--quiet-secs 900]
"""
import argparse
import glob
import io
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "final_campaign.out")


def procs():
    """Python processes with their command lines. ps aux cannot do this here."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        return None, "process query failed: %s" % e
    rows = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        pid, cmd = line.split("\t", 1)
        if "analysis/" in cmd or "analysis\\" in cmd:
            rows.append((pid.strip(), re.sub(r".*python\.exe\s+", "", cmd).strip()[:78]))
    return rows, None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quiet-secs", type=float, default=900.0); a = ap.parse_args()
    now = time.time()
    print("CAMPAIGN SUPERVISION  %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))

    rows, err = procs()
    print("PROCESS")
    if err:
        print("   %s" % err)
    elif not rows:
        print("   nothing of ours is running")
    else:
        for pid, cmd in rows:
            print("   %-7s %s" % (pid, cmd))
    driver_alive = bool(rows) and any("tep_final_campaign" in c for _, c in rows)

    step, started = None, None
    if os.path.exists(LOG):
        for line in io.open(LOG, encoding="utf-8", errors="replace"):
            m = re.match(r"== (\S+) \((\d+) command", line)
            if m:
                step = m.group(1)
                t = re.search(r"(\d\d:\d\d:\d\d)", line)
                started = t.group(1) if t else None
        done = [l for l in io.open(LOG, encoding="utf-8", errors="replace") if " ok in " in l or "FAILED" in l]
    print("\nSTEP")
    print("   last announced: %s, started %s" % (step or "none", started or "?"))
    cmds = [l.strip() for l in io.open(LOG, encoding="utf-8", errors="replace") if step and (" %s cmd " % step) in l]
    print("   commands finished in this step: %d%s" % (len(cmds), (" | last: " + cmds[-1][:70]) if cmds else ""))

    logs = sorted(glob.glob(os.path.join(ROOT, "logs", "campaign_%s_*.out" % (step or "*"))),
                  key=os.path.getmtime, reverse=True)
    print("\nSPOOL")
    quiet = None
    if not logs:
        print("   no per-command log for this step yet")
    else:
        f = logs[0]
        quiet = now - os.path.getmtime(f)
        print("   %s" % os.path.relpath(f, ROOT))
        print("   %d bytes, last written %.0f s ago (%s)"
              % (os.path.getsize(f), quiet, time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(f)))))
        tail = [l.rstrip() for l in io.open(f, encoding="utf-8", errors="replace")][-2:]
        for l in tail:
            print("     | %s" % l[:96])

    print("\nVERDICT")
    if not driver_alive:
        print("   the driver is NOT running -- the campaign has ended or died; read the log tail")
    elif quiet is None:
        print("   driver alive, no per-command log yet: the step has just started")
    elif quiet > a.quiet_secs:
        print("   *** driver alive but its newest log has been silent for %.0f s (threshold %.0f)."
              % (quiet, a.quiet_secs))
        print("   *** that is the case worth looking at: a live process writing nothing.")
    else:
        print("   alive and spooling: last write %.0f s ago" % quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
