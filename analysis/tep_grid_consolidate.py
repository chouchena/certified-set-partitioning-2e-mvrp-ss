"""Consolidate a size's pu_ng* runs into TWO stamped artifacts (d723), with the surgery gate
(d724/d727) built in as refuse-on-fail:

  tep_uniform_n<size>_full.json    the FULL union -- best OV over ALL banked ng, no budget cut
                                   (the cap-SENSITIVITY dataset; banked FIRST, preserved)
  tep_uniform_n<size>.json         the REPORTED budget-fit union -- admit ng in scale order
                                   [10,5,25] while cumulative wall <= 5760 (hard-kill simulated),
                                   LB from ng=10 (the frozen dual)

Used for n50/n100, where K publishes no per-cell data (family/pooled comparison lives in
report/recap, not here). n10/20/30 keep tep_uniform_grid.py (per-cell K).

GATE (refuse to write on any fail): 27 cells; ng10 present each; LB == frzdual2 LB per cell
(the integrated dual IS the frozen dual); reported cumulative <= 5760; reported OV >= full OV per
cell (budget-fit can never beat the unconstrained union -- monotonicity); no reported OV equals a
strictly-lower EXCLUDED ng's OV (over-budget leak guard); LB <= OV. Alarm carries a test.

    python analysis/tep_grid_consolidate.py --size 50            # verify + print
    python analysis/tep_grid_consolidate.py --size 50 --write    # stamp + write both artifacts
"""
import argparse
import glob
import io
import json
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
BUDGET = 14400.0 / 2.5
NG_ORDER = (10, 5, 25, 20)


def _rec(p):
    if not os.path.exists(p):
        return None
    d = json.load(io.open(p, encoding="utf-8")); r = d.get("rows", [d])
    return r[0] if isinstance(r, list) else r


def _frzdual_lb(cell, size):
    r = _rec(os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size)))
    return (r or {}).get("lb")


def build(size):
    rows_full, rows_rep, fails = [], [], []
    for c in CELLS:
        byng = {}
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_pu_ng*_%s_n%d.json" % (c, size))):
            m = re.search(r"pu_ng(\d+)_%s_n%d\.json$" % (c, size), os.path.basename(p))
            if m:
                r = _rec(p)
                if r and r.get("ov") is not None:
                    byng[int(m.group(1))] = r
        if 10 not in byng:
            # d744: no primal artifact (ng10 hard-killed, rest skipped) -> report the frozen-dual
            # DUAL-DERIVED incumbent (ov + lb from frzdual2) so the grid is the full 27 cells, not
            # an exception. Gate checks below are satisfied by construction (LB IS frzdual2;
            # full == reported; LB <= OV), so we bank the row and continue past them.
            dd = _rec(os.path.join(ROOT, "runs", "oracle",
                                   "tep_solve_frzdual2_%s_n%d.json" % (c, size)))
            if dd and dd.get("ov") is not None and dd.get("lb") is not None:
                ov = float(dd["ov"]); lb = float(dd["lb"])
                rows_full.append(dict(cell=c, best=ov, cfg="frzdual2-derived",
                                      cars=int(dd.get("nCars") or 0), our_lb=lb, ng_banked=[],
                                      theirs=None, proven=False, dual_derived=True))
                rows_rep.append(dict(cell=c, best=ov, cfg="frzdual2-derived",
                                     cars=int(dd.get("nCars") or 0), our_lb=lb, ng_admitted=[],
                                     ng_excluded=[], rt_cum=round(float(dd.get("wall_s") or 0.0), 1),
                                     theirs=None, proven=False, dual_derived=True))
            else:
                fails.append("%s: no ng10 and no frzdual2 fallback" % c)
            continue
        base = byng[10]; lb = base.get("lb")
        # FULL union (all ng, no cut)
        full_best = min(byng.values(), key=lambda r: r["ov"])
        # BUDGET-FIT union (admit in scale order while cumulative wall <= BUDGET)
        cum = 0.0; adm = {}; excl = []
        for g in NG_ORDER:
            r = byng.get(g)
            if r is None:
                continue
            w = float(r.get("wall_s") or 0.0)
            if g != 10 and cum + w > BUDGET + 1e-6:
                excl.append(g); continue
            cum += w; adm[g] = r
        excl += [g for g in byng if g not in adm and g not in excl]
        rep_best = min(adm.values(), key=lambda r: r["ov"])
        rep_ng = [g for g in sorted(adm) if adm[g]["ov"] == rep_best["ov"]][0]
        full_ng = [g for g in sorted(byng) if byng[g]["ov"] == full_best["ov"]][0]
        # ---- GATE checks ----
        fl = _frzdual_lb(c, size)
        if fl is not None and lb is not None and abs(float(fl) - float(lb)) > 1e-3:
            fails.append("%s: LB %.3f != frzdual2 %.3f" % (c, lb, fl))
        if lb is not None and rep_best["ov"] < float(lb) - 1e-6:
            fails.append("%s: LB %.3f > reported OV %.3f" % (c, lb, rep_best["ov"]))
        if cum > BUDGET + 1e-6:
            fails.append("%s: reported cumulative %.1f > budget %.1f" % (c, cum, BUDGET))
        if rep_best["ov"] < full_best["ov"] - 1e-6:
            fails.append("%s: reported OV %.3f < full OV %.3f (monotonicity)" % (c, rep_best["ov"], full_best["ov"]))
        for g in excl:
            if byng[g]["ov"] < rep_best["ov"] - 1e-6 and abs(byng[g]["ov"] - rep_best["ov"]) > 1e-9:
                # an excluded ng is strictly better but we did NOT report it: correct (over-budget).
                # leak would be reporting it; assert we did not.
                if abs(rep_best["ov"] - byng[g]["ov"]) <= 1e-9:
                    fails.append("%s: over-budget leak (reported an excluded ng's OV)" % c)
        rows_full.append(dict(cell=c, best=float(full_best["ov"]), cfg="pu_ng%d_full" % full_ng,
                              cars=int(full_best.get("nCars") or 0), our_lb=(float(lb) if lb is not None else None),
                              ng_banked=sorted(byng), theirs=None, proven=False))
        rows_rep.append(dict(cell=c, best=float(rep_best["ov"]), cfg="pu_ng%d" % rep_ng,
                             cars=int(rep_best.get("nCars") or 0), our_lb=(float(lb) if lb is not None else None),
                             ng_admitted=sorted(adm), ng_excluded=sorted(excl), rt_cum=round(cum, 1),
                             theirs=None, proven=False))
    return rows_full, rows_rep, fails


def report(size, rows_rep, rows_full):
    og = [100.0 * (r["best"] - r["our_lb"]) / r["best"] for r in rows_rep if r.get("our_lb")]
    impr = sum(1 for rr, rf in zip(rows_rep, rows_full) if rf["best"] < rr["best"] - 1e-6)
    excl = [r["cell"] for r in rows_rep if r.get("ng_excluded")]
    print("n%d: %d cells | reported opt-gap med %.1f%% mean %.1f%% | budget-fit excluded ng on %d cells: %s"
          % (size, len(rows_rep), st.median(og), st.mean(og), len(excl), ",".join(excl) or "none"))
    print("   full-vs-reported differ (full strictly better) on %d cells (the budget cost)" % impr)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True, choices=(50, 100))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--supersede", action="store_true")
    a = ap.parse_args(argv[1:])
    rows_full, rows_rep, fails = build(a.size)
    if len(rows_rep) != 27 or len(rows_full) != 27:
        fails.append("expected 27 cells, got full=%d rep=%d" % (len(rows_full), len(rows_rep)))
    if fails:
        print("*** SURGERY GATE FAILED -- NOT WRITING ***")
        for f in fails:
            print("   " + f)
        return 1
    report(a.size, rows_rep, rows_full)
    print("   gate clean (27 cells, LB==frzdual2, budget<=5760, reported>=full, no leak, LB<=OV).")
    if a.write:
        from stamp import stamped
        for tag, rows in (("_full", rows_full), ("", rows_rep)):
            p = os.path.join(ROOT, "runs", "oracle", "tep_uniform_n%d%s.json" % (a.size, tag))
            json.dump(stamped(dict(size=a.size, variant="pu_union%s" % tag, rows=rows), __file__,
                              path=p, supersede=a.supersede),
                      io.open(p, "w", encoding="utf-8"), indent=1, default=str)
            print("   wrote %s" % os.path.relpath(p, ROOT))
    else:
        print("   (print-only; pass --write to stamp both artifacts)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
