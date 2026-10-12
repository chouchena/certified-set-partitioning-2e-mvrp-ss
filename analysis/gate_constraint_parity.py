"""G-PARITY: does the verifier have a counterpart for every constraint the model posts?

WHY THIS GATE EXISTS. verify2 deliberately checks PROBLEM constraints, never the model's own
rows: it recomputes street cost from the routing rather than reading arcStreetCost, and it tests
|u_i - u_j| >= tau rather than testing whether f_ij is large enough. That independence is the
whole value -- had it checked (27)-(30) it would have ACCEPTED every (26)-violating timetable,
because those rows accept them.

The price of that independence is a hole this gate closes. If the model posts a constraint with
no verifier counterpart, nothing detects it, because a missing check produces NO OUTPUT. It is not
a wrong answer, it is an absent question -- the same failure shape as the verifier that ran 433
times on the wrong object and reported ok=True.

The consolidation found `gate_constraint_parity.py` among seven gate scripts that were never
written at all, and every figure quoted about parity came from reading a listing rather than
running a program. This is that program.

WHAT IT CAN AND CANNOT DO, stated so the gate is not over-read:

  CAN  catch a posted constraint with NO declared counterpart (a hole)
  CAN  catch a declared counterpart that does not exist in verify2 (drift, a typo, a rename)
  CAN  catch a verify2 class that is neither mapped nor declared checker-only (an orphan)
  CAN  fail when someone adds a constraint to a builder and forgets the verifier

  CANNOT verify the counterpart checks the SAME THING. Semantic equivalence is a human judgment,
         and the MAPPING below is exactly that judgment written down where it can be reviewed and
         argued with, rather than left implicit in two files that never mention each other.

So a PASS means "every posted constraint has a named checker and every named checker exists". It
does NOT mean "the verifier is complete". The mapping is the claim; the gate keeps it honest.

    python analysis/gate_constraint_parity.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDERS = ["joint_model_cplex.py", "joint_model_gurobi.py"]
VERIFIER = os.path.join("analysis", "verifier3.py")

# THE MAPPING. One entry per constraint the builders post, naming the verify2 class(es) that
# evaluate the same requirement on a committed solution. Each entry records WHAT the row encodes,
# so a reviewer can check the judgment rather than take it.
# NUMBERING WARNING, found by this gate on 2026-09-20. Our builders' "ConstNN" markers follow the
# numbering in K's RELEASED CODE, which is NOT the numbering in the article. Const8 is article (6);
# Const14 is article (12); Const7 is not article (7) at all but Table 1's h_i domain. So this map
# is a genuine translation, not an identity, and each entry below names the ARTICLE constraint it
# discharges. Reading a "Const14" comment as article (14) would be wrong.
MAP = {
    "Const4":  (["C4-LASTXFER"],      "(4) final transfer before returning to the garage"),
    "Const5":  (["C5-LOAD"],          "(5) LEFV capacity with reset at a transfer"),
    "Const7":  (["T1-H-lo", "T1-H-hi"], "(7) garage reachability and return bounds on h_i"),
    "Const8":  (["C6-ARC"],           "(6) street arc timing; big-M is encoding, timing is checked"),
    "Const9":  (["OBJ"],              "(7) defines f^s; verifier3 RECOMPUTES travel instead"),
    "Const12": (["C10-HUB"],          "(10) exactly one satellite iff a transfer exists"),
    "Const13": (["C11-XFER-START"],   "(11) transfer cannot start before the LEFV arrives"),
    "Const14": (["C12-XFER-DEPART"],  "ARTICLE (12): u_i + sum_p (U + t_pj) v_ip <= h_j. Our "
                                      "marker says Const14 because our builder follows K's CODE "
                                      "numbering, which DIFFERS from the article's."),
    "Const15": (["C13-SYNC-lo", "C13-SYNC-hi"], "(13) vessel-window bounds on u_i"),
    "Const18": (["C16-WDEG-out", "C16-WDEG-in"], "(16) each transfer served once by a vessel"),
    "Const19": (["C17-WFLEET"],       "(17) vessel flow balance at the central depot"),
    "Const20": (["C18-WLOAD"],        "(18) m_i <= l_i <= Q_w"),
    "Const21": (["C19-WACC"],         "(19) vessel load accumulation along a tour"),
    "Const22": (["C20-WSEQ"],         "(20) vessel task sequencing in time"),
    "Const23": (["OBJ"],              "(21)(22) define f^w at the depot legs; RECOMPUTED"),
    "Const24": (["OBJ"],              "(23) defines f^w hub-to-hub; RECOMPUTED"),
    "(26)":    (["C26"],              "(26) same-satellite transfers at least U apart -- checked "
                                      "in its ORIGINAL form; (27)-(30) never read"),
}

# verify2 classes with NO model counterpart BY DESIGN. Each needs a reason: these are checks on
# the artifact rather than on the formulation, and a model has nothing to say about them.
CHECKER_ONLY = {
    # Published constraints our builder posts WITHOUT a marker, so this gate cannot see them from
    # the source side. Named here so they are not reported as orphans and are not silently lost.
    "C2-DEG-out": "(2) out-degree 1 per customer -- posted unmarked at joint_model_cplex.py:117",
    "C2-DEG-in":  "(2) in-degree 1 per customer -- posted unmarked at :118",
    "C3-FLEET":   "(3) LEFVs leaving = returning = nCars -- posted unmarked at :120-121",
    # Domains: carried by the artifact's data shape rather than by a row.
    "D8-ARCSET":   "(8) x_ij binary -- the artifact stores a SET of traversed arcs",
    "D9-PHI":      "(9) phi_i binary -- vi is a set of customers",
    "D15-HUB":     "(15) v_ip binary -- hubs is parallel to vi and names satellites",
    "D25-WARCSET": "(25) y_ij binary -- yij is a set of pairs",
    # Artifact-level: properties of the dump, not of the formulation.
    "A-FIELD":     "a required field is absent from the dump",
    "A-TIMETABLE": "no committed (h,u): not a primal result at all (I4)",
    "A-ALIEN":     "a node index outside the instance",
    "A-STRUCT":    "the routing does not form closed tours from the garage",
    "A-H":         "a needed h_i is absent",
    "A-U":         "a needed u_i is absent",
    "A-NCARS":     "the dump carries no nCars",
    "A-NVESSEL":   "the dump carries no nVessel",
    "A-OBJVAL":    "the dump carries no objVal",
    "A-TRIP_LOAD": "a vessel task with no street trip feeding it",
}


def posted_constraints():
    """Constraint markers each builder posts, from its own source."""
    found = {}
    for b in BUILDERS:
        path = os.path.join(ROOT, b)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        names = set(re.findall(r"#\s*(Const\d+)", src))
        for m in re.findall(r"#\s*(Const\d+)\s*/\s*(\d+)", src):
            names.add("Const" + m[1])            # "Const20/21" posts both
        if "hardSingleTransfer" in src:
            names.add("(26)")
        found[b] = names
    return found


def verifier_classes():
    """verifier3's classes, read from its OWN declarations rather than scraped.

    An earlier version used a regex over the source, which could not parse names like
    "C2-DEG-out" or "T1-H-lo" and silently reported them missing. Importing the module is exact,
    and it means a renamed class is caught here rather than passing unnoticed.
    """
    import importlib
    if os.path.join(ROOT, "analysis") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "analysis"))
    v3 = importlib.import_module("verifier3")
    cls = set(v3.ARTIFACT_CLASSES)
    for _n, (_kind, names, _why) in v3.PUBLISHED.items():
        cls |= set(names)
    # classes that exist only at runtime, via need()
    cls |= {"A-H", "A-U", "A-NCARS", "A-NVESSEL", "A-OBJVAL", "A-TRIP_LOAD", "A-TIMETABLE"}
    return cls


def main():
    posted = posted_constraints()
    vclasses = verifier_classes()
    fails, notes = [], []

    all_posted = set()
    for b, names in posted.items():
        all_posted |= names
        print("%-26s posts %2d constraint markers" % (b, len(names)))
    print("%-26s implements %2d classes" % (VERIFIER, len(vclasses)))
    print()

    # 1. every posted constraint needs a declared counterpart
    print("%-10s %-34s %s" % ("posted", "verifier counterpart", "status"))
    print("-" * 78)
    for c in sorted(all_posted, key=lambda s: (s != "(26)", s)):
        if c not in MAP:
            print("%-10s %-34s %s" % (c, "-- NONE DECLARED --", "FAIL"))
            fails.append("%s is posted by a builder and has NO declared verifier counterpart" % c)
            continue
        names, _why = MAP[c]
        missing = [n for n in names if n not in vclasses]
        if missing:
            print("%-10s %-34s %s" % (c, ",".join(names), "FAIL: %s absent" % ",".join(missing)))
            fails.append("%s maps to %s, which verifier3 does not implement" % (c, missing))
        else:
            print("%-10s %-34s %s" % (c, ",".join(names), "ok"))

    # 2. every mapped class must actually exist (catches renames)
    for c, (names, _w) in MAP.items():
        if c not in all_posted:
            notes.append("%s is in the mapping but no builder posts it (stale entry?)" % c)

    # 3. no orphan verifier classes
    mapped = {n for names, _w in MAP.values() for n in names}
    orphans = sorted(vclasses - mapped - set(CHECKER_ONLY))
    print()
    if orphans:
        print("ORPHAN verifier classes -- neither mapped to a constraint nor declared "
              "checker-only:")
        for o in orphans:
            print("   %s" % o)
            fails.append("verifier3 class %s is undeclared: map it or mark it checker-only" % o)
    else:
        print("No orphan verifier classes: every class is either mapped or declared checker-only.")

    for n in notes:
        print("NOTE: %s" % n)

    print()
    print("G-PARITY: %d failure(s)" % len(fails))
    for f in fails:
        print("   " + f)
    if not fails:
        print()
        print("PASS -- every posted constraint has a named verifier counterpart, and every named")
        print("counterpart exists. THIS IS NOT A COMPLETENESS PROOF: semantic equivalence is the")
        print("human judgment recorded in MAP, which this gate keeps honest but cannot verify.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
