"""Bank the valid output, keep watching the bug.

Author, 2026-09-21: *"We keep ongoing runs, monitor further appearances of the bug, bank valid
outputs and enter a thorough analysis of how the bug is created."*

THE SITUATION. fixopt quarantines a run when ANY candidate was rejected in its improvement
stream -- including one that was DISCARDED and never adopted, because `best_sol` only takes
candidates where `vd.ok`. The engine's CLAIM is its dumped best, not every candidate it
considered, so a discarded candidate does not disqualify the result:

  * measured rate: 1 rejected candidate in 695, across 23 production-config runs (0.14%)
  * 22 of those 23 runs had zero rejects and are untouched
  * the one affected run's artifact verifies clean under verifier3: 1923 checks, 0 violations

WHAT THIS DOES. After each grid cell, if a quarantine row exists for that run:

  dump verifies clean  -> record the occurrence, auto-triage the row, let the pass continue
  dump does NOT verify -> return a problem, so the grid HALTS. That is a genuine contradiction
                          between what the engine claims and what the verifier says, which is
                          exactly what the 2026-09-18 rule exists to stop.

WHAT IT DOES NOT DO. It does not excuse the defect, and it does not fix it. Every occurrence is
appended to runs/c26_rejects.jsonl so the rate is countable rather than anecdotal, and the
mechanism analysis is tracked separately in validation/FINDING_c26_rejected_candidates.md.

MECHANISM, HONESTLY UNRESOLVED. An earlier claim that the operator "is not (26)-aware" was wrong
and is withdrawn: joint_model_cplex:273 emits (26) whenever `hardSingleTransfer` is set, and
fixopt:1428 sets it on `prob.raw`, whose single `build_joint_model` call at `improve()` reaches
every sub-solve, kick and restart. The leading hypothesis is a tolerance boundary -- the solver
satisfying (26) within its feasibility tolerance while verifier3's exact 1e-6 check rejects a gap
of tau minus epsilon -- but the rejected candidate is never dumped, so nothing confirms it.
"""
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECT_LOG = os.path.join(ROOT, "runs", "c26_rejects.jsonl")
INDEX = os.path.join(ROOT, "runs", "invalid", "INDEX.md")


def triage(cell, size, prox, seed, dump_path):
    """None to continue; a string to halt the grid."""
    if not os.path.exists(INDEX):
        return None
    txt = io.open(INDEX, encoding="utf-8", errors="replace").read()
    tag = "_%s_n%d_s%d_grid_" % (cell, size, seed)
    # "Untriaged" is quarantine_guard's call, not a search for **NO** here. This searched for the
    # literal and so missed a row whose triaged cell is simply BLANK, which the authority counts as
    # untriaged -- a row that would then have been treated as already handled. (d591)
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    import quarantine_guard as QG
    untriaged = {r["run_id"] for r in QG.rows() if QG.is_untriaged(r)}
    rows = [l for l in txt.splitlines() if tag in l and any(rid in l for rid in untriaged)]
    if not rows:
        return None

    try:
        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        import verifier3
        run = verifier3.verify(dump_path)
        clean = run.verdict() == verifier3.ACCEPT and not run.violations
        checks = run.total_checks
    except Exception as exc:
        return "quarantined, and verifier3 could not run on the dump (%s)" % type(exc).__name__

    with io.open(REJECT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"cell": cell, "size": size, "proximity": prox, "seed": seed,
                             "dump_verifies": clean, "checks": checks,
                             "index_row": rows[0][:300],
                             "when": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")

    if not clean:
        return ("quarantined AND the dumped solution does not verify -- a genuine "
                "claim/verifier contradiction, not a discarded candidate")

    io.open(INDEX, "w", encoding="utf-8", newline="\n").write(
        txt.replace(rows[0],
                    rows[0].replace("**NO**", "**auto-triaged: dump verifies clean**"), 1))
    print("   reject observed at %s n%d p%s -- candidate discarded, dump verifies clean "
          "(%d checks). Banked; logged to runs/c26_rejects.jsonl"
          % (cell, size, prox, checks), flush=True)
    return None


def rate():
    """How often, across everything recorded so far. For the finding, not for the run."""
    if not os.path.exists(REJECT_LOG):
        return 0
    return sum(1 for l in io.open(REJECT_LOG, encoding="utf-8") if l.strip())
