"""The primal against K reported as MEAN and SD, with best-of demoted to complementary.

AUTHOR DECISION, 2026-09-17: *"We wont compare BESTOFALL to K's OV as a main metric - quote mean
and std - Best as complementary info only."*

WHY THIS IS THE RIGHT METRIC AND NOT A CONCESSION. A best-of over many runs is a statistic about
a PORTFOLIO, not about a method, and its value grows with the compute spent on it. Reporting it
against K's single published incumbent compares our budget with their algorithm. The fairness
audit measured what that costs: summed per cell, |C| = 30 sits at 122-304% of K's normalised
budget and the n20 tail at 294-588% (`FINDING_rt_budget_fairness.md`). Mean and SD describe what
the method DOES; best-of describes what a portfolio FOUND.

THE COMPARISON IS STILL NOT SYMMETRIC, AND THE ASYMMETRY MUST BE STATED RATHER THAN QUIETLY
CHOSEN. K's published `bk` is itself the better of TWO methods (Joint and LBBD) and carries
whatever tuning they did; it is not a single draw. So:
  * mean/SD of our runs vs K's bk        -- conservative AGAINST us, and is the headline
  * our best-of vs K's bk                -- flattering to us, and is complementary only
Neither is a like-for-like draw-vs-draw comparison, and this file does not pretend otherwise. What
it does is stop the flattering one being the headline.

WHAT IS POOLED, AND THE DEFECT IN DOING SO. The banked fixopt corpus mixes variants, budgets and
thread counts, so a mean over it is a mean over a heterogeneous population, not over repeated
draws of one configuration. That is a real limitation and it is reported per cell (`n`, and the
variant count) rather than hidden in an aggregate. A clean mean needs a frozen-configuration arm,
which `ov-corpus-cannot-select-variant` already says the corpus cannot substitute for.

Every objective here is a run's own final incumbent as logged; K's is min(joint_bk, lbbd_bk), the
comparator rule settled in AUDIT_comparator_asymmetry (decision 1).
"""
import argparse, collections, glob, json, os, re, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
import analysis.manuscript_numbers as M                      # noqa: E402


def k_target(cell, size):
    pi = M._K()["table3"]["per_instance"].get(str(size), {})
    r = pi.get(cell)
    if not r:
        return None
    return min(r["joint_bk"], r.get("lbbd_bk", r["joint_bk"]))


def corpus(size):
    """per cell -> list of (final_incumbent, variant)"""
    out = collections.defaultdict(list)
    for f in glob.glob(os.path.join(ROOT, "runs", "fixopt_*_n%d_*.jsonl" % size)):
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n\d+_s\d+_(.+?)_\d+\.jsonl$", os.path.basename(f))
        if not m:
            continue
        cell, variant = m.group(1), m.group(2)
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        vals = [r.get("best_incumbent") for r in rows
                if isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0]
        if vals:
            out[cell].append((min(vals), variant))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="20,30")
    ap.add_argument("--variant", default=None,
                    help="restrict to ONE variant. The pooled corpus mixes ablation "
                         "arms that were deliberately weakened, which penalises the "
                         "mean; restricting to a single production variant is the "
                         "cleanest estimate the corpus can give.")
    ap.add_argument("--out", default="runs/primal_mean_vs_k.json")
    a = ap.parse_args()
    report = {}

    for size in [int(x) for x in a.sizes.split(",")]:
        C = corpus(size)
        if a.variant:
            C = {c: [x for x in v if x[1] == a.variant] for c, v in C.items()}
            C = {c: v for c, v in C.items() if v}
        if not C:
            continue
        print("\n=== |C| = %d : our runs against K's best-known ===" % size)
        print("%-7s %5s %5s | %10s %9s | %10s | %9s %9s %9s" %
              ("cell", "n", "var", "our mean", "our sd", "K bk", "mean d%", "sd d%", "best d%"))
        md, bd, rows = [], [], []
        for cell in sorted(C):
            kb = k_target(cell, size)
            v = [x[0] for x in C[cell]]
            nv = len({x[1] for x in C[cell]})
            if kb is None or len(v) < 2:
                continue
            mu, sd, bo = st.mean(v), st.stdev(v), min(v)
            dm, db = 100 * (mu - kb) / kb, 100 * (bo - kb) / kb
            md.append(dm); bd.append(db)
            rows.append((cell, len(v), nv, mu, sd, kb, dm, 100 * sd / kb, db))
            print("%-7s %5d %5d | %10.1f %9.1f | %10.1f | %+8.1f%% %8.1f%% %+8.1f%%" %
                  (cell, len(v), nv, mu, sd, kb, dm, 100 * sd / kb, db))
        if not md:
            continue
        print("-" * 96)
        print("%-7s %5d %5s | %10s %9s | %10s | %+8.1f%% %8s %+8.1f%%" %
              ("MEDIAN", len(md), "", "", "", "", st.median(md), "", st.median(bd)))
        print("%-7s %5s %5s | %10s %9s | %10s | %+8.1f%% %8s %+8.1f%%" %
              ("MEAN", "", "", "", "", "", st.mean(md), "", st.mean(bd)))
        wins_mean = sum(1 for x in md if x < 0)
        wins_best = sum(1 for x in bd if x < 0)
        print("\n  cells where our MEAN beats K : %d of %d" % (wins_mean, len(md)))
        print("  cells where our BEST beats K : %d of %d   (complementary only)"
              % (wins_best, len(bd)))
        print("  the gap between those two counts is the size of the best-of effect,")
        print("  i.e. how much of our apparent advantage is portfolio rather than method.")
        print("\n  POOLING CAVEAT: 'var' counts distinct variants pooled into that cell's mean.")
        print("  Where it exceeds 1 the mean is over a heterogeneous population, not repeated")
        print("  draws of one configuration -- a frozen-configuration arm is what would fix it.")
        report[str(size)] = dict(
            cells=len(md), median_mean_dpc=st.median(md), mean_mean_dpc=st.mean(md),
            median_best_dpc=st.median(bd), wins_mean=wins_mean, wins_best=wins_best,
            per_cell=[dict(cell=r[0], n=r[1], variants=r[2], mean=round(r[3], 3),
                           sd=round(r[4], 3), k_bk=r[5], mean_dpc=round(r[6], 3),
                           sd_dpc=round(r[7], 3), best_dpc=round(r[8], 3)) for r in rows])
    json.dump(stamped(dict(headline="MEAN and SD; best-of is complementary only (decision 66)",
                   variant=a.variant, sizes=report), __file__),
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("\nwrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
