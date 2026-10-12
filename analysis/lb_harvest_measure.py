"""LAGRANGIAN-HARVEST measurement driver (Stage 2, 2026-10-02): valid LB(t) trajectory for a
SINGLE rung run STANDALONE, cap-agnostic, hard guillotine. Produces the within-rung valid-bound
curve the dual-only batch could not (it banked only at rung completion, so killed rungs yielded
nothing).

Design (all agreed 2026-10-02):
  * SINGLE RUNG, STANDALONE. Each target is (cell,size,delta). Rungs are cold/from-scratch in the
    solver (no inheritance), so a standalone rung reproduces exactly what the ladder's rung does --
    and this is what lets us read finest-first vs coarse-first post-hoc.
  * GATED HARVEST. The solver computes a free per-iteration ceiling z_RMP + |C|*best_rc (an upper
    bound on the valid Lagrangian bound); only when it clears the running best LB does it pay for
    the no-prune valid pricing ("then and if"). Bound VALIDITY is the solver's own (start_states
    and not exhausted). Off-by-default in tep_cg_bound; turned on here via harvest_cb.
  * CAP-AGNOSTIC. max_secs is 0 -- the 5760 plays NO role in behaviour. The stop rule is: soft
    target at `soft` (=5760), but defer the actual stop to the NEXT banked valid LB (or stop at
    once if the ceiling can no longer clear best_lb); `runaway` is a hard backstop only. The cap is
    chosen POST-HOC from the trajectory; the run is a truncatable RT simulation.
  * REDUCED->FULL. CG bounds the reduced instance; the full LB is `bound + water`, water constant
    per cell. The gate threshold is therefore seeded at (ab4 - water) in reduced space.
  * INCREMENTAL + fsync, so a hard-killed run keeps its trajectory to the kill.
Outputs go to logs/harvest_measure/ (diagnostics, NOT banked bounds; not swept by the guillotine).
"""
import argparse
import io
import json
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

OUTDIR = os.path.join(ROOT, "logs", "harvest_measure")


def _emit(fh, rec):
    fh.write(json.dumps(rec, default=str) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


def _harvest_worker(cell, size, delta, tag, threads, soft, runaway, outpath):
    import lb_solver as L
    import tep_cg_bound as T
    import gurobipy as gp

    m = gp.Model(); m.dispose()                 # WARM env/license before the clock
    try:
        import tep_pricer  # noqa
    except Exception:
        pass

    prox = L.k_proximity(size)
    fh = io.open(outpath, "w", encoding="utf-8")
    t0 = time.time()
    clk = lambda: round(time.time() - t0, 3)

    ab = L.ab4_floor(cell, size, prox)
    ab4, water = ab["ab4"], ab["water"]
    _emit(fh, dict(t=0.0, event="seed", cell=cell, size=size, delta=delta, tag=tag,
                   ab4=round(ab4, 6), water=round(water, 6), lb0_reduced=round(ab4 - water, 6),
                   soft=soft, runaway=runaway, threads=threads,
                   cores=dict(degree=1, threads=threads, cores_used=threads, tenancy=1)))

    def cb(rec):
        rec = dict(rec)
        rec["event"] = "harvest"
        if rec.get("bound") is not None:
            rec["lb_full"] = round(rec["bound"] + water, 6)       # reduced -> full
        if rec.get("ceiling") is not None:
            rec["ceiling_full"] = round(rec["ceiling"] + water, 6)
        _emit(fh, rec)

    try:
        r = T.run(cell, delta, 4000, ["prio", "ts"], 10, 1000, False, L.LABEL_CAP, size=size,
                  proximity=prox, max_secs=0.0, start_states=True, threads=threads,
                  harvest_cb=cb, harvest_lb0=(ab4 - water),
                  harvest_soft_secs=soft, harvest_throttle=10.0, harvest_runaway=runaway,
                  return_master=True)
    except Exception as e:
        _emit(fh, dict(t=clk(), event="error", error="%s: %s" % (type(e).__name__, str(e)[:200])))
        fh.close(); return

    # OV endpoint (dual byproduct, K-free): one master_ip solve on the converged pool, so each
    # trajectory carries LB(t) AND an OV for the cheating-plan cap decision. Cheap (<=30 s), and
    # only reached when the rung self-stopped (a hard-killed run is terminated before here).
    ov_final = None
    M = r.pop("master", None)
    if M is not None:
        try:
            ovr = T.master_ip(M, cell, size, threads=threads, timelimit=30.0)
            if ovr.get("verified") and ovr.get("objVal") is not None:
                ov_final = float(ovr["objVal"])
                # KEEP THE VERIFIED INCUMBENT (routes + schedule), not just the objective, so the
                # OV is re-verifiable, bankable and citable. Diagnostic path (logs/), not runs/.
                solpath = None
                sol = ovr.get("solution")
                if sol is not None:
                    # TOP-LEVEL format so analysis/verify_incumbent.py (reviewer tool) ingests it
                    # directly: solution fields (xij, vi, hubs, yij, nCars, nVessel, objVal) at the
                    # root, plus cell/size/_proximity/tag for the instance rebuild.
                    rec = dict(sol)
                    rec.update(cell=cell, size=size, tag=tag, objVal=ov_final,
                               _proximity=prox, verified=True)
                    solpath = os.path.join(OUTDIR, "%s_n%d_%s_incumbent.json" % (cell, size, tag))
                    io.open(solpath, "w", encoding="utf-8").write(json.dumps(rec, default=str))
                _emit(fh, dict(t=clk(), event="OV", cell=cell, tag=tag,
                               ov_final=round(ov_final, 6), ov_secs=ovr.get("ip_secs"),
                               incumbent_saved=solpath))
            M.m.dispose()
        except Exception as e:
            _emit(fh, dict(t=clk(), event="error:ov", tag=tag, error=str(e)[:160]))

    lp = r.get("lp_street")
    composed = (lp + water) if lp is not None else None
    _emit(fh, dict(t=clk(), event="FINAL", cell=cell, size=size, delta=delta, tag=tag,
                   status=r.get("status"), proven=bool(r.get("proven")),
                   lp_reduced=(round(lp, 6) if lp is not None else None),
                   lp_full=(round(composed, 6) if composed is not None else None),
                   ov_final=(round(ov_final, 6) if ov_final is not None else None),
                   ab4=round(ab4, 6), water=round(water, 6),
                   gurobi_work=(r.get("det_ticks") or {}).get("gurobi_work"),
                   iters=r.get("iters"), total_s=clk(), self_stopped=True))
    fh.close()


def measure(cell, size, delta, tag, soft=5760.0, runaway=6912.0, threads=4, warm_margin=240.0):
    os.makedirs(OUTDIR, exist_ok=True)
    outpath = os.path.join(OUTDIR, "%s_n%d_%s.jsonl" % (cell, size, tag))
    p = mp.Process(target=_harvest_worker, args=(cell, size, delta, tag, threads, soft, runaway, outpath))
    t_spawn = time.time()
    p.start()
    p.join(timeout=runaway + warm_margin)
    hard_killed = False
    if p.is_alive():
        p.terminate(); p.join()
        hard_killed = True
    wall_spawn_to_end = round(time.time() - t_spawn, 1)
    traj = []
    if os.path.exists(outpath):
        for ln in io.open(outpath, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try: traj.append(json.loads(ln))
                except Exception: pass
    final = next((r for r in reversed(traj) if r.get("event") == "FINAL"), None)
    banked = [r for r in traj if r.get("banked")]
    best_full = max([r["lb_full"] for r in banked], default=None)
    ab4 = next((r.get("ab4") for r in traj if r.get("event") == "seed"), None)
    return dict(cell=cell, size=size, delta=delta, tag=tag, hard_killed=hard_killed,
                self_stopped=bool(final), status=(final or {}).get("status"),
                ab4=ab4, best_harvest_full=best_full,
                lp_full=(final or {}).get("lp_full"), ov_final=(final or {}).get("ov_final"),
                proven=(final or {}).get("proven"),
                total_s=(final or {}).get("total_s") or (traj[-1].get("t") if traj else None),
                n_points=len(traj), n_banked=len(banked),
                wall_spawn_to_end=wall_spawn_to_end, outpath=outpath)


DEFAULT_TARGETS = [
    # treatment: killed-rung standalone (the within-rung valid LB the dual batch could not get)
    ("C204", 100, 60.0, "d60"),     # the outlier: never completed any CG rung (ab4 floor only)
    ("R207", 100, 10.0, "d10"),
    ("R211", 100, 10.0, "d10"),
    ("RC204", 100, 10.0, "d10"),
    ("C203", 100, 20.0, "d20"),
    # finest-first post-hoc test (cold d1, re-based = finest-first trajectory)
    ("R207", 100, 1.0, "d1"),       # heavy: expect dominated
    ("C205", 100, 1.0, "d1"),       # light: the place finest-first could win
    # negative controls: converging rungs, expect the harvest inert (banks exactly LP*+water)
    ("C201", 100, 60.0, "d60"),
    ("C206", 100, 60.0, "d60"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=None,
                    help="CELL:SIZE:DELTA:TAG ... (default = the agreed treatment+finest+controls)")
    ap.add_argument("--unproven", nargs="*", type=int, default=None,
                    help="sizes; auto-build targets = all best_of proven:false cells at the "
                         "pre-registered family-coarsest grain (C d60, R/RC d20), in the given order")
    ap.add_argument("--soft", type=float, default=5760.0)
    ap.add_argument("--runaway", type=float, default=6912.0,
                    help="hard backstop wall (1.2x soft): bounds the past-soft extension to roughly "
                         "one more near-convergence iteration; past this is region we truncate away")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--deadline", default=None, help="HH:MM local; stop launching after")
    a = ap.parse_args()

    import subprocess
    print("[compileall] out-of-RT bytecode ...", flush=True)
    subprocess.run([sys.executable, "-m", "compileall", "-q", os.path.join(ROOT, "analysis")], check=False)

    if a.unproven:
        targets = []
        for size in a.unproven:
            rows = json.load(io.open(os.path.join(ROOT, "runs", "oracle",
                             "tep_n%d_best_of.json" % size), encoding="utf-8"))["rows"]
            for r in rows:
                if r.get("proven"):
                    continue
                cell = r["cell"]
                delta = 60.0 if cell.startswith("C") else 20.0   # PREREG family-coarsest: C d60, R/RC d20
                targets.append((cell, size, delta, "d%g" % delta))
    elif a.targets:
        targets = []
        for t in a.targets:
            c, s, d, tag = t.split(":")
            targets.append((c, int(s), float(d), tag))
    else:
        targets = DEFAULT_TARGETS

    dl = None
    if a.deadline:
        hh, mm = map(int, a.deadline.split(":"))
        tgt = list(time.localtime()); tgt[3], tgt[4], tgt[5] = hh, mm, 0
        dl = time.mktime(tuple(tgt))
        if dl <= time.time():
            dl += 86400

    for (cell, size, delta, tag) in targets:
        if dl and time.time() >= dl:
            print("[deadline reached] stopping before %s %s" % (cell, tag), flush=True); break
        print("=" * 70, flush=True)
        print("[harvest] %s n%d %s (delta=%g) soft=%.0f runaway=%.0f threads=%d (%s)"
              % (cell, size, tag, delta, a.soft, a.runaway, a.threads, time.strftime("%H:%M:%S")), flush=True)
        res = measure(cell, size, delta, tag, soft=a.soft, runaway=a.runaway, threads=a.threads)
        res["measured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        print("  -> status=%s proven=%s ab4=%s best_harvest_full=%s lp_full=%s total_s=%s "
              "banked=%d points=%d hard_killed=%s (wall %.0fs)"
              % (res["status"], res["proven"], res["ab4"], res["best_harvest_full"], res["lp_full"],
                 res["total_s"], res["n_banked"], res["n_points"], res["hard_killed"],
                 res["wall_spawn_to_end"]), flush=True)
        io.open(os.path.join(OUTDIR, "SUMMARY.jsonl"), "a", encoding="utf-8").write(
            json.dumps(res, default=str) + "\n")
    print("[done]", time.strftime("%H:%M:%S"), flush=True)


if __name__ == "__main__":
    main()
