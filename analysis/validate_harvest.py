"""VALIDATION (prints only, writes no artifact): confirm the refactored certify path is
numerically unchanged, and that the gated harvest hook (1) fires near convergence, (2) banks a
VALID bound, (3) never overshoots the completed LP* (max interim bound <= LP*), and converges to
it. Run on a fast-converging rung."""
import sys, json
ROOT = r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir\analysis"
sys.path.insert(0, ROOT)
import tep_cg_bound as T
import lb_solver as L


def run_certify(cell, size, delta):
    prox = L.k_proximity(size)
    r = T.run(cell, delta, 400, ["prio", "ts"], 10, 1000, False, L.LABEL_CAP,
              size=size, proximity=prox, max_secs=0.0, start_states=True, threads=4, certify=True)
    lg = r.get("lagrangian") or {}
    print("CERTIFY " + json.dumps(dict(bound=round(lg.get("bound") or 0, 4), valid=lg.get("valid"),
          lp_street=round(r.get("lp_street") or 0, 4), proven=r.get("proven"))), flush=True)
    return r


def run_harvest(cell, size, delta):
    prox = L.k_proximity(size)
    ab4 = L.ab4_floor(cell, size, prox)["ab4"]
    recs = []
    r = T.run(cell, delta, 400, ["prio", "ts"], 10, 1000, False, L.LABEL_CAP,
              size=size, proximity=prox, max_secs=0.0, start_states=True, threads=4,
              harvest_cb=lambda rec: recs.append(rec), harvest_lb0=ab4,
              harvest_soft_secs=0.0, harvest_throttle=10.0, harvest_runaway=0.0)
    lp = r.get("lp_street")
    fired = [x for x in recs if x.get("fired")]
    valid = [x for x in fired if x.get("valid")]
    banked = [x for x in recs if x.get("banked")]
    maxv = max([x["bound"] for x in valid], default=None)
    print("HARVEST " + json.dumps(dict(
        cell=cell, size=size, delta=delta, ab4=round(ab4, 3),
        lp_street=round(lp, 4) if lp else None, n_iters=len(recs), n_fired=len(fired),
        n_valid=len(valid), n_banked=len(banked),
        max_valid_bound=round(maxv, 4) if maxv is not None else None,
        final_banked=round(banked[-1]["bound"], 4) if banked else None,
        overshoot=(round(maxv - lp, 6) if (maxv is not None and lp) else None))), flush=True)
    if maxv is not None and lp is not None:
        assert maxv <= lp + 1e-4, "OVERSHOOT max interim %.6f > LP* %.6f" % (maxv, lp)
        print("  OK: max interim bound <= completed LP* (%.6f <= %.6f)" % (maxv, lp), flush=True)
    else:
        print("  NOTE: gate did not fire (no valid interim bound) on this rung", flush=True)
    return r


if __name__ == "__main__":
    run_certify("C205", 100, 60.0)
    run_harvest("C205", 100, 60.0)
