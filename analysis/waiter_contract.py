"""A waiter may not be armed until its predicate has been shown to tell the two states apart. (d585)

WHY. Three waiters failed inside one hour on 2026-09-28, each reporting a running campaign as
finished, each for a different reason:

  1. it matched "FAILED --" in an APPEND-ONLY log that had held that string since the previous day;
  2. it used `ps aux | grep tep_final_campaign`, and `ps aux` in this shell carries no command
     lines, so the probe could not see the thing it was asked about -- it returned 0 always;
  3. it put the wait loop in a `( ... ) &` subshell inside a background task, so the loop died with
     the task's foreground, and the harness reported the task complete two seconds later.

Every one was an indicator that could not distinguish the two states. This module refuses to hand
back a predicate until it has watched it say PRESENT for something that is running and ABSENT for
something that certainly is not.

    python analysis/waiter_contract.py --pattern tep_final_campaign        # verify, then print the loop
    python analysis/waiter_contract.py --pattern tep_final_campaign --expect-absent

The printed loop is the only form that works here: the wait IS the background task's foreground
command, with no inner backgrounding and nothing after it.
"""
import argparse
import subprocess
import sys

PS = ("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
      "Where-Object {{ $_.CommandLine -like '*{pat}*' }} | Measure-Object).Count")


def count(pattern):
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", PS.format(pat=pattern)],
                             capture_output=True, text=True, timeout=60).stdout
        return int((out or "0").strip() or 0)
    except Exception as e:
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", required=True, help="a fragment of the command line to wait on")
    ap.add_argument("--expect-absent", action="store_true",
                    help="the target is NOT expected to be running now; only the negative half is checked")
    a = ap.parse_args()
    absent_probe = "definitely_not_a_running_process_kjh23"
    print("WAITER CONTRACT for pattern %r\n" % a.pattern)
    neg = count(absent_probe)
    print("  negative control (a pattern nothing can match): %s" % neg)
    if neg != 0:
        print("  *** the probe does not return 0 for an absent target. It cannot detect an exit. REFUSED.")
        return 1
    pos = count(a.pattern)
    print("  the pattern right now: %s" % pos)
    if pos < 0:
        print("  *** the probe failed to run. REFUSED.")
        return 1
    if pos == 0 and not a.expect_absent:
        print("  *** the target is not running, so the positive half is untested. Arm it only with")
        print("  *** --expect-absent, and understand that the waiter may fire immediately.")
        return 1
    print("\n  CONTRACT MET: the probe says %d now and 0 for something absent." % pos)
    print("  Arm exactly this, as the background task's own foreground command:\n")
    print('    until [ "$(powershell -NoProfile -Command "%s" | tr -d \'\\r\\n \')" = "0" ]; '
          'do sleep 300; done; echo "%s ENDED $(date)"' % (PS.format(pat=a.pattern), a.pattern))
    print("\n  Do NOT wrap it in ( ... ) &, and do not put anything after it: the loop must be the task.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
