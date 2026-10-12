"""Every cell x every size x every proximity through greedy26 and verifier3.

WHAT THIS IS. A COVERAGE test of the constructive generator and the verifier, over the entire
instance space rather than the three cells the smoke uses. 27 cells x 6 sizes x 5 proximities.
No solver is involved at any point -- greedy26 constructs, verifier3 checks arithmetic -- so the
whole grid costs minutes.

WHAT IT BUYS. verifier3 currently sees 15 greedy seeds and 30 impaired solutions. This puts 810
independent (instance, solution) pairs through it, and puts every instance in the space through
construction, which is the only way to find a cell that fails to build or a corner where the
generator cannot place a transfer.

WHAT IT IS NOT, stated so the pass is not over-read.

  * MOST OF THIS GRID IS NOT COMPARABLE TO K. K publish p = 0.0 for Tables 3 and 4, p = 0.1 for
    Table 6 and Fig. 5, and a sweep {0, 0.1, 0.2, 0.3, 0.4} at |C| = 50 only (Fig. 4). Every
    other (size, proximity) pairing here is one K never ran -- p = 0.0 at |C| = 100 is precisely
    the mismatch that voided a batch (d209). Each row is therefore LABELLED published or not, and
    nothing from an unpublished pairing may be compared to their numbers.
  * GREEDY SEEDS ARE POOR SOLUTIONS. This tests feasibility coverage, not quality. An ACCEPT here
    says the construction is sound, not that the objective is any good.
  * IT IS NOT INDEPENDENT. greedy26 and verifier3 are both ours, written from one reading of K's
    article. A misreading in both agrees with itself. That is oracle-residue-open's territory.

    python analysis/greedy_grid_full.py [--sizes 10,20,30,40,50,100] [--prox 0.0,0.1,0.2,0.3,0.4]
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import instance_view
import verifier3
import greedy26

OUT = os.path.join(ROOT, "runs", "oracle")
CELLS = (["C20%d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC20%d" % i for i in range(1, 9)])


def published(size, prox):
    """Is this (size, proximity) a pairing K actually ran? Table 3/4 p=0.0 at 10/20/30/50,
    Table 6 p=0.1 at 100, Fig. 5 p=0.1 at 10-50, Fig. 4 sweeps p at 50 only."""
    if prox == 0.0 and size in (10, 20, 30, 50):
        return "table3/4"
    if prox == 0.1 and size == 100:
        return "table6"
    if prox == 0.1 and size in (10, 20, 30, 40, 50):
        return "fig5"
    if size == 50 and prox in (0.2, 0.3, 0.4):
        return "fig4 sweep"
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10,20,30,40,50,100")
    ap.add_argument("--prox", default="0.0,0.1,0.2,0.3,0.4")
    a = ap.parse_args()
    sizes = [int(x) for x in a.sizes.split(",")]
    proxes = [float(x) for x in a.prox.split(",")]
    os.makedirs(OUT, exist_ok=True)

    print("GREEDY26 x VERIFIER3 over the FULL grid: %d cells x %d sizes x %d proximities = %d"
          % (len(CELLS), len(sizes), len(proxes), len(CELLS) * len(sizes) * len(proxes)))
    print("No solver anywhere: greedy26 constructs, verifier3 checks arithmetic.")
    print()
    rows, t0 = [], time.time()
    bad, noseed, built = [], [], 0
    raws = {}
    for size in sizes:
        for prox in proxes:
            acc = rej = ns = 0
            c26 = 0
            for cell in CELLS:
                if cell not in raws:
                    raws[cell] = instance_view.VInstance._load_json(cell)
                try:
                    inst = instance_view.VInstance(cell, size, wls=0.1,
                                                   tau=verifier3.tau_for(raws[cell], size),
                                                   proximity=prox)
                except Exception as e:
                    bad.append("%s/n%d/p%s: instance build raised %s"
                               % (cell, size, prox, type(e).__name__))
                    continue
                built += 1
                try:
                    sol = greedy26.construct(inst)
                except Exception as e:
                    bad.append("%s/n%d/p%s: greedy raised %s" % (cell, size, prox,
                                                                 type(e).__name__))
                    ns += 1
                    continue
                if sol is None:
                    noseed.append("%s/n%d/p%s" % (cell, size, prox))
                    ns += 1
                    continue
                run = verifier3.verify_solution(inst, sol, cell=cell, size=size,
                                                proximity=prox, label="greedy")
                v = run.verdict()
                nv = len([f for f in run.violations if f.cls.startswith("C26")])
                c26 += nv
                if v == verifier3.ACCEPT:
                    acc += 1
                else:
                    rej += 1
                    if len(bad) < 20:
                        cls = [f.cls for f in run.findings if f.severity == "VIOLATION"]
                        bad.append("%s/n%d/p%s: verifier3 %s (%s)"
                                   % (cell, size, prox, v, cls[0] if cls else "-"))
            pub = published(size, prox)
            rows.append(dict(size=size, proximity=prox, published=pub, accept=acc,
                             reject=rej, no_seed=ns, c26=c26))
            print("   n%-4d p%-4s %-11s ACCEPT %2d/%2d   no-seed %2d   (26) posts %d"
                  % (size, prox, pub or "NOT K's", acc, len(CELLS), ns, c26))

    tot_acc = sum(r["accept"] for r in rows)
    tot_rej = sum(r["reject"] for r in rows)
    tot_ns = sum(r["no_seed"] for r in rows)
    tot_c26 = sum(r["c26"] for r in rows)
    print()
    print("   instances built %d | ACCEPT %d | REJECT %d | no seed %d | (26) violations %d"
          % (built, tot_acc, tot_rej, tot_ns, tot_c26))
    for b in bad[:12]:
        print("      " + b)
    if noseed:
        print("      no seed on %d combination(s), e.g. %s"
              % (len(noseed), ", ".join(noseed[:6])))
    pubrows = [r for r in rows if r["published"]]
    print()
    print("   of these, %d of %d (size, proximity) pairings are ones K actually ran; the rest"
          % (len(pubrows), len(rows)))
    print("   are ours alone and NOTHING from them may be compared to K's numbers.")
    json.dump(stamped({"rows": rows, "failures": bad, "no_seed": noseed, "built": built,
               "accept": tot_acc, "reject": tot_rej, "c26": tot_c26,
               "verdict": "PASS" if not (tot_rej or bad) else "FAIL",
               "wall_s": round(time.time() - t0, 1)}, __file__),
              open(os.path.join(OUT, "greedy_grid_full.json"), "w"), indent=1, default=str)
    print()
    print("   %.1f s" % (time.time() - t0))
    return 1 if (tot_rej or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
