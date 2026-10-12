"""BASELINE REPRODUCTION CONTROL -- queued to start only after the cap-TL extension frees the cores.

Question it answers: R203's baseline came out +68.9 WORSE on the extension seeds (3,4: mean
1023.0) than on the banked seeds (0-2: mean 954.2), while R211 shifted +0.5. Two explanations:
  (a) seeds 3,4 are genuinely harder for R203  -> captl's robustness advantage is REAL
  (b) the current code regressed R203's baseline -> the extension comparison is CONTAMINATED
Re-running the baseline at seeds 0-2 on the CURRENT code discriminates them:
  reproduces ~954.2 -> (a);  comes out ~1023 -> (b).
R211 is the negative control: it should reproduce 904.18/936.604/919.012.

Waits for the extension drivers to exit, then runs both cells in parallel (4 threads each)."""
import os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ext_running():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                          "Where-Object { $_.CommandLine -like '*captl_ext_driver*' }).Count"],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out or 0) > 0
    except ValueError:
        return True



# Module-level code here is REACHABLE BY IMPORT. On 2026-09-20 an import-check gate
# exec'd this file; its body ran, kill_tree() force-killed every fixopt.py on the
# machine, and two runs of a live campaign were destroyed. Everything below is behind
# main() so that importing this module does nothing at all.


def main():
    print("[ctrl] waiting for cap-TL extension to finish ...", flush=True)
    while ext_running():
        time.sleep(120)
    print("[ctrl] extension done -- launching baseline reproduction control", flush=True)

    procs = []
    for cell in ("R203", "R211"):
        cmd = [sys.executable, os.path.join(ROOT, "analysis", "calib_run.py"),
               "--size", "30", "--cells", cell, "--variants", "baseline", "--seeds", "0,1,2",
               "--budget", "2400", "--threads", "4", "--out", f"validation/captl_ctrl_{cell}.csv"]
        procs.append(subprocess.Popen(cmd, cwd=ROOT))
        print(f"[ctrl] launched {cell} baseline seeds 0-2", flush=True)
    for p in procs:
        p.wait()

    BANKED = {"R203": [962.837, 951.968, 947.722], "R211": [904.18, 936.604, 919.012]}
    print("\n[ctrl] === BASELINE REPRODUCTION RESULT ===", flush=True)
    import csv
    for cell in ("R203", "R211"):
        p = os.path.join(ROOT, "validation", f"captl_ctrl_{cell}.csv")
        if not os.path.exists(p):
            continue
        got = [float(r["best_obj"]) for r in csv.DictReader(open(p))
               if r.get("best_obj") not in ("", "None", None)]
        if not got:
            continue
        b = BANKED[cell][:len(got)]
        mg, mb = sum(got) / len(got), sum(b) / len(b)
        print(f"  {cell}: current-code {[f'{x:.1f}' for x in got]} mean {mg:.1f} "
              f"| banked {[f'{x:.1f}' for x in b]} mean {mb:.1f} | shift {mg-mb:+.1f}", flush=True)
        if cell == "R203":
            print("  -> VERDICT: " + ("(b) CODE REGRESSION -- extension comparison CONTAMINATED"
                                      if mg - mb > 30 else
                                      "(a) seeds 3,4 genuinely harder -- captl robustness REAL"), flush=True)
    print("[ctrl] done", flush=True)


if __name__ == "__main__":
    main()
