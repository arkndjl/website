"""Position repricing to the CSC pay percentiles (Noah Nov 27: reprice RB / WR / TE / DL to what schools report paying).
A log offset per position on every paid row at it, team totals held. Solved so each repriced position's mean CSC log
error over the quantiles (A4) is zero."""
import math, collections, sys, numpy as np
import full as F
from full import rows, byT, csc_score, on3, deals, starters, CSC, target, POS
GRP={'RB':'RB','WR':'WR','TE':'TE','DL':'DL','EDGE':'DL'}
def tweak(off):
    out={}
    for (t,div),ps in byT.items():
        rr=[r for r in ps if r['y']]
        if not rr: continue
        B=sum(r['y'] for r in rr); w=[r['y']*math.exp(off.get(r['pos'],0.0)) for r in rr]; s=sum(w)
        for r,x in zip(rr,w): out[id(r)]=B*x/s
    return out
def cscpos(yn,qmin=0,qmax=1,tier='A4'):
    A=[r for r in rows if (r['p4'] if tier=='A4' else not r['p4']) and r['kind']!='other']; byp=collections.defaultdict(list)
    for r in A: byp[POS.get(r['pos'])].append(yn.get(id(r),0.0))
    o={}
    for pos in CSC:
        xs=sorted(byp.get(pos,[]),reverse=True); m=len(xs)
        if m<60 or pos in('Kicker','Punter'): continue
        n,tot,qs,_,_=target(pos,tier); e=[]
        for q in sorted(set(qs)|{.5,.25}):
            if q<qmin or q>qmax: continue
            u=(1-q)*n/m
            if u<.98: e.append(math.log((xs[min(m-1,int(u*m))]+1e4)/(tot(q)+1e4)))
        o[pos]=round(float(np.mean(e)),3) if e else None
    return o
def rep(nm,yn): print(f'{nm:26s} cscA4 {csc_score(yn,"A4")} cscN {csc_score(yn,"N")} on3 {on3(yn)} deals {deals(yn)} espn {starters(yn)} top {max(yn.values())/1e6:.1f}M')
def on3pos(yn):
    g=collections.defaultdict(list)
    for r in F.V: g[r['pos']].append(math.log(max(yn[id(r)],1e3)/r['nil']))
    return {k:(len(v),round(float(np.mean(v)),2)) for k,v in sorted(g.items())}
CP={'RB':'Running Back','WR':'Wide Receiver','TE':'Tight End','DL':'Defensive Lineman'}
def solve(which=('RB','WR','TE','DL'),qmin=0,iters=40,ref0=False):
    off={}
    for _ in range(iters):
        e=cscpos(tweak(off),qmin)
        ref=0.0 if ref0 else float(np.mean([v for k,v in e.items() if k not in [CP[w] for w in which]]))
        for p,g in GRP.items():
            if g in which: off[p]=off.get(p,0.0)-.5*(e[CP[g]]-ref)
    return off
if __name__=='__main__':
    b=tweak({}); rep('base',b)
    print(' all q',cscpos(b)); print(' q>=.74',cscpos(b,.74)); print(' q .3-.74',cscpos(b,.3,.74)); print(' nonA4 all',cscpos(b,tier='N')); print(' on3 by pos',on3pos(b))
    for nm,kw in (('to zero, all q',dict(ref0=True)),('to others mean, all q',dict()),('to zero, q>=.74',dict(ref0=True,qmin=.74))):
        off=solve(**kw); y=tweak(off); rep(nm,y); print('  off',{k:round(v,2) for k,v in off.items()}); print('  csc',cscpos(y)); print('  on3',on3pos(y))
