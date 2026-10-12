"""preflight.py -- the LAUNCH GATE. Produces an audit token ONLY if the run passes
mechanical checks. The run's entry point AND the PreToolUse hook require a fresh
token whose hash matches the command, so a run that skips preflight cannot start
(enforcement by artifact, not by memory).

Hard-fail checks:
  A  RESULT-ON-DISK: refuse if a PROVEN result for any target cell already exists
     (analysis.ledger.best_proven_on_disk) unless --recompute-reason is given.
  D  LOGGING: refuse if --harness contains track_progress=False (Rule-4 infringement).
  E   ADVERSARY: refuse without a non-empty --adversary-id (the hostile pre-launch pass).
  R13 COMPARABILITY: if --vs-karademir, refuse unless --cores is declared AND equals K's
      basis (4), unless --screen-note labels it a non-comparison SCREEN.

Usage:
  python -m analysis.preflight --cmd "python validation/foo.py ..." \
      --cells R207,R203 --size 20 --kind lb --harness validation/foo.py \
      --adversary-id <agentId> [--recompute-reason "tracked RT-curve re-run"]
"""
import argparse, hashlib, json, os, re, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped
from analysis.ledger import best_proven_on_disk, reproduced_baseline_on_disk

TOKDIR = os.path.join(ROOT, "runs", "audit_tokens")


def norm_cmd(cmd: str) -> str:
    return re.sub(r"\s+", " ", (cmd or "").strip())


def cmd_hash(cmd: str) -> str:
    return hashlib.sha256(norm_cmd(cmd).encode()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="the EXACT launch command the run will use")
    ap.add_argument("--cells", default="", help="comma list of target cells (disk-check)")
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--kind", default="lb", choices=["lb", "ub"])
    ap.add_argument("--harness", default="", help="harness file path (logging grep)")
    ap.add_argument("--adversary-id", required=True, help="id of the hostile pre-launch audit")
    ap.add_argument("--recompute-reason", default="", help="stated override for the disk-check")
    ap.add_argument("--vs-karademir", action="store_true",
                    help="R13: this run's output may feed a comparison against Karademir")
    ap.add_argument("--cores", type=int, default=0, help="core count the run will use (R13)")
    ap.add_argument("--screen-note", default="",
                    help="R13 override: label a non-comparable-cores run as a SCREEN, not a comparison figure")
    ap.add_argument("--reproduce-baseline", action="store_true",
                    help="this run reproduces K's LBBD baseline (checks runs/lbbd_*.jsonl for recompute)")
    ap.add_argument("--seed", default="", help="seed(s) the run will use (recorded in the token)")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="permit launch on a dirty git tree (state still captured by code_hash, but not a clean SHA)")
    a = ap.parse_args()

    K_CORES = 4   # Karademir's Gurobi CPU budget (the comparable basis)

    fails = []
    existing = {}
    for c in [x.strip() for x in a.cells.split(",") if x.strip()]:
        r = best_proven_on_disk(c, a.size, a.kind, ROOT)
        if r:
            existing[c] = r
    if existing and not a.recompute_reason:
        fails.append(f"[A] RESULT-ON-DISK: proven {a.kind} already exists {existing}. "
                     "Pass --recompute-reason to override (e.g. tracked-trajectory re-run).")
    if a.reproduce_baseline:
        base = {}
        for c in [x.strip() for x in a.cells.split(",") if x.strip()]:
            r = reproduced_baseline_on_disk(c, a.size, ROOT)
            if r:
                base[c] = r
        if base and not a.recompute_reason:
            fails.append(f"[A-BASELINE] K-LBBD REPRODUCTION already on disk {base} "
                         "(runs/lbbd_*.jsonl). Pass --recompute-reason to override.")
    if a.harness and os.path.exists(os.path.join(ROOT, a.harness)):
        txt = open(os.path.join(ROOT, a.harness), encoding="utf-8", errors="ignore").read()
        if re.search(r"track_progress\s*=\s*False", txt):
            fails.append(f"[D] LOGGING: {a.harness} has track_progress=False (Rule-4 infringement).")
    if not a.adversary_id.strip():
        fails.append("[E] ADVERSARY: no --adversary-id (hostile pre-launch audit required).")
    try:
        import subprocess
        _dirty = bool(subprocess.run(["git", "-C", ROOT, "status", "--porcelain"],
                                     capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception:
        _dirty = False
    if _dirty and not a.allow_dirty:
        fails.append("[GIT] DIRTY TREE: uncommitted changes — commit first so the run stamps a CLEAN SHA "
                     "('always commit before runs'), or pass --allow-dirty. `git add -A && git commit`.")
    if a.vs_karademir:
        if a.cores <= 0:
            fails.append("[R13] COMPARABILITY: --vs-karademir set but --cores not declared "
                         f"(Karademir basis = {K_CORES} cores). Declare the core count.")
        elif a.cores != K_CORES and not a.screen_note.strip():
            fails.append(f"[R13] COMPARABILITY: {a.cores} cores != Karademir basis ({K_CORES}). "
                         "A non-comparable-cores run cannot enter a comparison table. Either run "
                         f"at {K_CORES} cores, or pass --screen-note to label it a SCREEN (not a figure).")

    if fails:
        sys.stderr.write("PREFLIGHT REFUSED:\n  - " + "\n  - ".join(fails) + "\n")
        sys.exit(2)

    prov = None
    try:
        from analysis.provenance import stamp as _prov_stamp
        prov = _prov_stamp(seed=(a.seed or None), cores=(a.cores or None))
    except Exception:
        prov = None
    os.makedirs(TOKDIR, exist_ok=True)
    h = cmd_hash(a.cmd)
    json.dump({"hash": h, "cmd": norm_cmd(a.cmd), "cells": a.cells, "size": a.size,
               "kind": a.kind, "adversary_id": a.adversary_id,
               "recompute_reason": a.recompute_reason, "existing_on_disk": existing,
               "vs_karademir": a.vs_karademir, "cores": a.cores, "seed": a.seed,
               "screen_note": a.screen_note, "K_cores": K_CORES, "provenance": prov,
               "created_at": datetime.datetime.now().isoformat(timespec="seconds")},
              open(os.path.join(TOKDIR, h + ".json"), "w"), indent=2)
    print("PREFLIGHT OK. token:", h)


if __name__ == "__main__":
    main()
