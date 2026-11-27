import json, math, collections, re
import numpy as np
W='/home/user/website/'
d=json.load(open(W+'static/data/cfb-all.json')); c={k:i for i,k in enumerate(d['cols'])}
on={x['slug']:x for x in json.load(open('on3_cfb.json'))}
P4C={'SEC','Big Ten','Big 12','ACC'}
rows=[]
for r in d['rows']:
    if r[c['ynil']] is None: continue
    g=lambda k:r[c[k]]
    slug=None
    if g('on3l'):
        m=re.search(r'/rivals/([^/]+)-\d+/?$', g('on3l')); slug=m.group(1) if m else None
        full=g('on3l').rstrip('/').split('/')[-1]
    o=on.get(full) if g('on3l') else None
    if o is None and slug: o=on.get(slug)
    rows.append(dict(name=g('name'),pos=g('pos'),team=g('team'),conf=g('conf'),div=g('div'),fv=g('fv'),y=g('ynil'),x=g('xnil'),snaps=g('snaps'),cls=g('cls'),
        p4=(g('conf') in P4C or g('team')=='Notre Dame'), ranked=o is not None, nil=(o or {}).get('nil'), grade=g('on3'), transfer=(o or {}).get('transfer')))
if __name__=='__main__':
    print(list(on.keys())[:3])
    R=[r for r in rows if r['div']=='FBS']
    print(len(R), sum(r['ranked'] for r in R), sum(1 for r in R if r['nil']))
    V=[r for r in R if r['nil']]; C=[r for r in R if r['ranked'] and not r['nil']]
    for k in ('y','x'):
        e=np.array([math.log(max(r[k],1e3)/r['nil']) for r in V]); print(k,'valued n',len(V),'bias',e.mean().round(3),'sd',e.std().round(3),'rmse',np.sqrt((e**2).mean()).round(3), 'r',np.corrcoef([math.log(max(r[k],1e3)) for r in V],[math.log(r['nil']) for r in V])[0,1].round(3))
        cv=np.array([r[k] for r in C]); print(k,'censored n',len(C),'share >300K',(cv>3e5).mean().round(3),'median',np.median(cv), 'p90',np.quantile(cv,.9))
        # unranked players above 300K
        U=[r for r in R if not r['ranked']]; uv=np.array([r[k] for r in U]); print(k,'unranked n',len(U),'>300K',(uv>3e5).sum(),'>1M',(uv>1e6).sum())
    print('valued by p4',collections.Counter(r['p4'] for r in V), 'ranked p4', collections.Counter(r['p4'] for r in C))
    tot=collections.Counter()
    for r in R: tot['p4' if r['p4'] else 'g5']+=r['y']
    nt=collections.Counter(); 
    for t,p in {(r['team'],r['p4']) for r in R}: nt['p4' if p else 'g5']+=1
    print({k:(round(tot[k]/nt[k]/1e6,2),nt[k]) for k in tot})
    # count players above thresholds
    for k in ('y','x'):
        v=np.array([r[k] for r in R]); print(k,[int((v>t).sum()) for t in (3e5,5e5,1e6,2e6,3e6)])
    nv=np.array([r['nil'] for r in V]); print('on3',[int((nv>=t).sum()) for t in (3e5,5e5,1e6,2e6,3e6)])
