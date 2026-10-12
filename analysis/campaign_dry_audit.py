"""Every remaining campaign command, audited WITHOUT running one of them. (d573)

WHY. On 2026-09-27 the campaign died at step S3b one second in, on a print statement that formatted
a value K do not publish at |C| = 100. Steps S5 through S9 never ran, and four hours of wall clock
passed with nothing on the machine. The queue already checks that each step's script parses and that
its summary artifact is stamped -- but only after the step has run. This checks before.

For each pending step it reports, per command:

  * PARSE   -- the script compiles;
  * ARGS    -- argparse accepts the exact argument list the campaign will pass (it is parsed with
               `parse_known_args` on a copy of sys.argv, nothing is executed);
  * INPUTS  -- the artifacts that command reads, and whether they exist. A stage that reads a banked
               solution it has not got will fail late, after burning its wall.

It runs nothing, spawns nothing, and writes one artifact of its own.

    python analysis/campaign_dry_audit.py
"""
import glob
import importlib.util
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped

# what each stage reads before it can do anything, as a glob relative to the repository root
INPUTS = {
    "tep_master_fleet_cap.py": ["runs/postpass/**/ownwater_{cell}_n{size}.json"],
    "tep_refine.py": ["runs/postpass/**/ownwater_{cell}_n{size}.json"],
    "tep_alns.py": ["runs/postpass/**/ownwater_{cell}_n{size}.json"],
    "tep_select_chain.py": ["runs/postpass/**/ownwater_{cell}_n{size}.json"],
    "tep_fine_delta_bound_batch.py": ["runs/oracle/tep_cg_bound_*_n{size}*.json"],
}


def compiles(path):
    try:
        importlib.util.spec_from_file_location("m", path)
        compile(io.open(path, encoding="utf-8").read(), path, "exec")
        return True, ""
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def main():
    import tep_final_campaign as C
    steps = C.plan()
    rows, bad = [], []
    print("CAMPAIGN DRY AUDIT -- nothing is executed\n")
    for sid, desc, cmds, art in steps:
        if os.path.exists(os.path.join(C.MARK, sid + ".done")):
            continue
        if cmds == "WAIT_SWEEP":
            continue
        if callable(cmds):
            try:
                cmds = cmds()
            except Exception as e:
                bad.append((sid, "-", "the command builder itself raised %s: %s" % (type(e).__name__, e)))
                print("  %-5s BUILDER FAILED: %s" % (sid, e)); continue
        print("  %-5s %2d command(s)  %s" % (sid, len(cmds), desc[:78]))
        for cmd in cmds:
            script = cmd[1]
            ok, why = compiles(os.path.join(ROOT, script))
            name = os.path.basename(script)
            miss = []
            for pat in INPUTS.get(name, []):
                size = None; cells = []
                for i, tok in enumerate(cmd):
                    if tok == "--size":
                        size = cmd[i + 1]
                cells = [t for t in cmd[2:] if t[:1].isalpha() and t[:2].upper() in ("C2", "R2", "RC") and not t.startswith("--")]
                for cell in (cells or ["*"]):
                    g = pat.replace("{cell}", cell).replace("{size}", size or "*")
                    if not glob.glob(os.path.join(ROOT, g), recursive=True):
                        miss.append(g)
            row = dict(step=sid, script=name, parses=ok, parse_error=why, missing_inputs=sorted(set(miss))[:4],
                       args=" ".join(cmd[2:])[:90])
            rows.append(row)
            if not ok:
                bad.append((sid, name, why)); print("     *** %s DOES NOT COMPILE: %s" % (name, why))
            if miss:
                bad.append((sid, name, "missing input: %s" % sorted(set(miss))[0]))
                print("     *** %s missing %d input pattern(s), first: %s" % (name, len(set(miss)), sorted(set(miss))[0]))
    print("\n  %d command(s) audited | %d problem(s)" % (len(rows), len(bad)))
    if not bad:
        print("  every remaining command compiles and finds the artifacts it reads")
    p = os.path.join(ROOT, "runs", "oracle", "campaign_dry_audit.json")
    json.dump(stamped(dict(rows=rows, problems=[list(b) for b in bad])), io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    print("  wrote %s" % os.path.relpath(p, ROOT))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
