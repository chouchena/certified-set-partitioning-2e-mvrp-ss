"""Is the primal TRUNCATED or CONVERGED at the large sizes? One cell, one pool, two work limits. (d574)

THE QUESTION. The master IP closes its pool to optimality on every |C| = 10 and |C| = 20 cell, but it
is cut off on 32 of 72 runs at |C| = 50 (work limit) and 55 of 72 at |C| = 100 (time limit). Where it
is cut off it still carries a MIP gap -- median 6.0 per cent, worst 18.1. That gap is what a bigger
budget could in principle buy on the PRIMAL side, and nobody has checked whether it actually does.

THE DESIGN, and why it is a fair test. Column generation runs ONCE and the resulting pool is frozen.
The integer program is then solved twice on that same pool: at the stock work limit and at a raised
one, with `m.reset()` between so the second solve starts cold and cannot inherit the first's
incumbent. Anything that differs between the two runs is the budget and nothing else.

WHY A WORK LIMIT AND NOT A TIME LIMIT. Gurobi's WorkLimit counts deterministic work units, so the
comparison reproduces even if another job shares the machine -- which one does today. A time-limited
cell would not be safe to probe under contention, which is why the target is a work-limited one.

PRE-REGISTERED OUTCOME, fixed before the run: the IP street objective at the raised limit, against
the stock limit, on the same pool. Improvement means the primal at this size is budget-limited and
more IP effort is worth buying. No improvement means the pool, not the budget, is what binds -- and
the lever moves to generating better columns.

    python analysis/tep_ip_cap_probe.py R209 --size 50 --stock 120 --raised 480
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import tep_cg_bound as T
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped


def summarise(r):
    return dict(status=r.get("ip_status"), secs=r.get("ip_secs"), street=r.get("ip_street"),
                bound=r.get("ip_bound"), gap_pct=(100.0 * r["ip_gap"]) if r.get("ip_gap") is not None else None,
                cars=r.get("ip_cars"), verified=r.get("verified"), objVal=r.get("objVal"),
                retime=r.get("retime_status"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--stock", type=float, default=120.0); ap.add_argument("--raised", type=float, default=480.0)
    ap.add_argument("--iters", type=int, default=80)
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    delta = T.default_delta(inst)
    print("IP CAP PROBE -- %s n%d, one pool, work limits %.0f then %.0f\n" % (a.cell, a.size, a.stock, a.raised))
    t0 = time.time()
    r = T.run(a.cell, delta, a.iters, ["prio", "ts"], 10, 1000, False, 3_000_000, size=a.size,
              start_states=True, proximity=prox, return_master=True, max_secs=0.0)
    M = r["master"]
    print("  column generation: LP street %.2f, %d columns, %.0f s, status %s"
          % (r["lp_street"], r["cols"], time.time() - t0, r.get("status")), flush=True)
    out = {}
    for tag, work in (("stock", a.stock), ("raised", a.raised)):
        M.m.reset()
        t1 = time.time()
        res = T.master_ip(M, a.cell, a.size, threads=2, timelimit=3600.0, work=work)
        out[tag] = summarise(res); out[tag]["work"] = work; out[tag]["wall"] = round(time.time() - t1, 1)
        print("  %-6s work %5.0f -> IP street %10.2f | gap %6s | cars %s | status %s | %s | %.0f s"
              % (tag, work, res.get("ip_street") or float("nan"),
                 ("%.2f%%" % (100 * res["ip_gap"])) if res.get("ip_gap") is not None else "n/a",
                 res.get("ip_cars"), res.get("ip_status"), res.get("retime_status"), out[tag]["wall"]), flush=True)
    s0, s1 = out["stock"].get("street"), out["raised"].get("street")
    verdict = "no improvement -- the POOL binds, not the budget"
    if s0 and s1 and s1 < s0 - 1e-6:
        verdict = "IMPROVED by %.2f%% on the same pool -- the primal at this size is budget-limited" % (100 * (1 - s1 / s0))
    elif s0 and s1 and s1 > s0 + 1e-6:
        verdict = "WORSE at the raised limit, which can only be solver noise on an unclosed tree"
    print("\n  VERDICT: %s" % verdict)
    p = os.path.join(ROOT, "runs", "oracle", "tep_ip_cap_probe_%s_n%d.json" % (a.cell, a.size))
    json.dump(stamped(dict(cell=a.cell, size=a.size, delta=delta, lp_street=r["lp_street"], cols=r["cols"],
                           arms=out, verdict=verdict)), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
