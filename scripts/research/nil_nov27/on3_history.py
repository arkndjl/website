import json,numpy as np,collections,datetime as dt
H=json.load(open('hist.json'))
P={}
for k,p in H.items():
    L=(p['hist'] or {}).get('list') or []
    s={dt.date.fromtimestamp(x['dateUnix']+43200):x['valuation'] for x in L if x.get('valuation')}
    if len(s)>30: P[k]={**p,'s':s}
print('players with history',len(P),'median days',np.median([len(p['s']) for p in P.values()]))
days=sorted({d for p in P.values() for d in p['s']}); print(days[0],days[-1])
# change events
ev=[]
for p in P.values():
    ds=sorted(p['s']); 
    for a,b in zip(ds,ds[1:]):
        if p['s'][a]!=p['s'][b]: ev.append((b,p['pos'],np.log(p['s'][b]/p['s'][a]),p['name']))
print('change events',len(ev),'per player-year',round(len(ev)/len(P),1))
bym=collections.Counter(e[0].strftime('%Y-%m') for e in ev); print(sorted(bym.items()))
big=[e for e in ev if abs(e[2])>.2]; print('moves over 20%:',len(big),sorted(collections.Counter(e[0].strftime('%Y-%m') for e in big).items()))
# position index: median log value among players valued on both dates, monthly
ms=[dt.date(2025,12,1)]+[dt.date(2026,m,1) for m in range(1,12)]+[days[-1]]
def val(p,d):
    s=p['s']; 
    while d>=days[0]:
        if d in s: return s[d]
        d-=dt.timedelta(days=1)
    return None
G=['QB','RB','WR','TE','OT','IOL','EDGE','DL','LB','CB','S']
idx={g:[] for g in G+['ALL']}
for a,b in zip(ms,ms[1:]):
    ch=collections.defaultdict(list)
    for p in P.values():
        va,vb=val(p,a),val(p,b)
        if va and vb: ch[p['pos']].append(np.log(vb/va)); ch['ALL'].append(np.log(vb/va))
    for g in idx: idx[g].append((np.mean(ch[g]) if ch[g] else np.nan, len(ch[g])))
print('monthly mean log change by position (n in last month):')
for g in ['ALL']+G: print(f'{g:5s}',' '.join(f'{x:+.2f}' for x,_ in idx[g]),' n',idx[g][-1][1],' cum',round(float(np.nansum([x for x,_ in idx[g]])),2))
json.dump({g:[(float(x),n) for x,n in v] for g,v in idx.items()},open('idx.json','w'))
