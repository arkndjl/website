import json,sys,numpy as np,datetime as dt
sys.path.insert(0,'/home/user/website/scripts')
from names import key
H=json.load(open('hist.json')); P={}
for k,p in H.items():
    L=(p['hist'] or {}).get('list') or []
    P[key(p['name'])]={**p,'s':{dt.date.fromtimestamp(x['dateUnix']+43200):x['valuation'] for x in L if x.get('valuation')}}
D=[x for x in json.load(open('/mnt/project-files/nil-audit-nov27/deals.json')) if x['sport']=='football' and x.get('amount_usd') and x.get('independent_of_on3_valuation')]
D.append({'player':'Kamario Taylor','amount_usd':7.5e6,'date':'2026-11-25','position':'QB','kind':'re-sign'})
def at(p,d):
    ds=[x for x in p['s'] if x<=d]; return p['s'][max(ds)] if ds else None
rows=[]
for x in D:
    p=P.get(key(x['player'])); 
    if not p or not p['s']: print(x['player'],x['date'],'no On3 history'); continue
    d=dt.date.fromisoformat(x['date']); b=at(p,d-dt.timedelta(days=3)); first=min(p['s']); a=at(p,max(p['s']))
    print(f"{x['player']:20s} {x['position']:4s} {x['date']} deal {x['amount_usd']/1e6:4.1f}M  On3 before {('%.2fM'%(b/1e6)) if b else 'n/a (history starts '+str(first)+')'}  On3 now {a/1e6:.2f}M", (f" gap {np.log(x['amount_usd']/b):+.2f} later move {np.log(a/b):+.2f}" if b else ''))
