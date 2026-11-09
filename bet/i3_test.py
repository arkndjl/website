"""I3 pre-registered walk-forward on the committed live ledger: each game day staked with a per-sport TIMING posterior
from earlier days only (prior N(.5, .26^2), through-origin regression, se = max(iid, day-clustered)), against TIMING .5"""
import sys,json,math,collections
W='/tmp/audit-nov09/wt-bet/'; sys.path.insert(0,W+'scripts')
import numpy as np, clv as C, units as DU, rule_monitor as RM, games_picks as GP
UF=json.load(open(DU.FIT)); RJ=json.load(open(GP.RULES))
P0,S0=0.5,0.26
B0=DU.dec(DU.BASE)-1; r0=(B0-1)/2
def kof(sport,e):
    S=RJ['sports'][sport]
    if e.get('seg'):
        for z in S.get('segments') or []:
            if z['mk']==e['mk'] and f"{z['fam']}: {z['val']}"==e['seg']: return z['k']
    return S['markets'][e['mk']].get('k')
def btp(sport,mk):
    bt=UF['sports'][sport][mk]['backtest']; lv=UF['sports'][sport][mk]['live']
    return {**DU.DEFAULT,'on':'gap','a':bt['a'],'b':bt['b'],'evbar':bt['gbar'],'V':[[bt['seA']**2,0],[0,bt['seB']**2]],'lam':1.0,'cap':DU.BOOK_CAP,'rho':lv.get('rho',0),'nbar':lv.get('nbar',1)}
rows=[]
for sport in ('cbb','nba','cfb','nfl'):
    for e in json.load(open(W+f'data/games_picks_{sport}.json'))['log']:
        if e['mk']=='ml' or e.get('res') not in('w','l','p') or e.get('pass') or e.get('close') is None or e.get('clvRet') is None or e.get('line') is None: continue
        if e['mk'] not in UF['sports'].get(sport,{}): continue
        k=kof(sport,e)
        if not k: continue
        gap=e.get('sz') or e['edge']; p=btp(sport,e['mk'])
        c=GP.calib(sport,e['mk'],e['side'],e['line'],gap,k)
        crb=C.ret(sport,e['mk'],e['side'],e['line'],DU.BASE,e['close'])
        rows.append(dict(sport=sport,mk=e['mk'],day=RM.day(e['kick']),c=c,price=e['price'],gap=gap,p=p,cr=e['clvRet'],crb=crb,
                         x=(p['a']+p['b']*(gap-p['evbar'])-r0)/DU.TIMING, y=crb-r0, kick=e['kick']))
print('picks',len(rows),collections.Counter(r['sport'] for r in rows))
def post(prev):
    """TIMING posterior from earlier picks of the sport"""
    if len(prev)<2: return P0,S0,None,None
    x=np.array([r['x'] for r in prev]); y=np.array([r['y'] for r in prev]); g=[r['day'] for r in prev]
    b=(x@y)/(x@x); e=y-b*x
    sc=collections.defaultdict(float)
    for gi,xi,ei in zip(g,x,e): sc[gi]+=xi*ei
    G=len(sc); iid=math.sqrt((e@e)/(len(x)-1)/(x@x))
    se=max(iid,math.sqrt(sum(v*v for v in sc.values())*G/(G-1))/(x@x)) if G>1 else iid
    w0,w1=1/S0**2,1/se**2
    return (P0*w0+b*w1)/(w0+w1),math.sqrt(1/(w0+w1)),b,se
def stake_T(r,T,sT):
    """the shipped stake with the edge over a coin rescaled to TIMING T and (sT x open edge)^2 added to its variance"""
    p,c,o,gap=r['p'],r['c'],r['price'],r['gap']
    w,pu,l=c
    if w*(DU.dec(o)-1)-l<=0: return 0.0
    ev0=w*B0-l
    if ev0<=0: return 0.0
    e5,_=DU.edge(p,ev0,gap)                      # calibrated return at BASE at TIMING .5
    rc=(1-pu)*(B0-1)/2; d5=e5-rc                 # its edge over a coin
    e=rc+(T/DU.TIMING)*d5
    V=p['V']; dv=min(gap-p['evbar'],0.0)
    var=max(0.0,V[0][0]+dv*dv*V[1][1])*(T/DU.TIMING)**2+(sT*d5/DU.TIMING)**2
    if e<=0: return 0.0
    u=e*e/(e*e+var)
    ws=(e+1-pu)/(B0+1); B=DU.dec(o)-1; ev=ws*B-(1-pu-ws)
    if ev<=0: return 0.0
    f=p['lam']*u*ev/(B*(1-pu))*100
    return min(p['cap'],max(DU.UNIT_MIN,round(f*4)/4)) if f>0 else 0.0
days=sorted({r['day'] for r in rows}); trace=[]
for r in rows:
    prev=[q for q in rows if q['sport']==r['sport'] and q['day']<r['day']]
    T,sT,b,se=post(prev)
    r['T'],r['sT']=T,sT
    r['u_old']=DU.stake(r['sport'],r['mk'],r['c'],r['price'],p=r['p'],gap=r['gap'])
    r['u_chk']=stake_T(r,DU.TIMING,0.0)
    r['u_new']=stake_T(r,T,sT)
assert all(abs(r['u_old']-r['u_chk'])<1e-9 for r in rows),'stake_T at .5 / 0 must reproduce units.stake'
def report(v,lab):
    g=[r['day'] for r in v]; cr=[r['cr'] for r in v]
    out=[lab,f"n {len(v)} days {len(set(g))} flat clvRet {np.mean(cr):+.4f}"]
    for key in ('u_old','u_new'):
        w=[r[key] for r in v]
        if sum(w)>0:
            m,se,t,G=RM.clustered(cr,g,w); out.append(f"{key}: {sum(w):.1f}u on {sum(1 for x in w if x>0)}, stake-weighted clvRet {m:+.4f} (t {t:.2f})" if t is not None else f"{key}: {sum(w):.1f}u, sw clvRet {m:+.4f}")
        else: out.append(f"{key}: 0u")
    d=collections.defaultdict(lambda:[0.0,0.0])
    for r in v:
        d[r['day']][0]+=r['u_old']/100*r['cr']; d[r['day']][1]+=r['u_new']/100*r['cr']
    go=np.array([math.log(1+a) for a,b in d.values()]); gn=np.array([math.log(1+b) for a,b in d.values()]); dd=gn-go
    t=dd.mean()/(dd.std(ddof=1)/math.sqrt(len(dd))) if len(dd)>1 and dd.std(ddof=1)>0 else float('nan')
    out.append(f"log growth at the close: old {go.sum()*100:+.2f}% new {gn.sum()*100:+.2f}% | difference {dd.sum()*100:+.2f}%, day t {t:.2f} ({len(dd)} days)")
    print(' | '.join(out))
report(rows,'POOLED')
for sp in ('cbb','nba','cfb','nfl'): report([r for r in rows if r['sport']==sp],sp)
print('posterior by sport after each day (T mean, sd):')
for sp in ('cbb','nba','cfb','nfl'):
    v=[r for r in rows if r['sport']==sp]; ds=sorted({r['day'] for r in v})
    print(' ',sp,[(d[5:],round(next(r['T'] for r in v if r['day']==d),2),round(next(r['sT'] for r in v if r['day']==d),2)) for d in ds], 'final',tuple(round(x,3) if x is not None else None for x in post(v)))
def ratio_t(v):
    g=[r['day'] for r in v]; U0=sum(r['u_old'] for r in v); U1=sum(r['u_new'] for r in v)
    if U0<=0 or U1<=0: return None
    R0=sum(r['u_old']*r['cr'] for r in v)/U0; R1=sum(r['u_new']*r['cr'] for r in v)/U1
    inf=collections.defaultdict(float)
    for r in v: inf[r['day']]+=r['u_new']*(r['cr']-R1)/U1-r['u_old']*(r['cr']-R0)/U0
    G=len(inf); se=math.sqrt(sum(x*x for x in inf.values())*G/(G-1)) if G>1 else float('nan')
    return R1-R0,se,(R1-R0)/se if se else float('nan'),G
print('stake-weighted clvRet, new minus old (day-clustered, linearised):')
for lab,v in [('pooled',rows)]+[(sp,[r for r in rows if r['sport']==sp]) for sp in ('cbb','nba','cfb','nfl')]:
    x=ratio_t(v); print(' ',lab,None if x is None else f"{x[0]:+.4f} se {x[1]:.4f} t {x[2]:.2f} ({x[3]} days)")
