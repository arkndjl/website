import json, math, collections, subprocess, numpy as np
import full as F
from full import rows, byT, BUD, csc_score, on3, deals, starters, K0
d0=json.loads(subprocess.check_output(['git','-C','/home/user/website','show','654423a:static/data/cfb-all.json'])); c0={k:i for i,k in enumerate(d0['cols'])}
oldy={(r[c0['name']],r[c0['team']],r[c0['pos']]):r[c0['ynil']] for r in d0['rows'] if r[c0['ynil']]}
B_FV={'P4':0.018,'G5':0.006,'FCS':0.0}
def build(k=1.1, d=0.05, fvs=1.0, carried='exact'):
    out={}
    for (t,div),ps in byT.items():
        live=[r for r in ps if r['kind']=='live']
        if not live: continue
        tier=live[0]['tier']; B=BUD.get(t) if tier=='P4' and t in BUD else sum(r['y'] for r in live)
        lwl={id(r):(k/K0)*math.log(max(r['y'],500)) for r in live}
        # carried: stale old-regime (k 1.1) value moved onto this run's scale by the live players' median shift
        sh=[lwl[id(r)]-(k/1.1)*math.log(oldy[(r['name'],r['team'],r['pos'])]) for r in live if (r['name'],r['team'],r['pos']) in oldy]
        cst=float(np.median(sh)) if sh else None
        rr=list(live); lw=[lwl[id(r)] for r in live]
        for r in ps:
            if r['kind']=='carried' and cst is not None and r['y']:
                rr.append(r); lw.append((k/1.1)*math.log(max(r['y'],500))+cst)
        if d>0:
            for r in ps:
                if r['kind']!='prov': continue
                same=[x for x in live if x['pos']==r['pos']] or live
                base=float(np.median([lwl[id(x)] for x in same])); mf=float(np.median([x['fv'] for x in same]))
                rr.append(r); lw.append(base+math.log(d)+(k/K0)*fvs*B_FV[tier]*1.375/1.375*(r['fv']-mf))
        lw=np.array(lw); w=np.exp(lw-lw.max()); w/=w.sum()
        for r,x in zip(rr,w): out[id(r)]=B*x
    return out
def rep(name,yn):
    p=[yn.get(id(r),0) for r in rows if r['kind']=='prov' and r['p4']]; l=[yn[id(r)] for r in rows if r['kind']=='live' and r['p4']]; cr=[yn.get(id(r),0) for r in rows if r['kind']=='carried' and r['p4']]
    print(f'{name:16s} cscA4 {csc_score(yn,"A4")} cscN {csc_score(yn,"N")} on3 {on3(yn)} deals {deals(yn)} espn {starters(yn)} top {max(yn.values())/1e6:.1f}M | P4/team: live {sum(l)/68e6:.1f} carried {sum(cr)/68e6:.1f} prov {sum(p)/68e6:.1f} (med {np.median(p)/1e3:.0f}K, p90 {np.quantile(p,.9)/1e3:.0f}K)')
if __name__=='__main__':
    for k in (1.1,1.25,1.375):
        for dd in (0,.03,.05,.075,.1,.15):
            rep(f'k{k} d{dd}',build(k,dd))
    yn=build(1.1,.05); F.csc_score(yn,'A4',True)
