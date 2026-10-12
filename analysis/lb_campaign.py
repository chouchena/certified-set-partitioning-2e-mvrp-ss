"""Forward LB campaign at any size, under the replicable protocol. Supersedes night_batch.

PROTOCOL (fixed here so every cell in a size is directly averagable):
  budget      DETERMINISTIC ticks (--det-tl), not wall seconds. Measured 2026-09-10: a wall
              limit made truncated bounds irreproducible (551.81 vs 544.23 on identical R203
              runs) because it stops the search after a different amount of WORK each time.
              Ticks are machine- and load-independent. --tl is a generous wall BACKSTOP only,
              and limit_hit records which one actually bound each solve.
  seed        fixed CPLEX randomseed + PYTHONHASHSEED=0 + parallel=1 (deterministic) + fixed
              threads. Together with det-ticks this reproduces truncated bounds exactly.
  k_hi        SIZE-DEPENDENT and passed in, because provability is governed by |H|, not by the
              drop fraction: |H|=11 proved in 1.4 s at n20 while |H|=15 failed at a 450 s wall
              on ten n30 cells. k_cap is DERIVED as k_hi+5 inside the descend, and a
              k_cap <= k_hi contradiction is fatal there (it silently cost ten n30 cells).
  proximity   0.0 for n<=50 (K Tables 3/4), 0.1 for n=100 (Table 6). Comparing an n100 bound
              computed at 0.0 against Table 6 would be a different problem, not a worse number.

WHAT THIS DOES NOT DO. It does not re-run banked work, and it does not pick tl from outcomes.
Cells are family-interleaved so any interrupted prefix stays family-balanced, and each cell's
artifact is snapshotted under a protocol-tagged name so a later run cannot silently erase it.

REPORTING GRANULARITY IS K'S, NOT OURS -- see analysis/lb_monitor.py. Per-instance at n<=30
(Table 3), pooled at n50 (Table 4), per-family at n100 (Table 6). At n40 K publishes NOTHING,
so an n40 run is DESCRIPTIVE ONLY and this runner says so at launch rather than implying a
comparison that cannot exist.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SEED = 20260910
FAMS = ("C", "R", "RC")
CELLS27 = ([f"C2{i:02d}" for i in range(1, 9)]
           + [f"R2{i:02d}" for i in range(1, 12)]
           + [f"RC2{i:02d}" for i in range(1, 9)])


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def _det_env():
    e = dict(os.environ)
    e["PYTHONHASHSEED"] = "0"
    return e


def say(log, m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def art(cell, size):
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


def difficulty(size=30):
    """K's n30 gap% as a difficulty proxy. K publishes no per-cell gap at n50/n100, and n30 is
    the largest size where they do, so it is the best available ordering key."""
    sys.path.insert(0, ROOT)
    from analysis.lb_monitor import k_table3
    K = k_table3(size)
    return {c: K[c][1] for c in K}


def interleave(cells):
    """Family-interleaved AND HARDEST-FIRST, so any interrupted prefix is family-balanced and
    difficulty-CONSERVATIVE.

    WHY THIS MATTERS -- caught 2026-09-10. Plain numeric order runs C201/R201/RC201 first, and
    those are the EASIEST cells in the dataset: K proves C201 optimal at both n20 and n30
    (gap 0/0), R201 is 0/2% and RC201 0/11%. A prefix of the numeric order therefore flatters
    the method systematically, and the n100 probe that produced '|H|=50 proven in 192 s' was run
    on exactly that cell. night_batch sorted by -K[c]; lb_campaign lost the property. Restored.
    """
    d = difficulty()
    by = {f: sorted([c for c in cells if fam(c) == f],
                    key=lambda c: -d.get(c, 0.0)) for f in FAMS}
    out = []
    while any(by.values()):
        for f in FAMS:
            if by[f]:
                out.append(by[f].pop(0))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--k-hi", type=int, required=True)
    ap.add_argument("--det-tl", type=float, default=450000.0)
    ap.add_argument("--tl", type=int, default=1800, help="WALL BACKSTOP only")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cell-budget", type=float, default=7200.0)
    ap.add_argument("--cells", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--allow-dirty", action="store_true")
    A = ap.parse_args()

    prox = 0.1 if A.size == 100 else 0.0
    log = os.path.join(ROOT, "runs", f"lb_campaign_n{A.size}.log")
    sys.path.insert(0, ROOT)
    from analysis.repro_preflight import preflight
    cells = interleave([c.strip() for c in A.cells.split(",") if c.strip()] or CELLS27)
    d = difficulty()
    preflight(f"lb_campaign_n{A.size}", seed=SEED, threads=A.threads,
              allow_dirty=A.allow_dirty,
              extra=dict(size=A.size, k_hi=A.k_hi, det_tl=A.det_tl, wall_backstop=A.tl,
                         proximity=prox, cell_budget=A.cell_budget, order=cells),
              attest=dict(
                  sample_choice=f"all {len(cells)} Solomon class-2 cells, family-interleaved and "
                                f"HARDEST-FIRST by K's n30 gap%; first three are "
                                f"{cells[:3]} at gaps "
                                f"{[round(d.get(c,0)) for c in cells[:3]]}%",
                  sample_position=f"any interrupted prefix is difficulty-CONSERVATIVE: the "
                                  f"easiest cells ({[c for c in cells[-3:]]}) run LAST, so a "
                                  f"partial result understates rather than flatters",
                  design=f"descend k_hi={A.k_hi} (|H|={A.size-A.k_hi}), k_cap=k_hi+5 asserted "
                         f">k_hi, det_tl={A.det_tl:.0f} ticks, wall backstop {A.tl}s "
                         f"(< cell_budget {A.cell_budget}s, asserted), threads={A.threads}, "
                         f"proximity={prox} (K Table {'6' if A.size==100 else '3/4'})",
                  replicability=f"CPLEX randomseed={SEED}, parallel=deterministic, "
                                f"PYTHONHASHSEED=0, budget in deterministic TICKS not wall; "
                                f"det_ticks+limit_hit logged per solve; clean-tree gate",
                  rt=f"lb_curve gives time-to-beat and time-to-best per cell; these are NOT the "
                     f"cell wall total, which is time-to-exhaust-the-descend",
                  rules=f"anomaly halt after 2 malformed cells (the k_cap signature); no partial "
                        f"family means (lb_monitor withholds until a family closes); artifacts "
                        f"snapshotted before overwrite"))
    say(log, f"=== LB CAMPAIGN n{A.size}: {len(cells)} cells, k_hi={A.k_hi} (|H|={A.size-A.k_hi}) "
             f"det_tl={A.det_tl:.0f}tk wall_backstop={A.tl}s threads={A.threads} prox={prox} "
             f"seed={SEED} ===")
    if A.size == 40:
        say(log, "    NOTE: |C|=40 appears in NO K table (T3=10/20/30, T4=10/20/50, T6=100), "
                 "so no COMPARISON to K is possible. It is still NEW PUBLISHABLE DATA -- bounds "
                 "at a size nobody has reported -- and is scheduled deliberately, after the LB "
                 "domination validation, not dropped.")
    say(log, f"    order (family-interleaved): {cells}")

    anomalies = []
    for i, c in enumerate(cells, 1):
        a = art(c, A.size)
        if recs(a):
            say(log, f"[{i}/{len(cells)}] {c} SKIP -- artifact already present")
            continue
        say(log, f"[{i}/{len(cells)}] {c}")
        t0 = time.time()
        try:
            subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                            "--cells", c, "--size", str(A.size), "--k-hi", str(A.k_hi),
                            "--tl", str(A.tl), "--det-tl", str(A.det_tl),
                            "--workers", str(A.threads), "--proximity", str(prox),
                            "--cell-budget", str(A.cell_budget), "--seed", str(SEED),
                            "--allow-overwrite"],
                           cwd=ROOT, env=_det_env(), timeout=A.cell_budget + 1800,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except Exception as e:
            say(log, f"  {c} error/timeout: {e}")
        r = recs(a)
        best = max((x["block_relax"] for x in r), default=None)
        pv = sum(1 for x in r if x.get("proven"))
        lim = {}
        for x in r:
            lim[x.get("limit_hit")] = lim.get(x.get("limit_hit"), 0) + 1
        say(log, f"  {c} done in {time.time()-t0:.0f}s   best={best} recs={len(r)} "
                 f"proven={pv} limits={lim}")
        # ANOMALY HALT -- the guard whose absence is the real lesson of the k_cap defect.
        # That batch ran all 26 cells to completion while TEN of them returned a single
        # unproven record, and the family means were then computed over the wreckage. No
        # pre-mortem item caught it because every item asked "is the DESIGN right?" and none
        # asked "does the OUTPUT look like the protocol ran at all?". A descend is supposed to
        # produce a chain of records with at least one proven; one unproven record means the
        # escalate-up path never executed. Two such cells halt the batch instead of spending
        # the night manufacturing more of them.
        # The k_cap signature is EXACTLY ONE record -- escalate-up never executed. A cell with
        # SEVERAL records and none proven is a legitimately hard cell that escalated and still
        # could not prove: C204/n100 did 4 solves at |H|=30..27, all unproven, in 1412 s. Those
        # truncated dual bounds are valid LBs (proof Step 0). Conflating the two would have
        # halted this campaign on its first three cells -- all deliberately the hardest -- and
        # lost the night. Report it loudly; do not halt on it.
        if pv == 0 and len(r) > 1:
            say(log, f"  note {c}: {len(r)} solves, none proven -- hard cell, not a defect. "
                     f"Best bound is a truncated dual bound (valid LB, proof Step 0).")
        if len(r) <= 1:
            anomalies.append(c)
            say(log, f"  !! ANOMALY on {c}: recs={len(r)} proven={pv}. A descend must produce a "
                     f"CHAIN of records; exactly one means escalate-up never executed -- the "
                     f"k_cap-defect signature.")
            if len(anomalies) >= 2:
                say(log, f"!! HALTING BATCH after {len(anomalies)} anomalous cells "
                         f"{anomalies}. Diagnose before burning the remaining "
                         f"{len(cells)-i} cells.")
                return
        if r:
            tag = A.tag or f"detl{int(A.det_tl)}"
            dst = a.replace(".json", f"_{tag}.json")
            try:
                shutil.copyfile(a, dst)
            except Exception as e:
                say(log, f"    !! snapshot failed: {e}")
    say(log, f"=== LB CAMPAIGN n{A.size} COMPLETE ===")


if __name__ == "__main__":
    main()
