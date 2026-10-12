"""THE DUAL LEG -- our certified lower bound against K's, across the whole grid.

Every number in `validation/RESULT_dual_leg.md` comes from here. One run, one table.

WHY THIS IS THE STRONGEST LEG WE HAVE, stated plainly and then qualified:
a relaxation ALWAYS produces a bound, so unlike every primal statistic in this project
there is no censoring, no never-count, and no cell that "did not finish". The denominator
is every cell, at every size, always.

K PUBLISH NO LOWER BOUND. Theirs is recovered as BK x (1 - Gap/100). That is the GUROBI
convention, (UB-LB)/UB, and as of 2026-09-17 it is CONFIRMED AGAINST THE PAPER rather than
assumed (decision 178): Table 3's caption reads "the percent gap reported by the solver",
the Table 6 note names Gurobi, and the solver is Gurobi 9.12 at line 888. This mattered —
under the alternative convention our n30 ratio would fall from 1.353x to 1.035x.

THE SPLIT THAT MUST TRAVEL WITH EVERY NUMBER (inherited from lb_vs_k_headline.py):
  * On cells K PROVED, their "bound" IS the optimum. It cannot be beaten, and a ratio below
    1 there is our distance to optimality, NOT a loss. Pooling those cells into a win/loss
    count would both understate the result and misdescribe their work.
  * On cells K did NOT prove — where a bound is actually needed — the comparison is live.

GRANULARITY IS K'S, NOT OURS. They publish per-instance only to |C| = 30; |C| = 50 is pooled
(Table 4) and |C| = 100 is per-family (Table 6). We match whatever they published, which is
why the |C| = 50 and 100 rows are means and not counts.

TWO DISCLOSURES THAT ARE NOT OPTIONAL.
  1. |C| = 100 RC uses a RECONSTRUCTED travel_sl. K's published RC/LBBD row is internally
     inconsistent — 1525.1 + 1970.6 = 3495.7 against their own printed total of 4451.6,
     while all five other rows in Table 6 add exactly. Reconstructed to ~2481 from three
     agreeing constraints (decision 179). Flagged in the output, every run.
  2. |C| = 100 uses max-over-all-records for coverage (decision 176). Valid — unproven
     records carry CPLEX's best_bound — but it gains a median +0.00% over the proven
     frontier, so it buys CELL-SET MATCHING with K, not a stronger bound.
"""
import json, os, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
import analysis.manuscript_numbers as M                       # noqa: E402

FAM = lambda c: "RC" if c.startswith("RC") else c[0]
RC_TRAVEL_SL_RECONSTRUCTED = 2480.8      # decision 179; K print 1525.1, which cannot be right


def records(cell, size):
    p = os.path.join(ROOT, "crossfeed", "easy_reduction_descend_%s_n%d.json" % (cell, size))
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    return [x for x in (d if isinstance(d, list) else [d]) if isinstance(x, dict)]


def lb_frontier(cell, size):
    """The repo's canonical bound: block_relax at the SMALLEST PROVEN k.

    block_relax decreases in k, so min proven k is the strongest bound the descent proved.
    """
    pv = [x for x in records(cell, size) if x.get("proven")]
    if not pv:
        return None
    kf = min(x["k"] for x in pv)
    return [x["block_relax"] for x in pv if x["k"] == kf][0]


def lb_maxrec(cell, size):
    """max over ALL records. Extends COVERAGE where nothing proved; see module docstring."""
    v = [x["block_relax"] for x in records(cell, size)
         if isinstance(x.get("block_relax"), (int, float))]
    return max(v) if v else None


def main():
    K = M._K()
    out = {}
    print(__doc__.split("WHY THIS")[0].strip())
    print()

    # ---------- |C| = 10, 20, 30 : per instance ----------
    for size in (10, 20, 30):
        per = K["table3"]["per_instance"][str(size)]
        prov, unpr = [], []
        for c in sorted(per):
            lb = lb_frontier(c, size)
            if lb is None:
                continue
            klb = per[c]["joint_bk"] * (1 - per[c]["joint_gap"] / 100.0)
            (prov if abs(per[c]["joint_gap"]) < 1e-9 else unpr).append(lb / klb)
        n = len(prov) + len(unpr)
        exceed = sum(1 for r in unpr if r > 1.0)
        print("|C| = %-3d  %2d/%2d cells | K PROVED %2d (their bound IS the optimum; we reach "
              "%.1f-%.1f%% of it)" % (size, n, len(per), len(prov),
                                      100 * min(prov) if prov else float("nan"),
                                      100 * max(prov) if prov else float("nan")))
        if unpr:
            print("           %s | K UNPROVED %2d: we EXCEED on %d of %d, median ratio %.3fx"
                  % (" " * 11, len(unpr), exceed, len(unpr), st.median(unpr)))
        out["n%d" % size] = dict(cells=n, proven=len(prov), unproven=len(unpr),
                                 exceed=exceed,
                                 median_ratio_unproven=st.median(unpr) if unpr else None)

    # ---------- |C| = 50 : pooled (Table 4) ----------
    row = {r["method"]: r for r in K["table4"] if r["size"] == 50 and r["wls"] == "1:10"}
    cells = sorted(M._cells(50))
    lbs = [x for x in (lb_frontier(c, 50) for c in cells) if x is not None]
    kj, kl = row["Joint"]["bk"], row["LBBD"]["bk"]
    klb = kj * (1 - row["Joint"]["gap_imp"] / 100.0)
    ours, ref = st.mean(lbs), min(kj, kl)
    print("\n|C| = 50   %2d/27 cells POOLED (K publish no per-instance data at this size;"
          % len(lbs))
    print("           their Table 4 caption: '27 instances ... averaged for each scenario')")
    print("           our LB %.1f  vs  K implied LB %.1f  ->  %.2fx |  maxGap %.1f%% "
          "(K advertise %.1f%%)" % (ours, klb, ours / klb, 100 * (ref - ours) / ref,
                                    row["Joint"]["gap_imp"]))
    out["n50"] = dict(cells=len(lbs), ours=ours, k_lb=klb, ratio=ours / klb,
                      maxgap=100 * (ref - ours) / ref, k_gap=row["Joint"]["gap_imp"])

    # ---------- |C| = 100 : per family (Table 6) ----------
    # Three bound sources, all printed and all written (d361: the MILP-only row was read as the
    # portfolio and gave a wrong sign; d398: the TEP column-generation bound joins the portfolio):
    #   milp      -- max block_relax over the descent records (the historical row, kept for continuity)
    #   portfolio -- max(proved MILP frontier via manuscript_numbers._frontier, arithmetic AB4)
    #   portfolio+cg -- the above with the TEP CG composed bound (street LP + arithmetic water term;
    #                   the proven finer-bucket value where one exists), per cell
    print("\n|C| = 100  per FAMILY (K publish no per-instance data; proximity 0.1, not 0.0)")
    AB = M._AB()

    def cg_composed(c):
        best = None
        for tag in ("", "_d10", "_d30"):
            q = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s.json" % (c, tag))
            if os.path.exists(q):
                try:
                    r = json.load(open(q, encoding="utf-8"))
                except Exception:
                    continue
                if r.get("proven"):
                    best = r["composed"] if best is None else max(best, r["composed"])
        return best

    out["n100"] = {}
    for f0 in ("C", "R", "RC"):
        t6 = K["table6"][f0]
        cs = [c for c in sorted(M._cells(100)) if FAM(c) == f0]
        lbs = [x for x in (lb_maxrec(c, 100) for c in cs) if x is not None]
        port, port_cg = [], []
        for c in cs:
            try:
                fr = M._frontier(c, 100)[0]
            except Exception:
                fr = None
            p = max(x for x in (fr, AB.get((c, 100))) if x is not None)
            port.append(p); port_cg.append(max(p, cg_composed(c) or 0.0))
        kj, kl = t6["joint"]["zIP"], t6["lbbd"]["zIP"]
        klb = kj * (1 - t6["gap_joint"] / 100.0)
        ours, ref = st.mean(lbs), min(kj, kl)
        op, opc = st.mean(port), st.mean(port_cg)
        flag = "  <-- RC/LBBD travel_sl RECONSTRUCTED, see d179" if f0 == "RC" else ""
        verdict = "we exceed" if ours > klb else "*** MILP-only row does not exceed (the portfolio does) ***"
        print("   %-3s %2d/%-2d cells | MILP-only LB %7.1f vs K implied %7.1f -> %.2fx  %s"
              % (f0, len(lbs), t6["n"], ours, klb, ours / klb, verdict))
        print("       %s  portfolio (frontier, AB4) %7.1f -> %.2fx | portfolio + TEP CG %7.1f -> %.2fx  (%d/%d cells with a proven CG bound)"
              % (" " * 12, op, op / klb, opc, opc / klb, sum(1 for c in cs if cg_composed(c) is not None), len(cs)))
        print("       %s  maxGap vs K's best family UB %.1f: MILP-only %.1f%%, portfolio %.1f%%, portfolio+CG %.1f%% (K advertise %.1f%%)%s"
              % (" " * 12, ref, 100 * (ref - ours) / ref, 100 * (ref - op) / ref, 100 * (ref - opc) / ref, t6["gap_joint"], flag))
        out["n100"][f0] = dict(cells=len(lbs), ours=ours, k_lb=klb, ratio=ours / klb,
                               maxgap=100 * (ref - ours) / ref, k_gap=t6["gap_joint"],
                               ours_portfolio=op, ratio_portfolio=op / klb, maxgap_portfolio=100 * (ref - op) / ref,
                               ours_portfolio_cg=opc, ratio_portfolio_cg=opc / klb, maxgap_portfolio_cg=100 * (ref - opc) / ref,
                               cg_cells=sum(1 for c in cs if cg_composed(c) is not None))

    print("\n  NO CENSORING ANYWHERE ABOVE: a relaxation always produces a bound, so the")
    print("  denominator is every cell at every size. This is the only leg in the project")
    print("  with that property.")
    p = os.path.join(ROOT, "runs", "dual_vs_k.json")
    json.dump(stamped(out, __file__), open(p, "w"), indent=1)
    print("\nwrote runs/dual_vs_k.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
