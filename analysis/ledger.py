"""
ledger.py -- one append-only JSONL record per (experiment, cell, config) run.

Every harness that produces a number the paper might cite MUST call `emit(...)`
for EACH configuration it evaluates -- not just the winner. Ablation and
sensitivity tables are then a pivot over `config`, never a re-run.

Record schema (one JSON object per line in results/ledger.jsonl):
  ts          ISO-8601 UTC
  experiment  short slug, e.g. "mfree_cuts", "fixopt_portfolio", "easy_reduction"
  cell        instance family+setting, e.g. "C204"
  size        |C|
  config      dict -- every knob that was varied to produce this row
              (timing_mode, cuts, k, operator set, kick policy, TL, seed, ...)
  metrics     dict -- every number produced (bound, obj, proven, gap, n_cuts, ...)
  wall_s      float
  verified    bool | None  (None = not applicable, e.g. pure model solve)
  run_id      groups rows from one process invocation
  notes       optional free text

Read back with `load()` -> list[dict]; `frame()` -> pandas.DataFrame.
"""
from __future__ import annotations
import json, os, time, uuid, datetime as _dt
from typing import Any

try:                                    # fail-open: provenance must never break logging
    from analysis.provenance import stamp as _prov_stamp
except Exception:                       # pragma: no cover
    _prov_stamp = None

_LEDGER = os.path.join(os.path.dirname(__file__), os.pardir, "results", "ledger.jsonl")
RUN_ID = f"{_dt.datetime.utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def emit(experiment: str, cell: str, size: int, config: dict[str, Any],
         metrics: dict[str, Any], wall_s: float, verified: bool | None = None,
         notes: str = "", ledger_path: str | None = None, run_id: str | None = None) -> None:
    prov = None
    if _prov_stamp is not None:
        try:
            cfg = config or {}
            prov = _prov_stamp(seed=cfg.get("seed"),
                               cores=cfg.get("cores") or cfg.get("threads") or cfg.get("workers"),
                               solver=cfg.get("solver"))
        except Exception:
            prov = None
    rec = dict(
        ts=_dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        experiment=experiment, cell=cell, size=int(size),
        config=_jsonable(config), metrics=_jsonable(metrics),
        norm=_norm_facts(metrics),          # canonical (lb,ub,proven) so disk-check is decidable
        provenance=prov,                    # code_hash+git+seed+cores+solver (reproducibility)
        wall_s=round(float(wall_s), 1), verified=verified,
        run_id=run_id or RUN_ID, notes=notes,
    )
    path = ledger_path or _LEDGER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def _jsonable(d):
    out = {}
    for k, v in dict(d).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [x if isinstance(x, (str, int, float, bool)) or x is None else str(x) for x in v]
        else:
            out[k] = str(v)
    return out


# ---- canonical value extraction (a "result already on disk?" gate must be a
# DETERMINISTIC query; harnesses store "the number" under >=5 different keys) ----
_LB_KEYS = ("block_relax", "bound", "best_bound", "zA", "lb", "trips_lb")
_UB_KEYS = ("final_obj", "objVal", "obj", "incumbent", "best", "best_obj")


def _first(metrics: dict, keys) -> tuple:
    for k in keys:
        v = (metrics or {}).get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v), k
    return None, None


def _norm_facts(metrics: dict) -> dict:
    """Canonical (lb, ub, proven) view of a heterogeneous metrics dict."""
    metrics = metrics or {}
    lb, lbk = _first(metrics, _LB_KEYS)
    ub, ubk = _first(metrics, _UB_KEYS)
    proven = bool(metrics.get("proven", False))
    gap = metrics.get("gap")
    ub_proven = proven or (isinstance(gap, (int, float)) and not isinstance(gap, bool) and gap <= 1e-9)
    return {"lb": lb, "lb_key": lbk, "lb_proven": proven,
            "ub": ub, "ub_key": ubk, "ub_proven": bool(ub_proven)}


def best_proven(cell: str, size: int, kind: str = "lb",
                ledger_path: str | None = None) -> dict | None:
    """Deterministic 'is there already a PROVEN <kind> for (cell,size)?'
    kind='lb' -> max proven lower bound; 'ub' -> min proven upper bound. Applies the
    alias map at query time so it works on legacy rows too. Returns
    {value, run_id, experiment, kind} or None. This is the query the launch
    result-already-on-disk gate calls; before it, the ledger was undecidable
    (the proven R207 LB 493.36 lived under `block_relax` with verified=None)."""
    best = None
    for r in load(ledger_path):
        if r.get("cell") != cell or int(r.get("size", -1)) != int(size):
            continue
        nf = r.get("norm") or _norm_facts(r.get("metrics", {}))
        if kind == "lb" and nf.get("lb") is not None and nf.get("lb_proven"):
            if best is None or nf["lb"] > best["value"]:
                best = {"value": nf["lb"], "run_id": r.get("run_id"),
                        "experiment": r.get("experiment"), "kind": "lb"}
        elif kind == "ub" and nf.get("ub") is not None and nf.get("ub_proven"):
            if best is None or nf["ub"] < best["value"]:
                best = {"value": nf["ub"], "run_id": r.get("run_id"),
                        "experiment": r.get("experiment"), "kind": "ub"}
    return best


def best_proven_on_disk(cell: str, size: int, kind: str = "lb",
                        root: str | None = None) -> dict | None:
    """UNION disk-check: the ledger (best_proven) PLUS ad-hoc result JSONs
    (crossfeed/easy_reduction_*, results/lb_portfolio/*). The ledger alone MISSES
    results written only to per-cell files (e.g. R203 566.79 / RC202 829.42 live in
    crossfeed/easy_reduction_*_n<size>.json and were never emitted). This is the
    query the launch 'result-already-on-disk?' gate must use — ledger-only is a
    false-negative machine (exactly the flaw that re-ran the overnight LB)."""
    import glob
    root = root or os.path.join(os.path.dirname(__file__), os.pardir)
    led = best_proven(cell, size, kind, os.path.join(root, "results", "ledger.jsonl"))
    best_val = led["value"] if led else None
    src = f"ledger:{led['experiment']}" if led else None
    if kind == "lb":
        for pat in (os.path.join(root, "crossfeed", f"easy_reduction*_{cell}_n{size}.json"),
                    os.path.join(root, "results", "lb_portfolio", f"{cell}_n{size}*.json")):
            for fp in glob.glob(pat):
                try:
                    d = json.load(open(fp, encoding="utf-8"))
                except Exception:
                    continue
                for rr in (d if isinstance(d, list) else [d]):
                    if not isinstance(rr, dict):
                        continue
                    val = rr.get("block_relax")
                    val = val if val is not None else rr.get("LB")
                    if isinstance(val, (int, float)) and not isinstance(val, bool) and rr.get("proven"):
                        if best_val is None or val > best_val:
                            best_val, src = float(val), os.path.basename(fp)
    return None if best_val is None else {"value": best_val, "source": src, "kind": kind}


def reproduced_baseline_on_disk(cell: str, size: int, root: str | None = None) -> dict | None:
    """Is a reproduced Karademir baseline (LBBD) already on disk for (cell,size)?
    Closes the blind spot in best_proven_on_disk, which scans crossfeed/ + results/lb_portfolio/
    for OUR bounds but NOT runs/lbbd_*.jsonl (K's reproduced LBBD curves). A preflight for a
    'reproduce K's LBBD' run must see these to refuse recompute -- this is exactly the artifact a
    stale-memory claim ('no reproduced curve exists') missed on 2026-09-06. Returns
    {final_bound, final_incumbent, wall_s, source} for the best (max-bound) run, or None."""
    import glob
    root = root or os.path.join(os.path.dirname(__file__), os.pardir)
    best = None
    for fp in glob.glob(os.path.join(root, "runs", f"lbbd_{cell}_n{size}*.jsonl")):
        try:
            recs = [json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
        except Exception:
            continue
        bnds = [r.get("best_bound") for r in recs
                if isinstance(r.get("best_bound"), (int, float)) and not isinstance(r.get("best_bound"), bool)]
        incs = [r.get("best_incumbent") if r.get("best_incumbent") is not None else r.get("incumbent")
                for r in recs]
        incs = [i for i in incs if isinstance(i, (int, float)) and not isinstance(i, bool)]
        walls = [r.get("wall_s") for r in recs if isinstance(r.get("wall_s"), (int, float))]
        if not bnds:
            continue
        cand = {"final_bound": max(bnds), "final_incumbent": (min(incs) if incs else None),
                "wall_s": (max(walls) if walls else None), "source": os.path.basename(fp)}
        if best is None or cand["final_bound"] > best["final_bound"]:
            best = cand
    return best


def load(ledger_path: str | None = None) -> list[dict]:
    path = ledger_path or _LEDGER
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def frame(ledger_path: str | None = None):
    import pandas as pd
    rows = load(ledger_path)
    flat = []
    for r in rows:
        d = {k: r[k] for k in ("ts", "experiment", "cell", "size", "wall_s", "verified", "run_id", "notes")}
        for k, v in r.get("config", {}).items():
            d[f"cfg.{k}"] = v
        for k, v in r.get("metrics", {}).items():
            d[f"m.{k}"] = v
        flat.append(d)
    return pd.DataFrame(flat)


if __name__ == "__main__":
    import sys
    f = frame()
    if f.empty:
        print("ledger empty:", _LEDGER)
    else:
        with __import__("pandas").option_context("display.max_columns", None, "display.width", 200):
            print(f.to_string(index=False))
