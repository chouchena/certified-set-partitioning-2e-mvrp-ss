"""The n50 grid, both rounding configurations, against K's Table 4. (d462)

WHY n50 EXISTS NOW. It was missing from both legs. CLAUDE.md section 4 already records the excuse
that was offered once -- "K publish no per-instance n50 data" -- and why it does not hold: it is
equally true of n100, which was covered. It was a choice, and this reverses it.

WHAT THE COMPARATOR IS, AND IT IS NOT PER CELL. K publish n50 pooled by the water-to-street COST
RATIO, in Table 4: four pools (1:10, 1:5, 1:1, 10:1) x two methods, each with a best-known, a time
to incumbent, and a travel/fleet breakdown. There is no per-instance n50 table, so a per-cell claim
is impossible at this size and is not made. Our instances carry travelcostwater 0.1 against
travelcoststreet 1, which is exactly their **1:10** pool -- so that pool, and only that pool, is the
like-for-like comparison. Their other three pools would need the cost ratio varied, which is a
separate study and is not run here.

Their 1:10 figures: Joint best-known 1989.3, LBBD 1941.8, and for LBBD street 1099.4, water 851.6,
street fleet 3.70, water fleet 3.59. LBBD is the better of their two methods and is the comparator,
as at every other size (d456).

CAUTION ON THE COMPONENTS. Their travel columns are raw distances while the objective weights water
by 0.1, so a component comparison must weight ours the same way or it is not like for like. The
table below prints raw distances beside their raw distances and says so.

    python analysis/tep_n50_batch.py
"""
import argparse
import io
import json
import os
import statistics as st
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped

SIZE = 50
CELLS = (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
         + ["RC%d" % i for i in range(201, 209)])
PY = sys.executable
K_1_10 = dict(joint_bk=1989.3, lbbd_bk=1941.8, street=1099.4, water=851.6, fleet_sl=3.70, fleet_wl=3.59)


def paths(cell, cfg):
    sub = "ceil" if cfg == "ceil" else ""
    sol = os.path.join(ROOT, "runs", "postpass", sub, "ownwater_%s_n%d.json" % (cell, SIZE))
    sel = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d_ip%s.json"
                       % (cell, SIZE, "_primal" if cfg == "ceil" else ""))
    return sel, sol


def step(cmd, log):
    with io.open(os.path.join(ROOT, log), "w", encoding="utf-8", errors="replace") as fh:
        return subprocess.call(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)


def components(cell, sol):
    inst = V.load_instance(cell, SIZE, k_proximity(SIZE))
    D, CDC = inst.D, inst.CDC
    hub = {int(x): int(h) for x, h in zip(sol["vi"], sol["hubs"])}
    ts = set(hub)
    street = sum((D[i][hub[i]] + D[hub[i]][j]) if i in ts else D[i][j]
                 for i, j in ((int(x), int(y)) for x, y in sol["xij"]))
    water = sum(D[CDC if int(x) == CDC else hub[int(x)]][CDC if int(y) == CDC else hub[int(y)]]
                for x, y in sol["yij"])
    return street, water


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="*", default=None)
    ap.add_argument("--ip-work", type=float, default=120.0)
    ap.add_argument("--configs", default="floor,ceil")
    ap.add_argument("--cg-secs", type=float, default=420.0,
                    help="wall on the PRIMAL column generation only; the bound leg keeps none")
    a = ap.parse_args()
    cells = a.cells or CELLS
    cfgs = a.configs.split(",")
    rows = []
    for c in cells:
        rec = dict(cell=c)
        for cfg in cfgs:
            sel, sol = paths(c, cfg)
            pr = ["--primal-round"] if cfg == "ceil" else []
            if not os.path.exists(sel):
                # WALL ON THE PRIMAL'S COLUMN GENERATION, and why it is admissible here. R204's
                # ceil CG sat in a misprice loop for ten minutes at n50 with no wall and killed the
                # batch. This stage is a COLUMN GENERATOR for the primal, not a bound instrument:
                # its output is a trip pool that the chaining and verifier3 check independently, so
                # an unconverged stop costs solution quality and cannot cost validity. The BOUND
                # leg keeps no wall and must still come back `proven` -- that separation is the
                # point, and it is disclosed rather than silently applied.
                rc = step([PY, "analysis/tep_cg_bound.py", c, "--size", str(SIZE), "--ip",
                           "--start-states", "--ip-work", str(a.ip_work),
                           "--max-secs", str(a.cg_secs)] + pr,
                          "logs/n50_%s_cg_%s.out" % (cfg, c))
                if rc != 0 or not os.path.exists(sel):
                    rec[cfg + "_fail"] = "master/IP exit %s" % rc; continue
            if not os.path.exists(sol):
                rc = step([PY, "analysis/tep_chain_own_water.py", c, "--size", str(SIZE)] + pr,
                          "logs/n50_%s_chain_%s.out" % (cfg, c))
                if rc != 0 or not os.path.exists(sol):
                    rec[cfg + "_fail"] = "chain/verify exit %s" % rc; continue
            d = json.load(io.open(sol, encoding="utf-8"))
            if not d.get("_provenance", {}).get("code_hash"):
                rec[cfg + "_fail"] = "no code_hash"; continue
            s, w = components(c, d)
            rec[cfg] = float(d["objVal"]); rec[cfg + "_cars"] = int(d["nCars"])
            rec[cfg + "_vessels"] = int(d["nVessel"]); rec[cfg + "_street"] = s; rec[cfg + "_water"] = w
        have = [(k, rec[k]) for k in cfgs if k in rec]
        if have:
            best_cfg, best = min(have, key=lambda x: x[1])
            rec.update(best=best, best_cfg=best_cfg)
            print("  %-6s floor %10s  ceil %10s  -> %9.1f (%s, %d cars)"
                  % (c, ("%.1f" % rec["floor"]) if "floor" in rec else "-",
                     ("%.1f" % rec["ceil"]) if "ceil" in rec else "-", best, best_cfg,
                     rec[best_cfg + "_cars"]), flush=True)
        else:
            print("  %-6s FAILED both configurations" % c, flush=True)
        rows.append(rec)
        json.dump(stamped(dict(size=SIZE, k_pool="1:10", k=K_1_10, rows=rows)),
                  io.open(os.path.join(ROOT, "runs", "oracle", "tep_n50_batch.json"), "w", encoding="utf-8"),
                  indent=1, default=str)

    ok = [r for r in rows if "best" in r]
    print("\n  %d of %d cells produced a verified solution" % (len(ok), len(rows)))
    if not ok:
        return 1
    m = st.mean(r["best"] for r in ok)
    ms = st.mean(r[r["best_cfg"] + "_street"] for r in ok)
    mw = st.mean(r[r["best_cfg"] + "_water"] for r in ok)
    mc = st.mean(r[r["best_cfg"] + "_cars"] for r in ok)
    mv = st.mean(r[r["best_cfg"] + "_vessels"] for r in ok)
    print("\n  n50 against K Table 4, pool 1:10 (our cost ratio). Travel figures are RAW distances.")
    print("  %-22s %10s %10s %9s" % ("", "ours", "K LBBD", "vs them"))
    print("  %-22s %10.1f %10.1f %+8.2f%%" % ("objective (mean)", m, K_1_10["lbbd_bk"], 100.0 * (m / K_1_10["lbbd_bk"] - 1)))
    print("  %-22s %10.1f %10.1f %+8.2f%%" % ("street travel", ms, K_1_10["street"], 100.0 * (ms / K_1_10["street"] - 1)))
    print("  %-22s %10.1f %10.1f %+8.2f%%" % ("water travel", mw, K_1_10["water"], 100.0 * (mw / K_1_10["water"] - 1)))
    print("  %-22s %10.2f %10.2f %+8.2f%%" % ("street fleet", mc, K_1_10["fleet_sl"], 100.0 * (mc / K_1_10["fleet_sl"] - 1)))
    print("  %-22s %10.2f %10.2f %+8.2f%%" % ("water fleet", mv, K_1_10["fleet_wl"], 100.0 * (mv / K_1_10["fleet_wl"] - 1)))
    print("  (also vs their Joint best-known %.1f: %+.2f%%)" % (K_1_10["joint_bk"], 100.0 * (m / K_1_10["joint_bk"] - 1)))
    if len(ok) < len(CELLS):
        print("  MEANS ARE OVER A SUBSET (%d of %d cells) and are provisional." % (len(ok), len(CELLS)))
    nc = sum(1 for r in ok if r.get("best_cfg") == "ceil")
    print("  ceil is the chosen configuration on %d of %d" % (nc, len(ok)))
    print("  wrote runs/oracle/tep_n50_batch.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
