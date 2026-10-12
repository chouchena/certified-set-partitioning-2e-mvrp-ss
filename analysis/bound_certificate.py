"""Certificate contract for TEP bound artifacts. (d519)

A bound may be cited only if the artifact itself shows how it was proven: the flag alone was not enough on
2026-09-25, when 89 n100 subset artifacts carried proven=true and no pricing history, and on 2026-09-23, when
24 n100 default-width artifacts were declared proven by the ng pass alone (d427 showed that pass is not a proof).

  certified(d) is True iff
    d["proven"] is true, AND
    d carries a boolean "certificate" (written by drivers since d519) that is true, OR
    d["hist"] holds an elementary pass (tag ELEM) that added 0 columns, was not exhausted and left zero covering slack.

Artifacts with neither field are NOT certified, whatever their flag says. Every reader of bound values imports this
function instead of testing the flag; the writer (tep_cg_bound.run) sets proven only after such a pass (d427), so
the two agree on every artifact written since then and disagree exactly on the ones that must not be cited.
"""


def elementary_pass(d):
    h = (d or {}).get("hist") or []
    elem = [x for x in h if str(x.get("tag", "")).strip().upper().startswith("ELEM")]
    return elem[-1] if elem else None


def withdrawn(d):
    """True when this artifact's VALUE was withdrawn by decision, whatever its certificate says.

    d442 (2026-09-25): THE INTEGER-CAR CUT IS INVALID AS A BOUND, refuted with a witness. On
    C204 at |C| = 20 the parent LP is 473.8646 at N = 1.015; the N >= 2 child costs 601.5139 but
    the N <= 1 child is FEASIBLE at 474.1331, so a valid branch bound -- the minimum over two
    children that partition the feasible set -- is 474.1331 while the cut reports 601.5139.
    The cut OVERSTATES by 127.38, 26.87 per cent, in the unsafe direction for a lower bound.
    d442: "Every integer-car value is withdrawn as a bound."

    WHY THIS LIVES HERE AND NOT IN A READER. d442 added no code marker, reasoning that the
    values "were already inside the d427 suspension so nothing standing depends on them". That
    was true on the day. Two days later tep_n30_best_of was changed to glob the _ip_intcars
    artifacts deliberately, its comment calling them "a valid and much stronger bound on disk and
    unread"; two days after that the d427 suspension was lifted, removing the last accidental
    barrier. By 2026-10-01 these artifacts carried 25 of 131 reported cells -- n10 6, n20 4,
    n50 15 -- inflating them by 1,831 in total, up to 157.79 on one cell and 32 per cent on
    another, and they had reached the derived best_of artifacts the manuscript registry reads.
    Recording a defect is not enforcing against it; this is the enforcement.
    """
    return bool((d or {}).get("int_car_cuts"))


def certified(d):
    # A CEIL-ROUNDED ARTIFACT IS NEVER A CERTIFIED BOUND, whatever its pricing proved (2026-09-28).
    # TEM-ceil is a RESTRICTION: its LP value is not a lower bound and must never be cited as one
    # (d414). Until today `certified` only asked about the proof, so a proven `_ip_primal` artifact
    # came back True and `bound_class` labelled it "elementary" -- at |C| = 10, 20 and 30 those
    # artifacts ARE proven, and their LP sits ABOVE the relaxation's. Every current reader happened
    # to filter the file name as well (`tep_n30_best_of.offer`, `tep_final_campaign.lacking_bound`),
    # so no reported bound was affected -- checked on all five sizes, 0 of 135. But the hole was one
    # glob away from publishing a restriction as a lower bound, which is the worst error this project
    # can make, and it was found by the new G24 rather than by a reader.
    if not d or d.get("primal_rounding") or not d.get("proven") or withdrawn(d):
        return False
    if d.get("certificate") is not None:
        return bool(d["certificate"])
    last = elementary_pass(d)
    return bool(last) and last.get("added") == 0 and not last.get("exhausted") and float(last.get("slack", 1.0)) < 1e-6


def ng_pass(d):
    """The last pricing pass that was NOT the elementary one, i.e. the ng-route pass."""
    h = (d or {}).get("hist") or []
    ng = [x for x in h if not str(x.get("tag", "")).strip().upper().startswith("ELEM")]
    return ng[-1] if ng else None


def ng_certified(d):
    """A WEAKER BUT VALID CERTIFICATE: the ng-route class converged, so the LP is the optimum over
    that class and is a lower bound on the elementary LP, hence on the optimum. (2026-09-27)

    Why this is a bound at all. The master's covering rows count VISITS, not distinct customers
    (`tep_cg_bound.py:178`, `coef[cov[c]] += 1` per occurrence), and the rows are >= 1. The ng-route
    class contains every elementary route plus routes that revisit a customer outside the ng memory,
    so its LP is a relaxation of the elementary LP:  LP(ng) <= LP(elementary) <= OPT. Converging the
    ng pricer therefore certifies a valid, weaker bound. It does NOT certify the elementary LP, which
    is what d519 refused and still refuses: `certified()` is untouched and this function is separate.

    FOUR CONDITIONS, and the third is the one that is easy to get wrong:

      1. the pass ran at FULL route length (stage is None) -- a length-limited pass says nothing
         about longer routes;
      2. it did not exhaust its label cap;
      3. it found NO candidate below the reduced-cost cut: `cand == 0`, not `added == 0`. Those are
         different. R211 at |C|=100 recorded added 0 with cand 114207 -- every column it found was
         already in the master -- and the elementary pass then found five columns at rc -4.46. Read
         through `added` alone, that artifact would have been certified and its bound would have been
         wrong;
      4. the master carries no covering slack, so the LP value is a real objective and not a
         penalty-propped one;

    and one more that is a property of the driver rather than the row: the pass must have priced on
    the TRUE duals. `tep_cg_bound` smooths duals (Wentges) and re-prices with the true ones whenever a
    smoothed pass adds nothing, recording `mispriced=True`; that flag is therefore required unless
    smoothing was off.
    """
    r = ng_pass(d)
    if not r or (d or {}).get("primal_rounding") or withdrawn(d):
        return False
    if r.get("stage") is not None or r.get("exhausted"):
        return False
    if (r.get("cand") or 0) != 0:
        return False
    if not r.get("mispriced") and (d or {}).get("smooth", 0.5):
        return False
    return float(r.get("slack", 1.0)) < 1e-6


def bound_class(d):
    """Which certificate an artifact carries, strongest first: 'elementary', 'ng', or None."""
    if certified(d):
        return "elementary"
    if ng_certified(d):
        return "ng"
    return None


def why_not(d):
    """One line saying why an artifact is not certified, for logs and the preflight."""
    if not d:
        return "no artifact"
    if not d.get("proven"):
        return "not proven (status %s)" % d.get("status")
    if d.get("certificate") is not None and not d["certificate"]:
        return "certificate false"
    last = elementary_pass(d)
    if last is None:
        return "proven flag without any stored elementary pass (pre-d519 artifact)"
    return "elementary pass added %s exhausted %s slack %s" % (last.get("added"), last.get("exhausted"), last.get("slack"))


def best_valid(items, value, klass, tol=1e-6):
    """The winner among valid bounds: the largest value, and AT EQUAL VALUE the stronger class.

    `items` is any sequence; `value(item)` is the bound and `klass(item)` its certificate class,
    "elementary" or "ng". Two values within `tol` are the same bound -- 1e-6 is the tolerance
    the certificate itself is stated at -- and among them an elementary artifact wins. The
    winner's OWN value is returned with it, never the tied ng value, so a bound is never
    reported 1e-7 above what its certificate covers.

    WHY (2026-09-30). Every reader took the max over both classes and read the class off the
    winner, and none said what happens at a tie. tep_n30_best_of ranked (lp, width, class)
    tuples, so at equal lp and width the string comparison "ng" > "elementary" made the ng
    artifact win; bound_source took the first maximum in glob order, which put the canonical
    file ahead of `_ip` by the accident that "." sorts before "_". Measured over all 135 cells
    before the fix: 0 tie cells on disk -- the defect had no blast. It becomes live with the
    DSSR certificates for R204, R207 and R211 at |C| = 50, whose elementary value is BIT-IDENTICAL
    to the ng value already on disk (delta 0.0, and +4.55e-13 on R211): three cells that would
    hold an elementary certificate and be reported as ng-class. One rule, here, for every reader.
    Returns None when `items` is empty.
    """
    items = list(items)
    if not items:
        return None
    top = max(float(value(x)) for x in items)
    tied = [x for x in items if float(value(x)) >= top - tol]
    elem = [x for x in tied if klass(x) == "elementary"]
    return max(elem or tied, key=lambda x: float(value(x)))
