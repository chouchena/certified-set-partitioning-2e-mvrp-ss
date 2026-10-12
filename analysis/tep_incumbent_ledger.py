"""Audited incumbent ledger, runtime event log, and the banking of every final incumbent in the repo. (d533, author 01:28)

For every cell of every size this reads EVERY banked primal artifact in the production dirs and writes, under results/
(tracked in git, unlike runs/):

  results/ledger/tep_incumbent_ledger_n<size>.json   per cell: every banked solution with its stage/operator, objective,
                                                      cars, vessels, runtime seconds, timestamp, code hash, path, and the
                                                      inner-operator trail where the stage recorded one (refine by_type,
                                                      ALNS best_ops); the improvement chain in pipeline order (which
                                                      operator beat the previous best, from what, to what, by how much);
                                                      and the chronological order of banking.
  results/ledger/tep_incumbent_ledger_n<size>.md     the same as a readable table.
  results/ledger/rt_event_log_n<size>.json           per cell: seconds charged per stage (primal stages from the artifacts,
                                                      bound legs from the bound artifacts), the envelope, total and share.
  results/incumbents/n<size>/<cell>.json             the final incumbent itself (full solution: xij, vi, hubs, yij, hi, ui,
                                                      nCars, nVessel, objVal, provenance), verifiable with
                                                      python analysis/verify_incumbent.py results/incumbents/n<size>/<cell>.json

Unstamped seconds (the earliest floor artifacts predate the stamp) are reported as null, never invented.

    python analysis/tep_incumbent_ledger.py [--sizes 10 20 30 50 100]
"""
import argparse
import glob
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "analysis"))
from stamp import stamped
import run_full_grid as G

STAGES = ("floor", "ceil", "refine", "alns", "selchain", "masterip", "forced")
CELLS = ["C%d" % i for i in range(201, 209)] + ["R%d" % i for i in range(201, 212)] + ["RC%d" % i for i in range(201, 209)]
KEEP = ("selection", "superseded_objVal", "superseded_from", "gurobi_status", "work_used", "rounding", "by_type", "best_ops", "stats", "secs", "chain_secs")


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else None


def bound_trajectory(cell, size):
    """LB improvement over runtime, from the per-iteration history every bound artifact stores: the
    converged LP, the seconds to reach 95 and 99 percent of it, and the total. (d552: the ledger
    recorded the primal improvement chain and nothing about how the bound got where it got.)"""
    base = ("runs/oracle/tep_cg_bound_%s.json" % cell) if size == 100 else ("runs/oracle/tep_cg_bound_%s_n%d.json" % (cell, size))
    d = load(os.path.join(ROOT, base)) or load(os.path.join(ROOT, base.replace(".json", "_ip.json")))
    if not d or not d.get("hist"):
        return None
    h = [(x.get("secs"), x.get("lp")) for x in d["hist"] if x.get("lp") is not None and x.get("secs") is not None]
    if not h:
        return None
    final = h[-1][1]
    def first_at(frac):
        for sec, lp in h:
            if lp >= frac * final - 1e-9:
                return sec
        return None
    return dict(converged_lp=final, secs_total=h[-1][0], secs_to_95pct=first_at(0.95),
                secs_to_99pct=first_at(0.99), iterations=len(h), status=d.get("status"), delta=d.get("delta"))


def bound_secs(cell, size):
    out = {}
    base = ("runs/oracle/tep_cg_bound_%s.json" % cell) if size == 100 else ("runs/oracle/tep_cg_bound_%s_n%d.json" % (cell, size))
    b = load(os.path.join(ROOT, base))
    if b: out["bound_d20"] = b.get("secs")
    for w in (10, 5):
        for suf in ("_ip", ""):
            f = load(os.path.join(ROOT, ("runs/oracle/tep_cg_bound_%s_d%d%s.json" % (cell, w, suf)) if size == 100 else ("runs/oracle/tep_cg_bound_%s_n%d_d%d%s.json" % (cell, size, w, suf))))
            if f: out["bound_d%d" % w] = f.get("secs"); break
    if size == 100:
        s = [load(f).get("secs") for f in glob.glob(os.path.join(ROOT, "runs/oracle/tep_easy_reduction_%s_n100_k*.json" % cell))]
        if s: out["bound_subset_total"] = sum(x for x in s if x is not None)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sizes", nargs="*", type=int, default=[10, 20, 30, 50, 100]); a = ap.parse_args()
    os.makedirs(os.path.join(ROOT, "results", "ledger"), exist_ok=True)
    for n in a.sizes:
        ledger, rt, md = {}, {}, []
        os.makedirs(os.path.join(ROOT, "results", "incumbents", "n%d" % n), exist_ok=True)
        for c in CELLS:
            events = []
            for st_ in STAGES:
                p = os.path.join(ROOT, "runs", "postpass", "" if st_ == "floor" else st_, "ownwater_%s_n%d.json" % (c, n))
                d = load(p)
                if not d: continue
                pv = d.get("_provenance") or {}
                ev = dict(stage=st_, objVal=float(d["objVal"]), nCars=int(d["nCars"]), nVessel=int(d.get("nVessel", 0)),
                          secs=d.get("secs"), when=pv.get("when") or d.get("_finished"), code_hash=pv.get("code_hash"),
                          verified=bool(d.get("_verified")), path=os.path.relpath(p, ROOT).replace("\\", "/"))
                for k in KEEP:
                    if k in d and k not in ev: ev[k] = d[k]
                if st_ == "alns" and isinstance(d.get("stats"), dict): ev["best_ops"] = d["stats"].get("best_ops")
                if d.get("best_ops") is not None: ev["best_ops"] = d["best_ops"]
                if d.get("stage_detail") is not None: ev["stage_detail"] = d["stage_detail"]
                events.append(ev)
            if not events: continue
            chain = []; run = None
            for ev in events:                      # pipeline order
                if run is None or ev["objVal"] < run - 1e-6:
                    chain.append(dict(stage=ev["stage"], from_val=run, to_val=ev["objVal"], delta_pct=(100.0 * (ev["objVal"] / run - 1)) if run else None, cars=ev["nCars"]))
                    run = ev["objVal"]
            best = min(events, key=lambda e: e["objVal"])
            ledger[c] = dict(final=dict(objVal=best["objVal"], nCars=best["nCars"], stage=best["stage"], path=best["path"], code_hash=best["code_hash"]),
                             improvement_chain=chain, events_pipeline_order=events,
                             events_chronological=sorted(events, key=lambda e: e["when"] or ""))
            env = G.envelope(n, 2.5, c); secs = {e["stage"]: e["secs"] for e in events}; secs.update(bound_secs(c, n))
            charged = sum(v for v in secs.values() if isinstance(v, (int, float)))
            rt[c] = dict(envelope_s=env, charged_s=charged, share=charged / env if env else None, per_stage_s=secs, unstamped=[k for k, v in secs.items() if v is None],
                         bound_trajectory=bound_trajectory(c, n))
            # bank the final incumbent, full solution, in the repo
            dst = os.path.join(ROOT, "results", "incumbents", "n%d" % n, "%s.json" % c)
            shutil.copy2(os.path.join(ROOT, best["path"]), dst)
            md.append("| %s | %.3f | %d | %s | %s | %s |" % (c, best["objVal"], best["nCars"], best["stage"], " -> ".join("%s %.1f" % (x["stage"], x["to_val"]) for x in chain), ("%.0f / %.0f" % (charged, env))))
        json.dump(stamped(dict(size=n, cells=ledger)), io.open(os.path.join(ROOT, "results", "ledger", "tep_incumbent_ledger_n%d.json" % n), "w", encoding="utf-8"), indent=1, default=str)
        json.dump(stamped(dict(size=n, cells=rt)), io.open(os.path.join(ROOT, "results", "ledger", "rt_event_log_n%d.json" % n), "w", encoding="utf-8"), indent=1, default=str)
        io.open(os.path.join(ROOT, "results", "ledger", "tep_incumbent_ledger_n%d.md" % n), "w", encoding="utf-8").write(
            "# Incumbent ledger, n%d -- generated by analysis/tep_incumbent_ledger.py, do not edit\n\n| cell | final objVal | cars | stage | improvement chain (pipeline order) | charged s / envelope s |\n|---|---|---|---|---|---|\n%s\n" % (n, "\n".join(md)))
        print("n%d: %d cells; final incumbents banked under results/incumbents/n%d/; ledger + RT log under results/ledger/" % (n, len(ledger), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
