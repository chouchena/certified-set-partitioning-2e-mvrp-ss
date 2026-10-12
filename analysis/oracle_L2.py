"""L2 of the transcription oracle: is the MODEL BUILDER correct, GIVEN the transcription?

Specified since before v1 and never built. The v5 amnesic audit (EM1) found the stack's
attribution argument -- "an L3 signal is attributable BECAUSE L1 and L2 passed" -- resting on a
layer that had never run. This is that layer.

Neither check uses K's numbers, so L2 is independent of the oracle it gates.

L2a  ROW CENSUS.  Every row the builder emits is attributed to the SOURCE LINE that emitted it,
     by shimming `Model.addConstr` and reading the caller's frame. Each call site then has to
     match a declared count derived from its index set. Three ways to fail:

       UNDECLARED  a call site emits rows this census never accounted for
       MISSING     a declared call site emits nothing (a block silently skipped)
       COUNT       a call site emits a number its quantifier does not imply

     and the per-site counts must sum to m.NumConstrs, so nothing hides between sites.

     WHAT IT CATCHES: a dropped branch, a guard that skips cases, a block behind a flag that
     never fires, a quantifier over the wrong index set.
     WHAT IT DOES NOT: a call site whose ROW CONTENT is wrong but whose COUNT is right. Counting
     rows says nothing about what is in them. That is L1's job, and it is why L2 is a layer
     rather than the instrument.

L2b  ROUND-TRIP (G-MODEL-ADMITS).  Every solution verifier3 ACCEPTS must be FEASIBLE in the
     built model: pin each decision variable to its committed value and ask Gurobi.

     This is the ONLY instrument for an OVER-TIGHT model, and verifier3 is structurally blind to
     one: shrinking the feasible region leaves every point that comes back still satisfying every
     constraint, so verification passes while the optimum silently inflates. The evidence of
     over-tightness is an ABSENCE, and an absence cannot be found by checking what arrived.

     Auxiliaries (mi, li, fij, o, z, nofCars, nofVessels, arc costs) are left FREE. Pinning them
     would test our extraction, not the model; leaving them free asks the right question -- does
     ANY completion of this routing satisfy the model?

WHAT L2 CANNOT DO, so it is not over-read: it validates the builder GIVEN the transcription. If
the builder and verifier3 share a misreading of K, both agree and L2 passes. It is a consistency
check between two artifacts, not a check against truth.

    python analysis/oracle_L2.py
"""
import glob
import hashlib
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import verifier3

OUT = os.path.join(ROOT, "runs", "oracle")
BUILDER = os.path.join(ROOT, "joint_model_gurobi.py")
VERIFIER = os.path.join(ROOT, "analysis", "verifier3.py")


def sources():
    """Hash the two files this result is about, so the result can detect its own staleness.

    A passing L2 that cannot tell it is stale is the SESSION_RESUME failure recorded in
    CLAUDE.md: prose -- and a JSON result is prose here -- cannot detect its own staleness.
    G21 in the release gate recomputes these and fails when either has moved.
    """
    out = {}
    for path in (BUILDER, VERIFIER, os.path.abspath(__file__)):
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        out[rel] = hashlib.sha256(io.open(path, "rb").read()).hexdigest()[:16]
    return out

# ---------------------------------------------------------------------------------------------
# The census. Key = a distinctive PREFIX of the call site's source text (stable under edits above
# it, unlike a line number). Value = (article, count-expression, note).
#
# Counts are written from the INDEX SET and cross-checked against the article's quantifier. Where
# the two differ it is because the builder pre-prunes arcs by a time-window test; that is recorded
# in `note` rather than hidden, because pruning is a model RESTRICTION and so is exactly the thing
# L2b exists to test.
#
# Symbols available to each expression: n (customers), P (satellites), A (arcs kept), A_fromC
# (kept arcs leaving a customer), A_CC (kept arcs between two customers), A_i0 (kept arcs
# customer->garage), pairs (n choose 2).
# ---------------------------------------------------------------------------------------------
CENSUS = [
    ("m.addConstr(gp.quicksum(xij[i, j] for j in SetCd if (i, j) in arcset) == 1",
     "(2) out-degree", "n", "one per customer -- the article's quantifier exactly"),
    ("m.addConstr(gp.quicksum(xij[j, i] for j in SetCd if (j, i) in arcset) == 1",
     "(3) in-degree", "n", "one per customer"),
    ("m.addConstr(gp.quicksum(xij[i, 0] for i in Customers if (i, 0) in arcset) == nofCars)",
     "(3) fleet-street", "1", "defines nofCars; part of K's (3)"),
    ("m.addConstr(gp.quicksum((xij[i, 0] if (i, 0) in arcset else 0)",
     "(3) garage balance", "1", "garage in-degree equals out-degree"),
    ("m.addConstr(vi[i] >= xij[i, 0])",
     "(4)", "A_i0", "ARTICLE quantifies over all i in C; where (i,garage) was pruned the row "
                    "would be vacuous, so absence is not a dropped case"),
    ("m.addConstr(mi[j] - mi[i] >= nd[j].demand",
     "(5) load MTZ", "A_CC", "one per kept customer-customer arc"),
    ("m.addConstr(float(nd[0].earliest + D[0][i]) <= hi[i])",
     "Table 1 h domain, lower", "n", "NOT a numbered constraint: Table 1 gives h_i its domain"),
    ("m.addConstr(float(nd[0].latest - D[i][0] - nd[i].serviceTime - TD) >= hi[i])",
     "Table 1 h domain, upper", "n", "NOT a numbered constraint: Table 1 gives h_i its domain"),
    ("m.addConstr(hi[i] + nd[i].serviceTime + TD * vi[i] + arcStreetCost[i, j]",
     "(6) time MTZ", "A_fromC", "one per kept arc leaving a customer"),
    ("m.addConstr(arcStreetCost[i, j] >= D[i][j] * xij[i, j])",
     "(7) f^s floor", "A", "K: travel time realized from i to j must be positive"),
    ("m.addConstr(arcStreetCost[i, j] >= D[i][j] * xij[i, j] + minTravel",
     "(7) f^s detour", "A_fromC", "K: lower bound on travel if a transfer follows node i"),
    ("m.addConstr(gp.quicksum(vip[i, p] for p in Satellites) == vi[i])",
     "(10) assignment", "n", "exactly one satellite iff a transfer exists"),
    ("m.addConstr(ui[i] >= hi[i] + nd[i].serviceTime",
     "(11) transfer start", "n", "K: cannot start before the LEFV arrives at the satellite"),
    ("m.addConstr(nd[CDC].earliest + gp.quicksum(D[CDC][p] * vip[i, p]",
     "(13) u lower", "n", "K: transfer start must respect the vessels' time window"),
    ("m.addConstr(nd[CDC].latest >= ui[i]",
     "(13) u upper", "n", "K: transfer start must respect the vessels' time window"),
    ("m.addConstr(gp.quicksum((D[i][p] + D[p][j]) * (xij[i, j] + vip[i, p] - 1)",
     "(14) f^s at a transfer", "A_fromC", "defines f^s through the chosen satellite"),
    ("m.addConstr(ui[i] + gp.quicksum((TD + D[p][j]) * vip[i, p]",
     "(12) departure", "A_fromC", "K: LEFV cannot leave until the transfer is completed"),
    ("m.addConstr(gp.quicksum(y[i, j] for j in setCw if i != j) == vi[i])",
     "(16) water out", "n", "K: the task is served exactly once by a vessel"),
    ("m.addConstr(gp.quicksum(y[j, i] for j in setCw if i != j) == vi[i])",
     "(16) water in", "n", "K: the task is served exactly once by a vessel"),
    ("m.addConstr(gp.quicksum(y[i, CDC] - y[CDC, i] for i in Customers) == 0)",
     "(17) CDC balance", "1", "vessels leaving = returning"),
    ("m.addConstr(li[i] >= mi[i])",
     "(18) vessel load", "n", "K: task capacity at least the LEFV load after its last customer"),
    ("m.addConstr(li[j] - li[i] >= mi[j] - problem.VesselCapacity",
     "(19) vessel capacity", "n*(n-1)", "K: vessel capacity not exceeded at any point"),
    ("m.addConstr(gp.quicksum(y[i, CDC] for i in Customers) == nofVessels)",
     "(17) fleet-water", "1", "defines nofVessels; part of K's (17)"),
    ("m.addConstr(nofVessels >= lowerVessels)",
     "valid inequality", "1", "NOT K's -- ours: ceil(sum d / Q_v)"),
    ("m.addConstr(ui[i] + TD + arcWaterCost[i, j] <= ui[j] + MijWater",
     "(20) vessel sequencing", "n*(n-1)", "K: schedules transfer start times on a vessel"),
    ("m.addConstr(arcWaterCost[CDC, i] >=",
     "(21) f^w depot->hub", "n", "defines f^w; recomputed, never read as a row"),
    ("m.addConstr(arcWaterCost[i, CDC] >=",
     "(22) f^w hub->depot", "n", "defines f^w; recomputed, never read as a row"),
    ("m.addConstr(arcWaterCost[i, j] >= D[p][r] * (y[i, j] + vip[i, p] + vip[j, r] - 2))",
     "(23) f^w hub->hub", "n*(n-1)*P*(P-1)", "every ordered customer pair x every distinct satellite "
                                         "pair"),
    ("m.addConstr(ui[i] - ui[j] <= fij[i, j])",
     "(27)", "pairs", "VACUOUS arm, faithful to K"),
    ("m.addConstr(ui[j] - ui[i] <= fij[i, j])",
     "(28)", "pairs", "VACUOUS arm, faithful to K"),
    ("m.addConstr(fij[j, i] == fij[i, j])",
     "(29)", "pairs", "VACUOUS arm, faithful to K"),
    ("m.addConstr(fij[i, j] >= TD * (vip[i, p] + vip[j, p] - 1))",
     "(30)", "pairs*P", "VACUOUS arm: r bounded below twice and never costed"),
    # (26) is now enforced by INDICATOR constraints, not big-M. The big-M disjunction
    # let a binary sitting at 1 - 1.1e-8 be multiplied by Mbig = 1187 into a real
    # 1.3049e-5 violation of a 20-unit separation. Indicators are enforced by branching,
    # so there is no coefficient for the tolerance to multiply. The census below tracks
    # the new sites; the two big-M rows it replaced are gone from the builder.
    ("m.addConstr(sep[i, j] >= vip[i, p] + vip[j, p] - 1)",
     "(26) same-satellite flag", "pairs*P", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr(a1[i, j] <= sep[i, j])",
     "(26) a1 gated by sep", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr(a1[i, j] <= o)",
     "(26) a1 gated by order", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr(a0[i, j] <= sep[i, j])",
     "(26) a0 gated by sep", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr(a0[i, j] <= 1 - o)",
     "(26) a0 gated by order", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr(a1[i, j] + a0[i, j] >= sep[i, j])",
     "(26) one ordering when shared", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr((a1[i, j] == 1) >> (ui[j] >= ui[i] + TD))",
     "(26) indicator i before j", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr((a0[i, j] == 1) >> (ui[i] >= ui[j] + TD))",
     "(26) indicator j before i", "pairs", "CORRECTED arm, behind hardSingleTransfer"),
    ("m.addConstr(nofVessels * problem.penaltyVessels == FleetWater)",
     "objective", "1", "cost accumulator"),
    ("m.addConstr(nofCars * problem.penaltyCars == FleetStreet)",
     "objective", "1", "cost accumulator"),
    ("m.addConstr(gp.quicksum(problem.travelcoststreet * arcStreetCost[i, j]",
     "objective", "1", "cost accumulator"),
    ("m.addConstr(gp.quicksum(problem.travelcostwater * arcWaterCost[i, j]",
     "objective", "1", "cost accumulator"),
    ("m.addConstr(TravelWater >= problem.travelcostwater * minTr * lowerVessels)",
     "valid inequality", "1", "NOT K's -- ours"),
    ("m.addConstr(FleetStreet + FleetWater + TravelStreet + TravelWater <= zObj)",
     "objective", "1", "epigraph"),
    # stationaryBarges variant, off in every cell we run; declared so it cannot appear unnoticed
    ("m.addConstr(FleetWater == problem.penaltyVessels * nofBarges)",
     "barge variant", "0", "stationaryBarges only"),
    ("m.addConstr(gp.quicksum(z[p] for p in Satellites) <= nofBarges)",
     "barge variant", "0", "stationaryBarges only"),
    ("m.addConstr(vip[i, p] <= z[p])",
     "barge variant", "0", "stationaryBarges only"),
    ("m.addConstr(arcWaterCost[i, j] == 0)",
     "barge variant", "0", "stationaryBarges only"),
]


def match_site(text):
    """Longest declared prefix matching this call site's source, or None."""
    best = None
    for pref, art, expr, note in CENSUS:
        if text.startswith(pref) and (best is None or len(pref) > len(best[0])):
            best = (pref, art, expr, note)
    return best


def census_build(cell, size, prox, hard):
    """Build once with addConstr shimmed; returns {call-site source -> rows emitted}, handle."""
    import linecache
    import gurobipy as gp
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi

    tally = {}
    orig = gp.Model.addConstr

    def shim(self, *a, **kw):
        f = sys._getframe(1)
        if os.path.abspath(f.f_code.co_filename) == os.path.abspath(BUILDER):
            key = linecache.getline(BUILDER, f.f_lineno).strip()
            tally[key] = tally.get(key, 0) + 1
        return orig(self, *a, **kw)

    gp.Model.addConstr = shim
    try:
        p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
        p.hardSingleTransfer = hard
        H = build_joint_model_gurobi(p)
    finally:
        gp.Model.addConstr = orig
    H["m"].update()
    return tally, H


def symbols(H):
    C = set(H["Customers"])
    arcs = [tuple(a) for a in H["arcList"]]
    n = len(C)
    return dict(n=n, P=len(H["Satellites"]), A=len(arcs),
                A_fromC=sum(1 for i, j in arcs if i in C),
                A_CC=sum(1 for i, j in arcs if i in C and j in C),
                A_i0=sum(1 for i, j in arcs if i in C and j == 0),
                pairs=n * (n - 1) // 2)


def run_L2a(cases):
    print("L2a -- ROW CENSUS. Every emitted row attributed to its call site and matched against")
    print("       the count its index set implies. Sites keyed on source text, not line number.")
    print()
    rows, fails = [], []
    for cell, size, prox, hard in cases:
        tally, H = census_build(cell, size, prox, hard)
        S = symbols(H)
        # NumConstrs counts LINEAR rows only. (26) is enforced by indicator
        # constraints from 2026-09-21, and Gurobi files those under NumGenConstrs --
        # so the shim tallied 2 calls per pair that the model total did not count,
        # and every case reported an UNATTRIBUTED shortfall of exactly 2*pairs
        # (90 at n10, 380 at n20, 870 at n30). The census must count what the
        # builder emits, whichever family the solver files it under.
        _m = H["m"]
        total_model = _m.NumConstrs + getattr(_m, "NumGenConstrs", 0)
        total_seen = sum(tally.values())
        bad, seen_arts = [], set()
        for key, got in sorted(tally.items()):
            hit = match_site(key)
            if hit is None:
                bad.append(("UNDECLARED", key[:66], got, "?"))
                continue
            _pref, art, expr, _note = hit
            seen_arts.add(art + "|" + _pref)
            want = int(eval(expr, {"__builtins__": {}}, S))
            if got != want:
                bad.append(("COUNT", "%-20s %s" % (art, key[:40]), got, want))
        for pref, art, expr, _note in CENSUS:
            if art + "|" + pref in seen_arts:
                continue
            want = int(eval(expr, {"__builtins__": {}}, S))
            if want == 0:
                continue
            # Keyed on the CONSTRAINT NUMBER, not on a label. This read
            # `art.startswith("(26) corrected")` until 2026-09-21, when (26) was
            # re-encoded with indicator constraints and its sites were relabelled
            # "(26) same-satellite flag", "(26) a1 gated by sep" and so on. The
            # exemption stopped matching and L2 demanded eight blocks on the vacuous
            # arm where they correctly do not exist. Same failure as NC3: a guard
            # keyed on a label is disarmed by relabelling. "(26)" cannot drift.
            if not hard and art.startswith("(26)"):
                continue                      # legitimately absent in the vacuous arm
            bad.append(("MISSING", "%-20s %s" % (art, pref[:40]), 0, want))
        if total_seen != total_model:
            bad.append(("UNATTRIBUTED", "rows in the model no call site accounted for",
                        total_model, total_seen))
        tag = "corrected" if hard else "vacuous"
        print("   %-7s n%-4d p%-4s %-10s sites %3d  rows %8d  model %8d   %s"
              % (cell, size, prox, tag, len(tally), total_seen, total_model,
                 "ok" if not bad else "%d PROBLEM(S)" % len(bad)))
        for kind, what, got, want in bad:
            print("        %-13s %-62s got %s want %s" % (kind, what, got, want))
            fails.append("%s/n%d %s: %s %s (got %s, want %s)"
                         % (cell, size, tag, kind, what, got, want))
        rows.append(dict(cell=cell, size=size, proximity=prox, arm=tag, sites=len(tally),
                         rows=total_seen, model_rows=total_model, symbols=S, problems=len(bad)))
    print()
    print("   L2a: %d failure(s)" % len(fails))
    return rows, fails


def run_L2b(artifacts, tl=300.0, threads=4):
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi
    from gurobipy import GRB
    print()
    print("L2b -- ROUND-TRIP (G-MODEL-ADMITS). Does the model ADMIT what verifier3 ACCEPTS?")
    print("       The only instrument for an over-tight model; verifier3 cannot see one.")
    print()
    rows, fails = [], []
    for path in artifacts:
        base = os.path.basename(path)
        run = verifier3.verify(path)
        if run.verdict() != verifier3.ACCEPT:
            print("   %-24s verifier3=%s -- skipped" % (base[:24], run.verdict()))
            continue
        sol = json.load(open(path, encoding="utf-8"))
        mm = re.search(r"((?:RC|R|C)\d{3})_n(\d+)", base)
        cell, size = mm.group(1), int(mm.group(2))
        prox = float(sol["_proximity"])
        p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
        p.hardSingleTransfer = bool(sol.get("_posts_26", True))
        # AND THE BIG-M ARM, which was missing until 2026-09-21. L2b honoured the
        # artifact's _posts_26 but not its _valid_bigm, so a solution produced with a
        # VALID big-M was pinned into a model carrying K's UNDERSIZED constants. The
        # model then excluded it and L2b reported an over-tight model -- which is our
        # own documented finding about K's constants, reproducing itself and being read
        # as a defect. Confirmed by IIS on v3_C201_n100: the binding row was
        # -u[18] + u[77] + 1606*Y[77,18] + arcCostW <= 1426, still forcing
        # u[18] >= u[77] - 1426 = 1870.6 with the arc UNUSED, against a street row
        # capping u[18] at 1837.1. M = 1426 cannot make it vacuous when u[77] = 3296.6.
        p.validBigM = bool(sol.get("_valid_bigm", False))
        H = build_joint_model_gurobi(p)
        m = H["m"]

        xsel = {(int(a), int(b)) for a, b in sol["xij"]}
        ysel = {(int(a), int(b)) for a, b in sol["yij"]}
        hub = dict(zip([int(c) for c in sol["vi"]], [int(q) for q in sol["hubs"]]))

        # An arc the solution USES that the builder never created is over-tightness of the
        # harshest kind: the model cannot represent the solution at all. Detect it before the
        # solve, because Gurobi would report only a generic INFEASIBLE.
        pruned = sorted(xsel - set(H["xij"].keys()))
        missing_y = sorted(ysel - set(H["y"].keys()))

        n = 0
        for key, var in H["xij"].items():
            m.addConstr(var == (1 if key in xsel else 0)); n += 1
        for key, var in H["y"].items():
            m.addConstr(var == (1 if key in ysel else 0)); n += 1
        for c, var in H["vi"].items():
            m.addConstr(var == (1 if c in hub else 0)); n += 1
        for (c, q), var in H["vip"].items():
            m.addConstr(var == (1 if hub.get(c) == q else 0)); n += 1
        for c, var in H["hi"].items():
            if str(c) in (sol.get("hi") or {}):
                m.addConstr(var == float(sol["hi"][str(c)])); n += 1
        for c, var in H["ui"].items():
            if str(c) in (sol.get("ui") or {}):
                m.addConstr(var == float(sol["ui"][str(c)])); n += 1

        m.Params.OutputFlag = 0
        m.Params.TimeLimit = tl
        m.Params.Threads = threads
        t0 = time.time()
        m.optimize()
        st = m.Status
        name = {GRB.OPTIMAL: "FEASIBLE", GRB.INFEASIBLE: "INFEASIBLE",
                GRB.INF_OR_UNBD: "INF_OR_UNBD", GRB.TIME_LIMIT: "TIME_LIMIT"}.get(st, "st%d" % st)
        obj = m.ObjVal if st == GRB.OPTIMAL else None
        # A completion must also reproduce the banked objective, or the model admits the routing
        # but prices it differently -- a transcription defect in the cost rows that would
        # otherwise pass as FEASIBLE.
        drift = None if obj is None else abs(obj - float(sol["objVal"]))
        ok = (st == GRB.OPTIMAL) and not pruned and not missing_y
        if pruned or missing_y:
            fails.append("%s: the solution uses %d street arc(s) and %d water arc(s) the builder "
                         "never created -- the model cannot represent it"
                         % (base, len(pruned), len(missing_y)))
        elif st != GRB.OPTIMAL:
            fails.append("%s: verifier3 ACCEPTS it, the model says %s -- the model EXCLUDES a "
                         "feasible point" % (base, name))
        elif drift is not None and drift > 0.01:
            ok = False
            fails.append("%s: the model ADMITS it but prices it %.3f against a banked %.3f "
                         "(drift %.3f)" % (base, obj, float(sol["objVal"]), drift))
        print("   %-24s pinned %6d  %-11s obj %11s  drift %8s  %6.1fs  %s"
              % (base[:24], n, name,
                 "-" if obj is None else "%.3f" % obj,
                 "-" if drift is None else "%.4f" % drift,
                 time.time() - t0, "ok" if ok else "OVER-TIGHT"))
        rows.append(dict(artifact=base, cell=cell, size=size, proximity=prox, pinned=n,
                         model=name, obj=obj, banked=float(sol["objVal"]), drift=drift,
                         pruned_street=len(pruned), pruned_water=len(missing_y), ok=ok))
    print()
    print("   L2b: %d failure(s)" % len(fails))
    for f in fails:
        print("      " + f)
    return rows, fails


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    # both arms of (26), every family, every published size -- so a size- or family-dependent
    # branch cannot hide
    cases = [("C201", 10, 0.0, False), ("C201", 10, 0.0, True),
             ("C201", 20, 0.0, True), ("R201", 20, 0.0, True),
             ("C201", 30, 0.0, True), ("RC201", 50, 0.1, True),
             ("R201", 100, 0.1, True)]
    a_rows, a_fails = run_L2a(cases)
    arts = sorted(glob.glob(os.path.join(ROOT, "runs", "v3smoke", "*.json")))
    b_rows, b_fails = run_L2b(arts)
    tot = len(a_fails) + len(b_fails)
    json.dump(stamped({"L2a": a_rows, "L2b": b_rows, "failures": a_fails + b_fails,
               "verdict": "PASS" if not tot else "FAIL",
               "sources": sources(), "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "wall_s": round(time.time() - t0, 1)}, __file__),
              open(os.path.join(OUT, "L2.json"), "w"), indent=1, default=str)
    print()
    print("L2: %d failure(s)   %.1f min" % (tot, (time.time() - t0) / 60))
    if not tot:
        print()
        print("   PASS. Every emitted row is attributed to a declared call site and matches the")
        print("   count its index set implies; the model ADMITS and correctly PRICES every")
        print("   solution verifier3 accepts. The attribution argument now has its L2 leg.")
        print()
        print("   NOT ESTABLISHED: that the rows say the right thing -- counting is not reading;")
        print("   nor that the builder and verifier3 do not share a misreading of K.")
    return 1 if tot else 0


if __name__ == "__main__":
    sys.exit(main())
