"""
portfolio_trace.py -- reconstruct per-island convergence from the RunLogger
jsonls, mark migration / kick events, and answer the post-hoc questions:
  * which island (and which event: rotation move / kick / migrate_in) produced
    the global best, and when
  * time-to-target: first wall_s any island reached <= target (BKS or LB)
  * gap-vs-RT: what fraction of the total improvement came in the last X% of
    the run (feeds the "stop early by LB proximity" decision)

  python -m analysis.portfolio_trace --instance RC203 --size 20 --seed 0 \
      [--variant-glob 'pf_*'] [--target 739.22] [--lb 656.45] [--plot out.png]
"""
from __future__ import annotations
import argparse, glob, json, os


def load_island(path):
    evs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            evs.append(d)
    return evs


def step_curve(evs):
    """[(wall_s, best_incumbent)] — monotone non-increasing step function."""
    pts, cur = [], None
    for d in evs:
        bi = d.get("best_incumbent")
        if bi is None:
            continue
        if cur is None or bi < cur - 1e-9:
            cur = bi
            pts.append((round(d.get("wall_s", 0.0), 1), bi))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--variant-glob", default="pf_*")
    ap.add_argument("--target", type=float, default=None, help="BKS for time-to-target")
    ap.add_argument("--lb", type=float, default=None, help="valid LB for gap%")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--plot", default=None)
    a = ap.parse_args()

    pat = os.path.join(a.runs_dir, f"fixopt_{a.instance}_n{a.size}_s{a.seed}_{a.variant_glob}.jsonl")
    files = sorted(glob.glob(pat))
    if not files:
        print("no island jsonls match", pat)
        return

    islands = {}
    events = {}   # island -> list of (wall_s, kind, obj)
    for fp in files:
        name = os.path.basename(fp).split(f"_s{a.seed}_")[-1].replace(".jsonl", "")
        evs = load_island(fp)
        islands[name] = step_curve(evs)
        ev = []
        for d in evs:
            tr = d.get("trigger", "")
            w = round(d.get("wall_s", 0.0), 1)
            if tr == "migrate_in":
                ev.append((w, "migrate_in", (d.get("extra") or {}).get("obj")))
            elif tr == "migrate_out":
                ev.append((w, "migrate_out", (d.get("extra") or {}).get("obj")))
            elif "kick" in tr and d.get("best_incumbent") is not None and d.get("incumbent") is not None:
                ev.append((w, "kick_gain", d["incumbent"]))
        events[name] = ev

    # global best over all islands + who/when/how
    gb, gb_isl, gb_t, gb_kind = 1e18, None, None, None
    for name, evs in islands.items():
        for (w, obj) in evs:
            if obj < gb - 1e-9:
                gb, gb_isl, gb_t = obj, name, w
    # classify the event that produced it
    for (w, kind, obj) in events.get(gb_isl, []):
        if obj is not None and abs(obj - gb) < 1e-6:
            gb_kind = kind

    print(f"\n=== {a.instance} n{a.size} s{a.seed} ===")
    for name, evs in islands.items():
        fin = evs[-1][1] if evs else None
        nmig = sum(1 for (_, k, _) in events[name] if k == "migrate_in")
        nkick = sum(1 for (_, k, _) in events[name] if k == "kick_gain")
        print(f"  {name:9} final={fin}  steps={len(evs)}  migrate_in={nmig}  kick_gains={nkick}")
    print(f"  GLOBAL BEST = {gb:.2f}  by island '{gb_isl}' at {gb_t}s  (event: {gb_kind or 'rotation'})")

    if a.lb:
        print(f"  gap vs LB {a.lb}: {(gb - a.lb) / gb * 100:.2f}%")
    if a.target:
        # first time any island reached <= target
        tt = None
        for name, evs in islands.items():
            for (w, obj) in evs:
                if obj <= a.target + 1e-6:
                    tt = w if tt is None else min(tt, w)
                    break
        print(f"  time-to-target ({a.target}): {tt if tt is not None else 'not reached'}")

    # gap-vs-RT: fraction of total improvement in the last 25% of wall time
    for name, evs in islands.items():
        if len(evs) < 2:
            continue
        t_end = evs[-1][0]
        span = evs[0][1] - evs[-1][1]
        if span <= 0 or t_end <= 0:
            continue
        cut = 0.75 * t_end
        after = next((o for (w, o) in evs if w >= cut), evs[-1][1])
        late = (after - evs[-1][1]) / span * 100
        print(f"  {name:9} improvement in last 25% of RT: {late:.1f}% of total")

    if a.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(9, 5))
            for name, evs in islands.items():
                if not evs:
                    continue
                xs = [w for (w, _) in evs] + [evs[-1][0]]
                ys = [o for (_, o) in evs] + [evs[-1][1]]
                ax.step(xs, ys, where="post", label=name)
                for (w, kind, _) in events[name]:
                    ax.axvline(w, alpha=0.15,
                               color={"migrate_in": "g", "migrate_out": "b", "kick_gain": "r"}.get(kind, "k"))
            if a.target:
                ax.axhline(a.target, ls="--", color="k", label="BKS")
            if a.lb:
                ax.axhline(a.lb, ls=":", color="gray", label="LB")
            ax.set_xlabel("wall_s"); ax.set_ylabel("best incumbent"); ax.legend()
            ax.set_title(f"{a.instance} n{a.size} s{a.seed}")
            fig.savefig(a.plot, dpi=110, bbox_inches="tight")
            print(f"  plot -> {a.plot}")
        except Exception as ex:
            print(f"  plot failed: {ex}")


if __name__ == "__main__":
    main()
