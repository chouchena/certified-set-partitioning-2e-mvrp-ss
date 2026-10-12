"""Per-instance report: new bound vs the earlier run and vs K, for cells finished so far.

Usage: python cellreport.py <size> [cell ...]
Reads only artifacts the run has DECLARED done, to avoid the mid-descent partial-maximum
error that misreported R207 as 549.16 when it finished at 588.59.
"""
import json
import os
import re
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "analysis")
from lb_monitor import k_table3, fam          # noqa: E402

SIZE = int(sys.argv[1])
WANT = sys.argv[2:]
# SIZE ON BOTH SIDES OF THE JOIN. lb_n20_reprov.log was listed unconditionally, so at
# SIZE != 20 every cell that finished in the n20 reprov run was reported as a finished
# cell at this size, carrying its n20 wall time. Same defect class as the rt_normalize
# stage-4 bug that voided the M7 report on 2026-09-17.
LOGS = [f"runs/lb_reprov_n{SIZE}.log", f"runs/lb_repair_n{SIZE}.log"]
if SIZE == 20:
    LOGS.insert(0, "runs/lb_n20_reprov.log")


def finished():
    done = []
    for fp in LOGS:
        if not os.path.exists(fp):
            continue
        for l in open(fp, encoding="utf-8", errors="replace"):
            m = re.search(r"^\[[\d:]+\]\s+((?:C|R|RC)\d{3}) done in (\d+)s", l)
            if m:
                done.append((m.group(1), int(m.group(2))))
    return done


def recs(fp):
    if not os.path.exists(fp):
        return []
    try:
        r = json.load(open(fp, encoding="utf-8"))
    except Exception:
        return []
    return [x for x in (r if isinstance(r, list) else [r])
            if isinstance(x, dict) and x.get("block_relax") is not None]


def best(fp):
    r = recs(fp)
    return (max(x["block_relax"] for x in r), len(r),
            sum(1 for x in r if x.get("proven"))) if r else (None, 0, 0)


def main():
    t3 = k_table3(SIZE)
    AB = {}
    try:
        AB = {r["cell"]: r for r in json.load(open("runs/ab4_grid_results.json")).values()
              if "error" not in r and r["size"] == SIZE}
    except Exception:
        pass
    rows = [(c, s) for c, s in finished() if not WANT or c in WANT]
    if not rows:
        print("(no finished cells yet)")
        return
    print(f"{'cell':6}{'wall':>6}{'OLD':>9}{'NEW':>9}{'delta':>8}{'rec':>4}{'prv':>4}"
          f"{'PORT':>9}{'K LB':>9}{'ours/K':>8}{'K cert':>8}{'we cert':>8}  flag")
    for c, secs in rows:
        new, nr, npv = best(f"crossfeed/easy_reduction_descend_{c}_n{SIZE}.json")
        o1, _, _ = best(f"crossfeed/easy_reduction_descend_{c}_n{SIZE}_noprov.json")
        o2, _, _ = best(f"crossfeed/easy_reduction_{c}_n{SIZE}.json")
        old = max([v for v in (o1, o2) if v is not None], default=None)
        ab = AB.get(c, {}).get("ab4")
        port = max([v for v in (new, ab) if v is not None], default=None)
        k = t3.get(c)
        klb, kbk = (k[0], k[2]) if k else (None, None)
        d = f"{(new - old) / old * 100:+7.1f}%" if (new and old) else "      --"
        flag = []
        if new and old and new < old - 1e-6:
            flag.append("REGRESSION")
        if port and kbk and port > kbk + 1e-6:
            flag.append("*** ABOVE BK -- INVALID")
        if ab and new and ab > new:
            flag.append("AB carries")
        print(f"{c:6}{secs:>6}{(old if old else 0):>9.2f}{(new if new else 0):>9.2f}{d}"
              f"{nr:>4}{npv:>4}{(port if port else 0):>9.2f}"
              f"{(klb if klb else 0):>9.2f}"
              f"{(port / klb if (port and klb) else 0):>8.2f}"
              f"{(klb / kbk * 100 if (klb and kbk) else 0):>7.1f}%"
              f"{(port / kbk * 100 if (port and kbk) else 0):>7.1f}%  {' '.join(flag)}")


if __name__ == "__main__":
    main()
