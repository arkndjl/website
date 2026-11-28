"""Walk-forward check: each class from a fit on the classes before it only. Run from the repo root."""
import sys,math;sys.path.insert(0,'scripts/research/recruit_pos_nov28');import numpy as np
import cfb_pos as F, cbb_pos as B, mnl
def wf(rows, specs, start):
    c=np.array([r['c'] for r in rows]);Y=np.array([r['y'] for r in rows]);out={}
    for nm,mk in specs.items():
        X=np.array([mk(r) for r in rows]);ll=np.full(len(rows),np.nan)
        for k in sorted(set(c)):
            if k<start: continue
            tr=c<k; b=mnl.fit(X[tr],Y[tr],1.0); ll[c==k]=mnl.logloss(mnl.predict(X[c==k],b),Y[c==k])
        out[nm]=ll
    ks=[k for k in sorted(set(c)) if k>=start]; n=list(specs)
    d=[np.nanmean(out[n[0]][c==k])-np.nanmean(out[n[-1]][c==k]) for k in ks]
    print(n[0],'->',n[-1],'walk-forward LL %.4f -> %.4f'%(np.nanmean(out[n[0]]),np.nanmean(out[n[-1]])),'t %.2f wins %d/%d'%(np.mean(d)/(np.std(d,ddof=1)/math.sqrt(len(d))),sum(x>0 for x in d),len(d)))
rows=[r for r in F.load() if 2014<=r['c']<=2024]
hs=[r['ht'] for r in rows if r['ht']];ws=[r['wt'] for r in rows if r['wt']];gs=[r['grade'] for r in rows if r['grade']]
F.SZ.update(ht=float(np.mean(hs)),hs=float(np.std(hs)),wt=float(np.mean(ws)),ws=float(np.std(ws)),gr=float(np.mean(gs)),gs=float(np.std(gs)))
wf(rows,{'listed':lambda r:F.feats(r['code'],r['ht'],r['wt'],r['grade'],size=False,gr=False),'model':lambda r:F.feats(r['code'],r['ht'],r['wt'],r['grade'])},2017)
ath=[r for r in rows if r['code']=='ATH']
wf(ath,{'listed':lambda r:F.feats(r['code'],r['ht'],r['wt'],r['grade'],size=False,gr=False),'model':lambda r:F.feats(r['code'],r['ht'],r['wt'],r['grade'])},2017)
rows=B.load();hs=[r['ht'] for r in rows if r['ht']];ws=[r['wt'] for r in rows if r['wt']]
import math as m;B.SZ.update(ht=float(np.mean(hs)),hs=float(np.std(hs)),wt=float(np.mean(ws)),ws=float(np.std(ws)),lr=float(np.mean([m.log(r['rk']) for r in rows if r['rk']])))
wf(rows,{'listed':lambda r:B.feats(r['code'],r['ht'],r['wt'],r['rk'],False,False),'model':lambda r:B.feats(r['code'],r['ht'],r['wt'],r['rk'])},2013)
