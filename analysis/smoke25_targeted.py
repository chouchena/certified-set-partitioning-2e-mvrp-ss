"""STEP 7: 25 cells chosen to MAXIMISE the odds of invalidating verifier3's transcription.

Author: *"smoke it on 25 selected cells validated by verifier3 where the odds to invalidate are
the higher."*

SELECTION IS CONSTRAINT-TARGETED, NOT DIFFICULTY-TARGETED. The design audit (A4) found the
existing two-source differential -- verifier3 vs verify2 on 17 |C|=100 dumps -- was strong evidence
about (26) and thin about everything else, because 15 of those 17 REJECTED on C26 and a dump that
fails early exercises nothing downstream. So picking "hard" cells would repeat that mistake: cells
that fail early are exactly the ones that test least.

What raises the odds of invalidation is a cell where the UNDER-EXERCISED constraints actually BIND.
Measured over the 59-incumbent corpus, the least-exercised classes are:

    D8-ARCSET 44, D9-PHI 44, D15-HUB 44, D25-WARCSET 44, OBJ 44   (once per artifact)
    A-STRUCT 88, C3-FLEET 176, C17-WFLEET 176, C4-LASTXFER 410

and four constraints -- (1), (8), (9), (15) -- rest SOLELY on Leg C, which bounds only
over-strictness. Those are the exposure.

BINDING PRESSURE, scored from instance properties alone (no solve, no circularity):

  tau_pressure      transfers per satellite x tau, against the CDC horizon  -> how hard (26) binds
  load_pressure     total demand / LEFV capacity                            -> how hard (5) binds
  window_pressure   mean customer window width / horizon, inverted          -> (6)(11)(12)(13)
  vessel_pressure   total demand / vessel capacity                          -> (18)(19)(20)

A cell scoring high is one where a transcription error has the best chance of producing a
DISAGREEMENT between my reading and reality -- because the constraint is live rather than slack.

    python analysis/smoke25_targeted.py
"""
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import greedy26
import instance_view
import verifier3

CELLS = (["C20%d" % i for i in range(1, 9)]
         + ["R2%02d" % i for i in range(1, 12)]
         + ["RC20%d" % i for i in range(1, 9)])
SIZES = [10, 20, 30, 50, 100]
K_PROX = {10: 0.0, 20: 0.0, 30: 0.0, 50: 0.0, 100: 0.1}
N_PICK = 25
OUT = os.path.join(ROOT, "runs", "smoke25")


def pressure(cell, size):
    """Binding pressure from instance properties only. No solve -- selection must not depend on
    the thing being tested."""
    prox = K_PROX[size]
    raw = instance_view.VInstance._load_json(cell)
    tau = verifier3.tau_for(raw, size)
    inst = instance_view.VInstance(cell, size, wls=0.1, tau=tau, proximity=prox)
    nd, D = inst.nodes, inst.D
    C, P = list(inst.customers), list(inst.satellites)
    horizon = nd[inst.CDC].latest - nd[inst.CDC].earliest
    demand = sum(nd[i].demand for i in C)

    # (26): a transfer every ~4 customers, spread over |P| satellites, each consuming tau
    xfers = max(1.0, size / 4.0)
    tau_p = (xfers / len(P)) * tau / max(1.0, horizon)
    load_p = demand / float(instance_view.LEFV_CAPACITY)
    vessel_p = demand / float(instance_view.VESSEL_CAPACITY)
    widths = [nd[i].latest - nd[i].earliest for i in C]
    window_p = 1.0 - (sum(widths) / len(widths)) / max(1.0, horizon)
    score = 2.0 * tau_p + 0.6 * window_p + 0.25 * (load_p / size) + 0.25 * (vessel_p / size)
    return dict(cell=cell, size=size, proximity=prox, tau=tau, horizon=round(horizon, 1),
                tau_p=round(tau_p, 4), load_p=round(load_p, 2), vessel_p=round(vessel_p, 2),
                window_p=round(window_p, 3), score=round(score, 4), inst=inst)


def main():
    os.makedirs(OUT, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("STEP 7 -- 25 cells selected by BINDING PRESSURE, not by difficulty")
    print()
    t0 = time.time()
    scored = []
    for size in SIZES:
        for cell in CELLS:
            try:
                scored.append(pressure(cell, size))
            except Exception:
                pass
    scored.sort(key=lambda d: -d["score"])
    picks = scored[:N_PICK]
    print("scored %d (cell,size) combinations in %.0fs; taking the top %d"
          % (len(scored), time.time() - t0, N_PICK))
    fam = {}
    for p in picks:
        f = "C" if p["cell"][0] == "C" else ("RC" if p["cell"].startswith("RC") else "R")
        fam[f] = fam.get(f, 0) + 1
    sz = {}
    for p in picks:
        sz[p["size"]] = sz.get(p["size"], 0) + 1
    print("   families %s   sizes %s" % (fam, dict(sorted(sz.items()))))
    print()

    hdr = ("%-7s %5s %5s %6s %8s %7s %6s %-9s %6s %5s %4s"
           % ("cell", "n", "prox", "tau", "tau_p", "window_p", "score", "verifier3",
              "checks", "viol", "C26"))
    print(hdr)
    print("-" * len(hdr))
    rows, fails = [], []
    cls_tot = {}
    for p in picks:
        inst = p.pop("inst")
        sol = greedy26.construct(inst)
        if sol is None:
            print("%-7s %5d %5s %6s %8.4f %7.3f %6.3f %-9s"
                  % (p["cell"], p["size"], p["proximity"], p["tau"], p["tau_p"],
                     p["window_p"], p["score"], "DECLINED"))
            p["verifier3"] = "DECLINED"
            rows.append(p)
            continue
        run = verifier3.verify_solution(inst, sol, cell=p["cell"], size=p["size"],
                                        proximity=p["proximity"])
        v = run.verdict()
        c26 = len([f for f in run.violations if f.cls.startswith("C26")])
        for k, n in run.checks_run.items():
            cls_tot[k] = cls_tot.get(k, 0) + n
        path = os.path.join(OUT, "s25_%s_n%d.json" % (p["cell"], p["size"]))
        sol["_proximity"] = p["proximity"]
        json.dump(stamped(sol, __file__), open(path, "w"), default=str)
        p.update(verifier3=v, checks=run.total_checks, violations=len(run.violations),
                 c26=c26, artifact=os.path.relpath(path, ROOT))
        rows.append(p)
        if v != verifier3.ACCEPT:
            fails.append("%s/n%d -> %s (%d violations)" % (p["cell"], p["size"], v,
                                                           len(run.violations)))
        print("%-7s %5d %5s %6s %8.4f %7.3f %6.3f %-9s %6d %5d %4d"
              % (p["cell"], p["size"], p["proximity"], p["tau"], p["tau_p"], p["window_p"],
                 p["score"], v, run.total_checks, len(run.violations), c26))

    acc = sum(1 for r in rows if r.get("verifier3") == "ACCEPT")
    dec = sum(1 for r in rows if r.get("verifier3") == "DECLINED")
    io.open(os.path.join(OUT, "report.json"), "w", encoding="utf-8").write(
        json.dumps({"picks": rows, "class_evaluations": cls_tot}, indent=1, default=str))
    print()
    print("  ACCEPT %d | non-ACCEPT %d | greedy26 DECLINED %d   of %d"
          % (acc, len(rows) - acc - dec, dec, len(rows)))
    print("  evaluations added: %d over %d classes" % (sum(cls_tot.values()), len(cls_tot)))
    print()
    print("  classes this run exercised MOST (the targets it was selected for):")
    for k, v in sorted(cls_tot.items(), key=lambda x: -x[1])[:6]:
        print("     %-22s %6d" % (k, v))
    print()
    if fails:
        print("  NON-ACCEPT -- each is a candidate transcription finding and must be explained:")
        for f in fails:
            print("     " + f)
    else:
        print("  No disagreement found. THIS DOES NOT CONFIRM THE TRANSCRIPTION: these solutions")
        print("  were built by greedy26, which enforces the constraints AS I READ THEM, so a")
        print("  shared misreading would be invisible here. It bounds OVER-strictness on the")
        print("  cells where the constraints bind hardest -- which is the strongest thing a")
        print("  self-generated corpus can say.")
    print("  -> %s" % os.path.relpath(OUT, ROOT))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
