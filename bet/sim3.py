"""final operating characteristics of the changed monitor (real RM.decide / RM.drift): whole held-out slates resampled
with their own residuals. usage: sim3.py sims out.json [--segs]"""
import sys,json,collections
sys.path.insert(0,'/tmp/audit-nov09/fix/bet'); import sim2 as S
import numpy as np
RM,DU,GP,RJ=S.RM,S.DU,S.GP,S.RJ
P=RM.params()
def run(sl,mu1,sd,rho,mean,horizon,sims,rng):
    allx=np.concatenate(sl); mu_h=allx.mean(); c=collections.Counter(); hits=[]
    for s in range(sims):
        bets=[];d=0
        while len(bets)<horizon:
            v=sl[rng.integers(len(sl))]
            bets+=[{'kick':S.KS[d],'clvRet':float(xi)} for xi in (v-mu_h)+mean]; d+=1
        dc=RM.decide(bets,sd,P,mu1,rho); dr=RM.drift(bets,mu1,sd,rho,P)
        z=dc.get('hitAt'); e=(dc.get('edge') or {}).get('hitAt'); pz=dr['at'][1] if dr['state']=='paused' else None
        c['zero']+=z is not None; c['edge']+=e is not None; c['paused']+=pz is not None; c['confirmed']+=dr['state']=='confirmed'
        a=[x for x in (z,e,pz) if x]; c['stop']+=bool(a)
        if a: hits.append(min(a))
    return {**{k:round(c[k]/sims,3) for k in ('zero','edge','paused','confirmed','stop')},'median':int(np.median(hits)) if hits else None}
sims=int(sys.argv[1]); rules=[]
for sport in GP.SPORTS:
    Sx=RJ['sports'][sport]
    for mk in ('spread','total'):
        m=Sx['markets'][mk]
        if m.get('on'): rules.append((sport,mk,m['x'],None,None,m['heldRec']))
    if '--segs' in sys.argv:
        for z in Sx.get('segments') or []: rules.append((sport,z['mk'],z['x'],z['fam'],z['val'],z['held']))
res={}
for sport,mk,x,fam,val,held in rules:
    d=S.held_slates(sport,mk,x,fam,val); sl=[np.array(v) for v in d.values()]
    mu1=RM.expected_live(sport,held); sd=RM.sd_of(held); rho=RM.rho_for(sport,mk,{**held,'clvIcc':held.get('clvIcc',DU._icc(d))})
    name=f"{sport}:{mk}"+(f" | {fam}: {val}" if fam else '')
    if not mu1 or mu1<=0: print(name,'no drift test (mu1',mu1,')'); continue
    rng=np.random.default_rng(5); row={'mu1':round(mu1,4),'sd':round(sd,4),'rho':round(rho,3),'bets':S.HZ[sport],'perSlate':round(sum(map(len,sl))/len(sl),1)}
    for lab,mean in (('edge',mu1),('half',mu1/2),('zero',0.0),('minus3',-.03)):
        row[lab]=run(sl,mu1,sd,rho,mean,S.HZ[sport],sims,rng)
        print(name,{k:v for k,v in row.items() if k not in('edge','half','zero','minus3')} if lab=='edge' else '',lab,row[lab],flush=True)
    res[name]=row
json.dump(res,open(sys.argv[2],'w'),indent=1)
