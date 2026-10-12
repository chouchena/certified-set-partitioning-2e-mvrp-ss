"""
portfolio.py -- the primal cooperative portfolio (unified solver, primal stage).

route_merge fixes RC203/R204 but regresses 5 other cells; no single fixopt
neighbourhood config is a uniform winner (2026-09-02).  A referee needs ONE
config that isn't per-cell tuned.  Answer: run a fixed set of islands in
parallel from a common seed, take the best VERIFIED incumbent.  The "config"
is the island set -- identical for every instance.

  python -m solver.engines.portfolio --instance RC203 --size 20 \
      --budget 600 --total-threads 8 [--warm-json seed.json] [--seed 0]

Islands (fixed):
  merge   route_merge + kick        -- inter-route restructuring
  seg     route_segment + kick      -- intra-route / sub-route
  destroy spatial_destroy frontload -- the baseline LNS
  kick    aggressive kick           -- diversification (short patience, wide frac)

v1 is independent + best-of (no live migration).  Migration is a documented
enhancement; add once v1 is validated on the 11 cells.

Emits per-island + winner to results/ledger.jsonl (experiment=portfolio).
"""
from __future__ import annotations
import sys, os, json, time, argparse, subprocess, re, glob
sys.path.insert(0, ".")
from solver.config import InstanceSpec
from solver.problem import SolverProblem
from analysis.ledger import emit

PY = sys.executable

# Phase B config (validation/phase_a_analysis.md + Phase B-v1 R207 diagnosis):
#   seg  = intensifier: small sub-routes, ~0.4s solves, fast even at 1 thread;
#          ~150-260 iters, converges ~760s then idles -> stall early (300s/2k).
#   kick = diversifier: bursty escapes, still improving at 1500s in Phase A on
#          6/8 runs -> NEEDS 3 threads (at 2t with route_merge it did only 16-19
#          iters / 2400s, 50s solves -- dead weight).  route_merge REMOVED
#          (Phase A merge island did 82 iters, 0 sole-wins -- not worth it).
#          Runs to the 2500s cap, EXCEPT stop early when near-LB (gap<6%).
#   merge DROPPED.
ISLANDS = {
    "merge":   ["--route-merge", "--kick-patience", "45"],
    "seg":     ["--route-segment", "--kick-patience", "45"],
    "destroy": ["--kick-patience", "60"],
    "kick":    ["--kick-patience", "20", "--kick-frac", "0.45", "--no-frontload"],
}
DEFAULT_ISLAND_THREADS = {"seg": 1, "kick": 3, "merge": 3, "destroy": 2}
# per-island stall / migration profile (seconds).
#   seg  = intensifier -> stall early (300s idle + 2 failed kicks), reclaims
#          the ~50-90% dead time Phase A showed after it converges ~760s.
#   kick = diversifier -> LENIENT stall only: Phase A escapes land within ~400s
#          of the last gain (RC203 s0: +83 in the last 400s), so 900s idle + 8
#          failed kicks means genuinely stuck this seed (v3 smoke: kick flat at
#          844 for 875s).  Caps the wasted RT on unlucky seeds (~half of RC203
#          draws) without cutting the escapes.  LB early-exit still applies.
ISLAND_STALL = {
    "seg":  {"stall_patience": 0, "migrate_patience": 150},   # no stall
    "kick": {"stall_patience": 0, "migrate_patience": 120},   # no stall
}


def _parse_best(txt):
    m = re.findall(r"final best \(verified\)\s*=\s*([0-9.]+)\s+wall=([0-9.]+)s", txt)
    if m:
        return float(m[-1][0]), float(m[-1][1])
    m2 = re.findall(r"\+improve obj=([0-9.]+).*verify=OK", txt)
    return (min(map(float, m2)) if m2 else None), None


def run(instance, size, budget, total_threads, seed, warm_json, islands,
        migrate=False, tag="", stall_patience=None, target_lb=None,
        island_threads=None, kick_extra=None):
    outdir = "results/portfolio"
    os.makedirs(outdir, exist_ok=True)
    sfx = f"__{tag}" if tag else ""
    thr = dict(DEFAULT_ISLAND_THREADS)
    if island_threads:
        thr.update(island_threads)
    thr = {n: thr.get(n, max(1, total_threads // len(islands))) for n in islands}
    migrate_path = None
    if migrate:
        migrate_path = f"{outdir}/{instance}_n{size}_s{seed}{sfx}__migrate.json"
        if os.path.exists(migrate_path):
            os.remove(migrate_path)
    print(f"=== primal portfolio  {instance} n{size}{sfx}  "
          f"{'stall' if stall_patience else str(budget)+'s'} cap={budget}s  "
          f"islands={ {n: thr[n] for n in islands} }  seed={seed} "
          f"migrate={bool(migrate_path)} lb={target_lb} ===", flush=True)
    procs, logs, dumps = {}, {}, {}
    t0 = time.time()
    for name in islands:
        log = f"{outdir}/{instance}_n{size}_s{seed}{sfx}__{name}.log"
        dump = f"{outdir}/{instance}_n{size}_s{seed}{sfx}__{name}.sol.json"
        logs[name], dumps[name] = log, dump
        for f in (dump,):
            if os.path.exists(f):
                os.remove(f)
        cmd = [PY, "solver/engines/fixopt.py", "--instance", instance, "--size", str(size),
               "--budget", str(budget), "--threads", str(thr[name]), "--seed", str(seed),
               "--variant", f"pf_{name}", "--dump-best", dump] + ISLANDS[name]
        if warm_json:
            cmd += ["--warm-json", warm_json]
        if migrate_path:
            cmd += ["--migrate-path", migrate_path]
        if target_lb:
            cmd += ["--target-lb", str(target_lb)]
        if name == "kick" and kick_extra:
            cmd += list(kick_extra)
        prof = ISLAND_STALL.get(name, {})
        # run-until-stall ABANDONED (2026-09-04): both operators produce sparse
        # but CONTINUOUS improvement over the full budget -- the Phase A "dead
        # time after convergence" was actually slow productive grind (seg went
        # 635->582 over iters 42-261).  Any idle-based stall cuts that.  Fixed
        # --budget + LB early-exit is the model.  stall_patience>0 -> opt-in.
        if prof.get("stall_patience", 0) > 0:
            cmd += ["--stall-patience", str(prof["stall_patience"]),
                    "--stall-kicks", str(prof.get("stall_kicks", 2)),
                    "--stall-lb-frac", str(prof.get("stall_lb_frac", 0.0))]
        if prof.get("migrate_patience"):
            cmd += ["--migrate-patience", str(prof["migrate_patience"])]
        procs[name] = subprocess.Popen(cmd, stdout=open(log, "w"), stderr=subprocess.STDOUT)

    for name, pr in procs.items():
        pr.wait()
    wall = time.time() - t0

    # collect each island's newest RunLogger jsonl into a namespaced copy
    tracedir = f"{outdir}/trace"
    os.makedirs(tracedir, exist_ok=True)
    for name in islands:
        cand = sorted(glob.glob(f"runs/fixopt_{instance}_n{size}_s{seed}_pf_{name}_*.jsonl"),
                      key=os.path.getmtime)
        if cand:
            import shutil
            shutil.copy(cand[-1], f"{tracedir}/{instance}_n{size}_s{seed}{sfx}__{name}.jsonl")

    results = {}
    for name, log in logs.items():
        txt = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
        obj, tbest = _parse_best(txt)
        results[name] = {"obj": obj, "t_best": tbest}
        print(f"  {name}: final={obj}  t_best={tbest}", flush=True)

    finite = {n: r["obj"] for n, r in results.items() if r["obj"] is not None}
    winner = min(finite, key=finite.get) if finite else None
    best = finite.get(winner)

    # RULE: independent verifier on every primal result.  Re-verify the winning
    # island's dumped solution with a FRESH SolverProblem/verifier instance.
    verified = None
    if winner and os.path.exists(dumps[winner]):
        try:
            sol = json.load(open(dumps[winner]))
            vprob = SolverProblem(InstanceSpec(instance, size))
            vd = vprob.verify(sol)
            verified = bool(vd.ok)
            print(f"  [verify] winner {winner}: ok={vd.ok} recomputed={vd.recomputed_obj} "
                  f"(reported {best})  viol={vd.violations[:2]}", flush=True)
            if vd.ok and vd.recomputed_obj is not None:
                best = vd.recomputed_obj
        except Exception as ex:
            print(f"  [verify] FAILED to re-verify winner: {ex}", flush=True)
            verified = False

    for n, r in results.items():
        emit("portfolio", instance, size,
             config=dict(island=n, cap_s=budget, threads=thr[n], seed=seed,
                         tag=tag, migrate=bool(migrate_path), stall=bool(stall_patience),
                         warm=bool(warm_json)),
             metrics=dict(final_obj=r["obj"], t_best=r["t_best"], won=(n == winner)),
             wall_s=wall, verified=(verified if n == winner else None))

    out = {"instance": instance, "size": size, "seed": seed, "tag": tag,
           "winner": winner, "best": best, "verified": verified,
           "wall_s": round(wall, 1), "per_island": results, "warm_json": warm_json,
           "migrate": bool(migrate_path)}
    json.dump(out, open(f"{outdir}/{instance}_n{size}_s{seed}{sfx}.json", "w"), indent=1)
    print(f"\n{instance}: winner={winner}  best={best}  verified={verified}  ({wall:.0f}s)", flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--total-threads", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--warm-json", default=None)
    ap.add_argument("--islands", default="seg,kick")
    ap.add_argument("--migrate", action="store_true",
                    help="cooperative: islands share a global-best incumbent file")
    ap.add_argument("--tag", default="", help="arm label; namespaces all output files")
    ap.add_argument("--stall-patience", type=float, default=None,
                    help="run-until-stall: --budget becomes a hard cap")
    ap.add_argument("--target-lb", type=float, default=None,
                    help="valid LB for the proven-optimal early exit")
    ap.add_argument("--island-threads", default="",
                    help="override, e.g. merge:3,seg:2,kick:3")
    ap.add_argument("--kick-extra", default="",
                    help="extra fixopt flags appended to the KICK island only "
                         "(space-joined, e.g. '--kick-k 3 --kick-from-best')")
    a = ap.parse_args()
    it_over = {}
    if a.island_threads:
        for kv in a.island_threads.split(","):
            k, v = kv.split(":"); it_over[k] = int(v)
    run(a.instance, a.size, a.budget, a.total_threads, a.seed, a.warm_json,
        a.islands.split(","), migrate=a.migrate, tag=a.tag,
        stall_patience=a.stall_patience, target_lb=a.target_lb, island_threads=it_over,
        kick_extra=a.kick_extra.split() if a.kick_extra else None)
