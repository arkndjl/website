#!/usr/bin/env python3
"""NFL props: how correlated are the rule's bets in one game, one player, one week (Oct 29 2026)? Held-out growth of
per-prop, player-joint and per-game-capped sizing at a weekly budget. Research only; scripts/nfl_props_paper.py took
the player-joint version (Noah: "100%/wk, player props as one bet"). Run from scripts/: python3 nfl_props_corr_research.py"""
import sys, json, gzip, math, numpy as np
from collections import defaultdict
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import nfl_props_research as R
rows=R.build_rows()
ix={(int(s),int(w),i):k for k,(s,w,i) in enumerate(zip(rows['s'],rows['w'],rows['id']))}
g2={str(r[0]):(int(r[1]),int(r[2])) for r in rows['g2']}; a2={str(r[0]):r[1] for r in rows['a2']}
pos={}
O=json.load(gzip.open(R.OPENS,'rt')); sh=R.shape(rows,'full'); F=json.load(open(__import__('os').path.join(R.ROOT, 'data', 'nfl_props_fit.json'))); c=F['c']
B=100/110
sel=[]
for gid,g in O.items():
    sw=g2.get(gid)
    if not sw: continue
    for a,st,L in g['props']:
        if st not in R.STATS: continue
        gs=a2.get(a); k=ix.get((sw[0],sw[1],gs))
        if k is None: continue
        y=sum(rows['y_'+q][k] for q in R.STATS[st]); mu=sum(rows['full_'+q][k] for q in R.STATS[st])
        if y==L: continue
        p=R.p_over(sh,st,mu,L)
        if p is None or max(p,1-p)<.6: continue
        side='o' if p>=.6 else 'u'
        win=(y>L) if side=='o' else (y<L)
        ch=.5+c*(max(p,1-p)-.5)
        sel.append(dict(s=sw[0],w=sw[1],g=gid,a=a,st=st,side=side,ch=ch,r=B if win else -1.0))
def rho(groups):
    N=sum(len(x) for x in groups); k=len(groups); mu=sum(sum(x) for x in groups)/N
    ssb=sum(len(x)*(np.mean(x)-mu)**2 for x in groups); ssw=sum(sum((q-np.mean(x))**2 for q in x) for x in groups)
    msb,msw=ssb/(k-1),ssw/(N-k); m0=(N-sum(len(x)**2 for x in groups)/N)/(k-1)
    return (msb-msw)/(msb+(m0-1)*msw)
out={}
for name,ss in (('tune',(2024,)),('held',(2025,2026))):
    S=[b for b in sel if b['s'] in ss]
    byg=defaultdict(list); byw=defaultdict(list); byside=defaultdict(list); bypl=defaultdict(list)
    for b in S:
        byg[b['g']].append(b['r']); byw[(b['s'],b['w'])].append(b['r']); byside[(b['g'],b['side'])].append(b['r']); bypl[(b['g'],b['a'])].append(b['r'])
    # same game, different-game-same-week split: pairs correlation
    out[name]={'n':len(S),'perGame':round(np.mean([len(v) for v in byg.values()]),1),'maxGame':max(len(v) for v in byg.values()),
      'rhoGame':round(rho([v for v in byg.values() if len(v)>0]),3),'rhoGameSide':round(rho(list(byside.values())),3),
      'rhoPlayer':round(rho(list(bypl.values())),3),'rhoWeek':round(rho(list(byw.values())),3),
      'underShare':round(np.mean([b['side']=='u' for b in S]),3)}
print(json.dumps(out,indent=0))
# sizing variants on held: house Kelly x TIMING per bet; game scale 1/(1+(n_g-1)rho_g); week budget
rg=out['tune']['rhoGameSide']; rg2=out['tune']['rhoGame']
def kel(ch): return max(0,.5*(ch*B-(1-ch))/B)*100
def run(S, game_rho=None, game_cap=None, week_budget=None, week_rho=.004):
    byw=defaultdict(list)
    for b in S: byw[(b['s'],b['w'])].append(b)
    lg=[]; ex=[]
    for wk,bs in byw.items():
        f=[]
        gcount=defaultdict(int)
        for b in bs: gcount[(b['g'],b['side'])]+=1
        for b in bs:
            x=kel(b['ch'])
            if game_rho is not None: x/= (1+(gcount[(b['g'],b['side'])]-1)*game_rho)
            f.append(x)
        # game cap: scale each game's sum
        if game_cap:
            gs=defaultdict(float)
            for b,x in zip(bs,f): gs[b['g']]+=x
            f=[x*min(1,game_cap/gs[b['g']]) for b,x in zip(bs,f)]
        if week_budget and sum(f)>week_budget: f=[x*week_budget/sum(f) for x in f]
        ex.append(sum(f)); lg.append(math.log(max(1e-9,1+sum(x/100*b['r'] for x,b in zip(f,bs)))))
    return {'logWeek':round(float(np.mean(lg)),4),'worst':round(math.expm1(min(lg)),3),'exp':round(float(np.mean(ex)),1)}
for name,ss in (('tune',(2024,)),('held',(2025,2026))):
    S=[b for b in sel if b['s'] in ss]
    print(name)
    for lab,kw in (('current: 100%/wk budget',dict(week_budget=100)),('50%/wk',dict(week_budget=50)),
                   ('game-side joint (rho %.3f), no budget'%rg,dict(game_rho=rg)),
                   ('game-side joint + 100%%/wk',dict(game_rho=rg,week_budget=100)),
                   ('game cap 5%% + 100%%/wk',dict(game_cap=5,week_budget=100)),
                   ('game cap 3%% + 100%%/wk',dict(game_cap=3,week_budget=100)),
                   ('game cap 5%%, no budget',dict(game_cap=5)),
                   ('game-side joint + game cap 5%%',dict(game_rho=rg,game_cap=5)),
                   ('game-side joint + game cap 5%% + 100%%/wk',dict(game_rho=rg,game_cap=5,week_budget=100))):
        print(' ',lab,run(S,**kw))
