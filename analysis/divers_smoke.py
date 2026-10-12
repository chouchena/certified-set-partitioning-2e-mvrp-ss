"""DIVERSIFICATION SMOKE: does enlarging the SUPPORT revive an exhausted neighbourhood?

THE QUESTION. At a deep plateau we measured q = 0 (0 hits / 200 kicks, 95% CI [0, 1.9]), and
the in-situ data agrees (0/48). We also measured that neither of the two obvious levers helps
there: breadth cannot (H = 1-(1-q)^k is 0 for any k when q = 0) and depth cannot (the
conversion curve is measured on live states, not dead ones). The ONE lever never tested is the
SUPPORT -- WHICH customers are freed, not how many samples or how long each gets. kick_count is
fixed at 9 of 30 everywhere.

This tests it with ZERO solver change, on exactly the states where the operator is dead:
replay the 4 harvested deep-plateau incumbents at kick_count = 9 (control), 12, 18, 24.

  q rises with support  -> the neighbourhood is under-sized, not dead. Plateau-gated support
                           escalation is justified, and it is a one-constant change.
  q stays 0             -> the neighbourhood is structurally exhausted at this incumbent, and
                           no sampling change of any kind can help. Diversification must then
                           move the POINT (bounded accept-worse, or soft restart), which is a
                           bigger and riskier change touching known-buggy accept-worse code.

THE BAR IS NOT ZERO. After t>=1200s local search still delivers 48 improvements / 258.9 units
= 13.6 per run across 19 cap-TL runs, while kicks deliver exactly 0. So the search is not
plateaued -- the KICK neighbourhood is exhausted while local search keeps working. Any
diversification that costs wall time must beat what local search would have done with it.
"""
import argparse, glob, json, math, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
DEEP = os.path.join(ROOT, "runs", "kickstates", "_deep")
VALID = os.path.join(ROOT, "validation")


def say(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def wilson(x, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supports", default="9,12,18,24")
    ap.add_argument("--draws", type=int, default=20)
    a = ap.parse_args()
    sup = [int(s) for s in a.supports.split(",") if s.strip()]
    states = sorted(glob.glob(os.path.join(DEEP, "kickstate_deep_*.json")))
    if not states:
        say("no deep states harvested -- run kick_deep_probe first"); sys.exit(1)
    say(f"{len(states)} deep-plateau states x {a.draws} draws x supports {sup}")

    procs = []
    for s in sup:
        for cell in ("R203", "R211"):
            pat = os.path.join(DEEP, f"kickstate_deep_{cell}_*.json")
            if not glob.glob(pat):
                continue
            out = os.path.join(VALID, f"kickbench_sup{s}_{cell}.jsonl")
            if os.path.exists(out):
                os.remove(out)
            procs.append(subprocess.Popen(
                [PY, os.path.join(ROOT, "analysis", "kick_bench.py"),
                 "--states", pat, "--cell", cell, "--draws", str(a.draws),
                 "--depths", "20", "--cores", "1", "--kick-count", str(s),
                 "--shard", "0/1", "--out", out],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT))
    say(f"launched {len(procs)} 1-core workers")
    for p in procs:
        p.wait()

    print("\n=== q at a DEEP PLATEAU vs SUPPORT (customers freed per kick) ===")
    print(f"{'support':>8}{'kicks':>7}{'hits':>6}{'q':>8}{'95% CI':>16}{'mean gain|hit':>15}")
    base = None
    for s in sup:
        rows = []
        for f in glob.glob(os.path.join(VALID, f"kickbench_sup{s}_*.jsonl")):
            for l in open(f, encoding="utf-8"):
                if l.strip():
                    rows.append(json.loads(l))
        if not rows:
            continue
        x = sum(1 for r in rows if r["improved"])
        p, lo, hi = wilson(x, len(rows))
        g = [r["gain"] for r in rows if r["improved"]]
        if base is None:
            base = p
        print(f"{s:8}{len(rows):7}{x:6}{100*p:7.2f}%"
              f"{f'[{100*lo:.1f}, {100*hi:.1f}]':>16}{(sum(g)/len(g) if g else 0):15.1f}")
    print("\n  q rises  -> neighbourhood under-sized; plateau-gated support escalation justified")
    print("  q stays 0 -> structurally exhausted; only moving the POINT can help")
    print("  BAR TO BEAT: local search still yields 13.6 units/run after t>=1200s.")


if __name__ == "__main__":
    main()
