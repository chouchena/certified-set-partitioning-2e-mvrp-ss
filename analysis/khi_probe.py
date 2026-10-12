"""Choose k_hi for a size by a PROVABILITY criterion -- outcome-blind, no bound values consulted.

WHY A PROBE AND NOT A FORMULA. Provability depends on WHICH customers are retained, not just how
many: the descend keeps the |H| HARDEST by the easiness ranking, so the retained population
differs by size. |H|=33 proved in 0.2 s at |C|=100 while |H|=15 was borderline at |C|=30 --
a formula in |H| or in the drop fraction cannot express that.

THE CRITERION. Walk |H| DOWNWARD from an optimistic start and take the largest |H| whose cold
solve PROVES within a small tick budget. That is the same rule used to set k_hi=67 at |C|=100.
It reads the solver's STATUS (proved / not), never a bound value, so it cannot tune on the
outcome -- and the resulting k_hi is a deterministic function of the instance plus the probe
budget, so a replicator reproduces it.

WHY THE LARGEST PROVABLE |H|. Measured across the |C|=100 C family: bound quality is ordered by
proof depth (13 proofs -> 2412.9, 7 -> 2096.3, 2 -> 1949.7, 1 -> 1935.8, 0 -> arithmetic bound
carries). A cell that proves at its starting |H| enters the warm-started descent and walks
outward, where PROVEN bounds are monotone in |H|. A cell that never proves stays in the
escalation phase and is carried by the arithmetic bound regardless.

Prints a single k_hi line the caller can parse; writes the full ladder to runs/khi_probe_n<S>.log.
"""
import argparse, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SEED = 20260910


def say(size, m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(os.path.join(ROOT, "runs", f"khi_probe_n{size}.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--cell", default=None, help="reference cell; default C201")
    ap.add_argument("--det-tl", type=float, default=120000.0, help="probe budget in ticks")
    ap.add_argument("--fracs", default="0.55,0.45,0.35,0.28,0.22,0.16,0.11")
    A = ap.parse_args()
    cell = A.cell or "C201"
    prox = 0.1 if A.size == 100 else 0.0
    scratch = os.path.join(ROOT, "runs", "khi_probe")
    os.makedirs(scratch, exist_ok=True)
    say(A.size, f"=== k_hi PROBE n{A.size} on {cell}: largest |H| that PROVES within "
                f"{A.det_tl:.0f} ticks (prox={prox}, seed={SEED}) ===")
    env = dict(os.environ); env["PYTHONHASHSEED"] = "0"
    chosen = None
    for frac in [float(x) for x in A.fracs.split(",")]:
        H = max(4, int(round(A.size * frac)))
        k = A.size - H
        if k < 1:
            continue
        out = os.path.join(scratch, f"probe_{cell}_n{A.size}_H{H}.json")
        # tl MUST NOT exceed the cell budget: easy_reduction_descend asserts that and exits
        # FATAL. Hardcoding tl=1200 against a budget of det_tl/400+300 made every ladder step
        # die instantly for any det_tl < 360000 -- including this probe's own default of
        # 120000. With output sent to DEVNULL and a missing artifact read as "not proven",
        # the probe then reported a confident k_hi derived from ZERO successful solves.
        # Caught 2026-09-11. A probe needs one cold solve per rung, so budget >= tl suffices.
        budget = A.det_tl / 400.0 + 300
        tl = int(min(1200.0, budget))   # --tl is an INT argument
        t0 = time.time()
        try:
            pr = subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                                 "--cells", cell, "--size", str(A.size), "--k-hi", str(k),
                                 "--k-cap", str(k + 1), "--tl", str(tl), "--det-tl", str(A.det_tl),
                                 "--workers", "4", "--proximity", str(prox), "--seed", str(SEED),
                                 "--cell-budget", str(budget),
                                 "--out", out, "--allow-overwrite"],
                                cwd=ROOT, env=env, timeout=2400,
                                capture_output=True, text=True)
        except Exception as e:
            say(A.size, f"  |H|={H:>3} (k={k}) error: {e}")
            continue
        import json
        r = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
        r = [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]
        # DISTINGUISH "ran and did not prove" FROM "never ran". Treating the second as the
        # first is what produced a fabricated k_hi; refuse to guess instead.
        if not r:
            tail = ((pr.stdout or "") + (pr.stderr or "")).strip().splitlines()
            msg = tail[-1] if tail else "(no output)"
            say(A.size, f"  |H|={H:>3} (k={k:>3})  !! NO ARTIFACT after {time.time()-t0:.0f}s "
                        f"-- the solve did not run. Last line: {msg}")
            say(A.size, "  ABORTING PROBE: a failed solve is not evidence of unprovability.")
            raise SystemExit(2)
        pv = bool(r[0].get("proven"))
        say(A.size, f"  |H|={H:>3} (k={k:>3})  proven={pv}  {time.time()-t0:.0f}s")
        if pv:
            chosen = k
            break
    if chosen is None:
        chosen = A.size - max(4, int(round(A.size * 0.11)))
        say(A.size, f"  no |H| proved; falling back to the smallest tried, k_hi={chosen}")
    say(A.size, f"KHI_CHOSEN n{A.size} = {chosen}  (|H|={A.size - chosen})")


if __name__ == "__main__":
    main()
