"""Coverage map: every interim finding, primal and dual, with variant provenance, against every K exhibit.

Author, 2026-09-26: "Map our interim findings along with their variant provenance primal and dual vs K
at the family level wherever possible or aggregate -- include uncovered K's results."

WHAT THIS IS. One read-only pass over every banked artifact and every exhibit in kref, printed as a
map and written as JSON, so the map regenerates in one command. Nothing here solves anything.

THE COMPARATOR RULE PER SIZE, fixed by the predecessors' publication and not by us:
  n10/n20/n30  Table 3, per instance  -> per-cell best = min(Joint bk, LBBD bk) (d456); their bound =
               Joint bk * (1 - Joint gap/100); aggregated to FAMILY here, with per-cell counts kept.
  n50          Table 4, POOLED over 27 cells by water:street cost ratio; our instances are the 1:10
               pool (d472). No per-cell claim exists at this size. Family split shown but flagged.
  n100         Table 6, per FAMILY (LBBD column); bound derived from their gap (d453).
  Table 4 also pools n10 and n20 by ratio; our n10/n20 defaults are the 1:10 ratio, so those pools
  are comparable to our 27-cell means and are reported as a second view of n10/n20.

PROVENANCE. Primal: which configuration produced the per-cell best (floor / ceil / selchain /
forced / diverse / refine) and the water-stage label (exact at n30/n50, WORK-LIMITED at n100, d481).
At n100 ceil is REJECTED (d470) and is not a candidate. Dual: which bucket width produced the proven
bound (d20 / d10 / d5, best-of-bound = max of proven, d464) or the easy-reduction instrument (n100).
n10 bounds are not reported: every n10 cell is K-proven and a bound on a closed cell says nothing.
n50 has no bound leg: 18/27 default-width LPs proved as by-products of the primal runs and are
listed as such, NOT as a leg.

UNCOVERED. Every K exhibit or column we have not compared is listed at the end with the reason.

    python analysis/tep_coverage_map.py
"""
import glob
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import kref
from k_comparison import k_best_incumbent
from stamp import stamped
from bound_certificate import certified   # d519: readers require the elementary certificate, not the flag

FAM = lambda c: "RC" if c.startswith("RC") else c[0]
CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
CFG_DIRS = ("", "ceil", "selchain", "forced", "diverse", "refine", "alns", "masterip")
BELOW_K_ABS = 0.05   # "below K" = objective at least 0.05 BELOW their best, ABSOLUTE -- the same rule tep_n30_best_of.py uses. A percent rule miscounted RC205 (0.051 below) once.


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def primal(size):
    """Per-cell best over configuration dirs, with provenance. Ceil excluded at n100 (d470)."""
    out = {}
    for c in CELLS:
        cands = []
        for sub in CFG_DIRS:
            if size == 100 and sub == "ceil":
                continue
            p = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (c, size))
            d = load(p)
            if d:
                cands.append((float(d["objVal"]), sub or "floor", int(d["nCars"]), int(d["nVessel"])))
        if cands:
            v, cfg, cars, ves = min(cands)
            out[c] = dict(obj=v, cfg=cfg, cars=cars, vessels=ves, n_cfgs=len(cands))
    return out


def dual(size, ab):
    """Per-cell proven bound with width/instrument provenance. Composed = street LP + water term."""
    out = {}
    for c in CELLS:
        cands = []
        suf = "" if size == 100 else "_n%d" % size
        d = load(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s.json" % (c, suf)))
        if d and certified(d) and d.get("lp_street") is not None and not d.get("primal_rounding"):
            cands.append((float(d["lp_street"]), "d20"))
        for w in (10, 5):
            for s2 in ("_ip", ""):
                dw = load(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s_d%d%s.json" % (c, suf, w, s2)))
                if dw and certified(dw) and dw.get("lp_street") is not None and not dw.get("primal_rounding"):
                    cands.append((float(dw["lp_street"]), "d%d" % w)); break
        water = float(ab[(c, size)]["water"]) if (c, size) in ab else None
        if size == 100:
            best = None
            for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_%s_n100_k*.json" % c)):
                e = load(f)
                if e and certified(e) and (best is None or e["lp_composed"] > best):
                    best = float(e["lp_composed"])
            if best is not None:
                out[c] = dict(lb=best, width="easy-reduction"); continue
        if cands and water is not None:
            lp, w = max(cands)
            out[c] = dict(lb=lp + water, width=w)
    return out


def k_table3(size):
    per = kref.table3(size) if callable(getattr(kref, "table3", None)) else None
    per = json.load(open(kref.PATH, encoding="utf-8"))["table3"]["per_instance"][str(size)]
    out = {}
    for c, p in per.items():
        out[c] = dict(best=min(float(p["joint_bk"]), float(p["lbbd_bk"])),
                      bound=float(p["joint_bk"]) * (1 - float(p["joint_gap"]) / 100.0),
                      proven=float(p["joint_gap"]) == 0.0)
    return out


def fam_rows(size, P, D, K):
    rows = []
    for f in ("C", "R", "RC"):
        cells = [c for c in CELLS if FAM(c) == f]
        hp = [c for c in cells if c in P]; hk = [c for c in cells if c in K]; hd = [c for c in cells if c in D]
        both = [c for c in cells if c in P and c in K]
        r = dict(family=f, n=len(cells), primal_cells=len(hp), bound_cells=len(hd), k_cells=len(hk))
        if both:
            r["our_inc_mean"] = st.mean(P[c]["obj"] for c in both)
            r["k_inc_mean"] = st.mean(K[c]["best"] for c in both)
            r["inc_vs_k_pct"] = 100.0 * (r["our_inc_mean"] / r["k_inc_mean"] - 1)
            r["cells_below_k"] = sum(1 for c in both if P[c]["obj"] < K[c]["best"] - BELOW_K_ABS and not K[c]["proven"])
            r["cells_k_proven"] = sum(1 for c in both if K[c]["proven"])
            r["cfg_counts"] = {k: sum(1 for c in both if P[c]["cfg"] == k) for k in sorted({P[c]["cfg"] for c in both})}
        open_both = [c for c in cells if c in D and c in K and not K[c]["proven"]]
        if open_both:
            r["our_lb_mean"] = st.mean(D[c]["lb"] for c in open_both)
            r["k_lb_mean"] = st.mean(K[c]["bound"] for c in open_both)
            r["lb_vs_k_x"] = r["our_lb_mean"] / r["k_lb_mean"] if r["k_lb_mean"] else None
            r["lb_above_k_cells"] = sum(1 for c in open_both if D[c]["lb"] > K[c]["bound"])
            r["width_counts"] = {k: sum(1 for c in open_both if D[c]["width"] == k) for k in sorted({D[c]["width"] for c in open_both})}
            pb = [c for c in open_both if c in P]
            if pb:
                r["our_bracket_pct"] = st.median(100.0 * (1 - D[c]["lb"] / P[c]["obj"]) for c in pb)
                r["k_bracket_pct"] = st.median(100.0 * (1 - K[c]["bound"] / K[c]["best"]) for c in pb)
        rows.append(r)
    return rows


def main():
    ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"),
                                                               encoding="utf-8"))["records"]}
    KJ = json.load(open(kref.PATH, encoding="utf-8"))
    out = dict(sizes={}, table4=[], uncovered=[])
    W = lambda s: "exact (<1 s, optimal)" if s in (30, 50) else ("WORK-LIMITED (60 units, d481)" if s == 100 else "GREEDY -- never harmonized; STALE vs tonight's levers")

    print("COVERAGE MAP -- interim findings vs K, family level where their publication permits.\n")
    for size in (10, 20, 30):
        P, D, K = primal(size), dual(size, ab), k_table3(size)
        rows = fam_rows(size, P, D, K)
        out["sizes"]["n%d" % size] = dict(comparator="Table 3 per instance -> family means; their best = min(Joint,LBBD)",
                                          water_stage=W(size), rows=rows,
                                          k_proven_cells=sum(1 for c in K if K[c]["proven"]))
        print("== n%d  [Table 3, per instance -> family]  K-proven cells: %d of 27  | water stage: %s"
              % (size, out["sizes"]["n%d" % size]["k_proven_cells"], W(size)))
        print("   %-3s %5s | %9s %9s %8s %6s %-28s | %9s %9s %6s %-22s | %7s %7s"
              % ("fam", "cells", "our inc", "K inc", "vs K", "below", "primal cfg", "our LB", "K LB", "x K", "bound width", "our br", "K br"))
        for r in rows:
            print("   %-3s %2d/%2d | %9s %9s %8s %6s %-28s | %9s %9s %6s %-22s | %7s %7s"
                  % (r["family"], r["primal_cells"], r["n"],
                     ("%.1f" % r["our_inc_mean"]) if "our_inc_mean" in r else "-",
                     ("%.1f" % r["k_inc_mean"]) if "k_inc_mean" in r else "-",
                     ("%+.2f%%" % r["inc_vs_k_pct"]) if "inc_vs_k_pct" in r else "-",
                     ("%d" % r["cells_below_k"]) if "cells_below_k" in r else "-",
                     ",".join("%s:%d" % kv for kv in r.get("cfg_counts", {}).items()),
                     ("%.1f" % r["our_lb_mean"]) if "our_lb_mean" in r else "-",
                     ("%.1f" % r["k_lb_mean"]) if "k_lb_mean" in r else "-",
                     ("%.2f" % r["lb_vs_k_x"]) if r.get("lb_vs_k_x") else "-",
                     ",".join("%s:%d" % kv for kv in r.get("width_counts", {}).items()),
                     ("%.1f%%" % r["our_bracket_pct"]) if "our_bracket_pct" in r else "-",
                     ("%.1f%%" % r["k_bracket_pct"]) if "k_bracket_pct" in r else "-"))
        if size == 10:
            print("   (n10: every cell is K-PROVEN; a bound on a closed cell says nothing and is not reported. 'below' must be 0.)")
        print()

    # n50 -- Table 4 pool 1:10, and Table 4 views of n10/n20 at the same ratio
    P50 = primal(50)
    t4 = {(r["size"], r["wls"], r["method"]): r for r in KJ["table4_full"]}
    for size, P in ((10, primal(10)), (20, primal(20)), (50, P50)):
        k = t4.get((size, "1:10", "LBBD")); kj = t4.get((size, "1:10", "Joint"))
        if not k or not P:
            continue
        m = st.mean(P[c]["obj"] for c in P)
        cfg = {kk: sum(1 for c in P if P[c]["cfg"] == kk) for kk in sorted({P[c]["cfg"] for c in P})}
        fam = {f: st.mean(P[c]["obj"] for c in P if FAM(c) == f) for f in ("C", "R", "RC")}
        rec = dict(size=size, pool="1:10", cells=len(P), our_mean=m, k_lbbd=float(k["bk"]), k_joint=float(kj["bk"]) if kj else None,
                   vs_lbbd_pct=100.0 * (m / float(k["bk"]) - 1), below_pool_mean=sum(1 for c in P if P[c]["obj"] < float(k["bk"])),
                   cfg_counts=cfg, family_means_not_like_for_like=fam, water_stage=W(size),
                   bound_leg=("18/27 default-width LPs proved as BY-PRODUCTS, not a reported leg" if size == 50 else "see Table 3 block"))
        out["table4"].append(rec)
        print("== n%d  [Table 4, POOLED over 27 by water:street ratio; ours = 1:10]  water stage: %s" % (size, W(size)))
        print("   our 27-cell mean %.1f vs LBBD %.1f (%+.2f%%) vs Joint %s | cells individually below the pool mean: %d/27 | cfg %s"
              % (m, float(k["bk"]), rec["vs_lbbd_pct"], ("%.1f" % rec["k_joint"]) if rec["k_joint"] else "-", rec["below_pool_mean"],
                 ",".join("%s:%d" % kv for kv in cfg.items())))
        print("   family means (NOT like-for-like, their pool mixes all three): C %.1f  R %.1f  RC %.1f | bound leg: %s"
              % (fam["C"], fam["R"], fam["RC"], rec["bound_leg"]))
        print()

    # n100 -- Table 6 family
    P100, D100 = primal(100), dual(100, ab)
    klb = kref.derived_lb(100)
    rows = []
    print("== n100 [Table 6, per FAMILY; their incumbent = LBBD column]  water stage: %s | ceil arm now part of the pipeline at n100 (d516/d520: C203 -6.75, R207 +5.38; sweep in progress), best-of per cell" % W(100))
    print("   %-3s %5s | %9s %9s %8s | %9s %9s %6s | %7s %7s | %s"
          % ("fam", "cells", "our inc", "K inc", "vs K", "our LB", "K LB", "x K", "our br", "K br", "bound instrument"))
    for f in ("C", "R", "RC"):
        cells = [c for c in CELLS if FAM(c) == f]
        t = kref.table6(f); kinc = float(t["lbbd"]["zIP"]); kl = float(klb[f])
        hp = [c for c in cells if c in P100]; hd = [c for c in cells if c in D100]
        oi = st.mean(P100[c]["obj"] for c in hp) if hp else None; ob = st.mean(D100[c]["lb"] for c in hd) if hd else None
        r = dict(family=f, n=len(cells), primal_cells=len(hp), bound_cells=len(hd), our_inc_mean=oi, k_inc_mean=kinc,
                 inc_vs_k_pct=(100.0 * (oi / kinc - 1)) if oi else None, our_lb_mean=ob, k_lb_mean=kl,
                 lb_vs_k_x=(ob / kl) if ob else None, our_bracket_pct=(100.0 * (1 - ob / oi)) if (oi and ob) else None,
                 k_bracket_pct=100.0 * (1 - kl / kinc), instrument="easy-reduction (d448)")
        rows.append(r)
        print("   %-3s %2d/%2d | %9.1f %9.1f %+7.2f%% | %9.1f %9.1f %5.2fx | %6.1f%% %6.1f%% | %s"
              % (f, len(hp), len(cells), oi, kinc, r["inc_vs_k_pct"], ob, kl, r["lb_vs_k_x"], r["our_bracket_pct"], r["k_bracket_pct"], r["instrument"]))
    out["sizes"]["n100"] = dict(comparator="Table 6 per family (LBBD)", water_stage=W(100), rows=rows, primal_cfg="floor and ceil per cell (ceil arm added d516; sweep in progress)")
    print()

    # UNCOVERED K results
    unc = out["uncovered"]
    for (size, wls) in sorted({(r["size"], r["wls"]) for r in KJ["table4_full"]}):
        if wls != "1:10":
            unc.append(dict(exhibit="Table 4", what="n%d pool %s (Joint+LBBD, with travel/fleet split)" % (size, wls),
                            why="our instances carry the 1:10 cost ratio only; the other ratios are a separate study, not started (d472)"))
    unc.append(dict(exhibit="Table 4 / Table 3 / Table 6", what="inc_time (time to incumbent) at every size",
                    why="settled: we do not race K on speed -- our time-to-best is budget-bounded and theirs is not (CLAUDE.md s.3)"))
    unc.append(dict(exhibit="Table 4", what="n10/n20 component splits (travel street/water, fleet, used satellites) at 1:10",
                    why="comparable to our artifacts but not yet computed; done at n50 (d472) and n100 (d458)"))
    unc.append(dict(exhibit="bound leg", what="n50 lower bound", why="no leg run; 18/27 default-width LPs proved as by-products of the primal; 9 R-cells elem_exhausted"))
    unc.append(dict(exhibit="bound leg", what="n10 lower bound vs Table 3", why="every n10 cell is K-proven; a bound on a closed cell is not a claim"))
    unc.append(dict(exhibit="Table 3", what="n20 bound on the 7 K-proven cells; n30 bound on C201", why="closed cells; only open cells are compared"))
    for k in ("fig4", "fig5"):
        if k in KJ["text_facts"]:
            unc.append(dict(exhibit=k, what=str(KJ["text_facts"][k])[:120], why="a figure, not a table; not reproduced"))
    unc.append(dict(exhibit="n10/n20 primal", what="artifacts are floor-only with GREEDY water: none of ceil (P5 adopted it there, but only on the old K-retime route), exact water, select+chain, forced or diverse has been applied",
                    why="stale by every lever built 2026-09-26; refresh is cheap (exact water: seconds; ceil route: minutes) but is a solver job, d415-gated"))
    unc.append(dict(exhibit="n20 dual", what="finer-bucket bound (d5) on the 20 open cells", why="not run; the n30 grid lifted proven bounds +1.4 to +7.8 percent, so the same lever is available at n20"))
    unc.append(dict(exhibit="n30 dual", what="C207 and R208 at d=5 (unproven; keep d20)", why="C207 stalled, R208 hit the 900 s wall; solo re-run with longer stall/wall proposed, not run"))
    unc.append(dict(exhibit="n100 primal", what="in-cycle exact water; refinement stage", why="d481: work-limited water at n100; refine out of scope there per PREREG; neither run"))
    print("== UNCOVERED K RESULTS (and our own gaps against them)")
    for u in unc:
        print("   [%-24s] %-72s -- %s" % (u["exhibit"], u["what"], u["why"]))
    p = os.path.join(ROOT, "runs", "oracle", "tep_coverage_map.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
