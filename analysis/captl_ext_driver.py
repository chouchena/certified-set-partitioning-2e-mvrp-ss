"""cap-TL extension driver. Runs the paired (baseline, captl) comparison SEED-MAJOR so that a
preempted batch still leaves COMPLETE PAIRS on disk (the mk_h2h batch was killed mid-flight; a
variant-major order would have left baselines with no partner). Both variants run at the SAME
code_hash, which the banked seeds 0-2 do NOT share -- that confound is the reason for this run.

  python analysis/captl_ext_driver.py --cell R203 --half A
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--half", required=True)
    ap.add_argument("--seeds", default="3,4,5,6,7")
    a = ap.parse_args()
    for s in [x.strip() for x in a.seeds.split(",") if x.strip()]:
        cmd = [sys.executable, os.path.join(ROOT, "analysis", "calib_run.py"),
               "--size", "30", "--cells", a.cell, "--variants", "baseline,captl",
               "--seeds", s, "--budget", "2400", "--threads", "4",
               "--out", f"validation/captl_ext_{a.half}.csv"]
        print(f"[ext] {a.cell} seed {s} (baseline+captl) ...", flush=True)
        subprocess.run(cmd, cwd=ROOT)
        print(f"[ext] {a.cell} seed {s} pair DONE", flush=True)
    print("[ext] driver done", flush=True)


if __name__ == "__main__":
    main()
