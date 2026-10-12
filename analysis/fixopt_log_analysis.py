"""
fixopt_log_analysis.py -- dissect the fixopt rseg stream: construction vs final,
improvement curve, plateau onset, wasted budget, per-mode contribution, kicks.

Sources:
  validation/pipeline_fixopt.log   -- the +improve obj=.. mode=.. t=.. trace
  runs/fixopt_<cell>_n20_s0_rseg.jsonl  -- RunLogger events (mode tags, noimprove)
"""
from __future__ import annotations
import json, re, sys, glob, os
from collections import defaultdict

PIPE = "validation/pipeline_fixopt.log"
BUDGET = 600.0

CELLS_ORDER = ["R203", "R204", "R207", "R208", "R211", "RC202", "RC204", "RC208"]


def parse_pipeline(path):
    """-> {cell: {'construct': float|None, 'events': [(t, obj, mode)], 'final': float}}"""
    cells = {}
    cur = None
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"fixopt rseg (\w+)\s", ln)
        if m:
            cur = m.group(1)
            cells[cur] = {"construct": None, "events": [], "final": None}
            continue
        if cur is None:
            continue
        m = re.search(r"construct:\s*ok=\w+\s+obj=([\d.]+)", ln)
        if m:
            cells[cur]["construct"] = float(m.group(1))
            continue
        m = re.search(r"\+improve obj=([\d.]+)\s+mode=(\w+).*?t=(\d+)s", ln)
        if m:
            cells[cur]["events"].append((int(m.group(3)), float(m.group(1)), m.group(2)))
            continue
        m = re.search(r"final best \(verified\)\s*=\s*([\d.]+)", ln)
        if m:
            cells[cur]["final"] = float(m.group(1))
    return cells


def analyse(cell, d):
    ev = d["events"]
    if not ev:
        print(f"{cell:6s}  no improvement events"); return
    c0 = d["construct"]
    fin = d["final"] or ev[-1][1]
    t_last = ev[-1][0]
    waste = BUDGET - t_last
    # 90%-of-total-improvement time
    total_imp = (c0 - fin) if c0 else (ev[0][1] - fin)
    base = c0 if c0 else ev[0][1]
    t90 = next((t for (t, o, _) in ev if base - o >= 0.9 * total_imp), t_last)
    # per-mode: sum of obj reduction credited to each mode
    permode = defaultdict(float); permode_n = defaultdict(int)
    prev = base
    for (t, o, md) in ev:
        permode[md] += max(0.0, prev - o); permode_n[md] += 1
        prev = o
    modes = sorted(permode, key=lambda k: -permode[k])
    ms = "  ".join(f"{k}:{permode[k]:.0f}({permode_n[k]})" for k in modes)
    kick = permode.get("kick", 0.0)
    print(f"{cell:6s} constr {c0:7.1f} -> final {fin:7.1f}   "
          f"improved {total_imp:6.1f} ({100*total_imp/base:4.1f}%)")
    print(f"       last improve t={t_last:3d}s   90% done by t={t90:3d}s   "
          f"WASTED {waste:3.0f}s ({100*waste/BUDGET:2.0f}% of budget)")
    print(f"       by mode: {ms}")
    if kick == 0.0 and any(t > 0.5 * BUDGET for t in [waste]):
        print(f"       >>> long dead plateau, no kick active")
    print()


if __name__ == "__main__":
    cells = parse_pipeline(PIPE)
    order = [c for c in CELLS_ORDER if c in cells] + \
            [c for c in cells if c not in CELLS_ORDER]
    print(f"=== fixopt rseg stream — {len(order)} cells, budget {BUDGET:.0f}s ===\n")
    tot_waste = 0.0
    for c in order:
        analyse(c, cells[c])
        if cells[c]["events"]:
            tot_waste += BUDGET - cells[c]["events"][-1][0]
    print(f"--- total wasted budget across {len(order)} cells: "
          f"{tot_waste:.0f}s ({tot_waste/60:.0f} min, "
          f"{100*tot_waste/(BUDGET*len(order)):.0f}% of stream) ---")

    # jsonl noimprove tallies
    print("\n=== noimprove events per cell (from RunLogger jsonl) ===")
    for c in order:
        fp = f"runs/fixopt_{c}_n20_s0_rseg.jsonl"
        if not os.path.exists(fp):
            continue
        ni = defaultdict(int)
        for L in open(fp, encoding="utf-8", errors="replace"):
            try:
                e = json.loads(L)
            except Exception:
                continue
            tr = e.get("trigger", "")
            if tr.startswith("fixopt_noimprove"):
                ni[tr.split(":", 1)[-1]] += 1
        if ni:
            print(f"  {c:6s} " + "  ".join(f"{k}:{v}" for k, v in sorted(ni.items())))
