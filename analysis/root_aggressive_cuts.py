import sys, os, json
sys.path.insert(0, r"C:\Users\user\Downloads\2nd-paper-karademir\2nd-paper-karademir")
import os as _o, sys as _s
_s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
from analysis.stamp import stamped
from build_instance import build
from joint_model_cplex import build_joint_model
REF={"C202":(663.1,678.7),"C203":(648.2,673.7),"R204":(525.9,582.8),"RC202":(829.4,900.6)}
print(f"{'cell':8s} {'default':>9s} {'AGGRESSIVE':>11s} {'our LB':>8s} {'incumb':>8s}  our LB / root")
dflt={r['cell']:r['root_after_cuts'] for r in json.load(open('runs/root_after_cuts.json'))}
out=[]
for c in REF:
    pr=build(c,20,tau="formula"); H=build_joint_model(pr); m=H.m; p=m.parameters
    p.timelimit=600; p.mip.limits.nodes=1; p.threads=4

    for nm in ['gomory','cliques','covers','disjunctive','flowcovers','gubcovers',
               'implied','mircut','pathcut','zerohalfcut','liftproj']:
        try: getattr(p.mip.cuts,nm).set(2)
        except Exception: pass
    p.mip.strategy.probe.set(3)
    m.solve(log_output=False); d=m.solve_details
    lb,inc=REF[c]; out.append(dict(cell=c,aggressive=d.best_bound,time=d.time))
    print(f"{c:8s} {dflt[c]:9.1f} {d.best_bound:11.1f} {lb:8.1f} {inc:8.1f}  {lb/d.best_bound:6.2f}x  ({d.time:.0f}s)")
json.dump(stamped(out, __file__),open('runs/root_aggressive_cuts.json','w'),indent=1)
