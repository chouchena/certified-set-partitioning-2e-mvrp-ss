"""KICK-vs-NO-KICK ablation, under the corrected measurement protocol.

This is the ONE experiment left standing after the adversarial pass, and it is what decides
which config gets frozen. It exists because the cap-TL result was withdrawn: that comparison
carried a confirmed order confound (R203 deltas monotone in run order, Spearman rho=+1.000,
exact p=0.0167 -- better supported than the treatment effect at Wilcoxon p=0.0577) and changed
THREE knobs at once (kick_k 1->4, kick_count 10->9, escalating TL -> fixed 20s).

PROTOCOL (each clause fixes a specific defect that was found on disk):
 (i)   SINGLE TENANCY. One fixopt at a time, 4 threads. The whole n30 campaign ran R203 and
       R211 concurrently = 8 live threads on a Lunar Lake 4P+4LPE part, so nothing in it was a
       4-core comparison.
 (ii)  Report MEDIAN over seeds with censoring shown; never min-over-N.
 (iii) ONE config string. Both arms are identical except the kick switch.
 (iv)  COUNTERBALANCED arm order (alternating slot 1) + randomised block order. Single tenancy
       alone would NOT have prevented the R203 artifact -- that came from an uncounterbalanced
       ABAB schedule with baseline permanently in slot 1 of every block.

The no-kick arm uses --kick-patience 1e9, NOT omission of the flag. Omitting it makes
enough_failed unconditionally True (fixopt.py:333-334), arming the stall-break, and also nulls
mig_pat and pushes rd_pat to budget -- four knobs instead of one. Verified: --stall-patience is
unset in every launcher, which is what keeps this arm clean; that is a precondition, not a
property, so it is asserted below.

Both arms run the BEST kick config we have (cap-TL: k4/count9/TL20). A null result then reads
"even our best kick configuration contributes nothing", which is the strongest form of it.
"""
import argparse, os, random, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="R203,R211")
    ap.add_argument("--seeds", default="20,21,22,23,24")
    ap.add_argument("--budget", type=float, default=2400)
    ap.add_argument("--order-seed", type=int, default=17, help="RNG for block-order shuffle")
    ap.add_argument("--resume-from", type=int, default=0,
                    help="block index to resume the arm-order alternation from, so a preempted "
                         "run stays counterbalanced instead of restarting slot 1 assignment")
    a = ap.parse_args()

    # protocol assertion (iv-adjacent): the no-kick arm is only clean while this stays unset
    src = open(os.path.join(ROOT, "analysis", "calib_run.py"), encoding="utf-8").read()
    if "stall-patience" in src or "stall_patience" in src:
        say("ABORT: calib_run.py now sets --stall-patience; the no-kick arm is no longer clean")
        sys.exit(1)

    cells = [c.strip() for c in a.cells.split(",") if c.strip()]
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    blocks = [(c, s) for c in cells for s in seeds]
    random.Random(a.order_seed).shuffle(blocks)          # (iv) randomised block order

    # resume: skip (cell,seed) pairs already complete on disk, so a preempted run is not redone
    import csv as _csv
    done = set()
    for c in cells:
        p = os.path.join(ROOT, "validation", f"kick_ablation_{c}.csv")
        if not os.path.exists(p):
            continue
        seen = {}
        for r in _csv.DictReader(open(p)):
            seen.setdefault((r["cell"], r["seed"]), set()).add(r["variant"])
        done |= {k for k, v in seen.items() if {"captl", "nokick"} <= v}
    todo = [b for b in blocks if (b[0], str(b[1])) not in done]
    if done:
        say(f"resume: {len(done)} pair(s) already banked, skipping: "
            + ", ".join(f"{c} s{s}" for c, s in sorted(done)))

    say(f"KICK-vs-NO-KICK ablation: {len(todo)} blocks x 2 arms = {2*len(todo)} runs, "
        f"single-tenant at {a.budget:.0f}s -> ~{2*len(todo)*a.budget/3600:.1f}h")
    for j, (cell, seed) in enumerate(todo):
        # (iv) counterbalanced: each arm takes slot 1 in half the blocks. The index continues
        # from --resume-from so a preempted run does not restart slot-1 assignment and skew it.
        i = j + a.resume_from
        arms = ["captl", "nokick"] if i % 2 == 0 else ["nokick", "captl"]
        say(f"block {j+1}/{len(todo)}: {cell} s{seed}  order={arms[0]},{arms[1]}")
        for arm in arms:
            cmd = [PY, os.path.join(ROOT, "analysis", "calib_run.py"),
                   "--size", "30", "--cells", cell, "--variants", arm, "--seeds", str(seed),
                   "--budget", str(a.budget), "--threads", "4",
                   "--out", f"validation/kick_ablation_{cell}.csv"]
            t0 = time.time()
            subprocess.run(cmd, cwd=ROOT)                 # (i) SEQUENTIAL: single tenancy
            say(f"  {cell} s{seed} {arm} done in {time.time()-t0:.0f}s")
        say(f"block {j+1} PAIR DONE")
    say("ABLATION COMPLETE")


if __name__ == "__main__":
    main()
