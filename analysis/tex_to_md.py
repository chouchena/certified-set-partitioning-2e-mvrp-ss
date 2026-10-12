r"""Render the flattened submission .tex to a readable Markdown manuscript (for review, not for
typesetting). Resolves \num{id[.key]} from paper/numbers.json so the prose carries real numbers;
converts sectioning, bold/emph, citations and refs to plain Markdown; lists each figure/table by its
caption. Math is left inline ($...$) for a Markdown math viewer. Lossy by design -- the PDF is the
authoritative form; this is a diff-able, comment-able text copy.

    python analysis/tex_to_md.py paper/manuscript/submission/main4.tex paper/manuscript/submission/main4.md
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def num_lookup():
    p = os.path.join(ROOT, "paper", "numbers.json")
    d = json.load(open(p)) if os.path.exists(p) else {}
    out = {}
    for nid, rec in d.items():
        if str(nid).startswith("_") or nid == "sources":
            continue
        v = rec.get("value") if isinstance(rec, dict) else rec
        if isinstance(v, dict):
            for k, kv in v.items():
                out["%s.%s" % (nid, k)] = str(kv)
        else:
            out[nid] = str(v)
    return out


def brace(s, i):
    """Return the balanced {...} starting at s[i]=='{' as (content, index-after)."""
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def convert(tex, nums):
    # strip comments (keep escaped \%)
    tex = re.sub(r"(?<!\\)%.*", "", tex)
    # body only
    m = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex, re.S)
    body = m.group(1) if m else tex

    # title / abstract / keywords up top
    out = []
    mt = re.search(r"\\title(?:\[[^\]]*\])?\{", tex)
    if mt:
        title, _ = brace(tex, mt.end() - 1)
        out.append("# " + re.sub(r"\s+", " ", re.sub(r"\\%", "%", title)).strip())
    ma = re.search(r"\\abstract\{", tex)
    if ma:
        ab, _ = brace(tex, ma.end() - 1)
        out.append("\n**Abstract.** " + ab.strip())
    mk = re.search(r"\\keywords\{", tex)
    if mk:
        kw, _ = brace(tex, mk.end() - 1)
        out.append("\n**Keywords:** " + kw.strip())
    out.append("\n---\n")

    # drop float environments but keep their captions
    def float_sub(m):
        inner = m.group(2)
        cap = re.search(r"\\caption\{", inner)
        if cap:
            c, _ = brace(inner, cap.end() - 1)
            kind = "Figure" if m.group(1) == "figure" else "Table"
            return "\n> **%s.** %s\n" % (kind, re.sub(r"\s+", " ", c).strip())
        return ""
    body = re.sub(r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", float_sub, body, flags=re.S)
    # algorithm/align/equation: keep as fenced blocks
    body = re.sub(r"\\begin\{(align|equation|align\*|equation\*)\}(.*?)\\end\{\1\}",
                  lambda m: "\n```\n%s\n```\n" % m.group(2).strip(), body, flags=re.S)

    # sectioning
    body = re.sub(r"\\section\*?\{", "\n\x01# ", body)
    body = re.sub(r"\\subsection\*?\{", "\n\x01## ", body)
    body = re.sub(r"\\subsubsection\*?\{", "\n\x01### ", body)
    body = re.sub(r"\\bmhead\{", "\n\x01#### ", body)
    # close the heading brace: a heading line \x01...{title} -> markdown
    def head(m):
        txt, _ = brace(m.group(0), m.group(0).index("{"))
        level = m.group(1)
        return "\n%s %s\n" % (level, re.sub(r"\s+", " ", txt).strip())
    body = re.sub(r"\x01(#{1,4}) \{", lambda m: "\n%s " % m.group(1), body)  # marker -> hashes, brace handled next

    # inline commands with one brace arg
    def repl_num(m):
        key = m.group(1)
        return nums.get(key, "[" + key + "]")
    body = re.sub(r"\\num\{([^}]*)\}", repl_num, body)
    body = re.sub(r"\\(?:textbf|textsc)\{([^{}]*)\}", r"**\1**", body)
    body = re.sub(r"\\(?:emph|textit|textrm)\{([^{}]*)\}", r"*\1*", body)
    body = re.sub(r"\\citep?\{([^}]*)\}", lambda m: "(%s)" % m.group(1).replace("_", r"\_"), body)
    body = re.sub(r"\\citet\{([^}]*)\}", lambda m: "%s" % m.group(1).replace("_", r"\_"), body)
    body = re.sub(r"\\citeauthor\{([^}]*)\}", lambda m: m.group(1).replace("_", r"\_"), body)
    body = re.sub(r"\\(?:eqref|ref)\{([^}]*)\}", r"(\1)", body)
    body = re.sub(r"\\label\{[^}]*\}", "", body)
    body = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}", "", body)
    # lists
    body = re.sub(r"\\begin\{(itemize|enumerate)\}", "", body)
    body = re.sub(r"\\end\{(itemize|enumerate)\}", "", body)
    body = re.sub(r"\\item\s*", "\n- ", body)
    # leftover simple commands and braces
    body = body.replace("\\maketitle", "").replace("\\backmatter", "")
    body = re.sub(r"\\(?:bibliography|input|includegraphics|orcid|affil|author\*?|email|fnm|sur|orgname|orgaddress|city|postcode|country)\b\*?(\[[^\]]*\])?(\{[^}]*\})*", "", body)
    body = re.sub(r"\\[a-zA-Z]+\*?", "", body)      # drop remaining control words
    body = body.replace("{", "").replace("}", "")
    body = body.replace("\\%", "%").replace("~", " ").replace("---", "—").replace("--", "–")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return "\n".join(out) + "\n" + body.strip() + "\n"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "paper", "manuscript", "submission", "main4.tex")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "paper", "manuscript", "submission", "main4.md")
    tex = open(src, encoding="utf-8").read()
    md = convert(tex, num_lookup())
    md = ("<!-- Readable Markdown rendering of the manuscript, generated by analysis/tex_to_md.py. "
          "LOSSY: the compiled PDF (main4.pdf) is the authoritative form; equations/tables are "
          "simplified here for review and diffing. -->\n\n" + md)
    open(dst, "w", encoding="utf-8").write(md)
    print("wrote %s (%d lines)" % (os.path.relpath(dst, ROOT), md.count(chr(10))))


if __name__ == "__main__":
    main()
