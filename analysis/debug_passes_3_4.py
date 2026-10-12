"""DEBUG PASSES 3 and 4 for analysis/verify_committed.py.

AUTHOR, 2026-09-18: *"You will have to code a new verifier right? Debug it 7 times."*

PASS 4 -- ONE INJECTED FAULT PER CONSTRAINT CLASS. Design audit 1, fix F6: pass 2 exercises ONE
of twelve classes, and the design's most serious falsifier is about the other eleven, "whose
sensitivity is never tested". A checker blind to `sync-CDC-upper` passes pass 1 (CP-SAT agrees
because the corpus never violates it), passes pass 2 (that injects (26)), passes the |C| = 20
control, and still certifies nothing about `sync-CDC-upper`.

METHOD. For each class, re-derive the SAME bound the checker uses, then set the committed value
0.5 units on the WRONG side of it -- far outside A1.9's 0.002 rounding band -- and require THAT
CLASS to fire at magnitude 0.5. Other classes firing is recorded, never disqualifying: h and u are
chained, so moving one value legitimately breaks several constraints at once, and A1.8 records that
demanding "exactly one" is what made the original negative control unrunnable.

PASS 3 -- SYNTHETIC KNOWN-GOOD. Pass 1 proves the checker agrees with CP-SAT; both could still
share a misreading of the instance. So build a timetable that is correct BY CONSTRUCTION -- take a
real routing and schedule it greedily at the earliest feasible time each constraint allows, which
is the textbook forward pass -- and require ZERO violations. If the checker rejects a schedule
built from its own stated bounds, its bounds and its comparisons disagree with each other.
"""
import glob, json, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SCALE = 1000
EPS = 0.5          # injection size: 250x the 0.002 rounding band


def harness(path):
    """(inst, routes, hub_of, tset, vroutes, H, U) exactly as the verifier derives them."""
    import verifier as V
    from analysis.verify_committed import _resolve_tau, resolve_proximity
    b = os.path.basename(path)
    m = re.search(r"_((?:C|R|RC)\d{3})_n(\d+)", b)
    if not m:
        return None
    cell, size = m.group(1), int(m.group(2))
    sol = json.load(open(path, encoding="utf-8"))
    H = {int(k): v for k, v in (sol.get("hi") or {}).items()}
    U = {int(k): v for k, v in (sol.get("ui") or {}).items()}
    if not H or not U:
        return None
    prox, _ = resolve_proximity(sol, path)
    if prox is None:
        return None
    tau = _resolve_tau(cell, size, prox)
    inst = V.VInstance(cell, size, wls=0.1, tau=tau, proximity=prox)
    cap = {}
    orig = V._schedule_feasible

    def icpt(inst_, routes, hub_of, tset, vroutes):
        cap["a"] = (inst_, routes, hub_of, tset, vroutes)
        return True, "harness"
    V._schedule_feasible = icpt
    try:
        V.verify(inst, sol)
    finally:
        V._schedule_feasible = orig
    if "a" not in cap:
        return None
    inst_, routes, hub_of, tset, vroutes = cap["a"]
    return inst_, routes, hub_of, tset, vroutes, H, U


def fire(inst, routes, hub_of, tset, vroutes, H, U, cls, node):
    from analysis.verify_committed import _check_committed
    bad, miss = _check_committed(inst, routes, hub_of, tset, vroutes, H, U)
    hit = [b for b in bad if b[0].split("-satellite")[0] == cls and b[1] == node]
    return hit, bad


def pass4(path):
    from analysis.verify_committed import _check_committed
    got = harness(path)
    if not got:
        return None
    inst, routes, hub_of, tset, vroutes, H, U = got
    D, nd = inst.D, inst.nodes
    CDC, depot, tau = inst.CDC, inst.depot, inst.tau
    base_bad, base_miss = _check_committed(inst, routes, hub_of, tset, vroutes, H, U)
    results = []

    def attempt(cls, node, newH=None, newU=None):
        H2 = dict(H) if newH is None else newH
        U2 = dict(U) if newU is None else newU
        hit, bad = fire(inst, routes, hub_of, tset, vroutes, H2, U2, cls, node)
        ok = bool(hit) and abs(hit[0][2] - EPS) <= 0.01
        results.append((cls, node, ok, hit[0][2] if hit else None, len(bad) - len(base_bad)))

    # pick a route with a transfer and at least 3 stops
    route = None
    for r in routes:
        if len(r) >= 3 and any(c in tset for c in r):
            route = r
            break
    if route is None:
        return None
    c0 = route[0]
    # a customer with a non-transfer predecessor, and one with a transfer predecessor
    plain_c = xfer_c = None
    prev, prev_x = depot, False
    for c in route:
        if prev != depot and not prev_x and plain_c is None:
            plain_c = (prev, c)
        if prev_x and xfer_c is None:
            xfer_c = (prev, c)
        prev_x = c in tset
        prev = c
    tc = next((c for c in route if c in tset), None)

    # 1/2 -- street time window on h
    H2 = dict(H); H2[c0] = nd[c0].earliest - EPS
    attempt("S-TW-lower", c0, newH=H2)
    H2 = dict(H); H2[c0] = nd[c0].latest + EPS
    attempt("S-TW-upper", c0, newH=H2)

    # 3 -- arc from depot
    H2 = dict(H); H2[c0] = (nd[depot].earliest + D[depot][c0]) - EPS
    attempt("arc-from-depot", c0, newH=H2)

    # 4 -- plain arc
    if plain_c:
        p, c = plain_c
        H2 = dict(H); H2[c] = (H[p] + nd[p].service + D[p][c]) - EPS
        attempt("arc-plain", c, newH=H2)

    # 5 -- arc after a transfer
    if xfer_c:
        p, c = xfer_c
        q = hub_of[p]
        H2 = dict(H); H2[c] = (U[p] + tau + D[q][c]) - EPS
        attempt("arc-after-transfer", c, newH=H2)

    # 6 -- depot upper bound
    H2 = dict(H)
    H2[c0] = (nd[depot].latest - D[c0][depot] - nd[c0].service - tau) + EPS
    attempt("S-TW-DEP-UB", c0, newH=H2)

    if tc is not None:
        p = hub_of[tc]
        # 7 -- transfer after service
        U2 = dict(U); U2[tc] = (H[tc] + nd[tc].service + D[tc][p]) - EPS
        attempt("xfer-after-service", tc, newU=U2)
        # 8/9 -- the two CDC synchronisation bounds
        U2 = dict(U); U2[tc] = (nd[CDC].earliest + D[CDC][p]) - EPS
        attempt("sync-CDC-lower", tc, newU=U2)
        U2 = dict(U); U2[tc] = (nd[CDC].latest - tau - D[p][CDC]) + EPS
        attempt("sync-CDC-upper", tc, newU=U2)

    # 10 -- multi-trip return, only if the route ENDS in a transfer
    last = route[-1]
    if last in tset:
        q = hub_of[last]
        U2 = dict(U); U2[last] = (nd[depot].latest - tau - D[q][depot]) + EPS
        attempt("multitrip-return", last, newU=U2)

    # 11 -- vessel sequencing
    for vr in vroutes:
        pair = None
        for a, b in zip(vr, vr[1:]):
            if a in hub_of and b in hub_of and a in U and b in U:
                pair = (a, b)
                break
        if pair:
            a, b = pair
            U2 = dict(U)
            U2[b] = (U[a] + tau + D[hub_of[a]][hub_of[b]]) - EPS
            attempt("vessel-seq", b, newU=U2)
            break

    # 12 -- constraint (26)
    by_sat = {}
    for c in tset:
        by_sat.setdefault(hub_of[c], []).append(c)
    for p, mem in by_sat.items():
        mem = [c for c in mem if c in U]
        if len(mem) >= 2:
            s = sorted(mem, key=lambda c: U[c])
            U2 = dict(U); U2[s[1]] = U[s[0]] + tau - EPS
            attempt("c26", s[1], newU=U2)
            break
    return results, len(base_bad), len(base_miss)


def pass3(path):
    """Greedy earliest-feasible forward pass -- correct BY CONSTRUCTION -- must give 0 violations."""
    from analysis.verify_committed import _check_committed
    got = harness(path)
    if not got:
        return None
    inst, routes, hub_of, tset, vroutes, H, U = got
    D, nd = inst.D, inst.nodes
    CDC, depot, tau = inst.CDC, inst.depot, inst.tau
    H2, U2 = {}, {}
    for r in routes:
        prev, prev_x = depot, False
        for c in r:
            if prev == depot:
                t = nd[depot].earliest + D[depot][c]
            elif prev_x:
                q = hub_of[prev]
                t = U2[prev] + tau + D[q][c]
            else:
                t = H2[prev] + nd[prev].service + D[prev][c]
            H2[c] = max(t, nd[c].earliest)
            if c in tset:
                p = hub_of[c]
                U2[c] = max(H2[c] + nd[c].service + D[c][p], nd[CDC].earliest + D[CDC][p])
                prev_x = True
            else:
                prev_x = False
            prev = c
    bad, miss = _check_committed(inst, routes, hub_of, tset, vroutes, H2, U2)
    # Only the LOWER-bound classes are guaranteed by a forward pass; upper bounds and (26) are
    # not, and a violation there is a property of the ROUTING, not of the checker. Report both.
    lower = {"S-TW-lower", "arc-from-depot", "arc-plain", "arc-after-transfer",
             "xfer-after-service", "sync-CDC-lower"}
    viol_lower = [b for b in bad if b[0].split("-satellite")[0] in lower]
    return len(bad), viol_lower, len(miss)


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else "runs/solutions/cov_R2*_n100_s0.json"
    files = sorted(glob.glob(os.path.join(ROOT, pat)))
    print(__doc__.strip())
    print()
    print("PASS 4 -- ONE INJECTED FAULT PER CONSTRAINT CLASS (magnitude %.1f, band 0.01)" % EPS)
    tested, passed, seen = 0, 0, {}
    for p in files[:3]:
        out = pass4(p)
        if not out:
            continue
        res, nb, nm = out
        print("  %s   (baseline: %d violations, %d missing)" % (os.path.basename(p), nb, nm))
        for cls, node, ok, mag, delta in res:
            tested += 1
            passed += 1 if ok else 0
            seen[cls] = seen.get(cls, 0) + (1 if ok else 0)
            print("     %-22s node %-5s  %-6s mag %-9s other classes %+d"
                  % (cls, node, "FIRED" if ok else "*** MISS ***",
                     ("%.4f" % mag) if mag is not None else "none", delta))
    print("  RESULT: %d/%d injections detected at the expected magnitude, %d distinct classes"
          % (passed, tested, len(seen)))
    missed = [c for c, n in seen.items() if n == 0]
    if missed:
        print("  CLASSES NEVER DETECTED: %s" % ", ".join(sorted(missed)))
    print()
    print("PASS 3 -- SYNTHETIC KNOWN-GOOD (greedy earliest-feasible forward pass)")
    p3ok = True
    for p in files[:3]:
        out = pass3(p)
        if not out:
            continue
        nbad, lower, nmiss = out
        ok = (len(lower) == 0)
        p3ok = p3ok and ok
        print("  %-30s lower-bound violations %d (want 0)  | all classes %d, missing %d  %s"
              % (os.path.basename(p)[:30], len(lower), nbad, nmiss,
                 "PASS" if ok else "*** FAIL ***"))
        for b in lower[:5]:
            print("        %s node %s by %.4f" % b)
    p4ok = (tested > 0 and passed == tested)
    print()
    print("PASS 4 %s | PASS 3 %s" % ("CLEAN" if p4ok else "FAILED",
                                     "CLEAN" if p3ok else "FAILED"))
    return 0 if (p4ok and p3ok) else 1


if __name__ == "__main__":
    sys.exit(main())
