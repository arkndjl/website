"""the auditor's monitor_sim.py against the changed rule_monitor: whole held-out slates resampled with their own
residuals, mean theta x mu1. usage: sim2.py <hL,...> [sims] [--segs]"""
import sys,json,math,collections,datetime
sys.path.insert(0,'/tmp/audit-nov09/wt-bet/scripts')
import numpy as np, units as DU, rule_monitor as RM, games_picks as GP
RJ=json.load(open(GP.RULES)); F=json.load(open(GP.FIT))['sports']; P0=RM.params()
HZ={'cbb':1000,'cfb':600,'nfl':300,'nba':600}
def held_slates(sport,mk,x,fam=None,val=None):
    rows=[r for r in GP.load_wf(sport) if r.get('res') is not None]
    m=RJ['sports'][sport]['markets'][mk]; cap=F[sport]['cap'][0 if mk=='spread' else 1]
    tune,vl=set(GP.RULE_TUNE[sport]),set(GP.RULE_VAL[sport])
    rs=[r for r in rows if (r.get('Lo') if mk=='spread' else r.get('To')) is not None and r['S']>max(tune|vl)]
    es=[e for e in GP.rule_bets(sport,rs,mk,x,True,cap) if e.get('clvRet') is not None]
    if fam: es=[e for e in es if GP.seg_of(sport,e['g'],mk,e['side'],e['line']).get(fam)==val]
    d=collections.defaultdict(list)
    for e in es: d[DU.slate_of(sport,e['g'])].append(e['clvRet'])
    return d
BASE=datetime.datetime(2026,11,1,23,tzinfo=datetime.timezone.utc)
KS=[(BASE+datetime.timedelta(days=d)).strftime('%Y-%m-%dT%H:%M:%SZ') for d in range(3000)]
def run(sl,mu1,sd,rho,theta,horizon,sims,hLs,rng):
    allx=np.concatenate(sl); mu_h=allx.mean()
    out={h:collections.Counter() for h in hLs}; hits={h:[] for h in hLs}; dn=[]
    for s in range(sims):
        bets=[];d=0
        while len(bets)<horizon:
            v=sl[rng.integers(len(sl))]
            bets+=[{'kick':KS[d],'clvRet':float(xi)} for xi in (v-mu_h)+theta*mu1]; d+=1
        dr=RM.drift(bets,mu1,sd,rho,P0)
        if dr['at']: dn.append(dr['at'][1])
        for h in hLs:
            P={**P0,'cusum':{**P0['cusum'],'hL':h}}
            dc=RM.decide(bets,sd,P,mu1,rho)
            cs=dc.get('hitAt') is not None
            # the test as it runs live: the first of the two to fire decides (a confirm retires the drift test only)
            paused=dr['state']=='paused'
            out[h]['close']+=cs; out[h]['paused']+=paused; out[h]['confirmed']+=dr['state']=='confirmed'
            out[h]['any']+=cs or paused
            if cs or paused: hits[h].append(min([x for x in (dc.get('hitAt'),dr['at'][1] if paused else None) if x]))
    return {h:({k:v/sims for k,v in out[h].items()},int(np.median(hits[h])) if hits[h] else None) for h in hLs}
if __name__=='__main__':
    hLs=[float(x) for x in sys.argv[1].split(',')]; sims=int(sys.argv[2]) if len(sys.argv)>2 else 400
    rules=[]
    for sport in GP.SPORTS:
        S=RJ['sports'][sport]
        for mk in ('spread','total'):
            m=S['markets'][mk]
            if m.get('on'): rules.append((sport,mk,m['x'],None,None,m['heldRec']))
        if '--segs' in sys.argv:
            for z in S.get('segments') or []: rules.append((sport,z['mk'],z['x'],z['fam'],z['val'],z['held']))
    res={}
    for sport,mk,x,fam,val,held in rules:
        d=held_slates(sport,mk,x,fam,val); sl=[np.array(v) for v in d.values()]
        mu1=RM.expected_live(sport,held); sd=RM.sd_of(held); rho=DU._icc(d)
        name=f"{sport}:{mk}"+(f" | {fam}: {val}" if fam else '')
        if not mu1 or mu1<=0: print(name,'no test (mu1',mu1,')'); continue
        rng=np.random.default_rng(5)
        row={}
        for theta in (1.0,0.5,0.0,-1.0):
            r=run(sl,mu1,sd,rho,theta,HZ[sport],sims,hLs,rng); row[theta]=r
            for h in hLs:
                o,med=r[h]
                print(f"{name} mu1 {mu1:.4f} sd {sd:.3f} icc {rho:.3f} n/slate {sum(map(len,sl))/len(sl):.1f} | theta {theta:+.1f} hL {h:.2f} {HZ[sport]} bets: close stop {o.get('close',0):.3f} drift paused {o.get('paused',0):.3f} confirmed {o.get('confirmed',0):.3f} any stop {o.get('any',0):.3f} (median at {med})",flush=True)
        res[name]={'mu1':mu1,'sd':sd,'icc':rho,'rows':{str(t):{str(h):row[t][h] for h in hLs} for t in row}}
    json.dump(res,open(sys.argv[sys.argv.index('--out')+1],'w')) if '--out' in sys.argv else None
