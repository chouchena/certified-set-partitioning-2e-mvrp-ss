"""THE FOURTH GATE. Every change, run and claim is checked against the standing rules.

    python analysis/rules_alignment.py --change            # staged diff (pre-commit uses this)
    python analysis/rules_alignment.py --run  runs/oracle/lb_cell_R201_n50.json
    python analysis/rules_alignment.py --claim "our n20 mean is +12.461 vs banked"

WHY A FOURTH. Three gates already refuse: `artifact_guard` at the write, `artifact_gate` over
the output, `change_discipline` over the diff. Each answers one narrow mechanical question.
None of them asks whether the thing being done is ALIGNED WITH THE RULES -- whether a deletion
names the value it destroys, whether a comparative claim is like-for-like, whether an alarm was
tested before it was raised. Those are the failures that cost the most on 2026-09-29/30 and not
one of them would have tripped the first three gates.

TWO KINDS OF CHECK, AND THE FILE IS HONEST ABOUT WHICH IS WHICH.

  MECHANICAL  decidable from the text or the artifact. Refuses on its own.
  JUDGEMENT   needs a reader: was this standard the one the artifact was produced under? is
              this defect consequential? The gate cannot answer these, so it does not pretend
              to. It PRINTS them as an explicit question list and exits nonzero until each is
              answered in the message with `ALIGNED:<id> <reason>`. An unanswered judgement
              question blocks exactly as hard as a mechanical failure -- silence is not a pass.

That split is the point. A checker that scores judgement questions automatically would license
the confidence it cannot support; one that omits them checks only what is easy, which is how
`change_discipline` v1 missed the removed `check_secs` term.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))


def _git(*a):
    return subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True, text=True).stdout


class Report:
    def __init__(self):
        self.fail, self.judge, self.ok = [], [], []

    def mech(self, rid, passed, why):
        (self.ok if passed else self.fail).append((rid, why))

    def ask(self, rid, question):
        self.judge.append((rid, question))

    def emit(self, msg):
        answered = set(re.findall(r"ALIGNED:([A-Z]\d+)", msg or ""))
        open_q = [(i, q) for i, q in self.judge if i not in answered]
        print("rules alignment: %d mechanical passed, %d failed, %d judgement question(s), "
              "%d answered" % (len(self.ok), len(self.fail), len(self.judge),
                               len(self.judge) - len(open_q)))
        for rid, why in self.fail:
            print("  FAIL      %-5s %s" % (rid, why))
        for rid, q in open_q:
            print("  UNANSWERED %-4s %s" % (rid, q))
            print("             answer with  ALIGNED:%s <reason>  in the message" % rid)
        if self.fail or open_q:
            return 3
        print("  aligned")
        return 0


# --------------------------------------------------------------------------- CHANGE
def check_change(msg, rep, msg_path=None):
    staged = [f for f in _git("diff", "--cached", "--name-only").split()]
    deleted = [f for f in _git("diff", "--cached", "--name-only", "--diff-filter=D").split()
               if f.startswith("runs/")]
    body = msg or ""

    # C1 MECHANICAL -- behaviour changes named. Delegated so there is ONE definition.
    # The message file is passed THROUGH, not re-derived. Without it change_discipline falls
    # back to .git/COMMIT_EDITMSG, which under `git commit -m/-F` holds the PREVIOUS message.
    cd_cmd = [sys.executable, os.path.join(ROOT, "analysis", "change_discipline.py")]
    if msg_path:
        cd_cmd += ["--message", msg_path]
    r = subprocess.run(cd_cmd, cwd=ROOT, capture_output=True, text=True)
    rep.mech("C1", r.returncode == 0,
             "change_discipline refuses: a behaviour change is unnamed (run it for the list)")

    # C2 MECHANICAL -- a deletion of results must state the VALUE lost, not only the defect.
    if deleted:
        has = re.search(r"\b(zero|0\.0+|no) (LP |bound |)value\b|value lost|lp_street .*unchanged"
                        r"|identical to \w+ decimals|bought (nothing|zero)", body, re.I)
        rep.mech("C2", bool(has),
                 "%d result artifact(s) deleted and the message does not state what VALUE is "
                 "lost. CLAUDE.md: delete on a consequence, not a defect." % len(deleted))
        # C3 JUDGEMENT -- the standard question. Not decidable from text.
        rep.ask("C3", "%d artifact(s) deleted: were they defective by the standard they were "
                      "PRODUCED under, or by one adopted afterwards?" % len(deleted))

    # C4 MECHANICAL -- an alarm in the message must come with its test.
    alarm = re.search(r"\b(defect|bug|invalid|refuted|wrong|broken|violat\w+)\b", body, re.I)
    # WHAT COUNTS AS CITING A TEST. The first version omitted "audit", and so refused its own
    # introducing commit -- a message that said "audited against today's actual failures, and it
    # failed the first time" three times over. The gate was structurally right to block; its
    # vocabulary was wrong. Recorded because a checker's word list is itself a claim about what
    # evidence looks like.
    tested = re.search(r"\b(measured|verified|re-?ran|re-?audit\w*|audit\w*|trial|falsifier"
                       r"|checked|probe|smoke\w*|reproduc\w+)\b|\b0 of \d|\b\d+ of \d+",
                       body, re.I)
    if alarm:
        rep.mech("C4", bool(tested),
                 "the message reports a defect and cites no test. CLAUDE.md: an alarm is a "
                 "claim and carries the same burden.")

    # C5 MECHANICAL -- never 'novel'; 'validated' only as 'not refuted'.
    rep.mech("C5", not re.search(r"\bnovel\b", body, re.I), "the message says 'novel'")
    rep.mech("C6", not re.search(r"\b(validates?|validated|confirms?|confirmed) (the|that|our)\b",
                                 body, re.I),
             "the message says validated/confirmed; a falsification test can only refute")
    return staged


# --------------------------------------------------------------------------- RUN
def check_run(path, rep):
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:
        rep.mech("R0", False, "unreadable artifact: %s" % type(e).__name__); return
    p = d.get("_provenance") or {}
    rep.mech("R1", bool(p) and not p.get("sources_dirty") and not p.get("sources_unresolved"),
             "provenance absent, or sources_dirty/sources_unresolved non-empty")
    rep.mech("R2", bool((d.get("_rt") or {}).get("det_ticks")),
             "no deterministic clock on the artifact")
    rep.mech("R3", d.get("reproducible") is not False,
             "reproducible=false: the trajectory was decided by the wall clock")
    if d.get("size") is not None and d.get("cell"):
        try:
            from k_comparison import proven_cells
            rep.mech("R4", d["cell"] not in proven_cells(int(d["size"])),
                     "%s n%s is K-proven: a bound there is calibration, not a claim"
                     % (d["cell"], d["size"]))
            from k_comparison import k_proximity
            pr = (d.get("params") or {}).get("proximity", d.get("proximity"))
            if pr is not None:
                rep.mech("R5", abs(float(pr) - k_proximity(int(d["size"]))) < 1e-12,
                         "proximity %s but K's table for n%s is %s -- a different instance"
                         % (pr, d["size"], k_proximity(int(d["size"]))))
        except Exception:
            pass
    rep.ask("R6", "was an adverse pre-run audit written before this run, and does the cell "
                  "scope match the claim scope?")
    # R7 MECHANICAL -- d47's thread/tenancy rule, read off the artifact rather than trusted to
    # whichever driver happened to launch it. See analysis/rt_class.py for why it lives there.
    try:
        from rt_class import quotable, SUBMISSION_THREADS
        rt = d.get("_rt") or {}
        if rt.get("rt_class") == "submission":
            ok, why = quotable(d)
            rep.mech("R7", ok, "declares rt_class=submission and %s; d47 requires %d threads "
                               "and single tenancy" % (why, SUBMISSION_THREADS))
        elif (d.get("secs") is not None) and rt.get("rt_class") is None:
            rep.mech("R7", False,
                     "reports seconds and carries no rt_class, so nothing ever decided whether "
                     "this wall is quotable. That omission is how 55 one-thread walls reached a "
                     "comparison table on 2026-09-30. Pass rt_class= to stamped().")
    except Exception:
        pass


# --------------------------------------------------------------------------- CLAIM
def check_claim(text, rep):
    rep.mech("K1", not re.search(r"\bnovel\b", text, re.I), "the claim says 'novel'")
    rep.mech("K2", not re.search(r"\b(validates?|validated|confirms?|confirmed)\b", text, re.I),
             "'validated/confirmed' -- a falsification test can only refute; say 'not refuted'")
    # COMPARATIVE DETECTION. The first version wrote `\b\+\d`, and `\b` between a space and a
    # `+` is NOT a word boundary, so "+12.461" never matched; "gain over" was not in the list
    # either. Audited against the real confounded claim of 2026-09-30 -- "n20 finished with a
    # +12.461 mean gain over the banked best-of" -- the checker returned ALIGNED. A gate that
    # green-lights the exact failure it was built for is worse than no gate at all.
    comparative = re.search(
        r"(?:\bvs\b|\bversus\b|\bagainst\b|\bbeats?\b|\bbetter\b|\bworse\b|\bhigher\b"
        r"|\blower\b|\bgains?\b|\bloss(?:es)?\b|\bimprov\w+\b|\bdelta\b|\bmean\b"
        r"|\bover the\b|\bthan\b|\bx[0-9.]+\b|[+-]\s?\d|\d\s?%)", text, re.I)
    if comparative:
        rep.mech("K3", bool(re.search(r"(python |analysis/|runs/|\.py|\.json)", text)),
                 "comparative claim with no command or artifact cited. CLAUDE.md: every "
                 "comparative claim cites the command that produced it.")
        rep.ask("K4", "is this comparison LIKE FOR LIKE -- same instance, same proximity, same "
                      "pricer configuration, same certificate class? Today a +12.461 mean and "
                      "four 'disagreement' cells were confounded this way.")
    rep.mech("K5", bool(re.search(r"\bn\d{2,3}\b|\|C\| *= *\d+|size \d+", text)),
             "no size named. CLAUDE.md: every result names its size inline.")
    # K6 MECHANICAL -- a RUNTIME claim must rest on an artifact whose wall is quotable. This is
    # the half of d47 no gate could reach before: the rule's trigger is "feeds a REPORTED
    # runtime", and that happens when a claim is made, long after the artifact is sealed. On
    # 2026-09-30 a grid born `valid_bound: false` had its walls put into a comparison table --
    # legitimate at write time, a d47 breach at claim time, and nothing connected the two.
    if re.search(r"\b(wall|runtime|rt\b|seconds?|secs?\b|\d+ *s\b|faster|slower|speedup|"
                 r"time-to-best|ttb)\b", text, re.I):
        cited = re.findall(r"(runs/[\w/.\-]+\.json)", text)
        if not cited:
            rep.mech("K6", False, "a runtime claim citing no artifact. Name the runs/*.json "
                                  "whose wall this is, so d47 can be checked against it.")
        else:
            from rt_class import quotable
            bad = []
            for rel in cited:
                p = os.path.join(ROOT, rel)
                try:
                    ok, why = quotable(json.load(io.open(p, encoding="utf-8")))
                except Exception as e:
                    ok, why = False, "unreadable (%s)" % type(e).__name__
                if not ok:
                    bad.append("%s: %s" % (rel, why))
            rep.mech("K6", not bad,
                     "runtime quoted from artifact(s) whose wall is not quotable -- %s"
                     % "; ".join(bad[:3]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--change", action="store_true")
    ap.add_argument("--run")
    ap.add_argument("--claim")
    ap.add_argument("--message", default=None)
    a = ap.parse_args()
    rep = Report()
    if a.change:
        p = a.message or os.path.join(ROOT, ".git", "COMMIT_EDITMSG")
        msg = io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        check_change(msg, rep, a.message)
        return rep.emit(msg)
    if a.run:
        check_run(a.run, rep)
        return rep.emit(io.open(a.message, encoding="utf-8").read() if a.message else "")
    if a.claim:
        check_claim(a.claim, rep)
        return rep.emit(a.claim)
    ap.error("one of --change, --run, --claim")


if __name__ == "__main__":
    sys.exit(main())
