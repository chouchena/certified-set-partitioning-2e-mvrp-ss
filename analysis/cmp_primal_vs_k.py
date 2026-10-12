"""Primal batch vs K's per-instance baseline (n20/n30): OV (ours vs K's incumbent, d1 = MIN over
K's joint/LBBD) and optimality gap (ours-to-ours vs K-to-K = K's published joint_gap). Prints only."""
import sys
sys.path.insert(0, "analysis")
import k_comparison as K

kref = K._kref()
OURS = {
    20: {"C203": (674.452, 658.299), "C204": (668.935, 519.703), "R207": (582.385, 465.718),
         "R211": (577.696, 483.324), "RC204": (643.028, 489.010)},
    30: {"C203": (827.030, 799.032), "C204": (806.690, 734.868), "R207": (890.122, 677.521),
         "R211": (913.712, 694.814), "RC204": (1278.418, 904.853)},
}
for n in (20, 30):
    per = kref["table3"]["per_instance"][str(n)]
    print("=== n%d ===" % n)
    print("  %-6s %9s %9s %7s | %8s %8s" % ("cell", "ourOV", "K_OV", "dOV%", "ours_gap", "K_gap"))
    for c in ["C203", "C204", "R207", "R211", "RC204"]:
        ov, lb = OURS[n][c]
        r = per[c]
        k_ov = min(r["joint_bk"], r["lbbd_bk"])        # d1: primal takes the MIN over K's methods
        k_gap = r["joint_gap"]                          # K-to-K: K's published joint optimality gap
        our_gap = 100.0 * (ov - lb) / ov
        print("  %-6s %9.2f %9.2f %+6.1f%% | %7.1f%% %7.0f%%"
              % (c, ov, k_ov, 100.0 * (ov / k_ov - 1), our_gap, k_gap))
