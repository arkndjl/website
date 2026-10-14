"""Positional backtest for the mock draft's pick step (mockDraft in scripts/cfb_teams.mjs).

Replays the 2020-25 drafts pick by pick in the real draft order (after trades): each team takes the board player
with the best mock utility, starting from the DraftTek final board through the board-to-pick curve (BOARD_PICK).
Scores each variant leave-one-draft-out on
  cnt:    sum over positions and rounds 1-3 of |simulated picks - real picks| (a draft's position-by-round shape)
  qbR1:   |simulated - real| first-round QBs
  mae100: mean |simulated - real pick| for players really taken in the top 100
  team:   the share of each team's real rounds 1-3 positions the sim also gives that team in rounds 1-3
Variants: board order; the mock's dup and run penalties; plus its QB need and set-QB block; then the candidates
for a more position-aware mock: a position x round premium (fit on the other drafts' residuals against the
board), QB urgency (a QB-needy team pays to beat the needy teams picking before its next turn to the QB it wants:
the log-pick drop to the QB it would get later), QB supply (a QB's pick moves with the number of QBs ranked
ahead of him), and recent picks (draft capital a team spent at the group in the last one or two drafts, per
starting spot, with the line as one group or as OT / G / C; the live mock carries this through fetchNflNeeds,
which counts each rookie-deal player at his draft capital, room by room). QB need per team and draft: the team's main passer the season before was outside the top 14 in
EPA a play (250+ attempts), 35 or older, or under 60% of its attempts, and it took no first-round QB in the two
drafts before. Run after scripts/draft_backtest.py (it matches the board names to picks). Writes
data/cfb_draft_sim_backtest.json. Usage: python3 scripts/draft_sim_backtest.py (needs numpy).
"""
import os, subprocess, csv, json, math, re, collections
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, 'scripts', '.cache', 'draft'); os.chdir(W)
NV = 'https://github.com/nflverse/nflverse-data/releases/download/'
get = lambda out, url: os.path.exists(out) or subprocess.run(['curl', '-sSLf', '-o', out, url])
YEARS = range(2020, 2026)
for y in YEARS: get(f'ps_{y - 1}.csv', NV + f'stats_player/stats_player_reg_{y - 1}.csv')
get('players.csv', NV + 'players/players.csv')
rows = json.load(open('rows.json'))
dp = list(csv.DictReader(open('draft_picks.csv')))
TF = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA'}
tf = lambda t: TF.get(t, t)
G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
NG = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'DE': 'EDGE', 'OLB': 'EDGE',
      'DT': 'DL', 'DL': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S', 'SAF': 'S'}
def norm(n):
    n = re.sub(r'\(.*?\)', '', n).lower().replace('.', '').replace("'", '').replace('’', '')
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n); return re.sub(r'[^a-z]', '', n)
# ---- QB need by team and draft --------------------------------------------------------------------------
born = {r['gsis_id']: r['birth_date'] for r in csv.DictReader(open('players.csv'))}
qneed = {}
for Y in YEARS:
    by = collections.defaultdict(list)
    for r in csv.DictReader(open(f'ps_{Y - 1}.csv')):
        if r['position'] == 'QB': by[tf(r['recent_team'])].append(r)
    prim = {}
    for t, L in by.items():
        r = max(L, key=lambda r: int(r['attempts'] or 0)); n = lambda k: int(r[k] or 0)
        bd = born.get(r['player_id']) or ''
        prim[t] = dict(att=n('attempts'), epa=(float(r['passing_epa'] or 0) + float(r['rushing_epa'] or 0)) / max(1, n('attempts') + n('carries') + n('sacks_suffered')),
                       age=Y - int(bd[:4]) if bd[:4].isdigit() else 28, share=n('attempts') / max(1, sum(int(x['attempts'] or 0) for x in L)))
    top = sorted([t for t in prim if prim[t]['att'] >= 250], key=lambda t: -prim[t]['epa'])[:14]
    r1 = {tf(r['team']) for r in dp if r['position'] == 'QB' and r['round'] == '1' and Y - 2 <= int(r['season']) <= Y - 1}
    for t, p in prim.items(): qneed[(Y, t)] = 0 if (t in top and p['age'] <= 34 and p['share'] >= 0.6) or t in r1 else 1
# ---- the drafts -----------------------------------------------------------------------------------------
SUB = {'T': 'OT', 'OT': 'OT', 'G': 'G', 'OG': 'G', 'C': 'C', 'OC': 'C'}   # nflverse / DraftTek line spots
NSTART = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'OT': 2, 'G': 2, 'C': 1, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2}
recent = collections.defaultdict(float); recent2 = collections.defaultdict(float)   # (draft, team, group): capital (the needs model's 1 - .13 ln pick) / starters
for r in dp:
    y, g = int(r['season']), NG.get(r['position'])
    if not g: continue
    for Y in YEARS:
        if Y - 2 <= y <= Y - 1:
            q = max(0.15, 1 - 0.13 * math.log(int(r['pick'])))
            for k in {g, SUB.get(r['position'], g)}: recent[(Y, tf(r['team']), k)] += q * (1 if y == Y - 1 else 0)
            for k in {g, SUB.get(r['position'], g)}: recent2[(Y, tf(r['team']), k)] += q * (1 if y == Y - 1 else 0.5)
order = {Y: sorted([(int(r['pick']), int(r['round']), tf(r['team']), NG.get(r['position'], 'X'), norm(r['pfr_player_name'])) for r in dp if int(r['season']) == Y]) for Y in YEARS}
def per_round(excl):   # long-run picks per position and round, 2015-25 less the test draft (the mock's perRound prior)
    c = collections.Counter(); ys = [y for y in range(2015, 2026) if y != excl]
    for r in dp:
        if int(r['season']) in ys and int(r['round']) <= 3: c[(NG.get(r['position'], 'X'), int(r['round']))] += 1
    return {(g, r): c[(g, r)] / len(ys) for g in G for r in (1, 2, 3)}
def actual(Y):
    bmap = {norm(r['name']): r['g'] for r in rows if r['year'] == Y}
    c = collections.Counter()
    for pk, rd, t, g, n in order[Y]:
        if rd <= 3: c[(bmap.get(n, g), rd)] += 1
    return c
for y in YEARS:   # each player's order at his position on the board (QB supply)
    c = collections.Counter()
    for r in sorted([r for r in rows if r['year'] == y], key=lambda r: r['rank']): c[r['g']] += 1; r['k'] = c[r['g']]
BP = json.load(open(os.path.join(ROOT, 'data', 'cfb_draft_backtest.json')))['curve']
lnx = lambda rk: BP[0] + BP[1] * math.log(rk) + BP[2] * math.log(rk) ** 2
UND = 290
# the mock's constants (cfb_teams.mjs): NEED_W, QB_DUP_LN, DUP_LN, QB_BLOCK_LN, RUN_LN; non-QB need sits at its
# league average (~.5) so a QB-needy team's edge is NEED_W x (1 - .5)
MOCK = dict(run=0.15, qbdup=1.0, dup=0.15, qbneed=True, needw=0.45, needbase=0.5, block=0.8)
def sim(Y, prm, pr, prem=None, shift=None):
    pool = [dict(r, lx=lnx(r['rank']) + (shift or {}).get(r['name'], 0)) for r in rows if r['year'] == Y and r['g'] in G and r['rank'] <= 400]
    taken = set(); tpos = collections.defaultdict(list); rc = collections.Counter(); out = {}
    od = order[Y]; qbs = sorted([p for p in pool if p['g'] == 'QB'], key=lambda p: p['lx'])
    nxt = {i: next((j for j in range(i + 1, len(od)) if od[j][2] == od[i][2]), len(od)) for i in range(len(od))}
    for i, (pk, rd, t, *_) in enumerate(od):
        ri = min(rd, 3); needy = qneed.get((Y, t), 1) if prm.get('qbneed') else 1
        later = None
        if prm.get('urg') and needy:
            comp = sum(1 for k in range(i + 1, nxt[i]) if od[k][2] != t and qneed.get((Y, od[k][2]), 0) and 'QB' not in tpos[od[k][2]])
            avq = [p for p in qbs if id(p) not in taken]
            later = avq[comp]['lx'] if comp < len(avq) else lnx(400)
        best = None
        for p in pool:
            if id(p) in taken: continue
            g = p['g']; u = -p['lx']
            if g == 'QB':
                u -= tpos[t].count('QB') * prm.get('qbdup', 0)
                if prm.get('qbneed'):
                    u += prm['needw'] * (needy - prm['needbase'])
                    if not needy and rd <= 3: u -= prm['block']
                if later is not None: u += prm['urg'] * max(0.0, later - p['lx'])
            else: u -= tpos[t].count(g) * prm.get('dup', 0)
            if prm.get('recent'):
                k = SUB.get(p['pos'], g) if prm.get('olsplit') and g == 'OL' else g
                if k != 'OL' or SUB.get(p['pos']) or not prm.get('olsplit'): u -= prm['recent'] * min(1.0, (recent2 if prm.get('lag2') else recent)[(Y, t, k)] / NSTART[k])
            if prm.get('run'):
                cap = max(1, round(pr[(g, ri)] * 1.25))
                if rc[(g, rd)] >= cap: u -= prm['run'] * (rc[(g, rd)] - cap + 1)
            if prem: u += prem.get((g, ri), 0.0)
            if best is None or u > best[0]: best = (u, p)
        if best is None: break
        p = best[1]; taken.add(id(p)); tpos[t].append(p['g']); rc[(p['g'], rd)] += 1; out[norm(p['name'])] = (pk, p['g'], rd, t)
    return out
def score(Y, res):
    act = actual(Y); sc = collections.Counter((g, rd) for pk, g, rd, t in res.values() if rd <= 3)
    # team fit: the share of each team's real rounds 1-3 positions the sim also gives that team in rounds 1-3
    bmap = {norm(r['name']): r['g'] for r in rows if r['year'] == Y}
    real = collections.Counter((t, bmap.get(n, g)) for pk, rd, t, g, n in order[Y] if rd <= 3)
    simt = collections.Counter((t, g) for pk, g, rd, t in res.values() if rd <= 3)
    team = sum((real & simt).values()) / sum(real.values())
    e = [abs(min(r['pick'], UND) - res.get(norm(r['name']), (UND,))[0]) for r in rows if r['year'] == Y and r['g'] in G and r['pick'] and r['pick'] <= 100]
    return dict(team=team, cnt=sum(abs(sc[k] - act[k]) for k in ((g, r) for g in G for r in (1, 2, 3))), qbR1=abs(sc[('QB', 1)] - act[('QB', 1)]), mae100=float(np.mean(e)), sc=sc, act=act)
def fit_prem(train, k=20.0, cap=0.5):   # minus the shrunk mean residual by position and board-implied round, net of the round's mean
    s = collections.defaultdict(list)
    for r in rows:
        if r['year'] in train and r['g'] in G and r['rank'] <= 120:
            x = math.exp(lnx(r['rank'])); ri = 1 if x <= 32 else 2 if x <= 64 else 3
            s[(r['g'], ri)].append(math.log(min(r['pick'], UND) if r['pick'] else UND) - lnx(r['rank']))
    m = {ri: np.mean([v for (g, rr), L in s.items() if rr == ri for v in L]) for ri in (1, 2, 3)}
    return {key: max(-cap, min(cap, -(sum(L) - len(L) * m[key[1]]) / (len(L) + k))) for key, L in s.items()}
def fit_supply(train):   # QB ln-pick residual on ln(QB order on the board), ridge, from the other drafts
    q = [r for r in rows if r['year'] in train and r['g'] == 'QB' and r['rank'] <= 150]
    X = np.array([[1, math.log(r['k'])] for r in q]); y = np.array([math.log(min(r['pick'], UND) if r['pick'] else UND) - lnx(r['rank']) for r in q])
    return np.linalg.solve(X.T @ X + np.diag([0, 1.0]), X.T @ y)
def run(prm, prem=False, supply=False):
    agg = collections.defaultdict(list); qb = []; SC = collections.Counter(); AC = collections.Counter()
    for Y in YEARS:
        tr = [y for y in YEARS if y != Y]; shift = None
        if supply:
            b = fit_supply(tr); shift = {r['name']: b[0] + b[1] * math.log(r['k']) for r in rows if r['year'] == Y and r['g'] == 'QB'}
        s = score(Y, sim(Y, prm, per_round(Y), fit_prem(tr) if prem else None, shift))
        for k in ('cnt', 'qbR1', 'mae100', 'team'): agg[k].append(s[k])
        qb.append([s['sc'][('QB', 1)], s['act'][('QB', 1)]]); SC.update(s['sc']); AC.update(s['act'])
    return dict(**{k: round(float(np.mean(v)), 3) for k, v in agg.items()}, qbR1_sim_real=qb,
                byRound={g: [[round(SC[(g, r)] / len(YEARS), 1), round(AC[(g, r)] / len(YEARS), 1)] for r in (1, 2, 3)] for g in G})
V = {'board order': run({}), 'dup + run penalties': run(dict(MOCK, qbneed=False)), 'mock now (+ QB need, set-QB block)': run(MOCK),
     '+ position x round premium': run(MOCK, prem=True), '+ QB supply (QB order on the board)': run(MOCK, supply=True)}
for u in (0.25, 0.5, 1.0): V[f'+ QB urgency {u}'] = run(dict(MOCK, urg=u))
for w in (0.15, 0.25, 0.45, 0.7):
    V[f'+ last draft {w} (OL one group)'] = run(dict(MOCK, recent=w))
    V[f'+ last draft {w} (OT / G / C)'] = run(dict(MOCK, recent=w, olsplit=True))
    V[f'+ last 2 drafts {w} (OT / G / C)'] = run(dict(MOCK, recent=w, olsplit=True, lag2=True))
for k, v in V.items(): print(f"{k:40s} teamfit {v['team']:.3f} cnt {v['cnt']:5.2f}  qbR1 {v['qbR1']:.2f}  mae100 {v['mae100']:5.2f}  QB R1 sim/real {v['qbR1_sim_real']}")
needy = {Y: sum(v for (y, t), v in qneed.items() if y == Y) for Y in YEARS}
json.dump({'_readme': __doc__.strip().split('\n\n')[0] + ' Leave-one-draft-out, 2020-25. byRound: [simulated, real] picks per draft in rounds 1-3.',
           'qbNeedyTeams': needy, 'variants': V}, open(os.path.join(ROOT, 'data', 'cfb_draft_sim_backtest.json'), 'w'), indent=1)
