import sys,json,collections
sys.path.insert(0,'/tmp/audit-nov09/fix/bet'); import sim2 as S
import numpy as np
RM,DU,GP,RJ=S.RM,S.DU,S.GP,S.RJ
P=RM.params()
def zc(days,sd,rho,k,h,minN):
    Sx=0;n=0
    for v in days:
        n+=len(v); Sx=max(0.0,Sx+sum(-x/sd-k for x in v)/(1+(len(v)-1)*rho))
        if Sx>=h and n>=minN: return n
    return None
for sport in GP.SPORTS:
    for mk in ('spread','total'):
        m=RJ['sports'][sport]['markets'][mk]
        if not m.get('on'): continue
        d=S.held_slates(sport,mk,m['x']); sl=[np.array(v) for v in d.values()]
        held=m['heldRec']; mu1=RM.expected_live(sport,held); sd=RM.sd_of(held); rho=DU._icc(d)
        allx=np.concatenate(sl); mu_h=allx.mean(); rng=np.random.default_rng(5)
        sm=np.array([v.mean()-mu_h for v in sl]); print(sport,mk,'slates',len(sl),'slate-mean resid quantiles /sd',np.round(np.quantile(sm,[.01,.05,.5,.95,.99])/sd,2),'kurt of bets',round(float(((allx-mu_h)**4).mean()/allx.var()**2),1))
        for lab,mean in (('edge',mu1),('zero',0.0),('-1.5%',-.015),('-3%',-.03),('-5%',-.05)):
            hz=S.HZ[sport]; c=collections.Counter(); med=[]
            for s in range(300):
                days=[];n=0
                while n<hz:
                    v=(sl[rng.integers(len(sl))]-mu_h)+mean; n+=len(v); days.append(list(v))
                hit=zc(days,sd,rho,.25,10,50); c['z']+=hit is not None
                if hit: med.append(hit)
            print(f"  mean {lab}: deflated zero-CUSUM stops {c['z']/300:.3f} (median {int(np.median(med)) if med else None})")
