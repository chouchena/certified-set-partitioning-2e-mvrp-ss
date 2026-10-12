"""Stage 3c: q at 4 CORES on the SAME states -- the decisive test for parallel multikick.

Stage 3 measured q at 1 core: early 4.5% [2.8,7.0], mid 0.6% [0.1,3.1]. Production's burst hit
rate (39% early) implies q~11.6% at 4 cores. Taken at face value that says a 4-core kick is
~2.6x likelier to land than a 1-core one, and that parallelising 4 kicks onto 4 single cores
is ~1.7x better per second of burst time.

But those two numbers come from DIFFERENT measurement contexts -- bench/1-core/harvested-states
versus production/4-core/in-situ -- so the ratio is not trustworthy. This re-runs the identical
corpus, identical seeded draws, identical 20s TL, changing ONLY --cores 1 -> 4. Then

    q(4 cores) vs q(1 core)  on matched draws

is the whole parallel question, because parallelism buys k kicks per burst-second only by
paying for each one with a quarter of the threads:
    4 x 1-core concurrent : H = 1-(1-q1)^4  in  20s of wall
    4 x 4-core sequential : H = 1-(1-q4)^4  in  80s of wall
    parallel wins iff  (1-(1-q1)^4)/20  >  (1-(1-q4)^4)/80

Runs 2 workers (4 threads each) to fill the 8-core box, after the pipeline and deep probe.
"""
import argparse, glob, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
STATES = os.path.join(ROOT, "runs", "kickstates")
VALID = os.path.join(ROOT, "validation")


def say(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def busy():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { "
         "$_.CommandLine -like '*kick_pipeline*' -or $_.CommandLine -like '*kick_bench*' -or "
         "$_.CommandLine -like '*kick_harvest*' -or $_.CommandLine -like '*kick_deep_probe*' -or "
         "$_.CommandLine -like '*fixopt.py*' }).Count"],
        capture_output=True, text=True).stdout.strip()
    try:
        return int(out or 0) > 0
    except ValueError:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=20, help="must match stage 3 for paired draws")
    ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()

    if a.wait:
        say("waiting for pipeline + deep probe to free the cores ...")
        while busy():
            time.sleep(180)
        say("cores free")

    procs = []
    for cell in ("R203", "R211"):
        out = os.path.join(VALID, f"kickbench_c4_{cell}_0.jsonl")
        cmd = [PY, os.path.join(ROOT, "analysis", "kick_bench.py"),
               "--states", os.path.join(STATES, f"{cell}_s*", "kickstate_*.json"),
               "--cell", cell, "--draws", str(a.draws), "--depths", "20",
               "--cores", "4", "--shard", "0/1", "--out", out]
        say(f"benching {cell} at 4 cores, {a.draws} draws/state")
        procs.append(subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.STDOUT))
    for p in procs:
        p.wait()

    # paired verdict: same states, same draw indices, 1 core vs 4 cores
    import json, math
    def load(pat):
        d = {}
        for f in glob.glob(os.path.join(VALID, pat)):
            for l in open(f, encoding="utf-8"):
                if not l.strip():
                    continue
                r = json.loads(l)
                if abs(r["depth"] - 20.0) < 1e-9:
                    d[(r["state"], r["draw"])] = r
        return d

    def wilson(x, n, z=1.96):
        if n == 0:
            return (0, 0, 1)
        p = x / n; dd = 1 + z * z / n
        c = (p + z * z / (2 * n)) / dd
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / dd
        return p, max(0.0, c - h), min(1.0, c + h)

    one, four = load("kickbench_q_*.jsonl"), load("kickbench_c4_*.jsonl")
    keys = sorted(set(one) & set(four))
    say(f"matched draws: {len(keys)}")
    if not keys:
        say("no matched draws -- cannot compare"); return
    x1 = sum(1 for k in keys if one[k]["improved"])
    x4 = sum(1 for k in keys if four[k]["improved"])
    p1, l1, h1 = wilson(x1, len(keys)); p4, l4, h4 = wilson(x4, len(keys))
    print(f"\n=== q on MATCHED draws (n={len(keys)}) ===")
    print(f"  1 core, 20s: q = {100*p1:5.2f}%  95% CI [{100*l1:4.1f}, {100*h1:4.1f}]")
    print(f"  4 core, 20s: q = {100*p4:5.2f}%  95% CI [{100*l4:4.1f}, {100*h4:4.1f}]")
    # McNemar on discordant pairs
    b = sum(1 for k in keys if four[k]["improved"] and not one[k]["improved"])
    c = sum(1 for k in keys if one[k]["improved"] and not four[k]["improved"])
    if b + c:
        chi = (abs(b - c) - 1) ** 2 / (b + c)
        print(f"  McNemar: 4-core-only {b}, 1-core-only {c}, chi2={chi:.2f} "
              f"(>3.84 = p<0.05)")
    H1 = 1 - (1 - p1) ** 4
    H4 = 1 - (1 - p4) ** 4
    print(f"\n  4 x 1-core CONCURRENT: H={100*H1:5.1f}% in 20s -> {H1/20:.5f} hits/s")
    print(f"  4 x 4-core SEQUENTIAL: H={100*H4:5.1f}% in 80s -> {H4/80:.5f} hits/s")
    if H4 > 0:
        r = (H1 / 20) / (H4 / 80)
        print(f"  -> parallel is {r:.2f}x the hit-rate per burst-second  "
              f"({'PARALLEL WINS' if r > 1 else 'SEQUENTIAL WINS -- do not build the parallel version'})")
    say("CORES PROBE COMPLETE")


if __name__ == "__main__":
    main()
