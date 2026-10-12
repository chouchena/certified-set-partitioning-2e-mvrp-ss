"""THE NUMBERS REGISTRY. Every number that appears in the manuscript is computed here.

NOTE ON THE FILE NAME. This must NOT be called `numbers.py`: `analysis/` is placed on sys.path,
and a module of that name shadows the standard library's `numbers`, which `decimal`, `fractions`
and `statistics` all import transitively. The first run failed with
"module 'numbers' has no attribute 'Number'" for exactly that reason.

THE RULE: no number is typed into the paper by hand -- not in a table, not in a figure caption,
and NOT EMBEDDED IN A SENTENCE. Prose numbers are the ones that rot silently: a table gets
regenerated, but "R has the widest windows (0.397)" sits in a paragraph for six months while the
artifact behind it is superseded twice.

HOW IT WORKS
  * each number is a NAMED entry computed from banked artifacts by a function here
  * `python analysis/manuscript_numbers.py` recomputes all of them and writes:
        paper/numbers.json   value + provenance + the claim it belongs to
        paper/numbers.tex    \\newcommand{\\numID}{value} for LaTeX
  * the manuscript writes \\num{lb-unproven-winrate}, never "19/20"
  * `--check` recomputes and DIFFS against the stored file, so a stale number fails a command
  * every figure emits a provenance sidecar the same way (see analysis/figstyle.py)

WHY A DIFF AND NOT JUST A REGENERATE. Regenerating silently would hide that a number moved.
The diff is the point: if an artifact changes, the build FAILS and a human decides whether the
manuscript sentence around it still makes sense. A number that moved may invalidate the clause
it sits in, and only a person can judge that.

Each entry carries `claim`, the register id that governs it, so a number in the paper can always
be traced to the claim that licenses it and the falsifier that could retire it.
"""
import os, re, sys, json, glob, math, argparse, collections, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

REG = {}          # id -> dict(fn, unit, desc, claim)


def number(nid, unit="", desc="", claim=""):
    def deco(fn):
        REG[nid] = dict(fn=fn, unit=unit, desc=desc, claim=claim)
        return fn
    return deco


def _fixed(v, nd=3):
    """Render to a FIXED number of decimals, as a string.

    Not cosmetic. `round(0.2600, 3)` is `0.26`, and float repr then drops the trailing zero,
    so a dict whose members are all computed to three decimals reaches the page as
    "C 0.26, R 0.397, RC 0.315" -- three values, two precisions, quoted side by side in one
    sentence. The rounding was already correct; the RENDERING was not, and only the rendering
    is what a reader sees. Caught by analysis/check_number_consistency.py.
    """
    return f"{v:.{nd}f}"


# ----------------------------------------------------------------- shared loaders
def _K():
    return json.load(open(os.path.join(ROOT, "data/karademir2025/k_reference.json")))


def _repro_obj(cell, size):
    """Our reproduction objective for one cell, from the banked run log.

    Reads the VERIFIER's `recomputed_obj`, not the solver's reported objective. The verifier
    shares no imports with the inherited model files and recomputes the cost from the solution
    it is handed; taking the solver's own number here would make the comparison against K a
    check of one solver against another's printout rather than of the solution itself.

    Returns None when no artifact exists, so a missing run shows up as a MISS in the count
    rather than silently shrinking the denominator.
    """
    f = os.path.join(ROOT, f"runs/repro_{cell}_n{size}_tauformula_p0.0.jsonl")
    if not os.path.exists(f):
        return None
    obj = None
    with open(f) as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("phase") == "verify_done":
                obj = rec.get("extra", {}).get("recomputed_obj")
    return obj


def _AB():
    """The arithmetic bound, from the PROVENANCED artifact -- the frozen AB variant.

    REPOINTED 2026-09-16. This read `runs/ab4_grid_results.json`, dated 2026-09-11 and carrying
    no provenance block. The time-window arc pruning was adopted into the bound the NEXT DAY --
    commit b950230, "Adopt TW arc pruning into the arithmetic bound (ab_code_hash 4897cede ->
    4134cf4a)" -- and `runs/ab_grid_provenanced.json` was written at 2026-09-12T18:35 carrying
    the POST-adoption hash `4134cf4a2559c9d8`. The grid was recomputed; the registry was never
    re-pointed at it.

    So every arithmetic-bound number in the paper was the SUPERSEDED, weaker variant, and
    `validation/DECISION_report_the_frozen_variant_only.md` -- registered hours before this was
    found -- requires the frozen one.

    THE PRUNING IS K'S OWN RULE, `integratedJointModel.py:58`: an arc exists only when
    `e_i + s_i + D[i][j] <= l_j`. Restricting our distance relaxations to their admitted set
    needs no new validity argument beyond that line, and minimising over a subset can only RAISE
    the bound. Measured across the grid: higher or equal on all 162 cells, with the gain growing
    by size -- mean +2.5 at n10, +6.0 at n20, +13.0 at n30, +19.6 at n50 and **+65.3 at n100,
    where all 27 cells rise** and where the arithmetic bound carries the portfolio.

    `ab4` and `ab4_full` are identical in this artifact; `ab4` is kept for continuity with the
    field name the superseded file used.
    """
    d = json.load(open(os.path.join(ROOT, "runs/ab_grid_provenanced.json")))
    return {(r["cell"], r["size"]): r.get("ab4") for r in d["records"]}


def _cells(size):
    out = []
    for f in glob.glob(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_*_n{size}.json")):
        b = os.path.basename(f)
        if any(x in b for x in ("noprov", "kcapbug", "tl450", "detl", "_bq")):
            continue
        out.append(b.split("descend_")[1].split(f"_n{size}")[0])
    return sorted(set(out))


def _recs(cell, size):
    """Descent records for one cell, PREFERRING THE BUDGET-EQUALISATION RE-RUN.

    REPOINTED 2026-09-16 on the `ALL TEN DONE` marker. The ten n100 cells that bound at their
    original budget were re-run at `--cell-budget 9000` and wrote `..._bq9000.json`. PREREG_n100
    Amendment 2 makes the terminal value of a **budget-free run** the canonical quantity for the
    cross-size comparison, so that is the artifact the registry must read. A banked run that BOUND
    is not budget-free and is therefore not eligible -- which is the whole reason those ten were
    re-run.

    WHY THIS DID NOT HAPPEN BY ITSELF, recorded because the failure was silent. `_cells` excludes
    "_bq" from ENUMERATION. That exclusion was added in 13652b4 while Amendment 3 was being
    drafted -- a deliberate guard so a half-finished batch could not contaminate the registry
    mid-flight. The guard was right, and it was never lifted when the batch completed: after nine
    hours of compute every n100 number in the manuscript was still its 2026-09-11 banked value and
    nothing failed or warned. The enumeration guard STAYS -- each cell keeps exactly one plain
    file, so cells are still counted once -- and what changes here is only which records a given
    cell resolves to.

    THIS CAN LOWER A BOUND, AND THAT IS CORRECT. RC202's re-run is weaker than its banked run by
    21.33, because the re-run picked up an extra wall-stopped record under machine load. The
    banked value remains a valid lower bound, but it did not come from a budget-free run, so it is
    not the registered quantity. Taking the weaker number is what the pre-registration requires,
    and it runs against us, which is the right direction for it to run.
    """
    base = os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{cell}_n{size}")
    bq = base + "_bq9000.json"
    return json.load(open(bq if os.path.exists(bq) else base + ".json"))


def _frontier(cell, size):
    """(bound, nH, certifies) -- ONE rule at every size, per the decision of 2026-09-16.

    The bound is `lb_estimator.cell_bound`: the strongest REPRODUCIBLE valid lower bound this
    cell has produced. It is no longer the proven record at the smallest k -- that rule discarded
    stronger valid records whenever anything was proven, and switched to a max when nothing was,
    so different sizes were measured by different functions. See
    validation/AUDIT_estimator_specification.md E1 and DECISION_reported_bound_estimator.md.

    `certifies` now means "this cell proves its relaxation somewhere", NOT "the bound came from a
    proven record". Under the old rule those coincided; they no longer do, and the name says which
    one it is. Callers wanting the proved frontier itself call `lb_estimator.frontier`.
    """
    import lb_estimator
    r = _recs(cell, size)
    b = lb_estimator.cell_bound(r, reproducible_only=True)
    rec = lb_estimator.bound_record(r, reproducible_only=True)
    if b is None:
        raise AssertionError(f"{cell}/n{size}: no reproducible record supplies a bound")
    return b, (rec or {}).get("nH"), lb_estimator.certifies(r)


def _fam(c):
    return "RC" if c.startswith("RC") else c[0]


# ----------------------------------------------------------------- the headline bound
def _n20_split():
    K, rows = _K(), []
    per = K["table3"]["per_instance"]["20"]
    for c in sorted(per):
        bk, g = per[c]["joint_bk"], per[c]["joint_gap"]
        klb = bk * (1 - g / 100.0)
        m, _, _ = _frontier(c, 20)
        rows.append((c, g, m, klb, bk))
    return [r for r in rows if r[1] > 0], [r for r in rows if r[1] == 0]


@number("lb-unproven-wins", desc="cells where our bound exceeds K's derived dual bound, of the K-unproven arm at n20", claim="lb-n20-domination")
def _():
    un, _p = _n20_split()
    return f"{sum(1 for r in un if r[2] > r[3])} of {len(un)}"


@number("lb-unproven-mean-ratio", desc="mean ours/K dual bound over the K-unproven n20 arm", claim="lb-n20-domination")
def _():
    un, _p = _n20_split()
    return _fixed(st.mean(r[2] / r[3] for r in un), 3)


@number("budget-sensitivity", desc="share of the terminal bound held at a fraction of each cell's own budget",
        claim="trajectory-analysis-placement")
def _():
    """S-B2, the escalation-budget sensitivity. Answers a row SKELETON Part 7b marked
    "NOT RUN -- BLOCKING for any escalated result", using banked trajectories and no solver.

    WHY IT IS NO LONGER BLOCKING. PREREG_n100 Amendment 4 established that every descent record
    carries `lb_curve`, and that the bound held at any T within the run's length is recoverable
    as the running maximum over points with elapsed <= T. That is not an estimate of what a
    T-second run would have returned -- it is what it would have returned, because every recorded
    value is a valid dual bound (L-step0) and the estimator is a max. Coverage is complete:
    217,214 curve points over 108 cells, zero records without a curve.

    WHAT IT SHOWS. At HALF its budget every size already holds 98.1-99.7% of its terminal bound.
    The calibration is not buying the result; the bound saturates early. That is the sensitivity
    curve the skeleton said an escalated result could not be reported without.

    UNDEFINED IS NOT ZERO. R205/n100's only reproducible record starts at t = 1806 of a 2696 s
    cell, so no reproducible bound exists at 25% or 50%. Scoring it 0.0 dragged the n100 row from
    0.9685/0.9812 to 0.9326/0.9449 -- a fabricated result from a silent default. It is excluded
    and counted.
    """
    import sensitivity_curves as SC
    out = {}
    for size, rows in SC.budget_curve().items():
        for i, f in enumerate(SC.FRACTIONS):
            vals = [r[3][i] for r in rows if r[3][i] is not None]
            out[f"n{size}-at{int(f * 100)}"] = _fixed(st.mean(vals), 4)
        out[f"n{size}-undefined"] = str(sum(1 for r in rows if any(x is None for x in r[3])))
    return out


@number("wls-sensitivity", desc="our arithmetic bound vs K best-known across their four cost scenarios",
        claim="degradation-defence")
def _():
    """S-H, the WLS cost-scenario sensitivity. K devote their section 5.3 and a third of Table 4
    to the water:street cost ratio, and every MILP run we hold fixes 1:10 -- a gap a referee who
    knows their paper will find. The arithmetic-bound sweep (runs/ab_wls_sweep.json, 540
    evaluations) existed with no registry entry and no finding until 2026-09-16.

    THE RESULT IS NOT STABILITY, AND THAT IS BETTER. Our bound's share of K's best-known rises
    0.571 -> 0.592 -> 0.750 -> 0.968 across 1:10, 1:5, 1:1, 10:1. At K's 10:1 scenario the
    arithmetic bound alone is within about 3% of their best-known at every size -- including n50,
    where the 1:10 share is 0.461.

    THE MECHANISM IS ARITHMETIC, NOT A FITTED TREND. Of the bound's components, STREET TRAVEL is
    the only one WLS does not scale: its maximum spread within a cell across all four ratios is
    exactly 0.00, against 277528.68 for water and 15364.80 for fleet. The slack in our bound lives
    in that street-routing term, so as WLS scales everything else the fixed slack becomes a
    vanishing share and the bound approaches tight. Four aggregate points would be a trend; the
    invariance is what carries the claim.

    SCOPE, AND IT MUST TRAVEL WITH THE NUMBER. This is the ARITHMETIC bound only -- the MILP side
    is unrun (~62-65 h). The comparator is min(Joint, LBBD), the registered rule. K publish all
    four ratios only at sizes 10, 20 and 50, so 1:5, 1:1 and 10:1 are scored against size-level
    means; per-cell validation is possible only at 1:10, where 81 comparisons show 0 violations
    and the tightest cell reaches 86.0% of K's per-instance best-known.
    """
    import sensitivity_curves as SC
    wc, sw = SC.wls_curve()
    inv = SC.invariance(sw)
    out = {}
    for wls, d in wc.items():
        tag = wls.replace(":", "to")
        out[f"share-{tag}"] = _fixed(d["share"], 3)
        out[f"street-{tag}"] = _fixed(d["street_share"], 3)
    out["n-per-ratio"] = str(wc["1:10"]["n"])
    out["street-invariance-spread"] = _fixed(inv["travel"], 2)
    out["water-spread"] = _fixed(inv["water"], 2)
    return out


@number("lb-dual-wilcoxon", desc="paired test of our bound against K's derived dual, K-unproven cells at n20 and n30",
        claim="lb-n20-domination")
def _():
    """The dual headline, tested rather than counted.

    WHY THIS EXISTS. Every other leg of this paper carries a paired test -- S3a the sign test,
    exact Wilcoxon and Friedman/Holm; the primal negative an exact Wilcoxon (z = -1.381). The
    dual leg, which is the FAVOURABLE headline, reported only `19 of 20` and a mean ratio.
    Testing our negative and our ablation while quoting our headline as a bare count is backwards,
    and a referee reading the ablation first will see it. Added 2026-09-16.

    THE COMPARATOR IS DERIVED, NOT PUBLISHED, and the paper must say so. K print `joint_bk` and
    `joint_gap`; their dual bound is our reconstruction `bk * (1 - gap/100)`. `joint_gap` is
    printed as an INTEGER, so the reconstruction carries +-0.5pp. `p-robust-range` reports the
    p-value across that interval so a reader can see the rounding cannot manufacture the result.

    THE ARM IS DEFINED BY K'S OWN FAILURE TO PROVE (gap > 0). That is a mechanical, pre-existing
    criterion, not one we chose -- 20 of 27 cells at n20, 26 of 27 at n30 -- but it is a selected
    subset and must be described as one. n10 contributes nothing: K prove every cell there.

    THE TEST IS THE HAND-ROLLED EXACT ONE from s3a_significance, not scipy. This registry has no
    scipy dependency and does not acquire one here; s3a_friedman_holm cross-checks that
    implementation against scipy, which is where that assurance lives.

    WHAT THIS DOES NOT CLAIM. It is a comparison against a fixed published vector, not against a
    re-run of their method. The inference is "our bound exceeds their published dual on these
    instances", never "our method beats theirs under replication". Cells within a family share
    structure, so independence is imperfect -- the same Demsar limitation disclosed for S3a.
    """
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from s3a_significance import wilcoxon_exact, sign_test

    K = _K()
    out = {}
    for size in (20, 30):
        per = K["table3"]["per_instance"][str(size)]
        rows = []
        for c in sorted(per):
            bk, g = per[c]["joint_bk"], per[c]["joint_gap"]
            if g <= 0:
                continue                      # K proved it; there is no gap to compare against
            rows.append((c, g, bk, _frontier(c, size)[0], bk * (1 - g / 100.0)))
        n = len(rows)
        wins = sum(1 for r in rows if r[3] > r[4])
        ratios = [r[3] / r[4] for r in rows]
        _wp, _wm, _z, p, _n, kind = wilcoxon_exact([math.log(x) for x in ratios])
        # Two-sided, matching how S3a reports; wilcoxon_exact returns the one-sided tail.
        p2 = min(1.0, 2 * p)
        ps = []
        for d in (+0.5, -0.5):                # K's gap is an integer: half-ULP either way
            rr = [r[3] / (r[2] * (1 - (r[1] + d) / 100.0)) for r in rows]
            ps.append(min(1.0, 2 * wilcoxon_exact([math.log(x) for x in rr])[3]))
        out[f"n{size}-cells"] = str(n)
        out[f"n{size}-wins"] = f"{wins} of {n}"
        out[f"n{size}-mean-ratio"] = _fixed(st.mean(ratios), 3)
        out[f"n{size}-median-ratio"] = _fixed(st.median(ratios), 3)
        out[f"n{size}-p"] = f"{p2:.1g} ({kind}, n={n})"
        out[f"n{size}-p-robust-range"] = f"{min(ps):.1g}-{max(ps):.1g}"
        if size == 20:
            out["n20-sign-p"] = f"{min(1.0, 2 * sign_test(wins, n)):.1g}"
            lo = min(rows, key=lambda r: r[3] / r[4])
            # THE SINGLE LOSS IS PRINTED, NOT BURIED. It falls on the cell where K's gap is
            # SMALLEST, so their derived dual is strongest exactly where they nearly closed it.
            # That is the right thing to happen and it shows the comparison is not rigged.
            out["n20-worst-cell"] = lo[0]
            out["n20-worst-ratio"] = _fixed(lo[3] / lo[4], 3)
            out["n20-worst-k-gap"] = _fixed(lo[1], 0)
    return out


@number("lb-proven-pct-range", unit="%", desc="our bound as a share of the proven optimum, K-proven n20 cells", claim="full-descent-2pct-residual")
def _():
    _u, pr = _n20_split()
    v = [100 * r[2] / r[4] for r in pr]
    return f"{min(v):.1f}-{max(v):.1f}"


@number("objective-identity-match", desc="K-proven n20 optima we reproduce at their reported precision", claim="objective-identity-v2")
def _():
    """Reproduction of K's proven n20 optima, MEASURED rather than asserted.

    THE DEFECT THIS REPLACES (found 2026-09-15). The previous body was
    `return f"{len(pr)} of {len(pr)}"` -- the count of K-proven n20 cells over itself. It
    printed "7 of 7" unconditionally, consulted no reproduction artifact, and would have gone
    on printing "7 of 7" if every one of our runs had drifted. A number that cannot come out
    any other way is not evidence, and this one was about to be cited in Section 3 as the
    headline that their published values ARE reproducible.

    What is compared: our verifier's recomputed objective, rounded to the ONE decimal K print
    in Table 3, against the value they print. Rounding to their precision is the whole test --
    they publish 685.2 and we obtain 685.185, and claiming a match at three decimals would be
    claiming something we cannot see.
    """
    _u, pr = _n20_split()
    hit = 0
    for cell, _g, _m, _klb, bk in pr:
        ours = _repro_obj(cell, 20)
        if ours is not None and round(ours, 1) == round(bk, 1):
            hit += 1
    return f"{hit} of {len(pr)}"


# ----------------------------------------------------------------- family / mechanism
@number("tw-ratio-by-family-n50", desc="mean time-window width over horizon, by family at n50", claim="tw-width-drives-k-difficulty")
def _():
    from build_instance import build
    g = collections.defaultdict(list)
    for c in _cells(50):
        p = build(c, 50, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
        nd, C = p.nodes, list(p.customers)
        hz = nd[0].latest - nd[0].earliest
        g[_fam(c)].append(st.mean(nd[i].latest - nd[i].earliest for i in C) / hz)
    return {f: _fixed(st.mean(v), 3) for f, v in sorted(g.items())}


@number("s2k-closure", desc="S2k: what our bound is worth to an exact solver on three open cells",
        claim="s2k-exact-closure")
def _():
    """Every number the S2k passage quotes, from validation/s2k_closure.csv.

    WHICH QUANTITY COMES FROM WHICH ARM, because they are not interchangeable and the prereg
    amendment of 2026-09-16 exists to keep them apart:

      * the CONTROL arm's `best_bound` is a MEASUREMENT -- the solver's own dual progress in an
        hour on this machine. That is what `control-bound` reports.
      * the BOUND-INJECTED arm's `best_bound` is NOT. It returns the injected value by
        construction, because the constraint sets the floor and branch-and-bound never lifted
        it. It is deliberately NOT reported here; quoting it would restate our own input as a
        result. What that arm contributes is `injected-gap`.

    `closed` is read from the artifact rather than inferred from the gap: the registered
    acceptance test is the solver's own terminal status, not a threshold we apply afterwards.
    """
    import csv
    rows = list(csv.DictReader(open(os.path.join(ROOT, "validation/s2k_closure.csv"))))
    if not rows:
        raise AssertionError("s2k_closure.csv is empty")
    B = {r["cell"]: r for r in rows if r["arm"] == "B"}
    C = {r["cell"]: r for r in rows if r["arm"] == "C"}
    cells = sorted(B)
    if sorted(C) != cells:
        raise AssertionError(f"arms not paired: B={sorted(B)} C={sorted(C)}")

    closed = sum(1 for r in rows if str(r["closed"]).lower() == "true")
    bg = [float(B[c]["gap_pct"]) for c in cells]
    cg = [float(C[c]["gap_pct"]) for c in cells]
    ratio = [float(B[c]["our_lb"]) / float(C[c]["best_bound"]) for c in cells]
    return {
        "cells": str(len(cells)),
        "arms": str(len(rows)),
        "closed": f"{closed} of {len(rows)}",
        "tl-s": _fixed(float(rows[0]["tl"]), 0),
        "injected-gap-range": f"{min(bg):.1f}-{max(bg):.1f}",
        "control-gap-range": f"{min(cg):.1f}-{max(cg):.1f}",
        "control-bound-range": f"{min(float(C[c]['best_bound']) for c in cells):.1f}-"
                               f"{max(float(C[c]['best_bound']) for c in cells):.1f}",
        "ours-over-control-range": f"{min(ratio):.2f}-{max(ratio):.2f}",
        "nodes-total": f"{sum(int(r['nodes']) for r in rows):,}",
    }


@number("rc208-one-car", desc="the RC208/n20 one-vehicle outlier: value, comparator, mechanism",
        claim="rc208-quarantine-lifted-one-car-basin")
def _():
    """Every number in the RC208 footnote, from the frozen solution and K's published row.

    WHY ONE ENTRY AND NOT SIX. These numbers only mean anything together -- the value, the
    comparator it is measured against, and the fleet arithmetic that accounts for the gap. Split
    across six registry ids they could drift apart, and a footnote whose saving and travel no
    longer reconcile to its objective is worse than no footnote. Computed here in one place, they
    cannot.

    THE COMPARATOR IS min(joint_bk, lbbd_bk), NOT joint_bk. Scoring against joint_bk alone turns
    19.20% into 22.54% on this cell and is a registered defect
    (`primal-comparator-defect-s2close`). See validation/DECISION_rc208_one_car_outlier_disclosure.md.

    THE VALUE IS THE FROZEN SOLUTION, not the ledger. runs/summary.csv carries 682.923 for this
    cell, which has no stored solution and is retired by that decision document's section 6. The
    quoted 693.868 is read from the solution file and re-derived from its own components, so a
    solution that stopped summing correctly would fail here rather than be quoted.
    """
    # READ THE CERTIFIED ARCHIVE, not results/portfolio. The origin file is gitignored
    # (`results/` and `*.sol.json` both), so a number sourced from it has no committed
    # provenance -- the defect recorded in section 8 of the decision document. The archive at
    # validation/certificates/ is tracked, sha256-pinned, and re-verified by
    # analysis/certify_frozen_solution.py, which exits non-zero if these bytes ever move.
    sol = json.load(open(os.path.join(
        ROOT, "validation/certificates/RC208_n20_one_car_solution.json")))
    obj = sol["objVal"]
    parts = sum(sol[k] for k in ("FleetStreet", "FleetWater", "TravelStreet", "TravelWater"))
    if abs(parts - obj) > 1e-6:
        raise AssertionError(f"RC208 components {parts} do not sum to objective {obj}")
    if int(sol["nCars"]) != 1:
        raise AssertionError(f"RC208 frozen solution is not the one-car solution: nCars={sol['nCars']}")
    row = _K()["table3"]["per_instance"]["20"]["RC208"]
    base = min(row["joint_bk"], row["lbbd_bk"])

    # THE TWO-VEHICLE COMPARATOR is what makes the footnote's central sentence checkable: K's
    # published value sits beside our best TWO-car solution, not beside our one-car solution.
    # Taken from the stored solution set rather than typed, and it is a MINIMUM over stored
    # two-car solutions, so it can only move down as more are found -- which would weaken the
    # sentence, not strengthen it. That is the safe direction for a claim of this kind.
    two = _best_stored(cell="RC208", size=20, cars=2)
    if two is None:
        raise AssertionError("no stored two-car RC208/n20 solution; the footnote needs one")

    return {
        "value": _fixed(obj, 3),
        "cars": str(int(sol["nCars"])),
        "vessels": str(int(sol["nVessel"])),
        "comparator": _fixed(base, 1),
        "improvement-pct": _fixed(100.0 * (base - obj) / base, 2),
        "fleet-street": _fixed(sol["FleetStreet"], 2),
        "two-car-value": _fixed(two, 3),
        "published-over-two-car-pct": _fixed(100.0 * (base - two) / base, 2),
        "published-over-one-car-pct": _fixed(100.0 * (base - obj) / obj, 2),  # 2 dp: the other two percentages in this entry are 2 dp (C3)
    }


_N20_SOLUTION_NAME = re.compile(r"^(?:best_)?((?:RC|R|C)\d{3})_n20")


def _stored_n20_solutions():
    """Every stored |C| = 20 solution we hold, as (cell, cars, objective).

    THREE SOURCES, AND THE OMISSION OF A FOURTH IS THE POINT.

      * `published_artifacts/solutions` -- the frozen best-known set, one `best_<cell>_n20.json`
        per cell. This is the authoritative one and it was MISSING: the census read 8 one-car
        cells when we hold 12, because every cell whose one-car solution lives only here
        (R206, R209, R210, RC204) was invisible.
      * `results/portfolio` -- the untracked working set.
      * `validation/certificates` -- the tracked, sha256-pinned copies of the two solutions a
        paper sentence rests on.

    `runs/solutions` is DELIBERATELY NOT SCANNED. It is raw probe output, and it contains
    `fleetdrop_*` files from the probe that solved at TD = 0 while the verifier checked at
    TD = 180. Two of them (C204, C207) carry nCars = 1 on schedules that do not verify.
    Including that directory would have raised this census from 8 to 14 rather than to 12, and
    the two extra cells would have been artefacts of a known-defective run. A directory of
    unverified output is not a source for a number in the paper.

    The filename is parsed by an ANCHORED pattern rather than `split("_n20")[0]`, which returned
    `best_C201` for the frozen set and would have silently turned `fleetdrop_C204` into a cell
    name had the directory list ever grown. A file that does not match is skipped, not guessed.
    """
    out = []
    pats = [os.path.join(ROOT, "published_artifacts/solutions/*.json"),
            os.path.join(ROOT, "results/portfolio/*.json"),
            os.path.join(ROOT, "validation/certificates/*_solution.json")]
    for pat in pats:
        for f in glob.glob(pat):
            b = os.path.basename(f)
            m = _N20_SOLUTION_NAME.match(b)
            if not m:
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            if not isinstance(d, dict) or "nCars" not in d or "objVal" not in d:
                continue
            out.append((m.group(1), int(d["nCars"]), float(d["objVal"])))
    return out


def _best_stored(cell, size, cars):
    vals = [o for c, n, o in _stored_n20_solutions() if c == cell and n == cars]
    return min(vals) if vals else None


@number("one-car-cells-n20", desc="|C|=20 cells for which we hold a one-vehicle solution",
        claim="rc208-quarantine-lifted-one-car-basin")
def _():
    """How many n20 cells we FIND a one-vehicle solution on, and the denominator.

    WORDED AS A FLOOR, DELIBERATELY. This counts cells where a one-car solution happens to sit
    in our stored set. Search effort was not uniform across cells (`ov-median-vs-bestof-gap`:
    the cells we looked at hardest have the best best-of-N), so this is a lower bound on where
    such solutions exist, not a census of the benchmark. Any sentence built on it must say
    "we find them on N of 27", never "they exist on N of 27".
    """
    cells = {c for c, n, _o in _stored_n20_solutions() if n == 1}
    total = len(_cells(20))
    return f"{len(cells)} of {total}"


@number("r205-one-car-optimal", desc="R205/n20: a one-vehicle solution, proven optimal",
        claim="rc208-quarantine-lifted-one-car-basin")
def _():
    """Read from the CERTIFICATE, which derives optimality rather than trusting a status code.

    The certificate sets `proves_optimal` only when Gurobi status 2, a zero MIP gap, and
    bound == incumbent all hold. Sourcing the sentence here means the manuscript cannot claim
    optimality for a solution whose artifact stopped supporting it.
    """
    cert = json.load(open(os.path.join(
        ROOT, "validation/certificates/R205_n20_optimal_certificate.json")))
    if not cert.get("proves_optimal"):
        raise AssertionError("R205 certificate no longer proves optimality")
    if int(cert["nCars"]) != 1:
        raise AssertionError(f"R205 certified solution is not one-car: nCars={cert['nCars']}")
    return {"value": _fixed(cert["objective_recomputed"], 3),
            "cars": str(int(cert["nCars"]))}


@number("transfer-duration-by-family", unit="time units",
        desc="transfer duration U resolved by K's published rule, by instance family",
        claim="objective-identity-v2")
def _():
    """U = ceil(2 x mean customer service duration), evaluated per family.

    WHY THIS IS GENERATED AND NOT TYPED. It is two small integers that sit in one sentence of
    Section 3, which is exactly the shape of number the header of this file warns about: a
    prose constant nobody re-derives. It is also the number the reproducibility disclosure
    turns on, so it must come from the generator rather than from our notes about it.

    U is a property of the instance family, not of the cell -- it depends only on the customer
    service duration, which is 90 across C2xx and 10 across R2xx/RC2xx. We evaluate it on every
    n20 cell anyway and assert the family is constant, because "it depends only on the family"
    is an assumption about their generator, and an assumption we rely on is one we should be
    able to watch fail.
    """
    from build_instance import build
    g = collections.defaultdict(set)
    for c in _cells(20):
        p = build(c, 20, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
        g[_fam(c)].add(int(p._resolved_tau))
    for fam, vals in g.items():
        if len(vals) != 1:
            raise AssertionError(f"U is not constant within family {fam}: {sorted(vals)}")
    return {f: str(next(iter(v))) for f, v in sorted(g.items())}


@number("cross-size-share", desc="our bound as a share of K best-known, n50 vs n100, one construction",
        claim="degradation-defence")
def _():
    """The n50-vs-n100 degradation, computed like-for-like. Fixes AUDIT_estimator_specification E3/E4/E5.

    WHY THIS ENTRY EXISTS. PREREG_n100 Amendment 1 banked a table (0.578, 0.367, 0.247, 0.322) as
    prose, with no generating code anywhere -- `grep -rln "0\\.578" --include=*.py` returned
    nothing -- and Amendment 2's registered PRIMARY OUTCOME cites "n50's 0.578". A registered
    outcome depending on an unregenerable number is the breach of rule 1 that this entry closes.

    THE DENOMINATORS DO NOT MATCH AS PUBLISHED, and that is K's doing, not an error of ours.
    `sizes_tested` in the canonical reference records table4 = [10, 20, 50] and table6 = [100]:

      * n50  -- table4 carries a SIZE-LEVEL `bk`, one scalar aggregated over the 27 instances.
      * n100 -- table6 carries FAMILY-LEVEL `zIP` for C, R, RC, with no size-level row.

    So a like-for-like comparison needs one of them reconstructed. We pool table6's families by
    their instance counts (8, 11, 8), which reproduces the same construction table4 already uses
    -- a mean over the same 27 instances -- rather than comparing a size-level ratio on one side
    against a family-normalised one on the other.

    Checked before adopting: the pooled n100 denominator gives 0.319 against the 0.322 the
    family-level route gives, so the granularity mismatch was worth 0.003. Amendment 1's headline
    was right, but by luck rather than by construction, and it is now right by construction.

    THE COMPARATOR IS min(joint, lbbd). Registered as `primal-comparator-defect-s2close` and
    applied in `rc208-one-car`, but NOT in the by-family share entries, which divide by `joint`
    alone. K's LBBD zIP is below their joint zIP at both sizes, so `joint` UNDER-states our share,
    and unevenly: the correction is +2.4% relative at n50 and +10.7% at n100. Using `joint` makes
    the degradation look worse than it is. Both are returned here so the difference is visible.

    THE ESTIMATOR IS `lb_estimator.cell_bound`, per Amendment 6 -- the best REPRODUCIBLE valid
    bound. `_frontier` (the proved frontier) is a different quantity and differs on 9 cells across
    the grid, worst +5.86% at R206/n50; in aggregate the two agree to 0.002, so the choice moves
    per-cell tables and not this headline.
    """
    import lb_estimator
    K = _K()

    def t4(size, method):
        r = [x for x in K["table4"] if x["size"] == size and x["wls"] == "1:10"
             and x["method"] == method]
        if not r:
            raise AssertionError(f"table4 has no size={size} row; do not substitute another table")
        return r[0]["bk"]

    def t6_pooled(which):
        fams = K["table6"]
        return (sum(v[which]["zIP"] * v["n"] for v in fams.values())
                / sum(v["n"] for v in fams.values()))

    den = {
        (50, "joint"): t4(50, "Joint"),
        (50, "min"): min(t4(50, "Joint"), t4(50, "LBBD")),
        (100, "joint"): t6_pooled("joint"),
        (100, "min"): min(t6_pooled("joint"), t6_pooled("lbbd")),
    }

    def share(size, comp):
        vals = []
        for c in _cells(size):
            recs = json.load(open(os.path.join(
                ROOT, f"crossfeed/easy_reduction_descend_{c}_n{size}.json")))
            b = lb_estimator.cell_bound(recs, reproducible_only=True)
            if b is None:
                raise AssertionError(f"{c}/n{size}: no reproducible record")
            vals.append(b / den[(size, comp)])
        return st.mean(vals)

    out = {}
    for comp in ("joint", "min"):
        s50, s100 = share(50, comp), share(100, comp)
        out[f"n50-{comp}"] = _fixed(s50, 3)
        out[f"n100-{comp}"] = _fixed(s100, 3)
        out[f"drop-{comp}"] = _fixed((1 - s100 / s50) * 100, 1)
    out["n50-denominator"] = _fixed(den[(50, "min")], 1)
    out["n100-denominator"] = _fixed(den[(100, "min")], 1)
    return out


@number("milp-over-kbk-by-family-n100", desc="restriction bound as a share of K best-known, by family at n100", claim="degradation-defence")
def _():
    K = _K()
    g = collections.defaultdict(list)
    for c in _cells(100):
        bk = K["table6"][_fam(c)]["joint"]["zIP"]
        g[_fam(c)].append(_frontier(c, 100)[0] / bk)
    return {f: _fixed(st.mean(v), 3) for f, v in sorted(g.items())}


@number("protocol", desc="protocol constants read from the artifacts, not typed",
        claim="replicability-needs-det-ticks")
def _():
    """Section 6's protocol subsection. READ FROM THE RECORDS, never typed, because a protocol
    constant stated in prose and not regenerated is exactly the kind of number that drifts away
    from what was actually run.

    The thread count is asserted UNIQUE across every descent record. If a future batch runs at a
    different width this raises rather than silently reporting one of two values -- which is what
    runs/RUN_MANIFEST.json already shows happening across kinds (cores 4 on lb rows, 8 on ub).
    """
    seen = set()
    for f in glob.glob(os.path.join(ROOT, "crossfeed/easy_reduction_descend_*_n*.json")):
        for r in json.load(open(f)):
            if isinstance(r, dict) and r.get("threads"):
                seen.add(int(r["threads"]))
    if len(seen) != 1:
        raise AssertionError(f"bounding runs span several thread counts {sorted(seen)}; "
                             f"Section 6 states one")
    return {"bound-threads": str(seen.pop())}


@number("ab-tightens-k-gaps", desc="cells where the arithmetic bound exceeds K's published dual bound, and the gap reduction that follows",
        claim="ab-tightens-k-published-gaps")
def _():
    """SKELETON Part 7.3b. Everything here is recomputed from primary data -- K's published
    per-instance table and the frozen AB artifact -- never transcribed from the finding document.

    WHY THAT MATTERS HERE SPECIFICALLY. paper/FINDING_ab_tightens_K_gaps.md carries BOTH 24/54
    (its measurement table, current) and 23/54 (its "stated correctly" box, the PRE-PRUNING
    figure). The stale number survived in the same file that warns about stale numbers. Computing
    from source is what stops the manuscript inheriting it.

    K's dual bound is recovered as bk * (1 - gap/100), which is `k-lb-derivation`, STANDING.
    A cell counts as improved when AB strictly exceeds that bound; the tightened gap is then
    taken against max(K's bound, AB), which is what a reader would do with both numbers in hand.

    CELLS K PROVE OPTIMAL ARE EXCLUDED FROM THE COUNTS AND THE AVERAGES (2026-09-17). Where their
    gap is 0 their dual bound IS the optimum, so "AB strictly exceeds it" requires the bound to
    exceed the optimum and is impossible for a valid lower bound. Those cells could never be
    counted as improvements yet sat in the denominator: 8 of 54 -- seven at |C| = 20 and one at
    30 -- so the entry reported `24 of 54` for a rate that is really `24 of 46`. They also
    contributed structural ZEROS to the average gaps, since g = 0 and the tightened gap is also
    0, which diluted the reduction.

    The filter is `analysis.k_comparison.proven_cells`, the same mechanical `gap > 0` criterion
    `lb-dual-wilcoxon`, `gap-closed-by-family` and `lb-time-to-exceed-k` already apply. It is
    pre-existing, not chosen here because it happens to help -- and it DOES help, on all three
    figures. That is stated rather than offset.

    THE SPREAD KEYS BELOW ARE DELIBERATELY NOT FILTERED, and the reason is not that proven bounds
    are somehow more admissible there. A RANGE IS NOT INVARIANT TO SAMPLE SIZE: remove points and
    it can only shrink. `k-narrowest-family-spread` is a MINIMUM over families and its minimum is
    n20-C, which loses FOUR of its EIGHT cells to this filter. Applying the filter there moves it
    404 -> 235 and `spread-factor` 4.7 -> 2.7, and the check that this is arithmetic rather than
    substance is that every family losing cells shrank while the two losing none (n30-R, n30-RC)
    did not move at all. Filtering a range would trade a population problem for an n problem.

    Those keys carry a SEPARATE, UNFIXED confound: they compare ranges across families of unequal
    size (8, 11, 8). The repair is to report n per family or to use an n-robust dispersion
    measure, and it is not attempted here.
    """
    from analysis.k_comparison import proven_cells      # local: k_comparison reads this module
    Kp, AB = _K()["table3"]["per_instance"], _AB()
    moved, per = [], {}
    for size in (20, 30):
        prov = proven_cells(size)
        rows = []
        for c, d in Kp[str(size)].items():
            if c in prov:
                continue          # their bound IS the optimum; no improvement is available

            ab = AB.get((c, size))
            if ab is None:
                continue
            bk, g = d["joint_bk"], d["joint_gap"]
            klb = bk * (1 - g / 100.0)
            newg = min(g, 100.0 * (bk - ab) / bk)
            rows.append((c, g, newg, ab > klb))
        per[size] = rows
        moved += [(c, size, g, ng, g - ng) for c, g, ng, hit in rows if hit]
    tot = sum(len(v) for v in per.values())
    big = max(moved, key=lambda x: x[4])
    out = {
        "cells": f"{len(moved)} of {tot}",
        "loses": f"{tot - len(moved)} of {tot}",
        "n20-cells": str(sum(1 for m in moved if m[1] == 20)),
        "n30-cells": str(sum(1 for m in moved if m[1] == 30)),
        "mean-reduction-pp": _fixed(st.mean(m[4] for m in moved), 1),
        "threshold-pct": str(int(min(m[2] for m in moved))),
        "largest-cell": big[0],
        "largest-size": str(big[1]),
        "largest-from-pct": _fixed(big[2], 0),
        "largest-to-pct": _fixed(big[3], 1),
        "largest-pp": _fixed(big[4], 1),
    }
    # WHY THE OTHER CELLS DO NOT MOVE. The contrast is deliberately taken at its WEAKEST: our
    # WIDEST within-family spread against their NARROWEST. Any other pairing flatters us more.
    # A RANGE GROWS WITH SAMPLE SIZE, and these families are NOT the same size -- 8, 11 and 8 at
    # each of two sizes. `ab-widest` is a MAXIMUM over groups and `k-narrowest` a MINIMUM, so the
    # two figures can come from groups with different n, and a range from 11 points is expected to
    # exceed a range from 8 for that reason alone. The cell COUNT behind each is therefore emitted
    # beside it, so the sentence that quotes them can state it rather than imply a like-for-like
    # comparison. The values themselves are unchanged.
    ab_ranges, k_ranges, ab_sds, k_sds = [], [], [], []
    for size in (20, 30):
        for f in ("C", "R", "RC"):
            cs = [c for c in Kp[str(size)] if _fam(c) == f and (c, size) in AB]
            if len(cs) < 2:
                continue
            a = [AB[(c, size)] for c in cs]
            kb = [Kp[str(size)][c]["joint_bk"] * (1 - Kp[str(size)][c]["joint_gap"] / 100.0)
                  for c in cs]
            ab_ranges.append((max(a) - min(a), len(cs), size, f))
            k_ranges.append((max(kb) - min(kb), len(cs), size, f))
            ab_sds.append((st.stdev(a), len(cs), size, f))
            k_sds.append((st.stdev(kb), len(cs), size, f))
    ab_w = max(ab_ranges)
    k_n = min(k_ranges)
    ab_ws = max(ab_sds)
    k_ns = min(k_sds)
    out["ab-widest-family-spread"] = _fixed(ab_w[0], 0)
    out["ab-widest-family-n"] = str(ab_w[1])
    out["ab-widest-family"] = f"{ab_w[3]} at |C|={ab_w[2]}"
    out["k-narrowest-family-spread"] = _fixed(k_n[0], 0)
    out["k-narrowest-family-n"] = str(k_n[1])
    out["k-narrowest-family"] = f"{k_n[3]} at |C|={k_n[2]}"
    out["spread-factor"] = _fixed(k_n[0] / ab_w[0], 1)
    # THE N-ROBUST COMPANION, added 2026-09-17. A range grows with n and these families are of
    # unequal size, so the range pairing above is confounded. The STANDARD DEVIATION is not: it
    # uses every instance and carries the n-1 correction. Reported ALONGSIDE the range rather than
    # instead of it -- the range stays the headline because it is the CONSERVATIVE figure (4.7x
    # against SD's 5.8x), and dropping it after seeing that SD is larger would be choosing the
    # statistic by its answer.
    #
    # The SD pairing happens to be MATCHED on n -- both groups have 11 instances -- so it answers
    # the unequal-n objection by construction instead of by argument. That is a property of the
    # data, not of the choice, and it is why the disclosure is worth making rather than hiding.
    out["ab-widest-family-sd"] = _fixed(ab_ws[0], 1)
    out["ab-widest-family-sd-n"] = str(ab_ws[1])
    out["k-narrowest-family-sd"] = _fixed(k_ns[0], 1)
    out["k-narrowest-family-sd-n"] = str(k_ns[1])
    out["spread-factor-sd"] = _fixed(k_ns[0] / ab_ws[0], 1)
    for size in (20, 30):
        rows = per[size]
        o = st.mean(r[1] for r in rows)
        n = st.mean(r[2] for r in rows)
        out[f"avg-n{size}-from-pct"] = _fixed(o, 1)
        out[f"avg-n{size}-to-pct"] = _fixed(n, 1)
        out[f"avg-n{size}-pp"] = _fixed(o - n, 1)
    return out


@number("ab-over-kbk-by-family-n50", desc="arithmetic bound as a share of K best-known, by family at n50", claim="n50-headline-under-registered-estimator")
def _():
    K, AB = _K(), _AB()
    bk = [r for r in K["table4"] if r["size"] == 50 and r["wls"] == "1:10" and r["method"] == "Joint"][0]["bk"]
    g = collections.defaultdict(list)
    for c in _cells(50):
        g[_fam(c)].append((AB[(c, 50)] or 0) / bk)
    return {f: _fixed(st.mean(v), 3) for f, v in sorted(g.items())}


# ----------------------------------------------------------------- n50 and crossover
@number("n50-ratio-vs-k", desc="portfolio bound over K's derived dual bound at n50", claim="n50-headline-under-registered-estimator")
def _():
    K, AB = _K(), _AB()
    j = [r for r in K["table4"] if r["size"] == 50 and r["wls"] == "1:10" and r["method"] == "Joint"][0]
    klb = j["bk"] * (1 - j["gap_imp"] / 100.0)
    cs = _cells(50)
    return _fixed(st.mean(max(_frontier(c, 50)[0], AB[(c, 50)] or 0) for c in cs) / klb, 3)


@number("gap-closed-by-family", desc="share of K's closable gap that our portfolio bound closes, and the nominal gain, by family and size",
        claim="gap-reporting-framing")
def _():
    """BOTH MEASURES, ALWAYS, AND PER FAMILY -- which is what `gap-reporting-framing` requires:
    "reported as BOTH closed% and nominal gain, always, because each covers the other's failure
    mode. Lead with aggregate closed% per family."

    WHY BOTH. closed% divides by (their incumbent - their dual), which vanishes where their gap
    is small: the claim records R201/n30 as a -12.5 NOMINAL miss that reads as -59.8% closed. The
    nominal gain has the opposite failure -- it is scale-bound and flatters big-objective cells.
    Neither alone is safe.

    AGGREGATE, NOT MEAN-OF-RATIOS. The share is sum(ours - theirs) over sum(BK - theirs) within a
    family, never the mean of per-cell ratios, for the vanishing-denominator reason above.

    GRANULARITY IS K'S, NOT OURS, and it differs by size: per-instance at |C| = 20 and 30, POOLED
    over 27 at |C| = 50 (they report that size by cost ratio, not by family), per-family at
    |C| = 100. The n50 row is therefore marked and must not be read as a family value.

    THE ARM AT n20/n30 IS K'S OWN FAILURE TO PROVE (gap > 0), a mechanical pre-existing criterion.
    Family counts therefore differ between sizes -- C contributes 4 cells at n20 and 7 at n30 --
    because they prove fewer as size grows. The counts are returned so no row is read as a
    constant denominator.

    ESTIMATOR: the portfolio max(restriction, arithmetic), which `n100-complete-rollup` fixes as
    the reported bound. NOTE this differs from the figures: paper/figures/CAPTIONS.md quotes
    R at n100 as +4.2%, computed before the 2026-09-16 registry repoint to the budget-free
    artifacts. R205 and R206 are both n100 R cells and both moved, so F2 and its caption are
    STALE until regenerated.
    """
    Kp, AB = _K(), _AB()
    out = {}

    def row(tag, ours, kd, bk, n):
        out[tag + "-closed-pct"] = _fixed(100.0 * (ours - kd) / (bk - kd), 1)
        out[tag + "-gain"] = _fixed(ours - kd, 1)
        out[tag + "-closable"] = _fixed(bk - kd, 1)
        out[tag + "-cells"] = str(n)

    for size in (20, 30):
        pi = Kp["table3"]["per_instance"][str(size)]
        for f in ("C", "R", "RC"):
            cs = [c for c in _cells(size) if c in pi and pi[c]["joint_gap"] > 0 and _fam(c) == f]
            if not cs:
                continue
            o = sum(max(_frontier(c, size)[0], AB.get((c, size)) or 0) for c in cs)
            kd = sum(pi[c]["joint_bk"] * (1 - pi[c]["joint_gap"] / 100.0) for c in cs)
            row(f"n{size}-{f}", o, kd, sum(pi[c]["joint_bk"] for c in cs), len(cs))

    j = [r for r in Kp["table4"] if r["size"] == 50 and r["wls"] == "1:10"
         and r["method"] == "Joint"][0]
    cs = _cells(50)
    row("n50-pooled", st.mean(max(_frontier(c, 50)[0], AB.get((c, 50)) or 0) for c in cs),
        j["bk"] * (1 - j["gap_imp"] / 100.0), j["bk"], len(cs))

    t6 = Kp["table6"]
    for f in sorted(t6):
        d = t6[f]
        cs = [c for c in _cells(100) if _fam(c) == f]
        row(f"n100-{f}", st.mean(max(_frontier(c, 100)[0], AB.get((c, 100)) or 0) for c in cs),
            d["joint"]["zIP"] * (1 - d["gap_joint"] / 100.0), d["joint"]["zIP"], d["n"])
    return out


@number("lb-time-to-exceed-k", desc="wall seconds until our bound first exceeds K's derived dual bound, K-unproven cells",
        claim="lb-n20-domination")
def _():
    """L1 -- the runtime result RT_RAW_METRICS_CATALOGUE ranks first in the project and says to
    lead with. It had NO generating code: the figures lived as the literal 1.84 in three prose
    documents and in neither the registry nor RT_LEG_DESCRIPTIVES.json. Registered 2026-09-16.

    THIS IS TIME-TO-BEAT AND NOTHING ELSE. Three runtime quantities are distinct and are
    routinely conflated:
        L1  time until OUR bound exceeds THEIR published bound   -- this entry, 1.84 s / 3.31 s
        M2  time until our own best                              -- 302.8 s / 711.9 s (mean)
        M1  our TOTAL run time                                   -- 1102.1 s / 1256.1 s (median)
    Quoting 1.84 s as a run time would be wrong by nearly three orders of magnitude.

    HOW IT IS MEASURED. `lb_curve` in each descent record is a list of (wall seconds,
    block_relax) pairs; the times are seconds -- the last point matches the record's own `wall`
    to a tenth -- and the values are the FULL bound with the water term already in, matching
    `block_relax` to two decimals. The statistic is the earliest crossing over all records of the
    cell. K's bound is their published `bk * (1 - gap/100)`, the derivation `k-lb-derivation`.

    CENSORING IS STRUCTURAL, NOT STATISTICAL, which is why the MEDIAN is reported and the mean is
    not. One cell per size never crosses -- R209 at n20 (ratio 0.996) and R201 at n30 -- and they
    never will, rather than having run out of clock. The mean is 21 s at n20 and 88 s at n30,
    dragged by single cells at 186 s and 1495 s, so it describes the tail and not the typical
    case.

    THE ASYMMETRY MUST TRAVEL WITH THIS NUMBER. We hold our own trajectory and none of theirs, so
    we can say how quickly we pass their published value and never when they first reached it.
    RT_RAW_METRICS_CATALOGUE: "Disclose the asymmetry rather than let the reader assume symmetry."

    THE CONDITIONS ARE PART OF THE NUMBER, and this entry did not say so until 2026-09-17. A wall
    clock depends on the thread count and on what else was running. Verified rather than assumed:
    ALL 382 descent records carrying an `lb_curve` were produced at `threads=4`, and the reprov
    drivers hold for single tenancy before each cell (`lb_n20_reprov.py:152`,
    `lb_repair_n30.py:197`). So the figures below are 4-thread, single-tenant numbers.

    THIS CONSTRAINS HOW THE GRID MAY BE COMPLETED. Extending this entry to |C| = 50 or 100
    requires the same 4 threads AND the same single tenancy, or the new times are not
    commensurable with these and the row cannot be added. A DETERMINISTIC budget does NOT lift
    that: det ticks make the BOUND reproducible under co-tenancy, they do nothing for the CLOCK,
    which is what this number is. Any co-tenant run is usable for its bound and must never be
    mined for a time.
    """
    Kp = _K()["table3"]["per_instance"]
    out = {}
    for size in (20, 30):
        pi, ts, never = Kp[str(size)], [], []
        for c in _cells(size):
            if c not in pi or pi[c]["joint_gap"] <= 0:
                continue
            klb = pi[c]["joint_bk"] * (1 - pi[c]["joint_gap"] / 100.0)
            first = None
            for r in _recs(c, size):
                for t, v in (r.get("lb_curve") or []):
                    if v > klb:
                        first = t if first is None else min(first, t)
                        break
            (ts if first is not None else never).append(first if first is not None else c)
        out[f"n{size}-median-s"] = _fixed(st.median(ts), 2)
        out[f"n{size}-cells"] = f"{len(ts)} of {len(ts) + len(never)}"
        out[f"n{size}-never"] = ", ".join(never) if never else "none"
        out[f"n{size}-max-s"] = _fixed(max(ts), 0)
    return out


@number("lb-over-kdual-n100", desc="our portfolio bound over K's derived dual bound, by family at n100",
        claim="degradation-defence")
def _():
    """THE LB-vs-LB COMPARISON AT |C| = 100, which the registry did not previously carry.

    WHY IT WAS MISSING AND WHY THAT MATTERED. Every other n100 entry compares our bound to K's
    INCUMBENT (`milp-over-kbk-by-family-n100`, `cross-size-share`), which is a different quantity
    and reads far weaker -- 0.24 to 0.48 of their solution -- because a lower bound is not
    supposed to reach an incumbent. The bound-to-bound comparison is the one the paper's claim is
    about, it is derivable from published values at this size, and at the size that carries the
    paper it was simply absent.

    THE COMPARATOR IS THE JOINT DUAL, AND IT IS THE ONLY ONE AVAILABLE. K publish `gap_joint` per
    family in Table 6 but NO LBBD gap -- at any size. Their LBBD dual bound is unpublished
    throughout, which is precisely why `beats-both-k-bounds-v3` pairs their published Joint bound
    with our own REPRODUCED LBBD rather than a second published one.

    GRANULARITY. Family level only: Table 6 aggregates, so no per-instance statement is possible
    here and none is made. `gap_joint` is printed to one decimal, so the derived bound carries
    about +-0.05 pp -- an order tighter than Table 3's integer gaps.

    THE JENSEN CAVEAT, and its direction. `bk * (1 - gap/100)` applied to family MEANS is not the
    mean of the per-instance duals unless cov(bk, gap) = 0. Measured where K publish per-instance
    data, `jensen-favours-our-n50-claim` gives cov -1.4 at n20 and +12.8 at n30; a POSITIVE
    covariance makes the derived bound OVERSTATE their true mean dual, which understates our
    ratio. It cannot be measured at n100 because no per-instance data is published there, so this
    is stated as an unquantified caveat whose measured instances both lean our way or are
    negligible.

    PROXIMITY MATCHES: Table 6 is at 0.1 (`text_facts.proximity`) and so is our entire n100 leg.
    """
    K, AB = _K(), _AB()
    t6 = K["table6"]
    out = {}
    for f in sorted(t6):
        d = t6[f]
        klb = d["joint"]["zIP"] * (1 - d["gap_joint"] / 100.0)
        cs = [c for c in _cells(100) if _fam(c) == f]
        ours = st.mean(max(_frontier(c, 100)[0], AB.get((c, 100)) or 0) for c in cs)
        out[f] = _fixed(ours / klb, 3)
        out[f + "-kdual"] = _fixed(klb, 1)
    return out


@number("ab-crossovers-by-size", desc="cells where the arithmetic bound exceeds the restriction bound", claim="n50-headline-under-registered-estimator")
def _():
    AB = _AB()
    return {f"n{s}": f"{sum(1 for c in _cells(s) if (AB.get((c, s)) or 0) > _frontier(c, s)[0])} of {len(_cells(s))}"
            for s in (10, 20, 30, 50, 100)}


# ----------------------------------------------------------------- descent cost structure
@number("descent-cost-multiplier", unit="x", desc="median wall-time multiplier per step down in k, n20", claim="trajectory-analysis-placement")
def _():
    rs = []
    for c in _cells(20):
        r = sorted(json.load(open(os.path.join(
            ROOT, f"crossfeed/easy_reduction_descend_{c}_n20.json"))), key=lambda x: -x["k"])
        for a, b in zip(r, r[1:]):
            if a["wall"] > 0.05 and b["wall"] > 0.05:
                rs.append(b["wall"] / a["wall"])
    return round(st.median(rs), 2)


@number("budget-below-frontier", unit="%", desc="median share of a cell's budget spent on solves that never certify, n20", claim="trajectory-analysis-placement")
def _():
    sh = []
    for c in _cells(20):
        r = json.load(open(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_{c}_n20.json")))
        pr = [x for x in r if x["proven"]]
        if not pr:
            continue
        kf = min(x["k"] for x in pr)
        tot = sum(x["wall"] for x in r)
        if tot:
            sh.append(sum(x["wall"] for x in r if x["k"] < kf) / tot)
    return round(100 * st.median(sh), 1)


# ----------------------------------------------------------------- fleet certificate
@number("fleet-certificate-coverage", desc="cells where one vehicle is proved impossible, by size", claim="fleet-certificate-scales-and-dominates-ab")
def _():
    out = {}
    for s, f in ((20, "runs/fleet_subset_infeasibility.json"), (30, "runs/fleet_check_n30.json"),
                 (50, "runs/fleet_check_n50.json"), (100, "runs/fleet_check_n100_prox01.json")):
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        rows = json.load(open(p))
        rows = rows if isinstance(rows, list) else rows.get("rows", [])
        out[f"n{s}"] = f"{sum(1 for r in rows if r.get('infeasible_k1') or r.get('proved'))} of {len(rows)}"
    return out


# ----------------------------------------------------------------- S3a selection ablation
# These run the ABLATION SCRIPTS THEMSELVES rather than re-deriving the statistics here. A
# second implementation of an exact Wilcoxon inside the registry is a second thing to get
# wrong, and a divergence between the paper's number and the verdict script's number is the
# exact defect this registry exists to prevent.
def _s3a(mod, *a):
    import io as _io, contextlib as _c
    m = __import__(mod)
    with _c.redirect_stdout(_io.StringIO()):
        return m.main(*a)


@number("s3a-easiness-winrate", desc="informative cells where the easiness ordering gives the stronger frontier bound, per arm", claim="s3a-ablation-complete-three-arm")
def _():
    return {a: f"{_s3a('s3a_significance', a, 20)['wins']} of "
               f"{_s3a('s3a_significance', a, 20)['n']}" for a in ("random", "reverse")}


@number("s3a-wilcoxon-p", desc="exact one-sided Wilcoxon signed-rank p on log frontier ratios, easiness vs arm", claim="s3a-ablation-complete-three-arm")
def _():
    out = {}
    for a in ("random", "reverse"):
        r = _s3a("s3a_significance", a, 20)
        out[a] = f"{r['wilcoxon']['p']:.2g} ({r['wilcoxon']['method']}, n_eff={r['wilcoxon']['n_eff']})"
    return out


@number("s3a-mean-frontier-ratio", desc="mean arm/easiness frontier bound ratio over informative cells", claim="s3a-ablation-complete-three-arm")
def _():
    return {a: _fixed(_s3a("s3a_significance", a, 20)["mean_ratio"], 3)
            for a in ("random", "reverse")}


@number("s3a-friedman-p", desc="Iman-Davenport F p-value, three arms over informative cells", claim="s3a-ablation-complete-three-arm")
def _():
    r = _s3a("s3a_friedman_holm", 20)
    return f"{r['p_F']:.2g} (F({r['df1']},{r['df2']}) = {r['F']:.2f}, N = {r['N']})"


@number("s3a-holm-adjusted-p", desc="Holm step-down adjusted p against the easiness control", claim="s3a-ablation-complete-three-arm")
def _():
    r = _s3a("s3a_friedman_holm", 20)
    return {h["arm"]: f"{h['p_holm']:.2g}" for h in r["holm"]}


@number("s3a-average-rank", desc="mean Friedman rank of each arm (1 = strongest bound)", claim="s3a-ablation-complete-three-arm")
def _():
    return {k: _fixed(v, 3) for k, v in _s3a("s3a_friedman_holm", 20)["avg_rank"].items()}


@number("s3a-informative-cells", desc="cells entering the ablation after the pre-registered k=0 exclusion", claim="s3a-ablation-complete-three-arm")
def _():
    return _s3a("s3a_friedman_holm", 20)["N"]


# ----------------------------------------------------------------- driver
def compute():
    out = {}
    for nid, meta in sorted(REG.items()):
        try:
            v = meta["fn"]()
        except Exception as e:
            v = f"ERROR: {type(e).__name__}: {e}"
        out[nid] = dict(value=v, unit=meta["unit"], desc=meta["desc"], claim=meta["claim"])
    return out


def to_tex(nums):
    r"""LaTeX macros, addressed by their REGISTRY ID.

    Emitted through \csname rather than \newcommand, and that is not a style choice:
    a LaTeX control sequence may contain letters ONLY, so ids carrying digits or hyphens
    -- `ab-crossovers-by-size` / `n10` / `s3a-wilcoxon-p`, i.e. most of ours -- cannot be
    \newcommand names at all. Stripping them to `\numabcrossoversbysizen10` produced a
    file that does not compile, and worse, would have silently collided any two ids that
    differ only in punctuation.

    So the manuscript writes \num{ab-crossovers-by-size.n50}: the id EXACTLY as the
    registry records it, dict-valued entries addressed with a dot. An id that does not
    exist raises a LaTeX error naming it, because a number that silently vanishes from a
    sentence is the failure this whole mechanism exists to prevent.
    """
    # A RAW string. This block is LaTeX; writing it through an ordinary Python literal
    # means doubling every backslash, and the first attempt duly turned "\num" into a
    # newline followed by "um" -- in the one file whose whole job is to be exact.
    lines = r'''% GENERATED by analysis/manuscript_numbers.py -- DO NOT EDIT.
% Every manuscript number is defined here and cited as \num{id}, where `id` is the
% registry id verbatim; dict-valued entries are addressed as \num{id.key}.
% A missing id is a LaTeX ERROR, not a silent blank.

\makeatletter
\providecommand{\num}[1]{%
  \@ifundefined{snum@#1}%
    {\PackageError{numbers}{No registered number '#1'. Run analysis/manuscript_numbers.py}{}}%
    {\@nameuse{snum@#1}}}
\makeatother
'''.split(chr(10))

    def define(key, val):
        lines.append(r"\expandafter\def\csname snum@%s\endcsname{%s}" % (key, val))

    for nid, d in sorted(nums.items()):
        v = d["value"]
        if isinstance(v, dict):
            for k, kv in v.items():
                define(f"{nid}.{k}", kv)
        else:
            define(nid, v)
    return "\n".join(lines) + "\n"


def main(check):
    nums = compute()
    jp = os.path.join(ROOT, "paper", "numbers.json")
    errs = [k for k, v in nums.items() if isinstance(v["value"], str) and v["value"].startswith("ERROR")]

    if check:
        if not os.path.exists(jp):
            print("no paper/numbers.json -- run without --check first"); return 1
        old = json.load(open(jp))
        old = {k: v for k, v in old.items() if not k.startswith("_") and k != "sources"}   # stamped() adds provenance keys that are not numbers (false REMOVED, 2026-09-26)
        moved = [k for k in nums if k in old and old[k]["value"] != nums[k]["value"]]
        new = [k for k in nums if k not in old]
        gone = [k for k in old if k not in nums]
        for k in moved:
            print(f"  MOVED   {k}: {old[k]['value']}  ->  {nums[k]['value']}")
        for k in new:
            print(f"  NEW     {k}: {nums[k]['value']}")
        for k in gone:
            print(f"  REMOVED {k}")
        bad = moved or new or gone or errs
        print(f"\n  {len(nums)} numbers; {len(moved)} moved, {len(new)} new, "
              f"{len(gone)} removed, {len(errs)} errors")
        if moved:
            print("  A MOVED number may invalidate the sentence around it. A human decides,")
            print("  then re-runs without --check to accept.")
        return 1 if bad else 0

    json.dump(stamped(nums, __file__), open(jp, "w"), indent=1, sort_keys=True, default=str)
    open(os.path.join(ROOT, "paper", "numbers.tex"), "w").write(to_tex(nums))
    for nid, d in sorted(nums.items()):
        print(f"  {nid:34s} {str(d['value'])[:58]}")
    print(f"\n  wrote paper/numbers.json and paper/numbers.tex ({len(nums)} numbers, {len(errs)} errors)")
    for e in errs:
        print(f"    ERROR {e}: {nums[e]['value']}")
    return 1 if errs else 0


@number("m6-matched-budget",
        desc="M6: our bound against K's LBBD reproduced at a budget matched to K's own per-cell incumbent time",
        claim="beats-both-k-bounds-v3")
def _():
    """THE PRE-REGISTERED OUTCOME OF M6. Prereg: PREREG_M6_matched_budget_reproduction.md,
    write-up: RESULT_M6_matched_budget.md, scorer: analysis/m6_score.py.

    WHY THIS ENTRY EXISTS SEPARATELY FROM THE SCORER. The scorer decides the prereg's branches and
    prints the table; this exposes the handful of values a SENTENCE may cite, so that none of them
    reaches the page hand-typed.

    THE CAVEAT IS PART OF THE NUMBER AND TRAVELS WITH IT. `converged` is 0 of 12 -- eleven cells
    stopped on time_limit and RC201 on max_iter -- so `analysis/rt_normalize.py`'s caution holds in
    full: a time-limited reproduction is NOT "K's method on our machine". What M6 licenses is the
    narrower statement that the reproduced LBBD bound is INSENSITIVE TO BUDGET over this range,
    which is what `masters-growth-median` is doing beside `mean-ratio`. A sentence citing
    `mean-ratio` without the work-unit growth beside it is citing half the result.

    `old-mean-ratio` IS PRESERVED AT THE PRECISION THE REGISTER KEPT IT, two decimals, and cannot
    be recovered at three: rt_fair_pipeline.py stage 1 rewrote the twelve pre-M6 artifacts in
    place and runs/ is gitignored, so the old per-cell bounds are gone. It is declared as its own
    kind in check_number_consistency.py for exactly that reason.

    SCOPE. 12 of 27 n20 cells. Prereg section 6 item 3 requires every figure from this run to be
    reported that way and never as a grid result.
    """
    d = json.load(open(os.path.join(ROOT, "runs/m6_score.json"), encoding="utf-8"))
    rows = d["rows"]
    if len(rows) != 12:
        raise AssertionError(f"M6 must score exactly 12 cells, found {len(rows)}")
    growth = sorted(r["masters"] / r["old_masters"] for r in rows)
    worst = min(rows, key=lambda r: r["ratio"])
    conv = sum(1 for r in rows if r["status"] not in ("time_limit", "max_iter"))
    return {
        "mean-ratio": _fixed(d["mean_ratio"], 3),
        "worst-ratio": _fixed(worst["ratio"], 3),
        "worst-cell": worst["cell"],
        "wins": f"{d['wins']} of {d['n']}",
        "cells": str(d["n"]),
        "old-mean-ratio": _fixed(d["old"]["mean_ratio_vs_lbbd"], 2),
        "old-wins": f"{d['old']['wins']} of {d['old']['n']}",
        "masters-growth-min": _fixed(growth[0], 1),
        "masters-growth-median": _fixed(st.median(growth), 1),
        "masters-growth-max": _fixed(growth[-1], 1),
        "converged": f"{conv} of {len(rows)}",
        "budget-cap-s": str(int(max(r["budget_s"] for r in rows))),
        "budget-floor-s": str(int(min(r["budget_s"] for r in rows))),
    }


@number("m7-matched-budget-n30",
        desc="M7: the |C|=30 arm of the matched-budget reproduction, the registered falsifier of beats-both-k-bounds-v3",
        claim="beats-both-k-bounds-v3")
def _():
    """THE PRE-REGISTERED OUTCOME OF M7. Prereg: PREREG_M7_n30_matched_budget.md, scorer:
    analysis/m7_score.py. Same 12 instance ids as M6, one size up, same budget rule.

    THE OUTCOME IS A RATIO OF TWO MEANS, not a mean. The claim under test is that our margin does
    not DEPEND on which of K's two bounds it is measured against, so the quantity is
    `ratio-of-ratios` = R_lbbd / R_joint, refuted below 0.85. Citing R_lbbd alone reports a margin
    and not the falsifier.

    NOT REFUTED, NEVER CONFIRMED. A falsification test can only refute (CLAUDE.md section 2). Any
    sentence citing these numbers says the falsifier was run and did not refute.

    THE DRIFT IS PART OF THE RESULT AND MUST BE REPORTED WITH IT. `ratio-of-ratios` is 0.967 at
    |C| = 30 against `n20-ratio-of-ratios` 1.002 at |C| = 20 -- a 3.5% move IN the falsifier's
    direction. It is far inside the threshold, and it is one step on two sizes, so it supports no
    trend claim; but reporting 0.967 as though it were 1.0 would be hiding the only signal the run
    produced. `worst-cell-ratio` is the per-cell minimum and lands at 0.8502, two ten-thousandths
    above the threshold's numeric value. The falsifier quantity, the two sizes and the threshold
    are all rendered at 4 dp for exactly that reason: at 3 dp the last two both print 0.850 and
    read as though a cell had touched the threshold. IT HAS NOT, AND IT COULD NOT -- the prereg
    defines the threshold on the AGGREGATE ratio of two means over 12 cells, and never per cell.
    RC204 is reported because the near-coincidence is the kind of thing a referee spots, not
    because it carries any decision.

    THE COMPARATOR IS WEAKER HERE THAN AT n20, not stronger: `converged` is 0 of 12 and all twelve
    stopped on time_limit, five at the 5400 s cap, so rt_normalize.py's caution that a time-limited
    reproduction is NOT "K's method on our machine" travels with every n30 figure.

    SCOPE. 12 of 27 n30 cells, prereg section 5 item 2. Never a grid result.
    """
    d = json.load(open(os.path.join(ROOT, "runs/m7_score.json"), encoding="utf-8"))
    a, b, rows = d["n20"], d["n30"], d["rows_n30"]
    if len(rows) != 12:
        raise AssertionError(f"M7 must score exactly 12 cells, found {len(rows)}")
    per = sorted(rows, key=lambda r: r["r_lbbd"] / r["r_joint"])
    # BUDGET-based. wall >= 5400 would count R208 (budget 5298 s, wall 5411 s) as capped.
    capped = sum(1 for r in rows if r["budget_s"] >= 5400.0 - 1e-9)
    return {
        "ratio-of-ratios": _fixed(b["ratio"], 4),
        "n20-ratio-of-ratios": _fixed(a["ratio"], 4),
        "threshold": _fixed(d["threshold"], 4),
        "r-lbbd": _fixed(b["R_lbbd"], 3),
        "r-joint": _fixed(b["R_joint"], 3),
        "wins-lbbd": f"{b['wins_lbbd']} of 12",
        "wins-joint": f"{b['wins_joint']} of 12",
        "worst-cell": per[0]["cell"],
        "worst-cell-ratio": _fixed(per[0]["r_lbbd"] / per[0]["r_joint"], 4),
        "cells": "12",
        "converged": f"{b['converged']} of 12",
        "at-cap": f"{capped} of 12",
    }


@number("n20-fleet-total",
        desc="|C|=20 street-fleet total against the total K's published mean implies",
        claim="n20-fleet-total-42-best-found")
def _():
    """PREREG: validation/PREREG_n20_fleet_total.md, threshold "a verified 27-cell total <= 42",
    registered before the run. Scored by analysis/n20_fleet_total.py.

    BEST-FOUND, NOT A MINIMUM, and the two are kept apart by construction. `proven-minimal` counts
    only cells where minimality is PROVED -- a verified one-car solution (1 is the floor), the
    L-fleet certificate, or a solver infeasibility proof on the FULL model. C208 is counted
    separately as ARGUED because its minimality rests on H1, which is empirical (12 of 12), not a
    proof. Any sentence using `total` must say best-found until `open-cells` reaches 0.

    S2u's INFEASIBLE results are NOT admitted. They pinned 4 customers to the incumbent, so they
    exclude a one-car solution within that neighbourhood only. Admitting them would add four cells
    to `proven-minimal` on evidence that does not support it.

    K'S TOTAL IS RECONSTRUCTED AND THE RECONSTRUCTION IS EXACT. They publish a |C|=20 street-fleet
    mean of 1.59 over 27 instances (table4_full, wls 1:10, Joint and LBBD agree). Exactly one
    integer total rounds to it: 43. 42/27 = 1.5556 -> 1.56 and 44/27 = 1.6296 -> 1.63.

    NOT A LIKE-FOR-LIKE ALGORITHMIC COMPARISON. Our 42 is a best-of across a portfolio, many seeds
    and several bespoke probes; their 43 is what their reported runs achieved. It is a statement
    about what is ACHIEVABLE, not about which method finds it -- the same asymmetry disclosed for
    the objective leg, and it must travel with the number.
    """
    d = json.load(open(os.path.join(ROOT, "runs/n20_fleet_total.json"), encoding="utf-8"))
    if d["n_cells"] != 27:
        raise AssertionError(f"expected 27 cells, found {d['n_cells']}")
    if d["verified"] != 27:
        raise AssertionError(f"only {d['verified']} of 27 cells verify; the total is not reportable")
    return {
        "total": str(d["total"]),
        "k-total": str(d["k_total"]),
        "margin": str(d["k_total"] - d["total"]),
        "verified": f"{d['verified']} of {d['n_cells']}",
        "one-car-cells": str(sum(1 for r in d["rows"] if r.get("cars") == 1)),
        "two-car-cells": str(sum(1 for r in d["rows"] if r.get("cars") == 2)),
        "proven-minimal": f"{d['proven']} of {d['n_cells']}",
        "argued-cells": str(d["argued"]),
        "open-cells": str(len(d["open_cells"])),
        "k-published-mean": _fixed(1.59, 2),
    }


# ============================================================================ TEP headline tables (2026-09-26)
# Every entry below reads a generating artifact of the TEP leg and nothing else; the n-count is asserted and
# PROVEN (attainment) and OPEN (competition) cells are never pooled (author rule, d498). Claims: the tep-* ids.

# UNIFORM GRID (d684): our side is the LAST GENERATED grid of the one uniform trackable variant prim_ens,
# NOT the retired best_of cross-campaign assembly. Generator: analysis/tep_uniform_grid.py (committed fe98f56).
# G12b heads list in release_gate.py still names the old files -- re-point pending in the gate re-source.
_TEP_BEST_OF = {10: "runs/oracle/tep_uniform_n10.json", 20: "runs/oracle/tep_uniform_n20.json", 30: "runs/oracle/tep_uniform_n30.json"}   # explicit names: G12b greps for them


def _tep_best_of(size):
    d = json.load(open(os.path.join(ROOT, _TEP_BEST_OF[size]), encoding="utf-8"))
    rows = d["rows"]
    if len(rows) != 27:
        raise AssertionError("tep_n%d_best_of: expected 27 cells, found %d" % (size, len(rows)))
    return rows


def _tep_gap_stats(rows):
    g = [100.0 * (r["best"] / r["theirs"] - 1) for r in rows]
    w = max(rows, key=lambda r: r["best"] / r["theirs"])
    return {"cells": str(len(rows)), "median": _fixed(st.median(g), 2), "mean": _fixed(st.mean(g), 2),
            "worst": _fixed(max(g), 2), "worst-cell": w["cell"], "within-1pct": "%d of %d" % (sum(1 for x in g if x <= 1.0), len(rows))}


@number("tep-n10-attainment", desc="|C|=10: attainment of the 27 K-proven optima by the TEP primal (per-cell best-of)", claim="tep-primal-attainment-n10")
def _():
    rows = _tep_best_of(10)
    if not all(r["proven"] for r in rows):
        raise AssertionError("n10 must be all K-proven")
    if any(r["best"] < r["theirs"] - 0.05 for r in rows):
        raise AssertionError("a value below a proven optimum: defect, not reportable")
    return _tep_gap_stats(rows)


def _tep_split(size):
    rows = _tep_best_of(size)
    P = [r for r in rows if r["proven"]]; O = [r for r in rows if not r["proven"]]
    out = {}
    for tag, rs in (("proven", P), ("open", O)):
        for k, v in _tep_gap_stats(rs).items():
            out["%s-%s" % (tag, k)] = v
    out["open-below-k"] = "%d of %d" % (sum(1 for r in O if r["best"] < r["theirs"] - 0.05), len(O))
    lb = [r for r in O if r["our_lb"]]
    if lb:
        # d555: statistics.median everywhere, NOT the upper-middle element of the sorted list. The two differ on an
        # even-sized set -- the 18 n50 open cells printed 16.7 from one script and 15.8 from the other on the same
        # artifacts -- so the estimator is pinned to the standard definition in every script that reports a median.
        og = sorted(100.0 * (1 - r["our_lb"] / r["best"]) for r in lb); tg = sorted(100.0 * (1 - r["their_lb"] / r["theirs"]) for r in lb)
        out["open-bracket-ours"] = _fixed(st.median(og), 1)
        out["open-bracket-k"] = _fixed(st.median(tg), 1)
        out["open-bound-above-k"] = "%d of %d" % (sum(1 for r in lb if r["our_lb"] > r["their_lb"] + 1e-6), len(lb))
        out["open-cells-with-bound"] = str(len(lb))
    return out


@number("tep-n20-split", desc="|C|=20: PROVEN (7) attainment and OPEN (20) competition, with the open-cell bracket and bound comparison", claim="tep-primal-n20")
def _():
    return _tep_split(20)


@number("tep-n30-split", desc="|C|=30: PROVEN (1) attainment and OPEN (26) competition, with the open-cell bracket and bound comparison", claim="tep-primal-n30")
def _():
    return _tep_split(30)


@number("tep-n30-fine-delta", desc="|C|=30: the finer-bucket (d=5) bound leg -- cells proven and the median lift over the default width", claim="tep-bound-above-k-n30")
def _():
    d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_fine_delta_bound_n30_d5.json"), encoding="utf-8"))
    ok = [r for r in d["rows"] if r.get("d_proven") and r.get("base_lp")]
    g = sorted(100.0 * (r["d_lp"] / r["base_lp"] - 1) for r in ok)
    return {"cells": str(len(d["rows"])), "proven-at-d5": "%d of %d" % (len(ok), len(d["rows"])),
            "median-lift": _fixed(st.median(g), 2) if g else "n/a", "unproven": str(len(d.get("unproven", [])))}


@number("tep-n50-pool", desc="|C|=50: our 27-cell mean against the K pool the instances belong to (Table 4, 1:10); pooled, proximity inferred", claim="tep-primal-n50-pool")
def _():
    d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_n50_batch.json"), encoding="utf-8"))
    rows = d["rows"]
    if len(rows) != 27:
        raise AssertionError("tep_n50_batch: expected 27 cells, found %d" % len(rows))
    ours = st.mean(r["best"] for r in rows); kb = min(d["k"]["joint_bk"], d["k"]["lbbd_bk"])
    return {"cells": "27", "our-mean": _fixed(ours, 1), "k-pool-best": _fixed(kb, 1), "vs-k-pct": _fixed(100.0 * (ours / kb - 1), 2),
            "k-pool": str(d.get("k_pool")), "ceil-chosen": str(sum(1 for r in rows if r["best_cfg"] == "ceil"))}


@number("tep-n100-family", desc="|C|=100: family means of our verified primal against K published family means; bound columns only where certified", claim="tep-primal-n100-family")
def _():
    d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_n100_family_table.json"), encoding="utf-8"))
    out = {}
    for r in d["rows"]:
        f = r["family"].lower()
        out[f + "-cells"] = str(r["n"]); out[f + "-ours"] = _fixed(r["our_inc"], 1); out[f + "-k"] = _fixed(r["their_inc"], 1)
        out[f + "-vs-k-pct"] = _fixed(100.0 * (r["our_inc"] / r["their_inc"] - 1), 2)
        out[f + "-lb-certified"] = "yes" if r.get("our_lb") is not None else "no"
        if r.get("our_lb") is not None:
            out[f + "-lb-ratio"] = _fixed(r["our_lb"] / r["their_lb"], 2); out[f + "-our-gap"] = _fixed(r["our_gap"], 1); out[f + "-k-gap"] = _fixed(r["their_gap"], 1)
    if sum(int(v) for k, v in out.items() if k.endswith("-cells")) != 27:
        raise AssertionError("n100 family table must cover 27 cells")
    return out


# ===== TEP BODY RESULT KEYS (grid closed 2026-10-09, d775). Sourced from the consolidated grid
# =====  tep_uniform_n{50,100}.json + K reference + the shared wilcoxon_exact. Key names match §6. =
def _cons(size):
    d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_uniform_n%d.json" % size), encoding="utf-8"))
    r = d["rows"]
    if len(r) != 27:
        raise AssertionError("tep_uniform_n%d: expected 27 cells, found %d" % (size, len(r)))
    return r


def _fam(c):
    return "RC" if c.startswith("RC") else c[0]


def _k_n100_fam():
    """K Table 6 per family: (OV=min(joint,lbbd) zIP, LB=joint zIP*(1-gap/100), gap_joint, n)."""
    import kref_build as _kb
    return {f: (min(d["joint"]["zIP"], d["lbbd"]["zIP"]),
                d["joint"]["zIP"] * (1 - d["gap_joint"] / 100.0), d["gap_joint"], d["n"])
            for f, d in _kb.TABLE6.items()}


def _k_n50_pool():
    """K Table 4 (wls 1:10) pool: (OV=min(joint,lbbd) bk, LB=joint bk*(1-gap_imp/100), gap=K's
    PUBLISHED joint optimality gap).

    THE GAP IS K'S PUBLISHED JOINT GAP, not a recomputed hybrid (d784, reviewer 3B). The only
    optimality gap K print at n50 is the Joint method's gap_imp; LBBD's gap_imp is an
    improvement-over-best-known, not an optimality gap, so it is not an alternative denominator here.
    Dividing the Joint-reconstructed dual by the LBBD incumbent instead printed 57.0 -- a number K
    never published and that mixes one method's bound with another's incumbent. The OV comparator for
    the incumbent-improvement figure stays min(joint,lbbd) (the better of K's two incumbents, d774),
    returned as element 0; the gap returned as element 2 is K's own published figure, consistent with
    how `_k_n100_fam` reads the published per-family joint gap at n100.
    """
    t4 = {r["method"]: r for r in _K()["table4"] if r.get("size") == 50 and r.get("wls") == "1:10"}
    kj, kl = float(t4["Joint"]["bk"]), float(t4["LBBD"]["bk"])
    gap = float(t4["Joint"]["gap_imp"])
    klb = kj * (1 - gap / 100.0)
    return min(kj, kl), klb, gap


@number("protocol", desc="RT protocol constants: hardware factor f, per-cell budget K_cap/f (s), bound-leg threads (d245/d246/d250, d47)", claim="rt-budget-fairness")
def _():
    return {"hw-factor": "2.5", "budget-s": "5760", "bound-threads": "4"}


@number("optgap", desc="opt-gap (OV-LB)/OV means on the competition (open) cells, ours and K, n50/n100 (d763/d742/d774)", claim="tep-primal-n100-family")
def _():
    out = {}
    for size in (50, 100):
        og = [100.0 * (r["best"] - r["our_lb"]) / r["best"] for r in _cons(size) if r.get("our_lb")]
        out["n%d-competition-mean" % size] = _fixed(st.mean(og), 1)
    out["n50-k-mean"] = _fixed(_k_n50_pool()[2], 1)
    fam = _k_n100_fam(); tot = sum(v[3] for v in fam.values())
    out["n100-k-mean"] = _fixed(sum(v[2] * v[3] for v in fam.values()) / tot, 1)
    # incumbent (OV) improvement over the published incumbents, SAME sources as the gap (d774/#48):
    # ours = mean best over the consolidated grid; K = min(joint,lbbd) pooled (n50) / family-weighted
    # (n100); positive = our mean incumbent is that % below K's, at the shared 1:10 weighting.
    our_ov50 = st.mean([r["best"] for r in _cons(50)])
    out["n50-ov-improve-pct"] = _fixed(100.0 * (1 - our_ov50 / _k_n50_pool()[0]), 1)
    our_ov100 = st.mean([r["best"] for r in _cons(100)])
    out["n100-ov-improve-pct"] = _fixed(100.0 * (1 - our_ov100 / (sum(v[0] * v[3] for v in fam.values()) / tot)), 1)
    return out


@number("primal", desc="primal incumbents: n10 slip from the K-proven optima and the count reported dual-derived at n100 (d761/d744)", claim="tep-primal-attainment-n10")
def _():
    rows10 = _tep_best_of(10)
    slip = sorted(100.0 * (r["best"] / r["theirs"] - 1) for r in rows10)
    outliers = sorted(r["cell"] for r in rows10 if (r["best"] / r["theirs"] - 1) * 100.0 > 1.0)
    dd = sum(1 for r in _cons(100) if r.get("dual_derived"))
    return {"n10-median-slip": _fixed(st.median(slip), 3), "n10-mean-slip": _fixed(st.mean(slip), 2),
            "n10-max-slip": _fixed(max(slip), 2), "n10-outlier-cells": ", ".join(outliers),
            "dualonly-cells": str(dd)}


@number("lb-vs-k", desc="certified LB vs K's derived dual: open-cell wins + Wilcoxon (n20/30), K-stronger near-proof cells, pooled/family LB ratios (n50/100). Mirrors lb-dual-wilcoxon (d743).", claim="lb-n20-domination")
def _():
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from s3a_significance import wilcoxon_exact
    Kref = _K(); out = {}; kstronger = 0
    for size in (20, 30):
        per = Kref["table3"]["per_instance"][str(size)]
        rows = []
        for c in sorted(per):
            bk, g = per[c]["joint_bk"], per[c]["joint_gap"]
            if g <= 0:
                continue
            rows.append((c, g, bk, _frontier(c, size)[0], bk * (1 - g / 100.0)))
        n = len(rows)
        wins = sum(1 for r in rows if r[3] > r[4] + 1e-6)
        kstronger += sum(1 for r in rows if r[4] > r[3] + 1e-6)
        wp, wm, z, p, _n, kind = wilcoxon_exact([math.log(r[3] / r[4]) for r in rows])
        p2 = min(1.0, 2 * p)
        ps = []
        for d in (+0.5, -0.5):
            rr = [r[3] / (r[2] * (1 - (r[1] + d) / 100.0)) for r in rows]
            ps.append(min(1.0, 2 * wilcoxon_exact([math.log(x) for x in rr])[3]))
        rb = (wp - wm) / (wp + wm) if (wp + wm) else 0.0
        out["n%d-open-cells" % size] = str(n)
        out["n%d-wins" % size] = "%d of %d" % (wins, n)
        out["n%d-wilcoxon-p" % size] = "%.1g" % p2
        out["n%d-effect" % size] = _fixed(rb, 2)
        if size == 20:
            out["n20-p-robust-range"] = "%.1g--%.1g" % (min(ps), max(ps))
    out["k-stronger-cells"] = str(kstronger)
    our_lb50 = st.mean([r["our_lb"] for r in _cons(50) if r.get("our_lb")])
    out["n50-pooled-ratio"] = _fixed(our_lb50 / _k_n50_pool()[1], 2)
    fam = _k_n100_fam(); byfam = {}
    for r in _cons(100):
        if r.get("our_lb"):
            byfam.setdefault(_fam(r["cell"]), []).append(r["our_lb"])
    for F in ("C", "R", "RC"):
        out["n100-%s-ratio" % F] = _fixed(st.mean(byfam[F]) / fam[F][1], 2)
    return out


def _frz(cell, size):
    """Dual-derived incumbent (ov) + certified LB from the frozen-dual artifact."""
    p = os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8")); rr = d.get("rows", [d]); r0 = rr[0] if isinstance(rr, list) else rr
    if r0.get("ov") is None or r0.get("lb") is None:
        return None
    return float(r0["ov"]), float(r0["lb"])


@number("ablation", unit="%", desc="what the primal leg adds over the dual-derived incumbent: mean OV reduction % and opt-gap reduction pp over cells where the primal ran (all sizes), and the n100 figure (d737/d765/d767)", claim="tep-primal-n100-family")
def _():
    ovg, gapg, n100 = [], [], []
    for size in (10, 20, 30, 50, 100):
        rows = _tep_best_of(size) if size in (10, 20, 30) else _cons(size)
        for r in rows:
            if r.get("dual_derived"):
                continue                      # R204/R208 n100: refinement-not-applied, no treatment
            frz = _frz(r["cell"], size)
            lb = r.get("our_lb")
            if not frz or not lb:
                continue
            dov = frz[0]; fov = r["best"]
            if dov <= 0 or fov <= 0:
                continue
            ovg.append(100.0 * (dov - fov) / dov)
            gapg.append(100.0 * ((dov - lb) / dov - (fov - lb) / fov))
            if size == 100:
                n100.append(100.0 * (dov - fov) / dov)
    return {"mean-ov-gain-pct": _fixed(st.mean(ovg), 1), "mean-gap-gain-pp": _fixed(st.mean(gapg), 1),
            "n100-ov-gain-pct": _fixed(st.mean(n100), 1)}


@number("portfolio", desc="portfolio bound: cells where the closed-form arithmetic bound ab4 carries the composed max over LP+water (all at n10, the smallest instances)", claim="tep-bound-above-k-n30")
def _():
    import glob as _g
    n = 0
    for p in _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_*_n*.json")):
        d = json.load(open(p, encoding="utf-8")); rr = d.get("rows", [d]); r0 = rr[0] if isinstance(rr, list) else rr
        ab, lc = r0.get("ab4"), r0.get("lb_composed")
        if ab is not None and lc is not None and float(ab) > float(lc) + 1e-6:
            n += 1
    return {"ab-carries-cells": str(n)}


@number("transfer-duration-by-family", desc="transfer duration U = ceil(2*mean service) per family, from build_instance tau=formula (the published spec, not the released-generator 0); family-constant across sizes (§3)", claim="objective-identity-v2")
def _():
    import sys as _s
    _s.path.insert(0, ROOT); _s.path.insert(0, os.path.join(ROOT, "analysis"))
    from build_instance import build as _b
    return {fam: str(int(getattr(_b(cell, 100, tau="formula"), "_resolved_tau")))
            for fam, cell in (("C", "C201"), ("R", "R201"), ("RC", "RC201"))}


@number("surrogate-median-delta", unit="%", desc="surrogate vs exact scoring on the n30 grid: max median objective difference over the refine and ALNS arms (design validation, not a result)", claim="tep-primal-n30")
def _():
    v = []
    for arm in ("refine", "alns"):
        d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_surrogate_equivalence_%s_n30.json" % arm), encoding="utf-8"))
        v.append(float(d["median_pct"]))
    return _fixed(max(v), 2)


def _frz_walls(size):
    import glob as _g
    w = {}
    for p in _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_*_n%d.json" % size)):
        d = json.load(open(p, encoding="utf-8")); r = d.get("rows", [d])[0]
        if r.get("wall_s"):
            w[r["cell"]] = float(r["wall_s"])
    return w


def _ov_at_cap(cell, size, cap):
    """Best verified incumbent reached by cumulative wall <= cap, from the pu_ng10 story; falls back
    to the frozen-dual incumbent when no primal artifact exists (R204/R208)."""
    import glob as _g
    p = _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng10_%s_n%d.json" % (cell, size)))
    best = None
    if p:
        d = json.load(open(p[0], encoding="utf-8")); r = d.get("rows", [d])[0]
        for s in r.get("story", []):
            if s.get("out_val") is not None and (s.get("t_run") or 0.0) <= cap + 1e-6:
                v = float(s["out_val"]); best = v if best is None else min(best, v)
    if best is None:
        frz = _frz(cell, size); best = frz[0] if frz else None
    return best


@number("budget-sens", desc="budget sensitivity (#41/d754-759): hardware-factor ceilings from the bound-leg walls, and OV/opt-gap degradation at the ceiling vs f=2.5, re-sliced from the banked ng10 trajectories", claim="rt-budget-fairness")
def _():
    Kcap = 14400.0
    w100, w50 = _frz_walls(100), _frz_walls(50)
    fmax = Kcap / max(w100.values()); fmax50 = Kcap / max(w50.values()); fall = Kcap / min(w100.values())
    out = {"f-max": _fixed(fmax, 1), "f-max-n50": _fixed(fmax50, 1),
           "f-all-derived": "%d" % round(fall), "cap-floor-s": "%d" % round(Kcap / fmax)}
    for size, fm, tag in ((100, fmax, "n100"), (50, fmax50, "n50")):
        capb, capf = Kcap / 2.5, Kcap / fm
        ovg, gfm, gb = [], [], []
        for r in _cons(size):
            lb = r.get("our_lb")
            ob = _ov_at_cap(r["cell"], size, capb); of = _ov_at_cap(r["cell"], size, capf)
            if not (lb and ob and of):
                continue
            ovg.append(100.0 * (of - ob) / ob)
            gfm.append(100.0 * (of - lb) / of); gb.append(100.0 * (ob - lb) / ob)
        if size == 100:
            out["ov-degrade-max-pct"] = _fixed(st.mean(ovg), 1)
            out["n100-base-mean"] = _fixed(st.mean(gb), 1)
            out["n100-derived-mean"] = _fixed(st.mean(gfm), 1)
            out["gap-degrade-max-pp"] = _fixed(st.mean(gfm) - st.mean(gb), 1)
        else:
            out["n50-base-mean"] = _fixed(st.mean(gb), 1)
            out["n50-derived-mean"] = _fixed(st.mean(gfm), 1)
    return out


@number("longrt-n50", desc="n50 LONGER-than-budget sensitivity (appendix): the ng-union consolidation drops any ng run that pushes a cell's cumulative wall past the fair 5760 s cap (d716/d717); re-admitting those over-budget runs (cumulative up to ~1.7x the cap) moves the mean optimality gap by hundredths of a point -- the reported n50 gap is not budget-limited. Distinct from budget-sens, which sweeps the ng10 run's own trajectory toward SHORTER budgets.", claim="rt-budget-fairness")
def _():
    import glob as _g
    cap = 5760.0

    def _row(ng, cell):
        p = _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng%d_%s_n50.json" % (ng, cell)))
        if not p:
            return None
        d = json.load(open(p[0], encoding="utf-8"))
        return d.get("rows", [d])[0]

    cells = sorted({os.path.basename(f).split("_")[4]
                    for f in _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng10_*_n50.json"))})
    fitg, fullg, improved = [], [], []
    maxmult, maxcell = 0.0, None
    for c in cells:
        runs = {ng: _row(ng, c) for ng in (10, 5, 25)}
        if runs[10] is None or not runs[10].get("lb"):
            continue
        lb = runs[10]["lb"]
        cum, fit, full, fullcum = 0.0, [], [], 0.0
        for ng in (10, 5, 25):                       # ng10 mandatory (the baseline+LB), then ng5, ng25
            r = runs[ng]
            if r is None or r.get("ov") is None:
                continue
            w = r.get("wall_s") or 0.0
            full.append(r["ov"]); fullcum += w
            if ng == 10 or cum + w <= cap:           # budget-fit consolidation (the reported grid)
                fit.append(r["ov"]); cum += w
        if not fit or not full:
            continue
        fo, uo = min(fit), min(full)                 # fair-budget union vs full (longer) union
        fitg.append(100.0 * (fo - lb) / fo); fullg.append(100.0 * (uo - lb) / uo)
        if uo < fo - 1e-6:
            improved.append(c)
        m = fullcum / cap
        if m > maxmult:
            maxmult, maxcell = m, c
    # The fair-budget mean gap is already reported as optgap.n50-competition-mean (15.4%); we do NOT
    # re-register it here (a 1-dp fair/full PAIR would read as a 0.1 pp move and contradict the true
    # sub-0.1 pp delta). The appendix reuses that figure and reports the delta, which is the finding.
    return {"cells": "%d" % len(fitg),
            "delta-pp": _fixed(st.mean(fitg) - st.mean(fullg), 2),
            "cells-improved": "%d" % len(improved),
            "max-mult": _fixed(maxmult, 2),
            "max-mult-cell": maxcell}


@number("depth", desc="computational depth (#50): time-to-best crossing K's published levels (open cells n20/30), bound-leg wall share at n100, and pricing work scaling n50->n100", claim="rt-budget-fairness")
def _():
    import glob as _g
    Kref = _K(); ttb_lb, ttb_ov = [], []
    for size in (20, 30):
        per = Kref["table3"]["per_instance"][str(size)]
        for c in sorted(per):
            bk, g = per[c]["joint_bk"], per[c]["joint_gap"]
            if g <= 0:
                continue
            kdual = bk * (1 - g / 100.0)
            fp = os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_%s_n%d.json" % (c, size))
            if os.path.exists(fp):
                r = json.load(open(fp, encoding="utf-8")).get("rows", [{}])[0]
                for h in r.get("lb_hist", []):
                    if h.get("lp") is not None and float(h["lp"]) >= kdual:
                        ttb_lb.append(float(h.get("secs") or 0.0)); break
            pp = _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng10_%s_n%d.json" % (c, size)))
            if pp:
                rr = json.load(open(pp[0], encoding="utf-8")).get("rows", [{}])[0]
                for s in rr.get("story", []):
                    if s.get("out_val") is not None and float(s["out_val"]) <= bk:
                        ttb_ov.append(float(s.get("t_run") or 0.0)); break
    shares = []
    for p in _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_*_n100.json")):
        r = json.load(open(p, encoding="utf-8")).get("rows", [{}])[0]; bw = r.get("wall_s"); cell = r.get("cell")
        pp = _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_pu_ng10_%s_n100.json" % cell))
        if bw and pp:
            rr = json.load(open(pp[0], encoding="utf-8")).get("rows", [{}])[0]; pw = rr.get("wall_s")
            if pw and float(pw) >= float(bw):
                shares.append(100.0 * float(bw) / float(pw))

    def _medwork(size):
        ws = []
        for p in _g.glob(os.path.join(ROOT, "runs/oracle/tep_solve_frzdual2_*_n%d.json" % size)):
            r = json.load(open(p, encoding="utf-8")).get("rows", [{}])[0]
            if r.get("det_work_total"):
                ws.append(float(r["det_work_total"]))
        return st.median(ws) if ws else None
    w50, w100 = _medwork(50), _medwork(100)
    note = ("a factor of %.1f from $|C|=50$ to $100$" % (w100 / w50)) if (w50 and w100) else "n/a"
    return {"ttb-lb-median-s": _fixed(st.median(ttb_lb), 0) if ttb_lb else "n/a",
            "ttb-ov-median-s": _fixed(st.median(ttb_ov), 0) if ttb_ov else "n/a",
            "lb-wall-share": _fixed(st.median(shares), 0) if shares else "n/a",
            "work-scaling-note": note}


@number("tep-coverage", desc="which K exhibits the TEP results cover and which stay uncovered", claim="tep-primal-n100-family")
def _():
    d = json.load(open(os.path.join(ROOT, "runs/oracle/tep_coverage_map.json"), encoding="utf-8"))
    un = d.get("uncovered", [])
    return {"uncovered": str(len(un)), "sizes": str(len(d.get("sizes", [])))}



@number("tep-bound-calibration", desc="bound quality against GROUND TRUTH: distance of our certified bound below the proven optimum, by size, with the share of the objective one car costs",
        claim="tep-bound-calibration")
def _():
    """The only like-for-like ruler for a lower bound is a known optimum, and K prove optima on 27 cells at |C|=10,
    7 at |C|=20 and 1 at |C|=30. Reported in the same convention as every other gap in the paper, (OPT - LB)/OPT.
    The car-share column is the mechanism: the relaxation prices the fleet continuously, so its gap tracks what one
    car is worth relative to the objective. A finer bucket width does NOT close it (n10 C202: identical LP at
    widths 60, 20 and 5), so the gap is not a discretisation artefact.

    WHAT CLOSES IT, measured 2026-09-27 (d568): rounding the fleet variable does. Adding N >= ceil(N_LP) after the
    proof and re-pricing to proof -- valid because the LP's car count bounds the cars of every feasible solution
    from below and cars are integer -- moved this table's n10 mean from 22.9 to 18.8 per cent and its n20 mean from
    16.3 to 9.9 on the first 15 cells alone. So "structural" means structural to the CONTINUOUS PRICING OF THE
    FLEET, and the fix is to round that term rather than to refine time. The paragraph in the paper says it that
    way; anything stronger would be contradicted by this table's own movement."""
    import verifier3 as V
    out = {}
    for n in (10, 20, 30):
        rows = [r for r in _tep_best_of(n) if r["proven"] and r["our_lb"]]
        if not rows: continue
        g = [100.0 * (1 - r["our_lb"] / r["theirs"]) for r in rows]
        inst = V.load_instance(rows[0]["cell"], n, 0.0)
        share = 100.0 * float(inst.penalty_cars) / st.mean(r["theirs"] for r in rows)
        out["n%d-cells" % n] = str(len(rows)); out["n%d-mean" % n] = _fixed(st.mean(g), 1)
        out["n%d-median" % n] = _fixed(st.median(g), 1); out["n%d-max" % n] = _fixed(max(g), 1)
        out["n%d-car-share" % n] = _fixed(share, 1)
    return out


@number("tep-abstract", desc="every quantity the ABSTRACT asserts, from analysis/abstract_facts.py -- their proofs and published averages, our attainment over all 35 proven cells, the open-cell brackets at every size, which end closes the interval, and the budget",
        claim="abstract-quantities-audited")
def _():
    """The abstract is the paragraph a referee reads adversarially, so nothing in it is typed and nothing in it
    is derived here: every value comes from runs/oracle/abstract_facts.json, whose script also audits the K side
    against their own tables and exits nonzero if a count does not reconcile. Run that script before the build."""
    d = json.load(open(os.path.join(ROOT, "runs/oracle/abstract_facts.json"), encoding="utf-8"))
    T, A, B, C, R = d["theirs"], d["attainment"], d["brackets"], d["closure"], d["runtime"]
    if T["cells_total"] != 135 or T["proven_total"] != 35:
        raise AssertionError("K coverage moved: %s of %s" % (T["proven_total"], T["cells_total"]))
    out = {"k-instances": str(T["cells_total"]), "k-proven": str(T["proven_total"]),
           "k-avg-min": _fixed(T["published_average_min"] if T["published_average_min"] > 0 else
                               min(v for v in T["published_averages"].values() if v > 0), 1),
           "k-avg-max": _fixed(T["published_average_max"], 1),
           # every percentage in this entry renders at 1 dp -- including the ones K publish as whole
           # numbers -- so that analysis/check_number_consistency.py C3 has ONE kind to compare and a
           # reader never sees the same quantity twice at two widths. The counts are declared as counts
           # there; the attainment pair carries 2 dp because 0.35 has no first decimal to spare.
           "k-per-instance-max": _fixed(T["per_instance_gap_max"], 1),
           "attain-cells": str(A["all"]["cells"]), "attain-mean": _fixed(A["all"]["mean"], 2),
           "attain-exact": str(A["all"]["exact"]), "attain-within1": str(A["all"]["within1"]),
           "attain-worst": _fixed(A["all"]["worst"], 2)}
    for k in ("n20", "n30", "n50"):
        v = B[k]
        out[k + "-cells"] = str(v["cells"]); out[k + "-ours"] = _fixed(v["ours_median"], 1)
        if v.get("k_median") is not None:
            out[k + "-k"] = _fixed(v["k_median"], 1); out[k + "-smaller"] = str(v["smaller_than_k"])
    out["n100-cells"] = str(B["n100"]["cells"]); out["n100-ours"] = _fixed(B["n100"]["ours_mean"], 1)
    out["n100-k"] = _fixed(B["n100"]["k_mean"], 1)
    inc = [abs(r["inc_vs_k"]) for r in B["n100"]["by_family"].values()]
    out["n100-inc-min"] = _fixed(min(inc), 1); out["n100-inc-max"] = _fixed(max(inc), 1)
    for k in ("n20", "n30", "n100"):
        out[k + "-bound-share"] = _fixed(C[k]["bound_share"], 1)
    if R:
        out["budget-worst-share"] = _fixed(R["worst_cell_share_at_2p5"], 1)
        out["budget-worst-cell"] = "%s at |C|=%s" % (max((v for k, v in R.items() if isinstance(v, dict)),
                                                        key=lambda v: v["max_share_at_2p5"])["max_cell"],
                                                     max(((k, v) for k, v in R.items() if isinstance(v, dict)),
                                                         key=lambda kv: kv[1]["max_share_at_2p5"])[0][1:])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="recompute and DIFF against the stored file; non-zero exit if anything moved")
    a = ap.parse_args()
    sys.exit(main(a.check))
