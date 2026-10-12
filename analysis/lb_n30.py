"""Extend the LB leg to |C|=30 -- the CORE GRID size, and the one the paper's asset does not reach.

WHERE WE ACTUALLY ARE. Every LB result in this project is n20: 29 artifacts at n20 versus 3 at
n30, and those 3 have ZERO proven records. They used a different bounder (cpsat, not the cplex
descend that produced every n20 number), all hit a 900s wall at proven=False, and R207's
unproven 433.51 sits just BELOW K's n30 LB of ~436.5. So the 18/20 dominance and the 0.004x
RT-to-beat are n20 statements with no evidence at n30.

WHY n30 IS THE RIGHT NEXT SIZE, not 40/50/100:
  - TRAJECTORY 0b calls n30 the CORE GRID and explicitly notes it is NOT infra-gated.
  - K reports n30 PER-INSTANCE (Table 3), so the same cell-by-cell comparison is possible.
    At n50 K reports only pooled averages over 27 instances; at n100 only per-family averages
    at a DIFFERENT proximity (0.1 vs 0.0). Neither supports a per-cell claim.
  - K's n30 table has 26 beatable cells (gap 2-71%) against n20's 20 -- MORE opportunity.

DESIGN. Same cplex descend that produced the n20 result, at 4 threads (K's basis), single
tenant. k_hi is scaled to keep the DROP FRACTION comparable: n20 used k_max 9-10 of 20
(~45-50%), so n30 uses 15 of 30. Cells are ordered by descending K gap -- the regime where the
n20 advantage was largest, so a failure there is decisive rather than ambiguous.

HONEST PRIOR: this may simply not transfer. The n20 wins came from proven bounds in 0.1-68.8s;
at n30 the only existing evidence is three unproven bounds at a 900s wall. If nothing proves
within the budget, that is the finding -- and it scopes the paper to n20 rather than hiding it.
"""
import argparse, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(os.path.join(ROOT, "runs", "lb_n30.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def k_n30():
    """K's per-instance LB, gap and LBBD IncT at |C|=30, from Table 3."""
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|" + r"\s*([\d.+*−-]+)\s*\|" * 6, l)
        if m and sec and "= 30" in sec:
            try:
                bk = float(m.group(2))
                gap = float(m.group(3).replace("*", "").replace("−", "-"))
                out[m.group(1)] = (bk * (1 - gap / 100), gap, float(m.group(7)))
            except ValueError:
                pass
    return out


def report(K):
    print("\n=== LB at |C|=30 vs K (per-instance, Table 3) ===")
    print(f"{'cell':7}{'Kgap':>6}{'K LB':>9}{'K IncT':>9}{'cold':>9}{'best':>9}"
          f"{'cold/K':>8}{'best/K':>8}{'RT-beat':>9}{'ratio':>8}")
    for f in sorted(__import__("glob").glob(os.path.join(ROOT, "crossfeed",
                                                         "easy_reduction*_n30.json"))):
        m = re.search(r"_((?:C|R|RC)\d{3})_n30", f)
        if not m or m.group(1) not in K:
            continue
        cell = m.group(1)
        recs = json.load(open(f, encoding="utf-8"))
        recs = recs if isinstance(recs, list) else [recs]
        pv = [x for x in recs if isinstance(x, dict) and x.get("proven") and "block_relax" in x]
        klb, kgap, kinct = K[cell]
        if not pv:
            print(f"{cell:7}{kgap:5.0f}%{klb:9.1f}{kinct:9.0f}"
                  f"{'NO PROVEN BOUND':>43}")
            continue
        kmax = max(pv, key=lambda r: r["k"]); best = max(pv, key=lambda r: r["block_relax"])
        cum, hit = 0.0, None
        for r in sorted(pv, key=lambda r: -r["k"]):
            cum += r.get("wall") or 0
            if r["block_relax"] > klb:
                hit = cum; break
        print(f"{cell:7}{kgap:5.0f}%{klb:9.1f}{kinct:9.0f}{kmax['block_relax']:9.1f}"
              f"{best['block_relax']:9.1f}{kmax['block_relax']/klb:7.2f}x{best['block_relax']/klb:7.2f}x"
              f"{(f'{hit:.1f}s' if hit else 'never'):>9}{(f'{hit/kinct:.3f}x' if hit else '--'):>8}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="")
    ap.add_argument("--n", type=int, default=6, help="how many cells, highest K gap first")
    ap.add_argument("--k-hi", type=int, default=15, help="n20 used 9-10 of 20 (~45-50%); "
                                                         "15 of 30 keeps the drop fraction comparable")
    ap.add_argument("--tl", type=int, default=450)
    ap.add_argument("--timeout", type=int, default=5400)
    a = ap.parse_args()
    K = k_n30()
    if a.cells:
        cells = [c.strip() for c in a.cells.split(",") if c.strip()]
    else:
        # FAMILY-BALANCED, highest K gap within each family. Taking the global top-N would
        # give 5 RC / 1 C / 0 R -- and R is the family where the n20 bound performed WORST
        # (mean advantage 1.24 vs C 1.53, RC 1.56, and both n20 losses were R). A batch with
        # no R cells would flatter us exactly where the method is weakest.
        per = max(1, a.n // 3)
        cells = []
        for fam in ("C", "R", "RC"):
            fc = [(c, v[1]) for c, v in K.items() if v[1] > 0
                  and ("RC" if c.startswith("RC") else c[0]) == fam]
            cells += [c for c, _ in sorted(fc, key=lambda t: -t[1])[:per]]
    say(f"LB at n30, {len(cells)} cells, highest K gap first: {cells}")
    for i, c in enumerate(cells, 1):
        say(f"[{i}/{len(cells)}] {c} (K gap {K[c][1]:.0f}%) ...")
        t0 = time.time()
        try:
            subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                            "--cells", c, "--size", "30", "--tl", str(a.tl),
                            "--k-hi", str(a.k_hi), "--workers", "4"],
                           cwd=ROOT, timeout=a.timeout)
        except Exception as e:
            say(f"  {c} error/timeout: {e}")
        say(f"  {c} done in {time.time()-t0:.0f}s")
        report(K)
    say("LB n30 COMPLETE")


if __name__ == "__main__":
    main()
