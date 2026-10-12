"""Score a coverage sweep, with the provenance checks I kept failing by hand.

WHY THIS EXISTS. In ten minutes on 2026-09-18 I misread the same sweep three times:
  * called R202 a failure on its `verify=REJECT` lines, then over-corrected and called it a
    success because it dumped 4,722.1 -- BOTH WRONG. fixopt.py:1404 sets
    run_valid = verified = (rejects == 0), so ANY rejection invalidates the WHOLE run and it
    is moved to runs/invalid/ with run_valid = NO. R202 had 17 rejects. It is not a weaker
    result; it is not a result;
  * reported C201 as a verified n100 solution when its dump was STALE, left behind from a
    run configuration I had banked as invalid two hours earlier and whose .jsonl I had
    deleted without deleting the dump;
  * reported C207's construction as though it were a result, when all 23 of its improvements
    had been rejected and it never improved at all.

Every one of those is checkable mechanically. So it is checked mechanically.

THE THREE CHECKS, applied to every dumped solution:
  1. PROVENANCE -- the dump's `_run_id` must match a run log that still exists. An orphaned
     dump is quarantined, not reported. (CLAUDE.md section 4, "stale artifacts outliving
     their headline".)
  2. IMPROVEMENT -- the banked objective is compared to the run's FIRST incumbent. A dump
     equal to the construction is reported as CONSTRUCTION ONLY, never as a result.
  3. VALIDITY -- the run must not be quarantined. A single verifier rejection anywhere in the
     run sets run_valid = NO for the entire run (fixopt.py:1404), which is a far stricter rule
     than "the rejected solutions were discarded". Rejections are NOT routine.
"""
import glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import analysis.manuscript_numbers as M                       # noqa: E402

FAM = lambda c: "RC" if c.startswith("RC") else c[0]


def load(p):
    out = []
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


def run_index(size):
    """run_id -> run facts. Searches runs/ AND runs/invalid/.

    A run whose verifier rejected ANY solution is moved to runs/invalid/ and recorded with
    run_valid = NO (fixopt.py:1404 sets run_valid = verified = (rejects == 0)). Such a run is
    NOT a weaker result -- it is not a result. Looking only in runs/ made these read as
    "orphaned dumps", which understates it: they are quarantined.
    """
    idx = {}
    pats = [os.path.join(ROOT, "runs", "fixopt_*_n%d_*.jsonl" % size),
            os.path.join(ROOT, "runs", "invalid", "fixopt_*_n%d_*.jsonl" % size)]
    for f in [x for pat in pats for x in glob.glob(pat)]:
        m = re.search(r"fixopt_((?:C|R|RC)\d{3})_n%d_" % size, os.path.basename(f))
        if not m:
            continue
        rows = load(f)
        if not rows:
            continue
        rid = os.path.basename(f)[:-6]
        st = ver = None
        for r in rows:
            e = r.get("extra") or {}
            if isinstance(e, dict):
                if e.get("status"):
                    st = e["status"]
                if e.get("verified") is not None:
                    ver = e["verified"]
        ov = [r["best_incumbent"] for r in rows
              if isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0]
        idx[rid] = dict(cell=m.group(1), first=(ov[0] if ov else None),
                        best=(min(ov) if ov else None), status=st, verified=ver, n=len(ov),
                        quarantined=(os.sep + "invalid" + os.sep) in f)
    return idx


def main(size=100):
    K = M._K()
    per_family = size == 100
    idx = run_index(size)
    dumps = sorted(glob.glob(os.path.join(ROOT, "runs", "solutions", "*_n%d*.json" % size)))
    print("COVERAGE SCORE, |C| = %d -- %d dumps, %d run logs" % (size, len(dumps), len(idx)))
    print()
    print("%-7s %10s %5s %9s %-18s %s"
          % ("cell", "objVal", "cars", "vs K", "improvement", "provenance"))
    good, orphan, constr = [], [], []
    for p in dumps:
        m = re.search(r"_((?:C|R|RC)\d{3})_n%d" % size, os.path.basename(p))
        if not m:
            continue
        c = m.group(1)
        try:
            j = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        o = j.get("objVal")
        if not o:
            continue
        rid = j.get("_run_id") or ""
        r = idx.get(rid)
        if r is not None and r.get("quarantined"):
            orphan.append((c, o, rid))
            print("%-7s %10.1f %5s %9s %-18s QUARANTINED -- verifier rejected a solution,"
                  " run_valid=NO" % (c, o, j.get("nCars"), "-", "-"))
            continue
        if r is None:
            orphan.append((c, o, rid))
            print("%-7s %10.1f %5s %9s %-18s ORPHAN -- no run log (%s)"
                  % (c, o, j.get("nCars"), "-", "-", rid[-30:] or "no run_id"))
            continue
        if per_family:
            t = K["table6"][FAM(c)]
            kref = min(t["joint"]["zIP"], t["lbbd"]["zIP"])
        else:
            row = K["table3"]["per_instance"].get(str(size), {}).get(c)
            kref = min(row["joint_bk"], row.get("lbbd_bk", row["joint_bk"])) if row else None
        vsk = ("%+.1f%%" % (100.0 * (o - kref) / kref)) if kref else "-"
        if r["first"] and abs(o - r["first"]) < 1e-6:
            constr.append(c)
            imp = "CONSTRUCTION ONLY"
        else:
            imp = "%+.1f%%" % (100.0 * (o - r["first"]) / r["first"]) if r["first"] else "?"
            good.append((c, o, j.get("nCars"), vsk, imp))
        print("%-7s %10.1f %5s %9s %-18s %s/%s"
              % (c, o, j.get("nCars"), vsk, imp, r["status"], r["verified"]))

    fails = {rid: r for rid, r in idx.items() if r["best"] is None}
    print("-" * 78)
    print("  REAL results (verified AND improved) : %d   %s"
          % (len(good), " ".join(g[0] for g in good)))
    print("  construction only                    : %d   %s" % (len(constr), " ".join(constr)))
    print("  QUARANTINED / orphaned (NOT results) : %d   %s"
          % (len(orphan), " ".join(o[0] for o in orphan)))
    print("  runs with no incumbent at all        : %d   %s"
          % (len(fails), " ".join(sorted({r["cell"] for r in fails.values()}))))
    if per_family:
        t6 = K["table6"]
        print("  K fleet_sl: C %.2f  R %.2f  RC %.2f"
              % (t6["C"]["lbbd"]["fleet_sl"], t6["R"]["lbbd"]["fleet_sl"],
                 t6["RC"]["lbbd"]["fleet_sl"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 100))
