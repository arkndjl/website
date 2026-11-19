# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Preseason points O/U (Hockey-Reference) as the NHL season prior: sim test, early-game term, futures row
(pre-registered H2a, H2b, H2c).

usage: preseason_ou.py --parse <dir with <S>.html pages>     -> scripts/data/futures/nhl_preseason.json
       preseason_ou.py --test <out.json>
The 2027 page's lines are stored; its Final Pts column is never read.
"""
import gzip, html, json, math, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
LINES = os.path.join(ROOT, 'scripts', 'data', 'futures', 'nhl_preseason.json')
NICK = {'Ducks': 'ANA', 'Mighty Ducks': 'ANA', 'Bruins': 'BOS', 'Sabres': 'BUF', 'Flames': 'CGY', 'Hurricanes': 'CAR', 'Blackhawks': 'CHI',
        'Avalanche': 'COL', 'Blue Jackets': 'CBJ', 'Stars': 'DAL', 'Red Wings': 'DET', 'Oilers': 'EDM', 'Panthers': 'FLA',
        'Kings': 'LAK', 'Wild': 'MIN', 'Canadiens': 'MTL', 'Predators': 'NSH', 'Devils': 'NJD', 'Islanders': 'NYI',
        'Rangers': 'NYR', 'Senators': 'OTT', 'Flyers': 'PHI', 'Penguins': 'PIT', 'Sharks': 'SJS', 'Kraken': 'SEA',
        'Blues': 'STL', 'Lightning': 'TBL', 'Maple Leafs': 'TOR', 'Canucks': 'VAN', 'Golden Knights': 'VGK',
        'Capitals': 'WSH', 'Jets': 'WPG', 'Thrashers': 'WPG', 'Coyotes': 'UTA', 'Hockey Club': 'UTA', 'Mammoth': 'UTA'}
SCHED = {2013: 48, 2021: 56}
TUNE, HELD = list(range(2014, 2020)), list(range(2020, 2027))
STD = [s for s in TUNE + HELD if s not in (2020, 2021)]
W_GRID = [0.25, 0.5, 0.75, 1.0]


def parse(d):
    out = {}
    for f in sorted(os.listdir(d)):
        m = re.fullmatch(r'(\d{4})\.html', f)
        if not m:
            continue
        S = int(m.group(1))
        h = open(os.path.join(d, f), encoding='utf8', errors='replace').read()
        tb = h[h.find('<table class="sortable stats_table" id="preseason_odds"'):]
        tb = tb[:tb.find('</table>')]
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb, re.S):
            c = [html.unescape(re.sub(r'<[^>]+>', ' ', x)).strip() for x in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', tr, re.S)]
            if len(c) < 3:
                continue
            code = next((v for k, v in NICK.items() if c[0].endswith(k)), None)
            if not code:
                continue
            ou = float(c[2]) if re.fullmatch(r'\d+(\.\d)?', c[2]) else None
            cup = int(c[1]) if re.fullmatch(r'[+-]\d+', c[1]) else None
            if ou is not None or cup is not None:
                out.setdefault(str(S), {})[code] = {'ou': ou, 'cup': cup}
    os.makedirs(os.path.dirname(LINES), exist_ok=True)
    json.dump({'source': 'https://www.hockey-reference.com/leagues/NHL_<S>_preseason_odds.html', 'lines': out}, open(LINES, 'w'),
              separators=(',', ':'))
    print({S: (len(v), sum(1 for x in v.values() if x['ou'] is not None)) for S, v in out.items()})


def tstat(d, cl):
    import harness as H
    pr = H.paired(np.asarray(d), np.zeros(len(d)), np.asarray(cl))
    return round(pr['t'], 2), pr['p']


def sim_test(L):
    import nhl_sim_backtest as B
    import nhl_games as G
    B.CPS = [0, 20]
    fit = json.load(open(G.FIT))
    P, feats, otc = fit['params'], fit['feats'], fit['ot']
    hist, rows, snaps = B.snapshots(P)
    snaps = [s for s in snaps if s['S'] in TUNE + HELD]
    coefs = B.bases(snaps, rows, feats)
    B.OTW.update(B.ot_fits(rows, coefs))
    sd = min(B.SD_GRID, key=lambda s: abs(s - fit['seasonSd']))
    recs = []                       # per team x checkpoint
    day0 = {}
    for sn in sorted(snaps, key=lambda s: (s['S'], s['k'])):
        S, k = sn['S'], sn['k']
        if str(S) not in L:
            continue
        c = coefs[S]
        base = {t: sum(c[x] * v for x, v in sn['comp'][t].items() if x in c) for t in sn['comp']}
        reg = [g for g in hist if g['S'] == S and not g['po']]
        left_games = [g for g in reg if g['day'] >= sn['day']]
        left = len(left_games) / len(reg)
        pts, made, divw, cup = B.outcomes(hist, S)
        gp = {}
        for g in reg:
            gp[g['h']] = gp.get(g['h'], 0) + 1; gp[g['a']] = gp.get(g['a'], 0) + 1

        def run(b):
            rng = np.random.default_rng(1000 * S + k)
            teams, pm, pd_, pc, xp = B.sim(S, b, sn['pts'], left_games, c.get('home', 0.13), otc, 0.0, sd, left, rng)
            return teams, pm, xp
        teams, pm0, xp0 = run(base)
        if k == 0:
            ou = {t: (L[str(S)].get(t) or {}).get('ou') for t in teams}
            tgt = {t: ou[t] * gp[t] / SCHED.get(S, 82) if ou[t] is not None else None for t in teams}
            ok = [t for t in teams if tgt[t] is not None]
            bx = np.array([base[t] for t in teams]); s = float(np.polyfit(bx, xp0, 1)[0])
            day0[S] = {'gap': {t: (tgt[t] - xp0[i]) / s if tgt[t] is not None else 0.0 for i, t in enumerate(teams)},
                       'tgt': tgt, 'xp0': dict(zip(teams, xp0)), 's': s}
        d0 = day0[S]
        for w in W_GRID:
            nb = {t: base[t] + w * left * d0['gap'][t] for t in teams}
            _, pm1, xp1 = run(nb)
            for i, t in enumerate(teams):
                recs.append({'S': S, 'k': k, 't': t, 'w': w, 'ae0': abs(xp0[i] - pts[t]), 'ae1': abs(xp1[i] - pts[t]),
                             'b0': (pm0[i] - (t in made)) ** 2, 'b1': (pm1[i] - (t in made)) ** 2,
                             'aeLine': abs(d0['tgt'][t] - pts[t]) if d0['tgt'][t] is not None and k == 0 else None,
                             'xp0': d0['xp0'][t], 'tgt': d0['tgt'][t], 'pts': pts[t]})
        print('sim', S, k, flush=True)
    res = {'sd': sd, 'slope': {str(S): round(v['s'], 2) for S, v in day0.items()}}

    def pick(w, seasons, a, b):
        r = [x for x in recs if x['w'] == w and x['S'] in seasons]
        return np.array([x[b] - x[a] for x in r]), np.array([x['S'] for x in r]), r
    tune = {w: float(pick(w, TUNE, 'ae0', 'ae1')[0].mean()) for w in W_GRID}
    w = min(tune, key=tune.get)
    res['wTune'] = {str(k): round(v, 3) for k, v in tune.items()}; res['w'] = w
    for lab, seasons in (('tune', TUNE), ('held', HELD)):
        d, cl, r = pick(w, seasons, 'ae0', 'ae1')
        t, p = tstat(d, cl)
        won = sum(1 for S in seasons if d[cl == S].mean() < 0)
        res['points_' + lab] = {'n': len(d), 'maeBase': round(float(np.mean([x['ae0'] for x in r])), 3),
                                'maeNew': round(float(np.mean([x['ae1'] for x in r])), 3), 'd': round(float(d.mean()), 3), 't': t, 'p': p,
                                'seasonsBetter': f'{won}/{len(seasons)}',
                                'byK': {str(k): round(float(np.mean([x['ae1'] - x['ae0'] for x in r if x['k'] == k])), 3) for k in (0, 20)}}
        ss = [S for S in seasons if S in STD]
        d, cl, r = pick(w, ss, 'b0', 'b1')
        t, p = tstat(d, cl)
        res['playoff_' + lab] = {'n': len(d), 'brierBase': round(float(np.mean([x['b0'] for x in r])), 4),
                                 'brierNew': round(float(np.mean([x['b1'] for x in r])), 4), 'd': round(float(d.mean()), 4), 't': t, 'p': p,
                                 'seasonsBetter': f"{sum(1 for S in ss if d[cl == S].mean() < 0)}/{len(ss)}"}
    # H2c: does the day-0 sim add to the line? final - line on (sim - line); MAE; the sim's side at -110
    fut = {}
    for lab, seasons in (('tune', TUNE), ('held', HELD), ('all', TUNE + HELD)):
        r = [x for x in recs if x['w'] == W_GRID[0] and x['k'] == 0 and x['S'] in seasons and x['tgt'] is not None]
        g = np.array([x['xp0'] - x['tgt'] for x in r]); e = np.array([x['pts'] - x['tgt'] for x in r]); cl = np.array([x['S'] for x in r])
        b = float((g * e).sum() / (g * g).sum())
        t, _ = tstat(-(g * e), cl)                       # sign: positive t = the sim's lean is right
        push = e == 0
        win = np.sign(g) == np.sign(e)
        ret = np.where(push, 0.0, np.where(win, 100 / 110, -1.0))
        tr, _ = tstat(-ret, cl)
        fut[lab] = {'n': len(r), 'b': round(b, 3), 'tLean': t, 'maeSim': round(float(np.abs(g - e).mean()), 2),
                    'maeLine': round(float(np.abs(e).mean()), 2), 'retSimSide': round(float(ret.mean()), 4), 'tRet': tr,
                    'hit': round(float(win[~push].mean()), 3)}
    res['futures'] = fut
    return res


def game_test(L):
    import harness as H
    rows = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'nhl.json.gz')))
    rows.sort(key=lambda g: (g['day'], g['id']))
    gp, X = {}, []
    for g in rows:
        S = g['S']
        kh, ka = (S, g['h']), (S, g['a'])
        lh, la = (L.get(str(S), {}).get(g['h']) or {}).get('ou'), (L.get(str(S), {}).get(g['a']) or {}).get('ou')
        wgt = 0.0 if g['po'] or lh is None or la is None else max(0.0, 1 - (gp.get(kh, 0) + gp.get(ka, 0)) / 2 / 20)
        z = math.log(g['p'] / (1 - g['p']))
        X.append((S, g['day'], z, wgt, ((lh or 0) - (la or 0)) / 40, float(g['hs'] > g['as'])))
        if not g['po']:
            gp[kh] = gp.get(kh, 0) + 1; gp[ka] = gp.get(ka, 0) + 1
    A = np.array([(a, c, d, e, f) for a, b, c, d, e, f in X]); day = np.array([x[1] for x in X])
    S, z, wgt, ou, y = A.T
    pnew = np.full(len(y), np.nan); coefs = {}
    for s in range(2020, 2027):
        tr = (S < s) & (wgt > 0)
        F = np.column_stack([wgt[tr] * ou[tr], wgt[tr] * z[tr]])
        b = np.zeros(2)
        for _ in range(40):
            p = 1 / (1 + np.exp(-(z[tr] + F @ b)))
            st = np.linalg.solve((F * (p * (1 - p))[:, None]).T @ F + 1e-6 * np.eye(2), F.T @ (y[tr] - p))
            b += st
        coefs[s] = [round(float(v), 3) for v in b]
        te = (S == s) & (wgt > 0)
        pnew[te] = 1 / (1 + np.exp(-(z[te] + wgt[te] * (b[0] * ou[te] + b[1] * z[te]))))
    p0 = 1 / (1 + np.exp(-z))
    out = {'coef': coefs}
    for lab, ss in (('tune', (2020, 2021, 2022, 2023)), ('held', (2024, 2025, 2026))):
        m = np.isin(S, ss) & ~np.isnan(pnew)
        l1, l0 = H.logloss(pnew[m], y[m]), H.logloss(p0[m], y[m])
        pr = H.paired(l1, l0, day[m])
        out[lab] = {'n': int(m.sum()), 'llBase': round(float(l0.mean()), 5), 'llNew': round(float(l1.mean()), 5),
                    'd': round(float((l1 - l0).mean()), 5), 't': round(pr['t'], 2), 'p': pr['p'],
                    'seasonsBetter': f"{sum(1 for s in ss if (l1 - l0)[S[m] == s].mean() < 0)}/{len(ss)}"}
    return out


if __name__ == '__main__':
    if sys.argv[1] == '--parse':
        parse(sys.argv[2])
    else:
        L = json.load(open(LINES))['lines']
        res = {'game': game_test(L)}
        print(json.dumps(res['game'], indent=1), flush=True)
        res['sim'] = sim_test(L)
        json.dump(res, open(sys.argv[2], 'w'), indent=1)
        print(json.dumps(res['sim'], indent=1))
