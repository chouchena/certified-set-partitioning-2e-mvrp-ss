# ===================== RED FLAG -- TEP USE ONLY (2026-09-28) =====================
# This file REACHES K's FORMULATION (solver/engines/fixopt.py -> build_joint_model ->
# integratedJointModel). The standing constraint is that K's formulation is never part
# of our solution (d449, d451), and the fixopt-based work was archived and locked under
# archive/fixopt_locked/ on 2026-09-28.
#
# THIS FILE WAS NOT ARCHIVED because the admissible TEP path still depends on it.
# It is permitted ONLY where that dependency already exists. It must not be imported by
# new work, and no result derived from it may be reported without saying so.
#
# The load-bearing case: tep_cg_bound.master_ip calls assemble_precluster.retime, which
# builds K's joint model. So every master_ip result passes through K's formulation --
# which contradicts d451's claim that retime was replaced. Unresolved; see
# archive/fixopt_locked/LOCK.md.
# =================================================================================

"""The budget-matched grid, one seed at a time, breadth first.

THE AUTHOR'S DESIGN: run every cell at seed 0, then every cell at seed 1, and so on -- so a
COMPLETE picture exists as early as possible and sharpens with each pass, rather than three seeds
of one slice and nothing anywhere else.

WHAT IT TARGETS. Only what can carry a claim:

    n10 p0.0 / p0.1   Table 3, all 27 -- every one K-PROVEN            54 runs
    n20 p0.0 / p0.1   Table 3, all 27 (20 beatable + 7 proven)       54 runs
    n30 p0.0 / p0.1   Table 3, all 27 (26 beatable + 1 proven)       54 runs
    n50 p0.0 / p0.1   Table 4, pooled over 27                        54 runs
    n100 p0.1         Table 6, family means over 27                  27 runs
                                                                  ---------
                                                                   243 runs per seed

THE K-PROVEN CELLS ARE NOT PADDING. 35 cells are proven optimal by K -- 27 at n10, 7 at n20, 1 at
n30 -- and they are the ONLY places where the true optimum is known, so they are the only place
our distance from optimality can be measured at all. Everywhere else, at n20/n30's unproven cells
and at n50/n100, nobody knows it. An earlier version dropped n10 as "zero beatable", which was
exactly backwards: zero-beatable is what makes it informative.

They also DISCRIMINATE THE PROXIMITY INFERENCE. Table 3's proximity is inferred, not stated. If we
attain the proven optima at p=0.0 and miss systematically at p=0.1, that is direct evidence of
which instance set K actually solved -- settling the project's largest exposure empirically rather
than by argument.

Fig. 4 and Fig. 5 remain absent: k_reference.json holds NO numeric figure data, so no comparison
exists there without digitizing someone else's plot (A10).

WHY TWO PROXIMITIES. K STATE proximity 0.1 for Table 6. For Tables 3 and 4 it is INFERRED, from
S5.4's "base scenario, where proximity equals to 0". If a referee reads Table 3 as 0.1 we would be
comparing against different instances, and no amount of model correctness saves that. Running both
makes the claim "we beat K under either reading of their proximity".

THE BUDGET, and it is the reason this file was rewritten on 2026-09-21. Six defects, each of which
silently produced plausible numbers:

  1. LB_SECONDS = 0.087 was a FRACTION subtracted from SECONDS, so the deduction was 0.087 s and
     every cell ran a full 4 h. That, not a bad estimate, is where the 702 h figure came from:
     351 cells x 4 h / 2 concurrent.
  2. K_CAP = 14400 is K's cap in THEIR seconds. Ours are worth roughly two of theirs, so the
     envelope is 5760 s. At 14400 we would spend ~2.5x K's normalised budget and lose the
     budget-fairness defence, which is the entire reason to freeze.
  3. No --det-budget. Wall-clock was the only stop rule, against a STANDING claim (wall 551.81 vs
     544.23 on identical runs; det-ticks 554.79 = 554.79) and against fixopt's own help.
     REVERSED 2026-09-22, and the reversal is not a retraction of the measurement. The 551.81
     vs 544.23 pair is a BOUND measurement on the dual leg, where det_tl binds and the claim
     replicability-needs-det-ticks still stands untouched. It never licensed a PRIMAL budget;
     the extension did. Measured over every run trace, the primal budget bound on 31% of n100
     runs and 68% of n20 -- 34 of 137 and 1 of 19 in the last three days -- so the stop rule
     was already wall clock on most runs while every row was labelled deterministic. See
     validation/AUDIT_dropping_det_ticks.md and primal-harness-blocking-defects-v3.
  4. Resume tested os.path.exists only. After a freeze, a dump from any earlier config would be
     silently accepted -- CLAUDE.md section 4, stale artifacts outliving their headline.
  5. --concurrent 2 x --threads 4 on a 4-core machine: every wall time and time-to-best inflated
     and mutually uncomparable.
  6. The grid was 351 runs including n10 p0.0, which its own comment marked zero-beatable.

TIME-TO-BEST needs no instrumentation. Every improving iteration already logs
`+improve obj=... mode=... verify=OK (recomputed ...)  t=NNs`, so the anytime trajectory and its
operator attribution come out of the log. Report it as elapsed share or budget utilisation, never
raw seconds: objection D2 is settled -- our time-to-best is bounded by our budget and K's is not,
and per core we are the faster hardware.

    python analysis/run_full_grid.py --plan-only
    python analysis/run_full_grid.py --seed 0
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

OUT = os.path.join(ROOT, "runs", "grid")
KREF = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")
CALIB = os.path.join(ROOT, "validation", "GRID_CALIBRATION.json")
RTD = os.path.join(ROOT, "validation", "RT_LEG_DESCRIPTIVES.json")

# K's stated cap, in K's seconds. Table 4 note; verified at source via analysis/k_says.py.
K_CAP_THEIR_SECONDS = 14400.0

# rt_normalize ranks a scalar machine factor as the WEAKEST of its three routes, so the RT leg
# never rests on one: HW_FACTORS is the SENSITIVITY RANGE reported beside any budget statement.
#
# THE ENVELOPE TAKES 2.5 -- author's decision, 2026-09-22, over an argued case for the 2.0 point
# estimate. 2.5 is the strictest factor tested: it gives us the LEAST compute, so a budget claim
# made here survives every weaker reading. What it costs is recorded rather than glossed -- the
# LB wall is deducted BEFORE the primal gets anything, so over the 27 n100 cells the primal
# envelope is a median 38.7% smaller at 2.5 than at 2.0, and 55.7% smaller on R209 (LB 3174 s).
# At n100 every seed is still improving when cut off, so that is objective value, not slack.
#
# HOMOGENEITY -- author, 2026-09-22: "make sure it is applied homogeneously for LB too."
# The envelope arithmetic already is. K_CAP/factor converts K's cap into OUR seconds, and
# lb_cell_seconds is measured on our machine, so both terms of the subtraction are our-seconds
# and our per-cell total is LB + primal = K_CAP/factor exactly. At 2.5 that is 5760 our-seconds
# == 14400 K-seconds: we TIE K's budget, we do not beat it.
#
# The corollary binds elsewhere and is easy to get wrong: any report of our seconds against K's
# must apply the SAME factor. Reporting 5760/14400 = 40% would claim a 2.5x budget win while
# the envelope was sized by conceding exactly that 2.5x -- taking the factor's benefit when
# budgeting and denying its cost when reporting. analysis/combined_budget_vs_k.py carries the
# factor axis for this reason.
HW_FACTORS = (1.0, 1.5, 2.0, 2.5)
HW_FACTOR_ENVELOPE = 2.5


def k_unproven(size):
    """Cells K did NOT prove optimal at this size -- the only ones that can be beaten."""
    pi = json.load(io.open(KREF, encoding="utf-8"))["table3"]["per_instance"]
    cells = pi.get(str(size), {})
    return sorted(c for c, d in cells.items() if d.get("joint_gap") not in (0.0, None))


def all_cells():
    return (["C20%d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
            + ["RC20%d" % i for i in range(1, 9)])


def lb_cell_seconds(cell, size):
    """OUR LB's wall on THIS cell -- the per-cell deduction, not a size median.

    Author, 2026-09-21: "The per cell adjustment is our LB's RT." The envelope is K's budget
    less what our own dual leg already spent ON THAT CELL, so a cell where the LB ran long
    leaves the primal less, and one where it ran short leaves more. Using a size median
    silently overspends on the expensive cells and underspends on the cheap ones -- a
    second-order error against a first-order fairness claim.

    Summed over the descent's records exactly as analysis/rt_leg_descriptives does, so the two
    accountings cannot drift apart. Returns None when the cell has no LB artifact, and the
    caller falls back to the size median rather than inventing a number.
    """
    import glob as _glob
    fp = os.path.join(ROOT, "crossfeed",
                      "easy_reduction_descend_%s_n%d.json" % (cell, size))
    if not os.path.exists(fp):
        return None
    try:
        recs = json.load(io.open(fp, encoding="utf-8"))
    except Exception:
        return None
    if not recs:
        return None
    return sum(float(r.get("wall") or 0.0) for r in recs)


def lb_seconds():
    """Per-size MEDIAN LB wall. The fallback when a cell has no artifact of its own."""
    rt = json.load(io.open(RTD, encoding="utf-8"))["run_time"]
    out = {int(k[1:]): float(v["median_s"]) for k, v in rt.items()}
    # n10 was never measured on the LB leg (RT_LEG_DESCRIPTIVES covers n20/30/50/100). It is
    # given n20's LB as a proxy, which is CONSERVATIVE in the direction that matters: n10's LB
    # can only be cheaper than n20's, so this UNDERSTATES our envelope and never overstates it.
    out.setdefault(10, out[20])
    return out


def envelope(size, factor, cell=None):
    """Primal seconds for a cell: K's budget on OUR machine, less our own LB's wall on it.

    K's budget IS uniformly 14,400 s on every cell we target: all of them are unproven, so K
    ran to the limit -- 20 of 27 at n20, 26 of 27 at n30, and n50/n100 where their gaps are
    58% and 60-77%. Their published inc_time is time-to-INCUMBENT, not total runtime, and
    reading it as their spend understates it by an order of magnitude.
    """
    lb = lb_cell_seconds(cell, size) if cell else None
    if lb is None:
        lb = lb_seconds()[size]
    return K_CAP_THEIR_SECONDS / factor - lb


def grid_rows():
    """(size, proximity, exhibit, cells, why). Ordered by headroom: most beatable first."""
    return [
        (100, 0.1, "table6", all_cells(), "family means over 27; proximity STATED"),
        (50, 0.0, "table4", all_cells(), "pooled over 27; proximity INFERRED"),
        (50, 0.1, "table4", all_cells(), "pooled over 27; the alternative reading"),
        (30, 0.0, "table3", all_cells(), "26 beatable + 1 K-proven for attainment; INFERRED"),
        (30, 0.1, "table3", all_cells(), "the same 27; the alternative reading"),
        (20, 0.0, "table3", all_cells(), "20 beatable + 7 K-proven for attainment; INFERRED"),
        (20, 0.1, "table3", all_cells(), "the same 27; the alternative reading"),
        # n10 has NOTHING beatable -- all 27 are K-proven optima -- and is here for exactly
        # that reason. It is the only place our distance from a TRUE optimum is measurable,
        # and attaining at p=0.0 while missing at p=0.1 would settle the proximity inference
        # empirically instead of by argument. Short budget: see GRID_CALIBRATION.json.
        (10, 0.0, "table3", all_cells(), "27 K-proven: attainment + proximity discriminator"),
        (10, 0.1, "table3", all_cells(), "the same 27; the alternative reading"),
    ]


def calibration():
    """Per-size N and deterministic budget. REFUSES to invent one."""
    if not os.path.exists(CALIB):
        return None
    c = json.load(io.open(CALIB, encoding="utf-8"))
    return {int(k): v for k, v in c.get("by_size", {}).items()}


def dump_path(cell, size, prox, seed):
    return os.path.join(OUT, "g_%s_n%d_p%s_s%d.json" % (cell, size, prox, seed))


def done_and_current(cell, size, prox, seed, code_hash):
    """A cell is done only if its dump exists AND was produced by the FROZEN code.

    Existence alone was the old test. After a freeze that silently accepts a dump from any
    earlier configuration, which is how a stale artifact outlives its headline.
    """
    p = dump_path(cell, size, prox, seed)
    if not os.path.exists(p):
        return False
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return False
    return d.get("_code_hash") == code_hash


def inspect(cell, size, prox, seed, cal):
    """Look at the dump the moment it lands. A quarantine is a BUG SIGNAL, not a filing action.

    Author, 2026-09-21: "special attention to quarantine which mostly means bug". So this halts
    the grid rather than logging and continuing. The decisive check is the LAST one: with a
    correctly calibrated det budget, det binds before wall on every cell. A wall-bound run means
    either the machine is contended or the budget is mis-calibrated -- both bugs, and both
    silently produce a plausible number that is simply under-searched. On 2026-09-21 that was
    true of the first two cells of the grid and nothing noticed until three cells in.
    """
    p = dump_path(cell, size, prox, seed)
    if not os.path.exists(p):
        return "no dump written"
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        return "dump unreadable (%s)" % type(e).__name__
    if d.get("objVal") is None:
        return "dump carries no objVal"
    if not d.get("_production_d243"):
        return "not the production configuration"
    if not (d.get("_posts_26") and d.get("_valid_bigm")):
        return "posts_26=%s valid_bigm=%s -- not the frozen config" % (d.get("_posts_26"),
                                                                      d.get("_valid_bigm"))
    # A run that used its whole wall budget is now the NORMAL case, not a defect. The old
    # check rejected `ran >= 0.98 * cap` as "the det budget never bound, this run is
    # under-searched" -- which stops meaning anything once the wall IS the stop rule. It was
    # also wrong at the design level: per_run_s was a flat per-size number while wall_cap is
    # per-cell, so on any cell whose fair share fell below per_run_s the det budget was sized
    # for a longer run than the wall allowed and the wall HAD to bind. That was 95 of 243
    # grid cells -- the check would have halted the grid on more than a third of its work.
    #
    # What still deserves a halt is the opposite: a run that stopped far SHORT of its budget,
    # which means it died rather than finished.
    ran = float(d.get("_run_wall_s") or 0)
    cap = float(d.get("_wall_budget_s") or 0)
    if cap and ran < 0.5 * cap:
        return ("SHORT: ran %.0f s of a %.0f s budget (%.0f%%), so it stopped for a reason "
                "other than the budget -- diagnose before banking." % (ran, cap, 100.0 * ran / cap))
    return None


def run_cell(cell, size, prox, exhibit, seed, threads, cal, factor):
    dump = dump_path(cell, size, prox, seed)
    log = os.path.join(ROOT, "logs", "grid_%s_n%d_p%s_s%d.out" % (cell, size, prox, seed))
    # per_run_s from the calibration WINS when present. The envelope is a CAP, not a
    # quota: n10 is deliberately given far less than its share because every cell there
    # is a K-proven optimum and the question is attainment, not depth.
    # PER-CELL, and per_run_s is a CEILING rather than an override. It exists so n10 can
    # take 300 s against a ~4,600 s envelope -- attainment, not depth. Applied as an
    # override it silently discarded the per-cell deduction: at n30 R209's LB ran 3,567 s,
    # leaving 439 s per run, and the flat 901 s would have spent TWICE its fair budget on
    # exactly the cell a fairness challenge targets. A ceiling can only ever spend less.
    fair = envelope(size, factor, cell) / cal[size]["seeds"]
    ceil_s = cal[size].get("per_run_s")
    wall_cap = min(fair, float(ceil_s)) if ceil_s else fair
    # WALL IS THE DECLARED STOP RULE (primal-harness-blocking-defects-v3, 2026-09-22).
    # No --det-budget. It bound on 31% of n100 runs and 68% of n20 over the whole corpus,
    # and 34 of 137 / 1 of 19 in the last three days -- so it was already not the stop rule
    # on most runs, while every row was labelled as though it were. It also works AGAINST
    # the budget claim it was assumed to support: under a tick budget our wall spend varies,
    # so the envelope becomes an approximation of itself, whereas under wall stopping our
    # per-cell spend is EXACTLY K_CAP/factor -- 5760 our-seconds == 14400 K-seconds.
    # What replaces it is not a budget but a MEASUREMENT: fixopt records det_used, so a
    # contended run stays detectable afterwards even though nothing was equalised at run
    # time. Gate G14 enforces that field exists.
    cmd = [sys.executable, os.path.join(ROOT, "solver", "engines", "fixopt.py"),
           "--instance", cell, "--size", str(size), "--seed", str(seed),
           "--threads", str(threads),
           "--budget", str(round(wall_cap, 1)),
           "--variant", "grid", "--dump-best", dump]
    k_prox = {"table3": 0.0, "table4": 0.0, "table6": 0.1}[exhibit]
    if abs(prox - k_prox) > 1e-9:
        cmd += ["--proximity", str(prox),
                "--proximity-ack",
                "K's proximity for %s is INFERRED from S5.4's base scenario, not stated. This "
                "arm runs the alternative reading (%.1f) so the claim holds under either."
                % (exhibit, prox)]
    else:
        cmd += ["--k-exhibit", exhibit]
    fh = io.open(log, "w", encoding="utf-8")
    return subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT), log


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=4)
    # ONE cell at a time. Two x 4 threads on 4 cores inflates every runtime, and time-to-best
    # is now a reported quantity rather than a diagnostic.
    ap.add_argument("--concurrent", type=int, default=1)
    ap.add_argument("--hw-factor", type=float, default=HW_FACTOR_ENVELOPE,
                    help="hardware normalisation. Default is the STRICTEST tested (2.5), so a "
                         "budget claim made here survives the whole HW_FACTORS range.")
    ap.add_argument("--sizes", default="",
                    help="restrict to these sizes, e.g. '100'. Empty = the full 243-cell grid. "
                         "A restricted run is COVERAGE, not the grid: it produces the family "
                         "means K publish at that size and nothing else, and must be reported "
                         "as such.")
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    rows = grid_rows()
    if a.sizes:
        want = set(int(x) for x in a.sizes.split(","))
        rows = [r for r in rows if r[0] in want]
        if not rows:
            sys.exit("no grid rows for sizes %s" % sorted(want))
    total = sum(len(cells) for _s, _p, _e, cells, _w in rows)
    cal = calibration()

    print("BUDGET-MATCHED GRID -- seed %d" % a.seed)
    print("   K's cap %.0f s of THEIR seconds; at factor %.1f that is %.0f s of ours."
          % (K_CAP_THEIR_SECONDS, a.hw_factor, K_CAP_THEIR_SECONDS / a.hw_factor))
    print()
    print("   %5s %5s %-8s %6s %10s %10s %9s  %s"
          % ("n", "p", "exhibit", "cells", "LB s", "primal s", "per run", "what K report"))
    for size, prox, exhibit, cells, why in rows:
        env = envelope(size, a.hw_factor)
        per = (float(cal[size].get("per_run_s") or env / cal[size]["seeds"])
               if cal else None)
        print("   %5d %5s %-8s %6d %10.0f %10.0f %9s  %s"
              % (size, prox, exhibit, len(cells), lb_seconds()[size], env,
                 ("%.0f" % per) if per else "NEEDS CALIB", why))
    print()
    print("   %d runs per seed." % total)

    if cal is None:
        print()
        print("   REFUSING: no %s." % os.path.relpath(CALIB, ROOT))
        print("   It must give, per size, the number of seeds N and the deterministic budget.")
        print("   Those are not guessable: det_tl miscalibration has already caused a documented")
        print("   regression (k=15 needed 589,199 ticks; 450,000 cut it off), and N versus")
        print("   per-run length is the whole best-of tradeoff under a fixed envelope.")
        return 2

    if a.plan_only:
        print()
        print("   --plan-only; nothing ran.")
        return 0

    from analysis.launch_budget_matched import gate, canary
    from repro_preflight import code_hash
    ch = code_hash()
    bad = gate()
    if bad:
        print("   REFUSING TO LAUNCH -- %d gate failure(s):" % len(bad))
        for b in bad:
            print("      %s" % b)
        return 1
    print("   gate passed   frozen code_hash %s" % ch)
    cbad = canary(rows[0][3][0], 100, a.seed, a.threads)
    if cbad:
        print("   CANARY FAILED -- not launching:")
        for b in cbad:
            print("      %s" % b)
        return 1
    print("   canary OK: dump path, verifier3 ACCEPT, provenance PRODUCTION")
    print()

    # SEQUENTIAL, and each cell is inspected the moment it lands. Two cells at four threads on a
    # four-core machine makes every runtime meaningless, and a defect found at cell 3 is cheap
    # while the same defect found at cell 243 costs the pass.
    done_n, t0 = 0, time.time()
    for size, prox, exhibit, cells, _why in rows:
        for cell in cells:
            if done_and_current(cell, size, prox, a.seed, ch):
                done_n += 1
                continue
            proc, log = run_cell(cell, size, prox, exhibit, a.seed, a.threads, cal, a.hw_factor)
            proc.wait()
            problem = inspect(cell, size, prox, a.seed, cal)
            if not problem:
                # A discarded candidate does not disqualify a verified result; a dumped
                # solution the verifier rejects does. grid_rejects tells them apart, banks
                # the first and halts on the second.
                from analysis.grid_rejects import triage as _triage_rejects
                problem = _triage_rejects(cell, size, prox, a.seed,
                                          dump_path(cell, size, prox, a.seed))
            if problem:
                print()
                print("   HALTED at %s n%d p%s -- %s" % (cell, size, prox, problem))
                print("   %s" % os.path.relpath(log, ROOT))
                print()
                print("   A quarantine is a bug signal, not a filing action. Diagnose before")
                print("   resuming: this driver is resumable, so nothing already done is lost.")
                return 1
            done_n += 1
            print("   [%3d/%3d] %-7s n%-4d p%-4s %-7s  (%.1f h elapsed)"
                  % (done_n, total, cell, size, prox, exhibit, (time.time() - t0) / 3600),
                  flush=True)
    print()
    print("   SEED %d COMPLETE -- %.1f h" % (a.seed, (time.time() - t0) / 3600))
    print("   Verify every dump before any mean is taken: a mean over unverified cells, or over")
    print("   fewer than 27, is not comparable to K's 27-cell aggregate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
