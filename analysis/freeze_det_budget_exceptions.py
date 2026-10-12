"""Freeze the recovered deterministic tick budgets for rows recorded before 2026-09-15.

WHY A FROZEN EXCEPTION LIST AND NOT JUST A GATE.
`runs/summary.csv` records `status=det_budget_exhausted` for 452 rows -- runs whose PRIMARY
stop rule was a deterministic tick budget -- and `config_json` records that budget for
**zero** of them. A blanket gate demanding the field would therefore fail forever on history,
and a gate that can never pass is worse than no gate: it gets suppressed, and then it is not
watching the new rows either.

So the rule is in two parts:
  * NEW rows must carry `det_budget` in `config_json`            -- enforced by G14
  * HISTORICAL rows are excused, individually, by this frozen file, which records the value
    recovered from each run's own event log and the file it came from.

AUDITED BEFORE FREEZING (author's condition, 2026-09-15):
  452 rows ran under a tick budget; 0 record it in config_json
  446 recovered from event logs, clustering on 4 budgets: 434000, 130200, 32550, 40000
    6 NOT recoverable -- the same (cell, size, seed, variant) was run at two different
      budgets, so the key does not identify the run and recovery correctly refuses to guess
  NONE of those 6 backs a quoted number: they are C203/n20 and C201/n10, and the cells whose
  primal incumbent reaches the manuscript are the 11 R1 ledger cells plus the 7 T2
  objective-identity cells. Verified, not assumed.

The 6 stay marked `unrecoverable` rather than filled in. An exception list that quietly
guesses is the defect it exists to prevent.
"""
import os, sys, csv, json, datetime, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
OUT = os.path.join(ROOT, "validation", "det_budget_exceptions.json")


def main():
    import redump_incumbents as R
    rows = list(csv.DictReader(open(os.path.join(ROOT, "runs/summary.csv"), encoding="utf-8")))
    det = [r for r in rows if r.get("status") == "det_budget_exhausted"]

    entries, unrecoverable = {}, []
    hist = collections.Counter()
    for r in det:
        cfg = json.loads(r["config_json"]) if r.get("config_json") else {}
        if "det_budget" in cfg:
            continue                                  # already compliant; not an exception
        key = f"{r['instance']}/n{r.get('size')}/s{r.get('seed')}/{cfg.get('variant', '-')}"
        v = R.recover_det_budget(r["instance"], r.get("size"), r.get("seed") or 0,
                                 cfg.get("variant", "redump"))
        if v is None:
            unrecoverable.append(key)
            entries[key] = dict(det_budget=None, recovered=False,
                                reason="two different budgets in the logs for this key; "
                                       "the key does not identify the run")
        else:
            entries[key] = dict(det_budget=v, recovered=True,
                                source="runs/fixopt_<cell>_n<size>_s<seed>_<variant>_*.jsonl")
            hist[v] += 1

    doc = dict(
        frozen_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rule="Rows recorded BEFORE frozen_at are excused from carrying det_budget in "
             "config_json, individually, by this file. Rows recorded after it are not: "
             "release_gate G14 requires the field. Adding a row here after the freeze is a "
             "deliberate act and should be argued for, not done to make a gate pass.",
        audited="452 tick-budgeted rows, 0 with det_budget in config_json, 446 recovered, "
                "6 ambiguous and none of those backs a quoted number",
        # ROWS and KEYS differ: several rows can share one (cell, size, seed, variant) key.
        # Reporting only one of the two numbers would misstate the size of the gap.
        n_rows=len(det), n_keys=len(entries),
        n_recovered=sum(1 for e in entries.values() if e["recovered"]),
        n_unrecoverable=len(set(unrecoverable)),
        n_unrecoverable_rows=len(unrecoverable),
        budgets=dict(sorted(hist.items())),
        unrecoverable=sorted(set(unrecoverable)),
        entries=dict(sorted(entries.items())))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(stamped(doc, __file__), open(OUT, "w"), indent=1)
    print(f"  froze {len(entries)} exception(s) to validation/det_budget_exceptions.json")
    print(f"    recovered     : {doc['n_recovered']}")
    print(f"    unrecoverable : {doc['n_unrecoverable']}  {doc['unrecoverable']}")
    print(f"    budgets seen  : {doc['budgets']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
