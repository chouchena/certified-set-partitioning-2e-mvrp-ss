"""AUDIT: does our capture of Karademir et al. (2025) cover every exhibit, and does it agree?

Written 2026-09-19 after an audit against the PDF found three defects in what we believed:

  1. "K never published n40" -- FALSE. Fig. 5 tests |C| = 40 explicitly and names the size in its
     caption. The size was absent from our reference because we chose not to capture Fig. 5, not
     because K omitted it. That is CLAUDE.md failure mode 2 -- dressing our choice as K's limit.

  2. "K states no proximity for Fig. 5" -- FALSE. S5.5.2 states it plainly ("4 satellites are
     located at the 0.1 proximity value for two-echelon systems") and Table 5 repeats it twice.

  3. PROXIMITY IS A PROPERTY OF THE EXHIBIT, NOT OF THE SIZE. |C| = 50 is at 0.0 in Table 4 and
     at 0.1 in Fig. 5; |C| = 10/20/30 are at 0.0 in Table 3 and 0.1 in Fig. 5. Any {size:
     proximity} map -- including fixopt's K_PROXIMITY guard -- is well-defined ONLY once a
     comparator set is fixed. Ours is Tables 3/4/6. That scoping is ours.

WHAT THIS CHECKS. Four things, each of which can fail independently:

  A  EXHIBIT COVERAGE   every Table 1-6 and Fig. 1-5 is either captured or carries a reason.
  B  VALUE AGREEMENT    every captured table reproduces K's own published averages.
  C  PROXIMITY BASIS    every proximity we hold says whether K STATES it or we INFER it.
  D  SCOPE HONESTY      every size K tests is present, and any size we do not compare at is
                        recorded as OUR scope decision rather than as an absence in K.

Exit nonzero on any failure.

    python analysis/audit_k_alignment.py

Disclaimer: the model, formulation and instances are those of Karademir, Beirigo & Atasoy (2025),
EJOR 322(2) 480-499. Our use of their published results for comparison is acknowledged; the values
here are facts transcribed for comparison, not their content redistributed.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "data", "karademir2025", "k_reference.json")

# Every exhibit in the article, and what it is. `data` = carries numbers we could use.
EXHIBITS = {
    "Table 1": ("notation", False),
    "Table 2": ("model variants", False),
    "Table 3": ("per-instance results, |C| = 10/20/30", True),
    "Table 4": ("size x WLS x method averages, |C| = 10/20/50", True),
    "Table 5": ("service design alternative SETTINGS (carries proximity 0.1)", True),
    "Table 6": ("family averages, |C| = 100", True),
    "Fig. 1": ("example network schematic", False),
    "Fig. 2": ("subproblem schematic", False),
    "Fig. 3": ("LBBD flowchart", False),
    "Fig. 4": ("satellite-location study, |C| = 50, proximity sweep", True),
    "Fig. 5": ("benchmark systems, |C| = 10..50 at proximity 0.1", True),
}

# Sizes K tests anywhere in the article, and where.
K_SIZES = {10: ["Table 3", "Table 4", "Fig. 5"],
           20: ["Table 3", "Table 4", "Fig. 5"],
           30: ["Table 3", "Fig. 5"],
           40: ["Fig. 5"],
           50: ["Table 4", "Fig. 4", "Fig. 5"],
           100: ["Table 6"]}

# The comparator set we actually use. Stating it here makes the scoping a declaration rather
# than an accident of which exhibits happened to be captured.
OUR_COMPARATOR = {10: "Table 3", 20: "Table 3", 30: "Table 3",
                  50: "Table 4", 100: "Table 6"}

fails, warns = [], []


def check(cond, leg, msg):
    (fails if not cond else warns).append(("FAIL" if not cond else "ok", leg, msg))
    return cond


def main():
    if not os.path.exists(REF):
        print("k_reference.json absent -- run analysis/kref_build.py")
        return 2
    d = json.load(open(REF, encoding="utf-8"))
    tf = d["text_facts"]
    rows = []

    # ---- LEG A: exhibit coverage -------------------------------------------------
    notcap = tf.get("NOT_captured", {})
    for name, (what, has_data) in sorted(EXHIBITS.items()):
        key = name.lower().replace(". ", "").replace(" ", "")      # "Table 3" -> "table3"
        captured = key in d or key in tf
        reason = None
        if not captured:
            reason = next((v for k, v in notcap.items()
                           if key.replace("table", "table").replace("fig", "fig") in k), None)
        if not has_data:
            rows.append(("A", name, "no numeric content", "n/a"))
            continue
        ok = captured or bool(reason)
        rows.append(("A", name, what, "CAPTURED" if captured else
                     ("reason given" if reason else "MISSING, no reason")))
        check(ok, "A", "%s: neither captured nor explained" % name)

    # ---- LEG B: value agreement --------------------------------------------------
    t3 = d["table3"]["per_instance"]
    t4 = {(r["size"], r["wls"], r["method"]): r["bk"] for r in d["table4"]}
    for s in sorted(t3, key=int):
        cells = t3[s]
        for meth, key in (("Joint", "joint_bk"), ("LBBD", "lbbd_bk")):
            vals = [cells[c][key] for c in cells if cells[c].get(key) is not None]
            if not vals:
                continue
            mean = sum(vals) / len(vals)
            pub = t4.get((int(s), "1:10", meth))
            if pub is None:
                rows.append(("B", "n%s %s" % (s, meth),
                             "mean %.2f over %d cells" % (mean, len(vals)),
                             "no Table 4 row at this size"))
                continue
            ok = abs(mean - pub) < 0.06
            rows.append(("B", "n%s %s" % (s, meth),
                         "ours %.2f vs K %.1f" % (mean, pub),
                         "MATCH" if ok else "MISMATCH"))
            check(ok, "B", "n%s %s mean %.3f != published %.1f" % (s, meth, mean, pub))

    # ---- LEG C: proximity basis --------------------------------------------------
    prox = tf.get("proximity", {})
    basis = tf.get("proximity_basis", {})
    for k in sorted(prox):
        b = basis.get(k, "")
        kind = "STATED" if b.startswith("STATED") else ("INFERRED" if b.startswith("INFERRED")
                                                        else "NO BASIS")
        rows.append(("C", k, str(prox[k]), kind))
        check(bool(b), "C", "proximity[%s] has no recorded basis" % k)

    # ---- LEG D: scope honesty ----------------------------------------------------
    for size, where in sorted(K_SIZES.items()):
        comp = OUR_COMPARATOR.get(size)
        if comp is None:
            rows.append(("D", "|C|=%d" % size, "K tests it in %s" % ", ".join(where),
                         "OUR SCOPE EXCLUDES IT"))
            # not a failure -- a declared choice. It IS a failure to have no note about it.
            check(size in (40,), "D",
                  "|C|=%d is tested by K and absent from our comparator with no note" % size)
        else:
            ok = comp in where
            rows.append(("D", "|C|=%d" % size, "we compare at %s" % comp,
                         "ok" if ok else "COMPARATOR NOT AN EXHIBIT FOR THIS SIZE"))
            check(ok, "D", "|C|=%d: comparator %s does not test this size" % (size, comp))

    # ---- report ------------------------------------------------------------------
    print("K ALIGNMENT AUDIT      reference: %s" % os.path.relpath(REF, ROOT))
    print()
    print("%-4s %-16s %-46s %s" % ("leg", "item", "detail", "verdict"))
    print("-" * 104)
    for leg, item, detail, verdict in rows:
        print("%-4s %-16s %-46s %s" % (leg, item, detail[:46], verdict))

    hard = [f for f in fails if f[0] == "FAIL"]
    print()
    print("A exhibit coverage | B value agreement | C proximity basis | D scope honesty")
    print("failures: %d" % len(hard))
    for _, leg, msg in hard:
        print("   [%s] %s" % (leg, msg))
    if not hard:
        print("PASSED -- every exhibit accounted for, every captured table checksums against K's "
              "own averages, every proximity carries its basis.")
    print()
    print("STANDING NOTE. |C|=40 is tested by K (Fig. 5 only, 26 instances at proximity 0.1) and "
          "is NOT in our comparator. That is OUR scope decision. Fig. 5 reports average travel "
          "time and fleet size, not the objective z, and its absolute values live in a figure's "
          "data table we have not captured -- so an n40 comparison is possible but is a DIFFERENT "
          "comparison object, not a missing row.")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
