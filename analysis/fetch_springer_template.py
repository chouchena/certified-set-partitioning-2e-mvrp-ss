"""Fetch the Springer Nature LaTeX template into paper/manuscript/, verified by sha256.

WHY THIS IS A FETCH SCRIPT AND NOT A TRACKED FILE. `sn-jnl.cls` and the `.bst` files are the
PUBLISHER'S, distributed under the LaTeX Project Public Licence. They are not ours to place in
our release tree, and `analysis/release_gate.py` G1b blocks publisher-copyright content on
exactly that principle. So we do what we already do for the predecessors' code: pin it, hash
it, fetch it on demand, and never track it.

The submission itself is a different matter -- the journal asks for "original source files
INCLUDING style files", so the class file travels WITH the manuscript to the publisher. That is
the publisher receiving their own file back, which is not redistribution.

PINNED: version 3.1, December 2024, the current template as of 2026-09-15.
"""
import os, sys, io, zipfile, hashlib, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "paper", "manuscript")

URL = ("https://cms-resources.apps.public.k8s.springernature.io/"
       "springer-cms/rest/v1/content/18782940/data/v12")
ZIP_SHA256 = "812e76dcaa9c28dc1bff1fb6065d51729b67d4ea140552a05088317414a3ecae"

# member in the zip -> (path under paper/manuscript, expected sha256)
WANT = {
    "sn-article-template/sn-jnl.cls":
        ("sn-jnl.cls", "36d0c3273a59d48dc6a9c7b080dfa1ec50dc10229d8751568d1f2e490ffa5ecc"),
    "sn-article-template/bst/sn-apacite.bst":
        ("sn-apacite.bst", "be9346857b116ec0359319ff26ace70da573475e4c92c6fb9418f841ff7a7c75"),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def patch_apacite(text):
    """Make @incollection / @inproceedings print their DOI.

    The pristine sn-apacite.bst defines doi.block and calls it for @article, but the
    @incollection path (which @inproceedings and @conference alias to) never does, so a chapter
    or a proceedings paper drops its DOI from the compiled references (referee, 2026-10-11, e.g.
    fischetti2007atsp and shaw1998lns). We insert the existing doi.block helper into incollection,
    just before format.orig.note. Applied AFTER the pristine hash is verified, so the integrity
    check still pins the publisher's original and this patch is reproducible on top of it.
    """
    if "  doi.block\n  format.orig.note" in text:
        return text                                   # already patched
    anchor = "  if$\n  format.orig.note\n  fin.entry\n}\n\nFUNCTION {inbookcollection}"
    if anchor not in text:
        raise SystemExit("  !! cannot patch sn-apacite.bst: incollection anchor not found "
                         "(the template changed; re-pin and re-derive the patch)")
    return text.replace(anchor, "  if$\n  doi.block\n  format.orig.note\n  fin.entry\n}"
                                "\n\nFUNCTION {inbookcollection}", 1)


def main():
    missing = [d for _, (d, _) in WANT.items() if not os.path.exists(os.path.join(DEST, d))]
    if not missing and "--force" not in sys.argv:
        print("  template already present; pass --force to refetch")
        return 0

    print(f"  fetching {URL}")
    blob = urllib.request.urlopen(URL, timeout=120).read()
    got = sha(blob)
    if got != ZIP_SHA256:
        # A CHANGED HASH IS NOT A FAILURE TO ROUTE AROUND. Springer reissues the template
        # without changing the URL, and a silently newer class file means the PDF we checked
        # is not the PDF the next person builds. Someone re-pins it deliberately.
        print(f"  !! zip sha256 MISMATCH\n     expected {ZIP_SHA256}\n     got      {got}")
        print("     The publisher has reissued the template. Re-pin DELIBERATELY: verify the "
              "class version, rebuild the manuscript, and check the PDF before updating "
              "ZIP_SHA256 here.")
        return 1

    os.makedirs(DEST, exist_ok=True)
    z = zipfile.ZipFile(io.BytesIO(blob))
    for member, (dest, want) in WANT.items():
        data = z.read(member)
        if sha(data) != want:
            print(f"  !! {member} sha256 mismatch inside a matching zip -- refusing")
            return 1
        note = ""
        if dest == "sn-apacite.bst":
            data = patch_apacite(data.decode("utf-8")).encode("utf-8")
            note = "  (pristine sha256 ok; DOI-rendering patch applied, see patch_apacite)"
        open(os.path.join(DEST, dest), "wb").write(data)
        print(f"  wrote paper/manuscript/{dest}  ({len(data)} bytes, sha256 ok){note}")
    print("  NOTE: `apacite` itself comes from your TeX distribution, not from this zip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
