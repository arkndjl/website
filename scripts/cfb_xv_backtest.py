"""Backtest for XV (scripts/cfb_av.mjs XV_W, XV_C): college WAR with each player's quality measured by the parts of his
stat line that track team margin, in place of PFN's all-in-one score alone. Run by hand, after
node scripts/cfb_av_backtest.mjs (it fills the caches this reads):
    python3 scripts/cfb_xv_backtest.py -> data/cfb_xv_backtest.json

Data: PFN impact rankings (scripts/.cache/av/pfn_<pos>.json: the score and the stat line under it, FBS, every season
since 2019; OL, CB and S since 2024), ESPN results (games<season>.json), and this season's board
(static/data/cfb-all.json) for 2026 snap shares (before 2026: games played / team games, as the AV backtest).
  ratings    margin a game (SRS), points scored and points prevented a game, all opponent-adjusted (ridge least squares
             on FBS-vs-FBS games, home field, margin capped at 35, points at 63), and win% in FBS games
  parts      per position, rates from the stat line oriented so that up is good (QB completion %, net yards an attempt,
             INT rate, rush yards a game; RB yards a carry, elusiveness; OL pressure rate allowed, run-block score; EDGE
             and DT sacks and splash plays a snap; LB pressures a snap, passer rating allowed; CB passer rating and
             yards a target allowed; S plays on the ball a target...), z on the season's starter pool (the top
             STARTERS x teams by score), capped at 3 SD, missing = 0 (the pool's mean). A passer rating with no targets
             is missing (PFN lists it as 0, a perfect rating: 40 LBs in 2026). Regressing the coverage parts by
             targets (z x n / (n + k), k 10 to 40) did no better on held-out seasons (r .877 to .875), so they aren't
  fit        team SRS on each position's sum over its starters of share x (score z - SAV_REPL) plus each part's sum of
             share x z; ridge (lam 50 on standardized parts, none on the scores), a part is kept only with the sign
             football says (iteratively dropped otherwise); fit on 2024-25, the seasons with all ten positions
  tests      against season AV (the same fit on the score alone, and the shipped SAV_W), correlations on held-out
             seasons: 2025 fit -> 2024, 2024 -> 2025, 2024-25 -> 2026 (half a season, so r, not R^2, which the
             shorter season's smaller spread breaks); the same for win%, and offense (QB-OL) against points scored,
             defense against points prevented
  seven      the seven positions graded since 2019 (no OL, CB, S), each of 2019 and 2021-25 held out in turn (2020 left out)
  forward    each returning player's last-season value summed at this season's team (transfers included), against
             this season's SRS: alone, and with last season's SRS
  fvTest     XV's parts against NFL careers beyond FV's production term (the badge test; see that section)
"""
import json, math, os, re, sys, unicodedata
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'av')
OUT = os.path.join(ROOT, 'data', 'cfb_xv_backtest.json')
POS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
OFF = {'QB', 'RB', 'WR', 'TE', 'OL'}
STARTERS = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2}
SAV_W = {'QB': 2.75, 'RB': 0.82, 'WR': 0.55, 'TE': 0.28, 'OL': 0.17, 'EDGE': 0.83, 'DL': 0.23, 'LB': 0.4, 'CB': 0.72, 'S': 0.74}   # cfb_av.mjs
SAV_REPL, LAM = -1, 50
YEARS = list(range(2019, 2027))
ALIAS = {'miami fl': 'miami', 'mississippi': 'ole miss', 'usf': 'south florida', 'north carolina state': 'nc state',
         'appalachian state': 'app state', 'connecticut': 'uconn', 'louisianamonroe': 'ul monroe', 'sam houston state': 'sam houston'}
# the parts each position's value may load on, "up is good" (cfb_av.mjs xvParts computes the same from a PFN row)
PARTS = {'QB': ['cmp', 'nypa', 'intr', 'rush'], 'RB': ['ypc', 'elu'], 'WR': ['catch', 'ypr', 'epa'], 'TE': ['catch', 'epa', 'blk'],
         'OL': ['prs', 'rb', 'pb'], 'EDGE': ['prs', 'sk', 'spl'], 'DL': ['prs', 'spl', 'sk'], 'LB': ['cov', 'prs', 'tfl'],
         'CB': ['cov', 'ypt', 'ball'], 'S': ['cov', 'ball', 'ypt']}


def norm(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower().replace('&', 'and')
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', s)).strip()


def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def per(a, b):
    return None if a is None or not b else a / b


def neg(x):
    return None if x is None else -x


def parts(g, r):
    """a PFN row's parts, up = good (keep in step with xvParts in scripts/cfb_av.mjs)"""
    f = lambda k: num(r.get(k))
    gp = f('gp') or f('gamesQ'); sn = f('snaps') or f('snapsQ')
    if g == 'QB': return dict(cmp=f('cmpPct'), nypa=f('nypa'), intr=neg(per(f('int'), f('att'))), rush=per(f('ryds'), gp))
    if g == 'RB': return dict(ypc=f('ypc'), elu=f('elu'))
    if g in ('WR', 'TE'): return dict(catch=f('catch'), ypr=f('ypr'), epa=f('epaTar'), blk=f('blk'))
    if g == 'OL': return dict(prs=neg(f('prsRate')), rb=f('rbScore'), pb=f('pbScore'))
    if g in ('EDGE', 'DL'): return dict(prs=f('prsRate'), sk=per(f('sk'), sn), spl=per(f('splash'), sn))
    if g == 'LB': return dict(cov=neg(f('rtg')) if f('tgt') else None, prs=per(f('prs'), sn), tfl=per(f('tfl'), sn))
    if g in ('CB', 'S'): return dict(cov=neg(f('rtg')) if f('tar') else None, ypt=neg(per(f('yds'), f('tar'))), ball=per((f('int') or 0) + (f('pbu') or 0), f('tar')))


# ---- team ratings ---------------------------------------------------------------------------------------------
def solve_ridge(rows, ys, k_ridge):
    X, Y = np.array(rows), np.array(ys)
    return np.linalg.solve(X.T @ X + np.diag(k_ridge), X.T @ Y)


TEAM, nameId = {}, {}
for y in YEARS:
    G = [g for g in json.load(open(os.path.join(CACHE, f'games{y}.json'))) if g['done']]
    cnt = {}
    for g in G:
        for t in (g['home'], g['away']): cnt[t] = cnt.get(t, 0) + 1
        nameId[norm(g['homeName'])] = g['home']; nameId[norm(g['awayName'])] = g['away']
    fbs = [t for t in cnt if cnt[t] >= (3 if y == 2020 else 5)]
    ix, n = {t: i for i, t in enumerate(fbs)}, len(fbs)
    mr, my, pr, py, wins = [], [], [], [], {t: [0, 0] for t in fbs}
    for g in G:
        h, a = ix.get(g['home']), ix.get(g['away'])
        if h is None or a is None: continue
        hfa = 0 if g['neutral'] else 1
        r = np.zeros(n + 1); r[h], r[a], r[n] = 1, -1, hfa
        mr.append(r); my.append(max(-35, min(35, g['hs'] - g['as'])))
        for o, d, s, sg in ((h, a, g['hs'], 1), (a, h, g['as'], -1)):
            r = np.zeros(2 * n + 2); r[o], r[n + d], r[2 * n], r[2 * n + 1] = 1, -1, hfa * sg, 1
            pr.append(r); py.append(min(s, 63))
        if g['hs'] != g['as']:
            for t in (g['home'], g['away']): wins[t][1] += 1
            wins[g['home'] if g['hs'] > g['as'] else g['away']][0] += 1
    bm = solve_ridge(mr, my, [2.0] * n + [0.0])
    bp = solve_ridge(pr, py, [2.0] * (2 * n) + [0.0, 0.0])
    srs, off, dfn = bm[:n] - bm[:n].mean(), bp[:n] - bp[:n].mean(), bp[n:2 * n] - bp[n:2 * n].mean()
    for i, t in enumerate(fbs):
        TEAM[(y, t)] = dict(srs=srs[i], off=off[i], dfn=dfn[i], wp=wins[t][0] / max(1, wins[t][1]), games=cnt[t])

# ---- player seasons -------------------------------------------------------------------------------------------
allb = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-all.json')))
SHARE26 = {}
for row in allb['rows']:
    p = dict(zip(allb['cols'], row)); m = re.search(r'/(\d+)\.png', p.get('logo') or '')
    if p.get('div') == 'FBS' and p.get('snapShare') is not None and m: SHARE26[(m.group(1), norm(p['name']), p['pos'])] = p['snapShare']
rows = []
for g in POS:
    for r in json.load(open(os.path.join(CACHE, f'pfn_{g}.json'))):
        y = r['season']; k = norm(r['team']); tid = nameId.get(ALIAS.get(k, k))
        if r['division'] != 'FBS' or not tid or (y, tid) not in TEAM: continue
        sh = SHARE26.get((tid, norm(r['name']), g)) if y == 2026 else (num(r.get('gp')) or 0) / TEAM[(y, tid)]['games']
        if sh is None: continue
        rows.append(dict(id=r['id'], pos=g, season=y, tid=tid, sh=min(1.0, sh), score=r['score'], c=parts(g, r)))
for y in YEARS:
    nT = sum(1 for (yy, _) in TEAM if yy == y)
    for g in POS:
        L = [r for r in rows if r['season'] == y and r['pos'] == g]
        if not L: continue
        pool = sorted(L, key=lambda r: -r['score'])[:STARTERS[g] * nT]
        for k in ['score'] + PARTS[g]:
            get = (lambda p: p['score']) if k == 'score' else (lambda p, k=k: p['c'][k])
            v = [get(p) for p in pool if get(p) is not None]
            m, s = (float(np.mean(v)), float(np.std(v)) or 1.0) if len(v) >= 20 else (0.0, None)
            for p in L:
                x = get(p)
                p.setdefault('z', {})[k] = 0.0 if x is None or s is None else max(-3.0, min(3.0, (x - m) / s))
by = {}
for r in rows: by.setdefault((r['season'], r['tid']), []).append(r)
COLS = [(g, k) for g in POS for k in PARTS[g]]


def team_feats(y, t):
    """[score z - SAV_REPL summed over the starters by position (10)], [part sums (COLS)], [filled share by position]"""
    S, C, T = np.zeros(len(POS)), np.zeros(len(COLS)), np.zeros(len(POS))
    ps = by.get((y, t), [])
    for j, g in enumerate(POS):
        left = STARTERS[g]
        for p in sorted([p for p in ps if p['pos'] == g], key=lambda p: -p['sh']):
            s = min(p['sh'], left)
            if s <= 0: break
            left -= s; T[j] += s; S[j] += s * (p['z']['score'] - SAV_REPL)
            for i, (gg, k) in enumerate(COLS):
                if gg == g: C[i] += s * p['z'][k]
    return S, C, T


DATA = {}
for y in YEARS:
    keys = sorted(t for (yy, t) in TEAM if yy == y)
    F = [team_feats(y, t) for t in keys]
    DATA[y] = dict(t=keys, S=np.array([f[0] for f in F]), C=np.array([f[1] for f in F]),
                   Y={k: np.array([TEAM[(y, t)][k] for t in keys]) for k in ('srs', 'off', 'dfn', 'wp')})


def fit(train, pos=POS, use_parts=True, lam=LAM):
    """weights: score by position (unpenalized) + parts (ridge, sign-constrained by dropping)"""
    js = [POS.index(g) for g in pos]
    ci = [i for i, (g, _) in enumerate(COLS) if g in pos] if use_parts else []
    S = np.vstack([DATA[y]['S'][:, js] for y in train]); C = np.vstack([DATA[y]['C'][:, ci] for y in train]) if ci else np.zeros((len(S), 0))
    Y = np.concatenate([DATA[y]['Y']['srs'] for y in train])
    sdC = C.std(0) + 1e-9 if ci else np.zeros(0)
    act = list(range(len(ci)))
    while True:
        M = np.hstack([S, C[:, act] / sdC[act]]); Mc = M - M.mean(0)
        b = np.linalg.solve(Mc.T @ Mc + np.diag([0.0] * len(js) + [lam] * len(act)), Mc.T @ (Y - Y.mean()))
        bad = [a for i, a in enumerate(act) if b[len(js) + i] < 0]
        if not bad: break
        act.remove(min(bad, key=lambda a: b[len(js) + act.index(a)]))
    w = {g: float(b[i]) for i, g in enumerate(pos)}
    c = {COLS[ci[a]]: float(b[len(js) + i] / sdC[a]) for i, a in enumerate(act)}
    return w, c


def team_value(y, w, c, side=None):
    keep = lambda g: side is None or (g in OFF) == (side == 'off')
    v = sum(w[g] * DATA[y]['S'][:, POS.index(g)] for g in w if keep(g))
    return v + sum(x * DATA[y]['C'][:, COLS.index(k)] for k, x in c.items() if keep(k[0]))


r3 = lambda x: round(float(x), 3)
cor = lambda a, b: r3(np.corrcoef(a, b)[0, 1])
SPLITS = [([2025], 2024), ([2024], 2025), ([2024, 2025], 2026)]
tests = {}
for train, test in SPLITS:
    Y = DATA[test]['Y']; out = {}
    for name, (w, c) in (('seasonAvShipped', (SAV_W, {})), ('seasonAvRefit', fit(train, use_parts=False)), ('xv', fit(train))):
        out[name] = dict(srs=cor(team_value(test, w, c), Y['srs']), winPct=cor(team_value(test, w, c), Y['wp']),
                         offense=cor(team_value(test, w, c, 'off'), Y['off']), defense=cor(team_value(test, w, c, 'def'), Y['dfn']))
    tests[str(test)] = dict(train=train, teams=len(Y['srs']), **out)
mean_of = lambda m, k: r3(np.mean([tests[str(t)][m][k] for _, t in SPLITS]))
summary = {m: {k: mean_of(m, k) for k in ('srs', 'winPct', 'offense', 'defense')} for m in ('seasonAvShipped', 'seasonAvRefit', 'xv')}

# seven positions graded since 2019, each season held out
P7 = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']
SEV = [2019, 2021, 2022, 2023, 2024, 2025]
seven = {}
for test in SEV:
    train = [y for y in SEV if y != test]
    seven[str(test)] = {name: cor(team_value(test, *fit(train, P7, up)), DATA[test]['Y']['srs']) for name, up in (('seasonAv', False), ('xv', True))}


# forward: last season's value of returning players at this season's team
def r2_of(Y, cols):
    A = np.column_stack([np.ones(len(Y))] + cols); b = np.linalg.lstsq(A, Y, rcond=None)[0]
    return r3(1 - ((Y - A @ b) ** 2).sum() / ((Y - Y.mean()) ** 2).sum())


def pval(p, w, c):
    g = p['pos']
    return p['sh'] * (w[g] * (p['z']['score'] - SAV_REPL) + sum(x * p['z'][k] for (gg, k), x in c.items() if gg == g))


forward = {}
for y, train in ((2025, [2024]), (2026, [2024, 2025])):
    prev = {(p['id'], p['pos']): p for p in rows if p['season'] == y - 1}
    ts = [t for t in DATA[y]['t'] if (y - 1, t) in TEAM]
    Y, L = np.array([TEAM[(y, t)]['srs'] for t in ts]), np.array([TEAM[(y - 1, t)]['srs'] for t in ts])
    out = {'lastSrs': r2_of(Y, [L])}
    for name, (w, c) in (('seasonAv', fit(train, use_parts=False)), ('xv', fit(train))):
        ret = {}
        for p in rows:
            q = prev.get((p['id'], p['pos'])) if p['season'] == y else None
            if q: ret[p['tid']] = ret.get(p['tid'], 0) + pval(q, w, c)
        R = np.array([ret.get(t, 0) for t in ts])
        out[name] = dict(returning=r2_of(Y, [R]), withLastSrs=r2_of(Y, [L, R]))
    forward[str(y)] = dict(train=train, teams=len(ts), **out)

# the live weights: 2024-25, and each position's spread (points a game per SD of quality, full-time starters)
W, C = fit([2024, 2025])
spread = {}
for g in POS:
    st = [p for p in rows if p['season'] in (2024, 2025) and p['pos'] == g and p['sh'] >= 0.5]
    q = [W[g] * p['z']['score'] + sum(x * p['z'][k] for (gg, k), x in C.items() if gg == g) for p in st]
    spread[g] = dict(seasonAv=SAV_W[g], xv=r3(np.std(q)), scoreShare=r3(W[g] ** 2 * np.var([p['z']['score'] for p in st]) / max(1e-9, np.var(q))))


# ---- FV: do XV's parts predict NFL careers beyond production (and the badges FV already uses)? ----------------
# The FV badge test (scripts/cfb_badge_backtest.mjs): each player's last PFN season 2019-22 at the seven positions graded
# then, NFL weighted AV a season through 2025 (undrafted 0; a player in a later draft dropped), production = FV's blend
# (score z on the season's FBS curve, 5/4/3 by snap volume, K 3000). screen: each part's last-season z (starter pool, as
# XV uses it) beyond production; shipped: the two that pass as scripts/fetch_cfb.mjs FV_XV measures them (regressed by
# volume like a badge, z among 100+ snap players), LB holding FV's Tackler badge fixed too. Pass: t >= 2 and a
# leave-one-final-season-out gain. Badge-style weight = FV_W.pfn (.4) x b / b_prod x 1/2
import csv
NFLPOS = {'QB': ['QB'], 'RB': ['RB', 'FB'], 'WR': ['WR'], 'TE': ['TE'], 'EDGE': ['DE', 'OLB', 'EDGE', 'DL'], 'DL': ['DT', 'DE', 'DL', 'NT'], 'LB': ['LB', 'ILB', 'OLB', 'MLB']}
SPG = {'QB': 65, 'RB': 30, 'WR': 40, 'TE': 40, 'EDGE': 50, 'DL': 45, 'LB': 55}
nmk = lambda s: re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', re.sub(r'[^a-z ]', '', unicodedata.normalize('NFKD', s or '').lower()))).strip()
picks = {}
for pk in csv.DictReader(open(os.path.join(CACHE, 'draft_picks.csv'))):
    if 2020 <= int(pk['season']) <= 2025: picks.setdefault(nmk(pk['pfr_player_name']), []).append(pk)
RAW = {(r['id'], g, r['season']): r for g in P7 for r in json.load(open(os.path.join(CACHE, f'pfn_{g}.json'))) if r['division'] == 'FBS'}
snapv = lambda r: num(r.get('snapsQ')) or num(r.get('snaps')) or ((num(r.get('gp')) or num(r.get('gamesQ')) or 0) * 55 or None)
BADGE = {'LB': {'tackler': (lambda r: neg(num(r.get('mt'))), lambda r: num(r.get('tkl')), 180),
                'cov': (lambda r: neg(num(r.get('rtg'))) if num(r.get('tgt')) else None, lambda r: num(r.get('tgt')), 400)},
         'EDGE': {'sk': (lambda r: per(num(r.get('sk')), snapv(r)), snapv, 2000)}}
BZ = {}
for g, st in BADGE.items():
    for y in YEARS:
        pool = [(k, r) for k, r in RAW.items() if k[1] == g and k[2] == y and (snapv(r) or 0) >= 100]
        for name, (val, vol, half) in st.items():
            xs = [(k, val(r), max(0, vol(r) or 0)) for k, r in pool]; xs = [x for x in xs if x[1] is not None]
            if len(xs) < 20: continue
            nw = sum(x[2] for x in xs); m = sum(x[2] * x[1] for x in xs) / nw
            reg = np.array([m + (v - m) * n / (n + half) for _, v, n in xs])
            for (k, _, _), z in zip(xs, (reg - reg.mean()) / reg.std()): BZ[(k, name)] = z


def last_seasons(g):
    R = [r for r in rows if r['pos'] == g]; cz, by, P = {}, {}, []
    for r in R: cz.setdefault(r['season'], []).append(r['score']); by.setdefault(r['id'], {})[r['season']] = r
    cz = {y: (np.mean(v), np.std(v)) for y, v in cz.items()}
    for sea in by.values():
        last = max(sea); r = sea[last]; D = last + 1
        if last > 2022: continue
        cand = [pk for pk in picks.get(nmk(RAW[(r['id'], g, last)]['name']), []) if pk['position'] in NFLPOS[g]]
        pk = next((x for x in cand if int(x['season']) == D), None)
        if not pk and any(int(x['season']) > D for x in cand): continue
        nu = de = 0
        for k, w in enumerate([5, 4, 3]):
            x = sea.get(last - k)
            if x:
                v = x['sh'] * TEAM[(x['season'], x['tid'])]['games'] * SPG[g]; nu += w * v * (x['score'] - cz[x['season']][0]) / cz[x['season']][1]; de += w * v
        p = dict(last=last, prod=nu / (de + 3000), av=float(pk['w_av'] or 0) / (2025 - D + 1) if pk else 0.0, **{'z:' + k: r['z'][k] for k in PARTS[g]})
        for name in BADGE.get(g, {}): p['b:' + name] = BZ.get(((r['id'], g, last), name), 0.0)
        P.append(p)
    return P


def beyond(P, base, x):
    Y, L = np.array([p['av'] for p in P]), np.array([p['last'] for p in P])
    B = np.column_stack([[p[b] for p in P] for b in ['prod'] + base]); X = np.array([p[x] for p in P])
    res_ = lambda M, y: y - np.column_stack([np.ones(len(y)), M]) @ np.linalg.lstsq(np.column_stack([np.ones(len(y)), M]), y, rcond=None)[0]
    pr = float(np.corrcoef(res_(B, X), res_(B, Y))[0, 1]); t = pr * math.sqrt((len(P) - 2 - B.shape[1]) / (1 - pr * pr))
    sse = [0.0, 0.0]; sst = 0.0
    for s in set(L):
        tr, te = L != s, L == s
        for i, M in enumerate((B, np.column_stack([B, X]))):
            A = np.column_stack([np.ones(tr.sum()), M[tr]]); b = np.linalg.lstsq(A, Y[tr], rcond=None)[0]
            sse[i] += float(((Y[te] - np.column_stack([np.ones(te.sum()), M[te]]) @ b) ** 2).sum())
        sst += float(((Y[te] - Y[tr].mean()) ** 2).sum())
    Ms = np.column_stack([B, X]); Ms = (Ms - Ms.mean(0)) / Ms.std(0)
    beta = np.linalg.lstsq(np.column_stack([np.ones(len(Y)), Ms]), (Y - Y.mean()) / Y.std(), rcond=None)[0][1:]
    return dict(n=len(P), partial=r3(pr), t=round(t, 2), oosGain=r3(100 * (sse[0] - sse[1]) / sst), pass_=bool(t >= 2 and sse[1] < sse[0]),
                fvWeight=r3(0.4 * beta[-1] / beta[0] * 0.5))


fvTest = dict(screen={}, shipped={})
for g in P7:
    P = last_seasons(g)
    fvTest['screen'][g] = {k: beyond(P, [], 'z:' + k) for k in PARTS[g] if np.std([p['z:' + k] for p in P]) > 0}
    if g == 'LB': fvTest['shipped']['LB.cov'] = beyond(P, ['b:tackler'], 'b:cov')
    if g == 'EDGE': fvTest['shipped']['EDGE.sk'] = beyond(P, [], 'b:sk')
res = dict(asof=str(np.datetime64('today')), lam=LAM, weights=dict(score={g: r3(v) for g, v in W.items()}, parts={f'{g}.{k}': round(v, 4) for (g, k), v in C.items()}),
           spread=spread, summary=summary, tests=tests, seven=seven, forward=forward, fvTest=fvTest)
json.dump(res, open(OUT, 'w'), indent=1)
print(json.dumps(dict(summary=summary, seven=seven, forward=forward), indent=1))
print('XV_W', {g: round(v, 2) for g, v in W.items()})
print('XV_C', {f'{g}.{k}': round(v, 4) for (g, k), v in C.items()})
print('spread', {g: s['xv'] for g, s in spread.items()})
print('fvTest shipped', fvTest['shipped'])
for g, d in fvTest['screen'].items(): print('  screen', g, {k: (v['t'], v['oosGain']) for k, v in d.items()})
