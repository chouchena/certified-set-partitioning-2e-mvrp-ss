"""RELEASE GATE — executable preconditions for publishing the replication package.

WHY THIS IS A SCRIPT AND NOT A CHECKLIST. This project has walked past its own written checks
more than once: the claims gate accepted "NOT RUN" prose as a run; `k_cap` silently contradicted
`k_hi` for ten cells; `build()` defaulted to `tau="code"` while `InstanceSpec` defaulted to
`tau="formula"`. Each was written down somewhere. None was caught by reading. A release
precondition that is not executable is not a precondition.

"Zero flaws guaranteed" is not achievable and is not claimed. What IS achievable is that every
KNOWN failure mode fails a command. This file encodes those; anything it does not check is
explicitly out of scope and listed at the bottom, so the boundary is visible rather than implied.

Run:  python analysis/release_gate.py [--tree .]
Exit: 0 if every BLOCKING check passes, 1 otherwise.
"""
import os, sys, json, glob, hashlib, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = []


def check(name, blocking, ok, detail=""):
    RESULTS.append(dict(name=name, blocking=blocking, ok=bool(ok), detail=detail))
    return ok


def tracked_files(tree):
    out = subprocess.run(["git", "ls-files"], cwd=tree, capture_output=True, text=True)
    return set(out.stdout.split())


def load(p):
    """Read a json artifact or return None. The new TEP-era checks all read artifacts."""
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 16), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------- G1 redistribution
def g1_no_third_party_tracked(tree):
    """THE one that matters. Publishing a tree that tracks their unlicensed files redistributes
    them -- the highest-ranked risk in paper/LICENCE_AUDIT_AND_PLAN.md, and the one that makes a
    continuation paper read as having taken rather than continued."""
    mf = os.path.join(tree, "third_party_manifest.json")
    if not os.path.exists(mf):
        return check("G1 no third-party file tracked", True, False, "third_party_manifest.json missing")
    theirs = set(json.load(open(mf))["files"])
    bad = sorted(theirs & tracked_files(tree))
    return check("G1 no third-party file tracked", True, not bad,
                 f"{len(bad)} of {len(theirs)} third-party files are TRACKED"
                 + (f" (e.g. {', '.join(bad[:4])})" if bad else ""))


# ------------------------------------------------- G1b unmanifested third-party content
def g1b_no_unmanifested_thirdparty(tree):
    """The manifest covers their GITHUB files. It does NOT cover their PUBLISHED PAPER.

    `paper/karademir2025-EJOR.pdf` is a copyrighted Elsevier article and
    `paper/karademir2025-fulltext-layout.txt` is its extracted text. Redistributing a
    publisher PDF is a clearer problem than redistributing unlicensed code, and the
    manifest-based G1 check misses it completely -- found 2026-09-15 while building the
    exporter. Keeping a personal copy to read is ordinary; shipping it is not.
    """
    patterns = ("karademir2025-EJOR.pdf", "karademir2025-fulltext-layout.txt")
    tracked = tracked_files(tree)
    bad = sorted(f for f in tracked if any(pat in f for pat in patterns))
    # any other PDF under paper/ is at least worth a look
    other = sorted(f for f in tracked
                   if f.lower().endswith(".pdf") and f not in bad)
    detail = (f"{len(bad)} publisher-copyright file(s) tracked: {', '.join(bad)}" if bad
              else ("ok" + (f" (other PDFs present, check provenance: {', '.join(other)})" if other else "")))
    return check("G1b no publisher-copyright content tracked", True, not bad, detail)


# ---------------------------------------------------------------- G2 our own front page
def g2_readme_is_ours(tree):
    p = os.path.join(tree, "README.md")
    if not os.path.exists(p):
        return check("G2 README is ours", True, False, "README.md missing")
    txt = open(p, encoding="utf-8", errors="replace").read()
    # Their README's identifying marks. If these dominate, the front page is describing their paper.
    theirs = ("2echelon-synchronization" in txt
              or "These models are discussed in the following paper" in txt)
    return check("G2 README is ours", True, not theirs,
                 "README is the PREDECESSORS' (inherited at the root commit)" if theirs else "ok")


# ---------------------------------------------------------------- G3-G5 required files
def g3_required_files(tree):
    req = {"LICENSE": True, "THIRD_PARTY.md": True, "CITATION.cff": False,
           "fetch_karademir.py": True, "third_party_manifest.json": True}
    missing_block = [f for f, b in req.items() if b and not os.path.exists(os.path.join(tree, f))]
    missing_warn = [f for f, b in req.items() if not b and not os.path.exists(os.path.join(tree, f))]
    check("G3 required files present", True, not missing_block,
          f"missing: {', '.join(missing_block)}" if missing_block else "ok")
    check("G3b recommended files present", False, not missing_warn,
          f"missing: {', '.join(missing_warn)}" if missing_warn else "ok")
    return not missing_block


# ---------------------------------------------------------------- G4 dependency pinning
def g4_pinned_env(tree):
    have = any(os.path.exists(os.path.join(tree, f))
               for f in ("requirements.txt", "environment.yml", "pyproject.toml"))
    return check("G4 dependencies pinned", True, have,
                 "no requirements.txt / environment.yml / pyproject.toml" if not have else "ok")


# ---------------------------------------------------------------- G5 solver version recorded
def g5_solver_version_recorded():
    """A bound that cannot say which solver produced it is not reproducible. We do not vendor
    CPLEX; we must record its version, and the artifacts already do."""
    fs = glob.glob(os.path.join(ROOT, "crossfeed/easy_reduction_descend_*_n20.json"))
    fs = [f for f in fs if not any(x in f for x in ("noprov", "kcapbug", "tl450", "detl"))]
    missing = []
    for f in fs:
        try:
            r = json.load(open(f))
        except Exception:
            continue
        if not r or not r[0].get("cplex"):
            missing.append(os.path.basename(f))
    # SUPERSEDED-ERA SCOPE (2026-09-28 audit): the retained-set corpus the manuscript no longer
    # cites; the TEP legs run Gurobi and record its version through stamp(). Kept because it is
    # free, demoted because it cannot block a release of a paper it does not describe.
    return check("G5 solver version in every n20 artifact (superseded era)", False, not missing,
                 f"{len(missing)} artifacts lack a cplex version" if missing else
                 f"all {len(fs)} carry it")


# ---------------------------------------------------------------- G6 provenance completeness
def g6_provenance_complete():
    need = ("code_hash", "git_sha", "seed", "det_tl", "threads", "python")
    fs = glob.glob(os.path.join(ROOT, "crossfeed/easy_reduction_descend_*_n20.json"))
    fs = [f for f in fs if not any(x in f for x in ("noprov", "kcapbug", "tl450", "detl"))]
    bad, dirty = [], []
    for f in fs:
        try:
            r = json.load(open(f))
        except Exception:
            continue
        if not r:
            continue
        k = r[0]
        if any(k.get(n) in (None, "") for n in need):
            bad.append(os.path.basename(f))
        if k.get("git_dirty"):
            dirty.append(os.path.basename(f))
    # EXTENDED TO THE CURRENT CORPUS (2026-09-28 audit). The n20 crossfeed artifacts are the
    # superseded retained-set era; what must carry provenance now is every artifact the manuscript
    # reads. stamped() writes _provenance.code_hash on all of them, and one without it cannot be
    # reproduced. Before this, no blocking check read a single TEP artifact.
    tep = sorted(glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_*.json")))
    def _stamped(f):
        d = load(f)
        if isinstance(d, list):          # a few artifacts are arrays of records; the stamp rides on each
            d = d[0] if d and isinstance(d[0], dict) else {}
        return bool(((d or {}).get("_provenance") or {}).get("code_hash") or (d or {}).get("code_hash"))
    tep_bad = [os.path.basename(f) for f in tep if not _stamped(f)]
    check("G6 full provenance on every n20 artifact", True, not bad,
          f"{len(bad)} incomplete" if bad else f"all {len(fs)} complete")
    check("G6c full provenance on every TEP artifact", True, not tep_bad,
          ("%d of %d without code_hash: %s" % (len(tep_bad), len(tep), ", ".join(tep_bad[:4]))) if tep_bad
          else "all %d TEP artifacts carry code_hash" % len(tep))
    # git_dirty is a WARNING not a blocker: a dirty tree at run time does not invalidate the
    # number, it only means the commit hash alone does not reconstruct the code state.
    return check("G6b artifacts produced from a clean tree", False, not dirty,
                 f"{len(dirty)} artifacts have git_dirty=true" if dirty else "ok")


# ---------------------------------------------------------------- G7 one commit per campaign
def g7_campaign_code_invariant():
    """Did the CODE change mid-campaign? Commit count is a proxy; code_hash is the answer.

    This check used to count distinct `git_sha` per campaign and warn whenever a campaign
    spanned more than one -- n30 five, n50 six, n100 twelve. That is a false alarm by
    construction: a campaign running for hours will span every commit made meanwhile,
    including ones touching only documentation, and none of that can affect a bound.

    The real question is whether the loaded module bytes changed, and `code_hash` answers it
    exactly. Measured 2026-09-15: n30, n50 and n100 each carry a SINGLE code_hash (dcdc9666)
    across their 5, 6 and 12 commits. The code was invariant; only the repository moved.

    So the check now tests the thing it cares about, and the commit spread is reported as
    context rather than as a finding. Blocking, because a campaign whose code genuinely
    changed halfway through is a real defect -- the old proxy could never say which it was.
    """
    import collections
    bad, ctx = [], []
    for size in (10, 20, 30, 50, 100):
        hashes, shas = collections.Counter(), set()
        for f in glob.glob(os.path.join(ROOT, f"crossfeed/easy_reduction_descend_*_n{size}.json")):
            if any(x in f for x in ("noprov", "kcapbug", "tl450", "detl")):
                continue
            try:
                r = json.load(open(f))
            except Exception:
                continue
            if not r:
                continue
            if r[0].get("code_hash"):
                hashes[str(r[0]["code_hash"])[:8]] += 1
            if r[0].get("git_sha"):
                shas.add(r[0]["git_sha"][:8])
        if not hashes:
            continue
        if len(hashes) > 1:
            bad.append(f"n{size}: {len(hashes)} distinct code_hash "
                       f"({', '.join(sorted(hashes))}) -- the code CHANGED mid-campaign")
        elif len(shas) > 1:
            ctx.append(f"n{size} spans {len(shas)} commits at one code_hash "
                       f"{next(iter(hashes))}")
    # SUPERSEDED-ERA SCOPE (2026-09-28 audit): same corpus as G5, same demotion, same reason.
    return check("G7 code invariant within each campaign (superseded era)", False, not bad,
                 "; ".join(bad) if bad else
                 ("ok" + (f" ({'; '.join(ctx)})" if ctx else "")))


# ---------------------------------------------------------------- G8 artifact backing
def g8_no_unbacked_numbers():
    p = os.path.join(ROOT, "published_artifacts/MANIFEST.json")
    if not os.path.exists(p):
        return check("G8 every quoted incumbent artifact-backed", True, False, "snapshot not built")
    gaps = json.load(open(p)).get("gaps", {})
    # A SNAPSHOT OLDER THAN THE EVIDENCE PROVES NOTHING (2026-09-28 audit). On the day of the audit
    # this manifest was twelve days old and covered 60 solutions at |C| = 10 and 20, so an empty
    # `gaps` said nothing about the 135 incumbents the paper reports, nor about the 26 harvested
    # that night. Emptiness means something only if the snapshot is newer than what it covers.
    newest = 0.0
    for sub in ("runs/postpass", "runs/oracle"):
        for f in glob.glob(os.path.join(ROOT, sub, "**", "*.json"), recursive=True):
            newest = max(newest, os.path.getmtime(f))
    if newest > os.path.getmtime(p):
        return check("G8 every quoted incumbent artifact-backed", True, False,
                     "snapshot is OLDER than the newest artifact it should cover -- rebuild it")
    return check("G8 every quoted incumbent artifact-backed", True, not gaps,
                 f"{len(gaps)} ledger-only incumbents: {', '.join(sorted(gaps)[:6])}"
                 if gaps else "ok")


# ---------------------------------------------------------------- G9 third-party integrity
def g9_third_party_hashes(tree):
    mf = os.path.join(tree, "third_party_manifest.json")
    if not os.path.exists(mf):
        return check("G9 third-party hashes match", True, False, "manifest missing")
    m = json.load(open(mf))["files"]
    bad, absent = [], 0
    for rel, meta in m.items():
        p = os.path.join(tree, rel)
        if not os.path.exists(p):
            absent += 1
            continue
        if sha256(p) != meta["sha256"]:
            bad.append(rel)
    return check("G9 third-party hashes match", True, not bad,
                 f"{len(bad)} MODIFIED third-party files" if bad
                 else f"{len(m)-absent} present and unmodified, {absent} absent (fetched on demand)")


# ------------------------------------------------- G11/G12 manuscript-quantity provenance
def g11_figures_have_provenance(tree):
    """A figure or table that cannot say which code and which artifacts produced it is not
    reproducible, and a reader cannot tell whether it still matches the text beside it."""
    missing, total = [], 0
    for sub, ext in (("figures", ".pdf"), ("tables", ".tex")):
        d = os.path.join(tree, "paper", sub)
        if not os.path.isdir(d):
            continue
        stems = {os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(ext)}
        total += len(stems)
        missing += [f"{sub}/{s}" for s in sorted(stems)
                    if not os.path.exists(os.path.join(d, s + ".prov.json"))]
    return check("G11 every figure/table has a provenance sidecar", True, not missing,
                 f"{len(missing)} without a sidecar: {', '.join(missing[:4])}" if missing
                 else f"all {total} figures and tables carry one")


def g12_numbers_current(tree):
    """Every manuscript number is computed, never typed. --check DIFFS rather than regenerating,
    so a number that MOVED fails the build and a human decides whether the sentence still holds."""
    script = os.path.join(tree, "analysis", "manuscript_numbers.py")
    if not os.path.exists(script):
        return check("G12 manuscript numbers current", True, False, "manuscript_numbers.py missing")
    r = subprocess.run([sys.executable, script, "--check"], cwd=tree,
                       capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if l.strip().startswith(("MOVED", "NEW", "REMOVED"))]

    # A NUMBER THAT MOVED AND A NUMBER THAT CANNOT BE COMPUTED YET ARE DIFFERENT FAILURES.
    # The release tree deliberately ships none of the predecessors' code, so any entry that
    # imports their `instanceGenerator` raises ModuleNotFoundError until `fetch_karademir.py`
    # has been run. Reporting that as "stale" tells a replicator their download is broken when
    # it is working exactly as designed. Separated so the gate stays honest in BOTH trees.
    unfetched = [l for l in tail
                 if ("ModuleNotFoundError" in l and ("instanceGenerator" in l or "build_instance" in l))
                 # data/json/*.json are K's benchmark instances (in third_party_manifest, restored by
                 # fetch_karademir.py), so a missing one in the release tree is "run fetch first",
                 # not a stale number -- the same not-a-staleness-failure case as the module import.
                 or ("FileNotFoundError" in l and "data" in l and "json" in l)]
    real = [l for l in tail if l not in unfetched]
    if real:
        return check("G12 manuscript numbers current", True, False,
                     f"{len(real)} stale: {real[0].strip()[:60]}")
    if unfetched:
        return check("G12 manuscript numbers current", False, False,
                     f"{len(unfetched)} entry(ies) need the predecessors' code or instances -- run "
                     f"fetch_karademir.py first; not a staleness failure")
    return check("G12 manuscript numbers current", True, r.returncode == 0,
                 "ok" if r.returncode == 0 else "check failed")


def g12b_numbers_not_stale(tree):
    """G12 diffs numbers.tex against what manuscript_numbers.py PRODUCES; it never asks whether
    manuscript_numbers.py reads the artifacts the headline tables read. On 2026-09-26 that let
    G12 pass with numbers.tex nine days old and zero of the day's headline artifacts referenced
    (d486). This gate asks the two questions G12 cannot: is numbers.tex older than the newest
    headline artifact, and does manuscript_numbers.py reference the headline tables at all."""
    tex = os.path.join(tree, "paper", "numbers.tex")
    script = os.path.join(tree, "analysis", "manuscript_numbers.py")
    if not (os.path.exists(tex) and os.path.exists(script)):
        return check("G12b manuscript numbers not stale", True, False, "numbers.tex or manuscript_numbers.py missing")
    heads = ["tep_n30_best_of", "tep_n50_batch", "tep_n100_family_table", "tep_fine_delta_bound_n30_d5", "tep_coverage_map"]
    arts = [os.path.join(tree, "runs", "oracle", h + ".json") for h in heads]
    arts = [a for a in arts if os.path.exists(a)]
    src = open(script, encoding="utf-8").read()   # release_gate imports no io; builtin open
    referenced = [h for h in heads if h in src]
    newest = max((os.path.getmtime(a) for a in arts), default=0.0)
    stale = newest > os.path.getmtime(tex)
    if stale or not referenced:
        import time
        return check("G12b manuscript numbers not stale", True, False,
                     "numbers.tex %s; headline artifacts referenced by manuscript_numbers.py: %d of %d%s"
                     % (time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(tex))), len(referenced), len(heads),
                        (" (newest artifact %s)" % time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))) if stale else ""))
    return check("G12b manuscript numbers not stale", True, True, "numbers.tex newer than every headline artifact; %d of %d referenced" % (len(referenced), len(heads)))


def g1c_unmanifested_third_party(tree):
    """Their content that the MANIFEST does not cover, and which G1 therefore never saw.

    G1 checks the 35 files in `third_party_manifest.json`. `ResultsJoint/` is also theirs --
    it arrived in the inherited-repository baseline commit and holds their solved-route
    outputs -- but it is in no manifest, so G1 passed over it and `export_release.py` shipped
    all 15 files into a release stating it contains none of their material, from a repository
    that declares no licence. Found 2026-09-15 by running the gate against the EXPORTED tree
    for the first time, rather than against the working tree where G1 fails anyway.

    Listed by directory because that is how it arrived. Any further inherited directory
    belongs here the moment it is noticed.

    TRACKED IS THE TEST, NOT PRESENT ON DISK. The concern is REDISTRIBUTION. Keeping a copy
    locally to read is ordinary -- G1b says exactly that about their PDF -- and a check that
    fires on a local copy would be permanently red in the working tree, which is how a check
    gets ignored. Untracked 2026-09-15, kept on disk, gitignored.
    """
    THEIRS = ["ResultsJoint/"]
    tracked = tracked_files(tree)
    found = []
    for d in THEIRS:
        n = sum(1 for f in tracked if f.startswith(d))
        if n:
            found.append(f"{d} ({n} files tracked)")
    return check("G1c no unmanifested third-party content", True, not found,
                 "; ".join(found) + " -- theirs, not in the manifest" if found else "ok")


def g14_det_work_recorded(tree):
    """Every primal row must record the deterministic work it DID. Not the budget it was given.

    RE-SCOPED 2026-09-22 under `primal-harness-blocking-defects-v3`. The old rule required a
    `det_budget` on any row whose status was `det_budget_exhausted`, and it had been RED for a
    week: 238 offenders since the 2026-09-15 freeze, including every run of the current
    campaign. Two independent reasons it was never going to come back green:

      * the primal no longer HAS a governing tick budget -- d(v3) reclassified wall-clock
        stopping from a blocking defect to the declared stop rule, because the budget bound on
        only 31% of n100 runs and 68% of n20 (34 of 137 and 1 of 19 in the last three days),
        and because the fairness claim is denominated in wall seconds;
      * the status it keyed on is not a fact. `fixopt.py` sets
        `status="det_budget_exhausted"` whenever a det budget was SET, regardless of whether it
        bound, so the rows it selected are a mix of det-stopped and wall-stopped runs. A gate
        cannot enforce provenance off a field that reports intent.

    WHAT IT WATCHES NOW, and why this is the load-bearing check rather than a consolation. With
    no budget equalising search, `det_used` is the only way to tell AFTERWARDS how much work a
    run actually received -- which is what makes a contended run detectable and excludable.
    v3 is explicitly conditional on that field existing. This gate is that condition.

    SELF-ARMING, so it cannot be quietly forgotten while the writer patch is pending. The
    `det_used` stamp lives in `fixopt.py` and could not be applied while a job held the file
    (editing it mid-campaign would stamp running work with code that did not produce it). So:

      * no row anywhere carries `det_used` -> NOT ARMED. Non-blocking, and says so loudly.
      * the field appears -> the rule goes live from that first row, and every row closed after
        it must carry the field. No manual ledger, no freeze date to remember to advance.
    """
    import csv as _csv
    summ = os.path.join(tree, "runs", "summary.csv")
    if not os.path.exists(summ):
        return check("G14 det work recorded", False, True, "no runs/summary.csv in this tree")

    rows = []
    for r in _csv.DictReader(open(summ, encoding="utf-8")):
        cfg = json.loads(r["config_json"]) if r.get("config_json") else {}
        rows.append((r, cfg))

    carriers = [(r, c) for r, c in rows if "det_used" in c and r.get("closed_at")]
    if not carriers:
        return check("G14 det work recorded", False, True,
                     "NOT ARMED: no row records det_used yet. The stamp is queued for "
                     "solver/engines/fixopt.py (see primal-harness-blocking-defects-v3, which "
                     "is conditional on it). This gate blocks as soon as the first row "
                     "carries the field.")

    armed_at = min(r.get("closed_at") for r, _c in carriers)
    offenders = []
    for r, cfg in rows:
        if not r.get("closed_at") or r["closed_at"] < armed_at:
            continue                       # predates the rule
        if "det_used" in cfg:
            continue
        offenders.append("%s/n%s/s%s/%s (closed %s)"
                         % (r["instance"], r.get("size"), r.get("seed"),
                            cfg.get("variant", "-"), (r.get("closed_at") or "?")[:10]))
    return check("G14 det work recorded", True, not offenders,
                 "%d row(s) closed after %s lack det_used: %s"
                 % (len(offenders), armed_at[:10], offenders[0]) if offenders
                 else "ok (armed %s; %d row(s) carry det_used)" % (armed_at[:10], len(carriers)))


def g16_k_comparison_authority(tree):
    """The rules for comparing against K are derivable in exactly one place, and it works.

    TWO MISTAKES RECUR, for the same structural reason -- the knowledge lived only in
    `text_facts` and in whichever analysis last remembered it, so each new script re-derived it
    and the newest one forgot:

      * including cells K PROVE OPTIMAL in a DUAL comparison. Their dual bound IS the optimum, so
        no bound can exceed it and the cell scores a loss that was never available. Seven of the
        twenty-seven cells at |C| = 20 are proved, and one at |C| = 30.
      * taking proximity 0.0 at |C| = 100, where K's Table 6 is at 0.1. `InstanceSpec.proximity`
        defaults to 0.0, so this is a WRONG ANSWER rather than an error.

    This gate does not try to detect the mistakes by pattern-matching the codebase -- an earlier
    attempt at that produced false positives, flagging `lb_vs_k_headline.py`, which has always
    handled the split correctly, simply because it writes the filter differently. It instead
    asserts that the single authority exists and passes its own self-test, so that any analysis
    CAN get the right answer without re-deriving it.
    """
    script = os.path.join(tree, "analysis", "k_comparison.py")
    if not os.path.exists(script):
        return check("G16 K-comparison authority present", True, False,
                     "analysis/k_comparison.py missing -- every analysis re-derives the arm")
    r = subprocess.run([sys.executable, script], cwd=tree, capture_output=True, text=True)
    bad = [l.strip() for l in r.stdout.splitlines() if "FAIL" in l]
    return check("G16 K-comparison authority + artifact proximity", True, r.returncode == 0,
                 bad[0][:70] if bad else
                 next((l.split(":", 1)[1].strip() for l in r.stdout.splitlines()
                       if "records checked" in l), "selftest ok") + " records at K's proximity")


def g15_verbatim_overlap(tree):
    """No long verbatim run shared with the predecessor paper.

    A LOCAL PROXY for iThenticate, and only that: it compares against ONE document, so a
    pass is not a clearance and the out-of-scope note below still names the gap. But it
    covers the highest-probability source of an embarrassing match in a continuation paper
    whose referees may be the matched authors, and it costs nothing to run on every build.

    Runs the detector's own self-test first. A matcher that has never fired is not evidence,
    so the gate refuses to report a clean result it has not shown itself capable of failing.
    """
    script = os.path.join(tree, "analysis", "similarity_check.py")
    if not os.path.exists(script):
        return check("G15 no verbatim overlap with the predecessor", True, False,
                     "similarity_check.py missing")
    st = subprocess.run([sys.executable, script, "--selftest"], cwd=tree,
                        capture_output=True, text=True)
    if st.returncode != 0:
        return check("G15 no verbatim overlap with the predecessor", True, False,
                     "the detector FAILED ITS OWN SELF-TEST -- clean results are meaningless")
    r = subprocess.run([sys.executable, script], cwd=tree, capture_output=True, text=True)
    line = next((l.strip() for l in r.stdout.splitlines()
                 if "flagged overlap" in l or "reference text not present" in l), "")
    worst = next((l.strip() for l in r.stdout.splitlines() if "FAIL:" in l), "")
    return check("G15 no verbatim overlap with the predecessor", True, r.returncode == 0,
                 worst[:70] if worst else (line[:70] or "ok"))


def g1d_no_unpublished_manuscript(tree):
    """The authors' OWN unpublished work must not ship either.

    `paper/srps-submitted-fulltext.txt` is the authors' SRPS manuscript, under review at
    another venue, supplied 2026-09-15 solely as a self-plagiarism reference corpus for
    analysis/similarity_check.py. Publishing it in a replication package would put a
    manuscript that is still with another journal's referees into the public record.

    Separate from G1/G1b/G1c because the reason differs: that content is OTHER people's, this
    is the authors' own and still confidential. A reader of the gate should be able to see
    that both cases were considered rather than one standing in for the other."""
    pats = ("srps-submitted-fulltext", "srps")
    bad = sorted(f for f in tracked_files(tree)
                 if f.startswith("paper/") and any(p in f.lower() for p in pats))
    return check("G1d no unpublished manuscript tracked", True, not bad,
                 f"{len(bad)} tracked: {', '.join(bad)}" if bad else "ok")


def g13_number_rendering(tree):
    """A quantity appearing more than once must appear the SAME WAY.

    G12 guarantees each number is COMPUTED once; it says nothing about how it is RENDERED.
    The first run of this check found `tw-ratio-by-family-n50` reaching the page as
    "C 0.260, R 0.397, RC 0.315" spelled `0.26, 0.397, 0.315` -- three values computed to
    three decimals, two of them printed that way, quoted side by side in one sentence. The
    rounding was right; float repr dropped the trailing zero. Only the rendering is what a
    reader sees, and a referee who finds one quantity spelled two ways reasonably wonders
    which others moved."""
    script = os.path.join(tree, "analysis", "check_number_consistency.py")
    if not os.path.exists(script):
        return check("G13 number rendering consistent", True, False,
                     "check_number_consistency.py missing")
    r = subprocess.run([sys.executable, script], cwd=tree, capture_output=True, text=True)
    fails = [l.strip() for l in r.stdout.splitlines() if "[FAIL]" in l]
    return check("G13 number rendering consistent", True, r.returncode == 0,
                 f"{len(fails)} split rendering(s): {fails[0][:58]}" if fails
                 else ("ok" if r.returncode == 0 else "check failed"))


# ---------------------------------------------------------------- G10 claims register clean
def g10_claims_gate():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/claims.py"), "check"],
                       capture_output=True, text=True)
    problems = [l for l in r.stdout.splitlines() if l.strip().startswith("[")]
    return check("G10 claim register has no unresolved problems", False, not problems,
                 f"{len(problems)} register warnings (see claims.py check)" if problems else "ok")


# ------------------------------------------------- G17 session state is not stale (amnesia gate)
def g17_session_state():
    """NON-BLOCKING BY DESIGN, and the reason is worth stating.

    This gate guards RELEASABILITY. A stale SESSION_RESUME.md does not make the manuscript wrong
    -- every number still has generating code and every claim still has a falsifier. What it makes
    wrong is the NEXT DECISION, by hiding results and settled decisions from whoever reads it.

    Added 2026-09-17 after the author reported recurrent re-litigation of settled questions and
    said they were losing trust. The instrument existed; it was two days stale and unread, and
    nothing detected that. Prose cannot detect its own staleness, so this does it.
    """
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/session_state.py"), "--quiet"],
                       capture_output=True, text=True)
    n = "?"
    for l in r.stdout.splitlines():
        if "STALE by" in l:
            parts = l.split("STALE by", 1)[1].split()
            if parts:
                n = parts[0]
    return check("G17 session state current (decisions + results)", False, r.returncode == 0,
                 f"SESSION_RESUME.md stale by {n} artifact(s) -- rewrite before proposing work"
                 if r.returncode else "ok")


# ------------------------------------------- G20 every run is at K's proximity for its size
def g20_run_proximity():
    """BLOCKING. A run built at the wrong proximity is not comparable to K, and it fails silently.

    2026-09-18 (d209): the whole |C| = 100 overnight sweep ran at proximity 0.0 against K's Table 6
    at 0.1. Every "vs K" figure was void. The data to catch it was ALREADY in runs/summary.csv,
    which carries a `proximity` column on every row -- this gate is three lines and would have
    fired on the first coverage run.

    G16 does not cover this: analysis/k_comparison.py:129 globs only crossfeed descend artifacts,
    so its "1134 records at K's proximity" is one family, not the corpus. Its own docstring names
    this exact failure and declines to detect it. This gate closes that scope gap.
    """
    import csv as _csv
    summ = os.path.join(ROOT, "runs", "summary.csv")
    if not os.path.exists(summ):
        return check("G20 runs at K's proximity for their size", False, True, "no summary.csv")
    # run as 'python analysis/release_gate.py', so sys.path[0] is analysis/ -- import both ways
    try:
        from analysis.k_comparison import k_proximity
    except ModuleNotFoundError:
        from k_comparison import k_proximity
    bad = []
    skipped = 0
    for r in _csv.DictReader(open(summ, encoding="utf-8")):
        # d295, author-approved 2026-09-23: a QUARANTINED row feeds nothing published (every
        # published-path reader -- make_tables, freeze_published_artifacts, reference_set_audit,
        # redump_incumbents, score_coverage -- already excludes it), so its proximity cannot
        # void a "vs K" figure. The fifteen d209 orphans are marked with the reason in the
        # ledger; an UNQUARANTINED wrong-proximity row still blocks.
        if (r.get("quarantined") or "").strip().lower() == "true":
            skipped += 1
            continue
        try:
            size = int(r.get("size") or 0)
            prox = float(r.get("proximity"))
        except (TypeError, ValueError):
            continue
        try:
            want = k_proximity(size)          # sizes K never published are not our business
        except KeyError:
            continue
        if want is not None and abs(prox - want) > 1e-9:
            bad.append((r.get("run_id", "?"), size, prox, want))
    return check("G20 runs at K's proximity for their size", True, not bad,
                 ("ok (%d quarantined row(s) skipped)" % skipped) if not bad else
                 "%d run(s) at the wrong proximity, e.g. %s: |C|=%s at %.1f, K's table is %.1f"
                 % (len(bad), bad[0][0][:40], bad[0][1], bad[0][2], bad[0][3]))


# ------------------------------------------- G19 a verifier/solver contradiction blocks release
def g19_quarantine_guard():
    """BLOCKING. An engine whose validity claim the INDEPENDENT VERIFIER has contradicted cannot
    feed a published claim until the root cause is known.

    AUTHOR RULE, 2026-09-18: *"I want to stop all runs after any quarantine except if because no
    incumbent found by main solver ie. if verifier contradict main solver validity claim."*

    The distinction matters and is clean in the data: a solver that finds NO INCUMBENT
    (`seed_infeasible`) is failing honestly and never reaches runs/invalid/ -- 12 such runs sit in
    runs/ and zero in the quarantine. A solver whose solution the verifier REJECTS is a
    correctness failure, and one of the two is wrong.

    WHY THIS GATE DID NOT EXIST UNTIL NOW, which is the whole point of adding it: runs/invalid/
    INDEX.md has said "**BLOCKING**: the engine that produced it cannot feed a published claim
    until the root cause is found and `triaged` is set" since it was created. On 13-14 September
    22 runs were quarantined and nothing reacted for two weeks, because no gate read the file
    (d206). The policy existed; the enforcement did not.
    """
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/quarantine_guard.py"),
                        "--quiet"], capture_output=True, text=True)
    # Parse the guard's own report rather than importing it -- an import that fails silently
    # would understate the count, and a gate that understates its own failure is worse than none.
    n = "?"
    full = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/quarantine_guard.py")],
                          capture_output=True, text=True)
    for l in full.stdout.splitlines():
        if "UNTRIAGED" in l and ":" in l:
            n = l.rsplit(":", 1)[1].strip()
    return check("G19 no untriaged verifier/solver contradiction", True, r.returncode == 0,
                 "ok" if r.returncode == 0 else
                 f"{n} untriaged contradiction(s) in runs/invalid/INDEX.md -- "
                 f"run analysis/quarantine_guard.py; triage before releasing")


# ------------------------------------------- G18 exploratory results never reach the manuscript
def g18_explore_quarantine():
    """BLOCKING. The explore lane exists so new ideas can use the idle cores without waiting for
    the pipeline; the price is that its results are worthless for publication -- co-tenant,
    LPE-pinned, deprioritised, and often run at a throwaway budget. The lane marks its own tree,
    but a marker no one checks is a convention, not a guarantee.

    This is the guarantee: if any generating code reads from runs/explore/, the gate FAILS.
    An exploratory result is a reason to run a real experiment, never a number to print.
    """
    bad = []
    for sub in ("analysis", "paper"):
        d = os.path.join(ROOT, sub)
        for dp, _dn, fn in os.walk(d):
            for f in fn:
                if not f.endswith((".py", ".tex", ".json", ".md")):
                    continue
                fp = os.path.join(dp, f)
                if os.path.basename(fp) == "explore_lane.py":
                    continue          # the lane itself must name its own tree
                if os.path.basename(fp) == "release_gate.py":
                    continue          # this check must name it too
                try:
                    t = open(fp, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                if "runs/explore" in t or "runs\explore" in t:
                    bad.append(os.path.relpath(fp, ROOT))
    return check("G18 exploratory results quarantined", True, not bad,
                 "%d file(s) read the explore tree: %s" % (len(bad), ", ".join(bad[:3]))
                 if bad else "ok (no generating code reads runs/explore)")


def g21_oracle_L2_current():
    """BLOCKING. The builder layer of the transcription oracle must be PASSING and NOT STALE.

    L2 is the only check that can see an OVER-TIGHT model. verifier3 is structurally blind to one:
    shrinking the feasible region leaves every returned point still satisfying every constraint,
    so verification passes while the optimum silently inflates. The evidence is an ABSENCE.

    WHY STALENESS IS THE REAL RISK. A green L2.json is a result about two specific files. Edit the
    builder or verifier3 afterwards and the JSON still reads PASS -- the same failure CLAUDE.md
    records for SESSION_RESUME, which "existed, carried a Decisions taken section, was two days
    stale and unread, and nothing detected that". So this gate recomputes the source hashes rather
    than trusting the verdict.

    It also requires the negative controls to be green, because the v4 audit (DM3) found two of
    three power perturbations were mathematically incapable of firing while their null was being
    read as evidence. A detector that has never been shown to fire is not a detector.
    """
    l2p = os.path.join(ROOT, "runs", "oracle", "L2.json")
    ctlp = os.path.join(ROOT, "runs", "oracle", "L2_controls.json")
    if not os.path.exists(l2p):
        return check("G21 oracle L2 current and passing", True, False,
                     "runs/oracle/L2.json missing -- run python analysis/oracle_L2.py")
    d = json.load(open(l2p, encoding="utf-8"))
    if d.get("verdict") != "PASS":
        return check("G21 oracle L2 current and passing", True, False,
                     "L2 verdict %s: %s" % (d.get("verdict"), "; ".join(d.get("failures", []))[:180]))
    try:
        sys.path.insert(0, os.path.join(ROOT, "analysis"))
        import oracle_L2
        now = oracle_L2.sources()
    except Exception as e:
        return check("G21 oracle L2 current and passing", True, False,
                     "cannot recompute source hashes (%s)" % type(e).__name__)
    was = d.get("sources") or {}
    drifted = [k for k in now if was.get(k) != now[k]]
    if drifted:
        return check("G21 oracle L2 current and passing", True, False,
                     "STALE: %s changed since L2 ran -- re-run python analysis/oracle_L2.py"
                     % ", ".join(drifted))
    if not os.path.exists(ctlp):
        return check("G21 oracle L2 current and passing", True, False,
                     "controls never run -- L2's 0 failures is uninterpretable without them")
    c = json.load(open(ctlp, encoding="utf-8"))
    silent = c.get("silent") or []
    cdrift = [k for k in now if (c.get("sources") or {}).get(k) != now[k]]
    if silent:
        return check("G21 oracle L2 current and passing", True, False,
                     "%d L2 control(s) SILENT: %s" % (len(silent), "; ".join(silent)[:150]))
    if cdrift:
        return check("G21 oracle L2 current and passing", True, False,
                     "controls STALE: %s changed since they ran" % ", ".join(cdrift))
    nb = len(d.get("L2b") or [])
    na = len(d.get("L2a") or [])
    # 7 control ROWS = 6 injected defects + 1 undamaged baseline; say so rather than calling
    # all seven "controls", which would overstate the number of defects actually detected.
    inj = len(c.get("L2a", [])) + len(c.get("L2b", [])) - 1
    return check("G21 oracle L2 current and passing", True, True,
                 "%d census builds, %d round-trips, 0 failures; %d/%d injected defects detected"
                 % (na, nb, inj - len(silent), inj))


def g22_ambiguity_register():
    """BLOCKING. The code must agree with validation/AMBIGUITY_REGISTER.md.

    Where K's article leaves a reading open, the register records which one we took and why. A
    register nothing enforces drifts -- SESSION_RESUME went two days stale unread, and the claim
    register was a parallel record until gate_claims_prose made it binding. This runs G22's own
    checks so a pick cannot move without the gate noticing.
    """
    import subprocess as _sp
    r = _sp.run([sys.executable, os.path.join(ROOT, "analysis", "gate_ambiguity.py")],
                capture_output=True, text=True)
    last = [l for l in (r.stdout or "").splitlines() if l.startswith("G22:")]
    fails = [l.strip() for l in (r.stdout or "").splitlines() if "**FAIL**" in l]
    return check("G22 code agrees with the ambiguity register", True, r.returncode == 0,
                 "; ".join(fails)[:200] if fails else (last[0] if last else "ran clean"))


def g23_k_comparator_none():
    """BLOCKING. A value K do not publish must never be formatted or divided as if they did.

    THREE TIMES IN ONE DAY (2026-09-27). `k_best_incumbent` returns None at |C| = 50 and 100, where K
    publish pool and family aggregates instead of per-instance values. tep_n30_best_of.py divided by it
    and crashed AFTER printing a table and BEFORE writing the artifact, so a stale file outlived the
    numbers on screen. tep_master_fleet_cap.py formatted it with %.1f and killed the final campaign at
    step S3b one second in, taking S5 through S9 with it. tep_force_fleet.py carried the identical line
    and would have been the third.

    The check is deliberately narrow, because a gate that cries wolf gets ignored: it flags a float
    format spec applied to the conventional names for that value on a line that carries no guard. It
    cannot catch every shape, and it catches the one that has actually happened.
    """
    import re as _re
    bad = []
    for f in sorted(glob.glob(os.path.join(ROOT, "analysis", "*.py"))):
        # The mutation fixture carries the defect as a payload string BY DESIGN, so scanning it turns
        # the gate red on its own test rig -- which is what happened the first time the rig ran
        # (2026-09-28). Excluded by name, and nothing else is.
        if os.path.basename(f) == "gate_selftest.py":
            continue
        src = open(f, encoding="utf-8", errors="replace").read()
        if "k_best_incumbent" not in src:
            continue
        # LOGICAL LINES, NOT PHYSICAL ONES. The first version scanned physical lines, so a print whose
        # format string sat on one line and its arguments on the next was invisible: `% (rnd, ...` had
        # no kb and the continuation had no `%`. That is exactly the shape of the two live crashes in
        # tep_master_fleet_cap, and the gate reported PASS over both. Lines are joined until brackets
        # balance, and the reported number is the line the statement starts on.
        logical, buf, start, depth = [], "", 1, 0
        for i, line in enumerate(src.splitlines(), 1):
            if not buf:
                start = i
            buf += (" " if buf else "") + line.strip()
            depth += line.count("(") + line.count("[") - line.count(")") - line.count("]")
            if depth <= 0:
                logical.append((start, buf)); buf = ""; depth = 0
        for i, line in logical:
            if _re.search(r"%\s*\(.*\b(kb|k_inc|their_best)\b", line) or _re.search(r"%[.0-9]*f.*\b(kb|k_inc|their_best)\b", line):
                # THE GUARD MUST ATTACH TO THE VALUE, NOT SIT ANYWHERE ON THE LINE. The first version
                # accepted any line containing "if", so a print carrying an unrelated ternary --
                # "PASS" if ok else "FAIL" -- masked an unguarded kb two arguments later. That false
                # negative hid two live crashes on the SUCCESS path of tep_master_fleet_cap while the
                # campaign was running: they would have fired the moment a cell produced a verified
                # solution. A heuristic gate that is too generous is worse than none, because it is
                # believed (d578).
                guarded = bool(_re.search(r"\b(kb|k_inc|their_best)\b[^,]{0,30}\b(if|or)\b", line)
                               or _re.search(r"\bif\s+(kb|k_inc|their_best)\b", line)
                               or "None" in line)
                if _re.search(r"%[.0-9]*f", line) and not guarded:
                    bad.append("%s:%d" % (os.path.basename(f), i))
    return check("G23 no unguarded use of a comparator K do not publish", True, not bad,
                 ("unguarded: %s" % ", ".join(bad[:4])) if bad else "every float format of K's per-cell value is guarded")


def _tep_cells():
    return (["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)]
            + ["RC%d" % i for i in range(201, 209)])


def g24_nothing_better_on_disk():
    """BLOCKING, and it is the gate this project most needed. TWICE IN TWO DAYS a valid result sat in
    the repository unread: nine ng-route certificates at |C| = 50 (d559) and twenty-six verified
    master-IP solutions, one worth 7.34 per cent (d582). Both times every reader enumerated a
    hand-written list of places and missed the one the result was written to. No check noticed.

    This asks the question directly: is there anything on disk better than what we report? A verified
    solution cheaper than the banked incumbent, or a certified bound higher than the reported one, is
    a release blocker -- not because it is wrong, but because the paper would understate its own
    result and a referee recomputing from the released artifacts would find the discrepancy.
    """
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    import tep_harvest_master_ip as H
    from bound_certificate import bound_class
    worse_primal, worse_bound = [], []
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_cg_bound_*_ip*.json")):
        d = H.load(p)
        ip = (d or {}).get("ip")
        if not isinstance(ip, dict) or not ip.get("verified") or not ip.get("objVal"):
            continue
        bb = H.banked_best(d.get("cell"), d.get("size") or 100)
        if bb and ip["objVal"] < bb[0] - H.TOL:
            worse_primal.append("%s n%s by %.2f%%" % (d.get("cell"), d.get("size") or 100,
                                                      100.0 * (1 - ip["objVal"] / bb[0])))
    # THE BOUND IS REPORTED BY A DIFFERENT TABLE AT |C| = 100. best_of carries the per-cell bound at
    # 10 to 50; at 100 the reported bound is the family table's, and its per-cell provenance is in
    # `bound_sources`. Comparing n100 against best_of -- which finds no bound there, because the n100
    # artifacts are named without the size -- flagged all 27 cells on the first run of this check.
    for size in (10, 20, 30, 50):
        art = load(os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % size))
        if not art:
            continue
        for r in art["rows"]:
            best = H.our_bound(r["cell"], size)
            if best is not None and (r.get("our_lb") is None or best > r["our_lb"] + 1e-6):
                worse_bound.append("%s n%d" % (r["cell"], size))
    fam = load(os.path.join(ROOT, "runs", "oracle", "tep_n100_family_table.json"))
    for r in (fam or {}).get("rows", []):
        for cell, srcname in (r.get("bound_sources") or {}).items():
            chosen = H.load(os.path.join(ROOT, "runs", "oracle", srcname)) or {}
            cv = chosen.get("composed") if chosen.get("composed") is not None else chosen.get("lp_composed")
            best = H.our_bound(cell, 100)
            if best is not None and (cv is None or best > float(cv) + 1e-6):
                worse_bound.append("%s n100" % cell)
    bad = worse_primal + worse_bound
    return check("G24 nothing better than what we report sits on disk", True, not bad,
                 ("%d unread: %s" % (len(bad), "; ".join(bad[:4]))) if bad else
                 "no verified solution beats a banked incumbent and no certified bound beats a reported one")


def g25_every_reported_bound_certified():
    """BLOCKING. A bound may be reported only with a certificate of a named class (d519, d559). The
    per-cell tables already refuse an uncertified value; nothing checked that the tables were the
    only path, and the certificate classes are now two, so the class must travel with the value."""
    bad = []
    for size in (10, 20, 30, 50, 100):
        art = load(os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % size))
        if not art:
            continue
        for r in art["rows"]:
            if r.get("our_lb") is not None and not r.get("lb_class"):
                bad.append("%s n%d" % (r["cell"], size))
    return check("G25 every reported bound carries a certificate class", True, not bad,
                 ("%d bound(s) with no class: %s" % (len(bad), ", ".join(bad[:5]))) if bad else
                 "every reported bound names elementary or ng")


def g26_incumbent_invariants():
    """BLOCKING. Three invariants on every reported incumbent, all cheap because they read artifacts:
    it is marked verified by a run of verifier3, it is NOT below our own certified bound for the cell
    (one of the two would be wrong), and it is NOT below an optimum K prove (a defect, not a win).

    Full re-verification of all 135 solutions is NOT done here -- it is `tep_reverify_all.py`, which
    the campaign's own final step runs. This gate asserts the invariants that can be read, and that a
    re-verification exists and passed.
    """
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    import tep_harvest_master_ip as H
    kt = load(os.path.join(ROOT, "runs", "oracle", "k_targets_small.json")) or {}
    bad = []
    for size in (10, 20, 30, 50, 100):
        prov = {r["cell"]: r for r in (kt.get("n%d" % size) or {}).get("rows", [])}
        for cell in _tep_cells():
            bb = H.banked_best(cell, size)
            if not bb:
                continue
            lb = H.our_bound(cell, size)
            if lb is not None and bb[0] < lb - 1e-6:
                bad.append("%s n%d below our own bound" % (cell, size))
            pr = prov.get(cell)
            if pr and pr.get("proven") and pr.get("k_inc") and bb[0] < float(pr["k_inc"]) - H.TOL:
                bad.append("%s n%d below a proven optimum" % (cell, size))
    rv = load(os.path.join(ROOT, "runs", "oracle", "tep_reverify_all.json"))
    if not rv:
        bad.append("no tep_reverify_all.json: the full re-verification has never been run")
    elif rv.get("failures"):
        bad.append("re-verification reports %d failure(s)" % len(rv["failures"]))
    return check("G26 incumbent invariants hold", True, not bad,
                 ("%d violation(s): %s" % (len(bad), "; ".join(bad[:4]))) if bad else
                 "no incumbent below our bound or below a proven optimum; re-verification on file and clean")


def g27_tables_agree_with_the_accessor():
    """BLOCKING. Every table's answer must equal the single accessor's answer (d585).

    Reader blindness twice in two days had one cause: each reader carried its own list of places to
    look. `analysis/best_known.py` now owns that question. The readers are NOT rewritten while a
    campaign is running -- this check reports the first divergence instead, which is the same
    protection without touching the pipeline mid-flight.
    """
    sys.path.insert(0, os.path.join(ROOT, "analysis"))
    from best_known import best_solution, best_bound
    bad = []
    for size in (10, 20, 30, 50, 100):
        art = load(os.path.join(ROOT, "runs", "oracle", "tep_n%d_best_of.json" % size))
        for r in (art or {}).get("rows", []):
            s = best_solution(r["cell"], size)
            if s and r.get("best") is not None and abs(float(r["best"]) - s[0]) > 0.05:
                bad.append("%s n%d incumbent: table %.3f, accessor %.3f (%s)"
                           % (r["cell"], size, r["best"], s[0], s[1]))
            b = best_bound(r["cell"], size)
            if b and r.get("our_lb") is not None and b[0] > float(r["our_lb"]) + 1e-6:
                bad.append("%s n%d bound: table %.1f, accessor %.1f (%s)"
                           % (r["cell"], size, r["our_lb"], b[0], b[2]))
    return check("G27 tables agree with the single accessor", True, not bad,
                 ("%d divergence(s): %s" % (len(bad), "; ".join(bad[:3]))) if bad else
                 "every per-cell table matches best_known")


def g28_estimates_not_named_as_bounds():
    """BLOCKING, and deliberately narrow. An estimate called `max_` gets used as a bound.

    That is not hypothetical: `max_lift` -- an educated guess at what the integer-car cut would buy
    -- was treated as a ceiling until measurement refuted it on 6 of 23 cells. The quantity was
    fine; the NAME did the damage. Anything that is not a bound says `est_` in its own identifier.
    """
    import re as _re
    banned = _re.compile(r"\b(max_(?:lift|gain|improv\w*)|upper_est\w*)\b")
    bad = []
    for f in sorted(glob.glob(os.path.join(ROOT, "analysis", "*.py"))):
        if os.path.basename(f) in ("release_gate.py", "gate_selftest.py"):
            continue
        for i, line in enumerate(open(f, encoding="utf-8", errors="replace").read().splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if banned.search(line):
                bad.append("%s:%d" % (os.path.basename(f), i))
    return check("G28 an estimate is not named like a bound", True, not bad,
                 ("%d name(s) claiming a bound: %s" % (len(bad), ", ".join(bad[:4]))) if bad else
                 "no estimate is named max_*")


def main(tree):
    print(f"RELEASE GATE  tree={tree}\n")
    g1_no_third_party_tracked(tree)
    g1b_no_unmanifested_thirdparty(tree)
    g2_readme_is_ours(tree)
    g3_required_files(tree)
    g4_pinned_env(tree)
    g5_solver_version_recorded()
    g6_provenance_complete()
    g7_campaign_code_invariant()
    g8_no_unbacked_numbers()
    g9_third_party_hashes(tree)
    g11_figures_have_provenance(tree)
    g12_numbers_current(tree)
    g12b_numbers_not_stale(tree)
    g1c_unmanifested_third_party(tree)
    g1d_no_unpublished_manuscript(tree)
    g14_det_work_recorded(tree)
    g15_verbatim_overlap(tree)
    g16_k_comparison_authority(tree)
    g13_number_rendering(tree)
    g10_claims_gate()
    g17_session_state()
    g18_explore_quarantine()
    g19_quarantine_guard()
    g20_run_proximity()
    g21_oracle_L2_current()
    g22_ambiguity_register()
    g23_k_comparator_none()
    g24_nothing_better_on_disk()
    g25_every_reported_bound_certified()
    g26_incumbent_invariants()
    g27_tables_agree_with_the_accessor()
    g28_estimates_not_named_as_bounds()

    width = max(len(r["name"]) for r in RESULTS)
    nblock = 0
    for r in RESULTS:
        tag = "PASS" if r["ok"] else ("**FAIL**" if r["blocking"] else "warn")
        if not r["ok"] and r["blocking"]:
            nblock += 1
        print(f"  [{tag:8s}] {r['name']:{width}s}  {r['detail']}")

    print(f"\n  blocking failures: {nblock}")
    print("  VERDICT:", "RELEASABLE" if nblock == 0 else "NOT RELEASABLE")
    print("""
  OUT OF SCOPE for this gate, and therefore still human work:
    * that the manuscript's numbers match the artifacts (table scripts must regenerate them)
    * iThenticate PROPER. G15 checks verbatim overlap against THREE local corpora -- the
      predecessors' paper, their code comments, and the authors' own SRPS manuscript -- so
      it covers the predecessor and the self-plagiarism risks. It does NOT see the published
      literature, the web, or the works in our own bibliography; a passage taken from any of
      those passes G15 and is caught only at submission
    * whether the prose describing their model is written in our own words
    * that fetch_karademir.py actually succeeds against a live network""")
    return 1 if nblock else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=ROOT)
    a = ap.parse_args()
    sys.exit(main(os.path.abspath(a.tree)))
