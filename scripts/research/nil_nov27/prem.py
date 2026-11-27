import json,sys,collections,numpy as np
sys.path.insert(0,'/home/user/website/scripts')
from names import key as name_key
d=json.load(open('/home/user/website/static/data/cfb-all.json')); c={k:i for i,k in enumerate(d['cols'])}
R=[dict(zip(d['cols'],r)) for r in d['rows']]
live=[r for r in R if r['xnil'] and r['ynil'] and not r['carried'] and r['src']!='espn' and r['div']=='FBS']
on={x['slug']:x for x in json.load(open('on3_cfb.json'))}
for r in live:
    o=on.get((r.get('on3l') or '').rstrip('/').split('/')[-1]); r['nil']=(o or {}).get('nil')
deals=[x for x in json.load(open('/mnt/project-files/nil-audit-nov27/deals.json')) if x['sport']=='football' and x.get('amount_usd')]
bk=collections.defaultdict(list)
for r in live: bk[name_key(r['name'])].append(r)
def tier(fv): return '<40' if fv<40 else '40-44' if fv<45 else '45-49' if fv<50 else '50-54' if fv<55 else '55+'
def tab(rows,key,val):
    g=collections.defaultdict(list)
    for r in rows: g[key(r)].append(val(r))
    for k in sorted(g): v=np.array(g[k]); print(f'   {str(k):16s} n {len(v):3d} mean {v.mean():+.2f} med {np.median(v):+.2f} sd {v.std():.2f}')
V=[r for r in live if r['nil']]
if __name__=='__main__':
    print('On3 (n %d): log(On3/yNIL) by FV tier, QB vs rest'%len(V))
    tab(V,lambda r:('QB' if r['pos']=='QB' else 'other',tier(r['fv'])),lambda r:np.log(r['nil']/r['ynil']))
    print('log(On3/xNIL)'); tab(V,lambda r:('QB' if r['pos']=='QB' else 'other',tier(r['fv'])),lambda r:np.log(r['nil']/r['xnil']))
    print('by position log(On3/yNIL)'); tab(V,lambda r:r['pos'],lambda r:np.log(r['nil']/r['ynil']))
    # deals: latest per player, independent or not
    last={}
    for x in sorted(deals,key=lambda x:x.get('date') or ''):
        m=bk.get(name_key(x['player']))
        if m and len(m)==1: last[x['player']]=(x,m[0])
    print('deals matched',len(last),'independent',sum(1 for x,_ in last.values() if x.get('independent_of_on3_valuation')))
    for ind in (True,False):
        S=[(x,r) for x,r in last.values() if bool(x.get('independent_of_on3_valuation'))==ind]
        print(' independent' if ind else ' list/On3-linked',len(S))
        for nm,f in (('y',lambda x,r:np.log(x['amount_usd']/r['ynil'])),('x',lambda x,r:np.log(x['amount_usd']/r['xnil']))):
            print('  log(deal/%sNIL)'%nm); tab(S,lambda t:('QB' if t[1]['pos']=='QB' else 'other',tier(t[1]['fv'])),lambda t:f(*t))
    for x,r in sorted(last.values(),key=lambda t:-t[0]['amount_usd'])[:25]:
        print(f"   {x['player']:26s} {r['pos']:4s} FV {r['fv']} deal {x['amount_usd']/1e6:4.1f}M  yNIL {r['ynil']/1e6:4.1f}  xNIL {r['xnil']/1e6:4.1f}  On3 {(r['nil'] or 0)/1e6:3.1f} {x['kind']} {x['date']} ind={x.get('independent_of_on3_valuation')}")
