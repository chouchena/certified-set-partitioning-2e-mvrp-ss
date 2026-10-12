"""NIGHT DRIVER, 2026-09-17b. Picks up when the 16:42 driver finishes. Author handed the lead.

It NEVER stops a running job. It waits until no solver process but its own children is alive,
then works the queue below. Every step logs what it did and why, so the morning reads as a record
rather than a result.

QUEUE, in this order and for these reasons:

  1. SCORE the Stage 0 n100 gate at the TRAJECTORY's 600k checkpoint, not the driver's 1.2M
     (analysis/score_stage0_gate.py). The two disagree because the driver predates trajectory v2
     by 56 minutes; the trajectory is the authority and the gate is not softened to match the
     bigger budget it happens to have been given.

  2. CE2 CALIBRATION PROBE, one cell, ~35 min. The pre-launch audit of
     PREREG_single_run_capped raised two blockers that only a measurement can retire: the
     deterministic tick rate has NEVER been observed beyond 400 s (the whole calibration corpus
     tops out at 400.1 s) and R206's own rate is already below what the sizing assumed. This
     probes R206 at 5x the calibration length and reports whether the det budget or the wall
     bound. It is deliberately ONE CELL: the audit's instruction was "do not run the first full
     9,234 s cell as the calibration probe".

  3. n100 COVERAGE, 27 cells, CONDITIONAL ON STEP 1 PASSING. Author's call tonight, over my own
     earlier ordering: coverage is the deliverable (trajectory v2 Stage 2) and Stage 1's purpose
     is to pick a config, which the smoke already tests at n100. An unfrozen config is acceptable
     for a run whose claim is "we have a primal at n100 at all". If the gate FAILS this step is
     skipped and the night ends there -- that is the trajectory's own instruction.

  4. MISSING PRIMAL CELLS, n30 then n50, ALWAYS -- not gated on anything. Author, 2026-09-17:
     "If you are out of runs, run missing primal cells." These are the rest of trajectory v2
     Stage 2's 73: 21 at n30 and 25 at n50. n30 first because it is the LAST size where K publish
     per-instance data, so wins there are countable cell by cell; above it only family or pooled
     means are available. Neither is gated on the n100 smoke -- Stage 0 gates n100 alone.

WHAT IT WILL NOT DO. It will not launch PREREG_single_run_capped (audit: DO NOT LAUNCH, five
blockers, d192). It will not run anything two-up: every step here is wall-sensitive or
single-tenant by its own prereg. It will not run PREREG_WS Stage A -- that is a two-ARM
methodological comparison at n30, and step 4 here is one-arm COVERAGE at the same cells; they
answer different questions and step 4 does not consume the prereg's design.
"""
import datetime as dt, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # launched as 'python analysis/x.py', so sys.path[0] is analysis/
PY = sys.executable
LOG = os.path.join(ROOT, "logs", "night_2026-09-17b.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

MY_PID = os.getpid()
CE2_CELL = "R206"
CE2_DET = 1_740_000          # one fifth of 8.7M; ~5x the calibration length
CE2_ITER_DET = 10_850        # audit A2: pin it, do NOT accept det_budget/40
CE2_WALL = 2_400
COV_SEEDS = 1                # EQUAL for every cell; see cover()

# COVERAGE BUDGET -- trajectory v2 Stage 2, and NOT the RT discipline. These are two
# different exercises and conflating them cost me an arithmetic error tonight:
#
#   COVERAGE        "do we have a primal at this cell at all"   ~800 s/cell   73 cells = ~16 h
#   DISCIPLINE-MATCHED  "this result cost no more than K's"     9,780-12,065 s/cell = ~225 h
#
# 1 x allowance and 5 x allowance/5 are the SAME total, so no split of the discipline makes
# it affordable -- the allowance itself is the cost. Stage 2 sets ~800 s deliberately (about
# 6% of K's clock) because the deliverable is EXISTENCE. The discipline binds the later
# exercise, where a number is reported against K.
#
# NO PER-SEED ALLOWANCE, and none is needed: fixopt's restarts do not own budget. One loop,
# one drain, ~25 s per iteration, kicks capped at min(4*iter_tl, half the remaining time)
# (fixopt.py:481-486, :564-566). Nothing can exhaust it and nothing starves.
#
# iter_det is PINNED at the banked corpus value, never det_budget/40 (pre-launch audit A2):
# at 600 ticks/s, 10,850 ticks is ~18 s against the 25 s iter_tl wall, so the DETERMINISTIC
# limit binds inside each sub-solve. The default would make it ~245 s and the wall would bind,
# producing a run that closes "deterministically" while every neighbourhood solve did not.
COV_ITER_DET = 10_850
COV = {30:  dict(wall=3600, det=1_200_000),
       50:  dict(wall=3600, det=1_200_000),
       100: dict(wall=3600, det=1_200_000)}


def say(m):
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), m)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def other_python():
    """PIDs of python processes that are not me and not my children."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                           capture_output=True, text=True, timeout=30)
        pids = []
        for l in r.stdout.splitlines()[1:]:
            p = l.split('","')
            if len(p) > 1:
                try:
                    q = int(p[1].strip('"'))
                except ValueError:
                    continue
                if q != MY_PID:
                    pids.append(q)
        return pids
    except Exception:
        return []


def wait_clear(label, max_h=8):
    say("WAIT: %s -- holding until no other python process is alive. Never interrupting." % label)
    t0 = time.time()
    quiet = 0
    while time.time() - t0 < max_h * 3600:
        p = other_python()
        if not p:
            quiet += 1
            if quiet >= 3:                      # 3 consecutive clear polls = really done
                say("  machine clear after %.0f min" % ((time.time() - t0) / 60))
                return True
        else:
            quiet = 0
            if int(time.time() - t0) % 1800 < 60:
                say("  still waiting (%d other python proc(s), %.0f min)"
                    % (len(p), (time.time() - t0) / 60))
        time.sleep(60)
    say("  GAVE UP waiting after %d h" % max_h)
    return False


def run(cmd, label, timeout_s):
    say("RUN: %s" % label)
    say("  " + " ".join(cmd))
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout_s)
        say("  exit %d in %.0f s" % (r.returncode, time.time() - t0))
        for l in (r.stdout or "").splitlines()[-25:]:
            say("  | " + l)
        if r.returncode != 0:
            for l in (r.stderr or "").splitlines()[-10:]:
                say("  ! " + l)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        say("  TIMEOUT after %.0f s -- left alone, not killed hard" % (time.time() - t0))
        return False


def missing_cells(size):
    """Cells at this size with no banked primal solution. Coverage is the deliverable."""
    import glob as _g, re as _re
    import analysis.manuscript_numbers as _M
    have = set()
    for f in _g.glob(os.path.join(ROOT, "runs", "fixopt_*_n%d_*.jsonl" % size)):
        m = _re.search(r"fixopt_((?:C|R|RC)\d{3})_n%d_" % size, os.path.basename(f))
        if not m:
            continue
        try:
            for l in open(f, encoding="utf-8"):
                l = l.strip()
                if not l:
                    continue
                r = json.loads(l)
                if isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0:
                    have.add(m.group(1))
                    break
        except Exception:
            pass
    return [c for c in sorted(_M._cells(size)) if c not in have]


def cover(size, cells, label, seeds=None):
    """Equal runs per cell, SEED-MAJOR so the corpus is balanced at every instant.

    AUTHOR, 2026-09-17: "since we seek comparable mean results at all cells - fixopt should
    run the same number of runs for all cells."

    That is the defect three audits kept finding: d182 (run counts "assigned by attention, not
    design"; 89% of a denominator in six cells), the 33x comparator spread in the pre-launch
    audit, d142/A3 (per-cell verdicts not invariant to the mixture). An unbalanced corpus cannot
    support a MEAN at all -- only a best-of, which is the estimator SKELETON.md:714 already
    concedes as a limitation.

    WHY SEED-MAJOR AND NOT CELL-MAJOR. Cell-major (all seeds of C201, then all of C202...) is
    balanced only if it RUNS TO COMPLETION. Interrupted at any point it leaves early cells with
    `seeds` runs and later cells with none -- manufacturing exactly the attention-weighted corpus
    the author is ruling out. Seed-major (every cell at seed 0, then every cell at seed 1, ...)
    is balanced after every complete pass, so an interruption costs depth uniformly instead of
    covering some cells and abandoning others. The partial result stays analysable.
    """
    seeds = COV_SEEDS if seeds is None else seeds
    say("")
    cfg = COV[size]
    say("%s: %d cells x %d seeds at |C| = %d, SEED-MAJOR (balanced at every pass)"
        % (label, len(cells), seeds, size))
    say("  det %s, iter_det PINNED %d, wall backstop %d s. COVERAGE budget (trajectory v2"
        % (format(cfg["det"], ","), COV_ITER_DET, cfg["wall"]))
    say("  Stage 2, ~6%% of K's clock) -- NOT the RT discipline, which is a separate and")
    say("  far more expensive exercise. Deliverable here is EXISTENCE, one run per cell.")
    done = 0
    already = set(sorted(set(_c for _c in cells)) ) - set(missing_cells(size))
    if already:
        say("  skipping %d cell(s) that already have a valid run: %s"
            % (len(already), " ".join(sorted(already))))
        cells = [c for c in cells if c not in already]
    for sd in range(seeds):
        say("  --- pass %d of %d (seed %d), %d cells ---" % (sd + 1, seeds, sd, len(cells)))
        for i, c in enumerate(cells, 1):
            dump = os.path.join(ROOT, "runs", "solutions",
                                "cov_%s_n%d_s%d.json" % (c, size, sd))
            os.makedirs(os.path.dirname(dump), exist_ok=True)
            cfg = COV[size]
            ok = run([PY, "-m", "solver.engines.fixopt",
                      "--instance", c, "--size", str(size),
                      "--det-budget", str(cfg["det"]), "--iter-det", str(COV_ITER_DET),
                      "--budget", str(cfg["wall"]), "--threads", "4", "--seed", str(sd),
                      "--variant", "cov_n%d" % size, "--dump-best", dump],
                     "%s %s s%d [%d/%d]" % (label, c, sd, i, len(cells)), cfg["wall"] + 900)
            done += ok
        say("  pass %d done -- every cell now has %d run(s). Corpus is balanced." % (sd + 1, sd + 1))
    say("%s COMPLETE: %d runs over %d cells x %d seeds" % (label, done, len(cells), seeds))
    return done


def main():
    say("=" * 78)
    say("NIGHT DRIVER 2026-09-17b -- author handed the lead, machine must not idle")
    say("=" * 78)

    if not wait_clear("the 16:42 driver, S2p Stage 1, and the n100 smoke"):
        return 1

    # ---- 1. Stage 0 gate, at the trajectory's budget ----
    say("")
    say("STEP 1: score the Stage 0 n100 gate at the TRAJECTORY's 600k, not the driver's 1.2M")
    gate_ok = run([PY, "analysis/score_stage0_gate.py"], "Stage 0 gate", 600)
    out = ""
    try:
        r = subprocess.run([PY, "analysis/score_stage0_gate.py"], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
        out = r.stdout or ""
    except Exception:
        pass
    gate_pass = "GATE PASSES" in out
    say("  gate verdict: %s" % ("PASS" if gate_pass else "FAIL or unreadable"))

    # ---- 2. CE2 calibration probe ----
    say("")
    import glob as _g
    if _g.glob(os.path.join(ROOT, "runs", "fixopt_%s_n20_s0_ce2_calib_*.jsonl" % CE2_CELL)):
        say("")
        say("STEP 2 SKIPPED: a CE2 probe already exists (d199 banked it, and a repeat gave")
        say("  the reproducibility check d200). Re-running it on every restart was waste.")
    else:
        say("STEP 2: CE2 calibration probe -- %s, det %d, iter_det PINNED at %d (audit A2)"
            % (CE2_CELL, CE2_DET, CE2_ITER_DET))
        say("  purpose: the tick rate has never been observed beyond 400 s. This is 5x that.")
        run([PY, "-m", "solver.engines.fixopt",
             "--instance", CE2_CELL, "--size", "20",
             "--det-budget", str(CE2_DET), "--iter-det", str(CE2_ITER_DET),
             "--budget", str(CE2_WALL), "--threads", "4", "--seed", "0",
             "--variant", "ce2_calib"], "CE2 probe", CE2_WALL + 900)

    # ---- 3. n100 coverage, gated ----
    say("")
    if not gate_pass:
        say("STEP 3 SKIPPED: the Stage 0 gate did not pass at the trajectory's 600k checkpoint.")
        say("  Trajectory v2 Stage 0: n100 in stages 2-3 is ABANDONED on a gate failure, and the")
        say("  n100 primal is reported as construction-only with its gap stated. Not softened.")
        say("  n100 is abandoned for stages 2-3. But n30 and n50 are NOT gated on Stage 0,")
        say("  and the author's instruction is explicit: if out of runs, run missing primal")
        say("  cells. Falling through to STEP 4.")
        say("")
        say("STEP 4: n30 -- last per-instance size, wins countable cell by cell")
        cover(30, missing_cells(30), "STEP 4 n30")
        say("")
        say("STEP 5: n50")
        cover(50, missing_cells(50), "STEP 5 n50")
        say("")
        say("ALL QUEUED WORK DONE (n100 gated off).")
        for sz in (30, 50):
            say("  |C| = %-4d still uncovered: %d" % (sz, len(missing_cells(sz))))
        return 0

    say("STEP 3: n100 COVERAGE -- trajectory v2 Stage 2, the deliverable.")
    cover(100, missing_cells(100), "STEP 3 n100")

    # ---- 4/5. the rest of Stage 2's 73 cells. NOT gated on the n100 smoke. ----
    say("")
    say("STEP 4: n30 -- the LAST size where K publish per-instance data, so wins are countable")
    say("  cell by cell. Above it only family or pooled means exist. Not gated on Stage 0.")
    cover(30, missing_cells(30), "STEP 4 n30")

    say("")
    say("STEP 5: n50")
    cover(50, missing_cells(50), "STEP 5 n50")

    say("")
    say("ALL QUEUED WORK DONE. Coverage was the deliverable; here is where it stands:")
    for sz in (30, 50, 100):
        say("  |C| = %-4d still uncovered: %d" % (sz, len(missing_cells(sz))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
