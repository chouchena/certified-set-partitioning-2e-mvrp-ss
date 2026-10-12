"""SESSION STATE — executable, and it FAILS when it is stale.

WHY THIS EXISTS. On 2026-09-17 the author wrote: "It looks like you are in amnesia mode,
recurrently forgetting past decisions, discussions, runs and results ... I am losing trust."

The diagnosis was not that state tracking was missing. `SESSION_RESUME.md` existed, carried a
"Decisions taken" section, and was TWO DAYS STALE -- M6, M7, B0, the primal trajectory refactor,
the fleet total and the run-sequencing decision were all absent from it. It was not read, and
nothing required it to be.

THE PATTERN THAT FIXES THIS IS ALREADY IN THIS REPOSITORY. Everything here that works is
executable and fails loudly: release_gate.py, claims.py check, check_number_consistency.py.
Process state was the one thing left as prose. Prose cannot detect its own staleness, so it
rots silently and then gets contradicted in conversation.

WHAT THIS DOES.
  1. Prints what is LIVE right now -- running solver processes and the tail of their logs.
  2. Prints SETTLED DECISIONS from validation/DECISIONS.jsonl, which is append-only and
     machine-readable, so "we already decided this" is queryable instead of remembered.
  3. Detects STALENESS: any result artifact newer than SESSION_RESUME.md's own declared date
     is state the resume file does not know about. That is the amnesia condition, and it
     EXITS NONZERO.

Run it at session start, after any context compaction, and before proposing work.

    python analysis/session_state.py            # report, exit 1 if stale
    python analysis/session_state.py --quiet    # staleness check only
"""
import argparse, datetime as dt, glob, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESUME = os.path.join(ROOT, "SESSION_RESUME.md")
DECISIONS = os.path.join(ROOT, "validation", "DECISIONS.jsonl")

# Directories whose newest file dates the project's real state. runs/ is gitignored but it is
# where results land, so it counts: staleness is about what HAPPENED, not what was committed.
RESULT_GLOBS = [
    "runs/*.json", "runs/*.out", "runs/*.log",
    "validation/RESULT_*.md", "validation/PREREG_*.md", "validation/FINDING_*.md",
    "crossfeed/*.json", "paper/numbers.json",
]


def resume_date():
    """The date SESSION_RESUME.md DECLARES for itself, not its mtime.

    The mtime lies: touching the file, or a checkout, moves it without anyone rewriting the
    content. The header line is what a human asserted the state was as of.
    """
    if not os.path.exists(RESUME):
        return None, "SESSION_RESUME.md does not exist"
    head = open(RESUME, encoding="utf-8").readline()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", head)
    if not m:
        return None, "no date in the first line: %r" % head[:80]
    return dt.date(*(int(x) for x in m.groups())), ""


def newer_than(d):
    """Result artifacts modified after the resume's declared date."""
    out = []
    for g in RESULT_GLOBS:
        for f in glob.glob(os.path.join(ROOT, g)):
            mt = dt.date.fromtimestamp(os.path.getmtime(f))
            if mt > d:
                out.append((mt, os.path.relpath(f, ROOT)))
    return sorted(out, reverse=True)


def decisions():
    if not os.path.exists(DECISIONS):
        return []
    rows = []
    for l in open(DECISIONS, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("//"):
            try:
                rows.append(json.loads(l))
            except Exception:
                pass
    return rows


# Topic -> the document that GOVERNS it. Printed every run, because the failure this catches is
# not a stale file but an unopened one: on 2026-09-17 a full RT-fairness audit was produced using
# a normalisation factor that RT_COMPARABILITY.md metric M3 rejects outright, and the document was
# found only after the author pushed back. Mirrors CLAUDE.md section 5.
AUTHORITIES = [
    # 2026-09-17 (decision 157): this row named RT_COMPARABILITY.md, which has said
    # "SUPERSEDED by RT_LEG_DESIGN.md" on its own line 3 since 2026-09-13. The stale
    # pointer survived because nothing checks that a named authority is still current.
    # SUPERSEDED_BY below is that check.
    ("runtime / budget comparability with K", "validation/RT_LEG_DESIGN.md"),
    ("  ^ predecessor, reasoning only", "validation/RT_COMPARABILITY.md"),
    # 2026-09-17 (decision 193): a 13.6-hour run spec was written without reading the
    # trajectory, which had been superseded FOUR HOURS earlier. The table listed every
    # authority except the one that says what to run next. NEWEST_GLOB below resolves
    # to the current file, so a new trajectory cannot go unnoticed the way v2 did.
    ("WHAT TO RUN NEXT -- read before any run spec", "@newest:validation/TRAJECTORY_*.md"),
    ("primal compute vs K's budget", "validation/FINDING_rt_budget_fairness.md"),
    ("what is not novel, and why", "validation/S1_LITERATURE_BRIEF.md"),
    ("every reported number", "analysis/manuscript_numbers.py"),
    ("lemmas and their proofs", "paper/LEMMAS.md"),
    ("skeleton, figure/table slots", "paper/SKELETON.md"),
]


def live():
    """Running python processes and the tail of any log written in the last hour."""
    procs = []
    try:
        r = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=20)
        procs = [l.split()[1] for l in r.stdout.splitlines()
                 if l.lower().startswith("python.exe")]
    except Exception:
        pass
    now = dt.datetime.now().timestamp()
    hot = []
    for f in glob.glob(os.path.join(ROOT, "logs", "**", "*.log"), recursive=True) + \
             glob.glob(os.path.join(ROOT, "runs", "*.out")):
        if now - os.path.getmtime(f) < 3600:
            hot.append(os.path.relpath(f, ROOT))
    return procs, sorted(hot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="staleness check only")
    a = ap.parse_args()

    d, err = resume_date()
    stale = newer_than(d) if d else []

    if not a.quiet:
        print("=== SESSION STATE ===  today %s" % dt.date.today())
        procs, hot = live()
        print("\n-- LIVE --")
        print("  python processes : %s" % (", ".join(procs) if procs else "none"))
        if hot:
            for f in hot[:6]:
                print("  writing (<1h)    : %s" % f)
        else:
            print("  writing (<1h)    : nothing")

        print("\n-- GOVERNING DOCUMENTS -- open the authority BEFORE answering, not after --")
        for topic, path in AUTHORITIES:
            if path.startswith("@newest:"):
                # Resolve to the most recently modified match, so a superseding
                # document is surfaced automatically instead of silently ignored.
                cands = sorted(glob.glob(os.path.join(ROOT, path[8:])),
                               key=os.path.getmtime, reverse=True)
                if not cands:
                    print("  %-38s %s   (NONE FOUND)" % (topic, path[8:]))
                    continue
                path = os.path.relpath(cands[0], ROOT).replace("\\", "/")
                if len(cands) > 1:
                    topic += " [newest of %d]" % len(cands)
            full = os.path.join(ROOT, path)
            mark = ""
            if not os.path.exists(full):
                mark = "   (MISSING)"
            elif not topic.startswith("  ^"):
                # A named authority that declares itself superseded is worse than a
                # missing one: it reads as current and answers questions wrongly.
                # Decision 157 -- this exact failure cost a full day.
                # Banner form only -- a line that OPENS with the word, as
                # RT_COMPARABILITY.md:3 does ("> **SUPERSEDED 2026-09-13 by ...").
                # Matching any mention false-positives: manuscript_numbers.py:11 says
                # "artifact behind it is superseded twice" about something else.
                try:
                    for ln in open(full, encoding="utf-8").read(1500).splitlines()[:15]:
                        if re.match(r"^[\s>#*_-]*SUPERSEDED\b", ln.strip().upper()):
                            mark = "   *** DECLARES ITSELF SUPERSEDED -- FIX THIS TABLE ***"
                            break
                except Exception:
                    pass
            print("  %-38s %s%s" % (topic, path, mark))

        # d206: 22 runs were quarantined on 13-14 September and nothing reacted for two
        # weeks, because no status command printed this. The REAL enforcement is fixopt
        # refusing to start (d208); this banner exists so a human sees it too.
        try:
            _qg = subprocess.run([sys.executable,
                                  os.path.join(ROOT, "analysis", "quarantine_guard.py")],
                                 capture_output=True, text=True, timeout=30)
            if _qg.returncode != 0:
                print("")
                print("  !! VERIFIER/SOLVER CONTRADICTION -- fixopt WILL REFUSE TO START !!")
                for _l in _qg.stdout.splitlines():
                    if "UNTRIAGED" in _l or "CONTRADICTED" in _l:
                        print("  " + _l.strip())
                print("  triage before running: python analysis/quarantine_guard.py")
        except Exception:
            pass

        rows = decisions()
        print("\n-- SETTLED DECISIONS (%d) -- do not reopen without new evidence --" % len(rows))
        for r in rows:
            print("  [%s] %s" % (r.get("date", "?"), r.get("decision", "")))
            if r.get("where"):
                print("           where: %s" % r["where"])
        if not rows:
            print("  (none recorded -- validation/DECISIONS.jsonl is empty or missing)")

    print("\n-- STALENESS --")
    if err:
        print("  !! %s" % err)
        return 1
    print("  SESSION_RESUME.md declares: %s" % d)
    if not stale:
        print("  OK: no result artifact is newer than that date.")
        return 0
    print("  !! STALE by %d artifact(s). SESSION_RESUME.md does not know about:" % len(stale))
    for mt, f in stale[:12]:
        print("       %s  %s" % (mt, f))
    if len(stale) > 12:
        print("       ... and %d more" % (len(stale) - 12))
    print("")
    print("  THIS IS THE AMNESIA CONDITION. Results exist that the resume file does not")
    print("  record, so anything read from it is incomplete. Rewrite SESSION_RESUME.md")
    print("  (and append to validation/DECISIONS.jsonl) before proposing work.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
