"""G-P8 -- IS CONSTRAINT (26) RUNNABLE AT ALL? A precondition to the arm decision.

AUTHOR, 2026-09-18: *"I want a gate validating constraint 26 is runnable. K's decision to shortcut
it might be because it makes the solver unrunnable. In this case, we have to consider other ways
around as they did."*

WHY THIS GATE EXISTS, AND WHY IT COMES BEFORE THE ARM DECISION.

Part 2 asks whether enforcing (26) costs objective or time. That question presumes the corrected
model can be solved at all. The evidence says do not presume it:

    validation/discriminating_26.json
      C205 n20  tau 180  vacuous 685.19 proven 77.4 s | corrected 685.19 proven 142.7 s  (1.84x)
      C201 n20  tau 180  vacuous 697.69 proven  1.8 s | corrected 697.69 proven   1.8 s  (1.00x)
      RC208 n20 tau  20  vacuous 693.87 proven        | corrected 962.53 at 71.1% GAP after 603 s

One of three n20 cells did not close, and it is the manuscript's headline cell. Nobody has run the
corrected model at n50 or n100, where the encoding is O(n^2): 190 ordering binaries and 1,520 rows
at n20, ~4,950 and ~39,600 at n100.

So the hypothesis under test is K's: that (26) as a disjunction is not affordable, and that
(27)-(30) is a relaxation adopted because the exact form does not solve. If that is right, the
finding is not "their linearization is vacuous" but "the constraint is not tractable in this
formulation and it was relaxed" -- a different statement, and one we would have to make about
ourselves too.

WHAT "RUNNABLE" MEANS HERE. Three states, thresholds fixed before the data (CLAUDE.md section 2):

  RUNNABLE   root LP solves, an incumbent is found, and the final gap exceeds the vacuous arm's
             gap on the same cell and budget by at most GAP_OK.
  DEGRADED   an incumbent is found but the gap exceeds GAP_OK. Usable with disclosure; not free.
  UNRUNNABLE no incumbent inside the budget, or the root LP does not solve.

Always measured AGAINST THE VACUOUS ARM ON THE SAME CELL AND BUDGET, never an absolute. A cell
hard in both arms is a hard cell, not evidence about (26).

WHAT THE GATE DECIDES. It does not choose an arm. It removes arms from the ballot:

  any cell UNRUNNABLE under an arm -> that arm is struck; Part 2 decides among the survivors
  no exact arm survives            -> the workaround is forced, and the manuscript must say so

THE ARMS, AND WHICH ONES ARE REAL.

  Arm R  K's published linearization. Baseline, runnable by construction. IMPLEMENTED.
  Arm C  full disjunction, o[i,j] for every i<j, gated on vip. IMPLEMENTED
         (joint_model_cplex.py:254-270, behind problem.hardSingleTransfer).

  Arm Y  REFUTED 2026-09-18 -- DO NOT PUT THIS ON THE BALLOT.
         The proposal was to post the disjunction only for same-satellite pairs on DIFFERENT
         vessel routes, on the grounds that eq (20) chains same-vessel pairs at >= tau, and that
         1,147 of 1,416 same-satellite pairs in the corpus are so entailed. The reduction is not
         implementable and the measured yield is zero:
           (a) whether i and j share a vessel route is decided by y, so it cannot be read at
               build time. The 1,147 figure was measured on REALIZED SOLUTIONS and licenses no
               static rule. Quoting it as a model reduction confuses a solution property with a
               formulation property.
           (b) the one reduction that IS sound -- drop o[i,j] when i and j provably cannot share
               a satellite, from Const13/Const15 feasibility -- yields nothing. Measured over 11
               n20 cells spanning all three families and both tau values:
                   0 pairs dropped of 190 per cell; 16,720 rows before, 16,720 after; 0.0% cut.
               Every customer can reach every satellite at n20. Command: see arm_y_reduction()
               below, which is kept as the executable record of the refutation.

  Arm L  lazy separation: solve without (26), check each incumbent's <=9 same-satellite pairs,
         add the one violated disjunction, continue. Exact at the final incumbent, and it posts
         O(violations) rows instead of O(n^2). NOT IMPLEMENTED -- see build_arm_l() for exactly
         what it needs. With Arm Y refuted this is the only cheaper exact encoding left.
  Arm P  lexmin repair as a post-pass (Part 8.3). Not an encoding of (26) at all; it accepts a
         relaxed optimum and repairs the timetable. On the ballot only if no exact arm survives.

WHAT THIS GATE CANNOT SETTLE. It measures OUR encoding in OUR solver on OUR instances. K's
tractability constraints are not ours and we cannot recover what they tried. Nothing here licenses
a statement about their reasoning -- only about whether the exact constraint is affordable for us.
Any K-facing sentence remains parked (d221).
"""
import argparse, itertools, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- thresholds, fixed here, before the data -------------------------------------------------
GAP_OK = 0.05          # an arm's gap may exceed the vacuous arm's by at most 5 percentage points
ROOT_LP_TL = 60.0      # seconds; a root relaxation that does not solve in a minute is a finding
DET_TL = 300_000       # ticks, matching Part 8's Stage 2 budget so the result transfers

IMPLEMENTED = ("R", "C")
KNOWN = ("R", "C", "Y", "L", "P")


def arm_y_reduction(pr):
    """The executable record of Arm Y's refutation. Returns (pairs, dropped, rows_C, rows_Y).

    Sound static test: vip[i,s] can be 1 only if Const13 and Const15 are jointly satisfiable --
        lb(i,s) = max(e_i + st_i + D[i][s], CDC.earliest + D[CDC][s])
        ub(s)   = CDC.latest - TD - D[s][CDC]
    using h_i >= e_i, which is h_i's declared lower bound, so the test can never drop a satellite
    the MILP could actually use. Measured yield at n20: exactly zero. Kept so the claim stays
    falsifiable at other sizes rather than being repeated from memory.
    """
    nd, D, TD, CDC = pr.nodes, pr.DistMatrix, pr.TransferDuration, pr.CDC
    allow = {i: {s for s in pr.satellites
                 if max(nd[i].earliest + nd[i].serviceTime + D[i][s], nd[CDC].earliest + D[CDC][s])
                 <= nd[CDC].latest - TD - D[s][CDC] + 1e-9}
             for i in pr.customers}
    S = len(pr.satellites)
    pairs = dropped = rows_c = rows_y = 0
    for i, j in itertools.combinations(sorted(pr.customers), 2):
        pairs += 1
        rows_c += 2 * S
        k = len(allow[i] & allow[j])
        rows_y += 2 * k
        if k == 0:
            dropped += 1
    return pairs, dropped, rows_c, rows_y


def build_arm_l(problem):
    """Arm L -- lazy separation. NOT IMPLEMENTED. Raises rather than pretending.

    What it needs, so the next person does not re-derive it:
      1. a Gurobi build (joint_model_gurobi.py), because docplex's lazy-constraint callback does
         not expose the incumbent's variable values the way Model.cbGetSolution does. Three
         models in this repository already set LazyConstraints=1.
      2. a callback that, on each MIPSOL, reads vip and u, groups transfers by satellite, sorts
         by u, and for the first adjacent pair closer than tau adds BOTH disjunctive rows for
         that (i,j) with a fresh binary. Adding only the violated direction is unsound: it
         forbids one order without permitting the other.
      3. a termination argument. Each callback adds at most one pair's rows, and there are
         O(n^2) pairs, so it terminates, but the bound is the thing Arm L exists to avoid --
         the gate must record rows actually added, not the bound.
      4. the same dump path as the other arms, so verify2 sees an identical artifact shape.
    """
    raise NotImplementedError(
        "Arm L is specified, not built. Do not report an Arm L measurement until build_arm_l "
        "posts real constraints -- an arm that silently falls back to Arm R would report Arm R's "
        "runtime under Arm L's name, which is the 'fix built and never wired' failure.")


def measure(cell, size, arm, proximity=0.0, det_tl=DET_TL):
    """Solve one (cell, size) under one arm. Returns a record; never raises on a solver outcome."""
    from build_instance import build
    from joint_model_cplex import build_joint_model

    rec = {"cell": cell, "size": size, "arm": arm, "proximity": proximity, "det_tl": det_tl}
    if arm not in IMPLEMENTED:
        rec.update(state="NOT-IMPLEMENTED",
                   detail="arm %s has no builder; see the module docstring" % arm)
        return rec

    pr = build(cell, size, wls=0.1, tau="formula", proximity=proximity)
    pr.singleTransfer = True
    pr.hardSingleTransfer = (arm == "C")
    rec["tau"] = pr.TransferDuration
    p_, d_, rc_, ry_ = arm_y_reduction(pr)
    rec["armY_pairs"], rec["armY_dropped"] = p_, d_
    rec["armY_rows_C"], rec["armY_rows_Y"] = rc_, ry_

    try:
        H = build_joint_model(pr)
    except Exception as e:
        rec.update(state="BUILD-ERROR", detail="%s: %s" % (type(e).__name__, e))
        return rec

    m = H.m
    rec["n_binaries"] = sum(1 for _ in m.iter_binary_vars())
    rec["n_constraints"] = m.number_of_constraints

    # --- root LP first. A root relaxation that does not solve is decisive on its own. ---
    try:
        relaxed = m.copy()
        for v in relaxed.iter_binary_vars():
            v.set_vartype(relaxed.continuous_vartype)
        relaxed.set_time_limit(ROOT_LP_TL)
        t1 = time.time()
        lp = relaxed.solve()
        rec["root_lp_s"] = round(time.time() - t1, 2)
        rec["root_lp"] = None if lp is None else round(lp.objective_value, 4)
        if lp is None:
            rec.update(state="UNRUNNABLE", detail="root LP did not solve in %gs" % ROOT_LP_TL)
            return rec
    except Exception as e:
        rec.update(state="UNRUNNABLE", detail="root LP raised %s" % type(e).__name__)
        return rec

    # --- the MILP, under a DETERMINISTIC budget so the measurement reproduces ---
    m.parameters.dettimelimit = det_tl
    m.parameters.threads = 4
    m.parameters.parallel = 1          # deterministic parallel, as lb_campaign.py pins for the dual leg
    t2 = time.time()
    sol = m.solve()
    rec["wall_s"] = round(time.time() - t2, 2)
    try:
        rec["det_used"] = round(m.solve_details.deterministic_time, 1)
        rec["status"] = m.solve_details.status
    except Exception:
        pass
    if sol is None:
        rec.update(state="UNRUNNABLE", detail="no incumbent within %d ticks" % det_tl)
        return rec
    rec["obj"] = round(sol.objective_value, 4)
    rec["bound"] = round(m.solve_details.best_bound, 4)
    rec["gap"] = round(m.solve_details.mip_relative_gap, 6)
    rec["state"] = "FOUND"             # RUNNABLE/DEGRADED decided against Arm R by classify()
    return rec


def classify(rec_arm, rec_R):
    """RUNNABLE / DEGRADED / UNRUNNABLE, always relative to the vacuous arm on the same cell."""
    st = rec_arm.get("state")
    if st in ("UNRUNNABLE", "BUILD-ERROR", "NOT-IMPLEMENTED"):
        return st
    if rec_R.get("state") in ("UNRUNNABLE", "BUILD-ERROR"):
        return "BASELINE-UNRUNNABLE"   # the cell is hard in both arms; not evidence about (26)
    dgap = rec_arm.get("gap", 1.0) - rec_R.get("gap", 0.0)
    return "RUNNABLE" if dgap <= GAP_OK else "DEGRADED"


def main():
    ap = argparse.ArgumentParser(description="G-P8: is constraint (26) runnable?")
    ap.add_argument("--cells", default="RC208,C205,C201")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--arms", default="R,C")
    ap.add_argument("--det-tl", type=int, default=DET_TL)
    ap.add_argument("--proximity", type=float, default=0.0)
    ap.add_argument("--log", default=None)
    ap.add_argument("--reduction-only", action="store_true",
                    help="print the Arm Y reduction census and exit; no solve")
    a = ap.parse_args()

    cells = [c.strip() for c in a.cells.split(",") if c.strip()]
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    # Part 14.3: a gate that passes on empty input is broken.
    if not cells:
        print("G-P8 FAIL: empty cell set -- a gate that passes on nothing is broken")
        return 1
    if not arms:
        print("G-P8 FAIL: empty arm set")
        return 1
    bad = [x for x in arms if x not in KNOWN]
    if bad:
        print("G-P8 FAIL: unknown arm(s) %s; known arms are %s" % (", ".join(bad), ", ".join(KNOWN)))
        return 1
    if "R" not in arms:
        print("G-P8 FAIL: Arm R is the baseline every other arm is classified against")
        return 1
    if "Y" in arms:
        print("G-P8 FAIL: Arm Y was refuted 2026-09-18 (zero static reduction at n20, and the")
        print("  entailment it rests on is a solution property, not a model property). See the")
        print("  module docstring. Run --reduction-only to reproduce the refutation.")
        return 1

    from build_instance import build
    if a.reduction_only:
        print("Arm Y static reduction census -- the refutation, reproducible")
        print("%-8s %4s %5s %7s %8s %9s %9s %7s"
              % ("cell", "tau", "sats", "pairs", "dropped", "C rows", "Y rows", "cut"))
        tc = ty = 0
        for cell in cells:
            pr = build(cell, a.size, wls=0.1, tau="formula", proximity=a.proximity)
            p_, d_, rc_, ry_ = arm_y_reduction(pr)
            tc += rc_; ty += ry_
            print("%-8s %4d %5d %7d %8d %9d %9d %6.1f%%"
                  % (cell, pr.TransferDuration, len(pr.satellites), p_, d_, rc_, ry_,
                     100.0 * (1 - ry_ / rc_) if rc_ else 0.0))
        print("\nTOTAL %d cells: Arm C %d rows, Arm Y %d rows, reduction %.1f%%"
              % (len(cells), tc, ty, 100.0 * (1 - ty / tc) if tc else 0.0))
        print("A reduction of 0.0% is the refutation: no static rule extracts the entailment.")
        return 0

    print("thresholds: GAP_OK=%.2f  ROOT_LP_TL=%gs  det_tl=%d   (fixed before the data)"
          % (GAP_OK, ROOT_LP_TL, a.det_tl))
    print("%-8s %-4s %8s %10s %10s %9s %8s  %s"
          % ("cell", "arm", "binaries", "root LP", "obj", "gap", "wall s", "state"))

    records, verdicts = [], {}
    for cell in cells:
        base = {}
        for arm in arms:
            r = measure(cell, a.size, arm, a.proximity, a.det_tl)
            if arm == "R":
                base = r
            else:
                r["state"] = classify(r, base)
            records.append(r)
            verdicts.setdefault(arm, []).append(r.get("state"))
            print("%-8s %-4s %8s %10s %10s %9s %8s  %s"
                  % (cell, arm, r.get("n_binaries", "-"), r.get("root_lp", "-"),
                     r.get("obj", "-"), r.get("gap", "-"), r.get("wall_s", "-"),
                     str(r.get("state")) + (("  " + r["detail"]) if r.get("detail") else "")))

    print()
    struck, kept = [], []
    for arm in arms:
        if arm == "R":
            continue
        st = verdicts.get(arm, [])
        nbad = sum(1 for s in st if s in ("UNRUNNABLE", "BUILD-ERROR"))
        if nbad:
            struck.append(arm)
            print("  ARM %s STRUCK -- UNRUNNABLE on %d of %d cell(s)" % (arm, nbad, len(st)))
        elif any(s == "NOT-IMPLEMENTED" for s in st):
            print("  ARM %s NOT MEASURED -- no builder exists" % arm)
        elif any(s == "DEGRADED" for s in st):
            kept.append(arm)
            print("  ARM %s DEGRADED on %d of %d cell(s) -- usable only with disclosure"
                  % (arm, sum(1 for s in st if s == "DEGRADED"), len(st)))
        else:
            kept.append(arm)
            print("  ARM %s RUNNABLE on all %d cell(s)" % (arm, len(st)))

    if a.log:
        lp = a.log if os.path.isabs(a.log) else os.path.join(ROOT, a.log)
        with open(lp, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        print("  full record -> %s (%d rows)" % (a.log, len(records)))

    print()
    # A run of the baseline alone evaluates no arm. Saying "no arm is runnable" there would be a
    # catastrophic verdict on a degenerate input -- the failure Part 14.3 exists to forbid, and the
    # one this gate hit on its own first solve-path smoke.
    if arms == ["R"]:
        print("  G-P8: baseline only -- no arm was evaluated, so no verdict is available.")
        print("  Pass at least one of %s alongside R." % ", ".join(a for a in KNOWN if a != "R"))
        return 1
    if not kept:
        print("  G-P8 VERDICT: NO EXACT ARM IS RUNNABLE on these cells. (26) is not affordable in")
        print("  this formulation at this size, and the workaround is forced -- as it may have")
        print("  been for K. Arm L (lazy) is unbuilt; Arm P (repair post-pass) is the fallback.")
        print("  Any manuscript sentence about (27)-(30) must carry this.")
        return 1
    print("  G-P8 VERDICT: arms remaining on the ballot for Part 2: %s" % ", ".join(kept))
    print("  arms struck: %s" % (", ".join(struck) if struck else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
