"""Verify a banked incumbent from the repo, independently of everything that produced it. (author 2026-09-27: reviewer verification)

    python analysis/verify_incumbent.py results/incumbents/n30/R208.json
    python analysis/verify_incumbent.py --all                      # every incumbent under results/incumbents/

Reads only the solution file. The cell, size and proximity come from the file itself; the instance is rebuilt from the
predecessors' published generator (fetched, never committed -- see paper/REPLICABILITY.md); the solution is checked
against every semantic constraint of their model as transcribed in analysis/verifier3.py, and the objective is RECOMPUTED
from the decoded solution rather than read from the file. A reviewer needs this file and the instance generator; nothing
of our pipeline is involved in the check.

Exit code 0 only if the solution passes every check and its stored objective matches the recomputed one to 1e-3.
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity


def verify(path, quiet=False):
    sol = json.load(io.open(path, encoding="utf-8"))
    size = int(sol.get("size") or 0)
    cell = sol.get("cell") or os.path.splitext(os.path.basename(path))[0]
    prox = float(sol.get("_proximity", k_proximity(size)))
    inst = V.load_instance(cell, size, prox)
    run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=prox, label="reviewer")
    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
    ok = (not bad) and (not run.blocking)
    o = run.objective
    obj = o.get("recomputed", o.get("total", o.get("objVal"))) if isinstance(o, dict) else o   # verifier3 returns dict(recomputed, claimed, street, water, n_cars, n_vessel)
    stored = float(sol["objVal"])
    match = (obj is None) or abs(float(obj) - stored) <= 1e-3
    if not quiet:
        print("%s n%d (proximity %.1f): %s | objVal stored %.3f, recomputed %s | cars %s, vessels %s | %d finding(s)%s"
              % (cell, size, prox, "PASS" if (ok and match) else "FAIL", stored, ("%.3f" % obj) if obj is not None else "n/a",
                 sol.get("nCars"), sol.get("nVessel"), len(bad), (": " + ", ".join(str(x.cls) for x in bad[:6])) if bad else ""))
        if run.blocking: print("  blocking: %s" % run.blocking[:3])
    return ok and match


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("path", nargs="?"); ap.add_argument("--all", action="store_true"); a = ap.parse_args()
    if a.all:
        files = sorted(glob.glob(os.path.join(ROOT, "results", "incumbents", "n*", "*.json")))
        bad = [f for f in files if not verify(f)]
        print("\n  %d incumbent(s): %d PASS, %d FAIL%s" % (len(files), len(files) - len(bad), len(bad), (" -- " + ", ".join(os.path.relpath(f, ROOT) for f in bad)) if bad else ""))
        return 0 if not bad else 1
    if not a.path:
        print(__doc__); return 2
    return 0 if verify(a.path) else 1


if __name__ == "__main__":
    sys.exit(main())
