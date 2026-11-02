"""Kicker and punter grades, Nov 2 2026 research (scripts/st_kickers.py). Punter grade weights: next season points over expected a punt on shrunk points + shrunk gross yards.  python3 pfit.py nfl|cfb (after res.py)"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out") + "/"
os.makedirs(OUT, exist_ok=True)
import sys, numpy as np, json; 
import st_kickers as K
from collections import defaultdict
sport=sys.argv[1]
res=json.load(open(OUT + f'res_{sport}.json'))
kv=res['punt pts']['k']; kg=res['punt gross']['k']; kpin=res['punt pin']['k']; kfar=res['punt far']['k']
pl = K.nfl_plays(range(2012,2026)) if sport=='nfl' else K.cfb_plays(range(2010,2026))[0]
pu=pl['pu']
for fld in ('v','gross'): K.expect(pu,fld,fld+'_oe',lambda r:(r['s'],int(min(99,r['yl'])//3)))
A=defaultdict(lambda: defaultdict(float))
for r in pu:
    a=A[(r['p'],r['s'])]; a['n']+=1; a['v']+=r['v_oe']; a['g']+=r['gross_oe']; sd='pin' if r['yl']<=50 else 'far'; a[sd]+=r['v_oe']; a[sd+'n']+=1
X=[];Y=[];W=[];S=[]
for (p,s),a in A.items():
    b=A.get((p,s+1))
    if b and a['n']>=5 and b['n']>=10:
        V=a['pin']/(a['pinn']+kpin)+a['far']/(a['farn']+kfar)   # shrunk value a punt (parts)
        V=(a['pin']/(a['pinn']+kpin)*a['pinn']+a['far']/(a['farn']+kfar)*a['farn'])/a['n']
        G=a['g']/(a['n']+kg)
        X.append([V,G]); Y.append(b['v']/b['n']); W.append(b['n']); S.append(s)
X=np.array(X);Y=np.array(Y);W=np.array(W);S=np.array(S)
def fit(idx,tr):
    A_=X[tr][:,idx]*np.sqrt(W[tr])[:,None]; return np.linalg.lstsq(A_,Y[tr]*np.sqrt(W[tr]),rcond=None)[0]
for idx,lab in (([0],'V'),([1],'G'),([0,1],'V+G')):
    pr=np.zeros(len(Y))
    for s in set(S):
        tr=S!=s; pr[~tr]=X[~tr][:,idx]@fit(idx,tr)
    mse=np.average((Y-pr)**2,weights=W); mse0=np.average(Y**2,weights=W)
    print(sport,lab,'LOSO weighted r',round(np.corrcoef(pr,Y)[0,1],3),'MSE gain %',round(100*(1-mse/mse0),2),'coefs (all)',np.round(fit(idx,np.ones(len(Y),bool)),4), 'n',len(Y))
