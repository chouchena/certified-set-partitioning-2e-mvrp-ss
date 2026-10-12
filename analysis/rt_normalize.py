"""RT comparability without a hardware fudge factor.

THE PROBLEM. K ran Gurobi 9.12 on 4x Xeon Gold 5218 @2.30GHz; we run CPLEX on an Intel Core
Ultra 7 258V (Lunar Lake, 4 P-cores + 4 LPE) at roughly twice the clock. Any wall-clock ratio
against K's PUBLISHED times mixes algorithm, solver and hardware.

WHY CORE-SECONDS DO NOT FIX IT. KC-3 prescribes "laptop timings + explicit core-normalization
(core-seconds)". That is the right unit for reconciling OUR OWN 8-thread screens against our
4-thread runs, but it does nothing for the K comparison: both sides are 4 cores, so the ratio
is unchanged. Core-seconds is bookkeeping, not normalisation.

WHAT ACTUALLY WORKS, in descending order of strength:
 1. ELIMINATE the hardware term -- compare against OUR OWN reproduction of K's LBBD, run on
    this machine. runs/lbbd_<cell>_n20_karademir.jsonl. The hardware cancels exactly instead of
    being estimated. This only transfers the problem, though: the comparison is now only as
    good as the reproduction, so this script MEASURES that fidelity rather than assuming it.
 2. WORK UNITS -- solver- and hardware-independent counts. Our bound is one root solve; K's
    LBBD needs N master solves + N subproblem solves + N optimality cuts. Those counts are
    extractable from the traces and are typically more convincing to an OR referee than
    seconds.
 3. A scalar machine factor (SPEC / MIPLIB ratio) -- weakest. MILP performance does not reduce
    to one scalar. Sensitivity check only, never the basis of a claim.

Reports 1 and 2, and flags every cell whose reproduction did NOT converge -- a time-limited
reproduction is a weak comparator and must not be presented as "K's method on our machine".
"""
import glob, json, os, re, sys
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.lb_coverage import k_paper_lb          # noqa: E402
from analysis.lb_crossing_samehw import our_bounds   # noqa: E402


def repro(cell, size=20):
    """Parse our same-machine reproduction of K's LBBD -> bound, wall, work units, status."""
    p = os.path.join(ROOT, "runs", f"lbbd_{cell}_n{size}_karademir.jsonl")
    if not os.path.exists(p):
        return None
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    if not rows:
        return None
    bound = inc = None
    iters, cuts, masters, subs = set(), 0, 0, 0
    status, wall, cfg = None, None, {}
    for r in rows:
        b = r.get("best_bound")
        if isinstance(b, (int, float)):
            bound = b if bound is None else max(bound, b)
        i = r.get("best_incumbent")
        if isinstance(i, (int, float)):
            inc = i if inc is None else min(inc, i)
        t = str(r.get("trigger") or "")
        m = re.search(r"iter(\d+)", t)
        if m:
            iters.add(int(m.group(1)))
        if t.startswith("opt_cut"):
            cuts += 1
        if t.startswith("master:"):
            masters += 1
        if t.startswith("lbbd:"):
            subs += 1
        e = r.get("extra") or {}
        if isinstance(e, dict):
            if "status" in e:
                status = e["status"]
            if "wall_s" in e:
                wall = e["wall_s"]
            if "config" in e:
                cfg = e["config"]
    return dict(bound=bound, inc=inc, iters=len(iters), cuts=cuts, masters=masters,
                subs=subs, status=status, wall=wall, cfg=cfg)


def main(size=20):
    # SIZE. Everything below was hardcoded to 20 -- the glob, k_paper_lb() and our_bounds().
    # rt_fair_pipeline.py's stage 4 invoked this with no size at all, so the M7 |C| = 30 arm
    # printed a complete, internally consistent |C| = 20 report under an n30 heading. The 12
    # n30 artifacts were fine; only the report was wrong. Caught because a cell logged at
    # 5443 s appeared in the table at 2526 s.
    K = k_paper_lb(size)
    cells = sorted(os.path.basename(f).split("_")[1]
                   for f in glob.glob(os.path.join(ROOT, "runs", f"lbbd_*_n{size}_karademir.jsonl")))
    print(f"=== 1. FIDELITY of our same-machine reproduction of K's LBBD  (|C| = {size}) ===")
    print("    (the same-machine RT claim is only as good as this)")
    print(f"{'cell':7}{'repro bound':>12}{'K paper LB':>12}{'ratio':>8}{'status':>16}"
          f"{'wall_s':>9}{'iters':>7}{'cuts':>6}")
    conv, tl, rows = 0, 0, []
    for c in cells:
        r = repro(c, size)
        kp = K.get(c)
        if not r or kp is None:
            continue
        rat = (r["bound"] / kp) if (r["bound"] and kp) else None
        ok = str(r["status"] or "").startswith("optimal") or str(r["status"] or "") == "converged"
        conv += ok
        tl += not ok
        rows.append((c, r, kp, rat))
        print(f"{c:7}{(r['bound'] or 0):12.2f}{kp:12.2f}"
              f"{(rat or 0):8.2f}{str(r['status'])[:15]:>16}{(r['wall'] or 0):9.1f}"
              f"{r['iters']:7}{r['cuts']:6}")
    if rows:
        rr = [x[3] for x in rows if x[3]]
        print(f"\n  reproduction reaches {min(rr):.2f}-{max(rr):.2f} of K's PUBLISHED LB "
              f"(median {st.median(rr):.2f})")
        print(f"  converged: {conv}/{len(rows)}   TIME-LIMITED: {tl}/{len(rows)}")
        if tl:
            print("  !! A time-limited reproduction is NOT 'K's method on our machine'. Cells above")
            print("     that did not converge are weak comparators and must be labelled as such,")
            print("     or the reproduction re-run to convergence before any same-machine claim.")

    print("\n=== 2. WORK UNITS (hardware- and solver-independent) ===")
    print(f"{'cell':7}{'OUR bound':>11}{'our solves':>12}{'K repro bound':>15}"
          f"{'K masters':>11}{'K subs':>8}{'K cuts':>8}")
    for c, r, kp, rat in rows:
        ob = our_bounds(c, size)
        cold = ob[2] if ob else None
        print(f"{c:7}{(cold or 0):11.2f}{'1 (root)':>12}{(r['bound'] or 0):15.2f}"
              f"{r['masters']:11}{r['subs']:8}{r['cuts']:8}")
    print("\n  'our solves' = 1 cold root solve at k_max, selection-free.")
    print("  This is the comparison that survives a change of machine OR solver.")

    print("\n=== 3. CORE-SECONDS caveat ===")
    print("  Both sides are 4 cores, so core-seconds leaves the K ratio UNCHANGED. It is the")
    print("  right unit only for reconciling our own 8-thread screens. Report it for disclosure,")
    print("  never as the normalisation that makes a timing claim legal.")
    print("  PROVENANCE GAP: these lbbd_* artifacts record engine/cut_arm/wls/tau but NO thread")
    print("  count and NO solver. The 'same machine' claim is currently asserted, not evidenced.")


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--size", type=int, default=20)
    main(_ap.parse_args().size)
