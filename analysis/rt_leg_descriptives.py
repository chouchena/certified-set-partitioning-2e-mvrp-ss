"""RT-leg descriptives: the host manifest, and our run time by size and family.

Closes items 2 and 3 of `validation/RT_LEG_DESIGN.md` section 5. Both are analysis over artifacts
we already hold; neither is a run.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR. `RT_LEG_DESIGN.md` section 6 is explicit: report the
elapsed-share ratio, the >=3-order separation and budget utilisation; report deterministic
budgets as reproducibility rather than comparison; DEFER seconds-to-target and speedups; and
NEVER our-budget-over-their-limit or any per-cell RT claim at n50/n100.

So the run-time means below are **descriptive**, to sit beside K's published Run-time row
mean-to-mean. They are NOT a speed claim and cannot become one, because **our totals are bounded
by our own per-cell budget while K's are not.** That is why every mean here is printed with its
budget utilisation: a mean of 955 s against a 1200 s cap says something quite different from the
same mean against a 14400 s cap, and the number alone does not distinguish them.

THE HOST MANIFEST exists so that Tier 2 is *possible* later, not because we are doing Tier 2. It
records what a hardware normalisation would need and, just as usefully, what varied across our
own campaign -- the thread count is not constant across every run in `provenance.csv`, and a
reader comparing run times deserves to know that before we do.

USAGE
    python analysis/rt_leg_descriptives.py            # write the report
    python analysis/rt_leg_descriptives.py --check    # recompute and diff; non-zero on drift
"""
import os, sys, csv, json, glob, argparse, platform, subprocess, datetime, collections
import statistics as st
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_MD = os.path.join(ROOT, "validation", "RT_LEG_DESCRIPTIVES.md")
OUT_JSON = os.path.join(ROOT, "validation", "RT_LEG_DESCRIPTIVES.json")
SIZES = (20, 30, 50, 100)

# Suffixed artifacts are superseded variants kept on disk; the same exclusion `manuscript_numbers`
# applies, and it must stay in step with it or the two will describe different cell sets.
EXCLUDE = ("noprov", "kcapbug", "tl450", "detl", "_bq")


def _fam(cell):
    return "RC" if cell.startswith("RC") else cell[0]


def descents(size):
    """Per cell: total wall, time-to-best, elapsed share, budget, threads.

    TOTAL RT *AND* TIME-TO-BEST, because they answer different questions and only one of them
    is safe to compare.

      * TOTAL WALL sits beside K's published Run-time row (`RT_LEG_DESIGN` §5 item 2). It is
        bounded by our own per-cell budget, so it is descriptive and never a speed claim.
      * TIME-TO-BEST is what Tier 1 item 1a needs -- "share of the run elapsed at the best
        solution", a ratio INTERNAL to each run. That ratio is hardware-free and is explicitly
        reportable; the raw seconds are not, being seconds-to-target, which §6 defers.

    Time-to-best is taken as the END of the record that first attains the cell's best
    `block_relax` -- `t_start + wall`. The finer `lb_curve` inside a record would place it
    earlier; taking the record end is the CONSERVATIVE choice, since it can only make our
    elapsed share look worse, never better.
    """
    out = []
    for f in sorted(glob.glob(os.path.join(
            ROOT, "crossfeed", f"easy_reduction_descend_*_n{size}.json"))):
        b = os.path.basename(f)
        if any(x in b for x in EXCLUDE):
            continue
        cell = b.split("descend_")[1].split(f"_n{size}")[0]
        try:
            recs = json.load(open(f))
        except Exception:
            continue
        if not recs:
            continue
        wall = sum((r.get("wall") or 0.0) for r in recs)
        budgets = {r.get("cell_budget") for r in recs if r.get("cell_budget")}
        threads = {r.get("threads") for r in recs if r.get("threads")}

        # Time-to-best: the end of the record that first attains the cell's best block_relax,
        # walking the records in the order the descent actually ran them (by t_start).
        ordered = sorted((r for r in recs if r.get("block_relax") is not None),
                         key=lambda r: (r.get("t_start") if r.get("t_start") is not None else 0.0))
        best, ttb = None, None
        for r in ordered:
            v = r["block_relax"]
            if best is None or v > best:
                best = v
                ttb = (r.get("t_start") or 0.0) + (r.get("wall") or 0.0)
        share = (ttb / wall) if (ttb is not None and wall > 0) else None

        out.append({"cell": cell, "wall": wall, "ttb": ttb, "share": share,
                    "best": best,
                    "budget": (max(budgets) if budgets else None),
                    "threads": (sorted(threads) if threads else [])})
    return out


def cpu_model():
    """Best-effort CPU name of the CURRENT host. Marked as captured-now, never back-dated."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def host_manifest():
    """What every run recorded about where it ran, consolidated."""
    rows = list(csv.DictReader(open(os.path.join(ROOT, "runs", "provenance.csv"))))
    m = {"runs_recorded": len(rows)}
    for col in ("host", "platform", "py", "git_branch", "cores"):
        m[col] = dict(collections.Counter(r[col] for r in rows if r.get(col)))
    dates = sorted(r["closed_at"][:10] for r in rows if r.get("closed_at"))
    m["provenance_covers"] = [dates[0], dates[-1]] if dates else None

    # SOLVER VERSIONS come from the descent records, not provenance.csv: that file's `solver`
    # column is populated on only a handful of rows, whereas every descent record carries the
    # cplex and docplex versions it actually ran against.
    cplex, docplex = collections.Counter(), collections.Counter()
    for size in SIZES:
        for f in glob.glob(os.path.join(ROOT, "crossfeed",
                                        f"easy_reduction_descend_*_n{size}.json")):
            if any(x in os.path.basename(f) for x in EXCLUDE):
                continue
            try:
                recs = json.load(open(f))
            except Exception:
                continue
            for r in recs:
                if r.get("cplex"):
                    cplex[str(r["cplex"])] += 1
                if r.get("docplex"):
                    docplex[str(r["docplex"])] += 1
    m["cplex"] = dict(cplex)
    m["docplex"] = dict(docplex)
    m["cpu_model_current_host"] = cpu_model()
    m["captured_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return m


def rt_table():
    """Mean and median total descent wall, by size and by family, with budget utilisation."""
    out = {}
    for size in SIZES:
        rows = descents(size)
        if not rows:
            continue
        per_fam = collections.defaultdict(list)
        util = [r["wall"] / r["budget"] for r in rows if r["budget"]]

        # THE ELAPSED SHARE IS ONLY MEANINGFUL ON A RUN THAT ENDED ON ITS OWN.
        # share = time-to-best / total wall. On a truncated run the DENOMINATOR is set by an
        # arbitrary cap rather than by the descent's own termination, so the ratio answers
        # "how far into the cap did the best arrive" instead of "how far into a completed
        # search". Mixing the two pools incommensurable denominators.
        #
        # THE DIRECTION OF THE BIAS WAS MEASURED, NOT ASSUMED, and it is the opposite of what
        # it first looks like. At n100 the truncated cells ran LONGER (mean wall 2580 s
        # against 1686 s free) because they ran to the cap, while their time-to-best was only
        # a little later (1231 s against 1054 s). So their share is LOWER, 0.49 against 0.59,
        # and excluding them RAISES the mean from 0.55 to 0.59. The first version of this
        # comment claimed truncation inflates the share "because a run cut off just after its
        # best scores near 1.0" -- plausible, and wrong here.
        #
        # Computed over BUDGET-FREE cells only; the truncated count is reported beside it so
        # the exclusion is visible rather than silent.
        free = [r for r in rows if not (r["budget"] and r["wall"] >= 0.9 * r["budget"])]
        shares = [r["share"] for r in free if r["share"] is not None]
        for r in rows:
            per_fam[_fam(r["cell"])].append(r)
        entry = {"n_cells": len(rows),
                 "mean_s": round(st.mean(r["wall"] for r in rows), 1),
                 "median_s": round(st.median([r["wall"] for r in rows]), 1),
                 "ttb_mean_s": round(st.mean(r["ttb"] for r in rows if r["ttb"] is not None), 1),
                 "elapsed_share_mean": (round(st.mean(shares), 3) if shares else None),
                 "elapsed_share_n": len(shares),
                 "elapsed_share_excluded_truncated": len(rows) - len(free),
                 "elapsed_share_median": (round(st.median(shares), 3) if shares else None),
                 "threads": sorted({t for r in rows for t in r["threads"]}),
                 "budget_utilisation_mean": (round(st.mean(util), 3) if util else None),
                 # THE BUDGET IS NOT UNIFORM and the means are uninterpretable without this.
                 # n100 runs on 2400 s -- a quarter of n50's -- so its high utilisation is a
                 # small denominator, not diligence; and n30 pools two different budgets, so a
                 # single n30 mean averages cells that were not given the same chance.
                 # STRING KEYS, deliberately. JSON coerces dict keys to strings on write, so a
                 # float-keyed dict never equals its own reload and `--check` reported drift
                 # against a file it had just written. The check caught it; the defect was the
                 # check's own round-trip, not the data.
                 "cell_budgets": dict(collections.Counter(
                     str(int(r["budget"])) for r in rows if r["budget"])),
                 "cells_over_budget": sum(
                     1 for r in rows if r["budget"] and r["wall"] > r["budget"]),
                 "by_family": {}}
        for fam in ("C", "R", "RC"):
            v = per_fam.get(fam)
            if v:
                sh = [r["share"] for r in v
                      if r["share"] is not None
                      and not (r["budget"] and r["wall"] >= 0.9 * r["budget"])]
                entry["by_family"][fam] = {
                    "n": len(v),
                    "mean_s": round(st.mean(r["wall"] for r in v), 1),
                    "median_s": round(st.median([r["wall"] for r in v]), 1),
                    "ttb_mean_s": round(st.mean(r["ttb"] for r in v if r["ttb"] is not None), 1),
                    "elapsed_share_mean": (round(st.mean(sh), 3) if sh else None)}
        out[f"n{size}"] = entry
    return out


def build():
    return {"host_manifest": host_manifest(), "run_time": rt_table()}


def render(d):
    h, rt = d["host_manifest"], d["run_time"]
    L = []
    L.append("# RT-leg descriptives — host manifest and run time by size and family")
    L.append("")
    L.append("**GENERATED by `analysis/rt_leg_descriptives.py`. Do not edit.**")
    L.append("Closes items 2 and 3 of `validation/RT_LEG_DESIGN.md` §5.")
    L.append("")
    L.append("> **These are descriptives, not a speed claim, and cannot become one.** Our totals")
    L.append("> are bounded by our own per-cell budget while K's are not, which is why each mean")
    L.append("> is printed with its budget utilisation. `RT_LEG_DESIGN.md` §6: never")
    L.append("> our-budget-over-their-limit, and no per-cell RT claim at n50 or n100.")
    L.append("")
    L.append("## Host manifest")
    L.append("")
    L.append(f"* runs recorded in `provenance.csv`: **{h['runs_recorded']}**, "
             f"covering {h['provenance_covers'][0]} to {h['provenance_covers'][1]}")
    L.append(f"* host: {h['host']}")
    L.append(f"* platform: {h['platform']}")
    L.append(f"* CPU (current host, captured now): **{h['cpu_model_current_host'] or 'unavailable'}**")
    L.append(f"* python: {h['py']}")
    L.append(f"* CPLEX: {h['cplex'] or 'not recorded'}")
    L.append(f"* docplex: {h['docplex'] or 'not recorded'}")
    L.append(f"* cores recorded per run: {h['cores']}")
    L.append("")
    L.append("**The core count is not constant across the campaign** — most runs at 4, a minority")
    L.append("at 2 and one at 1. Anyone comparing run times across the whole of `provenance.csv`")
    L.append("must account for that. The descent artifacts below are uniform at 4 threads, which")
    L.append("is also the four CPUs K report, so the table that follows is internally consistent.")
    L.append("")
    L.append("## Total run time by size and family")
    L.append("")
    L.append("Total wall per cell, summed over every block solve the descent performed. This is")
    L.append("the quantity that sits beside K's published **Run time** row. It is bounded by our")
    L.append("own per-cell budget, which is why the utilisation column is not optional.")
    L.append("")
    L.append("| size | cells | mean (s) | median (s) | C mean | R mean | RC mean | budget used |")
    L.append("|---|---|---|---|---|---|---|---|")
    for k in [f"n{s}" for s in SIZES]:
        e = rt.get(k)
        if not e:
            continue
        f = e["by_family"]
        cell = lambda x: (f"{f[x]['mean_s']:.0f}" if x in f else "-")
        util = (f"{100*e['budget_utilisation_mean']:.0f}%"
                if e["budget_utilisation_mean"] is not None else "-")
        L.append(f"| {k} | {e['n_cells']} | {e['mean_s']:.0f} | {e['median_s']:.0f} | "
                 f"{cell('C')} | {cell('R')} | {cell('RC')} | {util} |")
    L.append("")
    L.append("### The budget is NOT uniform across sizes, and the means mean little without it")
    L.append("")
    L.append("| size | cell budget (s) | cells over budget |")
    L.append("|---|---|---|")
    for k in [f"n{s}" for s in SIZES]:
        e = rt.get(k)
        if not e:
            continue
        b = ", ".join(f"{v} x{n}" for v, n in sorted(e["cell_budgets"].items(), key=lambda kv: int(kv[0])))
        L.append(f"| {k} | {b} | {e['cells_over_budget']} |")
    L.append("")
    L.append("Two consequences a reader must not have to derive for themselves:")
    L.append("")
    L.append("* **n100 has the smallest budget of any size, on the largest instances.** Its high")
    L.append("  utilisation is a small denominator, not diligence. Any statement that the bound")
    L.append("  degrades with size is **partly a statement about budget**, and the two are")
    L.append("  confounded here. That caveat belongs wherever the degradation is discussed.")
    L.append("* **n30 pools two budgets**, so a single n30 mean averages cells that were not")
    L.append("  given the same chance. Split it before quoting it.")
    L.append("")
    L.append("Cells recorded over budget exceeded it because the budget is checked *between*")
    L.append("block solves, so the solve in progress runs to its own limit first.")
    L.append("")
    L.append("## Time to best, and the elapsed-share ratio (Tier 1, item 1a)")
    L.append("")
    L.append("Time to best is the end of the record that first attains the cell's best bound.")
    L.append("**The seconds are descriptive and are not to be compared** -- that is")
    L.append("seconds-to-target, which `RT_LEG_DESIGN` §6 defers. **The share is the reportable")
    L.append("statistic**: a ratio internal to each run, so it carries no hardware claim.")
    L.append("")
    L.append("**Computed over budget-FREE cells only.** On a truncated run the denominator is")
    L.append("set by an arbitrary cap rather than by the search ending, so the ratio answers a")
    L.append("different question and the two pools are incommensurable. At n100 the truncated")
    L.append("cells ran longer (mean 2580 s against 1686 s) for a time-to-best only slightly")
    L.append("later, so their share is *lower*, 0.49 against 0.59 -- excluding them RAISES the")
    L.append("mean. The n100 figure becomes trustworthy only once those ten are budget-free.")
    L.append("")
    L.append("| size | time-to-best mean (s) | elapsed share mean | median | n | truncated, excluded | C | R | RC |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for k in [f"n{s}" for s in SIZES]:
        e = rt.get(k)
        if not e:
            continue
        f = e["by_family"]
        sh = lambda x: (f"{f[x]['elapsed_share_mean']:.2f}"
                        if x in f and f[x]["elapsed_share_mean"] is not None else "-")
        L.append(f"| {k} | {e['ttb_mean_s']:.0f} | {e['elapsed_share_mean']:.2f} | "
                 f"{e['elapsed_share_median']:.2f} | {e['elapsed_share_n']} | "
                 f"{e['elapsed_share_excluded_truncated']} | {sh('C')} | {sh('R')} | {sh('RC')} |")
    L.append("")
    L.append("Threads: " + ", ".join(f"{k} -> {rt[k]['threads']}" for k in rt))
    L.append("")
    L.append(f"_Captured {h['captured_at']}._")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="recompute and diff against the stored JSON; non-zero on drift")
    a = ap.parse_args()

    d = build()
    # `captured_at` and the live CPU probe move every run by design; everything else is the
    # measurement and must not.
    volatile = {"captured_at", "cpu_model_current_host"}
    if a.check:
        if not os.path.exists(OUT_JSON):
            print("no stored JSON; run without --check first")
            return 1
        old = json.load(open(OUT_JSON))
        a_ = {k: v for k, v in old["host_manifest"].items() if k not in volatile}
        b_ = {k: v for k, v in d["host_manifest"].items() if k not in volatile}
        if a_ != b_ or old["run_time"] != d["run_time"]:
            print("DRIFT against the stored descriptives")
            return 1
        print("OK: descriptives unchanged")
        return 0

    json.dump(stamped(d, __file__), open(OUT_JSON, "w"), indent=2, sort_keys=True)
    open(OUT_MD, "w", encoding="utf-8").write(render(d))
    # Console is cp1252 here; the FILE is utf-8. Print an ascii-safe echo rather
    # than the rendered markdown, which died on an arrow glyph.
    print(render(d).encode('ascii', 'replace').decode('ascii'))
    return 0


if __name__ == "__main__":
    sys.exit(main())
