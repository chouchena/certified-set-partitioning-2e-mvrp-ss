"""Freeze the run artifacts that BACK PUBLISHED NUMBERS into a committed snapshot.

THE PROBLEM. `.gitignore` excludes `runs/*` and `results/`, so 227 solution files, 172
portfolio files and `summary.csv` -- the evidence for every primal claim, including the
7/7 objective-identity table -- are untracked. A code release that cannot reproduce its own
tables is not a release.

WHY NOT JUST UNIGNORE `runs/`. The ignore is deliberate and correct: `analysis/provenance.py`
stamps `git_dirty`, and if live run outputs were tracked then every new run would dirty the
tree and contaminate the provenance of the NEXT run. The stamp must track CODE state, not
data churn.

THE FIX. A frozen SNAPSHOT on a separate, non-ignored path. `runs/` stays ignored and keeps
churning; `published_artifacts/` holds exactly what the manuscript cites, with a sha256
manifest so a replicator can verify the snapshot against a re-run.

Selection rule, deliberately narrow: the two run ledgers, plus the single BEST-objective
solution file per (cell, size) across both stores -- the incumbent every quoted number refers to.
Not all 399 files; only the evidence.
"""
import os, sys, re, json, glob, hashlib, shutil
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "published_artifacts")
STORES = [("runs/solutions", r"fixopt_([A-Za-z0-9]+)_n(\d+)_"),
          ("results/portfolio", r"([A-Za-z0-9]+)_n(\d+)_"),
          # 2026-10-01: the stores where current incumbents actually live. The original two scanned
          # only runs/solutions/fixopt_* and results/portfolio, so once the stale snapshot that had
          # masked G8 was rebuilt, 50 ledger incumbents at n30/n40/n50/n100 showed as unbacked GAPS
          # even though their solution is banked -- as ownwater (postpass, the same file
          # best_known.best_solution reads) or as ip_primal / banked (oracle). Scanned recursively
          # for the postpass stage subdirs; superseded/ and invalid/ are skipped in the loop so a
          # retired artifact can never back a quoted number.
          ("runs/postpass", r"ownwater_([A-Za-z0-9]+)_n(\d+)\.json"),
          ("runs/oracle", r"tep_cg_bound_([A-Za-z0-9]+)_n(\d+)_ip_primal\.json"),
          ("runs/oracle", r"tep_cg_banked_([A-Za-z0-9]+)_n(\d+)\.json")]
LEDGERS = ["runs/summary.csv", "runs/ledger.csv", "runs/provenance.csv", "runs/RUN_MANIFEST.json"]

# TEP TWO-LEG EVIDENCE (2026-10-09). The STORES/summary.csv model above backs the superseded
# restriction/primal corpus; it cannot see the TEP artifacts, whose incumbents live in `ov`/`lb`
# (not `objVal`) and are not recorded in summary.csv. The current manuscript (every §6 number,
# figure and table) reads these instead, so the snapshot must carry them verbatim to reproduce:
#   * the consolidated grids tep_uniform_n*.json -- the single-accessor source manuscript_numbers
#     ._cons reads for every reported number;
#   * the per-cell pu_ng* artifacts recap_grid_vs_k.our_union globs for the figures and that
#     tab_budget_sensitivity re-slices (the ng10 story) for the budget table;
#   * the per-cell frzdual2 artifacts behind the dual-derived incumbents (R204/R208 at n100) and
#     the bound-leg walls.
# Copied whole (not best-per-cell) because the union is computed ACROSS a cell's ng runs, so a
# replicator needs each one present; superseded/ and invalid/ are skipped as everywhere here.
TEP_GLOBS = ["runs/oracle/tep_uniform_n*.json",
             "runs/oracle/tep_solve_pu_ng*_n*.json",
             "runs/oracle/tep_solve_frzdual2_*_n*.json"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 16), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    os.makedirs(os.path.join(OUT, "solutions"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "ledgers"), exist_ok=True)
    manifest = {"purpose": "artifacts backing published numbers; runs/ stays gitignored so "
                           "live churn does not dirty the provenance stamp",
                "ledgers": {}, "solutions": {}}

    for rel in LEDGERS:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            print(f"  MISSING ledger {rel}"); continue
        dst = os.path.join(OUT, "ledgers", os.path.basename(rel))
        shutil.copy2(src, dst)
        manifest["ledgers"][os.path.basename(rel)] = {
            "source": rel, "sha256": sha256(dst), "bytes": os.path.getsize(dst)}
        print(f"  ledger  {rel}")

    best = {}
    for root, pat in STORES:
        for f in glob.glob(os.path.join(ROOT, root, "**", "*.json"), recursive=True):
            rel = f.replace("\\", "/")
            if "/superseded/" in rel or "/invalid/" in rel:
                continue          # a retired artifact must never back a quoted number
            m = re.match(pat, os.path.basename(f))
            if not m:
                continue
            cell, size = m.group(1), int(m.group(2))
            try:
                d = json.load(open(f))
            except Exception:
                continue
            o = d.get("objVal")
            if o is None:
                continue
            key = (cell, size)
            if key not in best or o < best[key][0]:
                best[key] = (o, f)

    for (cell, size), (o, f) in sorted(best.items()):
        dst = os.path.join(OUT, "solutions", f"best_{cell}_n{size}.json")
        shutil.copy2(f, dst)
        manifest["solutions"][f"{cell}_n{size}"] = {
            "objVal": o, "source": os.path.relpath(f, ROOT).replace("\\", "/"),
            "sha256": sha256(dst)}
    print(f"  {len(best)} best-incumbent solution files")

    # TEP evidence: copy each matched artifact whole into tep/, recording its sha256. This is what
    # backs the current manuscript; the primal-era gaps logic below governs the superseded corpus.
    os.makedirs(os.path.join(OUT, "tep"), exist_ok=True)
    manifest["tep_evidence"] = {}
    tep_bytes = 0
    for pat in TEP_GLOBS:
        for f in sorted(glob.glob(os.path.join(ROOT, pat))):
            rel = f.replace("\\", "/")
            if "/superseded/" in rel or "/invalid/" in rel:
                continue
            base = os.path.basename(f)
            dst = os.path.join(OUT, "tep", base)
            shutil.copy2(f, dst)
            manifest["tep_evidence"][base] = {
                "source": os.path.relpath(f, ROOT).replace("\\", "/"),
                "sha256": sha256(dst), "bytes": os.path.getsize(dst)}
            tep_bytes += os.path.getsize(dst)
    print(f"  {len(manifest['tep_evidence'])} TEP evidence files ({tep_bytes/1048576:.1f} MB): "
          f"consolidated grids + per-cell pu_ng/frzdual2 for every §6 number, figure and table")

    # GAPS. A snapshot that silently omits evidence is worse than no snapshot. Any cell whose
    # best VERIFIED incumbent in the ledger has no corresponding solution file is recorded here
    # by name, so the manuscript cannot cite it as artifact-backed when it is only ledger-backed.
    import csv
    ledger_best = {}
    sc = os.path.join(ROOT, "runs/summary.csv")
    PRIMAL = {"fixopt", "joint_milp_cplex", "joint_milp_gurobi", "lbbd"}
    if os.path.exists(sc):
        for r in csv.DictReader(open(sc)):
            if r.get("engine") not in PRIMAL:
                continue
            if r.get("verified", "").lower() != "true" or r.get("quarantined", "").lower() == "true":
                continue
            try:
                v = float(r["final_incumbent"])
            except Exception:
                continue
            key = f"{r['instance']}_n{r['size']}"
            if key not in ledger_best or v < ledger_best[key]:
                ledger_best[key] = v
    # RETIRED INCUMBENTS. These five ledger rows record a better value than any stored solution,
    # and the re-dump that would have reproduced them FAILED -- R203_n20 at 0/1, RC208_n20 at 0/2,
    # the three n30 cells at 0/1 each (logs/redump_R1/results.json).
    #
    # PREREG_R1_incumbent_redump.md section 5 row 3 registered the rule BEFORE those results
    # existed: "report the reproducible value, retire the unreproducible one." The same section
    # anticipated this exact moment -- "after seeing a worse result there is an obvious temptation
    # to keep quoting the better recorded number on the grounds that 'it was really achieved
    # once'. That is exactly the practice this register exists to prevent."
    #
    # So they are RETIRED, not repaired and not hidden: the manifest records each one with both
    # values and the reason, and `gaps` is what remains genuinely unexplained. A gate that fails
    # on a number the project has already decided not to quote is a gate that gets silenced by
    # habit; one that distinguishes "unexplained" from "deliberately retired" keeps its teeth.
    #
    # NONE OF THE FIVE BACKS A MANUSCRIPT SENTENCE, verified 2026-09-16:
    #   RC208_n20  682.923 already retired by DECISION_rc208_one_car_outlier_disclosure.md sec 6;
    #              the footnote quotes the CERTIFIED 693.868, i.e. the weaker number.
    #   R203_n20   639.087 is an LBBD-sourced best; K publish 638.4, so the cell is a loss either
    #              way and no claim rests on which of ours is quoted.
    #   R211_n30, RC204_n30, RC208_n30  unquotable under `primal-coverage-scoped-to-n20`, whose
    #              falsifier forbids any primal claim at a size where fewer than 27 cells ran.
    #              n30 primal coverage is 5 of 27.
    # 2026-10-01 EXPANSION. Rebuilding the snapshot (G8 had been failing on staleness, which
    # short-circuited the gap check) surfaced 13 further ledger-only incumbents, ALL at non-quoted
    # sizes. Each is the SAME case PREREG_R1 section 5 row 3 governs -- the summary.csv primal
    # (fixopt/MILP) records a value with no banked solution artifact that reproduces it -- and each
    # is at a size the manuscript does not quote per cell, so none backs a sentence:
    #   * n40 (C201, R201, RC201): n40 is internal-paired-comparison only (AMBIGUITY_REGISTER A10);
    #     no per-cell primal is quoted at this size. Ledger-backed only, no artifact, not re-dumped.
    #   * n30 (C201, C202, C203, R201, R207, RC201, RC203) and n50 (C201, RC201, RC205): per-cell
    #     primal is unquotable under `primal-coverage-scoped-to-n20` (n30 coverage is 5 of 27). The
    #     summary.csv incumbent beats any banked solution and was NOT re-dumped, so the reproducible
    #     value is reported and this one is retired -- not repaired, not hidden.
    _UNQUOTABLE_N30 = "unreproducible summary.csv primal; n30 per-cell primal unquotable (primal-coverage-scoped-to-n20, coverage 5/27); not re-dumped"
    _UNQUOTABLE_N50 = "unreproducible summary.csv primal; n50 per-cell primal unquotable (primal-coverage-scoped-to-n20); not re-dumped"
    _UNQUOTABLE_N40 = "n40 is internal-paired-comparison only (AMBIGUITY_REGISTER A10); no per-cell primal quoted at n40; ledger-backed only, no artifact, not re-dumped"
    RETIRED = {
        "R203_n20":  "re-dump 0/1; LBBD-sourced best, K publish 638.4 -- cell is a loss either way",
        "R211_n30":  "re-dump 0/1; n30 primal is 5 of 27 cells, unquotable per primal-coverage-scoped-to-n20",
        "RC204_n30": "re-dump 0/1; n30 primal is 5 of 27 cells, unquotable per primal-coverage-scoped-to-n20",
        "RC208_n20": "re-dump 0/2; already retired in favour of the certified 693.868",
        "RC208_n30": "re-dump 0/1; n30 primal is 5 of 27 cells, unquotable per primal-coverage-scoped-to-n20",
        "C201_n30": _UNQUOTABLE_N30, "C202_n30": _UNQUOTABLE_N30, "C203_n30": _UNQUOTABLE_N30,
        "R201_n30": _UNQUOTABLE_N30, "R207_n30": _UNQUOTABLE_N30, "RC201_n30": _UNQUOTABLE_N30,
        "RC203_n30": _UNQUOTABLE_N30,
        "C201_n50": _UNQUOTABLE_N50, "RC201_n50": _UNQUOTABLE_N50, "RC205_n50": _UNQUOTABLE_N50,
        "C201_n40": _UNQUOTABLE_N40, "R201_n40": _UNQUOTABLE_N40, "RC201_n40": _UNQUOTABLE_N40,
    }
    gaps, retired = {}, {}
    for key, v in sorted(ledger_best.items()):
        sol = manifest["solutions"].get(key)
        if key in RETIRED and (sol is None or sol["objVal"] > v + 0.01):
            retired[key] = {"ledger_incumbent": v,
                            "snapshot_objVal": (sol or {}).get("objVal"),
                            "retired_because": RETIRED[key],
                            "rule": "PREREG_R1_incumbent_redump.md section 5 row 3"}
            continue
        if sol is None:
            gaps[key] = {"ledger_incumbent": v, "issue": "NO stored solution file; ledger-backed only"}
        elif sol["objVal"] > v + 0.01:
            # NOTE the 0.01 tolerance. summary.csv stores final_incumbent ROUNDED, so a strict
            # comparison flags ~14 cells whose entire "gap" is <=0.005 of CSV rounding -- e.g.
            # C201_n20, ledger 697.69 vs solution 697.695. Only differences ABOVE the rounding
            # resolution are real.
            gaps[key] = {"ledger_incumbent": v, "snapshot_objVal": sol["objVal"],
                         "issue": "ledger reports a BETTER incumbent than any stored solution"}
    manifest["gaps"] = gaps
    manifest["retired"] = retired
    print(f"  GAPS: {len(gaps)} cells whose best verified incumbent is not artifact-backed")
    for k in list(gaps)[:12]:
        print(f"     {k}: {gaps[k]['issue']}")
    print(f"  RETIRED: {len(retired)} ledger incumbents deliberately not quoted "
          f"(PREREG_R1 section 5). These are reported, not hidden:")
    for k, r in sorted(retired.items()):
        print(f"     {k}: ledger {r['ledger_incumbent']} vs stored {r['snapshot_objVal']} "
              f"-- {r['retired_because']}")
    missing = sorted(set(RETIRED) - set(retired))
    if missing:
        # A retirement that no longer applies must not sit in the list unnoticed: if a cell stops
        # being a gap (a later re-dump succeeds), its entry here is stale and should be removed.
        print(f"  NOTE: {len(missing)} retirement(s) no longer needed and should be deleted "
              f"from RETIRED: {', '.join(missing)}")

    json.dump(stamped(manifest, __file__), open(os.path.join(OUT, "MANIFEST.json"), "w"), indent=1, sort_keys=True)
    print(f"wrote {OUT}/MANIFEST.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
