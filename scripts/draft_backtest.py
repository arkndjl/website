"""Draft-slot backtest for the mock draft (scripts/cfb_teams.mjs, BOARD_PICK).

Fetches DraftTek final pre-draft big boards (2020-25, top 600), nflverse draft picks and combine results,
and fits ln(pick) on board rank plus candidate factors, scored leave-one-draft-out. Writes
data/cfb_draft_backtest.json and the matched rows (scripts/.cache/draft/rows.json, for draft_sim_backtest.py).
Usage: python3 scripts/draft_backtest.py (needs numpy).
"""
import os, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, 'scripts', '.cache', 'draft'); os.makedirs(W, exist_ok=True); os.chdir(W)   # raw pulls, reused by draft_sim_backtest.py
get = lambda out, url: os.path.exists(out) or subprocess.run(["curl", "-sSLf", "-A", "Mozilla/5.0", "-o", out, url])
for y in range(2020, 2026):
    for p in range(1, 7):
        get(f"dt_{y}_{p}.html", f"https://www.drafttek.com/{y}-NFL-Draft-Big-Board/Top-NFL-Draft-Prospects-{y}-Page-{p}.asp")
for f in ["draft_picks/draft_picks.csv", "combine/combine.csv"]:
    get(f.split('/')[1], "https://github.com/nflverse/nflverse-data/releases/download/" + f)
import re, glob, json, html
out=[]
for f in sorted(glob.glob('dt_*.html')):
    y=int(f.split('_')[1]); s=open(f,encoding='latin1').read()
    s=re.sub(r'<!--.*?-->','',s,flags=re.S)
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
        tds=[html.unescape(re.sub('<[^>]+>','',t)).strip() for t in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(tds)>=8 and tds[0].isdigit():
            out.append(dict(year=y,rank=int(tds[0]),name=tds[2],school=tds[3],pos=tds[4],ht=tds[5],wt=tds[6],elig=tds[7]))
seen=set(); res=[]
for r in out:
    k=(r['year'],r['rank'])
    if k in seen: continue
    seen.add(k); res.append(r)
json.dump(res,open('boards.json','w'))
import json, csv, re, math, collections
B=json.load(open('boards.json'))
def norm(n): 
    n=n.lower().replace('.','').replace("'",'').replace('’','')
    n=re.sub(r'\b(jr|sr|ii|iii|iv|v)\b','',n); return re.sub(r'[^a-z]','',n)
picks={}; DP=[]
for r in csv.DictReader(open('draft_picks.csv')):
    y=int(r['season'])
    if 2020<=y<=2025: picks[(y,norm(r['pfr_player_name']))]=int(r['pick']); DP.append(r)
# boards and PFR spell some names differently (Cameron / Cam Ward, Ahmad / Sauce Gardner, Byron Young (TN)): an
# unmatched board name falls back to the one draftee that year with his last name (at his position group when
# several share it)
def last(n):
    w=[x for x in re.sub(r'\(.*?\)','',n).replace('.','').split() if x.lower() not in ('jr','sr','ii','iii','iv','v')]
    return re.sub(r'[^a-z]','',w[-1].lower()) if w else ''
bylast=collections.defaultdict(list)
for r in DP: bylast[(int(r['season']),last(r['pfr_player_name']))].append(r)
NGRP={'QB':'QB','RB':'RB','FB':'RB','WR':'WR','TE':'TE','T':'OL','G':'OL','C':'OL','OL':'OL','DE':'EDGE','OLB':'EDGE','DT':'DL','DL':'DL','NT':'DL','LB':'LB','ILB':'LB','CB':'CB','DB':'CB','S':'S','SAF':'S'}
comb={}
for r in csv.DictReader(open('combine.csv')):
    y=int(r['season'])
    if 2020<=y<=2025: comb[(y,norm(r['player_name']))]=r; comb.setdefault((y,'last',last(r['player_name'])),[]).append(r)
teams=json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']
P5={'SEC','Big Ten','ACC','Big 12','Pac-12'}
conf={}
for t in teams:
    for k in [t['team'],t.get('full') or '',t.get('abbr') or '']:
        if k: conf[norm(k)]=t['conf']
ALIAS={'appalachianstate':'appstate','centralflorida':'ucf','sanjosestate':'sanjosestate','southernmississippi':'southernmiss','ullafayette':'louisiana','miamifl':'miami','usc':'usc','ole miss':'olemiss','lsu':'lsu','tcu':'tcu','byu':'byu','ucf':'ucf','smu':'smu','pittsburgh':'pitt','ncstate':'ncstate','northcarolinastate':'ncstate'}
GROUP={'CB':'CB','CBN':'CB','WR':'WR','WRS':'WR','WRF':'WR','EDGE':'EDGE','OLB':'EDGE','S':'S','SRF':'S','OT':'OL','OG':'OL','OC':'OL','OL':'OL','RB':'RB','RBC':'RB','FB':'RB','ILB':'LB','LB':'LB','TE':'TE','QB':'QB','DL3T':'DL','DL5T':'DL','DL1T':'DL','DT':'DL','PK':'K','P':'K','LS':'K','ATH':'WR'}
onboard={(b['year'],norm(re.sub(r'\(.*?\)','',b['name']))) for b in B}   # draftees a board name already matches exactly
rows=[];miss=collections.Counter()
for b in B:
    k=(b['year'],norm(re.sub(r'\(.*?\)','',b['name'])))
    pk=picks.get(k)
    if pk is None:
        c=[x for x in bylast.get((b['year'],last(b['name'])),[]) if (b['year'],norm(x['pfr_player_name'])) not in onboard]; g=GROUP.get(b['pos'],'X')
        c2=[x for x in c if NGRP.get(x['position'])==g or (g in ('EDGE','LB','DL') and NGRP.get(x['position']) in ('EDGE','LB','DL'))]
        if len(c2)==1 and (b['rank']<=150 or c2[0]['pfr_player_name'][:1]==b['name'][:1]): pk=int(c2[0]['pick'])
        elif len(c)==1 and b['rank']<=150: pk=int(c[0]['pick'])
    sch=norm(b['school']); c=conf.get(ALIAS.get(sch,sch))
    if c is None: miss[b['school']]+=1
    m=re.match(r"(\d)'(\d+)",b['ht']); ht=int(m[1])*12+int(m[2]) if m else None
    cb=comb.get(k)
    if cb is None and len(comb.get((b['year'],'last',last(b['name'])),[]))==1: cb=comb[(b['year'],'last',last(b['name']))][0]
    rows.append(dict(year=b['year'],rank=b['rank'],name=b['name'],g=GROUP.get(b['pos'],'X'),pos=b['pos'],ht=ht,wt=float(b['wt']) if b['wt'].isdigit() else None,
      under=b['elig'] in ('JR','RJR','RSO','rSO','rJR'),elig=b['elig'],p5=c in P5 if c else False,fbs=c is not None,pick=pk,
      combine=cb is not None,forty=float(cb['forty']) if cb and cb['forty'] else None,vert=float(cb['vertical']) if cb and cb['vertical'] else None,
      broad=float(cb['broad_jump']) if cb and cb['broad_jump'] else None))
json.dump(rows,open('rows.json','w'))
# ---- fit: ln(pick) on board rank plus each factor set, leave one draft out --------------------------------
import numpy as np
R = [r for r in rows if r['rank'] <= 200 and r['g'] != 'K']
CAL = json.load(open(os.path.join(ROOT, 'data', 'cfb_calibration.json')))['size']
UND = 290.0
for r in R: r['y'] = math.log(min(r['pick'], UND) if r['pick'] else UND)
fz = collections.defaultdict(list)
for r in R:
    if r['forty']: fz[r['g']].append(r['forty'])
fst = {g: (np.mean(v), np.std(v)) for g, v in fz.items()}
G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
def feats(r, sets):
    lr = math.log(r['rank']); f = [1, lr, lr * lr]
    if 'pos' in sets: f += [1.0 if r['g'] == g else 0.0 for g in G[1:]]
    if 'class' in sets: f += [1.0 if r['under'] else 0.0]
    if 'level' in sets: f += [0.0 if r['p5'] else 1.0, 0.0 if r['fbs'] else 1.0]
    if 'size' in sets:
        n = CAL.get({'OL': 'OT'}.get(r['g'], r['g']))
        hz = ((r['ht'] - n['ht']['mean']) / n['ht']['sd']) if n and r['ht'] else 0
        wz = ((r['wt'] - n['wt']['mean']) / n['wt']['sd']) if n and r['wt'] else 0
        f += [max(-3, min(3, hz)), max(-3, min(3, wz)), max(0, -hz - 1.0), max(0, -wz - 1.0)]
    if 'combine' in sets:
        f += [0.0 if r['combine'] else 1.0]
        f += [(r['forty'] - fst[r['g']][0]) / fst[r['g']][1]] if r['forty'] and r['g'] in fst else [0.0]
    return f
def fit(tr, sets, lam=1.0):
    X = np.array([feats(r, sets) for r in tr]); y = np.array([r['y'] for r in tr])
    I = np.eye(X.shape[1]); I[0, 0] = 0
    return np.linalg.solve(X.T @ X + lam * I, X.T @ y)
def mae(sets, top):
    e = []
    for yr in range(2020, 2026):
        b = fit([r for r in R if r['year'] != yr], sets)
        e += [abs(min(math.exp(np.dot(feats(r, sets), b)), UND) - math.exp(r['y'])) for r in R if r['year'] == yr and r['rank'] <= top]
    return round(float(np.mean(e)), 1)
res = {'raw rank': {t: round(float(np.mean([abs(min(r['rank'], UND) - math.exp(r['y'])) for r in R if r['rank'] <= t])), 1) for t in (32, 100, 150)}}
for sets in [(), ('pos',), ('pos', 'class'), ('pos', 'class', 'level'), ('pos', 'class', 'level', 'size'), ('combine',), ('pos', 'class', 'level', 'size', 'combine')]:
    res['+'.join(sets) or 'rank curve'] = {t: mae(sets, t) for t in (32, 100, 150)}
out = {'_readme': 'Mean absolute pick error, leave-one-draft-out, DraftTek final pre-draft boards 2020-25 (top 32 / 100 / 150 board ranks; undrafted = pick 290). See scripts/draft_backtest.py.',
       'mae': res, 'curve': [round(float(x), 4) for x in fit(R, ())], 'combine': [round(float(x), 4) for x in fit(R, ('combine',))[3:]]}
json.dump(out, open(os.path.join(ROOT, 'data', 'cfb_draft_backtest.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
