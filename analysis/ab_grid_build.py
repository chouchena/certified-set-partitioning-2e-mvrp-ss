"""
Provenanced rebuild of the arithmetic-bound grid -- and a fidelity test of the existing one.

WHY THIS EXISTS (refactor finding A1, 2026-09-12). `runs/ab4_grid_results.json` is the sole
source of the C7 headline finding, and:

  * it carries NO provenance (no code_hash, git_sha, seed, host or timestamp), and
  * its producer, `scratchpad/ab4_grid.py`, NO LONGER EXISTS.

Nothing in the repo could regenerate it. `fullset_bound()` is deterministic arithmetic on
instance data, so a fresh driver MUST reproduce the stored values exactly. That makes this
script two things at once:

    --verify   recompute and diff against the stored artifact. A mismatch means the stored
               numbers came from code we no longer have, which would invalidate the headline.
    (default)  write runs/ab_grid_provenanced.json WITH provenance.

Deliberately writes to a NEW path. The original artifact is evidence and is not overwritten.
"""
import os, sys, json, time, socket, hashlib, argparse, subprocess, platform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from analysis.stamp import stamped

from build_instance import build
from crossfeed.fullset_bound import fullset_bound
from crossfeed.check_cuts import cut_bounds

CELLS = ([f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
         + [f"RC2{i:02d}" for i in range(1, 9)])
# The stored grid holds 162 records = 27 cells x 6 (size, prox) combinations.
COMBOS = [(10, 0.0), (20, 0.0), (30, 0.0), (40, 0.0), (50, 0.0), (100, 0.1)]

# A1 fix: the files that actually determine an AB number. The campaign's own code_hash set
# omits BOTH of these, which is why a change to the bound would not register anywhere.
AB_HASH_FILES = ("crossfeed/fullset_bound.py", "crossfeed/check_cuts.py",
                 "crossfeed/blockA_cpsat.py", "build_instance.py")


def provenance():
    h = hashlib.sha256()
    for rel in AB_HASH_FILES:
        fp = os.path.join(ROOT, rel)
        if os.path.exists(fp):
            h.update(open(fp, "rb").read())
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"],
                                      cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"],
                                             cwd=ROOT, text=True).strip())
    except Exception:
        sha, dirty = None, None
    return {"ab_code_hash": h.hexdigest()[:16], "ab_hash_files": list(AB_HASH_FILES),
            "git_sha": sha, "git_dirty": dirty, "host": socket.gethostname(),
            "python": platform.python_version(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seed": 0, "note": "AB is deterministic arithmetic: no solver, no seed dependence"}


def compute(cell, size, prox):
    p = build(cell, size, wls=0.1, tau="formula", proximity=prox, time_limit=60)
    b, parts = fullset_bound(p)
    cb = cut_bounds(p, list(p.customers))
    return {"cell": cell, "size": size, "prox": prox,
            "ab4": round(b, 6), "ab4_full": b,
            "ap": parts["dist_ap"], "mst": parts["dist_mst"], "forced": parts["dist_forced"],
            "best_travel": parts["dist_raw"], "which": parts["dist_winner"],
            "V_final": parts["V_LB"], "clique": parts["clique"],
            "clique_used": parts["clique_used"], "trips_lb": cb["trips_lb"],
            "water": parts["water"], "fleet_term": parts["fleet_term"],
            "travel_term": parts["travel_term"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="diff against runs/ab4_grid_results.json instead of writing")
    ap.add_argument("--combos", default="20:0.0,30:0.0",
                    help="size:prox pairs, or 'all' for the full 162-record grid")
    a = ap.parse_args()
    combos = (COMBOS if a.combos == "all"
              else [(int(x.split(":")[0]), float(x.split(":")[1])) for x in a.combos.split(",")])

    # The legacy artifact runs/ab4_grid_results.json was produced by the PRE-TW-PRUNING bound.
    # Comparing against it is a fidelity test ONLY while the bound is unchanged; once the bound
    # is intentionally tightened, a mismatch is the intended effect, not a defect. Guarded by
    # the ab_code_hash that produced the legacy file.
    # The live grid runs/ab_grid_provenanced.json was built at ab_code_hash 4134cf4a2559c9d8.
    # The CURRENT hash is 8013e7abf33abde7 and the divergence is BENIGN: the only
    # intervening change to an AB-hashed file is 0365e57, two docstring lines renaming
    # "Lemma 3" to "AB-L3" in fullset_bound.py. No computation changed, so the grid is
    # current despite the mismatch. Recorded because the 2026-09-17 sweep raised a false
    # staleness alarm on exactly this and had to re-derive it from git.
    LEGACY_HASH = "4897cede2c185f22"     # pre-TW-pruning
    old = {}
    op = os.path.join(ROOT, "runs", "ab4_grid_results.json")
    cur = provenance()["ab_code_hash"]
    legacy_applicable = (cur == LEGACY_HASH)
    if os.path.exists(op) and legacy_applicable:
        old = json.load(open(op))
    elif os.path.exists(op):
        print("NOTE: legacy fidelity check SKIPPED.")
        print("      ab_code_hash is now %s; the legacy artifact was produced by %s."
              % (cur, LEGACY_HASH))
        print("      The bound changed ON PURPOSE (TW arc pruning adopted 2026-09-12), so")
        print("      runs/ab4_grid_results.json is SUPERSEDED and is not a comparison target.")
        print("")

    recs, diffs, checked = [], [], 0
    for size, prox in combos:
        for cell in CELLS:
            r = compute(cell, size, prox)
            recs.append(r)
            key = f"{cell}|n{size}"
            o = old.get(key)
            if o is not None and abs(o.get("prox", 0.0) - prox) < 1e-9:
                checked += 1
                # The stored artifact holds values ROUNDED TO 2 DECIMALS, so compare at that
                # precision -- and round from FULL precision, never from the 6dp field. Two
                # tolerance bugs were hit here: 1e-4 flagged all 54 cells on 0.004-0.005
                # deltas (the rounding bound), and double-rounding 6dp->2dp flagged 8 more on
                # exact half-way values. Neither was a code difference.
                d = round(r["ab4_full"], 2) - o["ab4"]
                if abs(d) > 1e-9:
                    diffs.append((key, round(o["ab4"], 4), round(r["ab4"], 4), round(d, 4)))
                    print(f"  MISMATCH {key:14} stored={o['ab4']:.4f} "
                          f"recomputed={r['ab4']:.4f}  delta={d:+.4f}", flush=True)
        print(f"  n{size} prox {prox}: {len(CELLS)} cells computed", flush=True)

    print(f"\n{'=' * 70}")
    print(f"records computed : {len(recs)}")
    print(f"compared to stored artifact : {checked}")
    print(f"MISMATCHES : {len(diffs)}")
    if diffs:
        print("\n*** The stored grid was NOT produced by the current fullset_bound.")
        print("*** Every claim sourced from it is affected. Do not proceed until resolved.")
    elif checked:
        print("\nEXACT MATCH on every compared cell. The stored grid is retroactively")
        print("validated: it is reproducible from code we still hold, and the C7 headline")
        print("rests on numbers a third party can regenerate.")

    if not a.verify:
        out = {"provenance": provenance(), "records": recs}
        op2 = os.path.join(ROOT, "runs", "ab_grid_provenanced.json")
        json.dump(stamped(out, __file__), open(op2, "w"), indent=1)
        print(f"\n-> runs/ab_grid_provenanced.json  ab_code_hash={out['provenance']['ab_code_hash']}")
    return 2 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
