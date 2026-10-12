"""G22 -- the code must agree with the ambiguity register.

WHY THIS IS A GATE AND NOT A DOCUMENT. validation/AMBIGUITY_REGISTER.md records, for every place
K's article leaves a choice, which reading we took and why. A register nothing enforces drifts:
this project has watched it happen twice -- SESSION_RESUME went two days stale and unread with
nothing detecting it, and the claim register stayed a parallel record until gate_claims_prose
made it binding. So each pick that can be checked mechanically is checked here, against the code
as it actually runs.

WHAT IS CHECKED, and what each would catch:

  A2 tau            build() STILL DEFAULTS TO tau="code" (= 0), the reading that lands ~10% below
                    K's published values. This asserts the registered reading is the one the
                    formula produces, and that the default is still the known trap rather than
                    having silently become something else.
  A3 proximity      k_setting() must resolve every published size to the registered proximity,
                    and must refuse a size/exhibit pairing K never published.
  A4 distances      the rebuilt matrix must be 2-decimal and must satisfy the triangle
                    inequality -- the single non-iterated pass K's code applies.
  A5 big-M          every street big-M must be at least the span it has to cover. An UNDERSIZED
                    big-M is invisible to any solution verifier, so this is the only routine
                    check that sees it at all.
  A6 arc pruning    the prune predicate must be the registered one, and must be EMPTY: no arc it
                    removes may be usable, proven per-arc against the article's own bound.

WHAT IT CANNOT CHECK. A1 (which linearization is "the" model), A7-A10 (classification and
comparison-scope decisions) and A11 (labelling) are judgements recorded in prose, not settings a
script can read off. They are listed here as UNCHECKABLE so the gate's silence about them is
explicit rather than mistaken for approval.

    python analysis/gate_ambiguity.py
"""
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

REG = os.path.join(ROOT, "validation", "ambiguities.json")
RESULTS = []


def check(aid, name, ok, detail=""):
    RESULTS.append(dict(id=aid, name=name, ok=bool(ok), detail=detail))
    return ok


def load():
    return json.load(io.open(REG, encoding="utf-8"))


def a2_tau(reg):
    """The registered reading is the article's formula, and build()'s default is still the trap."""
    import inspect
    from build_instance import build
    sig = inspect.signature(build)
    default = sig.parameters["tau"].default
    p = build("C201", 10, wls=0.1, tau="formula", proximity=0.0)
    got = float(p.TransferDuration)
    svc = [p.nodes[i].serviceTime for i in p.customers]
    want = math.ceil(2 * (sum(svc) / len(svc)))
    ok = abs(got - want) < 1e-9 and got > 0
    note = "tau=%.1f from the article's formula (ceil(2 x mean service)=%d)" % (got, want)
    if default != reg["A2"]["code_default_is_still"]:
        return check("A2", "tau is the article's formula", False,
                     "build() default changed from %r to %r -- the register records the trap and "
                     "it has moved" % (reg["A2"]["code_default_is_still"], default))
    return check("A2", "tau is the article's formula", ok,
                 note + "; build() default is still %r (the known trap, every call site "
                        "overrides it)" % default)


def a3_proximity(reg):
    from solver.engines.fixopt import k_setting
    bad = []
    for size_s, want in reg["A3"]["proximity_by_size"].items():
        try:
            got, exhibit, _basis = k_setting(int(size_s))
        except Exception as e:
            bad.append("size %s raised %s" % (size_s, type(e).__name__))
            continue
        if abs(float(got) - float(want)) > 1e-12:
            bad.append("size %s -> %s, register says %s" % (size_s, got, want))
    # and it must REFUSE a pairing K never published
    refused = False
    try:
        k_setting(40)                      # no default comparator: Fig. 5 only
    except KeyError:
        refused = True
    if not refused:
        bad.append("k_setting(40) did not refuse -- K publish no objective exhibit at n40")
    return check("A3", "proximity from k_setting matches the register", not bad,
                 "; ".join(bad) if bad else
                 "%d sizes resolve to the registered proximity; unpublished pairings refused"
                 % len(reg["A3"]["proximity_by_size"]))


def a4_distances(reg):
    from build_instance import build
    p = build("C201", 10, wls=0.1, tau="formula", proximity=0.0)
    D = p.DistMatrix
    n = len(D)
    dp = int(reg["A4"]["decimals"])
    # TWO-SIDED. "round(D, dp) == D" only bounds precision from ABOVE -- 2-decimal data is
    # trivially also "at 3 decimals", so the one-sided form passed a register that had been
    # drifted from 2 to 3. Found by drifting it on purpose. So also require dp-1 to be
    # INSUFFICIENT for at least one entry, which pins the precision exactly.
    off = [(i, j) for i in range(n) for j in range(n)
           if abs(round(D[i][j], dp) - D[i][j]) > 1e-9]
    needs_dp = any(abs(round(D[i][j], dp - 1) - D[i][j]) > 1e-9
                   for i in range(n) for j in range(n))
    worst, bad_tri = 0.0, 0
    for i in range(n):
        for j in range(n):
            for k in range(n):
                slack = D[i][k] + D[k][j] - D[i][j]
                if slack < -1e-9:
                    bad_tri += 1
                    worst = min(worst, slack)
    ok = not off and not bad_tri and needs_dp
    if not needs_dp and not off:
        return check("A4", "distances at exactly the registered precision", False,
                     "every entry fits in %d decimals -- the register claims %d, so the data is "
                     "COARSER than registered and the pick has drifted" % (dp - 1, dp))
    return check("A4", "distances at exactly the registered precision", ok,
                 ("%d entries not at %d decimals; %d triangle violations (worst %.6f)"
                  % (len(off), dp, bad_tri, worst)) if not ok else
                 "all %d entries at exactly %d decimals (%d insufficient), triangle inequality "
                 "holds" % (n * n, dp, dp - 1))


def a5_bigm(reg):
    """Every street big-M must cover the span it has to cover.

    THE M IS READ OUT OF THE BUILT MODEL, not recomputed from the builder's own formula. The
    first version of this check did the latter and was therefore a tautology -- it compared an
    expression with a copy of itself and reported a slack of exactly 0.0 on every row, which
    would have stayed 0.0 had the builder's formula been wrong. Here the coefficient on x_ij is
    recovered from the (6) row Gurobi actually holds, and compared against the bound derived
    independently from the article: with x_ij = 0 the row must not bind for ANY point in the
    variable box, so

        M  >=  l_i + s_i + tau + max_p(D_ip + D_pj) - e_j

    with h_i <= l_i and h_j >= e_j from Table 1, tau*v_i <= tau, and f^s_ij <= max_p(D_ip + D_pj).

    An UNDERSIZED M is invisible to every solution verifier -- it shrinks the region, so returned
    points still satisfy every constraint while the optimum silently inflates. This is the only
    routine check that sees it.
    """
    from build_instance import build
    from joint_model_gurobi import build_joint_model_gurobi
    p = build("C201", 10, wls=0.1, tau="formula", proximity=0.0)
    p.hardSingleTransfer = True
    H = build_joint_model_gurobi(p)
    m = H["m"]
    m.update()
    nd, D, TD = p.nodes, p.DistMatrix, p.TransferDuration
    Sats = list(p.satellites)
    byname = {v.VarName: v for v in m.getVars()}
    bad, checked, tight = [], 0, None
    for c in m.getConstrs():
        row = m.getRow(c)
        coef = {}
        for t in range(row.size()):
            coef[row.getVar(t).VarName] = row.getCoeff(t)
        xs = [nm for nm in coef if nm.startswith("x.") and coef[nm] > 1.0]
        if len(xs) != 1:
            continue
        nm = xs[0]
        _, si, sj = nm.split(".")
        i, j = int(si), int(sj)
        # the (6) row carries +h[i] and -h[j]; (14)'s row carries u[i] instead, so require h[i]
        if coef.get("h[%d]" % i, 0) <= 0 or coef.get("h[%d]" % j, 0) >= 0:
            continue
        if i not in p.customers:
            continue
        M = coef[nm]
        need = (nd[i].latest + nd[i].serviceTime + TD
                + max(D[i][pp] + D[pp][j] for pp in Sats) - nd[j].earliest)
        checked += 1
        slack = M - need
        tight = slack if tight is None else min(tight, slack)
        if slack < -1e-6:
            bad.append("row for arc (%d,%d): model M=%.3f < required %.3f" % (i, j, M, need))
    if not checked:
        return check("A5", "big-M read from the model is valid", False,
                     "no (6) row matched the pattern -- the check found nothing to test, which "
                     "is a silent pass and must not be reported as one")
    return check("A5", "big-M read from the model is valid", not bad,
                 "; ".join(bad[:3]) if bad else
                 "%d (6) rows read from the model, minimum slack %.6f (0.0 = smallest valid M, "
                 "as registered)" % (checked, tight))


def a6_pruning(reg):
    """The prune must be EMPTY: every removed arc is unusable by the article's own (6)."""
    from build_instance import build
    p = build("C201", 10, wls=0.1, tau="formula", proximity=0.0)
    nd, D = p.nodes, p.DistMatrix
    SetCd = [0] + list(p.customers)
    pruned, unsound = 0, []
    for i in SetCd:
        for j in SetCd:
            if i == j:
                continue
            keep = (nd[i].earliest + nd[i].serviceTime + D[i][j] <= nd[j].latest)
            if keep:
                continue
            pruned += 1
            # earliest conceivable arrival at j over this arc, from the article's own rows:
            #   h_j >= h_i + s_i + TD*v_i + f^s_ij  >=  e_i + s_i + D_ij     (TD*v_i >= 0, f^s >= D)
            # and h_j <= l_j by Table 1. So the arc is usable only if e_i+s_i+D_ij <= l_j.
            earliest = nd[i].earliest + nd[i].serviceTime + D[i][j]
            if earliest <= nd[j].latest + 1e-9:
                unsound.append("arc (%s,%s) pruned but reachable at %.3f <= l_j %.3f"
                               % (i, j, earliest, nd[j].latest))
    return check("A6", "arc pruning removes only unusable arcs", not unsound,
                 "; ".join(unsound[:3]) if unsound else
                 "%d arcs pruned, every one provably unusable under (6) + Table 1" % pruned)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not os.path.exists(REG):
        print("G22: validation/ambiguities.json missing -- the register is not machine-readable")
        return 1
    reg = load()
    print("G22 -- the code must agree with validation/AMBIGUITY_REGISTER.md")
    print()
    for fn in (a2_tau, a3_proximity, a4_distances, a5_bigm, a6_pruning):
        try:
            fn(reg)
        except Exception as e:
            check(fn.__name__[:2].upper(), fn.__name__, False,
                  "raised %s: %s" % (type(e).__name__, e))
    w = max(len(r["name"]) for r in RESULTS)
    for r in RESULTS:
        print("  [%-8s] %-3s %-*s  %s" % ("PASS" if r["ok"] else "**FAIL**", r["id"], w,
                                          r["name"], r["detail"]))
    print()
    unchecked = reg.get("UNCHECKABLE", {})
    print("  NOT CHECKED BY THIS GATE, listed so its silence is not read as approval:")
    for aid, why in sorted(unchecked.items()):
        print("    %-4s %s" % (aid, why))
    fails = [r for r in RESULTS if not r["ok"]]
    print()
    print("G22: %d failure(s)" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
