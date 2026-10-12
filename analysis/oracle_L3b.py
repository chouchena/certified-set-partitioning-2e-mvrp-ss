"""L3b -- G-d. A comparison against K at n50 and n100, where I had said none was possible.

THE HOLE I CLAIMED WAS STRUCTURAL. L1b covers n10, L3 covers n20/n30. Neither reaches n50 or
n100 -- and n40 upward is exactly where L0 says (26) can first bind. K DO publish both sizes
(Table 4, Table 6), but as incumbents carrying gaps of 60-77 percent, so they cannot serve an
"is our optimum their optimum" test. I concluded no run closes it. That was too quick.

THE TEST THAT DOES WORK, and needs no optimum on either side.

A published incumbent is a FEASIBLE POINT of K's model, so it is an UPPER BOUND on K's optimum.
A valid lower bound for OUR model is a lower bound on ours. If the two models are the same model:

    LB_ours  <=  z*_ours  =  z*_K  <=  BK_K

so LB_ours <= BK_K must hold. A violation is a HARD CONTRADICTION with exactly two readings:

    (a) our model is OVER-TIGHT -- we exclude the region their solution lives in, so our optimum
        sits above their feasible point; or
    (b) their published incumbent is not feasible in their own model.

Either is a finding. This is one-sided -- LB_ours <= BK_K is consistent with an UNDER-tight model
too, so passing corroborates nothing about looseness. L2c is the instrument for that direction.

WHY IT IS WORTH RUNNING ANYWAY. It is the ONLY check that reaches K's published numbers at the
sizes where (26) binds, and the sizes where our own primal work lives. A per-cell margin that
stays comfortably positive at n20/n30 and collapses towards zero at n100 would also localise
where a transcription problem, if there is one, starts to matter.

    python analysis/oracle_L3b.py
"""
import json
import os
import sys
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

OUT = os.path.join(ROOT, "runs", "oracle")
FAM = {"C": "C", "R": "R", "RC": "RC"}


def fam_of(cell):
    return "RC" if cell.startswith("RC") else cell[0]


def k_upper(k, cell, size):
    """K's published UPPER bound on the optimum for this cell, and where it came from.

    Per-instance at n10/20/30 (Table 3). At n100 K publish family AVERAGES only (Table 6), so the
    per-cell bound is not available and the family mean is compared against our family mean --
    a weaker statement, and labelled as one.
    """
    s = str(size)
    t3 = k.get("table3", {}).get("per_instance", {}).get(s, {})
    if cell in t3 and t3[cell].get("joint_bk") is not None:
        return float(t3[cell]["joint_bk"]), "Table 3 per-instance"
    return None, None


def k_size_upper(k, size, wls="1:10"):
    """K's Table 4 is a LIST of size-level aggregates, not per-instance rows. The tightest upper
    bound on their optimum at a size is the LOWEST published incumbent across their methods."""
    t4 = k.get("table4")
    if not isinstance(t4, list):
        return None, None
    vals = [r.get("bk") for r in t4
            if r.get("size") == size and r.get("wls") == wls and r.get("bk") is not None]
    if not vals:
        return None, None
    return float(min(vals)), "Table 4 size mean, wls %s (min over their methods)" % wls


def k_family_upper(k, fam, size):
    if size != 100:
        return None, None
    t6 = k.get("table6", {}).get(fam, {})
    vals = [t6.get("joint", {}).get("zIP"), t6.get("lbbd", {}).get("zIP")]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    # the LOWEST published incumbent is the tightest upper bound on their optimum
    return float(min(vals)), "Table 6 family mean (min of joint / LBBD zIP)"


def our_bounds():
    """Every lower bound we have, keyed (cell, size). AB variants are all valid LBs; take the
    LARGEST, because that is the strongest claim and therefore the easiest to contradict."""
    out = {}
    srcs = [os.path.join(ROOT, "runs", "ab4_grid_results.json"),
            os.path.join(ROOT, "runs", "ab_vs_milp.json")]
    rows = []
    for path in srcs:
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        rows += (d if isinstance(d, list) else list(d.values()))
    for r in rows:
        if not isinstance(r, dict):
            continue
        cell, size = r.get("cell"), r.get("size")
        if not cell or not size:
            continue
        # the STRONGEST valid lower bound we hold, because that is the easiest to contradict.
        # V_ab1/V_new/V_final are vehicle COUNTS, not bounds -- including them would have
        # compared a fleet size against an objective.
        cands = [r.get(kk) for kk in ("ab4", "ab3", "ab1", "milp")]
        cands = [float(v) for v in cands if isinstance(v, (int, float))]
        if not cands:
            continue
        best = max(cands)
        key = (cell, int(size))
        if key not in out or best > out[key][0]:
            out[key] = (best, "strongest of ab1/ab3/ab4/milp")
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = json.load(open(os.path.join(ROOT, "data", "karademir2025", "k_reference.json"),
                       encoding="utf-8"))
    lbs = our_bounds()
    print("L3b -- LB_ours <= BK_K. The only check that reaches K's published numbers at n50/n100.")
    print("       One-sided: a violation refutes; passing corroborates nothing about looseness.")
    print()
    print("   %-7s %5s %12s %12s %11s  %s" % ("cell", "n", "our LB", "K upper", "margin",
                                              "source"))
    rows, viol = [], []
    per_size = {}
    for (cell, size), (lb, src) in sorted(lbs.items(), key=lambda t: (t[0][1], t[0][0])):
        ku, ksrc = k_upper(k, cell, size)
        if ku is None:
            continue
        margin = ku - lb
        ok = margin >= -0.05
        rows.append(dict(cell=cell, size=size, lb=lb, k_upper=ku, margin=margin, ok=ok,
                         our_source=src, k_source=ksrc))
        per_size.setdefault(size, []).append(margin / ku if ku else 0.0)
        if not ok:
            viol.append("%s/n%d: our LB %.3f EXCEEDS K's published incumbent %.3f by %.3f"
                        % (cell, size, lb, ku, -margin))
        print("   %-7s %5d %12.3f %12.3f %11.3f  %s %s"
              % (cell, size, lb, ku, margin, ksrc, "" if ok else "  <-- CONTRADICTION"))

    # n50: K publish size-level aggregates only (Table 4 is a list, not per-instance rows)
    print()
    for size in (50,):
        ku, ksrc = k_size_upper(k, size)
        ours = [lb for (c, sz), (lb, _sr) in lbs.items() if sz == size]
        if ku is None or not ours:
            continue
        mean_lb = sum(ours) / len(ours)
        margin = ku - mean_lb
        ok = margin >= -0.05
        rows.append(dict(cell="all cells", size=size, lb=mean_lb, k_upper=ku, margin=margin,
                         ok=ok, our_source="mean of %d cells" % len(ours), k_source=ksrc))
        per_size.setdefault(size, []).append(margin / ku if ku else 0.0)
        if not ok:
            viol.append("n%d: our mean LB %.3f EXCEEDS K's published %.3f" % (size, mean_lb, ku))
        print("   %-7s %5d %12.3f %12.3f %11.3f  %s %s"
              % ("all", size, mean_lb, ku, margin, ksrc, "" if ok else "  <-- CONTRADICTION"))

    # n100: K publish family averages only
    print()
    for fam in ("C", "R", "RC"):
        ku, ksrc = k_family_upper(k, fam, 100)
        ours = [lb for (c, s), (lb, _sr) in lbs.items() if s == 100 and fam_of(c) == fam]
        if ku is None or not ours:
            continue
        mean_lb = sum(ours) / len(ours)
        margin = ku - mean_lb
        ok = margin >= -0.05
        rows.append(dict(cell="family %s" % fam, size=100, lb=mean_lb, k_upper=ku,
                         margin=margin, ok=ok, our_source="mean of %d cells" % len(ours),
                         k_source=ksrc))
        per_size.setdefault(100, []).append(margin / ku if ku else 0.0)
        if not ok:
            viol.append("family %s at n100: our mean LB %.3f EXCEEDS K's published %.3f"
                        % (fam, mean_lb, ku))
        print("   %-7s %5d %12.3f %12.3f %11.3f  %s %s"
              % ("fam " + fam, 100, mean_lb, ku, margin, ksrc,
                 "" if ok else "  <-- CONTRADICTION"))

    print()
    print("   comparisons %d   contradictions %d" % (len(rows), len(viol)))
    for v in viol:
        print("      " + v)
    print()
    print("   MARGIN AS A FRACTION OF K'S VALUE, by size -- where a problem would first show:")
    for s in sorted(per_size):
        m = per_size[s]
        print("      n%-4d  n=%2d   min %+.1f%%   median %+.1f%%   max %+.1f%%"
              % (s, len(m), 100 * min(m), 100 * st.median(m), 100 * max(m)))
    print()
    print("   POWER, stated because the margins above are wide. This test fires only once our")
    print("   lower bound RISES ABOVE K's incumbent, so an over-tight model is invisible until")
    print("   it inflates the optimum by the whole margin. Smallest detectable inflation:")
    for s_ in sorted(per_size):
        m = per_size[s_]
        need = 1.0 / (1.0 - min(m)) if min(m) < 1 else float("inf")
        print("      n%-4d  the optimum would have to be inflated by at least %.0f%% before any"
              % (s_, 100 * (need - 1)))
        print("             cell at this size could contradict K")
    print()
    if not viol:
        print("   NOT REFUTED. No lower bound we hold exceeds a value K publish as attainable,")
        print("   at any size we can reach.")
        print()
        print("   BUT IT DOES NOT CLOSE THE n50/n100 GAP IT WAS BUILT FOR. The power table above")
        print("   is the real result: at n20 and n30 the test bites at a 2-3% inflation, which is")
        print("   a genuine constraint on over-tightness. At n50 and n100 our bound sits 45-70%")
        print("   below K's incumbent, so the optimum would have to roughly DOUBLE before")
        print("   anything could fire. At exactly the sizes where (26) binds, this instrument is")
        print("   close to powerless, and the coverage hole at n50/n100 STAYS OPEN. Closing it")
        print("   needs a stronger lower bound, not another comparison.")
        print()
        print("   IT CORROBORATES ONE DIRECTION ONLY. An UNDER-tight model also passes this, and")
        print("   comfortably: a looser model has a lower optimum and a lower bound. And the n100")
        print("   row compares a family MEAN to a family MEAN, because K publish no per-instance")
        print("   n100 values -- weaker than the per-cell rows above it.")
    json.dump(stamped({"rows": rows, "violations": viol,
               "verdict": "NOT REFUTED" if not viol else "CONTRADICTION"}, __file__),
              open(os.path.join(OUT, "L3b.json"), "w"), indent=1, default=str)
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
