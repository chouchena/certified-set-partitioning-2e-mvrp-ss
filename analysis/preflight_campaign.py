"""Campaign preflight: the double-checks that must PASS before any multi-cell launch. (d522)

WHY THIS EXISTS. On 2026-09-26 three campaigns went out on a flag that nobody asked the artifact to prove:
an --lp-only mode that could never fire ran four full MIPs; a waiter matched a DONE marker left by a crashed
earlier launch and reported a result before the run had written it; and 89 + 24 n100 bound artifacts carried
`proven: true` with no stored certificate, which put an uncertified headline into the claims register for
twenty minutes. Each was cheap to catch BEFORE the launch and expensive after. This script runs those
catches, in order, and refuses the campaign if any fails. It never launches anything itself.

    python analysis/preflight_campaign.py --name easyred_recompute_n100 --kind bound \
        --driver analysis/tep_easy_reduction_recompute.py \
        --test-cmd "python analysis/tep_easy_reduction.py C201 --size 100 --drop 48" \
        --artifact runs/oracle/tep_easy_reduction_C201_n100_k48.json \
        --markers "logs/*.marker" --claims-tokens n100,bound --ack-claims tep-cg-bounds-suspended-pending-proof

CHECKS
  P1 driver parses and calls stamped(            -- an unstamped result is not a result
  P2 no wall-bounded solver process is live       -- d415: wall-stopped runs go solo (override: --allow-live)
  P3 armed waiters listed                         -- informational, printed so a duplicate waiter is seen
  P4 stale markers removed                        -- a waiter must never match a marker from an earlier launch
  P5 register: STANDING claims that mention the campaign tokens AND suspension/pending/retraction wording
                                                  -- each must be acknowledged by id, or the run is refused
  P6 the one-cell cheap test exits 0 within --test-timeout
  P7 the artifact contract: JSON, _provenance.code_hash, and for kind=bound certified(d) (bound_certificate),
     for kind=primal _verified true + objVal + nCars; secs stamped
  The record is written to runs/oracle/preflight/<name>_<stamp>.json and the ledger cites it.
"""
import argparse
import ast
import glob
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
from bound_certificate import certified, why_not

SOLVER_DRIVERS = ("tep_cg_bound.py", "tep_chain_own_water.py", "tep_select_chain.py", "tep_master_fleet_cap.py", "tep_alns.py",
                  "tep_refine.py", "tep_easy_reduction", "tep_ceil_n30_batch.py", "tep_fine_delta_bound_batch.py", "tep_n50_batch.py", "fixopt")


def live_solver_processes():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process -Filter \"name like 'python%'\" | ForEach-Object { $_.ProcessId.ToString() + ' ' + $_.CommandLine }"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        return ["<census failed: %r>" % e]
    me = str(os.getpid())
    # the preflight's own command line names the drivers it checks; exclude itself (first-use false positive, 22:34)
    return [l.strip() for l in out.splitlines() if any(k in l for k in SOLVER_DRIVERS) and "preflight_campaign.py" not in l and not l.strip().startswith(me + " ")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True); ap.add_argument("--kind", choices=("bound", "primal"), required=True)
    ap.add_argument("--driver", required=True, help="the campaign driver to be launched afterwards")
    ap.add_argument("--test-cmd", required=True, help="the one-cell cheap test, run from ROOT")
    ap.add_argument("--artifact", required=True, help="the artifact the cheap test must produce")
    ap.add_argument("--markers", default="", help="glob of marker files a waiter will watch; stale ones are removed")
    ap.add_argument("--claims-tokens", default="", help="comma list; STANDING claims mentioning any token AND suspend/pending/retract wording must be acknowledged")
    ap.add_argument("--ack-claims", default="", help="comma list of claim ids acknowledged")
    ap.add_argument("--allow-live", action="store_true"); ap.add_argument("--test-timeout", type=float, default=900.0)
    a = ap.parse_args()
    checks = []
    def check(name, ok, detail):
        checks.append(dict(check=name, ok=bool(ok), detail=str(detail)[:600])); print("  [%s] %-4s %s" % ("PASS" if ok else "FAIL", name, str(detail)[:150]), flush=True)
    print("PREFLIGHT %s (%s campaign) %s" % (a.name, a.kind, time.strftime("%Y-%m-%d %H:%M:%S")))
    # P1
    try:
        src = io.open(os.path.join(ROOT, a.driver), encoding="utf-8").read(); ast.parse(src)
        check("P1", "stamped(" in src, "driver parses; stamped( %s" % ("present" if "stamped(" in src else "MISSING"))
    except Exception as e:
        check("P1", False, "driver does not parse: %r" % e)
    # P2
    live = live_solver_processes()
    check("P2", (not live) or a.allow_live, ("no live solver process" if not live else "LIVE: %s" % "; ".join(l[:80] for l in live)) + (" (override --allow-live)" if live and a.allow_live else ""))
    # P3
    try:
        w = subprocess.run([sys.executable, os.path.join(ROOT, "analysis", "waiters.py")], capture_output=True, text=True, timeout=120, cwd=ROOT).stdout
        rows = [l for l in w.splitlines() if l and not l.startswith("pid") and "harness shell" not in l and "waiters.py" not in l and not l.endswith("processes.") and "Arm nothing" not in l]
        check("P3", True, "%d waiter/job rows: %s" % (len(rows), " | ".join(r[:60] for r in rows[:4])))
    except Exception as e:
        check("P3", True, "waiters.py unavailable: %r" % e)
    # P4
    stale = glob.glob(os.path.join(ROOT, a.markers)) if a.markers else []
    for m in stale:
        os.remove(m)
    check("P4", True, ("removed %d stale marker(s): %s" % (len(stale), ", ".join(os.path.basename(m) for m in stale))) if stale else "no stale markers")
    # P5
    toks = [t.strip().lower() for t in a.claims_tokens.split(",") if t.strip()]
    acks = {t.strip() for t in a.ack_claims.split(",") if t.strip()}
    hits = []
    if toks:
        reg = json.load(io.open(os.path.join(ROOT, "validation", "claims.json"), encoding="utf-8")); reg = reg if isinstance(reg, list) else reg.get("claims", [])
        for c in reg:
            if c.get("status") != "STANDING": continue
            text = (str(c.get("id", "")) + " " + str(c.get("claim", ""))).lower()
            if any(t in text for t in toks) and any(k in text for k in ("suspend", "pending", "retract", "not sound", "invalid")):
                hits.append(c["id"])
    un = [h for h in hits if h not in acks]
    check("P5", not un, ("%d STANDING claim(s) touch this campaign: %s%s" % (len(hits), ", ".join(hits), (" -- UNACKNOWLEDGED: %s" % ", ".join(un)) if un else " -- all acknowledged")) if hits else "no standing suspension/pending claim mentions %s" % toks)
    # P6
    t0 = time.time()
    try:
        r = subprocess.run(a.test_cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=a.test_timeout)
        check("P6", r.returncode == 0, "cheap test exit %d in %.0f s%s" % (r.returncode, time.time() - t0, "" if r.returncode == 0 else " | tail: " + (r.stdout + r.stderr)[-300:].replace("\n", " / ")))
    except subprocess.TimeoutExpired:
        check("P6", False, "cheap test exceeded %.0f s" % a.test_timeout)
    # P7
    p = os.path.join(ROOT, a.artifact); d = None
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        check("P7", False, "artifact missing or not JSON: %r" % e)
    if d is not None:
        ok = bool((d.get("_provenance") or {}).get("code_hash")); why = [] if ok else ["no code_hash"]
        if a.kind == "bound":
            if not certified(d): ok = False; why.append("NOT certified: " + why_not(d))
            if d.get("lp_street") is None and d.get("lp_composed") is None: ok = False; why.append("no lp value")
        else:
            if not d.get("_verified"): ok = False; why.append("not verified")
            if d.get("objVal") is None or d.get("nCars") is None: ok = False; why.append("no objVal/nCars")
        if d.get("secs") is None: why.append("(secs not stamped: runtime cannot be charged)")
        check("P7", ok, ("artifact contract holds" + ("; " + "; ".join(why) if why else "")) if ok else "; ".join(why))
    passed = all(c["ok"] for c in checks)
    os.makedirs(os.path.join(ROOT, "runs", "oracle", "preflight"), exist_ok=True)
    out = os.path.join(ROOT, "runs", "oracle", "preflight", "%s_%s.json" % (a.name, time.strftime("%Y%m%d_%H%M%S")))
    json.dump(stamped(dict(name=a.name, kind=a.kind, driver=a.driver, test_cmd=a.test_cmd, artifact=a.artifact, checks=checks, passed=passed)),
              io.open(out, "w", encoding="utf-8"), indent=1, default=str)
    print("  %s -- record %s" % ("PREFLIGHT PASSED: the campaign may be launched (by hand, with this record cited)" if passed else "PREFLIGHT FAILED: do not launch", os.path.relpath(out, ROOT)))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
