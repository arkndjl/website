import json, math, collections, re, numpy as np
from csc import CSC, Q
from calib2 import target
W='/home/user/website/'
d=json.load(open(W+'static/data/cfb-all.json')); c={k:i for i,k in enumerate(d['cols'])}
on={x['slug']:x for x in json.load(open('on3_cfb.json'))}
BUD={t:(lo+hi)/2*1e6 for t,(lo,hi) in json.load(open(W+'data/nil_budgets.json'))['cfb']['teams'].items()}
P4C={'SEC','Big Ten','Big 12','ACC'}
POS={'QB':'Quarterback','RB':'Running Back','WR':'Wide Receiver','TE':'Tight End','OL':'Offensive Lineman','EDGE':'Defensive Lineman','DL':'Defensive Lineman','LB':'Linebacker','CB':'Defensive Back','S':'Defensive Back','K':'Kicker','P':'Punter'}
rows=[]
for r in d['rows']:
    g=lambda k:r[c[k]]
    if g('fv') is None or not g('team'): continue
    kind='prov' if g('src')=='espn' else 'carried' if g('carried') else 'live' if g('ynil') else 'other'
    o=on.get(g('on3l').rstrip('/').split('/')[-1]) if g('on3l') else None
    rows.append(dict(name=g('name'),pos=g('pos'),team=g('team'),div=g('div'),fv=g('fv'),y=g('ynil'),x=g('xnil'),snaps=g('snaps') or 0,kind=kind,cls=g('cls'),
        p4=(g('conf') in P4C or g('team')=='Notre Dame') and g('div')=='FBS', nil=(o or {}).get('nil') if kind=='live' else None))
# conf None split groups: p4 by team membership
p4t={r['team'] for r in rows if r['p4']}
for r in rows: r['p4']=r['team'] in p4t and r['div']=='FBS'; r['tier']='P4' if r['p4'] else 'G5' if r['div']=='FBS' else 'FCS'
byT=collections.defaultdict(list)
for r in rows: byT[(r['team'],r['div'])].append(r)
K0=1.375
# pooled regression of live log-weight on team FE + pos + fv, per tier
def fit_b(tier):
    L=[r for r in rows if r['kind']=='live' and r['tier']==tier]
    teams=sorted({r['team'] for r in L}); poss=sorted({r['pos'] for r in L})
    X=np.zeros((len(L),len(teams)+len(poss)-1+1)); y=np.zeros(len(L))
    for i,r in enumerate(L):
        X[i,teams.index(r['team'])]=1
        j=poss.index(r['pos'])
        if j: X[i,len(teams)+j-1]=1
        X[i,-1]=r['fv']-20; y[i]=math.log(max(r['y'],500))
    b=np.linalg.lstsq(X,y,rcond=None)[0]
    return {'team':dict(zip(teams,b[:len(teams)])),'pos':{p:(b[len(teams)+j-1] if j else 0.0) for j,p in enumerate(poss)},'fv':b[-1],'sd':float(np.std(y-X@b))}
FIT={t:fit_b(t) for t in ('P4','G5','FCS')}
def build(k=K0, d=0.0, dc=None, fvs=1.0):
    """live: exact reweight; carried (dc) and provisional (d): the live fit at his team, position and FV x discount"""
    dc=d if dc is None else dc; out={}
    for (t,div),ps in byT.items():
        live=[r for r in ps if r['kind']=='live']
        if not live: continue
        tier=live[0]['tier']; F=FIT[tier]; B=BUD.get(t) if tier=='P4' and t in BUD else sum(r['y'] for r in live)
        lw=[]; rr=[]
        for r in ps:
            if r['kind']=='live': lw.append((k/K0)*math.log(max(r['y'],500))); rr.append(r)
            elif r['kind'] in('prov','carried'):
                dd=d if r['kind']=='prov' else dc
                if dd<=0: continue
                base=F['team'].get(t,np.mean(list(F['team'].values())))+F['pos'].get(r['pos'],min(F['pos'].values()))+fvs*F['fv']*(r['fv']-20)
                lw.append((k/K0)*base+math.log(dd)); rr.append(r)
        lw=np.array(lw); w=np.exp(lw-lw.max()); w/=w.sum()
        for r,x in zip(rr,w): out[id(r)]=B*x
    return out
def csc_score(yn, tier, verbose=False):
    A=[r for r in rows if (r['p4'] if tier=='A4' else not r['p4']) and r['kind']!='other']
    byp=collections.defaultdict(list)
    for r in A: byp[POS.get(r['pos'])].append(yn.get(id(r),0.0))
    e=[]
    for pos in CSC:
        xs=sorted(byp.get(pos,[]),reverse=True); m=len(xs)
        if m<60 or pos in('Kicker','Punter'): continue
        n,tot,qs,_,_=target(pos,tier)
        for q in sorted(set(qs)|{.5,.25}):
            u=(1-q)*n/m
            if u>=0.98: continue
            mod=xs[min(m-1,int(u*m))]; t=tot(q)
            e.append((pos,q,math.log((mod+1e4)/(t+1e4))))
            if verbose: print(f'{pos:18s} q{q:.3f} model {mod:>10,.0f} target {t:>10,.0f} {e[-1][2]:+.2f}')
    a=np.array([x[2] for x in e]); return round(float(np.sqrt((a**2).mean())),3), round(float(a.mean()),3)
V=[r for r in rows if r['nil'] and r['div']=='FBS']
def on3(yn):
    e=np.array([math.log(max(yn[id(r)],1e3)/r['nil']) for r in V]); rr=np.corrcoef([math.log(max(yn[id(r)],1e3)) for r in V],[math.log(r['nil']) for r in V])[0,1]
    return dict(bias=round(float(e.mean()),2),rmse=round(float(np.sqrt((e**2).mean())),3),r=round(float(rr),3),max=round(float(e.max()),2))
DE=[('Brendan Sorsby',5e6),('Sam Leavitt',5e6),('Drew Mestemaker',3.6e6),('Darian Mensah',7e6),('Jordan Seaton',3.25e6),('Cam Coleman',3e6),('Jeremiah Smith',5.5e6),('Lincoln Kienholz',2.75e6),('Kenny Minchey',2.75e6),('Hollywood Smothers',1.0e6),('Raleek Brown',1.0e6),('Jackson Cantwell',2e6),('Felix Ojo',775e3),('Julian Sayin',2.0e6)]
bn={r['name']:r for r in rows if r['kind']=='live' and r['div']=='FBS'}
def deals(yn):
    e=np.array([math.log(yn[id(bn[n])]/v) for n,v in DE if n in bn and id(bn[n]) in yn]); return len(e), round(float(e.mean()),2), round(float(np.sqrt((e**2).mean())),2)
ESPN={'QB':(1e6,3e6),'RB':(3e5,8e5),'WR':(4e5,1e6),'TE':(3e5,6e5),'OL':(4e5,1.2e6),'EDGE':(5e5,1.2e6),'DL':(5e5,1e6),'LB':(3e5,7e5),'CB':(4e5,9e5),'S':(3e5,9e5)}
ST={'QB':1,'RB':1,'WR':3,'TE':1,'OL':5,'EDGE':2,'DL':2,'LB':2,'CB':3,'S':2}
def starters(yn):
    errs=[]
    for g,n in ST.items():
        v=[]
        for (t,div),ps in byT.items():
            if not ps[0]['p4']: continue
            v+=[yn[id(r)] for r in sorted([r for r in ps if r['pos']==g and id(r) in yn], key=lambda r:-r['snaps'])[:n]]
        lo,hi=ESPN[g]; errs.append(math.log(np.median(v)/math.sqrt(lo*hi)))
    errs=np.array(errs); return round(float(errs.mean()),2), round(float(np.sqrt((errs**2).mean())),2)
def rep(name,yn):
    top=max(yn.values()); p=[yn.get(id(r),0) for r in rows if r['kind']=='prov' and r['p4']]
    print(f'{name:22s} cscA4 {csc_score(yn,"A4")} cscN {csc_score(yn,"N")} on3 {on3(yn)} deals {deals(yn)} espn {starters(yn)} top {top/1e6:.1f}M provP4 med {np.median(p)/1e3:.0f}K share {sum(p)/1e6/68:.1f}M/team')
if __name__=='__main__':
    print(collections.Counter((r['tier'],r['kind']) for r in rows)); print({t:(round(F['fv'],3),round(F['sd'],2)) for t,F in FIT.items()})
    rep('live now (k1.375,d0)',build())
    for k in (1.1,1.25,1.375):
        for dd in (0,.05,.1,.2,.35,.6,1.0):
            rep(f'k{k} d{dd}',build(k,dd))
