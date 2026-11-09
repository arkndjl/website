# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Postseason-only layer research: do playoff games follow the regular-season game model, or do
some team traits (star concentration, goaltending, form, strength against good teams, experience, rest, variance)
predict playoff results beyond it?

Baseline: each sport's walk-forward game model (scripts/data/games_wf/<sport>.json.gz) on postseason games, as the
season sims play them. Layer: logit p = a x baseline logit + c x (not neutral) + sum b_k x (home trait k - away trait k),
fit on postseason games only. Traits come from that team's regular season (no playoff game feeds its own traits).

Honest test: leave one season out. Inside each training fold the trait set is chosen by greedy forward selection on an
inner leave-one-season-out, so the held-out season never helps pick features. Scored on log loss and Brier, paired
by game (t) and by season (wins), plus calibration bins. A sport ships only when the held-out layer beats the
baseline (t <= -2 on log loss, better in most seasons).

    python3 scripts/postseason_research.py            # all sports -> data/postseason_research.json
    python3 scripts/postseason_research.py nba nhl    # some
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, 'scripts', 'data', 'games_wf')
OUT = os.path.join(ROOT, 'data', 'postseason_research.json')
SD = {'nfl': 12.86, 'nba': 12.25, 'cbb': 11.5}     # the game models' win sd (data/<sport>_games_fit.json)
LAM = 4.0                                          # ridge on the trait betas (standardized traits) and on a - 1


def Phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def day(s):
    return datetime.fromisoformat(s[:10]).toordinal()


def load(s):
    return json.load(gzip.open(os.path.join(WF, s + '.json.gz')))


# ------------------------------------------------------------------ games (baseline logit, result, season, teams)
def rows_for(sport):
    """[{S, d, h, a, z, y, po, n, res, m, mk}] for every finished game; z is the model's home-win logit, mk the market's"""
    out = []
    if sport == 'nhl':
        for g in load('nhl'):
            if g.get('hs') is None or g.get('p') is None:
                continue
            c = g.get('c') or {}
            out.append({'S': g['S'], 'd': day(g['day']), 'h': g['h'], 'a': g['a'], 'z': logit(g['p']),
                        'y': float(g['hs'] > g['as']), 'po': g['po'], 'n': 0, 'res': g['hs'] - g['as'], 'm': g['m'],
                        'mk': logit(c['p']) if c.get('p') else None, 'id': str(g['id'])})
        return out
    if sport == 'soccer':
        # UEFA knockout rounds (Champions League and Europa League, February on); draws dropped so each game is a
        # binary home-win chance given a winner, logit = log(p home / p away). Season = the August-May season
        for g in load('soccer'):
            if g.get('hs') is None or g['hs'] == g['as'] or not g.get('p'):
                continue
            y, mo = int(g['day'][:4]), int(g['day'][5:7])
            sy = y if mo >= 7 else y - 1
            po = int(g['lg'] in ('uefa.champions', 'uefa.europa') and 2 <= mo <= 6)
            ph, pd, pa = g['p']
            out.append({'S': sy, 'd': day(g['day']), 'h': g['h'], 'a': g['a'], 'z': math.log(ph / pa),
                        'y': float(g['hs'] > g['as']), 'po': po, 'n': 0, 'res': g['hs'] - g['as'],
                        'm': g['l'][0] - g['l'][1], 'mk': None, 'id': str(g['id'])})
        return out
    ncaa = None
    if sport == 'cbb':
        th = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cbb_tourney_hist.json')))
        ncaa = {g['id'] for v in th.values() for g in v.get('ncaa', [])}
    for g in load(sport):
        if g.get('res') is None or g['res'] == 0 or g.get('m') is None:
            continue
        sd = g.get('sigma') or SD[sport]
        if sport == 'cfb':
            po = int((g.get('wk') or 0) >= 16)
        elif sport == 'cbb':
            po = int(g['id'] in ncaa)
            if g.get('po') and not po:
                po = 2                               # conference tournaments: neither regular season nor the title event
        else:
            po = g.get('po', 0)
        out.append({'S': g['S'], 'd': day(g['date']), 'h': g['home'], 'a': g['away'], 'z': logit(Phi(g['m'] / sd)),
                    'y': float(g['res'] > 0), 'po': po, 'n': int(g.get('neutral') or 0), 'res': g['res'], 'm': g['m'],
                    'mk': logit(Phi(g['L'] / sd)) if g.get('L') is not None else None, 'id': str(g['id']),
                    'tot': g.get('tot'), 'sd': sd})
    return out


# ------------------------------------------------------------------ team traits from the regular season
def generic_traits(rows):
    """(S, team) -> trait dict from that season's regular-season games: form (residual over the last stretch),
    vsgood (residual against the top third), rsd (residual sd), mgap (market minus model, last stretch), str (mean
    expected margin: model strength), exp (playoff games the season before), rest is per game"""
    by = defaultdict(list)
    po_games = defaultdict(int)
    for r in rows:
        if r['po'] == 0:
            for t, sgn in ((r['h'], 1), (r['a'], -1)):
                by[(r['S'], t)].append((r['d'], sgn * (r['res'] - r['m']), sgn * r['m'], r, sgn))
        elif r['po'] == 1:
            po_games[(r['S'], r['h'])] += 1
            po_games[(r['S'], r['a'])] += 1
    mean_m = {k: np.mean([x[2] for x in v]) for k, v in by.items()}
    tr = {}
    for (S, t), v in by.items():
        v.sort(key=lambda x: x[0])
        res = np.array([x[1] for x in v])
        k = max(4, len(v) // 4)
        # the opponents' strength: their own season mean expected margin
        opp = [(x[1], mean_m.get((S, x[3]['a'] if x[4] == 1 else x[3]['h']), 0.0)) for x in v]
        cut = np.quantile([mean_m[q] for q in mean_m if q[0] == S], 2 / 3)
        good = [e for e, o in opp if o >= cut]
        gap = []
        for x in v[-k:]:
            r = x[3]
            if r['mk'] is not None:
                gap.append(x[4] * (r['mk'] - r['z']))
        tr[(S, t)] = {'form': float(res[-k:].mean()), 'vsgood': float(np.mean(good)) if len(good) >= 2 else 0.0,
                      'rsd': float(res.std()), 'mgap': float(np.mean(gap)) if gap else 0.0,
                      'str': float(np.mean([x[2] for x in v])),
                      'exp': math.log1p(po_games.get((S - 1, t), 0)), 'last': v[-1][0]}
    return tr


def nba_traits():
    """(S, team) -> star (top-two players' share of the team's box value), top1 (best player's box value a game),
    three (3PA a possession), pace (possessions)"""
    gh = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
    pb = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_pbox_hist.json.gz')))
    val = defaultdict(lambda: defaultdict(float))
    gp = defaultdict(int)
    sh = defaultdict(lambda: [0.0, 0.0, 0])
    for g in gh:
        if g.get('t') == 3 or not g.get('fin'):
            continue
        S = g['S']
        if g.get('sh') and g.get('poss'):
            for t in (g['h'], g['a']):
                if t in g['sh']:
                    x = sh[(S, t)]
                    x[0] += g['sh'][t][1]; x[1] += g['poss']; x[2] += 1
        b = pb.get(g['id'])
        if not b:
            continue
        for t, ps in b.items():
            gp[(S, t)] += 1
            for p in ps:
                mn, pts, reb, ast, f3, stl, blk, tov, fga, fta = p[4:14]
                f3m = f3 if isinstance(f3, (int, float)) else 0
                v = pts + 0.3 * reb + 0.7 * ast + stl + 0.7 * blk - tov - 0.45 * fga - 0.2 * fta + 0 * f3m
                val[(S, t)][p[0]] += v
    out = {}
    for k in set(list(val) + list(sh)):
        d = {}
        if k in val and gp[k] >= 20:
            vs = sorted((max(x, 0.0) for x in val[k].values()), reverse=True)
            tot = sum(vs) or 1.0
            d['star'] = (vs[0] + vs[1]) / tot
            d['top1'] = vs[0] / gp[k]
        if k in sh and sh[k][2] >= 20:
            d['three'] = sh[k][0] / sh[k][1]
            d['pace'] = sh[k][1] / sh[k][2]
        out[k] = d
    return out


def nhl_traits():
    """(S, team) -> gsax (the team's goalies' goals saved above expected a game), xgs (xG share, all situations),
    g1 (the top goalie's share of starts: one clear starter)"""
    gh = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nhl_games_hist.json.gz')))
    xf = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    st = defaultdict(lambda: defaultdict(int))
    for g in gh:
        if g['po'] or not g.get('final') or 'x' not in g:
            continue
        S = g['S']
        for t, o in (('h', 'a'), ('a', 'h')):
            team = g[t]
            x = xf[(S, team)]
            x[0] += g['x'][t][1]; x[1] += g['x'][o][1]; x[2] += g['hs'] if o == 'h' else g['as']; x[3] += 1
            for row in (g.get('gl') or {}).get(t, []):
                if row[2]:
                    st[(S, team)][row[0]] += 1
    out = {}
    for k, x in xf.items():
        if x[3] < 20:
            continue
        s = st.get(k, {})
        out[k] = {'gsax': (x[1] - x[2]) / x[3], 'xgs': x[0] / max(x[0] + x[1], 1e-6),
                  'g1': max(s.values()) / max(sum(s.values()), 1) if s else 0.5}
    return out


def cbb_traits():
    """(S, team name) -> seed gap (committee seed line vs the rating's rank among the field), pace (points a game, both teams)"""
    th = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cbb_tourney_hist.json')))
    names = {}
    for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_games_hist.json.gz'))):
        names[g['home']] = g['hn']; names[g['away']] = g['an']
    seeds = {}
    for S, v in th.items():
        for tid, f in v['field'].items():
            if tid in names:
                seeds[(int(S), names[tid])] = f['seed']
    return seeds


# ------------------------------------------------------------------ the layer
def design(games, feats):
    z = np.array([g['z'] for g in games])
    hx = np.array([1.0 - g['n'] for g in games])
    X = [z, hx] + [np.array([g['f'].get(f, 0.0) for g in games]) for f in feats]
    return np.c_[tuple(X)], np.array([g['y'] for g in games])


def fit(X, y, calib=True):
    """Newton logistic with ridge: column 0 (baseline logit) toward 1, column 1 (home) toward 0, traits toward 0"""
    k = X.shape[1]
    b = np.zeros(k); b[0] = 1.0
    prior = np.zeros(k); prior[0] = 1.0
    lam = np.full(k, LAM); lam[0] = 2 * LAM; lam[1] = 1.0
    if not calib:
        lam[0] = lam[1] = 1e9
    for _ in range(30):
        p = 1 / (1 + np.exp(-(X @ b)))
        g = X.T @ (p - y) + lam * (b - prior)
        H = X.T @ (X * (p * (1 - p))[:, None]) + np.diag(lam)
        step = np.linalg.solve(H, g)
        b -= step
        if np.abs(step).max() < 1e-8:
            break
    return b


def pred(X, b):
    return 1 / (1 + np.exp(-(X @ b)))


def ll_vec(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def loso(games, feats, calib=True):
    """held-out probabilities by season for a fixed trait set"""
    Ss = sorted({g['S'] for g in games})
    p = np.zeros(len(games))
    idx = defaultdict(list)
    for i, g in enumerate(games):
        idx[g['S']].append(i)
    X, y = design(games, feats)
    for S in Ss:
        te = np.array(idx[S]); tr = np.array([i for i in range(len(games)) if games[i]['S'] != S])
        b = fit(X[tr], y[tr], calib)
        p[te] = pred(X[te], b)
    return p


def select(games, cands):
    """greedy forward selection on an inner leave-one-season-out log loss (calibration always in)"""
    y = np.array([g['y'] for g in games])
    chosen = []
    best = ll_vec(loso(games, chosen), y).mean()
    while True:
        trial = [(ll_vec(loso(games, chosen + [f]), y).mean(), f) for f in cands if f not in chosen]
        if not trial:
            break
        v, f = min(trial)
        if v >= best - 1e-4:
            break
        best, chosen = v, chosen + [f]
    return chosen


def standardize(games, cands):
    sc = {}
    for f in cands:
        v = np.array([g['f'].get(f, 0.0) for g in games])
        s = sc[f] = float(v.std() or 1.0)
        for g in games:
            g['f'][f] = g['f'].get(f, 0.0) / s
    return sc


def evaluate(games, cands):
    """outer leave-one-season-out with nested selection; returns held-out probs for baseline, calibration-only,
    the nested-selected layer, and each fold's chosen traits"""
    Ss = sorted({g['S'] for g in games})
    base = 1 / (1 + np.exp(-np.array([g['z'] for g in games])))
    cal = loso(games, [])
    lay = np.zeros(len(games))
    picks = {}
    for S in Ss:
        tr = [g for g in games if g['S'] != S]
        te_i = [i for i, g in enumerate(games) if g['S'] == S]
        fs = select(tr, cands)
        picks[S] = fs
        Xtr, ytr = design(tr, fs)
        b = fit(Xtr, ytr)
        Xte, _ = design([games[i] for i in te_i], fs)
        lay[te_i] = pred(Xte, b)
    return base, cal, lay, picks


def compare(p0, p1, y, S):
    d = ll_vec(p1, y) - ll_vec(p0, y)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0.0
    bs = (p1 - y) ** 2 - (p0 - y) ** 2
    tb = bs.mean() / (bs.std(ddof=1) / math.sqrt(len(bs))) if bs.std() > 0 else 0.0
    seasons = sorted(set(S))
    wins = sum(1 for s in seasons if d[S == s].mean() < 0)
    return {'ll0': round(float(ll_vec(p0, y).mean()), 4), 'll1': round(float(ll_vec(p1, y).mean()), 4),
            'dll': round(float(d.mean()), 4), 't': round(float(t), 2),
            'brier0': round(float(((p0 - y) ** 2).mean()), 4), 'brier1': round(float(((p1 - y) ** 2).mean()), 4),
            'tBrier': round(float(tb), 2), 'seasonsBetter': f'{wins}/{len(seasons)}'}


def calib_bins(p, y, k=5):
    o = np.argsort(p)
    out = []
    for ch in np.array_split(o, k):
        out.append([round(float(p[ch].mean()), 3), round(float(y[ch].mean()), 3), int(len(ch))])
    return out


POOL = defaultdict(list)


def run(sport):
    rows = rows_for(sport)
    tr = generic_traits(rows)
    extra = {}
    cands = ['form', 'vsgood', 'rsd', 'mgap', 'exp', 'rest', 'str']
    if sport == 'nba':
        extra = nba_traits(); cands += ['star', 'top1', 'three', 'pace']
    elif sport == 'nhl':
        extra = nhl_traits(); cands += ['gsax', 'xgs', 'g1']
    seeds = cbb_traits() if sport == 'cbb' else {}
    if sport == 'cbb':
        cands += ['seed']
    games = []
    last = {}
    for r in sorted(rows, key=lambda r: r['d']):
        if r['po'] == 1:
            th, ta = tr.get((r['S'], r['h'])), tr.get((r['S'], r['a']))
            if th and ta:
                f = {k: th[k] - ta[k] for k in ('form', 'vsgood', 'rsd', 'mgap', 'exp', 'str')}
                rh = r['d'] - last.get(r['h'], r['d'] - 7); ra = r['d'] - last.get(r['a'], r['d'] - 7)
                f['rest'] = min(rh, 8) - min(ra, 8)
                eh, ea = extra.get((r['S'], r['h']), {}), extra.get((r['S'], r['a']), {})
                for k in ('star', 'top1', 'three', 'pace', 'gsax', 'xgs', 'g1'):
                    if k in eh and k in ea:
                        f[k] = eh[k] - ea[k]
                if sport == 'cbb':
                    sh, sa = seeds.get((r['S'], r['h'])), seeds.get((r['S'], r['a']))
                    if sh and sa:
                        # the committee's view beyond the model: seed line edge vs the model's own margin
                        f['seed'] = (sa - sh)
                games.append(dict(r, f=f))
        last[r['h']] = r['d']; last[r['a']] = r['d']
    sc = standardize(games, cands)
    y = np.array([g['y'] for g in games]); S = np.array([g['S'] for g in games])
    base, cal, lay, picks = evaluate(games, cands)
    # single-trait screens (calibration + one trait, plain leave-one-season-out: descriptive only, not the gate)
    single = {}
    for f in cands:
        pf = loso(games, [f])
        single[f] = compare(cal, pf, y, S)
        POOL[f].append(ll_vec(pf, y) - ll_vec(cal, y))
    full = select(games, cands)
    Xf, yf = design(games, full)
    bf = fit(Xf, yf)
    mk = np.array([g['mk'] if g['mk'] is not None else np.nan for g in games])
    ok = ~np.isnan(mk)
    res = {'n': len(games), 'seasons': [int(s) for s in sorted(set(S))],
           'calibOnly': compare(base, cal, y, S), 'layer': compare(base, lay, y, S),
           'layerVsCalib': compare(cal, lay, y, S),
           'market': compare(base[ok], 1 / (1 + np.exp(-mk[ok])), y[ok], S[ok]) if ok.sum() > 30 else None,
           'picksByFold': {str(k): v for k, v in picks.items()},
           'final': {'feats': full, 'a': round(float(bf[0]), 3), 'home': round(float(bf[1]), 3),
                     'b': {f: round(float(bf[2 + i]), 3) for i, f in enumerate(full)},
                     'scale': {f: round(sc[f], 4) for f in full}},
           'single': single, 'calibBase': calib_bins(base, y), 'calibLayer': calib_bins(lay, y)}
    best = min((('calib', res['calibOnly']), ('layer', res['layer'])), key=lambda x: x[1]['ll1'])
    res['pass'] = bool(best[1]['t'] <= -2.0 and int(best[1]['seasonsBetter'].split('/')[0]) * 2 > len(set(S)))
    res['pick'] = best[0] if res['pass'] else 'baseline'
    return res


def main():
    sports = sys.argv[1:] or ['nfl', 'nba', 'nhl', 'cbb', 'cfb', 'soccer']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for s in sports:
        r = run(s)
        out[s] = r
        print(s, 'n', r['n'], 'calib', r['calibOnly'], '\n   layer', r['layer'], '\n   vs calib', r['layerVsCalib'],
              '\n   market', r['market'], '\n   final', r['final'], 'pass', r['pass'], r['pick'], flush=True)
        for f, v in r['single'].items():
            print('     single', f, v['dll'], v['t'], v['seasonsBetter'])
    pooled = {}
    for f, ds in POOL.items():
        d = np.concatenate(ds)
        pooled[f] = {'sports': len(ds), 'n': int(len(d)), 'dll': round(float(d.mean()), 5),
                     't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)}
        print('pooled', f, pooled[f])
    if len(sports) >= 6:
        out['pooled'] = pooled
    out['other'] = {
        'tennis': 'majors already tested in scripts/tennis_model.py (data/tennis_fit.json failed list): Grand Slam K x1.2 '
                  'no change, Slam/Masters x ratings +1.4e-4 worse held out; best-of-5 is in the match chain',
        'cs2': 'not tested: majors since Feb 2024 are ~5 events with no event labels in scripts/data/cs2_history.json.gz, '
               'and the held-out window (Jul 2025 on) holds two'}
    out['shipped'] = [s for s in ('nfl', 'nba', 'nhl', 'cbb', 'cfb', 'soccer') if out.get(s, {}).get('pass')]
    out['updated'] = datetime.now().strftime('%Y-%m-%d')
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
