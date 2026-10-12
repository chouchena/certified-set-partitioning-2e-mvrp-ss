"""The |C| = 20 street-fleet total, with every cell's minimality status derived, not asserted.

PREREG: validation/PREREG_n20_fleet_total.md, whose primary threshold is "a verified 27-cell total
of <= 42", registered before the run.

WHY THIS IS A SCRIPT AND NOT A REGISTRY ENTRY. It verifies all 27 solutions through `verifier.py`,
which is far too slow to run on every `numbers.tex` regeneration. It writes a frozen artifact and
the registry reads that -- the same pattern `fleet_subset_infeasibility.json` already uses.

THE TOTAL IS A BEST-FOUND, NOT A MINIMUM, and the two must never be conflated. Each cell is
classified into exactly one of:

  PROVEN  -- the fleet is provably minimal. Three independent grounds:
             * the cell holds a verified ONE-car solution (1 is the floor; nothing is below it);
             * the L-fleet arithmetic certificate proves one vehicle impossible;
             * a solver proved `nofCars <= ours-1` infeasible on the FULL model.
  ARGUED  -- K prove the objective optimal and we match it, so under H1 (removing a vehicle always
             pays, 12 of 12 observed) the optimal solution carries the minimal fleet. H1 is
             EMPIRICAL. This is an argument, not a proof, and is counted separately for that reason.
  OPEN    -- no proof that `ours - 1` is impossible.

S2U's INFEASIBLE RESULTS ARE DELIBERATELY NOT ADMITTED as proofs. They were obtained with 4
customers pinned to the incumbent, so they exclude a one-car solution only within that
neighbourhood, not within the instance. Admitting them would inflate PROVEN by four cells on
evidence that does not support it.

K's COMPARATOR IS RECONSTRUCTED, and the reconstruction is exact. They publish a |C| = 20 street
fleet mean of 1.59 over 27 instances (`table4_full`, wls 1:10, both Joint and LBBD). Exactly one
integer total is consistent with it: 43, since 42/27 = 1.5556 -> 1.56 and 44/27 = 1.6296 -> 1.63.
"""
import argparse, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from solver.config import InstanceSpec                       # noqa: E402
from solver.problem import SolverProblem                     # noqa: E402
import analysis.manuscript_numbers as M                      # noqa: E402

NAME = re.compile(r"^(?:best_|merge_)?((?:RC|R|C)\d{3})_n20")
SOURCES = ("published_artifacts/solutions/*.json",
           "results/portfolio/*.json",
           "validation/certificates/*_solution.json",
           "runs/solutions/merge_*_n20_d0.json")


def best_solutions():
    """Fewest cars wins, cheapest breaks ties. Returns {cell: (nCars, objVal, path, doc)}."""
    best = {}
    for pat in SOURCES:
        for f in glob.glob(os.path.join(ROOT, pat)):
            m = NAME.match(os.path.basename(f))
            if not m:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict) or "nCars" not in d or "objVal" not in d:
                continue
            key = (int(d["nCars"]), float(d["objVal"]))
            if m.group(1) not in best or key < best[m.group(1)][0]:
                best[m.group(1)] = (key, f, d)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/n20_fleet_total.json")
    a = ap.parse_args()

    cert = {r["cell"]: r for r in json.load(
        open(os.path.join(ROOT, "runs/fleet_subset_infeasibility.json"), encoding="utf-8"))}
    probe_p = os.path.join(ROOT, "runs/fleet_lb_solver_n20.json")
    probe = ({r["cell"]: r for r in json.load(open(probe_p, encoding="utf-8"))}
             if os.path.exists(probe_p) else {})
    K20 = M._K()["table3"]["per_instance"]["20"]
    best = best_solutions()

    rows, total, verified = [], 0, 0
    print(f"{'cell':7s}{'cars':>5s}{'objective':>11s}{'verified':>10s}  {'status':8s} ground")
    for c in sorted(M._cells(20)):
        if c not in best:
            print(f"{c:7s}{'?':>5s}{'-':>11s}{'NO FILE':>10s}")
            rows.append(dict(cell=c, cars=None, status="NO SOLUTION"))
            continue
        (n, o), f, d = best[c]
        vd = SolverProblem(InstanceSpec.for_k_comparison(c, 20)).verify(d)
        rec = getattr(vd, "recomputed_obj", None)
        # The objective is matched at the precision the FILE stores. Two files store 2 dp
        # (C205 685.19, R201 821.71) against full-precision recomputations 0.005 away; a 1e-3
        # tolerance rejects those for rounding, not for any defect. vd.ok is the constraint check.
        obj_ok = rec is None or abs(rec - o) < 6e-3
        ok = bool(vd.ok) and obj_ok
        verified += ok
        total += n

        if n == 1:
            status, ground = "PROVEN", "one car is the floor"
        elif cert.get(c, {}).get("infeasible_k1"):
            status, ground = "PROVEN", "L-fleet certificate proves >=2"
        elif probe.get(c, {}).get("outcome") == "INFEASIBLE":
            status, ground = "PROVEN", "solver proved nofCars<=%d infeasible" % (n - 1)
        elif K20[c]["joint_gap"] == 0:
            status, ground = "ARGUED", "K prove the objective optimal, plus H1 (empirical)"
        else:
            status, ground = "OPEN", "no proof that %d is impossible" % (n - 1)

        rows.append(dict(cell=c, cars=n, objective=o, verified=ok, status=status,
                         ground=ground, source=os.path.relpath(f, ROOT)))
        print(f"{c:7s}{n:5d}{o:11.2f}{('yes' if ok else 'NO'):>10s}  {status:8s} {ground}")

    prov = sum(1 for r in rows if r.get("status") == "PROVEN")
    argu = sum(1 for r in rows if r.get("status") == "ARGUED")
    opencells = [r["cell"] for r in rows if r.get("status") == "OPEN"]
    k_total = 43

    print()
    print(f"  27-cell street-fleet total   : {total}      K implied {k_total}")
    print(f"  cells verified               : {verified} of 27")
    print(f"  one-car / two-car            : {sum(1 for r in rows if r.get('cars') == 1)}"
          f" / {sum(1 for r in rows if r.get('cars') == 2)}")
    print(f"  proven minimal               : {prov} of 27")
    print(f"  argued via H1 (not a proof)  : {argu}  "
          f"{[r['cell'] for r in rows if r.get('status') == 'ARGUED']}")
    print(f"  OPEN                         : {len(opencells)}  {opencells}")
    print()
    if verified == 27 and total <= 42:
        print("  PREREG primary threshold (verified 27-cell total <= 42): MET")
    else:
        print("  PREREG primary threshold: NOT met")
    print("  The total is a BEST-FOUND. It becomes a PROVEN MINIMUM only when every cell is")
    print("  PROVEN -- which needs the %d open cells plus C208's H1 dependence removed."
          % len(opencells))

    out = dict(total=total, k_total=k_total, verified=verified, n_cells=len(rows),
               proven=prov, argued=argu, open_cells=opencells, rows=rows,
               prereg="validation/PREREG_n20_fleet_total.md")
    json.dump(stamped(out, __file__), open(os.path.join(ROOT, a.out), "w"), indent=1)
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
