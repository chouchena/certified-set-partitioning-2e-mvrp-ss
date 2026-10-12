"""How much wall time does cap-TL actually spend INSIDE kick bursts?

This is the headroom question for the PARALLEL-1-core kick build (#29): parallelising 4 kicks
onto 4 cores can only recover time that is currently being spent in bursts. If bursts are a
large share of wall time, parallelisation has room to win; if they are a sliver, the build
cannot help no matter how well it works -- Amdahl.

A 'fixopt_kick' record is emitted at the END of a burst; burst duration is taken as the gap
from the preceding record. Also reports how many kick bursts actually IMPROVED the incumbent."""
import glob, json, os, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def analyse(p):
    rows = []
    for l in open(p, encoding="utf-8"):
        if l.strip():
            rows.append(json.loads(l))
    total = max((r.get("wall_s") or 0) for r in rows)
    bursts, improved, prev_best = [], 0, None
    for i, r in enumerate(rows):
        if "kick" in str(r.get("trigger", "")).lower() and i > 0:
            dur = (r.get("wall_s") or 0) - (rows[i - 1].get("wall_s") or 0)
            if dur >= 0:
                bursts.append(dur)
            b = r.get("best_incumbent")
            if prev_best is not None and b is not None and b < prev_best - 1e-9:
                improved += 1
        if r.get("best_incumbent") is not None:
            prev_best = r.get("best_incumbent")
    return total, bursts, improved


print("=== cap-TL burst time budget (headroom for the parallel build) ===\n")
print(f"{'run':<34} {'wall':>7} {'#burst':>7} {'burst_s':>8} {'%wall':>7} {'med_s':>7} {'improved':>9}")
agg_share, agg_dur = [], []
for p in sorted(glob.glob(os.path.join(ROOT, "runs", "fixopt_R2*_n30_s*_cal_captl_*.jsonl"))):
    total, bursts, imp = analyse(p)
    if not bursts or total <= 0:
        continue
    s = sum(bursts)
    agg_share.append(s / total); agg_dur.extend(bursts)
    name = os.path.basename(p).replace("fixopt_", "").replace("_n30", "").replace(".jsonl", "")[:33]
    print(f"{name:<34} {total:7.0f} {len(bursts):7d} {s:8.0f} {100*s/total:6.1f}% {st.median(bursts):7.1f} {imp:9d}")

if agg_share:
    ms = st.mean(agg_share)
    print(f"\nmean burst share of wall time : {100*ms:.1f}%")
    print(f"median single-burst duration  : {st.median(agg_dur):.1f}s  (n={len(agg_dur)} bursts)")
    print("\n--- Amdahl ceiling for the parallel-1-core build ---")
    for sp in (2.0, 3.0, 4.0):
        rec = ms * (1 - 1 / sp)
        print(f"  if parallel kicks are {sp:.0f}x faster per burst: recovers {100*rec:4.1f}% of wall time "
              f"-> equivalent to a {1/(1-rec):.2f}x longer run")
    print("\n  (upper bound: even an INFINITELY fast burst only returns the full "
          f"{100*ms:.1f}% -> {1/(1-ms):.2f}x effective budget)")
