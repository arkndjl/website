# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Exploration (not a test): does team context explain what a CFB draft-day FV grade misses? All-time rows (one per
player, draft-day grade with his class held out), mature drafts 2015-23. Residual = outcome FV - grade."""
import gzip,json,sys,os,collections,numpy as np
sys.path.insert(0,'scripts'); import fv_alltime as FA, names as N
import inspect
src=inspect.getsource(FA.cfb); cut=src.index("    # one row per player"); ns={}
exec(src[:cut].replace("def cfb(path):","def cfb_fin(path):")+"    return fin\n", FA.__dict__, ns)
fin=ns["cfb_fin"](FA.CFB_ROWS)
rows=[dict(r, stars=q.get("stars"), years=q.get("years")) for r,q in fin if r.get("out") is not None and r.get("fvx") is not None]
H=json.load(gzip.open('scripts/data/cfb_hist_md.json.gz'))
def ridge_unit(S):
    adv=H['adv'][S]; teams=sorted({r['team'] for r in adv}|{r['opponent'] for r in adv}); ix={t:i for i,t in enumerate(teams)}; n=len(teams)
    X=[];y=[];w=[]
    for r in adv:
        o=r.get('offense') or {}
        if not o.get('plays') or o.get('ppa') is None: continue
        x=np.zeros(2*n); x[ix[r['team']]]=1; x[n+ix[r['opponent']]]=1; X.append(x); y.append(o['ppa']); w.append(o['plays']/65)
    X=np.array(X); y=np.array(y); w=np.array(w); mu=(w*y).sum()/w.sum()
    Aw=X*w[:,None]; b=np.linalg.solve(X.T@Aw+2*np.eye(2*n), Aw.T@(y-mu))
    return {t:(b[ix[t]], -b[n+ix[t]]) for t in teams}   # offense rating, defense rating (higher = better)
U={}
for S in H['adv']:
    u=ridge_unit(S); o=np.array([v[0] for v in u.values()]); d=np.array([v[1] for v in u.values()])
    U[int(S)]={N.team_key(t):((v[0]-o.mean())/o.std(),(v[1]-d.mean())/d.std()) for t,v in u.items()}
P4=set()
for S,gs in H['games'].items():
    for g in gs:
        for sd in ('home','away'):
            if g.get(sd+'Conference') in ('SEC','Big Ten','Big 12','ACC','Pac-12'): P4.add((int(S),N.team_key(g[sd+'Team'])))
D=[]
for r in rows:
    S=r['last']; u=U.get(S,{}).get(N.team_key(r['team']))
    if u is None: continue
    D.append((r['pos'],r['draft'] or S+1,r['fvx'],r['out'],u[0],u[1],1 if (S,N.team_key(r['team'])) in P4 else 0,r.get('pick') or 0))
print(len(D),'of',len(rows),'rows joined')
pos=np.array([d[0] for d in D]); cls=np.array([d[1] for d in D]); fv=np.array([d[2] for d in D]); out=np.array([d[3] for d in D]); uo=np.array([d[4] for d in D]); ud=np.array([d[5] for d in D]); p4=np.array([d[6] for d in D])
res=out-fv
def sl(x,y,cl):
    x=x-x.mean(); b=(x*y).sum()/(x*x).sum(); e=(y-y.mean()-b*x)*x
    by=collections.defaultdict(float)
    for v,c in zip(e,cl): by[c]+=v
    se=np.sqrt(sum(v*v for v in by.values()))/ (x*x).sum()
    return b,b/se
for nm,mask in [('all',np.ones(len(D),bool)),('fvx>=30',fv>=30),('fvx>=40',fv>=40)]:
    print('==',nm,mask.sum())
    for g in ['QB','RB','WR','TE','EDGE','DT','LB','OFF','DEF']:
        k=mask&(np.isin(pos,['QB','RB','WR','TE']) if g=='OFF' else np.isin(pos,['EDGE','DT','LB']) if g=='DEF' else pos==g)
        if k.sum()<40: continue
        own=uo if g in('QB','RB','WR','TE','OFF') else ud; oth=ud if g in('QB','RB','WR','TE','OFF') else uo
        b1,t1=sl(own[k],res[k],cls[k]); b2,t2=sl(oth[k],res[k],cls[k]); b3,t3=sl(p4[k].astype(float),res[k],cls[k])
        print(f'  {g:5s} n {k.sum():5d} resid mean {res[k].mean():+.2f} | own unit z: {b1:+.2f} (t {t1:+.1f}) | other unit z: {b2:+.2f} (t {t2:+.1f}) | P4: {b3:+.2f} (t {t3:+.1f})')
