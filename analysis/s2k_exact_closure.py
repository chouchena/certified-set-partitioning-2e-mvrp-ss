"""
S2k — does injecting OUR lower bound let an exact solver close a cell K left open?

Applies validation/PREREG_S2k_exact_closure.md exactly, and nothing else.

Two arms per cell, identical apart from one constraint:

  Arm B   K's joint MILP  +  `zObj >= our_LB`        (our dual leg, and nothing else)
  Arm C   K's joint MILP  alone                       (control)

Arm B carries NO MIP start, deliberately: a warm start would conflate the quality of our dual
bound with the quality of our primal incumbent, and a closure could then be credited to either.

`zObj >= our_LB` is VALID -- our LB is a proven lower bound, so it cannot exclude the optimum.
If it ever makes a model INFEASIBLE that is a HARD STOP: the bound would not be valid, and that
invalidates the whole dual leg rather than just this run.

    python analysis/s2k_exact_closure.py --cells C202,C203,R202 --tl 3600

Writes validation/s2k_closure.csv. Exit 0 normally, 2 on a hard stop.
"""
import os, sys, re, csv, json, glob, time, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import kref

OUT = os.path.join(ROOT, "validation", "s2k_closure.csv")
FIELDS = ["ts", "cell", "size", "arm", "our_lb", "status", "obj", "best_bound", "gap_pct",
          "nodes", "wall_s", "tl", "k_joint_bk", "k_lbbd_bk", "k_joint_gap", "closed"]


def our_lb(cell, size):
    """The FROZEN variant's bound, plus the arithmetic term. One artifact, one estimator.

    SIZE-EXACT: 'n10' must never match 'n100' (this bug has bitten this project three times).

    NARROWED 2026-09-16 TO THE FROZEN VARIANT ONLY. This previously globbed
    `easy_reduction(_descend)?_{cell}_n{size}(_.*)?\\.json` and took a raw max over everything
    that matched. That trailing `(_.*)?` admitted every variant on disk -- `_noprov`, `_tl450`,
    `_detl450000`, `_kcapbug`, `_khi70_detl450000` -- and the non-descend ascending sweep as well.
    It is the same wildcard the registry's own `_cells()` guards against with an exclusion list.

    IT DID NOT CHANGE A REPORTED NUMBER, AND IT DID FIRE. C203's injected bound was sourced from
    `easy_reduction_C203_n20.json`, the older ascending sweep, rather than from the descent --
    the two happen to agree at 648.18, so the outcome was clean and the provenance was not. A
    bound injected into the predecessors' model should be the bound the paper reports, by
    construction rather than by coincidence.

    The estimator is `lb_estimator.cell_bound`, the same one the manuscript uses, so what is
    injected here and what is printed there cannot drift apart.
    """
    import lb_estimator
    best = None
    p = os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{size}.json")
    if os.path.exists(p):
        try:
            recs = json.load(open(p))
        except Exception:
            recs = []
        recs = [r for r in (recs if isinstance(recs, list) else [recs])
                if r.get("size") is None or int(r["size"]) == size]
        best = lb_estimator.cell_bound(recs, reproducible_only=True)
    gp = os.path.join(ROOT, "runs", "ab_grid_provenanced.json")
    if os.path.exists(gp):
        for r in json.load(open(gp))["records"]:
            if r["cell"] == cell and r["size"] == size:
                ab = r.get("ab4_full")
                if isinstance(ab, (int, float)) and (best is None or ab > best):
                    best = ab
    return best


def run_arm(cell, size, arm, lb, tl, threads):
    from solver.config import InstanceSpec
    from solver.problem import SolverProblem
    from joint_model_cplex import build_joint_model
    prob = SolverProblem(InstanceSpec(cell, size))
    h = build_joint_model(prob.raw)
    m = h.m
    if arm == "B":
        m.add_constraint(h.zObj >= lb, ctname="our_lower_bound")
    m.parameters.timelimit = tl
    m.parameters.mip.tolerances.mipgap = 0.0
    m.parameters.threads = threads
    t0 = time.time()
    sol = m.solve(log_output=False)
    wall = time.time() - t0
    sd = m.solve_details
    status = sd.status if sd else "no-details"
    obj = sol.objective_value if sol else None
    bb = getattr(sd, "best_bound", None)
    gap = getattr(sd, "mip_relative_gap", None)
    nodes = getattr(sd, "nb_nodes_processed", None)
    # "closed" = proved optimal, i.e. the gap reached zero within the limit
    closed = bool(sol is not None and gap is not None and gap <= 1e-6)
    return dict(status=status, obj=obj, best_bound=bb,
                gap_pct=(gap * 100 if gap is not None else None),
                nodes=nodes, wall_s=round(wall, 1), closed=closed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="C202,C203,R202")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=float, default=3600.0)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    cells = [c.strip() for c in a.cells.split(",") if c.strip()]
    k = kref.table3(a.size)

    new = not os.path.exists(OUT)
    fh = open(OUT, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        w.writeheader()

    hard_stop = False
    for cell in cells:
        lb = our_lb(cell, a.size)
        if lb is None:
            print(f"[s2k] {cell}: no dual bound on record -- skipped", flush=True)
            continue
        for arm in ("B", "C"):
            print(f"[s2k] {cell} n{a.size} arm {arm} "
                  f"({'zObj >= %.3f' % lb if arm == 'B' else 'control'}) tl={a.tl:.0f}s ...",
                  flush=True)
            try:
                r = run_arm(cell, a.size, arm, lb, a.tl, a.threads)
            except Exception as e:
                print(f"  !! {type(e).__name__}: {e}", flush=True)
                r = dict(status=f"ERROR:{type(e).__name__}", obj=None, best_bound=None,
                         gap_pct=None, nodes=None, wall_s=None, closed=False)
            # HARD STOP: a valid lower bound can never make the model infeasible.
            if arm == "B" and isinstance(r["status"], str) and "infeasible" in r["status"].lower():
                print(f"  *** HARD STOP: injecting zObj >= {lb} made {cell} INFEASIBLE.")
                print("      Our dual bound would then be INVALID -- this invalidates the dual")
                print("      leg, not merely this run. Stop and investigate before anything else.")
                hard_stop = True
            w.writerow({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "cell": cell, "size": a.size,
                        "arm": arm, "our_lb": lb, "tl": a.tl,
                        "k_joint_bk": k[cell]["joint_bk"], "k_lbbd_bk": k[cell]["lbbd_bk"],
                        "k_joint_gap": k[cell]["joint_gap"], **r})
            fh.flush()
            print(f"  -> status={r['status']} obj={r['obj']} bound={r['best_bound']} "
                  f"gap={r['gap_pct']}% nodes={r['nodes']} wall={r['wall_s']}s "
                  f"CLOSED={r['closed']}", flush=True)
            if hard_stop:
                fh.close()
                return 2
    fh.close()
    print(f"\n-> {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
