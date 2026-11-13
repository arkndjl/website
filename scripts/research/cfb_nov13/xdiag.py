# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
import json,numpy as np,sys
D=json.load(open(sys.argv[1])); F=D['feats']; R=[r for r in D['rows'] if not (r['S']==2026 and r['w']>=11) and r['S']>=2018]
print(len(R),F)
X=np.array([r['x'] for r in R]); res=np.array([r['res'] for r in R],float); m=np.array([r['m'] for r in R]); m0=np.array([r['m0'] for r in R])
L=np.array([r['L'] if r['L'] is not None else np.nan for r in R]); w=np.array([r['w'] for r in R]); S=np.array([r['S'] for r in R])
bk={'wk1':w==1,'wk2-3':(w>=2)&(w<=3),'wk4-6':(w>=4)&(w<=6),'wk7-10':(w>=7)&(w<=10),'wk11-14':(w>=11)&(w<=14),'post':w>=15}
print('feature: slope of (res-m0) on x / slope of (L-m0) on x, with t, by week bucket (m0 = model before stack/early)')
for j,f in enumerate(F):
    line=f'{f:5s}'
    for b,k in bk.items():
        x=X[k,j]; 
        if x.std()<1e-9: line+=f' | {b}: -'; continue
        def sl(y,x):
            ok=~np.isnan(y); x=x[ok]; y=y[ok]; x=x-x.mean(); y=y-y.mean(); b=(x*y).sum()/(x*x).sum(); e=y-b*x; se=np.sqrt((e*e).sum()/(len(x)-2)/(x*x).sum()); return b,b/se
        b1,t1=sl(res[k]-m0[k],x); b2,t2=sl(L[k]-m0[k],x)
        line+=f' | {b}: {b1:+.2f}({t1:+.1f}) / {b2:+.2f}({t2:+.1f})'
    print(line)
