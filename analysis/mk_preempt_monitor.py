"""Preempt monitor for the multikick head-to-head (user rule 2026-09-08):
stop the current-design multikick batch once we have 3 CONFIRMING losses across >=2 cells,
where 'confirming' = (a) paired same-seed loss (k3 OV > baseline OV) AND (b) the loss carries the
diagnosed BURST-TIME-SINK signature (escalated kick TL >=100 OR a >150s gap between kick events).
On trigger: kill the calib_run+fixopt processes (preempt) and report the confirming set, so the
cap-TL smoke can be launched (gated) next. Read-only except the final kill."""
import time, os, csv, glob, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_results():
    res = {}
    for h in ("A", "B"):
        p = os.path.join(ROOT, "validation", f"mk_h2h_{h}.csv")
        if os.path.exists(p):
            for r in csv.DictReader(open(p)):
                if r.get("best_obj") not in ("", "None", None):
                    res[(r["cell"], r["variant"], r["seed"])] = float(r["best_obj"])
    return res


def burst_signature(cell, seed):
    fs = glob.glob(os.path.join(ROOT, "runs", f"fixopt_{cell}_n30_s{seed}_cal_k3_*.jsonl"))
    if not fs:
        return False, "no-trace"
    f = max(fs, key=os.path.getmtime)
    walls, escalated = [], False
    for l in open(f, encoding="utf-8"):
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except Exception:
            continue
        if "kick" in str(r.get("trigger")):
            e = r.get("extra") or {}
            w = e.get("wall_s") or r.get("wall_s")
            if isinstance(w, (int, float)):
                walls.append(w)
            if (e.get("next_kick_tl") or 0) >= 100:
                escalated = True
    maxgap = max((walls[i] - walls[i - 1] for i in range(1, len(walls))), default=0.0)
    return (escalated or maxgap > 150), f"escalated={escalated} maxgap={maxgap:.0f}s"


def kill_batch():
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and "
                        "($_.CommandLine -match 'calib_run' -or $_.CommandLine -match 'engines.fixopt') } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                       capture_output=True, timeout=30)
    except Exception as e:
        print("kill error:", e)


def main():
    for _ in range(90):                       # ~3h at 120s cadence
        res = read_results()
        confirming = []
        for (cell, var, seed), ov in res.items():
            if var != "k3":
                continue
            b = res.get((cell, "baseline", seed))
            if b is None or ov <= b + 1e-6:   # need a paired same-seed LOSS
                continue
            sig, desc = burst_signature(cell, seed)
            if sig:
                confirming.append((cell, seed, ov, b, desc))
        cells = {c for c, _, _, _, _ in confirming}
        if len(confirming) >= 3 and len(cells) >= 2:
            print("=== PREEMPT CONDITION MET: %d confirming k3 losses across %d cells ==="
                  % (len(confirming), len(cells)))
            for c, s, k, b, d in confirming:
                print(f"  {c} s{s}: k3={k:.1f} > baseline={b:.1f} (LOSS)  burst-sig[{d}]")
            kill_batch()
            print("BATCH PREEMPTED (calib_run+fixopt killed). READY FOR CAP-TL SMOKE.")
            return
        print(f"[poll] confirming losses so far: {len(confirming)} across {len(cells)} cells", flush=True)
        time.sleep(120)
    print("poll window ended WITHOUT meeting preempt condition (batch left running)")


if __name__ == "__main__":
    main()
