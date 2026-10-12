"""Replace a banked DSSR certificate with one from the FIXED certifier, and record the retraction.

    python analysis/dssr_recertify.py --size 50 --dry-run     # what would change, and by how much
    python analysis/dssr_recertify.py --size 50               # do it

WHY THIS EXISTS AND WHY IT IS NARROW. dssr_certify --bank refuses to overwrite an artifact that
carries a certificate, on purpose: a certified result is evidence and two releases must not share
a filename. That rule is right and is not being relaxed. But d635 established that the
certificates banked on 2026-09-30 before commit 60753ec were produced by a certifier that could
report a value ABOVE LP(R_e) -- measured overstatements of +0.98 and +3.51 on deliberately
under-converged pools, with a named witness route. Those artifacts must not stand, and deleting
them would destroy the runtime and provenance of work that was really done. So they are
SUPERSEDED, with the old value, the old code hash and the reason recorded on the new artifact.

THE RULE THIS APPLIES, from CLAUDE.md: delete on a consequence, not on a defect, and repair a
result that is wrongly LABELLED by regenerating the label rather than destroying the value. Here
the value itself was wrong, so the value is regenerated -- by the fixed certifier, from its own
smoke run -- and the old one is kept on the record inside `retraction`.

WHAT IT REFUSES TO DO. It will not supersede unless the replacement was produced by a source
hash DIFFERENT from the artifact's own, so it cannot be used to overwrite a result with a re-run
of the same code. It will not raise a value: the defect overstates, so a replacement ABOVE the
banked value is not the repair this script is for and is refused for a human to look at. And it
will not touch an artifact whose banked value already equals the re-verified one.
"""
import argparse
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

NINE = ["R202", "R203", "R204", "R206", "R207", "R208", "R209", "R210", "R211"]
TOL = 1e-9


def newest_smoke(cell, size):
    fs = sorted(glob.glob(os.path.join(ROOT, "logs", "smoke", "dssr_%s_n%d_*.json" % (cell, size))),
                key=os.path.getmtime)
    return (fs[-1], json.load(io.open(fs[-1], encoding="utf-8"))) if fs else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=50)
    ap.add_argument("--cells", nargs="+", default=NINE)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    from stamp import stamped

    print("%-6s %16s %16s %11s %-10s %s"
          % ("cell", "banked", "re-verified", "change", "smoke src", "action"))
    acted = skipped = refused = 0
    for cell in a.cells:
        p = os.path.join(ROOT, "runs", "oracle",
                         "tep_cg_bound_%s%s.json" % (cell, "" if a.size == 100 else "_n%d" % a.size))
        sp, sm = newest_smoke(cell, a.size)
        if not os.path.exists(p) or sm is None:
            print("%-6s %16s %16s %11s %-10s %s" % (cell, "-", "-", "-", "-", "no artifact or no smoke"))
            skipped += 1
            continue
        old = json.load(io.open(p, encoding="utf-8"))
        ov, nv = float(old["lp_street"]), float(sm["lp_street"])
        oh = (old.get("_provenance") or {}).get("source_hash")
        nh = (sm.get("_provenance") or {}).get("source_hash")
        short = os.path.basename(sp)[-13:-5]
        if abs(nv - ov) <= TOL:
            print("%-6s %16.9f %16.9f %11.9f %-10s unchanged: the banked value stands"
                  % (cell, ov, nv, nv - ov, short))
            skipped += 1
            continue
        if oh == nh:
            print("%-6s %16.9f %16.9f %11.9f %-10s REFUSED: same source hash, not a fix"
                  % (cell, ov, nv, nv - ov, short))
            refused += 1
            continue
        if nv > ov + TOL:
            print("%-6s %16.9f %16.9f %+11.9f %-10s REFUSED: replacement is HIGHER; the defect "
                  "overstates, so this is not that repair" % (cell, ov, nv, nv - ov, short))
            refused += 1
            continue
        payload = {k: v for k, v in sm.items() if not k.startswith("_")}
        # the tep_cg_bound shape the readers need, recomputed for the new value
        ab = {(q["cell"], q["size"]): q for q in json.load(io.open(
            os.path.join(ROOT, "runs", "ab_grid_provenanced.json"), encoding="utf-8"))["records"]}[(cell, a.size)]
        payload["ab_street"] = float(ab["fleet_term"]) + float(ab["travel_term"])
        payload["ab4"] = float(ab["ab4"])
        payload["water_ab"] = float(ab["water"])
        payload["composed"] = nv + float(ab["water"])
        payload["lp_composed"] = payload["composed"]
        payload["lb_reported"] = max(payload["composed"], payload["ab4"])
        payload["lb_carrier"] = "composed" if payload["composed"] >= payload["ab4"] else "ab4"
        payload["primal_rounding"] = False
        payload["valid_bound"] = bool(payload.get("certificate"))
        payload.pop("valid_bound_why", None)
        payload.pop("diagnostic_only", None)
        payload["status"] = "proven" if payload.get("certificate") else payload.get("status")
        payload["retraction"] = dict(
            retracted_value=ov, retracted_composed=old.get("composed"),
            retracted_source_hash=oh, retracted_finished=old.get("_finished"),
            change=nv - ov, decision="d635",
            why="the banked value was produced by a certifier that priced without start-state "
                "labels, so dominance ranked labels by an understated reduced cost and the "
                "search could miss the elementary route that prices out; witness route "
                "[8, 18, 6, 40, 21, 41] at exact rc -8.7186 on R206 n50",
            replaced_by_source_hash=nh, replaced_from=os.path.basename(sp))
        payload["_command"] = " ".join(sys.argv)
        import time as _t
        payload["_finished"] = _t.strftime("%Y-%m-%d %H:%M")
        print("%-6s %16.9f %16.9f %11.9f %-10s %s"
              % (cell, ov, nv, nv - ov, short, "would supersede" if a.dry_run else "SUPERSEDING"))
        if not a.dry_run:
            doc = stamped(payload, "analysis/dssr_recertify.py", "analysis/dssr_certify.py",
                          "analysis/tep_cg_bound.py", "analysis/tep_pricer.py",
                          det=payload.get("det_ticks"), wall=payload.get("secs"),
                          rt_class="diagnostic", path=p, supersede=True)
            with io.open(p, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=1, default=str)
        acted += 1
    print("\n%s: %d superseded, %d unchanged, %d refused"
          % ("DRY RUN" if a.dry_run else "DONE", acted, skipped, refused))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
