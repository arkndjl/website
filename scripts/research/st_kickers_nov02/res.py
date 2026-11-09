# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Kicker and punter grades, Nov 2 2026 research (scripts/st_kickers.py). Stability: shrinkage k and year-to-year r of every kicker/punter part.  python3 res.py nfl 2012 2025 | cfb 2010 2025"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out") + "/"
os.makedirs(OUT, exist_ok=True)
import sys, json; 
import st_kickers as K
sport=sys.argv[1]; a,b=int(sys.argv[2]),int(sys.argv[3])
if sport=='nfl': pl=K.nfl_plays(range(a,b+1))
else: pl,names,D=K.cfb_plays(range(a,b+1))
S=set(range(a,b+1))
# full-history version of grade(): fit FG on everything
H,P=None,None
import math
fg=pl['fg']; bb=K.logit_fit([K.fg_feats(r) for r in fg],[r['m'] for r in fg]); print('fg b',[round(x,3) for x in bb])
for r in fg:
    z=sum(x*y for x,y in zip(bb,K.fg_feats(r))); r['xm']=1/(1+math.exp(-z)); r['poe']=3*(r['m']-r['xm']); r['raw']=r['m']
from collections import defaultdict
rate=defaultdict(list)
for r in pl['xp']: rate[r['s']].append(r['m'])
for r in pl['xp']: r['poe']=r['m']-K.mean(rate[r['s']])
K.expect(pl['ko'],'v','poe',lambda r:(r['s'],int(r['yl']//5)))
for fld in ('v','gross','net','i20','tb','ret'):
    K.expect(pl['pu'],fld,fld+'_oe',lambda r:(r['s'],int(min(99,r['yl'])//3)))
pin=[r for r in pl['pu'] if r['yl']<=50]; far=[r for r in pl['pu'] if r['yl']>50]
out={}
def show(lab,rows,fld,**kw):
    h=K.hyper(rows,fld,S,**kw); out[lab]=h; print(f'{lab:22s}',h)
show('fg poe (season)',fg,'poe',minn=12); show('fg poe (career k)',fg,'poe',by_career=True,minn=12,hi=2000); show('fg raw',fg,'raw',minn=12)
show('xp',pl['xp'],'poe',minn=15,hi=2000)
pre=[r for r in pl['ko'] if r['s']<2024]; post=[r for r in pl['ko'] if r['s']>=2024]
show('ko all',pl['ko'],'poe',minn=20); 
if pre: show('ko pre-2024',pre,'poe',minn=20)
if post: show('ko 2024+',post,'poe',minn=20)
show('punt pts',pl['pu'],'v_oe',minn=25); show('punt pin',pin,'v_oe',minn=6); show('punt far',far,'v_oe',minn=20)
for x in ('gross','net','i20','tb','ret'): show('punt '+x,pl['pu'],x+'_oe',minn=25)
json.dump(out,open(OUT + f'res_{sport}.json','w'))
