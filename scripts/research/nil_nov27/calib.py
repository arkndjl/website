import json, math, collections, numpy as np
from base import rows
from csc import CSC, Q
B=json.load(open('../football/budgets.json'))
ATH={}
for x in B:
    if str(x['season'])=='2026' and 'Athletic' in (x.get('source_name') or '') and x.get('low_usd') and x.get('high_usd'):
        ATH.setdefault(x['school'],(x['low_usd']+x['high_usd'])/2)
NM={'Miami':'Miami','California':'California','Pittsburgh':'Pittsburgh','Ole Miss':'Ole Miss'}
R=[r for r in rows if r['div']=='FBS']
teams={r['team'] for r in R if r['p4']}
print(len(ATH), sorted(set(ATH)-teams), sorted(teams-set(ATH)))
POS={'QB':'Quarterback','RB':'Running Back','WR':'Wide Receiver','TE':'Tight End','OL':'Offensive Lineman','EDGE':'Defensive Lineman','DL':'Defensive Lineman','LB':'Linebacker','CB':'Defensive Back','S':'Defensive Back','K':'Kicker','P':'Punter'}
def build(kappa, budget, R=R, posadj=None):
    by=collections.defaultdict(list)
    for r in R: by[r['team']].append(r)
    out={}
    for t,ps in by.items():
        b=budget(t,ps)
        lw=np.array([kappa*math.log(max(r['y'],500))+(posadj.get(r['pos'],0) if posadj else 0) for r in ps]); w=np.exp(lw-lw.max()); w=w/w.sum()
        for r,x in zip(ps,w): out[id(r)]=b*x
    return out
oldB=lambda t,ps: sum(r['y'] for r in ps)
athB=lambda t,ps: ATH.get(t) or sum(r['y'] for r in ps)
def targets(tier='A4'):
    """(csc pos, overall quantile q, rev-share $) points with $>0"""
    pts=[]
    for pos,d in CSC.items():
        a=d[tier]; n=a['all'][1]; npd=a['paid'][1]
        for q,v in zip(Q,a['all'][2]):
            if v and v>0: pts.append((pos,q,v,n))
        for q,v in zip(Q,a['paid'][2]):
            if v: pts.append((pos,1-(npd/n)*(1-q),v,n))
    return pts
def score(yn, f, sel, tier='A4', verbose=False):
    P=[r for r in R if sel(r)]
    byp=collections.defaultdict(list)
    for r in P: byp[POS.get(r['pos'])].append(yn[id(r)])
    e=[]
    for pos,q,v,n in targets(tier):
        xs=sorted(byp.get(pos,[]),reverse=True); m=len(xs)
        if m<20: continue
        u=(1-q)*n/m
        if u>=0.97: continue
        mod=max(xs[min(m-1,int(u*m))],100)
        e.append((pos,q,math.log(mod/(f*v))))
        if verbose: print(pos,round(q,3),round(mod),round(f*v),round(e[-1][2],2))
    a=np.array([x[2] for x in e]); return float(np.sqrt((a**2).mean())), float(a.mean()), len(a)
if __name__=='__main__':
    p4=lambda r:r['p4']
    cnt=collections.Counter(POS.get(r['pos']) for r in R if r['p4']); print({k:(v,CSC[k]['A4']['all'][1]) for k,v in cnt.items() if k})
    for f in (1.0,1.5,1.9):
        print('f',f,'old', score(build(1,oldB),f,p4))
        for k in (1,1.5,2,2.5,3,3.5,4,5):
            print('  k',k, [round(x,3) for x in score(build(k,athB),f,p4)])
