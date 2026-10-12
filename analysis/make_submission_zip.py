r"""Build the numbered submission zip -- the same curated layout as the previous package, plus the
one genuinely-missing part (third_party_manifest.json), and a RELEASE NUMBER in the filename so the
new package does not overwrite the previous one.

Layout mirrors the repository so the validation scripts run from the zip root as written. None of the
predecessors' bytes are included: the 35 third-party files are fetched by fetch_karademir.py and
verified against third_party_manifest.json (which ships -- 35 hashes, not their content).

    python analysis/make_submission_zip.py            # -> 2E-MVRP-SS_submission_v2_YYYYMMDD.zip
    python analysis/make_submission_zip.py --rel v3   # choose the release token
"""
import argparse
import datetime
import glob
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rel", default="v2", help="release token embedded in the filename")
    a = ap.parse_args()

    stage = os.path.join(ROOT, "_pkg_%s" % a.rel)
    if os.path.exists(stage):
        shutil.rmtree(stage)

    def put(srcrel, dstrel=None):
        src = os.path.join(ROOT, srcrel)
        dst = os.path.join(stage, dstrel or srcrel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            print("  [warn] missing:", srcrel)

    # root-level modules the code imports + the third-party HASH manifest (NOT their bytes)
    for f in ("build_instance.py", "instance_view.py", "fetch_karademir.py",
              "third_party_manifest.json"):
        put(f)
    put("SUBMISSION_README.md", "README.md")
    put("paper/COVER_LETTER.md", "cover_letter.md")

    # code (exclude caches)
    ncode = 0
    for mod in ("analysis", "crossfeed"):
        for py in glob.glob(os.path.join(ROOT, mod, "*.py")):
            put(os.path.relpath(py, ROOT)); ncode += 1

    # data + paper sources
    put("data/karademir2025/k_reference.json")
    for f in ("numbers.json", "numbers.tex", "references.bib"):
        put("paper/" + f)
    for f in ("main5.pdf", "main5.md", "main5.tex", "main5.bbl", "sn-jnl.cls", "sn-apacite.bst"):
        put("paper/manuscript/submission/" + f)

    # only the FOUR referenced figures (not the whole figures dir)
    FIGS = ("lb_ov_vs_k_by_size", "band_family_n100", "optgap_vs_k_by_size", "ablation_primal_leg")
    nfig = 0
    for stem in FIGS:
        for ext in (".pdf", ".png"):
            src = "paper/figures/%s%s" % (stem, ext)
            if os.path.exists(os.path.join(ROOT, src)):
                put(src, "paper/manuscript/figures/%s%s" % (stem, ext)); nfig += 1

    # validation: CURATED submission set only (not the dev-history *.md)
    VAL = ("VALIDATION_REPORT.md", "EQ_TO_CODE.md", "ADVERSE_REVIEW.md",
           "AREA2_FLOOR_MAPPING.md", "AREA4_FLOOR_RELAXATION.md", "AREA4_PRICING_AUDIT.md",
           "AREA4_FASTPRICER_AUDIT.md", "AREA5_CERTIFICATE_AUDIT.md", "AREA6_INCUMBENT_REVERIFY.md",
           "AREA7_ARITHMETIC_BOUND.md", "incumbent_manifest.json", "certificate_records.json",
           "DECISIONS.jsonl")
    for f in VAL:
        put("validation/" + f)

    # artifacts: frzdual2 certificates + the pu_ng REPORTED incumbents named in the manifest
    ncert = 0
    for j in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_*_n*.json")):
        put(os.path.relpath(j, ROOT)); ncert += 1
    man = json.load(open(os.path.join(ROOT, "validation", "incumbent_manifest.json")))
    ninc = 0
    for c in man["cells"]:
        p = os.path.join("runs", "oracle", c["source"])
        if os.path.exists(os.path.join(ROOT, p)):
            put(p); ninc += 1

    stamp = datetime.date.today().strftime("%Y%m%d")
    base = os.path.join(ROOT, "2E-MVRP-SS_submission_%s_%s" % (a.rel, stamp))
    zippath = shutil.make_archive(base, "zip", stage)
    mb = os.path.getsize(zippath) / 1e6
    shutil.rmtree(stage)
    print("wrote %s" % os.path.relpath(zippath, ROOT))
    print("  %.1f MB | %d code | %d figs | %d validation | %d frzdual2 | %d incumbents | manifest: yes"
          % (mb, ncode, nfig, len(VAL), ncert, ninc))


if __name__ == "__main__":
    main()
