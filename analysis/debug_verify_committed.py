"""DEBUG HARNESS for analysis/verify_committed.py. Seven passes. Pass 1 is the decisive one.

AUTHOR, 2026-09-18: *"You will have to code a new verifier right? Debug it 7 times."*

Correct, and the exposure is real: the schedule-validity census rests entirely on
`verify_committed._check_committed`, which I wrote in the same hours as nine errors, and which so
far has been "validated" only by agreeing with a corpus. Agreement with a corpus is not a test --
a checker blind to a constraint agrees with every clean corpus there is.

PASS 1 -- CP-SAT EQUIVALENCE. The decisive one, and the only one that needs no judgement.
Build the verifier's OWN model (verifier.py:223-280), then FIX every h and u to the committed
value and solve. CP-SAT then answers exactly one question: "does the committed assignment satisfy
this model?" My hand evaluation answers the same question. THEY MUST AGREE ON EVERY SOLUTION.
Any disagreement is a bug in my code, located mechanically, with no interpretation involved.

This catches what the |C| = 20 positive control cannot. A checker missing a constraint reports
every n20 schedule VALID and passes that control silently; it cannot pass this one, because
CP-SAT still has the constraint the checker dropped.

PASSES 2-7 are in `main()` and each is reported separately; none of them is a substitute for 1.

NOTHING HERE MODIFIES verifier.py. The model is rebuilt from the same source lines, not patched.
"""
import glob, json, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SCALE = 1000


def cpsat_check_committed(inst, routes, hub_of, tset, vroutes, H, U):
    """verifier.py:223-280's model with h and u FIXED to the committed values.

    Transcribed from the same lines the checker transcribes, but posted to CP-SAT instead of
    evaluated. Returns (True|False|None, detail). None = solver could not decide.
    """
    from ortools.sat.python import cp_model
    D, nd = inst.D, inst.nodes
    CDC, depot, tau = inst.CDC, inst.depot, inst.tau
    lo = lambda x: int(math.floor(x * SCALE))
    hi = lambda x: int(math.ceil(x * SCALE))
    S = lambda x: int(round(x * SCALE))

    m = cp_model.CpModel()
    h, u = {}, {}
    for r in routes:
        for c in r:
            if c not in H:
                return None, "committed h missing for %s" % c
            h[c] = m.NewIntVar(lo(nd[c].earliest), hi(nd[c].latest), "h_%s" % c)
            m.Add(h[c] == S(H[c]))                       # FIX to the committed value
    for c in tset:
        if c not in U:
            return None, "committed u missing for %s" % c
        u[c] = m.NewIntVar(lo(nd[CDC].earliest), hi(nd[CDC].latest), "u_%s" % c)
        m.Add(u[c] == S(U[c]))                           # FIX to the committed value

    for r in routes:
        prev, prev_xfer = depot, False
        for c in r:
            if prev == depot:
                m.Add(h[c] >= lo(nd[depot].earliest + D[depot][c]))
            elif prev_xfer:
                q = hub_of[prev]
                m.Add(h[c] >= u[prev] + lo(tau + D[q][c]))
            else:
                m.Add(h[c] >= h[prev] + lo(nd[prev].service + D[prev][c]))
            m.Add(h[c] <= hi(nd[depot].latest - D[c][depot] - nd[c].service - tau))
            if c in tset:
                p = hub_of[c]
                m.Add(u[c] >= h[c] + lo(nd[c].service + D[c][p]))
                m.Add(u[c] >= lo(nd[CDC].earliest + D[CDC][p]))
                m.Add(u[c] <= hi(nd[CDC].latest - tau - D[p][CDC]))
                prev_xfer = True
            else:
                prev_xfer = False
            prev = c
        if r and r[-1] in tset:
            q = hub_of[r[-1]]
            m.Add(u[r[-1]] <= hi(nd[depot].latest - tau - D[q][depot]))

    for vr in vroutes:
        for a, b in zip(vr, vr[1:]):
            if a in hub_of and b in hub_of:
                m.Add(u[b] >= u[a] + lo(tau + D[hub_of[a]][hub_of[b]]))

    if tau > 0:
        by_sat = {}
        for c in tset:
            by_sat.setdefault(hub_of[c], []).append(c)
        dur = lo(tau)
        for p, members in by_sat.items():
            if len(members) < 2:
                continue
            m.AddNoOverlap([m.NewFixedSizeIntervalVar(u[c], dur, "iv_%s" % c) for c in members])

    sol = cp_model.CpSolver()
    sol.parameters.max_time_in_seconds = 30.0
    sol.parameters.num_search_workers = 4
    st = sol.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return True, "committed assignment satisfies the model"
    if st == cp_model.INFEASIBLE:
        return False, "committed assignment violates the model"
    return None, "CP-SAT undetermined (%s)" % sol.StatusName(st)


def pass1_equivalence(pattern, limit=None):
    """My hand evaluation vs CP-SAT on the SAME fixed assignment. They must agree everywhere."""
    import verifier as V
    from analysis.verify_committed import _check_committed, _resolve_tau, resolve_proximity

    agree = disagree = undecided = skipped = 0
    rows = []
    files = sorted(glob.glob(os.path.join(ROOT, pattern)))
    if limit:
        files = files[:limit]
    for p in files:
        m = re.search(r"_((?:C|R|RC)\d{3})_n(\d+)", os.path.basename(p))
        if not m:
            continue
        cell, size = m.group(1), int(m.group(2))
        try:
            sol = json.load(open(p, encoding="utf-8"))
        except Exception:
            skipped += 1
            continue
        H = {int(k): v for k, v in (sol.get("hi") or {}).items()}
        U = {int(k): v for k, v in (sol.get("ui") or {}).items()}
        if not H or not U:
            skipped += 1
            continue
        # THE PROXIMITY THE RUN ACTUALLY USED, not K's table for the size. Pass 1's VERDICT is
        # proximity-agnostic (both sides get the same `inst`), but the instance still has to be
        # the one the dump was built on, or the violations being agreed about are d209's artifacts
        # rather than the corpus's. Measured: at k_proximity(100)=0.1 the verifier fails earlier
        # on cov_RC202/RC205_n100 and the check never fires at all; at the run's own 0.0 it does.
        try:
            prox, psrc = resolve_proximity(sol, p)
            if prox is None:
                rows.append((cell, size, "NO-PROX", "proximity unresolved -- not evaluated"))
                skipped += 1
                continue
            tau = _resolve_tau(cell, size, prox)
            inst = V.VInstance(cell, size, wls=0.1, tau=tau, proximity=prox)
        except Exception as e:
            rows.append((cell, size, "SETUP-ERR", type(e).__name__))
            skipped += 1
            continue

        cap = {}
        orig = V._schedule_feasible

        def intercept(inst_, routes, hub_of, tset, vroutes):
            cap["mine"] = _check_committed(inst_, routes, hub_of, tset, vroutes, H, U)
            cap["cp"] = cpsat_check_committed(inst_, routes, hub_of, tset, vroutes, H, U)
            return True, "debug"
        V._schedule_feasible = intercept
        try:
            V.verify(inst, sol)
        except Exception as e:
            rows.append((cell, size, "VERIFY-ERR", type(e).__name__))
            skipped += 1
            continue
        finally:
            V._schedule_feasible = orig

        if "mine" not in cap or "cp" not in cap:
            skipped += 1                      # the check never fired (tau==0, or <2 per satellite)
            continue
        bad, missing = cap["mine"]
        mine_ok = (not bad) and (not missing)
        cp_ok, detail = cap["cp"]
        if cp_ok is None:
            undecided += 1
            rows.append((cell, size, "UNDECIDED", detail))
        elif mine_ok == cp_ok:
            agree += 1
        else:
            disagree += 1
            rows.append((cell, size, "DISAGREE",
                         "mine=%s cpsat=%s | %s" % (mine_ok, cp_ok,
                                                    ", ".join("%s(%s,%.4f)" % b for b in bad[:3]))))
    return agree, disagree, undecided, skipped, rows


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "runs/solutions/*_n20*.json"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    print(__doc__.split("PASSES 2-7")[0].strip())
    print()
    print("PASS 1 -- CP-SAT EQUIVALENCE on %s" % pattern)
    a, d, u, s, rows = pass1_equivalence(pattern, limit)
    print("  agree      : %d" % a)
    print("  DISAGREE   : %d   <-- any nonzero is a BUG IN MY CHECKER" % d)
    print("  undecided  : %d" % u)
    print("  skipped    : %d   (no committed timetable, or the check never fires)" % s)
    for r in rows[:15]:
        print("    %-7s n%-4d %-11s %s" % r)
    print()
    print("  VERDICT: %s" % ("PASS 1 CLEAN -- the checker agrees with the verifier's own model"
                             if d == 0 and a > 0 else
                             "PASS 1 FAILED -- do not run the census" if d else
                             "PASS 1 INCONCLUSIVE -- nothing was actually compared"))
    return 1 if d else 0


if __name__ == "__main__":
    sys.exit(main())
