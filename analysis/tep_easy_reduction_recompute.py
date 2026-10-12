"""Recompute the n100 subset-master bounds so that every artifact carries its own elementary certificate. (d519)

WHY. The 2026-09-25 batch (89 artifacts, tep_easy_reduction_<cell>_n100_k<drop>.json) stored `proven: true`
but no pricing history, so whether the flag came from the elementary stopping rule (d427) cannot be read
from the artifact; the register holds a STANDING suspension of n100 CG bounds until "a recomputation in
which the elementary proving pass confirms each reported value". This driver is that recomputation, with
the same (cell, drop) pairs, the driver defaults for walls, one run at a time, solo.

WHAT IT CHECKS (CLAUDE.md section 4, a queue checks its own steps): the driver parses and stamps; every
run's artifact exists, carries `_provenance.code_hash`, and carries `certificate` (true or false -- a
false certificate is a RECORD, not a failure: that value is simply not a bound); the old artifact is copied
to runs/oracle/superseded/tep_easy_reduction_2026-09-25/ before it is overwritten; the summary compares the
old and new composed values per pair and is written after every run (resumable: pairs whose artifact already
carries `certificate` are skipped).

    python analysis/tep_easy_reduction_recompute.py            # all 89 pairs
    python analysis/tep_easy_reduction_recompute.py --cells C201 --drops 48   # cheap test first
"""
import argparse
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

PY = sys.executable
OLD = os.path.join(ROOT, "runs", "oracle", "superseded", "tep_easy_reduction_2026-09-25")


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="*", default=None); ap.add_argument("--drops", nargs="*", type=int, default=None)
    ap.add_argument("--max-secs", type=float, default=1200.0); ap.add_argument("--ip-time", type=float, default=900.0)
    ap.add_argument("--with-ip", action="store_true", help="also run the pool-restricted IP estimate (default off since 22:52: it is not part of the bound and cost up to 900 s per pair)")
    a = ap.parse_args()
    pairs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_*_n100_k*.json"))):
        d = load(f)
        if not d: continue
        pairs.append((d["cell"], int(d["drop"]), f))
    if a.cells: pairs = [p for p in pairs if p[0] in set(a.cells)]
    if a.drops: pairs = [p for p in pairs if p[1] in set(a.drops)]
    os.makedirs(OLD, exist_ok=True)
    out = os.path.join(ROOT, "runs", "oracle", "tep_easy_reduction_recompute_n100.json")
    prev = load(out); rows = prev["rows"] if prev else []
    done = {(r["cell"], r["drop"]) for r in rows}
    print("recompute %d (cell, drop) pairs at n100 with the elementary certificate stored; %d already done" % (len(pairs), len(done)), flush=True)
    for cell, drop, f in pairs:
        if (cell, drop) in done: continue
        old = load(f)
        if old is not None and "certificate" not in old:
            shutil.copy2(f, os.path.join(OLD, os.path.basename(f)))          # keep the 2026-09-25 artifact for the record
        elif old is not None and "certificate" in old:
            rows.append(dict(cell=cell, drop=drop, skipped="already carries a certificate", certificate=old["certificate"],
                             lp_composed=old.get("lp_composed"))); continue
        t0 = time.time()
        log = os.path.join(ROOT, "logs", "easyred_recompute_%s_k%d.out" % (cell, drop))
        with io.open(log, "w", encoding="utf-8", errors="replace") as fh:
            rc = subprocess.call([PY, "analysis/tep_easy_reduction.py", cell, "--size", "100", "--drop", str(drop),
                                  "--max-secs", str(a.max_secs), "--ip-time", str(a.ip_time)] + ([] if a.with_ip else ["--no-ip"]), cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
        new = load(f)
        if rc != 0 or new is None or not new.get("_provenance", {}).get("code_hash") or "certificate" not in new:
            rows.append(dict(cell=cell, drop=drop, failed="exit %s / artifact missing certificate or code_hash" % rc, secs=round(time.time() - t0)))
            print("  %-6s k%-2d FAILED (exit %s)" % (cell, drop, rc), flush=True)
        else:
            oc = float(old["lp_composed"]) if old and old.get("lp_composed") is not None else None
            nc = float(new["lp_composed"])
            rows.append(dict(cell=cell, drop=drop, certificate=bool(new["certificate"]), proven=bool(new["proven"]), status=new.get("status"),
                             lp_composed_old=oc, lp_composed_new=nc, old_proven=bool(old.get("proven")) if old else None,
                             delta_pct=(100 * (nc / oc - 1)) if oc else None, secs=round(time.time() - t0)))
            print("  %-6s k%-2d %s  composed %.2f (was %s, %s)  [%ds]"
                  % (cell, drop, "CERTIFIED" if new["certificate"] else "no certificate (%s)" % new.get("status"), nc,
                     ("%.2f" % oc) if oc else "-", ("%+.3f%%" % (100 * (nc / oc - 1))) if oc else "-", time.time() - t0), flush=True)
        json.dump(stamped(dict(size=100, rows=rows)), io.open(out, "w", encoding="utf-8"), indent=1, default=str)
    ok = [r for r in rows if r.get("certificate")]; nocert = [r for r in rows if "certificate" in r and not r["certificate"] and not r.get("skipped")]
    fail = [r for r in rows if r.get("failed")]
    ch = [r for r in rows if r.get("delta_pct") is not None]
    print("\n  %d pairs: %d certified, %d without certificate (%s), %d failed" % (len(rows), len(ok), len(nocert), ", ".join("%s k%d" % (r["cell"], r["drop"]) for r in nocert) or "-", len(fail)))
    if ch:
        d = sorted(r["delta_pct"] for r in ch)
        print("  new vs old composed value: median %+.3f%%, min %+.3f%%, max %+.3f%% over %d pairs" % (st.median(d), d[0], d[-1], len(d)))
    print("  wrote %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
