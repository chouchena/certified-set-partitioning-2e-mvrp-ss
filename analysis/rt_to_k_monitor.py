"""ALWAYS-ON RT-to-beat-K. The primary runtime metric, reported for every run.

WHY THIS IS THE RIGHT METRIC. Our wall-clock is not comparable to K's: K ran Gurobi 9.12 on
4x Xeon Gold 5218 @2.30GHz; we run CPLEX on Lunar Lake P-cores at roughly twice the clock, and
core-seconds do not fix it (both sides are 4 cores, so the ratio is unchanged). What IS
meaningful is the time at which OUR incumbent first reaches or beats K's best-known value for
that cell -- an event defined by K's OBJECTIVE, not by K's clock. It is still hardware-scaled,
so it must always be reported WITH the hardware and thread count, never as a bare ratio.

Reports, per run: whether K was beaten, when, and at what fraction of K's own IncT. Censoring
is explicit -- runs that never reach K's value are shown as such, never dropped, because
dropping them is precisely the min-over-N defect that made the old n20 RT asset unusable.
"""
import argparse, csv, glob, json, os, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def kdenoms():
    """K_min and K's IncT per (cell,size) from the ledger, which already joins them."""
    out = {}
    p = os.path.join(ROOT, "runs", "ledger.csv")
    if not os.path.exists(p):
        return out
    for r in csv.DictReader(open(p, encoding="utf-8")):
        try:
            if r.get("k_min"):
                out[(r["cell"], int(r["size"]))] = (float(r["k_min"]),
                                                    float(r["k_min_inct"] or 0) or None)
        except (ValueError, TypeError):
            continue
    return out


def rt_to_beat(trace, k_min):
    """first wall_s at which our incumbent <= K's best. None = never (CENSORED, not dropped)."""
    for l in open(trace, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        b = r.get("best_incumbent")
        w = r.get("wall_s")
        if isinstance(b, (int, float)) and isinstance(w, (int, float)) and b <= k_min:
            return w
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="runs/fixopt_*_n30_*.jsonl")
    ap.add_argument("--size", type=int, default=30)
    a = ap.parse_args()
    K = kdenoms()
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, a.glob))):
        base = os.path.basename(p)
        parts = base.replace(".jsonl", "").split("_")
        if len(parts) < 4:
            continue
        cell = parts[1]
        km = K.get((cell, a.size))
        if not km:
            continue
        k_min, k_inct = km
        t = rt_to_beat(p, k_min)
        rows.append((cell, base, t, k_min, k_inct))
    if not rows:
        print("no runs matched"); return
    beat = [r for r in rows if r[2] is not None]
    print(f"=== RT-to-beat-K over {len(rows)} runs (n{a.size}) ===")
    print(f"{'cell':7}{'K_min':>9}{'K IncT':>9}{'our t':>9}{'frac of K IncT':>16}  run")
    for cell, base, t, k_min, k_inct in rows:
        if t is None:
            print(f"{cell:7}{k_min:9.1f}{(k_inct or 0):9.0f}{'NEVER':>9}{'-- CENSORED':>16}  {base[:44]}")
        else:
            fr = (t / k_inct) if k_inct else float("nan")
            print(f"{cell:7}{k_min:9.1f}{(k_inct or 0):9.0f}{t:9.0f}{fr:15.2f}x  {base[:44]}")
    print(f"\n  beat K: {len(beat)}/{len(rows)} runs; CENSORED (never reached): {len(rows)-len(beat)}")
    if beat:
        fr = [r[2] / r[4] for r in beat if r[4]]
        if fr:
            print(f"  fraction of K's IncT among those that DID beat: "
                  f"median {st.median(fr):.2f}x, min {min(fr):.2f}x, max {max(fr):.2f}x")
    print("  REPORT THIS WITH hardware + thread count. It is an objective-defined event, but the")
    print("  clock is still ours: Lunar Lake 4P+4LPE vs K's 4x Xeon Gold 5218 @2.30GHz.")
    print("  Never report the median over beaters alone -- that is min-over-N by another name.")


if __name__ == "__main__":
    main()
