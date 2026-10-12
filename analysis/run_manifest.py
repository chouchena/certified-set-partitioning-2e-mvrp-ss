"""run_manifest.py -- the single RUN->PROVENANCE traceability registry for the replication repo.

Aggregates every provenance source into runs/RUN_MANIFEST.{json,csv}, one row per run/launch,
and flags each REPLICATION-GRADE (git_sha + code_hash present) or DEV (un-provenanced, pre-system).
Sources:
  A. runs/audit_tokens/*.json  -- gated launches (richest: cmd, git, code_hash, seed, cores, solver,
     adversary_id, recompute_reason, created_at). These are replication-grade.
  B. runs/provenance.csv       -- RunLogger runs (sidecar; many historical/incomplete).
  C. results/ledger.jsonl      -- ledger records (provenance field only on post-2026-09-06 emits).
Regenerate before every commit / before submission so the repo always ships a current manifest.
"""
import csv, glob, json, os
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(fp):
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        return None


def main():
    rows = []
    # A. gated launches (replication-grade by construction)
    for fp in sorted(glob.glob(os.path.join(ROOT, "runs", "audit_tokens", "*.json"))):
        t = _load(fp) or {}
        p = t.get("provenance") or {}
        rows.append({"source": "audit_token", "id": t.get("hash"), "cmd": t.get("cmd"),
                     "cells": t.get("cells"), "size": t.get("size"), "kind": t.get("kind"),
                     "git_sha": p.get("git_sha"), "git_dirty": p.get("git_dirty"),
                     "code_hash": p.get("code_hash"), "seed": t.get("seed") or p.get("seed"),
                     "cores": t.get("cores") or p.get("cores"), "solver": p.get("solver"),
                     "adversary_id": t.get("adversary_id"), "recompute_reason": t.get("recompute_reason"),
                     "when": t.get("created_at")})
    # B. RunLogger provenance sidecar
    pcsv = os.path.join(ROOT, "runs", "provenance.csv")
    if os.path.exists(pcsv):
        for r in csv.DictReader(open(pcsv, encoding="utf-8")):
            rows.append({"source": "runlogger", "id": r.get("run_id"), "cmd": None,
                         "cells": r.get("instance"), "size": r.get("size"), "kind": None,
                         "git_sha": r.get("git_sha"), "git_dirty": r.get("git_dirty"),
                         "code_hash": r.get("code_hash"), "seed": r.get("seed"),
                         "cores": r.get("cores"), "solver": r.get("solver"),
                         "adversary_id": None, "recompute_reason": None, "when": r.get("closed_at")})
    # grade
    for r in rows:
        r["replication_grade"] = bool(r.get("git_sha") and r.get("code_hash"))

    graded = sum(1 for r in rows if r["replication_grade"])
    # C. historical un-provenanced counts (for the honesty header)
    led = [json.loads(l) for l in open(os.path.join(ROOT, "results", "ledger.jsonl"), encoding="utf-8")] \
        if os.path.exists(os.path.join(ROOT, "results", "ledger.jsonl")) else []
    led_noprov = sum(1 for l in (json.loads(x) if isinstance(x, str) else x for x in led) if not (l.get("provenance")))
    run_logs = len(glob.glob(os.path.join(ROOT, "runs", "*.jsonl")))

    out = {"replication_grade_runs": graded, "total_registry_rows": len(rows),
           "historical_ledger_records_no_provenance": led_noprov,
           "historical_run_logs": run_logs,
           "note": "Replication-grade = git_sha+code_hash present. Historical dev runs are "
                   "un-provenanced (pre-2026-09-06 provenance system) and UN-BACKFILLABLE -> "
                   "paper-final results must be REGENERATED under the gated system.",
           "rows": rows}
    json.dump(stamped(out, __file__), open(os.path.join(ROOT, "runs", "RUN_MANIFEST.json"), "w"), indent=2)
    with open(os.path.join(ROOT, "runs", "RUN_MANIFEST.csv"), "w", newline="", encoding="utf-8") as fh:
        fields = ["source", "id", "replication_grade", "git_sha", "code_hash", "seed", "cores",
                  "solver", "cells", "size", "kind", "adversary_id", "recompute_reason", "when", "cmd"]
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"RUN_MANIFEST: {len(rows)} registry rows, {graded} REPLICATION-GRADE (git+code_hash).")
    print(f"Historical un-provenanced: {led_noprov} ledger records, ~{run_logs} run-logs -> DEV, un-backfillable.")
    print("wrote runs/RUN_MANIFEST.json + .csv")


if __name__ == "__main__":
    main()
