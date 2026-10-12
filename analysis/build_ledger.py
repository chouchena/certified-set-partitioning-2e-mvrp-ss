"""Build the capture-everything run ledger from fixopt traces (task #23; ablation-aware-harness).
Post-hoc: the runner just writes a rich trajectory jsonl; THIS computes the full metric set per run
and joins the K denominators (validation/nonobvious_set.csv) -> runs/ledger.csv. Works on every past
and future trace, so narrative framing (single vs portfolio, which RT ref) is a pivot, not a re-run.

Per run: provenance (git_sha/dirty, code_hash, host, cores, solver, budget, threads), OV, RT-total,
RT-to-best, n_incumbents, close status/verified, and vs-K: k_min + both RT refs (winning-method IncT,
combined Joint+LBBD IncT), beats_K, RT-to-beat-K + ratios. LB left blank (external block-A join, separate)."""
import csv, glob, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "validation", "nonobvious_set.csv")
OUT = os.path.join(ROOT, "runs", "ledger.csv")


def load_frame():
    K = {}
    if not os.path.exists(FRAME):
        return K
    for r in csv.DictReader(open(FRAME, encoding="utf-8")):
        K[(r["cell"], int(r["size"]))] = r
    return K


def parse_trace(f):
    recs = []
    for l in open(f, encoding="utf-8"):
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(r, dict):
            recs.append(r)
    if not recs:
        return None
    start = next((r for r in recs if r.get("phase") == "run_start"), recs[0])
    ex = start.get("extra") or {}
    cfg = ex.get("config") or {}
    prov = ex.get("provenance") or {}
    close = next((r for r in reversed(recs) if r.get("phase") == "closed"), None)
    cex = (close or {}).get("extra") or {}
    # incumbent trajectory (running min)
    traj, bs = [], None
    for r in recs:
        w = r.get("wall_s")
        v = r.get("best_incumbent") if r.get("best_incumbent") is not None else r.get("incumbent")
        if isinstance(w, (int, float)) and isinstance(v, (int, float)):
            bs = v if bs is None else min(bs, v)
            traj.append((w, bs))
    if not traj:
        return None
    ov = traj[-1][1]
    rt_total = traj[-1][0]
    rt_to_best = next(w for w, v in traj if v <= ov + 1e-9)
    n_inc = len({round(v, 6) for _, v in traj})
    return dict(
        run_id=os.path.basename(f)[:-6], cell=start.get("instance"), size=start.get("size"),
        variant=cfg.get("variant"), seed=start.get("seed"), budget=cfg.get("budget"),
        threads=cfg.get("threads"), cores=ex.get("cores"), solver=ex.get("solver") or "cplex",
        git_sha=prov.get("git_sha"), git_dirty=prov.get("git_dirty"), code_hash=prov.get("code_hash"),
        host=prov.get("host"), ov=round(ov, 4), rt_total=round(rt_total, 1),
        rt_to_best=round(rt_to_best, 1), n_incumbents=n_inc,
        status=cex.get("status"), verified=cex.get("verified"), run_valid=cex.get("run_valid"),
        _traj=traj)


def main():
    K = load_frame()
    fs = sorted(glob.glob(os.path.join(ROOT, "runs", "fixopt_*.jsonl")))
    rows = []
    for f in fs:
        d = parse_trace(f)
        if not d:
            continue
        key = (d["cell"], d["size"])
        kr = K.get(key)
        traj = d.pop("_traj")
        if kr:
            kmin = float(kr["k_min"]); d["obvious"] = kr["obvious"]
            d["k_min"] = kmin
            d["k_min_inct"] = float(kr["k_min_inct"]) if kr["k_min_inct"] else ""
            d["k_combined_inct"] = float(kr["k_combined_inct"]) if kr["k_combined_inct"] else ""
            d["beats_k"] = d["ov"] < kmin
            tb = next((w for w, v in traj if v <= kmin), None)
            d["rt_to_beat_k"] = round(tb, 1) if tb is not None else ""
            d["rt_ratio_vs_kmin_inct"] = (round(tb / float(kr["k_min_inct"]), 3)
                                          if tb is not None and kr["k_min_inct"] else "")
            d["rt_ratio_vs_combined"] = (round(tb / float(kr["k_combined_inct"]), 3)
                                         if tb is not None and kr["k_combined_inct"] else "")
        else:
            for k in ("obvious", "k_min", "k_min_inct", "k_combined_inct", "beats_k",
                      "rt_to_beat_k", "rt_ratio_vs_kmin_inct", "rt_ratio_vs_combined"):
                d[k] = ""
        rows.append(d)
    flds = ["run_id", "cell", "size", "variant", "seed", "budget", "threads", "cores", "solver",
            "git_sha", "git_dirty", "code_hash", "host", "ov", "rt_total", "rt_to_best",
            "n_incumbents", "status", "verified", "run_valid", "obvious", "k_min", "k_min_inct",
            "k_combined_inct", "beats_k", "rt_to_beat_k", "rt_ratio_vs_kmin_inct", "rt_ratio_vs_combined"]
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=flds); w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {len(rows)} run-rows -> {os.path.relpath(OUT, ROOT)}")
    beats = [r for r in rows if r.get("beats_k") is True and r.get("obvious") == "False"]
    print(f"non-obvious beats-K rows: {len(beats)} "
          f"(unique cells: {sorted(set(r['cell'] for r in beats))})")


if __name__ == "__main__":
    main()
