"""Chain the LB campaign stages so the box is never idle and never double-booked.

WHY A CHAIN AND NOT A GATE. The last time a poller launched work on a condition, it fired
inside another poller's sleep window and silently corrupted a comparison. This launches only,
never edits code, and waits on each producer's OWN terminal marker.

=========================== TWO BUGS THIS FILE ALREADY HAD ===========================
Both were caught by watching it run, not by reading it. They are the reason the checks below
look paranoid.

BUG 1 -- STALE MARKER. v1 waited for "n100 PROBE COMPLETE" in lb_n100_probe.log. That marker
was ALREADY in the file, written by stage A twenty minutes earlier, so the chain matched it
two seconds after arming and launched the next stage on top of a running one. A completion
marker is only evidence if it was written AFTER you started waiting.
FIX: capture the log's byte length at arm time and scan only what is appended past it.

BUG 2 -- TENANCY CHECK THROUGH A GAP. v1's "no solver live" test passed because the running
probe happened to be between ladder points, building its next model with no solver child
alive. An instantaneous process check cannot distinguish "finished" from "between solves".
FIX: the predecessor is identified by its OWN process pattern, and the box must read clear on
several CONSECUTIVE checks spaced apart, not once.

STOP CRITERIA (the loophole question). Each stage ends on exactly one of:
  - its own COMPLETE marker, appended after we started waiting  -> proceed
  - its process gone without that marker                        -> STOP, report failure
  - the per-stage deadline elapsing                             -> STOP, report failure
A missing marker never counts as success. Silence is not completion.
"""
import argparse, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "lb_chain.log")
SOLVER_PATTERNS = ("easy_reduction", "lb_repair", "lb_campaign", "n100_probe")


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] CHAIN: {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def live(pattern):
    o = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }}).Count"],
                       capture_output=True, text=True).stdout.strip()
    try:
        return int(o or 0)
    except ValueError:
        return -1


def busy():
    return sum(max(0, live(p)) for p in SOLVER_PATTERNS)


def mark_offset(logfile):
    """Byte length NOW. Anything at or before this is history, not evidence (BUG 1)."""
    p = os.path.join(ROOT, "runs", logfile)
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def wait_for(marker, logfile, proc_pattern, deadline_s, offset):
    p = os.path.join(ROOT, "runs", logfile)
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            if os.path.exists(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    if marker in fh.read():
                        return True
        except Exception:
            pass
        if time.time() - t0 > 300 and live(proc_pattern) == 0:
            say(f"!! '{proc_pattern}' is gone but '{marker}' never appeared after our start "
                f"offset in {logfile}. Treating as FAILURE, not completion.")
            return False
        time.sleep(30)
    say(f"!! deadline {deadline_s:.0f}s elapsed waiting for '{marker}' in {logfile}")
    return False


def wait_idle(checks=3, gap=30):
    """Require the box to read clear on CONSECUTIVE checks -- one look can land in the gap
    between two solves and read clear while a stage is very much still running (BUG 2)."""
    clear = 0
    while clear < checks:
        n = busy()
        if n == 0:
            clear += 1
        else:
            if clear:
                say(f"  tenancy re-armed: {n} process(es) reappeared after {clear} clear check(s)")
            clear = 0
        time.sleep(gap)
    return True


def why(outfile, n=8):
    """Surface WHY a stage died.

    The stage's stdout/stderr go to runs/<outfile> (a .out), but every ABORT message names
    the .log the chain WATCHES. On 2026-09-10 the n30 repair was refused by repro_preflight's
    claims gate; the refusal was written to lb_repair_n30.out while the abort pointed at
    lb_repair_n30.log, which had no new line at all. The chain looked silent, the repair was
    relaunched twice into the same refusal, and it cost a day. The information was never
    missing -- only unnamed. So print the tail here rather than making a human guess which
    file to open.
    """
    fp = os.path.join(ROOT, "runs", outfile)
    if not os.path.exists(fp):
        say(f"  (no {outfile} to explain the failure)"); return
    tail = [l.rstrip() for l in open(fp, encoding="utf-8", errors="replace").readlines()[-n:]]
    say(f"  --- last {len(tail)} line(s) of {outfile} ---")
    for l in tail:
        if l.strip():
            say(f"  | {l}")


def launch(name, argv, outfile):
    say(f"confirming the box is idle before {name} ({SOLVER_PATTERNS})")
    wait_idle()
    out = open(os.path.join(ROOT, "runs", outfile), "a", encoding="utf-8")
    say(f"launching {name}")
    subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-stage-b", action="store_true")
    ap.add_argument("--crossover-sizes", default="",
                    type=lambda v: [int(x) for x in v.split(",") if x.strip()],
                    help="sizes to run after the repair, to locate the AB/MILP crossover")
    ap.add_argument("--wait-campaign", type=int, default=0,
                    help="wait for lb_campaign at this size to finish first")
    A = ap.parse_args()

    if A.wait_stage_b:
        off = mark_offset("lb_n100_probe.log")
        say(f"waiting for n100 stage B; ignoring the {off} bytes of log already written "
            f"(stage A's COMPLETE marker is in there)")
        if not wait_for("n100 PROBE COMPLETE", "lb_n100_probe.log", "n100_probe", 5 * 3600, off):
            say("ABORTING chain: stage B did not complete cleanly. Inspect before continuing."); why("lb_n100_stageb.out")
            return
        say("stage B complete")

    if A.wait_campaign:
        lg = f"lb_campaign_n{A.wait_campaign}.log"
        off = mark_offset(lg)
        say(f"waiting for lb_campaign n{A.wait_campaign}; ignoring {off} bytes already written")
        if not wait_for(f"LB CAMPAIGN n{A.wait_campaign} COMPLETE", lg, "lb_campaign",
                        30 * 3600, off):
            say("ABORTING chain: the n100 campaign did not complete cleanly."); why("lb_campaign_n100.out")
            return
        say(f"lb_campaign n{A.wait_campaign} complete")

    off = mark_offset("lb_repair_n30.log")
    launch("n30 repair", [PY, os.path.join(ROOT, "analysis", "lb_repair_n30.py")],
           "lb_repair_n30.out")
    if not wait_for("LB REPAIR n30 COMPLETE", "lb_repair_n30.log", "lb_repair", 24 * 3600, off):
        say("ABORTING chain: n30 repair did not complete cleanly."); why("lb_repair_n30.out")
        return
    say("n30 repair COMPLETE.")

    # --- CROSSOVER STAGES -------------------------------------------------------------
    # Measured composition of max(MILP, arithmetic) by size: AB share 0% at n20, 15% at n30
    # (and all four of those are k_cap-damaged cells the repair may reclaim), 61% at n100.
    # Median AB/MILP ratio 0.60x -> 0.68x -> 1.11x, so the crossover sits between n30 and n100.
    # n40 and n50 LOCATE it, and that measurement needs NO K reference -- it is our arithmetic
    # bound against our own MILP. This is also the strongest justification for n40, a size K
    # generates but tabulates nowhere.
    for size in (A.crossover_sizes or []):
        off = mark_offset(f"khi_probe_n{size}.log")
        launch(f"k_hi probe n{size}",
               [PY, os.path.join(ROOT, "analysis", "khi_probe.py"), "--size", str(size)],
               f"khi_probe_n{size}.out")
        if not wait_for(f"KHI_CHOSEN n{size}", f"khi_probe_n{size}.log", "khi_probe",
                        6 * 3600, off):
            say(f"ABORTING chain: k_hi probe for n{size} did not complete."); why(f"khi_probe_n{size}.out"); return
        khi = None
        for l in open(os.path.join(ROOT, "runs", f"khi_probe_n{size}.log"),
                      encoding="utf-8", errors="replace"):
            if f"KHI_CHOSEN n{size}" in l:
                khi = int(l.split("=")[1].split("(")[0].strip())
        if khi is None:
            say(f"ABORTING chain: could not parse k_hi for n{size}."); return
        say(f"n{size}: k_hi={khi} (|H|={size-khi}) chosen by the provability criterion")
        off = mark_offset(f"lb_campaign_n{size}.log")
        launch(f"lb_campaign n{size}",
               [PY, os.path.join(ROOT, "analysis", "lb_campaign.py"), "--size", str(size),
                "--k-hi", str(khi), "--det-tl", "450000", "--tl", "900",
                "--cell-budget", "2400"],
               f"lb_campaign_n{size}.out")
        if not wait_for(f"LB CAMPAIGN n{size} COMPLETE", f"lb_campaign_n{size}.log",
                        "lb_campaign", 30 * 3600, off):
            say(f"ABORTING chain: lb_campaign n{size} did not complete cleanly."); why(f"lb_campaign_n{size}.out"); return
        say(f"lb_campaign n{size} COMPLETE")
    say("CHAIN COMPLETE")


if __name__ == "__main__":
    main()
