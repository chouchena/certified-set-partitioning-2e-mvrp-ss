"""SMOKE SUITE for analysis/verify_arith.py -- the arithmetic verifier variant.

Eight smokes. Each states what it would take for the smoke to pass while the tool is broken,
because a smoke that cannot fail is decoration.

S1 KNOWN-GOOD          the two frozen certificates must come back fully ok on all three legs.
                       Fails silently if the tool accepts everything -> S2 is its counterweight.
S2 KNOWN-BAD           the 14 n100 dumps known to violate (26) must be flagged, and the two known
                       clean ones (R203, R209) must not. Directional, so "accept everything" and
                       "reject everything" both die here.
S3 CROSS-CHECK         verdicts must agree with analysis/verify_committed.py, which is itself
                       pinned to the verifier's own CP-SAT model by debug pass 1 (d223/d226).
                       Disagreement is a finding either way.
S4 FAULT PER CLASS     one injected fault per constraint class; each must fire at the injected
                       magnitude. A checker blind to one class passes S1-S3 and dies here.
S5 STRUCTURE FAULTS    break the routing itself -- sever an arc, miscount nCars, miscount
                       nVessel, orphan a transfer -- and LEG 1 must catch each.
S6 OBJECTIVE TAMPER    perturb the claimed objVal; LEG 3 must refuse it. Guards the case where
                       obj_matches is computed but never consulted.
S7 NO SOLVER           ortools must NOT be in sys.modules after a full verification. This is the
                       whole claim of the variant, asserted mechanically rather than by reading.
S8 DETERMINISM         two runs over the same file must give byte-identical findings.
"""
import copy, glob, importlib, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CERTS = sorted(glob.glob(os.path.join(ROOT, "validation/certificates/*_solution.json")))
N100 = sorted(glob.glob(os.path.join(ROOT, "runs/solutions/*_n100*.json")))
KNOWN_CLEAN = {"cov_R203_n100_s0.json", "cov_R209_n100_s0.json"}
KNOWN_NOTT = {"cov_C207_n100_s0.json"}


def _p(name, ok, detail=""):
    print("  %-22s %s   %s" % (name, "PASS" if ok else "*** FAIL ***", detail))
    return ok


def s1_known_good():
    import analysis.verify_arith as A
    A.FORCE_PROX = 0.0            # n20: all 700 n20 runs used 0.0 and K's table3/4 is 0.0
    ok = True
    for p in CERTS:
        res, _ = A.verify_file(p)
        good = (not res.structure and not res.timetable and not res.missing
                and res.obj_matches is True)
        ok = ok and good
        print("      %-44s struct %d  timetable %d  OV %s"
              % (os.path.basename(p)[:44], len(res.structure), len(res.timetable),
                 res.obj_matches))
    A.FORCE_PROX = None
    return _p("S1 known-good", ok, "%d certificates" % len(CERTS))


def s2_known_bad():
    import analysis.verify_arith as A
    viol = clean = notchecked = 0
    wrong = []
    for p in N100:
        b = os.path.basename(p)
        res, _ = A.verify_file(p)
        if res.notes and "NOT-CHECKED" in res.notes[0]:
            notchecked += 1
            if b not in KNOWN_NOTT:
                wrong.append("unexpected NOT-CHECKED %s" % b)
            continue
        if res.timetable:
            viol += 1
            if b in KNOWN_CLEAN:
                wrong.append("flagged a known-clean %s" % b)
        else:
            clean += 1
            if b not in KNOWN_CLEAN:
                wrong.append("passed a known-violating %s" % b)
    ok = (not wrong) and viol == 14 and clean == 2 and notchecked == 1
    return _p("S2 known-bad", ok, "violating %d (want 14), clean %d (want 2), not-checked %d "
              "(want 1)%s" % (viol, clean, notchecked,
                              ("  " + "; ".join(wrong[:3])) if wrong else ""))


def s3_cross_check():
    import analysis.verify_arith as A
    from analysis.verify_committed import _check_committed
    agree = disagree = skipped = 0
    detail = []
    for p in N100:
        res, ctx = A.verify_file(p)
        if ctx is None or (res.notes and "NOT-CHECKED" in res.notes[0]):
            skipped += 1
            continue
        inst, routes, hub_of, tset, vroutes, H, U = ctx
        bad, miss = _check_committed(inst, routes, hub_of, tset, vroutes, H, U)
        mine = bool(res.timetable)
        theirs = bool(bad)
        if mine == theirs:
            agree += 1
        else:
            disagree += 1
            detail.append("%s mine=%s committed=%s" % (os.path.basename(p), mine, theirs))
    return _p("S3 cross-check", disagree == 0,
              "agree %d, disagree %d, skipped %d%s"
              % (agree, disagree, skipped, ("  " + "; ".join(detail[:3])) if detail else ""))


def s4_fault_per_class():
    import analysis.verify_arith as A
    EPS = 0.5
    path = os.path.join(ROOT, "runs/solutions/cov_R203_n100_s0.json")   # known-clean baseline
    res0, ctx = A.verify_file(path)
    inst, routes, hub_of, tset, vroutes, H, U = ctx
    D, nd = inst.D, inst.nodes
    CDC, depot, tau = inst.CDC, inst.depot, inst.tau

    def run(H2, U2):
        r = A.Result(path)
        A.check_timetable(inst, routes, hub_of, tset, vroutes, H2, U2, r)
        return r

    def fired(r, cls, node):
        return any(k.split("-satellite")[0] == cls and c == node and abs(d - EPS) <= 0.01
                   for k, c, d in r.timetable)

    route = next(r for r in routes if len(r) >= 3 and any(c in tset for c in r))
    c0 = route[0]
    plain = xfer = None
    prev, px = depot, False
    for c in route:
        if prev != depot and not px and plain is None:
            plain = (prev, c)
        if px and xfer is None:
            xfer = (prev, c)
        px = c in tset
        prev = c
    tc = next(c for c in route if c in tset)
    results = {}

    def att(cls, node, H2=None, U2=None):
        results[cls] = fired(run(H2 or dict(H), U2 or dict(U)), cls, node)

    H2 = dict(H); H2[c0] = nd[c0].earliest - EPS;                       att("S-TW-lower", c0, H2)
    H2 = dict(H); H2[c0] = nd[c0].latest + EPS;                         att("S-TW-upper", c0, H2)
    H2 = dict(H); H2[c0] = nd[depot].earliest + D[depot][c0] - EPS;     att("arc-from-depot", c0, H2)
    if plain:
        a, b = plain
        H2 = dict(H); H2[b] = H[a] + nd[a].service + D[a][b] - EPS;     att("arc-plain", b, H2)
    if xfer:
        a, b = xfer
        q = hub_of[a]
        H2 = dict(H); H2[b] = U[a] + tau + D[q][b] - EPS;               att("arc-after-transfer", b, H2)
    H2 = dict(H)
    H2[c0] = nd[depot].latest - D[c0][depot] - nd[c0].service - tau + EPS
    att("S-TW-DEP-UB", c0, H2)
    p = hub_of[tc]
    U2 = dict(U); U2[tc] = H[tc] + nd[tc].service + D[tc][p] - EPS;     att("xfer-after-service", tc, None, U2)
    U2 = dict(U); U2[tc] = nd[CDC].earliest + D[CDC][p] - EPS;          att("sync-CDC-lower", tc, None, U2)
    U2 = dict(U); U2[tc] = nd[CDC].latest - tau - D[p][CDC] + EPS;      att("sync-CDC-upper", tc, None, U2)
    last = route[-1]
    if last in tset:
        q = hub_of[last]
        U2 = dict(U); U2[last] = nd[depot].latest - tau - D[q][depot] + EPS
        att("multitrip-return", last, None, U2)
    for vr in vroutes:
        pair = next(((a, b) for a, b in zip(vr, vr[1:])
                     if a in hub_of and b in hub_of and a in U and b in U), None)
        if pair:
            a, b = pair
            U2 = dict(U); U2[b] = U[a] + tau + D[hub_of[a]][hub_of[b]] - EPS
            att("vessel-seq", b, None, U2)
            break
    by = {}
    for c in tset:
        by.setdefault(hub_of[c], []).append(c)
    for sat, mem in by.items():
        mem = [c for c in mem if c in U]
        if len(mem) >= 2:
            s = sorted(mem, key=lambda c: U[c])
            U2 = dict(U); U2[s[1]] = U[s[0]] + tau - EPS
            att("c26", s[1], None, U2)
            break
    missed = sorted(k for k, v in results.items() if not v)
    return _p("S4 fault per class", not missed and len(results) == 12,
              "%d/%d classes fired%s" % (sum(results.values()), len(results),
                                         ("  MISSED: " + ", ".join(missed)) if missed else ""))


def s5_structure_faults():
    import analysis.verify_arith as A
    path = os.path.join(ROOT, "runs/solutions/cov_R203_n100_s0.json")
    sol0 = json.load(open(path, encoding="utf-8"))
    got = A.resolve(sol0, path)
    import verifier as V
    inst = V.VInstance(got[0], got[1], wls=0.1, tau=got[3], proximity=got[2])
    base = A.derive(sol0, inst)[4]
    cases = {}
    s = copy.deepcopy(sol0); s["nCars"] = (s.get("nCars") or 1) + 1
    cases["nCars miscount"] = A.derive(s, inst)[4]
    s = copy.deepcopy(sol0); s["nVessel"] = (s.get("nVessel") or 1) + 1
    cases["nVessel miscount"] = A.derive(s, inst)[4]
    s = copy.deepcopy(sol0); s["xij"] = s["xij"][:-1]
    cases["severed street arc"] = A.derive(s, inst)[4]
    s = copy.deepcopy(sol0); s["yij"] = s["yij"][:-1]
    cases["severed vessel arc"] = A.derive(s, inst)[4]
    s = copy.deepcopy(sol0); s["vi"] = s["vi"][:-1]
    cases["orphaned transfer"] = A.derive(s, inst)[4]
    ok = (len(base) == 0) and all(len(v) > len(base) for v in cases.values())
    for k, v in cases.items():
        print("      %-22s baseline %d -> %d problem(s)%s"
              % (k, len(base), len(v), ("   " + v[0][:52]) if v else "   *** NOT CAUGHT ***"))
    return _p("S5 structure faults", ok, "baseline clean=%s" % (len(base) == 0))


def s6_objective_tamper():
    import analysis.verify_arith as A
    path = os.path.join(ROOT, "runs/solutions/cov_R203_n100_s0.json")
    res, ctx = A.verify_file(path)
    inst, routes, hub_of, tset, vroutes, H, U = ctx
    sol = json.load(open(path, encoding="utf-8"))
    good = res.obj_matches is True
    sol2 = copy.deepcopy(sol); sol2["objVal"] = sol["objVal"] + 0.01
    r2 = A.Result(path)
    A.check_objective(inst, sol2, hub_of, tset, r2)
    caught = r2.obj_matches is False
    return _p("S6 objective tamper", good and caught,
              "clean OV accepted=%s, +0.01 refused=%s" % (good, caught))


def s7_no_solver():
    """The entire claim of this variant, asserted rather than believed."""
    for m in [k for k in list(sys.modules) if k.startswith("ortools")]:
        del sys.modules[m]
    import analysis.verify_arith as A
    A.verify_file(os.path.join(ROOT, "runs/solutions/cov_R204_n100_s0.json"))
    loaded = sorted(k for k in sys.modules if k.startswith("ortools"))
    return _p("S7 no solver", not loaded,
              "ortools modules loaded after a full verification: %d %s"
              % (len(loaded), loaded[:2]))


def s8_determinism():
    import analysis.verify_arith as A
    path = os.path.join(ROOT, "runs/solutions/cov_RC201_n100_s0.json")
    a, _ = A.verify_file(path)
    b, _ = A.verify_file(path)
    same = (sorted(a.timetable) == sorted(b.timetable)
            and a.obj_recomputed == b.obj_recomputed
            and sorted(a.structure) == sorted(b.structure))
    return _p("S8 determinism", same, "%d findings, identical on repeat" % len(a.timetable))


def main():
    print(__doc__.strip())
    print()
    print("SMOKES")
    results = []
    for fn in (s1_known_good, s2_known_bad, s3_cross_check, s4_fault_per_class,
               s5_structure_faults, s6_objective_tamper, s7_no_solver, s8_determinism):
        try:
            results.append(fn())
        except Exception as e:
            results.append(_p(fn.__name__, False, "EXCEPTION %s: %s" % (type(e).__name__, str(e)[:60])))
    print()
    print("  %d/%d smokes pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
