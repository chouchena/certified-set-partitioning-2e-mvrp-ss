"""SMOKE for verifier3: does it REJECT what it should, and ACCEPT what it should?

A verifier that accepts everything is useless and looks perfect. Corpus agreement with verify2 is
not evidence on its own -- two checkers can agree by both being inert. So this injects a KNOWN
violation of each published constraint into a known-good solution and requires the corresponding
class to fire.

Each mutation is the smallest edit that breaks exactly one constraint, so a fired class is
attributable. A mutation that fires NOTHING is a hole in verifier3. A mutation that fires the
WRONG class is a mis-attribution and is reported as a failure too.

    python analysis/smoke_verifier3.py
"""
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

import greedy26
import instance_view
import verifier3

CELL, SIZE, PROX = "R201", 20, 0.0


def base():
    raw = instance_view.VInstance._load_json(CELL)
    inst = instance_view.VInstance(CELL, SIZE, wls=0.1,
                                   tau=verifier3.tau_for(raw, SIZE), proximity=PROX)
    return inst, greedy26.construct(inst)


def corpus_base():
    """A SECOND base, from the corpus, because greedy26 closes a route at EVERY transfer.

    That means a greedy26 solution has no MID-ROUTE transfer, so the controls for (5) -- load
    never resets -- and (12) -- leaving the satellite early -- have no site to mutate. They were
    reported SKIPPED, which is honest but leaves two classes uncontrolled. A fixopt dump that
    verifier3 ACCEPTs supplies the missing shape.
    """
    import glob
    import json
    for path in sorted(glob.glob(os.path.join(ROOT, "runs", "solutions", "*n100*.json"))):
        run = verifier3.verify(path)
        if run.verdict() != verifier3.ACCEPT:
            continue
        sol = json.load(open(path, encoding="utf-8"))
        m = __import__("re").search(r"((?:RC|R|C)\d{3})_n(\d+)", os.path.basename(path))
        cell, size = m.group(1), int(m.group(2))
        prox = run.meta.get("proximity")
        inst = verifier3.load_instance(cell, size, prox)
        # does it actually have a mid-route transfer?
        depot = inst.depot
        t = {int(c) for c in sol["vi"]}
        mid = [c for c in t
               if not [a for a in sol["xij"] if int(a[0]) == c and int(a[1]) == depot]]
        if mid:
            return inst, sol, cell, size, prox
    return None, None, None, None, None


# --------------------------------------------------------------------------------------------
#  SPLICE HELPERS. A mutation must leave the routing WELL-FORMED, or verifier3's structural guard
#  halts the later legs (correctly -- a broken routing would otherwise fabricate thousands of
#  findings) and the mutation is attributed to A-STRUCT instead of the constraint it targets.
#  The corpus dumps are multi-trip, so deleting arcs is not enough: the tour must be re-closed.
# --------------------------------------------------------------------------------------------
def splice_street(s, c):
    """Remove customer c from its route, joining predecessor to successor."""
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
    """Remove transfer task c from its vessel tour, joining predecessor to successor."""
    pred = [a for a in s["yij"] if int(a[1]) == c]
    succ = [a for a in s["yij"] if int(a[0]) == c]
    s["yij"] = [a for a in s["yij"] if int(a[0]) != c and int(a[1]) != c]
    if len(pred) == 1 and len(succ) == 1:
        i, j = int(pred[0][0]), int(succ[0][1])
        if i != j:
            s["yij"].append([i, j])
    return True


def drop_transfer(s, c):
    """Stop c being a transfer: out of vi/hubs/ui, and spliced out of its vessel tour."""
    idx = [int(x) for x in s["vi"]]
    if c not in idx:
        return False
    i = idx.index(c)
    s["vi"] = [x for k, x in enumerate(s["vi"]) if k != i]
    s["hubs"] = [x for k, x in enumerate(s["hubs"]) if k != i]
    s["ui"].pop(str(c), None)
    splice_vessel(s, c)
    return True


# Each entry: (published constraint, description, mutation, class that MUST fire)
def mutations(inst, sol):
    C = list(inst.customers)
    t = [int(c) for c in sol["vi"]]
    U = inst.tau
    out = []

    def m_c26(s):
        """(26): drag one transfer's u onto another sharing its satellite."""
        hub = dict(zip([int(c) for c in s["vi"]], [int(p) for p in s["hubs"]]))
        bysat = {}
        for c, p in hub.items():
            bysat.setdefault(p, []).append(c)
        for p, mem in bysat.items():
            if len(mem) >= 2:
                a, b = mem[0], mem[1]
                s["ui"][str(b)] = float(s["ui"][str(a)]) + U / 2.0   # half the required gap
                return True
        return False
    out.append((26, "two transfers at one satellite only U/2 apart", m_c26, "C26"))

    def m_tw(s):
        """Table 1 / window: push one h below its earliest."""
        c = C[0]
        s["hi"][str(c)] = float(inst.nodes[c].earliest) - 50.0
        return True
    out.append(("T1", "h_i below a_i", m_tw, "T1-H-lo"))

    def m_deg(s):
        """(2): drop a customer from the routing entirely."""
        cand = [x for x in C if x not in t] or C
        for c in cand:
            if splice_street(s, c):
                return True
        return False
    out.append((2, "a customer served zero times", m_deg, "C2-DEG-out"))

    def m_obj(s):
        """(1): claim a better objective than the routing supports."""
        s["objVal"] = float(s["objVal"]) - 100.0
        return True
    out.append((1, "claimed objective 100 below the recomputation", m_obj, "OBJ"))

    def m_xfer(s):
        """(11): start a transfer before the LEFV can reach the satellite."""
        c = t[0]
        s["ui"][str(c)] = float(inst.nodes[inst.CDC].earliest)
        return True
    out.append((11, "u_i before the LEFV arrives at the satellite", m_xfer, "C11-XFER-START"))

    def m_sync(s):
        """(13): push a u past the vessel window's upper bound."""
        c = t[0]
        s["ui"][str(c)] = float(inst.nodes[inst.CDC].latest) + 10.0
        return True
    out.append((13, "u_i past the vessel window", m_sync, "C13-SYNC-hi"))

    def m_wdeg(s):
        """(16): leave a transfer unserved by any vessel."""
        return splice_vessel(s, t[0])
    out.append((16, "a transfer served by no vessel", m_wdeg, "C16-WDEG-out"))

    def m_lastxfer(s):
        """(4): remove the transfer that closes a route."""
        last = None
        for c in t:
            if [a for a in s["xij"] if int(a[0]) == c and int(a[1]) == inst.depot]:
                last = c
                break
        if last is None:
            return False
        return drop_transfer(s, last)
    out.append((4, "route returns to the garage with no final transfer", m_lastxfer,
                "C4-LASTXFER"))

    def m_cap(s):
        """(5): delete a MID-route transfer so the LEFV load never resets and overruns Q_s."""
        depot = inst.depot
        mid = None
        for c in t:
            if not [a for a in s["xij"] if int(a[0]) == c and int(a[1]) == depot]:
                mid = c
                break
        if mid is None:
            return False
        return drop_transfer(s, mid)
    out.append((5, "LEFV load never resets: a mid-route transfer removed", m_cap, "C5-LOAD"))

    def m_arc(s):
        """(6): give a successor the SAME service time as its predecessor on a plain arc."""
        succ = {int(a[0]): int(a[1]) for a in s["xij"] if int(a[0]) != inst.depot}
        for i, j in succ.items():
            if i in C and j in C and i not in t:
                s["hi"][str(j)] = float(s["hi"][str(i)])
                return True
        return False
    out.append((6, "successor served at the same instant as its predecessor", m_arc, "C6-ARC"))

    def m_depart(s):
        """(12): let the LEFV leave the satellite before the transfer completes."""
        succ = {int(a[0]): int(a[1]) for a in s["xij"] if int(a[0]) != inst.depot}
        for c in t:
            j = succ.get(c)
            if j is not None and j in C:
                s["hi"][str(j)] = float(s["ui"][str(c)])      # no U, no travel from the hub
                return True
        return False
    out.append((12, "next customer served the instant the transfer starts", m_depart,
                "C12-XFER-DEPART"))

    def m_wseq(s):
        """(20): two consecutive vessel tasks served at the same instant.

        Needs a tour with at least TWO tasks. greedy26 uses singleton vessels, so it has none --
        this is the control the smoke audit flagged as the most important gap, since (20) is the
        big-M row whose MijWater goes negative on 26-37% of pairs.
        """
        CDCn = inst.CDC
        succ = {int(a[0]): int(a[1]) for a in s["yij"] if int(a[0]) != CDCn}
        for a, b in succ.items():
            if b != CDCn and str(a) in s["ui"] and str(b) in s["ui"]:
                s["ui"][str(b)] = float(s["ui"][str(a)])
                return True
        return False
    out.append((20, "two consecutive vessel tasks at the same instant", m_wseq, "C20-WSEQ"))

    def m_timetable(s):
        """V1: strip the committed timetable entirely."""
        s["hi"], s["ui"] = {}, {}
        return True
    out.append(("V1", "no committed timetable at all", m_timetable, "A-TIMETABLE"))

    def m_nCars(s):
        """(3): misreport the fleet count."""
        s["nCars"] = int(s["nCars"]) + 3
        return True
    out.append((3, "claimed nCars exceeds the routes present", m_nCars, "C3-FLEET"))

    return out


def run_suite(inst, sol, cell, size, prox, title):
    """The whole suite against one base. Returns (failures, skipped)."""
    run = verifier3.verify_solution(inst, sol, cell=cell, size=size, proximity=prox)
    print("=" * 96)
    print("BASE: %s   (%s/n%d, proximity %s, tau %s)" % (title, cell, size, prox, inst.tau))
    print("  positive control: verdict %s   checks %d   violations %d"
          % (run.verdict(), run.total_checks, len(run.violations)))
    fails, skipped = [], []
    if run.verdict() != verifier3.ACCEPT:
        fails.append("%s: positive control did not ACCEPT" % title)
        for f in run.violations[:4]:
            print("     ", f.cls, f.node, (f.detail or "")[:60])
    print()
    hdr = "%-5s %-52s %-9s %-18s %s" % ("(n)", "injected violation", "verdict", "class fired",
                                        "result")
    print(hdr)
    print("-" * len(hdr))
    for num, desc, mut, want in mutations(inst, sol):
        s2 = copy.deepcopy(sol)
        try:
            applied = mut(s2)
        except Exception as e:
            applied = False
            desc = desc + " [mutation error: %s]" % type(e).__name__
        if not applied:
            print("%-5s %-52s %-9s %-18s %s" % (num, desc[:52], "-", "-", "SKIPPED (no site)"))
            skipped.append("(%s) %s" % (num, desc))
            continue
        r = verifier3.verify_solution(inst, s2, cell=cell, size=size, proximity=prox)
        fired = sorted({f.cls for f in r.findings
                        if f.severity in ("VIOLATION", "UNEVALUATED")})
        got = want in fired
        rejected = r.verdict() == verifier3.REJECT
        res = "ok" if (got and rejected) else ("WRONG CLASS" if rejected else "NOT DETECTED")
        if not (got and rejected):
            fails.append("%s (%s) %s -> %s, fired %s, wanted %s"
                         % (title, num, desc, r.verdict(), fired or "nothing", want))
        print("%-5s %-52s %-9s %-18s %s"
              % (num, desc[:52], r.verdict(), (",".join(fired))[:18], res))
    print()
    return fails, skipped


def main():
    inst, sol = base()
    if sol is None:
        print("greedy26 declined on %s/n%d -- cannot smoke" % (CELL, SIZE))
        return 2
    print("verifier3 smoke -- negative controls over TWO bases")
    print()
    all_fails, all_skipped = [], []

    f1, s1 = run_suite(inst, sol, CELL, SIZE, PROX, "greedy26 construction")
    all_fails += f1
    all_skipped += [("greedy26", x) for x in s1]

    cinst, csol, ccell, csize, cprox = corpus_base()
    if csol is None:
        print("NOTE: no ACCEPT corpus dump with a mid-route transfer was found; the controls")
        print("      skipped above stay uncontrolled and that is a REAL gap, not a pass.")
        all_fails.append("no second base available: (5) and (12) remain uncontrolled")
    else:
        f2, s2 = run_suite(cinst, csol, ccell, csize, cprox, "corpus dump (mid-route transfers)")
        all_fails += f2
        all_skipped += [("corpus", x) for x in s2]

    print("=" * 96)
    print("SMOKE: %d failure(s)" % len(all_fails))
    for f in all_fails:
        print("   " + f)
    if all_skipped:
        print()
        print("SKIPPED for want of a site (not a pass, and not a failure -- the shape does not")
        print("occur in that base):")
        for who, x in all_skipped:
            print("   [%s] %s" % (who, x))
    if not all_fails:
        print()
        print("PASS -- every base ACCEPTs unmutated, and every injected violation with a site is")
        print("REJECTED by the class that owns it. verifier3 is not inert and attributes correctly.")
    return 1 if all_fails else 0


if __name__ == "__main__":
    sys.exit(main())
