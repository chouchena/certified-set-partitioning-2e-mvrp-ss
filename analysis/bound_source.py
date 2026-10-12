"""WHICH dual instrument a reported bound comes from, as a run parameter (d441).

The project now has two lower-bound instruments that can be reported on the same cell:

  descent   the frozen leg -- `dual_vs_k.lb_frontier`, falling back to `lb_maxrec`. Its validity
            is a PROOF (`validation/easy_reduction_bound_proof.md`, steps 1-2), with a 54-cell
            falsification run testing the implementation rather than the mathematics
  tep       the TEP column-generation bound, composed as the master's LP street part plus the
            arithmetic water term from the AB grid. It is reportable only where the run CONVERGED,
            and it is SUSPENDED at n100 (claim `tep-cg-bounds-suspended-pending-proof`)
  best      the larger of the two on that cell

THE RUNTIME RULE BINDS HERE, and it is the reason this is a parameter and not a default.
Per d245/d246/d250 and `analysis/run_full_grid.py`, **every bound instrument whose value is
reported is charged** against the cell's envelope of K_CAP/2.5 = 5,760 our-seconds, and the LB
wall is deducted BEFORE the primal gets anything. So `best` costs the sum of both walls on every
cell, including the cells where one of them loses. Measured cost of adding TEP to the descent, as
a share of the cell budget: 0.4% median at n20 and n30, 4.1% median at n100 and 24.2% on its worst
n100 cell. No cell is exhausted, but at n100 seconds taken from the primal are objective value,
because every seed is still improving when it is cut off.

`charged_seconds` returns what the choice costs, so no caller can report a bound without also
being able to report its price.

    python analysis/bound_source.py --size 30 --source best
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from bound_certificate import certified, ng_certified, best_valid   # d519: readers require the elementary certificate, not the flag

SOURCES = ("descent", "tep", "best")
#: Sizes at which the TEP bound may be reported. n100 WAS suspended (claim
#: tep-cg-bounds-suspended-pending-proof, 2026-09-26) pending a recomputation that stored the
#: certificate. That recomputation ran on 2026-09-27 -- 88 of 89 pairs certified, every
#: comparable value unchanged to 1e-6 -- and the suspending record's own reopen condition was
#: "the recomputation certifying every value unchanged, WHICH LIFTS THE SUSPENSION". The
#: n100 family row was re-admitted the same day. This constant simply never caught up, so it
#: went on refusing a leg the ledger had already re-admitted. Corrected 2026-09-29.
TEP_REPORTABLE_SIZES = (10, 20, 30, 50, 100)


def _ab(cell, size):
    recs = json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]
    for r in recs:
        if r["cell"] == cell and r["size"] == size:
            return r
    return None


def _ab4_seconds(cell, size):
    """AB4's measured wall on this cell, from the timed grid run. None if never timed.

    Charged like any other reported instrument (d245/d246/d250). It is small -- median 0.023 s,
    17 s across all 135 cells -- but "small" is not "free", and the rule says charged.
    """
    p = os.path.join(ROOT, "runs", "oracle", "ab4_grid_rt.json")
    try:
        for r in json.load(io.open(p, encoding="utf-8"))["rows"]:
            if r.get("cell") == cell and r.get("size") == size:
                return float(r["total_s"]) if r.get("total_s") is not None else None
    except Exception:
        return None
    return None


def descent_bound(cell, size):
    """The frozen leg's bound on this cell, and its wall in our seconds."""
    import dual_vs_k as D
    from analysis.run_full_grid import lb_cell_seconds
    v = D.lb_frontier(cell, size) or D.lb_maxrec(cell, size)
    return (float(v) if v else None), lb_cell_seconds(cell, size)


def tep_bound(cell, size, allow_suspended=False):
    """The composed TEP bound, or None when it is not reportable, and its wall.

    Returns None unless the run CONVERGED. An unconverged master's value is an upper bound on the
    relaxation, not a lower bound on the problem, and reporting one is the d427 defect.
    """
    if size not in TEP_REPORTABLE_SIZES and not allow_suspended:
        return None, None, "suspended at n%d" % size

    # THE LOOKUP IS best_known._bound_patterns, NOT A HAND-BUILT PATH (2026-09-28).
    #
    # This function used to build exactly one path, tep_cg_bound_<cell>[_n<size>].json, and take
    # its absence -- or its certified() verdict -- as final. The real artifacts carry suffixes:
    # _ip, _d20, _d10, _d5. Measured over the grid, that single path MISSED A CERTIFIED ARTIFACT
    # ON 85 OF 135 CELLS: 24 of 27 at n10, 6 at n20, 1 at n30, and ALL 27 at both n50 and n100,
    # where it found nothing whatsoever. Every reader of this accessor -- release_gate,
    # free_falsifiers, tep_n100_family_table -- was under-reporting the dual leg on two entire
    # sizes.
    #
    # It is the same defect that made baseline_audit report "dual 108/135" when the truth was
    # 135/135, and it has the same fix: _bound_patterns is the single authority for "which
    # artifacts hold a bound for this cell", and callers import it rather than re-deriving it.
    #
    # Taking the MAX over the matching artifacts is not a new liberty: TEP_FORMULATION section 5
    # already says the reported bound per cell is the largest proven LP over the widths run,
    # because the maximum of valid lower bounds is a valid lower bound.
    # bound_artifacts, not the raw patterns: it applies the two filters that make them correct
    # (the artifact's own size field must match, INVALID_ files skipped). Globbing the patterns
    # directly pulled n50 artifacts into every n100 cell -- 13 of C201's 23 matches were another
    # size -- and reported an n50 LP as the n100 bound.
    from best_known import bound_artifacts
    cands = bound_artifacts(cell, size)
    if not cands:
        return None, None, "no artifact"
    valued = [(q, e) for q, e in cands if e.get("lp_street") is not None]
    if not valued:
        return None, None, "no value"
    # A REDUCED-INSTANCE ARTIFACT IS NOT A FULL-CELL TEP BOUND (2026-09-29, caught on review
    # before anything reported it). _bound_patterns includes tep_easy_reduction_*_k*.json at
    # n100, and those carry a `drop` field: they are solved over H = C minus the k easiest
    # customers. validation/easy_reduction_bound_proof.md licenses exactly one composition,
    # z_A(H)* + w(full) <= z_joint*, and Step 0 extends it to "any valid dual bound d OF THAT
    # SAME PROBLEM" -- block A. The `lp_street` in these artifacts is the TEP MASTER's LP on the
    # reduced instance, a DIFFERENT model, and the proof's Step 2 splicing argument has never
    # been re-run for it. Composing it with water_ab would publish a number whose validity
    # nobody has established, which is the worst error this project can make. Excluded until
    # the subset-monotonicity argument is proven for the TEP master.
    # ELEMENTARY FIRST, ng AS A LABELLED SECOND TIER (2026-09-29). Refusing ng outright was
    # over-conservative and cost 1,300-1,470 per cell at n100, where the banked bounds are 23 ng
    # to 4 elementary. d427's finding is that ng convergence does not certify the ELEMENTARY LP
    # -- which is about what the bound may be CALLED, not whether it is one. ng_certified's own
    # contract: "a WEAKER BUT VALID CERTIFICATE ... the LP is the optimum over that class and is
    # a lower bound on the elementary LP, hence on the optimum", i.e. LP(ng) <= LP(elem) <= OPT.
    # The class is returned to the caller so nothing reports an ng bound as an elementary one.
    # THE CLASS LABELS THE WINNER; IT DOES NOT FILTER THE FIELD. A first version preferred
    # elementary and only fell back to ng, which DISCARDS A HIGHER VALID BOUND whenever the ng
    # artifact is the stronger one -- C204 n50 lost 117.7 that way (1270.1 taken over an
    # available 1387.9). Both classes are valid lower bounds, and the maximum of valid lower
    # bounds is valid, so the max is taken over BOTH and the class is read off whichever won.
    usable = [(q, e) for q, e in valued
              if not e.get("primal_rounding") and not e.get("drop")]
    ok = [(q, e) for q, e in usable if certified(e) or ng_certified(e)]
    klass = None
    if not ok:
        # THE DIAGNOSIS MUST NAME THE ACTUAL BLOCKER. My first version returned "ceil model" if
        # ANY candidate was ceil-rounded, which mislabelled 9 n50 cells whose real blocker is
        # that their only certificate is ng-class. certified() is elementary-only on purpose
        # (d427: ng convergence alone is not a proof), and this function does not quietly widen
        # it -- but it must say which refusal applied.
        secs = float(max((e.get("secs") or 0.0) for _, e in valued))
        straight = [e for _, e in valued if not e.get("primal_rounding") and not e.get("drop")]
        if not straight and any(e.get("drop") for _, e in valued):
            return None, secs, ("only reduced-instance (easy-reduction) artifacts: the proof "
                                "covers block A, not the TEP master LP on a subset")
        if straight and any(ng_certified(e) for e in straight):
            return None, secs, "ng-class only: not an elementary certificate (d427)"
        if straight:
            return None, secs, "not converged"
        return None, secs, "ceil model: a restriction, not a bound"
    # AT EQUAL LP THE ELEMENTARY CERTIFICATE WINS (2026-09-30). max() returned the first maximum
    # in glob order, which happened to be the canonical file because "." sorts before "_" -- a
    # sort accident, not a rule. bound_certificate.best_valid is the rule, shared by every reader.
    q, d = best_valid(ok, value=lambda t: float(t[1]["lp_street"]),
                      klass=lambda t: "elementary" if certified(t[1]) else "ng")
    klass = "elementary" if certified(d) else "ng"
    ab = _ab(cell, size)
    if ab is None:
        return None, float(d.get("secs") or 0.0), "no water term"
    # THE REPORTED BOUND IS max(COMPOSED, AB4), not the composed value alone (author,
    # 2026-09-28: "Our LB is the maximum of solver and AB4"). SKELETON's portfolio rule says so
    # -- "max(MILP, AB) is the max of two independently valid bounds" -- and this accessor was
    # returning only the composed half, so every reader of it (release_gate, free_falsifiers,
    # tep_n100_family_table) under-reported the bound on the cells where AB4 wins. Measured:
    # AB4 beats the composed value on 7 of 135 certified cells, all at |C| = 10, by up to +69.8
    # (RC208 176.468 -> 246.241). Both are valid, so the max is free and strictly better.
    composed = float(d["lp_street"]) + float(ab["water"])
    ab4 = float(ab["ab4"]) if ab.get("ab4") is not None else None
    val = composed if ab4 is None else max(composed, ab4)
    # `why` is None for an elementary bound and names the class for an ng one, so a caller that
    # prints the reason cannot present an ng bound as an elementary certificate.
    return val, float(d.get("secs") or 0.0), (None if klass == "elementary" else "class: ng")


def tep_bound_parts(cell, size, allow_suspended=False):
    """(composed, ab4, reported) for this cell -- the two portfolio halves and their max.

    tep_bound returns only the max, so a caller asking "which instrument carried this cell?"
    cannot answer it from tep_bound alone: comparing ab4 against a value that already contains
    ab4 can never report ab4. That is exactly the bug the first ab4_grid_rt run produced
    (carrier: ab4 0 of 126). The split lives here rather than in the caller so the composed
    value is never re-derived outside this module.
    """
    reported, secs, why = tep_bound(cell, size, allow_suspended=allow_suspended)
    if reported is None:
        return None, None, None
    ab = _ab(cell, size)
    ab4 = float(ab["ab4"]) if ab and ab.get("ab4") is not None else None
    composed = reported if ab4 is None else (reported if reported > ab4 + 1e-9 else None)
    if composed is None:
        # the max came from ab4; recover the composed half from the winning artifact
        import glob as _glob
        from best_known import _bound_patterns
        best = None
        for pat in _bound_patterns(cell, size):
            for q in _glob.glob(os.path.join(ROOT, "runs", "oracle", pat)):
                try:
                    e = json.load(io.open(q, encoding="utf-8"))
                except Exception:
                    continue
                if (e.get("lp_street") is not None and not e.get("primal_rounding")
                        and certified(e)):
                    if best is None or e["lp_street"] > best:
                        best = float(e["lp_street"])
        composed = None if best is None or ab is None else best + float(ab["water"])
    return composed, ab4, reported


def bound_for(cell, size, source="descent", allow_suspended=False):
    """The reported bound under `source`, which instrument won, and the seconds charged.

    `best` charges BOTH walls, because both were run and both are reported in the sense the
    runtime rule means: the reported value could have come from either, so neither is free.
    """
    assert source in SOURCES, "source must be one of %s" % (SOURCES,)
    dv, ds = descent_bound(cell, size)
    tv, ts, why = tep_bound(cell, size, allow_suspended=allow_suspended)

    # AB4 IS A PORTFOLIO MEMBER IN ITS OWN RIGHT, NOT A TERM INSIDE tep_bound (2026-09-28).
    #
    # It used to reach `best` only folded into the TEP composed bound, so whenever tep_bound
    # refused -- ng-class only, or n100 suspended -- AB4 went with it and `best` fell back to
    # the descent alone. Measured: on 25 cells that dropped a bound AB4 would have BEATEN the
    # descent, 7 at n50 and 18 at n100, by a median +197 and up to +472.
    #
    # AB4's validity does not depend on anything TEP does: it is deterministic arithmetic on
    # instance data (crossfeed/fullset_bound.py), so a missing pricing certificate is no reason
    # to discard it. Its cost is negligible and is charged anyway -- median 0.023 s per cell,
    # 17 s for the whole grid, a median 0.0069 per cent of the dual leg's own wall
    # (runs/oracle/ab4_grid_rt.json).
    ab = _ab(cell, size)
    av = float(ab["ab4"]) if ab and ab.get("ab4") is not None else None
    a_secs = _ab4_seconds(cell, size)

    if source == "descent":
        return dict(value=dv, winner="descent", charged=ds, tep_value=None, tep_why=why,
                    descent_value=dv, ab4_value=av)
    if source == "tep":
        return dict(value=tv, winner=("tep" if tv is not None else None), charged=ts,
                    tep_value=tv, tep_why=why, descent_value=dv, ab4_value=av)

    cands = [("descent", dv), ("tep", tv), ("ab4", av)]
    live = [(n, v) for n, v in cands if v is not None]
    # every instrument whose value could have been reported is charged (d245/d246/d250)
    charged = (ds or 0.0) + (ts or 0.0) + (a_secs or 0.0)
    if not live:
        return dict(value=None, winner=None, charged=charged, tep_value=None, tep_why=why,
                    descent_value=None, ab4_value=None)
    win, val = max(live, key=lambda t: t[1])
    return dict(value=val, winner=win, charged=charged, tep_value=tv, tep_why=why,
                descent_value=dv, ab4_value=av, ab4_charged=a_secs)


def charged_seconds(cell, size, source="descent"):
    return bound_for(cell, size, source).get("charged")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--source", default="best", choices=SOURCES)
    ap.add_argument("--open-only", action="store_true", default=True)
    ap.add_argument("--all-cells", dest="open_only", action="store_false",
                    help="include cells K prove optimal (a bound there cannot win; calibration only)")
    ap.add_argument("--allow-suspended", action="store_true",
                    help="report the TEP bound at a suspended size. For diagnosis only; never for a result")
    a = ap.parse_args()
    from analysis.run_full_grid import all_cells, K_CAP_THEIR_SECONDS, HW_FACTOR_ENVELOPE
    cap = K_CAP_THEIR_SECONDS / HW_FACTOR_ENVELOPE
    kp = os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")
    kt = json.load(io.open(kp, encoding="utf-8")).get("n%d" % a.size) if os.path.exists(kp) else None
    krow = {r["cell"]: r for r in kt["rows"]} if kt else {}
    print("source=%s  size=n%d  budget %.0f our-seconds/cell (K cap %.0f at factor %.1f)"
          % (a.source, a.size, cap, K_CAP_THEIR_SECONDS, HW_FACTOR_ENVELOPE))
    print("%-7s %10s %10s %10s %8s %9s %9s %s"
          % ("cell", "descent", "TEP", "reported", "winner", "charged", "primal", "note"))
    n = wk = tepwin = 0
    for c in all_cells():
        kr = krow.get(c)
        if a.open_only and kr is not None and kr.get("proven"):
            continue
        r = bound_for(c, a.size, a.source, allow_suspended=a.allow_suspended)
        if r["value"] is None and r["descent_value"] is None:
            continue
        n += 1
        tepwin += (r["winner"] == "tep")
        kb = float(kr["k_bound"]) if kr else None
        if kb and r["value"] and r["value"] > kb:
            wk += 1
        print("%-7s %10s %10s %10s %8s %9s %9s %s"
              % (c, ("%.2f" % r["descent_value"]) if r["descent_value"] else "-",
                 ("%.2f" % r["tep_value"]) if r["tep_value"] else "-",
                 ("%.2f" % r["value"]) if r["value"] else "-", r["winner"] or "-",
                 ("%.0f s" % r["charged"]) if r["charged"] else "-",
                 ("%.0f s" % (cap - r["charged"])) if r["charged"] else "-",
                 r["tep_why"] or ""))
    print("\n  %d cells; TEP is the reported instrument on %d; above K's bound on %d" % (n, tepwin, wk))
    print("  RUNTIME: source=best charges BOTH walls on every cell (d245/d246/d250).")


if __name__ == "__main__":
    main()
