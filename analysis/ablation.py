"""
ablation.py -- pivot the results ledger into ablation / sensitivity tables.

  python -m analysis.ablation <experiment> --on <cfg-key> [--fix k=6 timing_mode=indicator] [--metric block_relax]

Examples:
  # LB: effect of turning cuts on/off, holding timing + k
  python -m analysis.ablation mfree_cuts --on cuts --metric block_relax
  # LB: bigM vs indicator, per k
  python -m analysis.ablation mfree_cuts --on timing_mode --group k --metric proven
"""
from __future__ import annotations
import argparse
from analysis.ledger import frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--on", required=True, help="config key whose values become the columns")
    ap.add_argument("--group", default="cell", help="config/cell key(s) to index rows, comma-sep")
    ap.add_argument("--metric", default="block_relax")
    ap.add_argument("--fix", nargs="*", default=[], help="key=value filters (cfg.* or m.*)")
    a = ap.parse_args()

    df = frame()
    if df.empty:
        print("ledger empty")
        return
    df = df[df.experiment == a.experiment].copy()
    for kv in a.fix:
        k, v = kv.split("=", 1)
        col = k if k in df.columns else (f"cfg.{k}" if f"cfg.{k}" in df.columns else f"m.{k}")
        df = df[df[col].astype(str) == v]

    oncol = f"cfg.{a.on}" if f"cfg.{a.on}" in df.columns else a.on
    mcol = f"m.{a.metric}" if f"m.{a.metric}" in df.columns else a.metric
    rows = [g if g in df.columns else (f"cfg.{g}" if f"cfg.{g}" in df.columns else f"m.{g}")
            for g in a.group.split(",")]

    piv = df.pivot_table(index=rows, columns=oncol, values=mcol, aggfunc="last")
    import pandas as pd
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(f"\n{a.experiment}: {a.metric} by {a.on}  (fix: {a.fix or 'none'})\n")
        print(piv.to_string())


if __name__ == "__main__":
    main()
