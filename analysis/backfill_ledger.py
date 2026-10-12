"""one-off: seed results/ledger.jsonl from logs produced before ledger existed."""
import sys, re
sys.path.insert(0, ".")
from analysis.ledger import emit

RID = "backfill-pre-ledger"

# --- mfree_cuts C204 (validation/mfree_C204.log) ---
emit("mfree_cuts", "C204", 20,
     config=dict(timing_mode="indicator", cuts=True, k=6, tl=1800, workers=6),
     metrics=dict(zA=466.24, proven=True, block_relax=512.08, n_cuts=1, wlb=45.8),
     wall_s=808, verified=None, notes="frontier; == bigM baseline 512.08", run_id=RID)
emit("mfree_cuts", "C204", 20,
     config=dict(timing_mode="indicator", cuts=True, k=5, tl=180, workers=6),
     metrics=dict(zA=290.95, proven=False, block_relax=336.79, n_cuts=1, wlb=45.8),
     wall_s=180, verified=None, notes="filter window; slope 0.09/s; projected miss -> abandon k<=5", run_id=RID)

# --- check_cuts (validation/check_cuts.log) ---
_cc = [
    ("C203", 674.6, 8, 2, 8, 1, 1, 0),
    ("C204", 676.2, 8, 2, 8, 1, 1, 0),
    ("R203", 761.6, 7, 2, 6, 1, 1, 0),
    ("R207", 605.8, 7, 1, 6, 1, 1, 0),
    ("R211", 622.2, 7, 1, 6, 1, 1, 0),
    ("RC203", 867.9, 13, 2, 9, 1, 1, 0),
]
for cell, obj, nvi, ncars, trips, troutes, clq, nf in _cc:
    emit("check_cuts", cell, 20,
         config=dict(budget_s=150),
         metrics=dict(obj=obj, n_vi=nvi, n_cars=ncars, trips_lb=trips, time_routes=troutes,
                      clique=clq, n_forced=nf, violations=0, holds=True),
         wall_s=150, verified=True, notes="all cuts hold", run_id=RID)

print("backfilled")
