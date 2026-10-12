"""The standing supervision suite. Active by default; only the author turns it off. (d585)

WHAT IT IS. One command that runs every instrument built against this project's recurring failure
classes, prints a single table, and exits nonzero when something that must never be wrong is wrong.

    python analysis/supervision.py            # everything, ~3 minutes
    python analysis/supervision.py --fast     # the hard subset, seconds -- what the commit hook runs

TWO TIERS, and the distinction is deliberate.

  HARD   things that must never be true, campaign or no campaign: a crash waiting on a comparator K
         do not publish, an estimate named like a bound, a number with no generating code, two
         renderings of one quantity, a step whose ceiling is zero still queued. These BLOCK.

  SOFT   things that are legitimately red while a grid is running: tables not yet regenerated, the
         full re-verification not yet run, the published snapshot not yet rebuilt. These are printed
         every time, never hidden, and do not block.

THE OFF SWITCH IS THE AUTHOR'S. Create `validation/SUPERVISION_OFF` with a reason in it and the
commit hook stands down, saying so loudly on every commit. Nothing else disables it -- not a flag,
not an environment variable, and not me.

WHY IT EXISTS. Eight recurring failure classes, mined from 567 banked decisions, cost about eleven
hours of machine time and a day of wrong beliefs in the last week alone
(`validation/RECURRING_FLAWS_AND_SUPERVISION.md`). Each instrument here exists because one of them
happened and nothing noticed.
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
OFF = os.path.join(ROOT, "validation", "SUPERVISION_OFF")

# (label, argv, tier, what a failure means)
SUITE = [
    ("number rendering", ["analysis/check_number_consistency.py"], "hard",
     "one quantity printed two ways"),
    ("reproduction index", ["analysis/reproduction_index.py", "--check"], "hard",
     "a number, figure or table with no generating code"),
    ("abstract gate", ["analysis/abstract_wordcount.py"], "hard",
     "a typed number, an unresolved macro, or a word count outside the venue band"),
    ("campaign dry audit", ["analysis/campaign_dry_audit.py"], "hard",
     "a queued command that will not compile or cannot find its inputs"),
    ("single authority", ["analysis/single_authority.py"], "hard",
     "a module re-implementing a lookup that already has an owner -- two wrong copies in one morning"),
    ("quarantine", ["analysis/quarantine_watch.py", "--once"], "hard",
     "an untriaged verifier/solver contradiction -- the author rule is that all runs stop"),
    ("falsifier battery", ["analysis/falsifier_battery.py"], "soft",
     "a falsifier decidable from banked artifacts that refutes its claim"),
    ("step value preflight", ["analysis/step_value_preflight.py"], "soft",
     "a queued step whose best possible gain is zero"),
    ("harvest re-scan", ["analysis/tep_harvest_master_ip.py", "--dry-run"], "soft",
     "a verified solution better than what we report, sitting unread"),
    ("release gate", ["analysis/release_gate.py"], "soft",
     "see its own output; G26/G27/G8 are expected red until a grid is finished"),
]


def run(argv, timeout=1800):
    t0 = time.time()
    r = subprocess.run([PY] + argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="hard tier only")
    a = ap.parse_args()
    if os.path.exists(OFF):
        why = open(OFF, encoding="utf-8", errors="replace").read().strip()[:200]
        print("SUPERVISION IS OFF by the author's own switch (validation/SUPERVISION_OFF)")
        print("  reason on file: %s" % (why or "none given"))
        return 0
    suite = [s for s in SUITE if not a.fast or s[2] == "hard"]
    print("SUPERVISION SUITE  %s  (%s tier)\n" % (time.strftime("%H:%M:%S"), "hard" if a.fast else "hard + soft"))
    print("%-22s %-6s %8s  %s" % ("instrument", "tier", "secs", "verdict"))
    hard_fail, soft_fail = [], []
    for label, argv, tier, meaning in suite:
        try:
            rc, out, secs = run(argv)
        except Exception as e:
            rc, out, secs = 2, "runner failed: %s" % e, 0.0
        ok = rc == 0
        print("%-22s %-6s %8.1f  %s" % (label, tier, secs, "ok" if ok else "FAIL -- " + meaning))
        if not ok:
            (hard_fail if tier == "hard" else soft_fail).append((label, out.strip().splitlines()[-1:] or [""]))
    print()
    for label, tail in soft_fail:
        print("  soft: %-20s %s" % (label, tail[0][:88]))
    for label, tail in hard_fail:
        print("  HARD: %-20s %s" % (label, tail[0][:88]))
    if hard_fail:
        print("\n  %d hard failure(s). These do not wait for a grid to finish." % len(hard_fail))
        return 1
    print("\n  no hard failures%s" % ("; %d soft item(s) above are expected while a grid runs" % len(soft_fail) if soft_fail else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
