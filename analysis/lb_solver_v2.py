"""UNIFORM LB SOLVER v2 -- the defensible, uniform-on-policy variant. (author 2026-10-01)

One recipe on every cell, folding in four things agreed in design (target d637):

  1. SEEDED START. Each run starts with BOTH bounds in hand: the AB4 arithmetic floor as the
     best-known LB, and an INTRA-RUN CONSTRUCTOR OV -- a verified feasible primal built by the
     K-free greedy (cost_aware_greedy.construct_best_of) at the top of the run, instantly. So the
     per-rung gain gate is armed from rung 1, not rung 2. The OV is refined (min) by master_ip as
     columns accrue. No banked OV, no K: the OV is this run's own construction.

  2. UNIFORM PER-RUNG GAIN GATE. Before a rung runs, its max gain over the best-known certified LB
     is at most OV_intrarun - BK_LB (lb <= OPT <= OV). Below GAIN_CEILING_MIN the rung provably
     cannot earn a unit and is SKIPPED (validation/PREREG_uniform_gain_gate.md, smoked 2026-10-01).

  3. COMPILE VALIDITY + SAFETY over RT-expensive rungs. Two layers, both cheap, gating anything
     expensive: a STATIC py_compile of the whole import path before any launch, and a per-rung
     BUILD_ONLY dry-run that constructs the master + pricer and checks feasibility without the CG.

  4. INTRA-RUN 4-CORE BATCHED-GATED-PARALLEL execution. The budget is 1500 s on 4 cores, so the
     RT-expensive rungs run as <=K concurrent SINGLE-THREAD workers (K size-adaptive for memory),
     within the shared wall. The gate picks which rungs are worth launching; a batch runs in
     parallel; results are harvested as they finish; BK_LB and OV are updated; the next batch is
     re-gated. Reported bound is unchanged: max(AB4 floor, every rung that CERTIFIED).

EVERY in-run interim result is HARVESTED and LEVERAGED: each rung's certificate and composed bound,
each constructor/master_ip feasible primal (and a flag when it beats the banked incumbent -- the
G24 lesson), and every provisional LP rise. Full provenance: each parallel worker is its own solve
carrying its own code_hash + deterministic clock; the row is stamped over the whole source set.

This is a VARIANT for smoking, not yet the production path. It reuses lb_solver's proven building
blocks (ab4_floor, width_ladder, k_proximity, the certificate rule) rather than re-deriving them.
"""
import argparse
import io
import json
import os
import py_compile
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

import lb_solver as L                      # proven building blocks, reused not re-derived
import tep_cg_bound as T
from bound_certificate import certified, ng_certified
from stamp import stamped

# --------------------------------------------------------------------------- constants
GAIN_CEILING_MIN = 1.0                     # one unit of street cost; the variant owns its own config
WALL_BACKSTOP = L.WALL_BACKSTOP
MIN_RUNG_SECS = L.MIN_RUNG_SECS
COST_EXPONENT = L.COST_EXPONENT
LABEL_CAP = L.LABEL_CAP
# PARALLEL DEGREE, SIZE-ADAPTIVE (memory). Four concurrent masters are fine at small n; the n100
# master is large (the RC204 n100 memory wall is on record), so the degree falls with size. "No
# co-tenant" still holds: these are OUR cores on a solo machine.
DEGREE_BY_SIZE = {10: 4, 20: 4, 30: 3, 50: 2, 100: 1}
OV_IP_TIMELIMIT = 30.0                     # master_ip took <=12 s on every smoked cell; 30 s is
#                                            ample, and it is RESERVED from each worker's CG budget
#                                            below so the worker's total (CG + OV) holds the wall

# the modules whose validity must hold before any RT-expensive rung runs (layer-1 compile guard)
GUARDED_MODULES = ("analysis/lb_solver_v2.py", "analysis/lb_solver.py", "analysis/tep_cg_bound.py",
                   "analysis/tep_pricer.py", "analysis/bound_certificate.py",
                   "analysis/cost_aware_greedy.py", "analysis/verifier3.py",
                   "solver/problem.py", "solver/config.py", "solver/engines/construct.py")
SOURCES = ("analysis/lb_solver_v2.py", "analysis/lb_solver.py", "analysis/tep_cg_bound.py",
           "analysis/tep_pricer.py", "analysis/bound_certificate.py",
           "analysis/cost_aware_greedy.py", "analysis/verifier3.py")


# --------------------------------------------------------------- (3a) static compile guard
def compile_guard(modules=GUARDED_MODULES):
    """Layer 1: py_compile every module on the import path BEFORE any RT is spent. A syntax or
    load error must surface in milliseconds, never 20 minutes into a rung. Returns [] if clean."""
    bad = []
    for rel in modules:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            bad.append((rel, "missing"))
            continue
        try:
            py_compile.compile(p, doraise=True)
        except py_compile.PyCompileError as e:
            bad.append((rel, str(e).splitlines()[0][:160]))
    return bad


# ----------------------------------------------------------- (1) intra-run constructor OV
def constructor_ov(cell, size, seed=0):
    """A verified feasible primal from the K-free greedy, built at the top of the run -- instant,
    so the gain gate is armed from rung 1. Returns (obj, cars) or (None, None). obj is the
    verifier's OWN recomputation (the engine leaves objVal None by design)."""
    from solver.problem import SolverProblem
    from solver.config import InstanceSpec
    from cost_aware_greedy import construct_best_of
    sp = SolverProblem(InstanceSpec.for_k_comparison(cell, size))
    out = construct_best_of(sp, seed)
    sol, obj, cars = out[0], out[1], out[2]
    if sol is None or obj is None:
        return None, None
    return float(obj), cars


# ------------------------------------------------- (3b)+(4) the parallel rung worker (top-level)
def _rung_worker(payload):
    """Run exactly one rung in this process, SINGLE-THREADED (the parallelism is across workers,
    not inside one). First a BUILD_ONLY dry-run (layer-2 compile/feasibility guard); only if it
    builds do we spend the CG budget. Returns a picklable dict; no gurobipy model crosses back."""
    import tep_cg_bound as T
    c, size, delta, customers, ng, iters, per_iter, prox, max_secs = payload
    t0 = time.time()
    try:
        T.run(c, delta, 1, ["prio", "ts"], ng, per_iter, True, LABEL_CAP, size=size,
              proximity=prox, max_secs=5.0, start_states=True, threads=1, customers=customers)
    except Exception as e:
        return dict(delta=delta, customers=(len(customers) if customers else None),
                    build_ok=False, error="BUILD %s: %s" % (type(e).__name__, str(e)[:160]),
                    secs=round(time.time() - t0, 2))
    try:
        r = T.run(c, delta, iters, ["prio", "ts"], ng, per_iter, False, LABEL_CAP, size=size,
                  proximity=prox, max_secs=max_secs, start_states=True, threads=1,
                  customers=customers, return_master=True)
        M = r.pop("master", None)          # gurobipy model: used here, never returned (unpicklable)
        # INTRA-RUN OV over THIS rung's own columns (K-free master IP -> chaining -> verifier3),
        # far tighter than the loose constructor seed. Returned as a number; the master stays here.
        if M is not None:
            try:
                ovr = T.master_ip(M, c, size, threads=1, timelimit=OV_IP_TIMELIMIT)
                if ovr.get("verified") and ovr.get("objVal") is not None:
                    r["ov_master"] = float(ovr["objVal"])
                    r["ov_master_cars"] = ovr.get("nCars")
                    r["ov_master_secs"] = ovr.get("ip_secs")
                    # return the SOLUTION too (xij/vi/hubs are lists -> picklable across the pool),
                    # so the primal can INHERIT this rung's master_ip incumbent, not just its value.
                    r["ov_master_solution"] = ovr.get("solution")
            except Exception as e:
                r["ov_master_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
            try:
                M.m.dispose()      # free the gurobipy model so a persistent worker cannot leak
            except Exception:
                pass
        r["build_ok"] = True
        r["worker_secs"] = round(time.time() - t0, 2)
        return r
    except Exception as e:
        return dict(delta=delta, customers=(len(customers) if customers else None),
                    build_ok=True, error="RUN %s: %s" % (type(e).__name__, str(e)[:160]),
                    secs=round(time.time() - t0, 2))


def _rung_specs(cell, size, inst):
    """The ladder: width rungs coarsest-first, then subset rungs. Identical to lb_solver's."""
    dflt = T.default_delta(inst)
    ladder = L.width_ladder(float(inst.tau), dflt)
    specs = [(d, None, "tep:d%g" % d) for d in ladder]
    if ladder and size >= L.K_LADDER_MIN_SIZE:
        try:
            from tep_easy_reduction import easiest_first
            order = easiest_first(cell, size)
            for k in L.K_LADDER:
                keep = sorted(set(order[k:]))
                if 0 < len(keep) < len(order):
                    specs.append((dflt, keep, "sub:k%d" % k))
        except Exception:
            pass
    return specs, dflt, ladder


# --------------------------------------------------------------- the batched-gated-parallel driver
def solve_cell_v2(cell, size, wall_backstop=WALL_BACKSTOP, ng=10, iters=400, per_iter=1000,
                  degree=None, seed=0, verbose=True, pool=None):
    import verifier3 as V
    prox = L.k_proximity(size)
    t_start = time.time()
    clk = lambda: round(time.time() - t_start, 3)
    gates, rungs, improvements, harvest = [], [], [], []
    degree = degree or DEGREE_BY_SIZE.get(size, 1)

    def gate(name, decision, **kw):
        gates.append(dict(gate=name, t=clk(), decision=decision, **kw))

    # --- layer-1 compile guard, before any RT
    bad = compile_guard()
    gate("G_compile", "GO" if not bad else "NO-GO", bad=bad[:4])
    if bad:
        return dict(cell=cell, size=size, error="compile guard failed", bad=bad, gates=gates)

    # --- AB4 floor: the seeded LB
    ab = L.ab4_floor(cell, size, prox)
    lb, carrier, cert = ab["ab4"], "ab4", None
    water = ab["water"]

    # --- (1) constructor OV: the seeded intra-run upper bound
    ov, ov_cars = constructor_ov(cell, size, seed)
    ov_source = "constructor:cost_aware_greedy" if ov is not None else None
    gate("G0c_constructor_ov", "GO" if ov is not None else "NO-GO", ov=ov, cars=ov_cars,
         note="verified K-free greedy primal; seeds the gain gate from rung 1")
    if ov is not None:
        harvest.append(dict(kind="primal", source=ov_source, objVal=ov, nCars=ov_cars,
                            verified=True, t=clk()))
    ov_constructor = ov        # the seed, recorded distinctly from the master_ip-refined OV below
    best_sol = None            # the SOLUTION of the best (lowest-OV) master_ip incumbent, for inherit

    inst = V.load_instance(cell, size, prox)
    specs, dflt, ladder = _rung_specs(cell, size, inst)
    pending = list(specs)
    done_kinds = set()

    own_pool = pool is None       # a persistent pool may be passed in (solve_grid) to amortise
    if own_pool:                  # worker spawn + import + Gurobi license across cells
        pool = ProcessPoolExecutor(max_workers=max(degree, 1))
    try:
        while pending:
            left = wall_backstop - (time.time() - t_start)
            if left < MIN_RUNG_SECS:
                break
            # --- gate the candidates: gain ceiling (per rung) + kind not abandoned
            batch, skipped = [], []
            for (delta, customers, tag) in list(pending):
                kind = "sub" if customers else "tep"
                if kind in done_kinds:
                    pending.remove((delta, customers, tag)); continue
                if ov is not None:
                    gain_ceiling = ov - lb      # valid ceiling on remaining LB gain (ov is a UB)
                    if gain_ceiling < GAIN_CEILING_MIN:
                        gate("G0_gain_ceiling", "NO-GO", rung=tag, gain_ceiling=round(gain_ceiling, 6),
                             ov=round(ov, 6), bk_lb=round(lb, 6), threshold=GAIN_CEILING_MIN)
                        rungs.append(dict(rung=tag, delta=delta, status="skipped: gain ceiling",
                                          gain_ceiling=round(gain_ceiling, 6)))
                        pending.remove((delta, customers, tag)); continue
                    gate("G0_gain_ceiling", "GO", rung=tag, gain_ceiling=round(gain_ceiling, 6),
                         ov=round(ov, 6), bk_lb=round(lb, 6), threshold=GAIN_CEILING_MIN)
                batch.append((delta, customers, tag))
                if len(batch) >= degree:
                    break
            if not batch:
                break
            # --- launch the batch in parallel, single-thread workers, sharing the wall
            left = wall_backstop - (time.time() - t_start)
            futs = {}
            for (delta, customers, tag) in batch:
                payload = (cell, size, delta, customers, ng, iters, per_iter, prox,
                           max(left - OV_IP_TIMELIMIT - 10.0, 1.0))   # reserve the OV build + margin
                futs[pool.submit(_rung_worker, payload)] = (delta, customers, tag)
                gate("G_launch", "GO", rung=tag, degree=degree, wall_left=round(left, 1))
            # --- harvest as they complete, leveraging every interim result
            for fut in as_completed(futs):
                delta, customers, tag = futs[fut]
                pending.remove((delta, customers, tag))
                kind = "sub" if customers else "tep"
                r = fut.result()
                if not r.get("build_ok", True):
                    gate("G_build_only", "NO-GO", rung=tag, error=r.get("error"))
                    rungs.append(dict(rung=tag, delta=delta, status="build_only failed",
                                      error=r.get("error")))
                    done_kinds.add(kind); continue
                if r.get("error"):
                    gate("G_rung_error", "NO-GO", rung=tag, error=r.get("error"))
                    rungs.append(dict(rung=tag, delta=delta, status="run error",
                                      error=r.get("error")))
                    done_kinds.add(kind); continue
                cls = "elementary" if certified(r) else ("ng" if ng_certified(r) else None)
                lp = r.get("lp_street")
                composed = (float(lp) + water) if (cls and lp is not None) else None
                rungs.append(dict(rung=tag, delta=delta, certificate=cls, composed=composed,
                                  lp_street=lp, secs=r.get("secs"), cols=r.get("cols"),
                                  worker_secs=r.get("worker_secs"),
                                  gurobi_work=(r.get("det_ticks") or {}).get("gurobi_work"),
                                  bound_by=r.get("bound_by"), reproducible=r.get("reproducible"),
                                  cert_evidence=r.get("cert_evidence")))
                # HARVEST + LEVERAGE: a certified rise raises BK_LB
                if composed is not None and composed > lb + 1e-9:
                    improvements.append(dict(kind="certified", rung=tag, lb_from=round(lb, 6),
                                             lb_to=round(composed, 6), gain=round(composed - lb, 6),
                                             certificate=cls, t=clk()))
                    lb, carrier, cert = composed, tag, cls
                # HARVEST + LEVERAGE the worker's intra-run master_ip OV: tighten the running OV
                # (min) so the gain gate sharpens as rungs land, and record the verified primal.
                ovm = r.get("ov_master")
                if ovm is not None:
                    if ov is None or ovm < ov:
                        ov, ov_source = ovm, "master_ip:%s" % tag
                        best_sol = r.get("ov_master_solution")   # keep the best incumbent's solution
                    harvest.append(dict(kind="primal", source="master_ip:%s" % tag, objVal=ovm,
                                        nCars=r.get("ov_master_cars"), verified=True, t=clk()))
                    gate("G0b_intra_ov", "GO", rung=tag, ov=round(ovm, 6), ov_running=round(ov, 6),
                         ip_secs=r.get("ov_master_secs"))
                if cls is None:
                    done_kinds.add(kind)   # this kind gets dearer down the list; abandon it
                # refutation safety (uses the intra-run OV, not banked/K)
                if ov is not None and composed is not None and composed > ov + 1e-6:
                    gate("G12_refutation", "NO-GO", rung=tag, value=round(composed, 6),
                         ov=round(ov, 6), note="a bound above our own feasible OV: one is wrong")
    finally:
        if own_pool:
            pool.shutdown(wait=True)

    reported = lb
    total_s = round(time.time() - t_start, 2)
    row = dict(cell=cell, size=size, proximity=prox, ng=ng, variant="v2-parallel", degree=degree,
               ab4=ab["ab4"], water=water, ov_constructor=ov_constructor, ov_final=ov,
               ov_source=ov_source,
               lb=reported, lb_carrier=carrier, certificate=cert,
               headroom=((ov - reported) if ov is not None else None),
               best_solution=best_sol,     # the inheritable incumbent (best master_ip), or None
               rungs=rungs, gates=gates, improvements=improvements, harvest=harvest,
               ladder=ladder, total_s=total_s,
               valid_bound=(ov is None or reported <= ov + 1e-6))
    return row


def _warmup(_):
    """Front-load a worker's Gurobi env/license + module import so startup is paid ONCE per worker,
    not per cell, and is NOT charged to any cell's budget clock."""
    import gurobipy as gp
    m = gp.Model(); m.dispose()        # forces env + license acquisition in this process
    import tep_cg_bound                 # forces our import/compile in this process
    return True


def solve_grid(cases, wall_backstop=WALL_BACKSTOP, warm=True):
    """Solve many (cell, size) with ONE PERSISTENT worker pool, so each worker pays its import and
    Gurobi license once for the whole grid rather than once per cell. The pool is sized to the max
    degree; each cell still submits only up to its size-adaptive degree concurrently."""
    import time as _t
    K = max(DEGREE_BY_SIZE.values())
    rows = []
    with ProcessPoolExecutor(max_workers=K) as pool:
        if warm:
            t0 = _t.time()
            list(pool.map(_warmup, range(K)))
            print("  [solve_grid] warmed %d workers in %.1fs (import+license off the budget)"
                  % (K, _t.time() - t0), flush=True)
        for cell, size in cases:
            rows.append(solve_cell_v2(cell, size, wall_backstop=wall_backstop, pool=pool))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--wall", type=float, default=WALL_BACKSTOP)
    ap.add_argument("--degree", type=int, default=None)
    a = ap.parse_args()
    row = solve_cell_v2(a.cell, a.size, wall_backstop=a.wall, degree=a.degree)
    print(json.dumps({k: v for k, v in row.items()
                      if k not in ("gates", "rungs", "improvements", "harvest")},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
