"""Re-run all 27 n20 cells under FULL PROVENANCE. Defence, not expansion.

WHY THIS RUN EXISTS. Every n20 artifact on disk predates provenance stamping: seed=None,
code_hash=None, git_sha=None, det_tl=None. Measured 2026-09-11 across the grid:

    size   reproducible   no-provenance   not run
     20        0/27            27            0     <- this run
     30       10/27            16            1
    100       27/27             0            0

n20 carries our STRONGEST published claims -- C 1.43x and RC 1.47x versus K, the best numbers
in validation/degradation_defence.md -- and not one of them can currently be reproduced from a
committed code release. Under the standing rule that full provenance and replicability are an
absolute requirement for any published result, those claims are presently unpublishable. This
run defends results already in the paper; n40/n50 would add results that are not. Defence first.

=============================== PRE-MORTEM ===============================
1. SILENT NO-OP. analysis/lb_campaign.py skips any cell whose artifact exists
   ("SKIP -- artifact already present"). Pointed at n20 it would skip all 27 and report success
   having done nothing. That is why this is a separate driver rather than a campaign invocation.
2. DESTROYING THE OLD VALUES. lb_campaign snapshots AFTER the run, so the pre-provenance
   artifact would be overwritten with no baseline and no way to detect a regression.
   MITIGATION: every artifact is copied to *_noprov.json BEFORE its cell runs, and the old
   maximum is recorded as the regression baseline. Same pattern as lb_repair_n30.
3. REGRESSION. A re-run at a different k_hi can return BELOW the old value, exactly as C204 did
   in the n30 repair. Old n20 records are a mix of proven and truncated, so both cases occur.
   MITIGATION: pre-registered in validation/PREREG_n20_reprov.md BEFORE any result exists.
   Every regression is reported, never dropped; the max over runs is NOT taken.
4. TUNING ON THE OUTCOME. k_hi is chosen by khi_probe's provability criterion, which reads the
   solver's STATUS and never a bound value, run on RC208 -- the HARDEST n20 cell by K's gap
   (65%), not the default C201 which is the easiest in the dataset and would flatter the choice.
5. BUDGET MISCALIBRATION. det_tl=653400 is 450 s of THIS host's work at the measured 1452 tk/s,
   not the 1030 tk/s that was assumed before and silently bought 69% of intent (see claim
   det-tl-miscalibration-confirmed). The wall backstop is deliberately far above it so the
   DETERMINISTIC limit binds first -- a wall-truncated bound is not reproducible, which is the
   very defect this run exists to remove.
6. CO-TENANCY. Wall-clock budgets are calibrated for exclusive use. This run holds for single
   tenancy before each cell and must not share the box with a primal leg.
"""
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "lb_n20_reprov.log")
SIZE, PROX, THREADS, SEED = 20, 0.0, 4, 20260910
DET_TL = 653400.0          # 450 s of this host's work at the MEASURED 1452 tk/s
TL = 1800                  # wall BACKSTOP only; det_tl must bind first
BUDGET = 5400.0
K_HI = int(os.environ.get("N20_K_HI", "0"))   # from khi_probe; 0 = refuse to run

CELLS = ([f"C20{i}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC20{i}" for i in range(1, 9)])


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def art(cell):
    return os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{SIZE}.json")


def recs(path):
    if not os.path.exists(path):
        return []
    try:
        r = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    r = r if isinstance(r, list) else [r]
    return [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]


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


def _det_env():
    e = dict(os.environ)
    e["PYTHONHASHSEED"] = "0"
    return e


def main():
    sys.path.insert(0, ROOT)
    from analysis.night_batch import k_targets
    from analysis.lb_campaign import interleave
    from analysis.repro_preflight import preflight
    if K_HI <= 0:
        sys.exit("REFUSING to run: N20_K_HI not set. Run khi_probe --size 20 first and pass its "
                 "KHI_CHOSEN value, so k_hi is the probe's outcome-blind choice and not a guess.")
    preflight("lb_n20_reprov", seed=SEED, threads=THREADS,
              allow_dirty="--allow-dirty" in sys.argv,
              extra=dict(wall_backstop=TL, det_tl=DET_TL, k_hi=K_HI, k_cap=K_HI + 5,
                         proximity=PROX, cell_budget=BUDGET, size=SIZE),
              attest=dict(
                  sample_choice="ALL 27 Solomon class-2 cells at |C|=20 -- the complete K Table 3 "
                                "grid, no selection, so no outcome-blind question arises",
                  sample_position="complete grid; ordered family-interleaved HARDEST-FIRST by K's "
                                  "n20 gap so any interrupted prefix is difficulty-conservative "
                                  "rather than flattering",
                  design="re-run for PROVENANCE, not for a better bound. k_hi from khi_probe on "
                         "RC208 (hardest cell, K gap 65%); det_tl=653400 = 450s of this host's "
                         "measured work; wall backstop far above it so the det limit binds first",
                  replicability="seed 20260910, PYTHONHASHSEED=0, deterministic tick budget, "
                                "code_hash + git_sha stamped on every record. THIS IS THE POINT OF "
                                "THE RUN: the 27 artifacts being replaced have none of these",
                  rt="per-cell wall reported; bound VALUES are det-tick based and load-independent, "
                     "so RT is descriptive and never enters a bound",
                  rules="pre-mortem in this docstring; decision rule pre-registered in "
                        "validation/PREREG_n20_reprov.md before any result exists; old artifacts "
                        "preserved to *_noprov.json BEFORE each cell; every regression reported, "
                        "never dropped; max over runs NOT taken"))
    K = k_targets(SIZE)
    cells = interleave(CELLS)
    say(f"=== LB n20 REPROV: {len(cells)} cells, k_hi={K_HI} k_cap={K_HI + 5} "
        f"det_tl={DET_TL:.0f}tk (wall backstop {TL}s) threads={THREADS} prox={PROX} "
        f"budget={BUDGET:.0f}s seed={SEED} ===")
    say(f"    order (family-interleaved, hardest-first): {cells}")

    before = {}
    for c in cells:
        r = recs(art(c))
        before[c] = max((x["block_relax"] for x in r), default=None)
        dst = art(c).replace(".json", "_noprov.json")
        if os.path.exists(art(c)) and not os.path.exists(dst):
            shutil.copyfile(art(c), dst)
    kept = sum(1 for c in cells
               if os.path.exists(art(c).replace(".json", "_noprov.json")))
    say(f"    preserved {kept} pre-provenance artifact(s) -> *_noprov.json")

    regressions = []
    for i, c in enumerate(cells, 1):
        n = live_solvers()
        while n > 0:
            say(f"  WAIT: {n} solver process(es) live before {c}; holding for single tenancy")
            time.sleep(60)
            n = live_solvers()
        gap = K.get(c)
        gap_s = f"{gap:.0f}%" if gap is not None else "n/a (K proves it)"
        say(f"[{i}/{len(cells)}] {c} (K gap {gap_s}) old_best={before[c]}")
        t0 = time.time()
        try:
            subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                            "--cells", c, "--size", str(SIZE), "--tl", str(TL),
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
        reg = nb is not None and before[c] is not None and nb < before[c] - 1e-6
        if reg:
            regressions.append(c)
        say(f"  {c} done in {time.time() - t0:.0f}s   [reprov] old={before[c]} new={nb} "
            f"recs={len(r)} proven={pv} {'REGRESSION' if reg else ''}")
    say(f"=== LB n20 REPROV COMPLETE -- {len(regressions)} regression(s) {regressions} ===")


if __name__ == "__main__":
    main()
