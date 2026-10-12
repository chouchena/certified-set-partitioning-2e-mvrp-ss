"""Cuts at the tail of the incumbent: design, audit and smoke, without touching frozen code. (d581)

=====================  DESIGN  =====================

The expensive part of a cut experiment is not the cut, it is rebuilding the column pool. The pool,
the model and the incumbent are all in memory the moment `master_ip` finishes, so the cut attempt
belongs THERE: one extra integer solve on the same pool, with the base solve as its own control.

    base solve            -> incumbent_0, bound_0        (the control, already paid for)
    ceiling = (incumbent_0 - bound_0) / incumbent_0      (d580: the max ANY row can buy here)
    if ceiling >= threshold:
        add cut rows to the same model
        re-solve at the same work limit               -> incumbent_1
        decode -> retime -> verify
        keep the cheaper VERIFIED solution, record both

This script is that experiment run from outside: it calls `tep_cg_bound.run(..., return_master=True)`
once, then `master_ip` twice with rows added in between. Nothing in the frozen pipeline changes, so
it can run before the baseline tag exists.

TWO CUT FAMILIES, both valid for the master IP because its covering rows are EQUALITIES (a partition):

  TRIP-COUNT   sum_r x_r >= ceil(total demand / Q). Every trip carries at most Q, so any partition
               needs at least that many trips. One row, no separation. This is what Oliveira et al.'s
               RC and SRC both collapse to in our formulation.

  SUBSET-ROW   for a triple S of customers, sum_r floor(|r inter S| / 2) x_r <= 1 (Jepsen, Petersen,
               Spoorendonk and Pisinger 2008). In a partition each customer is covered once, so at
               most one selected column can cover two or more of any three customers. Separated by
               enumerating triples against the incumbent LP solution -- trivial at these row counts,
               and FREE of pricing because the pool is fixed.

=====================  ADVERSE AUDIT, written before the run  =====================

A1. VALIDITY. Both families are valid only if the covering rows are equalities. `master_ip` sets
    `row.Sense = GRB.EQUAL` (d412), so they are -- but this script asserts it at run time rather
    than trusting the comment, because if that ever reverts to `>=` the subset-row cut becomes
    invalid and would silently cut off feasible solutions.

A2. THE CONTROL MUST NOT BE CONTAMINATED. Rows added for the treatment stay on the model. The two
    arms are therefore run in order -- control first, treatment second -- and the script never
    reuses the model for a third arm. It also records `NumConstrs` before and after so a reader can
    see exactly how many rows were added.

A3. AN UNVERIFIED IMPROVEMENT IS NOT AN IMPROVEMENT. A lower IP objective that fails to decode,
    re-time or verify is reported and discarded. The comparison of record is between VERIFIED
    solutions; the IP objectives are reported beside them as the search-level quantity.

A4. THE CEILING BOUNDS THE ANSWER. By d580 the treatment cannot beat `bound_0`. If the measured
    improvement ever exceeds the ceiling, the experiment is wrong, not the theory -- the script
    checks this and says so.

A5. DETERMINISM UNDER LOAD. The comparison uses Gurobi's WorkLimit, which counts deterministic work
    units, so it reproduces while another job shares the machine. Wall seconds are reported but are
    not the measurement.

A6. WHAT A NULL MEANS. If cuts change nothing on a cell with a large ceiling, the honest reading is
    that Gurobi's own cut generation already finds these families under other names -- which is the
    caveat recorded in validation/CUT_FAMILIES.md, not a surprise.

    python analysis/tep_cut_tail_smoke.py RC208 --size 20 --work 60
"""
import argparse
import io
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import instance_view
import tep_cg_bound as T
import verifier3 as V
from k_comparison import k_best_incumbent, k_proximity
from stamp import stamped
import tep_bk_in_column_space as BK

Q = float(instance_view.LEFV_CAPACITY)


def summarise(r):
    # `solution` is kept deliberately. Without it a primal improvement cannot be re-verified by
    # verifier3 and cannot be harvested, so it is a number in a log and nothing else -- which is
    # exactly what happened on RC208 n30, where the cut arm beat its control by 10.81 and the
    # solution had already been discarded by the time anyone looked (d588). The harvest contract
    # is `ip.solution` next to a verified `objVal` (analysis/tep_harvest_master_ip.py).
    return dict(status=r.get("ip_status"), street=r.get("ip_street"), bound=r.get("ip_bound"),
                gap_pct=(100.0 * r["ip_gap"]) if r.get("ip_gap") is not None else None,
                cars=r.get("ip_cars"), verified=r.get("verified"), objVal=r.get("objVal"),
                retime=r.get("retime_status"), secs=r.get("ip_secs"),
                solution=r.get("solution"))


def add_cuts(M, inst, gp, GRB, max_triples=4000):
    """Trip-count plus separated subset-row cuts. Returns (n_added, detail)."""
    # A1: the partition hypothesis, asserted rather than assumed
    senses = {c.Sense for c in M.cov.values()}
    assert senses == {GRB.EQUAL}, "subset-row cuts need EQUALITY covering rows, found %s" % senses
    added, detail = 0, {}
    dem = sum(float(inst.nodes[c].demand) for c in M.C)
    need = int(math.ceil(dem / Q - 1e-9))
    M.m.addConstr(gp.quicksum(M.cols.values()) >= need, name="tripcount")
    added += 1; detail["tripcount_rhs"] = need
    # separation for |S| = 3 against the CURRENT LP solution
    M.m.update()
    lp = M.m.relax(); lp.Params.OutputFlag = 0; lp.optimize()
    xv = {k: v for k, v in zip(M.cols.keys(), [lp.getVarByName(v.VarName).X if v.VarName else 0.0
                                               for v in M.cols.values()])} if False else None
    # the relaxation copy loses the variable mapping, so separate on the integer model's LP by
    # solving it directly: set all columns continuous, optimise, read, then restore
    old = {k: v.VType for k, v in M.cols.items()}
    for v in M.cols.values():
        v.VType = GRB.CONTINUOUS
    M.m.optimize()
    xv = {k: v.X for k, v in M.cols.items() if v.X > 1e-6}
    for k, t in old.items():
        M.cols[k].VType = t
    members = {}
    for k in xv:
        for c in set(k[0]):
            members.setdefault(c, []).append(k)
    cust = sorted(M.C)
    src, tried = 0, 0
    for i in range(len(cust)):
        for j in range(i + 1, len(cust)):
            for l in range(j + 1, len(cust)):
                tried += 1
                if tried > max_triples:
                    break
                S = {cust[i], cust[j], cust[l]}
                tot, cols = 0.0, []
                for k, x in xv.items():
                    cnt = len(S & set(k[0]))
                    if cnt >= 2:
                        tot += x; cols.append(k)
                if tot > 1.0 + 1e-6 and cols:
                    M.m.addConstr(gp.quicksum(M.cols[k] for k in cols) <= 1, name="src_%d" % src)
                    src += 1; added += 1
    detail["subset_row_cuts"] = src; detail["triples_tried"] = min(tried, max_triples)
    M.m.update()
    return added, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--work", type=float, default=60.0); ap.add_argument("--iters", type=int, default=80)
    ap.add_argument("--ceil", action="store_true", default=True)
    ap.add_argument("--seed-bk", action="store_true",
                    help="inject the banked best-known's trips as columns and report against BK "
                         "(author constraint 3, d589) -- the BK-wired design")
    a = ap.parse_args()
    import gurobipy as gp
    from gurobipy import GRB
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    print("CUT-AT-THE-TAIL SMOKE -- %s n%d, ceil master, work limit %.0f on both arms\n" % (a.cell, a.size, a.work))
    t0 = time.time()
    r = T.run(a.cell, T.default_delta(inst), a.iters, ["prio", "ts"], 10, 1000, False, 3_000_000,
              size=a.size, start_states=True, proximity=prox, return_master=True, max_secs=0.0, primal=True)
    M = r["master"]
    print("  column generation: LP street %.2f, %d columns, %.0f s" % (r["lp_street"], r["cols"], time.time() - t0), flush=True)

    # --seed-bk: WIRE THE RUN OVER THE BASELINE OUTCOME (author constraint 3, d589). Inject the
    # banked best-known's own trips as columns, so the master IP can reproduce BK exactly and any
    # answer it returns is measured against what we already hold rather than against whatever its
    # own pool happened to reach. tep_bk_in_column_space.py established, with no solve, that BK's
    # trips ARE legal columns on all 22 live n20/n30/n50 cells, so this insertion cannot fail for
    # a reason we have not already looked at.
    bk_ref, bk_added, bk_trips = None, 0, 0
    if a.seed_bk:
        got = BK.banked(a.cell, a.size)
        if not got:
            print("  --seed-bk: NO banked solution for this cell; refusing to run a BK-wired arm "
                  "without a BK. Re-run without the flag if the same-pool contrast is what you want.")
            return 2
        sol, src = got
        bk_ref = float(sol["objVal"])
        trips, _, _ = BK.trips_of(sol)
        bk_trips = len(trips)
        for seq in trips:
            for (L, b, p, ba) in M.variants(seq):
                if M.add_column(seq, L, b, p, ba):
                    bk_added += 1
        M.m.update()
        print("  --seed-bk: BK %.3f from %s, %d trips -> %d new columns injected (pool now %d)"
              % (bk_ref, src, bk_trips, bk_added, len(M.cols)), flush=True)
        if bk_added == 0:
            print("  every BK column was ALREADY in the pool -- BK was reachable all along and the "
                  "master IP simply did not find it. That is a search result, not a pool result.")
    base = T.master_ip(M, a.cell, a.size, threads=2, timelimit=3600.0, work=a.work)
    b = summarise(base)
    ceiling = b["gap_pct"]
    print("  control    : IP street %10.2f | bound %10.2f | ceiling %5.2f%% | verified %s | obj %s"
          % (b["street"], b["bound"], ceiling or 0.0, b["verified"], b["objVal"]), flush=True)
    rows_before = M.m.NumConstrs
    n_added, detail = add_cuts(M, inst, gp, GRB)
    print("  cuts added : %d rows (%s), model %d -> %d constraints" % (n_added, detail, rows_before, M.m.NumConstrs), flush=True)
    M.m.reset()
    trt = T.master_ip(M, a.cell, a.size, threads=2, timelimit=3600.0, work=a.work)
    t = summarise(trt)
    print("  with cuts  : IP street %10.2f | bound %10.2f | gap %5s%% | verified %s | obj %s"
          % (t["street"], t["bound"], ("%.2f" % t["gap_pct"]) if t["gap_pct"] is not None else "n/a",
             t["verified"], t["objVal"]), flush=True)
    verdict, flags = "no change", []
    if b["street"] and t["street"]:
        d = 100.0 * (1 - t["street"] / b["street"])
        verdict = ("IP objective improved %.2f%%" % d) if d > 1e-9 else ("IP objective unchanged" if abs(d) < 1e-9
                                                                         else "IP objective WORSE by %.2f%%" % -d)
        if ceiling is not None and d > ceiling + 1e-6:          # A4
            flags.append("improvement %.2f%% EXCEEDS the ceiling %.2f%% -- the experiment is wrong" % (d, ceiling))
    if b["verified"] and t["verified"] and b["objVal"] and t["objVal"]:
        verdict += " | verified objective %.3f -> %.3f" % (b["objVal"], t["objVal"])
    elif t["street"] and not t["verified"]:
        flags.append("the cut arm did not verify (%s), so it is not an improvement" % t["retime"])   # A3
    kb, _ = k_best_incumbent(a.cell, a.size)
    if kb and t.get("objVal") and t["objVal"] < kb - 0.05:
        flags.append("cut solution is BELOW K's published value %s -- check whether that cell is proven"
                     % (("%.3f" % kb) if kb else "?"))
    bk_line = None
    if bk_ref is not None:
        arms_ok = [x for x in (b, t) if x.get("objVal")]
        if arms_ok:
            best_arm = min(arms_ok, key=lambda x: x["objVal"])
            gain = bk_ref - best_arm["objVal"]
            bk_line = ("BEATS the banked BK %.3f by %.3f (%.2f%%)" % (bk_ref, gain, 100.0 * gain / bk_ref)
                       if gain > 0.05 else
                       "REPRODUCES BK exactly (%.3f)" % bk_ref if abs(gain) <= 0.05 else
                       "does NOT reach BK %.3f -- short by %.3f (%.2f%%) even though BK's own columns "
                       "are in the pool, so this is the IP search falling short at this work limit, "
                       "not the pool lacking the solution" % (bk_ref, -gain, -100.0 * gain / bk_ref))
            print("  vs BASELINE: %s" % bk_line)
    print("\n  VERDICT: %s" % verdict)
    for f in flags:
        print("  *** %s" % f)
    p = os.path.join(ROOT, "runs", "oracle", "tep_cut_tail_smoke_%s_n%d.json" % (a.cell, a.size))
    # Expose the BETTER of the two verified arms under the key the harvest already reads, so a cut
    # improvement reaches the banked incumbents through the existing verified path (which refuses a
    # solution below a proven optimum or below our own certified bound) rather than a second one.
    arms = [x for x in (b, t) if x.get("verified") and x.get("objVal") and x.get("solution")]
    harvest_ip = min(arms, key=lambda x: x["objVal"]) if arms else None
    json.dump(stamped(dict(cell=a.cell, size=a.size, work=a.work, lp_street=r["lp_street"], cols=r["cols"],
                           ip=harvest_ip, size_for_harvest=a.size,
                           seed_bk=bool(a.seed_bk), bk_ref=bk_ref, bk_trips=bk_trips,
                           bk_columns_added=bk_added, bk_line=bk_line,
                           control=b, cuts=t, cut_detail=detail, rows_added=n_added,
                           ceiling_pct=ceiling, verdict=verdict, flags=flags)),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
