"""Every quantity that appears more than once must appear the SAME WAY. Enforced, not proofread.

THE FAILURE THIS CATCHES. `analysis/manuscript_numbers.py` guarantees each registered number is
COMPUTED once. It does not guarantee it is RENDERED once. A closed share can reach the page as
67.6 from the registry, 67.55 from a table that formats with its own `%.2f`, and "about 68%" from
a sentence someone wrote by hand. All three are correct and the paper still looks careless -- and
a referee who spots two renderings of one quantity reasonably wonders which other numbers moved.

Three checks, each failing the command rather than printing advice:

  C1  SPLIT RENDERING -- one value, two spellings. The same quantity rendered to different
      precision in different artifacts (registry vs tables vs figure sidecars).

  C2  HAND-TYPED DUPLICATES -- a numeric literal sitting in manuscript prose that equals a
      registered value. That number should be \\num{id}; as a literal it will not move when the
      artifact moves, which is the exact rot paper/REPLICABILITY.md exists to prevent.

  C3  INTERNAL INCONSISTENCY -- a registry entry whose own value is rendered inconsistently
      across the dict it carries (e.g. {'C': 0.46, 'R': 0.428}: two decimals against three).

SCOPE AND ITS LIMIT, stated so the check is not over-trusted: it compares RENDERED STRINGS. It
cannot know that 0.876 and 87.6 are the same quantity in different units, and it does not try --
guessing at unit conversions would produce false positives, and a check that cries wolf gets
ignored, which is worse than not having it.
"""
import os, re, sys, json, glob, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUM_RE = re.compile(r"(?<![\w.])(-?\d+\.\d+|-?\d+)(?![\w.])")
# Numbers that carry no risk: structural integers, years, and small counts that are obviously
# not measurements. Rendering "2" three ways is not a thing that happens.
IGNORE_EXACT = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                "20", "30", "50", "100", "27", "2025", "2026"}


def rendered(tok):
    """Decimal places as WRITTEN, which is the thing being checked."""
    return len(tok.split(".")[1]) if "." in tok else 0


def collect(path, text):
    for m in NUM_RE.finditer(text):
        tok = m.group(1)
        if tok in IGNORE_EXACT:
            continue
        try:
            val = float(tok)
        except ValueError:
            continue
        yield val, tok, path


def registry_values():
    """id -> list of (value, rendered token). Dict-valued entries expand per key."""
    p = os.path.join(ROOT, "paper", "numbers.json")
    if not os.path.exists(p):
        return {}
    out = {}
    for nid, d in json.load(open(p)).items():
        if str(nid).startswith("_") or nid == "sources":   # stamped() provenance keys are not numbers (2026-09-26)
            continue
        v = d["value"]
        items = v.items() if isinstance(v, dict) else [(None, v)]
        for k, kv in items:
            key = nid if k is None else f"{nid}.{k}"
            toks = [t for _, t, _ in collect("registry", str(kv))]
            out[key] = (str(kv), toks)
    return out


def main():
    problems = []

    # ---- gather every rendered number from the generated artifacts --------------
    seen = collections.defaultdict(set)          # value -> {(token, source)}
    sources = []
    np_ = os.path.join(ROOT, "paper", "numbers.json")
    if os.path.exists(np_):
        for nid, d in json.load(open(np_)).items():
            if str(nid).startswith("_") or nid == "sources":
                continue
            v = d["value"]
            items = v.items() if isinstance(v, dict) else [(None, v)]
            for k, kv in items:
                label = nid if k is None else f"{nid}.{k}"
                for val, tok, _ in collect(label, str(kv)):
                    seen[round(val, 9)].add((tok, f"registry:{label}"))
    # RAW-DATA APPENDIX TABLES are excluded from the C1 cross-registry scan. percell_grid and
    # stage_ablation list hundreds of per-cell / per-stage data points; a chance equality with a
    # registered SUMMARY at a different precision (e.g. a 0.26 stage reduction vs a 0.260 time-window
    # ratio) is a coincidence, not one quantity rendered two ways -- and their generators already
    # assert their aggregates equal the registered values. Summary tables stay in the scan.
    DATA_TABLES = {"percell_grid.tex", "stage_ablation.tex", "n50_longrt.tex"}
    for f in sorted(glob.glob(os.path.join(ROOT, "paper", "tables", "*.tex"))):
        if os.path.basename(f) in DATA_TABLES:
            continue
        sources.append(f)
        txt = open(f, encoding="utf-8").read()
        for val, tok, _ in collect(f, txt):
            seen[round(val, 9)].add((tok, os.path.basename(f)))

    # ---- C1: one value, two spellings ------------------------------------------
    # WHOLE NUMBERS ARE A WARNING, NOT A FAILURE, and the first run showed why: it flagged
    # "16.0" (a closed share, in T1) against "16" (a cell count, in fleet-certificate-coverage).
    # Two unrelated quantities that happen to share a value. Comparing rendered strings cannot
    # tell a coincidence from a defect without semantics we do not have, and a check that cries
    # wolf gets ignored -- which is worse than no check. A value with a NONZERO FRACTIONAL PART
    # colliding across artifacts is overwhelmingly the same measurement, so that stays blocking.
    warnings = []
    for val, entries in sorted(seen.items()):
        widths = {rendered(t) for t, _ in entries}
        if len(widths) <= 1:
            continue
        shown = ", ".join(f"{t!r} in {s}" for t, s in sorted(entries, key=lambda e: e[1]))
        msg = f"C1 split rendering of {val}: {shown}"
        (problems if val != int(val) else warnings).append(msg)

    # ---- C2: hand-typed literals in prose that duplicate a registered value -----
    reg = registry_values()
    regvals = {}
    for key, (s, toks) in reg.items():
        for t in toks:
            try:
                regvals.setdefault(round(float(t), 9), []).append((key, t))
            except ValueError:
                pass
    secs = sorted(glob.glob(os.path.join(ROOT, "paper", "manuscript", "sections", "*.tex")))
    secs += [os.path.join(ROOT, "paper", "manuscript", "main.tex")]
    for f in secs:
        if not os.path.exists(f):
            continue
        # PSEUDOCODE IS NOT PROSE. Numbers inside an algorithmic environment are algorithm
        # COEFFICIENTS (e.g. `0.5(B - refine time)`, a budget split), not reported results that
        # must be \num{} -- and they collide with registered statistics by coincidence. Blank the
        # whole environment up front (by shape, like the (16) equation refs), so no stateful flag
        # is needed and the per-line scan never sees it.
        body = re.sub(r"\\begin\{algorithm\*?\}.*?\\end\{algorithm\*?\}", " ",
                      open(f, encoding="utf-8").read(), flags=re.S)
        body = re.sub(r"\\begin\{algorithmic\}.*?\\end\{algorithmic\}", " ", body, flags=re.S)
        for line in body.splitlines(keepends=True):
            if line.lstrip().startswith("%"):
                continue
            # LAYOUT LENGTHS ARE NOT QUANTITIES. `0.85\linewidth`, `4.5cm`, `0pt` are typesetting
            # dimensions; stripped by shape so a figure width cannot match a registered ratio.
            line = re.sub(r"\d*\.?\d+\s*\\(?:line|text|column|page|par)?width", " ", line)
            line = re.sub(r"\d*\.?\d+(?:pt|cm|mm|in|em|ex|bp|pc|sp|dd|cc)\b", " ", line)
            line = re.sub(r"\\num\{[^}]*\}", " ", line)       # already correct: skip
            # INLINE MATH IS FORMULA CONTENT, NOT PROSE. C2 checks a literal "sitting in
            # manuscript prose" (docstring); a number inside $...$ or \(...\) is a formula
            # coefficient -- a bucket index, width or node label in a worked witness, e.g.
            # A1_proofs.tex "$\Delta=60$", "$15$" -- which collides with an unrelated registered
            # integer by coincidence, the same whole-number coincidence C1 downgrades to a warning.
            # Stripped by shape so a witness illustration cannot match a registered statistic.
            line = re.sub(r"\$[^$]*\$", " ", line)
            line = re.sub(r"\\\(.*?\\\)", " ", line)
            line = re.sub(r"\\label\{[^}]*\}|\\ref\{[^}]*\}|\\cite[a-z]*\{[^}]*\}", " ", line)
            # CONSTRUCTS THAT ARE NEVER QUANTITIES. Stripped by SHAPE, not by value: adding the
            # offending numbers to IGNORE_EXACT would blind the check to them everywhere, and
            # "25" is a live count (lb-dual-wilcoxon.n30-wins = "25 of 26").
            #
            #   * a WHOLLY PARENTHESISED number, optionally as a dash range -- "(16)--(25)".
            #     That is how one cites an equation or a constraint of the predecessors'
            #     formulation, and it recurs every time we do. A measurement in prose is never
            #     written "(16)".
            #   * ORCID identifiers. Added 2026-09-16 when typesetting the author ORCIDs made
            #     the checker match digit groups inside 0009-0005-9871-1330 against registered
            #     values -- three new false positives from a correct edit.
            line = re.sub(r"\(\s*\d+\s*\)(\s*-{2,3}\s*\(\s*\d+\s*\))?", " ", line)
            line = re.sub(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dXx]\b", " ", line)
            for val, tok, _ in collect(f, line):
                if round(val, 9) in regvals:
                    who = ", ".join(k for k, _ in regvals[round(val, 9)])
                    problems.append(
                        f"C2 hand-typed {tok!r} in {os.path.relpath(f, ROOT)} duplicates "
                        f"registered value(s): {who} -- use \\num{{{who.split(',')[0]}}}")

    # ---- C3: a single registry entry rendering its own keys inconsistently ------
    #
    # COMPARE WITHIN A KIND, NOT ACROSS AN ENTRY. The original rule compared decimal width across
    # every key of an entry, so a COUNT beside a RATIO failed by construction -- `cars=1` against
    # `value=642.216` is not a split rendering, it is two different quantities. Six of the ten
    # failures on 2026-09-16 were that.
    #
    # The fix declares the kinds rather than inferring them. KEY_GROUPS maps a registry id to
    # {key -> kind}; keys with no declared kind fall into one default group, so an entry that
    # declares nothing behaves EXACTLY as before and nothing is silently switched off.
    #
    # This STRENGTHENS the check. Under the old rule wls-sensitivity failed for the wrong reason
    # (a spread at 2 dp against shares at 3 dp) while hiding a real one: street-invariance-spread
    # and water-spread are two spreads in the SAME units and were rendered 2 dp against 0 dp,
    # with the entry's own docstring writing water at 2 dp. Grouping makes that the failure it
    # reports, and it was fixed rather than suppressed.
    KEY_GROUPS = {
        "r205-one-car-optimal": {"cars": "count"},
        # M7. NO SINGLE-KEY GROUP IS USED HERE -- one would pass trivially, which this file
        # warns against below. The falsifier quantity and the threshold it is compared with
        # are ONE kind and are checked together at 4 dp: the aggregate 0.9670, the n20
        # pair 1.0020, the threshold 0.8500, and the worst per-cell value 0.8502. Four
        # places is not decoration -- at three the last two both print 0.850 and a reader
        # cannot see that RC204 sits ABOVE the threshold rather than on it. The threshold is
        # exactly 0.85, so 0.8500 pads it without misstating what the prereg fixed. The two
        # mean-of-ratio keys stay in `_default` and must agree there at 3 dp.
        "m7-matched-budget-n30": {"cells": "count",
                                  "threshold": "falsifier-ratio",
                                  "ratio-of-ratios": "falsifier-ratio",
                                  "n20-ratio-of-ratios": "falsifier-ratio",
                                  "worst-cell-ratio": "falsifier-ratio"},
        "lb-dual-wilcoxon": {"n20-cells": "count", "n30-cells": "count",
                             "n20-worst-k-gap": "count"},
        # THE ABSTRACT'S OWN ENTRY (2026-09-27). Three kinds, and both non-default ones have more than
        # one key so neither passes trivially. Counts are instances and cells. The attainment pair is
        # the only quantity in the paper that needs 2 dp: 0.35 per cent above the optimum has no first
        # decimal to spare, and rendering it 0.4 beside a 20.9 gap would read as the same kind of number
        # when it is three orders finer. Everything else -- their published averages, their per-instance
        # maximum, both sides of every bracket, the closure shares, the family improvements and the
        # budget share -- is a percentage at 1 dp in the default group.
        "tep-abstract": {"k-instances": "count", "k-proven": "count", "attain-cells": "count",
                         "attain-exact": "count", "attain-within1": "count",
                         "n20-cells": "count", "n30-cells": "count", "n50-cells": "count",
                         "n100-cells": "count", "n20-smaller": "count", "n30-smaller": "count",
                         "attain-mean": "attainment-pct", "attain-worst": "attainment-pct"},
        # Same shape: cell counts beside percentages. It entered the registry on 2026-09-27 and took
        # G13 red with it, which is the check working -- the entry was written before its kinds were.
        "tep-bound-calibration": {"n10-cells": "count", "n20-cells": "count", "n30-cells": "count"},
        "budget-sensitivity": {"n20-undefined": "count", "n30-undefined": "count",
                               "n50-undefined": "count", "n100-undefined": "count"},
        "wls-sensitivity": {"n-per-ratio": "count",
                            "street-invariance-spread": "spread", "water-spread": "spread"},
        # Three kinds at two precisions: percentages and cost magnitudes BOTH at 1 dp, shares at
        # 3 dp. This entry is why the kind must be declared and cannot be inferred from width.
        "cross-size-share": {"drop-joint": "pct", "drop-min": "pct",
                             "n50-denominator": "cost", "n100-denominator": "cost"},
        # Four kinds, and the precisions differ FOR REASONS: our objectives carry 3 dp, K's
        # published comparator carries the 1 dp THEY printed, and forcing those together would
        # misrepresent their precision. The percentages are one kind and must agree -- declaring
        # them caught `published-over-one-car-pct` at 1 dp against the other two at 2 dp, which
        # was a real split rendering hidden inside a mixed-kind entry.
        # THE FOUR ENTRIES REGISTERED 2026-09-16. Each mixes kinds, and the declarations below
        # are deliberately COARSE: every key left undeclared falls into one `_default` group and
        # must agree there, so declaring less is the STRICTER choice. Single-key kinds would pass
        # trivially and are not used.
        #
        # `threshold-pct` and `largest-from-pct` are SINGLE gaps as K PRINTED THEM -- integers.
        # The averaged `avg-*-from-pct` keys are our own means over those integers and carry a
        # decimal honestly. Same reasoning as `rc208-one-car` below: forcing K's published
        # precision to match our derived precision would misrepresent theirs. Everything else in
        # this entry -- our percentages, percentage points, and the spread factor -- stays in
        # `_default` and is checked to agree at 1 dp.
        "ab-tightens-k-gaps": {"ab-widest-family-n": "count", "k-narrowest-family-n": "count",
                               "ab-widest-family-sd-n": "count",
                               "k-narrowest-family-sd-n": "count",
                               "n20-cells": "count", "n30-cells": "count",
                               "largest-size": "count",
                               "threshold-pct": "k-published-pct",
                               "largest-from-pct": "k-published-pct",
                               "ab-widest-family-spread": "cost-spread",
                               "k-narrowest-family-spread": "cost-spread"},
        # Only the cell counts are declared. All 30 remaining keys -- closed percentages, nominal
        # gains and closable amounts -- share `_default` and must agree at 1 dp.
        "gap-closed-by-family": {k: "count" for k in
                                 ("n20-C-cells", "n20-R-cells", "n20-RC-cells",
                                  "n30-C-cells", "n30-R-cells", "n30-RC-cells",
                                  "n50-pooled-cells",
                                  "n100-C-cells", "n100-R-cells", "n100-RC-cells")},
        # Ratios at 3 dp against the cost-valued dual bounds they are ratios OF. Two genuinely
        # different quantities, not one rendered two ways.
        "lb-over-kdual-n100": {"C-kdual": "kdual-cost", "R-kdual": "kdual-cost",
                               "RC-kdual": "kdual-cost"},
        # THE ONE JUDGEMENT CALL HERE, and it is flagged rather than buried. The medians (1.84 s,
        # 3.31 s) and the maxima (186 s, 1495 s) are the SAME UNIT -- seconds -- which is exactly
        # the shape this check treats as a real split rendering, and the precedent above is that
        # `wls-sensitivity` had such a case FIXED rather than declared away.
        #
        # It is declared here because the entry is consistent in SIGNIFICANT FIGURES, which is the
        # right convention for a quantity spanning three orders of magnitude: 1.84, 3.31, 186 and
        # 1495 are all three or four significant figures. Common decimal places would either
        # invent precision in the tail (186.00 s) or destroy the headline, and 1.84 s is quoted as
        # such in three prose documents and in RT_RAW_METRICS_CATALOGUE.
        #
        # This check cannot express significant figures, so the kind is what records the reason.
        "lb-time-to-exceed-k": {"n20-max-s": "tail-seconds", "n30-max-s": "tail-seconds"},
        # M6. The two RATIOS -- mean-ratio and worst-ratio -- are left in `_default` and must
        # agree at 3 dp, which is the comparison the entry exists for.
        #
        # `old-mean-ratio` is the SUPERSEDED value and is its own kind because it is preserved at
        # the precision the claim register kept it, two decimals, and CANNOT be recovered at
        # three: rt_fair_pipeline.py stage 1 rewrote the twelve pre-M6 artifacts in place and
        # runs/ is gitignored. Rendering it as 1.590 would assert a digit we do not have.
        "m6-matched-budget": {"cells": "count",
                              "old-mean-ratio": "superseded-record",
                              "masters-growth-min": "growth-factor",
                              "masters-growth-median": "growth-factor",
                              "masters-growth-max": "growth-factor",
                              "budget-cap-s": "budget-s",
                              "budget-floor-s": "budget-s"},
        # Every key here is a COUNT of cells or cars except the published mean, which is
        # K's own printed figure at their precision.
        "n20-fleet-total": {"k-published-mean": "k-published"},
        "rc208-one-car": {"cars": "count", "vessels": "count",
                          "value": "ours-obj", "two-car-value": "ours-obj",
                          "comparator": "k-published", "fleet-street": "component",
                          "improvement-pct": "pct", "published-over-two-car-pct": "pct",
                          "published-over-one-car-pct": "pct"},
        # TEP headline entries (2026-09-26). Counts of cells are counts; gaps vs K are percentages at 2 dp as in the
        # per-cell tables; brackets (bound-to-incumbent) are quoted at 1 dp as in the same tables and are their own
        # kind; objective values are quoted at 1 dp because K publish one decimal; cell names and yes/no are text.
        "tep-n10-attainment": {"cells": "count", "within-1pct": "count", "worst-cell": "cell-name"},
        "tep-n20-split": {"proven-cells": "count", "open-cells": "count", "open-cells-with-bound": "count", "proven-within-1pct": "count",
                          "open-within-1pct": "count", "open-below-k": "count", "open-bound-above-k": "count",
                          "proven-worst-cell": "cell-name", "open-worst-cell": "cell-name",
                          "open-bracket-ours": "bracket-pct", "open-bracket-k": "bracket-pct"},
        "tep-n30-split": {"proven-cells": "count", "open-cells": "count", "open-cells-with-bound": "count", "proven-within-1pct": "count",
                          "open-within-1pct": "count", "open-below-k": "count", "open-bound-above-k": "count",
                          "proven-worst-cell": "cell-name", "open-worst-cell": "cell-name",
                          "open-bracket-ours": "bracket-pct", "open-bracket-k": "bracket-pct"},
        "tep-n30-fine-delta": {"cells": "count", "proven-at-d5": "count", "unproven": "count"},
        "tep-n50-pool": {"cells": "count", "ceil-chosen": "count", "our-mean": "ours-obj", "k-pool-best": "k-published", "k-pool": "text"},
        "tep-n100-family": {"c-cells": "count", "r-cells": "count", "rc-cells": "count",
                            "c-ours": "ours-obj", "r-ours": "ours-obj", "rc-ours": "ours-obj",
                            "c-k": "k-published", "r-k": "k-published", "rc-k": "k-published",
                            "c-lb-certified": "text", "r-lb-certified": "text", "rc-lb-certified": "text",
                            "c-lb-ratio": "ratio", "r-lb-ratio": "ratio", "rc-lb-ratio": "ratio",
                            "c-our-gap": "bracket-pct", "r-our-gap": "bracket-pct", "rc-our-gap": "bracket-pct",
                            "c-k-gap": "bracket-pct", "r-k-gap": "bracket-pct", "rc-k-gap": "bracket-pct"},
        "tep-coverage": {"uncovered": "count", "sizes": "count"},
        # TEP BODY RESULT ENTRIES (2026-10-09). Registered for §6 and written before their kinds;
        # each mixes genuinely different quantities, declared here so C3 checks like against like.
        # budget-sens: a seconds floor and a coarse integer factor-ceiling are each their own kind;
        # the precise hardware factors agree at 1 dp; every degradation percentage/pp stays in
        # _default at 1 dp.
        "budget-sens": {"cap-floor-s": "budget-s", "f-all-derived": "factor-ceiling",
                        "f-max": "factor", "f-max-n50": "factor"},
        # longrt-n50: the two gaps (fair-gap, full-gap) are one kind in _default and agree at 1 dp;
        # the hundredths-of-a-point delta and the budget multiple are their own kinds; counts are counts.
        "longrt-n50": {"cells": "count", "cells-improved": "count",
                       "delta-pp": "pp-fine", "max-mult": "budget-factor"},
        # lb-vs-k: cell counts are counts; the LB ratios and matched-pairs effect sizes agree at
        # 2 dp in _default. (wins/p-values/ranges are text and are skipped by the fullmatch guard.)
        "lb-vs-k": {"k-stronger-cells": "count", "n20-open-cells": "count",
                    "n30-open-cells": "count"},
        # primal: the dual-only cell count is a count; the near-zero median slip carries 3 dp
        # honestly (0.003 cannot render at 2 dp), so it is its own kind; mean and max slip agree at
        # 2 dp in _default.
        "primal": {"dualonly-cells": "count", "n10-median-slip": "fine-slip"},
        # protocol: threads is a count, the budget is seconds, the hardware factor is a 1 dp factor
        # in _default -- three distinct quantities, one key each.
        "protocol": {"bound-threads": "count", "budget-s": "budget-s"},
    }
    for nid, d in (json.load(open(np_)).items() if os.path.exists(np_) else []):
        if str(nid).startswith("_") or nid == "sources":
            continue
        v = d["value"]
        if not isinstance(v, dict):
            continue
        groups = KEY_GROUPS.get(nid, {})
        by_kind = collections.defaultdict(lambda: collections.defaultdict(list))
        for k, kv in v.items():
            s = str(kv)
            if NUM_RE.fullmatch(s):
                by_kind[groups.get(k, "_default")][rendered(s)].append(f"{k}={s}")
        for kind, widths in sorted(by_kind.items()):
            if len(widths) > 1:
                flat = "; ".join(f"{w} dp: {', '.join(x)}" for w, x in sorted(widths.items()))
                where = "" if kind == "_default" else f" [kind: {kind}]"
                problems.append(
                    f"C3 {nid} renders its own keys inconsistently{where} -- {flat}")

    print(f"NUMBER-CONSISTENCY CHECK   "
          f"{len(seen)} distinct values across registry + {len(sources)} table file(s)")
    for w in warnings:
        print(f"  [warn] {w}")
        print(f"         whole number -- most likely two unrelated quantities sharing a value; "
              f"confirm by eye, not by this check")
    if problems:
        for p in problems:
            print(f"  [FAIL] {p}")
        print(f"\n  {len(problems)} problem(s). A quantity that reaches the page two ways is a "
              f"quantity a referee will ask about.")
        return 1
    print("  no split renderings, no hand-typed duplicates, no inconsistent entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
