"""Hard-check every DOI in paper/references.bib against Crossref.

WHY. A `doi = {...}` field is not a verified DOI. This project has already caught one citation
that could not be located at all (the Yuraszeck C&OR "note on", from an LLM-generated venue
review), and the standing rule is that no reference enters the manuscript unverified. That rule
must apply to OUR bibliography too, not only to citations handed to us.

WHAT IS CHECKED, per entry:
  * the DOI RESOLVES at all (a 404 means the identifier is wrong or invented)
  * the registered TITLE matches the bib title (token-overlap similarity, reported as a number
    rather than a pass/fail, because subtitle and punctuation differences are common and benign)
  * the registered YEAR matches
  * the first author's FAMILY NAME appears in the bib author field
  * the registered CONTAINER (journal/book) is reported so a wrong-venue entry is visible

A mismatch is not automatically an error -- Crossref records are themselves imperfect, and
preprint/published duplicates exist. The script reports and ranks; a human decides. What it
guarantees is that no entry ships UNCHECKED.

Usage:  python analysis/bib_verify.py [--bib paper/references.bib] [--out runs/bib_verify.json]
"""
import re, os, sys, json, time, argparse, urllib.request, urllib.error
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "bib-check/1.0 (mailto:davidch@mail.sapir.ac.il)"
STOP = {"a", "an", "the", "of", "for", "and", "on", "in", "to", "with", "by", "problem", "problems"}


def parse_bib(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", txt):
        kind, key = m.group(1), m.group(2).strip()
        start = m.end()
        depth, i = 1, start
        while i < len(txt) and depth:
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
            i += 1
        body = txt[start:i]

        def field(name):
            f = re.search(name + r"\s*=\s*", body, re.I)
            if not f:
                return ""
            j = f.end()
            if j < len(body) and body[j] in "{\"":
                close = "}" if body[j] == "{" else "\""
                d, k = 1, j + 1
                while k < len(body) and d:
                    if body[k] == "{":
                        d += 1
                    elif body[k] == close:
                        d -= 1
                    k += 1
                return body[j + 1:k - 1].strip()
            return body[j:].split(",")[0].strip()

        out.append(dict(key=key, kind=kind, doi=field("doi"), title=field("title"),
                        year=field("year"), author=field("author"),
                        journal=field("journal") or field("booktitle") or field("publisher")))
    return out


def norm(s):
    # Strip LaTeX brace protection BEFORE tokenising. "{B}enders" must normalise to "benders",
    # not to "b" + "enders" -- otherwise capitalisation guards look like title mismatches.
    # This was a real false positive on hooker2003lbbd and rahmaniani2020bdd.
    s = (s or "").replace("{", "").replace("}", "").replace("\\", "")
    toks = re.findall(r"[a-z0-9]+", s.lower())
    return [t for t in toks if t not in STOP]


def similarity(a, b):
    A, B = set(norm(a)), set(norm(b))
    return len(A & B) / max(1, len(A | B))


def crossref(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)["message"], None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main(bib, out):
    entries = parse_bib(bib)
    print(f"{len(entries)} entries in {os.path.relpath(bib, ROOT)}\n")
    rows, problems = [], []
    for e in entries:
        if not e["doi"]:
            rows.append(dict(e, status="NO DOI", sim=None))
            problems.append((e["key"], "no DOI field"))
            print(f"  {e['key']:26s} NO DOI")
            continue
        msg, err = crossref(e["doi"])
        time.sleep(0.2)                       # be polite to the API
        if msg is None:
            rows.append(dict(e, status=f"UNRESOLVED ({err})", sim=None))
            problems.append((e["key"], f"DOI does not resolve: {err}"))
            print(f"  {e['key']:26s} **UNRESOLVED**  {e['doi']}  ({err})")
            continue
        ct = (msg.get("title") or [""])[0]
        cy = str((msg.get("issued", {}).get("date-parts") or [[""]])[0][0])
        cv = (msg.get("container-title") or [""])[0]
        fam = ""
        if msg.get("author"):
            fam = msg["author"][0].get("family", "")
        sim = similarity(e["title"], ct)
        flags = []
        if sim < 0.55:
            flags.append(f"TITLE sim={sim:.2f}")
        if e["year"] and cy and e["year"] != cy:
            flags.append(f"YEAR bib={e['year']} crossref={cy}")
        if fam and fam.lower() not in (e["author"] or "").lower():
            flags.append(f"AUTHOR '{fam}' not in bib author field")
        status = "ok" if not flags else "CHECK: " + "; ".join(flags)
        if flags:
            problems.append((e["key"], status))
        rows.append(dict(e, status=status, sim=round(sim, 3),
                         crossref_title=ct, crossref_year=cy, crossref_venue=cv))
        mark = "ok  " if not flags else "**? "
        print(f"  {e['key']:26s} {mark} sim={sim:4.2f} {cy}  {cv[:42]}")
        for f in flags:
            print(f"       -> {f}")

    os.makedirs(os.path.dirname(os.path.join(ROOT, out)), exist_ok=True)
    json.dump(stamped(rows, __file__), open(os.path.join(ROOT, out), "w"), indent=1)
    print(f"\n  wrote {out}")
    print(f"  entries: {len(entries)}   needing a human look: {len(problems)}")
    for k, p in problems:
        print(f"    {k}: {p}")
    print("\n  NOTE: a flag is not proof of error. Crossref records carry their own subtitle and")
    print("  punctuation quirks, and preprint/published duplicates exist. The guarantee here is")
    print("  that no entry ships UNCHECKED -- not that every flag is a defect.")
    return 1 if any("UNRESOLVED" in r["status"] or r["status"] == "NO DOI" for r in rows) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bib", default=os.path.join(ROOT, "paper/references.bib"))
    ap.add_argument("--out", default="runs/bib_verify.json")
    a = ap.parse_args()
    sys.exit(main(a.bib, a.out))
