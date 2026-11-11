#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import gzip,json,sys,math,numpy as np
sys.path.insert(0, 'scripts')
import soccer_games as G
P=json.load(open('data/soccer_games_fit.json'))
rho=P.get('rho',P.get('params',{}).get('rho',-.04)) if isinstance(P,dict) else -.04
print('rho',rho)
wf=json.load(gzip.open('scripts/data/games_wf/soccer.json.gz','rt'))
H={r['id']:r for r in json.load(gzip.open('scripts/soccer_games_hist.json.gz','rt'))}
B5={'eng.1','esp.1','ita.1','ger.1','fra.1'}
tot=np.add.outer(np.arange(G.GMAX),np.arange(G.GMAX))
def nv(pr):
    q=np.array([1/pr[0],1/pr[1]]);return q/q.sum()
rows=[]
for o in wf:
    if o['lg'] not in B5: continue
    h=H.get(o['id'])
    if not h or 'ouo' not in h or 'ouc' not in h: continue
    f=G.level(o['lg'],o['S'])
    M=G.score_matrix(o['l'][0]*f,o['l'][1]*f,rho); p=float(M[tot>2.5].sum())
    po,pc=nv(h['ouo']),nv(h['ouc'])
    rows.append((o['S'],o['day'],p,o['o25'],po[0],pc[0],h['ouo'],o['hs']+o['as']>2))
print(len(rows))
for lo,hi in ((2013,2022),(2023,2027)):
    R=[r for r in rows if lo<=r[0]<=hi]
    p=np.array([r[2] for r in R]);p0=np.array([r[3] for r in R]);po=np.array([r[4] for r in R]);pc=np.array([r[5] for r in R]);y=np.array([r[7] for r in R])
    ll=lambda q:-(y*np.log(q)+(1-y)*np.log(1-q)).mean()
    print(lo,hi,len(R),'mean model',p.mean().round(3),'raw',p0.mean().round(3),'open',po.mean().round(3),'act',y.mean().round(3),'LL model',round(ll(p),4),'raw',round(ll(p0),4),'open',round(ll(po),4),'close',round(ll(pc),4))
    for cut in (.02,.04,.06,.08,.10):
        ev=[]
        for r in R:
            e_o=r[2]-r[4]; e_u=(1-r[2])-(1-r[4])
            if e_o>cut: ev.append(r[5]*r[6][0]-1)
            elif e_u>cut: ev.append((1-r[5])*r[6][1]-1)
        ev=np.array(ev)
        if len(ev)>2: print('  cut',cut,'n',len(ev),'CLV',round(ev.mean()*100,2),'t',round(ev.mean()/(ev.std()/math.sqrt(len(ev))),2))
