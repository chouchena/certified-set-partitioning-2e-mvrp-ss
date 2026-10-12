"""Re-run the n30 cells damaged by the k_cap<k_hi defect, at the SAME protocol as the other 16.

WHAT WAS BROKEN. easy_reduction_descend defaulted k_cap=14 while the n30 batch passed k_hi=15,
so `while not proven and k < k_cap` was False on entry: the escalate-up safety net never ran.
Ten cells returned a SINGLE UNPROVEN RECORD and were then averaged into family results as
though the method had been given its protocol. Five of them are R losses, and they produce the
entire R=1.18x n30 family figure. R's n30 marginality is therefore NOT ESTABLISHED -- it is an
artifact of a dead loop guard.

THE TENTH CELL. C204 does not appear in night_batch.stalled(), because the killed tl=900 ladder
had already overwritten its live artifact with a partial run that happens to show proven=True.
Its tl=450 log line reads "NO proven bound up to k=14" -- same defect, masked by a second bug
(pre-mortem item 1: the ladder made the live artifact non-uniform). Selected here from the
tl450 SNAPSHOT, not from the live file.

================================ PRE-MORTEM ================================
1. NON-UNIFORM PROTOCOL. These 10 must be directly averagable with the 16 undamaged cells.
   MITIGATION: identical threads=4 and proximity=0.0. NOT identical k_hi -- this text used to
   claim "k_hi=15; only k_cap changes" and that became FALSE when K_HI was raised to 20 (see
   the K_HI comment below). The 16 undamaged cells ran k_hi=15; these 10 run k_hi=20. That is
   a real protocol difference, it is DISCLOSED in every n30 roll-up, and n30 must never be
   presented as a single-protocol family mean. C204's live tl=900 artifact is replaced.
   Consequence, and the reason validation/PREREG_n30_repair_decision.md exists: because the
   bound is monotone decreasing in k and the repair starts at k=20, a repaired cell CAN come
   back weaker than the damaged value it replaces. The decision rule for that case is
   pre-registered there, before any result exists.
   DISCLOSED DIFFERENCE: the budget is DET_TL=450 000 deterministic ticks rather than 450 s of
   wall clock. On this host that is ~437-450 s at 4 threads, i.e. the same effort measured in a
   load-independent unit, chosen because a wall limit makes truncated bounds irreproducible
   (measured: 551.81 vs 544.23 on identical runs). This must be STATED, not hidden -- but it
   does not threaten the comparison, because every value the descend emits is a valid lower
   bound (proof Step 0), so a budget difference moves bound STRENGTH, never validity.

2. TUNING ON THE OUTCOME. Re-running only the cells that LOST would be tuning.
   MITIGATION: the selection rule is the PROCESS fact "descend produced a single unproven
   record at k_hi under the defect", evaluated on the tl450 snapshots. It includes cells that
   WON (R203 1.10x, R210 1.01x, RC204 1.69x) as well as cells that lost. Outcome-blind.

3. SILENT REGRESSION. A re-run could return a LOWER max bound than the damaged run (the
   truncated dual bound at k=15 is already valid by proof Step 0, and CPLEX timing varies).
   MITIGATION: the damaged artifacts are snapshotted to _kcapbug.json first, and the reporter
   prints old vs new per cell. A regression is REPORTED, never quietly dropped -- and both
   numbers are valid LBs, so the comparison is honest either way.

4. RUNAWAY ESCALATION. Escalating k with no ceiling could burn a night on one cell.
   MITIGATION: k_cap = k_hi+5 = 20 (|H|>=10), and a hard cell_budget of 5400 s that stops the
   descend CLEANLY with every record retained. Both are uniform across cells, so neither
   can bias one cell against another.

5. CO-TENANCY. The n30 primal campaign died of this. MITIGATION: strictly sequential, checked
   before every cell.

6. OVERWRITING BANKED WORK. Already cost us a banked n20 artifact today.
   MITIGATION: snapshot first, then pass --allow-overwrite explicitly per cell.

7. READING RESULTS EARLY. MITIGATION: verdicts key on this runner's own completion line, and
   the family roll-up refuses to print until all 26 target cells are complete.

8. NON-REPLICABLE OUTPUT. We report TRUNCATED dual bounds as valid LBs (proof Step 0), and a
   truncated bound is whatever the search reached -- so it moves with the CPLEX seed, the
   thread count and the parallel mode, none of which were pinned before 2026-09-10. An
   unreplicable number cannot be published.
   MITIGATION: analysis.repro_preflight gates the launch on a COMMITTED tree (a dirty tree
   means git_sha does not identify the code that ran) and writes a release manifest; the
   descend pins randomseed=SEED, parallel=1 (deterministic) and threads, and logs det_ticks
   per solve so a replicator can swap the wall-clock limit for dettimelimit and reproduce the
   value exactly on other hardware.
============================================================================
"""
import glob, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _det_env():
    """PYTHONHASHSEED pinned: set/dict iteration order can otherwise vary
    between runs, and the easiness ranking that selects WHICH customers are
    dropped is built from dict traversal. Cheap insurance for replicability."""
    e = dict(os.environ)
    e["PYTHONHASHSEED"] = "0"
    return e
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "lb_repair_n30.log")
# K_HI RAISED 15 -> 20 after the n100 evidence. At n100, k_hi=70 (|H|=30) PROVED in
# 0.2 s and the warm-started descent then walked out to |H|=50. At n30 these ten cells
# FAILED to prove at |H|=15 cold, and each cold failure burns a full per-k budget --
# 63% of all n30 wall time went to non-proving solves. Starting at k=20 (|H|=10) buys a
# near-instant provable anchor, after which every larger |H| is reached WARM.
# This is not a weaker protocol: the descent from k=20 covers every k that k_hi=15 would
# have reached and more, and the estimator is max over ALL records, so a more thorough
# search can only equal or improve the reported bound. The extra high-k records are
# strictly weaker bounds and can never become the max.
TL, K_HI, THREADS, PROX, BUDGET = 1800, 20, 4, 0.0, 5400.0
SEED = 20260910
# DETERMINISTIC budget, intended to equal the 450 s wall the other 16 n30 cells used.
# RECALIBRATED 2026-09-11 after the first repaired cell regressed. The 1030 tk/s figure
# this was originally derived from is wrong for this host: measured over 244 det-limited
# solves the median is 1452 tk/s (1578 at n30), so det_tl=450000 bought only ~310 s --
# 69% of the effort it was documented to match, handicapping every repaired cell by ~31%
# against the 16 it has to be averaged with. 450 s x 1452 tk/s = 653400.
#
# THIS IS A CALIBRATION FIX, NOT A DESIGN CHANGE. The intent was already written down
# ("~= the 450 s wall the other 16 n30 cells used"); only the implementation missed it.
# The regression is what prompted the check, but the defect is verifiable from 244 solves
# that have nothing to do with any repaired cell, so this is outcome-TRIGGERED, not
# outcome-TUNED. k_hi stays 20 exactly as pre-registered.
DET_TL = 653400.0


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def art(cell, size=30):
    return os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{size}.json")


def recs(path):
    if not os.path.exists(path):
        return []
    try:
        r = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    r = r if isinstance(r, list) else [r]
    return [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]


def damaged(cell):
    """PROCESS rule on the tl450 SNAPSHOT (the live file may have been clobbered by the
    killed ladder). Single unproven record at k_hi == the escalate-up net never ran."""
    snap = art(cell).replace(".json", "_tl450.json")
    r = recs(snap if os.path.exists(snap) else art(cell))
    return len(r) == 1 and not r[0].get("proven")


def live_solvers():
    o = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*easy_reduction*' -or "
                        "$_.CommandLine -like '*fixopt.py*' }).Count"],
                       capture_output=True, text=True).stdout.strip()
    try:
        return int(o or 0)
    except ValueError:
        return -1


def main():
    sys.path.insert(0, ROOT)
    from analysis.night_batch import k_targets, interleave
    from analysis.repro_preflight import preflight
    preflight("lb_repair_n30", seed=SEED, threads=THREADS,
              allow_dirty="--allow-dirty" in sys.argv,
              extra=dict(wall_backstop=TL, det_tl=DET_TL, k_hi=K_HI, k_cap=K_HI + 5,
                         proximity=PROX, cell_budget=BUDGET, size=30),
              attest=dict(
                  sample_choice="the 10 cells damaged by the k_cap<k_hi dead loop, selected by "
                                "the PROCESS fact 'single unproven record at k_hi' read from the "
                                "tl450 snapshots -- outcome-blind: it includes cells that WON "
                                "(R203 1.10x, R210 1.01x, RC204 1.69x) as well as the 5 losses",
                  sample_position="these are the HARD end of n30 (K gaps 36-71%); the 16 "
                                  "undamaged cells span the rest, so the repaired family means "
                                  "cover the full difficulty range",
                  design="k_hi=20 (|H|=10) for a near-instant provable anchor, then WARM descent; "
                         "k_cap=25 asserted >k_hi; det_tl=450000 ticks ~ the 450s the other 16 "
                         "cells used; wall backstop 1800s < cell_budget 5400s (asserted)",
                  replicability="seed 20260910, deterministic parallel, PYTHONHASHSEED=0, "
                                "tick budget, clean-tree gate, release manifest",
                  rt="lb_curve per solve -> real time-to-beat; the previous n30 RT medians came "
                     "from wall totals and are superseded",
                  rules="damaged artifacts preserved as *_kcapbug.json; old-vs-new printed per "
                        "cell; any REGRESSION reported not dropped; budget difference vs the "
                        "other 16 cells DISCLOSED in the pre-mortem"))
    K = k_targets(30)
    cells = interleave([c for c in K if damaged(c)], K)
    say(f"=== LB REPAIR n30: {len(cells)} damaged cells, k_cap={K_HI}+5, "
        f"k_hi={K_HI} det_tl={DET_TL:.0f}tk (wall backstop {TL}s) threads={THREADS} prox={PROX} "
        f"budget={BUDGET:.0f}s seed={SEED} ===")
    say(f"    order (family-interleaved): {cells}")

    before = {}
    for c in cells:
        r = recs(art(c))
        before[c] = max((x["block_relax"] for x in r), default=None)
        dst = art(c).replace(".json", "_kcapbug.json")
        if os.path.exists(art(c)) and not os.path.exists(dst):
            shutil.copyfile(art(c), dst)
            say(f"    damaged artifact preserved -> {os.path.basename(dst)}")

    for i, c in enumerate(cells, 1):
        n = live_solvers()
        while n > 0:
            say(f"  WAIT: {n} solver process(es) live before {c}; holding for single tenancy")
            time.sleep(60)
            n = live_solvers()
        say(f"[{i}/{len(cells)}] {c} (K gap {K[c]:.0f}%) old_best={before[c]}")
        t0 = time.time()
        try:
            subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                            "--cells", c, "--size", "30", "--tl", str(TL),
                            "--k-hi", str(K_HI), "--workers", str(THREADS),
                            "--proximity", str(PROX), "--cell-budget", str(BUDGET),
                            "--seed", str(SEED), "--det-tl", str(DET_TL),
                            "--allow-overwrite"],
                           cwd=ROOT, env=_det_env(), timeout=BUDGET + 1200,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except Exception as e:
            say(f"  {c} error/timeout: {e}")
        r = recs(art(c))
        nb = max((x["block_relax"] for x in r), default=None)
        pv = sum(1 for x in r if x.get("proven"))
        say(f"  {c} done in {time.time()-t0:.0f}s   [repair] "
            f"old={before[c]} new={nb} recs={len(r)} proven={pv} "
            f"{'REGRESSION' if (nb is not None and before[c] is not None and nb < before[c]) else ''}")
    say("=== LB REPAIR n30 COMPLETE ===")


if __name__ == "__main__":
    main()
