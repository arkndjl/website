#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import gzip,json,sys,math,numpy as np
from collections import defaultdict
sys.path.insert(0, 'scripts')
import soccer_games as G
wf=json.load(gzip.open('scripts/data/games_wf/soccer.json.gz','rt'))
B5={'eng.1','esp.1','ita.1','ger.1','fra.1'}
tot=defaultdict(lambda:[0.,0.])
for o in wf:
    if o['lg'] in B5: t=tot[(o['lg'],o['S'])]; t[0]+=sum(o['l']); t[1]+=o['hs']+o['as']
def lev(lg,S,k,hl=None):
    ss=[s for (l,s) in tot if l==lg and s<S]
    if k: ss=ss[-k:]
    if not ss: return 1.0
    w=[(0.5**((S-1-s)/hl) if hl else 1) for s in ss]
    return sum(wi*tot[(lg,s)][1] for wi,s in zip(w,ss))/sum(wi*tot[(lg,s)][0] for wi,s in zip(w,ss))
TT=np.add.outer(np.arange(G.GMAX),np.arange(G.GMAX))
cache={}
def o25(lh,la):
    k=(round(lh,3),round(la,3))
    if k not in cache: cache[k]=float(G.score_matrix(lh,la,-.04)[TT>2.5].sum())
    return cache[k]
res={}
for name,k,hl in (('cum',None,None),('last1',1,None),('last2',2,None),('last3',3,None),('hl2',None,2),('hl4',None,4)):
    out={}
    for lo,hi in ((2015,2022),(2023,2027)):
        L=[];D=[];days=[]
        for o in wf:
            if o['lg'] not in B5 or not lo<=o['S']<=hi: continue
            f=lev(o['lg'],o['S'],k,hl); p=o25(o['l'][0]*f,o['l'][1]*f); y=o['hs']+o['as']>2
            L.append(-(math.log(p) if y else math.log(1-p))); days.append(o['day'])
        out[(lo,hi)]=(np.array(L),days)
    res[name]=out
for name in res:
    s=[]
    for sp in res[name]:
        a,days=res[name][sp]; b,_=res['cum'][sp]
        dd=defaultdict(float)
        for x,dy in zip(a-b,days): dd[dy]+=x
        v=np.array(list(dd.values())); t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v)))*1
        s.append(f'{sp} LL {a.mean():.5f} d {a.mean()-b.mean():+.5f} t {t:+.2f}')
    print(name,' | '.join(s))
