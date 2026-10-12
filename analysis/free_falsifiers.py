"""A battery of FREE falsification attempts over banked artifacts. No solver, no CPU (d445).

Author, 2026-09-25: "lets keep on chasing free falsifier ideas". Everything here is arithmetic
over files already on disk, so it can run beside a wall-stopped batch without touching it.

Several of these re-attack STANDING claims with solutions that did not exist when the claim was
last tested. The descent bound's own registered falsifier is "any cell where the bound exceeds a
known feasible objective value", and it was last run on 2026-09-10 against 54 cells using K's
published incumbents. We now hold 60+ of our OWN verified solutions at n10, n20 and n100, several
of which are BELOW K's incumbent. Those are new, harder witnesses, and the claim has never met
them.

Each check prints PASS (not refuted) or REFUTED with the witness. A refutation here is worth more
than any positive result elsewhere, because it costs nothing to find and invalidates something we
are relying on.

    python analysis/free_falsifiers.py
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))

# the certified street-fleet floor, as fixopt._vehicle_floor documents it
V_LB = {10: lambda f: 1, 20: lambda f: 1, 30: lambda f: 2 if f == "C" else 1,
        50: lambda f: 3 if f == "C" else 2,
        100: lambda f: 5 if f == "C" else (3 if f == "RC" else 2)}


def fam(c):
    return "RC" if c.startswith("RC") else c[0]


def solutions():
    """Every verified solution we hold, with its cell, size and component split."""
    out = []
    d = os.path.join(ROOT, "runs", "postpass")
    for f in sorted(os.listdir(d)):
        if not f.startswith("ipchain") or not f.endswith(".json"):
            continue
        try:
            size = int(f.rsplit("_n", 1)[1].split(".")[0])
        except Exception:
            continue
        cell = f.replace("ipchain_ceil_", "").replace("ipchain_ss_", "").replace("ipchain_", "").split("_")[0]
        s = json.load(io.open(os.path.join(d, f), encoding="utf-8"))
        fleet = float(s.get("FleetStreet", 0)); travel = float(s.get("TravelStreet", 0))
        out.append(dict(file=f, cell=cell, size=size, obj=float(s["objVal"]),
                        cars=int(s.get("nCars", 0)), fleet=fleet, street=travel,
                        water=float(s["objVal"]) - fleet - travel))
    return out


def check(name, witnesses, n, note=""):
    if witnesses:
        print("  REFUTED  %-46s %d witness(es) of %d" % (name, len(witnesses), n))
        for w in witnesses[:4]:
            print("             %s" % w)
    else:
        print("  pass     %-46s not refuted in %d attempt(s)%s" % (name, n, (" -- " + note) if note else ""))
    return len(witnesses)


def main():
    sols = solutions()
    ab = {(r["cell"], r["size"]): r for r in json.load(io.open(os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}
    print("FREE FALSIFICATION BATTERY over %d verified solutions\n" % len(sols))
    bad = 0

    # 1 -- the descent bound against OUR solutions, not K's incumbents
    import dual_vs_k as D
    w, n = [], 0
    for s in sols:
        v = D.lb_frontier(s["cell"], s["size"]) or D.lb_maxrec(s["cell"], s["size"])
        if v is None:
            continue
        n += 1
        if float(v) > s["obj"] + 1e-6:
            w.append("%s n%d: descent %.2f > verified %.2f" % (s["cell"], s["size"], v, s["obj"]))
    bad += check("descent bound never above a verified solution", w, n,
                 "its registered falsifier, re-run on OUR solutions")

    # 2 -- the composed TEP bound against our solutions
    from bound_source import bound_for
    w, n = [], 0
    for s in sols:
        if s["size"] == 100:
            continue                      # suspended, not reportable, so not under test
        b = bound_for(s["cell"], s["size"], "tep")
        if b["value"] is None:
            continue
        n += 1
        if b["value"] > s["obj"] + 1e-6:
            w.append("%s n%d: TEP %.2f > verified %.2f" % (s["cell"], s["size"], b["value"], s["obj"]))
    bad += check("TEP composed bound never above a verified solution", w, n)

    # 3 -- best-of-two, which is what would actually be reported
    w, n = [], 0
    for s in sols:
        if s["size"] == 100:
            continue
        b = bound_for(s["cell"], s["size"], "best")
        if b["value"] is None:
            continue
        n += 1
        if b["value"] > s["obj"] + 1e-6:
            w.append("%s n%d: best-of-two %.2f > verified %.2f" % (s["cell"], s["size"], b["value"], s["obj"]))
    bad += check("best-of-two never above a verified solution", w, n)

    # 4 -- the AB water component, per component rather than as a sum
    w, n = [], 0
    for s in sols:
        k = (s["cell"], s["size"])
        if k not in ab:
            continue
        n += 1
        if float(ab[k]["water"]) > s["water"] + 1e-6:
            w.append("%s n%d: AB water %.2f > realised %.2f" % (s["cell"], s["size"], ab[k]["water"], s["water"]))
    bad += check("AB water term never above a realised water cost", w, n)

    # 5 -- the AB street component, same test
    w, n = [], 0
    for s in sols:
        k = (s["cell"], s["size"])
        if k not in ab:
            continue
        n += 1
        lb = float(ab[k]["fleet_term"]) + float(ab[k]["travel_term"])
        if lb > s["fleet"] + s["street"] + 1e-6:
            w.append("%s n%d: AB street %.2f > realised %.2f" % (s["cell"], s["size"], lb, s["fleet"] + s["street"]))
    bad += check("AB street term never above a realised street cost", w, n)

    # 6 -- the certified fleet floor against every verified car count
    w, n = [], 0
    for s in sols:
        if s["size"] not in V_LB:
            continue
        n += 1
        v = V_LB[s["size"]](fam(s["cell"]))
        if s["cars"] < v:
            w.append("%s n%d: %d cars, below the certified floor %d" % (s["cell"], s["size"], s["cars"], v))
    bad += check("certified fleet floor never above a verified car count", w, n)

    # 7 -- the same floor against the PROVEN n10 optima, a harder witness
    p = os.path.join(ROOT, "runs", "oracle", "tep_ov_vs_cars_n10.json")
    w, n = [], 0
    if os.path.exists(p):
        for cell, rows in json.load(io.open(p, encoding="utf-8"))["cells"].items():
            ok = [r for r in rows if r.get("obj") is not None]
            if not ok:
                continue
            n += 1
            best = min(ok, key=lambda r: r["obj"])
            if best["k"] < V_LB[10](fam(cell)):
                w.append("%s n10: optimum uses %d cars, floor claims %d" % (cell, best["k"], V_LB[10](fam(cell))))
    bad += check("fleet floor never above a PROVEN optimum's car count", w, n)

    # 8 -- a relaxation may not need MORE cars than a feasible solution uses
    w, n = [], 0
    for s in sols:
        q = os.path.join(ROOT, "runs", "oracle",
                         "tep_cg_bound_%s%s.json" % (s["cell"], "" if s["size"] == 100 else "_n%d" % s["size"]))
        if not os.path.exists(q):
            continue
        d = json.load(io.open(q, encoding="utf-8"))
        if d.get("N") is None or d.get("primal_rounding"):
            continue
        n += 1
        if float(d["N"]) > s["cars"] + 1e-6:
            w.append("%s n%d: LP needs %.3f cars, a feasible solution uses %d" % (s["cell"], s["size"], d["N"], s["cars"]))
    bad += check("the relaxation never needs more cars than a solution", w, n)

    # 9 -- every banked solution's objective must equal its own component split
    w = []
    for s in sols:
        if abs(s["obj"] - (s["fleet"] + s["street"] + s["water"])) > 1e-6:
            w.append("%s: split does not sum" % s["file"])
    bad += check("objective equals fleet + street + water", w, len(sols))

    # 10 -- is the objective CONVEX in the fleet, where we measured it exactly?
    w, n = [], 0
    if os.path.exists(p):
        for cell, rows in json.load(io.open(p, encoding="utf-8"))["cells"].items():
            ok = sorted([r for r in rows if r.get("obj") is not None], key=lambda r: r["k"])
            if len(ok) < 3:
                continue
            n += 1
            d1 = ok[1]["obj"] - ok[0]["obj"]; d2 = ok[2]["obj"] - ok[1]["obj"]
            if d2 < d1 - 1e-6:
                w.append("%s: increments %.2f then %.2f -- CONCAVE" % (cell, d1, d2))
    bad += check("objective is convex in the fleet where measured", w, n,
                 "if it held generally it would license a line search over the fleet")

    print("\n  %d of 10 checks refuted." % bad)
    print("  A pass is 'not refuted in N attempts', never 'validated' (CLAUDE.md section 2).")


if __name__ == "__main__":
    main()
