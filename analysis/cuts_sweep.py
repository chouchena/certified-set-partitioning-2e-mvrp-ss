"""Standalone paired cuts-on/off sweep at n100, compared against the campaign's LB.

STANDALONE by design: imports BlockA and add_rcc, edits no tracked source, so code_hash is
unchanged and the live campaign is unaffected. Budget is DETERMINISTIC TICKS, so the paired
values are load-independent -- co-tenancy inflates wall time but cannot move the numbers.

|H| IS FAMILY-DEPENDENT, and that is a measurement not a preference:
  C   -> cuts bind at |H|=33 (routes_lb=2, sometimes clique=2 and forced)
  R   -> vacuous at |H|=33 and 45; bind at |H|>=60
  RC  -> vacuous at |H|=33 and 45; bind at |H|>=60
The campaign window (|H| 33..28) therefore sits entirely inside the vacuous region for R and RC.
Testing each family where its cuts actually bind is the only way to measure the effect; testing
R at |H|=33 measures nothing, which is the error that produced a 0.00% delta earlier.

RESUMABLE: results are appended to a JSON file, completed (cell, H) pairs are skipped.
"""
import sys, os, time, json
sys.path.insert(0, ".")
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
from build_instance import build
from crossfeed.block_a import BlockA
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from crossfeed.blockA_cpsat import water_lb_scaled, SCALE
from crossfeed.mfree_cuts import add_rcc

OUT = sys.argv[1]
CELLS = [c.strip() for c in sys.argv[2].split(",") if c.strip()]
DET_TL = float(sys.argv[3]) if len(sys.argv) > 3 else 150000.0
SEED, PROX = 20260910, 0.1
HFOR = {"C": 33, "R": 60, "RC": 60}          # where each family's cuts actually bind


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


res = json.load(open(OUT)) if os.path.exists(OUT) else {}
for cell in CELLS:
    Hsize = HFOR[fam(cell)]
    key = f"{cell}|H{Hsize}"
    if key in res:
        print(f"{key}: skip (done)", flush=True); continue
    p = build(cell, 100, wls=0.1, tau="formula", proximity=PROX, time_limit=600)
    s, w, ctx = scarcity_and_weights(p)
    order = sorted(easiness(ctx, w), key=lambda c: -easiness(ctx, w)[c])
    drop = set(order[:100 - Hsize])
    H = [c for c in p.customers if c not in drop]
    wlb = water_lb_scaled(p)[0] / SCALE
    row = {"cell": cell, "fam": fam(cell), "H": Hsize, "wlb": round(wlb, 2)}
    for cuts in (False, True):
        ba = BlockA(p, integral=True, timing_mode="bigM", drop=drop)
        ba.m.parameters.threads = 4
        ba.m.parameters.parallel = 1
        ba.m.parameters.randomseed = SEED
        ba.m.parameters.dettimelimit = DET_TL
        nc = add_rcc(ba, p, H) if cuts else 0
        t0 = time.time()
        r = ba.solve(time_limit=3000, track_progress=False)
        row["on" if cuts else "off"] = dict(
            br=round((r["value"] + wlb), 2) if r["value"] is not None else None,
            proven=bool(r.get("proven")), wall=round(time.time() - t0, 1), ncuts=nc)
    a, b = row["off"]["br"], row["on"]["br"]
    row["delta_pct"] = round((b - a) / a * 100, 2) if a else None
    res[key] = row
    json.dump(stamped(res, __file__), open(OUT, "w"), indent=2)
    print(f"{cell:6} |H|={Hsize:>2}  off={a:9.2f}  on={b:9.2f}  "
          f"delta={row['delta_pct']:+6.2f}%  ({row['on']['ncuts']} cuts)", flush=True)
print("SWEEP DONE", flush=True)
