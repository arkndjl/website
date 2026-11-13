# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import gzip,json,numpy as np,collections,sys
H=json.load(gzip.open('scripts/data/cfb_hist_md.json.gz'))
wf=json.load(gzip.open(sys.argv[1] if len(sys.argv)>1 else '/tmp/cfb_wf_base.json.gz'))
fbs={}
names={}
for S,gs in H['games'].items():
    fbs[int(S)]=set()
    for g in gs:
        if g['homeClassification']=='fbs': fbs[int(S)].add(g['homeTeam'])
        if g['awayClassification']=='fbs': fbs[int(S)].add(g['awayTeam'])
# 2026 from wf rows: teams w/ >=4 games
c=collections.Counter()
for r in wf:
    if r['S']==2026: c[r['home']]+=1; c[r['away']]+=1
fbs[2026]={t for t,n in c.items() if n>=6}
tot=[]
for S in range(2017,2027):
    new=fbs[S]-fbs.get(S-1,set()) if S-1 in fbs else set()
    if S==2026: new={t for t in new if t not in fbs[2025]}
    for t in sorted(new):
        R=[r for r in wf if r['S']==S and t in (r['home'],r['away']) and not (S==2026 and r['wk']>=11)]
        if not R: continue
        e=[(r['res']-r['m'])*(1 if r['home']==t else -1) for r in R]
        eL=[(r['res']-r['L'])*(1 if r['home']==t else -1) for r in R]
        e4=[x for x,r in zip(e,R) if r['wk']<=5]
        print(S,t,len(R),'res-m %+.1f'%np.mean(e),'first5wk %+.1f (n%d)'%(np.mean(e4) if e4 else 0,len(e4)),'res-L %+.1f'%np.mean(eL), 'MAEm %.1f MAEL %.1f'%(np.mean(np.abs(e)),np.mean(np.abs(eL))))
        tot+= [(x,y,r['wk']) for x,y,r in zip(e,eL,R)]
a=np.array(tot)
print('all new-FBS team games n',len(a),'res-m %+.2f t %.1f'%(a[:,0].mean(),a[:,0].mean()/(a[:,0].std()/np.sqrt(len(a)))),'MAE m %.2f L %.2f'%(np.abs(a[:,0]).mean(),np.abs(a[:,1]).mean()))
b=a[a[:,2]<=5]; print('wk<=5 n',len(b),'res-m %+.2f t %.1f'%(b[:,0].mean(),b[:,0].mean()/(b[:,0].std()/np.sqrt(len(b)))),'MAE m %.2f L %.2f'%(np.abs(b[:,0]).mean(),np.abs(b[:,1]).mean()))
