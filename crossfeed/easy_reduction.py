"""
easy_reduction.py -- "easy customer" reduction for a tighter block-A bound.

Idea (user, 2026-09-02): some customers are trivially servable -- cheap on
whatever resource is SCARCE for this instance. Remove them from block A
entirely (no resources charged), solve the smaller H-problem to PROVEN
optimality (which the full block A can't reach -- it plateaus at ~45%
internal gap on the C-family), and report

    z_joint  >=  z_A(H)*  +  w(total demand)

VALID because (a) serving a subset costs no more than the full set
(triangle inequality: shortcut past the removed customers; fewer customers
never forces more vehicles), and (b) w is Karademir's water LB on the FULL
demand. The removed customers' easiness only affects TIGHTNESS, not
validity.

One composite easiness score, weights DERIVED from a resource-scarcity
precalc (not tuned):

  scarcity s_r  in [0,1], ~1 = tight:
    car     = Sigma q / (Q_car    * ceil(Sigma q / Q_car))
    vessel  = Sigma q / (Q_vessel * ceil(Sigma q / Q_vessel))
    time    = 1 - mean_i( q_i * TW_width_i ) / (horizon * Sigma q)     (demand-weighted TW tightness)
    geo     = demand-weighted mean nearest-neighbour distance / bbox diagonal
  weights   w_r = s_r / sum s_r          (scarce resource -> high weight)

  footprint f_r,i in [0,1] (customer i's normalised use of resource r):
    car/vessel = q_i / Q
    time       = (service_i + 2*dist_to_nearest_i) / TW_width_i
    geo        = dist_to_2nd_nearest_i / bbox_diag

  easiness_i = sum_r w_r * (1 - clip(f_r,i, 0, 1))     (high = cheap on the scarce resources)

Greedy fail-fast: drop the k easiest for k = 0,1,2,...; solve block A (CP-SAT)
on H; the deliverable is  max_k [ z_A(H)*_proven + w ]  vs the current
un-reduced bound.
"""
from __future__ import annotations
import argparse
import math
import sys

sys.path.insert(0, ".")
import time as _time
import numpy as np
from build_instance import build
from crossfeed.blockA_cpsat import solve_blockA_cpsat, water_lb_scaled, SCALE
from crossfeed.block_a import BlockA


def _bound_cpsat(name, size, drop, tl, workers):
    r = solve_blockA_cpsat(name, size, time_limit=tl, workers=workers, log=True, drop=drop)
    return {"lb": r["blockA_lb"], "inc": r["blockA_incumbent"], "proven": r["proven"],
            "status": r["status"], "wall": r["wall_s"], "carLB_H": r["car_lb_H"],
            "nH": r["n_customers_H"]}


def _bound_cplex(name, size, drop, tl, workers, timing="bigM"):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl)
    ba = BlockA(p, integral=True, timing_mode=timing, drop=drop)
    try:
        ba.m.parameters.threads = workers
    except Exception:
        pass
    t0 = _time.time()
    r = ba.solve(time_limit=tl, track_progress=True)   # Rule 4: capture (t,bound,inc) curve
    demH = sum(p.nodes[c].demand for c in p.customers if c not in set(drop or []))
    return {"lb": r["value"], "inc": r.get("incumbent"), "proven": bool(r.get("proven")),
            "status": r.get("status", ""), "wall": round(_time.time() - t0, 1),
            "carLB_H": math.ceil(demH / p.CarCapacity),
            "nH": len(p.customers) - len(set(drop or [])),
            "trace": r.get("progress_trace") or []}


BOUNDERS = {"cpsat": _bound_cpsat,
            "cplex": lambda n, s, d, tl, w: _bound_cplex(n, s, d, tl, w, "bigM"),
            "cplex_ind": lambda n, s, d, tl, w: _bound_cplex(n, s, d, tl, w, "indicator")}


def scarcity_and_weights(p):
    D, nd = p.DistMatrix, p.nodes
    C = list(p.customers)
    q = np.array([nd[c].demand for c in C], float)
    tw = np.array([nd[c].latest - nd[c].earliest for c in C], float)
    horizon = nd[p.CDC].latest - nd[p.CDC].earliest
    Qc, Qv = p.CarCapacity, p.VesselCapacity
    xs = np.array([nd[c].xcor for c in C]); ys = np.array([nd[c].ycor for c in C])
    cc = np.array([[math.hypot(xs[i]-xs[j], ys[i]-ys[j]) for j in range(len(C))]
                   for i in range(len(C))])
    np.fill_diagonal(cc, np.inf)
    nn = np.sort(cc, axis=1)          # nn[:,0] nearest, nn[:,1] 2nd
    diag = math.hypot(xs.ptp() if hasattr(xs, 'ptp') else np.ptp(xs),
                      np.ptp(ys)) or 1.0

    s_car = q.sum() / (Qc * math.ceil(q.sum() / Qc))
    s_ves = q.sum() / (Qv * math.ceil(q.sum() / Qv))
    s_time = 1.0 - float(np.sum(q * tw) / (horizon * q.sum()))
    s_geo = float(np.sum(q * nn[:, 0]) / q.sum()) / diag
    s = {"car": s_car, "vessel": s_ves, "time": max(0.0, s_time), "geo": s_geo}
    tot = sum(s.values()) or 1.0
    w = {k: v / tot for k, v in s.items()}
    return s, w, dict(C=C, q=q, tw=tw, nn=nn, diag=diag, Qc=Qc, Qv=Qv, D=D, nd=nd,
                      CDC=p.CDC, satellites=list(p.satellites))


def easiness(ctx, w):
    C, q, tw, nn, diag = ctx["C"], ctx["q"], ctx["tw"], ctx["nn"], ctx["diag"]
    D, nd, Sats = ctx["D"], ctx["nd"], ctx["satellites"]
    Qc, Qv = ctx["Qc"], ctx["Qv"]
    out = {}
    for idx, c in enumerate(C):
        d_near = nn[idx, 0]
        f_car = q[idx] / Qc
        f_ves = q[idx] / Qv
        f_time = (nd[c].serviceTime + 2 * d_near) / max(1.0, tw[idx])
        f_geo = nn[idx, 1] / diag
        f = {"car": f_car, "vessel": f_ves, "time": f_time, "geo": f_geo}
        out[c] = sum(w[r] * (1.0 - min(1.0, max(0.0, f[r]))) for r in w)
    return out


def run(name, size, max_drop=6, tl=150, workers=4, bounders=("cpsat",), k_start=0):
    p = build(name, size, wls=0.1, tau="formula", proximity=0.0, time_limit=tl)
    s, w, ctx = scarcity_and_weights(p)
    E = easiness(ctx, w)
    order = sorted(E, key=lambda c: -E[c])      # easiest first
    wlb = water_lb_scaled(p)[0] / SCALE

    print(f"\n=== {name}/{size}   bounders={bounders} ===")
    print(f"scarcity: " + "  ".join(f"{k}={v:.3f}" for k, v in s.items()))
    print(f"weights : " + "  ".join(f"{k}={v:.3f}" for k, v in w.items()))
    print(f"easiness rank (easiest->hardest): {order}")
    print(f"water LB (full demand) = {wlb:.2f}\n")
    print(f"{'bounder':>10} {'k':>2} {'|H|':>4} {'carLB':>6} {'status':>18} "
          f"{'zA(H)_LB':>9} {'blockRelax':>11} {'proven':>7} {'wall_s':>7}")

    rows = []
    for bname in bounders:
        fn = BOUNDERS[bname]
        for k in range(k_start, max_drop + 1):
            drop = set(order[:k])
            r = fn(name, size, drop, tl, workers)
            br = (r["lb"] + wlb) if r["lb"] is not None else None
            rec = {"bounder": bname, "k": k, "drop": sorted(drop), **r,
                   "block_relax": round(br, 2) if br is not None else None}
            # Rule 4: persist the bound-over-time curve on the block_relax scale (+wlb)
            tr = rec.pop("trace", None) or []
            rec["lb_curve"] = [{"t": q[0],
                                "lb": round(q[1] + wlb, 2) if q[1] is not None else None,
                                "inc": round(q[2] + wlb, 2) if len(q) > 2 and q[2] is not None else None}
                               for q in tr]
            try:                                    # replication provenance in the result file itself
                from analysis.provenance import stamp as _pstamp
                rec["provenance"] = _pstamp(seed=k_start, cores=workers, solver=bname)
            except Exception:
                rec["provenance"] = None
            rows.append(rec)
            print(f"{bname:>10} {k:>2} {r['nH']:>4} {r['carLB_H']:>6} "
                  f"{str(r['status'])[:18]:>18} {str(r['lb']):>9} "
                  f"{str(rec['block_relax']):>11} {str(r['proven']):>7} {r['wall']:>7}")
            import json
            json.dump(rows, open(f"crossfeed/easy_reduction_{name}_n{size}.json", "w"),
                      indent=2, default=str)

    print(f"\nun-reduced un-proven CP-SAT baseline (full sweep): C203~384.6")
    for bname in bounders:
        sub = [x for x in rows if x["bounder"] == bname and x["block_relax"] is not None]
        pr = [x for x in sub if x["proven"]]
        if sub:
            best = max(sub, key=lambda x: x["block_relax"])
            print(f"  {bname}: best any k={best['k']} -> {best['block_relax']} "
                  f"(proven={best['proven']}, {best['wall']}s)")
            if pr:
                bp = max(pr, key=lambda x: x["block_relax"])
                print(f"  {bname}: best PROVEN k={bp['k']} -> {bp['block_relax']} ({bp['wall']}s)")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C203")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--max-drop", type=int, default=6)
    ap.add_argument("--tl", type=int, default=150)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--bounders", default="cpsat", help="comma list: cpsat,cplex,cplex_ind")
    ap.add_argument("--k-start", type=int, default=0)
    a = ap.parse_args()
    for nm in a.cells.split(","):
        run(nm.strip(), a.size, a.max_drop, a.tl, a.workers,
            tuple(b.strip() for b in a.bounders.split(",")), a.k_start)
