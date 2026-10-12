"""CERTIFY A FROZEN SOLUTION — anchor the SOLUTION when the RUN cannot be anchored.

THE PROBLEM THIS SOLVES. `runs/provenance.csv` is the committed provenance record and it begins
2026-09-06. The RC208/n20 one-vehicle solution -- the strongest claim in the primal leg -- was
produced on 2026-09-04 by `fixopt_RC208_n20_s0_pf_kick_1788493266`, two days earlier. That run
has no provenance row, and `results/` is gitignored, so the value had no committed provenance of
any kind. Re-running the search would not fix it: a fresh run is a different run and may not
land on the same solution.

WHAT IS AND IS NOT BEING ANCHORED, because the distinction is the whole point.

  * NOT ANCHORED, and unrecoverable: which code state produced this solution. The run predates
    the provenance mechanism. No `code_hash` for it exists and none is invented here. Writing a
    fabricated row into `runs/provenance.csv` would make the run look covered when it is not,
    which is worse than the gap it papers over.
  * ANCHORED, and sufficient for the claim: that these exact bytes encode a feasible solution to
    this instance with this objective. A feasible solution is a POINT TEST -- the verifier
    rebuilds the instance from the benchmark file and re-costs the solution -- and that test does
    not depend on how the solution was found. The search is a heuristic; the certificate is not.

So the claim this supports is "693.868 is a feasible one-vehicle solution to RC208 at |C| = 20",
which is exactly the claim the footnote makes. It does NOT support "our procedure finds it", and
nothing here should be read as supporting that.

The verifier shares no imports with the inherited model files: it reconstructs the instance from
`data/json/` and recomputes every component. Certifying with it is therefore independent of the
code that produced the solution, which is what makes the certificate meaningful despite the
missing run provenance.

USAGE
    python analysis/certify_frozen_solution.py            # re-check, exit 1 on any drift
    python analysis/certify_frozen_solution.py --write    # (re)generate the certificate
"""
import os, sys, json, glob, hashlib, argparse, platform, subprocess, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

CERT_DIR = os.path.join(ROOT, "validation", "certificates")

# The curated set. Deliberately tiny: these are solutions a paper CLAIM rests on, archived into
# a tracked path because `results/` is gitignored and `*.sol.json` is ignored globally. Adding a
# row here is a decision that a number is load-bearing, not a convenience.
FROZEN = {
    "RC208_n20_one_car": dict(
        archived="RC208_n20_one_car_solution.json",
        origin="results/portfolio/RC208_n20_s0__pB_indep_s0__kick.sol.json",
        origin_run="fixopt_RC208_n20_s0_pf_kick_1788493266",
        cell="RC208", size=20, wls=0.1, tau=20.0, proximity=0.0,
        note="one street vehicle; the sole double-digit primal improvement in the study",
    ),
    # Added 2026-09-15. The RC208 footnote cites "on R205 a one-vehicle solution is optimal",
    # which makes this artifact load-bearing for a paper sentence. It was written by stage 1
    # into results/portfolio/, which is gitignored -- i.e. exactly the provenance gap RC208
    # had, caught this time before the number was quoted rather than after.
    "R205_n20_optimal": dict(
        archived="R205_n20_optimal_solution.json",
        origin="results/portfolio/R205_n20_redump.json",
        origin_run="stage1 corrective re-dump 2026-09-15, exact Gurobi solve",
        cell="R205", size=20, wls=0.1, tau=20.0, proximity=0.0,
        note="one street vehicle, and proven optimal: Gurobi status 2, bound == incumbent",
    ),
    # Added 2026-10-11. The RC208 one-vehicle footnote quotes a two-vehicle comparator
    # (published-over-two-car-pct). manuscript_numbers rc208-one-car reads it via _best_stored,
    # which in the RELEASE tree sees only published_artifacts/solutions and validation/certificates
    # -- results/portfolio is gitignored and not shipped. Anchoring the best two-vehicle solution
    # (852.558) into the tracked, sha256-pinned set lets that number regenerate without the
    # working portfolio. Same instance and weighting as the one-car entry above.
    "RC208_n20_two_car": dict(
        archived="RC208_n20_two_car_solution.json",
        origin="results/portfolio/RC208_n20_s0__pB_indep_s0__seg.sol.json",
        origin_run="fixopt RC208_n20_s0 pB_indep seg (portfolio, gitignored; pre-provenance)",
        cell="RC208", size=20, wls=0.1, tau=20.0, proximity=0.0,
        note="best two-vehicle RC208/n20 solution; the comparator in the one-vehicle footnote",
    ),
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def _verify(spec, sol_path):
    """Re-cost the archived solution against an independently rebuilt instance."""
    import verifier3 as V
    # verifier.py (VInstance/verify) was renamed to verifier3 (load_instance/verify_for_engine);
    # certify was never updated and had been crashing on the dead import (regression, fixed
    # 2026-10-11). load_instance derives tau from the instance (RC/R = 20), matching spec["tau"].
    inst = V.load_instance(spec["cell"], spec["size"], spec["proximity"], wls=spec["wls"])
    sol = json.load(open(sol_path))
    # expect="any" (the ORACLE mode, as in reverify_reported.py): check feasibility and recompute
    # the objective, but do NOT apply the d243 production-provenance BLOCK. These archived solutions
    # predate d243 and are feasibility point-tests, not production engine output; the certificate
    # claims feasibility + objective, never which formulation produced them (see the module docstring).
    verdict = V.verify_for_engine(inst, sol, cell=spec["cell"], size=spec["size"],
                                  proximity=spec["proximity"], expect="any")
    parts = {k: sol[k] for k in ("FleetStreet", "FleetWater", "TravelStreet", "TravelWater")
             if k in sol}
    return sol, verdict, parts


def certify(key, spec):
    from analysis.repro_preflight import code_hash
    sol_path = os.path.join(CERT_DIR, spec["archived"])
    if not os.path.exists(sol_path):
        raise SystemExit(f"archived solution missing: {sol_path}\n"
                         f"copy it from {spec['origin']} and re-run with --write")

    sol, verdict, parts = _verify(spec, sol_path)
    comp_sum = round(sum(parts.values()), 6) if parts else None

    rec = {
        "key": key,
        "claim": "these bytes encode a feasible solution to this instance with this objective",
        "not_claimed": "which code state produced the solution; the run predates "
                       "runs/provenance.csv and its code_hash is unrecoverable",
        "cell": spec["cell"], "size": spec["size"],
        "wls": spec["wls"], "tau": spec["tau"], "proximity": spec["proximity"],
        "origin_path": spec["origin"],
        "origin_run": spec["origin_run"],
        "origin_run_has_provenance_row": _origin_has_provenance(spec["origin_run"]),
        "archived_path": os.path.relpath(sol_path, ROOT).replace(os.sep, "/"),
        "archived_sha256": _sha256(sol_path),
        "objective_claimed": sol.get("objVal"),
        "objective_recomputed": verdict.recomputed_obj,
        "objective_matches": (verdict.recomputed_obj is not None and sol.get("objVal") is not None
                              and abs(verdict.recomputed_obj - sol["objVal"]) <= 1e-6),
        "components": parts,
        "components_sum": comp_sum,
        "nCars": sol.get("nCars"),
        "nVessel": sol.get("nVessel"),
        "verifier_ok": verdict.ok,
        "violations": verdict.violations,
        # OPTIMALITY, when the artifact carries a solver's own closure evidence. DERIVED, never
        # asserted: all three of status 2 (Gurobi OPTIMAL), a zero gap, and bound == incumbent
        # must hold. A solution file that merely says status 2 does not get to claim it here.
        # Absent these fields the key is None -- feasible and certified, optimality not claimed.
        "solver_status": sol.get("status"),
        "best_bound": sol.get("best_bound"),
        "mip_gap": sol.get("mip_gap"),
        "proves_optimal": bool(
            sol.get("status") == 2
            and sol.get("mip_gap") is not None and abs(sol["mip_gap"]) <= 1e-9
            and sol.get("best_bound") is not None
            and abs(sol["best_bound"] - sol["objVal"]) <= 1e-6
        ) if sol.get("status") is not None else None,
        "certified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "certified_code_hash": code_hash(),
        "certified_git_sha": _git("rev-parse", "--short=12", "HEAD"),
        "certified_git_dirty": bool(_git("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "note": spec["note"],
    }
    return rec


def _origin_has_provenance(run_id):
    import csv
    p = os.path.join(ROOT, "runs", "provenance.csv")
    if not os.path.exists(p):
        return None
    with open(p, newline="") as fh:
        return any(r.get("run_id") == run_id for r in csv.DictReader(fh))


# Fields that legitimately change between certifications: when it was run, on what code, by whom.
# Everything else is the certified FACT and must not move. Splitting them is what lets --check be
# strict about the solution while tolerating that the certifier itself gets re-run.
VOLATILE = {"certified_at", "certified_code_hash", "certified_git_sha",
            "certified_git_dirty", "python", "platform",
            # stamp.stamped() refreshes these every call (when / on what code / by whom); they are the
            # certifier being re-run, not the certified FACT moving. Added 2026-10-11 -- the dead
            # import had masked that --check can never be clean without exempting them.
            "_provenance", "_rt", "sources"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="(re)generate certificates instead of checking them")
    args = ap.parse_args()

    os.makedirs(CERT_DIR, exist_ok=True)
    failed = False
    for key, spec in FROZEN.items():
        rec = certify(key, spec)
        out = os.path.join(CERT_DIR, f"{key}_certificate.json")

        if not rec["verifier_ok"]:
            print(f"{key}: VERIFIER REJECTED the archived solution")
            for v in rec["violations"]:
                print(f"   x {v}")
            failed = True
            continue
        if rec["components_sum"] is not None and rec["objective_claimed"] is not None:
            if abs(rec["components_sum"] - rec["objective_claimed"]) > 1e-6:
                print(f"{key}: components {rec['components_sum']} do not sum to "
                      f"objective {rec['objective_claimed']}")
                failed = True
                continue

        if args.write:
            with open(out, "w") as fh:
                json.dump(stamped(rec, __file__), fh, indent=2, sort_keys=True)
                fh.write("\n")
            print(f"{key}: written -> {os.path.relpath(out, ROOT)}")
            print(f"   objective {rec['objective_recomputed']:.3f}  "
                  f"nCars={rec['nCars']}  sha256={rec['archived_sha256'][:16]}...")
            prov = rec["origin_run_has_provenance_row"]
            print(f"   origin run provenance row: {'present' if prov else 'ABSENT (expected)'}")
        else:
            if not os.path.exists(out):
                print(f"{key}: no certificate at {os.path.relpath(out, ROOT)} "
                      f"-- run with --write")
                failed = True
                continue
            old = json.load(open(out))
            drift = [k for k in set(old) | set(rec)
                     if k not in VOLATILE and old.get(k) != rec.get(k)]
            if drift:
                print(f"{key}: CERTIFICATE DRIFT in {sorted(drift)}")
                for k in sorted(drift):
                    print(f"   {k}: stored={old.get(k)!r} now={rec.get(k)!r}")
                failed = True
            else:
                print(f"{key}: OK  objective {rec['objective_recomputed']:.3f}  "
                      f"nCars={rec['nCars']}  sha256 unchanged")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
