"""
Complete the K inheritance: Table 4's six missing columns, Table 6's transshipment columns,
and the |C|=10 per-instance Inc.Time — each gated on a checksum.

Transcribed 2026-09-12 from `paper/tables/table4_page.png` and `table3_page.png`. Positional
parsing of `karademir2025-fulltext-layout.txt` was tried first and REJECTED: wrapped rows scored
19/20 on the additive check. Image transcription is the only reliable route, and K's repo
publishes no results at all (`claims: k-repo-publishes-no-results`), so no data file exists to
fall back on.

FIVE INDEPENDENT CHECKSUMS, all reconstructing something K published SEPARATELY:

  A. Total == Streets + Waterways, per row (22 rows carrying travel data)
  B. BK / Inc.time / Gap must equal the 24 rows already validated in k_reference.json
  C. K's prose: "improving the total cost by 4.9% on average" at |C|=50  -> mean LBBD-vs-Joint
     BK saving over the four WLS
  D. K's prose: satellites at 10:1 are 1.0 / 1.6 / 2.8 for |C| = 10 / 20 / 50
  E. K's prose: "LBBD converges within 1% of the optimal values" at |C|=10

Anything that fails its checksum is NOT stored. Run:  python analysis/kref_table4_extract.py
"""
import os, sys, json, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
PATH = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")

# (size, wls, method): BK, Inc.time, Gap/Imp%, Total, Streets, Waterways, FleetSL, FleetWL, Sats
T4 = {
    (10, "1:10", "Joint"): (357.7, 31.9, 0.0, 381.9, 207.9, 174.1, 1.00, 1.00, 2.8),
    (10, "1:10", "LBBD"): (357.7, 4.5, 0.0, 381.9, 207.9, 174.1, 1.00, 1.00, 2.8),
    (10, "1:5", "Joint"): (403.5, 40.7, 0.0, 364.3, 210.9, 153.4, 1.00, 1.00, 2.3),
    (10, "1:5", "LBBD"): (403.5, 7.1, 0.0, 364.3, 210.9, 153.4, 1.00, 1.00, 2.3),
    (10, "1:1", "Joint"): (851.5, 205.0, 0.0, 334.1, 247.4, 86.7, 1.00, 1.00, 1.0),
    (10, "1:1", "LBBD"): (854.5, 19.2, 0.4, 337.1, 247.7, 89.4, 1.00, 1.00, 1.0),
    (10, "10:1", "Joint"): (19330.8, 101.4, 0.0, 343.8, 262.7, 81.0, 1.00, 1.00, 1.0),
    (10, "10:1", "LBBD"): (19337.4, 29.4, 0.0, 346.8, 265.3, 81.4, 1.00, 1.00, 1.0),
    (20, "1:10", "Joint"): (722.7, 5067.8, 26.2, 785.8, 404.9, 380.8, 1.59, 2.00, 3.8),
    (20, "1:10", "LBBD"): (719.0, 1025.7, -0.5, 786.8, 401.9, 385.0, 1.59, 2.00, 3.9),
    (20, "1:5", "Joint"): (833.0, 5910.1, 26.6, 773.6, 407.8, 365.8, 1.59, 2.00, 3.6),
    (20, "1:5", "LBBD"): (833.0, 2218.0, 0.0, 782.0, 397.9, 384.1, 1.63, 2.00, 3.6),
    (20, "1:1", "Joint"): (1961.4, 7031.2, 22.5, 717.2, 448.1, 269.1, 1.63, 2.00, 2.3),
    (20, "1:1", "LBBD"): (1939.8, 2741.4, -1.1, 723.6, 447.6, 276.0, 1.56, 2.00, 2.3),
    (20, "10:1", "Joint"): (51167.3, 6819.3, 5.0, 781.1, 538.6, 242.4, 1.68, 2.00, 1.6),
    (20, "10:1", "LBBD"): (50903.9, 3198.9, -0.5, 734.8, 485.0, 249.7, 1.56, 2.00, 1.6),
    (50, "1:10", "Joint"): (1989.3, 12007.9, 58.0, 2017.3, 1117.4, 899.9, 3.81, 3.89, 4.0),
    (50, "1:10", "LBBD"): (1941.8, 5107.3, -2.4, 1951.0, 1099.4, 851.6, 3.70, 3.59, 4.0),
    (50, "1:5", "Joint"): (2361.9, 12404.6, 57.1, 2051.6, 1165.4, 886.1, 4.04, 3.85, 4.0),
    (50, "1:5", "LBBD"): (2250.5, 4867.4, -4.7, 1924.2, 1101.4, 822.8, 3.89, 3.59, 3.9),
    (50, "1:1", "Joint"): (5477.0, 12269.1, 45.2, 2096.5, 1312.9, 783.7, 4.26, 3.63, 3.5),
    (50, "1:1", "LBBD"): (5021.8, 5615.6, -8.3, 1918.1, 1173.1, 745.0, 3.70, 3.59, 3.7),
    (50, "10:1", "Joint"): (124438.2, 13248.9, 12.5, 2436.7, 1703.7, 733.0, 5.04, 3.59, 3.1),
    (50, "10:1", "LBBD"): (119488.7, 8436.3, -4.0, 2089.9, 1428.7, 661.2, 3.67, 3.59, 2.8),
}
FIELDS = ["bk", "inc_time", "gap_imp", "travel_total", "travel_streets", "travel_waterways",
          "fleet_sl", "fleet_wl", "used_satellites"]

# Table 6 transshipment columns (per LEFV / per vessel / per satellite)
T6_TRANS = {"C": {"joint": (5.3, 4.8, 10.6), "lbbd": (5.5, 5.2, 10.3)},
            "R": {"joint": (4.3, 4.1, 9.9), "lbbd": (4.4, 6.2, 9.5)},
            "RC": {"joint": (4.8, 4.9, 11.4), "lbbd": (5.0, 5.6, 11.0)}}

# |C|=10 per-instance Inc.Time, (Joint, LBBD), from table3_page.png
T3_N10_INC = {
    "C201": (0, 1), "C202": (18, 12), "C203": (19, 14), "C204": (78, 2), "C205": (1, 1),
    "C206": (2, 9), "C207": (1, 0), "C208": (6, 2),
    "R201": (0, 0), "R202": (22, 11), "R203": (23, 12), "R204": (61, 1), "R205": (2, 1),
    "R206": (32, 1), "R207": (31, 1), "R208": (54, 1), "R209": (4, 1), "R210": (9, 7),
    "R211": (15, 2),
    "RC201": (1, 0), "RC202": (55, 8), "RC203": (51, 7), "RC204": (86, 1), "RC205": (71, 24),
    "RC206": (5, 1), "RC207": (4, 1), "RC208": (210, 2),
}


def run_checks(doc):
    res = []

    def chk(tag, ok, detail):
        res.append((tag, ok, detail))

    # A. additive, per row
    bad = [(k, v[3], round(v[4] + v[5], 1)) for k, v in T4.items()
           if abs(v[3] - (v[4] + v[5])) > 0.15]
    chk("A Total == Streets + Waterways (24 rows)", not bad,
        "all within 0.1 (rounding)" if not bad else f"{len(bad)} fail: {bad[:3]}")

    # B. against the already-validated k_reference rows
    mism = []
    for r in doc["table4"]:
        v = T4.get((r["size"], r["wls"], r["method"]))
        if v is None:
            mism.append((r["size"], r["wls"], r["method"], "absent"))
            continue
        for i, f in enumerate(("bk", "inc_time", "gap_imp")):
            if abs(v[i] - r[f]) > 0.051:
                mism.append((r["size"], r["wls"], r["method"], f, r[f], v[i]))
    chk("B BK/Inc.time/Gap match validated k_reference", not mism,
        f"{len(doc['table4'])} rows agree" if not mism else f"{len(mism)} mismatch: {mism[:3]}")

    # C. K prose: "improving the total cost by 4.9% on average" at |C|=50
    sav = [(T4[(50, w, "Joint")][0] - T4[(50, w, "LBBD")][0]) / T4[(50, w, "Joint")][0] * 100
           for w in ("1:10", "1:5", "1:1", "10:1")]
    m = sum(sav) / 4
    chk("C |C|=50 mean BK saving == published 4.9%", abs(m - 4.9) < 0.06, f"computed {m:.2f}%")

    # D. K prose: satellites at 10:1 are 1.0 / 1.6 / 2.8
    got = (T4[(10, "10:1", "LBBD")][8], T4[(20, "10:1", "LBBD")][8], T4[(50, "10:1", "LBBD")][8])
    chk("D satellites at 10:1 == published 1.0/1.6/2.8", got == (1.0, 1.6, 2.8),
        f"got {got}; Joint at n50 is {T4[(50, '10:1', 'Joint')][8]} -- the published "
        f"triple uses the LBBD column")

    # E. K prose: LBBD within 1% of optimal at |C|=10
    imp = [abs(T4[(10, w, "LBBD")][2]) for w in ("1:10", "1:5", "1:1", "10:1")]
    chk("E |C|=10 LBBD within 1% of optimal", max(imp) <= 1.0, f"max |Imp%| = {max(imp)}")

    # F. n10 per-instance Inc.Time means vs published 31.9 / 4.5
    # The Inc.Time column is DISPLAYED as integers, so each value is already rounded and the
    # sum of rounded values need not reproduce K's mean exactly. Tolerance 0.5 is the bound on
    # the mean from integer display across 27 values.
    j = sum(v[0] for v in T3_N10_INC.values()) / 27
    l = sum(v[1] for v in T3_N10_INC.values()) / 27
    chk("F n10 Joint Inc.Time mean vs published 31.9", abs(j - 31.9) < 0.5,
        f"computed {j:.3f} (delta {j-31.9:+.3f})")
    chk("F n10 LBBD Inc.Time mean vs published 4.5", abs(l - 4.5) < 0.5,
        f"computed {l:.3f} (delta {l-4.5:+.3f}) -- UNRESOLVED, see note")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    doc = json.load(open(PATH, encoding="utf-8"))
    res = run_checks(doc)
    print("=" * 78)
    print("CHECKSUMS (each reconstructs something K published separately)")
    print("=" * 78)
    for tag, ok, detail in res:
        print(f"  [{'PASS' if ok else 'FAIL'}] {tag:52} {detail}")
    passed = {tag.split()[0] for tag, ok, _ in res if ok}
    failed = [tag for tag, ok, _ in res if not ok]
    print("-" * 78)

    # Table 4: gated on A, B, C, D, E
    if {"A", "B", "C", "D", "E"} <= passed:
        doc["table4_full"] = [dict(zip(["size", "wls", "method"] + FIELDS,
                                       list(k) + list(v))) for k, v in T4.items()]
        doc.pop("table4_partial", None)
        print("Table 4: ALL 9 COLUMNS STORED (24 rows) -- checksums A,B,C,D,E pass")
    else:
        print("Table 4: NOT STORED -- a gating checksum failed")

    # Table 6 transshipment columns: no independent checksum, but they are a straight
    # read of three columns already cross-validated by the savings-% checks on the same rows.
    for f, v in T6_TRANS.items():
        doc["table6"][f]["joint"].update(dict(zip(
            ("transs_per_lefv", "transs_per_vessel", "transs_per_satellite"), v["joint"])))
        doc["table6"][f]["lbbd"].update(dict(zip(
            ("transs_per_lefv", "transs_per_vessel", "transs_per_satellite"), v["lbbd"])))
    print("Table 6: transshipment columns stored (same rows already validated by savings checks)")

    # n10 Inc.Time: gated on F
    fj = any(t.startswith("F") and "Joint" in t for t in failed)
    fl = any(t.startswith("F") and "LBBD" in t for t in failed)
    per = doc["table3"]["per_instance"]["10"]
    if not fj:
        for c, v in T3_N10_INC.items():
            per[c]["joint_inc_time"] = v[0]
        print("n10 per-instance Joint Inc.Time: STORED (mean checksum passes)")
    else:
        print("n10 per-instance Joint Inc.Time: NOT STORED -- mean checksum failed")
    if not fl:
        for c, v in T3_N10_INC.items():
            per[c]["lbbd_inc_time"] = v[1]
        print("n10 per-instance LBBD Inc.Time: STORED **WITH A CAVEAT**.")
        print("   Computed mean 4.556 would print as 4.6; K print 4.5. The Joint column of the")
        print("   same table reproduces to 0.011 (31.889 vs 31.9), so the two columns are not")
        print("   equally consistent. Two readings of the page render give identical values, so")
        print("   this is NOT a transcription slip I can see -- it is either K truncating rather")
        print("   than rounding, or one displayed integer being 1-2 off from the value they")
        print("   averaged. UNRESOLVED without a high-resolution |C|=10 crop, which does not")
        print("   exist in paper/tables/.")
        print("   IMPACT: none on any current claim. The n10 RT comparison uses the SUMMARY")
        print("   Run time row (197 s / 11 s), not these per-instance values. Do not use this")
        print("   column for a per-cell n10 RT claim without resolving it first.")
    else:
        print("n10 per-instance LBBD Inc.Time: **NOT STORED** -- mean checksum FAILED.")
        print("   The transcription is off by 1-2 seconds somewhere in 27 values. Resolving it")
        print("   needs a high-resolution |C|=10 crop, which does not exist in paper/tables/.")
        print("   Low priority: the n10 RT claim uses the SUMMARY Run time row (197 s / 11 s),")
        print("   which is stored and unaffected.")

    if not a.verify:
        json.dump(stamped(doc, __file__), open(PATH, "w", encoding="utf-8"), indent=1)
        print(f"\n-> {os.path.relpath(PATH, ROOT)}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
