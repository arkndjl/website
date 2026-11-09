"""for each graded live spread/total pick: the Novig ladder as last archived at or before the flag, the pick's rung there"""
import sys,json,os,glob,bisect,collections
W='/tmp/audit-nov09/wt-bet/'
sys.path.insert(0,W+'scripts')
import novig as NV, clv as C, units as DU
def load(sport):
    nid2id={}
    for fn in sorted(glob.glob(W+f'scripts/data/odds_novig/{sport}-*.jsonl')):
        for x in open(fn):
            if x.strip():
                r=json.loads(x)
                if r.get('id'): nid2id[r['nid']]=str(r['id'])
    lad=collections.defaultdict(list)
    for fn in sorted(glob.glob(W+f'scripts/data/odds_novig_ladder/{sport}-*.jsonl')):
        for x in open(fn):
            if x.strip():
                r=json.loads(x); i=str(r['id']) if r.get('id') else nid2id.get(r['nid'])
                if i: lad[i].append((r['t'],r['lad']))
    return lad
def american(p): return NV.american(p)
def picks():
    out=[]
    for sport in ('cbb','nba','cfb','nfl'):
        lad=load(sport)
        for e in json.load(open(W+f'data/games_picks_{sport}.json'))['log']:
            if e['mk']=='ml' or e.get('res') not in('w','l','p') or e.get('close') is None or e.get('clvRet') is None or e.get('line') is None: continue
            rows=lad.get(str(e['espn'])) or lad.get(str(e['id'])) or []
            ts=[r[0] for r in rows]; j=bisect.bisect_right(ts,e['flagged'])-1
            L=None; near=None
            # the ladder as archived at the flag (the snap that saw this rung at this price: the last at or before the flag, else the first after within 20 minutes)
            for jj in ([j] if j>=0 else [])+([j+1] if j+1<len(rows) else []):
                key='L' if e['mk']=='spread' else 'T'
                rungs=rows[jj][1].get(key) or []
                for x,a0,a1 in rungs:
                    if abs(x-e['line'])<1e-9:
                        ask=a0 if e['side'] in('home','over') else a1; oth=a1 if e['side'] in('home','over') else a0
                        if near is None: near=(jj-j,rows[jj][0],rungs,ask,oth)
                if near: break
            out.append((sport,e,near))
    return out
if __name__=='__main__':
    P=picks(); c=collections.Counter()
    for sport,e,near in P:
        c[sport,'n']+=1
        if not near: c[sport,'no rung']+=1; continue
        c[sport,'rung']+=1
        c[sport,'price match']+= american(near[3])==e['price']
        c[sport,'price within 3c']+= abs(1/C.dec(e['price'])-near[3])<=0.031
    for k in sorted(c): print(k,c[k])
    print('examples'); 
    for sport,e,near in P[:3]+P[200:203]: print(sport,e['mk'],e['side'],e['line'],e['price'],e['flagged'],near and (near[0],near[1],near[3],near[4],len(near[2])))
