"""VERIFIER VARIANT -- A PARALLEL DIAGNOSTIC. It does NOT replace verifier.py and must not.

AUTHOR, 2026-09-18: *"I meant variant because we won't drop current verifier until we have frozen
our bug analysis and replacing code stainless steel validity."* So: the incumbent verifier remains
the authority. This runs ALONGSIDE it, and where the two disagree that disagreement is the
finding, not a licence to switch. Nothing here may be used to re-classify a run until the analysis
is frozen and this code is proven.

CHECK THE TIMETABLE THE INCUMBENT ALREADY CARRIES. Never search for one.

AUTHOR, 2026-09-18: *"Create a real verifier variant which would inherit all incumbent data and
check it's validity and accuracy for OV (not searching again for timetable)."*

THE GAP THIS FILLS. `verifier._schedule_feasible(inst, routes, hub_of, tset, vroutes)` never
receives `h_i` or `u_i`. Every dumped incumbent carries them -- 101 `hi` and 35 `ui` on
R210/n100 -- and the verifier discards them and asks CP-SAT whether ANY timetable exists for the
routing. So a rejection says "I could not find a schedule", not "your schedule is wrong", and the
two are different statements. This variant asks the second question.

HOW IT AVOIDS MY OWN ERRORS. Twice tonight I hand-rolled a constraint-26 check and got it wrong --
it reported violations on runs the verifier ACCEPTED (R204, R205) and none on runs it REJECTED
(R203), so it had no relationship to the verdict. The lesson is not to re-implement. So this file:
  * does NOT reconstruct routes, hub_of, tset or vroutes -- it MONKEYPATCHES `_schedule_feasible`
    so those arrive exactly as the verifier itself derived them;
  * transcribes the constraints from the model at verifier.py:223-280 one-for-one, evaluating
    each with the committed h/u instead of posting it to CP-SAT;
  * uses the SAME permissive rounding (lo = floor, hi = ceil, SCALE = 1000) so a disagreement
    cannot be a rounding artifact.

WHAT IT REPORTS, per solution:
  1. OV ACCURACY -- the verifier's own objective recomputation (it already does this).
  2. TIMETABLE VALIDITY -- for the committed {h_i,u_i}, every constraint evaluated, with the
     violated ones named and the magnitude of each violation.

THE THREE OUTCOMES AND WHAT EACH MEANS:
  * committed timetable VALID, verifier said no-timetable-exists  -> the VERIFIER is wrong: it
    failed to find a schedule it was handed.
  * committed timetable VIOLATES a constraint                     -> the SOLVER is wrong: it
    committed to a schedule that does not satisfy the model.
  * committed timetable absent or partial                         -> neither; the incumbent does
    not carry what is needed and the question cannot be asked of it.
"""
import glob, json, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SCALE = 1000


def _check_committed(inst, routes, hub_of, tset, vroutes, H, U):
    """Evaluate verifier.py:223-280's constraints against the COMMITTED h/u. No search."""
    D, nd = inst.D, inst.nodes
    CDC, depot, tau = inst.CDC, inst.depot, inst.tau
    lo = lambda x: math.floor(x * SCALE)
    hi = lambda x: math.ceil(x * SCALE)
    S = lambda x: int(round(x * SCALE))
    bad, missing = [], []

    def h(c):
        if c not in H:
            missing.append(("h", c))
            return None
        return S(H[c])

    def u(c):
        if c not in U:
            missing.append(("u", c))
            return None
        return S(U[c])

    def rec(kind, c, lhs, rhs, op):
        if lhs is None or rhs is None:
            return
        if op == ">=" and lhs < rhs:
            bad.append((kind, c, (rhs - lhs) / SCALE))
        if op == "<=" and lhs > rhs:
            bad.append((kind, c, (lhs - rhs) / SCALE))

    for r in routes:
        for c in r:
            hc = h(c)
            rec("S-TW-lower", c, hc, lo(nd[c].earliest), ">=")
            rec("S-TW-upper", c, hc, hi(nd[c].latest), "<=")

    for r in routes:
        prev, prev_xfer = depot, False
        for c in r:
            hc = h(c)
            if prev == depot:
                rec("arc-from-depot", c, hc, lo(nd[depot].earliest + D[depot][c]), ">=")
            elif prev_xfer:
                q = hub_of[prev]
                rec("arc-after-transfer", c, hc,
                    (u(prev) + lo(tau + D[q][c])) if u(prev) is not None else None, ">=")
            else:
                rec("arc-plain", c, hc,
                    (h(prev) + lo(nd[prev].service + D[prev][c])) if h(prev) is not None else None,
                    ">=")
            rec("S-TW-DEP-UB", c, hc,
                hi(nd[depot].latest - D[c][depot] - nd[c].service - tau), "<=")
            if c in tset:
                p = hub_of[c]
                uc = u(c)
                rec("xfer-after-service", c, uc,
                    (hc + lo(nd[c].service + D[c][p])) if hc is not None else None, ">=")
                rec("sync-CDC-lower", c, uc, lo(nd[CDC].earliest + D[CDC][p]), ">=")
                rec("sync-CDC-upper", c, uc, hi(nd[CDC].latest - tau - D[p][CDC]), "<=")
                prev_xfer = True
            else:
                prev_xfer = False
            prev = c
        if r and r[-1] in tset:
            q = hub_of[r[-1]]
            rec("multitrip-return", r[-1], u(r[-1]),
                hi(nd[depot].latest - tau - D[q][depot]), "<=")

    for vr in vroutes:
        for a, b in zip(vr, vr[1:]):
            if a in hub_of and b in hub_of:
                ua, ub = u(a), u(b)
                rec("vessel-seq", b, ub,
                    (ua + lo(tau + D[hub_of[a]][hub_of[b]])) if ua is not None else None, ">=")

    if tau > 0:                                   # constraint (26), as NoOverlap means pairwise
        by_sat = {}
        for c in tset:
            by_sat.setdefault(hub_of[c], []).append(c)
        for p, members in by_sat.items():
            if len(members) < 2:
                continue
            ts = sorted((u(c), c) for c in members if u(c) is not None)
            for (t1, c1), (t2, c2) in zip(ts, ts[1:]):
                if t2 - t1 < lo(tau):
                    bad.append(("c26-satellite-%s" % p, c2, (lo(tau) - (t2 - t1)) / SCALE))
    return bad, missing


def _resolve_tau(cell, size, proximity, wls=0.1):
    """VInstance cannot take tau='formula' -- it leaks the string into arithmetic. The solver
    resolves it via the instance builder, so resolve it the same way and pass the number."""
    from crossfeed.easy_reduction_descend import build
    return build(cell, size, wls=wls, tau="formula", proximity=proximity,
                 time_limit=20).TransferDuration


def resolve_run_id(sol, sol_path):
    """Run id for a dump. Only 17 of 248 dumps carry `_run_id`; the filename stem IS the run id
    for the rest. Design audits 1/2/3 all flagged that reading `_run_id` alone returns None for
    231 of 248 and that main() then PRINTS THAT AS 'not quarantined' -- a positive claim built
    from a missing key. Returns (run_id, provenance) where provenance is one of
    QUARANTINED / ACCEPTED / ORPHAN."""
    rid = sol.get("_run_id") or os.path.basename(sol_path)[:-5]
    if os.path.exists(os.path.join(ROOT, "runs", "invalid", rid + ".jsonl")):
        return rid, "QUARANTINED"
    if os.path.exists(os.path.join(ROOT, "runs", rid + ".jsonl")):
        return rid, "ACCEPTED"
    return rid, "ORPHAN"


def resolve_proximity(sol, sol_path):
    """THE PROXIMITY THE RUN ACTUALLY USED, from its own run_start config record.

    NOT `InstanceSpec.for_k_comparison`, and NOT an argv scalar. d209 established every existing
    n100 run used 0.0 while K's table 6 is 0.1; rebuilding those dumps at 0.1 moves the satellites
    and therefore every entry of D, which enters eight of the ten constraint classes. Violations so
    produced would be artifacts of the wrong instance -- d209 in a new costume -- and they would
    trip the design's most serious falsifier for a reason that has nothing to do with the solver.
    Returns (proximity, source). source 'run-config' is the only trustworthy one."""
    rid, _ = resolve_run_id(sol, sol_path)
    for d in ("invalid", ""):
        f = os.path.join(ROOT, "runs", d, rid + ".jsonl")
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                if '"run_start"' not in ln:
                    continue
                try:
                    cfg = json.loads(ln)["extra"]["config"]
                except Exception:
                    break
                if "proximity" in cfg:
                    return float(cfg["proximity"]), "run-config"
                break
        break
    return None, "UNRESOLVED"


def quarantine_reason(sol, sol_path=""):
    """Why this run was quarantined, from INDEX.md and from the run's own rejection text."""
    rid = sol.get("_run_id") or (os.path.basename(sol_path)[:-5] if sol_path else "")
    if not rid:
        return None, None
    idx_reason = None
    ip = os.path.join(ROOT, "runs", "invalid", "INDEX.md")
    if os.path.exists(ip):
        for ln in open(ip, encoding="utf-8"):
            if rid in ln:
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) > 3:
                    idx_reason = cells[3]
                break
    detail = None
    for d in ("invalid", ""):
        f = os.path.join(ROOT, "runs", d, rid + ".jsonl")
        if os.path.exists(f):
            txt = open(f, encoding="utf-8").read()
            mm = re.findall(r"(W-[A-Z0-9-]+/?\(?\d*\)?[^\"\]]{0,90})", txt)
            if mm:
                detail = mm[0][:95]
            break
    return idx_reason, detail


def audit(cell, size, sol_path, proximity, wls=0.1, tau=None):
    import verifier as V
    tau = _resolve_tau(cell, size, proximity, wls) if tau is None else tau
    inst = V.VInstance(cell, size, wls=wls, tau=tau, proximity=proximity)
    sol = json.load(open(sol_path, encoding="utf-8"))
    H = {int(k): v for k, v in (sol.get("hi") or {}).items()}
    U = {int(k): v for k, v in (sol.get("ui") or {}).items()}
    captured = {}

    orig = V._schedule_feasible

    def intercept(inst_, routes, hub_of, tset, vroutes):
        captured["fired"] = True
        captured["args"] = (routes, hub_of, tset, vroutes)
        captured["bad"], captured["missing"] = _check_committed(
            inst_, routes, hub_of, tset, vroutes, H, U)
        # Report the COMMITTED verdict so verify() continues on our answer, not a search.
        if captured["missing"]:
            return None, "committed timetable incomplete"
        return (len(captured["bad"]) == 0), (
            "committed timetable satisfies every constraint" if not captured["bad"]
            else "committed timetable violates %d constraint instance(s)" % len(captured["bad"]))

    V._schedule_feasible = intercept
    try:
        verdict = V.verify(inst, sol)
    finally:
        V._schedule_feasible = orig
    return verdict, captured, sol


def main():
    import verifier as V
    pats = sys.argv[1] if len(sys.argv) > 1 else "runs/solutions/cov_*_n100_s0.json"
    prox = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    print(__doc__.split("HOW IT AVOIDS")[0].strip())
    print()
    print("%-7s %9s %9s %6s | %-34s | %s" %
          ("cell", "objVal", "recomp", "OV ok", "WHY QUARANTINED", "committed timetable"))
    for p in sorted(glob.glob(os.path.join(ROOT, pats))):
        m = re.search(r"_((?:C|R|RC)\d{3})_n(\d+)", os.path.basename(p))
        if not m:
            continue
        cell, size = m.group(1), int(m.group(2))
        try:
            _s = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("%-7s %5d  UNREADABLE %s" % (cell, size, type(e).__name__))
            continue
        fprox, psrc = resolve_proximity(_s, p)
        if fprox is None:
            # Refuse to invent one. A schedule evaluated against an instance it was not built on
            # is not a measurement of anything.
            print("%-7s %9s %9s %6s | %-34s | PROXIMITY UNRESOLVED -- not evaluated"
                  % (cell, "-", "-", "-", "n/a"))
            continue
        try:
            vd, cap, sol = audit(cell, size, p, fprox)
        except Exception as e:
            print("%-7s %5d  ERROR %s: %s" % (cell, size, type(e).__name__, str(e)[:60]))
            continue
        bad = cap.get("bad", [])
        miss = cap.get("missing", [])
        if not cap.get("fired"):
            # verifier.py:501-503 gates _schedule_feasible behind v.ok AND tau>tol AND some
            # satellite hosting >=2 transfers. Before this branch existed, a solution that had
            # ZERO constraints evaluated printed "VALID -- satisfies every constraint": captured
            # was {}, both .get calls returned [], and `not bad` was vacuously true. Measured:
            # 25 of 248 dumps cannot reach the check structurally and 4 more are stopped by the
            # v.ok gate, two of which are quarantined n100 runs. NEVER fold this into VALID.
            state = "NOT-CHECKED (interception never fired -- nothing was evaluated)"
        elif miss:
            state = "INCOMPLETE (%d missing h/u)" % len(miss)
        elif not bad:
            state = "VALID -- satisfies every constraint"
        else:
            kinds = {}
            for k, c, d in bad:
                kinds[k.split("-satellite")[0]] = kinds.get(k.split("-satellite")[0], 0) + 1
            worst = max(d for _, _, d in bad)
            state = "VIOLATES %s  worst %.4f" % (
                ", ".join("%s x%d" % (k, n) for k, n in sorted(kinds.items())), worst)
        rid, prov = resolve_run_id(sol, p)
        qr, qd = quarantine_reason(sol, p)
        # Never print "not quarantined" off a missing key -- say which of the three it is.
        why = (qr or qd or prov) if prov == "QUARANTINED" else prov
        print("%-7s %9.1f %9.1f %6s | %-34s | %s"
              % (cell, sol.get("objVal", float("nan")),
                 vd.recomputed_obj or float("nan"), vd.obj_matches, why[:34], state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
