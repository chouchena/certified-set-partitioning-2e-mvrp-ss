"""one block-A(H) frontier solve in one formulation -> JSON. Used by lb_portfolio."""
import sys, json, time, argparse
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE

ap = argparse.ArgumentParser()
ap.add_argument("--cell", required=True)
ap.add_argument("--size", type=int, default=20)
ap.add_argument("--k", type=int, required=True)
ap.add_argument("--timing", required=True)           # bigM | disagg | indicator
ap.add_argument("--trip-cut", type=int, default=1)
ap.add_argument("--tl", type=int, default=900)
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--out", required=True)
a = ap.parse_args()

p0 = build(a.cell, a.size, wls=0.1, tau="formula", proximity=0.0, time_limit=60)
s, w, ctx = scarcity_and_weights(p0)
_e = easiness(ctx, w)
order = sorted(_e, key=lambda c: -_e[c])
E = set(order[:a.k])
wlb = water_lb_scaled(p0)[0] / SCALE

p = build(a.cell, a.size, wls=0.1, tau="formula", proximity=0.0, time_limit=a.tl + 60)
ba = BlockA(p, integral=True, timing_mode=a.timing, drop=E, trip_cut=bool(a.trip_cut))
try:
    ba.m.parameters.threads = a.workers
except Exception:
    pass

json.dump({"status": "running", "cell": a.cell, "timing": a.timing,
           "trip_cut": bool(a.trip_cut), "k": a.k}, open(a.out, "w"))
t0 = time.time()
r = ba.solve(time_limit=a.tl, track_progress=True)   # capture (t, best_bound, inc) curve (Rule 4)
wall = time.time() - t0
br = round((r["value"] or 0) + wlb, 2) if r["value"] is not None else None
# progress_trace holds the block-A dual-bound curve; shift by +wlb so it is on the
# same scale as block_relax (the reported LB) for the LB-vs-RT evolution plot.
raw_tr = r.get("progress_trace") or []
lb_curve = [{"t": p[0], "lb": round((p[1] + wlb), 2) if p[1] is not None else None,
             "inc": (round(p[2] + wlb, 2) if len(p) > 2 and p[2] is not None else None)}
            for p in raw_tr]
json.dump({"status": "done", "cell": a.cell, "timing": a.timing,
           "trip_cut": bool(a.trip_cut), "k": a.k,
           "zA": r["value"], "proven": bool(r["proven"]),
           "block_relax": br, "wlb": round(wlb, 2), "wall_s": round(wall, 1),
           "lb_curve": lb_curve},
          open(a.out, "w"))
print(f"[{a.timing}{'+cut' if a.trip_cut else ''}] zA={r['value']} proven={r['proven']} "
      f"block_relax={br} {wall:.0f}s", flush=True)
