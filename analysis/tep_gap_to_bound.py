"""Gap relative to the bound, (OV - LB) / LB, per cell and per size, for us and for K, each side with its own OV and LB.

Author formula (2026-09-27): (LB - OV) / LB; printed as the positive percentage (OV - LB) / LB. K side: their best
incumbent and their published (or, at n100, derived) bound; K-PROVEN cells are 0 by construction. Our side: the best
verified primal over the production dirs and the certified TEP bound (best proven width), where one exists. The size
means are given twice: over the cells where BOTH sides have a bound (like-for-like) and over all cells each side has.
At n100 K publish family means only, so their per-cell value does not exist; the family-mean form is printed instead.

    python analysis/tep_gap_to_bound.py
"""
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
from bound_certificate import certified

CELLS = ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)] + ["RC%d" % i for i in range(201, 209)]


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def gap(ov, lb):
    return 100.0 * (ov / lb - 1.0) if (ov is not None and lb) else None


def fmt(v):
    return ("%.1f%%" % v) if v is not None else "-"


def main():
    out = {}
    kts = load(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")) or {}
    for n in (10, 20, 30):
        rows = load(os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % n))["rows"]
        # author (2026-09-27 00:58): where no TEP bound exists, use the OLD bound instrument (k_targets_small "ours": the
        # frontier of the earlier descent legs). Valid bounds, but NOT the method of this paper; the source is printed per cell.
        oldlb = {r["cell"]: r.get("ours") for r in kts.get("n%d" % n, {}).get("rows", [])}
        tab = []
        print("\nn%d, %d cells: (OV - LB) / LB per cell, ours and K" % (n, len(rows)))
        print("%-6s %-6s | %9s %9s %3s %8s | %9s %9s %8s" % ("cell", "status", "our OV", "our LB", "src", "ours", "K OV", "K LB", "K"))
        for r in sorted(rows, key=lambda r: r["cell"]):
            lb, src = (r["our_lb"], "tep") if r["our_lb"] else ((oldlb.get(r["cell"]), "old") if oldlb.get(r["cell"]) else (None, "-"))
            og = gap(r["best"], lb); kg = 0.0 if r["proven"] else gap(r["theirs"], r["their_lb"])
            tab.append(dict(cell=r["cell"], proven=r["proven"], our_ov=r["best"], our_lb=lb, lb_source=src, ours=og, k_ov=r["theirs"], k_lb=r["their_lb"], k=kg))
            print("%-6s %-6s | %9.1f %9s %3s %8s | %9.1f %9.1f %8s" % (r["cell"], "PROVEN" if r["proven"] else "open", r["best"], ("%.1f" % lb) if lb else "-", src, fmt(og), r["theirs"], r["their_lb"], fmt(kg)))
        both = [t for t in tab if t["ours"] is not None]
        opn = [t for t in both if not t["proven"]]
        s = dict(cells=len(tab), ours_cells=len(both), tep_cells=sum(1 for t in both if t["lb_source"] == "tep"), old_cells=sum(1 for t in both if t["lb_source"] == "old"),
                 mean_ours_all=st.mean(t["ours"] for t in both) if both else None,
                 mean_k_all=st.mean(t["k"] for t in tab),
                 mean_ours_same_cells=st.mean(t["ours"] for t in both) if both else None,
                 mean_k_same_cells=st.mean(t["k"] for t in both) if both else None,
                 mean_ours_open=st.mean(t["ours"] for t in opn) if opn else None, mean_k_open=st.mean(t["k"] for t in opn) if opn else None,
                 open_cells_both=len(opn), ours_smaller_open=sum(1 for t in opn if t["ours"] < t["k"]))
        print("  MEAN, same cells (%d with our bound: %d TEP, %d old instrument): ours %s | K %s" % (s["ours_cells"], s["tep_cells"], s["old_cells"], fmt(s["mean_ours_same_cells"]), fmt(s["mean_k_same_cells"])))
        print("  MEAN, K over all %d cells (proven = 0): %s" % (len(tab), fmt(s["mean_k_all"])))
        if opn:
            print("  MEAN, OPEN cells with our bound (%d): ours %s | K %s | ours smaller on %d" % (len(opn), fmt(s["mean_ours_open"]), fmt(s["mean_k_open"]), s["ours_smaller_open"]))
        out["n%d" % n] = dict(rows=tab, summary=s)
    # n100: our per-cell certified bound and primal; K family means only
    fam = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
    best_lb = {}
    import glob
    for f in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_*_n100_k*.json")):
        d = load(f)
        if d and certified(d): best_lb[d["cell"]] = max(best_lb.get(d["cell"], -1e9), float(d["lp_composed"]))
    print("\nn100, 27 cells: OUR per-cell (OV - LB) / LB (certified subset bound); K publish family means only")
    tab = []
    for c in CELLS:
        ov = None
        for sub in ("", "ceil", "selchain", "forced", "refine", "alns", "masterip"):
            a = load(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n100.json" % c))
            if a: ov = float(a["objVal"]) if ov is None else min(ov, float(a["objVal"]))
        g = gap(ov, best_lb.get(c)); tab.append(dict(cell=c, our_ov=ov, our_lb=best_lb.get(c), ours=g))
        print("  %-6s our OV %9.1f  our LB %9.1f  ours %s" % (c, ov or 0, best_lb.get(c) or 0, fmt(g)))
    have = [t for t in tab if t["ours"] is not None]
    print("  MEAN over %d cells: ours %s" % (len(have), fmt(st.mean(t["ours"] for t in have))))
    famrows = []
    for r in fam["rows"]:
        og = gap(r["our_inc"], r["our_lb"]); kg = gap(r["their_inc"], r["their_lb"])
        famrows.append(dict(family=r["family"], n=r["n"], ours_of_means=og, k_of_means=kg))
        print("  family %-2s (n=%2d) from MEANS: ours %s | K %s   (K bound derived from the joint gap, K incumbent = LBBD)" % (r["family"], r["n"], fmt(og), fmt(kg)))
    # author (2026-09-27 01:05): the size-level aggregate at n100 is the mean of family means weighted by cell count (8 / 11 / 8),
    # for both sides, since K publish family means only. Both denominators are given.
    W = sum(r["n"] for r in fam["rows"])
    agg = dict(
        ours_lb_rel=sum(r["n"] * gap(r["our_inc"], r["our_lb"]) for r in fam["rows"]) / W,
        k_lb_rel=sum(r["n"] * gap(r["their_inc"], r["their_lb"]) for r in fam["rows"]) / W,
        ours_ov_rel=sum(r["n"] * r["our_gap"] for r in fam["rows"]) / W,
        k_ov_rel=sum(r["n"] * r["their_gap"] for r in fam["rows"]) / W,
        ours_lb_rel_percell_mean=st.mean(t["ours"] for t in have) if have else None,
        ours_ov_rel_percell_mean=st.mean(100.0 * (1 - t["our_lb"] / t["our_ov"]) for t in have) if have else None, cells=W)
    print("  n100 AGGREGATE, family means weighted by cells (%d): (OV-LB)/LB ours %.1f%% vs K %.1f%% | (OV-LB)/OV ours %.1f%% vs K %.1f%% | our per-cell means: %.1f%% / %.1f%%"
          % (W, agg["ours_lb_rel"], agg["k_lb_rel"], agg["ours_ov_rel"], agg["k_ov_rel"], agg["ours_lb_rel_percell_mean"], agg["ours_ov_rel_percell_mean"]))
    out["n100"] = dict(rows=tab, family=famrows, aggregate=agg, mean_ours_cells=st.mean(t["ours"] for t in have) if have else None)
    p = os.path.join(ROOT, "runs", "oracle", "tep_gap_to_bound.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
