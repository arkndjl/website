#!/usr/bin/env python3
"""Team variance profiles (team model idea 10, Oct 23 2026): does a game's spread of outcomes depend on who plays it?

Every games table prices a cover or a win as Phi(gap / sd) with one sd per sport (scripts/cover.py, the win sd in
nba_games_fit.py / cbb_games.py). Here the log sd of a game is a linear function of what is known before tip:

    tot   log of the closing total (more points, more possessions or plays: a wider margin)
    ltot  the closing total against the season-to-date league mean (the same, without the scoring era)
    spr   |closing spread| (garbage time in mismatches)
    hist  the two teams' past squared residuals (EWMA, shrunk to the league), as a log ratio to the league
    sty   the two teams' 3PA share of shots to date (NBA; ESPN team box 'sh')

fit by Gaussian maximum likelihood on the SEASONS seasons before each scored season (as cover.py fits), against the
result over the close (res - L, what cover chances use) and over the model (res - m, what win chances use).
Scored on Gaussian log loss per game, the home win log loss Phi(m / sd), and the cover log loss
Phi(b (m - L) / sd) (b from cover.py's slope), harness.paired clustered by game day x home team-season; tune seasons
and held out. Ship bar (briefs.md): tune t <= -1.5, held out no worse.

    python3 scripts/variance_research.py            # every sport -> data/variance_research.json
    VTRAIN=20 python3 scripts/variance_research.py  # fit on every season before, not the last SEASONS

FAILED, Oct 23 2026, nothing shipped (t: candidate minus the one-sd base, negative = better; tune / held):
- No term improves the home win log loss or the cover log loss in any sport. Win t's run 0 to +6 (|spread| is the
  worst: a wider sd for mismatches costs favourites win chance they keep). Fitting the sd's slope on the win log loss
  itself (not the Gaussian likelihood) also fails everywhere: best CFB ltot -0.3 / -0.15.
- The one real density effect is CBB's total: sd ~ total^0.4 (ltot: -2.2 / -2.3 on res - close, -2.1 / -3.3 on
  res - model), sd 11.0 to 11.9 over the middle 90% of games. It moves win and cover chances by under half a point and
  their log loss not at all (win -0.1 / +0.4, cover +1.6 / -1.0), so it stays out.
- 3PA style: NBA 3PA per 100 possessions -0.9 / -0.5 density, win +0.4 / -0.8; CBB 3PA share -0.7 / -2.7, win
  +1.4 / -0.2. A team's own past squared residuals (hist) is noise once shrunk (NBA -0.4 / -0.4, NFL +0.6 / -0.3).
- NBA's log total looks good with an expanding fit (-4.1 / -1.5) only because scoring rose with the era's spread of
  results; against the live last-3-seasons sd it is +2.7 held. Margins in every sport are close to homoskedastic.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
WF = os.path.join(HERE, 'data', 'games_wf')
OUT = os.path.join(ROOT, 'data', 'variance_research.json')
SEASONS = int(os.environ.get("VSEASONS", 3))
HELD = {'nba': 2023, 'cbb': 2023, 'nfl': 2023, 'cfb': 2022}   # held out from this season on
HL = 40.0          # games: half-life of a team's squared-residual memory
K = 30.0           # games of league-average squared residual a team's history starts with


def phi(z):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z) / math.sqrt(2)))


def rows_of(sport):
    r = [x for x in json.load(gzip.open(os.path.join(WF, sport + '.json.gz')))
         if x.get('res') is not None and x.get('L') is not None and x.get('m') is not None and x.get('T')]
    r.sort(key=lambda x: (x['date'], x['id']))
    return r


def style(sport):
    """game id -> {team: shot style}: NBA 3PA per 100 possessions (ESPN team box 'sh'); CBB 3PA share of FGA x 100 (cols 23-26: 2PM 2PA 3PM 3PA)
    (Barttorvik per-game player rows, joined on the Barttorvik name and ET date)"""
    out = {}
    if sport == 'nba':
        d = json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))
        for g in d['games']:
            sh = g.get('sh')
            if sh and g.get('poss'):
                out[g['id']] = {t: 100.0 * v[1] / g['poss'] for t, v in sh.items()}
    elif sport == 'cbb':
        import cbb_games as C
        games = [g for g in C.load_hist() if 'hb' in g]
        bt = {}
        for s in sorted({g['season'] for g in games}):
            p = os.path.join(C.BTLOG, f'{s}.json.gz')
            if not os.path.exists(p):
                continue
            for r in json.load(gzip.open(p)):
                try:
                    d = str(r[0]); k = (r[47], f'{d[:4]}-{d[4:6]}-{d[6:8]}')
                    v = bt.setdefault(k, [0.0, 0.0])
                    v[0] += float(r[26] or 0); v[1] += float(r[24] or 0) + float(r[26] or 0)   # 3PA; 2PA + 3PA
                except (IndexError, TypeError, ValueError):
                    continue
        for g in games:
            d = C.et_date(g['date'])
            e = {}
            for t, b in ((g['hn'], g['hb']), (g['an'], g['ab'])):
                v = bt.get((b, d))
                if v and v[1] >= 30:
                    e[t] = 100.0 * v[0] / v[1]
            if len(e) == 2:
                out[g['id']] = e
    return out


def features(sport, R):
    sty = style(sport)
    n = len(R)
    F = defaultdict(lambda: np.full(n, np.nan))
    m2 = {}          # team -> (weighted sum of y^2, weight)
    lg = [150.0 if sport in ('nba', 'nfl') else (130.0 if sport == 'cbb' else 240.0), 1.0]
    s3 = {}          # team -> (sum 3PA/100, weight) this season and last, decayed
    lg3 = [0.0, 0.0]
    seasT = defaultdict(lambda: [0.0, 0])
    a = 0.5 ** (1 / HL)
    for i, x in enumerate(R):
        h, w, S = x['home'], x['away'], x['S']
        T = float(x['T'])
        F['tot'][i] = math.log(T)
        st = seasT[S]
        F['ltot'][i] = math.log(T) - (st[0] / st[1] if st[1] >= 20 else math.log(T))
        F['spr'][i] = abs(x['L'])
        lm = lg[0] / lg[1]
        v = []
        for t in (h, w):
            s, wt = m2.get(t, (0.0, 0.0))
            v.append((s + K * lm) / (wt + K))
        F['hist'][i] = math.log(0.5 * (v[0] + v[1]) / lm)
        if sty:
            l3 = lg3[0] / lg3[1] if lg3[1] else 36.0
            v3 = []
            for t in (h, w):
                s, wt = s3.get((t, S), (0.0, 0.0))
                ps, pw = s3.get((t, S - 1), (0.0, 0.0))
                # this season to date, with last season's rate as 10 games of prior, then the league's as 5
                v3.append((s + 10 * (ps / pw if pw else l3) + 5 * l3) / (wt + 15))
            F['sty'][i] = 0.5 * (v3[0] + v3[1]) - l3
        # update after the game
        y2 = (x['res'] - x['L']) ** 2
        for t in (h, w):
            s, wt = m2.get(t, (0.0, 0.0))
            m2[t] = (a * s + y2, a * wt + 1)
        lg[0], lg[1] = 0.999 * lg[0] + y2, 0.999 * lg[1] + 1
        st[0] += math.log(T); st[1] += 1
        g = sty.get(x['id'])
        if g:
            for t in (h, w):
                if t in g:
                    s, wt = s3.get((t, S), (0.0, 0.0))
                    s3[(t, S)] = (s + g[t], wt + 1)
                    lg3[0] = 0.995 * lg3[0] + g[t]; lg3[1] = 0.995 * lg3[1] + 1
    return {k: np.array(v) for k, v in F.items()}


def mle(X, y, it=30):
    """log sd = X b, Gaussian maximum likelihood (Newton on the profile)"""
    b = np.zeros(X.shape[1]); b[0] = math.log(y.std())
    for _ in range(it):
        s2 = np.exp(2 * X @ b)
        r = y ** 2 / s2
        g = X.T @ (1 - r)
        Hm = 2 * (X * r[:, None]).T @ X + 1e-6 * np.eye(len(b))
        st = np.linalg.solve(Hm, g)
        b -= st
        if np.abs(st).max() < 1e-8:
            break
    return b


def walk(X, y, S, seasons):
    """predicted sd per row: each season fit on the SEASONS before it"""
    sd = np.full(len(y), np.nan)
    for s in seasons:
        tr = (S < s) & (S >= s - int(os.environ.get("VTRAIN", SEASONS)))
        te = S == s
        if tr.sum() < 300 or not te.any():
            continue
        ok = tr & ~np.isnan(X).any(1)
        b = mle(X[ok], y[ok])
        sd[te] = np.exp(X[te] @ b)
    return sd


def nll(y, sd):
    return np.log(sd) + 0.5 * (y / sd) ** 2 + 0.5 * math.log(2 * math.pi)


def binll(p, o):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(o * np.log(p) + (1 - o) * np.log(1 - p))


def slope(e, y):
    e0, y0 = e - e.mean(), y - y.mean()
    return float(min(1, max(0, (e0 @ y0) / (e0 @ e0))))


def run(sport):
    R = rows_of(sport)
    F = features(sport, R)
    S = np.array([x['S'] for x in R])
    yc = np.array([x['res'] - x['L'] for x in R], float)
    ym = np.array([x['res'] - x['m'] for x in R], float)
    m = np.array([x['m'] for x in R], float)
    gap = np.array([x['m'] - x['L'] for x in R], float)
    res = np.array([x['res'] for x in R], float)
    win = (res > 0).astype(float)
    push = res == np.array([x['L'] for x in R])
    covh = (yc > 0).astype(float)
    day = np.array([x['date'][:10] for x in R])
    team = np.array([f"{x['home']}|{x['S']}" for x in R])
    seasons = sorted(set(S))[SEASONS:]
    one = np.ones(len(R))
    names = ['tot', 'ltot', 'spr', 'hist'] + (['sty'] if 'sty' in F else [])
    cands = [[k] for k in names] + [['ltot', 'spr', 'hist'], names]
    cands = [c for i, c in enumerate(cands) if c not in cands[:i]]
    base_c = walk(one[:, None], yc, S, seasons)
    base_m = walk(one[:, None], ym, S, seasons)
    # cover slope b as cover.py fits it, the 3 seasons before
    bS = {s: slope(gap[(S < s) & (S >= s - SEASONS)], yc[(S < s) & (S >= s - SEASONS)]) for s in seasons}
    b = np.array([bS.get(s, 0.0) for s in S])
    held0 = HELD[sport]
    ok = ~np.isnan(base_c) & ~np.isnan(base_m)
    out = []
    for c in cands:
        X = np.column_stack([one] + [F[k] for k in c])
        okc = ok & ~np.isnan(X).any(1)
        sc = walk(X, yc, S, seasons)
        sm = walk(X, ym, S, seasons)
        full = np.column_stack([one] + [F[k] for k in c])
        coef = mle(full[okc & (S >= seasons[-1] - SEASONS + 1)], yc[okc & (S >= seasons[-1] - SEASONS + 1)])
        row = {'sport': sport, 'terms': c, 'coef_close': [round(v, 4) for v in coef]}
        for lab, k in (('tune', okc & (S < held0)), ('held', okc & (S >= held0))):
            r = {}
            r['nll_close'] = H.paired(nll(yc[k], sc[k]), nll(yc[k], base_c[k]), [day[k], team[k]])
            r['nll_model'] = H.paired(nll(ym[k], sm[k]), nll(ym[k], base_m[k]), [day[k], team[k]])
            r['win'] = H.paired(binll(phi(m[k] / sm[k]), win[k]), binll(phi(m[k] / base_m[k]), win[k]), [day[k], team[k]])
            kk = k & ~push
            r['cover'] = H.paired(binll(phi(b[kk] * gap[kk] / sc[kk]), covh[kk]),
                                  binll(phi(b[kk] * gap[kk] / base_c[kk]), covh[kk]), [day[kk], team[kk]])
            row[lab] = {a: {'d': round(v['d'], 6), 't': round(v['t'], 2), 'n': v['n']} for a, v in r.items()}
            row[lab]['sd_range'] = [round(float(np.nanpercentile(sc[k], 5)), 2), round(float(np.nanpercentile(sc[k], 95)), 2)]
        out.append(row)
        print(sport, '+'.join(c), 'coef', row['coef_close'],
              '| tune', {a: v['t'] for a, v in row['tune'].items() if a != 'sd_range'},
              '| held', {a: v['t'] for a, v in row['held'].items() if a != 'sd_range'}, row['held']['sd_range'], flush=True)
    return out


if __name__ == '__main__':
    sp = [a for a in sys.argv[1:] if a in ('nba', 'cbb', 'nfl', 'cfb')] or ['nba', 'cbb', 'nfl', 'cfb']
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    for s in sp:
        d[s] = run(s)
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)
