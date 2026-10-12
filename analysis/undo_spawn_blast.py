"""Undo the blast radius of the 2026-09-20 import-gate incident.

WHAT HAPPENED. `gate_importable.py` checked importability by exec'ing each module. Two modules do
their work at module level, so the gate ran them:

    captl_ctrl_runner.py   launched calib_run.py for R203 and R211, n30, seeds 0-2, 2400s each.
                           Two sweeps launched two sets: four unrequested 2400s campaigns.
    seq_handoff.py         called kill_tree(), which force-kills EVERY python process whose
                           command line matches fixopt.py -- then launched master_sequence
                           --stages 1b,2,3,4,5, which launched scale_screen and a step1 run.

The kills are the serious part. seq_handoff.log records HANDOFF firing at 17:35:55 and 17:41:57,
which are the two gate sweeps, and step 2 is missing exactly two dumps:

    s2_faithfulM_R201_n100_s1.json     killed 17:35
    s2_faithfulM_R201_n100_s2.json     killed 17:41

Step 2's own output said so and it was read past: it reported 18 pairs while its paired-delta line
reported 16 seeds. The two missing runs were inside the number that got quoted.

WHAT THIS UNDOES
    1. quarantines every artifact written by a spawned job, identified by run variant
    2. removes the spawned rows from runs/provenance.csv, which is a shared ledger
    3. names the two destroyed step-2 runs so the queue re-runs them

WHAT IT CANNOT UNDO. Wall-clock measured while four unrequested solvers held the machine. Every
runtime recorded between 17:30 and the moment the spawned jobs stopped is contaminated. Objective
values are unaffected: they are budget-limited incumbents either way, but the BUDGET they had was
not the budget they were given.

This is recorded in runs/_spawn_blast_2026-09-20/CONTAMINATED_WINDOW.json. An earlier version of
this docstring said the timings were "marked as such in runs/queue_state.json" -- they were not.
Nothing wrote that marker; the script only printed a warning, and the claim was repeated to the
author as though it were done. queue_state.json is also written by a live queue, so this record
goes in its own file rather than racing it.

IT REFUSES TO RUN while a spawning process is alive, because they would simply rewrite what it
removes.

    python analysis/undo_spawn_blast.py            report only
    python analysis/undo_spawn_blast.py --apply    quarantine and revert
"""
import argparse
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUAR = os.path.join(ROOT, "runs", "_spawn_blast_2026-09-20")

# The incident window. Nothing before this can be attributed to the gate.
WINDOW_START = "2026-09-20 17:30:00"

# Run variants that ONLY the spawned jobs produce. A step-2 or wave-A artifact never carries one.
SPAWNED_VARIANTS = ("cal_baseline", "scaleprobe", "scalefull")
SPAWNED_GLOBS = [
    "runs/fixopt_*_cal_baseline_*.jsonl",
    "runs/fixopt_*_scaleprobe_*.jsonl",
    "runs/fixopt_*_scalefull_*.jsonl",
    "runs/solutions/fixopt_*cal_baseline*.json",
    "runs/solutions/_tmp_*baseline*.json",
    "validation/captl_ctrl_*.csv",
    "validation/kickbench_sup*.jsonl",
    "runs/oracle/step1_validbigm_n20_30.jsonl",
    "runs/oracle/step1_validbigm_n20.json",
    "runs/oracle/step1_validbigm_n30.json",
]

# Destroyed by kill_tree(). These are not recoverable; they must be re-solved.
DESTROYED = [
    "runs/step2/s2_faithfulM_R201_n100_s1.json",
    "runs/step2/s2_faithfulM_R201_n100_s2.json",
]

# step1_validbigm is here because master_sequence spawned one at eight threads. It is ALSO a
# legitimate queue step, so the name alone does not identify a spawned run -- but a live process
# holding a file this script is about to move does, and missing it made the first --apply die
# half-way with a PermissionError on Windows.
SPAWNERS = ("calib_run.py", "master_sequence.py", "scale_screen.py", "step1_validbigm.py",
            "captl_ctrl_runner.py", "seq_handoff.py", "gate_importable.py")


def alive():
    """Which spawning processes are still running? Undoing under them is pointless."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
          "ForEach-Object { $_.CommandLine }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    out = []
    for line in (r.stdout or "").splitlines():
        for s in SPAWNERS:
            if s in line:
                out.append((s, line.strip()[:110]))
                break
    return out


def spawned_files():
    cut = time.mktime(time.strptime(WINDOW_START, "%Y-%m-%d %H:%M:%S"))
    hits = []
    for g in SPAWNED_GLOBS:
        for p in glob.glob(os.path.join(ROOT, g)):
            try:
                if os.path.getmtime(p) >= cut:
                    hits.append(p)
            except OSError:
                pass
    return sorted(set(hits))


def polluted_provenance_rows():
    """Rows ADDED since the last commit that carry a spawned variant.

    Not every row of that variant. Those variants have a legitimate history -- 406 of the 835
    rows mention one, and removing them all would delete months of real runs to clean up one
    afternoon. Only the rows this incident appended are pollution, and git already knows exactly
    which those are.
    """
    p = os.path.join(ROOT, "runs", "provenance.csv")
    if not os.path.exists(p):
        return p, [], []
    # BINARY. Reading this in text mode translates CRLF to LF, and writing it back rewrote all
    # 766 committed rows as a delete-and-re-add. The content was right and the diff was
    # unreadable, which for a shared ledger is most of the damage.
    raw = open(p, "rb").read()
    lines = raw.splitlines(keepends=True)
    r = subprocess.run(["git", "diff", "--unified=0", "--", "runs/provenance.csv"],
                       capture_output=True, text=True, cwd=ROOT)
    added = set()
    for l in (r.stdout or "").splitlines():
        if l.startswith("+") and not l.startswith("+++"):
            added.add(l[1:].strip().encode("utf-8", "replace"))
    vb = [v.encode() for v in SPAWNED_VARIANTS]
    bad = {l for l in added if any(v in l for v in vb)}
    keep = [l for l in lines if l.strip() not in bad]
    drop = [l for l in lines if l.strip() in bad]
    return p, keep, drop


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    print("UNDO the 2026-09-20 import-gate blast")
    print()
    running = alive()
    if running:
        print("   STILL RUNNING -- undoing now would be undone again within minutes:")
        for s, line in running:
            print("      %-22s %s" % (s, line))
        print()
        print("   These must be stopped first. This script will not remove artifacts that a")
        print("   live process is still writing.")
    else:
        print("   no spawning process is alive")
    print()

    files = spawned_files()
    print("   ARTIFACTS FROM SPAWNED JOBS: %d" % len(files))
    for f in files[:24]:
        print("      " + os.path.relpath(f, ROOT).replace("\\", "/"))
    if len(files) > 24:
        print("      ... and %d more" % (len(files) - 24))
    print()

    p, keep, drop = polluted_provenance_rows()
    print("   runs/provenance.csv: %d row(s) written by spawned runs, of %d total"
          % (len(drop), len(keep) + len(drop)))
    print()

    print("   DESTROYED BY kill_tree() -- not recoverable, must be re-solved:")
    for d in DESTROYED:
        print("      %-46s %s" % (d, "absent, as expected"
                                  if not os.path.exists(os.path.join(ROOT, d)) else "PRESENT?"))
    print()
    print("   CONTAMINATED MEASUREMENTS: every wall-clock recorded from %s until the spawned"
          % WINDOW_START[-8:])
    print("   jobs stop. Wave A's step seconds in runs/queue_state.json fall inside it. The")
    print("   RESULTS are deterministic analysis and stand; the TIMINGS do not.")

    if not a.apply:
        print()
        print("   report only; nothing changed. Re-run with --apply once the jobs are stopped.")
        return 0
    if running:
        print()
        print("   REFUSED: %d spawning process(es) still alive." % len(running))
        return 1

    os.makedirs(QUAR, exist_ok=True)
    moved = []
    for f in files:
        dest = os.path.join(QUAR, os.path.basename(f))
        shutil.move(f, dest)
        moved.append(os.path.relpath(f, ROOT).replace("\\", "/"))
    if drop:
        open(p, "wb").write(b"".join(keep))
    io.open(os.path.join(QUAR, "MANIFEST.json"), "w", encoding="utf-8").write(json.dumps(
        {"moved": moved, "provenance_rows_removed": len(drop), "destroyed": DESTROYED,
         "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "why": "Produced by jobs that an import-check gate started by accident on 2026-09-20. "
                "Never requested, never audited, and run under contention with a live campaign."},
        indent=1))
    print()
    print("   quarantined %d artifact(s) -> %s" % (len(moved), os.path.relpath(QUAR, ROOT)))
    print("   removed %d polluted row(s) from runs/provenance.csv" % len(drop))
    print("   the two destroyed step-2 runs are queued for re-solve, not recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
