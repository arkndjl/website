import json,sys,numpy as np,collections
sys.path.insert(0,'/home/user/website/scripts')
from names import key
S=json.load(open('../players/on3_nil_rankings_snapshot.json'))['lists']
j=json.load(open('/home/user/website/data/cfb_recruits.json'))
d=json.load(open('/home/user/website/static/data/cfb-all.json')); R=[dict(zip(d['cols'],r)) for r in d['rows']]
P4={'SEC','Big Ten','Big 12','ACC'}
lv=lambda r:'FCS' if r['div']=='FCS' else 'P4' if r['conf'] in P4 or r['team']=='Notre Dame' else 'G5'
by=collections.defaultdict(list)
B=[r for r in R if r['fv'] is not None and r['xnil']]
for r in B: by[(lv(r),round(r['fv']))].append(r['xnil'])
def nilAt(l,fv):
    for dd in range(7):
        for f in (round(fv)-dd,round(fv)+dd):
            v=by.get((l,f))
            if v and len(v)>=3: return sorted(v)[len(v)//2]
    return 0
adj=collections.defaultdict(list)
for r in B:
    if r['div']!='FCS' and not r['carried']:
        b=nilAt(lv(r),r['fv'])
        if b>0 and r['xnil']>0: adj[r['pos']].append(np.log(r['xnil']/b))
A={g:float(np.median(v)) for g,v in adj.items() if len(v)>=30}; print({g:round(v,2) for g,v in A.items()})
C={key(x['name']):x for x in j['class'] if x.get('xnil')}
M=[(o,C[key(o['name'])]) for o in S['hs_football'] if key(o['name']) in C and o.get('on3_val')]
for s in (0,.5,1):
    e=np.array([np.log(r['xnil']/o['on3_val'])+s*A.get(r['g'],0) for o,r in M]); p=np.array([np.log(r['xnil'])+s*A.get(r['g'],0) for o,r in M]); t=np.array([np.log(o['on3_val']) for o,_ in M])
    print(s,f'bias {e.mean():+.2f} sd {e.std():.3f} rmse {np.sqrt((e**2).mean()):.3f} r {np.corrcoef(p,t)[0,1]:.2f}')
# independent Athletic check: 5-star QB 750K-1M; top-150 QB 300-400K
for x in j['class']:
    if x.get('g')=='QB' and x.get('rank') and x['rank']<=150: print(x['name'],x['rank'],x.get('stars'),round(x['xnil']/1e3),'->',round(x['xnil']*np.exp(.5*A['QB'])/1e3))
n={g:len(adj[g]) for g in A}; cbar=sum(n[g]*A[g] for g in A)/sum(n.values()); print('centre',round(cbar,3))
rng=np.random.default_rng(2)
for s in (0,.5,1):
    e=np.array([np.log(r['xnil']/o['on3_val'])+s*(A.get(r['g'],cbar)-cbar) for o,r in M]); p=np.array([np.log(r['xnil'])+s*(A.get(r['g'],cbar)-cbar) for o,r in M]); t=np.array([np.log(o['on3_val']) for o,_ in M])
    print(s,f'bias {e.mean():+.2f} sd {e.std():.3f} rmse {np.sqrt((e**2).mean()):.3f} r {np.corrcoef(p,t)[0,1]:.2f}')
    if s==0: e0=e
    else:
        dr=[]
        for _ in range(4000):
            i=rng.integers(0,len(e),len(e)); dr.append(np.sqrt((e[i]**2).mean())-np.sqrt((e0[i]**2).mean()))
        print('   rmse change 90% CI',np.round(np.quantile(dr,[.05,.95]),3),'P(better)',np.mean(np.array(dr)<0).round(3))
