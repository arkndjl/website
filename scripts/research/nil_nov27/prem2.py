import math, collections, numpy as np
import full as F
from full import rows, byT, csc_score, on3, deals, starters, CSC, target, POS
def tweak(qb=0.0, qb1=0.0, c=0.0, topn=None):
    """QB weight x e^qb (all QBs), starter QB (top yNIL QB on team) x e^qb1, live exponent 1+c; team totals fixed"""
    out={}
    for (t,div),ps in byT.items():
        rr=[r for r in ps if r['y']]
        if not rr: continue
        B=sum(r['y'] for r in rr); q1=max([r for r in rr if r['pos']=='QB'],key=lambda r:r['y'],default=None)
        gm=np.exp(np.mean([math.log(r['y']) for r in rr if r['kind']=='live'] or [0]))
        w=[]
        for r in rr:
            x=r['y']
            if r['kind']=='live' and c: x=gm*(x/gm)**(1+c)
            if r['pos']=='QB': x*=math.exp(qb+(qb1 if r is q1 else 0))
            w.append(x)
        s=sum(w)
        for r,x in zip(rr,w): out[id(r)]=B*x/s
    return out
def cscpos(yn,qmin=.74):
    A=[r for r in rows if r['p4'] and r['kind']!='other']; byp=collections.defaultdict(list)
    for r in A: byp[POS.get(r['pos'])].append(yn.get(id(r),0.0))
    o={}
    for pos in CSC:
        xs=sorted(byp.get(pos,[]),reverse=True); m=len(xs)
        if m<60 or pos in('Kicker','Punter'): continue
        n,tot,qs,_,_=target(pos,'A4'); e=[]
        for q in sorted(set(qs)):
            if q<qmin: continue
            u=(1-q)*n/m
            if u<.98: e.append(math.log((xs[min(m-1,int(u*m))]+1e4)/(tot(q)+1e4)))
        o[pos[:9]]=round(float(np.mean(e)),2)
    return o
def rep(nm,yn): print(f'{nm:22s} cscA4 {csc_score(yn,"A4")} on3 {on3(yn)} deals {deals(yn)} espn {starters(yn)} top {max(yn.values())/1e6:.1f}M')
if __name__=='__main__':
    base=tweak(); rep('base',base); print('  CSC top quantiles (q>=.75) model/actual log, by position:',cscpos(base)); print('  mid (q .45-.74):',{k:v for k,v in cscpos(base,.45).items()})
    for qb in (.15,.3,.45): rep(f'QB all +{qb}',tweak(qb=qb))
    for q1 in (.15,.3,.45): rep(f'QB1 +{q1}',tweak(qb1=q1))
    for c in (-.1,.1,.2): rep(f'convex {c:+}',tweak(c=c))
    print('  after QB all +.3:',cscpos(tweak(qb=.3)))
