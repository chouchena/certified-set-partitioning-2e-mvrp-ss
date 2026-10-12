"""THE STANDING INDICATION TABLE -- directional read across the grid, all signals at once.

AUTHOR, 2026-09-17: *"I dont seek evidences but indications - preferably using as much
supporting info we have - this is the heading I want to keep"* and *"whenever applicable
Fleet potential reduction is another indication?"*

This is a STEERING instrument, not a manuscript exhibit. Nothing here is a claim; every
column is an indication, and the columns disagree with each other on purpose -- a signal
that survives several independent columns is worth acting on, one that appears in a single
column is worth checking first.

THE COLUMNS, and what each one is evidence ABOUT.

  K-SPREAD   K's OWN two methods disagreeing. Independent of our bound's looseness, which
             is exactly why it is the most trustworthy column here: if Joint and LBBD land
             11% apart, neither has converged, and that is K's own testimony. Near 0 means
             they have converged and there is nothing to take.
  PROVEN     cells K prove optimal. A STRUCTURAL ceiling: we cannot beat a proven optimum,
             only tie it. Where this is high the primal is capped by arithmetic.
  COVERAGE   cells on which we have ever produced a primal solution. Our own blindness.
  LB/K_LB    our certified bound against K's implied bound (OV x (1 - gap/100)). Above 1.0
             we have narrowed the uncertainty; at or below 1.0 we have learned nothing and
             any maxGap at that size is OUR looseness, not their slack.
  maxGap     (K_OV - our_LB)/K_OV. A valid CEILING on what anyone could beat K by, since
             L <= z* <= U_K. NOT a forecast: it is what we can prove, and at n20 it runs
             ~10x looser than what the cross-method evidence says is true.
  FLEET      K's achieved street fleet against ours. Needs no bound at all -- two observed
             numbers -- which is why it survives when the certified-floor column does not.

WHAT IS DELIBERATELY ABSENT, and why -- read this before asking for it back.
A "fleet slack vs a certified floor" column would be the sharpest form of the fleet
indication, and it is NOT COMPUTABLE TODAY. `runs/fleet_lb_arith_*.json` comes from
`analysis/fleet_lb_arithmetic.py`, which `analysis/fleet_energetic_bound.py` supersedes and
names two defects in: it built with the DEFAULT tau="code" so every reload was priced at
ZERO, and it omitted mandatory transfer time -- "my bound dropped the largest of the three".
Its floors are therefore understated and any slack computed from them is OVERSTATED. The
corrected generators have only been run at |C|=20, where both return fleet_lb = 1, and the
energetic docstring is explicit that "a bound of 2 PROVES one vehicle impossible; a bound
of 1 proves nothing". So: no valid fleet floor exists above |C|=20. Restoring that column
means running `fleet_energetic_bound.py` at 30/50/100 first.
"""
import collections, json, math, os, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import analysis.manuscript_numbers as M                       # noqa: E402

FAM = lambda c: "RC" if c.startswith("RC") else c[0]


def _load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def our_lb(cell, size):
    """max over ALL records of block_relax.

    Proven records carry the relaxation's optimum; UNPROVEN ones carry CPLEX's best_bound
    (`block_a.py`: value = inc if proven else bb), which is still a valid -- weaker -- bound.
    Dropping customers relaxes the problem, so a bound on the relaxation bounds the original,
    and DUAL TAKES THE MAX. Flagged as a CANDIDATE: the chain is verified in code but has not
    had a hand-recomputed witness, and this project has banked a bad fleet certificate before.
    """
    d = _load(os.path.join(ROOT, "crossfeed",
                           "easy_reduction_descend_%s_n%d.json" % (cell, size)))
    if d is None:
        return None
    d = d if isinstance(d, list) else [d]
    v = [x["block_relax"] for x in d
         if isinstance(x, dict) and isinstance(x.get("block_relax"), (int, float))]
    return max(v) if v else None


def k_penalty(fleet_sl, fleet_wl, travel_sl, travel_wl, zIP):
    """Recover penaltyCars from K's own published decomposition.

    z = nCars*P + nVessel*0.1P + street + 0.1*water, so P = (z - street - 0.1*water)
    / (nCars + 0.1*nVessel). It is FAMILY- and SIZE-specific, not a constant: at |C|=100
    this returns C 203.7, R 171.1, RC 223.6 from two independent rows each.
    """
    den = fleet_sl + 0.1 * fleet_wl
    return None if den <= 0 else (zIP - travel_sl - 0.1 * travel_wl) / den


def our_cars():
    """our achieved street fleet per (size, cell), best over the cost-aware ladder.

    fixopt does NOT log a car count (verified: no car/fleet field in any fixopt record), so
    the grid sweep is the only per-cell source we have. That is a LOGGING GAP, not a real
    absence -- the solutions exist, the counts were never written down.
    """
    out = collections.defaultdict(list)
    for fn in ("greedy_blind_vs_aware_grid_s20.json", "greedy_blind_vs_aware_grid.json"):
        d = _load(os.path.join(ROOT, "runs", fn))
        if not d or "rows" not in d:
            continue
        for r in d["rows"]:
            cars = []
            for sd in (r.get("seeds") or []):           # grid: rows[].seeds[][arm]
                for arm in (sd or {}).values():
                    if isinstance(arm, dict) and arm.get("ok") \
                            and isinstance(arm.get("cars"), (int, float)):
                        cars.append(arm["cars"])
            for arm in (r.get("arms") or {}).values():  # cost_aware_*: rows[].arms[].cars[]
                cars += [c for c in (arm.get("cars") or []) if isinstance(c, (int, float))]
            if cars:
                out[(r.get("size"), r.get("cell"))].append(min(cars))
        break
    return {k: min(v) for k, v in out.items()}


def main():
    K = M._K()
    CARS = our_cars()
    print(__doc__.split("THE COLUMNS")[0].strip())
    print()
    print("%-10s %9s %8s %9s %9s %9s | %8s %8s %7s" %
          ("stratum", "K-SPREAD", "PROVEN", "COVERAGE", "LB/K_LB", "maxGap",
           "K fleet", "our fleet", "ratio"))
    print("-" * 96)

    # ---- n10 / n20 / n30 : per-instance ----
    t4 = {(r["size"], r["method"]): r for r in K["table4_full"] if r["wls"] == "1:10"}
    for size in (10, 20, 30):
        per = K["table3"]["per_instance"][str(size)]
        sm = K["table3"]["summary"][str(size)]
        spread = 100.0 * abs(sm["joint"]["bk"] - sm["lbbd"]["bk"]) / min(sm["joint"]["bk"],
                                                                        sm["lbbd"]["bk"])
        proven = sum(1 for c in per if abs(per[c]["joint_gap"]) < 1e-9)
        lbs, gaps = [], []
        for c in sorted(per):
            lb = our_lb(c, size)
            if lb is None:
                continue
            U = min(per[c]["joint_bk"], per[c].get("lbbd_bk", per[c]["joint_bk"]))
            klb = per[c]["joint_bk"] * (1 - per[c]["joint_gap"] / 100.0)
            lbs.append(lb / klb if klb else float("nan"))
            gaps.append(100.0 * (U - lb) / U)
        cov = sum(1 for c in per if (size, c) in CARS or True)  # placeholder, see below
        prim = _primal_coverage(size)
        kf = t4.get((size, "LBBD"), {}).get("fleet_sl")
        ours = [CARS[(size, c)] for c in per if (size, c) in CARS]
        om = st.median(ours) if ours else None
        print("%-10s %8.2f%% %6d/27 %7d/27 %9s %8.1f%% | %8s %8s %7s" %
              ("n%d" % size, spread, proven, prim,
               ("%.2fx" % st.median(lbs)) if lbs else "-",
               st.median(gaps) if gaps else float("nan"),
               ("%.2f" % kf) if kf else "n/a",
               ("%.1f" % om) if om else "-",
               ("%.1fx" % (om / kf)) if (om and kf) else "-"))

    # ---- n50 : pooled ----
    row = {r["method"]: r for r in K["table4"] if r["size"] == 50 and r["wls"] == "1:10"}
    if row:
        j, l = row["Joint"]["bk"], row["LBBD"]["bk"]
        spread = 100.0 * abs(j - l) / min(j, l)
        lbs = [x for x in (our_lb(c, 50) for c in sorted(M._cells(50))) if x]
        klb = j * (1 - row["Joint"]["gap_imp"] / 100.0)
        ours = [CARS[(50, c)] for c in M._cells(50) if (50, c) in CARS]
        kf = t4.get((50, "LBBD"), {}).get("fleet_sl")
        om = st.median(ours) if ours else None
        print("%-10s %8.2f%% %6s %7d/27 %9s %8.1f%% | %8s %8s %7s" %
              ("n50 pool", spread, "0/27", _primal_coverage(50),
               "%.2fx" % (st.mean(lbs) / klb), 100.0 * (min(j, l) - st.mean(lbs)) / min(j, l),
               ("%.2f" % kf) if kf else "n/a",
               ("%.1f" % om) if om else "-",
               ("%.1fx" % (om / kf)) if (om and kf) else "-"))

    # ---- n100 : per family ----
    for f0 in ("C", "R", "RC"):
        t6 = K["table6"][f0]
        j, l = t6["joint"]["zIP"], t6["lbbd"]["zIP"]
        spread = 100.0 * abs(j - l) / min(j, l)
        cells = [c for c in sorted(M._cells(100)) if FAM(c) == f0]
        lbs = [x for x in (our_lb(c, 100) for c in cells) if x]
        klb = j * (1 - t6["gap_joint"] / 100.0)
        kf = t6["lbbd"]["fleet_sl"]
        ours = [CARS[(100, c)] for c in cells if (100, c) in CARS]
        om = st.median(ours) if ours else None
        print("%-10s %8.2f%% %6s %7d/%-2d %9s %8.1f%% | %8.2f %8s %7s" %
              ("n100 " + f0, spread, "0/%d" % t6["n"],
               _primal_coverage(100, f0), t6["n"],
               "%.2fx" % (st.mean(lbs) / klb) if lbs else "-",
               100.0 * (min(j, l) - st.mean(lbs)) / min(j, l) if lbs else float("nan"),
               kf, ("%.1f" % om) if om else "-",
               ("%.1fx" % (om / kf)) if (om and kf) else "-"))

    print("-" * 96)
    print("COVERAGE is cells with a banked fixopt solution; 'our fleet' is the cost-aware")
    print("ladder's best car count (fixopt logs none), so at |C|<=30 the fleet column is a")
    print("CONSTRUCTOR number and understates what fixopt reaches. Read it only at 50/100,")
    print("where the constructor IS our current best.")
    print()
    print("ABSENT ON PURPOSE: fleet slack vs a certified floor -- the only artifacts above")
    print("|C|=20 come from the superseded fleet_lb_arithmetic.py (reloads priced at zero).")
    print("See this module's docstring. Run fleet_energetic_bound.py at 30/50/100 to restore.")
    return 0


def _primal_coverage(size, family=None):
    import glob, re
    seen = set()
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_*_n%d_*.jsonl" % size)):
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n%d_" % size, os.path.basename(f))
        if not m:
            continue
        try:
            for line in open(f, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0:
                    c = m.group(1)
                    if family is None or FAM(c) == family:
                        seen.add(c)
                    break
        except Exception:
            pass
    return len(seen)


if __name__ == "__main__":
    sys.exit(main())
