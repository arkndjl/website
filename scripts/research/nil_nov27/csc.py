import json, math, numpy as np
from statistics import NormalDist
T=json.load(open('../football/dl/csc_rs_football_tables.json'))
num=lambda s: None if s=='-' else float(s.replace('$','').replace(',',''))
import re
CSC={}
for k,v in T.items():
    pos=v[1]; i=[j for j,s in enumerate(v) if s.startswith('With') ]
    blocks=[]
    for j,s in enumerate(v):
        m=re.match(r'(With|Without) \$0 \(n=([\d,]+)\)',s)
        if m: blocks.append((m.group(1),int(m.group(2).replace(',','')),[num(x) for x in v[j+1:j+6]]))
    CSC[pos]={'A4':{'all':blocks[0],'paid':blocks[1]},'N':{'all':blocks[2],'paid':blocks[3]}}
Q=[.9,.75,.5,.25,.1]; nd=NormalDist()
def fit(pos,tier):
    """lognormal on the paid cohort (quantile regression of log $ on z), plus paid share"""
    a=CSC[pos][tier]; n_all=a['all'][1]; n_paid=a['paid'][1]
    pts=[(nd.inv_cdf(q),math.log(v)) for q,v in zip(Q,a['paid'][2]) if v]
    if len(pts)<3: return dict(n=n_all,paid=n_paid,mu=math.log(pts[0][1]) if pts else 0,sd=1.0,mean=(pts[0][1]*1.6 if pts else 0),resid=0)
    z=np.array([p[0] for p in pts]); y=np.array([p[1] for p in pts])
    s,m=np.polyfit(z,y,1)
    return dict(n=n_all,paid=n_paid,mu=m,sd=s,mean=math.exp(m+s*s/2), resid=float(np.abs(y-(m+s*z)).max()))
if __name__=='__main__':
    tot={'A4':0,'N':0}; npl={'A4':0,'N':0}
    for pos in CSC:
        for t in ('A4','N'):
            f=fit(pos,t); tot[t]+=f['mean']*f['paid']; npl[t]+=f['n']
            print(pos,t,f['n'],f['paid'],'median',round(math.exp(f['mu'])),'sd',round(f['sd'],2),'mean',round(f['mean']),'maxresid',round(f['resid'],2))
    print({k:round(v/1e6) for k,v in tot.items()}, npl, 'A4 per school', tot['A4']/68/1e6)
