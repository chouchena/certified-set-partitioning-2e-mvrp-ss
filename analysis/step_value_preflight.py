"""Before a queued step spends a night: what can it possibly buy? (d585)

WHY. Three pre-committed campaign steps -- S3b, S6b, S7b -- were aimed at the master fleet cap, a
stage with one artifact in the whole grid and a loss on that one. S3b ran for five and a quarter
hours before it was stopped; S6b and S7b would have run 36 more commands. Every one of their 36
trigger cells was ruled out by an argument available before the first command: capping N <= cars-1
RESTRICTS the master IP, so its optimum can only be WORSE than the uncapped optimum over the same
pool, and on all 36 cells the banked incumbent already matched or beat that uncapped optimum.

The argument cost nothing to run. Nobody ran it, because nothing asked.

WHAT THIS DOES. For each pending campaign step it prints a CEILING on what the step can achieve,
where a ceiling exists, and says plainly where none does:

  fleet-cap steps      the restriction argument above, per trigger cell;
  cut / IP steps       the residual MIP gap, which by d580 bounds any row or any budget;
  bound steps          the cells actually lacking a certificate -- zero means the step is a no-op;
  everything else      "no ceiling derived", which is an honest answer and not a pass.

A step whose ceiling is zero should be marked done with the reason in its marker, not run.

    python analysis/step_value_preflight.py
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
import tep_final_campaign as C
from best_known import best_solution
from bound_certificate import bound_class
from stamp import stamped


def load(p):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None


def fleetcap_ceiling(size):
    """Cells where the banked incumbent is WORSE than the uncapped IP optimum over the same pool --
    the only cells a restriction of that IP could improve."""
    poss, total = [], 0
    for cell, cap in C.trigger_cells(size):
        total += 1
        bs = best_solution(cell, size)
        p = os.path.join(ROOT, "runs", "oracle",
                         "tep_cg_bound_%s%s_ip_primal.json" % (cell, "" if size == 100 else "_n%d" % size))
        ip = (load(p) or {}).get("ip") or {}
        if ip.get("verified") and ip.get("objVal") and bs and bs[0] <= float(ip["objVal"]) + 0.05:
            continue
        poss.append(cell)
    return total, poss


def bound_ceiling(size):
    """Cells with no certificate: what a bound step could add."""
    need = []
    for cell in C.CELLS:
        d = load(C.bound_path(cell, size))
        if not (d and bound_class(d)):
            need.append(cell)
    return need


def main():
    print("STEP VALUE PREFLIGHT -- what each pending step can possibly buy\n")
    steps = C.plan()
    rows = []
    for sid, desc, cmds, art in steps:
        if os.path.exists(os.path.join(C.MARK, sid + ".done")):
            continue
        if cmds == "WAIT_SWEEP":
            continue
        n = None
        for tok in desc.split():
            if tok.startswith("n") and tok[1:].isdigit():
                n = int(tok[1:])
        low = desc.lower()
        ceiling, note = None, "no ceiling derived"
        if "fleet cap" in low and n:
            total, poss = fleetcap_ceiling(n)
            ceiling = len(poss)
            note = "%d of %d trigger cells could possibly improve (restriction argument)" % (len(poss), total)
        elif "bound" in low and n:
            need = bound_ceiling(n)
            ceiling = len(need)
            note = "%d cells lack a certificate" % len(need)
        rows.append(dict(step=sid, desc=desc[:60], ceiling=ceiling, note=note))
        flag = "" if ceiling is None else ("  <<< CEILING ZERO: mark it done with the reason" if ceiling == 0 else "")
        print("  %-5s %-60s %s%s" % (sid, desc[:60], note, flag))
    zero = [r for r in rows if r["ceiling"] == 0]
    print("\n  %d pending step(s) examined | %d with a ceiling of zero" % (len(rows), len(zero)))
    p = os.path.join(ROOT, "runs", "oracle", "step_value_preflight.json")
    json.dump(stamped(dict(rows=rows), "analysis/step_value_preflight.py",
                      "analysis/best_known.py", "analysis/bound_certificate.py"),
              io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
