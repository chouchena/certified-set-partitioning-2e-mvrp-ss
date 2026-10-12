"""Structure of the n30 cells we lose on, against same-family cells we win on. (d465)

Author, 2026-09-26: "thorough analysis of their structure and algo headrooms left unaddressed
versus comparable". The numbers this prints were first produced inline and cited from a
transcript; this module is their generating code, as the replicability rule requires.

THREE THINGS IT ESTABLISHES, each with its own falsifier.

  1. THE NEAR-TWIN PAIR. RC202 and RC207 share tau, bucket width, bucket count, demand, mean and
     minimum window width, and trip count to within one; RC202 has the BETTER street. RC202 uses
     three cars, RC207 two, and they land on opposite sides of the predecessors by 26 points. The
     whole RC202 gap is one car. Falsified by any aggregate on which the two differ materially.

  2. THE TIME-WINDOW HYPOTHESIS, TESTED AND WITHDRAWN. Four hand-picked pairs suggested tight
     windows are where we lose. Over all 27 cells, mean window over bucket width against our margin
     to K gives a Pearson r that is weakly negative and explains about a tenth of the variance, and
     the near-twins have the same window profile. Selection bias, and recorded as such.

  3. THE FLEET FLOOR. ceil(N_LP) from the PROVEN default-bucket LP is a valid lower bound on the
     car count of any feasible solution, because floor bucketing is a relaxation. Cells at that
     floor have a provably optimal fleet and their residual gap is street routing. A finer bucket
     RAISES N_LP (d464), so a floor read at the default width can be too low, never too high.

    python analysis/tep_n30_structure.py
"""
import io
import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
import tep_cg_bound as T
from k_comparison import k_proximity
from stamp import stamped

SIZE = 30
GROUPS = (("RC lose", ["RC202", "RC206", "RC201"]), ("RC win", ["RC207", "RC204", "RC205"]),
          ("R  lose", ["R206", "R201"]), ("R  win", ["R208", "R207", "R210"]),
          ("C  lose", ["C206", "C202"]), ("C  win", ["C203", "C204"]))
TWINS = ("RC202", "RC207")


def describe(cell, r, prox):
    inst = V.load_instance(cell, SIZE, prox)
    nd, D = inst.nodes, inst.D
    cu = list(inst.customers)
    tw = [float(nd[i].latest) - float(nd[i].earliest) for i in cu]
    delta = T.default_delta(inst)
    hz = float(nd[inst.depot].latest) - float(nd[inst.depot].earliest)
    p = (os.path.join(ROOT, "runs", "postpass", "ownwater_%s_n%d.json" % (cell, SIZE)) if r["cfg"] == "floor"
         else os.path.join(ROOT, "runs", "postpass", r["cfg"], "ownwater_%s_n%d.json" % (cell, SIZE)))
    s = json.load(io.open(p, encoding="utf-8"))
    hub = {int(x): int(h) for x, h in zip(s["vi"], s["hubs"])}
    ts = set(hub)
    street = sum((D[i][hub[i]] + D[hub[i]][j]) if i in ts else D[i][j]
                 for i, j in ((int(a), int(b)) for a, b in s["xij"]))
    b = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s_n%d.json" % (cell, SIZE))
    nlp, floor = None, None
    if os.path.exists(b):
        d = json.load(io.open(b, encoding="utf-8"))
        if d.get("proven") and d.get("N") is not None:
            nlp = float(d["N"]); floor = int(math.ceil(nlp - 1e-9))
    return dict(cell=cell, vs_them=100.0 * (r["best"] / r["theirs"] - 1), cars=r["cars"], n_lp=nlp,
                car_floor=floor, trips=len(s["vi"]) + r["cars"], transfers=len(s["vi"]),
                tw_mean=st.mean(tw), tw_min=min(tw), tau=float(inst.tau), delta=delta,
                buckets=hz / delta, slack=st.mean(tw) / delta,
                demand=sum(float(nd[i].demand) for i in cu), street=street,
                lb_gap=(100.0 * (1 - r["our_lb"] / r["best"]) if r.get("our_lb") else None),
                ours=r["best"], theirs=r["theirs"], cfg=r["cfg"])


def main():
    prox = k_proximity(SIZE)
    rows = {r["cell"]: r for r in json.load(io.open(os.path.join(ROOT, "runs", "oracle", "tep_n30_best_of.json"),
                                                   encoding="utf-8"))["rows"]}
    desc = {c: describe(c, rows[c], prox) for c in rows}

    print("1. Losing cells against winning cells, same family.\n")
    print("%-8s %8s %5s %6s %6s %7s %6s %7s %7s %7s"
          % ("cell", "vs them", "cars", "floor", "trips", "twMean", "twMin", "demand", "street", "LBgap"))
    for name, cells in GROUPS:
        print("  -- %s" % name)
        for c in cells:
            d = desc[c]
            print("%-8s %+7.2f%% %5d %6s %6d %7.0f %6.0f %7.0f %7.0f %6s"
                  % (c, d["vs_them"], d["cars"], d["car_floor"] if d["car_floor"] is not None else "-",
                     d["trips"], d["tw_mean"], d["tw_min"], d["demand"], d["street"],
                     ("%.1f%%" % d["lb_gap"]) if d["lb_gap"] is not None else "-"))

    a, b = desc[TWINS[0]], desc[TWINS[1]]
    print("\n2. The near-twin pair: %s against %s.\n" % TWINS)
    for k, lab in (("tau", "tau"), ("delta", "bucket width"), ("buckets", "buckets"), ("tw_mean", "window mean"),
                   ("tw_min", "window min"), ("demand", "demand"), ("trips", "trips"), ("street", "street"),
                   ("cars", "CARS"), ("car_floor", "car floor"), ("vs_them", "vs their best (%)")):
        print("   %-18s %10.1f %10.1f" % (lab, float(a[k]), float(b[k])))
    print("   the gap is %.1f; one car is %.1f" % (a["ours"] - a["theirs"], float(V.load_instance(TWINS[0], SIZE, prox).penalty_cars)))

    X = [desc[c]["slack"] for c in desc]; Y = [desc[c]["vs_them"] for c in desc]
    mx, my = st.mean(X), st.mean(Y)
    num = sum((x - mx) * (y - my) for x, y in zip(X, Y))
    den = (sum((x - mx) ** 2 for x in X) * sum((y - my) ** 2 for y in Y)) ** 0.5
    r = num / den if den else float("nan")
    q = sorted((desc[c]["slack"], desc[c]["vs_them"], c) for c in desc)
    k = len(q) // 3
    lo = st.median([y for _, y, _ in q[:k]]); hi = st.median([y for _, y, _ in q[-k:]])
    print("\n3. Window slack (mean window / bucket width) against our margin, all %d cells." % len(X))
    print("   Pearson r = %+.3f  (r^2 = %.2f)" % (r, r * r))
    print("   tightest %d: median %+.2f%%   widest %d: median %+.2f%%" % (k, lo, k, hi))
    print("   the near-twins have slack %.1f and %.1f -- the hypothesis cannot separate them." % (a["slack"], b["slack"]))

    at_floor = [c for c in desc if desc[c]["car_floor"] is not None and desc[c]["cars"] == desc[c]["car_floor"]]
    above = [c for c in desc if desc[c]["car_floor"] is not None and desc[c]["cars"] > desc[c]["car_floor"]]
    print("\n4. Fleet: %d cells AT their proven car floor (fleet optimal, residual is street); %d ABOVE it: %s"
          % (len(at_floor), len(above), ", ".join(sorted(above))))
    print("   a floor read at the default bucket width can be too LOW, never too high (d464).")

    out = dict(size=SIZE, cells=list(desc.values()), pearson_r=r, tightest_median=lo, widest_median=hi,
               twins=TWINS, at_floor=sorted(at_floor), above_floor=sorted(above))
    p = os.path.join(ROOT, "runs", "oracle", "tep_n30_structure.json")
    json.dump(stamped(out), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("\n  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
