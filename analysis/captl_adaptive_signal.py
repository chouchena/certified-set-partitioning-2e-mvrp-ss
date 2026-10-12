"""Is there signal to drive an ADAPTIVE burst depth (user proposal: adapt on past burst
improvements + remaining RT)? Decided from the 125 bursts already on disk, before building
anything -- an adaptive rule keyed on a signal that isn't there just adds variance.

Result (see commit): TIME signal strong (hit rate 39% -> 21% -> 0%, p=0.008 early-vs-late);
HISTORY signal weak (35% after a hit vs 20% after a miss, p=0.09, and miss-streaks max out
at 4 so there is little to key on). Also explains WHY the dropped escalating design failed:
it escalated depth ON FAILURE, which correlates with late-run -- pouring time into bursts
exactly where their hit rate goes to zero. That is the burst-time-sink mechanism."""
import glob, json, math, statistics as st


def bursts_of(p):
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    prev, ev = None, []
    for i, r in enumerate(rows):
        b = r.get("best_incumbent")
        if "kick" in str(r.get("trigger", "")).lower() and i > 0:
            dur = (r.get("wall_s") or 0) - (rows[i - 1].get("wall_s") or 0)
            imp = prev is not None and b is not None and b < prev - 1e-9
            ev.append((r.get("wall_s") or 0, imp, (prev - b) if imp else 0.0, dur))
        if b is not None:
            prev = b
    return ev


def two_prop(x1, n1, x2, n2):
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def main():
    seqs = [e for e in (bursts_of(p) for p in
                        sorted(glob.glob("runs/fixopt_R2*_n30_s*_cal_captl_*.jsonl"))) if e]
    flat = [e for ev in seqs for e in ev]
    print(f"{len(flat)} bursts over {len(seqs)} runs; overall hit rate "
          f"{100*sum(1 for e in flat if e[1])/len(flat):.0f}%\n")

    print("TIME signal (drives an adaptive schedule):")
    buckets = []
    for lo, hi in ((0, 600), (600, 1200), (1200, 1800), (1800, 2400)):
        sel = [e for e in flat if lo <= e[0] < hi]
        if not sel:
            print(f"  t={lo:4d}-{hi:4d}s: no bursts")
            continue
        h = [e for e in sel if e[1]]
        buckets.append((len(h), len(sel)))
        print(f"  t={lo:4d}-{hi:4d}s: {len(sel):3d} bursts  hit {100*len(h)/len(sel):3.0f}%  "
              f"exp gain/burst {sum(e[2] for e in sel)/len(sel):5.1f}")
    if len(buckets) >= 2:
        z, p = two_prop(*buckets[0], *buckets[-1])
        print(f"  early vs late: z={z:.2f} p={p:.4f}")

    print("\nHISTORY signal (the weaker half of the proposal):")
    a = b_ = c = d = 0
    for ev in seqs:
        for i in range(1, len(ev)):
            if ev[i - 1][1]:
                a, b_ = (a + 1, b_) if ev[i][1] else (a, b_ + 1)
            else:
                c, d = (c + 1, d) if ev[i][1] else (c, d + 1)
    z, p = two_prop(a, a + b_, c, c + d)
    print(f"  after HIT {100*a/(a+b_):.0f}% vs after MISS {100*c/(c+d):.0f}%  z={z:.2f} p={p:.3f}")
    streak, s = [], 0
    for ev in seqs:
        s = 0
        for e in ev:
            if e[1]:
                streak.append(s); s = 0
            else:
                s += 1
    print(f"  miss-streak before a hit: median {st.median(streak):.0f} max {max(streak)} "
          f"-> little room for a streak-keyed rule")


if __name__ == "__main__":
    main()
