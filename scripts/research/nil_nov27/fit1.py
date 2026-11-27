import json, math, collections, numpy as np
from calib import ATH, POS, build, oldB, athB, R
from calib2 import score
p4=lambda r:r['p4']
V=[r for r in R if r['nil']]
def on3(yn, S=V):
    e=np.array([math.log(max(yn[id(r)],1e3)/r['nil']) for r in S])
    r_=np.corrcoef([math.log(max(yn[id(r)],1e3)) for r in S],[math.log(r['nil']) for r in S])[0,1]
    return dict(n=len(S),bias=round(float(e.mean()),3),sd=round(float(e.std()),3),rmse=round(float(np.sqrt((e**2).mean())),3),r=round(float(r_),3))
GRP={'QB':'QB','RB':'RB','WR':'WR','TE':'TE','OL':'OL','EDGE':'DL','DL':'DL','LB':'LB','CB':'DB','S':'DB'}
def fitpos(k, bud, iters=25, lr=0.6):
    adj=collections.defaultdict(float)
    for _ in range(iters):
        yn=build(k,bud,posadj=adj); rm,b,n,e=score(yn,p4)
        byp=collections.defaultdict(list)
        for pos,q,er in e: byp[pos].append(er)
        for cpos,errs in byp.items():
            for bp,cp in POS.items():
                if cp==cpos: adj[bp]-=lr*float(np.mean(errs))
    yn=build(k,bud,posadj=adj); return yn,dict(adj),score(yn,p4)
if __name__=='__main__':
    print('baseline on3',on3(build(1,oldB)), 'p4 only',on3(build(1,oldB),[r for r in V if r['p4']]))
    print('ath k1',on3(build(1,athB)))
    for k in (1,1.5,2,2.5,3):
        yn=build(k,athB); print('k',k,'no pos', [round(x,3) for x in score(yn,p4)[:2]], on3(yn))
        yn,adj,sc=fitpos(k,athB); print('   pos fit', [round(x,3) for x in sc[:2]], on3(yn), {a:round(b,2) for a,b in adj.items()})
