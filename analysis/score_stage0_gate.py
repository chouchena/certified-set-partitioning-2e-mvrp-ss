"""Stage 0 gate, scored at the TRAJECTORY's budget, not the driver's.

THE DISCREPANCY THIS RESOLVES. `analysis/overnight_2026_09_17.py` was written at 16:42 with
DET = 1,200,000 / WALL = 7,200. `validation/TRAJECTORY_primal_v2_2026-09-17.md` was written at
17:38 -- AFTER it -- and its Stage 0 prescribes `--det-tl 600,000`, wall backstop 5,400 s. The
trajectory is the authority (d193 records what happens when it is not read), but the driver was
already running and a running job is never stopped.

1,200,000 ticks is a SUPERSET of 600,000, so nothing is lost: the gate is evaluated at the
trajectory's checkpoint by TRUNCATING the trajectory at 600k ticks, and whatever the extra budget
bought is reported separately as a bonus observation that the gate does not depend on.

THE GATE, verbatim from Stage 0: "if neither cell produces a verified improvement over its
construction, stages 2-3 at n100 are ABANDONED and the n100 primal is reported as
construction-only with its gap stated. That is a real possible outcome and it is written here so
it cannot be softened later."

SECOND READOUT, registered tonight BEFORE the run lands (2026-09-17, d197): our fixopt cuts the
constructor's street fleet 4.04 -> 1.65 at |C| = 20, a 59% reduction. The n100 constructor sits at
16.5-18.5 cars against K's 7.5-8.75. If that reduction transfers, these two cells should land near
7-8 cars. Reported as a PREDICTION MADE IN ADVANCE, and it does not gate anything.
"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_DET = 600_000


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


def score(path):
    rows = load(path)
    if not rows:
        return None
    cfg = {}
    prov = {}
    for r in rows:
        e = r.get("extra") or {}
        if isinstance(e, dict):
            if isinstance(e.get("config"), dict) and not cfg:
                cfg = e["config"]
            if isinstance(e.get("provenance"), dict) and not prov:
                prov = e["provenance"]
    # d201: at n100 a run can produce improvements the INDEPENDENT VERIFIER rejects
    # ("W-1XFER: no feasible timetable exists"). Such a run banks no valid incumbent and
    # must NOT count toward the gate. Counting it was a defect in this scorer, caught
    # 2026-09-18 when a manual diagnostic inflated the gate to "2 of 3".
    rejected = any((r.get("extra") or {}).get("reject") for r in rows
                   if isinstance(r.get("extra"), dict))
    verified_ok = any((r.get("extra") or {}).get("verified") is True for r in rows
                      if isinstance(r.get("extra"), dict))
    pts = [(r.get("wall_s"), r.get("best_incumbent")) for r in rows
           if isinstance(r.get("best_incumbent"), (int, float)) and r["best_incumbent"] > 0]
    if rejected and not verified_ok:
        return dict(path=os.path.basename(path), status="ALL IMPROVEMENTS REJECTED (d201)",
                    cfg=cfg)
    if not pts:
        return dict(path=os.path.basename(path), status="NO INCUMBENT", cfg=cfg)
    # the construction is the first incumbent the run ever holds
    construction = pts[0][1]
    final = min(o for _, o in pts)
    # det ticks are stamped once, mid-file; without a per-record tick axis the 600k
    # checkpoint is approximated by the WALL fraction it corresponds to. Stated, not hidden.
    det_used = det_budget = None
    for r in rows:
        e = r.get("extra") or {}
        if isinstance(e, dict):
            if isinstance(e.get("det_used"), (int, float)):
                det_used = e["det_used"]
            if isinstance(e.get("det_budget"), (int, float)):
                det_budget = e["det_budget"]
    end = max(w for w, _ in pts if isinstance(w, (int, float)))
    frac = (GATE_DET / det_used) if det_used else None
    at_gate = None
    if frac is not None and frac < 1.0:
        cut = end * frac
        v = [o for w, o in pts if isinstance(w, (int, float)) and w <= cut]
        at_gate = min(v) if v else construction
    return dict(path=os.path.basename(path), construction=construction, final=final,
                at_gate=at_gate, end_wall=end, det_used=det_used, det_budget=det_budget,
                cfg=cfg, code_hash=prov.get("code_hash"))


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "runs", "*n100*.jsonl")))
    files = [f for f in files if "smoke" in os.path.basename(f).lower()
             or "fixopt" in os.path.basename(f).lower()]
    if not files:
        print("STAGE 0 GATE: no n100 run files yet.")
        return 2
    print(__doc__.split("THE DISCREPANCY")[0].strip())
    print()
    print("%-34s %11s %11s %11s %9s %s"
          % ("run", "construction", "at 600k", "final", "wall s", "verdict"))
    improved_gate = improved_full = 0
    for f in files:
        s = score(f)
        if not s or s.get("status"):
            print("%-34s  %s" % (os.path.basename(f)[:34], (s or {}).get("status", "unreadable")))
            continue
        g = s["at_gate"] if s["at_gate"] is not None else s["final"]
        vg = g < s["construction"] - 1e-9
        vf = s["final"] < s["construction"] - 1e-9
        improved_gate += vg
        improved_full += vf
        print("%-34s %11.2f %11.2f %11.2f %9.0f %s"
              % (s["path"][:34], s["construction"], g, s["final"], s["end_wall"],
                 "IMPROVED@gate" if vg else ("improved only past gate" if vf else "NO IMPROVEMENT")))
        if s["det_used"] and s["det_budget"]:
            print("%36s det %.0f of %.0f (%s)" % ("", s["det_used"], s["det_budget"],
                  "reached" if s["det_used"] >= 0.99 * s["det_budget"] else "WALL-CUT -- d191"))
    print("-" * 92)
    print("  GATE (trajectory v2 Stage 0, det 600k): improved on %d of %d cells"
          % (improved_gate, len(files)))
    print("  at the driver's full 1.2M budget          : improved on %d of %d"
          % (improved_full, len(files)))
    print()
    if improved_gate:
        print("  VERDICT: GATE PASSES. Stage 2 n100 coverage is authorised by the trajectory.")
    elif improved_full:
        print("  VERDICT: GATE FAILS AT 600k, passes only on the extra budget. The trajectory's")
        print("  gate is written at 600k and is NOT softened: this is a FAIL, with the bonus")
        print("  observation recorded that 1.2M ticks would have passed it.")
    else:
        print("  VERDICT: GATE FAILS. Per Stage 0, n100 in stages 2-3 is ABANDONED and the n100")
        print("  primal is reported as construction-only with its gap stated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
