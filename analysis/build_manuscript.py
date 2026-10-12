r"""Flatten paper/manuscript/main.tex into the SINGLE-FILE submission the publisher requires.

THE CONFLICT THIS RESOLVES. The Springer Nature template says, at the top of its own sample
file: "Please do not use \input{...} to include other tex files. Submit your LaTeX manuscript
as one .tex document." Our replicability rule (paper/REPLICABILITY.md) says no number, table or
figure may be typed by hand -- which is exactly what \input is for. Obeying the publisher by
hand would mean pasting generated values into prose, and every one of them would then rot
silently the next time an artifact moved.

So we author with \input and flatten mechanically. The submission is one file, the source is
replicable, and no human ever retypes a number.

WHAT IT DOES
  1. recursively inlines \input / \include, resolving relative to main.tex
  2. copies every \includegraphics target into the submission directory, FLAT, and rewrites
     the path -- the publisher wants figures as separate attachments, not in subdirectories
  3. copies the class file, the .bst and the .bbl (the publisher needs the .bbl: they do not
     re-run BibTeX)
  4. COMPILES the result and fails if it does not build
  5. checks the things a desk editor checks: abstract length, keyword count, leftover TODO,
     heading depth, and that no \input survived

Every check FAILS THE COMMAND rather than printing advice, for the same reason the release
gate does.
"""
import os, re, sys, shutil, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "paper", "manuscript")
OUT = os.path.join(SRC, "submission")

INPUT_RE = re.compile(r"^([^%\n]*?)\\(?:input|include)\{([^}]+)\}", re.M)
GRAPHIC_RE = re.compile(r"\\includegraphics(\[[^\]]*\])?\{([^}]+)\}")

# AOR, publisher-verified. paper/VENUE_AOR_REQUIREMENTS.md section 2.
ABSTRACT_WORDS = (150, 250)
KEYWORDS = (4, 6)
MAX_HEADING_DEPTH = 3          # decimal system, maximum three levels


def flatten(path, seen, depth=0):
    """Inline \\input/\\include depth-first. `seen` catches an include cycle."""
    real = os.path.realpath(path)
    if real in seen:
        raise RuntimeError(f"\\input cycle through {os.path.relpath(path, SRC)}")
    seen = seen | {real}
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    def sub(m):
        prefix, target = m.group(1), m.group(2)
        if prefix.strip().startswith("%"):
            return m.group(0)
        # Resolve relative to the manuscript ROOT (SRC), NOT the including file's directory, so a
        # nested \input inside a section inlines the SAME file a direct pdflatex of the authoring
        # main.tex would: LaTeX resolves \input against the main job directory, not the subfolder
        # of the file doing the \input. Section inputs (`sections/XX`) are unaffected; a table
        # fragment in paper/tables is reached as `../tables/XX` from paper/manuscript, in both.
        child = os.path.join(SRC, target)
        if not child.endswith(".tex"):
            child += ".tex"
        if not os.path.exists(child):
            raise RuntimeError(f"\\input{{{target}}} not found (from "
                               f"{os.path.relpath(path, SRC)})")
        rel = os.path.relpath(child, SRC).replace(os.sep, "/")
        body = flatten(child, seen, depth + 1)
        return (f"{prefix}%% >>> inlined from {rel} by analysis/build_manuscript.py\n"
                f"{body}\n%% <<< end {rel}")

    return INPUT_RE.sub(sub, text)


def collect_figures(text):
    """Copy artwork flat into the submission dir and rewrite the paths to match."""
    os.makedirs(OUT, exist_ok=True)
    copied = []

    def sub(m):
        opts, target = m.group(1) or "", m.group(2)
        cand = [os.path.join(SRC, target), os.path.join(ROOT, target)]
        if not os.path.splitext(target)[1]:
            cand = [c + e for c in list(cand) for e in (".pdf", ".eps", ".png")]
        src = next((c for c in cand if os.path.exists(c)), None)
        if src is None:
            raise RuntimeError(f"\\includegraphics{{{target}}}: no such file")
        base = os.path.basename(src)
        shutil.copy2(src, os.path.join(OUT, base))
        copied.append(base)
        return f"\\includegraphics{opts}{{{base}}}"

    return GRAPHIC_RE.sub(sub, text), copied


def strip_comments(text):
    r"""Drop LaTeX comments before checking.

    Not cosmetic: the first version of these checks reported "an \input survived flattening"
    because the generated banner SAYS the word \input, and the inlined-from markers say it
    once per section. A check that fires on its own prose is worse than no check -- it trains
    you to ignore it.
    """
    out = []
    for line in text.split("\n"):
        i, n = 0, len(line)
        while i < n:
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                line = line[:i]
                break
            i += 1
        out.append(line)
    return "\n".join(out)


def braced(text, macro):
    r"""Extract the balanced argument of \macro{...}. A greedy regex read our two-line
    placeholder abstract as 374 words, because it ran to the last brace in the file."""
    m = re.search(r"\\" + macro + r"\{", text)
    if not m:
        return None
    i, depth = m.end(), 1
    while i < len(text) and depth:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        depth += (c == "{") - (c == "}")
        i += 1
    return text[m.end():i - 1]


def checks(raw):
    """The things a desk editor checks. Each one is a hard failure, not a note."""
    bad = []
    text = strip_comments(raw)

    body = braced(text, "abstract")
    if body is None:
        bad.append("no \\abstract found")
    else:
        w = len(re.sub(r"\\[a-zA-Z]+|[{}]", " ", body).split())
        if not ABSTRACT_WORDS[0] <= w <= ABSTRACT_WORDS[1]:
            bad.append(f"abstract is {w} words; AOR requires "
                       f"{ABSTRACT_WORDS[0]}-{ABSTRACT_WORDS[1]}")

    m = re.search(r"\\keywords\{([^}]*)\}", text)
    if not m:
        bad.append("no \\keywords found")
    else:
        k = [x for x in m.group(1).split(",") if x.strip()]
        if not KEYWORDS[0] <= len(k) <= KEYWORDS[1]:
            bad.append(f"{len(k)} keywords; AOR requires {KEYWORDS[0]}-{KEYWORDS[1]}")

    deep = re.findall(r"\\(sub){%d,}section\b" % MAX_HEADING_DEPTH, text)
    if deep:
        bad.append(f"{len(deep)} heading(s) deeper than {MAX_HEADING_DEPTH} levels; AOR caps "
                   f"the decimal system at three -- split the section instead")

    if re.search(r"\\input\{|\\include\{", text):
        bad.append("an \\input survived flattening -- the submission must be ONE file")

    todo = len(re.findall(r"\bTODO\b", text))
    if todo:
        bad.append(f"{todo} TODO marker(s) remain")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-compile", action="store_true")
    ap.add_argument("--allow-todo", action="store_true",
                    help="build a DRAFT: report the desk-editor checks but do not fail on them")
    ap.add_argument("--name", default="main",
                    help="output basename for the flattened .tex and the PDF (e.g. main2 for a "
                         "versioned build); the SOURCE is always paper/manuscript/main.tex")
    a = ap.parse_args()
    out_tex = a.name + ".tex"

    main_tex = os.path.join(SRC, "main.tex")
    if not os.path.exists(main_tex):
        print("  no paper/manuscript/main.tex"); return 1

    print("  flattening")
    text = flatten(main_tex, frozenset())
    text, figs = collect_figures(text)
    text = ("%% GENERATED by analysis/build_manuscript.py -- DO NOT EDIT.\n"
            "%% Edit paper/manuscript/main.tex and its sections/, then rebuild.\n"
            "%% This is the SINGLE-FILE submission copy; the publisher's template forbids "
            "\\input.\n" + text)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, out_tex), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"  wrote paper/manuscript/submission/{out_tex} ({len(text.splitlines())} lines, "
          f"{len(set(figs))} figure file(s))")

    # The publisher wants the style files and the .bbl: they do not re-run BibTeX. The .bbl is
    # renamed to match the output basename so pdflatex <name> finds <name>.bbl.
    for f in ("sn-jnl.cls", "sn-apacite.bst"):
        p = os.path.join(SRC, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(OUT, f))
            print(f"  copied {f}")
        else:
            print(f"  [warn] {f} missing -- run analysis/fetch_springer_template.py")
    bbl = os.path.join(SRC, "main.bbl")
    if os.path.exists(bbl):
        shutil.copy2(bbl, os.path.join(OUT, a.name + ".bbl"))
        print(f"  copied main.bbl -> {a.name}.bbl")
    else:
        print("  [warn] main.bbl missing -- run bibtex before submitting")

    bad = checks(text)
    if bad:
        print("\n  DESK-EDITOR CHECKS:")
        for b in bad:
            print(f"    - {b}")
    else:
        print("\n  desk-editor checks: all pass")

    rc = 0
    if not a.no_compile:
        print("\n  compiling")
        # Three pdflatex passes against the copied .bbl: pass 1 writes \bibcite/\newlabel into
        # the .aux, passes 2-3 resolve \cite and \ref (and settle page references) from it. A
        # single pass leaves every citation undefined even with a correct .bbl present.
        r = None
        for _ in range(3):
            r = subprocess.run(["pdflatex", "-interaction=nonstopmode", out_tex],
                               cwd=OUT, capture_output=True, text=True)
        undef = sum(1 for l in r.stdout.splitlines()
                    if "Citation" in l and "undefined" in l) if r else 0
        if "Output written" not in (r.stdout if r else ""):
            print("  COMPILE FAILED:")
            for line in r.stdout.splitlines():
                if line.startswith("!") or "not found" in line:
                    print("   ", line)
            rc = 1
        else:
            print("   ", [l for l in r.stdout.splitlines() if "Output written" in l][0].strip())
            if undef:
                print(f"    [warn] {undef} undefined citation(s) remain after 3 passes")
                rc = 1

    if bad and not a.allow_todo:
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
