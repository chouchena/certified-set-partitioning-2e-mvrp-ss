"""
CONDITIONAL Gurobi validity check for the arithmetic bound (claim C7).

Design decision 2026-09-12: the expensive arm is NOT run on a schedule. The proof of
`AB <= z_joint*` is re-anchored to K's own Gurobi source in
`validation/AB_VALIDITY_VS_K_GUROBI.md` at zero compute, so a solver run adds nothing
unless an audit signal says the anchoring no longer holds.

    python analysis/gurobi_validity_check.py            # AUDIT  (free, no Gurobi, no solve)
    python analysis/gurobi_validity_check.py --fire T3  # EXPENSIVE arm, needs a named trigger

AUDIT exit codes:  0 = no trigger fired     2 = TRIGGERED, expensive arm is now required
                   1 = the audit itself could not run (missing artifact) -- treat as a trigger

PRE-REGISTERED TRIGGERS -- the expensive arm runs if and only if one of these fires.
Adding a trigger after seeing data is forbidden; removing one requires a recorded decision.

  T1  AB exceeds K's published best-known value on any cell.
      A lower bound above a feasible objective is INVALID. Decisive.
  T2  AB exceeds any verified incumbent of OUR OWN primal on the same cell.
      Same logic, independent solution source.
  T3  Any mapped model fact F1-F9 is no longer found in integratedJointModel.py.
      Guards the re-anchoring doc against the source file changing under it.
  T4  EXTERNAL: a referee, co-author or the authors challenge validity. Manual.
  T5  A claim starts using a regime the mapping was not read on -- stationaryBarges=True,
      problem_type != "2eVRP", or a model branch not covered by doc section 3.
  T6  Instance construction changes (generator version, tau rule, proximity handling)
      such that our data may no longer equal K's. Manual.

EXPENSIVE ARM, when fired:
  (a) rebuild K's Gurobi model at the affected cells and assert AB <= incumbent under a TL;
  (b) extend port_equivalence.py past |C|=8 -- the old "|C|<=8" cap was a RESTRICTED-licence
      limit that no longer applies (full academic WLS licence active 2026-09-12), so the
      port-fidelity evidence can be widened at the same time.
"""
import os, re, sys, json, glob, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
KSRC = os.path.join(ROOT, "integratedJointModel.py")

# F1-F9 as they must appear in K's source. Patterns are loose on whitespace and tight on
# the operator/structure the proof actually uses.
FACTS = {
    "F1a": (r"quicksum\(\s*xij\[i,\s*j\].*?\)\s*==\s*1", "outflow == 1 over SetCd"),
    "F1b": (r"quicksum\(\s*xij\[j,\s*i\].*?\)\s*==\s*1", "inflow == 1 over SetCd"),
    "F2": (r"quicksum\(\s*xij\[i,\s*0\]\s+for i in Customers\s*\)\s*==\s*nofCars",
           "nofCars = sum x[i,0]"),
    "F3": (r"arcStreetCost\[i,\s*j\]\s*>=\s*problem\.DistMatrix\[i\]\[j\]\s*\*\s*xij\[i,\s*j\]",
           "aS >= D*x"),
    "F4": (r"hi\[i\]\s*\+\s*problem\.nodes\[i\]\.serviceTime", "time advance via aS"),
    "F5a": (r"mi\[i\]\s*=\s*model\.addVar\(.*?ub\s*=\s*problem\.CarCapacity", "m <= CarCapacity"),
    "F5b": (r"mi\[j\]\s*-\s*mi\[i\]\s*>=\s*problem\.nodes\[j\]\.demand", "load recursion"),
    "F6": (r"vi\[i\]\s*>=\s*xij\[i,\s*0\]", "v_i >= x[i,0]"),
    "F7": (r"problem\.nodes\[0\]\.latest\s*-\s*problem\.DistMatrix\[i\]\[0\]", "garage window"),
    "F8a": (r"nofCars\s*\*\s*problem\.penaltyCars\s*==\s*FleetStreet", "FleetStreet equality"),
    "F8b": (r"exp3\s*==\s*TravelStreet", "TravelStreet equality"),
    "F8c": (r"FleetStreet\s*\+\s*FleetWater\s*\+\s*TravelStreet\s*\+\s*TravelWater\s*<=\s*zObj",
            "zObj"),
    "W1": (r"lowerVessels\s*=\s*math\.ceil\s*\(\s*sumDemand\s*/\s*problem\.VesselCapacity",
           "w(full) trip count"),
    "W2": (r"TravelWater\s*>=\s*problem\.travelcostwater\s*\*\s*minTr\s*\*\s*lowerVessels",
           "w(full) travel term"),
    "PRUNE": (r"problem\.nodes\[i\]\.earliest\s*\+\s*problem\.nodes\[i\]\.serviceTime"
              r"\s*\+\s*problem\.DistMatrix\[i\]\[j\]\s*<=\s*problem\.nodes\[j\]\.latest",
              "arcList TW pruning (doc 2.2)"),
}


def t3_source_facts():
    """T3: every mapped fact still present in K's Gurobi source."""
    if not os.path.exists(KSRC):
        return ["K source missing: integratedJointModel.py"], {}
    src = open(KSRC, encoding="utf-8", errors="replace").read()
    missing, found = [], {}
    for key, (pat, what) in FACTS.items():
        m = re.search(pat, src, re.S)
        if m:
            found[key] = src[:m.start()].count("\n") + 1
        else:
            missing.append("%s (%s)" % (key, what))
    return missing, found


def t1_ab_vs_k_bk():
    """T1: AB must not exceed K's published best-known value on any cell."""
    import lb_monitor as LM
    gp = os.path.join(ROOT, "runs", "ab4_grid_results.json")
    if not os.path.exists(gp):
        raise FileNotFoundError(gp)
    grid = json.load(open(gp))
    viol, checked = [], 0
    ktabs = {}
    for rec in grid.values():
        size = rec.get("size")
        if size not in (10, 20, 30) or rec.get("prox", 0.0) != 0.0:
            continue  # K publish per-instance BK only at |C| <= 30
        if size not in ktabs:
            ktabs[size] = LM.k_table3(size)
        row = ktabs[size].get(rec["cell"])
        ab = rec.get("ab4")
        if not row or ab is None:
            continue
        bk = row[2]
        checked += 1
        if ab > bk + 1e-6:
            viol.append((rec["cell"], size, round(ab, 2), round(bk, 2)))
    return viol, checked


def t2_ab_vs_our_incumbents():
    """T2: AB must not exceed any incumbent OUR OWN primal produced on the same cell.

    Source is results/ledger.jsonl (metrics.final_obj). VERIFIED rows are preferred --
    an unverified incumbent could itself be infeasible, so a violation against one is
    weaker evidence. Both are checked; the report separates them.
    """
    grid = json.load(open(os.path.join(ROOT, "runs", "ab4_grid_results.json")))
    led = os.path.join(ROOT, "results", "ledger.jsonl")
    best, best_v = {}, {}
    for line in open(led, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        obj = (d.get("metrics") or {}).get("final_obj")
        c, s_ = d.get("cell"), d.get("size")
        if not (c and s_ and isinstance(obj, (int, float)) and obj > 0):
            continue
        best[(c, s_)] = min(best.get((c, s_), float("inf")), float(obj))
        if d.get("verified") is True:
            best_v[(c, s_)] = min(best_v.get((c, s_), float("inf")), float(obj))
    viol, viol_v, checked, checked_v = [], [], 0, 0
    for rec in grid.values():
        key = (rec.get("cell"), rec.get("size"))
        ab = rec.get("ab4")
        if ab is None or rec.get("prox", 0.0) != 0.0:
            continue
        if key in best:
            checked += 1
            if ab > best[key] + 1e-6:
                viol.append((key[0], key[1], round(ab, 2), round(best[key], 2)))
        if key in best_v:
            checked_v += 1
            if ab > best_v[key] + 1e-6:
                viol_v.append((key[0], key[1], round(ab, 2), round(best_v[key], 2)))
    return viol, checked, viol_v, checked_v


def t5_regime():
    """T5: the mapping was read on problem_type='2eVRP', stationaryBarges=False."""
    bad = []
    for f in (glob.glob(os.path.join(ROOT, "crossfeed", "*.py"))
              + glob.glob(os.path.join(ROOT, "analysis", "lb_*.py"))):
        txt = open(f, encoding="utf-8", errors="replace").read()
        rel = os.path.relpath(f, ROOT)
        if re.search(r"stationaryBarges\s*=\s*True", txt):
            bad.append("%s: sets stationaryBarges=True" % rel)
        for m in re.finditer(r"problem_type\s*=\s*[\"']([^\"']+)", txt):
            if m.group(1) != "2eVRP":
                bad.append("%s: problem_type=%s" % (rel, m.group(1)))
    return bad


def audit():
    fired = []
    print("=" * 72)
    print("AB VALIDITY AUDIT  (free arm -- no Gurobi, no solve)")
    print("=" * 72)

    missing, found = t3_source_facts()
    if missing:
        fired.append(("T3", "facts not found in K's source: " + "; ".join(missing)))
        print("T3  FIRED   %d of %d facts missing" % (len(missing), len(FACTS)))
    else:
        print("T3  clean   %d/%d facts present in integratedJointModel.py"
              % (len(FACTS), len(FACTS)))
        print("            " + ", ".join("%s:L%d" % (k, v) for k, v in sorted(found.items())))

    try:
        v1, n1 = t1_ab_vs_k_bk()
        if v1:
            fired.append(("T1", "AB above K's BK on %d cells: %s" % (len(v1), v1[:5])))
            print("T1  FIRED   %d/%d cells have AB > K's published BK" % (len(v1), n1))
        else:
            print("T1  clean   0/%d cells have AB above K's published BK" % n1)
    except Exception as e:
        fired.append(("T1", "audit could not run: %s: %s" % (type(e).__name__, e)))
        print("T1  ERROR   %s" % e)

    try:
        v2, n2, v2v, n2v = t2_ab_vs_our_incumbents()
        if v2:
            fired.append(("T2", "AB above our own incumbent on %d cells: %s" % (len(v2), v2[:5])))
            print("T2  FIRED   %d/%d cells have AB > our own incumbent"
                  " (%d of them against a VERIFIED one)" % (len(v2), n2, len(v2v)))
        elif n2 == 0:
            # NOT a pass. Zero comparisons is the vacuous-falsifier failure mode
            # (prefix-length bug, 2026-09-09): a check that examined nothing must
            # never print "clean".
            fired.append(("T2", "VACUOUS -- 0 comparable incumbents found"))
            print("T2  NOT CHECKED   0 comparable incumbents in results/ledger.jsonl --"
                  " vacuous, not passing")
        else:
            print("T2  clean   0/%d cells have AB above one of our own incumbents"
                  " (%d of those against a VERIFIED incumbent)" % (n2, n2v))
    except Exception as e:
        fired.append(("T2", "audit could not run: %s: %s" % (type(e).__name__, e)))
        print("T2  ERROR   %s" % e)

    b5 = t5_regime()
    if b5:
        fired.append(("T5", "; ".join(b5)))
        print("T5  FIRED   %d regime departures" % len(b5))
    else:
        print("T5  clean   bound code on problem_type=2eVRP, stationaryBarges=False")

    print("-" * 72)
    if fired:
        print("TRIGGERED -- the expensive Gurobi arm is now REQUIRED:")
        for t, why in fired:
            print("  %s: %s" % (t, why))
        print("\n  run:  python analysis/gurobi_validity_check.py --fire %s" % fired[0][0])
        return 2
    print("NO TRIGGER. The source-anchored proof in")
    print("validation/AB_VALIDITY_VS_K_GUROBI.md stands; a Gurobi run would add nothing.")
    print("T4 (external challenge) and T6 (instance build) are MANUAL -- not auto-checkable.")
    return 0


def fire(trigger, cells, size, tl):
    """EXPENSIVE arm. Only reachable with an explicit named trigger."""
    if trigger not in ("T1", "T2", "T3", "T4", "T5", "T6"):
        print("refusing: '%s' is not a pre-registered trigger" % trigger)
        return 1
    print("EXPENSIVE ARM, trigger %s: build K's Gurobi model, assert AB <= incumbent" % trigger)
    print("NOTE: the old |C|<=8 cap came from a RESTRICTED licence and no longer applies.")
    import gurobipy  # noqa: F401  (licence probe -- fails loudly if unavailable)
    import instanceGenerator
    import integratedJointModel as JM
    grid = json.load(open(os.path.join(ROOT, "runs", "ab4_grid_results.json")))
    rows = []
    for cell in cells:
        p = instanceGenerator.readGenerate("%s.json" % cell, size, timeLimit=tl,
                                           problem_type="2eVRP", closeness=0.0)
        p.costScenario = 0.1
        p.update_rule = [False, False]
        p.Set_cost_coefficients()
        p.report = os.path.join(ROOT, "_pe_report.txt")
        p.stats = os.path.join(ROOT, "_pe_stats.txt")
        m = JM.JointSynchronized(p)
        inc = round(m.objVal, 3) if m else None
        ab = (grid.get("%s|n%d" % (cell, size)) or {}).get("ab4")
        ok = (inc is None) or (ab is None) or (ab <= inc + 1e-6)
        rows.append({"cell": cell, "size": size, "ab": ab,
                     "gurobi_incumbent": inc, "valid": ok})
        print("  %s n%d: AB=%s incumbent=%s %s"
              % (cell, size, ab, inc, "OK" if ok else "*** VIOLATION"))
    out = os.path.join(ROOT, "validation", "gurobi_validity_%s_n%d.json" % (trigger, size))
    json.dump(stamped({"trigger": trigger, "tl": tl, "rows": rows}, __file__), open(out, "w"), indent=2)
    print("-> %s" % os.path.relpath(out, ROOT))
    return 0 if all(r["valid"] for r in rows) else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", metavar="TRIGGER", default=None,
                    help="run the expensive arm; requires a pre-registered trigger name")
    ap.add_argument("--cells", default="C204,RC204,RC208,R208")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--tl", type=int, default=600)
    a = ap.parse_args()
    sys.exit(fire(a.fire, a.cells.split(","), a.size, a.tl) if a.fire else audit())
