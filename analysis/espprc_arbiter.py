"""SKELETON — the independent pricing arbiter of TRAJECTORY_DesignDP-0.0.md section 1.1.

    python analysis/espprc_arbiter.py R202 --size 30 --work 60

WHAT IT IS FOR. Every optimality certificate the dual leg prints today comes from the labelling
pricer whose soundness is the thing in question. `paper/LEMMAS_TEP.md` says it plainly: the
hypothesis "is established by our own ng pricer", and "there is no equivalent arbiter for the ng
class". On 2026-09-30 that stopped being theoretical — the completion-bound prune, recorded in
`OPEN_GAPS.md` as checked, correct and not to be re-audited, was refuted for the ng mode with 86
counterexamples (d625). This module prices the SAME subproblem by a route that shares no code
with `tep_pricer.py`: no dominance rule, no completion bound, no ng memory. A MIP, handed to
Gurobi.

WHY A MIP RATHER THAN ENUMERATION. `tep_exact_small.py` enumerates and is exhaustive, and it is
the cheaper arbiter wherever it runs — which is why DesignDP uses it at n10 and n20 and this
module only from n30 up. It does not scale: R203 at n20 already needed 246,235 trips, and three
n20 cells exceeded a 600 s cap. A MIP's **dual bound at timeout is a valid underestimate of the
true minimum reduced cost**, so it does not have to finish to be useful. That single property is
what makes an arbiter affordable at n100.

WHAT IT CERTIFIES, AND THE LIMIT OF THIS SKELETON. The model below forces ELEMENTARITY — each
customer at most once, with subtours killed by the time propagation rather than by cuts. So its
optimum is `rc_min` over the ELEMENTARY column set R_e, and:

  * dual bound >= -eps  ->  no elementary column prices out at these duals. That is
    L-TEP-cert's hypothesis exactly, established by independent code. It is the STRONGER
    certificate, not merely a confirmation of the ng one.

  * dual bound  < -eps  ->  a column exists; the incumbent route is returned and is a genuine
    negative-reduced-cost trip, usable by the master and by the primal pool.

  * LIMIT, stated because it is load-bearing for the Lagrangian branch of DesignDP 1.1 and is
    NOT implemented here: `R_e` is a SUBSET of the ng class, so `min over R_e >= min over R_ng`.
    The elementary `rc_min` is therefore an OVER-estimate of the ng one and may NOT be used as
    the `rc_min` in `z_RMP + kappa * rc_min` when the master's pool contains non-elementary
    columns. Version 0.0 is the certificate branch only. The Lagrangian branch needs either a
    pool restricted to elementary columns or a model that admits ng revisits, and neither is
    guessed at here.

THE MODEL. Nodes: the customers, plus a source s and a sink t.
  x[i,j] in {0,1}   arc used            y[i] in {0,1}   customer i served
  T[i] in [e_i, l_i]                    arrival time at i

  min  sum_j entry[j]*x[s,j] + sum_{i,j} scale*D[i][j]*x[i,j] + sum_i exit[i]*x[i,t]
       - sum_i pi[i]*y[i]
  s.t. sum_j x[s,j] = 1                              one entry leg
       sum_i x[i,t] = 1                              one exit leg
       sum_j x[i,j] = y[i]   for each customer i     out-degree
       sum_j x[j,i] = y[i]   for each customer i     in-degree
       sum_i dem[i]*y[i] <= Q                        capacity
       T[j] >= T[i] + sv[i] + D[i][j] - M(1 - x[i,j])  time propagation, and with it elementarity
       sum_i y[i] >= 1                               a trip serves someone

`entry` and `exit` come from `Master.pricer_legs`, which are UNDERESTIMATES of every variant's
flow-dual terms by construction. Using them keeps the arbiter's value a lower bound on the exact
per-variant reduced cost, which is the safe direction: a column this model calls non-negative
cannot be negative for any variant.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

EPS = 1e-6

# BUCKET EDGE MARGIN. Master.bucket is floor((t - H0)/delta + 1e-9), so a time sitting EXACTLY
# on a boundary belongs to the HIGHER bucket. v0.1 wrote that edge as `A <= next_edge - 1e-9`,
# and Gurobi's default FeasibilityTol is 1e-6 -- a thousand times larger -- so an arrival of
# exactly 780.0 satisfied a constraint meant to exclude it and the model claimed bucket 38
# while arriving in 39. It was worth mu_pre[(34,39)] - mu_pre[(34,38)] = 1.139951, which was
# the whole residual the n30 probe reported. The margin must sit well ABOVE the solver's
# tolerance and well below any real time difference; delta is 20 and the shortest legs are
# order 1, so 1e-4 is four orders clear on both sides.
BUCKET_MARGIN = 1e-4


def build_and_solve(inst, C, pi, entry, exit_, scale, Q, work_limit=60.0, threads=4,
                    verbose=False):
    """Returns a dict with the dual bound, the incumbent and the route. Never raises on a
    timeout: an unfinished MIP still has a dual bound, which is the whole point."""
    import gurobipy as gp
    from gurobipy import GRB

    nd, D = inst.nodes, inst.D
    e = {c: float(nd[c].earliest) for c in C}
    l = {c: float(nd[c].latest) for c in C}
    sv = {c: float(nd[c].service) for c in C}
    dem = {c: float(nd[c].demand) for c in C}

    # ARCS ARE RECOMPUTED HERE, not imported. Sharing `Pricer.succ` would couple the arbiter to
    # the code it is arbitrating, which is the one thing it must not do.
    arcs = [(i, j) for i in C for j in C
            if i != j and e[i] + sv[i] + D[i][j] <= l[j] + 1e-9]

    m = gp.Model("espprc_arbiter")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.Threads = threads
    if work_limit:
        m.Params.WorkLimit = float(work_limit)

    x = m.addVars(arcs, vtype=GRB.BINARY, name="x")
    xs = m.addVars(C, vtype=GRB.BINARY, name="xs")          # source -> j
    xt = m.addVars(C, vtype=GRB.BINARY, name="xt")          # i -> sink
    y = m.addVars(C, vtype=GRB.BINARY, name="y")
    T = m.addVars(C, lb={c: e[c] for c in C}, ub={c: l[c] for c in C}, name="T")

    m.addConstr(xs.sum() == 1, "one_entry")
    m.addConstr(xt.sum() == 1, "one_exit")
    for i in C:
        m.addConstr(xs[i] + gp.quicksum(x[j, i] for j in C if (j, i) in x) == y[i], "in_%s" % i)
        m.addConstr(xt[i] + gp.quicksum(x[i, j] for j in C if (i, j) in x) == y[i], "out_%s" % i)
    m.addConstr(gp.quicksum(dem[i] * y[i] for i in C) <= Q, "cap")
    m.addConstr(y.sum() >= 1, "nonempty")

    # TIME PROPAGATION. It enforces the windows AND kills every subtour, because time strictly
    # increases along any used arc and a cycle cannot. That is why no subtour-elimination family
    # is needed and why elementarity comes for free.
    for (i, j) in arcs:
        big_m = max(0.0, l[i] + sv[i] + D[i][j] - e[j])
        m.addConstr(T[j] >= T[i] + sv[i] + D[i][j] - big_m * (1 - x[i, j]), "t_%s_%s" % (i, j))

    obj = (gp.quicksum(float(entry[j]) * xs[j] for j in C)
           + gp.quicksum(float(exit_[i]) * xt[i] for i in C)
           + gp.quicksum(scale * D[i][j] * x[i, j] for (i, j) in arcs)
           - gp.quicksum(float(pi.get(i, 0.0)) * y[i] for i in C))
    m.setObjective(obj, GRB.MINIMIZE)

    t0 = time.time()
    m.optimize()
    secs = time.time() - t0

    out = dict(status=int(m.Status), secs=round(secs, 2),
               work=round(float(m.getAttr("Work")), 6),
               nodes=int(m.NodeCount), arcs=len(arcs), customers=len(C),
               dual_bound=None, incumbent=None, route=None, mip_gap=None)
    try:
        out["dual_bound"] = float(m.ObjBound)
    except Exception:
        pass
    if m.SolCount > 0:
        out["incumbent"] = float(m.ObjVal)
        out["mip_gap"] = float(m.MIPGap)
        first = [c for c in C if xs[c].X > 0.5]
        seq, cur = [], (first[0] if first else None)
        seen = set()
        while cur is not None and cur not in seen:
            seq.append(cur); seen.add(cur)
            nxt = [j for j in C if (cur, j) in x and x[cur, j].X > 0.5]
            cur = nxt[0] if nxt else None
        out["route"] = seq
    return out


def build_and_solve_exact(M, pi, mu_src, mu_pre, mu_post, work_limit=120.0, threads=4,
                          verbose=False, cutoff=True, warm_route=None):
    """v0.2 — the SAME subproblem with EXACT per-variant legs, and bucket edges the solver can see.

    WHY v0.0 COULD NOT. It priced with `entry`/`exit_` from `Master.pricer_legs`, which
    underestimate every variant by construction: `entry[c]` is a minimum over every start node
    taken independently of timing, and `exit_[c]` uses `sufmax[p][0]`, the most favourable
    bucket in the whole horizon. Measured on the first probe, R202 n30: the model returned
    -240.0230 on route [7, 19, 11, 10] whose EXACT reduced cost is +44.0937 -- 284.1168 of pure
    leg slack. A model that loose can never reach `>= -eps`, so it can never confirm anything.
    d430 named this as the cost of tightening and called it "not cheap" -- for LABELLING, where
    it means one pass per start. In a MIP it is more binaries, and v0.0 solved n30 to proven
    optimality in 0.2 s with one node, so the budget is there.

    WHAT EXACT MEANS HERE. `Master.best_variant` scores a trip as

        rc = tc*(D[L][first] + inner + D[last][p]) - sum pi
             + (mu_src if L is the depot else mu_post[(L, b)]) - mu_pre[(p, ba)]

    so the model must choose the start `(L, b)` and the exit `(p, ba)` itself, with `b` and `ba`
    tied to the route's own timing rather than optimised away from it.

    THE FACTORISATION THAT KEEPS IT SMALL. A naive start variable `(L, b, first)` is
    |sats|*nb*|C| -- 6,840 at n30. The cost term depends on `(L, first)` and the dual term on
    `(L, b)`, and nothing needs them in one index, so they are separate variables tied by a
    per-satellite consistency row. Same for the exit. That is 378 + 352 + 870 at n30 instead of
    8,059, and it is why this is worth building rather than enumerating.
    """
    import gurobipy as gp
    from gurobipy import GRB

    inst = M.inst
    C, sats, g = list(M.C), list(M.sats), M.g
    D, tc, H0, dl, nb, win = M.D, M.tc, M.H0, M.delta, M.nb, M.win
    nd = inst.nodes
    e = {c: float(nd[c].earliest) for c in C}
    l = {c: float(nd[c].latest) for c in C}
    sv = {c: float(nd[c].service) for c in C}
    dem = {c: float(nd[c].demand) for c in C}
    Q = 50.0
    HORIZON = H0 + nb * dl

    arcs = [(i, j) for i in C for j in C
            if i != j and e[i] + sv[i] + D[i][j] <= l[j] + 1e-9]
    # only start buckets and arrival buckets that a real trip could occupy
    sbk = [(L, b) for L in sats for b in range(win, nb)
           if any(H0 + b * dl + D[L][i] <= l[i] + 1e-9 for i in C)]
    ebk = [(p, ba) for p in sats for ba in range(nb)
           if any(M.bucket(e[i] + sv[i] + D[i][p]) <= ba <= M.bucket(l[i] + sv[i] + D[i][p])
                  for i in C)]

    m = gp.Model("espprc_arbiter_exact")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.Threads = threads
    # tolerances tightened so the bucket edges mean what they say (see BUCKET_MARGIN)
    m.Params.FeasibilityTol = 1e-9
    m.Params.IntFeasTol = 1e-9
    if work_limit:
        m.Params.WorkLimit = float(work_limit)
    if cutoff:
        # v0.3. WE NEVER NEEDED THE OPTIMUM, ONLY THE SIGN. Asking Gurobi to prove the
        # optimum is >= -eps makes it grind the dual bound up through the whole tree: on
        # R202 n30 that was 270,794 nodes to move it from -174.79 to -163.51, because the
        # big-M time propagation gives a nearly vacuous LP relaxation. With a Cutoff, every
        # node whose LP bound already sits above -eps is pruned on the spot instead of
        # being explored to improve a number nobody reads. Status CUTOFF then MEANS no
        # column prices out, which is L-TEP-cert's hypothesis established rather than
        # approached. Soundness is unchanged: the cutoff removes only solutions we have
        # already decided are not interesting.
        m.Params.Cutoff = -EPS

    x = m.addVars(arcs, vtype=GRB.BINARY, name="x")
    y = m.addVars(C, vtype=GRB.BINARY, name="y")
    T = m.addVars(C, lb={c: e[c] for c in C}, ub={c: l[c] for c in C}, name="T")
    sl = m.addVars([(L, i) for L in sats for i in C], vtype=GRB.BINARY, name="sl")   # start node, first
    sg = m.addVars(C, vtype=GRB.BINARY, name="sg")                                   # depot start, first
    sb = m.addVars(sbk, vtype=GRB.BINARY, name="sb")                                 # start bucket
    el = m.addVars([(i, p) for i in C for p in sats], vtype=GRB.BINARY, name="el")   # last, hub
    eb = m.addVars(ebk, vtype=GRB.BINARY, name="eb")                                 # arrival bucket
    A = m.addVar(lb=0.0, ub=HORIZON, name="A")                                       # arrival time at the hub

    m.addConstr(sg.sum() + sl.sum() == 1, "one_start")
    m.addConstr(el.sum() == 1, "one_exit")
    m.addConstr(sb.sum() + sg.sum() == 1, "one_start_bucket")
    m.addConstr(eb.sum() == 1, "one_arrival_bucket")
    for L in sats:                       # the bucket must belong to the satellite that was used
        m.addConstr(gp.quicksum(sl[L, i] for i in C)
                    == gp.quicksum(sb[L, b] for (LL, b) in sbk if LL == L), "sb_%s" % L)
    for p in sats:
        m.addConstr(gp.quicksum(el[i, p] for i in C)
                    == gp.quicksum(eb[p, ba] for (pp, ba) in ebk if pp == p), "eb_%s" % p)
    for i in C:
        m.addConstr(sg[i] + gp.quicksum(sl[L, i] for L in sats)
                    + gp.quicksum(x[j, i] for j in C if (j, i) in x) == y[i], "in_%s" % i)
        m.addConstr(gp.quicksum(el[i, p] for p in sats)
                    + gp.quicksum(x[i, j] for j in C if (i, j) in x) == y[i], "out_%s" % i)
    m.addConstr(gp.quicksum(dem[i] * y[i] for i in C) <= Q, "cap")
    m.addConstr(y.sum() >= 1, "nonempty")

    for (i, j) in arcs:
        bm = max(0.0, l[i] + sv[i] + D[i][j] - e[j])
        m.addConstr(T[j] >= T[i] + sv[i] + D[i][j] - bm * (1 - x[i, j]), "t_%s_%s" % (i, j))
    # the chosen start fixes the earliest arrival at the first customer
    for i in C:
        m.addConstr(T[i] >= H0 + D[g][i] - HORIZON * (1 - sg[i]), "tg_%s" % i)
        for L in sats:
            for (LL, b) in sbk:
                if LL != L:
                    continue
                m.addConstr(T[i] >= H0 + b * dl + D[L][i]
                            - HORIZON * (2 - sl[L, i] - sb[L, b]), "ts_%s_%s_%s" % (L, b, i))
    # A is the arrival time at the chosen hub, and it pins the arrival bucket
    for i in C:
        for p in sats:
            m.addConstr(A >= T[i] + sv[i] + D[i][p] - HORIZON * (1 - el[i, p]), "Alo_%s_%s" % (i, p))
            m.addConstr(A <= T[i] + sv[i] + D[i][p] + HORIZON * (1 - el[i, p]), "Ahi_%s_%s" % (i, p))
    # floor semantics with a margin the solver can actually see: a time ON the boundary belongs
    # to the higher bucket, so the lower edge is inclusive and the upper edge is strict.
    for (p, ba) in ebk:
        m.addConstr(A >= H0 + ba * dl - HORIZON * (1 - eb[p, ba]), "balo_%s_%s" % (p, ba))
        m.addConstr(A <= H0 + (ba + 1) * dl - BUCKET_MARGIN + HORIZON * (1 - eb[p, ba]),
                    "bahi_%s_%s" % (p, ba))

    obj = (gp.quicksum(tc * D[g][i] * sg[i] for i in C)
           + gp.quicksum(tc * D[L][i] * sl[L, i] for L in sats for i in C)
           + gp.quicksum(tc * D[i][j] * x[i, j] for (i, j) in arcs)
           + gp.quicksum(tc * D[i][p] * el[i, p] for i in C for p in sats)
           - gp.quicksum(float(pi.get(i, 0.0)) * y[i] for i in C)
           + float(mu_src) * sg.sum()
           + gp.quicksum(float(mu_post[(L, b)]) * sb[L, b] for (L, b) in sbk)
           - gp.quicksum(float(mu_pre[(p, ba)]) * eb[p, ba] for (p, ba) in ebk))
    m.setObjective(obj, GRB.MINIMIZE)

    if warm_route:
        # PARTIAL MIP START from a route the labelling pricer already knows. Only the arc
        # and visit variables are set; Gurobi repairs the rest. Whether this helps is the
        # open question -- I claimed it could not, the claim rested on a premise the
        # Cutoff measurement refuted, so it is now a trial factor rather than an opinion.
        try:
            for v in list(x.values()) + list(y.values()):
                v.Start = 0.0
            for c in warm_route:
                if c in y:
                    y[c].Start = 1.0
            for a, b in zip(warm_route, warm_route[1:]):
                if (a, b) in x:
                    x[a, b].Start = 1.0
            out_ws = True
        except Exception:
            out_ws = False
    t0 = time.time()
    m.optimize()
    out = dict(model=("exact-variant v0.3 cutoff" if cutoff else "exact-variant v0.2"),
               warm_start=bool(warm_route),
               cutoff=(-EPS if cutoff else None), status=int(m.Status), secs=round(time.time() - t0, 2),
               work=round(float(m.getAttr("Work")), 6), nodes=int(m.NodeCount),
               binaries=len(arcs) + len(sl) + len(sg) + len(sb) + len(el) + len(eb),
               arcs=len(arcs), start_buckets=len(sbk), exit_buckets=len(ebk),
               customers=len(C), dual_bound=None, incumbent=None, route=None, variant=None)
    try:
        out["dual_bound"] = float(m.ObjBound)
    except Exception:
        pass
    if m.SolCount > 0:
        out["incumbent"] = float(m.ObjVal)
        out["mip_gap"] = float(m.MIPGap)
        first = ([i for i in C if sg[i].X > 0.5] or
                 [i for L in sats for i in C if sl[L, i].X > 0.5])
        seq, cur, seen = [], (first[0] if first else None), set()
        while cur is not None and cur not in seen:
            seq.append(cur); seen.add(cur)
            nxt = [j for j in C if (cur, j) in x and x[cur, j].X > 0.5]
            cur = nxt[0] if nxt else None
        out["route"] = seq
        L = ([g] + [LL for (LL, i) in sl if sl[LL, i].X > 0.5])[-1]
        b = ([None] + [bb for (LL, bb) in sbk if sb[LL, bb].X > 0.5])[-1]
        p_ba = [(pp, bb) for (pp, bb) in ebk if eb[pp, bb].X > 0.5]
        out["variant"] = dict(L=L, b=b, p=(p_ba[0][0] if p_ba else None),
                              ba=(p_ba[0][1] if p_ba else None), arrival=float(A.X))
    return out


def verdict(out, exact_rc=None):
    """CONFIRM / COLUMN_EXISTS / INCONCLUSIVE_SLACK / INCONCLUSIVE.

    THE ASYMMETRY IS THE WHOLE POINT, and the first version of this function got it wrong.
    `entry` and `exit_` UNDERESTIMATE every variant's flow-dual terms, so this model's objective
    is a LOWER BOUND on the exact per-variant reduced cost. That makes the two directions
    completely different:

      dual bound >= -eps   SOUND. If the underestimate is non-negative the exact value is too,
                           so no column prices out. This is L-TEP-cert's hypothesis.
      dual bound  < -eps   PROVES NOTHING on its own. The gap may be entirely leg slack.

    Measured on the very first probe, R202 n30: the model returned -240.0230 on route
    [7, 19, 11, 10] and declared COLUMN_EXISTS, while that route's EXACT reduced cost through
    `Master.best_variant` is **+44.0937** -- 284.1168 of pure slack, the same mechanism d430
    measured as worth about 188 at n100. The labelling pricer was right and this function was
    wrong. A negative incumbent is therefore only reported as a column after its exact reduced
    cost has been checked, which is what `exact_rc` is for.
    """
    # GRB.CUTOFF == 6: proved nothing exists below the cutoff. With Cutoff = -eps that IS
    # the certificate, and it arrives without the dual bound ever having to be computed.
    if out.get("cutoff") is not None and out.get("status") == 6:
        return "CONFIRM", (
            "Gurobi returned CUTOFF at %.1e: no column prices out at these duals, proved "
            "by code sharing nothing with the labelling pricer" % out["cutoff"])
    db = out.get("dual_bound")
    if db is None:
        return "INCONCLUSIVE", "no dual bound returned"
    if db >= -EPS:
        return "CONFIRM", ("dual bound %.6f >= -eps: no elementary column prices out at these "
                           "duals, established without the labelling pricer" % db)
    inc, route = out.get("incumbent"), out.get("route")
    if inc is not None and route and exact_rc is not None:
        ex = exact_rc(route)
        out["incumbent_exact_rc"] = ex
        out["leg_slack"] = None if ex is None else (ex - inc)
        if ex is not None and ex < -EPS:
            return "COLUMN_EXISTS", ("route %s prices out at the EXACT reduced cost %.6f "
                                     "(model value %.6f)" % (route, ex, inc))
        if ex is not None and abs(ex - inc) > EPS:
            return "INCONCLUSIVE_SLACK", (
                "model value %.6f but the route's EXACT reduced cost is %+.6f -- %.4f of it is "
                "leg or bucket slack, so nothing is shown either way. The model must carry the "
                "per-variant legs to certify" % (inc, ex, ex - inc))
        if ex is not None:
            # THE MODEL IS EXACT AND FOUND NOTHING NEGATIVE, BUT THE TREE IS NOT CLOSED. This is
            # a different state from slack and was worth its own name: v0.2 reduced the slack to
            # 0.0000 on R202 n30 with an incumbent of exactly 0.0, while the dual bound sat at
            # -163.51 after 270,794 nodes. Nothing is wrong with the formulation; the search has
            # not finished, so "no column exists" is not yet established.
            return "INCONCLUSIVE_UNCLOSED", (
                "the model is EXACT here -- its incumbent %+.6f matches the route's exact "
                "reduced cost %+.6f to within eps -- and it found nothing negative, but the "
                "dual bound is still %.4f, so the search has not closed and no certificate "
                "follows. More budget or a stronger formulation, not a modelling fix."
                % (inc, ex, db))
    return "INCONCLUSIVE", ("dual bound %.6f < -eps and the exact reduced cost was not checked"
                            % db)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--delta", type=float, default=20.0)
    ap.add_argument("--ng", type=int, default=10)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--work", type=float, default=60.0, help="Gurobi WorkLimit for the arbiter")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--bank", action="store_true",
                    help="write a banked artifact under runs/oracle. Default is SMOKE: a log "
                         "line under logs/, which can never be cited as a result")
    ap.add_argument("--proximity", type=float, default=None)
    ap.add_argument("--no-cutoff", dest="cutoff", action="store_false", default=True,
                    help="ask for the optimum instead of the sign; v0.2 behaviour, kept as an arm")
    ap.add_argument("--model", choices=["exact", "underestimate"], default="exact",
                    help="exact = v0.1 per-variant legs (can certify); underestimate = v0.0, kept as the A10 arm")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import tep_cg_bound as T
    from k_comparison import k_proximity
    from stamp import stamped
    prox = k_proximity(a.size) if a.proximity is None else a.proximity

    print("PHASE -1 PROBE -- %s n%d, proximity %.1f, arbiter WorkLimit %.0f, threads %d"
          % (a.cell, a.size, prox, a.work, a.threads), flush=True)
    print("  step 1: run CG to convergence and keep the duals", flush=True)
    t0 = time.time()
    r = T.run(a.cell, a.delta, a.iters, ["prio", "ts"], a.ng, 1000, False, 3_000_000,
              size=a.size, proximity=prox, start_states=True, return_master=True)
    cg_secs = time.time() - t0
    M = r.pop("master")
    print("  CG: lp_street %.4f  proven %s  status %s  %.0fs"
          % (r["lp_street"], r.get("proven"), r.get("status"), cg_secs), flush=True)

    M.solve()
    pi, mu_src, mu_pre, mu_post = M.duals()
    entry, exit_, _exit_fn = M.pricer_legs(mu_src, mu_pre, mu_post)

    print("  step 2: ESPPRC as a MIP at those duals (%s), no labelling code in the path"
          % a.model, flush=True)
    if a.model == "exact":
        out = build_and_solve_exact(M, pi, mu_src, mu_pre, mu_post,
                                    work_limit=a.work, threads=a.threads, cutoff=a.cutoff)
    else:
        out = build_and_solve(M.inst, list(M.C), pi, entry, exit_, M.tc, 50.0,
                              work_limit=a.work, threads=a.threads)
    def _exact_rc(route):
        bv = M.best_variant(list(route), pi, mu_src, mu_pre, mu_post)
        return None if bv is None else float(bv[0])
    v, why = verdict(out, _exact_rc)
    print("  arbiter: status %s  work %.3f  nodes %d  %.1fs  binaries %s"
        % (out["status"], out["work"], out["nodes"], out["secs"], out.get("binaries")))
    print("  dual bound %s | incumbent %s" % (out["dual_bound"], out["incumbent"]))
    print("  VERDICT %s -- %s" % (v, why), flush=True)

    # THE READING, FIXED BEFORE THE RUN (d622): on a converged n30 cell the elementary
    # certificate already says no column prices out, so the arbiter MUST return CONFIRM. A MIP
    # that cannot establish this here will not establish it at n100, and the design changes.
    expected = "CONFIRM" if r.get("proven") else None
    agree = (expected is None) or (v == expected)
    print("  cg proven %s -> expected %s -> %s"
          % (r.get("proven"), expected, "AGREES" if agree else "*** DISAGREES ***"), flush=True)

    payload = dict(probe="DesignDP phase -1", cell=a.cell, size=a.size, proximity=prox,
                   delta=a.delta, ng=a.ng, cg_lp_street=r["lp_street"], cg_proven=r.get("proven"),
                   cg_status=r.get("status"), cg_secs=round(cg_secs, 1),
                   model=a.model, cutoff=a.cutoff, arbiter=out, verdict=v, verdict_why=why,
                   expected=expected, agrees=bool(agree),
                   threads=a.threads,
                   secs=round(time.time() - t0, 1),
                   det_ticks=dict(arbiter_work=out["work"], arbiter_nodes=out["nodes"],
                                  cg_labels=(r.get("det_ticks") or {}).get("pricer_labels")),
                   diagnostic_only=True,
                   valid_bound=False,
                   valid_bound_why="applicability probe for the arbiter; not a bound run")
    # THE PATH CARRIES THE MODEL. v0.0 and v0.1 are two releases and two results, and the
    # cross-release guard refused the collision the first time this ran -- correctly, since
    # the v0.0 artifact is ablation A10's off-arm and is not disposable.
    # THE PATH CARRIES THE MODEL AND THE CODE HASH. Two releases are two results: the guard
    # refused the v0.0->v0.1 collision, and then the v0.1->v0.2 one, both correctly. The model
    # name alone was not enough because v0.1 and v0.2 are the same model, fixed.
    _h = hashlib.sha256(io.open(__file__, "rb").read()).hexdigest()[:8]
    p = a.out or os.path.join(ROOT, "runs" if a.bank else "logs",
                              "oracle" if a.bank else "smoke",
                              "dp_probe_arbiter_%s_n%d_%s_%s.json" % (a.cell, a.size, a.model, _h))
    # STAMP FIRST, OPEN SECOND. Opening truncates, so a refusal from stamped() after the
    # open leaves a 0-byte file behind -- which is what happened to all three hard-cell
    # probes on 2026-09-30 when the source was edited while they were in flight. The
    # refusal itself was correct: the artifact would have recorded a source_hash for code
    # that never ran. The empty file was mine.
    doc = stamped(payload, "analysis/espprc_arbiter.py", "analysis/tep_cg_bound.py",
                  rt_class="diagnostic")
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT), flush=True)
    return 0 if agree else 3


if __name__ == "__main__":
    sys.exit(main())
