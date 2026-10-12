"""
dual_mining.py -- FAIL-FAST check for research idea #6:

    Mine a valid GLOBAL dual bound from the restricted LP sub-solves that a
    fix-and-optimize matheuristic (solver/engines/fixopt.py) generates.

Each fixopt restricted problem is  min c.x  s.t. A x >= b,  x_F = zhat_F .
LP-relax it. Its value phi_LP(zhat) is convex in the fixing point zhat, and
by LP duality the vector  mu  of duals on the fixing equalities  x_F = zhat_F
is a subgradient of phi_LP at zhat.  Hence for every collected sub-solve k

    cut_k(z) :=  phi_k + sum_{v in F_k} mu_{k,v} (z_v - zhat_{k,v})   <=  phi_LP(z)

is a valid affine UNDER-estimator of phi_LP, and since phi_LP(z*) <= phi_MILP(z*)
= (true optimum) at the true optimal binary vector z*, each cut is a valid
lower bound structure:  opt >= max_k cut_k(z*).

Two master problems are then solved over the (LP-relaxed) fixing variables z:
  * MASTER-A  (the "real" idea): z-only master -- the joint model's LINEAR
    structural constraints on the binaries (degree / flow / sum_p vip = vi /
    vi >= x[i,0] / water in-out / vessel count) + one cut per sub-solve,
    minimise eta.  Its optimum is a valid global lower bound.
  * MASTER-B  (diagnostic ceiling): the full monolithic joint LP relaxation
    with the SAME cuts added as  zObj >= cut_k(z) .  Trivially >= L0; shows the
    most the harvested cuts could ever buy on top of the one-shot LP.

L0  = monolithic joint LP relaxation (joint_synchronized_cplex lp_relax=True).
zstar = true MILP optimum.
Reported: gap closed = (mined - L0) / (zstar - L0) for each master / config.

VALIDITY SELF-CHECK: every mined bound must be <= zstar + tol.  A violation
means a bug in the dual extraction or the master -- it is reported, not hidden
(collaboration rule: an invalid bound is a defect to surface).

Self-contained: imports only build_instance, joint_model_cplex, runlog.
Does NOT modify fixopt.py / solver/ / joint_model_cplex.py / build_instance.py.

Run:
    PYTHONUTF8=1 python -m crossfeed.dual_mining
    PYTHONUTF8=1 python -m crossfeed.dual_mining --instances C201:6,C201:8,R201:8 --iters 30
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from docplex.mp.model import Model
from docplex.mp.relax_linear import LinearRelaxer

from build_instance import build
from joint_model_cplex import build_joint_model, joint_synchronized_cplex
from runlog import RunLogger

TOL = 1e-4


# ---------------------------------------------------------------------------
# instance structural data (reconstructed EXACTLY as build_joint_model does)
# ---------------------------------------------------------------------------
@dataclass
class Struct:
    Customers: list
    Satellites: list
    CDC: int
    SetCd: list
    setCw: list
    arcList: list           # street arcs (i,j)
    waterArcs: list          # water arcs (i,j) over setCw
    lowerVessels: int
    D: object
    nd: object


def structure(p) -> Struct:
    Customers = list(p.customers)
    Satellites = list(p.satellites)
    CDC = p.CDC
    D = p.DistMatrix
    nd = p.nodes
    SetCd = [0] + Customers
    setCw = [CDC] + Customers
    arcList = []
    for i in SetCd:
        for j in SetCd:
            if i == j:
                continue
            if nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest:
                arcList.append((i, j))
    waterArcs = [(i, j) for i in setCw for j in setCw if i != j]
    sumDemand = sum(nd[i].demand for i in Customers)
    lowerVessels = math.ceil(sumDemand / p.VesselCapacity)
    return Struct(Customers, Satellites, CDC, SetCd, setCw, arcList, waterArcs,
                  lowerVessels, D, nd)


# ---------------------------------------------------------------------------
# incumbent -> zhat (a value for every binary decision)
# ---------------------------------------------------------------------------
@dataclass
class ZHat:
    vi: dict          # i -> 0/1
    vip: dict         # (i,p) -> 0/1
    x: dict           # (i,j) -> 0/1   over arcList
    y: dict           # (i,j) -> 0/1   over waterArcs


def zhat_from_solution(sol, st: Struct) -> ZHat:
    vset = set(sol["vi"])
    hubs = sol.get("hubs") or []
    hub = {}
    for idx, i in enumerate(sol["vi"]):
        if idx < len(hubs):
            hub[i] = hubs[idx]
    xset = set((i, j) for i, j in sol["xij"])
    yset = set((i, j) for i, j in sol.get("yij", []))
    vi = {i: (1 if i in vset else 0) for i in st.Customers}
    vip = {(i, p): (1 if (i in vset and hub.get(i) == p) else 0)
           for i in st.Customers for p in st.Satellites}
    x = {(i, j): (1 if (i, j) in xset else 0) for (i, j) in st.arcList}
    y = {(i, j): (1 if (i, j) in yset else 0) for (i, j) in st.waterArcs}
    return ZHat(vi, vip, x, y)


# ---------------------------------------------------------------------------
# one restricted LP sub-solve  ->  harvest (phi, {var_key: mu})
# ---------------------------------------------------------------------------
@dataclass
class Cut:
    phi: float
    mu: dict          # key -> dual  ; key is ("v",i) / ("vip",i,p) / ("x",i,j) / ("y",i,j)
    zhat: dict        # same keys -> fixed value
    n_fixed: int
    mode: str
    S: tuple


def _fix_name(key) -> str:
    return "FX_" + "_".join(str(t) for t in key)


def restricted_subsolve(p, st: Struct, zh: ZHat, S: set, mode: str) -> Cut | None:
    """Build a fresh joint model, pin the binaries not touching S to zhat
    (mode='full' pins every non-touching binary incl. the 0s; mode='freeze'
    mirrors fixopt._freeze -- vi of retained customers + interior 'on' arcs
    only), LP-relax, solve, and read the duals on the fixing equalities."""
    H = build_joint_model(p)
    m = H.m
    CDC = st.CDC
    fixed_keys = {}          # key -> zhat value

    def touches(*nodes):
        return any(nd in S for nd in nodes)

    if mode == "full":
        for i in st.Customers:
            if not touches(i):
                fixed_keys[("v", i)] = zh.vi[i]
                for pp in st.Satellites:
                    fixed_keys[("vip", i, pp)] = zh.vip[(i, pp)]
        for (i, j) in st.arcList:
            if not touches(i, j):
                fixed_keys[("x", i, j)] = zh.x[(i, j)]
        for (i, j) in st.waterArcs:
            if not touches(i, j):
                fixed_keys[("y", i, j)] = zh.y[(i, j)]
    elif mode == "freeze":
        # mirror solver/engines/fixopt.py::_freeze
        for i in st.Customers:
            if not touches(i):
                fixed_keys[("v", i)] = zh.vi[i]
        for (i, j) in st.arcList:
            if zh.x[(i, j)] == 1 and i != 0 and j != 0 and not touches(i, j):
                fixed_keys[("x", i, j)] = 1
        for (i, j) in st.waterArcs:
            if zh.y[(i, j)] == 1 and i != CDC and j != CDC and not touches(i, j):
                fixed_keys[("y", i, j)] = 1
    else:
        raise ValueError(mode)

    for key, val in fixed_keys.items():
        tag = key[0]
        if tag == "vip":
            var = H.vip[(key[1], key[2])]
        elif tag == "v":
            var = H.vi[key[1]]
        elif tag == "x":
            var = H.xij[(key[1], key[2])]
        else:
            var = H.y[(key[1], key[2])]
        m.add_constraint(var == val, _fix_name(key))

    rel = LinearRelaxer.make_relaxed_model(m)
    rel.parameters.threads = 1
    s = rel.solve()
    if s is None:
        return None
    phi = s.objective_value
    mu = {}
    for key in fixed_keys:
        c = rel.get_constraint_by_name(_fix_name(key))
        if c is None:
            return None
        mu[key] = c.dual_value
    zhat = dict(fixed_keys)
    return Cut(phi=phi, mu=mu, zhat=zhat, n_fixed=len(fixed_keys), mode=mode, S=tuple(sorted(S)))


# ---------------------------------------------------------------------------
# MASTER-A : z-only structural master  ->  valid global lower bound
# ---------------------------------------------------------------------------
def master_A(p, st: Struct, cuts: list[Cut]) -> dict:
    m = Model(name="dualmine_masterA")
    m.parameters.threads = 1
    C, Sat, CDC = st.Customers, st.Satellites, st.CDC

    v = {i: m.continuous_var(0, 1, f"v.{i}") for i in C}
    vip = {(i, pp): m.continuous_var(0, 1, f"vip.{i}.{pp}") for i in C for pp in Sat}
    x = {(i, j): m.continuous_var(0, 1, f"x.{i}.{j}") for (i, j) in st.arcList}
    y = {(i, j): m.continuous_var(0, 1, f"y.{i}.{j}") for (i, j) in st.waterArcs}
    nCars = m.continuous_var(0, len(C), "nofCars")
    nVess = m.continuous_var(0, len(C), "nofVessels")
    eta = m.continuous_var(0, m.infinity, "eta")

    arcset = set(st.arcList)
    for i in C:
        m.add_constraint(m.sum(x[i, j] for j in st.SetCd if (i, j) in arcset) == 1)
        m.add_constraint(m.sum(x[j, i] for j in st.SetCd if (j, i) in arcset) == 1)
    m.add_constraint(m.sum(x[i, 0] for i in C if (i, 0) in arcset) == nCars)
    m.add_constraint(m.sum((x[i, 0] if (i, 0) in arcset else 0)
                           - (x[0, i] if (0, i) in arcset else 0) for i in C) == 0)
    for i in C:
        if (i, 0) in arcset:
            m.add_constraint(v[i] >= x[i, 0])
    for i in C:
        m.add_constraint(m.sum(vip[i, pp] for pp in Sat) == v[i])
    for i in C:
        m.add_constraint(m.sum(y[i, j] for j in st.setCw if i != j) == v[i])
        m.add_constraint(m.sum(y[j, i] for j in st.setCw if i != j) == v[i])
    m.add_constraint(m.sum(y[i, CDC] - y[CDC, i] for i in C) == 0)
    m.add_constraint(m.sum(y[i, CDC] for i in C) == nVess)
    m.add_constraint(nVess >= st.lowerVessels)

    def var_for(key):
        if key[0] == "v":
            return v[key[1]]
        if key[0] == "vip":
            return vip[(key[1], key[2])]
        if key[0] == "x":
            return x[(key[1], key[2])]
        return y[(key[1], key[2])]

    for k in cuts:
        expr = k.phi + m.sum(k.mu[key] * (var_for(key) - k.zhat[key]) for key in k.mu)
        m.add_constraint(eta >= expr)

    m.minimize(eta)
    s = m.solve()
    return {"bound": (s.objective_value if s else None),
            "status": m.solve_details.status if m.solve_details else "none"}


# ---------------------------------------------------------------------------
# MASTER-B : full joint LP relaxation + the same cuts on zObj
# ---------------------------------------------------------------------------
def master_B(p, cuts: list[Cut]) -> dict:
    H = build_joint_model(p)
    rel = LinearRelaxer.make_relaxed_model(H.m)
    rel.parameters.threads = 1
    zobj = rel.get_var_by_name("zObj")

    def var_for(key):
        if key[0] == "v":
            return rel.get_var_by_name(f"v.{key[1]}")
        if key[0] == "vip":
            return rel.get_var_by_name(f"vip.{key[1]}.{key[2]}")
        if key[0] == "x":
            return rel.get_var_by_name(f"x.{key[1]}.{key[2]}")
        return rel.get_var_by_name(f"Y[{key[1]},{key[2]}]")

    for k in cuts:
        expr = k.phi + rel.sum(k.mu[key] * (var_for(key) - k.zhat[key]) for key in k.mu)
        rel.add_constraint(zobj >= expr)
    s = rel.solve()
    return {"bound": (s.objective_value if s else None),
            "status": rel.solve_details.status if rel.solve_details else "none"}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
CONFIGS = [
    ("full_k2", "full", 2),
    ("full_k4", "full", 4),
    ("freeze_k3", "freeze", 3),
]


def run_instance(name: str, n: int, iters: int, seed: int) -> dict:
    print(f"\n=== {name} n={n} ===", flush=True)
    rng = random.Random(seed)
    # one RunLogger PER instance: RunLogger tracks a single global
    # best_incumbent/best_bound and guard-1 auto-quarantines if any logged
    # bound exceeds it -- sharing a logger across instances would compare
    # instance B's L0 against instance A's zstar and trip a false quarantine.
    lg = RunLogger(f"dual_mining_{name}_n{n}", instance=name, size=n, seed=seed,
                   config={"engine": "dual_mining", "wls": 0.1, "tau": "formula",
                           "proximity": 0.0, "iters": iters})

    p = build(name, n, wls=0.1, tau="formula", time_limit=120)
    st = structure(p)

    p_lp = build(name, n, wls=0.1, tau="formula", time_limit=120)
    L0 = joint_synchronized_cplex(p_lp, lp_relax=True)["lp_bound"]

    p_mip = build(name, n, wls=0.1, tau="formula", time_limit=120)
    rj = joint_synchronized_cplex(p_mip, time_limit=120, mip_gap=0.0)
    zstar = rj["objVal"]
    sol = rj["solution"]
    lg.incumbent(zstar, trigger="joint_milp_opt", extra={"status": rj["status"]})
    lg.bound(L0, trigger="joint_lp_L0")

    zh = zhat_from_solution(sol, st)
    print(f"  L0={L0}  zstar={zstar}  LP gap={zstar - L0:.3f}", flush=True)

    denom = zstar - L0
    res = {"instance": f"{name}:{n}", "L0": L0, "zstar": zstar, "lp_gap": denom,
           "configs": {}, "all_cuts": {}, "validity_ok": True, "violations": []}

    all_cuts: list[Cut] = []
    for label, mode, k in CONFIGS:
        cuts: list[Cut] = []
        t0 = time.time()
        n_infeas = 0
        for _ in range(iters):
            S = set(rng.sample(st.Customers, min(k, len(st.Customers))))
            c = restricted_subsolve(p, st, zh, S, mode)
            if c is None:
                n_infeas += 1
                continue
            cuts.append(c)
        wall = time.time() - t0
        if not cuts:
            print(f"  [{label}] no cuts harvested", flush=True)
            continue
        avg_fixed = sum(c.n_fixed for c in cuts) / len(cuts)
        mA = master_A(p, st, cuts)
        mB = master_B(p, cuts)
        bA, bB = mA["bound"], mB["bound"]
        gcA = (bA - L0) / denom if (bA is not None and denom > 1e-9) else None
        gcB = (bB - L0) / denom if (bB is not None and denom > 1e-9) else None

        # validity self-check
        for tag, b in (("masterA", bA), ("masterB", bB)):
            if b is not None and b > zstar + max(TOL, abs(zstar) * TOL):
                res["validity_ok"] = False
                res["violations"].append(f"{label}/{tag}: bound {b:.4f} > zstar {zstar:.4f}")

        res["configs"][label] = {
            "n_cuts": len(cuts), "n_infeas": n_infeas, "avg_fixed": round(avg_fixed, 1),
            "wall_s": round(wall, 1),
            "masterA": bA, "masterB": bB,
            "gap_closed_A": gcA, "gap_closed_B": gcB,
        }
        all_cuts.extend(cuts)
        lg.bound(bA if bA else L0, trigger=f"masterA:{label}",
                 extra={"n_cuts": len(cuts), "masterB": bB})
        print(f"  [{label}] cuts={len(cuts):3d} avgFixed={avg_fixed:4.1f} "
              f"masterA={_f(bA)} ({_pct(gcA)})  masterB={_f(bB)} ({_pct(gcB)})  {wall:.1f}s",
              flush=True)

    # combined master over ALL cuts
    if all_cuts:
        mA = master_A(p, st, all_cuts)
        mB = master_B(p, all_cuts)
        bA, bB = mA["bound"], mB["bound"]
        gcA = (bA - L0) / denom if (bA is not None and denom > 1e-9) else None
        gcB = (bB - L0) / denom if (bB is not None and denom > 1e-9) else None
        for tag, b in (("masterA", bA), ("masterB", bB)):
            if b is not None and b > zstar + max(TOL, abs(zstar) * TOL):
                res["validity_ok"] = False
                res["violations"].append(f"combined/{tag}: bound {b:.4f} > zstar {zstar:.4f}")
        res["all_cuts"] = {"n_cuts": len(all_cuts), "masterA": bA, "masterB": bB,
                           "gap_closed_A": gcA, "gap_closed_B": gcB}
        lg.bound(bA if bA else L0, trigger="masterA:combined",
                 extra={"n_cuts": len(all_cuts), "masterB": bB})
        print(f"  [COMBINED] cuts={len(all_cuts):3d}  "
              f"masterA={_f(bA)} ({_pct(gcA)})  masterB={_f(bB)} ({_pct(gcB)})", flush=True)

    print(f"  validity self-check: {'OK' if res['validity_ok'] else 'FAILED -> ' + '; '.join(res['violations'])}",
          flush=True)
    lg.close(status="failfast_done", run_valid=res["validity_ok"], verified=False,
             final_incumbent=zstar, final_bound=(res["all_cuts"].get("masterA") or L0))
    return res


def _f(x):
    return "None" if x is None else f"{x:.3f}"


def _pct(x):
    return "n/a" if x is None else f"{100 * x:+.1f}% gap closed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="C201:6,C201:8,R201:8")
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    pairs = []
    for tok in a.instances.split(","):
        nm, n = tok.split(":")
        pairs.append((nm.strip(), int(n)))

    results = []
    for nm, n in pairs:
        results.append(run_instance(nm, n, a.iters, a.seed))

    # verdict
    print("\n" + "=" * 70)
    print("FAIL-FAST VERDICT")
    print("=" * 70)
    best_A = []
    for r in results:
        cand = [c["gap_closed_A"] for c in r["configs"].values() if c["gap_closed_A"] is not None]
        if r["all_cuts"]:
            cand.append(r["all_cuts"]["gap_closed_A"])
        best = max(cand) if cand else None
        best_A.append(best)
        print(f"  {r['instance']:10s}  L0={r['L0']:.2f}  zstar={r['zstar']:.2f}  "
              f"best MASTER-A gap closed = {_pct(best)}   validity={'OK' if r['validity_ok'] else 'FAIL'}")
    ok_valid = all(r["validity_ok"] for r in results)
    meaningful = sum(1 for b in best_A if b is not None and b > 0.15)
    print()
    if not ok_valid:
        print("  >>> STOP: validity self-check FAILED on at least one instance. "
              "Dual extraction / master has a bug. Do not proceed.")
    elif meaningful >= 2:
        print(f"  >>> GO: MASTER-A closes >15% of the LP gap on {meaningful}/{len(results)} instances.")
    else:
        print(f"  >>> NO-GO: MASTER-A closes >15% of the LP gap on only {meaningful}/{len(results)} "
              "instances -- mined bound ~= monolithic LP. Idea #6 is dead.")

    import json
    out = os.path.join(_ROOT, "crossfeed", "dual_mining_results.json")
    json.dump(results, open(out, "w"), indent=2, default=str)
    print(f"\n  results -> {out}")


if __name__ == "__main__":
    main()
