"""FULL-UNION GRID recap: per-family (C/R/RC) and ALL, MEAN and MEDIAN of our OV, LB, opt-gap and
RT, beside K, at K's disclosed granularity. Read-only, single-tenant (run after the batch exits).

OURS -- the frozen full-union variant (d713, no gate):
  OV  = best verifier3-clean incumbent over the banked ng runs (pu_ng*), the keep-better union
  LB  = the ng=10 run's certified dual bound (frozen default-delta + water bound, d678)
  RT  = SUM of wall_s over the cell's banked ng runs = the real compute to PRODUCE that cell's
        union (dual+primal, every ng), beside its % of the 5760 s envelope (budget utilisation).
  opt-gap = (OV - LB)/OV, per cell, then family mean/median.
  n10/20/30 from runs/oracle/tep_uniform_n*.json (consolidated); n50 from the pu_ng* artifacts.

K -- at the granularity K publish (report_fam_vs_k conventions, settled):
  n10/20/30 per-cell (table3): K_OV = min(joint_bk,lbbd_bk); K_LB = joint_bk*(1-joint_gap/100)
            (the joint-model LB, the only LB K publish, d668); per cell -> family mean/median.
  n50 POOL only (table4 1:10): K_OV = min(joint,lbbd) bk; K_LB = joint_bk*(1-gap_imp/100). No
            family split exists, so K is an ALL-row pool value; our side still shows families.

RT vs K, NORMALIZED BY THE 2.5x FACTOR (author-directed) -- with the honesty labels that make it
safe. K publish time ONLY pooled (table4, by size/wls/method), never per cell, so RT-vs-K is a
SIZE-LEVEL line, not per-family. Three figures, each labeled, after dividing K's seconds by 2.5
(K-seconds -> our-seconds):
  * our RT (total wall, our-seconds)  vs  K BUDGET/2.5 = 5760 s -- the same normalized budget we
    tie; where K's gap_imp>0 they ran to the 14400 cap, so 5760 IS their normalized spend.
  * K inc_time/2.5 -- shown but LABELED time-to-INCUMBENT, not total; it understates K's spend by
    up to an order of magnitude and must never be read as "K's runtime".
Our time is total (we stop on budget/convergence); the honest comparison is our-total vs K's
normalized-cap where K did not converge. Per-family we print our RT + utilisation only.

    python analysis/recap_grid_vs_k.py                 # all sizes with a consolidated/union grid
    python analysis/recap_grid_vs_k.py --sizes 10,20,30,50
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
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import k_comparison as K

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])
FAMS = (("C", lambda c: c.startswith("C")),
        ("R", lambda c: c.startswith("R") and not c.startswith("RC")),
        ("RC", lambda c: c.startswith("RC")))
BUDGET = 14400.0 / 2.5    # 5760 our-seconds/cell (d245/d246/d250)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


# Fixed, deterministic order in which ng runs are admitted to the budget-fit union: ng10 is the
# mandatory baseline (it carries the certified LB), then the extra ng. A cell's reported union
# includes runs in THIS order only while cumulative artifact wall_s stays <= BUDGET (d716).
NG_ORDER = (10, 5, 25, 20)


def our_union(size):
    """{cell: (OV, LB, RT_wall, in_ng, excluded)} for the BUDGET-FIT full-union grid.

    OV = min verified OV over the ng runs ADMITTED under the per-cell fairness envelope (5760s),
    admitted in NG_ORDER while cumulative artifact wall_s <= BUDGET (d716); LB = ng10 run's lb;
    RT = cumulative wall_s of the admitted runs; in_ng = the ng admitted; excluded = ng dropped
    as over-budget (banked for ablation, not in the reported OV).
    """
    out = {}
    for c in CELLS:
        byng = {}
        for p in glob.glob(os.path.join(ROOT, "runs", "oracle",
                                        "tep_solve_pu_ng*_%s_n%d.json" % (c, size))):
            m = re.search(r"pu_ng(\d+)_%s_n%d\.json$" % (c, size), os.path.basename(p))
            if not m:
                continue
            d = json.load(io.open(p, encoding="utf-8")); r = d.get("rows", [d])
            byng[int(m.group(1))] = r[0] if isinstance(r, list) else r
        base = byng.get(10)
        if not base or base.get("ov") is None:
            # d744: no primal artifact (ng10 hard-killed, rest skipped) -> report the frozen-dual
            # DUAL-DERIVED incumbent (ov + lb from frzdual2) so the grid is the full 27 cells, not
            # an exception. These cells are flagged in_ng=['derived'].
            fp = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (c, size))
            if os.path.exists(fp):
                dd = json.load(io.open(fp, encoding="utf-8")); dd = dd.get("rows", [dd])
                dd = dd[0] if isinstance(dd, list) else dd
                if dd.get("ov") is not None:
                    out[c] = (float(dd["ov"]), dd.get("lb"), float(dd.get("wall_s") or 0.0),
                              ["derived"], [])
            continue
        # admit ng in fixed order while cumulative wall stays within the envelope
        cum = 0.0; admitted = {}; excluded = []
        for g in NG_ORDER:
            r = byng.get(g)
            if r is None or r.get("ov") is None:
                continue
            w = float(r.get("wall_s") or 0.0)
            if g != 10 and cum + w > BUDGET + 1e-6:
                excluded.append(g); continue          # over-budget extra ng -> ablation only
            cum += w; admitted[g] = r
        # any ng not in NG_ORDER (shouldn't happen) -> treat as excluded for transparency
        excluded += [g for g in byng if g not in NG_ORDER and g not in admitted]
        best = min(admitted.values(), key=lambda r: r["ov"])
        out[c] = (float(best["ov"]), base.get("lb"), cum, sorted(admitted), sorted(excluded))
    return out


def k_percell(size):
    pi = K._kref()["table3"]["per_instance"][str(size)]
    out = {}
    for c, d in pi.items():
        j, l = float(d["joint_bk"]), float(d.get("lbbd_bk") or d["joint_bk"])
        g = float(d.get("joint_gap") or 0.0)
        out[c] = (min(j, l), j * (1.0 - g / 100.0))
    return out


def optgap(ov, lb):
    return 100.0 * (ov - lb) / ov if (ov and lb is not None and ov > 0) else None


def _stat_row(label, ncell, ours_cells, k_cells):
    """ours_cells: list of (OV,LB,RT); k_cells: list of (KOV,KLB) or None."""
    o_ov = [x[0] for x in ours_cells]; o_lb = [x[1] for x in ours_cells]
    o_rt = [x[2] for x in ours_cells]; o_g = [optgap(x[0], x[1]) for x in ours_cells]
    # vs-K deltas, per cell, where K per-cell exists
    dov = dlb = dg = None
    if k_cells is not None:
        dov = [100.0 * (o / k - 1) for o, k in zip(o_ov, [kc[0] for kc in k_cells]) if k]
        dlb = [100.0 * (l / k - 1) for l, k in zip(o_lb, [kc[1] for kc in k_cells]) if (l is not None and k)]
        kg = [optgap(k[0], k[1]) for k in k_cells]
        dg = (o_g, kg)
    util = [100.0 * r / BUDGET for r in o_rt]
    print("  %-4s %2d | OV %8.1f/%8.1f  LB %8.1f/%8.1f  gap %5.1f/%5.1f%%  RT %5.0f/%5.0fs (%.0f%%)"
          % (label, ncell,
             _mean(o_ov) or 0, _med(o_ov) or 0, _mean(o_lb) or 0, _med(o_lb) or 0,
             _mean(o_g) or 0, _med(o_g) or 0, _mean(o_rt) or 0, _med(o_rt) or 0, _mean(util) or 0))
    if dov is not None:
        kg = dg[1]
        kov = _mean([k[0] for k in k_cells]); klb = _mean([k[1] for k in k_cells])
        print("        vsK: K_OV %8.1f  K_LB %8.1f  K_gap %5.1f/%5.1f%%  |  dOV %+5.2f/%+5.2f%%  dLB %+6.1f/%+6.1f%%"
              % (kov or 0, klb or 0, _mean(kg) or 0, _med(kg) or 0,
                 _mean(dov) or 0, _med(dov) or 0, _mean(dlb) or 0, _med(dlb) or 0))


def k_rt_line(size, our_rts):
    """Size-level RT vs K, normalized by 2.5x. K time pooled from table4 (time-to-incumbent)."""
    rows = [r for r in K._kref()["table4"] if r.get("size") == size]
    if not rows:
        print("        RT vs K: K publish no table4 time at n%d" % size); return
    # prefer the 1:10 wls scenario (d666); fall back to whatever exists
    wls = "1:10" if any(r.get("wls") == "1:10" for r in rows) else rows[0].get("wls")
    bym = {r["method"]: r for r in rows if r.get("wls") == wls}
    om, omed = _mean(our_rts), _med(our_rts)
    kbud = 14400.0 / 2.5
    parts = []
    for meth in ("Joint", "LBBD"):
        if meth in bym and bym[meth].get("inc_time") is not None:
            parts.append("%s %.0fs" % (meth, float(bym[meth]["inc_time"]) / 2.5))
    didconv = all(float(bym[m].get("gap_imp") or 0.0) == 0.0 for m in bym) if bym else False
    print("        RT vs K (/2.5, wls %s): our union %.0f/%.0fs  vs  K budget %.0fs%s | "
          "K time-to-INCUMBENT: %s (NOT total%s)"
          % (wls, om or 0, omed or 0, kbud,
             "" if size == 10 else " (=K normalized spend; K ran to cap, gap_imp>0)",
             ", ".join(parts) or "-",
             "; K CONVERGED here" if didconv else ", K still searching at cap"))


def report_size(size):
    ours = our_union(size)
    if not ours:
        print("\nn%d: no pu_ng* artifacts yet -- skipping" % size); return
    kpc = k_percell(size) if size in (10, 20, 30) else None
    print("\nn%d  (%d cells; mean/median shown as M/m)" % (size, len(ours)))
    for fam, pred in FAMS:
        cs = [c for c in CELLS if pred(c) and c in ours]
        if not cs:
            continue
        _stat_row(fam, len(cs), [ours[c] for c in cs],
                  [kpc[c] for c in cs] if kpc else None)
    allc = [c for c in CELLS if c in ours]
    _stat_row("ALL", len(allc), [ours[c] for c in allc],
              [kpc[c] for c in allc] if kpc else None)
    # RT vs K, normalized by 2.5x -- SIZE LEVEL (K time is pooled-only, table4)
    k_rt_line(size, [ours[c][2] for c in allc])
    # budget-fit transparency: cells where an ng run was excluded as over-budget (d716)
    exc = [(c, ours[c][3], ours[c][4]) for c in allc if ours[c][4]]
    if exc:
        print("        budget-fit (5760s): %d cell(s) had ng EXCLUDED as over-budget (ablation-only):"
              % len(exc))
        for c, adm, ex in exc:
            print("          %-6s admitted ng%s | excluded ng%s" % (c, adm, ex))
    if size == 50:
        t4 = {r["method"]: r for r in K._kref()["table4"] if r.get("size") == 50 and r.get("wls") == "1:10"}
        kj, kl = float(t4["Joint"]["bk"]), float(t4["LBBD"]["bk"])
        k_ov = min(kj, kl); k_lb = kj * (1.0 - float(t4["Joint"]["gap_imp"]) / 100.0)
        print("        K POOL (table4 1:10): OV %.1f  LB %.1f  gap %.1f%%  (no per-cell/family at n50)"
              % (k_ov, k_lb, optgap(k_ov, k_lb) or 0))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10,20,30,50")
    a = ap.parse_args(argv[1:])
    print("FULL-UNION GRID vs K  --  per family + ALL, mean/median of OV, LB, opt-gap, RT")
    print("RT = our per-cell wall summed over the union's ng runs; util = %% of 5760s budget.")
    print("RT is NOT compared to K head-to-head (RT_LEG_DESIGN: only budget utilisation is commensurable).")
    for s in [int(x) for x in a.sizes.split(",")]:
        report_size(s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
