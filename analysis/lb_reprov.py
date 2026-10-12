"""Re-run cells under FULL PROVENANCE at any size. Generalisation of lb_n20_reprov.

Defence, not expansion: this re-runs results already in the paper so they can be reproduced
from a committed code release. It is NOT an attempt to get a better bound, and the direction
the bounds move is not under our control.

=============================== PRE-MORTEM ===============================
1. SILENT NO-OP. analysis/lb_campaign.py skips any cell whose artifact exists, so pointed at a
   size that has already been run it would skip every cell and report success having done
   nothing. That is why this is a separate driver.
2. DESTROYING THE OLD VALUES. Two artifact naming conventions exist:
       crossfeed/easy_reduction_descend_<cell>_n<size>.json   (current)
       crossfeed/easy_reduction_<cell>_n<size>.json           (pre-provenance, older)
   lb_n20_reprov read only the first, so 10 of 27 n20 cells had before=None and their
   regression check was blind. BOTH are read here for the baseline, and the descend-named one
   is snapshotted to *_noprov.json before the cell runs. The old-named file is never written
   by the solver, so it survives untouched.
3. REGRESSION. A re-run at a different k_hi can return BELOW the old value. At n30 in
   particular the undamaged cells hold DEEP descents (R201 reached k=0, |H|=30, 16 records),
   and a run starting at a larger k may not reach that depth inside its budget. This risk is
   materially higher than it was at n20 and is pre-registered, not discovered.
4. TUNING ON THE OUTCOME. k_hi must come from khi_probe's provability criterion run on the
   HARDEST cell by K's gap -- never the default C201, which is the easiest in the dataset.
   This driver REFUSES to start without an explicit --k-hi so it can never be a guess.
5. BUDGET. det_tl is deterministic ticks (load-independent); --tl is only a wall BACKSTOP and
   must stay below --cell-budget or easy_reduction_descend exits FATAL. The det limit must
   bind first: a wall-truncated bound is not reproducible, which is the defect being removed.
6. CO-TENANCY. Wall budgets assume exclusive use. Holds for single tenancy before each cell.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SEED = 20260910
CELLS27 = ([f"C20{i}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
           + [f"RC20{i}" for i in range(1, 9)])


def say(log, m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def art(cell, size):
    return os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{size}.json")


def old_art(cell, size):
    return os.path.join(ROOT, "crossfeed", f"easy_reduction_{cell}_n{size}.json")


def recs(path):
    if not os.path.exists(path):
        return []
    try:
        r = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    r = r if isinstance(r, list) else [r]
    return [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]


def baseline(cell, size):
    """Best over BOTH naming conventions. Reading only the current name made the regression
    check blind on 10 of 27 n20 cells, six of which held single-record PROVEN full-instance
    solves -- exactly the values a re-run is most likely to fall below."""
    vals = [x["block_relax"] for x in recs(art(cell, size)) + recs(old_art(cell, size))]
    return max(vals) if vals else None


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--k-hi", type=int, required=True,
                    help="from khi_probe on the HARDEST cell; never a guess")
    ap.add_argument("--cells", default="", help="default: every cell lacking provenance")
    ap.add_argument("--det-tl", type=float, default=653400.0)
    ap.add_argument("--tl", type=int, default=1800)
    ap.add_argument("--cell-budget", type=float, default=9000.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--allow-dirty", action="store_true")
    A = ap.parse_args()
    if A.tl > A.cell_budget:
        sys.exit(f"REFUSING: tl={A.tl} exceeds cell-budget={A.cell_budget}; the descend would "
                 f"exit FATAL on every cell.")
    prox = 0.1 if A.size == 100 else 0.0
    log = os.path.join(ROOT, "runs", f"lb_reprov_n{A.size}.log")

    sys.path.insert(0, ROOT)
    from analysis.night_batch import k_targets
    from analysis.lb_campaign import interleave
    from analysis.repro_preflight import preflight

    def needs_prov(c):
        r = recs(art(c, A.size))
        return not any(x.get("seed") is not None and x.get("code_hash") for x in r)

    cells = ([c.strip() for c in A.cells.split(",") if c.strip()]
             or [c for c in CELLS27 if needs_prov(c)])
    cells = interleave(cells)
    preflight(f"lb_reprov_n{A.size}", seed=SEED, threads=A.threads, allow_dirty=A.allow_dirty,
              extra=dict(wall_backstop=A.tl, det_tl=A.det_tl, k_hi=A.k_hi, k_cap=A.k_hi + 5,
                         proximity=prox, cell_budget=A.cell_budget, size=A.size,
                         n_cells=len(cells)),
              attest=dict(
                  sample_choice=f"every |C|={A.size} cell lacking a provenanced artifact "
                                f"({len(cells)} cells) -- membership is a PROCESS fact read from "
                                f"the artifacts (seed/code_hash absent), never a bound value",
                  sample_position="ordered family-interleaved HARDEST-FIRST by K's gap so any "
                                  "interrupted prefix is difficulty-conservative",
                  design=f"re-run for PROVENANCE. k_hi={A.k_hi} from khi_probe on the hardest "
                         f"cell; det_tl={A.det_tl:.0f} deterministic ticks; wall backstop "
                         f"{A.tl}s below the {A.cell_budget:.0f}s cell budget so the det limit binds",
                  replicability=f"seed {SEED}, PYTHONHASHSEED=0, deterministic tick budget, "
                                f"code_hash + git_sha stamped on every record -- the point of the run",
                  rt="per-cell wall reported; bound VALUES are det-tick based and load-independent",
                  rules="baseline read from BOTH artifact naming conventions; descend-named "
                        "artifact snapshotted to *_noprov.json BEFORE each cell; every "
                        "regression reported, never dropped; max over runs NOT taken"))
    K = k_targets(A.size)
    say(log, f"=== LB REPROV n{A.size}: {len(cells)} cells, k_hi={A.k_hi} k_cap={A.k_hi + 5} "
             f"det_tl={A.det_tl:.0f}tk (wall backstop {A.tl}s) threads={A.threads} prox={prox} "
             f"budget={A.cell_budget:.0f}s seed={SEED} ===")
    say(log, f"    order (family-interleaved, hardest-first): {cells}")

    before = {}
    for c in cells:
        before[c] = baseline(c, A.size)
        dst = art(c, A.size).replace(".json", "_noprov.json")
        if os.path.exists(art(c, A.size)) and not os.path.exists(dst):
            shutil.copyfile(art(c, A.size), dst)

    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    regressions = []
    for i, c in enumerate(cells, 1):
        n = live_solvers()
        while n > 0:
            say(log, f"  WAIT: {n} solver process(es) live before {c}; holding for single tenancy")
            time.sleep(60)
            n = live_solvers()
        g = K.get(c)
        say(log, f"[{i}/{len(cells)}] {c} (K gap {f'{g:.0f}%' if g is not None else 'n/a'}) "
                 f"old_best={before[c]}")
        t0 = time.time()
        try:
            subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                            "--cells", c, "--size", str(A.size), "--tl", str(A.tl),
                            "--k-hi", str(A.k_hi), "--workers", str(A.threads),
                            "--proximity", str(prox), "--cell-budget", str(A.cell_budget),
                            "--seed", str(SEED), "--det-tl", str(A.det_tl),
                            "--allow-overwrite"],
                           cwd=ROOT, env=env, timeout=A.cell_budget + 1200,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except Exception as e:
            say(log, f"  {c} error/timeout: {e}")
        r = recs(art(c, A.size))
        nb = max((x["block_relax"] for x in r), default=None)
        pv = sum(1 for x in r if x.get("proven"))
        reg = nb is not None and before[c] is not None and nb < before[c] - 1e-6
        if reg:
            regressions.append(c)
        say(log, f"  {c} done in {time.time() - t0:.0f}s   [reprov] old={before[c]} new={nb} "
                 f"recs={len(r)} proven={pv} {'REGRESSION' if reg else ''}")
    say(log, f"=== LB REPROV n{A.size} COMPLETE -- {len(regressions)} regression(s) "
             f"{regressions} ===")


if __name__ == "__main__":
    main()
