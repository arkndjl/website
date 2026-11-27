import json, math, collections, numpy as np
from fit2 import build, byT, athB, R, on3, score, p4
from calib import oldB, ATH
DE=[('Brendan Sorsby',5e6),('Sam Leavitt',5e6),('Drew Mestemaker',3.6e6),('Darian Mensah',7e6),('Jordan Seaton',3.25e6),('Cam Coleman',3e6),('Jeremiah Smith',5.5e6),('Lincoln Kienholz',2.75e6),('Kenny Minchey',2.75e6),('Hollywood Smothers',1.0e6),('Raleek Brown',1.0e6),('Jackson Cantwell',2e6),('Felix Ojo',775e3)]
ESPN={'QB':(1e6,3e6),'RB':(3e5,8e5),'WR':(4e5,1e6),'TE':(3e5,6e5),'OL':(4e5,1.2e6),'EDGE':(5e5,1.2e6),'DL':(5e5,1e6),'LB':(3e5,7e5),'CB':(4e5,9e5),'S':(3e5,9e5)}
ST={'QB':1,'RB':1,'WR':3,'TE':1,'OL':5,'EDGE':2,'DL':2,'LB':2,'CB':3,'S':2}
byname={r['name']:r for r in R}
def deals(yn):
    e=[]
    for n,v in DE:
        r=byname.get(n)
        if r: e.append(math.log(yn[id(r)]/v))
    e=np.array(e); return len(e), round(float(e.mean()),2), round(float(np.sqrt((e**2).mean())),2)
def starters(yn, verbose=False):
    """P4 starters: top N at the position per team by snaps; median model pay vs ESPN range mid (geometric)"""
    out={}; errs=[]
    for g,n in ST.items():
        v=[]
        for t,ps in byT.items():
            if not ps[0]['p4']: continue
            q=sorted([r for r in ps if r['pos']==g], key=lambda r:-(r['snaps'] or 0))[:n]
            v+=[yn[id(r)] for r in q]
        lo,hi=ESPN[g]; med=float(np.median(v)); mid=math.sqrt(lo*hi)
        out[g]=(round(med/1e3), round(np.quantile(v,.25)/1e3), round(np.quantile(v,.75)/1e3), f'{lo/1e3:.0f}-{hi/1e3:.0f}')
        errs.append(math.log(med/mid))
    if verbose: print(out)
    errs=np.array(errs); return round(float(errs.mean()),2), round(float(np.sqrt((errs**2).mean())),2)
if __name__=='__main__':
    def rep(name,yn):
        s=score(yn,p4); o=on3(yn)
        print(f'{name:28s} csc rmse {s[0]:.2f} bias {s[1]:+.2f} | on3 bias {o["bias"]:+.2f} sd {o["sd"]:.2f} r {o["r"]:.2f} | deals {deals(yn)} | espn starters (bias,rmse) {starters(yn)}')
    rep('old',build(1,0,oldB)); starters(build(1,0,oldB),True)
    for lvl in (1,.88,.8,.735):
        for k,c in ((1,0),(1.25,0),(1.5,0),(1.25,.1),(1,.2)):
            rep(f'ath lvl {lvl} k {k} c {c}',build(k,c,athB,None,lvl))
    print([ (n, byname[n]['y'], byname[n]['nil']) for n,_ in DE if n in byname])
