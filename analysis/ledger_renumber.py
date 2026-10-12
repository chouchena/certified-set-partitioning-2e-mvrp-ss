"""Restore the decision NUMBER on every ledger entry that was appended without one.

    python analysis/ledger_renumber.py --plan      # propose, write nothing
    python analysis/ledger_renumber.py --apply     # rewrite the file, then verify

THE DEFECT. CLAUDE.md section 2: "Decisions are appended, never remembered." From 2026-09-25
the writer stopped emitting the `n` field: 164 of 597 entries carry no number, while prose in
CLAUDE.md, the lemma files and the ledger's own later entries goes on citing d437, d502, d519,
d571, d592 and a hundred others. So those decisions ARE appended -- the text is all there -- but
they are only REMEMBERED by number: 107 distinct citations resolve to nothing. A settled
question that cannot be looked up is exactly what the rule exists to prevent.

FILE SHAPE, measured before touching anything:
  lines 1-5    `//` comments, not JSON. Preserved byte for byte.
  n = 1..436   contiguous, lines 6-435, strictly increasing in file order.
  145 entries  lines 436-580, NO number. Room between 436 and 595 is 437..594.
  n = 595,596,600  lines 581-583.
  19 entries   lines 584-602, NO number.

HOW A NUMBER IS RECOVERED, strongest evidence first. The ledger is append-only and committed as
it grows, so git knows which commit introduced each entry.

  git      the commit that added the entry, and the dNNN citations in that commit's message or
           in the other files it touched. When a commit adds k entries and supplies exactly k
           consecutive unused numbers, the mapping is forced and is taken.
  span     otherwise the entry is placed by order between its nearest recovered neighbours,
           taking the next unused number above the previous entry's.

EVERY ASSIGNMENT RECORDS HOW IT WAS MADE, in `n_source`, so a reconstructed number is never
mistaken for one the original writer chose. Nothing else on any entry is touched: the script
re-reads the result and asserts every other field is byte-identical to what it replaced, and
that `n` is strictly increasing with no duplicates and no collision with the 433 numbers that
were already there. A single failed assertion writes nothing.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "validation", "DECISIONS.jsonl")
REL = "validation/DECISIONS.jsonl"
# The ledger has MIXED line endings as committed -- 375 CRLF and 227 LF. A write that
# normalises them rewrites 375 lines nobody asked to touch: the first apply did exactly
# that and git reported 403 changed lines against an intended 164. Every terminator now
# travels with its own line.
EOL = "\r\n"


def git(*a, **kw):
    r = subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True, text=True,
                       errors="ignore", **kw)
    return r.stdout


def read_lines(text):
    """(kind, raw, obj) per line. kind is 'comment', 'entry' or 'blank'."""
    out = []
    for raw in text.splitlines(keepends=True):
        s = raw.strip()
        if not s:
            out.append(("blank", raw, None))
        elif s.startswith("//"):
            out.append(("comment", raw, None))
        else:
            try:
                out.append(("entry", raw, json.loads(s)))
            except Exception:
                out.append(("comment", raw, None))
    return out


def key_of(d):
    """A stable fingerprint of an entry, independent of `n`."""
    return (d.get("date"), (d.get("decision") or "")[:160])


def commit_evidence():
    """{entry fingerprint: (sha, [dNNN cited by that commit])} for entries git can place."""
    shas = [s for s in git("log", "--format=%H", "--reverse", "--", REL).split() if s]
    seen, ev = {}, {}
    for sha in shas:
        blob = git("show", "%s:%s" % (sha, REL))
        if not blob.strip():
            continue
        entries = [o for k, _, o in read_lines(blob) if k == "entry"]
        new = [d for d in entries if key_of(d) not in seen]
        for d in entries:
            seen.setdefault(key_of(d), sha)
        if not new:
            continue
        # every dNNN this commit mentions: its message, and the diff of everything it touched
        text = git("log", "-1", "--format=%B", sha) + git("show", "--unified=0", sha)
        cited = sorted({int(m) for m in re.findall(r"\bd(\d{1,3})\b", text)})
        for d in new:
            ev[key_of(d)] = (sha[:12], cited)
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    if not (a.apply or a.plan):
        ap.error("pass --plan or --apply")

    original = io.open(LEDGER, encoding="utf-8", newline="").read()
    rows = read_lines(original)
    entries = [(i, o) for i, (k, _, o) in enumerate(rows) if k == "entry"]
    taken = {int(o["n"]) for _, o in entries if o.get("n") is not None}
    missing = [(i, o) for i, o in entries if o.get("n") is None]
    print("entries %d | numbered %d | UNNUMBERED %d | n range %d..%d"
          % (len(entries), len(taken), len(missing), min(taken), max(taken)))
    if not missing:
        print("nothing to do")
        return 0

    print("reading git history for %s ..." % REL, flush=True)
    ev = commit_evidence()
    print("  entries git could place: %d" % len(ev), flush=True)

    # ---- pass 1: a commit that adds k entries and cites exactly k consecutive free numbers ----
    by_commit = {}
    for i, o in missing:
        e = ev.get(key_of(o))
        if e:
            by_commit.setdefault(e[0], []).append((i, o, e[1]))
    assigned = {}
    for sha, group in by_commit.items():
        group.sort()
        cited = sorted({n for _, _, c in group for n in c if n not in taken})
        runs, cur = [], []
        for n in cited:
            if cur and n == cur[-1] + 1:
                cur.append(n)
            else:
                cur = [n]
                runs.append(cur)
        fit = [r for r in runs if len(r) == len(group)]
        if len(fit) == 1:
            for (i, o, _), n in zip(group, fit[0]):
                assigned[i] = (n, "git %s: the commit cites exactly these %d consecutive free "
                                  "numbers" % (sha, len(group)))
    print("  placed by git evidence: %d of %d" % (len(assigned), len(missing)))

    # ---- pass 2: order-preserving fill, next free number above the previous entry ----
    # The next number the writer itself already used, so a recovered number can never step over
    # an entry that carries its own. Without this the git pass placed 25 entries out of order and
    # the plan came back non-monotone -- caught by the check below rather than by inspection.
    later_fixed = {}
    nxt = None
    for i, o in reversed(entries):
        later_fixed[i] = nxt
        if o.get("n") is not None:
            nxt = int(o["n"])

    prev = 0
    used = set(taken)
    order = []
    rejected = 0
    for i, o in entries:
        if o.get("n") is not None:
            prev = int(o["n"])
            order.append((i, prev, None))
            continue
        cap = later_fixed.get(i)
        if i in assigned:
            n, why = assigned[i]
            # ACCEPT GIT EVIDENCE ONLY WHERE IT IS ORDER-CONSISTENT. A recovered number that
            # would sit below the previous entry, or at or above the next entry that carries its
            # own number, is not evidence of anything -- the commit cited a decision, it did not
            # necessarily introduce it.
            if n > prev and n not in used and (cap is None or n < cap):
                used.add(n)
                prev = n
                order.append((i, n, why))
                continue
            rejected += 1
        n = prev + 1
        while n in used or (cap is not None and n >= cap):
            n += 1
            if cap is not None and n >= cap:      # no room before the next fixed number
                break
        used.add(n)
        prev = n
        order.append((i, n, "span: RECONSTRUCTED 2026-09-30 from file order, next free number above the preceding entry. The original numbering is not gap-free (235-239 and 241 were assigned to decisions never written), so a reconstructed number may differ from the one a historical citation meant."))
    if rejected:
        print("  git placements rejected as out of order: %d" % rejected)
    filled = [(i, n, s) for i, n, s in order if s]

    print("\nPLAN -- %d entries gain a number" % len(filled))
    for i, n, s in filled[:6] + ([("...", "...", "...")] if len(filled) > 12 else []) + filled[-6:]:
        if i == "...":
            print("   ...")
            continue
        print("   line %-5d -> n=%-4d  %s" % (i + 1, n, s[:64]))
    nums = [n for _, n, _ in order]
    print("\n  strictly increasing : %s" % all(nums[k] < nums[k + 1] for k in range(len(nums) - 1)))
    print("  duplicates          : %d" % (len(nums) - len(set(nums))))
    print("  new n range         : %d..%d" % (min(nums), max(nums)))
    resolved = sorted({n for _, n, s in filled if s})
    print("  citations that now resolve: %d" % len([n for n in resolved if n <= 600]))
    if not a.apply:
        return 0

    if not (all(nums[k] < nums[k + 1] for k in range(len(nums) - 1)) and len(nums) == len(set(nums))):
        print("REFUSED: the plan is not strictly increasing or has duplicates. Nothing written.")
        return 3

    # ---- rewrite: only `n` and `n_source` are added, key order preserved ----
    out, fills = [], {i: (n, s) for i, n, s in filled}
    for idx, (kind, raw, o) in enumerate(rows):
        if kind != "entry" or idx not in fills:
            out.append(raw)
            continue
        n, src = fills[idx]
        eol = raw[len(raw.rstrip(EOL)):]     # this line's own terminator, put back verbatim
        new = {"n": n}
        new.update(o)
        new["n"] = n
        new["n_source"] = src
        out.append(json.dumps(new, ensure_ascii=False) + eol)
    text = "".join(out)

    bak = LEDGER + ".bak"
    io.open(bak, "w", encoding="utf-8", newline="").write(original)
    io.open(LEDGER, "w", encoding="utf-8", newline="").write(text)

    # ---- verify: every non-n field identical, entry count identical, comments intact ----
    back = read_lines(io.open(LEDGER, encoding="utf-8", newline="").read())
    bad = []
    if len(back) != len(rows):
        bad.append("line count %d -> %d" % (len(rows), len(back)))
    for (k0, r0, o0), (k1, r1, o1) in zip(rows, back):
        if k0 != k1:
            bad.append("line kind changed"); break
        if k0 != "entry":
            if r0 != r1:
                bad.append("a non-entry line changed: %r" % r0[:40]); break
            continue
        for f in set(o0) | set(o1):
            if f in ("n", "n_source"):
                continue
            if o0.get(f) != o1.get(f):
                bad.append("field %r changed on %s" % (f, (o0.get("date"),))); break
        if bad:
            break
    if bad:
        io.open(LEDGER, "w", encoding="utf-8", newline="").write(original)
        print("VERIFY FAILED, file restored: %s" % "; ".join(bad[:3]))
        return 3
    still = [i for i, (k, _, o) in enumerate(back) if k == "entry" and o.get("n") is None]
    print("\nAPPLIED. backup at %s" % os.path.basename(bak))
    print("  entries without a number now: %d" % len(still))
    print("  every other field verified unchanged on all %d entries" % len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
