#!/usr/bin/env python
"""Forward prediction and determinism audit for the n100 budget equalisation.

PREREG: validation/PREREG_n100_budget_equalisation.md, Amendment 5.

Two questions, both answerable from the BANKED 2400 s artifacts alone, i.e. before the
re-runs land. That is the point: a prediction made from data that already exists is a
prediction, not an explanation.

  (1) CAN A CELL'S BOUND IMPROVE AT ALL?
      easy_reduction_descend has two ways to spend budget. It escalates k upward while
      solves fail to certify, and it descends only after a solve CERTIFIES. A cell whose
      banked records are all `proven=False` has never entered the descent, so extra budget
      buys additional escalation records at higher k. Under monotone nesting (L-nest) the
      relaxation value is non-increasing in k, so those added records are EXPECTED to be
      weaker than the incumbent max and the estimator -- a max over all records -- is
      expected to be unchanged.

      NOT "cannot improve". The recorded values are TRUNCATED dual bounds, not the
      relaxation optima, so nesting does not order them. R205's own banked records go
      1070.27 at k=67 then 1074.85 at k=68: the truncated value rose with k. An added
      record CAN therefore exceed the incumbent max. The prediction is directional, and
      a nonzero improvement on an escalation-only cell refutes nothing except the word
      "expected".

  (2) IS THE COMPARISON MEASURING THE BUDGET AT ALL?
      Each record stops on one of two limits and says which in `limit_hit`: the
      deterministic tick budget (`det`, --det-tl) or the wall clock (`wall`, --tl). A
      wall-stopped record is not reproducible by construction -- the tick count where it
      stopped depends on machine load. Re-running the same cell re-solves the same k
      values, so any wall-stopped record re-solves to a DIFFERENT value, and that drift
      enters the reported delta alongside the budget effect.

      This is the audit that matters. CLAUDE.md fixes det_tl, not wall-clock, "wherever a
      result must reproduce" -- but the descent passes BOTH, and --tl wins whenever it
      binds first.

Usage:
    python analysis/n100_budget_forward_check.py            # report
    python analysis/n100_budget_forward_check.py --check    # exit 1 if a det/det pair drifts
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))

# The ten selected by the mechanical criterion in PREREG section 2. Fixed there, not here.
CELLS = ["R202", "R203", "R205", "R206", "R208", "R209", "R210", "RC202", "RC204", "RC205"]

BASE = "crossfeed/easy_reduction_descend_{cell}_n100.json"
RERUN = "crossfeed/easy_reduction_descend_{cell}_n100_bq{budget}.json"
BUDGETS = [9000, 18000, 36000]  # the Amendment 3 escalation ladder


def _load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None
    try:
        with open(full, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _rerun_path(cell):
    """Highest banked escalation rung for a cell, or None."""
    for budget in reversed(BUDGETS):
        path = RERUN.format(cell=cell, budget=budget)
        if _load(path) is not None:
            return path
    return None


def _complete(cell, path):
    """Did this re-run FINISH, or is it mid-flight?

    The descent rewrites its JSON after every record, so the file existing proves nothing.
    The driver log is the only witness that a cell finished: it writes "<cell> at <budget>
    done" only after the subprocess returns.
    """
    log = _load_text("logs/n100_budget_equalisation/driver.txt")
    if log is None:
        return None  # cannot tell
    return any(line.startswith(cell + " at ") and " done (exit=" in line for line in log)


def _load_text(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None
    with open(full, "r", encoding="utf-8") as fh:
        return [ln.split("] ", 1)[-1].strip() for ln in fh]


from lb_estimator import cell_bound, cell_bound_pair, wall_census  # noqa: E402


def _estimator(records):
    """The REPORTED bound: max over reproducible records only (PREREG Amendment 6)."""
    return cell_bound(records, reproducible_only=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any matched-k det/det pair fails to reproduce exactly")
    args = ap.parse_args()

    print("=" * 78)
    print("(1) FORWARD PREDICTION -- can extra budget reach the descent?")
    print("=" * 78)
    print("%-8s %-6s %-9s %-11s %s" % ("cell", "recs", "certifies", "status", "prediction"))

    predictions = {}
    for cell in CELLS:
        base = _load(BASE.format(cell=cell))
        if base is None:
            print("%-8s  NO BANKED ARTIFACT -- not predicted" % cell)
            continue
        proven_ks = [r.get("k") for r in base if r.get("proven")]
        path = _rerun_path(cell)
        if path is None:
            status = "to run"
        elif _complete(cell, path):
            status = "done"
        else:
            status = "IN FLIGHT"
        if proven_ks:
            pred = "descent CAN run at k=%s -> improvement possible" % min(proven_ks)
        else:
            pred = "escalation only -> no improvement EXPECTED"
        predictions[cell] = (bool(proven_ks), status)
        print("%-8s %-6d %-9s %-11s %s"
              % (cell, len(base), bool(proven_ks), status, pred))

    n_esc = sum(1 for c, (p, _) in predictions.items() if not p)
    n_desc = len(predictions) - n_esc
    print()
    print("  %d of %d cells are escalation-only; %d can descend."
          % (n_esc, len(predictions), n_desc))

    print()
    print("=" * 78)
    print("(2) DETERMINISM AUDIT -- which limit actually stopped each record?")
    print("=" * 78)
    print("%-8s %-6s %-6s %-6s %s" % ("cell", "recs", "wall", "det", "other"))
    tot = {"wall": 0, "det": 0, "other": 0, "n": 0}
    for cell in CELLS:
        base = _load(BASE.format(cell=cell))
        if base is None:
            continue
        w = sum(1 for r in base if r.get("limit_hit") == "wall")
        d = sum(1 for r in base if r.get("limit_hit") == "det")
        o = len(base) - w - d
        tot["wall"] += w
        tot["det"] += d
        tot["other"] += o
        tot["n"] += len(base)
        print("%-8s %-6d %-6d %-6d %d" % (cell, len(base), w, d, o))
    print()
    print("  %d of %d banked records stopped on the WALL clock, not the tick budget."
          % (tot["wall"], tot["n"]))
    print("  A wall-stopped record is not reproducible: --tl binds before --det-tl.")

    print()
    print("=" * 78)
    print("(3) MATCHED-k REPRODUCTION -- same cell, same k, only --cell-budget differs")
    print("=" * 78)
    print("  Any nonzero delta here is NOT a budget effect. The budget controls how many")
    print("  records get run, never the value of a record that both runs share.")
    print()
    print("  %-7s %-4s %-10s %-10s %-9s %s" % ("cell", "k", "banked", "re-run", "delta", "limit_hit base/re-run"))

    failures = []
    drift_det, drift_wall = [], []
    for cell in CELLS:
        base = _load(BASE.format(cell=cell))
        path = _rerun_path(cell)
        if base is None or path is None:
            continue
        rerun = _load(path)
        if rerun is None:
            continue
        b = {r["k"]: r for r in base if "k" in r}
        q = {r["k"]: r for r in rerun if "k" in r}
        for k in sorted(set(b) & set(q)):
            bv, qv = b[k].get("block_relax"), q[k].get("block_relax")
            if bv is None or qv is None:
                continue
            delta = qv - bv
            lb, lq = b[k].get("limit_hit"), q[k].get("limit_hit")
            both_det = (lb == "det" and lq == "det")
            # SAME CODE OR NOT. PREREG section 6.4 warned in advance that `det_tl` does not
            # survive a code change, and every pair here spans dcdc9666 -> 55a75f0f. So a
            # det/det disagreement is only a DETERMINISM failure when the code_hash matches;
            # across a code change it is the documented behaviour, and what matters is its
            # magnitude relative to the wall-induced drift the estimator exists to exclude.
            same_code = (b[k].get("code_hash") == q[k].get("code_hash"))
            flag = ""
            if abs(delta) > 1e-9:
                (drift_det if both_det else drift_wall).append((cell, k, delta))
                if both_det and same_code:
                    flag = "  <-- DETERMINISM FAILURE (same code_hash)"
                    failures.append((cell, k, delta))
                elif both_det:
                    flag = "  <-- code_hash differs; PREREG 6.4 expects this"
            print("  %-7s %-4d %-10.2f %-10.2f %+9.2f %s/%s%s"
                  % (cell, k, bv, qv, delta, lb, lq, flag))

    n_det_pairs = 0
    for cell in CELLS:
        base = _load(BASE.format(cell=cell))
        path = _rerun_path(cell)
        if base is None or path is None:
            continue
        rerun = _load(path)
        b = {r["k"]: r for r in base if "k" in r}
        q = {r["k"]: r for r in rerun if "k" in r}
        for k in sorted(set(b) & set(q)):
            if b[k].get("limit_hit") == "det" and q[k].get("limit_hit") == "det":
                n_det_pairs += 1

    print()
    print("  det/det pairs:            %d, of which %d drifted" % (n_det_pairs, len(drift_det)))
    print("  pairs touching the wall:  %d, of which %d drifted"
          % (_wall_pairs(), len(drift_wall)))
    if drift_det:
        worst_d = max(drift_det, key=lambda t: abs(t[2]))
        print("  largest det-side drift:     %s k=%d  %+.4f  (across a code change)" % worst_d)
    if drift_wall:
        worst = max(drift_wall, key=lambda t: abs(t[2]))
        print("  largest wall-induced drift: %s k=%d  %+.2f" % worst)
    # THE RATIO IS THE POINT. The estimator excludes wall-stopped records; this says by how much
    # that beats the residual code-change effect it cannot exclude.
    if drift_det and drift_wall:
        wd = max(abs(t[2]) for t in drift_wall)
        dd = max(abs(t[2]) for t in drift_det)
        print("  wall drift exceeds det drift by %.0fx -- the separation Amendment 6 rests on"
              % (wd / dd if dd else float("inf")))

    print()
    print("=" * 78)
    print("(4) PER-CELL ESTIMATOR -- PREREG Amendment 6, banked vs re-run")
    print("=" * 78)
    print("  `repro` excludes wall-stopped records and is what the paper reports.")
    print("  `all` is the max over everything. Both are valid LBs; only `repro` re-derives.")
    print()
    for cell in CELLS:
        base = _load(BASE.format(cell=cell))
        path = _rerun_path(cell)
        if base is None or path is None:
            continue
        rerun = _load(path)
        eb, eb_all = cell_bound_pair(base)
        eq, eq_all = cell_bound_pair(rerun)
        if eb is None or eq is None:
            continue
        status = "done" if _complete(cell, path) else "IN FLIGHT -- not final"
        note = ""
        if abs(eq_all - eq) > 1e-9:
            note = "   [all=%.2f, +%.2f = %.2f%% forgone for reproducibility]" % (
                eq_all, eq_all - eq, (eq_all - eq) / eq_all * 100)
        print("  %-7s banked=%9.2f  re-run=%9.2f  delta=%+7.2f   (%s)%s"
              % (cell, eb, eq, eq - eb, status, note))
        print("          limit_hit  banked=%s  re-run=%s"
              % (wall_census(base), wall_census(rerun)))

    if args.check:
        if failures:
            print()
            print("FAIL: %d matched-k pair(s) stopped on the deterministic limit in BOTH runs "
                  "and still disagreed." % len(failures))
            for cell, k, delta in failures:
                print("  %s k=%d delta=%+.6f" % (cell, k, delta))
            return 1
        print()
        print("OK: no matched-k pair at the SAME code_hash disagreed. Of %d det/det pairs, %d "
              "drifted across the code change PREREG 6.4 warned of." % (n_det_pairs, len(drift_det)))
    return 0


def _wall_pairs():
    """Count matched-k pairs where at least one side stopped on the wall."""
    n = 0
    for cell in CELLS:
        base = _load(BASE.format(cell=cell))
        path = _rerun_path(cell)
        if base is None or path is None:
            continue
        rerun = _load(path)
        if rerun is None:
            continue
        b = {r["k"]: r for r in base if "k" in r}
        q = {r["k"]: r for r in rerun if "k" in r}
        for k in sorted(set(b) & set(q)):
            if not (b[k].get("limit_hit") == "det" and q[k].get("limit_hit") == "det"):
                n += 1
    return n


if __name__ == "__main__":
    sys.exit(main())
