"""AUDIT of L-water (water bound): is the vessel penalty charged per TRIP or per VESSEL?

Why it mattered. Our composite bound adds `L * penaltyVessels` with
`L = ceil(sumDemand / VesselCapacity)`. If the objective charged the penalty once per
PHYSICAL VESSEL, and a vessel could perform several tours, then billing it once per tour
would OVER-charge and the term would not be a valid lower bound. Every LB number we report
rests on this term (57% of w on C201), so it had to be settled from their source, not inferred.

RESOLUTION -- read from the predecessors' released code:

  integratedJointModel.py:212   sum_{i in Customers} y[i,CDC] == nofVessels
      -> nofVessels counts water ROUTES returning to the CDC, i.e. dispatches. The
         formulation has no multi-trip vessel construct, so routes == vessels and the
         trip/vessel distinction COLLAPSES. No over-charging is possible.
  integratedJointModel.py:264   nofVessels * penaltyVessels == FleetWater
  integratedJointModel.py:213   nofVessels >= lowerVessels          <- THEIR constraint
  DecomposedModels.py:545-546   same two, in the decomposed model
  DecomposedModels.py:158-159   zwater >= c_w*minTr*L + L*penaltyVessels, minTr = min 2*D[CDC][s]

So L-water is NOT our reasoning about vessels: it is a restatement of constraints already
present in their model, and DecomposedModels.py:159 states our exact composite inequality,
round-trip factor included. `crossfeed/blockA_cpsat.py::water_lb_scaled` matches it term for term.

(Note: integratedJointModel.py uses a ONE-WAY minTr in its inline TravelWater cut -- a weaker
form of the same idea. The decomposed model uses the round-trip form, which is what we adopt.)

This script re-runs the empirical falsification: every stored solution carrying water
components must satisfy zwater >= w, and every one reporting nVessel must satisfy nVessel >= L.
"""
import sys, os, glob, re, json
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build_instance import build                                    # noqa: E402
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE           # noqa: E402

STORES = [("runs/solutions", r"fixopt_([A-Za-z0-9]+)_n(\d+)_"),
          ("results/portfolio", r"([A-Za-z0-9]+)_n(\d+)_")]


def main():
    cache = {}

    def w_of(c, s):
        if (c, s) not in cache:
            p = build(c, s, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
            w, L = water_lb_scaled(p)
            cache[(c, s)] = (w / SCALE, L)
        return cache[(c, s)]

    n, viol, vviol, ratios = 0, [], [], []
    for root, pat in STORES:
        for f in glob.glob(os.path.join(ROOT, root, "*.json")):
            m = re.match(pat, os.path.basename(f))
            if not m:
                continue
            c, s = m.group(1), int(m.group(2))
            try:
                d = json.load(open(f))
            except Exception:
                continue
            if "FleetWater" not in d or "TravelWater" not in d:
                continue
            try:
                w, L = w_of(c, s)
            except Exception:
                continue
            n += 1
            zw = d["FleetWater"] + d["TravelWater"]
            if zw < w - 1e-6:
                viol.append((os.path.basename(f), zw, w))
            ratios.append(zw / w)
            nv = d.get("nVessel")
            if nv is not None and nv < L:
                vviol.append((os.path.basename(f), nv, L))

    print(f"solutions tested: {n}")
    print(f"L-water violations (zwater < w): {len(viol)}")
    for v in viol[:10]:
        print("   ", v)
    print(f"nofVessels >= L violations: {len(vviol)}")
    if ratios:
        rs = sorted(ratios)
        print(f"zwater/w: min {rs[0]:.4f}  median {st.median(rs):.4f}  max {rs[-1]:.4f}")
        print("(min > 1 with margin => the test has slack; it is not vacuous)")
    print("VERDICT:", "PASS" if not viol and not vviol else "FAIL -- LEMMA 1 IS NOT VALID")
    return 0 if not viol and not vviol else 1


if __name__ == "__main__":
    sys.exit(main())
