# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Roster-aware team need for the NFL mock draft (mockDraft in scripts/cfb_teams.mjs), tested on real drafts.

History first (nflverse draft picks, 2002-26): a first-round pick is at the
position the team took in round 1 the year before about half as often as the draft's position mix implies.

Test: a conditional logit on the real picks of rounds 1-3, 2020-26 (each pick a choice among the board players still
on the board, DraftTek final big boards, in the real order after trades). The base utility is the mock's: the board's
log-pick (BOARD_PICK curve), QB need and the set-QB block (draft_sim_backtest.py), and a second player at a position
in one draft. Candidates added one at a time and together, scored leave-one-draft-out (fit on six drafts, held-out
log likelihood per pick on the seventh):
  rep1 / rep2  the team took this position in round 1 one / two drafts before
  rep1r2       ... in round 2 the draft before
  cap          rookie-deal capital at the position, last three drafts (1 - .13 ln pick) per starting spot: the live
               needs model's way of counting recent picks (fetchNflNeeds)
  war          our NFL WAR (scripts/nfl_war.py, rebuilt for each season before the draft): the team's best
               starters' WAR at the position, as need = its rank among the 32 teams (1 = weakest room)
  warage       the same with each player's WAR aged to next season (-12% a year past 29)
Coefficients are per unit of the board's log-pick, so they read in the mock's utility units (log-pick).
Writes data/cfb_mock_roster_backtest.json. Run after scripts/draft_backtest.py and scripts/draft_sim_backtest.py
(caches in scripts/.cache/draft); needs scripts/.cache/mock/warhist.json (nfl_war.board for 2018-25).
"""
import os, csv, json, math, re, collections, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, 'scripts', '.cache', 'draft')
rows = json.load(open(os.path.join(W, 'rows7.json')))
dp = list(csv.DictReader(open(os.path.join(W, 'draft_picks.csv'))))
TF = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'GNB': 'GB', 'KAN': 'KC', 'NWE': 'NE', 'NOR': 'NO', 'SFO': 'SF', 'TAM': 'TB', 'LVR': 'LV', 'SDG': 'LAC'}   # PFR draft codes to nflverse stats codes
tf = lambda t: TF.get(t, t)
G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
NG = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'DE': 'EDGE', 'OLB': 'EDGE',
      'DT': 'DL', 'DL': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S', 'SAF': 'S'}
NSTART = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2}
YEARS = list(range(2020, 2027))
def norm(n):
    n = re.sub(r'\(.*?\)', '', n).lower().replace('.', '').replace("'", '').replace('’', '')
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n); return re.sub(r'[^a-z]', '', n)
# ---- history: R1 at last year's R1 position ------------------------------------------------------------------
byTR = collections.defaultdict(list)
for r in dp:
    byTR[(int(r['season']), tf(r['team']), int(r['round']))].append(NG.get(r['position'], 'X'))
def repeat_rate(lag, rd, y0=2002, y1=2026):
    obs = exp = var = 0.0; n = 0
    for (y, t, rr), gs in byTR.items():
        if rr != 1 or not y0 <= y <= y1: continue
        prev = set(byTR.get((y - lag, t, rd), []))
        if not prev: continue
        mix = collections.Counter(g for (yy, _, r2), L in byTR.items() if yy == y and r2 == 1 for g in L); N = sum(mix.values())
        for g in gs:
            p = sum(mix[h] for h in prev) / N; n += 1; obs += g in prev; exp += p; var += p * (1 - p)
    return dict(n=n, obs=int(obs), exp=round(exp, 1), ratio=round(obs / exp, 2), z=round((obs - exp) / math.sqrt(var), 2))
# ---- QB need (draft_sim_backtest.py's rule) ------------------------------------------------------------------
born = {r['gsis_id']: r['birth_date'] for r in csv.DictReader(open(os.path.join(W, 'players.csv')))}
qneed = {}
for Y in YEARS:
    by = collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(W, f'ps_{Y - 1}.csv'))):
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
# ---- recent picks ---------------------------------------------------------------------------------------------
rep = collections.defaultdict(float)   # (Y, team, group, key) -> count
cap = collections.defaultdict(float)
for r in dp:
    y, g, rd = int(r['season']), NG.get(r['position']), int(r['round'])
    if not g: continue
    for Y in YEARS:
        if y == Y - 1 and rd == 1: rep[(Y, tf(r['team']), g, 'rep1')] = 1
        if y == Y - 2 and rd == 1: rep[(Y, tf(r['team']), g, 'rep2')] = 1
        if y == Y - 1 and rd == 2: rep[(Y, tf(r['team']), g, 'rep1r2')] = 1
        if Y - 3 <= y <= Y - 1: cap[(Y, tf(r['team']), g)] += max(0.15, 1 - 0.13 * math.log(int(r['pick'])))
# ---- our WAR: each room's starters the season before the draft --------------------------------------------------
WH = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'mock', 'warhist.json')))
def room_need(age):
    need = {}
    for Y in YEARS:
        room = collections.defaultdict(list)
        for r in WH[str(Y - 1)]:
            if r['pos'] not in NSTART: continue
            w = r['war']
            if age and r.get('age'): w *= 0.88 ** max(0, r['age'] + 1 - 30)
            room[(tf(r['t']), r['pos'])].append(w)
        teams = sorted({t for t, _ in room})
        for g in G:
            s = {t: sum(sorted(room.get((t, g), []), reverse=True)[:NSTART[g]]) for t in teams}
            order = sorted(teams, key=lambda t: s[t])            # weakest first
            for i, t in enumerate(order): need[(Y, t, g)] = 1 - i / (len(order) - 1)
    return need
WAR, WARA = room_need(False), room_need(True)
BP = json.load(open(os.path.join(ROOT, 'data', 'cfb_draft_backtest.json')))['curve']
lnx = lambda rk: BP[0] + BP[1] * math.log(rk) + BP[2] * math.log(rk) ** 2
FEATS = ['lx', 'qbneed', 'qbblock', 'dup', 'rep1', 'rep2', 'rep1r2', 'cap', 'war', 'warage', 'war_c', 'warage_c']
# ---- choice sets ------------------------------------------------------------------------------------------------
def choice_sets(maxround=3):
    out = []
    for Y in YEARS:
        board = [r for r in rows if r['year'] == Y and r['g'] in G and r['rank'] <= 400]
        bn = {norm(r['name']): r for r in board}
        byPick = {r['pick']: r for r in board if r['pick']}
        taken = set(); tpos = collections.defaultdict(list)
        for d in sorted([d for d in dp if int(d['season']) == Y], key=lambda d: int(d['pick'])):
            pk, rd, t = int(d['pick']), int(d['round']), tf(d['team'])
            if rd > maxround: break
            ch = byPick.get(pk)
            avail = [r for r in board if id(r) not in taken]
            if ch is not None and avail:
                X = np.zeros((len(avail), len(FEATS))); y = None
                for i, r in enumerate(avail):
                    g = r['g']; f = dict(lx=-lnx(r['rank']))
                    if g == 'QB':
                        f['qbneed'] = qneed.get((Y, t), 1); f['qbblock'] = 1 - qneed.get((Y, t), 1)
                    f['dup'] = tpos[t].count(g)
                    for k in ('rep1', 'rep2', 'rep1r2'): f[k] = rep[(Y, t, g, k)]
                    f['cap'] = min(1.0, cap[(Y, t, g)] / NSTART[g])
                    f['war'] = WAR.get((Y, t, g), 0.5); f['warage'] = WARA.get((Y, t, g), 0.5)
                    f['war_c'] = f['war'] - 0.5; f['warage_c'] = f['warage'] - 0.5
                    X[i] = [f.get(k, 0.0) for k in FEATS]
                    if r is ch: y = i
                out.append(dict(Y=Y, rd=rd, X=X, y=y))
            r = ch if ch is not None else None
            if r is not None: taken.add(id(r)); tpos[t].append(r['g'])
            else: tpos[t].append(NG.get(d['position'], 'X'))
    return out
def fit(sets, cols, ridge=1e-3, it=40):
    b = np.zeros(len(cols)); b[0] = 1.0
    for _ in range(it):
        g = np.zeros(len(cols)); H = np.zeros((len(cols), len(cols)))
        for s in sets:
            X = s['X'][:, cols]; u = X @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
            m = p @ X; g += X[s['y']] - m; H -= (X * p[:, None]).T @ X - np.outer(m, m)
        g -= ridge * b; H -= ridge * np.eye(len(cols))
        step = np.linalg.solve(H, g); b -= step
        if np.abs(step).max() < 1e-7: break
    return b
def ll(sets, cols, b):
    out = []
    for s in sets:
        u = s['X'][:, cols] @ b; u -= u.max(); out.append(u[s['y']] - math.log(np.exp(u).sum()))
    return out
def lodo(sets, base, add, rounds=(1, 2, 3)):
    cb = [FEATS.index(k) for k in base]; ca = cb + [FEATS.index(k) for k in add]
    per = []
    for Y in YEARS:
        tr = [s for s in sets if s['Y'] != Y]; te = [s for s in sets if s['Y'] == Y and s['rd'] in rounds]
        b0, b1 = fit(tr, cb), fit(tr, ca)
        per.append(float(np.sum(ll(te, ca, b1)) - np.sum(ll(te, cb, b0))))
    bA = fit(sets, ca)
    m, sd = np.mean(per), np.std(per, ddof=1)
    return dict(add=add, dLL=[round(x, 2) for x in per], mean=round(float(m), 3), t=round(float(m / (sd / math.sqrt(len(per)))), 2) if sd > 0 else None,
                wins=sum(x > 0 for x in per), coef_logpick={k: round(float(bA[i] / bA[0]), 3) for i, k in enumerate(base + add) if i})
if __name__ == '__main__':
    hist = {'R1 at last draft\'s R1 position': repeat_rate(1, 1), 'R1 at the R1 position two drafts back': repeat_rate(2, 1),
            'R1 at last draft\'s R2 position': repeat_rate(1, 2), '2020-26 only (R1 on R1)': repeat_rate(1, 1, 2020)}
    for k, v in hist.items(): print(k, v)
    S = choice_sets()
    print('picks', len(S), {Y: sum(s['Y'] == Y for s in S) for Y in YEARS})
    base = ['lx', 'qbneed', 'qbblock', 'dup']
    V = {}
    for add in (['rep1'], ['rep2'], ['rep1r2'], ['rep1', 'rep2'], ['rep1', 'rep2', 'rep1r2'], ['cap'], ['war_c'], ['warage_c'],
                ['cap', 'rep1', 'rep2'], ['warage_c', 'rep1', 'rep2'], ['cap', 'warage_c', 'rep1', 'rep2'], ['cap', 'warage_c', 'rep1', 'rep2', 'rep1r2']):
        r = lodo(S, base, add); V['+' + '+'.join(add)] = r
        print(f"{'+'.join(add):35s} dLL {r['mean']:7.3f} t {r['t']}  wins {r['wins']}/7  {r['dLL']}  coef {r['coef_logpick']}")
    # round 1 only (the picks Noah flagged), the full candidate set
    r1 = {}
    for add in (['rep1', 'rep2'], ['warage_c'], ['cap', 'warage_c', 'rep1', 'rep2']):
        r = lodo(S, base, add, rounds=(1,)); r1['+' + '+'.join(add)] = r
        print(f"R1 only {'+'.join(add):27s} dLL {r['mean']:7.3f} t {r['t']}  wins {r['wins']}/7  {r['dLL']}")
    json.dump({'_readme': __doc__.strip().split('\n\n')[0], 'history': hist, 'picks': len(S), 'base': base, 'lodo': V, 'round1': r1},
              open(os.path.join(ROOT, 'data', 'cfb_mock_roster_backtest.json'), 'w'), indent=1)
