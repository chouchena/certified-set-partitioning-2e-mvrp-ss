"""Backfill `det_used` into the ledger rows of runs whose per-run log recorded it (G14, d415).

The TEP harness recorded the deterministic ticks in its artifact and in its per-run event log
(`runs/<run_id>.jsonl`, the `retime` note) but not in the config the ledger serialises, so 84
rows closed after the gate armed carry no det_used and G14 blocks. This copies the SAME
measurement from each run's own log into its row and marks it `det_backfilled_from: runlog`.
Nothing is invented: a row whose log has no det_used is left untouched and reported.

Staged and all-or-nothing (CLAUDE.md section 4): the whole file is rebuilt in memory, every row
re-parsed and every config_json re-validated as JSON, and only then written, after a backup.

    python analysis/backfill_det_ledger.py [--apply]     (default: dry run)
"""
import argparse
import csv
import datetime
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMM = os.path.join(ROOT, "runs", "summary.csv")


def det_from_log(run_id):
    p = os.path.join(ROOT, "runs", "%s.jsonl" % run_id)
    if not os.path.exists(p):
        return None, None
    det = lim = None
    try:
        for line in io.open(p, encoding="utf-8"):
            e = (json.loads(line).get("extra") or {})
            if isinstance(e, dict) and e.get("det_used") is not None:
                det, lim = e["det_used"], e.get("det_limit")
    except Exception:
        return None, None
    return det, lim


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    with io.open(SUMM, encoding="utf-8", newline="") as fh:
        rdr = csv.DictReader(fh); fields = rdr.fieldnames; rows = list(rdr)
    armed = min(r["closed_at"] for r in rows
                if r.get("config_json") and "det_used" in json.loads(r["config_json"]) and r.get("closed_at"))
    filled = missing = 0
    for r in rows:
        if not r.get("closed_at") or r["closed_at"] < armed:
            continue
        cfg = json.loads(r["config_json"] or "{}")
        if "det_used" in cfg:
            continue
        det, lim = det_from_log(r["run_id"])
        if det is None:
            missing += 1
            print("  NO det_used in the log of %s (%s)" % (r["run_id"], r.get("status")))
            continue
        cfg["det_used"] = det
        cfg["det_bound"] = bool(lim and det >= 0.98 * float(lim))
        cfg["det_backfilled_from"] = "runlog"
        r["config_json"] = json.dumps(cfg, default=str)
        filled += 1
    # stage: rebuild, re-parse, validate every row before anything is written
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields); w.writeheader()
    for r in rows:
        w.writerow(r)
    text = buf.getvalue()
    chk = list(csv.DictReader(io.StringIO(text)))
    assert len(chk) == len(rows), "row count changed: %d -> %d" % (len(rows), len(chk))
    for r in chk:
        assert len(r) == len(fields), "field count changed on %s" % r.get("run_id")
        if r.get("config_json"):
            json.loads(r["config_json"])
    print("%d row(s) backfilled, %d without a usable log, %d rows total, re-parse OK" % (filled, missing, len(chk)))
    if not a.apply:
        print("dry run; pass --apply to write"); return 0
    bak = SUMM + ".bak_g14_" + datetime.date.today().isoformat()
    shutil.copy(SUMM, bak)
    io.open(SUMM, "w", encoding="utf-8", newline="").write(text)
    print("written; backup %s" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
