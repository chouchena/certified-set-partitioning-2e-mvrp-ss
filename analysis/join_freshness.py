"""
Standing guard: is any STORED JOIN stale with respect to its live sources?

Origin (refactor finding A1, 2026-09-12). `runs/ab_vs_milp.json` is a join of the AB grid with
the MILP bounds from the descend artifacts. It was built before the n30 reprovenance campaign
improved those bounds, so it silently carried **five phantom "AB beats MILP" n30 wins** from
artifacts already known to be damaged -- while three STANDING claims cited it. Nothing in the
pipeline noticed.

`runs/n100_final.json` is the same shape and was NOT stale, which isolates the mechanism:
**a stored join goes stale exactly when one of its inputs is re-run.** n30 was re-run; n100 was
not. So this is not a one-off -- every campaign that improves bounds silently ages every join
over those cells. The n50 campaign will age the crossover the moment it lands.

    python analysis/join_freshness.py          # exit 0 fresh, 2 stale, 1 cannot check

Run it after any campaign completes and before any claim is quoted from a join.
"""
import os, sys, json, glob, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

TOL = 0.011          # stored joins hold 2-dp values


def live_milp(cell, size):
    """max_k block_relax over every artifact for the cell -- same rule as lb_monitor.our_bound."""
    best = None
    # NEVER use f"..._n{size}*.json": "_n10*" also matches "n100". Two exact forms instead --
    # the bare file and underscore-suffixed variants. This glob bit twice on 2026-09-12.
    pats = (f"easy_reduction_descend_{cell}_n{size}.json",
            f"easy_reduction_descend_{cell}_n{size}_*.json",
            f"easy_reduction_{cell}_n{size}.json",
            f"easy_reduction_{cell}_n{size}_*.json")
    for pat in pats:
        for f in glob.glob(os.path.join(ROOT, "crossfeed", pat)):
            try:
                recs = json.load(open(f))
            except Exception:
                continue
            for r in (recs if isinstance(recs, list) else [recs]):
                v = r.get("block_relax")
                if isinstance(v, (int, float)) and (best is None or v > best):
                    best = v
    return best


def live_ab():
    p = os.path.join(ROOT, "runs", "ab_grid_provenanced.json")
    if not os.path.exists(p):
        return None
    return {(r["cell"], r["size"]): r for r in json.load(open(p))["records"]}


def check_ab_vs_milp(ab):
    p = os.path.join(ROOT, "runs", "ab_vs_milp.json")
    if not os.path.exists(p):
        return [], 0
    d = json.load(open(p))
    d = d if isinstance(d, list) else list(d.values())
    stale, n = [], 0
    for o in d:
        c, s = o["cell"], o["size"]
        m = live_milp(c, s)
        n += 1
        if m is not None and abs(m - o["milp"]) > TOL:
            stale.append((f"{c} n{s}", "milp", o["milp"], round(m, 2)))
        g = ab.get((c, s)) if ab else None
        if g and abs(round(g["ab4_full"], 2) - o["ab4"]) > TOL:
            stale.append((f"{c} n{s}", "ab4", o["ab4"], round(g["ab4_full"], 2)))
    return stale, n


def check_n100_final(ab):
    p = os.path.join(ROOT, "runs", "n100_final.json")
    if not os.path.exists(p):
        return [], 0
    d = json.load(open(p))
    stale, n = [], 0
    for c, o in d.items():
        m = live_milp(c, 100)
        n += 1
        if m is not None and abs(m - o["milp"]) > TOL:
            stale.append((f"{c} n100", "milp", o["milp"], round(m, 2)))
        g = ab.get((c, 100)) if ab else None
        if g and abs(round(g["ab4_full"], 2) - o["ab4"]) > TOL:
            stale.append((f"{c} n100", "ab4", o["ab4"], round(g["ab4_full"], 2)))
    return stale, n


JOINS = [("runs/ab_vs_milp.json", check_ab_vs_milp,
          "SUPERSEDED by runs/ab_vs_milp_derived.json -- rebuild with analysis/ab_vs_milp_build.py"),
         ("runs/n100_final.json", check_n100_final,
          "rebuild from the campaign artifacts + runs/ab_grid_provenanced.json")]


EXPECTED_CELLS = 27   # Solomon class-2: C201-208, R201-211, RC201-208


def check_coverage():
    """A join can be FRESH and still incomplete. ab_vs_milp.json covers only 17/26/24 of the
    27 cells at n20/n30/n100, and quoting its denominators produced a wrong crossover table
    on 2026-09-12 (reported n30 0/26 and n100 15/24; the truth is 0/27 and 17/27). Staleness
    and coverage are different defects and both must be checked."""
    import collections
    out = []
    p = os.path.join(ROOT, "runs", "ab_vs_milp.json")
    if os.path.exists(p):
        d = json.load(open(p))
        d = d if isinstance(d, list) else list(d.values())
        by = collections.Counter(r["size"] for r in d)
        for size, n in sorted(by.items()):
            if n < EXPECTED_CELLS:
                out.append(("runs/ab_vs_milp.json", size, n))
    p2 = os.path.join(ROOT, "runs", "n100_final.json")
    if os.path.exists(p2):
        n = len(json.load(open(p2)))
        if n < EXPECTED_CELLS:
            out.append(("runs/n100_final.json", 100, n))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    ab = live_ab()
    if ab is None:
        print("runs/ab_grid_provenanced.json missing -- run analysis/ab_grid_build.py --combos all")
        return 1
    total_stale = 0
    print("=" * 72)
    print("STORED-JOIN FRESHNESS  (a join ages whenever one of its inputs is re-run)")
    print("=" * 72)
    for name, fn, fix in JOINS:
        stale, n = fn(ab)
        total_stale += len(stale)
        if stale:
            print(f"\n{name}: **STALE** -- {len(stale)} of {n} rows disagree with live sources")
            for row in stale[:10]:
                print(f"    {row[0]:14} {row[1]:5} stored={row[2]:<10} live={row[3]}")
            if len(stale) > 10:
                print(f"    ... and {len(stale) - 10} more")
            print(f"    FIX: {fix}")
        else:
            print(f"{name}: fresh ({n} rows checked)")
    cov = check_coverage()
    print()
    if cov:
        print("COVERAGE (a join can be fresh and still incomplete):")
        for name, size, n in cov:
            print(f"  {name}: n{size} has {n}/{EXPECTED_CELLS} cells -- "
                  f"NEVER quote {n} as a denominator")
    else:
        print("COVERAGE: all joins cover 27/27 cells per size")

    print("-" * 72)
    if cov and not total_stale:
        print("No stale rows, but coverage is incomplete. Recompute counts from live")
        print("artifacts + runs/ab_grid_provenanced.json, not from the join.")
        return 2
    if total_stale:
        print(f"{total_stale} stale rows. Do NOT quote a claim from a stale join.")
        return 2
    print("All stored joins agree with their live sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
