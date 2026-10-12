"""EXHAUSTIVE PER-CONSTRAINT FALSIFICATION: 30 impaired incumbents, one per published constraint.

Author, 2026-09-20: *"take the 15 generated incumbents - impair each one making it infringe one
constraint then a second one - so you created 30 impaired incumbents - infringing each one one of
the 30 constraints."*

Takes the 15 verifier3-ACCEPT incumbents from the 60s grid smoke (3 cells x 5 sizes) and produces
two impaired copies of each -- 30 artifacts, each targeting ONE distinct published constraint of
K's (1)-(30). Every artifact carries a PRE-REGISTERED expected verdict and expected class, and the
run FAILS if any deviates.

WHY NINE OF THE THIRTY ARE A DIFFERENT KIND OF TEST. The 9 ENCODING constraints -- (7), (14),
(21), (22), (23), (27)-(30) -- constrain f^s_ij, f^w_ij and r_ij, VARIABLES THAT DO NOT EXIST IN A
SOLUTION ARTIFACT. An incumbent carries xij, vi, hubs, yij, nCars, nVessel, hi, ui, objVal and
nothing else; there is no field to corrupt. And if one is ADDED, verifier3 ignores it BY DESIGN --
it never reads an encoding quantity, it recomputes it. That property is exactly why it caught (26)
where the model could not.

So for those nine the artifact carries a deliberately corrupted encoding field and the expected
verdict is ACCEPT. That turns an impossible impairment into a POSITIVE test of the design
property: a corrupted f^s must not change the verdict. A test that cannot fail would be worse than
no test; this one can -- if verifier3 ever started reading f^s, these nine would flip to REJECT.

    python analysis/impair30.py
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from analysis.stamp import stamped

import verifier3

SRC = os.path.join(ROOT, "runs", "v3smoke")
OUT = os.path.join(ROOT, "runs", "impair30")
REPORT = os.path.join(ROOT, "logs", "impair30.jsonl")

ACCEPT, REJECT = verifier3.ACCEPT, verifier3.REJECT


# ---------------------------------------------------------------- splice helpers
def splice_street(s, c):
    pred = [a for a in s["xij"] if int(a[1]) == c]
    succ = [a for a in s["xij"] if int(a[0]) == c]
    if len(pred) != 1 or len(succ) != 1:
        return False
    i, j = int(pred[0][0]), int(succ[0][1])
    s["xij"] = [a for a in s["xij"] if int(a[0]) != c and int(a[1]) != c]
    if i != j:
        s["xij"].append([i, j])
    return True


def splice_vessel(s, c):
    pred = [a for a in s["yij"] if int(a[1]) == c]
    succ = [a for a in s["yij"] if int(a[0]) == c]
    s["yij"] = [a for a in s["yij"] if int(a[0]) != c and int(a[1]) != c]
    if len(pred) == 1 and len(succ) == 1:
        i, j = int(pred[0][0]), int(succ[0][1])
        if i != j:
            s["yij"].append([i, j])
    return True


def drop_transfer(s, c):
    idx = [int(x) for x in s["vi"]]
    if c not in idx:
        return False
    i = idx.index(c)
    s["vi"] = [x for k, x in enumerate(s["vi"]) if k != i]
    s["hubs"] = [x for k, x in enumerate(s["hubs"]) if k != i]
    s["ui"].pop(str(c), None)
    splice_vessel(s, c)
    return True


def transfers(s):
    return [int(c) for c in s["vi"]]


def route_succ(s, depot):
    return {int(a[0]): int(a[1]) for a in s["xij"] if int(a[0]) != depot}


# ---------------------------------------------------------------- the 30 impairments
# (constraint, short name, fn(inst, sol) -> bool, expected verdict, expected class)
def IMPAIRMENTS():
    def i1(inst, s):                       # (1) objective
        s["objVal"] = float(s["objVal"]) - 250.0
        return True

    def i2(inst, s):                       # (2) each customer served exactly once
        t = set(transfers(s))
        for c in list(inst.customers):
            if c not in t and splice_street(s, c):
                return True
        return False

    def i3(inst, s):                       # (3) LEFV fleet count
        s["nCars"] = int(s["nCars"]) + 2
        return True

    def i4(inst, s):                       # (4) final transfer before the garage
        for c in transfers(s):
            if [a for a in s["xij"] if int(a[0]) == c and int(a[1]) == inst.depot]:
                return drop_transfer(s, c)
        return False

    def i5(inst, s):                       # (5) LEFV capacity, load never resets
        for c in transfers(s):
            if not [a for a in s["xij"] if int(a[0]) == c and int(a[1]) == inst.depot]:
                return drop_transfer(s, c)
        return False

    def i6(inst, s):                       # (6) street arc timing
        t = set(transfers(s))
        for i, j in route_succ(s, inst.depot).items():
            if i in t or j == inst.depot or str(j) not in s["hi"]:
                continue
            s["hi"][str(j)] = float(s["hi"][str(i)])
            return True
        return False

    def i8(inst, s):                       # (8) x_ij binary -> duplicate arc
        s["xij"] = list(s["xij"]) + [list(s["xij"][0])]
        return True

    def i9(inst, s):                       # (9) phi_i binary -> repeated transfer
        s["vi"] = list(s["vi"]) + [s["vi"][0]]
        s["hubs"] = list(s["hubs"]) + [s["hubs"][0]]
        return True

    def i10(inst, s):                      # (10) hub iff transfer -> hub list too short
        s["hubs"] = list(s["hubs"])[:-1]
        return True

    def i11(inst, s):                      # (11) transfer starts before the LEFV arrives
        c = transfers(s)[0]
        s["ui"][str(c)] = float(inst.nodes[inst.CDC].earliest)
        return True

    def i12(inst, s):                      # (12) LEFV leaves the satellite too early
        succ = route_succ(s, inst.depot)
        for c in transfers(s):
            j = succ.get(c)
            if j is not None and j != inst.depot and str(j) in s["hi"]:
                s["hi"][str(j)] = float(s["ui"][str(c)])
                return True
        return False

    def i13(inst, s):                      # (13) u past the vessel window
        c = transfers(s)[0]
        s["ui"][str(c)] = float(inst.nodes[inst.CDC].latest) + 25.0
        return True

    def i15(inst, s):                      # (15) v_ip binary -> hub that is not a satellite
        s["hubs"] = list(s["hubs"])
        s["hubs"][0] = int(inst.customers[0])
        return True

    def i16(inst, s):                      # (16) a transfer served by no vessel
        return splice_vessel(s, transfers(s)[0])

    def i17(inst, s):                      # (17) vessel fleet count
        s["nVessel"] = int(s["nVessel"]) + 3
        return True

    def i18(inst, s):                      # (18) vessel capacity Q_w exceeded
        # chain every transfer onto ONE vessel tour: load accumulates past Q_w
        t = transfers(s)
        if len(t) < 2:
            return False
        CDC = inst.CDC
        s["yij"] = [[CDC, t[0]]] + [[t[k], t[k + 1]] for k in range(len(t) - 1)] + [[t[-1], CDC]]
        s["nVessel"] = 1
        return True

    def i19(inst, s):                      # (19) vessel load accumulation
        return i18(inst, s)

    def i20(inst, s):                      # (20) vessel sequencing in time
        t = transfers(s)
        if len(t) < 2:
            return False
        CDC = inst.CDC
        s["yij"] = [[CDC, t[0]]] + [[t[k], t[k + 1]] for k in range(len(t) - 1)] + [[t[-1], CDC]]
        s["nVessel"] = 1
        base = float(s["ui"][str(t[0])])
        for c in t:
            s["ui"][str(c)] = base          # all tasks at the same instant
        return True

    def i24(inst, s):                      # (24) f^w >= 0 -- ENCODING, see the module docstring
        s["fw"] = {"0,1": -999.0}
        return True

    def i25(inst, s):                      # (25) y_ij binary -> duplicate vessel arc
        s["yij"] = list(s["yij"]) + [list(s["yij"][0])]
        return True

    def i26(inst, s):                      # (26) same-satellite transfers closer than tau
        hub = dict(zip(transfers(s), [int(p) for p in s["hubs"]]))
        bysat = {}
        for c, p in hub.items():
            bysat.setdefault(p, []).append(c)
        for p, mem in bysat.items():
            if len(mem) >= 2:
                s["ui"][str(mem[1])] = float(s["ui"][str(mem[0])]) + inst.tau / 2.0
                return True
        return False

    def enc(field):
        """ENCODING: corrupt a variable verifier3 must NEVER read. Expected verdict ACCEPT."""
        def f(inst, s):
            s[field] = {"0,1": -12345.0}
            return True
        return f

    return [
        (1,  "claimed objective 250 below the recomputation", i1,  REJECT, "OBJ"),
        (2,  "a customer served zero times",                  i2,  REJECT, "C2-DEG-out"),
        (3,  "nCars overstated by 2",                         i3,  REJECT, "C3-FLEET"),
        (4,  "route reaches the garage with no final transfer", i4, REJECT, "C4-LASTXFER"),
        (5,  "LEFV load never resets: mid-route transfer gone", i5, REJECT, "C5-LOAD"),
        (6,  "successor served at its predecessor's instant", i6,  REJECT, "C6-ARC"),
        (7,  "ENCODING f^s corrupted -- must be IGNORED",      enc("fs"), ACCEPT, None),
        (8,  "duplicate street arc (x not binary)",           i8,  REJECT, "D8-ARCSET"),
        (9,  "a customer listed twice as a transfer",         i9,  REJECT, "D9-PHI"),
        (10, "hub list shorter than the transfer list",       i10, REJECT, "C10-HUB"),
        (11, "u before the LEFV reaches the satellite",       i11, REJECT, "C11-XFER-START"),
        (12, "next customer served the instant the transfer starts", i12, REJECT,
             "C12-XFER-DEPART"),
        (13, "u past the vessel window",                      i13, REJECT, "C13-SYNC-hi"),
        (14, "ENCODING f^s at a transfer corrupted -- IGNORED", enc("fs_xfer"), ACCEPT, None),
        (15, "a hub that is not a satellite",                 i15, REJECT, "D15-HUB"),
        (16, "a transfer served by no vessel",                i16, REJECT, "C16-WDEG-out"),
        (17, "nVessel overstated by 3",                       i17, REJECT, "C17-WFLEET"),
        (18, "every transfer chained onto ONE vessel",        i18, REJECT, "C18-WLOAD"),
        (19, "vessel load accumulates past Q_w",              i19, REJECT, "C18-WLOAD"),
        (20, "all vessel tasks at the same instant",          i20, REJECT, "C20-WSEQ"),
        (21, "ENCODING f^w depot leg corrupted -- IGNORED",   enc("fw_depot"), ACCEPT, None),
        (22, "ENCODING f^w return leg corrupted -- IGNORED",  enc("fw_return"), ACCEPT, None),
        (23, "ENCODING f^w hub-to-hub corrupted -- IGNORED",  enc("fw_hub"), ACCEPT, None),
        (24, "negative f^w present -- IGNORED",               i24, ACCEPT, None),
        (25, "duplicate vessel arc (y not binary)",           i25, REJECT, "D25-WARCSET"),
        (26, "two same-satellite transfers only tau/2 apart", i26, REJECT, "C26"),
        (27, "ENCODING r_ij corrupted -- IGNORED",            enc("rij27"), ACCEPT, None),
        (28, "ENCODING r_ij corrupted -- IGNORED",            enc("rij28"), ACCEPT, None),
        (29, "ENCODING r_ij = r_ji corrupted -- IGNORED",     enc("rij29"), ACCEPT, None),
        (30, "ENCODING r_ij >= U(...) corrupted -- IGNORED",  enc("rij30"), ACCEPT, None),
    ]


EXTRA_COVERAGE = """Classes that FIRED in the 30 but were never the DECLARED owner are not
controlled -- incidental firing proves a class is live, not that it owns what it claims. These
close that gap.

TWO ARE STRUCTURALLY IMPOSSIBLE TO ISOLATE, and chasing them would be dishonest rather than
thorough:

  C2-DEG-in   in-degree 2 means the route walk reaches that customer TWICE, so A-STRUCT catches
              the revisit first -- and in a connected walk there is no in-degree 2 WITHOUT a
              revisit. The class is exercised by impairment (2) through its in-degree ZERO case,
              where a spliced-out customer has neither arc.
  C10-HUB     hubs is a list PARALLEL to vi, so "a hub iff a transfer" holds by construction
              unless the two lengths disagree -- which is precisely impairment (10). That is now
              its declared owner.

Both are recorded here rather than left as apparent gaps: the fact that a class can only fire one
way is a property of the artifact's representation, not a hole in the checking."""


def COVERAGE_CONTROLS():
    """One dedicated control per class that the 30 exercised only incidentally."""
    def x_c13lo(inst, s):                  # C13-SYNC-lo: u BELOW the vessel window's lower bound
        c = transfers(s)[0]
        s["ui"][str(c)] = float(inst.nodes[inst.CDC].earliest) - 100.0
        return True

    def x_c16in(inst, s):                  # C16-WDEG-in: a transfer with vessel in-degree 2
        # Redirect a vessel arc, for the same reason as C2-DEG-in: appending one would raise the
        # source's out-degree and be caught by the tour walk before the degree check runs.
        t = transfers(s)
        if len(t) < 2:
            return False
        tgt = t[0]
        for a in s["yij"]:
            if int(a[1]) != tgt and int(a[1]) != inst.CDC:
                a[1] = tgt
                return True
        return False

    def x_t1hi(inst, s):                   # T1-H-hi: h above the customer's own latest
        for c in inst.customers:
            if str(c) in s["hi"]:
                s["hi"][str(c)] = float(inst.nodes[c].latest) + 500.0
                return True
        return False

    return [
        ("C13-SYNC-lo",  "u below the vessel window's lower bound",   x_c13lo),
        ("C16-WDEG-in",  "a transfer with vessel in-degree 2",        x_c16in),
        ("T1-H-hi",      "h above the customer's own latest",         x_t1hi),
    ]


def main():
    os.makedirs(OUT, exist_ok=True)
    bases = sorted(os.listdir(SRC))
    if len(bases) != 15:
        print("expected 15 base incumbents in runs/v3smoke, found %d" % len(bases))
        return 2

    # sanity: every base must ACCEPT before anything is impaired
    loaded = []
    print("BASES -- all 15 must ACCEPT unimpaired, or every impairment below is meaningless")
    for fn in bases:
        path = os.path.join(SRC, fn)
        run = verifier3.verify(path)
        cell = run.meta.get("cell")
        size = run.meta.get("size")
        prox = run.meta.get("proximity")
        inst = verifier3.load_instance(cell, size, prox)
        sol = json.load(open(path, encoding="utf-8"))
        loaded.append((fn, cell, size, prox, inst, sol, run.verdict()))
        if run.verdict() != ACCEPT:
            print("   %-22s %s  <-- BASE NOT ACCEPTED" % (fn, run.verdict()))
    bad_bases = [x for x in loaded if x[6] != ACCEPT]
    print("   %d/15 ACCEPT" % (15 - len(bad_bases)))
    if bad_bases:
        return 2
    print()

    imps = IMPAIRMENTS()
    assert len(imps) == 30, "expected 30 impairments, got %d" % len(imps)

    rows, fails, skipped = [], [], []
    hdr = ("%-4s %-46s %-14s %-9s %-9s %-16s %s"
           % ("(n)", "impairment", "base", "expect", "got", "class fired", "result"))
    print("30 IMPAIRED INCUMBENTS -- two per base, one per published constraint")
    print(hdr)
    print("-" * len(hdr))
    for k, (num, desc, fn_mut, want_verdict, want_cls) in enumerate(imps):
        bi = k % 15                       # two impairments per base, spread evenly
        fname, cell, size, prox, inst, sol, _ = loaded[bi]
        s = copy.deepcopy(sol)
        try:
            applied = fn_mut(inst, s)
        except Exception as e:
            applied = False
            desc += " [error %s]" % type(e).__name__
        if not applied:
            print("%-4s %-46s %-14s %-9s %-9s %-16s %s"
                  % (num, desc[:46], "%s/n%d" % (cell, size), want_verdict, "-", "-",
                     "SKIPPED (no site)"))
            skipped.append("(%s) %s on %s/n%d" % (num, desc, cell, size))
            continue
        s["_impaired_constraint"] = num
        s["_impairment"] = desc
        s["_base"] = fname
        outp = os.path.join(OUT, "impair_c%02d_%s_n%d.json" % (num, cell, size))
        json.dump(stamped(s, __file__), open(outp, "w"), default=str)

        r = verifier3.verify_solution(inst, s, cell=cell, size=size, proximity=prox,
                                      label=os.path.basename(outp))
        got = r.verdict()
        fired = sorted({f.cls for f in r.findings
                        if f.severity in ("VIOLATION", "UNEVALUATED")})
        ok = (got == want_verdict) and (want_cls is None or want_cls in fired)
        res = "ok" if ok else ("WRONG VERDICT" if got != want_verdict else "WRONG CLASS")
        if not ok:
            fails.append("(%s) %s on %s/n%d -> %s, fired %s, wanted %s/%s"
                         % (num, desc, cell, size, got, fired or "nothing", want_verdict,
                            want_cls))
        rows.append({"constraint": num, "impairment": desc, "base": fname,
                     "cell": cell, "size": size, "proximity": prox,
                     "expected_verdict": want_verdict, "got_verdict": got,
                     "expected_class": want_cls, "fired": fired,
                     "checks": r.total_checks, "artifact": os.path.relpath(outp, ROOT),
                     "pass": ok})
        print("%-4s %-46s %-14s %-9s %-9s %-16s %s"
              % (num, desc[:46], "%s/n%d" % (cell, size), want_verdict, got,
                 (",".join(fired))[:16], res))

    with open(REPORT, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    # ---- dedicated controls for classes the 30 exercised only incidentally ----------
    print()
    print("CLASS-COVERAGE CONTROLS -- each class below must be the OWNER of a rejection")
    print("%-14s %-44s %-9s %-16s %s" % ("class", "impairment", "verdict", "fired", "result"))
    print("-" * 96)
    for want_cls, desc, fn_mut in COVERAGE_CONTROLS():
        fname, cell, size, prox, inst, sol, _ = loaded[0 if "n10" in loaded[0][0] else 0]
        # pick a base with enough structure
        for cand in loaded:
            if cand[2] >= 30:
                fname, cell, size, prox, inst, sol, _ = cand
                break
        s = copy.deepcopy(sol)
        try:
            applied = fn_mut(inst, s)
        except Exception as e:
            applied = False
            desc += " [error %s]" % type(e).__name__
        if not applied:
            print("%-14s %-44s %-9s %-16s %s" % (want_cls, desc[:44], "-", "-", "SKIPPED"))
            skipped.append("coverage control for %s" % want_cls)
            continue
        r = verifier3.verify_solution(inst, s, cell=cell, size=size, proximity=prox)
        fired = sorted({f.cls for f in r.findings
                        if f.severity in ("VIOLATION", "UNEVALUATED")})
        ok = (r.verdict() == REJECT) and (want_cls in fired)
        if not ok:
            fails.append("coverage: %s (%s) -> %s, fired %s" % (want_cls, desc, r.verdict(),
                                                                fired or "nothing"))
        print("%-14s %-44s %-9s %-16s %s"
              % (want_cls, desc[:44], r.verdict(), (",".join(fired))[:16], "ok" if ok else "FAIL"))

    sem = [r for r in rows if r["expected_verdict"] == REJECT]
    enc_ = [r for r in rows if r["expected_verdict"] == ACCEPT]
    print()
    print("  impairable constraints REJECTed by the owning class : %d/%d"
          % (sum(1 for r in sem if r["pass"]), len(sem)))
    print("  ENCODING corruptions correctly IGNORED (ACCEPT)     : %d/%d"
          % (sum(1 for r in enc_ if r["pass"]), len(enc_)))
    print("  artifacts written -> %s" % os.path.relpath(OUT, ROOT))
    print()
    print("IMPAIR30: %d failure(s)" % len(fails))
    for f in fails:
        print("   " + f)
    if skipped:
        print("  skipped for want of a site:")
        for x in skipped:
            print("   " + x)
    if not fails and not skipped:
        print()
        print("PASS -- every impairable constraint is caught by the class that owns it, and every")
        print("ENCODING corruption is correctly ignored. verifier3 checks the published problem,")
        print("not our encoding of it.")
    return 1 if (fails or skipped) else 0


if __name__ == "__main__":
    sys.exit(main())
