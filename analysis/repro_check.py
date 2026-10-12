"""Prove replicability empirically: run the SAME cell twice at the SAME seed, demand equality.

A manifest records what we INTENDED. This checks what actually happens, which is the only
evidence that the intent worked.

WHY IT TARGETS A TRUNCATED BOUND. A PROVEN record reports z_A(H)*, a mathematical optimum --
it is seed-independent in value, so reproducing it proves nothing about the seed pinning. The
bound we additionally publish is the TRUNCATED dual bound at the time limit (valid by proof
Step 0), and that is whatever the branch-and-bound search happened to reach. It moves with the
CPLEX seed, the thread count and the parallel mode. So the check deliberately uses a time limit
too short to prove, and compares the truncated values.

WHAT A MISMATCH WOULD MEAN. The wall-clock time limit is the one remaining source of variation:
a loaded machine stops the search at a different point. That is exactly why det_ticks is
recorded per solve -- a replicator sets dettimelimit to the logged tick count and reproduces
the value on any hardware. If this check fails on an idle machine, seed pinning is not working
and no truncated bound should be published until it does.
"""
import argparse, json, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(cell, size, k_hi, tl, workers, seed, out, det_tl):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                    "--cells", cell, "--size", str(size), "--k-hi", str(k_hi),
                    "--k-cap", str(k_hi + 1), "--tl", str(tl), "--workers", str(workers),
                    "--cell-budget", str(tl * 3), "--seed", str(seed),
                    *(["--det-tl", str(det_tl)] if det_tl else []),
                    "--out", out, "--allow-overwrite"],
                   cwd=ROOT, env=env, timeout=tl * 8 + 600,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    r = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    return [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="R203")
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--k-hi", type=int, default=15)
    ap.add_argument("--tl", type=int, default=300, help="WALL BACKSTOP only; --det-tl is "
                                                        "the binding budget")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--det-tl", type=float, default=40000.0,
                    help="deterministic ticks -- THE replicable budget. 0 to test wall-only.")
    ap.add_argument("--reps", type=int, default=2)
    A = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="repro_")
    runs = []
    for i in range(A.reps):
        t0 = time.time()
        runs.append(run(A.cell, A.size, A.k_hi, A.tl, A.workers, A.seed,
                        os.path.join(tmp, f"rep{i}.json"), A.det_tl))
        print(f"  rep {i+1}/{A.reps} done in {time.time()-t0:.0f}s", flush=True)

    print(f"\n=== REPLICATION CHECK {A.cell}/n{A.size} k_hi={A.k_hi} tl={A.tl}s "
          f"threads={A.workers} seed={A.seed} x{A.reps} ===")
    n = min(len(r) for r in runs)
    if n == 0:
        sys.exit("no records produced -- cannot check")
    ok = all(len(r) == len(runs[0]) for r in runs)
    print(f"{'k':>4}{'proven':>8}" + "".join(f"{'rep'+str(i+1):>13}" for i in range(A.reps))
          + f"{'match':>8}")
    for j in range(n):
        vals = [r[j]["block_relax"] for r in runs]
        m = len(set(vals)) == 1
        ok &= m
        print(f"{runs[0][j]['k']:>4}{str(runs[0][j]['proven']):>8}"
              + "".join(f"{v:>13}" for v in vals) + f"{'YES' if m else 'NO':>8}")
    trunc = [j for j in range(n) if not runs[0][j]["proven"]]
    print(f"\ntruncated (seed-sensitive) records checked: {len(trunc)} of {n}")
    if not trunc:
        print("WARNING: every record proved, so this run does NOT exercise seed sensitivity. "
              "Lower --tl and re-run.")
    print("det_ticks rep1:", [r.get("det_ticks") for r in runs[0]])
    print("limit_hit rep1:", [r.get("limit_hit") for r in runs[0]])
    print("wall (s):", [[round(r[j]["wall"], 1) for j in range(n)] for r in runs])
    print("\nVERDICT:", "EXACT MATCH -- seed pinning works" if ok else
          "MISMATCH -- do NOT publish truncated bounds until this passes")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
