"""L1a of the transcription oracle: instance checks that need NO solve.

Design: DESIGN_transcription_oracle_v4.md.

Every quantity here is INSTANCE-DERIVED and published by K, so it tests the rebuild --
instance_view.py, itself a transcription of their generator -- without touching the constraint
transcription at all. That separation is the point: AM1 found that z* depends on four
transcriptions and v1 blamed only one.

UNRESOLVED IS A FIRST-CLASS OUTCOME (BM3). Where I do not know what a published quantity DENOTES,
the row is UNRESOLVED and STOPS the stack for that quantity. It is not a pass. Treating an
ambiguous published number as agreement would be the same error this whole exercise exists to
avoid.

    python analysis/oracle_L1a.py
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
import verifier3

FAM = {"C": ["C20%d" % i for i in range(1, 9)],
       "R": ["R2%02d" % i for i in range(1, 12)],
       "RC": ["RC20%d" % i for i in range(1, 9)]}
OUT = os.path.join(ROOT, "runs", "oracle")


def inst(cell, size, prox):
    raw = instance_view.VInstance._load_json(cell)
    return instance_view.VInstance(cell, size, wls=0.1,
                                   tau=verifier3.tau_for(raw, size), proximity=prox)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    k = json.load(open(os.path.join(ROOT, "data", "karademir2025", "k_reference.json"),
                       encoding="utf-8"))
    tf = k["text_facts"]
    rows = []

    print("L1a -- INSTANCE CHECKS, NO SOLVE. Tests the rebuild, not the constraints.")
    print()
    print("%-38s %-22s %-22s %s" % ("quantity", "ours", "K publishes", "verdict"))
    print("-" * 104)

    def emit(q, ours, kv, verdict, note=""):
        rows.append(dict(quantity=q, ours=str(ours), k=str(kv), verdict=verdict, note=note))
        print("%-38s %-22s %-22s %s%s" % (q[:38], str(ours)[:22], str(kv)[:22], verdict,
                                          ("   " + note) if note else ""))

    # --- scalar settings -------------------------------------------------------------
    emit("satellites |P|", len(inst("C201", 20, 0.0).satellites), tf["satellites"],
         "PASS" if len(inst("C201", 20, 0.0).satellites) == tf["satellites"] else "FAIL")
    emit("LEFV capacity Q_s", instance_view.LEFV_CAPACITY, tf["lefv_capacity"],
         "PASS" if instance_view.LEFV_CAPACITY == tf["lefv_capacity"] else "FAIL")
    emit("vessel capacity Q_w", instance_view.VESSEL_CAPACITY, tf["vessel_capacity"],
         "PASS" if instance_view.VESSEL_CAPACITY == tf["vessel_capacity"] else "FAIL")

    # tau rule: ceil(2 * mean customer service)
    okt = True
    for f, cells in FAM.items():
        for c in cells[:2]:
            raw = instance_view.VInstance._load_json(c)
            svc = [raw["customer_%d" % i]["service_time"] for i in range(1, 21)]
            okt &= (verifier3.tau_for(raw, 20) == math.ceil(2.0 * sum(svc) / len(svc)))
    emit("tau rule", "ceil(2 x mean service)", tf["tau_rule"], "PASS" if okt else "FAIL")

    # --- vessel lower bound, n50, per family (Fig. 4 text) ---------------------------
    pub = tf.get("fig4", {}).get("vessel_lower_bound_by_family")
    if pub:
        allok = True
        for f, cells in FAM.items():
            vals = [math.ceil(sum(inst(c, 50, 0.1).nodes[i].demand
                                  for i in inst(c, 50, 0.1).customers)
                              / instance_view.VESSEL_CAPACITY) for c in cells]
            mean = sum(vals) / len(vals)
            good = abs(mean - pub[f]) < 1e-9
            allok &= good
            emit("vessel LB n50, family %s" % f, "%.2f" % mean, pub[f],
                 "PASS" if good else "FAIL")
        rows.append(dict(quantity="vessel LB overall", verdict="PASS" if allok else "FAIL"))

    # --- min transfers, n100 (Table 6) -- DEFINITION UNKNOWN --------------------------
    for f, cells in FAM.items():
        mt = k["table6"][f].get("min_transfers")
        ours = sum(math.ceil(sum(inst(c, 100, 0.1).nodes[i].demand
                                 for i in inst(c, 100, 0.1).customers)
                             / instance_view.LEFV_CAPACITY) for c in cells) / len(cells)
        emit("min transfers n100, family %s" % f, "%.1f" % ours, mt, "UNRESOLVED",
             "their definition is not stated")

    # --- proximity per exhibit -------------------------------------------------------
    px = tf["proximity"]
    emit("proximity, Table 3 / 4 / 6", "0.0 / 0.0 / 0.1",
         "%s / %s / %s" % (px["table3"], px["table4"], px["table6"]),
         "PASS" if (px["table3"], px["table4"], px["table6"]) == (0.0, 0.0, 0.1) else "FAIL")

    npass = sum(1 for r in rows if r.get("verdict") == "PASS")
    nfail = sum(1 for r in rows if r.get("verdict") == "FAIL")
    nunres = sum(1 for r in rows if r.get("verdict") == "UNRESOLVED")
    print()
    print("  PASS %d | FAIL %d | UNRESOLVED %d" % (npass, nfail, nunres))
    print()
    if nfail:
        print("  L1a FAILS -- the instance rebuild differs from K's published settings.")
        print("  STOP: nothing below L1 is attributable.")
    elif nunres:
        print("  L1a PASSES on every resolvable quantity, with %d UNRESOLVED." % nunres)
        print("  UNRESOLVED STOPS THE STACK FOR THAT QUANTITY (BM3): K's min_transfers may be")
        print("  ceil(demand/Q_s) or a SOLUTION quantity, and the table does not say. Comparing")
        print("  an instance bound to a solution quantity would be a category error. The row is")
        print("  neither corroboration nor a defect until the definition is read from the")
        print("  article. It does NOT block L1b or L3, which do not depend on it.")
    else:
        print("  L1a PASSES outright.")
    print()
    print("  SCOPE: L1a tests DEMAND, CAPACITY and SETTINGS. It does NOT touch the distance")
    print("  matrix -- that was BM1, and it is L1b's job.")
    json.dump(stamped({"rows": rows}, __file__), open(os.path.join(OUT, "L1a.json"), "w"),
              indent=1, default=str)
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
