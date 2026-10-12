"""Wait for the cap-TL screen (R203,R211 captl N=3) to finish, then report the PAIRED
comparison vs the banked head-to-head baseline. Tracked-background so it auto-notifies."""
import time, os, csv, glob, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = {"R203": 919.8, "R211": 900.3}
# banked baseline from the killed head-to-head (mk_h2h_*.csv), same seeds
BASE = {("R203", 0): 962.8, ("R203", 1): 952.0, ("R203", 2): 947.7,
        ("R211", 0): 904.2, ("R211", 1): 936.6, ("R211", 2): 919.0}


def read_captl():
    d = {}
    for h in ("A", "B"):
        p = os.path.join(ROOT, "validation", f"captl_screen_{h}.csv")
        if os.path.exists(p):
            for r in csv.DictReader(open(p)):
                if r.get("best_obj") not in ("", "None", None):
                    d[(r["cell"], int(r["seed"]))] = (float(r["best_obj"]), float(r["wall_to_best"]))
    return d


def report(d):
    print("=== cap-TL screen: PAIRED cap-TL vs baseline (banked) ===")
    wins_vs_base = 0; wins_vs_K = 0; n = 0
    for cell in ("R203", "R211"):
        for s in range(3):
            if (cell, s) not in d:
                continue
            n += 1
            ov, wtb = d[(cell, s)]; b = BASE[(cell, s)]; k = K[cell]
            vb = "BEATS base" if ov < b - 1e-6 else "worse"
            vk = "BEATS K" if ov < k else "lose"
            if ov < b - 1e-6: wins_vs_base += 1
            if ov < k: wins_vs_K += 1
            print(f"  {cell} s{s}: capTL={ov:.1f} vs base={b:.1f} [{vb} {ov-b:+.1f}] | K={k} [{vk}] wtb={wtb:.0f}s")
    for cell in ("R203", "R211"):
        cs = [d[(cell, s)][0] for s in range(3) if (cell, s) in d]
        bs = [BASE[(cell, s)] for s in range(3) if (cell, s) in d]
        if cs:
            print(f"  {cell} MEAN: capTL={sum(cs)/len(cs):.1f} vs base={sum(bs)/len(bs):.1f} "
                  f"({'capTL better' if sum(cs)<sum(bs) else 'capTL WORSE'} by {abs(sum(cs)-sum(bs))/len(cs):.1f})")
    print(f"--> cap-TL beats baseline on {wins_vs_base}/{n} paired seeds; beats K on {wins_vs_K}/{n}")
    print("VERDICT: cap-TL PROMISING (build parallel version / extend)" if wins_vs_base >= n * 0.6
          else "VERDICT: cap-TL does NOT clearly beat baseline -> freeze baseline")


def main():
    for _ in range(80):                       # ~2.6h
        d = read_captl()
        if len(d) >= 6:
            report(d); return
        print(f"[poll] cap-TL runs done: {len(d)}/6", flush=True)
        time.sleep(120)
    print("timeout; partial results:")
    report(read_captl())


if __name__ == "__main__":
    main()
