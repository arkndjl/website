import json, math, collections, numpy as np
from statistics import NormalDist
from base import rows
from csc import CSC, Q
from calib import ATH, POS, build, oldB, athB, R
nd=NormalDist()
NG=json.load(open('../football/dl/csc_nilgo_data.json'))
fb=[s for s in NG['sports'] if s['name']=='Football'][0]['horizons'][0]['bands']
NGO={('A4' if b['cut']=='A4' else 'N'):{r['label']:(r['count'],r['values']) for r in b['rows']} for b in fb}
def qfun(points):
    """points: (overall quantile q, $>0); returns f(q) by linear interpolation of log $ on normal z, flat slope extrapolation"""
    pts=sorted({(nd.inv_cdf(min(max(q,1e-4),1-1e-4)),math.log(v)) for q,v in points if v and v>0})
    zs=np.array([p[0] for p in pts]); ys=np.array([p[1] for p in pts])
    def f(q):
        z=nd.inv_cdf(min(max(q,1e-4),1-1e-4))
        if z<=zs[0]: s=(ys[1]-ys[0])/(zs[1]-zs[0]); return math.exp(ys[0]+s*(z-zs[0]))
        if z>=zs[-1]: s=(ys[-1]-ys[-2])/(zs[-1]-zs[-2]); return math.exp(ys[-1]+s*(z-zs[-1]))
        return math.exp(float(np.interp(z,zs,ys)))
    return f
def target(pos,tier):
    a=CSC[pos][tier]; n=a['all'][1]; npd=a['paid'][1]
    rs=[(q,v) for q,v in zip(Q,a['all'][2])]+[(1-(npd/n)*(1-q),v) for q,v in zip(Q,a['paid'][2])]
    frs=qfun(rs); c,vals=NGO[tier].get(pos,(0,[]))
    ng=[(1-(c/n)*(1-q),v) for q,v in zip(Q,vals) if v]
    fng=qfun(ng) if len(ng)>=2 else (lambda q:0)
    lo_rs=1-npd/n; lo_ng=1-c/n
    def tot(q): return (frs(q) if q>lo_rs else 0)+(fng(q) if q>lo_ng else 0)
    qs=sorted({round(q,4) for q,v in rs if v and v>0})
    return n,tot,qs,frs,fng
def score(yn, sel, tier='A4', verbose=False, R=R):
    byp=collections.defaultdict(list)
    for r in R:
        if sel(r): byp[POS.get(r['pos'])].append(yn[id(r)])
    e=[]
    for pos in CSC:
        xs=sorted(byp.get(pos,[]),reverse=True); m=len(xs)
        if m<40: continue
        n,tot,qs,_,_=target(pos,tier)
        for q in qs:
            u=(1-q)*n/m
            if u>=0.95: continue
            mod=max(xs[min(m-1,int(u*m))],100); t=tot(q)
            e.append((pos,q,math.log(mod/t)))
            if verbose: print(f'{pos:18s} q{q:.3f} model {mod:>10,.0f} target {t:>10,.0f} {e[-1][2]:+.2f}')
    a=np.array([x[2] for x in e]); return float(np.sqrt((a**2).mean())), float(a.mean()), len(a), e
if __name__=='__main__':
    p4=lambda r:r['p4']
    # implied totals per A4 school from the target (integrate numerically, capped at q .995)
    S=0
    for pos in CSC:
        n,tot,_,frs,fng=target(pos,'A4'); qs=np.linspace(0.0005,0.9995,2000); S+=n*np.mean([tot(q) for q in qs])
        print(pos,n,'top1% total',round(tot(.99)),'p90',round(tot(.9)),'p50',round(tot(.5)))
    print('implied A4 football total per school $M',S/68/1e6)
    r=score(build(1,oldB),p4); print('old',[round(x,3) for x in r[:2]],r[2])
    for lev,name in ((athB,'athletic'),(lambda t,ps:20e6 if ps[0]['p4'] else sum(r['y'] for r in ps),'flat20'),(lambda t,ps:(ATH.get(t,0)*20/27.2) if ps[0]['p4'] else 1,'ath x .735')):
        for k in (1,1.25,1.5,1.75,2,2.5,3):
            r=score(build(k,lev),p4); print(name,'k',k,[round(x,3) for x in r[:2]])
    score(build(1.5,athB),p4,verbose=True)
