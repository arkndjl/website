"""Versatility backtest: do players who played more than one position in college have better NFL careers than
FV already expects? And does the board's position-change flag (a frame that fits another spot) mean more NFL value?

Run by hand after scripts/cfb_statplus_backtest.mjs and scripts/cfb_source_backtest.mjs (their cached PFN boards,
nflverse picks and DraftTek final boards), and scripts/cfb_move_backtest.mjs --rows scripts/.cache/vers/move_rows.json:
  python3 scripts/cfb_versatility_backtest.py -> data/cfb_versatility_backtest.json (needs numpy, pandas)

  universe   as in the Stat+ / source / badge backtests: each FBS player's last PFN season 2019-22 at QB, RB, WR, TE,
             EDGE, DT, LB (OL, CB and S have PFN only from 2024, so they have no NFL careers to test), outcome weighted
             NFL AV a season through 2025, undrafted = 0, players in a later draft dropped
  alignment  public data has no snap-by-alignment (PFF is paid; PFN, ESPN and CFBD play-by-play don't say where a
             defender lined up), so versatility is read from two things that are public:
               pfn   PFN graded him at two or more position groups (EDGE and DT, EDGE and LB, LB and S ...) with 100+
                     snaps in a season, in his career up to the final season. PFN files a player by where he played
               espn  ESPN's roster lists him at a position outside the PFN group (a PFN linebacker ESPN lists at safety,
                     a PFN receiver ESPN lists as a back; an edge listed DE or OLB is not a mismatch). cfbfastR's roster
                     files carry one listing per player for every season, so they can't show a change over time
               hs    247Sports' composite (2014-20 classes) recruited him at a position outside the group (a high school
                     safety now at linebacker, a quarterback now at receiver); ATH recruits apart (hsAth)
             careers link by name, at his final school or where the name is unique in FBS that season (as the board)
  move       the board's position-change flag (scripts/cfb_move_backtest.mjs rules at combine size), combine
             invitees 2020-23 only
  controls   A production (FV's 5/4/3 blend, K 3000); B production + DraftTek's final board (log rank and square),
             what FV holds for a draft-eligible player. Pooled fits carry position intercepts and slopes.
  pass       t >= 2 on control B and a leave-one-final-season-out R^2 gain, as every FV input
Result (Oct 14, 2026): nothing passes. 493 of 3,212 players count as multi-position on some measure (62 drafted); pooled
on control B the flag is -.02 AV a season (t -.44) and loses out of sample, and no measure or position reaches t 2 (PFN
two-group t .09, recruited elsewhere t .11, ATH recruit t -.25, the board's move flag t .54). The NFL already drafts
these players at their production. So multi-position eligibility is shown on the board and in the report, not in FV.
CB / S and OL slot versatility (the most common kinds) can't be tested until PFN's 2024 lines have NFL careers.
"""
import json, os, re, glob, math
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP, SRC, VC = (os.path.join(ROOT, 'scripts', '.cache', d) for d in ('statplus', 'sources', 'vers'))
OUT = os.path.join(ROOT, 'data', 'cfb_versatility_backtest.json')
os.makedirs(VC, exist_ok=True)
for y in range(2015, 2023):
    f = os.path.join(VC, f'r{y}.csv')
    if not os.path.exists(f):
        os.system(f'curl -sSLf -o {f} https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/csv/cfb_rosters_{y}.csv')

GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
TEST = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']
SPG = dict(QB=65, RB=30, WR=40, TE=40, OL=65, EDGE=50, DL=45, LB=55, CB=55, S=55)
NFLPOS = dict(QB=['QB'], RB=['RB', 'FB'], WR=['WR'], TE=['TE'], EDGE=['DE', 'OLB', 'EDGE', 'DL'], DL=['DT', 'DE', 'DL', 'NT'], LB=['LB', 'ILB', 'OLB', 'MLB'])
COARSE = dict(QB='QB', RB='RB', FB='RB', WR='WR', TE='TE', OL='OL', OT='OL', G='OL', C='OL', DL='DL', DE='DL', DT='DL', NT='DL', EDGE='DL',
              LB='LB', ILB='LB', OLB='LB', DB='DB', CB='DB', S='DB')
NFL_THROUGH, K, W, LAST = 2025, 3000, (5, 4, 3), (2019, 2020, 2021, 2022)

nm = lambda s: re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', re.sub(r'[^a-z ]', '', str(s or '').lower()))).strip()
school = lambda s: re.sub(r'\buniversity\b|\bof\b', '', nm(s).replace('state', 'st')).strip().split(' ')[0] if s else ''
vol = lambda g, r: next((r[k] for k in ('snapsQ', 'snaps') if isinstance(r.get(k), (int, float))), None) or (r.get('gp') or r.get('gamesQ') or 0) * SPG[g]

# ---- PFN careers (all ten boards) ------------------------------------------------------------------------------
pfn = {g: [r for r in json.load(open(os.path.join(SP, f'pfn_{g}.json'))) if r['division'] == 'FBS'] for g in GROUPS}
careers, teams_by = {}, {}
for g, rows in pfn.items():
    for r in rows:
        careers.setdefault(nm(r['name']), []).append(dict(g=g, team=school(r['team']), season=r['season'], v=vol(g, r)))
        teams_by.setdefault((nm(r['name']), r['season']), set()).add(school(r['team']))

def pfn_groups(name, team, last):
    """position groups PFN graded him at with 100+ snaps, seasons <= last, linked at this school or a unique name"""
    out = {}
    for h in careers.get(nm(name), []):
        if h['season'] > last or h['v'] < 100: continue
        if h['team'] != team and len(teams_by[(nm(name), h['season'])]) > 1: continue
        out[h['g']] = out.get(h['g'], 0) + h['v']
    return out

# ---- ESPN roster listings (cfbfastR, ESPN athlete id) ---------------------------------------------------------------
ros = pd.concat([pd.read_csv(f, usecols=['athlete_id', 'first_name', 'last_name', 'team', 'position', 'season'], low_memory=False) for f in sorted(glob.glob(os.path.join(VC, 'r20*.csv')))])
ros = ros[ros.position.isin(COARSE.keys())]
ros['c'] = ros.position.map(COARSE)
ros['k'] = (ros.first_name.astype(str) + ' ' + ros.last_name.astype(str)).map(nm)
ros['sch'] = ros.team.map(school)
listing = {a: dict(zip(g.season, g.c)) for a, g in ros.groupby('athlete_id')}
aid = {}
for (k, s, sch), g in ros.groupby(['k', 'season', 'sch']):
    if g.athlete_id.nunique() == 1: aid[(k, s, sch)] = g.athlete_id.iloc[0]

FITS = dict(QB={'QB'}, RB={'RB'}, WR={'WR'}, TE={'TE'}, OL={'OL'}, EDGE={'DL', 'LB'}, DL={'DL'}, LB={'LB'}, CB={'DB'}, S={'DB'})
def espn_listed(name, team, last):
    a = aid.get((nm(name), last, team))
    return None if a is None else listing[a].get(last)

# ---- 247 composite: the position each player was recruited at -------------------------------------------------------
HS_FITS = dict(QB={'PRO', 'DUAL', 'QB'}, RB={'RB', 'APB'}, WR={'WR'}, TE={'TE'}, OL={'OT', 'OG', 'OC', 'IOL', 'OL'}, EDGE={'WDE', 'SDE', 'EDGE', 'DL', 'OLB', 'LB'},
               DL={'DT', 'SDE', 'DL'}, LB={'ILB', 'OLB', 'LB'}, CB={'CB'}, S={'S'})
hs = {}
for f in sorted(glob.glob(os.path.join(VC, 'c247_*.html'))):
    for x in open(f, encoding='utf8', errors='ignore').read().split('rankings-page__list-item"')[1:]:
        n = re.search(r'name-link"[^>]*>([^<]*)', x); pos = re.search(r'class="position">\s*([^<]*?)\s*</div>', x)
        sch = re.search(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"', x)
        if n and pos: hs.setdefault(nm(n.group(1)), []).append((pos.group(1).strip(), school(sch.group(1)) if sch else ''))
def hs_pos(name, team):
    c = hs.get(nm(name), [])
    m = [p for p, sch in c if sch == team] or ([c[0][0]] if len(c) == 1 else [])
    return m[0] if m else None

# ---- NFL outcome, DraftTek boards -----------------------------------------------------------------------------------
dp = pd.read_csv(os.path.join(SP, 'draft_picks.csv'), low_memory=False)
dp = dp[dp.season.between(2020, 2025)].copy()
dp['k'] = dp.pfr_player_name.map(nm)
dp['sch'] = dp.college.map(school)
board = {}
for D in range(2020, 2024):
    board[D] = {}
    for pg in range(1, 7):
        f = os.path.join(SRC, f'dt_{D}_{pg}.html')
        if not os.path.exists(f): continue
        s = re.sub(r'<!--.*?-->', '', open(f, encoding='latin1').read(), flags=re.S)
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, flags=re.S):
            td = [re.sub(r'<[^>]+>', '', x).replace('&amp;', '&').replace('&#39;', "'").strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S)]
            if len(td) >= 8 and td[0].isdigit(): board[D].setdefault(nm(td[2]), int(td[0]))
moves = {(nm(r['name']), r['season']): r for r in json.load(open(os.path.join(VC, 'move_rows.json')))}

# ---- universe ---------------------------------------------------------------------------------------------------------
U = []
for g in TEST:
    rows, cz = pfn[g], {}
    for r in rows: cz.setdefault(r['season'], []).append(r['score'])
    cz = {s: (np.mean(x), np.std(x)) for s, x in cz.items()}
    by = {}
    for r in rows: by.setdefault(r['id'], {})[r['season']] = r
    for b in by.values():
        last = max(b)
        if last > 2022: continue
        r, D, n = b[last], last + 1, nm(b[last]['name'])
        cand = dp[(dp.k == n) & dp.position.isin(NFLPOS[g])]
        pk = cand[(cand.season == D) & (cand.sch == school(r['team']))]
        if pk.empty: pk = cand[cand.season == D]
        if pk.empty and (cand.season > D).any(): continue
        num = den = 0
        for k, w in enumerate(W):
            x = b.get(last - k)
            if x: v = vol(g, x); num += w * v * (x['score'] - cz[x['season']][0]) / cz[x['season']][1]; den += w * v
        team = school(r['team'])
        pg, el, hp = pfn_groups(r['name'], team, last), espn_listed(r['name'], team, last), hs_pos(r['name'], team)
        tot = sum(pg.values()) or 1
        mv = moves.get((n, last))
        rk = board[D].get(n)
        U.append(dict(g=g, last=last, name=r['name'], team=r['team'], prod=num / (den + K), lrank=math.log(rk or 700), ranked=rk is not None,
                      av=float(pk.w_av.fillna(0).iloc[0]) / (NFL_THROUGH - D + 1) if len(pk) else 0.0, drafted=len(pk) > 0,
                      pfn=int(len(pg) >= 2), pfnAlt=1 - pg.get(g, 0) / tot if pg else 0.0, pfnSet='+'.join(sorted(pg)),
                      espn=None if el is None else int(el not in FITS[g]), espnPos=el,
                      hs=None if hp is None else int(hp != 'ATH' and hp not in HS_FITS[g]), hsAth=None if hp is None else int(hp == 'ATH'), hsPos=hp,
                      move=None if mv is None else int(mv['flag'] is not None), moveTo=None if mv is None else mv['flag']))
d = pd.DataFrame(U)
d['any'] = ((d.pfn == 1) | (d.espn == 1) | (d.hs == 1)).astype(int)
d['now'] = ((d.pfn == 1) | (d.espn == 1)).astype(int)

# ---- tests --------------------------------------------------------------------------------------------------------------
def ols(X, y):
    X1 = np.column_stack([np.ones(len(X)), X]); A = X1.T @ X1 + np.eye(X1.shape[1]) * 1e-6
    return np.linalg.solve(A, X1.T @ y), A

def test(S, ctl, x):
    S = S[S[x].notna()]
    if len(S) < 40 or S[x].nunique() < 2 or S[x].sum() < 5: return None
    C = ctl(S); X = np.column_stack([C, S[x].astype(float)]); y = S.av.values
    co, A = ols(X, y); res = y - np.column_stack([np.ones(len(X)), X]) @ co
    s2 = res @ res / (len(S) - X.shape[1] - 1); se = math.sqrt(s2 * np.linalg.inv(A)[-1, -1])
    sse0 = sse1 = sst = 0
    for s in LAST:
        tr, te = S[S['last'] != s], S[S['last'] == s]
        if te.empty or len(tr) < 30: continue
        b0, _ = ols(ctl(tr), tr.av.values); b1, _ = ols(np.column_stack([ctl(tr), tr[x].astype(float)]), tr.av.values)
        p0 = np.column_stack([np.ones(len(te)), ctl(te)]) @ b0
        p1 = np.column_stack([np.ones(len(te)), ctl(te), te[x].astype(float)]) @ b1
        sse0 += ((te.av - p0) ** 2).sum(); sse1 += ((te.av - p1) ** 2).sum(); sst += ((te.av - tr.av.mean()) ** 2).sum()
    t = co[-1] / se; gain = 100 * (sse0 - sse1) / sst
    hit = S[S[x] > 0]
    return dict(n=int(len(S)), hits=int((S[x] > 0).sum()), hitsDrafted=int(hit.drafted.sum()), beta=round(float(co[-1]), 3), t=round(float(t), 2),
                oosGain=round(float(gain), 3), pass_=bool(t >= 2 and gain > 0))

A = lambda S: S[['prod']].values
B = lambda S: np.column_stack([S['prod'], S.lrank, S.lrank ** 2])
dummies = lambda S: np.column_stack([(S.g == g).astype(float) for g in TEST[1:]] + [(S.g == g) * S['prod'] for g in TEST[1:]])
pA = lambda S: np.column_stack([A(S), dummies(S)])
pB = lambda S: np.column_stack([B(S), dummies(S)])
CANDS = ['pfn', 'pfnAlt', 'espn', 'hs', 'hsAth', 'now', 'any', 'move']
out = dict(asof=pd.Timestamp.today().strftime('%Y-%m-%d'), method='see scripts/cfb_versatility_backtest.py',
           coverage=dict(players=len(d), drafted=int(d.drafted.sum()), pfn=int(d.pfn.sum()), espnLinked=int(d.espn.notna().sum()), espn=int(d.espn.fillna(0).sum()), hsLinked=int(d.hs.notna().sum()), hs=int(d.hs.fillna(0).sum()), hsAth=int(d.hsAth.fillna(0).sum()),
                         any=int(d['any'].sum()), moveRows=int(d.move.notna().sum()), move=int(d.move.fillna(0).sum())),
           pooled={c: dict(A=test(d, pA, c), B=test(d, pB, c)) for c in CANDS},
           positions={g: {c: dict(A=test(d[d.g == g], A, c), B=test(d[d.g == g], B, c)) for c in CANDS} for g in TEST})
# who the multi-position players are, and how often they're drafted against their production
out['sets'] = {g: d[(d.g == g) & (d['any'] == 1)].assign(s=lambda x: x.pfnSet + ' / ' + x.espnPos.fillna('-') + ' / ' + x.hsPos.fillna('-')).s.value_counts().head(8).to_dict() for g in TEST}
dr = lambda S: round(float(S.drafted.mean()) * 100, 1) if len(S) else None
out['draftRate'] = {g: dict(multi=dr(d[(d.g == g) & (d['any'] == 1)]), single=dr(d[(d.g == g) & (d['any'] == 0)])) for g in TEST}
out['examples'] = d[(d['any'] == 1) & d.drafted].sort_values('av', ascending=False).head(15)[['name', 'team', 'last', 'g', 'pfnSet', 'espnPos', 'hsPos', 'av']].round(2).to_dict('records')
def _nan_free(x):   # pandas leaves NaN for a missing ESPN position; NaN isn't JSON and breaks the Hugo build
    if isinstance(x, float) and x != x: return None
    if isinstance(x, dict): return {k: _nan_free(v) for k, v in x.items()}
    if isinstance(x, list): return [_nan_free(v) for v in x]
    return x


json.dump(_nan_free(out), open(OUT, 'w'), indent=1, allow_nan=False)
print(json.dumps(out['coverage']))
for c in CANDS: print('pooled', c.ljust(7), out['pooled'][c])
for g in TEST: print(g.ljust(5), '  '.join(f"{c} {v['B']['t'] if v['B'] else '-'}/{v['B']['oosGain'] if v['B'] else '-'}" for c, v in out['positions'][g].items()))
print(json.dumps(out['draftRate'])); print(json.dumps(out['sets'], indent=0))
