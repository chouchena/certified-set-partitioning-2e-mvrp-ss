"""Generate the clean release tree. The working repository CANNOT be published as-is.

WHY A GENERATED TREE. All 35 of the predecessors' files entered at the ROOT commit, so they are
present in every one of this repository's commits. History rewriting would fix that and is
EXCLUDED, because it changes every commit hash and orphans the `git_sha` stamped into every
artifact -- destroying the reproducibility record the campaign exists to produce.

So the release is a SEPARATE tree with no shared history, and it is GENERATED rather than
hand-assembled. A hand-copied release is exactly where a stray file survives.

WHAT IS EXCLUDED, and why each matters:
  * the 35 files in third_party_manifest.json -- their repository declares NO LICENCE, so we
    have no right to redistribute them. We ship SHA-256 hashes and a fetch script instead,
    which proves version identity without taking what is not ours.
  * their PUBLISHED PAPER and its extracted text. This is a separate and clearer problem than
    the unlicensed code: a copyrighted publisher PDF. The manifest does not cover it and the
    original G1 check missed it entirely.
  * run outputs that are regenerable and bulky; the frozen `published_artifacts/` snapshot is
    shipped instead.

The exported tree is then checked by `analysis/release_gate.py --tree <dest>`, so the export is
VERIFIED rather than trusted.

Usage:  python analysis/export_release.py --dest ../2emvrpss-bounds-release [--force]
"""
import os, sys, json, shutil, subprocess, argparse, fnmatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Publisher-copyright content. Keeping a copy to read is ordinary; shipping it is not.
DENY_EXACT = {
    "paper/karademir2025-EJOR.pdf",
    "paper/karademir2025-fulltext-layout.txt",
    # The authors' OWN SRPS manuscript, under review elsewhere. Unpublished work, held only
    # as a self-plagiarism reference corpus. Shipping it would publish a manuscript that is
    # still with another journal's referees.
    "paper/srps-submitted-fulltext.txt",
}

# Working-repository scaffolding with no place in a replication package.
DENY_GLOB = [
    "logs/*",            # live run logs
    "scratch/*",
    "*.log",
    "ResultsJoint/*",    # THEIRS. See below.
    "paper/srps*",       # OURS, unpublished, under review. See DENY_EXACT.
    "analysis/probe_*.py",  # exploratory probes (per the .gitignore convention); not reported-number
                            # generators and not validation instruments, so they stay out of the release.
    # Curation (2026-10-11): the release is the generators + core + artifacts, not the working tree.
    # archive/ is locked/retired material (archive/fixopt_locked, carrying its own MOVED/REDFLAGGED
    # notes); scripts/ are campaign launch shells (chain_s2*, launch_s2*) that no reported-number
    # generator and neither README nor REPLICABILITY.md invokes. Both are working scaffolding.
    # crossfeed/ and results/incumbents/ are KEPT: shipped generators read crossfeed, and the banked
    # incumbents under results/ are what a reviewer re-verifies.
    "archive/*",
    "scripts/*",
]

# THIRD-PARTY CONTENT THE MANIFEST DOES NOT COVER.
# `third_party_manifest.json` pins the 35 files `fetch_karademir.py` restores, and `denied()`
# drops those. `ResultsJoint/` is ALSO theirs -- it arrived in the inherited-repository
# baseline commit (d542ec2) and holds their solved-route outputs -- but it is not in the
# manifest, so G1 never checked it and the export shipped all 15 files. In a release that
# states it contains none of their material, from a repository that declares NO LICENCE.
# Denied by glob above; `analysis/release_gate.py` G1c now checks for it independently,
# because a deny list that nothing verifies is a comment.

# ARTIFACTS THE MANUSCRIPT PIPELINE READS THAT GIT DOES NOT TRACK.
# The export ships `git ls-files`, and `runs/*` is gitignored -- so the release tree arrived
# with 3 of the files under runs/ and could not regenerate 5 of its own 19 numbers. A
# replication package that cannot reproduce the numbers it publishes is the one defect the
# data-availability statement must not have. Listed explicitly rather than by glob, so that
# adding a manuscript number that reads a new artifact fails the gate instead of silently
# shipping a tree that cannot rebuild itself.
INCLUDE_UNTRACKED = [
    "runs/ab4_grid_results.json",             # F5, T1, and 3 registry numbers
    "runs/summary.csv",                       # T2 objective identity
    "runs/fleet_subset_infeasibility.json",   # fleet-certificate-coverage, n20
    "runs/fleet_check_n30.json",
    "runs/fleet_check_n50.json",
    "runs/fleet_check_n100_prox01.json",
    # Added 2026-10-11 after the exported-tree gate (G12) found these eight numbers could not be
    # regenerated in the release: the ab-* family entries, lb-over-kdual-n100 and n50-ratio-vs-k
    # read ab_grid_provenanced.json; m7-matched-budget-n30 reads m7_score.json; wls-sensitivity
    # reads ab_wls_sweep.json. All three are OURS (not in third_party_manifest) and gitignored.
    "runs/ab_grid_provenanced.json",
    "runs/m7_score.json",
    "runs/ab_wls_sweep.json",
    # Added 2026-10-11: objective-identity-match reads the banked JOINT-verifier reproduction logs
    # for the K-proven |C|=20 cells (recomputed_obj vs K's printed optimum). Ours, gitignored.
    "runs/repro_C201_n20_tauformula_p0.0.jsonl",
    "runs/repro_C203_n20_tauformula_p0.0.jsonl",
    "runs/repro_C204_n20_tauformula_p0.0.jsonl",
    "runs/repro_C205_n20_tauformula_p0.0.jsonl",
    "runs/repro_C206_n20_tauformula_p0.0.jsonl",
    "runs/repro_C208_n20_tauformula_p0.0.jsonl",
    "runs/repro_R201_n20_tauformula_p0.0.jsonl",
    "runs/repro_R205_n20_tauformula_p0.0.jsonl",
    "runs/repro_R211_n20_tauformula_p0.0.jsonl",
    "runs/repro_RC201_n20_tauformula_p0.0.jsonl",
]


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return sorted(out.stdout.split())


def denied(rel, third_party):
    if rel in third_party:
        return "third-party (unlicensed, fetched instead)"
    if rel in DENY_EXACT:
        return "PUBLISHER COPYRIGHT"
    for g in DENY_GLOB:
        if fnmatch.fnmatch(rel, g):
            return f"working scaffolding ({g})"
    return None


def main(dest, force, do_git):
    dest = os.path.abspath(dest)
    if os.path.exists(dest):
        if not force:
            sys.exit(f"REFUSING: {dest} exists. Pass --force to replace it.")
        shutil.rmtree(dest)
    third_party = set(json.load(open(os.path.join(ROOT, "third_party_manifest.json")))["files"])

    files = tracked()
    # Gitignored artifacts the pipeline reads. Appended AFTER the tracked list so they still
    # pass through denied() -- an untracked file is not exempt from the third-party and
    # publisher checks just because it was named here.
    missing_extra = [r for r in INCLUDE_UNTRACKED if not os.path.exists(os.path.join(ROOT, r))]
    if missing_extra:
        sys.exit("REFUSING: INCLUDE_UNTRACKED names files that do not exist: "
                 + ", ".join(missing_extra)
                 + "\nThe release would ship a tree that cannot regenerate its own numbers.")
    files = sorted(set(files) | set(INCLUDE_UNTRACKED))

    copied, skipped = [], {}
    for rel in files:
        why = denied(rel, third_party)
        if why:
            skipped.setdefault(why, []).append(rel)
            continue
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    print(f"exported {len(copied)} files to {dest}")
    for why, rels in sorted(skipped.items()):
        print(f"  EXCLUDED {len(rels):3d}  {why}")
        for r in rels[:4]:
            print(f"      {r}")
        if len(rels) > 4:
            print(f"      ... and {len(rels)-4} more")

    if do_git:
        subprocess.run(["git", "init", "-q"], cwd=dest)
        subprocess.run(["git", "add", "-A"], cwd=dest)
        subprocess.run(["git", "commit", "-q", "-m",
                        "Initial release: certified lower bounds for the 2E-MVRP-SS\n\n"
                        "Generated by analysis/export_release.py from a private development "
                        "repository. No third-party code, instances or publisher content is "
                        "redistributed; see THIRD_PARTY.md."], cwd=dest)
        print("  initialised a fresh git repository (no shared history)")

    print("\n--- running the release gate against the EXPORTED tree ---")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/release_gate.py"),
                        "--tree", dest], capture_output=True, text=True)
    print(r.stdout[-2200:])
    return r.returncode


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=os.path.join(os.path.dirname(ROOT), "2emvrpss-bounds-release"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.dest, a.force, not a.no_git))
