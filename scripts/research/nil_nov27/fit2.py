import json, math, collections, numpy as np
from calib import ATH, POS, oldB, athB, R
from calib2 import score
from fit1 import on3, V
p4=lambda r:r['p4']
byT=collections.defaultdict(list)
for r in R: byT[r['team']].append(r)
for t,ps in byT.items():
    mx=max(math.log(max(r['y'],500)) for r in ps)
    for r in ps: r['s']=math.log(max(r['y'],500))-mx
def build(k,c,bud,adj=None,lvl=1.0):
    out={}
    for t,ps in byT.items():
        b=bud(t,ps)*(lvl if ps[0]['p4'] else 1)
        lw=np.array([k*r['s']-c*r['s']**2+(adj.get(r['pos'],0) if adj else 0) for r in ps]); w=np.exp(lw-lw.max()); w/=w.sum()
        for r,x in zip(ps,w): out[id(r)]=b*x
    return out
def fitpos(k,c,bud,iters=40,lr=0.5,lvl=1.0):
    adj=collections.defaultdict(float)
    for _ in range(iters):
        yn=build(k,c,bud,adj,lvl); rm,b,n,e=score(yn,p4)
        byp=collections.defaultdict(list)
        for pos,q,er in e: byp[pos].append(er)
        mu=np.mean([np.mean(v) for v in byp.values()])
        for cpos,errs in byp.items():
            for bp,cp in POS.items():
                if cp==cpos: adj[bp]-=lr*(float(np.mean(errs))-mu)
    return build(k,c,bud,adj,lvl),dict(adj)
if __name__=='__main__':
    for lvl in (1.0,0.88):
        for k in (0.8,1.0,1.25):
            for c in (0,.1,.2,.3,.45,.6):
                yn=build(k,c,athB,None,lvl); s=score(yn,p4); o=on3(yn)
                yn2,adj=fitpos(k,c,athB,lvl=lvl); s2=score(yn2,p4); o2=on3(yn2)
                print(lvl,k,c,'csc',[round(x,3) for x in s[:2]],'on3',o['bias'],o['sd'],o['r'],'| pos: csc',[round(x,3) for x in s2[:2]],'on3',o2['bias'],o2['sd'],o2['r'])
