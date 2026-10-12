"""Check the quarantine AFTER EVERY CELL, not once per batch. Halts the campaign on a contradiction.

AUTHOR RULE, 2026-09-18, verbatim: *"I want to stop all runs after any quarantine except if
because no incumbent found by main solver ie. if verifier contradict main solver validity claim."*
AUTHOR RULE, 2026-09-28, verbatim: *"Monitor also quarantine after each cell run"*.

WHY A WATCHER AND NOT A LINE IN THE DRIVER. `analysis/quarantine_guard.py` has existed since
2026-09-18 and its own docstring says "Drivers call it BEFORE each batch". Measured today: the
campaign driver does not call it at all -- `grep -nE "invalid|quarantin|reject"
analysis/tep_final_campaign.py` returns nothing. Per batch is also the wrong granularity: a batch
here is hours and twenty-seven cells, so a contradiction on cell 2 keeps feeding twenty-five more
cells before anything reads the file. This watches per CELL, which is the granularity the author
asked for, and it works on a campaign that is ALREADY RUNNING -- editing the driver would not,
because Python has the module loaded.

WHAT COUNTS AS A TRIGGER. Any new or modified cell artifact under `runs/oracle/` matching the
campaign's own output patterns. On each one the watcher re-runs the guard.

WHAT COUNTS AS A HALT. A row in `runs/invalid/INDEX.md` that is untriaged AND was not there when
this watcher started. The baseline matters: a pre-existing backlog is the author's to triage, not
grounds for killing a live run. `seed_infeasible` -- the solver honestly finding no incumbent --
is never quarantined and never halts, which is the exception in the rule above.

TWO READS, FIVE SECONDS APART, before any halt. INDEX.md is appended to by a live process and a
half-written row must not kill a ten-hour campaign.

    python analysis/quarantine_watch.py                  # watch, halt on a new contradiction
    python analysis/quarantine_watch.py --no-halt        # watch and alarm only
    python analysis/quarantine_watch.py --once           # one pass, for the commit hook
"""
import argparse
import glob
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import quarantine_guard as QG

PY = sys.executable
LOG = os.path.join(ROOT, "logs", "quarantine_watch.out")
ART = os.path.join(ROOT, "runs", "oracle", "quarantine_watch.json")
HALTED = os.path.join(ROOT, "runs", "oracle", "campaign", "QUARANTINE_HALT")
PATTERNS = ("tep_cg_bound_*.json", "tep_selchain_*.json", "tep_select_chain_*.json",
            "tep_master_ip_*.json", "tep_*_best_of.json")


def say(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    # Under nohup, stdout is usually redirected INTO this same log; printing as well doubles
    # every line and a monitor you learn to skim is a monitor that stops being read.
    if sys.stdout.isatty():
        print(line, flush=True)
    try:
        with io.open(LOG, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
    except Exception:
        pass


def untriaged_ids():
    """Row identities the guard considers blocking. Identity, not a count: a count cannot tell a
    new contradiction from a triaged row being edited."""
    out = set()
    for r in QG.rows():
        if QG.is_untriaged(r):
            out.add("%s|%s|%s" % (r.get("ts"), r.get("run_id"), r.get("reason")))
    return out


def cell_artifacts():
    seen = {}
    for pat in PATTERNS:
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
            try:
                seen[p] = os.path.getmtime(p)
            except OSError:
                pass
    return seen


def campaign_pids():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                            "Where-Object { $_.CommandLine -like '*tep_final_campaign*' -or "
                            "$_.CommandLine -like '*tep_select_chain*' -or "
                            "$_.CommandLine -like '*run_full_grid*' }).ProcessId"],
                           capture_output=True, text=True, timeout=60)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def halt(new_rows, do_halt):
    say("QUARANTINE CONTRADICTION -- %d new untriaged row(s):" % len(new_rows))
    for k in sorted(new_rows):
        say("    %s" % k)
    pids = campaign_pids()
    if not do_halt:
        say("  --no-halt: NOT stopping the %d live run process(es) %s. This is alarm only." % (len(pids), pids))
        return
    say("  author rule 2026-09-18: a verifier/solver contradiction stops all runs. Killing %s" % (pids or "nothing -- no live run found"))
    for pid in pids:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Stop-Process -Id %d -Force" % pid],
                       capture_output=True, text=True)
    try:
        os.makedirs(os.path.dirname(HALTED), exist_ok=True)
        io.open(HALTED, "w", encoding="utf-8", newline="\n").write(
            "Halted %s by analysis/quarantine_watch.py.\nNew untriaged quarantine rows:\n%s\n\n"
            "Triage them in runs/invalid/INDEX.md (set triaged), delete this file, relaunch.\n"
            % (time.strftime("%Y-%m-%d %H:%M:%S"), "\n".join("  " + k for k in sorted(new_rows))))
    except Exception as e:
        say("  could not write the halt marker: %s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-halt", dest="halt", action="store_false", default=True)
    ap.add_argument("--once", action="store_true", help="one pass and exit; nonzero if blocking")
    ap.add_argument("--poll", type=float, default=30.0)
    a = ap.parse_args()

    base = untriaged_ids()
    if a.once:
        print("quarantine: %d untriaged row(s) in runs/invalid/INDEX.md" % len(base))
        for k in sorted(base):
            print("    %s" % k)
        return 1 if base else 0

    say("quarantine watch ARMED | baseline %d untriaged row(s) | halt-on-contradiction %s"
        % (len(base), "ON" if a.halt else "OFF (alarm only)"))
    if base:
        say("  the %d pre-existing row(s) are the author's to triage; they do not halt anything." % len(base))
    known = cell_artifacts()
    say("  watching %d cell artifact(s) under runs/oracle/ for the next cell to land" % len(known))
    cells_seen, fired = 0, 0
    while True:
        time.sleep(a.poll)
        now = cell_artifacts()
        fresh = [p for p, m in now.items() if known.get(p) != m]
        known = now
        if not fresh:
            continue
        cells_seen += len(fresh)
        cur = untriaged_ids()
        new = cur - base
        names = ", ".join(os.path.basename(p) for p in sorted(fresh)[:3])
        if not new:
            say("cell(s) landed (%s%s) -- quarantine clean (%d untriaged, all pre-existing)"
                % (names, " +%d" % (len(fresh) - 3) if len(fresh) > 3 else "", len(cur)))
            continue
        time.sleep(5)                      # second read: never halt on a half-written row
        new = untriaged_ids() - base
        if not new:
            say("cell(s) landed (%s) -- a row appeared and cleared on re-read; not halting" % names)
            continue
        fired += 1
        halt(new, a.halt)
        json.dump(dict(halted_at=time.strftime("%Y-%m-%d %H:%M:%S"), new_rows=sorted(new),
                       baseline=sorted(base), cells_seen=cells_seen, halt_enabled=a.halt),
                  io.open(ART, "w", encoding="utf-8"), indent=1)
        if a.halt:
            return 1
        base = untriaged_ids()             # alarm-only: re-baseline so it does not spam


if __name__ == "__main__":
    sys.exit(main())
