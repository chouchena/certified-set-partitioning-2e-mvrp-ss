"""Replay-verify a proposed code change against every existing artifact.

THE PROBLEM THIS SOLVES. A code change normally forces a re-run of the whole grid, because
artifacts produced under a different `code_hash` are not obviously comparable. That is
expensive: 27 cells at n100 alone cost 16 h.

THE PROTOCOL. Some changes only decide WHICH of the already-recorded solves to keep, or when
to stop the ladder. For those, the reported bound under the patched code is a deterministic
function of data the artifacts ALREADY contain. We can therefore compute, without running
anything, whether the patch would have changed any reported number. If it would not, the
existing artifacts remain valid under the new code and only genuinely impaired cells need
re-running.

    patch -> replay over all artifacts -> 0 bounds changed -> freeze, re-run only the impaired

WHAT IS REPLAY-VERIFIABLE
  * stopping rules (when to abandon the descent)
  * selection rules (which records feed the reported maximum)
  * aggregation changes (how the max is taken)
  * budget REDUCTIONS, via lb_curve, which records the anytime trajectory inside each solve
WHAT IS NOT
  * changing k_hi          -- solves at other k were never run; no data exists
  * budget INCREASES       -- no trajectory beyond where the solve stopped
  * new cuts / model edits -- changes the relaxation itself
  * warm-start changes     -- changes each solve's trajectory
A patch in the second group cannot be frozen this way and needs a real re-run.

MEASURED RESULTS (2026-09-11, 122 cells / 902 records):
  patience=1 early-stop : 33 bounds LOST  -> unsafe
  patience=2            :  6 bounds LOST  -> unsafe
  patience=3            :  0 bounds lost, 34 solves and 2.95 h saved -> SAFE, freezable
  skip already-failed k :  6 bounds LOST  -> unsafe. The warm re-solve beats its cold
                          attempt 17/17 times and IS the cell's reported best 6 times.
                          It looked like waste and is not.
"""
import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def artifacts(pattern="easy_reduction_descend_*.json"):
    for fp in glob.glob(os.path.join(ROOT, "crossfeed", pattern)):
        if "_noprov" in fp or "_kcapbug" in fp or "_tl450" in fp:
            continue          # snapshots, not live artifacts
        try:
            J = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        R = [x for x in J if isinstance(x, dict)
             and x.get("block_relax") is not None and x.get("k") is not None]
        if R:
            yield os.path.basename(fp), sorted(R, key=lambda r: -r["k"])   # execution order


def rule_patience(records, P):
    """Stop the descent after P consecutive truncated solves that fail to improve the best.
    Returns (kept_records, skipped_records)."""
    kept, skipped, best, streak, stopped = [], [], None, 0, False
    for x in records:
        if stopped:
            skipped.append(x)
            continue
        kept.append(x)
        useless = best is not None and not x.get("proven") and x["block_relax"] <= best + 1e-6
        streak = streak + 1 if useless else 0
        best = x["block_relax"] if best is None else max(best, x["block_relax"])
        if streak >= P:
            stopped = True
    return kept, skipped


def rule_skip_refailed_k(records):
    """Never re-solve a k that already hit a limit. REJECTED by replay -- kept so the
    rejection is reproducible rather than remembered."""
    kept, skipped, failed = [], [], set()
    for x in records:
        if x["k"] in failed:
            skipped.append(x)
            continue
        kept.append(x)
        if not x.get("proven"):
            failed.add(x["k"])
    return kept, skipped


RULES = {
    "patience1": lambda R: rule_patience(R, 1),
    "patience2": lambda R: rule_patience(R, 2),
    "patience3": lambda R: rule_patience(R, 3),
    "patience4": lambda R: rule_patience(R, 4),
    "skip_refailed_k": rule_skip_refailed_k,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True, choices=sorted(RULES))
    ap.add_argument("--pattern", default="easy_reduction_descend_*.json")
    A = ap.parse_args()
    fn = RULES[A.rule]
    cells = changed = saved_n = 0
    saved_wall = 0.0
    deltas = []
    for name, R in artifacts(A.pattern):
        cells += 1
        old = max(x["block_relax"] for x in R)
        kept, skipped = fn(R)
        new = max(x["block_relax"] for x in kept) if kept else None
        saved_n += len(skipped)
        saved_wall += sum((x.get("wall") or 0) for x in skipped)
        if new is None or abs(new - old) > 1e-6:
            changed += 1
            deltas.append((name, old, new))
    print(f"rule: {A.rule}   artifacts: {cells}")
    print(f"  reported bound CHANGED on {changed} cell(s)")
    print(f"  solves skipped: {saved_n}   wall saved: {saved_wall/3600:.2f} h")
    for n, o, v in deltas[:12]:
        print(f"    {n[:52]:54} {o:9.2f} -> {('none' if v is None else f'{v:9.2f}')}")
    print()
    if changed == 0:
        print("  VERDICT: BOUND-NEUTRAL on the existing corpus. Freezable without re-runs:")
        print("  every artifact would report the identical value under the patched code.")
        print("  NOTE this is EMPIRICAL, not a proof -- it holds for the runs we have.")
    else:
        print("  VERDICT: NOT bound-neutral. Applying it would change reported numbers,")
        print("  so it cannot be frozen by replay and needs a full re-run to adopt.")


if __name__ == "__main__":
    main()
