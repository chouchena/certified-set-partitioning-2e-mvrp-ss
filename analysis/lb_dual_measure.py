"""DUAL-ONLY measurement driver (Stage 1, 2026-10-01): LB & OV vs time, HARD-capped wallclock,
wise + tracked cores. NO primal leg.

Why this exists: to replace beliefs about the dual's budget need with the measured LB(t)/OV(t)
trajectory on the most RT-expensive cells, so the dual/primal split of the 5760 s envelope is set
from evidence, not assumption (validation/TRAJECTORY_FALSIFY_integrated_dualprimal.md, F1).

Design (all agreed 2026-10-01):
  * HARD KILL: each cell runs in a managed multiprocessing.Process; the parent terminates it at
    the deadline, so the 5760 s cap is GUARANTEED regardless of between-iteration overshoot. The
    soft per-rung max_secs is kept UNDERNEATH (graceful budgeting + lets the ladder try cheaper
    rungs); the hard kill is the last-resort backstop.
  * SEQUENTIAL ladder at 1 worker x THREADS cores -- wise core use (threads match K's 4), memory
    safe (one master at a time), and a clean step-wise LB(t) curve. degree x threads ~= 4.
  * COMPILE/WARM OUT OF RT: `compileall` once before the batch; each worker warms its Gurobi
    env/license BEFORE starting its own clock, so import+license is off the trajectory's RT.
  * INCREMENTAL TRAJECTORY: every LB rise and OV refresh is appended to a per-cell .jsonl and
    flushed, so a hard-killed cell still keeps its trajectory up to the kill.
  * DUAL ONLY: master_ip produces the OV byproduct (monitored + gates); no ALNS/refine/fixopt.
  * CORES TRACKED: degree, threads, cores_used, tenancy, and per-rung LP-vs-pricing recorded.
Outputs go to logs/dual_measure/ (diagnostics, NOT banked bounds; not swept by the guillotine).
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

OUTDIR = os.path.join(ROOT, "logs", "dual_measure")


def _emit(fh, rec):
    fh.write(json.dumps(rec, default=str) + "\n")
    fh.flush()
    os.fsync(fh.fileno())          # survive a hard terminate()


def _measure_worker(cell, size, threads, wall, outpath):
    """Runs in its own process. Warms the license, THEN starts its clock and runs the dual ladder
    sequentially, appending (t, lb, ov, work, event) to outpath after every step."""
    import lb_solver as L
    import lb_solver_v2 as V2
    import tep_cg_bound as T
    import verifier3 as V
    from bound_certificate import certified, ng_certified
    import gurobipy as gp

    m = gp.Model(); m.dispose()                 # WARM: env + license, before the clock
    try:
        import tep_pricer  # noqa  (force import/compile off the clock)
    except Exception:
        pass

    prox = L.k_proximity(size)
    fh = io.open(outpath, "w", encoding="utf-8")
    t0 = time.time()
    clk = lambda: round(time.time() - t0, 3)

    ab = L.ab4_floor(cell, size, prox)
    lb, carrier, cert = ab["ab4"], "ab4", None
    water = ab["water"]
    ov, _ = V2.constructor_ov(cell, size)
    ov_constructor = ov
    _emit(fh, dict(t=0.0, lb=round(lb, 6), ov=(round(ov, 6) if ov else None),
                   event="seed", carrier="ab4", cert=None,
                   cores=dict(degree=1, threads=threads, cores_used=threads, tenancy=1)))

    inst = V.load_instance(cell, size, prox)
    specs, _dflt, ladder = V2._rung_specs(cell, size, inst)
    done_kinds = set()
    for delta, customers, tag in specs:
        kind = "sub" if customers else "tep"
        if kind in done_kinds:
            continue
        left = wall - (time.time() - t0)
        if left < L.MIN_RUNG_SECS:
            _emit(fh, dict(t=clk(), lb=round(lb, 6), ov=(round(ov, 6) if ov else None),
                           event="stop:budget", rung=tag))
            break
        if ov is not None and ov - lb < V2.GAIN_CEILING_MIN:          # G0 gain gate
            _emit(fh, dict(t=clk(), lb=round(lb, 6), ov=round(ov, 6), event="skip:gain_ceiling",
                           rung=tag, gain_ceiling=round(ov - lb, 6)))
            continue
        soft = max(left - V2.OV_IP_TIMELIMIT - 10.0, 1.0)
        trun = time.time()
        try:
            r = T.run(cell, delta, 400, ["prio", "ts"], 10, 1000, False, L.LABEL_CAP, size=size,
                      proximity=prox, max_secs=soft, start_states=True, threads=threads,
                      customers=customers, return_master=True)
        except Exception as e:
            _emit(fh, dict(t=clk(), event="error:rung", rung=tag,
                           error="%s: %s" % (type(e).__name__, str(e)[:160])))
            done_kinds.add(kind); continue
        M = r.pop("master", None)
        cls = "elementary" if certified(r) else ("ng" if ng_certified(r) else None)
        lp = r.get("lp_street")
        composed = (float(lp) + water) if (cls and lp is not None) else None
        rung_secs = round(time.time() - trun, 2)
        if composed is not None and composed > lb + 1e-9:
            lb, carrier, cert = composed, tag, cls
            _emit(fh, dict(t=clk(), lb=round(lb, 6), ov=(round(ov, 6) if ov else None),
                           event="LB", rung=tag, cert=cls, rung_secs=rung_secs,
                           gurobi_work=(r.get("det_ticks") or {}).get("gurobi_work"),
                           iters=r.get("iters")))
        # master_ip OV byproduct (dual's own columns, K-free), min-tracked
        if M is not None:
            try:
                ovr = T.master_ip(M, cell, size, threads=threads, timelimit=V2.OV_IP_TIMELIMIT)
                if ovr.get("verified") and ovr.get("objVal") is not None:
                    cand = float(ovr["objVal"])
                    if ov is None or cand < ov:
                        ov = cand
                        _emit(fh, dict(t=clk(), lb=round(lb, 6), ov=round(ov, 6), event="OV",
                                       rung=tag, ov_secs=ovr.get("ip_secs")))
                M.m.dispose()
            except Exception as e:
                _emit(fh, dict(t=clk(), event="error:ov", rung=tag, error=str(e)[:120]))
        if cls is None:
            done_kinds.add(kind)
    _emit(fh, dict(t=clk(), event="FINAL", lb=round(lb, 6), lb_carrier=carrier, certificate=cert,
                   ov_constructor=(round(ov_constructor, 6) if ov_constructor else None),
                   ov_final=(round(ov, 6) if ov else None), ab4=round(ab["ab4"], 6),
                   total_s=clk(), ladder=ladder, self_stopped=True))
    fh.close()


def measure_cell(cell, size, wall=5760.0, threads=4, warm_margin=180.0):
    """Parent: spawn the worker, hard-kill at the deadline, read back the trajectory."""
    os.makedirs(OUTDIR, exist_ok=True)
    outpath = os.path.join(OUTDIR, "%s_n%d.jsonl" % (cell, size))
    p = mp.Process(target=_measure_worker, args=(cell, size, threads, wall, outpath))
    t_spawn = time.time()
    p.start()
    p.join(timeout=wall + warm_margin)               # HARD deadline (incl. warm)
    hard_killed = False
    if p.is_alive():
        p.terminate(); p.join()
        hard_killed = True
    wall_spawn_to_end = round(time.time() - t_spawn, 1)
    # read back whatever the worker flushed (survives a terminate)
    traj = []
    if os.path.exists(outpath):
        for ln in io.open(outpath, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try: traj.append(json.loads(ln))
                except Exception: pass
    final = next((r for r in reversed(traj) if r.get("event") == "FINAL"), None)
    lb = final["lb"] if final else (traj[-1].get("lb") if traj else None)
    tot = final["total_s"] if final else (traj[-1].get("t") if traj else None)
    return dict(cell=cell, size=size, hard_killed=hard_killed, self_stopped=bool(final),
                total_s=tot, wall_cap=wall, wall_spawn_to_end=wall_spawn_to_end,
                within_cap=(tot is not None and tot <= wall + 20), lb=lb,
                lb_carrier=(final or {}).get("lb_carrier"),
                certificate=(final or {}).get("certificate"),
                ov_final=(final or {}).get("ov_final"), n_points=len(traj), outpath=outpath)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True, help="e.g. RC204:100 R207:100")
    ap.add_argument("--wall", type=float, default=5760.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--deadline", default=None, help="HH:MM local; stop launching new cells after")
    a = ap.parse_args()

    import subprocess
    print("[compileall] out-of-RT bytecode ...", flush=True)
    subprocess.run([sys.executable, "-m", "compileall", "-q", os.path.join(ROOT, "analysis")],
                   check=False)

    dl = None
    if a.deadline:
        hh, mm = map(int, a.deadline.split(":"))
        now = time.localtime()
        import calendar
        tgt = list(now); tgt[3], tgt[4], tgt[5] = hh, mm, 0
        dl = time.mktime(tuple(tgt))
        if dl <= time.time():
            dl += 86400              # tomorrow

    for spec in a.cells:
        if dl and time.time() >= dl:
            print("[deadline reached] stopping before %s" % spec, flush=True); break
        cell, size = spec.split(":"); size = int(size)
        print("=" * 70, flush=True)
        print("[measure] %s n%d  wall=%.0f threads=%d  (%s)"
              % (cell, size, a.wall, a.threads, time.strftime("%H:%M:%S")), flush=True)
        t = time.time()
        res = measure_cell(cell, size, wall=a.wall, threads=a.threads)
        res["measured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        print("  -> lb=%s cert=%s total_s=%s within_cap=%s hard_killed=%s self_stopped=%s "
              "points=%d (wall %.0fs)" % (res["lb"], res["certificate"], res["total_s"],
              res["within_cap"], res["hard_killed"], res["self_stopped"], res["n_points"],
              res["wall_spawn_to_end"]), flush=True)
        io.open(os.path.join(OUTDIR, "SUMMARY.jsonl"), "a", encoding="utf-8").write(
            json.dumps(res, default=str) + "\n")
    print("[done]", time.strftime("%H:%M:%S"), flush=True)


if __name__ == "__main__":
    main()
