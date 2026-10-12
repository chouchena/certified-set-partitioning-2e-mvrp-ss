"""n30 repair roll-up. Run at LB REPAIR n30 COMPLETE. Writes nothing to the repo."""
import sys, json, glob, os, re, statistics as st; sys.path.insert(0,'.'); sys.path.insert(0,'analysis')
from lb_monitor import fam, k_table3, protocol_split
from analysis.night_batch import k_targets

AB={r["cell"]:r for r in json.load(open("runs/ab4_grid_results.json")).values()
    if "error" not in r and r["size"]==30}
DMG={os.path.basename(f).split("_")[3] for f in glob.glob("crossfeed/easy_reduction_descend_*_n30_kcapbug.json")}

def finished_cells():
    """Cells the repair has DECLARED done. Reading a live artifact mid-descent gives a
    PARTIAL maximum: on 2026-09-11 R207 read as 549.16 (its k=19 record, 2 rows written)
    while the run was still descending, and finished at 588.59 (k=17, 6 rows). The number
    was real but not the max, and it was reported before it was final. Only trust cells the
    log says are done."""
    import re as _re
    fp = os.path.join("runs", "lb_repair_n30.log")
    if not os.path.exists(fp):
        return set()
    done = set()
    for l in open(fp, encoding="utf-8", errors="replace"):
        m = _re.search(r"^\[[\d:]+\]\s+((?:C|R|RC)\d{3}) done in ", l)
        if m:
            done.add(m.group(1))
    return done


FINISHED = finished_cells()

def top(fp):
    try: J=[x for x in json.load(open(fp,encoding="utf-8")) if isinstance(x,dict) and x.get("block_relax") is not None]
    except Exception: return None,0,0
    if not J: return None,0,0
    return max(x["block_relax"] for x in J), len(J), sum(1 for x in J if x.get("proven"))

print(f"cells the repair log declares DONE: {len(FINISHED)}/10  {sorted(FINISHED)}")
print("="*84)
for l in protocol_split(30, list(k_targets(30))): print(l)
print("="*84)
print("\n=== REPAIR: per-cell old vs new (PREREG rule 2: every regression reported) ===")
print(f"{'cell':7}{'damaged':>10}{'repaired':>10}{'delta':>9}{'recs':>6}{'proven':>8}  verdict")
reg=[]; done=[]
for c in sorted(DMG):
    d,_,_ = top(f"crossfeed/easy_reduction_descend_{c}_n30_kcapbug.json")
    n,nr,np_ = top(f"crossfeed/easy_reduction_descend_{c}_n30.json")
    if c not in FINISHED:
        print(f"{c:7}{d:>10.2f}{'--':>10}{'':>9}{'':>6}{'':>8}  NOT YET REPAIRED (excluded)"); continue
    done.append(c)
    v = "REGRESSION" if n<d-1e-6 else ("equal" if abs(n-d)<1e-6 else "improved")
    if v=="REGRESSION": reg.append(c)
    print(f"{c:7}{d:>10.2f}{n:>10.2f}{(n-d)/d*100:>8.1f}%{nr:>6}{np_:>8}  {v}")
print(f"\n  repaired {len(done)}/10   REGRESSIONS {len(reg)} {reg}")
print(f"  PREREG rule 3 threshold is 3 -> {'FIRES: k_hi=20 REFUTED, re-run at k_hi=15' if len(reg)>=3 else 'does NOT fire; rule 1 stands (report the repair run)'}")

print("\n=== AB vs our MILP at n30, after repair ===")
print(f"{'cell':7}{'MILP':>10}{'AB4':>9}{'carrier':>9}{'was':>12}")
was_ab={"R204","R207","R208","R211","RC208"}
ab_wins=[]
cells=[c for c in k_targets(30)]
for c in sorted(cells):
    n,nr,_=top(f"crossfeed/easy_reduction_descend_{c}_n30.json")
    if n is None or c not in AB: continue
    ab=AB[c]["ab4"]; carr="AB4" if ab>n else "MILP"
    if carr=="AB4": ab_wins.append(c)
    if c in was_ab or carr=="AB4":
        print(f"{c:7}{n:>10.2f}{ab:>9.2f}{carr:>9}{('AB (damaged)' if c in was_ab else ''):>12}")
print(f"\n  AB beats our MILP at n30: {len(ab_wins)}/{len(cells)} cells {ab_wins}")

print("\n=== n30 family means vs K Table 3 (portfolio max(MILP,AB4)) ===")
t3=k_table3(30)
print(f"{'fam':>4}{'n':>4}{'K LB':>10}{'ours':>10}{'xK':>7}{'K certifies':>13}{'we certify':>12}")
for f in ("C","R","RC"):
    g=[c for c in cells if fam(c)==f and c in t3 and top(f'crossfeed/easy_reduction_descend_{c}_n30.json')[0]]
    if not g: continue
    kl=st.mean(t3[c][0] for c in g)
    ours=st.mean(max(top(f'crossfeed/easy_reduction_descend_{c}_n30.json')[0], AB[c]["ab4"]) for c in g)
    bk=st.mean(t3[c][2] for c in g)
    viol=[c for c in g if max(top(f'crossfeed/easy_reduction_descend_{c}_n30.json')[0],AB[c]["ab4"])>t3[c][2]+1e-6]
    print(f"{f:>4}{len(g):>4}{kl:>10.2f}{ours:>10.2f}{ours/kl:>7.2f}{kl/bk*100:>12.1f}%{ours/bk*100:>11.1f}%"
          + (f"  *** ABOVE BK: {viol}" if viol else ""))
