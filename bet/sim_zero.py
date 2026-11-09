import sys,json,collections
sys.path.insert(0,'/tmp/audit-nov09/fix/bet'); import sim2 as S
import numpy as np
RM,DU,GP,RJ=S.RM,S.DU,S.GP,S.RJ
P=RM.params()
for sport in GP.SPORTS:
    for mk in ('spread','total'):
        m=RJ['sports'][sport]['markets'][mk]
        if not m.get('on'): continue
        d=S.held_slates(sport,mk,m['x']); sl=[np.array(v) for v in d.values()]
        held=m['heldRec']; mu1=RM.expected_live(sport,held); sd=RM.sd_of(held); rho=DU._icc(d)
        allx=np.concatenate(sl); mu_h=allx.mean(); rng=np.random.default_rng(5)
        for lab,mean in (('edge',mu1),('zero',0.0),('-1.5%',-.015),('-3%',-.03),('-5%',-.05)):
            hz=S.HZ[sport]; c=collections.Counter(); med=[];medL=[]
            for s in range(300):
                xs=[];days=[]
                while len(xs)<hz:
                    v=(sl[rng.integers(len(sl))]-mu_h)+mean; xs+=list(v); days.append(list(v))
                _,_,hit=RM.cusum(xs,sd,P['cusum']['k'],P['cusum']['h'])
                _,_,hl=RM.cusum_llr(days,mu1,sd,rho,4.595,P['minN'])
                c['zero']+=hit is not None; c['llr']+=hl is not None; c['either']+=(hit is not None) or (hl is not None)
                if hit: med.append(hit)
                if hl: medL.append(hl)
            print(f"{sport} {mk} mean {lab}: zero-CUSUM (k .25 h 10) stops {c['zero']/300:.3f} (median {int(np.median(med)) if med else None}); edge-CUSUM hL 4.6 stops {c['llr']/300:.3f} (median {int(np.median(medL)) if medL else None}); either {c['either']/300:.3f}")
