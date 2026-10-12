"""ARBITER v0.4 — the same question on a time-expanded DAG, where big-M does not exist.

    python analysis/espprc_arbiter_dag.py R202 --size 30 --grid 5 --work 300

WHY A NEW FORMULATION RATHER THAN MORE EFFORT ON THE OLD ONE. Measured on R202 n30, where the
MIP's true optimum is 0.000000:

    root LP as built .......................... -296.2943
    root LP with EVERY timing constraint gone .. -298.6911
    + cardinality from capacity ............... -296.2943   (no effect at all)
    + 2-cycle elimination ..................... -289.4892

The entire big-M time-window family is worth **2.40 of a 296-unit gap** -- 0.8 per cent. Those
constraints are not weak, they are very nearly vacuous, so branch-and-bound starts 296 below
the answer and must branch the whole way up. It bought 11 units for 426,605 nodes. Nothing
incremental closes that, which is why v0.3's Cutoff was a null result: a cutoff can only prune
nodes whose bound has already risen above it, and these never do.

THE FIX IS STRUCTURAL. Put time in the NODE, not in a constraint. A node is `(customer, t)` --
"service at this customer starts somewhere in [t, t+grid)" -- and an arc exists only if the
timing permits it. An arc that would violate a window is then not absent-by-inequality, it is
absent. What remains is a resource-constrained shortest path on a DAG: the pure shortest-path
polytope is integral, and capacity plus visit-once are the only side constraints.

WHY IT MAY RELAX FREELY, WHICH IS THE WHOLE LICENCE FOR THIS DESIGN. The arbiter's job is to
produce a VALID UNDERESTIMATE of the minimum reduced cost. CONFIRM fires on
`dual bound >= -eps`, and any relaxation can only LOWER the minimum, so a relaxed arbiter that
still reaches -eps certifies exactly as soundly as an exact one. v0.0 failed not because it
relaxed but because it relaxed the wrong thing: loose entry/exit legs cost 284.1168 on a single
route, which is additive on the objective and ruinous. Time discretisation and elementarity are
structural, and structural looseness is what this graph is built to absorb.

EVERY RELAXATION IS ONE-DIRECTIONAL AND EACH IS STATED:

  time discretisation   a node stands for an INTERVAL [t, t+grid) and every arc is tested at
                        the most permissive reading of it, so any real schedule is representable
                        and some unrealisable ones are too. Downward on rc_min.
  hub arrival           an end arc is offered for EVERY bucket at or after the earliest
                        reachable one, so the solver may pick the most favourable dual. Waiting
                        on post-nodes is legal anyway (`Master.variants`), so this is at worst a
                        relaxation and probably an equality.
  grid granularity      finer is tighter and slower, coarser is looser and faster, and CONFIRM
                        is sound at every setting. That is the dial this formulation has and the
                        big-M one did not.

WHAT IS NOT RELAXED. The legs are exact, per variant, as in v0.2 -- `mu_post[(L,b)]` rides on
the start arc and `mu_pre[(p,ba)]` on the end arc as CONSTANT coefficients, because once time is
in the node the bucket is known at build time. No arrival variable, no bucket-linking
constraints, no BUCKET_MARGIN, and none of the tolerance trouble that cost v0.1 its first probe.

INDEPENDENCE IS PRESERVED. No dominance rule, no completion bound, no ng memory, and the arc set
is built here rather than imported from `Pricer.succ`.
"""
import argparse
import hashlib
import io
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

EPS = 1e-6


def build_dag(M, pi, mu_src, mu_pre, mu_post, grid=5.0, strict_arcs=False):
    """The time-expanded graph. Returns (nodes, arcs, meta) with every cost already baked in."""
    C, sats, g = list(M.C), list(M.sats), M.g
    D, tc, H0, dl, nb, win = M.D, M.tc, M.H0, M.delta, M.nb, M.win
    nd = M.inst.nodes
    e = {c: float(nd[c].earliest) for c in C}
    l = {c: float(nd[c].latest) for c in C}
    sv = {c: float(nd[c].service) for c in C}
    dem = {c: float(nd[c].demand) for c in C}

    # NODES. One per (customer, grid slot) covering the customer's own window. The slot's LOWER
    # edge represents it, and every test below uses that edge, which is the permissive reading.
    times = {}
    for i in C:
        k0 = int(math.floor(e[i] / grid))
        k1 = int(math.floor(l[i] / grid))
        times[i] = [k * grid for k in range(k0, k1 + 1)]
    nodes = [(i, t) for i in C for t in times[i]]

    inner = {}
    for (i, t) in nodes:
        for j in C:
            if j == i:
                continue
            need = t + sv[i] + D[i][j]
            # PERMISSIVE: a node stands for [t, t+grid), so arrival can be as early as
            # need - grid. Allowing the earliest slot that could receive it relaxes downward.
            for t2 in times[j]:
                # DIAGNOSTIC ONLY when strict_arcs: requiring t2 >= need makes the graph a
                # RESTRICTION, not a relaxation, so its bound is NOT valid and must never be
                # reported. It exists to measure how much of the residual gap is per-arc time
                # slack -- the permissive test lets a route gain up to `grid` on every arc, and
                # that compounds along the route.
                lo = need - 1e-9 if strict_arcs else need - grid - 1e-9
                if t2 + grid > need - 1e-9 and t2 >= lo:
                    inner[((i, t), (j, t2))] = tc * D[i][j]
                    break                                        # earliest receiving slot only

    # START ARCS. The depot departs at H0; a satellite departs post(L,b) at H0 + b*delta. The
    # dual rides as a constant because the start node is part of the arc's identity.
    start = {}
    for i in C:
        for t in times[i]:
            if t + grid > H0 + D[g][i] - 1e-9:
                start[("DEP", (i, t))] = tc * D[g][i] + float(mu_src)
    for L in sats:
        for b in range(win, nb):
            dep = H0 + b * dl
            if (L, b) not in mu_post:
                continue
            for i in C:
                if dep + D[L][i] > l[i] + grid + 1e-9:
                    continue
                for t in times[i]:
                    if t + grid > dep + D[L][i] - 1e-9:
                        start[((L, b), (i, t))] = tc * D[L][i] + float(mu_post[(L, b)])
                        break

    # END ARCS. Arrival at hub p is t + sv + D[i][p]; its bucket is known HERE, at build time,
    # so -mu_pre is a constant. Every bucket at or after the earliest reachable one is offered:
    # waiting on a post node is legal, and offering more can only lower the minimum.
    end = {}
    for (i, t) in nodes:
        for p in sats:
            # THE BUCKET RANGE CONSISTENT WITH THIS NODE, AND NOTHING WIDER. Service starts
            # somewhere in [t, t+grid), so the hub arrival lies in
            # [t + sv + D, t + grid + sv + D) and its bucket lies between these two. v0.4.0
            # offered EVERY bucket from ba0 to the horizon on the argument that waiting on a
            # post node is legal -- which handed the solver the largest mu_pre anywhere in the
            # horizon, i.e. exactly sufmax[p][ba0], the same slack d430 measured as worth about
            # 188. That was the dominant looseness, not the time discretisation.
            ba0 = M.bucket(t + sv[i] + D[i][p])
            ba1 = M.bucket(t + grid + sv[i] + D[i][p])
            for ba in range(max(0, ba0), min(nb - 1, ba1) + 1):
                if (p, ba) in mu_pre:
                    end[((i, t), (p, ba))] = tc * D[i][p] - float(mu_pre[(p, ba)])
    meta = dict(grid=grid, nodes=len(nodes), inner=len(inner), start=len(start), end=len(end),
                slots_per_customer=round(len(nodes) / max(1, len(C)), 1))
    return nodes, (start, inner, end), (times, e, l, sv, dem), meta


def solve_dag(M, pi, mu_src, mu_pre, mu_post, grid=5.0, work_limit=300.0, threads=4,
              relax_only=False, verbose=False, strict_arcs=False):
    import gurobipy as gp
    from gurobipy import GRB

    C = list(M.C)
    nodes, (start, inner, end), (times, e, l, sv, dem), meta = build_dag(
        M, pi, mu_src, mu_pre, mu_post, grid, strict_arcs)

    m = gp.Model("espprc_dag")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.Threads = threads
    if work_limit:
        m.Params.WorkLimit = float(work_limit)
    vt = GRB.CONTINUOUS if relax_only else GRB.BINARY
    xs = m.addVars(list(start), vtype=vt, lb=0, ub=1, name="s")
    xi = m.addVars(list(inner), vtype=vt, lb=0, ub=1, name="i")
    xe = m.addVars(list(end), vtype=vt, lb=0, ub=1, name="e")

    m.addConstr(xs.sum() == 1, "one_start")
    m.addConstr(xe.sum() == 1, "one_end")
    for v in nodes:                                    # flow conservation at every (customer, t)
        ins = ([xs[a] for a in start if a[1] == v] + [xi[a] for a in inner if a[1] == v])
        outs = ([xi[a] for a in inner if a[0] == v] + [xe[a] for a in end if a[0] == v])
        if ins or outs:
            m.addConstr(gp.quicksum(ins) == gp.quicksum(outs), "fc_%s_%s" % v)
    # visit-once and capacity: the only side constraints, and the reason it is not a pure path
    served = {}
    for i in C:
        vs = [v for v in nodes if v[0] == i]
        served[i] = gp.quicksum([xs[a] for a in start if a[1][0] == i]
                                + [xi[a] for a in inner if a[1][0] == i])
        m.addConstr(served[i] <= 1, "once_%s" % i)
    m.addConstr(gp.quicksum(dem[i] * served[i] for i in C) <= 50.0, "cap")

    m.setObjective(gp.quicksum(start[a] * xs[a] for a in start)
                   + gp.quicksum(inner[a] * xi[a] for a in inner)
                   + gp.quicksum(end[a] * xe[a] for a in end)
                   - gp.quicksum(float(pi.get(i, 0.0)) * served[i] for i in C), GRB.MINIMIZE)

    t0 = time.time()
    m.optimize()
    out = dict(model="dag v0.4", grid=grid, status=int(m.Status),
               secs=round(time.time() - t0, 2), work=round(float(m.getAttr("Work")), 6),
               nodes_explored=int(m.NodeCount), dual_bound=None, incumbent=None, route=None)
    out.update(meta)
    try:
        out["dual_bound"] = float(m.ObjBound) if not relax_only else float(m.ObjVal)
    except Exception:
        pass
    if not relax_only and m.SolCount > 0:
        out["incumbent"] = float(m.ObjVal)
        seq = []
        cur = [a[1] for a in start if xs[a].X > 0.5]
        cur = cur[0] if cur else None
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur); seq.append(cur[0])
            nxt = [a[1] for a in inner if a[0] == cur and xi[a].X > 0.5]
            cur = nxt[0] if nxt else None
        out["route"] = seq
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--delta", type=float, default=20.0)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--grid", type=float, default=5.0, help="time-expansion step; finer = tighter")
    ap.add_argument("--work", type=float, default=300.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--root-only", action="store_true", help="LP relaxation only, no branching")
    ap.add_argument("--strict-arcs", action="store_true",
                    help="DIAGNOSTIC ONLY: forbids the per-arc time slack, making the graph a "
                         "RESTRICTION whose bound is NOT valid. Measures where the gap lives.")
    ap.add_argument("--bank", action="store_true",
                    help="write a banked artifact under runs/oracle. Default is SMOKE: a log "
                         "line under logs/, which can never be cited as a result")
    ap.add_argument("--proximity", type=float, default=None)
    a = ap.parse_args()

    import tep_cg_bound as T
    from k_comparison import k_proximity
    from stamp import stamped
    prox = k_proximity(a.size) if a.proximity is None else a.proximity

    print("ARBITER v0.4 (DAG) -- %s n%d, grid %.1f, work %.0f, threads %d"
          % (a.cell, a.size, a.grid, a.work, a.threads), flush=True)
    t0 = time.time()
    r = T.run(a.cell, a.delta, a.iters, ["prio", "ts"], a.ng, 1000, False, 3_000_000,
              size=a.size, proximity=prox, start_states=True, return_master=True)
    M = r.pop("master")
    print("  CG: lp_street %.4f  proven %s  %.0fs" % (r["lp_street"], r.get("proven"),
                                                      time.time() - t0), flush=True)
    M.solve()
    pi, mu_src, mu_pre, mu_post = M.duals()

    out = solve_dag(M, pi, mu_src, mu_pre, mu_post, grid=a.grid, work_limit=a.work,
                    threads=a.threads, relax_only=a.root_only, strict_arcs=a.strict_arcs)
    print("  graph: %d nodes (%.1f slots/customer), %d inner + %d start + %d end arcs"
          % (out["nodes"], out["slots_per_customer"], out["inner"], out["start"], out["end"]),
          flush=True)
    print("  status %s  work %.3f  bb-nodes %d  %.1fs" % (out["status"], out["work"],
                                                          out["nodes_explored"], out["secs"]))
    print("  dual bound %s | incumbent %s" % (out["dual_bound"], out["incumbent"]), flush=True)

    db = out.get("dual_bound")
    v = "CONFIRM" if (db is not None and db >= -EPS) else "INCONCLUSIVE"
    if out.get("incumbent") is not None and out["route"]:
        bv = M.best_variant(list(out["route"]), pi, mu_src, mu_pre, mu_post)
        out["route_exact_rc"] = None if bv is None else float(bv[0])
        if out["route_exact_rc"] is not None:
            out["relaxation_slack"] = out["route_exact_rc"] - out["incumbent"]
    print("  VERDICT %s   (cg proven %s -> expected %s)"
          % (v, r.get("proven"), "CONFIRM" if r.get("proven") else "-"), flush=True)

    _h = hashlib.sha256(io.open(__file__, "rb").read()).hexdigest()[:8]
    payload = dict(probe="DesignDP phase -1, v0.4 DAG", cell=a.cell, size=a.size, proximity=prox,
                   delta=a.delta, ng=a.ng, grid=a.grid, cg_lp_street=r["lp_street"],
                   cg_proven=r.get("proven"), dag=out, verdict=v, threads=a.threads,
                   secs=round(time.time() - t0, 1),
                   det_ticks=dict(dag_work=out["work"], dag_nodes=out["nodes_explored"],
                                  cg_labels=(r.get("det_ticks") or {}).get("pricer_labels")),
                   diagnostic_only=True, valid_bound=False,
                   valid_bound_why="applicability probe for the DAG arbiter; not a bound run")
    doc = stamped(payload, "analysis/espprc_arbiter_dag.py", "analysis/tep_cg_bound.py",
                  rt_class="diagnostic")
    p = os.path.join(ROOT, "runs" if a.bank else "logs",
                     "oracle" if a.bank else "smoke",
                     "dp_probe_dag_%s_n%d_g%g_%s.json" % (a.cell, a.size, a.grid, _h))
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
