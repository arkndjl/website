import json,subprocess,time,os
UA='Mozilla/5.0'
def get(u):
    for i in range(3):
        try:
            o=subprocess.run(['curl','-s','--max-time','30','-A',UA,u],capture_output=True,text=True).stdout
            return json.loads(o)
        except Exception as e: time.sleep(2*(i+1))
    return None
people={}
for pos in ['QB','RB','WR','TE','OT','IOL','EDGE','DL','LB','CB','S']:
    j=get(f'https://api.on3.com/public/rdb/v1/nil-rankings?sportKey=1&orgType=College&positionAbbr={pos}')
    for r in (j or {}).get('list',[]):
        p=r['person']; people[p['key']]={'key':p['key'],'name':p['name'],'slug':p['slug'],'pos':pos,'cls':p.get('classYear'),'team':(p.get('status') or {}).get('committedOrganizationSlug'),'val':(r.get('valuation') or {}).get('valuation')}
    time.sleep(.4)
print(len(people),flush=True)
out={}
for i,(k,p) in enumerate(people.items()):
    j=get(f'https://api.on3.com/public/rdb/v1/people/{k}/valuation-growth?limit=400')
    out[k]={**p,'hist':j}
    if i%40==0: print(i,flush=True); json.dump(out,open('hist.json','w'))
    time.sleep(.35)
json.dump(out,open('hist.json','w')); print('done',len(out))
