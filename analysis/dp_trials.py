"""Phase -1, structured: one trial matrix over formulation x work x grid x warm start x size.

    python analysis/dp_trials.py --cells "30:R202,20:C201" --out T1

SMOKE, NOT A RESULT. One row per trial into logs/smoke/trials_<tag>.tsv, nothing under runs/.

WHY A MATRIX AND NOT MORE ONE-OFF PROBES. Everything so far moved one factor at a time and I
drew three conclusions that measurement then overturned: v0.3 called a null result when it
halved the work, "warm start cannot help" resting on a premise Cutoff had already refuted, and
--root-only reported as the arbiter's bound when it understates it by up to 3.5x. Single probes
with a story attached have a bad record here. This runs the factors together and logs the cells
of the table.

THE ARCHITECTURAL POINT, which is what makes the matrix affordable. CG dominates everything --
587 s on C204 n30, 246 s on R208 n30, 208 s on R208 n20, against arbiter solves of 0.4 to 4
work units. So CG runs ONCE per cell and every configuration is scored against THE SAME DUALS.
That makes the comparisons paired: any difference between two rows of one cell is the factor,
not the dual vector, which is the confound that voided the first hard-cell run.

FACTORS
  formulation  v03      big-M with Cutoff = -eps          (analysis/espprc_arbiter.py)
               v03nc    big-M, no cutoff, v0.2 behaviour
               v04      time-expanded DAG                 (analysis/espprc_arbiter_dag.py)
  work         10 / 100 / 1000 deterministic units. v04 is expected flat -- it closes at the
               root in about 1 unit -- and v03 rising. If v03 never catches v04's 1-unit value,
               the work cap question is answered for good.
  grid         v04 only: 20 / 10 / 5. Finer is tighter and CONFIRM is sound at every setting.
  warm start   v03 only, and the asymmetry is deliberate. v04 closes at the ROOT, so its bound
               IS the LP relaxation value and no incumbent can move it -- that argument is
               about there being no tree, not about pruning, and it does not depend on the
               premise that was refuted. For v03 there is a tree, so it is an open question.
               The warm route is the best column already in the master's pool, scored by
               Master.best_variant: genuinely what the labelling pricer knows.

THREAD COUNT IS FIXED AT 4 AND IS NOT A FACTOR HERE. Work is deterministic at a FIXED thread
count -- measured today, 300.099 against 300.112 across co-tenant and solo runs -- but d45 is
explicit that changing the count "invalidates every tick budget calibrated at 4". --threads-trial
tests that separately on one cell rather than assuming it.
"""
import argparse
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

WORKS = (10.0, 100.0, 1000.0)
GRIDS = (20.0, 10.0, 5.0)
COLS = ("cell size formulation grid work ws status dual_bound incumbent exact_rc "
        "bbnodes work_used secs graph cg_secs cg_lp").split()


def best_pool_route(M, pi, mu_src, mu_pre, mu_post, cap=4000):
    """The most negative column already in the master's pool -- what the pricer actually knows."""
    best = (0.0, None)
    for k in list(M.cols)[:cap]:
        seq = list(k[0])
        try:
            bv = M.best_variant(seq, pi, mu_src, mu_pre, mu_post)
        except Exception:
            continue
        if bv and bv[0] < best[0]:
            best = (bv[0], seq)
    return best[1]


def run_cell(size, cell, iters, grids, works, do_ws, threads, wr):
    import tep_cg_bound as T
    from k_comparison import k_proximity
    from espprc_arbiter import build_and_solve_exact
    from espprc_arbiter_dag import solve_dag

    prox = k_proximity(size)
    t0 = time.time()
    r = T.run(cell, 20.0, iters, ["prio", "ts"], 10, 1000, False, 3_000_000,
              size=size, proximity=prox, start_states=True, return_master=True)
    M = r.pop("master"); M.solve()
    cg_secs, cg_lp = round(time.time() - t0, 1), r["lp_street"]
    pi, mu_src, mu_pre, mu_post = M.duals()
    print("  %s n%d: CG %.0fs lp %.4f proven %s" % (cell, size, cg_secs, cg_lp, r.get("proven")),
          flush=True)

    warm = best_pool_route(M, pi, mu_src, mu_pre, mu_post) if do_ws else None

    def emit(form, grid, work, ws, o):
        ex = None
        if o.get("route"):
            bv = M.best_variant(list(o["route"]), pi, mu_src, mu_pre, mu_post)
            ex = None if bv is None else round(float(bv[0]), 6)
        row = dict(cell=cell, size=size, formulation=form, grid=grid, work=work, ws=int(bool(ws)),
                   status=o.get("status"), dual_bound=o.get("dual_bound"),
                   incumbent=o.get("incumbent"), exact_rc=ex,
                   bbnodes=o.get("nodes", o.get("nodes_explored")),
                   work_used=o.get("work"), secs=o.get("secs"),
                   graph=o.get("nodes") if form == "v04" else o.get("binaries"),
                   cg_secs=cg_secs, cg_lp=round(cg_lp, 4))
        wr(row)
        print("    %-6s g%-4s w%-6s ws%d -> status %-3s bound %s" %
              (form, grid if grid else "-", work, int(bool(ws)), o.get("status"),
               ("%.4f" % o["dual_bound"]) if o.get("dual_bound") is not None else "-"), flush=True)

    for work in works:
        for form, cut in (("v03", True), ("v03nc", False)):
            o = build_and_solve_exact(M, pi, mu_src, mu_pre, mu_post, work_limit=work,
                                      threads=threads, cutoff=cut)
            emit(form, None, work, False, o)
        if warm:
            o = build_and_solve_exact(M, pi, mu_src, mu_pre, mu_post, work_limit=work,
                                      threads=threads, cutoff=True, warm_route=warm)
            emit("v03", None, work, True, o)
        for grid in grids:
            o = solve_dag(M, pi, mu_src, mu_pre, mu_post, grid=grid, work_limit=work,
                          threads=threads)
            emit("v04", grid, work, False, o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True, help="comma list of size:CELL, e.g. 30:R202,20:C201")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--no-ws", dest="ws", action="store_false", default=True)
    ap.add_argument("--grids", default=",".join(str(g) for g in GRIDS))
    ap.add_argument("--works", default=",".join(str(w) for w in WORKS))
    a = ap.parse_args()

    path = os.path.join(ROOT, "logs", "smoke", "trials_%s.tsv" % a.out)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")

    def wr(row):
        with io.open(path, "a", encoding="utf-8") as f:
            f.write("\t".join(str(row.get(c, "")) for c in COLS) + "\n")

    grids = [float(x) for x in a.grids.split(",") if x]
    works = [float(x) for x in a.works.split(",") if x]
    print("trials -> %s | grids %s | works %s | threads %d"
          % (os.path.relpath(path, ROOT), grids, works, a.threads), flush=True)
    for spec in a.cells.split(","):
        size, cell = spec.split(":")
        try:
            run_cell(int(size), cell, a.iters, grids, works, a.ws, a.threads, wr)
        except Exception as e:
            print("  %s n%s FAILED: %s: %s" % (cell, size, type(e).__name__, e), flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
