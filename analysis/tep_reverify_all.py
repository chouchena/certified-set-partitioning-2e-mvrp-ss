"""Re-verify every banked primal artifact from disk with verifier3, at K's proximity for its size. (campaign step S9)

Every artifact under runs/postpass/{,ceil,selchain,forced,refine,alns}/ownwater_<cell>_n<size>.json is a solution some
stage banked after passing the verifier once. Before the tables are committed, every one is read back and verified
again, so that a later edit of any writer cannot have left a stale or corrupted solution in the production dirs. A
failure is a FAILURE (the artifact is listed and must be quarantined), not a warning. Objective values are recomputed
by the verifier and compared with the stored objVal; a mismatch above 1e-3 is listed as well.

    python analysis/tep_reverify_all.py [--sizes 10 20 30 50 100]
"""
import argparse
import glob
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from k_comparison import k_proximity
from stamp import stamped

DIRS = ("", "ceil", "selchain", "forced", "refine", "alns")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100]); a = ap.parse_args()
    rows = []; t0 = time.time(); insts = {}
    for n in a.sizes:
        prox = k_proximity(n)
        for sub in DIRS:
            for f in sorted(glob.glob(os.path.join(ROOT, "runs", "postpass", sub, "ownwater_*_n%d.json" % n))):
                c = os.path.basename(f).split("_")[1]
                sol = json.load(io.open(f, encoding="utf-8"))
                if (c, n) not in insts:
                    insts[(c, n)] = V.load_instance(c, n, prox)
                try:
                    run = V.verify_solution(insts[(c, n)], sol, cell=c, size=n, proximity=prox, label="reverify")
                    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
                    ok = (not bad) and (not run.blocking)
                    obj = getattr(run, "objective", None)
                    if isinstance(obj, dict): obj = obj.get("recomputed", obj.get("total", obj.get("objVal")))
                    if not isinstance(obj, (int, float)): obj = None
                    rows.append(dict(size=n, dir=sub or "floor", cell=c, objVal=float(sol["objVal"]), verified=ok,
                                     findings=[str(x.cls) for x in bad[:5]], recomputed=obj,
                                     obj_mismatch=(abs(float(obj) - float(sol["objVal"])) > 1e-3) if obj is not None else None,
                                     code_hash=bool((sol.get("_provenance") or {}).get("code_hash"))))
                except Exception as e:
                    rows.append(dict(size=n, dir=sub or "floor", cell=c, objVal=float(sol.get("objVal", 0)), verified=False, findings=["EXC %r" % e][:1]))
    fails = [r for r in rows if not r["verified"]]; mism = [r for r in rows if r.get("obj_mismatch")]; nohash = [r for r in rows if not r.get("code_hash")]
    print("re-verified %d artifacts in %.0f s: %d PASS, %d FAIL, %d objective mismatches, %d without code_hash" % (len(rows), time.time() - t0, len(rows) - len(fails), len(fails), len(mism), len(nohash)))
    for r in fails: print("  FAIL n%d %s/%s %.3f %s" % (r["size"], r["dir"], r["cell"], r["objVal"], r["findings"]))
    for r in mism: print("  MISMATCH n%d %s/%s stored %.3f recomputed %s" % (r["size"], r["dir"], r["cell"], r["objVal"], r["recomputed"]))
    for n in a.sizes:
        rs = [r for r in rows if r["size"] == n]
        print("  n%d: %d artifacts, %d pass" % (n, len(rs), sum(1 for r in rs if r["verified"])))
    out = os.path.join(ROOT, "runs", "oracle", "tep_reverify_all.json")
    json.dump(stamped(dict(rows=rows, passed=len(rows) - len(fails), failed=len(fails))), io.open(out, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(out, ROOT))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
