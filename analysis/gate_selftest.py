"""Mutation self-test for the release gate: can each blocking check actually FAIL? (d584)

THE CLASS OF DEFECT THIS ATTACKS. A check that cannot fail is worse than no check, because it is
believed. In the last month this project has shipped four of them:

  * G23 reported PASS over two live crashes -- twice, first because it accepted any line containing
    "if", then because it scanned physical lines while the defect spanned two;
  * G8 passed on a snapshot twelve days old covering 60 of 135 incumbents, so its empty `gaps` said
    nothing about the paper;
  * G5, G6 and G7 gated the retained-set corpus the manuscript had already replaced -- they could
    not fail on anything the paper says;
  * `certified()` returned True for a ceil-rounded artifact, so `bound_class` labelled a restriction
    "elementary", and no check asked.

Reading a check cannot establish that it works. Breaking something and watching it fire can.

HOW IT WORKS. For each mutation below: apply it to a COPY of the tree (nothing in the working tree
is touched), run the gate there, and assert the named check goes red. A mutation that leaves the
gate green is reported as a HOLE -- the check does not cover what its name claims.

    python analysis/gate_selftest.py [--only G24]

Exit 1 if any mutation fails to trip its check.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mut_unguarded_comparator(tree):
    """G23: put back the exact shape that crashed the campaign -- a float format of kb with the only
    guard being an unrelated ternary, split across two physical lines."""
    p = os.path.join(tree, "analysis", "tep_selftest_probe.py")
    io.open(p, "w", encoding="utf-8").write(
        "from k_comparison import k_best_incumbent\n"
        "def f(cell, size, obj, ok):\n"
        "    kb, which = k_best_incumbent(cell, size)\n"
        "    print('%s obj %.3f | verifier3 %s | vs theirs %+.2f%%'\n"
        "          % (cell, obj, 'PASS' if ok else 'FAIL',\n"
        "             100.0 * (obj / kb - 1)))\n")
    return "G23"


def mut_uncertified_bound(tree):
    """G25: strip the certificate class from a reported bound."""
    p = os.path.join(tree, "runs", "oracle", "tep_n30_best_of.json")
    d = json.load(io.open(p, encoding="utf-8"))
    for r in d["rows"]:
        if r.get("our_lb"):
            r["lb_class"] = None
            break
    json.dump(d, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
    return "G25"


def mut_better_solution_unread(tree):
    """G24: plant a verified solution better than the banked incumbent, in the place the readers do
    not look -- which is exactly what happened twice for real."""
    import glob
    src = sorted(glob.glob(os.path.join(tree, "runs", "oracle", "tep_cg_bound_*_n20_ip.json")))
    for p in src:
        d = json.load(io.open(p, encoding="utf-8"))
        ip = d.get("ip")
        if isinstance(ip, dict) and ip.get("verified") and ip.get("objVal"):
            ip["objVal"] = float(ip["objVal"]) * 0.5
            ip["solution"]["objVal"] = ip["objVal"]
            json.dump(d, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
            return "G24"
    return None


def mut_incumbent_below_bound(tree):
    """G26: make a reported bound exceed the incumbent it belongs to."""
    import glob
    for p in sorted(glob.glob(os.path.join(tree, "runs", "postpass", "ownwater_*_n20.json"))):
        d = json.load(io.open(p, encoding="utf-8"))
        d["objVal"] = float(d["objVal"]) * 0.2          # far below any bound
        json.dump(d, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
        return "G26"
    return None


def mut_stale_snapshot(tree):
    """G8: make the published snapshot older than the artifacts it claims to cover."""
    p = os.path.join(tree, "published_artifacts", "MANIFEST.json")
    if not os.path.exists(p):
        return None
    os.utime(p, (0, 0))
    return "G8"


def mut_unstamped_artifact(tree):
    """G6c: remove the provenance from a TEP artifact."""
    import glob
    for p in sorted(glob.glob(os.path.join(tree, "runs", "oracle", "tep_n*_best_of.json"))):
        d = json.load(io.open(p, encoding="utf-8"))
        if isinstance(d, dict) and d.get("_provenance"):
            d["_provenance"].pop("code_hash", None)
            json.dump(d, io.open(p, "w", encoding="utf-8"), indent=1, default=str)
            return "G6c"
    return None


MUTATIONS = [
    ("an unguarded comparator split over two lines", mut_unguarded_comparator),
    ("a reported bound with no certificate class", mut_uncertified_bound),
    ("a better verified solution left where readers do not look", mut_better_solution_unread),
    ("an incumbent below our own bound", mut_incumbent_below_bound),
    ("a published snapshot older than the evidence", mut_stale_snapshot),
    ("a TEP artifact with no code_hash", mut_unstamped_artifact),
]


def run_gate(tree):
    """Returns (red checks, crash message or None).

    THE FIRST VERSION IGNORED THE EXIT AND stderr, so a gate that CRASHED in the mutated copy looked
    exactly like a gate that passed -- and the self-test then reported the check as a hole. That is
    the same error the self-test exists to find, made inside the self-test itself (2026-09-28)."""
    r = subprocess.run([sys.executable, os.path.join(tree, "analysis", "release_gate.py"), "--tree", tree],
                       capture_output=True, text=True, timeout=1800)
    out = r.stdout or ""
    red = set()
    for line in out.splitlines():
        if "**FAIL**" in line:
            for tok in line.split():
                if tok.startswith("G"):
                    red.add(tok); break
    crash = None
    if "VERDICT" not in out:
        tailerr = (r.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
        crash = "gate did not reach a verdict (exit %s): %s" % (r.returncode, tailerr[0][:90])
    return red, crash


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=None); a = ap.parse_args()
    base_red, base_crash = run_gate(ROOT)
    if base_crash:
        print("  the gate does not run cleanly on the working tree: %s" % base_crash)
    print("MUTATION SELF-TEST OF THE RELEASE GATE\n")
    print("  the gate on the working tree is already red on: %s" % (", ".join(sorted(base_red)) or "nothing"))
    print("  a mutation counts as CAUGHT only if it turns its own check red beyond that.\n")
    holes = []
    for desc, fn in MUTATIONS:
        tmp = tempfile.mkdtemp(prefix="gate_selftest_")
        dst = os.path.join(tmp, "tree")
        # copy only what the gate reads; a full tree copy would take minutes
        shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "logs", "__pycache__", "*.pdf", "*.eps"))
        want = None
        try:
            want = fn(dst)
            if want is None:
                print("  %-58s SKIPPED (no suitable artifact)" % desc); continue
            if a.only and want != a.only:
                continue
            red, crash = run_gate(dst)
            if crash:
                print("  %-58s %s INCONCLUSIVE: %s" % (desc, want, crash))
                holes.append((desc, want + " (inconclusive)"))
                continue
            if want in base_red:
                print("  %-58s %s INCONCLUSIVE: already red on the working tree" % (desc, want))
                continue
            caught = want in red
            print("  %-58s %s %s" % (desc, want, "CAUGHT" if caught else "*** NOT CAUGHT -- the check has a hole"))
            if not caught:
                holes.append((desc, want))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\n  %d mutation(s) tested, %d hole(s)" % (len(MUTATIONS), len(holes)))
    for d, w in holes:
        print("    %s does not fail on: %s" % (w, d))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
