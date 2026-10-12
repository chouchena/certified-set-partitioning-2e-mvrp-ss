"""NOTATION AUDIT. One letter, one meaning -- and where Karademir et al. already have a letter
for a quantity, it is theirs.

WHY THIS IS EXECUTABLE AND NOT A STYLE NOTE. The rule "align our notation to K's" is exactly
the kind of rule that holds for as long as someone remembers it and then quietly stops holding
the first time a section is drafted at speed. The two checks that caught real errors in this
project were both executable. This one fails a build; a paragraph in a style guide does not.

WHAT IT CHECKS, precisely, and what it cannot check:
  * CHECKS: every base symbol appearing in manuscript math is declared below, and no symbol
    K reserve is used here for something other than what K use it for.
  * CANNOT CHECK: that a declared meaning is the meaning actually used in a given sentence.
    A symbol table cannot read prose. It narrows the failure to "someone changed the meaning
    without changing the table", which is a review-visible act rather than an invisible one.

THE AUTHORITY for K's column is their Table 1 (p. 484), their Section 3.3 (r_ij), and their
Section 4 (the decomposition symbols, and K'_w at Section 4.1). Read from the PDF page renders
on 2026-09-15, not from our notes about them.
"""
import os, re, sys, glob, argparse, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = os.path.join(ROOT, "paper", "manuscript", "sections")

# A LITERAL backslash and a REGEX-ESCAPED one are different strings and must not be confused:
# inside a pattern, a lone backslash escapes whatever follows it and silently changes the
# match. BSL is for building LaTeX text, RBS is for building patterns. (The first run of this
# file died on exactly that: `(?<!` + BSL + `)` compiled the `)` as an escaped paren.)
BSL = chr(92)
RBS = re.escape(BSL)

# --------------------------------------------------------------------------- K's symbols
# Every base symbol Karademir et al. (2025) bind to a meaning. A symbol in this map may appear
# in our manuscript ONLY with the meaning recorded here.
K_RESERVED = {
    # sets and indices (Table 1)
    "g": "garage for LEFVs",
    "d": "central depot for vessels",
    "C": "customer nodes",
    "P": "satellites, indexed by p",
    "N": "all nodes",
    "i": "node index", "j": "node index", "p": "satellite index", "n": "node index",
    # parameters (Table 1)
    "q": "demand at a node",
    "a": "earliest service time",
    "b": "latest service time",
    "tau": "service duration of a node",
    "U": "constant duration of a transfer task",
    "t": "shortest travel time between nodes",
    "c": "unit cost of travel (c^s street, c^w water)",
    "Q": "vehicle capacity (Q_s LEFV, Q_w vessel)",
    "K": "fleet size (K_s LEFVs, K_w vessels; K'_w the demand-implied vessel minimum)",
    "beta": "fixed cost of a vehicle (beta_s LEFV, beta_w vessel)",
    "M": "big-M linearisation constant",
    # K's LEVEL MARKERS. Not standalone quantities in their paper -- they appear as the sub- or
    # superscript that separates street from water on eight of their symbols (c^s/c^w, Q_s/Q_w,
    # K_s/K_w, beta_s/beta_w, f^s/f^w, z^s/z^w, M^s/M^w, C_s/C_w). Declared because our resource
    # index ranges over them as literal values in Algorithm 2, which is that same meaning used
    # as a value rather than as a decoration.
    "s": "level marker: street",
    "w": "level marker: water",
    # variables (Table 1)
    "x": "LEFV successor indicator",
    "m": "load on the LEFV after visiting a node",
    "h": "service start time at a customer with an LEFV",
    "phi": "transfer-task indicator",
    "v": "satellite assignment of a transfer task",
    "y": "vessel successor indicator over transfer tasks",
    "u": "service start time of a transfer task",
    "l": "load on the vessel after serving a transfer task",
    "f": "realised arc travel duration (f^s street, f^w water)",
    # Section 3.3 and Section 4
    "r": "time difference between two transfer tasks",
    "z": "cost (z^s street, z^w water, z^UB incumbent)",
    "psi": "street travel cost component, master problem",
    "epsilon": "transfer detour cost component, master problem",
    "D": "domain of a decision vector",
    "E": "arc set of a master solution (E_-, E_+)",
}

# --------------------------------------------------------------------------- our additions
# Quantities K do not name. Every letter here was checked against K_RESERVED above: none of
# them appears in their paper with any meaning. Adding a row here is a deliberate act -- prefer
# an expression in their symbols (see q(C) below) over minting a new letter.
OURS = {
    "mu": "min over satellites of the vessel round trip from d, an abbreviation for K eq. (44)",
    "I": "an instance",
    "A": "a customer subset offered as a fleet witness (Algorithm 3)",
    "kappa": "cap on witness subset size (Algorithm 3)",
    "W": "work lower bound accumulated by a witness subset (Algorithm 3)",
    "rho": "reload count a single vehicle would need (Algorithm 3)",
    "H": "retained customer set at a given drop count",
    "k": "drop count: how many customers are removed from the retained set",
    "T": "per-solve deterministic tick budget",
    "B": "per-cell budget",
    "pi": "the retained-set order over C",
    "lambda": "value returned by a block solve",
    "theta": "instance-level scarcity of a resource",
    "gamma": "per-customer consumption of a resource",
    "omega": "scarcity weight of a resource",
    "xi": "resource index, ranging over Xi",
    "Xi": "the four resources scored by the retained-set order: s, w, time, geo",
    "eta": "easiness score of a customer",
    "nu": "nearest-neighbour distance of a customer",
    "Omega": "time-window width of a customer, b_i - a_i",
    "Theta": "the planning horizon",
    "Delta": "the diagonal of the customer bounding box",
    # Added 2026-09-15 with the Appendix A proofs. `e` was FREED by this same alignment: it was
    # the earliest service time here and is now K's a_i, so the letter carries no other meaning
    # and is mnemonic for the customer being excised. It is also what paper/LEMMAS.md uses for
    # the middle node of the splice triple (i, e, j), and the two must not drift apart.
    "e": "the customer excised by a splice (the middle node of the triple i, e, j)",
    "sigma": "a solution of BlockA, in the proof of the restriction lemma",
    # Added 2026-09-15 with the max-over-records correction. Uppercase R is unused by K (their
    # r_ij is lowercase and is the transfer-task time difference), and it is set off as
    # \mathcal{R} so the two cannot be confused on the page.
    "R": "the set of block-solve records produced by the descent, certified or not",
    # Added 2026-09-15 with the corrected fleet certificate. Lowercase delta is unused by K;
    # capital Delta is already ours (the bounding-box diagonal) and the two are distinct
    # quantities in different sections, which the table records so nobody merges them.
    "delta": "cheapest satellite insertion anywhere in the instance, charged per transfer",
}

SANCTIONED = dict(K_RESERVED)
for k, v in OURS.items():
    if k in SANCTIONED:
        raise AssertionError(f"{k} is declared both as K's and as ours")
    SANCTIONED[k] = v

# Structural LaTeX that is not notation. Anything here is skipped before symbol extraction.
STRUCTURAL = {
    "begin", "end", "label", "ref", "eqref", "caption", "item", "text", "textsc", "textbf",
    "emph", "mathrm", "mathit", "operatorname", "num", "cite", "citet", "citep", "quad",
    "qquad", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr",
    "left", "right", "textstyle", "displaystyle", "underbrace",
    "lceil", "rceil", "lfloor", "rfloor", "sum", "min", "max", "in", "subseteq", "setminus",
    "cup", "cap", "leq", "geq", "neq", "star", "dots", "ldots", "cdots", "Leftarrow",
    "Rightarrow", "neg", "times", "cdot", "frac", "sqrt", "bar", "hat", "underline", "mathbb",
    "mathcal", "emptyset", "cup", "varnothing",
    "State", "Statex", "Require", "Ensure", "If", "Else", "ElsIf", "EndIf", "For", "EndFor",
    "While", "EndWhile", "Return", "Comment", "Function", "EndFunction", "algorithmic",
    "algorithm", "Procedure", "EndProcedure", "and", "or", "not", "true", "false",
}


def math_fragments(path):
    """Math content of one section, with %% commentary removed.

    Comments are stripped FIRST and deliberately. This file's comment blocks discuss the very
    symbols they replace -- auditing them would report every retired symbol as a live one.
    """
    out, lines = [], []
    for line in open(path, encoding="utf-8"):
        lines.append(re.sub(r"(?<!" + RBS + ")%.*$", "", line))
    text = "".join(lines)
    out += re.findall(r"[$]([^$]+)[$]", text)
    for env in ("equation", "align", "equation[*]", "align[*]"):
        out += re.findall(RBS + "begin{" + env + "}(.*?)" + RBS + "end{" + env + "}", text, re.S)
    return out


def _drop_balanced(text, opener):
    """Remove `opener{...}` including NESTED braces, which a regex character class cannot do.

    THE BUG THIS FIXES. The first version used `_\\{[^{}]*\\}`, which stops at the first inner
    brace: in `\\underbrace{...}_{\\text{street level}}` it matched nothing, the words survived
    into the symbol list, and the audit reported `e`, `o`, `s` and `w` as undeclared symbols.
    Four of the seven findings in its first run were its own parsing. An audit that invents
    findings is worse than no audit, because the real ones stop being believed.
    """
    out, i = [], 0
    while i < len(text):
        j = text.find(opener, i)
        if j < 0:
            out.append(text[i:])
            break
        k = j + len(opener)
        while k < len(text) and text[k] in " \t":
            k += 1
        if k >= len(text) or text[k] != "{":
            out.append(text[i:k or j + len(opener)])
            i = k if k > j else j + len(opener)
            continue
        depth, k2 = 0, k
        while k2 < len(text):
            if text[k2] == "{":
                depth += 1
            elif text[k2] == "}":
                depth -= 1
                if depth == 0:
                    k2 += 1
                    break
            k2 += 1
        out.append(text[i:j])
        out.append(" ")
        i = k2
    return "".join(out)


def base_symbols(fragment):
    """Reduce a math fragment to the set of BASE symbols it uses.

    Collisions are letter-level, so the audit is letter-level: Q_s and Q_w both reduce to Q,
    and the table records that Q means capacity in both. Subscripts and superscripts are
    dropped AFTER the base is taken, so an index i in t_{ij} is not counted as a use of i --
    indices are declared in the table anyway, but counting them would drown the report.
    """
    frag = fragment
    # Commands whose BRACED ARGUMENT is not notation. Listing the command in STRUCTURAL only
    # suppresses the command NAME -- the argument's letters still reach the symbol list, which
    # is how `\label{eq:objective}` reported `e` and `o` as undeclared symbols.
    for cmd in ("label", "ref", "eqref", "caption", "num", "cite", "citet", "citep",
                "mathrm", "mathit", "operatorname", "text", "textsc", "textbf", "emph"):
        frag = _drop_balanced(frag, BSL + cmd)
    frag = _drop_balanced(frag, "_")
    frag = _drop_balanced(frag, "^")
    frag = re.sub(r"\^[A-Za-z0-9]|_[A-Za-z0-9]", " ", frag)
    found = set()
    for tok in re.findall(RBS + r"[A-Za-z]+|[A-Za-z]", frag):
        name = tok[1:] if tok.startswith(BSL) else tok
        if name in STRUCTURAL:
            continue
        found.add(name)
    return found


def audit():
    used = collections.defaultdict(set)
    for path in sorted(glob.glob(os.path.join(SECTIONS, "*.tex"))):
        for frag in math_fragments(path):
            for s in base_symbols(frag):
                used[s].add(os.path.basename(path))
    undeclared = {s: f for s, f in used.items() if s not in SANCTIONED}
    return used, undeclared


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print the sanctioned table and exit")
    args = ap.parse_args()

    if args.list:
        for s in sorted(SANCTIONED, key=str.lower):
            origin = "K" if s in K_RESERVED else "ours"
            print(f"  {s:<10} [{origin:>4}]  {SANCTIONED[s]}")
        return 0

    used, undeclared = audit()
    print(f"symbols in manuscript math: {len(used)}")
    kept = sorted(s for s in used if s in K_RESERVED)
    mine = sorted(s for s in used if s in OURS)
    print(f"  from K's table  ({len(kept)}): {' '.join(kept)}")
    print(f"  ours            ({len(mine)}): {' '.join(mine)}")
    if undeclared:
        print()
        print("UNDECLARED SYMBOLS -- each is either a collision with K or a letter nobody chose:")
        for s in sorted(undeclared):
            print(f"  {s:<10} used in {', '.join(sorted(undeclared[s]))}")
        print()
        print("Fix by renaming to K's symbol where they have one, or by adding a row to OURS")
        print("in this file with the meaning and the check that K do not use that letter.")
        return 1
    print()
    print("OK: every symbol is declared, and no K symbol is used for another meaning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
