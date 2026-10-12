# ===================== RED FLAG -- TEP USE ONLY (2026-09-28) =====================
# This file REACHES K's FORMULATION (solver/engines/fixopt.py -> build_joint_model ->
# integratedJointModel). The standing constraint is that K's formulation is never part
# of our solution (d449, d451), and the fixopt-based work was archived and locked under
# archive/fixopt_locked/ on 2026-09-28.
#
# THIS FILE WAS NOT ARCHIVED because the admissible TEP path still depends on it.
# It is permitted ONLY where that dependency already exists. It must not be imported by
# new work, and no result derived from it may be reported without saying so.
#
# The load-bearing case: tep_cg_bound.master_ip calls assemble_precluster.retime, which
# builds K's joint model. So every master_ip result passes through K's formulation --
# which contradicts d451's claim that retime was replaced. Unresolved; see
# archive/fixopt_locked/LOCK.md.
# =================================================================================

"""Re-dump the 11 ledger-only incumbents so every quoted primal number is artifact-backed.

Protocol and pre-committed decision rules: validation/PREREG_R1_incumbent_redump.md

Each cell is re-run AT ITS OWN RECORDED CONFIGURATION, read from runs/summary.csv -- seed,
variant, budget, threads, engine -- never from a uniform default. Configs differ wildly across
the eleven (budgets 50s to 5400s, threads 2 or 4, five different fixopt variants), so a uniform
re-run would not reproduce anything.

TIERS (run in this order so the tier that matters finishes first):
  1. exact-solver cells whose optimum is already PROVEN -- C205/n20, R201/n20 (CPLEX),
     R205/n20 (Gurobi). Deterministic; these upgrade objective-identity from "attained" to
     "proven optimal, artifact-backed".
  2. tick-deterministic fixopt cells -- R204/n20, RC208/n20. Must reproduce exactly.
  3. wall-budgeted cells -- MAY NOT reproduce. The decision rule for that case is
     pre-committed in the prereg and implemented in `classify()` below.

EVERY dumped solution is passed through verifier.verify before being accepted. Standing trap:
never report a solver result the verifier has not passed.
"""
import os, sys, csv, json, time, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped

TOL = 0.01          # runs/summary.csv stores final_incumbent rounded; finer is noise
PRIMAL = {"fixopt", "joint_milp_cplex", "joint_milp_gurobi", "lbbd"}

TIER1 = [("C205", 20, "cplex"), ("R201", 20, "cplex"), ("R205", 20, "gurobi")]
TIER2 = [("R204", 20), ("RC208", 20)]
TIER3 = [("R203", 20), ("R203", 30), ("R211", 30), ("RC201", 10), ("RC204", 30), ("RC208", 30)]


def ledger_best(cell, size):
    """The recorded incumbent we are trying to back, plus the config that produced it."""
    best = None
    with open(os.path.join(ROOT, "runs/summary.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["instance"] != cell or r["size"] != str(size):
                continue
            if r.get("verified", "").lower() != "true":
                continue
            if r.get("quarantined", "").lower() == "true":
                continue
            if r["engine"] not in PRIMAL:
                continue
            try:
                v = float(r["final_incumbent"])
            except (TypeError, ValueError):
                continue
            if best is None or v < best[0]:
                best = (v, r)
    return best


def classify(rec, new):
    """PRE-COMMITTED rule. See the prereg; do not edit after seeing results."""
    if new is None:
        return "FAILED", "no solution produced"
    if abs(new - rec) <= TOL:
        return "MATCH", "artifact now backs the recorded number"
    if new < rec - TOL:
        return "BETTER", ("adopt the new value; EVERY downstream aggregate must be recomputed "
                          "(Wilcoxon, P2, margin analysis)")
    return "WORSE", ("report the reproducible value and RETIRE the unreproducible one; "
                     "record both")


def verify_solution(cell, size, sol):
    """Hard gate: a dump that fails verification is a defect to investigate, never skipped.

    Uses SolverProblem.verify -- the canonical path already used by the probe scripts. Do NOT
    construct `verifier.VInstance` directly here: its signature is
    (instance_name, size, wls, tau, proximity) with **tau defaulting to 0.0**, which is the
    TransferDuration=0 trap that has contaminated four scripts in this project and once
    produced a fake 22% improvement. SolverProblem resolves tau from InstanceSpec ("formula").
    """
    try:
        from solver.config import InstanceSpec
        from solver.problem import SolverProblem
    except Exception as e:                                    # pragma: no cover
        return None, f"verifier unavailable: {e}"
    try:
        v = SolverProblem(InstanceSpec.for_k_comparison(cell, size)).verify(sol)
        ok = getattr(v, "ok", None)
        if ok is None:
            ok = getattr(v, "feasible", None)
        return bool(ok), str(v)[:300]
    except Exception as e:
        return None, f"verification error: {e}"


def run_exact(cell, size, solver, out_path, time_limit):
    """Tier 1. joint_model_* already extracts a full component-level solution; flatten and save."""
    from build_instance import build
    p = build(cell, size, wls=0.1, tau="formula", proximity=0.0, time_limit=time_limit)
    if solver == "gurobi":
        from joint_model_gurobi import joint_synchronized_gurobi as solve
    else:
        from joint_model_cplex import joint_synchronized_cplex as solve
    t0 = time.time()
    res = solve(p, time_limit=time_limit, mip_gap=0.0, threads=4)
    wall = time.time() - t0
    if not res.get("solution"):
        return None, res.get("status"), wall
    rec = dict(res["solution"])
    rec["objVal"] = res["objVal"]
    rec["status"] = res["status"]
    rec["mip_gap"] = res.get("mip_gap")
    rec["best_bound"] = res.get("best_bound")
    rec["wall_s"] = wall
    rec["engine"] = f"joint_milp_{solver}"
    rec["redump"] = True
    json.dump(stamped(rec, __file__), open(out_path, "w"), indent=1, default=str)
    return rec, res["status"], wall


def run_lbbd(cell, size, cfg, out_path, time_limit):
    """Some recorded incumbents came from LBBD, not fixopt. Dispatching on the tier instead of
    on the RECORDED ENGINE would silently run the wrong solver and produce an unrelated number
    -- caught in the dry run for R203/n20."""
    from build_instance import build
    from solver.config import InstanceSpec
    from solver.lbbd import lbbd_solve
    from analysis.k_comparison import k_proximity
    prox = k_proximity(size)          # 0.0 below |C|=100, 0.1 at it; was hardcoded 0.0
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox, time_limit=time_limit)
    spec = InstanceSpec(cell, size, wls=0.1, tau="formula", proximity=prox)
    t0 = time.time()
    res = lbbd_solve(p, spec, cut_arm=cfg.get("cut_arm", "karademir"), time_limit=time_limit)
    wall = time.time() - t0
    if not res.incumbent:
        return None, res.status, wall
    rec = dict(res.incumbent)
    rec["objVal"] = res.incumbent_obj
    rec["status"] = res.status
    rec["engine"] = "lbbd"
    rec["wall_s"] = wall
    rec["redump"] = True
    json.dump(stamped(rec, __file__), open(out_path, "w"), indent=1, default=str)
    return rec, res.status, wall


def recover_det_budget(cell, size, seed, variant):
    """Recover the DETERMINISTIC tick budget that actually governed a recorded run.

    WHY THIS EXISTS -- defect found 2026-09-15, mid-campaign.
    `runs/summary.csv`'s `config_json` does NOT carry `det_budget`, even for runs whose
    recorded terminal status is `det_budget_exhausted` -- i.e. runs where the tick budget was
    the PRIMARY stop rule and the wall figure was only a safety cap. Rebuilding the command
    line from `config_json` alone therefore silently re-ran those cells under the WALL cap,
    which is a different stop rule and a different amount of search.

    The symptom was unmistakable once looked at: the originals terminate
    `det_budget_exhausted`, the re-runs terminate `ok`. Two different stop rules, so the
    comparison was never like-for-like, and the pre-committed rule would have RETIRED two
    valid verified incumbents (R204 582.795, RC208 682.923) on the strength of it.

    The value is recoverable: the per-run event log records it on the `run_start` line. The
    campaign scripts corroborate -- every 400 s fixopt launch pairs with `--det-budget 434000`.
    Returns None when nothing can be recovered, and the caller must then treat the cell as
    wall-budgeted rather than guess.
    """
    import glob as _glob
    pat = os.path.join(ROOT, "runs",
                       f"fixopt_{cell}_n{size}_s{seed}_{variant}_*.jsonl")
    seen = set()
    for f in sorted(_glob.glob(pat)):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"det_budget"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    # It appears on the `det_budget_spent` events under extra, and may also
                    # sit in the run_start config block. Take it from wherever it is.
                    ex = d.get("extra") or {}
                    for v in (ex.get("det_budget"),
                              (ex.get("config") or {}).get("det_budget")):
                        if v:
                            seen.add(float(v))
        except OSError:
            continue
    if len(seen) > 1:
        # Never average or pick one: differing budgets across logs for the same
        # seed/variant means the identity of the recorded run is genuinely ambiguous.
        print(f"    [warn] {cell}/n{size} s{seed} {variant}: conflicting det budgets "
              f"{sorted(seen)} -- refusing to guess")
        return None
    return seen.pop() if seen else None


def run_fixopt(cell, size, cfg, seed, out_path):
    """Tiers 2 and 3. Re-run fixopt at the RECORDED configuration."""
    cmd = [sys.executable, os.path.join(ROOT, "solver", "engines", "fixopt.py"),
           "--instance", cell, "--size", str(size),
           "--budget", str(cfg.get("budget", 300.0)),
           "--iter-tl", str(cfg.get("iter_tl", 25.0)),
           "--threads", str(cfg.get("threads", 4)),
           "--seed", str(seed if seed not in (None, "") else 0),
           "--variant", str(cfg.get("variant", "redump")),
           "--dump-best", out_path]
    det = cfg.get("det_budget") or recover_det_budget(
        cell, size, seed if seed not in (None, "") else 0, cfg.get("variant", "redump"))
    if det:
        # The tick budget is the PRIMARY stop rule when set; without it the wall cap decides,
        # and the re-run is not the recorded run.
        cmd += ["--det-budget", str(det)]
        print(f"    det budget recovered: {det:.0f} ticks")
    if cfg.get("route_segment"):
        cmd.append("--route-segment")
    if cfg.get("kick_patience"):
        cmd += ["--kick-patience", str(cfg["kick_patience"])]
    if not cfg.get("frontload", True):
        cmd.append("--no-frontload")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.time() - t0
    if proc.returncode != 0 or not os.path.exists(out_path):
        return None, f"rc={proc.returncode}", wall, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.load(open(out_path)), "ok", wall, proc.stdout[-800:]


def main(tiers, dry, only=None, wall_cap=None, tl_override=None):
    """
    `only`        restrict the plan to named cells (corrective re-runs of specific defects)
    `wall_cap`    override the fixopt WALL budget. The tick budget stays the primary stop
                  rule; this raises the SAFETY CAP so it cannot bind first. RC208/n20 spent
                  its 434000 ticks in 398.0 s against a 400 s cap -- 0.5% of headroom -- so
                  the cap, not the ticks, decided the re-run.
    `tl_override` override the time limit handed to the EXACT and LBBD paths. The computed
                  default is max(600, recorded wall_s * 2), and for R205/n20 that read the
                  wall time of a fixopt ledger row rather than of the Gurobi row that
                  actually reached optimality in 4116 s -- so the exact solve was given
                  roughly 600 s and duly hit the limit at 674.151 instead of reproducing
                  642.216. The limit was the defect, not the solver.
    """
    outdir = os.path.join(ROOT, "results", "portfolio")
    os.makedirs(outdir, exist_ok=True)
    logdir = os.path.join(ROOT, "logs", "redump_R1")
    os.makedirs(logdir, exist_ok=True)
    results = []

    plan = []
    if 1 in tiers:
        plan += [("1", c, s, solver) for c, s, solver in TIER1]
    if 2 in tiers:
        plan += [("2", c, s, None) for c, s in TIER2]
    if 3 in tiers:
        plan += [("3", c, s, None) for c, s in TIER3]

    if only:
        want = {c.strip().upper() for c in only}
        before = len(plan)
        plan = [p for p in plan if p[1].upper() in want]
        print(f"[redump] --only {sorted(want)}: {len(plan)} of {before} planned cells")
        missing = want - {p[1].upper() for p in plan}
        if missing:
            print(f"[redump] !! --only named cells not in any selected tier: {sorted(missing)}")

    for tier, cell, size, solver in plan:
        lb = ledger_best(cell, size)
        if lb is None:
            print(f"[{cell}/n{size}] NO ledger row -- skipped"); continue
        rec, row = lb
        cfg = json.loads(row["config_json"]) if row.get("config_json") else {}
        print(f"\n=== TIER {tier}  {cell}/n{size}  recorded {rec:.3f} "
              f"({row['engine']}, seed={row['seed'] or '-'}, variant={cfg.get('variant','-')}) ===",
              flush=True)
        if dry:
            eng = ("exact " + solver) if solver else row["engine"]
            print(f"    would run: {eng}  budget={cfg.get('budget', '(engine default)')} "
                  f"threads={cfg.get('threads', '(default)')} "
                  f"cut_arm={cfg.get('cut_arm', '-')}")
            continue

        out = os.path.join(outdir, f"{cell}_n{size}_redump.json")
        stdout = ""
        tl_default = max(600.0, float(row["wall_s"]) * 2.0)
        tl = float(tl_override) if tl_override else tl_default
        if tl_override:
            print(f"    time limit OVERRIDDEN to {tl:.0f}s "
                  f"(computed default would be {tl_default:.0f}s)")
        # DISPATCH ON THE RECORDED ENGINE, never on the tier. The dry run showed R203/n20 was
        # produced by LBBD while its tier list implied fixopt; running fixopt there would have
        # produced an unrelated number and "backed" nothing.
        if solver:
            sol, status, wall = run_exact(cell, size, solver, out, tl)
        elif row["engine"] == "lbbd":
            sol, status, wall = run_lbbd(cell, size, cfg, out, tl)
        elif row["engine"] == "fixopt":
            if wall_cap:
                cfg = dict(cfg, budget=float(wall_cap))
                print(f"    wall SAFETY CAP raised to {float(wall_cap):.0f}s; the tick "
                      f"budget remains the primary stop rule")
            sol, status, wall, stdout = run_fixopt(cell, size, cfg, row["seed"], out)
        else:
            print(f"    !! engine {row['engine']!r} has no re-dump path -- SKIPPED"); continue

        new = sol.get("objVal") if sol else None
        verdict, action = classify(rec, new)
        ok, vmsg = (None, "not attempted") if sol is None else verify_solution(cell, size, sol)
        print(f"    -> new={new}  status={status}  wall={wall:.1f}s  VERDICT={verdict}")
        print(f"       verifier: {ok}  ({vmsg[:120]})")
        print(f"       action  : {action}")
        if ok is False:
            print("       !! VERIFIER FAILED -- this is a DEFECT to investigate, not a skip.")

        results.append(dict(tier=tier, cell=cell, size=size, recorded=rec, new=new,
                            verdict=verdict, action=action, verifier_ok=ok,
                            status=status, wall_s=round(wall, 1),
                            engine=row["engine"], seed=row["seed"],
                            variant=cfg.get("variant"), out=os.path.relpath(out, ROOT)))
        json.dump(stamped(results, __file__), open(os.path.join(logdir, "results.json"), "w"), indent=1, default=str)
        if stdout:
            open(os.path.join(logdir, f"{cell}_n{size}.txt"), "w").write(stdout)

    if results:
        print("\n===== SUMMARY =====")
        for r in results:
            print(f"  T{r['tier']} {r['cell']}/n{r['size']:<3} rec={r['recorded']:9.3f} "
                  f"new={str(r['new']):>10s}  {r['verdict']:7s} verifier={r['verifier_ok']}")
        from collections import Counter
        print("  " + str(dict(Counter(r["verdict"] for r in results))))
        bad = [r for r in results if r["verifier_ok"] is False]
        if bad:
            print(f"  !! {len(bad)} VERIFIER FAILURES -- investigate before accepting anything")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="1,2,3")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None,
                    help="comma-separated cells; restrict the plan to these")
    ap.add_argument("--wall-cap", type=float, default=None,
                    help="override the fixopt WALL budget (safety cap). The tick "
                         "budget stays the primary stop rule.")
    ap.add_argument("--tl", type=float, default=None,
                    help="override the time limit for the exact and LBBD paths")
    a = ap.parse_args()
    main([int(x) for x in a.tiers.split(",") if x.strip()], a.dry_run,
         only=[c for c in (a.only or "").split(",") if c.strip()] or None,
         wall_cap=a.wall_cap, tl_override=a.tl)
