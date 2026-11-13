# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import gzip,json,numpy as np,collections,sys
H=json.load(gzip.open('scripts/data/cfb_hist_md.json.gz'))
wf=[r for r in json.load(gzip.open(sys.argv[1])) if r['fcs'] and not (r['S']==2026 and r['wk']>=11)]
def massey(games,lam=2.0,prior=None,iters=80):
    R=collections.defaultdict(float); by=collections.defaultdict(list)
    for g in games: by[g[0]].append(g); by[g[1]].append(g)
    pr=prior or {}
    for t in by: R[t]=pr.get(t,0)
    hfa=2.5
    for it in range(iters):
        hs=[m-R[h]+R[a] for h,a,m,n in games if not n]; hfa=np.mean(hs) if hs else 0
        for t,l in by.items():
            num=lam*pr.get(t,0); 
            for h,a,m,n in l:
                e=m-(0 if n else hfa); num+= e+R[a] if h==t else R[h]-e
            R[t]=num/(len(l)+lam)
    return dict(R)
fin={}; cls={}
for S in sorted(H['games'],key=int):
    gs=[(g['homeTeam'],g['awayTeam'],max(-35,min(35,g['homePoints']-g['awayPoints'])),g['neutralSite']) for g in H['games'][S] if g.get('completed') and g.get('homePoints') is not None]
    prior={t:.5*v for t,v in fin.get(int(S)-1,{}).items()}
    fin[int(S)]=massey(gs,2.0,prior)
    c={}
    for g in H['games'][S]: c[g['homeTeam']]=g['homeClassification']; c[g['awayTeam']]=g['awayClassification']
    cls[int(S)]=c
rows=[]
for r in wf:
    S=r['S']; 
    if S-1 not in fin: continue
    c=cls.get(S) or cls[S-1]
    hf=c.get(r['home'],'fcs')=='fbs' if S in cls else None
    # which side is FCS: use previous knowledge: team absent from fbs list
    fcsT = r['away'] if (cls.get(S,cls[2025]).get(r['home'])=='fbs') else r['home']
    d = -1 if fcsT==r['away'] else 1   # sign toward home margin of FCS strength
    F=fin[S-1]; fm=np.mean([v for t,v in F.items() if cls[S-1].get(t)=='fcs'])
    q1=F.get(fcsT); 
    q2=fin.get(S-2,{}).get(fcsT)
    if q1 is None: continue
    rows.append((S,r['wk'],d*(q1-fm), d*(((q1+(q2 if q2 is not None else q1))/2)-fm), r['res']-r['m'], r['L']-r['m'], r['id']))
a=np.array([x[:6] for x in rows],float)
print(len(a),'of',len(wf))
for nm,col in [('prev-season massey dev',2),('2yr avg',3)]:
    x=a[:,col]
    for tn,tc in [('res-m',4),('L-m',5)]:
        y=a[:,tc]; b=(x*y).sum()/(x*x).sum(); r=np.corrcoef(x,y)[0,1]
        print(nm,tn,'slope %.3f corr %.3f t %.1f'%(b,r,r*np.sqrt(len(x)-2)/np.sqrt(1-r*r)), 'sd x %.1f'%x.std())
    for lo,hi in [(2017,2020),(2021,2026)]:
        k=(a[:,0]>=lo)&(a[:,0]<=hi); r=np.corrcoef(a[k,col],a[k,4])[0,1]; r2=np.corrcoef(a[k,col],a[k,5])[0,1]
        print('   ',lo,hi,'n',k.sum(),'corr res-m %.3f  L-m %.3f'%(r,r2))
