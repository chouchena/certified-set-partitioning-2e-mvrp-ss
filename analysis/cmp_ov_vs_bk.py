"""Compare dual-byproduct OVs (overnight dual_measure + new harvest_measure) to best-known
incumbents (tep_n100_best_of 'best'). Prints only; writes nothing."""
import glob
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def final_ov(path):
    # best (min) verified OV seen, across both schemas: overnight uses OV-event key "ov";
    # harvest uses "ov_final". seed constructor OV is large and never the min.
    best = None
    try:
        for ln in io.open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            if r.get("event") == "seed":
                continue                      # constructor OV, not a refined/verified dual OV
            for k in ("ov_final", "ov"):
                v = r.get(k)
                if isinstance(v, (int, float)):
                    best = v if best is None else min(best, v)
    except Exception:
        pass
    return best


bk = {}
for row in json.load(io.open(os.path.join(ROOT, "runs", "oracle", "tep_n100_best_of.json")))["rows"]:
    bk[row["cell"]] = row.get("best")

cells = ["C204", "C203", "R207", "R211", "RC204", "C201", "C202", "C205", "C206"]
print("%-7s %10s %12s %12s %10s  %s" % ("cell", "BK", "dual_ON", "dual_HARV", "best_dual", "gap%_vs_BK"))
for c in cells:
    on = final_ov(os.path.join(ROOT, "logs", "dual_measure", "%s_n100.jsonl" % c))
    harv = None
    for p in glob.glob(os.path.join(ROOT, "logs", "harvest_measure", "%s_n100_*.jsonl" % c)):
        v = final_ov(p)
        if v is not None and (harv is None or v < harv):
            harv = v
    cands = [x for x in (on, harv) if x is not None]
    best_dual = min(cands) if cands else None
    b = bk.get(c)
    gap = ("%+.2f%%" % (100.0 * (best_dual / b - 1)) if (best_dual is not None and b) else "  -")
    print("%-7s %10s %12s %12s %10s  %s" % (
        c,
        ("%.2f" % b) if b is not None else "-",
        ("%.2f" % on) if on is not None else "-",
        ("%.2f" % harv) if harv is not None else "-",
        ("%.2f" % best_dual) if best_dual is not None else "-",
        gap))
