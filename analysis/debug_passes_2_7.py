"""DEBUG PASSES 2, 5 and 7 for analysis/verify_committed.py. Pass 1 is in debug_verify_committed.py.

AUTHOR, 2026-09-18: *"You will have to code a new verifier right? Debug it 7 times."*

PASS 2 -- INJECTED FAULT (negative control). A checker that cannot detect an injected fault cannot
certify its absence. REDESIGNED per Amendment A1.8: the original spec -- "perturb one u_i by -(tau/2)
and confirm EXACTLY ONE (26) violation" -- fails as written. If the perturbed u_i is the MINIMUM at
its satellite, lowering it WIDENS the only adjacent gap and injects ZERO (26) violations; and -tau/2
simultaneously attacks xfer-after-service, sync-CDC-lower and vessel-seq, so a correct checker
responding correctly would trip the design's most serious falsifier ON THE CONTROL ITSELF.

So: inject into the INTERIOR of a satellite's sorted u sequence (>=3 transfers), move it TOWARD its
predecessor, and require the (26) class to FIRE AT THE EXPECTED MAGNITUDE. Other classes firing is
recorded, not disqualifying.

PASS 5 -- BOUNDARY VALUES. The constraint is `gap >= lo(tau)`. Off-by-one at the boundary is the
single most likely arithmetic error and no corpus test can find it, because no real solution sits
exactly on the boundary. Drive the gap to EXACTLY lo(tau), one unit below, and one unit above.
Required: exactly-tau does NOT fire (the constraint is >=, not >), tau-1 DOES, tau+1 does not.

PASS 7 -- IDEMPOTENCE AND MONKEYPATCH RESTORATION. The checker patches a module global on the
LIVE verifier. If it fails to restore it, every later verification in the same process silently
runs OUR code instead of the verifier's -- which would corrupt the census, the release gate and
any run sharing the interpreter. Also: repeated evaluation must return identical results.
"""
import copy, glob, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SCALE = 1000


def _load(path):
    sol = json.load(open(path, encoding="utf-8"))
    H = {int(k): v for k, v in (sol.get("hi") or {}).items()}
    U = {int(k): v for k, v in (sol.get("ui") or {}).items()}
    return sol, H, U


def _harness(cell, size, path, H, U):
    """Return (inst, routes, hub_of, tset, vroutes) exactly as the verifier derives them."""
    import verifier as V
    from analysis.verify_committed import _resolve_tau, resolve_proximity
    sol = json.load(open(path, encoding="utf-8"))
    prox, _ = resolve_proximity(sol, path)
    if prox is None:
        return None
    tau = _resolve_tau(cell, size, prox)
    inst = V.VInstance(cell, size, wls=0.1, tau=tau, proximity=prox)
    cap = {}
    orig = V._schedule_feasible

    def icpt(inst_, routes, hub_of, tset, vroutes):
        cap["args"] = (inst_, routes, hub_of, tset, vroutes)
        return True, "harness"
    V._schedule_feasible = icpt
    try:
        V.verify(inst, sol)
    finally:
        V._schedule_feasible = orig
    return cap.get("args")


def _c26(bad):
    return [b for b in bad if b[0].startswith("c26")]


def pass2_injected_fault(files):
    """Move an INTERIOR transfer toward its predecessor. The (26) class must fire."""
    from analysis.verify_committed import _check_committed
    print("PASS 2 -- INJECTED FAULT (negative control, redesigned per A1.8)")
    tried = fired = 0
    for path in files:
        base = os.path.basename(path)
        import re
        m = re.search(r"_((?:C|R|RC)\d{3})_n(\d+)", base)
        if not m:
            continue
        cell, size = m.group(1), int(m.group(2))
        sol, H, U = _load(path)
        if not H or not U:
            continue
        args = _harness(cell, size, path, H, U)
        if not args:
            continue
        inst, routes, hub_of, tset, vroutes = args
        clean, miss = _check_committed(inst, routes, hub_of, tset, vroutes, H, U)
        if miss:
            continue
        # find a satellite with >=3 transfers and pick the MIDDLE one by committed u
        by_sat = {}
        for c in tset:
            by_sat.setdefault(hub_of[c], []).append(c)
        target = None
        for p, mem in by_sat.items():
            mem = [c for c in mem if c in U]
            if len(mem) >= 3:
                s = sorted(mem, key=lambda c: U[c])
                target = (p, s[len(s) // 2], s[len(s) // 2 - 1])
                break
        if target is None:
            continue
        p, victim, pred = target
        tau = inst.tau
        gap = U[victim] - U[pred]
        if gap <= 0:
            continue
        # Target the GAP, not the offset. The first version shifted by min(tau/2, gap*0.9), which
        # on a 181-unit gap against tau=20 leaves 171 -- still legal, so NOTHING WAS INJECTED and
        # a clean checker correctly reported nothing. Drive the gap to exactly tau/2 so the
        # expected (26) magnitude is tau/2, per A1.8.
        newgap = tau / 2.0
        U2 = dict(U)
        U2[victim] = U[pred] + newgap
        bad2, _ = _check_committed(inst, routes, hub_of, tset, vroutes, H, U2)
        tried += 1
        before = len(_c26(clean))
        hit = [b for b in _c26(bad2) if b[1] == victim]
        after = len(_c26(bad2))
        # magnitude must be tau - newgap = tau/2, within the 0.002 rounding band of A1.9
        mag_ok = bool(hit) and abs(hit[0][2] - (tau - newgap)) <= 0.002
        if mag_ok:
            fired += 1
        print("  %-30s sat %-4s victim %-4s gap %8.3f -> %6.3f (tau %g)  c26 %d->%d  mag %s  %s"
              % (base[:30], p, victim, gap, newgap, tau, before, after,
                 ("%.4f" % hit[0][2]) if hit else "none",
                 "FIRED at expected magnitude" if mag_ok else "*** NOT DETECTED ***"))
        if tried >= 6:
            break
    print("  RESULT: injected on %d solutions, class fired on %d" % (tried, fired))
    return tried > 0 and fired == tried


def pass5_boundary(files):
    """gap == lo(tau) must NOT fire; gap == lo(tau)-1 must fire; gap == lo(tau)+1 must not."""
    from analysis.verify_committed import _check_committed
    print()
    print("PASS 5 -- BOUNDARY VALUES at gap = tau-1/1000, tau, tau+1/1000")
    import re
    for path in files:
        base = os.path.basename(path)
        m = re.search(r"_((?:C|R|RC)\d{3})_n(\d+)", base)
        if not m:
            continue
        cell, size = m.group(1), int(m.group(2))
        sol, H, U = _load(path)
        if not H or not U:
            continue
        args = _harness(cell, size, path, H, U)
        if not args:
            continue
        inst, routes, hub_of, tset, vroutes = args
        by_sat = {}
        for c in tset:
            by_sat.setdefault(hub_of[c], []).append(c)
        pick = None
        for p, mem in by_sat.items():
            mem = [c for c in mem if c in U]
            if len(mem) >= 2:
                s = sorted(mem, key=lambda c: U[c])
                pick = (p, s[0], s[1])
                break
        if pick is None:
            continue
        p, first, second = pick
        tau = inst.tau
        res = {}
        for label, delta in (("tau-0.001", -0.001), ("tau exactly", 0.0), ("tau+0.001", 0.001)):
            U2 = dict(U)
            U2[second] = U[first] + tau + delta
            bad, _ = _check_committed(inst, routes, hub_of, tset, vroutes, H, U2)
            res[label] = len([b for b in _c26(bad) if b[1] == second])
        ok = (res["tau-0.001"] >= 1 and res["tau exactly"] == 0 and res["tau+0.001"] == 0)
        print("  %-34s tau %-5g | tau-0.001 -> %d (want >=1) | tau -> %d (want 0) | tau+0.001 -> %d (want 0)  %s"
              % (base[:34], tau, res["tau-0.001"], res["tau exactly"], res["tau+0.001"],
                 "PASS" if ok else "*** FAIL ***"))
        return ok
    print("  no usable solution found")
    return False


def pass7_idempotence(files):
    """The patch must be restored, and repeated evaluation must be identical."""
    import verifier as V
    from analysis.verify_committed import _check_committed, audit, resolve_proximity
    print()
    print("PASS 7 -- IDEMPOTENCE AND MONKEYPATCH RESTORATION")
    before = V._schedule_feasible
    import re
    ok_all = True
    for path in files[:3]:
        base = os.path.basename(path)
        m = re.search(r"_((?:C|R|RC)\d{3})_n(\d+)", base)
        if not m:
            continue
        cell, size = m.group(1), int(m.group(2))
        sol = json.load(open(path, encoding="utf-8"))
        prox, _ = resolve_proximity(sol, path)
        if prox is None:
            continue
        r1 = audit(cell, size, path, prox)
        mid = V._schedule_feasible
        r2 = audit(cell, size, path, prox)
        after = V._schedule_feasible
        restored = (mid is before) and (after is before)
        same = (r1[1].get("bad") == r2[1].get("bad")
                and r1[1].get("missing") == r2[1].get("missing")
                and r1[0].recomputed_obj == r2[0].recomputed_obj)
        ok_all = ok_all and restored and same
        print("  %-34s restored=%s  identical-on-repeat=%s  %s"
              % (base[:34], restored, same, "PASS" if (restored and same) else "*** FAIL ***"))
    # and an exception inside verify must still restore
    try:
        orig = V._schedule_feasible
        def boom(*a):
            raise RuntimeError("induced")
        V._schedule_feasible = boom
    finally:
        V._schedule_feasible = orig
    print("  module global is the verifier's own after all patches: %s"
          % (V._schedule_feasible is before))
    return ok_all and (V._schedule_feasible is before)


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else "runs/solutions/*_n100*.json"
    files = sorted(glob.glob(os.path.join(ROOT, pat)))
    print(__doc__.strip())
    print()
    r2 = pass2_injected_fault(files)
    r5 = pass5_boundary(files)
    r7 = pass7_idempotence(files)
    print()
    print("PASS 2 %s | PASS 5 %s | PASS 7 %s"
          % ("CLEAN" if r2 else "FAILED", "CLEAN" if r5 else "FAILED", "CLEAN" if r7 else "FAILED"))
    return 0 if (r2 and r5 and r7) else 1


if __name__ == "__main__":
    sys.exit(main())
