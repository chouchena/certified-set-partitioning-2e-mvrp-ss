"""Overnight batches against the agreed target. Design pre-mortem is the docstring.

TARGET (agreed): family-level dominance over K on K's NON-OPTIMAL instances, measured as
OptGap% (a presentation of LB needing no OV of ours). n20 is done and passing. n30 is 7 of 26.

BATCH 1 -- complete n30 LB coverage, uniform protocol.
BATCH 2 -- budget ladder on every cell that STALLED, selected by a mechanical outcome-blind rule.

================================ PRE-MORTEM ================================
Written before launch, per the standing rule. What could invalidate these runs:

1. NON-UNIFORM PROTOCOL across cells -> the family average would mix settings.
   MITIGATION: batch 1 uses exactly the settings the 7 completed cells used --
   tl=450s per k, k_hi=15, threads=4, proximity=0.0. No cell gets special treatment, so the
   completed cells need no re-run and the family means are computed over one protocol.

2. CO-TENANCY. The entire n30 primal campaign was invalidated by running two cells at once on a
   4P+4LPE part. MITIGATION: strictly sequential, one solver process at a time. Asserted at
   launch and re-checked between cells.

3. TUNING ON THE OUTCOME. Raising tl because R211/R208 lost would be exactly that.
   MITIGATION: batch 2's selection rule is "the descend produced a single unproven record at
   k_hi" -- a PROCESS fact, not a result. RC204 stalled and WON (1.69x); it is in the ladder
   too. And the ladder reports a bound-vs-budget FRONTIER rather than picking a tl, so there is
   no tuned parameter to defend. Every point on it is a valid bound (proof Step 0).

4. WRONG K REFERENCE SIZE. Fixing only our side of the ratio once made an error worse.
   MITIGATION: the n30 verdict watcher is size-explicit on BOTH halves; verified against n20
   and n30 before launch.

5. READING RESULTS EARLY. Three failures this session. MITIGATION: verdicts key on the runner's
   own "<CELL> done in Ns" completion line, never on file appearance, record count, or counters.

6. PROXIMITY MISMATCH. n30 compares to K Table 3, which is proximity 0.0 -- our default. (Only
   n100/Table 6 needs 0.1.) MITIGATION: left at 0.0 and stated here so it is not silently wrong
   if this script is later reused for n100.

7. INTERRUPTION LEAVING A SKEWED SET. If the batch is killed early, a gap-ordered run would
   leave only easy cells. MITIGATION: cells are interleaved across families, so any prefix is
   family-balanced.

8. LADDER OVERWRITING THE BASELINE. easy_reduction_descend writes to a FIXED filename
   (easy_reduction_descend_<cell>_n30.json), so re-running a cell at a higher tl would destroy
   its tl=450 result -- i.e. batch 2 would erase the very frontier it exists to measure, and
   silently, since the file would still look valid. Caught in this pre-mortem, before launch.
   MITIGATION: snapshot each artifact to a tl-tagged copy after every run, and snapshot the
   existing tl=450 artifacts BEFORE the ladder starts.

RESIDUAL RISK ACCEPTED: cells that stall give a FLOOR, not an estimate of what the method can
prove. That is what batch 2 measures rather than assumes.
============================================================================
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOG = os.path.join(ROOT, "runs", "night_batch.log")
TL, K_HI, THREADS, PROX = 450, 15, 4, 0.0


def say(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def k_targets(size=30):
    """K's NON-OPTIMAL instances at this size (gap > 0) -- the agreed target set."""
    out, sec = {}, None
    for l in open(os.path.join(ROOT, "paper", "paper-reference-data.md"), encoding="utf-8"):
        if l.startswith("### |C|"):
            sec = l.strip()
        m = re.match(r"\|\s*((?:C|R|RC)\d{3})\s*\|\s*([\d.]+)\s*\|\s*([\d.+*−-]+)\s*\|", l)
        if m and sec and f"= {size}" in sec:
            try:
                g = float(m.group(3).replace("*", "").replace("−", "-"))
                if g > 0:
                    out[m.group(1)] = g
            except ValueError:
                pass
    return out


def descend_artifact(cell, size=30):
    fs = glob.glob(os.path.join(ROOT, "crossfeed", f"easy_reduction_descend_{cell}_n{size}.json"))
    return fs[0] if fs else None


def stalled(cell, size=30):
    """PROCESS fact, not a result: the descend produced a single unproven record at k_hi.
    Outcome-blind by construction -- RC204 stalled and won 1.69x, and is included."""
    f = descend_artifact(cell, size)
    if not f:
        return False
    r = json.load(open(f, encoding="utf-8"))
    r = r if isinstance(r, list) else [r]
    r = [x for x in r if isinstance(x, dict) and x.get("block_relax") is not None]
    return len(r) == 1 and not r[0].get("proven")


def interleave(cells, K):
    """Family-interleaved so any prefix of an interrupted batch stays family-balanced."""
    byfam = {f: sorted([c for c in cells if ("RC" if c.startswith("RC") else c[0]) == f],
                       key=lambda c: -K[c]) for f in ("C", "R", "RC")}
    out, i = [], 0
    while any(byfam.values()):
        for f in ("C", "R", "RC"):
            if byfam[f]:
                out.append(byfam[f].pop(0))
        i += 1
    return out


def live_solvers():
    o = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*easy_reduction*' -or "
                        "$_.CommandLine -like '*fixopt.py*' }).Count"],
                       capture_output=True, text=True).stdout.strip()
    try:
        return int(o or 0)
    except ValueError:
        return -1


def snapshot(cell, tl, size=30):
    """Preserve this run's artifact under a tl-tagged name. Without this the ladder would
    overwrite the baseline (pre-mortem item 8)."""
    f = descend_artifact(cell, size)
    if not f:
        return None
    dst = f.replace(".json", f"_tl{int(tl)}.json")
    try:
        shutil.copyfile(f, dst)
        return dst
    except Exception as e:
        say(f"  !! snapshot failed for {cell} tl={tl}: {e}")
        return None


def run_cell(cell, tl, tag):
    n = live_solvers()
    if n > 0:
        say(f"  WAIT: {n} solver process(es) live before {cell}; holding for single tenancy")
        while live_solvers() > 0:
            time.sleep(60)
    t0 = time.time()
    try:
        subprocess.run([PY, os.path.join(ROOT, "crossfeed", "easy_reduction_descend.py"),
                        "--cells", cell, "--size", "30", "--tl", str(tl),
                        "--k-hi", str(K_HI), "--workers", str(THREADS),
                        "--proximity", str(PROX)],
                       cwd=ROOT, timeout=tl * 20 + 600,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    except Exception as e:
        say(f"  {cell} [{tag}] error/timeout: {e}")
    say(f"  {cell} done in {time.time()-t0:.0f}s   [{tag} tl={tl}]")
    snap = snapshot(cell, tl)
    if snap:
        say(f"    snapshot -> {os.path.basename(snap)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="1,2")
    ap.add_argument("--ladder", default="900,1800")
    a = ap.parse_args()
    K = k_targets(30)
    say(f"target set at n30: {len(K)} K-non-optimal cells")

    if "1" in a.batch:
        todo = [c for c in K if not descend_artifact(c)]
        todo = interleave(todo, K)
        say(f"=== BATCH 1: n30 LB coverage, {len(todo)} cells, uniform "
            f"tl={TL} k_hi={K_HI} threads={THREADS} prox={PROX}, family-interleaved ===")
        say(f"    order: {todo}")
        for i, c in enumerate(todo, 1):
            # re-check per cell: the lb_n30 stage may still be finishing RC208 as we start,
            # and re-running a cell that already has an artifact at this exact protocol is
            # pure waste (it would overwrite with identical settings).
            if descend_artifact(c):
                say(f"[1:{i}/{len(todo)}] {c} SKIP -- artifact already present at this protocol")
                continue
            say(f"[1:{i}/{len(todo)}] {c} (K gap {K[c]:.0f}%)")
            run_cell(c, TL, "batch1")
        say("=== BATCH 1 COMPLETE ===")

    if "2" in a.batch:
        st = [c for c in K if stalled(c)]
        say(f"=== BATCH 2: budget ladder on {len(st)} STALLED cells (process rule, "
            f"outcome-blind) ===")
        say(f"    stalled: {st}")
        for c in st:                     # preserve the tl=450 baseline BEFORE overwriting it
            snap = snapshot(c, TL)
            if snap:
                say(f"    baseline preserved -> {os.path.basename(snap)}")
        for tl in [int(x) for x in a.ladder.split(",") if x.strip()]:
            for i, c in enumerate(st, 1):
                say(f"[2:tl={tl} {i}/{len(st)}] {c}")
                run_cell(c, tl, "ladder")
        say("=== BATCH 2 COMPLETE ===")
    say("NIGHT BATCH COMPLETE")


if __name__ == "__main__":
    main()
