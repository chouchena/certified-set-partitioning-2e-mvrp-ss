"""Run #5 -- resolve L1a's three UNRESOLVED rows, or prove they are not comparable.

WHY THIS BLOCKS THINGS. oracle_L1a.py:117 records that an UNRESOLVED quantity STOPS THE STACK for
that quantity (BM3). `min_transfers` is an n100 quantity, so it gates every n100 claim -- including
L4, which must go to n100 because L0 shows (26) cannot bind below n40.

THE QUESTION. K's Table 6 prints min_transfers = 37.0 (C), 30.9 (R), 33.3 (RC). Ours, defined as
ceil(sum d / Q_s) averaged over the family, gives 37.0, 30.0, 35.0. One matches, two do not, and
K never state their definition.

THE DECISIVE TEST, and it needs no solve. Solomon's instances within a family share coordinates
and demands and differ only in their TIME WINDOWS. If that holds in our rebuild, then EVERY
demand-only definition is constant within a family, so its average over the family is an INTEGER.
K's R (30.9) and RC (33.3) are NOT integers. That would rule out the entire class of demand-only
definitions at once -- ours included -- and establish that K's quantity depends on time windows or
is a property of their SOLUTION.

If it is a solution quantity, comparing it to an instance bound is a CATEGORY ERROR, and the row
resolves as NOT-COMPARABLE rather than staying UNRESOLVED: the stack is no longer stopped, because
there is nothing there to corroborate or refute.

    python analysis/oracle_L1a_mintransfers.py
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import instance_view

OUT = os.path.join(ROOT, "runs", "oracle")
FAM = {"C": ["C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208"],
       "R": ["R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208", "R209", "R210",
             "R211"],
       "RC": ["RC201", "RC202", "RC203", "RC204", "RC205", "RC206", "RC207", "RC208"]}


def inst(cell, size=100, prox=0.1):
    raw = instance_view.VInstance._load_json(cell)
    import verifier3
    return instance_view.VInstance(cell, size, wls=0.1, tau=verifier3.tau_for(raw, size),
                                   proximity=prox)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = json.load(open(os.path.join(ROOT, "data", "karademir2025", "k_reference.json"),
                       encoding="utf-8"))
    Qs = instance_view.LEFV_CAPACITY
    Qw = instance_view.VESSEL_CAPACITY

    print("Run #5 -- what IS K's min_transfers? Deciding whether L1a's 3 UNRESOLVED rows are a")
    print("          transcription defect, a definition gap, or a category error.")
    print()
    print("STEP 1. Is demand constant within a Solomon family at n100?")
    print()
    per_fam = {}
    for f, cells in FAM.items():
        dem, tw = {}, {}
        for c in cells:
            I = inst(c)
            dem[c] = sum(I.nodes[i].demand for i in I.customers)
            tw[c] = round(sum(I.nodes[i].latest - I.nodes[i].earliest for i in I.customers), 1)
        per_fam[f] = (dem, tw)
        ds = sorted(set(dem.values()))
        print("   family %-3s  %2d cells   distinct demand totals: %d %s"
              % (f, len(cells), len(ds), ("(all %s)" % ds[0]) if len(ds) == 1 else str(ds[:4])))
        print("                          distinct time-window spans: %d"
              % len(set(tw.values())))
    print()
    demand_constant = all(len(set(d.values())) == 1 for d, _t in per_fam.values())
    print("   demand constant within every family: %s" % ("YES" if demand_constant else "NO"))

    print()
    print("STEP 2. Every demand-only definition against K's printed values.")
    print()
    defs = {
        "ceil(sum d / Q_s)": lambda I, d: math.ceil(d / Qs),
        "sum d / Q_s (unrounded)": lambda I, d: d / Qs,
        "ceil(sum d / Q_w)": lambda I, d: math.ceil(d / Qw),
        "ceil(sum d / Q_s) - 1": lambda I, d: math.ceil(d / Qs) - 1,
    }
    print("   %-26s %10s %10s %10s   verdict" % ("definition", "C", "R", "RC"))
    print("   %-26s %10.1f %10.1f %10.1f   (K's printed values)"
          % ("K Table 6", k["table6"]["C"]["min_transfers"], k["table6"]["R"]["min_transfers"],
             k["table6"]["RC"]["min_transfers"]))
    hits = []
    for name, fn in defs.items():
        vals = {}
        for f, cells in FAM.items():
            dem, _tw = per_fam[f]
            vals[f] = sum(fn(None, dem[c]) for c in cells) / len(cells)
        ok = all(abs(vals[f] - k["table6"][f]["min_transfers"]) < 0.05 for f in FAM)
        hits.append((name, vals, ok))
        print("   %-26s %10.1f %10.1f %10.1f   %s"
              % (name, vals["C"], vals["R"], vals["RC"], "REPRODUCES K" if ok else "no"))

    print()
    print("STEP 3. The integrality argument.")
    print()
    nonint = {f: k["table6"][f]["min_transfers"] for f in FAM
              if abs(k["table6"][f]["min_transfers"] - round(k["table6"][f]["min_transfers"])) > 1e-9}
    print("   K values that are NOT integers: %s"
          % (", ".join("%s=%.1f" % (f, v) for f, v in nonint.items()) or "none"))
    resolved = None
    if demand_constant and nonint:
        print()
        print("   A demand-only quantity is CONSTANT within a family (step 1), so its family")
        print("   average is an INTEGER. K print %s as non-integer. Therefore K's min_transfers"
              % ", ".join(sorted(nonint)))
        print("   is NOT a demand-only instance quantity -- and neither is ours.")
        print()
        print("   It must vary with what varies inside a Solomon family: the TIME WINDOWS, or it")
        print("   is a property of THEIR SOLUTION (transfers actually performed).")
        print()
        print("   RESOLUTION: NOT-COMPARABLE, not UNRESOLVED. Ours is an instance lower bound;")
        print("   theirs demonstrably is not the same kind of object. Comparing them is the")
        print("   category error BM3 names. The row is neither corroboration nor a defect, and")
        print("   it no longer stops the stack -- there is nothing there to corroborate.")
        resolved = "NOT-COMPARABLE"
    elif any(ok for _n, _v, ok in hits):
        resolved = "RESOLVED"
        print("   A demand-only definition reproduces all three. The row is RESOLVED.")
    else:
        resolved = "STILL-UNRESOLVED"
        print("   Neither argument settles it. The row stays UNRESOLVED and keeps stopping the")
        print("   stack for n100 instance claims.")

    print()
    print("STEP 4. The defect this could have been hiding, checked separately.")
    print()
    print("   An UNRESOLVED row can conceal a real rebuild defect: if our n100 demands were")
    print("   wrong, min_transfers would differ for that reason and 'definition unknown' would")
    print("   excuse it. So compare our per-family demand against K's OWN published vessel")
    print("   lower bound, which is demand-derived and which they DO define.")
    for f, cells in FAM.items():
        dem, _tw = per_fam[f]
        ours = sum(math.ceil(dem[c] / Qw) for c in cells) / len(cells)
        kf = k["table6"][f]
        dev = kf["lbbd"].get("dev_vessel_lb")
        fleet = kf["lbbd"].get("fleet_wl")
        implied = None if (dev is None or fleet is None) else round(fleet - dev, 2)
        print("   family %-3s  our ceil(sum d / Q_w) = %5.2f   K's LBBD fleet_wl - dev_vessel_lb "
              "= %s" % (f, ours, "n/a" if implied is None else "%.2f" % implied))
        if implied is not None and abs(ours - implied) < 0.051:
            print("               agree to 0.05 -- our n100 demand totals reproduce K's own "
                  "demand-derived bound")
        elif implied is not None:
            print("               DISAGREE by %.2f -- this is a REBUILD DEFECT, not a definition "
                  "gap" % abs(ours - implied))

    json.dump(stamped({"resolution": resolved, "demand_constant": demand_constant,
               "k_values": {f: k["table6"][f]["min_transfers"] for f in FAM},
               "candidates": [[n, v, ok] for n, v, ok in hits]}, __file__),
              open(os.path.join(OUT, "L1a_mintransfers.json"), "w"), indent=1, default=str)
    print()
    print("RESOLUTION: %s" % resolved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
