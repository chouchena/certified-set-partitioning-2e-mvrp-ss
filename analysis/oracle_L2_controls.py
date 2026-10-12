"""Negative controls for L2. Without these, L2's "0 failures" is uninterpretable.

WHY THIS FILE EXISTS. The v4 amnesic audit (DM3) found that two of three power perturbations were
mathematically incapable of firing: the run reported "NO POWER" and would have been read as
evidence of insensitivity. The lesson recorded then was general -- *a control must be shown
capable of firing before its null is read* -- and L2 passed 7 census builds and 15 round-trips
without a single check ever reporting a problem. That is exactly the shape of a detector that is
silently broken.

Each control below breaks ONE thing and requires the matching L2 check to catch it. A control that
does not fire is itself a failure.

  L2a-NC1  suppress every row from one declared call site  -> MISSING
  L2a-NC2  remove a call site from the census table        -> UNDECLARED
  L2a-NC3  halve one site's expected count                 -> COUNT
  L2b-NC1  tighten one customer's time window past its committed value  -> INFEASIBLE
  L2b-NC2  scale the street travel cost by 1%              -> priced differently (drift)
  L2b-NC3  delete an arc the solution uses from the model  -> cannot represent it

    python analysis/oracle_L2_controls.py
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import oracle_L2 as L2
import verifier3

CELL, SIZE, PROX = "C201", 10, 0.0


def census_problems(tally, H, hard, census=None):
    """Re-run L2a's comparison logic over a supplied tally. Returns the list of problem kinds."""
    census = L2.CENSUS if census is None else census
    S = L2.symbols(H)
    out, seen = [], set()

    def match(text):
        best = None
        for pref, art, expr, note in census:
            if text.startswith(pref) and (best is None or len(pref) > len(best[0])):
                best = (pref, art, expr, note)
        return best

    for key, got in sorted(tally.items()):
        hit = match(key)
        if hit is None:
            out.append(("UNDECLARED", key[:56], got, "?"))
            continue
        pref, art, expr, _ = hit
        seen.add(art + "|" + pref)
        want = int(eval(expr, {"__builtins__": {}}, S))
        if got != want:
            out.append(("COUNT", art, got, want))
    for pref, art, expr, _ in census:
        if art + "|" + pref in seen:
            continue
        want = int(eval(expr, {"__builtins__": {}}, S))
        if want == 0 or (not hard and art.startswith("(26) corrected")):
            continue
        out.append(("MISSING", art, 0, want))
    if sum(tally.values()) != H["m"].NumConstrs:
        out.append(("UNATTRIBUTED", "sum != NumConstrs", H["m"].NumConstrs, sum(tally.values())))
    return out


def l2a_controls():
    print("L2a controls -- can the row census report a problem at all?")
    print()
    tally, H = L2.census_build(CELL, SIZE, PROX, True)
    results = []

    # NC1: a whole block silently skipped. Drop every row attributed to (12) assignment.
    victim = [kk for kk in tally
              if kk.startswith("m.addConstr(gp.quicksum(vip[i, p] for p in Satellites)")][0]
    t1 = dict(tally)
    lost = t1.pop(victim)
    p1 = census_problems(t1, H, True)
    # the suppressed rows also stop reconciling with NumConstrs -- both detectors should speak
    fired = [k for k, *_ in p1]
    results.append(("L2a-NC1 block skipped (%d rows)" % lost, "MISSING", "MISSING" in fired, p1))

    # NC2: a call site the census never declared.
    shrunk = [c for c in L2.CENSUS
              if not c[0].startswith("m.addConstr(li[i] >= mi[i])")]
    p2 = census_problems(tally, H, True, census=shrunk)
    fired = [k for k, *_ in p2]
    results.append(("L2a-NC2 site not declared", "UNDECLARED", "UNDECLARED" in fired, p2))

    # NC3: a count expectation that does not match the index set.
    # Keyed on the CALL SITE, not on the label. Renaming the census labels to K's article
    # numbering silently disarmed the previous version -- it targeted the string
    # "(20) vessel load", which no longer existed, so the injection did nothing and the control
    # went quiet. G21 caught it; a source-derived key cannot be broken by a rename.
    NC3_SITE = "m.addConstr(li[i] >= mi[i])"
    bent = [(pref, art, ("(n)//2" if pref == NC3_SITE else expr), note)
            for pref, art, expr, note in L2.CENSUS]
    assert any(pref == NC3_SITE for pref, _a, _e, _n in L2.CENSUS),         "NC3 target site %r is not in the census -- the control would be a no-op" % NC3_SITE
    p3 = census_problems(tally, H, True, census=bent)
    fired = [k for k, *_ in p3]
    results.append(("L2a-NC3 wrong expected count", "COUNT", "COUNT" in fired, p3))

    for name, want, ok, probs in results:
        print("   %-38s expect %-12s %s   (%s)"
              % (name, want, "FIRED" if ok else "SILENT -- CONTROL FAILED",
                 ", ".join("%s:%s" % (k, str(w)[:22]) for k, w, _g, _n in probs[:3]) or "nothing"))
    return results


def pin_and_solve(path, tweak=None, tl=120.0, threads=2):
    """L2b's round-trip, with an optional deliberate defect. Returns (verdict, obj, drift, note)."""
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi
    from gurobipy import GRB
    base = os.path.basename(path)
    sol = json.load(open(path, encoding="utf-8"))
    mm = re.search(r"((?:RC|R|C)\d{3})_n(\d+)", base)
    cell, size = mm.group(1), int(mm.group(2))
    prox = float(sol["_proximity"])
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox)
    p.hardSingleTransfer = bool(sol.get("_posts_26", True))
    if tweak == "NC2":
        p.travelcoststreet = p.travelcoststreet * 1.01     # the model prices it differently
    H = build_joint_model_gurobi(p)
    m = H["m"]
    xsel = {(int(a), int(b)) for a, b in sol["xij"]}
    ysel = {(int(a), int(b)) for a, b in sol["yij"]}
    hub = dict(zip([int(c) for c in sol["vi"]], [int(q) for q in sol["hubs"]]))

    note = ""
    if tweak == "NC3":
        gone = sorted(xsel & set(H["xij"].keys()))[0]
        del H["xij"][gone]                                  # as if the builder never created it
        note = "arc %s removed" % (gone,)
    pruned = sorted(xsel - set(H["xij"].keys()))
    if pruned:
        return "CANNOT-REPRESENT", None, None, note or "%d arc(s)" % len(pruned)

    for key, var in H["xij"].items():
        m.addConstr(var == (1 if key in xsel else 0))
    for key, var in H["y"].items():
        m.addConstr(var == (1 if key in ysel else 0))
    for c, var in H["vi"].items():
        m.addConstr(var == (1 if c in hub else 0))
    for (c, q), var in H["vip"].items():
        m.addConstr(var == (1 if hub.get(c) == q else 0))
    for c, var in H["hi"].items():
        if str(c) in (sol.get("hi") or {}):
            if tweak == "NC1" and not note and c != 0:
                # an over-tight model: this customer's window excludes its committed h
                m.addConstr(var <= float(sol["hi"][str(c)]) - 1.0)
                note = "h[%s] capped 1.0 below its committed value" % c
                continue
            m.addConstr(var == float(sol["hi"][str(c)]))
    for c, var in H["ui"].items():
        if str(c) in (sol.get("ui") or {}):
            m.addConstr(var == float(sol["ui"][str(c)]))

    m.Params.OutputFlag = 0
    m.Params.TimeLimit = tl
    m.Params.Threads = threads
    m.optimize()
    st = m.Status
    name = {GRB.OPTIMAL: "FEASIBLE", GRB.INFEASIBLE: "INFEASIBLE",
            GRB.INF_OR_UNBD: "INF_OR_UNBD"}.get(st, "st%d" % st)
    obj = m.ObjVal if st == GRB.OPTIMAL else None
    drift = None if obj is None else abs(obj - float(sol["objVal"]))
    return name, obj, drift, note


def l2b_controls(path):
    print()
    print("L2b controls -- can the round-trip report an over-tight or mispriced model?")
    print()
    rows = []
    base, _, bdrift, _ = pin_and_solve(path, None)
    rows.append(("L2b baseline (undamaged)", "FEASIBLE, drift 0", base,
                 base == "FEASIBLE" and bdrift is not None and bdrift <= 0.01, ""))
    v1, _, _, n1 = pin_and_solve(path, "NC1")
    rows.append(("L2b-NC1 window excludes the point", "INFEASIBLE", v1, v1 == "INFEASIBLE", n1))
    v2, o2, d2, n2 = pin_and_solve(path, "NC2")
    rows.append(("L2b-NC2 cost row inflated 1%%", "drift > 0.01", "%s drift %.3f" % (v2, d2 or 0),
                 v2 == "FEASIBLE" and d2 is not None and d2 > 0.01, n2))
    v3, _, _, n3 = pin_and_solve(path, "NC3")
    rows.append(("L2b-NC3 used arc absent from model", "CANNOT-REPRESENT", v3,
                 v3 == "CANNOT-REPRESENT", n3))
    for name, want, got, ok, note in rows:
        print("   %-38s expect %-18s got %-22s %s%s"
              % (name, want, got, "FIRED" if ok else "SILENT -- CONTROL FAILED",
                 ("   [%s]" % note) if note else ""))
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = l2a_controls()
    art = os.path.join(ROOT, "runs", "v3smoke", "v3_C201_n10.json")
    b = l2b_controls(art)
    bad = [n for n, _w, ok, _p in a if not ok] + [n for n, _w, _g, ok, _t in b if not ok]
    print()
    print("L2 CONTROLS: %d silent" % len(bad))
    for n in bad:
        print("   SILENT: %s" % n)
    json.dump(stamped({"L2a": [[n, w, ok] for n, w, ok, _p in a],
               "L2b": [[n, w, g, ok] for n, w, g, ok, _t in b],
               "silent": bad, "sources": L2.sources(),
               "when": __import__("time").strftime("%Y-%m-%dT%H:%M:%S")}, __file__),
              open(os.path.join(L2.OUT, "L2_controls.json"), "w"), indent=1, default=str)
    if not bad:
        print()
        print("   Every control fired. L2's 0-failure result is now interpretable: the checks")
        print("   are demonstrably able to report a problem, so their silence is evidence")
        print("   rather than an absence of instrumentation.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
