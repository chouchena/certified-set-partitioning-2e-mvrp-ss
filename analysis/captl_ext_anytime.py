"""Anytime/RT read of the cap-TL EXTENSION pairs (same code_hash, so confound-free).
Auto-discovers each (cell,seed) pair from traces written after the extension launch,
so it works on partial results as seeds land."""
import glob, json, os, sys, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCH = float(sys.argv[1]) if len(sys.argv) > 1 else 1788886400.0  # extension launch 2026-09-08 19:54
GRID = [300, 600, 900, 1200, 1800, 2400]


def newest(cell, seed, variant):
    fs = [f for f in glob.glob(os.path.join(
        ROOT, "runs", f"fixopt_{cell}_n30_s{seed}_cal_{variant}_*.jsonl"))
        if os.path.getmtime(f) >= LAUNCH]
    return max(fs, key=os.path.getmtime) if fs else None


def curve(p):
    pts, best = [], None
    for l in open(p, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        inc = r.get("best_incumbent") if r.get("best_incumbent") is not None else r.get("incumbent")
        w = r.get("wall_s")
        if isinstance(inc, (int, float)) and isinstance(w, (int, float)):
            if best is None or inc < best:
                best = inc; pts.append((w, best))
    return pts


def at(pts, t):
    v = None
    for w, b in pts:
        if w <= t: v = b
        else: break
    return v


def t_reach(pts, target):
    for w, b in pts:
        if b <= target + 1e-9:
            return w
    return None


print("=== cap-TL EXTENSION anytime (clean, same code_hash) ===")
rt_win = rt_loss = 0
for cell in ("R203", "R211"):
    for seed in range(3, 8):
        bp_f, cp_f = newest(cell, seed, "baseline"), newest(cell, seed, "captl")
        if not bp_f or not cp_f:
            continue
        bp, cp = curve(bp_f), curve(cp_f)
        if not bp or not cp:
            continue
        bfin, cfin = bp[-1][1], cp[-1][1]
        tc, tb = t_reach(cp, bfin), t_reach(bp, cfin)
        dom = tc is not None and tb is None and tc < 1200
        if dom: rt_win += 1
        elif tc is None: rt_loss += 1
        print(f"\n{cell} s{seed}: base_final={bfin:.1f} captl_final={cfin:.1f} "
              f"(OV delta {cfin-bfin:+.1f})")
        print(f"   captl->base-final: {f'{tc:.0f}s ({tc/2400:.2f} of budget)' if tc else 'NEVER'}"
              f" | base->captl-final: {f'{tb:.0f}s' if tb else 'NEVER'}"
              f"  => {'RT-DOMINATES' if dom else ('RT-loss' if tc is None else 'partial')}")
        row = "   OV@t "
        for t in GRID:
            bv, cv = at(bp, t), at(cp, t)
            if bv is None or cv is None: continue
            row += f"| {t}: {cv:.0f}v{bv:.0f}{'+' if cv < bv else ('=' if abs(cv-bv) < 1e-6 else '-')} "
        print(row)
print(f"\n--> extension so far: RT-dominates {rt_win}, RT-loss {rt_loss}")
