"""Claim register — every quantitative claim, its evidence status, and what would kill it.

WHY THIS EXISTS. The 5-day metaprocess audit (2026-09-10) found the dominant failure is not
any single bug: the process GENERATES CLAIMS FASTER THAN IT VALIDATES THEM, and uses the user
as the validation layer. Census over 103 commits: `wrong` 16, `kill` 18, `defect` 12,
`invalidat` 6, `refut` 5, `retract` 4. Roughly a third of commits correct earlier commits, and
six separate questions were held in 3-4 mutually contradictory positions:

  multikick      "wrong lever" -> "don't build" -> "cores probe REVERSES it, 1.8x" -> leg deleted
  30% threshold  asserted -> refuted by RC207 on its FIRST out-of-sample cell -> ...
  RT framing     167x ratio -> dropped -> "(a) vs 14400s" -> audit found TRAJECTORY.md had
                 ALREADY retired exactly that -> outcome form restored
  n100 |H| cap   "capped ~13" -> "falsified, |H|=50" -> C204 fails at |H|=30

Each flip was invisible at the time because claims lived in prose — in commit messages, in
SESSION_RESUME, in chat — where a new assertion silently overwrites an old one. A register
makes the flip a data change instead of a rhetorical one.

WHAT IT ENFORCES
1. EVIDENCE STATUS is mandatory: MEASURED (read from an artifact), INFERRED (derived from
   measured things), ASSUMED (neither — a working hypothesis). An ASSUMED claim that is
   STANDING and load-bearing is the single most dangerous object in the project.
2. SAMPLE SUFFICIENCY IS CASE-DEPENDENT and must be argued, not assumed (user, 2026-09-10).
   A fixed "n>=5" is wrong: a validity proof needs n=1 (it is a proof), a deterministic bound
   comparison needs full coverage of the target set, a stochastic OV comparison needs a power
   calculation. The register does not pick the number — it REFUSES a claim that does not say
   why its sample settles THIS kind of question.
3. FALSIFIER is mandatory: the specific check that would disprove the claim, and whether it
   has actually been run. "Not yet run" is fine; not stating one is not.
4. SUPERSESSION IS EXPLICIT: a claim that replaces another names it, so contradiction chains
   are visible and countable rather than lost in prose.

USAGE
  python analysis/claims.py list            [--status STANDING] [--evidence ASSUMED]
  python analysis/claims.py check           # the gate: flags everything unsafe
  python analysis/claims.py render          # writes CLAIMS.md
  python analysis/claims.py add --id ... --claim ... --evidence ... --sample ... \
                                --sufficiency ... --falsifier ... [--supersedes id,id]
  python analysis/claims.py retract --id ... --why ...
"""
from __future__ import annotations
import argparse, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "validation", "claims.json")
MD = os.path.join(ROOT, "CLAIMS.md")
EVIDENCE = ("MEASURED", "INFERRED", "ASSUMED")
STATUS = ("STANDING", "RETRACTED", "SUPERSEDED")


def load():
    if not os.path.exists(REG):
        return []
    return json.load(open(REG, encoding="utf-8"))


def save(rows):
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    json.dump(rows, open(REG, "w", encoding="utf-8"), indent=2)


def add(a):
    rows = load()
    if any(r["id"] == a.id for r in rows):
        sys.exit(f"claim id '{a.id}' already exists — use retract/supersede, never overwrite")
    if a.evidence not in EVIDENCE:
        sys.exit(f"--evidence must be one of {EVIDENCE}")
    sup = [x.strip() for x in (a.supersedes or "").split(",") if x.strip()]
    ids = {r["id"] for r in rows}
    for s in sup:
        if s not in ids:
            sys.exit(f"--supersedes names unknown claim '{s}'")
    for r in rows:
        if r["id"] in sup:
            r["status"] = "SUPERSEDED"
            r["superseded_by"] = a.id
    rows.append(dict(id=a.id, claim=a.claim, value=a.value, evidence=a.evidence,
                     source=a.source, sample=a.sample, sufficiency=a.sufficiency,
                     falsifier=a.falsifier, falsifier_run=a.falsifier_run,
                     supersedes=sup, status="STANDING", date=time.strftime("%Y-%m-%d")))
    save(rows)
    print(f"added {a.id} [{a.evidence}]" + (f" superseding {sup}" if sup else ""))


def retract(a):
    rows = load()
    for r in rows:
        if r["id"] == a.id:
            r["status"] = "RETRACTED"
            r["retracted_why"] = a.why
            r["retracted_on"] = time.strftime("%Y-%m-%d")
            save(rows)
            print(f"retracted {a.id}: {a.why}")
            return
    sys.exit(f"no claim '{a.id}'")


def chain_len(rows, cid, seen=None):
    """How many times has this question changed position? Counts the supersession chain."""
    seen = seen or set()
    r = next((x for x in rows if x["id"] == cid), None)
    if not r or cid in seen:
        return 0
    seen.add(cid)
    return 1 + max([chain_len(rows, s, seen) for s in r.get("supersedes", [])] or [0])


_NOT_RUN_MARKERS = ("not run", "notrun", "not-run", "pending", "not yet",
                    "unrun", "never run", "tbd", "todo")


def _ran(v):
    """True only if falsifier_run records an ACTUAL execution.

    The original gate accepted any non-empty string, so an entry could defeat it
    by writing prose beginning 'NOT RUN -- ...' in the falsifier_run field. That
    hole was found on 2026-09-14 by walking into it: two new claims declared
    'NOT RUN' and the gate passed them. A falsifier that has not been executed
    must be indistinguishable, to the gate, from one that was never defined."""
    s = (v or "").strip().lower().lstrip("*_ ")
    if not s:
        return False
    return not any(s.startswith(m) for m in _NOT_RUN_MARKERS)


def check(a=None):
    rows = load()
    standing = [r for r in rows if r["status"] == "STANDING"]
    problems = []
    for r in standing:
        if r["evidence"] == "ASSUMED":
            problems.append(("ASSUMED-STANDING", r["id"],
                             "a working hypothesis is in play as if settled"))
        if not (r.get("sufficiency") or "").strip():
            problems.append(("NO-SUFFICIENCY", r["id"],
                             "sample given but no argument that it settles THIS question"))
        if not (r.get("falsifier") or "").strip():
            problems.append(("NO-FALSIFIER", r["id"], "nothing stated that would disprove it"))
        elif not _ran(r.get("falsifier_run")):
            # NOTE, 2026-09-17: a "FALSIFIER-MOOT" branch for SUPERSEDED/RETRACTED claims was
            # added here and immediately reverted -- it is unreachable, because `standing` above
            # already filters to STANDING. Every id this reports is a LIVE claim.
            #
            # The confusion it came from is worth recording: counting rows with an EMPTY
            # `falsifier_run` across ALL statuses also gives 16, a DIFFERENT set that happens to
            # be the same size. Twelve of the live sixteen carry a written reason in
            # `falsifier_run` ("NOT RUN -- ...") which `_ran` correctly refuses to accept as a
            # run; only four are silently unrun.
            problems.append(("FALSIFIER-NOT-RUN", r["id"],
                             f"falsifier defined but never executed: {r['falsifier'][:60]}"))
    for r in rows:
        n = chain_len(rows, r["id"])
        if n >= 3 and r["status"] == "STANDING":
            problems.append(("POSITION-FLIP", r["id"],
                             f"this question has now been answered {n} different ways"))
    print(f"claim register: {len(rows)} total, {len(standing)} standing, "
          f"{sum(1 for r in rows if r['status']=='RETRACTED')} retracted, "
          f"{sum(1 for r in rows if r['status']=='SUPERSEDED')} superseded")
    if not problems:
        print("CHECK PASSED — no standing claim is unsupported.")
        return 0
    print(f"\n{len(problems)} PROBLEM(S):")
    for kind, cid, why in problems:
        print(f"  [{kind:18}] {cid:28} {why}")
    return 1


def render(a=None):
    rows = load()
    order = {"MEASURED": 0, "INFERRED": 1, "ASSUMED": 2}
    lines = ["# Claim register",
             "",
             "Generated by `analysis/claims.py render`. Do not edit by hand.",
             "",
             "`MEASURED` = read from an artifact. `INFERRED` = derived from measured things.",
             "`ASSUMED` = neither; a working hypothesis. Sample sufficiency is **case-dependent**",
             "and must be argued per claim, not set by a fixed n.",
             ""]
    for st in ("STANDING", "SUPERSEDED", "RETRACTED"):
        sel = sorted([r for r in rows if r["status"] == st],
                     key=lambda r: (order.get(r["evidence"], 9), r["id"]))
        if not sel:
            continue
        lines += [f"## {st} ({len(sel)})", ""]
        for r in sel:
            lines.append(f"### `{r['id']}` — {r['evidence']}")
            lines.append(f"**{r['claim']}**")
            lines.append("")
            lines.append(f"- value: {r.get('value') or '—'}")
            lines.append(f"- source: {r.get('source') or '—'}")
            lines.append(f"- sample: {r.get('sample') or '—'}")
            lines.append(f"- why that sample settles it: {r.get('sufficiency') or '**MISSING**'}")
            lines.append(f"- falsifier: {r.get('falsifier') or '**MISSING**'}"
                         + (f" — run: {r['falsifier_run']}" if r.get('falsifier_run')
                            else " — **NOT RUN**"))
            if r.get("supersedes"):
                lines.append(f"- supersedes: {', '.join(r['supersedes'])}")
            if r.get("superseded_by"):
                lines.append(f"- superseded by: {r['superseded_by']}")
            if r.get("retracted_why"):
                lines.append(f"- RETRACTED: {r['retracted_why']}")
            lines.append("")
    open(MD, "w", encoding="utf-8").write("\n".join(lines))
    print(f"wrote {MD} ({len(rows)} claims)")


def listing(a):
    rows = load()
    for r in rows:
        if a.status and r["status"] != a.status:
            continue
        if a.evidence and r["evidence"] != a.evidence:
            continue
        print(f"{r['status']:11} {r['evidence']:9} {r['id']:30} {r['claim'][:70]}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    for f in ("id", "claim", "value", "source", "sample", "sufficiency", "falsifier"):
        p.add_argument(f"--{f}", default="")
    p.add_argument("--evidence", required=True)
    p.add_argument("--falsifier-run", dest="falsifier_run", default="")
    p.add_argument("--supersedes", default="")
    p.set_defaults(fn=add)
    p = sub.add_parser("retract"); p.add_argument("--id", required=True)
    p.add_argument("--why", required=True); p.set_defaults(fn=retract)
    p = sub.add_parser("check"); p.set_defaults(fn=check)
    p = sub.add_parser("render"); p.set_defaults(fn=render)
    p = sub.add_parser("list"); p.add_argument("--status", default="")
    p.add_argument("--evidence", default=""); p.set_defaults(fn=listing)
    a = ap.parse_args()
    rc = a.fn(a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
