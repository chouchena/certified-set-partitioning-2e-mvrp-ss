"""
lb_portfolio.py -- the LB unifier / formulation-race presolve stage.

No single block-A formulation dominates across instance families (2026-09-03
cut_ab + disagg_smoke: disagg -26% on tight C203, +84% on loose C204; the
trip cut -14% on C203, +47% on RC208).  And there is no cheap per-instance
predictor.  So: race the formulations in parallel, kill the losers on the
first proof, and if none prove take the max dual bound (valid -- all share
the same optimum z_A(H)*).

  python -m crossfeed.lb_portfolio --cell C204 --size 20 [--k 6] \
      --budget 900 --total-workers 6

Configs raced (override with --configs):
  bigM            -- the paper's formulation, per-arc M
  bigM+cut        -- + trip-count VI  (sum vi >= ceil(dem/Q))
  disagg          -- Const8 split into transfer / no-transfer regimes

Output: results/lb_portfolio/<cell>_n<size>.json + ledger (experiment=lb_portfolio).
Emits the WINNER as {LB, prov_LB%, winner, proven} for the primal portfolio seed.
"""
from __future__ import annotations
import sys, os, json, time, argparse, subprocess
sys.path.insert(0, ".")
from build_instance import build
from crossfeed.easy_reduction import scarcity_and_weights, easiness
from analysis.ledger import emit

PY = sys.executable
FRONTIER = {"C203": 5, "C204": 6, "R203": 6, "R204": 7, "R207": 6, "R208": 9,
            "R211": 8, "RC202": 5, "RC203": 6, "RC204": 8, "RC208": 8}

CONFIGS = {
    "bigM":     ("bigM", 0),
    "bigM+cut": ("bigM", 1),
    "disagg":   ("disagg", 1),
}


def run(cell, size, k, budget, total_workers, configs, poll=5.0):
    outdir = "results/lb_portfolio"
    os.makedirs(outdir, exist_ok=True)
    per = max(1, total_workers // len(configs))
    procs = {}
    files = {}
    print(f"=== LB portfolio  {cell} n{size}  k*={k}  budget={budget}s  "
          f"{len(configs)} configs x {per}t ===", flush=True)
    t0 = time.time()
    for name in configs:
        timing, tc = CONFIGS[name]
        f = f"{outdir}/{cell}_n{size}__{name}.json"
        files[name] = f
        if os.path.exists(f):
            os.remove(f)
        procs[name] = subprocess.Popen(
            [PY, "crossfeed/_lb_worker.py", "--cell", cell, "--size", str(size),
             "--k", str(k), "--timing", timing, "--trip-cut", str(tc),
             "--tl", str(budget), "--workers", str(per), "--out", f],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    winner = None
    results = {}
    while True:
        alive = {n: pr for n, pr in procs.items() if pr.poll() is None}
        for name, f in files.items():
            if name in results or not os.path.exists(f):
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            if d.get("status") != "done":
                continue
            results[name] = d
            tag = "PROVEN" if d["proven"] else f"bound {d['block_relax']}"
            print(f"  [{time.time()-t0:.0f}s] {name}: {tag}  ({d['wall_s']}s)", flush=True)
            if d["proven"] and winner is None:
                winner = name
                for n2, pr in alive.items():
                    if n2 != name:
                        pr.terminate()
                        print(f"    -> {name} proved first; killed {n2}", flush=True)
        if winner is not None:
            break
        if not alive:
            break
        if time.time() - t0 > budget + 120:
            for pr in alive.values():
                pr.terminate()
            break
        time.sleep(poll)

    time.sleep(2)
    for name, f in files.items():
        if name not in results and os.path.exists(f):
            try:
                d = json.load(open(f))
                if d.get("status") == "done":
                    results[name] = d
            except Exception:
                pass

    # aggregate: winner = first proof, else max block_relax (valid best-of)
    proven = [n for n, d in results.items() if d["proven"]]
    if winner is None and proven:
        winner = min(proven, key=lambda n: results[n]["wall_s"])
    if winner is None and results:
        winner = max(results, key=lambda n: results[n]["block_relax"] or 0)

    LB = results[winner]["block_relax"] if winner else None
    prov = bool(winner and results[winner]["proven"])
    wall = time.time() - t0
    out = {"cell": cell, "size": size, "k": k, "winner": winner, "LB": LB,
           "proven": prov, "wall_s": round(wall, 1),
           "per_config": {n: {kk: d[kk] for kk in ("timing", "trip_cut", "zA",
                              "proven", "block_relax", "wall_s")}
                          for n, d in results.items()}}
    json.dump(out, open(f"{outdir}/{cell}_n{size}.json", "w"), indent=1)

    for n, d in results.items():
        emit("lb_portfolio", cell, size,
             config=dict(formulation=n, timing=d["timing"], trip_cut=d["trip_cut"], k=k),
             metrics=dict(zA=d["zA"], proven=d["proven"], block_relax=d["block_relax"],
                          won=(n == winner)),
             wall_s=d["wall_s"], verified=None)

    print(f"\n{cell}: winner={winner}  LB={LB}  proven={prov}  ({wall:.0f}s)", flush=True)
    if LB:
        # prov_LB% needs a UB; report bound only here (primal fills the gap)
        print(f"  per-config: " + "  ".join(
            f"{n}={d['block_relax']}{'*' if d['proven'] else ''}({d['wall_s']:.0f}s)"
            for n, d in results.items()), flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--budget", type=int, default=900)
    ap.add_argument("--total-workers", type=int, default=6)
    ap.add_argument("--configs", default="bigM,bigM+cut,disagg")
    a = ap.parse_args()
    k = a.k or FRONTIER[a.cell]
    run(a.cell, a.size, k, a.budget, a.total_workers, a.configs.split(","))
