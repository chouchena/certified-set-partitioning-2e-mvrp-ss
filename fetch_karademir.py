"""
Fetch the Karademir et al. (2025) artifact that this work depends on.

WHY THIS EXISTS. Their repository declares no licence, so we hold no right to redistribute it.
This replication package therefore ships **none of their bytes** — it ships their commit id and
a SHA-256 for every file we used, and this script fetches the originals from source and verifies
them. The hashes prove which version produced our results without redistributing anything.

    python fetch_karademir.py            # fetch + verify into the repo root
    python fetch_karademir.py --verify   # verify what is already present, fetch nothing

Their code is a HARD DEPENDENCY, not an optional extra: `build_instance.py` imports
`instanceGenerator`, so every lower bound and every primal incumbent in this work flows through
their generator. Nothing here runs without it.

Karademir, C., Atasoy, B., van Duin, J.H.R., Negenborn, R.R. (2025). A two-echelon multi-trip
vehicle routing problem with synchronization for an integrated water- and land-based
transportation system. European Journal of Operational Research 322(2), 480-499.
https://doi.org/10.1016/j.ejor.2024.10.047
"""
import argparse, hashlib, io, json, os, sys, urllib.request, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "cigdemkarademir/2echelon-synchronization"
# Pinned. Their repository carries no tags or releases, so a commit id is the only stable handle.
COMMIT = "ebec1b5cd0754c8ec8dcdaafd821882c8485dbc9"   # 2024-11-14, "Update README.md"
MANIFEST = os.path.join(ROOT, "third_party_manifest.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest():
    if not os.path.exists(MANIFEST):
        sys.exit(f"{MANIFEST} missing — run --build-manifest while the files are present")
    return json.load(open(MANIFEST, encoding="utf-8"))


def build_manifest(files):
    """Record what we USED, from the copies that produced our results."""
    man = {"source": f"https://github.com/{REPO}", "commit": COMMIT,
           "citation": "Karademir et al. (2025) EJOR 322(2) 480-499, "
                       "doi:10.1016/j.ejor.2024.10.047",
           "licence": "NONE DECLARED by the authors; not redistributed here",
           "files": {}}
    missing = []
    for rel in files:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            man["files"][rel] = {"sha256": sha256(p), "bytes": os.path.getsize(p)}
        else:
            missing.append(rel)
    json.dump(man, open(MANIFEST, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(f"manifest: {len(man['files'])} files recorded -> {os.path.relpath(MANIFEST, ROOT)}")
    if missing:
        print(f"  NOT PRESENT, not recorded: {missing}")
    return man


def verify(man, quiet=False):
    ok = bad = absent = 0
    for rel, meta in sorted(man["files"].items()):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            absent += 1
            if not quiet:
                print(f"  ABSENT   {rel}")
            continue
        if sha256(p) == meta["sha256"]:
            ok += 1
        else:
            bad += 1
            print(f"  MISMATCH {rel}  (expected {meta['sha256'][:16]}...)")
    print(f"verify: {ok} match, {bad} mismatch, {absent} absent, of {len(man['files'])}")
    return bad == 0 and absent == 0


def fetch(man):
    url = f"https://github.com/{REPO}/archive/{COMMIT}.zip"
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    prefix = zf.namelist()[0].split("/")[0] + "/"
    n = 0
    for rel in man["files"]:
        member = prefix + rel
        try:
            blob = zf.read(member)
        except KeyError:
            print(f"  NOT IN ARCHIVE: {rel}")
            continue
        dest = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(dest) or ROOT, exist_ok=True)
        open(dest, "wb").write(blob)
        n += 1
    print(f"wrote {n} files at commit {COMMIT[:12]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="verify only, fetch nothing")
    ap.add_argument("--build-manifest", action="store_true",
                    help="record hashes from the copies currently present (maintainer use)")
    a = ap.parse_args()

    theirs = ["integratedJointModel.py", "LBBDmodel.py", "DecomposedModels.py", "Solve.py",
              "solveJoint.py", "SEVs.py", "solution.py", "instanceGenerator.py"]
    theirs += [f"data/json/{c}.json" for c in
               [f"C2{i:02d}" for i in range(1, 9)] + [f"R2{i:02d}" for i in range(1, 12)]
               + [f"RC2{i:02d}" for i in range(1, 9)]]

    if a.build_manifest:
        build_manifest(theirs)
        return 0
    man = load_manifest()
    print(f"Karademir et al. artifact, commit {man['commit'][:12]} — "
          f"{len(man['files'])} files, licence: {man['licence']}")
    if not a.verify:
        fetch(man)
    good = verify(man)
    if good:
        print("\nOK — the files present are byte-identical to those that produced our results.")
    else:
        print("\nFAILED. Do not run the pipeline: the dependency does not match what we used.")
    return 0 if good else 2


if __name__ == "__main__":
    sys.exit(main())
