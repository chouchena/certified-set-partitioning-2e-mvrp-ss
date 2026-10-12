"""The single authority for HOW to compare against K. Import it; do not re-derive it.

TWO MISTAKES KEEP RECURRING, and both recur for the same structural reason: the knowledge lives
in `text_facts` and in the heads of a few well-written analyses, so every new script re-derives it
and the newest one forgets.

  1. INCLUDING CELLS K PROVE OPTIMAL IN A **DUAL** COMPARISON. Where their gap is 0 their dual
     bound EQUALS the optimum, so no bound can exceed it. Including such a cell scores a loss that
     was never available and drags the mean toward 1. `analysis/lb_vs_k_headline.py` splits proven
     from unproven and always has; `m6_score.py` did not, which is why M6 reported "11 of 12, sole
     loss RC201" when RC201 is the ONLY cell where winning was impossible -- on the comparable set
     it is 11 of 11 at 1.640 rather than 1.586.

     This does NOT apply to PRIMAL comparisons. Matching a proven optimum is a legitimate tie and
     is scored as one (DESIGN_B_trip_based_primal.md Amendment 2.5). Hence `purpose`.

  2. TAKING THE WRONG PROXIMITY AT |C| = 100. K's Tables 3 and 4 are at proximity 0.0 and Table 6
     is at 0.1. `InstanceSpec.proximity` defaults to 0.0 with the comment "Tables 3/4 base", so
     `InstanceSpec(cell, 100)` silently yields the WRONG scenario -- a wrong answer rather than an
     error. `ab4_grid.py` already had to be given a required proximity argument and two write
     guards for this exact class of bug.

Neither value is hardcoded here: both are read from `k_reference.json`, so if the extraction of
K's paper is ever corrected this follows.

Usage:

    from analysis.k_comparison import k_proximity, comparable_cells, proven_cells

    prox  = k_proximity(100)                      # -> 0.1, from text_facts, not from memory
    cells = comparable_cells(20, purpose="dual")  # -> the 20 cells where a win is possible
    cells = comparable_cells(20, purpose="primal")# -> all 27; a tie on a proven cell counts
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Which published table carries each size. K report per-instance at 10/20/30 (Table 3), |C| = 50
# by cost ratio (Table 4), and |C| = 100 per family (Table 6).
K_TABLE_FOR_SIZE = {10: "table3", 20: "table3", 30: "table3", 50: "table4", 100: "table6"}

PURPOSES = ("dual", "primal")


def _kref():
    from analysis.manuscript_numbers import _K
    return _K()


def k_table_for_size(size):
    if size not in K_TABLE_FOR_SIZE:
        raise KeyError(f"no published K table for |C| = {size}; known sizes "
                       f"{sorted(K_TABLE_FOR_SIZE)}")
    return K_TABLE_FOR_SIZE[size]


def k_proximity(size):
    """The satellite proximity K's table FOR THIS SIZE is measured at.

    0.0 for |C| in {10, 20, 30, 50}, 0.1 for |C| = 100. Read from `text_facts.proximity`, never
    hardcoded, so a correction to the extraction propagates. Compare against a bound built at a
    different proximity and the two are not the same problem.
    """
    return _kref()["text_facts"]["proximity"][k_table_for_size(size)]


def proven_cells(size):
    """Cells K prove optimal at this size (published gap of exactly 0).

    Only meaningful where K publish per-instance gaps, i.e. Table 3 sizes. At |C| = 50 and 100
    they aggregate and no per-instance statement exists, so this returns an empty set and callers
    must not infer that nothing is proved -- only that we cannot tell per instance.
    """
    if k_table_for_size(size) != "table3":
        return set()
    per = _kref()["table3"]["per_instance"].get(str(size), {})
    return {c for c, r in per.items() if r.get("joint_gap") == 0}


def comparable_cells(size, purpose="dual", universe=None):
    """Cells on which a comparison against K is meaningful at this size.

    purpose="dual"   -- EXCLUDES cells K prove optimal. Their dual bound is the optimum; a bound
                        cannot exceed it, so including them scores an unavailable loss.
    purpose="primal" -- includes everything. Matching a proven optimum is a tie, not a failure.

    `universe` defaults to the cells we hold artifacts for at this size.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}, got {purpose!r}")
    from analysis.manuscript_numbers import _cells
    cells = list(universe) if universe is not None else list(_cells(size))
    if purpose == "primal":
        return cells
    prov = proven_cells(size)
    return [c for c in cells if c not in prov]


def describe(size):
    """One line a caller can print so the arm it used is visible in its own output."""
    prov = sorted(proven_cells(size))
    return (f"|C|={size}: K table {k_table_for_size(size)}, proximity {k_proximity(size)}, "
            f"{len(prov)} cell(s) proved optimal"
            + (f" ({', '.join(prov)}) excluded from dual comparisons" if prov else ""))


def audit_artifact_proximity(verbose=True):
    """Every stored record must have been built at the proximity K's table for its size uses.

    THE TRAP THIS CATCHES. `InstanceSpec.proximity` defaults to 0.0 ("Tables 3/4 base"), which is
    a WRONG ANSWER rather than an error at |C| = 100, where K's Table 6 is at 0.1. Twenty-four
    call sites construct an InstanceSpec and exactly one passes proximity explicitly, so a run at
    --size 100 that takes the default silently builds a different problem from the one it is
    compared against. Four of those sites are on the .verify() path, which is the `fleetdrop`
    failure class: the probe solved at one parameter while the verifier checked at another.

    RECORDS WITHOUT THE FIELD ARE COUNTED, NOT GUESSED. 414 of them predate it. At |C| = 20 and 30
    the correct value is 0.0, which was also the default, so they are almost certainly right --
    but "almost certainly" is not a check, and back-filling a guess would be worse than the
    omission. That is the same rule `lb_estimator.is_reproducible` already applies to `limit_hit`.
    They are reported as unverifiable and do not fail the audit.
    """
    import glob, json
    bad, seen, absent = [], 0, 0
    for size in (20, 30, 50, 100):
        want = k_proximity(size)
        for f in glob.glob(os.path.join(ROOT, "crossfeed",
                                        "easy_reduction_descend_*_n%d*.json" % size)):
            recs = json.load(open(f, encoding="utf-8"))
            recs = recs if isinstance(recs, list) else [recs]
            for r in recs:
                if not isinstance(r, dict):
                    continue
                got = r.get("proximity", "ABSENT")
                if got == "ABSENT":
                    absent += 1
                    continue
                seen += 1
                if abs(float(got) - float(want)) > 1e-9:
                    bad.append((os.path.basename(f), size, got, want))
    if verbose:
        print("artifact proximity audit")
        print("  records checked     : %d" % seen)
        print("  records unverifiable: %d (no proximity field; predate it, not back-filled)" % absent)
        print("  MISMATCHES          : %d" % len(bad))
        for b in bad[:10]:
            print("    %s  |C|=%s recorded %s, K table uses %s" % b)
    return bad


def _selftest():
    ok = True

    def check(label, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print(f"  [{'ok ' if good else 'FAIL'}] {label}: {got!r}" + ("" if good else f" != {want!r}"))

    print("k_comparison selftest")
    check("proximity at 20", k_proximity(20), 0.0)
    check("proximity at 50", k_proximity(50), 0.0)
    check("proximity at 100", k_proximity(100), 0.1)
    # THE EXPECTATIONS BELOW ARE THE 27-CELL GRID, not M6's 12-cell subset. Writing them from
    # the subset is the mistake this selftest caught on its first run: RC201 is the only proven
    # cell among M6's twelve, but SEVEN of the twenty-seven are proven at |C| = 20.
    check("proven at 20", sorted(proven_cells(20)),
          ["C201", "C205", "C206", "C208", "R201", "R205", "RC201"])
    check("proven at 30", sorted(proven_cells(30)), ["C201"])
    check("proven at 100 (aggregated -> empty)", proven_cells(100), set())
    d20, p20 = comparable_cells(20, "dual"), comparable_cells(20, "primal")
    check("dual arm at 20 excludes RC201", "RC201" in d20, False)
    check("primal arm at 20 keeps RC201", "RC201" in p20, True)
    check("dual arm at 20 drops all 7 proven", len(p20) - len(d20), 7)
    check("dual arm at 20 has 20 cells", len(d20), 20)
    try:
        comparable_cells(20, "bogus")
        check("bad purpose rejected", False, True)
    except ValueError:
        check("bad purpose rejected", True, True)
    for s in (20, 30, 50, 100):
        print("  " + describe(s))
    bad = audit_artifact_proximity()
    check("no artifact built at the wrong proximity", len(bad), 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())


def k_best_incumbent(cell, size):
    """Their BEST published incumbent for a cell: min over the two methods they report (d455).

    They publish joint_bk AND lbbd_bk per instance at 10, 20 and 30. `k_targets_small.json`
    records only joint_bk as `k_inc`, and their decomposition is the better of the two on 9 of 27
    cells at n20 and 23 of 27 at n30 -- by as much as 1047.2 against 843.6 on C203 at n30. A
    comparison against joint_bk alone therefore FLATTERS us, and did: it produced a withdrawn
    claim that R211 improved on them at n20 when it beats only their weaker method.

    Returns (value, which_method) or (None, None) where they publish no per-instance figure.
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
    import kref
    if size not in kref.PER_INSTANCE_SIZES:
        return None, None
    t = kref.table3(size)
    rows = t.get("per_instance") or t
    d = rows.get(cell)
    if not d:
        return None, None
    j = float(d["joint_bk"])
    l = float(d.get("lbbd_bk") or j)
    return (l, "LBBD") if l < j else (j, "Joint")
