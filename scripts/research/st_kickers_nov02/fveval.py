# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Kicker and punter grades, Nov 2 2026 research (scripts/st_kickers.py). CFB K/P FV driver test, scoring: logistic, held out by class, log loss vs the board score; forward 2016-20.  python3 fveval.py y|y2"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out") + "/"
os.makedirs(OUT, exist_ok=True)
import json, numpy as np
from collections import defaultdict
SP=OUT
rows=json.load(open(SP+'fvrows.json'))
def z_by_season(R,f):
    by=defaultdict(list)
    for r in R:
        if r.get(f) is not None: by[r['fin']].append(r[f])
    for r in R:
        v=by[r['fin']]; m=np.mean(v); s=np.std(v) or 1
        r['z_'+f]=0 if r.get(f) is None else (r[f]-m)/s
def logit(X,y,lam=1.0):
    X=np.c_[np.ones(len(X)),X]; b=np.zeros(X.shape[1])
    for _ in range(50):
        p=1/(1+np.exp(-X@b)); W=p*(1-p)
        R=lam*np.eye(len(b)); R[0,0]=0
        b+=np.linalg.solve(X.T@(X*W[:,None])+R, X.T@(y-p)-R@b)
    return b
def auc(s,y):
    pos=s[y==1]; neg=s[y==0]
    return np.mean([(p>n)+.5*(p==n) for p in pos for n in neg]) if len(pos) and len(neg) else np.nan
TGT='y'
def ev(R,feats,lab,target=None):
    target=target or TGT
    X=np.array([[r[f] for f in feats] for r in R]); X=(X-X.mean(0))/(X.std(0)+1e-9)
    y=np.array([1.0 if r[target]>0 else 0.0 for r in R]); S=np.array([r['fin'] for r in R])
    pr=np.zeros(len(y)); ll=defaultdict(float)
    for s in sorted(set(S)):
        tr=S!=s; b=logit(X[tr],y[tr]); p=1/(1+np.exp(-(np.c_[np.ones((~tr).sum()),X[~tr]]@b)))
        pr[~tr]=p
    L=-(y*np.log(pr)+(1-y)*np.log(1-pr))
    per={s:L[S==s].sum() for s in set(S)}
    return pr,L,per,auc(pr,y)
import sys
TGT=sys.argv[1] if len(sys.argv)>1 else 'y'
for kind in ('k','p'):
    R=[r for r in rows if r['kind']==kind]
    if kind=='k':
        for f in ('old_rate','old_long','old_xp'): z_by_season(R,f)
        for r in R: r['old']=r['z_old_rate']+.25*r['z_old_long']+.15*r['z_old_xp']
        cands={'old score':['old'],'new Adj (season total)':['new'],'new rate':['new_rate'],'new career total':['new_c'],'FG shrunk rate':['fgr'],'FG career':['fgc'],
               'KO season':['kor'],'KO career':['koc'],'long make career':['lngc'],'FGA career (volume)':['fgac'],'old + new':['old','new'],'new + long':['new','old_long'],
               'new career + long career':['new_c','lngc']}
    else:
        for f in ('old_rate','old_ypp','old_i20'): z_by_season(R,f)
        for r in R: r['old']=.6*r['z_old_rate']+.3*r['z_old_ypp']+.1*r['z_old_i20']
        cands={'old score':['old'],'new pts (season)':['new'],'new pts career':['new_c'],'gross OE (leg) season':['goe'],'gross OE career':['goec'],'net OE season':['noe'],
               'net OE career':['noec'],'pts + gross season':['new','goe'],'pts + gross career':['new_c','goec'],'old + gross career':['old','goec'],'old + net OE career':['old','noec'],'net OE career + gross career':['noec','goec'],'gross yds avg':['old_ypp']}
    base=None
    print(f'== {kind}: {len(R)} players, {sum(r["y"]>0 for r in R)} with an NFL season as primary {kind.upper()} within 5 yrs')
    res={}
    for lab,fs in cands.items():
        pr,L,per,a=ev(R,fs,lab); res[lab]=(L,per)
        if lab=='old score': base=(L,per)
        d=[base[1][s]-per[s] for s in per]; t=np.mean(d)/(np.std(d,ddof=1)/np.sqrt(len(d))+1e-12)
        print(f'  {lab:28s} AUC {a:.3f}  logloss {L.mean():.4f}  vs old: better in {sum(x>0 for x in d)}/{len(d)} classes, t {t:+.2f}')

    # forward: fit on classes <= 2015, test 2016-2020
    if kind=='p':
        for lab in ('old score','net OE career','old + net OE career'):
            fs=cands[lab]; X=np.array([[r[f] for f in fs] for r in R]); X=(X-X.mean(0))/(X.std(0)+1e-9)
            y=np.array([1.0 if r[TGT]>0 else 0.0 for r in R]); S=np.array([r['fin'] for r in R]); tr=S<=2015
            b=logit(X[tr],y[tr]); pr=1/(1+np.exp(-(np.c_[np.ones((~tr).sum()),X[~tr]]@b)))
            L=-(y[~tr]*np.log(pr)+(1-y[~tr])*np.log(1-pr)); print(f'  forward 2016-20 {lab:22s} logloss {L.mean():.4f} AUC {auc(pr,y[~tr]):.3f}')
