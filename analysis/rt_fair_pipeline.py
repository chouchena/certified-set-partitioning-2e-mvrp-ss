"""Make the same-machine RT comparison FAIR. Gated, then patch -> re-run -> report.

WHY. rt_normalize.py showed the same-machine reproduction of K's LBBD is high-FIDELITY
(0.92-1.09 of K's published LB, median 0.99) but is NOT a fair comparator, for two reasons
found on disk:

 1. BUDGET. Every reproduction ran ~900s (build time_limit=300 + lbbd_solve time_limit=600,
    both hardcoded defaults -- solver/lbbd.py:291,143). K's own LBBD IncT per cell ranges
    168-3763s, so we gave K's method between 0.24x and 5.36x the time K itself used, varying
    arbitrarily per cell. 0 of 12 reproductions converged; all hit the limit.
 2. THREADS. solver/lbbd.py sets NO thread count anywhere, so the reproduction ran at CPLEX's
    default = ALL 8 logical processors, while K ran 4 CPUs. It is not at K's basis either.

A time-limited, 8-thread, arbitrarily-budgeted reproduction cannot be presented as "K's method
on our machine". This fixes both, then regenerates the table.

STAGES
 0 GATE    wait for the kick ablation AND the LB coverage run (single tenancy).
 1 PATCH   expose --time-limit / --master-tl / --sub-tl / --threads on solver/lbbd.py and
           thread the value into Master.solve (and SubModel.solve where it accepts one).
           Idempotent; refuses while any solver process is live.
 2 SMOKE   one short cell; must produce a trace whose config records the thread count.
 3 RERUN   the 12 reproduction cells at 4 threads and a budget MATCHED to K's own LBBD IncT
           (1.5x, floor 900s, cap 5400s) so K's method is never handicapped.
 4 REPORT  re-run analysis/rt_normalize.py on the fair artifacts.
"""
import argparse, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LBBD = os.path.join(ROOT, "solver", "lbbd.py")
CELLS = ["C203", "C204", "R203", "R204", "R207", "R208", "R211",
         "RC201", "RC202", "RC203", "RC204", "RC208"]


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(os.path.join(ROOT, "runs", "rt_fair.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def busy():
    """True if ANY other python process from this repository is alive.

    FIXED 2026-09-15. The previous version matched an ALLOWLIST of five script names --
    fixopt.py, kick_ablation, calib_run, lb_coverage_run, easy_reduction. Every solver written
    since was invisible to it. On 2026-09-15 the live process was
    `analysis/s2k_exact_closure.py`, which matches none of them, so this gate read NOT BUSY
    while S2k was mid-run. Had this pipeline been armed it would have patched solver/lbbd.py
    and started a twelve-cell rerun on top of a comparison that scores its arms on WALL CLOCK.
    The earlier `redump_incumbents.py` was equally invisible.

    An allowlist of process names is the same failure family the run_pipeline header already
    records twice: `ps -ef | grep` for a path that never existed, and `pgrep` returning 127 so
    that `! pgrep` was always true. In each case the guard answered "clear" because it could
    not see, not because nothing was there.

    Now: the allowlist is DERIVED FROM THE FILESYSTEM. We enumerate every .py file this
    repository owns and match their basenames against the command lines of live python
    processes. A script added tomorrow is covered the day it is written, which is the property
    the hardcoded list lacked.

    NOT matching on the repository PATH, which was this fix's own first attempt and was also
    wrong: the pipeline does `cd "$(dirname "$0")"` and then `python analysis/foo.py`, so the
    command line carries a RELATIVE path and the absolute root never appears in it. The
    negative control caught that; without one this would have shipped reading NOT BUSY for the
    same reason as the bug it replaces.

    FAILS CLOSED. Any error returns True: if we cannot tell, we wait. A gate that guesses
    "clear" is what this replaces.
    """
    ps_script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script],
                             capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return True
    if not out:
        return False
    try:
        data = json.loads(out)
    except Exception:
        return True
    if isinstance(data, dict):
        data = [data]
    me = os.getpid()
    owned = _repo_scripts()
    for proc in data:
        try:
            pid = int(proc.get("ProcessId") or 0)
        except Exception:
            return True
        if not pid or pid == me:
            continue
        cmd = os.path.normcase(proc.get("CommandLine") or "")
        if any(name in cmd for name in owned):
            return True
    return False


def _repo_scripts():
    """Basenames of every .py file this repository owns, lowercased.

    Derived rather than listed, so a solver added later is seen without anyone remembering to
    update a guard. `archive/` is excluded: it holds superseded scripts that are not run.
    """
    out = set()
    for sub in (".", "analysis", "crossfeed", "solver", "validation", "scripts"):
        d = os.path.join(ROOT, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith(".py") and len(fn) > 5:      # skip trivially short names
                out.add(os.path.normcase(fn))
    return out


def k_lbbd_inct(size=20):
    """K's own LBBD IncT per cell at this size -- the budget their method actually got.

    SIZE IS A PARAMETER because the same matched-budget question is asked at |C|=30, where
    it is the registered falsifier for `beats-both-k-bounds-v3`. K publish 27 per-instance
    rows at both 20 and 30.
    """
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        # LBBD Imp% carries "+0.6" and bolded "**-12.7**", so the cell pattern must admit
        # + and * as well as the unicode minus. Without that, R207/R211/RC203 silently fell
        # through to the floor budget -- re-introducing the very handicap this fixes.
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|" + r"\s*([\d.+*−-]+)\s*\|" * 6, l)
        if m and sec and f"= {size}" in sec:
            try:
                out[m.group(1)] = float(m.group(7).replace("*", "").replace("−", "-"))
            except ValueError:
                pass
    return out


def backup_existing(cells, size):
    """Copy any artifact stage 3 is about to OVERWRITE into a timestamped folder.

    WHY THIS EXISTS. M6 rewrote runs/lbbd_<cell>_n20_karademir.jsonl in place for all twelve
    cells, backed nothing up, and runs/ is gitignored -- so the pre-M6 per-cell BOUNDS are
    gone and the before/after its own pre-registration asked for is only partly answerable
    (RESULT_M6_matched_budget.md section 6). A stage that overwrites the artifacts its own
    baseline depends on must copy them first.

    Copies only what exists, never overwrites a previous backup, and never blocks the run.
    """
    import shutil
    dest = os.path.join(ROOT, "runs", "pre_rerun_%s" % time.strftime("%Y%m%d_%H%M%S"))
    saved = 0
    for c in cells:
        src = os.path.join(ROOT, "runs", f"lbbd_{c}_n{size}_karademir.jsonl")
        if not os.path.exists(src):
            continue
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
        saved += 1
    say(f"STAGE 3: backed up {saved} existing artifact(s)"
        + (f" -> {os.path.relpath(dest, ROOT)}" if saved else " (none present -- fresh arm)"))
    return saved


PATCHES = [
    ('    def solve(self, time_limit=300):\n        self.m.parameters.timelimit = time_limit',
     '    def solve(self, time_limit=300, threads=None):\n'
     '        self.m.parameters.timelimit = time_limit\n'
     '        if threads:\n'
     '            self.m.parameters.threads = threads',
     "Master.solve threads"),
    ('def lbbd_solve(problem, spec, *, cut_arm="karademir", time_limit=600,\n'
     '               master_tl=180, sub_tl=60, max_iter=25, log=True) -> LBBDResult:',
     'def lbbd_solve(problem, spec, *, cut_arm="karademir", time_limit=600,\n'
     '               master_tl=180, sub_tl=60, max_iter=25, log=True,\n'
     '               threads=None) -> LBBDResult:',
     "lbbd_solve signature"),
    ('        ms = master.solve(time_limit=master_tl)',
     '        ms = master.solve(time_limit=master_tl, threads=threads)',
     "master call"),
    ('        sr = sub.solve(time_limit=sub_tl)',
     '        try:\n'
     '            sr = sub.solve(time_limit=sub_tl, threads=threads)\n'
     '        except TypeError:      # SubModel predates the threads kwarg\n'
     '            sr = sub.solve(time_limit=sub_tl)',
     "sub call"),
    ('    ap.add_argument("--max-iter", type=int, default=20)',
     '    ap.add_argument("--max-iter", type=int, default=20)\n'
     '    ap.add_argument("--time-limit", type=float, default=600,\n'
     '                    help="overall LBBD budget (s). Was hardcoded at the 600 default, "\n'
     '                         "which handicapped K\'s method by 0.24x-5.36x per cell.")\n'
     '    ap.add_argument("--master-tl", type=float, default=180)\n'
     '    ap.add_argument("--sub-tl", type=float, default=60)\n'
     '    ap.add_argument("--threads", type=int, default=None,\n'
     '                    help="solver threads. Unset = CPLEX default = ALL cores, which is "\n'
     '                         "what every existing reproduction used. K ran 4.")',
     "CLI args"),
    ('    r = lbbd_solve(p, spec, cut_arm=a.cut_arm, max_iter=a.max_iter)',
     '    r = lbbd_solve(p, spec, cut_arm=a.cut_arm, max_iter=a.max_iter,\n'
     '                   time_limit=a.time_limit, master_tl=a.master_tl, sub_tl=a.sub_tl,\n'
     '                   threads=a.threads)',
     "lbbd_solve call"),
]


def stage1_patch():
    src = open(LBBD, encoding="utf-8").read()
    if "threads=None) -> LBBDResult" in src:
        say("STAGE 1: already patched -- no-op")
        return True
    if busy():
        say("STAGE 1: REFUSING -- solver processes still live"); return False
    for anchor, repl, what in PATCHES:
        if src.count(anchor) != 1:
            say(f"STAGE 1: ABORT -- anchor for {what} matched {src.count(anchor)} times")
            return False
        src = src.replace(anchor, repl)
    open(LBBD, "w", encoding="utf-8").write(src)
    say("STAGE 1: applied 6 edits to solver/lbbd.py")
    return True


def stage2_smoke(size=20, cell="RC201"):
    """Short run proving the patched CLI threads a thread count into the trace.

    IT WRITES TO A REAL ARTIFACT PATH, which is the trap: hardcoded at RC201/n20, running
    this before an |C|=30 arm would have overwritten RC201's M6 result -- an artifact that
    cannot be regenerated cheaply and that RESULT_M6_matched_budget.md depends on. It now
    smokes at the arm's own size and backs up whatever it is about to replace.
    """
    backup_existing([cell], size)
    say(f"STAGE 2: smoke -- {cell} n{size}, 4 threads, 300s")
    r = subprocess.run([PY, LBBD, "--instance", cell, "--size", str(size),
                        "--time-limit", "300", "--threads", "4", "--max-iter", "6"],
                       cwd=ROOT, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        say("STAGE 2: FAILED"); say((r.stdout + r.stderr)[-1200:]); return False
    say("STAGE 2: OK -- " + (r.stdout.strip().splitlines() or ["(no output)"])[-1][:160])
    return True


def stage3_rerun(mult, floor, cap, size=20, cells=None):
    inct = k_lbbd_inct(size)
    cells = cells or CELLS
    backup_existing(cells, size)
    say(f"STAGE 3: re-run {len(cells)} cells at |C|={size}, 4 threads, budget = {mult}x "
        f"K's own LBBD IncT (floor {floor}s, cap {cap}s)")
    for i, c in enumerate(cells, 1):
        ki = inct.get(c)
        bud = min(cap, max(floor, (ki or floor) * mult))
        say(f"[{i}/{len(cells)}] {c} n{size}: K IncT={ki} -> budget {bud:.0f}s")
        t0 = time.time()
        try:
            subprocess.run([PY, LBBD, "--instance", c, "--size", str(size),
                            "--time-limit", str(bud), "--threads", "4", "--max-iter", "60"],
                           cwd=ROOT, timeout=bud + 1800,
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        except Exception as e:
            say(f"  {c} ERROR/timeout: {e}")
        say(f"  {c} done in {time.time()-t0:.0f}s")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mult", type=float, default=1.5)
    ap.add_argument("--floor", type=float, default=900)
    ap.add_argument("--cap", type=float, default=5400)
    ap.add_argument("--size", type=int, default=20)
    ap.add_argument("--skip-smoke", action="store_true",
                    help="stage 1 is idempotent and was smoke-verified when first applied; "
                         "skip re-proving it")
    ap.add_argument("--cells", default="",
                    help="comma-separated; default is the 12 paired reproduction cells")
    ap.add_argument("--wait", action="store_true")
    a = ap.parse_args()
    if a.wait:
        say("STAGE 0: waiting for ablation + LB coverage (single tenancy) ...")
        while busy():
            time.sleep(300)
        say("STAGE 0: cores free")
    if not stage1_patch():
        sys.exit(1)
    if not a.skip_smoke and not stage2_smoke(a.size):
        say("STOPPED after smoke failure"); sys.exit(1)
    cells = [x.strip() for x in a.cells.split(",") if x.strip()] or CELLS
    stage3_rerun(a.mult, a.floor, a.cap, a.size, cells)
    say("STAGE 4: report")
    # --size, or stage 4 reports n20 whatever the arm ran at. This omission voided M7's report.
    subprocess.run([PY, os.path.join(ROOT, "analysis", "rt_normalize.py"),
                    "--size", str(a.size)], cwd=ROOT)
    say("RT FAIR PIPELINE COMPLETE")


if __name__ == "__main__":
    main()
