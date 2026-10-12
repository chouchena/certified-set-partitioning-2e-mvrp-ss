"""Stage 5: turn bench measurements into a burst schedule.

Reads kick_bench JSONL and answers, with intervals rather than adjectives:
  1. q(t)      per-kick success probability by run position   -> does ANY escalation work late?
  2. convert(d) P(improve at depth d | same draw failed at base) -> does escalate-on-miss work?
  3. best-of-k surface, computed (not measured) from the per-kick outcome distribution,
     because kicks are independent draws with the min taken: H(k) = 1-(1-q)^k.
  4. value(k,d) = expected gain per second of wall clock, through the measured cycle model.
     This is the objective: a burst schedule is chosen on RATE, not on kick quality.

Cycle model (measured from 12 cap-TL runs): search-to-plateau P = 165s, and on 4 cores a
burst of k kicks at depth d costs ceil(k/4)*d seconds of wall time (kicks are independent,
so they parallelise; depth does not).
"""
import argparse, collections, glob, json, math, os, statistics as st

P_PLATEAU = 165.0     # measured search-to-plateau, seconds
CORES = 4


def wilson(x, n, z=1.96):
    """Binomial CI that behaves at x=0 -- which is the case that decides this whole question."""
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def bucket(w):
    if w is None:
        return "unknown"
    return "early(<600)" if w < 600 else ("mid(600-1200)" if w < 1200 else "late(>1200)")


def load(paths):
    rows = []
    for p in paths:
        for l in open(p, encoding="utf-8"):
            if l.strip():
                rows.append(json.loads(l))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="validation/kickbench_*.jsonl")
    ap.add_argument("--base-depth", type=float, default=20.0)
    a = ap.parse_args()
    rows = load(sorted(glob.glob(a.bench)))
    if not rows:
        print("no bench rows found"); return
    print(f"=== kick calibration ({len(rows)} kick solves) ===\n")

    # ---- 1. q(t) at base depth -------------------------------------------------
    print("1. PER-KICK SUCCESS q(t) at base depth "
          f"{a.base_depth:.0f}s  (burst hit rate H = 1-(1-q)^k)")
    base = [r for r in rows if abs(r["depth"] - a.base_depth) < 1e-9]
    qhat = {}
    for b in ("early(<600)", "mid(600-1200)", "late(>1200)"):
        sel = [r for r in base if bucket(r.get("wall_s")) == b]
        if not sel:
            continue
        x = sum(1 for r in sel if r["improved"])
        p, lo, hi = wilson(x, len(sel))
        qhat[b] = (p, lo, hi, len(sel))
        gains = [r["gain"] for r in sel if r["improved"]]
        print(f"   {b:16s} q = {100*p:5.1f}%  95% CI [{100*lo:4.1f}, {100*hi:4.1f}]  "
              f"n={len(sel):4d}  mean gain|hit {st.mean(gains) if gains else 0:6.1f}")
    late = qhat.get("late(>1200)")
    if late:
        verdict = ("LATE IS ALIVE -> breadth-scaling can work" if late[1] > 0.02 else
                   "LATE MAY BE DEAD -> if the CI upper bound is also small, no k helps; "
                   "change the SUPPORT (kick_count) or stop kicking")
        print(f"   -> {verdict}")

    # ---- 2. conversion curve ---------------------------------------------------
    print("\n2. CONVERSION: P(improve at depth d | SAME draw failed at base depth)")
    failed = {(r["state"], r["draw"]) for r in base if not r["improved"]}
    depths = sorted({r["depth"] for r in rows if r["depth"] > a.base_depth})
    if not depths:
        print("   (no deeper probes in this bench -- run stage 4 to fill this in)")
    for d in depths:
        sel = [r for r in rows if abs(r["depth"] - d) < 1e-9 and (r["state"], r["draw"]) in failed]
        if not sel:
            continue
        x = sum(1 for r in sel if r["improved"])
        p, lo, hi = wilson(x, len(sel))
        print(f"   depth {d:5.0f}s: converts {100*p:5.1f}%  95% CI [{100*lo:4.1f}, {100*hi:4.1f}]  n={len(sel)}")
    if depths:
        print("   flat curve -> misses are EXHAUSTION (escalate-on-miss is dead; cap-TL's fixed "
              "depth is right).  rising -> escalation was right in DIRECTION, wrong in magnitude.")

    # ---- 3/4. best-of-k surface and the rate objective --------------------------
    print("\n3+4. BURST SCHEDULE: value(k,d) = expected gain per second of wall clock")
    print(f"     cycle = P({P_PLATEAU:.0f}s search-to-plateau) + burst; on {CORES} cores a burst "
          f"of k kicks at depth d costs ceil(k/{CORES})*d seconds")
    for b, (q, lo, hi, n) in qhat.items():
        gains = [r["gain"] for r in base
                 if bucket(r.get("wall_s")) == b and r["improved"]]
        g = st.mean(gains) if gains else 0.0
        if q <= 0 or g <= 0:
            print(f"\n   {b}: q=0 -> no schedule pays; nothing to optimise here")
            continue
        print(f"\n   {b}: q={100*q:.1f}%, mean gain|hit={g:.1f}")
        best = None
        KS = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64)
        for k in KS:
            for d in sorted({a.base_depth} | set(depths)):
                H = 1 - (1 - q) ** k
                burst = math.ceil(k / CORES) * d
                val = H * g / (P_PLATEAU + burst)
                if best is None or val > best[0]:
                    best = (val, k, d, H, burst)
        print(f"      {'k':>3} {'depth':>6} {'H(burst hit)':>13} {'burst_s':>8} {'gain/s':>9}")
        for k in KS:
            d = a.base_depth
            H = 1 - (1 - q) ** k
            burst = math.ceil(k / CORES) * d
            val = H * g / (P_PLATEAU + burst)
            mark = "  <== optimum" if best and (k, d) == (best[1], best[2]) else ""
            print(f"      {k:3d} {d:6.0f} {100*H:12.1f}% {burst:8.0f} {val:9.4f}{mark}")
        if best[1] == KS[-1]:
            print(f"      !! optimum sits at the k ceiling ({KS[-1]}) -- the true optimum is "
                  f"higher; widen KS, and note a burst this wide is no longer a kick but a restart")
        print(f"      -> best k={best[1]} depth={best[2]:.0f}s "
              f"(today: k=4 depth={a.base_depth:.0f}s, burst {math.ceil(4/CORES)*a.base_depth:.0f}s "
              f"sequential-equivalent {4*a.base_depth:.0f}s)")

    print("\nCAVEAT: value(k,d) is only compared against OTHER burst schedules. Late in a run the "
          "real\n        comparator is NOT kicking at all and giving the time back to local search. "
          "If every\n        late value(k,d) is tiny, the answer is to stop kicking -- but deciding "
          "that needs\n        local search's own gain-rate, which this bench does not measure.")
    print("\nNOTE: this selects a CANDIDATE. Subproblem gain != run gain (a better kick changes "
          "the downstream trajectory), so confirm the chosen schedule with ONE paired full-run "
          "A/B against cap-TL -- not a sweep.")


if __name__ == "__main__":
    main()
