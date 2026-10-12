"""MASTER SEQUENCER -- runs the corrected trajectory in one process, in priority order.

WHY ONE PROCESS. The previous design chained independent waiters on "is anything busy?".
That produced a real failure: the kick-pipeline gate fired inside the control runner's 120s
sleep, patched fixopt, and the control then ran at the wrong code_hash. Sequencing inside a
single process removes the race entirely -- no stage can start while another is running,
because there is nothing to poll.

ORDER, by existential-risk / time-to-signal (NOT by recency of discovery):
  1 LB-COVERAGE   could kill the ONLY remaining leg. The banked claim is "11/11 on LOOSE
                  cells" (tested band = K gap 36-65%); these 9 cells are 6-31% and have never
                  been run. Decisive signal arrives in the first cell or two.
  2 SCALE-A       feasibility at n30/40/50/100. Establishes the size ceiling for ~1h.
  3 SCALE-BC      full primal + LB at the sizes that survive A.
  4 ABLATION      kick-vs-no-kick. Resumed, NOT restarted: 2 balanced pairs are already
                  banked. This is a methods contribution, not an existential test -- the LB
                  leg computes its gaps against K's incumbent (K_inc) and reads no primal
                  output at all, so the frozen primal config feeds nothing that carries the paper.
  5 RT-FAIR       contingent: only meaningful if stage 1 leaves a leg to time.

ADVERSE AUDIT OF THIS DESIGN (findings folded in):
 A1 I PROPOSED THE WRONG CELL ORDER AND THE AUDIT CAUGHT IT. I "corrected" the queue to
    tightest-first (R209 at 6%). Wrong: the banked claim covers LOOSE cells, so a 6%-gap cell
    is OUT OF SCOPE and failing it refutes nothing. The decisive cell is R206 (31%) -- the one
    ADJACENT to the tested band. Order is therefore descending gap from the boundary, which is
    what was originally queued. My correction is retracted.
 A2 This is a DOSE-RESPONSE, not pass/fail: it maps bound-advantage against K's gap and finds
    where it crosses zero. "Dominance for K gap above ~X%" is a scoped, defensible claim and a
    better result than an unexplained 11/11.
 A3 CENSORING. A cell that fails to prove within tl drops out, and difficulty correlates with
    tightness -- so dropouts bias the surviving set toward cells we can solve. Censored cells
    must be reported, not silently omitted.
 A4 SCALE-A CONFLATES two failures: "intractable" and "300s was too short". At n100 the model
    may not even finish construction. The report must separate them.
 A5 Bound values from PROVEN solves are deterministic, so run order cannot confound them --
    unlike the primal, where order confounding is exactly what invalidated the n30 campaign.
"""
import argparse, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "master_sequence.log")


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def stage(name, cmd, eta_h):
    say(f"=== STAGE {name} START (ETA ~{eta_h}) ===")
    t0 = time.time()
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    say(f"=== STAGE {name} DONE in {(time.time()-t0)/3600:.2f}h (rc={rc}) ===")
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="1,1b,1c,2,3,4,5")
    a = ap.parse_args()
    want = {s.strip() for s in a.stages.split(",")}
    say("MASTER SEQUENCE START -- single process, no inter-stage polling")

    if "1" in want:
        # boundary-first order (descending K gap from the tested band's edge) -- see A1
        stage("1 LB-COVERAGE", [PY, os.path.join(ROOT, "analysis", "lb_coverage_run.py"),
                                "--workers", "4"], "2-5h (worst 10h)")
    if "1b" in want:
        # ~30min, ZERO solver change, and it gates the whole diversification design.
        # Must precede the ablation: the ablation tests kick-vs-no-kick under the CURRENT
        # non-diversified operator, so if diversification changes the operator, the ablation
        # is answering a question about a configuration we are replacing.
        stage("1b DIVERS-SMOKE", [PY, os.path.join(ROOT, "analysis", "divers_smoke.py")],
              "~30min")
    if "1c" in want:
        # The LB leg IS the paper, and ALL of it is n20: 29 artifacts at n20 vs 3 at n30, and
        # those 3 have ZERO proven records (different bounder, all capped at 900s). n30 is the
        # CORE GRID size, is not infra-gated, and K reports it PER-INSTANCE -- unlike n50
        # (pooled) and n100 (per-family, different proximity). So extending the paper's own
        # asset to n30 outranks a feasibility probe of the deleted primal leg.
        stage("1c LB-n30", [PY, os.path.join(ROOT, "analysis", "lb_n30.py"), "--n", "6"],
              "4-9h")
    if "2" in want:
        stage("2 SCALE-A", [PY, os.path.join(ROOT, "analysis", "scale_screen.py"),
                            "--stage", "A"], "1-1.5h")
        stage("2r RT-to-K", [PY, os.path.join(ROOT, "analysis", "rt_to_k_monitor.py")], "instant")
    if "3" in want:
        stage("3 SCALE-BC", [PY, os.path.join(ROOT, "analysis", "scale_screen.py"),
                             "--stage", "BC"], "8-20h")
    if "4" in want:
        # resume: blocks 1-2 are banked and balanced; continue the alternation from index 2
        stage("4 ABLATION-RESUME", [PY, os.path.join(ROOT, "analysis", "kick_ablation.py"),
                                    "--seeds", "20,21,23,24", "--cells", "R203,R211",
                                    "--resume-from", "2"], "~10.7h")
    if "5" in want:
        stage("5 RT-FAIR", [PY, os.path.join(ROOT, "analysis", "rt_fair_pipeline.py")], "~8.9h")
        stage("5r RT-to-K", [PY, os.path.join(ROOT, "analysis", "rt_to_k_monitor.py")], "instant")
    say("MASTER SEQUENCE COMPLETE")


if __name__ == "__main__":
    main()
