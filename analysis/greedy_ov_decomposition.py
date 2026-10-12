"""Where does the cost-aware constructor's OV improvement actually COME FROM?

The grid comparison reported a percentage and a car count. Neither says how much OBJECTIVE was
gained, nor how it splits. "4041 cars saved" is not an objective improvement until it is multiplied
by a penalty that varies by cell (penaltyCars runs 131-194 at |C| = 20 alone), and a car saved can
even be bought by spending MORE travel than it is worth.

THE DECOMPOSITION IS EXACT, not a model. The verifier computes

    z = nCars*penaltyCars + nVessel*penaltyVessels + c_s*street + c_w*water

so for a paired (BLIND, AWARE) comparison on one cell-seed:

    dOV       = OV_aware - OV_blind                                   (negative = better)
    d_cars    = (cars_a - cars_b) * penaltyCars     <- of THIS cell
    d_vessels = (ves_a  - ves_b ) * penaltyVessels  <- of THIS cell
    d_routing = dOV - d_cars - d_vessels            <- the residual IS the travel term

No distances are re-summed; the residual is forced by the identity. Per-cell penalties are read
from the instance and stored in the artifact, because applying one cell's penalties to another is
an error this project has already made once.

WHY THE SPLIT MATTERS. If the whole gain is `d_cars`, the lever is purely fleet and its value
scales with penaltyCars. If a material part is `d_routing`, the constructor is also building
cheaper tours, which is a different and more transferable claim. And if `d_routing` is POSITIVE
while `d_cars` is negative, the constructor is buying cars with travel -- still a net win, but a
trade rather than an improvement, and it should be described that way.

Usage:  python analysis/greedy_ov_decomposition.py --in runs/greedy_ov_decomp_s20.json
"""
import argparse, json, os, statistics as st, sys
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="runs/greedy_ov_decomp_s20.json")
    a = ap.parse_args()
    d = json.load(open(os.path.join(ROOT, a.inp), encoding="utf-8"))
    arms = [str(x) for x in d["ladder"]]
    base = arms[0]

    print("OV IMPROVEMENT, DECOMPOSED. BLIND = st%s, AWARE = best verified over %s"
          % (base, d["ladder"]))
    print("  paired per cell-seed; negative = AWARE better. Penalties are PER CELL.\n")

    per_size = {}
    for size in d["sizes"]:
        rows = [r for r in d["rows"] if r["size"] == size]
        dov, dcar, dves, drt, rel = [], [], [], [], []
        for r in rows:
            pc, pv = r["penCars"], r["penVes"]
            for sd in r["seeds"]:
                b = sd[base]
                cand = [v for v in sd.values() if v["ok"] and v["obj"]]
                if not (b["ok"] and b["obj"] and cand):
                    continue
                x = min(cand, key=lambda v: v["obj"])
                o = x["obj"] - b["obj"]
                c = (x["cars"] - b["cars"]) * pc
                w = (x["ves"] - b["ves"]) * pv
                dov.append(o); dcar.append(c); dves.append(w); drt.append(o - c - w)
                rel.append(100.0 * o / b["obj"])
        if not dov:
            continue
        per_size[size] = dict(
            pairs=len(dov), total_dov=sum(dov), mean_dov=st.mean(dov),
            total_cars=sum(dcar), total_ves=sum(dves), total_rt=sum(drt),
            mean_rel=st.mean(rel), median_rel=st.median(rel),
            worse=sum(1 for x in dov if x > 1e-9), better=sum(1 for x in dov if x < -1e-9))

    print("%-6s %7s %12s %11s | %12s %10s %12s | %9s" %
          ("size", "pairs", "TOTAL dOV", "mean dOV", "from cars", "from ves", "from routing",
           "mean d%"))
    for size, s in per_size.items():
        print("%-6d %7d %12.1f %11.2f | %12.1f %10.1f %12.1f | %8.2f%%" %
              (size, s["pairs"], s["total_dov"], s["mean_dov"],
               s["total_cars"], s["total_ves"], s["total_rt"], s["mean_rel"]))

    print("\n=== SHARE of the OV gain, by source (negative share = that term IMPROVED) ===")
    print("%-6s %14s %12s %12s %12s" % ("size", "TOTAL dOV", "cars %", "vessels %", "routing %"))
    for size, s in per_size.items():
        t = s["total_dov"]
        if abs(t) < 1e-9:
            continue
        print("%-6d %14.1f %11.1f%% %11.1f%% %11.1f%%" %
              (size, t, 100 * s["total_cars"] / t, 100 * s["total_ves"] / t,
               100 * s["total_rt"] / t))

    print("\n  A share ABOVE 100%% on one term means another term moved the WRONG way and was")
    print("  paid for out of it -- a trade, not a clean improvement. Read the signed totals")
    print("  above, not only the shares.")

    print("\n=== how often does AWARE actually improve the OV? ===")
    print("%-6s %8s %8s %8s %10s" % ("size", "better", "worse", "equal", "pairs"))
    for size, s in per_size.items():
        eq = s["pairs"] - s["better"] - s["worse"]
        print("%-6d %8d %8d %8d %10d" % (size, s["better"], s["worse"], eq, s["pairs"]))
    print("\n  AWARE contains the BLIND rung, so it can never be worse at the warm start itself;")
    print("  a nonzero 'worse' column would be a defect in the ladder selection, not a result.")

    out = os.path.join(ROOT, "runs", "greedy_ov_decomposition.json")
    json.dump(stamped({str(k): v for k, v in per_size.items()}, __file__), open(out, "w"), indent=1)
    print("\nwrote runs/greedy_ov_decomposition.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
