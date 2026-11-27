import json,math,collections,numpy as np
import full as F, prem2 as P2
from full import rows,byT,csc_score,on3,deals,starters,CSC,target
NB=json.load(open('/home/user/website/data/nil_budgets.json'))['cfb']['teams']
def lam(l):
    out={}
    for (t,div),ps in byT.items():
        f=1.0
        if t in NB and div=='FBS': lo,hi=NB[t]; f=(lo+l*(hi-lo))/((lo+hi)/2)
        for r in ps:
            if r['y']: out[id(r)]=r['y']*f
    return out
for l in (0,.5,1,1.5): P2.rep(f'budget at range pos {l}',lam(l))
# team residual vs On3: which teams pay over the model
tr=collections.defaultdict(list)
for r in F.V: tr[r['team']].append(math.log(r['nil']/r['y']))
T=[(t,np.mean(v),len(v)) for t,v in tr.items() if len(v)>=4 and t in NB]
w=[ (NB[t][1]-NB[t][0])/((NB[t][0]+NB[t][1])/2) for t,_,_ in T]; m=[x for _,x,_ in T]; b=[math.log((NB[t][0]+NB[t][1])/2) for t,_,_ in T]
print('teams',len(T),'sd of team mean On3 residual',np.std(m).round(2),'corr with log budget',np.corrcoef(m,b)[0,1].round(2),'with range width',np.corrcoef(m,w)[0,1].round(2))
print(sorted([(t,round(x,2),n) for t,x,n in T],key=lambda z:z[1])[:5],sorted([(t,round(x,2),n) for t,x,n in T],key=lambda z:-z[1])[:5])
# K/P coverage: starters (board rows, no src) at kS x team median live pay, backups at .05 x
d=json.load(open('/home/user/website/static/data/cfb-all.json')); c={k:i for i,k in enumerate(d['cols'])}
kp=[dict(zip(d['cols'],r)) for r in d['rows'] if r[c['pos']] in('K','P')]
med={k:np.median([r['y'] for r in ps if r['kind']=='live']) for k,ps in byT.items() if any(r['kind']=='live' for r in ps)}
p4t={r['team'] for r in rows if r['p4']}
print('P4 team median live yNIL: median',np.median([v for (t,dv),v in med.items() if t in p4t]))
def kscore(kS,kB=.05,verbose=False):
    e=[]
    for pos,g in (('Kicker','K'),('Punter','P')):
        for tier in ('A4','N'):
            xs=sorted([ (kS if not r['src'] else kB)*med.get((r['team'],r['div']),0) for r in kp if r['pos']==g and ((r['team'] in p4t)==(tier=='A4'))],reverse=True); m=len(xs)
            n,tot,qs,_,_=target(pos,tier)
            for q in sorted(set(qs)):
                u=(1-q)*n/m
                if u>=.98: continue
                mod=xs[min(m-1,int(u*m))]; e.append(math.log((mod+1e4)/(tot(q)+1e4)))
                if verbose: print(f'   {pos} {tier} q{q:.2f} model {mod:,.0f} target {tot(q):,.0f} (board n {m}, CSC n {n})')
    e=np.array(e); return round(float(np.sqrt((e**2).mean())),3),round(float(e.mean()),3)
for kS in (0,.1,.2,.3,.4,.6,1): print('K/P starter share',kS,kscore(kS))
kscore(.3,verbose=True)
print(collections.Counter((r['pos'],bool(r['src']),r['team'] in p4t) for r in kp), 'FV starters',np.quantile([r['fv'] for r in kp if not r['src']],[.1,.5,.9]),'FV backups',np.quantile([r['fv'] for r in kp if r['src'] and r['fv']],[.1,.5,.9]) if any(r['src'] and r['fv'] for r in kp) else None)
def kscore2(kS,g,kB=.05,sub=None):
    e=[]
    for pos,gp in (('Kicker','K'),('Punter','P')):
        if sub and pos!=sub: continue
        for tier in ('A4','N'):
            xs=sorted([ (kS*math.exp(g*((r['fv'] or 37)-37)) if not r['src'] else kB)*med.get((r['team'],r['div']),0) for r in kp if r['pos']==gp and ((r['team'] in p4t)==(tier=='A4'))],reverse=True); m=len(xs)
            n,tot,qs,_,_=target(pos,tier)
            for q in sorted(set(qs)):
                u=(1-q)*n/m
                if u>=.98: continue
                e.append(math.log((xs[min(m-1,int(u*m))]+1e4)/(tot(q)+1e4)))
    e=np.array(e); return round(float(np.sqrt((e**2).mean())),3),round(float(e.mean()),3)
best=min(((kscore2(k,g,kb),k,g,kb) for k in (.08,.1,.12,.15,.2) for g in (0,.03,.06,.09,.12) for kb in (.01,.02,.05)),key=lambda z:z[0][0])
print('best',best,'blank',kscore2(0,0,0))
k,g,kb=best[1:]
print('fit on kickers -> punters',min(((kscore2(a,b,kb,'Kicker'),a,b) for a in (.08,.1,.12,.15,.2) for b in (0,.03,.06,.09,.12)),key=lambda z:z[0][0]))
kk=min(((kscore2(a,b,kb,'Kicker'),a,b) for a in (.08,.1,.12,.15,.2) for b in (0,.03,.06,.09,.12)),key=lambda z:z[0][0]); print(' punters at kicker fit',kscore2(kk[1],kk[2],kb,'Punter'),'punters blank',kscore2(0,0,0,'Punter'))
pp=min(((kscore2(a,b,kb,'Punter'),a,b) for a in (.08,.1,.12,.15,.2) for b in (0,.03,.06,.09,.12)),key=lambda z:z[0][0]); print(' kickers at punter fit',pp,kscore2(pp[1],pp[2],kb,'Kicker'),'kickers blank',kscore2(0,0,0,'Kicker'))
