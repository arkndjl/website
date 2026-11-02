"""Kicker and punter grades, Nov 2 2026 research (scripts/st_kickers.py). Which punt metric this season best predicts next season (held out by season).  python3 blend2.py nfl|cfb"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out") + "/"
os.makedirs(OUT, exist_ok=True)
import sys, numpy as np; 
import st_kickers as K
from collections import defaultdict
sport=sys.argv[1]
pl = K.nfl_plays(range(2012,2026)) if sport=='nfl' else K.cfb_plays(range(2010,2026))[0]
pu=pl['pu']
for r in pu: r['ryf']=r['ry'] if r['ret'] else 0
for fld in ('v','gross','net','i20','tb','ret','ryf'):
    K.expect(pu,fld,fld+'_oe',lambda r:(r['s'],int(min(99,r['yl'])//3)))
for r in pu:
    r['pin_oe']=r['v_oe'] if r['yl']<=50 else 0; r['far_oe']=r['v_oe'] if r['yl']>50 else 0
C=['v_oe','gross_oe','net_oe','i20_oe','tb_oe','ret_oe','ryf_oe','pin_oe','far_oe']
by=defaultdict(list)
for r in pu: by[(r['p'],r['s'])].append(r)
rows=[]
for (p,s),xs in by.items():
    ys=by.get((p,s+1))
    if ys and len(xs)>=25 and len(ys)>=25:
        rows.append((s,[np.mean([x[c] for x in xs]) for c in C],np.mean([y['v_oe'] for y in ys]),np.mean([y['net_oe'] for y in ys])))
S=np.array([r[0] for r in rows]); X=np.array([r[1] for r in rows]); Y=np.array([r[2] for r in rows]); Y2=np.array([r[3] for r in rows])
def cv(cols,Yt):
    idx=[C.index(c) for c in cols]; pr=np.zeros(len(Yt))
    for s in set(S):
        tr=S!=s; A=np.c_[np.ones(tr.sum()),X[tr][:,idx]]; b=np.linalg.lstsq(A,Yt[tr],rcond=None)[0]
        pr[~tr]=np.c_[np.ones((~tr).sum()),X[~tr][:,idx]]@b
    b=np.linalg.lstsq(np.c_[np.ones(len(Yt)),X[:,idx]],Yt,rcond=None)[0]
    return np.corrcoef(pr,Yt)[0,1],np.round(b[1:],4)
print(sport,'pairs',len(rows))
for tl,Yt in (('next pts OE',Y),('next net OE',Y2)):
    print(' target',tl)
    for cols in (['v_oe'],['net_oe'],['gross_oe'],['pin_oe','far_oe'],['far_oe'],['gross_oe','ryf_oe'],['gross_oe','ret_oe','ryf_oe'],['gross_oe','ryf_oe','i20_oe','tb_oe'],['v_oe','gross_oe'],['net_oe','gross_oe'],['v_oe','net_oe','gross_oe']):
        r,b=cv(cols,Yt); print(f'   {"+".join(cols):36s} r {r:+.3f} b {b}')
