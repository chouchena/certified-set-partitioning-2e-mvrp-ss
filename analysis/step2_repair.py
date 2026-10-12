"""Re-solve the step-2 dumps that kill_tree() destroyed, and nothing else.

WHY. On 2026-09-20 an import-check gate exec'd seq_handoff.py, whose module-level code calls
kill_tree() -- a force-kill of every python process matching fixopt.py. It fired twice, at
17:35:55 and 17:41:57, and took two runs of the live step-2 campaign with it:

    s2_faithfulM_R201_n100_s1.json
    s2_faithfulM_R201_n100_s2.json

Step 2 reported 18 pairs while its paired-delta line reported 16 seeds. The discrepancy WAS the
damage, printed in its own output.

WHY NOT RE-RUN STEP 2. The other 34 dumps are stamped and intact, and the two witnesses -- the
result that matters -- are at C201/n100 seeds 0 and 1, untouched. Re-running the campaign would
cost three hours and, because the budget is wall-clock, would return different incumbents for 34
runs that are already attributable. Repairing exactly the hole is the smaller and more honest
operation.

WHAT THIS DOES NOT CLAIM. The repaired runs are solved on a machine in a different state from
their 16:00-18:00 siblings. They are budget-limited incumbents either way and no claim rests on
their objective, but the aggregate records which dumps were repaired so a reader is not told the
campaign was uniform when it was not.

    python analysis/step2_repair.py [--budget 300] [--det 600000]
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

from step2_bigm_n50n100 import run_fixopt, DUMPS

OUT = os.path.join(ROOT, "runs", "oracle")

# (cell, size, seed, valid_bigm). Exactly the two the kill destroyed.
MISSING = [("R201", 100, 1, False), ("R201", 100, 2, False)]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--det", type=float, default=600000.0)
    a = ap.parse_args()
    os.makedirs(DUMPS, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    print("STEP 2 REPAIR -- re-solving only the dumps kill_tree() destroyed.")
    print()
    repaired, already = [], []
    t0 = time.time()
    for cell, size, seed, valid in MISSING:
        arm = "validM" if valid else "faithfulM"
        dest = os.path.join(DUMPS, "s2_%s_%s_n%d_s%d.json" % (arm, cell, size, seed))
        if os.path.exists(dest):
            already.append(os.path.basename(dest))
            print("   present already, not re-solved: %s" % os.path.basename(dest))
            continue
        print("   solving %s/n%d seed %d, %s arm, %.0fs ..."
              % (cell, size, seed, arm, a.budget), flush=True)
        p = run_fixopt(cell, size, seed, valid, a.budget, a.det)
        if p and os.path.exists(p):
            d = json.load(io.open(p, encoding="utf-8"))
            repaired.append(dict(dump=os.path.relpath(p, ROOT), obj=d.get("objVal"),
                                 code_hash=d.get("_code_hash"), cell=cell, size=size,
                                 seed=seed, arm=arm))
            print("      obj %.3f   code_hash %s" % (d.get("objVal") or 0,
                                                     (d.get("_code_hash") or "?")[:8]))
        else:
            print("      NO DUMP -- the repair failed and the hole remains")

    present = len([f for f in os.listdir(DUMPS) if f.startswith("s2_")])
    print()
    print("   repaired %d   already present %d   step2 dumps now %d of 36"
          % (len(repaired), len(already), present))
    if present < 36:
        print("   THE CAMPAIGN IS STILL INCOMPLETE. step2_reaggregate will report the real")
        print("   denominator; it does not pad a missing pair.")
    json.dump(stamped({"repaired": repaired, "already_present": already,
                       "dumps_present": present, "expected": 36,
                       "cause": "kill_tree() in seq_handoff.py, reached by an import-check gate "
                                "on 2026-09-20 at 17:35:55 and 17:41:57",
                       "wall_s": round(time.time() - t0, 1)},
                      __file__, "analysis/step2_bigm_n50n100.py"),
              io.open(os.path.join(OUT, "step2_repair.json"), "w", encoding="utf-8"),
              indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
