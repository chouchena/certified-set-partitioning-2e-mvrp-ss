"""n20/n30 per-cell PARITY cross-check (d663) -- discharges the 'our OV beats K at n100' burden.

Logic: at n100 K publishes no per-cell data, so 'ourOV < K_best' is a family-mean statement whose
validity rests on our OV machinery measuring the SAME feasible cost as K's on the SAME instance. At
n20/n30 K DOES publish per-instance incumbents (table3), so we can check that directly. If our
dual-derived OV tracks K per-cell there (small margin), the machinery is parity and the LARGE n100
margins are a real effect (K's n100 MILP is loose -- time-limit-bound, 60-77% gap, methods disagree
10-13%), not an artifact. If we 'won' by 12-27% even at n20/n30, that would flag a comparison bug.

Our OV = dual-derived (frzdual 'ov' = master_ip incumbent), the same quantity as the n100 table.
K per-cell = k_comparison.k_best_incumbent (table3). Single-tenant, read-only.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from k_comparison import k_best_incumbent

CELLS = (["C2%02d" % i for i in range(1, 9)] + ["R2%02d" % i for i in range(1, 12)]
         + ["RC2%02d" % i for i in range(1, 9)])


def our_ov(cell, size):
    for tag in ("frzdual", "frzprimal", "s%d" % size):
        p = os.path.join(ROOT, "runs", "oracle", "tep_solve_%s_%s_n%d.json" % (tag, cell, size))
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            r = d.get("rows", [d]); r = r[0] if isinstance(r, list) else r
            if r.get("ov") is not None:
                return r["ov"], tag
    return None, None


def main(argv):
    for size in (20, 30):
        print("\n=== PARITY n%d: our dual-derived OV vs K per-cell incumbent (table3) ===" % size)
        print("  %-7s %10s %10s %8s  %s" % ("cell", "ourOV", "K_inc", "margin", "src/method"))
        margins = []
        for c in CELLS:
            ov, tag = our_ov(c, size)
            try:
                kv = k_best_incumbent(c, size)
                kinc = kv[0] if isinstance(kv, (tuple, list)) else kv
                kmeth = kv[1] if isinstance(kv, (tuple, list)) and len(kv) > 1 else ""
            except Exception:
                kinc = kmeth = None
            if ov is None or kinc is None:
                print("  %-7s %10s %10s %8s  %s" % (c, ov if ov else "-", kinc if kinc else "-", "-", tag or ""))
                continue
            m = 100.0 * (ov / kinc - 1.0)
            margins.append(m)
            flag = "  <-- DECIMAL MATCH" if abs(ov - kinc) < 0.5 else ""
            print("  %-7s %10.2f %10.2f %+7.2f%%  %s/%s%s" % (c, ov, kinc, m, tag, kmeth, flag))
        if margins:
            margins.sort()
            n = len(margins)
            med = margins[n // 2] if n % 2 else 0.5 * (margins[n // 2 - 1] + margins[n // 2])
            mean = sum(margins) / n
            beat = sum(1 for m in margins if m < -0.05)
            tie = sum(1 for m in margins if abs(m) <= 0.05)
            print("  --- n=%d | mean %+.2f%% | median %+.2f%% | range [%+.2f%%, %+.2f%%] | beat %d tie %d lose %d"
                  % (n, mean, med, margins[0], margins[-1], beat, tie, n - beat - tie))
    print("\n  VERDICT: small n20/n30 margins (|few %|) => OV machinery is PARITY with K on shared")
    print("  instances => the large n100 family margins (-12/-24/-27%) are a real effect (K's n100")
    print("  incumbents are time-limit-loose), not a comparison artifact. Large margins HERE would")
    print("  instead flag a bug and BLOCK the n100 OV claim.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
