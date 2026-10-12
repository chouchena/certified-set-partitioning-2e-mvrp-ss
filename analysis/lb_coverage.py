"""LB coverage extension -- ZERO compute, then a work-list for what is still missing.

WHY: with the primal leg deleted, the desk-reject coverage rule (TRAJECTORY 0b: all 27
instances x {10,20,30} + 50 + 100) now applies to the LB leg, and that leg is reported on 11
cells at n20. But the 11-cell limit was never a compute limit -- it was a hardcoded
K_PAPER_LB dict in lb_crossing_samehw.py.

K's paper lower bound is DERIVABLE for all 27 cells from paper/paper-reference-data.md:
    LB = Joint BK * (1 - Joint Gap% / 100)
Verified against all 11 hardcoded values, 11/11 exact to <0.15. So every cell for which we
already hold an easy_reduction artifact can enter the table with no new solving.

HEADLINE METRIC IS COLD k_max, NOT argmax-over-k. Max-over-k is a legitimate operation on
valid lower bounds, but it selects on the dimension whose validity is the open theorem; the
cold single solve at k_max is selection-free and stands alone. Both are reported, cold first.
"""
import glob, json, os, re, sys
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.lb_crossing_samehw import our_bounds, k_repro   # noqa: E402

ALL27 = ([f"C20{i}" for i in range(1, 9)] + [f"R20{i}" for i in range(1, 10)]
         + ["R210", "R211"] + [f"RC20{i}" for i in range(1, 9)])


def k_paper_lb(size=20):
    """K's per-instance LB at this |C|, derived from their Joint BK and Joint Gap%.

    SIZE IS A PARAMETER because both sides of a ratio must carry it. This function was
    hardcoded to the "= 20" section, and `rt_normalize.py` paired it with n30 artifacts,
    which re-emitted the n20 report under an n30 heading. `lb_verdict_watch.py` had already
    worked around it with a private copy instead of fixing it here. Default 20 keeps every
    existing caller bit-identical; the widened gap-token class ([+*] for K's footnote marks)
    is inert at 20 -- verified against the strict form on all 27 cells before it was made.
    """
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|\s*([\d.]+)\s*\|\s*([\d.+*−-]+)\s*\|", l)
        if m and sec and f"= {size}" in sec:
            try:
                bk = float(m.group(2))
                gap = float(m.group(3).replace("*", "").replace("+", "").replace("−", "-"))
            except ValueError:
                continue
            out[m.group(1)] = bk * (1 - gap / 100)
    return out


def main():
    K = k_paper_lb()
    rows, missing_art, missing_k = [], [], []
    for cell in ALL27:
        ob = our_bounds(cell)
        kp = K.get(cell)
        if kp is None:
            missing_k.append(cell); continue
        if ob is None:
            missing_art.append(cell); continue
        best, kb, cold, kmax, wall = ob
        kr = k_repro(cell)
        kr_b = kr[0] if isinstance(kr, (list, tuple)) and kr else (kr if isinstance(kr, float) else None)
        rows.append(dict(cell=cell, cold=cold, kmax=kmax, wall=wall, best=best, kbest=kb,
                         kpaper=kp, krepro=kr_b))

    print(f"=== LB coverage at |C|=20: {len(rows)} of 27 cells ===")
    print(f"{'cell':7}{'cold k_max':>11}{'k':>4}{'wall_s':>8}{'K_paper':>9}{'cold/K':>8}"
          f"{'>K_paper':>9}{'argmax':>9}{'k*':>4}{'>K_rep':>8}")
    nc = nb = nkr = kr_n = 0
    for r in rows:
        cg = r["cold"] > r["kpaper"]; bg = r["best"] > r["kpaper"]
        nc += cg; nb += bg
        krs = ""
        if r["krepro"]:
            kr_n += 1
            hit = r["cold"] > r["krepro"]; nkr += hit
            krs = "Y" if hit else "n"
        print(f"{r['cell']:7}{r['cold']:11.2f}{r['kmax']:4}{(r['wall'] or 0):8.1f}"
              f"{r['kpaper']:9.2f}{r['cold']/r['kpaper']:8.2f}{'Y' if cg else 'n':>9}"
              f"{r['best']:9.2f}{r['kbest']:4}{krs:>8}")
    print(f"\n  COLD k_max (selection-free) beats K's paper LB : {nc}/{len(rows)}")
    print(f"  argmax-over-k beats K's paper LB               : {nb}/{len(rows)}")
    if kr_n:
        print(f"  COLD k_max beats K's REPRODUCED LBBD           : {nkr}/{kr_n}")
    if rows:
        rat = sorted(r["cold"] / r["kpaper"] for r in rows)
        print(f"  cold/K_paper ratio: min {rat[0]:.2f}  median {st.median(rat):.2f}  max {rat[-1]:.2f}")

    print(f"\n=== WORK LIST to reach 27/27 at |C|=20 ===")
    print(f"  need easy_reduction artifact ({len(missing_art)}): {' '.join(missing_art)}")
    if missing_k:
        print(f"  K paper LB underivable ({len(missing_k)}): {' '.join(missing_k)}")
    print(f"  cold-solve wall times observed: "
          f"{min((r['wall'] or 0) for r in rows):.1f}-{max((r['wall'] or 0) for r in rows):.1f}s per cell")


if __name__ == "__main__":
    main()
