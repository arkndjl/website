"""I1 pre-registered check on the graded live picks: evDU recomputed with the rung's own lean (units.priced mkt)"""
import sys,json,math,collections
sys.path.insert(0,'/tmp/audit-nov09/fix/bet'); import i1_data as D
import numpy as np
C,DU=D.C,D.DU
sys.path.insert(0,D.W+'scripts'); import games_picks as GP, rule_monitor as RM
RJ=json.load(open(GP.RULES)); F=json.load(open(GP.FIT))['sports']
def kof(sport,e):
    S=RJ['sports'][sport]
    if e.get('seg'):
        for z in S.get('segments') or []:
            if z['mk']==e['mk'] and f"{z['fam']}: {z['val']}"==e['seg']: return z['k']
    return S['markets'][e['mk']].get('k')
rows=[];skip=collections.Counter()
for sport,e,near in D.picks():
    if e.get('pass'): skip['pass']+=1; continue
    if not near: skip['no ladder rung']+=1; continue
    own=1/C.dec(e['price'])
    if abs(own-near[3])>0.015: skip['quote moved']+=1; continue
    k=kof(sport,e)
    if not k: skip['no k']+=1; continue
    sgn=1 if e['side'] in('home','over') else -1
    q_side=(own+1-near[4])/2; q_home=q_side if sgn>0 else 1-q_side
    f=e['line']+C.fair_line(sport,e['mk'],e['line'],q_home)-C.fair_line(sport,e['mk'],e['line'],0.5)
    cap=F[sport]['cap'][0 if e['mk']=='spread' else 1]
    edge=e.get('sz') or e['edge']
    gap_f=min(e['edge']+sgn*(e['line']-f),cap)
    c_old=GP.calib(sport,e['mk'],e['side'],e['line'],edge,k)
    c_mkt=GP.lean_at(sport,e["mk"],e["side"],e["line"],f)
    c_new=C.chances(sport,e['mk'],e['side'],e['line'],f+sgn*k*gap_f)
    p=DU.params(sport,e['mk'])
    ev_old=DU.priced(p,c_old,e['price'],edge)[1]; ev_new=DU.priced(p,c_new,e['price'],gap_f,mkt=c_mkt)[1]
    u_old=DU.stake(sport,e['mk'],c_old,e['price'],gap=edge); u_new=DU.stake(sport,e['mk'],c_new,e['price'],gap=gap_f,mkt=c_mkt)
    k_old=p['lam']*DU.kelly_pct(p,c_old,e['price'],edge); k_new=p['lam']*DU.kelly_pct(p,c_new,e['price'],gap_f,mkt=c_mkt)
    rows.append(dict(sport=sport,mk=e['mk'],be=(own-.5)*100,price=e['price'],cr=e['clvRet'],ev_log=e.get('evDU') or 0,ev_old=ev_old,ev_new=ev_new,u_old=u_old,u_new=u_new,k_old=k_old,k_new=k_new,
                     day=sport+RM.day(e['kick']),q=q_side,lean=sgn*(f-e['line']),raw=e.get('unitsRaw') or e['units']))
print('picks used',len(rows),'skipped',dict(skip))
def ols(y,x,g):
    y=np.array(y,float); X=np.column_stack([np.ones(len(y)),np.array(x,float)])
    Xi=np.linalg.inv(X.T@X); b=Xi@X.T@y; e=y-X@b
    sc=collections.defaultdict(lambda: np.zeros(2))
    for gi,xi,ei in zip(g,X,e): sc[gi]+=xi*ei
    G=len(sc); V=Xi@sum(np.outer(s,s) for s in sc.values())@Xi*G/(G-1)
    Vi=Xi*float(e@e)/(len(y)-2)
    se=np.sqrt(np.maximum(np.diag(V),np.diag(Vi)))
    return b,b/np.sqrt(np.diag(V)),b/se,G
g=[r['day'] for r in rows]; x=[r['be'] for r in rows]
for lab,y in (('clvRet at own price',[r['cr'] for r in rows]),('evDU logged',[r['ev_log'] for r in rows]),('evDU old formula, today\'s fit',[r['ev_old'] for r in rows]),('evDU new formula',[r['ev_new'] for r in rows]),
              ('clvRet - evDU old',[r['cr']-r['ev_old'] for r in rows]),('clvRet - evDU new  << the test',[r['cr']-r['ev_new'] for r in rows]),
              ('Kelly % old (uncapped)',[r['k_old'] for r in rows]),('Kelly % new (uncapped)',[r['k_new'] for r in rows])):
    b,t,tf,G=ols(y,x,g); print(f"{lab}: mean {np.mean(y):+.4f}, slope per +1pp of break-even chance {b[1]:+.5f} (day-clustered t {t[1]:.2f}; floored at iid {tf[1]:.2f}; {G} days)")
for lab,f in (('plus',lambda r:r['price']>=100),('-101..-105',lambda r:-105<=r['price']<0),('<=-106',lambda r:r['price']<=-106)):
    v=[r for r in rows if f(r)]
    print(f"{lab}: n {len(v)} clvRet {np.mean([r['cr'] for r in v]):+.4f} | evDU old {np.mean([r['ev_old'] for r in v]):+.4f} new {np.mean([r['ev_new'] for r in v]):+.4f} | stake old {np.mean([r['u_old'] for r in v]):.2f}u new {np.mean([r['u_new'] for r in v]):.2f}u | new stake 0 on {sum(r['u_new']==0 for r in v)} (old 0 on {sum(r['u_old']==0 for r in v)}) | mkt mid {np.mean([r['q'] for r in v]):.4f} lean pts {np.mean([r['lean'] for r in v]):+.2f}")
def sw(key):
    w=np.array([r[key] for r in rows]); y=np.array([r['cr'] for r in rows])
    m,se,t,G=RM.clustered(list(y),g,list(w)); return m,se,t,w.sum(),int((w>0).sum())
for key,lab in (('u_old','old stakes (recomputed, today\'s fit)'),('u_new','new stakes'),('k_old','old uncapped Kelly'),('k_new','new uncapped Kelly')):
    m,se,t,W,n=sw(key); print(f"stake-weighted clvRet at own price, {lab}: {m:+.4f} (se {se:.4f}, t {t:.2f}); total {W:.1f}u on {n} picks")
print('flat clvRet %.4f'%np.mean([r['cr'] for r in rows]))
# paired: per-pick (new - old stake) x clvRet, summed by day
d=collections.defaultdict(float)
for r in rows: d[r['day']]+=(r['u_new']-r['u_old'])*r['cr']
v=np.array(list(d.values())); print(f"units of close value gained by restaking (sum over picks of (new - old stake) x clvRet): {v.sum():+.3f}u, day t {v.mean()/(v.std(ddof=1)/math.sqrt(len(v))):.2f} ({len(v)} days)")
print('share of stake on plus-priced picks: old %.3f new %.3f (share of picks %.3f)'%(sum(r['u_old'] for r in rows if r['price']>=100)/sum(r['u_old'] for r in rows),sum(r['u_new'] for r in rows if r['price']>=100)/sum(r['u_new'] for r in rows),np.mean([r['price']>=100 for r in rows])))
for sp in ('cbb','nba','cfb','nfl'):
    v=[r for r in rows if r['sport']==sp]
    if v: print(sp,'n',len(v),'stake old %.2f new %.2f'%(np.mean([r['u_old'] for r in v]),np.mean([r['u_new'] for r in v])),'sw clvRet old %+.4f new %+.4f'%(np.average([r['cr'] for r in v],weights=[r['u_old'] for r in v]),np.average([r['cr'] for r in v],weights=[r['u_new'] for r in v]) if sum(r['u_new'] for r in v) else float('nan')))
dr=[r for r in rows if r['u_new']==0 and r['u_old']>0]; kp=[r for r in rows if r['u_new']>0]; ad=[r for r in rows if r['u_new']>0 and r['u_old']==0]
for lab,v in (('dropped by the new formula (stake 0, was > 0)',dr),('kept',kp),('added (was 0)',ad)):
    if v:
        m,se,t,G=RM.clustered([r['cr'] for r in v],[r['day'] for r in v]); print(f"{lab}: n {len(v)} clvRet {m:+.4f} (se {se:.4f})")
