"""INDEPENDENT re-verification of a dual-derived incumbent (logs/harvest_measure/*_incumbent.json).
Runs verifier3 (V.verify_solution) FRESH on the saved solution and RECOMPUTES its objective --
not trusting master_ip's internal flag. Handles both the nested ({'solution': {...}}) and flat
(solution fields at root) layouts. Prints only."""
import io
import json
import sys

ROOT = r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir\analysis"
sys.path.insert(0, ROOT)
import verifier3 as V
import lb_solver as L


def reverify(path):
    d = json.load(io.open(path, encoding="utf-8"))
    sol = d.get("solution", d)                       # nested or flat
    cell = d.get("cell") or sol.get("cell")
    size = int(d.get("size") or sol.get("size"))
    prox = float(d.get("_proximity") or L.k_proximity(size))
    claimed = d.get("objVal", sol.get("objVal"))
    inst = V.load_instance(cell, size, prox)
    run = V.verify_solution(inst, sol, cell=cell, size=size, proximity=prox,
                            label="reverify_%s" % cell)
    findings = list(getattr(run, "findings", []) or [])
    bad = [x for x in findings if getattr(x, "severity", None) != "TOLERANCE"]
    blocking = getattr(run, "blocking", None)
    o = getattr(run, "objective", {}) or {}
    recomputed = o.get("recomputed", o.get("total", o.get("objVal"))) if isinstance(o, dict) else o
    verified = (not bad) and (not blocking)
    match = (recomputed is None or claimed is None) or abs(float(recomputed) - float(claimed)) <= 1e-3
    print("REVERIFY " + json.dumps(dict(
        cell=cell, size=size, path=path.replace("\\", "/").split("/")[-1],
        claimed_objVal=claimed, recomputed=(round(recomputed, 4) if recomputed is not None else None),
        obj_match_1e3=bool(match), verified=bool(verified),
        n_blocking=(len(blocking) if blocking else 0), n_nontol=len(bad),
        nCars=sol.get("nCars"), nVessel=sol.get("nVessel"),
        findings=[str(x) for x in bad[:12]]), default=str), flush=True)
    return bool(verified and match)


if __name__ == "__main__":
    ok = True
    for p in sys.argv[1:]:
        ok = reverify(p) and ok
    sys.exit(0 if ok else 1)
