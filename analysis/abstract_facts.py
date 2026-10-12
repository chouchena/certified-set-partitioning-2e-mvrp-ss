"""EVERY QUANTITY THE ABSTRACT ASSERTS, recomputed from the artifacts and audited against K's own tables (d556).

WHY THIS EXISTS. The abstract is the one paragraph a referee reads adversarially, and the review of
2026-09-27 caught four statements in draft 1 that the artifacts do not support as written:

  1. "proved optimality on N of their instances" -- the count must come from their per-instance gap
     columns (a published gap of exactly 0), not from a remembered number. It is 35 of 135: all 27 at
     |C| = 10, 7 at |C| = 20, 1 at |C| = 30, and none at 50 or 100 where they publish aggregates only.
  2. "gaps run from 26 to 77 per cent" -- those are AVERAGES BY SIZE AND FAMILY. Their per-instance
     gaps run from 0 (the 35 proven cells) to 71, and the smallest nonzero one is 2.
  3. "we attain it to a mean 0.38 per cent over 27 instances" -- 0.377 is the |C| = 10 figure alone.
     Over all 35 cells they prove it is 0.350, of which 20 reproduce the optimum to the precision they
     publish it in (one decimal) and 29 sit within one per cent of it.
  4. "median gap falls from 46.4 to 17.2" -- ours is a median over the cells where both sides have a
     value, and THEIR side is recomputed, not quoted: their published gap is against their combined
     model's own incumbent, while we divide the implied bound by the BETTER of their two published
     incumbents. That is conservative -- it shrinks their interval, never ours -- and the difference
     is large enough to matter (46.4 here against the 51.0 median of their published column at n30).

The script prints the audit, writes runs/oracle/abstract_facts.json, and is the generating code behind
the `tep-abstract` macro block in analysis/manuscript_numbers.py. Nothing in the abstract may be typed
by hand; if a sentence needs a number that is not printed here, add it here first.

    python analysis/abstract_facts.py

Exit code 1 if any internal consistency check fails (counts that must sum to 135, a proven-cell count
that must match the per-instance tables, a family table that must cover 27 cells).
"""
import io
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

SIZES = (10, 20, 30, 50, 100)
# K publish objective values to ONE DECIMAL, so a match is |ours - theirs| <= 0.05, not equality: our
# exact 365.489 on C201 at |C| = 10 IS their 365.5, and thirteen more cells sit inside that half-digit.
# Read as strict inequality they look like fourteen solutions below a proven optimum, which is how the
# first run of this script reported them -- the same class of error as comparing a relaxation to a
# feasible value, in the opposite direction. The primal guard in tep_n30_best_of.py has always used 0.05.
K_PRECISION = 0.05
PER_INSTANCE = (10, 20, 30)


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def kref():
    return load(os.path.join(ROOT, "data", "karademir2025", "k_reference.json"))


def their_side(K):
    """What K publish: proofs, per-instance gap range, and the averages by size and family."""
    t3 = K["table3"]["per_instance"]
    proven, cells, per_instance_gaps = {}, {}, []
    for n in PER_INSTANCE:
        rows = t3[str(n)]
        cells[n] = len(rows)
        proven[n] = sum(1 for r in rows.values() if r.get("joint_gap") == 0)
        per_instance_gaps += [float(r["joint_gap"]) for r in rows.values() if r.get("joint_gap") is not None]
    # 50 and 100 are published as pool and family aggregates: 27 instances each, no per-instance proof
    cells[50] = cells[100] = 27
    proven[50] = proven[100] = 0
    nz = [g for g in per_instance_gaps if g > 0]
    avgs = {}
    for n in PER_INSTANCE:
        avgs["n%d" % n] = float(K["table3"]["summary"][str(n)]["joint"]["gap"])
    for row in K["table4"]:
        if row.get("size") == 50 and row.get("wls") == "1:10" and row.get("method") == "Joint":
            avgs["n50 (1:10)"] = float(row["gap_imp"])
    for fam, r in K["table6"].items():
        avgs["n100 %s" % fam] = float(r["gap_joint"])
    return dict(cells_total=sum(cells.values()), proven_total=sum(proven.values()),
                proven_by_size={str(k): v for k, v in proven.items()},
                cells_by_size={str(k): v for k, v in cells.items()},
                per_instance_gap_min=min(per_instance_gaps), per_instance_gap_max=max(per_instance_gaps),
                per_instance_gap_min_nonzero=min(nz), per_instance_cells=len(per_instance_gaps),
                published_averages=avgs, published_average_min=min(avgs.values()), published_average_max=max(avgs.values()))


def bestof(n):
    d = load(os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % n))
    return d["rows"] if d else []


def attainment():
    """Where K PROVE an optimum, how far above it our best verified incumbent sits. Attainment, never pooled
    with the open cells (the author's standing rule) -- but reported over all 35 as well, because the abstract
    says "the instances they solved" and that phrase covers every one of them."""
    def summarise(pairs):
        g = [100.0 * (o / t - 1) for o, t in pairs]
        return dict(cells=len(g), mean=st.mean(g), median=st.median(g), worst=max(g),
                    exact=sum(1 for o, t in pairs if abs(o - t) <= K_PRECISION), within1=sum(1 for x in g if x <= 1.0),
                    below=sum(1 for o, t in pairs if o < t - K_PRECISION))
    out, allp = {}, []
    for n in PER_INSTANCE:
        rs = [r for r in bestof(n) if r.get("proven") and r.get("theirs")]
        if not rs:
            continue
        pairs = [(r["best"], r["theirs"]) for r in rs]
        allp += pairs
        out["n%d" % n] = summarise(pairs)
    if allp:
        out["all"] = summarise(allp)
    return out


def brackets():
    """(OV - LB)/OV on the OPEN cells, ours against theirs, both against the better of their two incumbents.

    n50 and n100 carry no per-cell K value; n100 is therefore the cell-weighted family table and n50 is
    one-sided. `k_gap` is recomputed, not quoted -- see the module docstring, point 4."""
    out = {}
    for n in (20, 30, 50):
        rs = [r for r in bestof(n) if r.get("our_lb") and not r.get("proven")]
        if not rs:
            continue
        og = [100.0 * (1 - r["our_lb"] / r["best"]) for r in rs]
        both = [r for r in rs if r.get("their_lb") and r.get("theirs")]
        tg = [100.0 * (1 - r["their_lb"] / r["theirs"]) for r in both]
        out["n%d" % n] = dict(cells=len(og), ours_median=st.median(og), ours_mean=st.mean(og),
                              k_cells=len(tg), k_median=(st.median(tg) if tg else None),
                              smaller_than_k=(sum(1 for r in both if (1 - r["our_lb"] / r["best"]) < (1 - r["their_lb"] / r["theirs"])) if tg else None))
    f = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
    if f:
        W = sum(r["n"] for r in f["rows"])
        if W != 27:
            raise AssertionError("the n100 family table must cover 27 cells, not %d" % W)
        out["n100"] = dict(cells=W, ours_median=None, ours_mean=sum(r["n"] * r["our_gap"] for r in f["rows"]) / W,
                           k_cells=W, k_median=None, k_mean=sum(r["n"] * r["their_gap"] for r in f["rows"]) / W,
                           by_family={r["family"]: dict(cells=r["n"], ours=r["our_gap"], k=r["their_gap"],
                                                        inc_vs_k=100.0 * (r["our_inc"] / r["their_inc"] - 1)) for r in f["rows"]})
    return out


def closure_split():
    """FROM WHICH END. Of the interval K leave open -- their incumbent minus the bound their gap implies --
    how much our bound closes from below and our incumbent from above, in cost units summed over the cells
    where both sides have a value. The two shares add to the whole closure by construction:

        (U_k - L_k) - (U_o - L_o) = (L_o - L_k) + (U_k - U_o)

    A negative primal term means our incumbent is above theirs in aggregate on those cells, which is the
    case at |C| = 20 and 30 and must not be dressed up: there, the closure is the bound leg alone."""
    out = {}
    for n in (20, 30):
        rs = [r for r in bestof(n) if r.get("our_lb") and r.get("their_lb") and r.get("theirs") and not r.get("proven")]
        if not rs:
            continue
        dl = sum(r["our_lb"] - r["their_lb"] for r in rs)
        du = sum(r["theirs"] - r["best"] for r in rs)
        out["n%d" % n] = dict(cells=len(rs), from_bound=dl, from_primal=du, bound_share=100.0 * dl / (dl + du))
    f = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
    if f:
        dl = sum(r["n"] * (r["our_lb"] - r["their_lb"]) for r in f["rows"])
        du = sum(r["n"] * (r["their_inc"] - r["our_inc"]) for r in f["rows"])
        out["n100"] = dict(cells=sum(r["n"] for r in f["rows"]), from_bound=dl, from_primal=du,
                           bound_share=100.0 * dl / (dl + du))
    return out


def runtime():
    """The budget statement the abstract makes, from the runtime artifact: our worst cell as a share of the
    14 400 s per-instance limit, with our seconds charged at the strictest hardware factor (2.5)."""
    d = load(os.path.join(ROOT, "runs", "oracle", "tep_runtime_vs_k.json"))
    if not d:
        return {}
    cap, out = 14400.0, {}
    for n in SIZES:
        r = d.get("n%d" % n)
        if not r:
            continue
        out["n%d" % n] = dict(max_our_s=r["max_our_s"], max_cell=r["max_cell"],
                              max_share_at_2p5=100.0 * 2.5 * r["max_our_s"] / cap,
                              median_our_s=r["median_our_s"],
                              max_share_at_2p5_with_abandoned=100.0 * 2.5 * r["max_our_s_with_abandoned"] / cap)
    if out:
        out["worst_cell_share_at_2p5"] = max(v["max_share_at_2p5"] for v in out.values() if isinstance(v, dict))
    return out


def main():
    K = kref()
    if not K:
        print("no K reference table"); return 1
    T = their_side(K)
    A = attainment()
    B = brackets()
    C = closure_split()
    R = runtime()
    fail = []
    if T["cells_total"] != 135:
        fail.append("their instance count is %d, not 135" % T["cells_total"])
    if A.get("all") and A["all"]["cells"] != T["proven_total"]:
        fail.append("attainment covers %d cells but they prove %d" % (A["all"]["cells"], T["proven_total"]))
    if A.get("all") and A["all"]["below"]:
        fail.append("our incumbent is BELOW a proven optimum on %d cell(s) -- a defect, not a result" % A["all"]["below"])

    print("WHAT THEY PUBLISH (data/karademir2025/k_reference.json, tables 3, 4 and 6)")
    print("  instances %d | they prove optimality on %d: %s"
          % (T["cells_total"], T["proven_total"],
             ", ".join("%s at |C|=%s" % (v, k) for k, v in T["proven_by_size"].items() if v)))
    print("  per-instance gaps over the %d cells they tabulate individually: %.0f to %.0f per cent, smallest nonzero %.0f"
          % (T["per_instance_cells"], T["per_instance_gap_min"], T["per_instance_gap_max"], T["per_instance_gap_min_nonzero"]))
    print("  AVERAGES by size and family: %.1f to %.1f per cent -- %s"
          % (T["published_average_min"], T["published_average_max"],
             ", ".join("%s %.1f" % kv for kv in T["published_averages"].items())))
    print()
    print("ATTAINMENT where they prove an optimum (our best verified incumbent over theirs)")
    for k, v in A.items():
        print("  %-5s %2d cells | mean %+.3f%% | median %+.3f%% | worst %+.3f%% | matches the optimum on %d | within 1%% on %d"
              % (k, v["cells"], v["mean"], v["median"], v["worst"], v["exact"], v["within1"]))
    print()
    print("PROVEN OPTIMALITY GAP on the OPEN cells, (OV - LB)/OV, theirs RECOMPUTED against their better incumbent")
    for k, v in B.items():
        if v.get("ours_median") is not None:
            print("  %-5s %2d cells | ours median %.1f%%%s"
                  % (k, v["cells"], v["ours_median"],
                     ("" if v["k_median"] is None else " | theirs median %.1f%% over %d cells | ours smaller on %d"
                      % (v["k_median"], v["k_cells"], v["smaller_than_k"]))))
        else:
            print("  %-5s %2d cells | ours %.1f%% | theirs %.1f%% (cell-weighted family means; no per-cell value published)"
                  % (k, v["cells"], v["ours_mean"], v["k_mean"]))
            for fam, r in v["by_family"].items():
                print("        %-3s %2d cells | ours %.1f%% vs theirs %.1f%% | incumbent %+.1f%% against the better of their two methods"
                      % (fam, r["cells"], r["ours"], r["k"], r["inc_vs_k"]))
    print()
    print("FROM WHICH END the interval closes (cost units summed over the cells with both sides)")
    for k, v in C.items():
        print("  %-5s %2d cells | bound leg %+.0f | primal leg %+.0f | the bound is %.0f%% of the closure"
              % (k, v["cells"], v["from_bound"], v["from_primal"], v["bound_share"]))
    print()
    print("BUDGET: our worst cell against their 14 400 s per-instance limit, our seconds charged at 2.5")
    for k in ("n10", "n20", "n30", "n50", "n100"):
        v = R.get(k)
        if v:
            print("  %-5s worst cell %s at %.0f our-s -> %.1f%% of the limit (%.1f%% counting abandoned attempts)"
                  % (k, v["max_cell"], v["max_our_s"], v["max_share_at_2p5"], v["max_share_at_2p5_with_abandoned"]))
    out = dict(theirs=T, attainment=A, brackets=B, closure=C, runtime=R, failures=fail)
    p = os.path.join(ROOT, "runs", "oracle", "abstract_facts.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    if fail:
        print("  CONSISTENCY FAILURES: %s" % "; ".join(fail))
        return 1
    print("  consistency checks: 135 instances, %d proofs, no incumbent below a proven optimum -- all pass" % T["proven_total"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
