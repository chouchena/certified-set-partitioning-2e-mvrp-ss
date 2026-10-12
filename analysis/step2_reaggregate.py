"""Rebuild step 2's result from its OWN stamped dumps, without re-solving anything.

WHY THIS EXISTS RATHER THAN A RE-RUN. runs/oracle/step2_bigm.json was written by an aggregator
that attached no provenance, so under the standing rule it is not evidence and was quarantined.
But the thing it aggregates -- 36 fixopt dumps in runs/step2/ -- each carry a full stamp:
_code_hash, _git_sha, _engine_version, _verifier_code_hash, _solver_version, _seed, _proximity,
_valid_bigm, _posts_26. The SOLVING is therefore already attributable. Only the summary was not.

Re-solving would cost about five hours and would produce different incumbents, because the
budget is wall-clock. Re-deriving costs the pin checks alone and produces the SAME result from
the SAME artifacts -- which is what reproducing a summary is supposed to mean.

WHAT IS RECOMPUTED, not copied:
    verifier3 on every valid-M incumbent                       (deterministic, cheap)
    the pin into K's FAITHFUL model: ADMITS or EXCLUDES        (deterministic given the dump)
Both read only the dump and the model code, and both are re-derived here so that no verdict in
the output is inherited from a file that could not be attributed.

WHAT IS COPIED: the objective values and the run metadata, straight out of the stamped dumps.

Every dump's own code_hash is carried into the aggregate, so a reader can see whether the 36 runs
were produced by one code version or several. They were not all produced by one: the stamping
landed mid-campaign, and saying so is the point.

    python analysis/step2_reaggregate.py [--tl 300] [--threads 4]
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import verifier3
from step2_bigm_n50n100 import faithful_admits

OUT = os.path.join(ROOT, "runs", "oracle")
DUMPS = os.path.join(ROOT, "runs", "step2")
NAME = re.compile(r"s2_(validM|faithfulM)_((?:RC|R|C)\d{3})_n(\d+)_s(\d+)\.json$")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=300.0)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    found = {}
    unstamped = []
    for p in sorted(glob.glob(os.path.join(DUMPS, "*.json"))):
        m = NAME.search(os.path.basename(p))
        if not m:
            continue
        arm, cell, size, seed = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        d = json.load(io.open(p, encoding="utf-8"))
        if not d.get("_code_hash"):
            unstamped.append(os.path.basename(p))
            continue
        found[(cell, size, seed, arm)] = (p, d)

    print("STEP 2, RE-AGGREGATED from stamped dumps -- no solve is repeated.")
    print("        Pin checks and verifier3 ARE recomputed, so no verdict is inherited from")
    print("        the aggregate that could not be attributed.")
    print()
    if unstamped:
        print("   %d dump(s) carry no _code_hash and are EXCLUDED, not silently averaged in:"
              % len(unstamped))
        for u in unstamped[:8]:
            print("      " + u)
        print()

    keys = sorted({(c, s, sd) for c, s, sd, _arm in found}, key=lambda k: (k[1], k[0], k[2]))
    print("   %-7s %5s %5s %-6s %12s %-9s %-16s %-10s"
          % ("cell", "n", "seed", "arm", "obj", "verifier3", "faithful model", "code_hash"))
    rows, witnesses, hashes = [], [], {}
    t0 = time.time()
    for cell, size, seed in keys:
        rec = dict(cell=cell, size=size, seed=seed)
        vp = found.get((cell, size, seed, "validM"))
        fp = found.get((cell, size, seed, "faithfulM"))
        if vp:
            path, d = vp
            hashes.setdefault(d["_code_hash"], 0)
            hashes[d["_code_hash"]] += 1
            vrun = verifier3.verify(path)
            verdict = faithful_admits(path, tl=a.tl, threads=a.threads)
            rec.update(valid_obj=d["objVal"], valid_verifier=vrun.verdict(),
                       valid_provenance=vrun.meta.get("provenance"),
                       valid_code_hash=d["_code_hash"], valid_engine=d.get("_engine_version"),
                       valid_dump=os.path.relpath(path, ROOT), faithful_model=verdict)
            if verdict == "EXCLUDES" and vrun.verdict() == verifier3.ACCEPT:
                witnesses.append("%s/n%d seed %d: obj %.3f, verifier3 ACCEPT, and the FAITHFUL "
                                 "model rules it INFEASIBLE" % (cell, size, seed, d["objVal"]))
            print("   %-7s %5d %5d %-6s %12.3f %-9s %-16s %-10s"
                  % (cell, size, seed, "valid", d["objVal"], vrun.verdict(), verdict,
                     d["_code_hash"][:8]), flush=True)
        if fp:
            path, d = fp
            hashes.setdefault(d["_code_hash"], 0)
            hashes[d["_code_hash"]] += 1
            rec.update(faithful_obj=d["objVal"], faithful_code_hash=d["_code_hash"],
                       faithful_dump=os.path.relpath(path, ROOT))
            if rec.get("valid_obj") is not None:
                rec["delta"] = rec["valid_obj"] - d["objVal"]
            print("   %-7s %5d %5d %-6s %12.3f %-9s %-16s %-10s"
                  % ("", size, seed, "faith", d["objVal"], "-", "", d["_code_hash"][:8]),
                  flush=True)
        rows.append(rec)

    print()
    print("   pairs %d   WITNESSES (valid-M incumbent the faithful model excludes): %d"
          % (len(rows), len(witnesses)))
    for w in witnesses:
        print("      " + w)
    print()
    if witnesses:
        print("   FINDING. K's constants exclude solutions that are feasible for the model their")
        print("   article states, at the sizes our results live at. One witness suffices, and")
        print("   no budget argument weakens it, because the solution exists.")
    else:
        print("   NOT OBSERVED on these dumps. It does NOT show the constant is harmless: our")
        print("   search may never visit the excluded region.")

    print()
    print("   CODE VERSIONS BEHIND THESE DUMPS: %d distinct" % len(hashes))
    for h, n in sorted(hashes.items(), key=lambda kv: -kv[1]):
        print("      %-12s %d dump(s)" % (h[:12], n))
    if len(hashes) > 1:
        print("   More than one. The stamping landed mid-campaign, so the campaign is NOT")
        print("   single-version; that is recorded here rather than averaged away.")

    deltas = [r["delta"] for r in rows if r.get("delta") is not None]
    if deltas:
        print()
        print("   SECONDARY, bounding nothing at these sizes: paired delta over %d pairs, "
              "valid - faithful. negative %d, zero %d, positive %d."
              % (len(deltas), sum(1 for d in deltas if d < -1e-6),
                 sum(1 for d in deltas if abs(d) <= 1e-6),
                 sum(1 for d in deltas if d > 1e-6)))
        print("   Both arms are budget-limited incumbents, so a sign means the search, not the")
        print("   model. No claim rests on it.")

    json.dump(stamped({"rows": rows, "witnesses": witnesses, "pairs": len(rows),
                       "dump_code_hashes": hashes, "excluded_unstamped_dumps": unstamped,
                       "reaggregated": True, "pin_tl": a.tl,
                       "wall_s": round(time.time() - t0, 1)},
                      __file__, "analysis/step2_bigm_n50n100.py", "joint_model_gurobi.py",
                      "analysis/verifier3.py"),
              io.open(os.path.join(OUT, "step2_bigm.json"), "w", encoding="utf-8"),
              indent=1, default=str)
    print()
    print("   %.1f min -> runs/oracle/step2_bigm.json" % ((time.time() - t0) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
