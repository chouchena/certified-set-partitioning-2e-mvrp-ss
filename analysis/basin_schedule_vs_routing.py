"""Do distinct basins differ more in ROUTING or in SCHEDULE? The measurement AUDIT_temporal
   _hypothesis_overturned.md concluded on, without making it.

WHY THIS EXISTS. That audit overturned the schedule-first proposal on a table of four columns:
street arcs in common, transfer set shared, water arcs shared, nCars. It concluded "if basins were
schedule structures we would see similar routes with different timings; we see the opposite".

**It never compared timings.** "Transfer set shared" is WHICH customers precede a reload -- a
set-membership quantity, routing-adjacent. The schedule is WHEN things happen. Two solutions can
share the entire transfer set and run on completely different clocks.

A second defect: the percentages are not comparable. RC203 shares 3 of 40 street arcs (8%) against
4 of 10 transfers (40%). Different cardinalities have different chance-overlap baselines, so
"8% < 40%" does not establish that routing differs more. A null model is needed and none was used.

WHAT THIS MEASURES INSTEAD, per cell, between the best and worst plausible stored solution:

  routing_jaccard   |A n B| / |A u B| over street arcs        -- scale-free, comparable
  transfer_jaccard  same over the transfer set                -- scale-free, comparable
  time_spearman     rank correlation of per-customer service times -- is the ORDER preserved?
  time_nrms         RMS |hi_a - hi_b| over customers, / horizon    -- are the CLOCKS the same?

READ IT LIKE THIS. Basins that are ROUTING structures show low routing_jaccard with HIGH
time_spearman and LOW time_nrms -- different roads, same clock. Basins that are SCHEDULE
structures show the reverse. A cell with both low is simply two unrelated solutions and says
nothing either way.

NO CLAIM IS MADE FROM ONE CELL. This is a descriptive split designed to find whether ANY instance
looks schedule-structured, because the proposal it bears on was rejected on an aggregate.

FILTERING. The stored pool contains unverified probe output, including TD=0 `fleetdrop` artifacts
whose objective is far BELOW our verified best and therefore infeasible. Any solution better than
the verified best is excluded and reported separately -- it is either junk or an unbanked
discovery, and both need naming rather than averaging in.
"""
import argparse, glob, json, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped

NAME = re.compile(r"^(?:best_|merge_|fixopt_|crossover_|fleetdrop_|sol_)?((?:RC|R|C)\d{3})_n(\d+)")


def spearman(a, b):
    n = len(a)
    if n < 3:
        return float("nan")

    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def jac(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else float("nan")


def load(size):
    """cell -> list of (objVal, doc). Only solutions carrying hi."""
    per = {}
    for pat in ("published_artifacts/solutions/*.json", "results/portfolio/*.json",
                "runs/solutions/*.json", "validation/certificates/*_solution.json"):
        for f in glob.glob(os.path.join(ROOT, pat)):
            m = NAME.match(os.path.basename(f))
            if not m or int(m.group(2)) != size:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict) or "hi" not in d or "objVal" not in d or "xij" not in d:
                continue
            per.setdefault(m.group(1), []).append((float(d["objVal"]), d))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--out", default="runs/basin_schedule_vs_routing.json")
    a = ap.parse_args()

    import analysis.manuscript_numbers as M
    from build_instance import build

    verified = {}
    for f in glob.glob(os.path.join(ROOT, "published_artifacts/solutions/best_*_n%d.json" % a.size)):
        m = NAME.match(os.path.basename(f))
        if m:
            verified[m.group(1)] = float(json.load(open(f, encoding="utf-8"))["objVal"])

    per = load(a.size)
    rows, impossible = [], []
    print("%-7s %4s %9s %9s  %8s %9s  %9s %8s"
          % ("cell", "n", "best", "worst", "routeJac", "transfJac", "timeRho", "timeNRMS"))
    for cell in sorted(per):
        vb = verified.get(cell)
        cand = sorted(per[cell], key=lambda t: t[0])
        if vb is not None:
            better = [o for o, _ in cand if o < vb - 1e-6]
            if better:
                impossible.append((cell, min(better), vb))
            cand = [(o, d) for o, d in cand if o >= vb - 1e-6]
        if len(cand) < 2:
            continue
        (ob, db), (ow, dw) = cand[0], cand[-1]
        if ow - ob < 1e-6:
            continue
        p = build(cell, a.size, tau="formula")
        horizon = max(n.latest for n in p.nodes) or 1.0
        cust = [c for c in p.customers if str(c) in db["hi"] and str(c) in dw["hi"]]
        ta = [db["hi"][str(c)] for c in cust]
        tb = [dw["hi"][str(c)] for c in cust]
        rj = jac([tuple(x) for x in db["xij"]], [tuple(x) for x in dw["xij"]])
        tj = jac(db.get("vi") or [], dw.get("vi") or [])
        rho = spearman(ta, tb)
        nrms = math.sqrt(sum((x - y) ** 2 for x, y in zip(ta, tb)) / len(ta)) / horizon
        rows.append(dict(cell=cell, n=len(cand), best=ob, worst=ow, route_jaccard=rj,
                         transfer_jaccard=tj, time_spearman=rho, time_nrms=nrms))
        print("%-7s %4d %9.2f %9.2f  %8.3f %9.3f  %9.3f %8.3f"
              % (cell, len(cand), ob, ow, rj, tj, rho, nrms))

    print()
    if impossible:
        print("EXCLUDED as better than the verified best (junk, or an unbanked discovery):")
        for c, o, v in impossible:
            print("   %-6s stored %.2f against verified best %.2f" % (c, o, v))
    else:
        print("no stored solution beats its verified best.")
    json.dump(stamped(dict(size=a.size, rows=rows, excluded=impossible), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("\nwrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
