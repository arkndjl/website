"""pos.py with the front seven pooled: schools list many edge players as linebackers (board P4 DL + EDGE 1,322 against
CSC's 1,060 defensive linemen; LB 795 against 858), so DL / EDGE is scored on DL + LB together."""
import math, collections, numpy as np
import full as F
from full import rows, csc_score, on3, deals, starters, CSC, target, POS
from pos import tweak, rep, on3pos
GROUPS={'QB':['Quarterback'],'RB':['Running Back'],'WR':['Wide Receiver'],'TE':['Tight End'],'OL':['Offensive Lineman'],'F7':['Defensive Lineman','Linebacker'],'DB':['Defensive Back']}
BP={'QB':'QB','RB':'RB','WR':'WR','TE':'TE','OL':'OL','DL':'F7','EDGE':'F7','LB':'F7','CB':'DB','S':'DB'}
QS=(.25,.4,.5,.6,.7,.75,.8,.85,.9,.925)
def pooled(names,tier):
    v=[]; N=0
    for nm in names:
        n,tot,_,_,_=target(nm,tier); N+=n
        v+=[tot((i+.5)/n) for i in range(n)]
    return N,sorted(v,reverse=True)
def err(yn,tier='A4',qmin=0):
    A=[r for r in rows if (r['p4'] if tier=='A4' else not r['p4']) and r['kind']!='other']; byg=collections.defaultdict(list)
    for r in A:
        if r['pos'] in BP: byg[BP[r['pos']]].append(yn.get(id(r),0.0))
    o={}
    for g,names in GROUPS.items():
        N,tv=pooled(names,tier); xs=sorted(byg[g],reverse=True); e=[]
        for q in QS:
            if q<qmin: continue
            k=int((1-q)*N)
            if k<len(xs)*.98 and k<len(xs): e.append(math.log((xs[k]+1e4)/(tv[k]+1e4)))
        o[g]=round(float(np.mean(e)),3)
    return o
def total(o): v=np.array(list(o.values())); return round(float(np.sqrt((v**2).mean())),3), round(float(v.std()),3)
def solve(which=('RB','WR','TE','F7'),iters=60,only=('DL','EDGE'),tier='A4'):
    off={}
    for _ in range(iters):
        e=err(tweak(off),tier); ref=float(np.mean([v for g,v in e.items() if g not in which]))
        for p,g in BP.items():
            if g in which and (g!='F7' or p in only): off[p]=off.get(p,0.0)-.5*(e[g]-ref)
    return off
if __name__=='__main__':
    b=tweak({}); rep('base',b); print('  grp',err(b),total(err(b))); print('  top',err(b,qmin=.74)); print('  nonA4',err(b,'N'))
    for nm,kw in (('RB WR TE DL/EDGE',{}),('RB WR TE DL/EDGE/LB',dict(only=('DL','EDGE','LB'))),('RB WR TE only',dict(which=('RB','WR','TE'))),('RB only',dict(which=('RB',)))):
        off=solve(**kw); y=tweak(off); rep(nm,y); print('  off',{k:round(v,2) for k,v in off.items()}); print('  grp',err(y),total(err(y))); print('  nonA4',err(y,'N')); print('  on3',on3pos(y))
