"""The quick primal fix (d428): let the integer master SELECT the trip partition, and let the
existing exact CONTINUOUS-TIME chaining model do the chaining and the timing. No buckets in the
primal path at all.

The bucket grid exists to make the flow a valid relaxation for the BOUND. Nothing forces the
primal through it: TEP's stage 2 is "which trips", and stage 3 is "chain and time them", and we
already have an exact Gurobi model for stage 3 in `assemble_precluster.chain` -- hub choice, car
chains, transfer times, the tau-spacing (26), depot and CDC returns, all in continuous time. It
is the model that produced every assembled solution in the ledger; the only change here is that
its trips come from the master IP instead of a composition heuristic.

    python analysis/tep_ip_chain.py RC204 [--work 120] [--cap 300] [--retime-cap 240]
Reads runs/oracle/tep_cg_bound_<cell>_ip.json (the IP's selected trips), writes
runs/postpass/ipchain_<cell>_n100.json when the result verifies.
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import verifier3 as V
from analysis.stamp import stamped
from assemble_precluster import chain, decode, retime
from k_comparison import k_proximity
from tep_pretests import best_artifact


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell"); ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--work", type=float, default=120.0); ap.add_argument("--cap", type=float, default=300.0)
    ap.add_argument("--retime-cap", type=float, default=240.0); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--select-suffix", default="", help="read the selection from ..._ip<SUFFIX>.json; 'primal' reads the ceil-rounded selection (d440)")
    ap.add_argument("--tag", default="", help="bank as ipchain<TAG>_<cell>_n<size>.json so a probe does not overwrite the banked route")
    a = ap.parse_args()
    prox = k_proximity(a.size)
    inst = V.load_instance(a.cell, a.size, prox)
    # the writer suffixes the size for everything but n100 (tep_cg_bound.py out_name), so the
    # reader must too -- without this, a small-n run silently consumed the n100 selection (d439)
    src = os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_%s%s_ip%s.json"
                       % (a.cell, "" if a.size == 100 else "_n%d" % a.size,
                          ("_" + a.select_suffix) if a.select_suffix else ""))
    ip = json.load(io.open(src, encoding="utf-8"))["ip"]
    trips = [list(t) for t in ip["trips"]]
    cov = [c for t in trips for c in t]
    print("%s n%d: %d trips from the master IP, %d customer visits, %d distinct (of %d); IP street %.1f with %.0f cars"
          % (a.cell, a.size, len(trips), len(cov), len(set(cov)), len(inst.customers), ip["ip_street"], ip["ip_cars"]), flush=True)
    if len(set(cov)) != len(inst.customers):
        print("  the selection does not cover every customer -- stopping"); return 2
    t0 = time.time()
    res = chain(inst, trips, cap=a.cap, work=a.work, seed=a.seed)
    if res is None:
        print("  continuous-time chaining: INFEASIBLE in %.0f s" % (time.time() - t0)); return 1
    print("  continuous-time chaining: %d cars, street %.1f (gurobi %s, work %.1f, %.0f s)"
          % (res["cars"], res["street"], res["gurobi"]["status"], res["gurobi"].get("work_used") or 0, time.time() - t0), flush=True)
    cand = decode(trips, res, depot=inst.depot)
    out, status, secs = retime(a.cell, cand, cap=a.retime_cap, size=a.size, proximity=prox)
    if out is None:
        print("  exact re-timing: %s in %.0f s -- no timetable" % (status, secs)); return 1
    run = V.verify_solution(inst, out, cell=a.cell, size=a.size, proximity=prox, label="tep_ip_chain")
    bad = [x for x in run.findings if x.severity != "TOLERANCE"]
    ok = (not bad) and (not run.blocking)
    bk = best_artifact(a.cell, a.size)
    print("  exact re-timing: %s in %.0f s -> obj %.1f, %d cars, %d vessels | verifier3 %s | best known %.1f (%+.2f%%)"
          % (status, secs, out["objVal"], out["nCars"], out["nVessel"], "PASS" if ok else "FAIL " + (bad[0].cls if bad else "blk"),
             float(bk[1]["objVal"]) if bk else float("nan"),
             100.0 * (out["objVal"] / float(bk[1]["objVal"]) - 1) if bk else float("nan")), flush=True)
    if ok:
        out["_source"] = "analysis/tep_ip_chain.py: master IP selection + continuous-time chaining"
        out["_ip_street"] = ip["ip_street"]; out["_ip_cars"] = ip["ip_cars"]; out["_verified"] = True
        out["_verifier_recomputed"] = run.objective.get("recomputed"); out["size"] = a.size; out["_proximity"] = prox
        dst = os.path.join(ROOT, "runs", "postpass", "ipchain%s_%s_n%d.json" % (a.tag, a.cell, a.size))
        json.dump(stamped(out, "analysis/tep_ip_chain.py", "analysis/assemble_precluster.py", "analysis/tep_cg_bound.py"),
                  io.open(dst, "w", encoding="utf-8"), indent=1, default=str)
        print("  banked %s" % os.path.relpath(dst, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
