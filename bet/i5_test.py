"""I5 pre-registered test: held-out (test seasons) clvRet at the haircut, surviving rule set vs current; dropped set <= 0 pooled"""
import sys,json,math,collections
sys.path.insert(0,'/tmp/audit-nov09/wt-bet/scripts')
import numpy as np, games_picks as GP, units as DU, rule_monitor as RM
F=json.load(open(GP.FIT))['sports']
def picks(RJ):
    out={}
    for sport in GP.SPORTS:
        S=RJ['sports'][sport]; rows=[r for r in GP.load_wf(sport) if r.get('res') is not None]
        tune,val=set(GP.RULE_TUNE[sport]),set(GP.RULE_VAL[sport]); m_=DU.TIMING*DU.LEAK.get(sport,1.0)
        for mk in ('spread','total'):
            par=S['markets'].get(mk) or {}; segs=[z for z in S.get('segments') or [] if z['mk']==mk]
            if not par.get('on') and not segs: continue
            cap=F[sport]['cap'][0 if mk=='spread' else 1]
            rs=[r for r in rows if (r.get('Lo') if mk=='spread' else r.get('To')) is not None and r['S']>max(tune|val)]
            for e in GP.rule_bets(sport,rs,mk,GP.RULE_GRID[mk][0],True,cap):
                if e.get('clvRet') is None: continue
                sg=GP.seg_of(sport,e['g'],mk,e['side'],e['line'])
                ok=(par.get('on') and e['gap']>=par['x']) or any(sg.get(z['fam'])==z['val'] and e['gap']>=z['x'] for z in segs)
                if ok: out[(sport,mk,e['g']['id'])]=(DU.adj(e['clvRet'],0.0,m_),e['clvRet'],sport+DU.slate_of(sport,e['g']))
    return out
def stat(d,keys):
    if not keys: return 'n 0'
    x=[d[k][0] for k in keys]; raw=[d[k][1] for k in keys]; g=[d[k][2] for k in keys]
    m,se,t,G=RM.clustered(x,g)
    return f"n {len(x)} haircut value {m:+.4f} (se {se:.4f}, t {t:.2f}, {G} slates); raw clvRet {np.mean(raw):+.4f}"
cur=picks(json.load(open('rules_current.json'))); new=picks(json.load(open('rules_i5.json')))
D=set(cur)-set(new); A=set(new)-set(cur)
print('current set  :',stat(cur,list(cur)))
print('surviving set:',stat(new,list(new)))
print('dropped (in current, not in new):',stat(cur,list(D)))
print('added   (in new, not in current):',stat(new,list(A)))
for sp in GP.SPORTS:
    for mk in ('spread','total'):
        f=lambda ks:[k for k in ks if k[0]==sp and k[1]==mk]
        if f(cur) or f(new): print(' ',sp,mk,'| current',stat(cur,f(cur)),'| new',stat(new,f(new)),'| dropped',stat(cur,f(D)),'| added',stat(new,f(A)))
