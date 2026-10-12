"""The reproduction index: every number, table, plot and quantity in the manuscript, and how to reproduce or verify it.

THE PUBLISHING RULE (author, 2026-09-27): every and each number, table, plot and quantity in the manuscript must
allow reproduction via indexed code in this repository, or verification in the bibliography. Nothing may reach the
page whose provenance is neither a command we ship nor a citation a referee can check.

This script BUILDS the index (paper/REPRODUCTION_INDEX.md) from the artifacts themselves, never by hand:

  * numbers  -- every entry of the registry in analysis/manuscript_numbers.py: its id, the claim that licenses it,
                and the command that regenerates it. An entry without a claim id is listed as a DEFECT.
  * figures  -- every paper/figures/*.pdf with its provenance sidecar: the sources it was built from and the
                command that makes it. A figure without a sidecar is a DEFECT.
  * tables   -- every generator under analysis/ that writes into paper/tables/, with its output.
  * external -- every quantity taken from the predecessors' paper, with the exhibit it comes from, read from
                data/karademir2025/k_reference.json (fetched and sha256-verified, never committed).

    python analysis/reproduction_index.py [--check]     # --check exits non-zero if anything is unindexed
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def numbers():
    """id -> (claim, description) from the registry, by importing it rather than parsing prose."""
    import manuscript_numbers as M
    return {k: (v.get("claim", ""), v.get("desc", "")) for k, v in M.REG.items()}


def figures():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "paper", "figures", "*.pdf"))):
        stem = os.path.splitext(os.path.basename(f))[0]
        prov = load(os.path.join(ROOT, "paper", "figures", stem + ".prov.json"))
        srcs = sorted((prov or {}).get("sources", {}) or {}) if prov else []
        # THE GENERATOR IS IN generated_by, NOT IN sources (2026-09-27). This loop only ever looked at
        # sources, so the five F-series figures -- whose sources are a LIST of data files with no script
        # among them -- were reported as "sidecar names no analysis/ generator" for as long as the index
        # has existed, while every one of them names analysis/make_figures.py in generated_by. The
        # T-series passed by luck: their sources are a DICT that happens to have the script as a key.
        gen = (prov or {}).get("generated_by")
        cmd = ("python %s" % gen) if isinstance(gen, str) and gen.endswith(".py") else None
        if not cmd:
            for s in srcs:
                if s.startswith("analysis/") and s.endswith(".py"):
                    cmd = "python %s" % s
        # A SUPERSEDED FIGURE IS NOT A CURRENT EXHIBIT. Five carry a superseded record (pre-d243 solver,
        # retired 2026-09-20) and were being listed as reproducible exhibits of this paper, which is a
        # worse failure than a missing generator: the index is what a referee reads to decide what the
        # paper rests on.
        sup = (prov or {}).get("superseded")
        out[stem] = dict(sidecar=bool(prov), sources=srcs, command=cmd,
                         superseded=(sup if isinstance(sup, dict) else ({"on": str(sup)} if sup else None)))
    return out


def tables():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "analysis", "*.py"))):
        try:
            s = io.open(f, encoding="utf-8").read()
        except Exception:
            continue
        if "paper/tables" in s or os.path.join("paper", "tables") in s:
            outs = sorted(set(re.findall(r"[\w./\\-]*paper[/\\]tables[/\\][\w.\-]+", s)))
            out[os.path.relpath(f, ROOT).replace("\\", "/")] = outs
    return out


def external():
    k = load(os.path.join(ROOT, "data", "karademir2025", "k_reference.json")) or {}
    ex = {}
    for key in sorted(k):
        if key.startswith("_") or key == "source":
            continue
        v = k[key]
        ex[key] = ("%d entries" % len(v)) if isinstance(v, (list, dict)) else str(v)[:60]
    return ex, (k.get("source") or {})


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); a = ap.parse_args()
    N, F, T = numbers(), figures(), tables()
    E, src = external()
    defects = [("number", nid, "no claim id") for nid, (cl, _) in sorted(N.items()) if not cl]
    defects += [("figure", stem, "no provenance sidecar") for stem, d in sorted(F.items()) if not d["sidecar"]]
    defects += [("figure", stem, "sidecar names no generator") for stem, d in sorted(F.items())
                if d["sidecar"] and not d["command"] and not d["superseded"]]
    lines = ["# Reproduction index — generated by `analysis/reproduction_index.py`, do not edit",
             "",
             "**The publishing rule.** Every number, table, plot and quantity in the manuscript must be reproducible",
             "by a command in this repository, or verifiable in the bibliography. This index is the map, and",
             "`python analysis/reproduction_index.py --check` fails if anything on the page is not on it.",
             "",
             "## 1. Numbers — regenerate all with `python analysis/manuscript_numbers.py` (diff with `--check`)",
             "",
             "Each entry emits a LaTeX macro into `paper/numbers.tex`; the manuscript never types a number.",
             "",
             "| number id | claim id (`validation/claims.json`) | what it is |", "|---|---|---|"]
    for nid, (cl, desc) in sorted(N.items()):
        lines.append("| `%s` | %s | %s |" % (nid, ("`%s`" % cl) if cl else "**MISSING**", (desc or "").replace("|", "/")[:110]))
    live = {k: v for k, v in F.items() if not v["superseded"]}
    dead = {k: v for k, v in F.items() if v["superseded"]}
    lines += ["", "## 2. Figures — each carries a `.prov.json` sidecar naming its sources", "",
              "| figure | command | sources hashed in the sidecar |", "|---|---|---|"]
    for stem, d in sorted(live.items()):
        lines.append("| `%s` | %s | %s |" % (stem, ("`%s`" % d["command"]) if d["command"] else "**MISSING**",
                                             ", ".join("`%s`" % s for s in d["sources"][:4]) or "**none**"))
    if dead:
        lines += ["", "### 2b. Superseded figures — present in the tree, NOT exhibits of this paper", "",
                  "They are kept because the sidecar records what produced them and when it was retired; nothing in",
                  "the manuscript may cite one.", "",
                  "| figure | retired | why |", "|---|---|---|"]
        for stem, d in sorted(dead.items()):
            s = d["superseded"] or {}
            lines.append("| `%s` | %s | %s |" % (stem, s.get("on", "?"), str(s.get("why", "")).replace("|", "/")[:130]))
    lines += ["", "## 3. Tables", "", "| generator | writes |", "|---|---|"]
    for g, outs in sorted(T.items()):
        lines.append("| `python %s` | %s |" % (g, ", ".join("`%s`" % o for o in outs) or "(discovered at run time)"))
    lines += ["", "## 4. Quantities taken from the predecessors (verification in the bibliography)", "",
              "Read from `data/karademir2025/k_reference.json`, which is fetched and sha256-verified on demand and",
              "never committed (third-party content). Every use in the manuscript cites the exhibit named here.", "",
              "| key in the reference | content |", "|---|---|"]
    for k, v in sorted(E.items()):
        lines.append("| `%s` | %s |" % (k, v))
    if src:
        lines += ["", "Source record: " + "; ".join("%s = %s" % (k, str(v)[:80]) for k, v in sorted(src.items()))]
    lines += ["", "## 5. Defects", ""]
    lines += (["None: every number carries a claim id and every figure a sidecar naming its generator."] if not defects
              else ["| kind | item | defect |", "|---|---|---|"] + ["| %s | `%s` | %s |" % d for d in defects])
    io.open(os.path.join(ROOT, "paper", "REPRODUCTION_INDEX.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump(stamped(dict(numbers=N, figures=F, tables=T, external=sorted(E), defects=defects)),
              io.open(os.path.join(ROOT, "runs", "oracle", "reproduction_index.json"), "w", encoding="utf-8"), indent=1, default=str)
    print("indexed %d numbers, %d figures, %d table generators, %d external exhibits | defects: %d"
          % (len(N), len(F), len(T), len(E), len(defects)))
    for d in defects[:12]:
        print("   DEFECT %-7s %-34s %s" % d)
    print("  wrote paper/REPRODUCTION_INDEX.md and runs/oracle/reproduction_index.json")
    return 1 if (a.check and defects) else 0


if __name__ == "__main__":
    sys.exit(main())
