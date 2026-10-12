"""Dual->primal inheritance A/B (orchestrator; NOT a value-determining source). Pre-registered in
validation/PREREG_inheritance_ab.md -- DO NOT change the outcome/threshold here.

Per (cell, size), three SINGLE-TENANT runs, in order:
  GEN       tep_solve --no-refine --no-alns --no-select --dump-incumbent  -> the dual master_ip
            incumbent handoff (CG-only). --no-bank (no runtime-bearing artifact); the handoff is a
            solution-only, provenance-stamped, runtime-claimless file.
  CONTROL   tep_solve --ws-only                                            -> greedy-WS final OV.
  TREATMENT tep_solve --ws-only --inherit <handoff>                        -> best-of{greedy, dual}.

All three share one --envelope so CONTROL and TREATMENT are a FAIR paired contrast (same budget,
differ only by the inherited WS). Finals are deterministic given the seed+committed code, so the
OVs reproduce; only the (wall-bound) runtime does not, and it is never quoted here.

QUARANTINE STOPS THE BATCH (tep_solve exit 2/3), per CLAUDE.md s1. The ab summary is written to
logs/ (NOT runs/**: it is a decision summary over --no-bank measurement runs, not a banked result).
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELLS = ["C204", "R207", "R211", "RC204"]
SIZES = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else [30, 50]
SEED = 0
ENV = 3600.0                      # paired budget; stage caps = SHARES*ENV (bounded, >> n30/n50 need)
GUILL = int(ENV * 1.2) + 240      # per-run external guillotine
HANDOFF = os.path.join(ROOT, "handoff")
PY = sys.executable
OV_RE = re.compile(r"=> OV ([\d.]+)")


def precompile():
    print("[compileall out-of-RT] %s" % time.strftime("%H:%M:%S"), flush=True)
    subprocess.run([PY, "-m", "compileall", "-q",
                    os.path.join(ROOT, "analysis"), os.path.join(ROOT, "solver"),
                    os.path.join(ROOT, "crossfeed"), os.path.join(ROOT, "build_instance.py")],
                   cwd=ROOT, check=False)
    print("[compileall done] %s" % time.strftime("%H:%M:%S"), flush=True)


def run(args, tag):
    """Run one tep_solve invocation, echo-free capture; return (exit, ov_or_None)."""
    print("  -> %-9s %s" % (tag, time.strftime("%H:%M:%S")), flush=True)
    t0 = time.time()
    try:
        r = subprocess.run([PY, os.path.join("analysis", "tep_solve.py")] + args,
                           cwd=ROOT, timeout=GUILL, capture_output=True, text=True)
        rc, out = r.returncode, (r.stdout or "")
    except subprocess.TimeoutExpired as e:
        rc, out = 124, (e.stdout or "" if isinstance(e.stdout, str) else "")
    ov = None
    for m in OV_RE.finditer(out):
        ov = float(m.group(1))                     # last "=> OV" = this run's final
    print("     %-9s exit=%d ov=%s (%.0fs)" % (tag, rc, ("%.3f" % ov) if ov else "-",
                                               time.time() - t0), flush=True)
    return rc, ov


def main():
    precompile()
    if not os.path.isdir(HANDOFF):
        os.makedirs(HANDOFF)
    rows = []
    for n in SIZES:
        for cell in CELLS:
            print("=== %s n%d (seed %d) ===" % (cell, n, SEED), flush=True)
            hp = os.path.join(HANDOFF, "dualinc_%s_n%d.json" % (cell, n))
            base = [cell, "--size", str(n), "--seed", str(SEED), "--envelope", str(int(ENV)),
                    "--no-bank"]
            # GEN (CG-only dual incumbent -> handoff)
            rc, gen_ov = run(base + ["--no-refine", "--no-alns", "--no-select",
                                     "--dump-incumbent", hp, "--tag", "abgen"], "gen")
            if rc in (2, 3):
                print("!!! QUARANTINE (rc=%d) at %s n%d gen -- STOPPING BATCH (CLAUDE.md s1)."
                      % (rc, cell, n), flush=True)
                return rc
            got_handoff = os.path.exists(hp)
            # CONTROL (greedy WS)
            rc_c, ctl = run(base + ["--ws-only", "--tag", "abctl"], "control")
            if rc_c in (2, 3):
                print("!!! QUARANTINE (rc=%d) at %s n%d control -- STOPPING." % (rc_c, cell, n),
                      flush=True)
                return rc_c
            # TREATMENT (greedy WS + inherited dual incumbent)
            trt = None
            if got_handoff:
                rc_t, trt = run(base + ["--ws-only", "--inherit", hp, "--tag", "abtrt"], "treatment")
                if rc_t in (2, 3):
                    print("!!! QUARANTINE (rc=%d) at %s n%d treatment -- STOPPING." % (rc_t, cell, n),
                          flush=True)
                    return rc_t
            else:
                print("     NO HANDOFF (gen produced no incumbent) -- treatment skipped", flush=True)
            d = (100.0 * (trt - ctl) / ctl) if (trt and ctl) else None
            rows.append(dict(cell=cell, size=n, seed=SEED, dual_inc_ov=gen_ov,
                             control_ov=ctl, treatment_ov=trt, delta_ov_pct=d))
            print("     RESULT dual_inc=%s control=%s treatment=%s dOV%%=%s"
                  % (gen_ov, ctl, trt, ("%+.2f" % d) if d is not None else "-"), flush=True)
    # summary -> logs/ (decision summary, not a runs/** result)
    sp = os.path.join(ROOT, "logs", "inherit_ab_summary.json")
    json.dump(dict(prereg="validation/PREREG_inheritance_ab.md", envelope_s=ENV, seed=SEED,
                   rows=rows), open(sp, "w"), indent=1)
    print("\n=== A/B SUMMARY (dOV%% <0 = treatment cheaper; denom=control) ===", flush=True)
    print("  %-6s %4s | %10s %10s %10s | %8s" %
          ("cell", "n", "dual_inc", "control", "treatment", "dOV%"), flush=True)
    for r in rows:
        print("  %-6s %4d | %10s %10s %10s | %8s" %
              (r["cell"], r["size"],
               ("%.2f" % r["dual_inc_ov"]) if r["dual_inc_ov"] else "-",
               ("%.2f" % r["control_ov"]) if r["control_ov"] else "-",
               ("%.2f" % r["treatment_ov"]) if r["treatment_ov"] else "-",
               ("%+.2f" % r["delta_ov_pct"]) if r["delta_ov_pct"] is not None else "-"),
              flush=True)
    print("\nwrote %s" % os.path.relpath(sp, ROOT), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
