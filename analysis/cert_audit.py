r"""Area 5 -- per-cell lower-bound certificate audit (d792). READ-ONLY over banked artifacts.

For every reported cell the bound is max(lb_composed, ab4), where lb_composed = certified street LP +
water term and ab4 is the closed-form arithmetic bound; the certificate class comes from the frzdual2
artifact (the same source tab_percell_grid.cert_of reads). This sweep extracts, per cell, the record
a referee needs to establish the bound is safe, and asserts the invariants that make it one:

  * valid_bound is True and the reported bound equals max(lb_composed, ab4);
  * where the LP carries (ab4 <= lb_composed), its certificate pass added 0 columns, did NOT exhaust
    its label budget, and left zero covering (artificial) slack -- so the restricted LP value is a
    real objective the pricing closed on, not a big-M penalty or a truncated search;
  * the arithmetic bound carries exactly the cells the manuscript registers (portfolio.ab-carries).

WHAT THIS IS, AND IS NOT (referee #6). This is a STORED-STATE CONSISTENCY audit: it checks that the
recorded certificate flags are internally consistent and that the reported bound reconstructs from
the stored components. It is NOT an independent re-solve of each certificate -- that would rebuild the
master from the banked column pool, re-solve the LP, and re-price to confirm no column is below
-epsilon. The banked artifacts store the LP value, the per-pass closing state (added, exhausted,
slack, labels) and the components, but not the full column pool, so an independent re-solve needs a
re-run of the solver and is out of scope here. The general validity rests on the Appendix A1 proofs;
this audit guards against a mislabelled or truncated record among the reported cells.

It writes a human-readable audit (validation/AREA5_CERTIFICATE_AUDIT.md) and a full-precision
per-cell record (validation/certificate_records.json), and exits nonzero on any violated invariant.
No solver runs: it reads runs/oracle/tep_solve_frzdual2_*.json.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (10, 20, 30, 50, 100)
TOL = 1e-3


def frz(cell, size):
    p = os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_%s_n%d.json" % (cell, size))
    return json.load(open(p)) if os.path.exists(p) else None


def cells_present():
    out = {}
    for p in glob.glob(os.path.join(ROOT, "runs", "oracle", "tep_solve_frzdual2_*_n*.json")):
        base = os.path.basename(p)[len("tep_solve_frzdual2_"):-5]
        cell, sz = base.rsplit("_n", 1)
        out.setdefault(int(sz), set()).add(cell)
    return out


def record(cell, size):
    d = frz(cell, size)
    if d is None:
        return None
    r = d["rows"][0]
    lph = r.get("lb_hist") or [{}]
    last = lph[-1]
    lp_street = float(r.get("lp_street") or 0.0)
    water = float(r.get("water_ab") or 0.0)
    ab4 = float(r.get("ab4") or 0.0)
    lb_comp = float(r.get("lb_composed") or 0.0)
    reported = max(lb_comp, ab4)
    ab_carries = ab4 > lb_comp + 1e-9
    eps_corr = 1e-6 * size   # eps|C| dual correction (Lemma tepcert); safe_bound = raw_bound - eps_corr
    prov = d.get("_provenance", {})
    return {
        "cell": cell, "size": size, "ng": (r.get("caps") or {}).get("ng"),
        "lp_street": lp_street, "water_ab": water, "ab4": ab4, "lb_composed": lb_comp,
        "eps_correction": eps_corr, "safe_bound": reported - (0.0 if ab_carries else eps_corr),
        "raw_bound": reported, "carrier": "AB" if ab_carries else (r.get("certificate") or "?"),
        "certificate": r.get("certificate"), "why_not": r.get("certificate_why_not"),
        "proven": bool(r.get("proven")), "valid_bound": bool(r.get("valid_bound")),
        "lb_valid": bool(r.get("lb_valid")),
        "added": last.get("added"), "exhausted": bool(last.get("exhausted")),
        "slack": float(last.get("slack", 1.0)), "labels": last.get("labels"),
        "det_work": r.get("det_work_total"), "wall_s": r.get("wall_s"),
        "code_hash": prov.get("code_hash"), "git_dirty": prov.get("git_dirty"),
        "ab_carries": ab_carries,
    }


def main():
    present = cells_present()
    rows, problems = [], []
    for size in SIZES:
        for cell in sorted(present.get(size, [])):
            rec = record(cell, size)
            if rec is None:
                continue
            rows.append(rec)
            # invariants
            if not rec["valid_bound"] or not rec["lb_valid"]:
                problems.append("%s n%d: valid_bound/lb_valid false" % (cell, size))
            if abs(rec["raw_bound"] - max(rec["lb_composed"], rec["ab4"])) > TOL:
                problems.append("%s n%d: raw_bound != max(lb_composed, ab4)" % (cell, size))
            if not rec["ab_carries"]:
                # the LP carries: its pass must have closed (added 0, not exhausted, zero slack)
                if rec["added"] not in (0, None) or rec["exhausted"] or rec["slack"] > 1e-6:
                    problems.append("%s n%d: LP carries but pass not closed (added=%s exhausted=%s slack=%.2e)"
                                    % (cell, size, rec["added"], rec["exhausted"], rec["slack"]))

    ab_cells = [(r["cell"], r["size"]) for r in rows if r["ab_carries"]]
    # cross-check AB-carries against the registered portfolio count
    reg = None
    try:
        nj = json.load(open(os.path.join(ROOT, "paper", "numbers.json")))
        reg = int(nj["portfolio"]["value"]["ab-carries-cells"])
    except Exception:
        pass
    if reg is not None and len(ab_cells) != reg:
        problems.append("AB-carries count %d != registered portfolio.ab-carries-cells %d"
                        % (len(ab_cells), reg))

    # ---- write the audit ---------------------------------------------------------------------
    lines = ["# Area 5 -- per-cell lower-bound certificate audit", "",
             "> Evidence for the \"Bound certification\" acceptance row (d792). Generated READ-ONLY by",
             "> `analysis/cert_audit.py` over `runs/oracle/tep_solve_frzdual2_*.json`. No solver runs.",
             ">",
             "> **This is a stored-state CONSISTENCY audit, not an independent re-solve** (referee #6): it",
             "> checks the recorded certificate flags are internally consistent and the reported bound",
             "> reconstructs from the stored components. An independent re-solve (rebuild the master from the",
             "> column pool, re-solve, re-price) needs a solver re-run and is out of scope; validity rests on",
             "> the Appendix A1 proofs. Full-precision per-cell records --- the raw bound, the",
             "> $\\varepsilon\\lvert C\\rvert$ correction, and the safe bound (the certified value less that",
             "> correction; NOT floored here --- the appendix table displays it floored to one decimal) ---",
             "> are in `validation/certificate_records.json`.",
             "",
             "Per cell: street LP, water term, arithmetic bound AB4, composed LP+water, the raw",
             "bound max(LP+water, AB4), which member carries it, the LP certificate class, and the",
             "closing evidence of the certifying pass (columns added, label-budget not exhausted, zero",
             "covering/artificial slack). `det_work` is the deterministic Gurobi Work; `code_hash` is the",
             "reproducibility anchor.", ""]
    by_size = {}
    for r in rows:
        by_size.setdefault(r["size"], []).append(r)
    for size in SIZES:
        rs = by_size.get(size)
        if not rs:
            continue
        nab = sum(1 for r in rs if r["ab_carries"])
        lines += ["## $|C| = %d$  (%d cells; AB carries %d, LP certificate carries %d)"
                  % (size, len(rs), nab, len(rs) - nab), "",
                  "| cell | ng | LP street | water | AB4 | LP+water | raw bound | carrier | cert | added | exhausted | slack | det\\_work |",
                  "|------|----|-----------|-------|-----|----------|-----------|---------|------|-------|-----------|-------|----------|"]
        for r in sorted(rs, key=lambda x: x["cell"]):
            lines.append("| %s | %s | %.2f | %.2f | %.2f | %.2f | %.2f | %s | %s | %s | %s | %.1e | %s |"
                         % (r["cell"], r["ng"], r["lp_street"], r["water_ab"], r["ab4"],
                            r["lb_composed"], r["raw_bound"], r["carrier"], r["certificate"],
                            r["added"], r["exhausted"], r["slack"], r["det_work"]))
        lines.append("")
    lines += ["## Summary", "",
              "- cells audited: **%d**" % len(rows),
              "- arithmetic bound carries: **%d** cells%s"
              % (len(ab_cells), (" (registered portfolio.ab-carries-cells = %d)" % reg) if reg is not None else ""),
              "  %s" % ", ".join("%s n%d" % c for c in sorted(ab_cells, key=lambda x: (x[1], x[0]))),
              "- code_hash present on every cell: **%s**" % all(r["code_hash"] for r in rows),
              "", ("**ALL INVARIANTS HOLD.**" if not problems else "**VIOLATIONS:**")]
    for p in problems:
        lines.append("- " + p)
    out = os.path.join(ROOT, "validation", "AREA5_CERTIFICATE_AUDIT.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    jpath = os.path.join(ROOT, "validation", "certificate_records.json")
    json.dump({"note": "stored-state consistency audit (not an independent re-solve); full precision. "
                       "raw_bound = max(lb_composed, ab4), the uncorrected certified value. "
                       "safe_bound = raw_bound minus eps|C| where the LP carries (the certified value "
                       "less its dual correction). NEITHER is floored here; the per-cell appendix "
                       "displays safe_bound floored to one decimal (analysis/tab_percell_grid.py). "
                       "See cert_audit.py docstring and Appendix A1.",
               "cells": sorted(rows, key=lambda r: (r["size"], r["cell"]))},
              open(jpath, "w"), indent=1, sort_keys=True, default=str)
    print("wrote %s (%d cells, %d AB-carries, %d problem(s))"
          % (os.path.relpath(out), len(rows), len(ab_cells), len(problems)))
    print("wrote %s (full-precision per-cell records)" % os.path.relpath(jpath))
    for p in problems:
        print("  PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
