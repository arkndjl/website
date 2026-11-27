import json,sys,numpy as np,collections
sys.path.insert(0,'/home/user/website/scripts')
from names import key
S=json.load(open('../players/on3_nil_rankings_snapshot.json'))['lists']
j=json.load(open('/home/user/website/data/cfb_recruits.json')); nf=json.load(open('/home/user/website/data/cfb.json'))['nilFit']
G=['QB','RB','WR','TE','OL','EDGE','DL','LB','CB','S']; b=dict(zip(G,[0]+nf['now'][4:13])); qf=nf['now'][13]
d=json.load(open('/home/user/website/static/data/cfb-all.json')); c={k:i for i,k in enumerate(d['cols'])}
cnt=collections.Counter(r[c['pos']] for r in d['rows'] if r[c['xnil']] and r[c['fv']] and r[c['fv']]>=30 and r[c['div']]=='FBS')
tot=sum(cnt[g] for g in G); bbar=sum(cnt[g]*b[g] for g in G)/tot; print('pos coefs',{g:round(v,2) for g,v in b.items()},'QBxFV',qf,'bbar',round(bbar,2))
C={key(x['name']):x for x in j['class'] if x.get('xnil')}
M=[(o,C[key(o['name'])]) for o in S['hs_football'] if key(o['name']) in C and o.get('on3_val')]
print('matched',len(M),collections.Counter(r['g'] for _,r in M).most_common())
def score(s):
    e=np.array([np.log(r['xnil']*np.exp(s*(b.get(r['g'],bbar)-bbar))/o['on3_val']) for o,r in M]); p=np.array([np.log(r['xnil'])+s*(b.get(r['g'],bbar)-bbar) for o,r in M]); t=np.array([np.log(o['on3_val']) for o,_ in M])
    return f'bias {e.mean():+.2f} sd {e.std():.3f} rmse {np.sqrt((e**2).mean()):.3f} r {np.corrcoef(p,t)[0,1]:.2f}'
for s in (0,.25,.5,.75,1): print('position term x',s,score(s))
g=collections.defaultdict(list)
for o,r in M: g[r['g']].append(np.log(r['xnil']/o['on3_val']))
print({k:(len(v),round(float(np.mean(v)),2)) for k,v in g.items()})
# QB only
def scoreq(q):
    e=np.array([np.log(r['xnil']*(np.exp(q) if r['g']=='QB' else 1)/o['on3_val']) for o,r in M]); return f'bias {e.mean():+.2f} rmse {np.sqrt((e**2).mean()):.3f}'
for q in (.3,.5,.7): print('QB only +',q,scoreq(q))
# leave-one-out for a QB premium fitted on the others
qs=[np.log(o['on3_val']/r['xnil']) for o,r in M if r['g']=='QB']; print('QB recruits n',len(qs),'mean log(On3/x)',np.mean(qs).round(2),'se',(np.std(qs,ddof=1)/np.sqrt(len(qs))).round(2))
print([(r['name'],r['rank'],round(r['xnil']/1e3),round(o['on3_val']/1e3)) for o,r in M if r['g']=='QB'])
rng=np.random.default_rng(1)
def errs(s,norm=True):
    e=np.array([np.log(r['xnil']/o['on3_val'])+s*(b.get(r['g'],bbar)-bbar) for o,r in M]); return e
for s in (.5,1):
    e0=errs(0); e1=errs(s); n=len(M); dr=[];ds=[]
    for _ in range(4000):
        i=rng.integers(0,n,n); dr.append(np.sqrt((e1[i]**2).mean())-np.sqrt((e0[i]**2).mean())); ds.append(e1[i].std()-e0[i].std())
    print('s',s,'rmse change',np.round(np.quantile(dr,[.05,.5,.95]),3),'sd change',np.round(np.quantile(ds,[.05,.5,.95]),3),'P(rmse better)',np.mean(np.array(dr)<0).round(3),'P(sd better)',np.mean(np.array(ds)<0).round(3))
# class pool neutral: rescale so total recruit xNIL is unchanged
allc=[x for x in j['class'] if x.get('xnil')]
for s in (.5,1):
    k=sum(x['xnil'] for x in allc)/sum(x['xnil']*np.exp(s*(b.get(x['g'],bbar)-bbar)) for x in allc)
    e=errs(s)+np.log(k); print('s',s,'pool-neutral scale',round(k,3),'bias',e.mean().round(2),'rmse',np.sqrt((e**2).mean()).round(3))
