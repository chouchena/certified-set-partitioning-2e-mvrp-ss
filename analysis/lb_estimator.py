#!/usr/bin/env python
"""The canonical per-cell dual-bound estimator. ONE definition, imported everywhere.

PREREG: validation/PREREG_n100_budget_equalisation.md, Amendment 6.

    reported_bound(cell) = max{ block_relax(r) : r a record, r did NOT stop on the wall clock }

WHY A MAX. Every record is a valid lower bound on the optimum -- a truncated dual bound is
still a dual bound (L-step0), and the block relaxation is valid by L-block and L-restrict. The
maximum of valid lower bounds is a valid lower bound. This is why the estimator may range over
records at different k without any monotonicity assumption.

WHY EXCLUDE WALL-STOPPED RECORDS. The descent is passed both `--det-tl` (ticks) and `--tl`
(seconds) and whichever binds first wins. A record that stopped on `--det-tl` reproduces
exactly -- measured: 7 of 7 matched-k pairs reproduced not just the bound but the TICK COUNT to
the decimal. A record that stopped on `--tl` cannot reproduce, because the tick count at which
the clock ran out depends on machine load; 6 of 6 such pairs drifted, by up to +6.82.

So excluding wall-stopped records buys reproducibility. It costs bound quality, and the trade is
registered in Amendment 6 rather than chosen after the fact.

THE EXCLUSION CAN ONLY LOWER THE REPORTED BOUND. It is a max over a SUBSET, so it is weakly
dominated by the max over everything. The change therefore runs against us -- it cannot inflate
a result, only shrink one. That is the whole reason it is safe to adopt on partial sight.

WHAT IS NOT EXCLUDED. A record whose `limit_hit` is neither `det` nor `wall` terminated on the
solver's own optimality proof. Those are the BEST records, not the worst, and dropping them
would be an error -- an earlier draft of this pricing did exactly that and undercounted RC205.
The test is `limit_hit == "wall"`, never `limit_hit != "det"`.
"""
from __future__ import annotations


def is_reproducible(record) -> bool:
    """A record reproduces unless the wall clock is what stopped it.

    Records predating the `limit_hit` field are treated as reproducible: the field was added
    when the two-limit race was found, and back-filling a guess would be worse than the
    omission. Their provenance is carried by `det_tl`/`tl` in the record itself.
    """
    return record.get("limit_hit") != "wall"


def cell_bound(records, reproducible_only: bool = True):
    """Reported dual bound for one cell. Returns None if no record qualifies."""
    vals = [
        r.get("block_relax")
        for r in records
        if isinstance(r.get("block_relax"), (int, float))
        and (is_reproducible(r) if reproducible_only else True)
    ]
    return max(vals) if vals else None


def cell_bound_pair(records):
    """(reproducible bound, all-records bound). Amendment 6 requires BOTH be reportable."""
    return cell_bound(records, True), cell_bound(records, False)


def wall_census(records):
    """How many records stopped on each limit. For the disclosure Amendment 6 mandates."""
    out = {}
    for r in records:
        key = r.get("limit_hit") or "unrecorded"
        out[key] = out.get(key, 0) + 1
    return out


# ---------------------------------------------------------------------------
# THE FRONTIER. A DIFFERENT QUANTITY, KEPT SEPARATE ON PURPOSE.
#
# `cell_bound` answers "what is the strongest bound we can certify for this cell".
# `frontier` answers "how large a retained set can the descent PROVE" -- the method's own
# headline, and the quantity the retained-set-versus-size figure plots.
#
# Until 2026-09-16 these were the same function, triplicated verbatim in manuscript_numbers.py,
# make_tables.py and make_figures.py, and it returned the PROVEN record at the smallest k --
# discarding stronger valid records when any record was proven. That cost up to 5.86% of our own
# bound (R206/n50: 792.97 reported against 839.46 available) and, worse, it silently switched to
# a max when nothing was proven, so n50 (27/27 on the proven branch) and n100 (9/27) were
# measured by different rules along the axis the degradation claim runs on.
#
# The split is the fix: the bound is always `cell_bound`; the frontier is asked for by name
# where the frontier is what is meant. See validation/AUDIT_estimator_specification.md E1.
# ---------------------------------------------------------------------------

def frontier(records):
    """(k, nH, certifies) at the smallest PROVEN k. (None, None, False) if nothing proved.

    Deliberately returns no bound. Callers that want a number want `cell_bound`; conflating the
    two is the defect this split exists to prevent.
    """
    proven = [r for r in records if r.get("proven")]
    if not proven:
        return None, None, False
    k = min(r["k"] for r in proven)
    rec = next(r for r in proven if r["k"] == k)
    return k, rec.get("nH"), True


def certifies(records):
    """Does this cell prove its relaxation anywhere? The stratification flag."""
    return any(r.get("proven") for r in records)


def frontier_bound(records):
    """block_relax AT the proved frontier. None when nothing is proved.

    S3a's pre-committed primary outcome (PREREG_S3a Amendment 1): the bound at the SMALLEST k an
    arm can prove. That amendment corrected the outcome from "largest common k" to "smallest",
    because block_relax is monotone decreasing in k and the original wording compared the arms'
    WEAKEST bounds -- the "backwards primary outcome" recorded in CLAUDE.md.

    NOT the same as `cell_bound`, and the ablation is right to use this one. Comparing retained-set
    policies needs a quantity each policy PROVES, so the comparison cannot be contaminated by how
    far a truncated solve happened to get. `cell_bound` is the reporting quantity; this is the
    comparison quantity.
    """
    k, _, ok = frontier(records)
    if not ok:
        return None
    return next(r["block_relax"] for r in records if r.get("proven") and r["k"] == k)


def bound_record(records, reproducible_only: bool = True):
    """The record that supplies `cell_bound`, for provenance and for its nH."""
    best, bv = None, None
    for r in records:
        v = r.get("block_relax")
        if not isinstance(v, (int, float)):
            continue
        if reproducible_only and not is_reproducible(r):
            continue
        if bv is None or v > bv:
            best, bv = r, v
    return best
