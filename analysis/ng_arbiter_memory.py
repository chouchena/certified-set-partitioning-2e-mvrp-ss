"""EXTERNAL VALIDATOR: ng-memory monotonicity. Refutes an ng certificate; never produces one.

WHY. Since the in-run elementary pass was dropped (2026-09-29), nothing inside a run checks that
the ng pricer's "no column prices out" is true. `L-TEP-cert-ng` is mathematics; what is unchecked
is our **transcription** of Baldacci's construction. The elementary class has an independent
arbiter (`tep_exact_small`, no pricer, exact enumeration) and the ng class has none.

THE TEST. A larger ng memory is a tighter relaxation, so

    LP(ng = k)  <=  LP(ng = k')      for k < k'

Re-pricing a cell at a smaller memory and finding a HIGHER LP refutes the implementation. This is
the only validator in the set that reaches |C| = 100, where every ng-certified cell lives and
where exact enumeration never will.

IT IS A REFUTER, NOT A PROVER. Agreement corroborates; it proves nothing. Stated because this
project does not let a falsification test masquerade as a validation.

OUTSIDE THE RT ENVELOPE. Its value is never reported as a bound, so its seconds are not charged
(d of 2026-09-29) — the same treatment verifier3 already gets on the primal. Enforced by
construction: it writes its own artifact and `bound_source` never reads it.

IT MUST NOT TOUCH THE CORPUS. `tep_cg_bound.main()` names its output from cell/size/delta only,
so a CLI run at `--ng 5` would OVERWRITE the banked `--ng 10` artifact. This calls `run()`
in-process instead, which returns the result and writes nothing.

    python analysis/ng_arbiter_memory.py --cells R202 R203 --size 50
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "solver"))
import verifier3 as V
import tep_cg_bound as T
from k_comparison import k_proximity
from best_known import bound_artifacts
from bound_certificate import ng_certified, certified
from stamp import stamped


def ng_convergence_lp(d):
    """The LP at the moment the ng loop converged: the last non-ELEM history row."""
    cg = [x for x in (d.get("hist") or [])
          if isinstance(x.get("lp"), (int, float))
          and not str(x.get("tag", "")).strip().upper().startswith("ELEM")]
    return float(cg[-1]["lp"]) if cg else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--small-ng", type=int, default=5)
    ap.add_argument("--max-secs", type=float, default=600.0)
    ap.add_argument("--since", default="2026-09-29",
                    help="only validate artifacts finished on or after this date")
    ap.add_argument("--tag", default="ng5")
    a = ap.parse_args()

    print("ng-MEMORY MONOTONICITY ARBITER -- outside the RT envelope, refuter only")
    print("test: LP(ng=%d) <= LP(ng=%d). A HIGHER value at the smaller memory REFUTES.\n"
          % (a.small_ng, 10))
    prox = k_proximity(a.size)
    rows = []
    for cell in a.cells:
        ref = None
        for q, d in bound_artifacts(cell, a.size):
            if (d.get("_finished") or "")[:10] < a.since:
                continue
            if d.get("primal_rounding") or d.get("drop") or d.get("lp_street") is None:
                continue
            if not (certified(d) or ng_certified(d)):
                continue
            if ref is None or d["lp_street"] > ref[1]["lp_street"]:
                ref = (q, d)
        if ref is None:
            print("  %-7s no artifact on or after %s -- skipped" % (cell, a.since))
            continue
        q, d = ref
        big_ng = d.get("ng")
        base = ng_convergence_lp(d)
        delta = float(d.get("delta")) if d.get("delta") else None
        inst = V.load_instance(cell, a.size, prox)
        if delta is None:
            delta = T.default_delta(inst)

        t0 = time.time()
        err = None
        try:
            # run() RETURNS the result and writes nothing; main() is what writes an artifact.
            r = T.run(cell, delta, 400, ["prio", "ts"], a.small_ng, 1000, False, 3_000_000,
                      size=a.size, proximity=prox, max_secs=a.max_secs,
                      start_states=bool(d.get("start_states")), return_master=False)
            small = ng_convergence_lp(r)
            if small is None:
                small = r.get("lp_street")
        except Exception as e:
            small, err = None, "%s: %s" % (type(e).__name__, str(e)[:90])
        secs = round(time.time() - t0, 1)

        ok = (small is not None and base is not None and small <= base + 1e-6)
        rows.append(dict(cell=cell, size=a.size, delta=delta,
                         ng_big=big_ng, ng_small=a.small_ng,
                         lp_big=base, lp_small=small, secs=secs, error=err,
                         monotone=ok if small is not None else None,
                         artifact=os.path.relpath(q, ROOT)))
        print("  %-7s ng=%-3s LP %10.2f  |  ng=%-2d LP %10s  %7.0fs  %s"
              % (cell, big_ng, base if base is not None else -1, a.small_ng,
                 ("%.2f" % small) if small is not None else "ERR", secs,
                 "ok" if ok else ("*** REFUTED" if small is not None else err)), flush=True)

        p = os.path.join(ROOT, "runs", "oracle", "ng_arbiter_%s_n%d.json" % (a.tag, a.size))
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(stamped(dict(rows=rows, small_ng=a.small_ng, size=a.size,
                                   since=a.since, outside_rt=True,
                                   note="refuter only; never produces a bound"),
                              "analysis/ng_arbiter_memory.py", "analysis/tep_cg_bound.py",
                              "analysis/tep_pricer.py"), f, indent=1, default=str)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)

    done = [r for r in rows if r["monotone"] is not None]
    bad = [r for r in done if not r["monotone"]]
    print("\n  validated %d | REFUTATIONS %d | errors %d"
          % (len(done), len(bad), len(rows) - len(done)))
    for r in bad:
        print("    *** %-7s n%-4d LP(ng=%d) %.2f > LP(ng=%s) %.2f"
              % (r["cell"], r["size"], r["ng_small"], r["lp_small"], r["ng_big"], r["lp_big"]))
    print("  wrote runs/oracle/ng_arbiter_%s_n%d.json" % (a.tag, a.size))
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
