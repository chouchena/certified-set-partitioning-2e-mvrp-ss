"""What does K actually publish? Query this instead of recalling it.

WHY THIS EXISTS. The recurring failure in this project is not failing to read the sources -- it is
reading them and then answering from reconstruction. On 2026-09-20 the RT granularity table in
RT_LEG_DESIGN.md was read, and in the SAME reply |C| = 50 was described as having no published
timing. Table 4 reports pooled inc_time at 10, 20 and 50, and the table that says so had just
been quoted. Earlier the same day two L4 rows were misattributed by reading a streamed log
instead of the JSONL, and a commit message claimed a patch that had silently failed.

Every existing gate checks DOCUMENTS and CODE. None checks a claim made in conversation. This is
the smallest thing that closes that: one command that prints what K publish, so the answer comes
from k_reference.json rather than from memory.

    python analysis/k_says.py                 # the whole coverage matrix
    python analysis/k_says.py timing          # what timing exists, at what granularity
    python analysis/k_says.py proximity       # which proximity belongs to which exhibit
    python analysis/k_says.py 50              # everything published at |C| = 50
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")


def load():
    return json.load(open(REF, encoding="utf-8"))


def coverage(k):
    """Per size: what K publish, and at what granularity."""
    rows = []
    pi = k["table3"]["per_instance"]
    for s in ("10", "20", "30"):
        if s in pi:
            n = len(pi[s])
            prov = sum(1 for d in pi[s].values() if d.get("joint_gap") == 0.0)
            rows.append((int(s), "Table 3", "PER-INSTANCE", "%d cells, %d proven optimal" % (n, prov),
                         "joint_bk, joint_gap, joint_inc_time, lbbd_*"))
    t4 = k.get("table4_full") or []
    for r in t4:
        if r.get("wls") == "1:10":
            rows.append((r["size"], "Table 4", "POOLED over 27",
                         "%s: bk %.1f" % (r["method"], r["bk"]),
                         "bk, inc_time %s, gap_imp, travel_*, fleet_*" % r.get("inc_time")))
    for fam, d in k.get("table6", {}).items():
        rows.append((100, "Table 6", "FAMILY MEAN (%s, %d cells)" % (fam, d.get("n", 0)),
                     "joint zIP %.1f, gap %.1f%%" % (d["joint"]["zIP"], d["gap_joint"]),
                     "zIP, travel_*, fleet_*, dev_vessel_lb, min_transfers -- NO TIMING"))
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = load()
    q = (sys.argv[1].lower() if len(sys.argv) > 1 else "")

    if q in ("", "all", "coverage"):
        print("WHAT K PUBLISH, by size and granularity")
        print()
        print("  %5s %-9s %-26s %-34s" % ("size", "exhibit", "granularity", "values"))
        for size, ex, gran, vals, _f in sorted(coverage(k)):
            print("  %5d %-9s %-26s %-34s" % (size, ex, gran, vals))
        print()
        print("  |C| = 40 appears ONLY in Fig. 5, which reports average travel time and fleet")
        print("  size -- NOT the objective. There is no per-cell objective at 40 or 100.")

    if q in ("", "all", "timing"):
        print()
        print("TIMING -- which comparisons are even possible")
        print()
        print("  %5s %-22s %-30s" % ("size", "metric", "granularity"))
        pi = k["table3"]["per_instance"]
        for s in sorted(pi, key=int):
            print("  %5s %-22s %-30s" % (s, "joint_inc_time", "PER-INSTANCE (Table 3)"))
        for r in (k.get("table4_full") or []):
            if r.get("wls") == "1:10":
                print("  %5d %-22s %-30s" % (r["size"], "inc_time = %s s" % r.get("inc_time"),
                                             "POOLED over 27 (Table 4, %s)" % r["method"]))
        print("  %5d %-22s %-30s" % (100, "NONE", "Table 6 carries no timing at all"))
        print()
        print("  K's stated time limit: %s s.   Hardware: %s"
              % (k["text_facts"].get("time_limit_s"), k["text_facts"].get("hardware")))
        print("  Their run time covers the BOUND AND THE INCUMBENT TOGETHER -- one exact method")
        print("  producing both. Any budget-matched comparison must account for that.")

    if q in ("", "all", "proximity", "prox"):
        print()
        print("PROXIMITY -- which value belongs to which exhibit")
        print()
        px = k["text_facts"]["proximity"]
        for ex in sorted(px):
            print("  %-12s %s" % (ex, px[ex]))
        basis = k["text_facts"].get("proximity_basis", {})
        for ex in sorted(basis):
            print("  %-12s basis: %s" % (ex, str(basis[ex])[:96]))

    if q.isdigit():
        size = int(q)
        print("EVERYTHING K PUBLISH AT |C| = %d" % size)
        print()
        hit = False
        for s2, ex, gran, vals, fields in sorted(coverage(k)):
            if s2 == size:
                hit = True
                print("  %-9s %-26s %s" % (ex, gran, vals))
                print("            fields: %s" % fields)
        if not hit:
            print("  NOTHING. K publish no results at this size.")
            print("  (|C| = 40 exists only in Fig. 5: average travel time and fleet size,")
            print("   not the objective, so no objective comparison is possible there.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
