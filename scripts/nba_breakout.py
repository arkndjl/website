# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA Potential Breakout ("next up" tab): breakout odds and contextual usage scaling for every NBA player
(static/data/next-up/nba.json). Model and held-out tests: scripts/nba_breakout_research.py -> data/nba_breakout_fit.json.

    python3 scripts/nba_breakout.py            # build: this season from bbref (cached by nba_xpm.py) + the fit; stdlib only
    python3 scripts/nba_breakout.py --hist     # refresh the past four seasons (scripts/data/nba_breakout_hist.json), once a season

Feature columns live here so the research fit and the live board build them the same way."""
import datetime as dt
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FIT = os.path.join(ROOT, 'data', 'nba_breakout_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'next-up', 'nba.json')
HTWT = os.path.join(ROOT, 'scripts', 'nba_htwt.json')
HIST = os.path.join(ROOT, 'scripts', 'data', 'nba_breakout_hist.json')
CEIL = os.path.join(ROOT, 'data', 'nba_ceiling_fit.json')         # scripts/nba_ceiling_research.py
BEST = os.path.join(ROOT, 'scripts', 'data', 'nba_career_best.json')   # best shrunk BPM per bbref id through 2025-26 (LAKER history)

TARGETS = ('ts_plus', 'tov_pct')
MEAN = {'ts_plus': 100.0, 'tov_pct': 13.0}
BASE = ['x0', 'x0*r0', 'r0', 'age', 'age2', 'u0', 'xprev', 'hasprev']
BLOCKS = {
    'shot profile': ['ftr_plus', 'threepar_plus', 'fg2_plus', 'ft_plus'],
    'role': ['ast_pct', 'orb_pct', 'big', 'guard', 'tov0'],
    'frame': ['ht', 'bmi'],
    'past usage history': ['own', 'xprevc'],
    'age': ['agec'],
    'low-usage rates': ['x0c', 'x0c_lowu'],
}


def columns(tgt=None):
    return BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in tr], []) for tr in BLOCKS.values()], [])


def history(P, pid, y):
    return [P[(pid, s)] for s in range(y - 6, y + 1) if (pid, s) in P]


def own_slope(hist, tgt):
    """the player's own usage -> rate slope across his seasons (250+ MP), shrunk toward 0"""
    h = [o for o in hist if o['mp'] >= 250]
    if len(h) < 2:
        return 0.0
    W = [o['mp'] / 1000 for o in h]
    sw = sum(W)
    mu = sum(w * o['usage_pct'] for w, o in zip(W, h)) / sw
    mx = sum(w * o[tgt] for w, o in zip(W, h)) / sw
    sxy = sum(w * (o['usage_pct'] - mu) * (o[tgt] - mx) for w, o in zip(W, h))
    sxx = sum(w * (o['usage_pct'] - mu) ** 2 for w, o in zip(W, h))
    return sxy / (sxx + 20.0)


def trait_vals(tgt, a, hist, htwt):
    x0 = a[tgt]
    prev = [o for o in hist if o['y'] < a['y'] and o['mp'] >= 250]
    xprev = prev[-1][tgt] if prev else x0
    lowu = max(0.0, 20 - a['usage_pct']) / 10
    ht = (htwt or {}).get('ht') or 79
    wt = (htwt or {}).get('wt') or 220
    return {
        'ftr_plus': a['ftr_plus'], 'threepar_plus': a['threepar_plus'], 'fg2_plus': a['fg2_plus'], 'ft_plus': a['ft_plus'],
        'ast_pct': a['ast_pct'], 'orb_pct': a['orb_pct'], 'big': a['c_pct'] + a['pf_pct'], 'guard': a['pg_pct'] + a['sg_pct'],
        'tov0': a['tov_pct'], 'ht': ht, 'bmi': 703.0 * wt / ht ** 2, 'own': own_slope(hist, tgt),
        'xprevc': xprev - x0, 'agec': a['age'] - 26, 'x0c': x0 - MEAN[tgt], 'x0c_lowu': (x0 - MEAN[tgt]) * lowu,
        '_xprev': xprev, '_has': 1.0 if prev else 0.0,
    }


def features(tgt, a, hist, htwt, dU):
    t = trait_vals(tgt, a, hist, htwt)
    x0, r0, age = a[tgt], a['mp'] / (a['mp'] + 1000), a['age']
    v = {'x0': x0, 'x0*r0': x0 * r0, 'r0': r0, 'age': age, 'age2': age * age, 'u0': a['usage_pct'],
         'xprev': t['_xprev'], 'hasprev': t['_has'], 'dU': dU}
    for tr in BLOCKS.values():
        for k in tr:
            v[k] = t[k]
            v['dU*' + k] = dU * t[k]
    return [v[c] for c in columns(tgt)]


def predict(fit, tgt, a, hist, htwt, dU):
    f = fit['scaling'][tgt]['fit']
    allc = columns(tgt)
    x = dict(zip(allc, features(tgt, a, hist, htwt, dU)))
    return f['b0'] + sum(b * x[c] for b, c in zip(f['b'], f['cols']))


# ---------- breakout odds ----------
K_SHR, BPM_REP = 600.0, -2.0
BO_CANDS = ('age curve', 'low-volume efficiency', 'vacated usage', 'shooting luck', 'projection gap', 'minutes room',
            'usage scaling')
BO_LABEL = {'age curve': ['age', 'age', 'age'], 'low-volume efficiency': ['low-vol eff', 'usage'],
            'shooting luck': ['3P luck', 'FT touch'], 'projection gap': ['proj gap'], 'usage scaling': ['scales', 'creator'],
            'vacated usage': ['open usage'], 'minutes room': ['min room', 'min room']}


def shr(bpm, mp):
    return (bpm * mp + BPM_REP * K_SHR) / (mp + K_SHR)


def marcel(hist, y):
    """3-season BPM, weights 5/4/3 by MP, shrunk to replacement with 1000 MP"""
    num = den = 0.0
    for o in hist:
        w = {0: 5, 1: 4, 2: 3}.get(y - o['y'])
        if w:
            num += w * o['bpm'] * o['mp']
            den += w * o['mp']
    return (num + BPM_REP * 1000) / (den + 1000)


BAR = 1.0                    # quality bar: shrunk BPM, about the 80th percentile of 1,000+ MP seasons
BO_CANDS2 = ('draft curve', 'coaching change', 'opportunity ahead', 'improvement trend')
BO_LABEL.update({'draft curve': ['pick', 'pick', 'pick'], 'coaching change': ['new coach'],
                 'opportunity ahead': ['room ahead', 'old room'], 'improvement trend': ['rising', 'rising']})
TM = {'BRK': 'BKN', 'PHO': 'PHX', 'CHO': 'CHA', 'NJN': 'BKN', 'NOH': 'NOP', 'NOK': 'NOP', 'GS': 'GSW', 'NY': 'NYK',
      'SA': 'SAS', 'NO': 'NOP', 'UTAH': 'UTA', 'WSH': 'WAS'}
KN_S, KN_A, KN_M = (-4.0, -2.6, -1.4, 0.0), (20.0, 23.0, 26.0, 30.0), (6.2, 7.0, 7.5, 7.9)


def group(o):
    if o.get('pg_pct', 0) + o.get('sg_pct', 0) >= 50:
        return 'G'
    return 'C' if o.get('c_pct', 0) >= 50 else 'F'


_IDX = {}


def career_best(P, pid, y):
    """best shrunk BPM of any season through y"""
    ix = _IDX.get(id(P))
    if ix is None:
        ix = _IDX[id(P)] = {}
        for (q, s), o in P.items():
            ix.setdefault(q, []).append(o)
    return max([shr(o['bpm'], o['mp']) for o in ix.get(pid, []) if o['y'] <= y] or [-9.0])


def prev_shr(P, pid, y):
    o = P.get((pid, y - 1))
    return shr(o['bpm'], o['mp']) if o else None


def spline(x, k):
    """restricted cubic spline terms (k - 2 columns), Harrell's form"""
    import numpy as np
    k = list(k)
    t = lambda v: np.maximum(v, 0) ** 3  # noqa: E731
    d = (k[-1] - k[0]) ** 2
    cols = []
    for j in range(len(k) - 2):
        cols.append((t(x - k[j]) - t(x - k[-2]) * (k[-1] - k[j]) / (k[-1] - k[-2])
                     + t(x - k[-1]) * (k[-2] - k[j]) / (k[-1] - k[-2])) / d)
    return np.column_stack(cols)


def bo_feats(a, s0, vac, mar, prev=None, draft=None, coach=None, opp=(0.0, 0.0)):
    age, usg, ts, mp = a['age'], a['usage_pct'], a['ts_plus'], a['mp']
    lowu = max(0.0, 22 - usg) / 10
    lm = math.log(mp)
    lp = math.log(draft[1]) if draft else math.log(61)
    yrs = a['y'] - draft[0] if draft else max(0.0, age - 20)
    tr = s0 - prev if prev is not None else 0.0
    return {'base': [s0, lm],
            'age curve': [age, age * age, age * s0],
            'low-volume efficiency': [(ts - 100) * lowu, usg],
            'vacated usage': [vac],
            'shooting luck': [(a['fg3_plus'] - 100) * a['threepar_plus'] / 100, a['ft_plus'] - 100],
            'projection gap': [mar - s0],
            'minutes room': [lm * s0, (mp < 1500) * a['obpm']],
            'usage scaling': [a['ftr_plus'] * lowu, a['ast_pct'] * lowu],
            'draft curve': [lp, lp * (age - 22), yrs],
            'coaching change': [coach or 0.0],
            'opportunity ahead': list(opp),
            'improvement trend': [tr, tr * (age - 24)]}


# ---------- live build ----------
def _rows(h, tid):
    import nba_xpm as X
    tb = re.search(r'<table[^>]*id="%s"[^>]*>(.*?)</table>' % tid, h, re.S)
    if not tb:
        return {}
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb.group(1), re.S):
        c = dict(re.findall(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
        nm = c.get('name_display', '')
        m = re.search(r'/players/\w/(\w+)\.html', nm)
        if not m:
            continue
        pid = m.group(1)
        tm = X.cell(c.get('team_name_abbr', ''))
        if pid in out:                                     # stints after the TOT row: remember the last team
            out[pid]['_last'] = tm
            continue
        d = {k: X.cell(v) for k, v in c.items()}
        d['_n'] = X.cell(nm).rstrip('*')
        d['_tm'] = tm
        out[pid] = d
    return out


def _f(d, k):
    try:
        return float(d.get(k) or 0)
    except ValueError:
        return 0.0


def season_rows(season, fresh=False):
    """bbref advanced + totals -> {pid: LAKER-style season dict}"""
    import nba_xpm as X
    adv = _rows(X.fetch(season, fresh, 'advanced'), 'advanced')
    tot = _rows(X.fetch(season, fresh, 'totals'), 'totals_stats')
    if not adv or not tot:
        return {}, {}
    S = {k: sum(_f(t, k) for t in tot.values()) for k in ('pts', 'fga', 'fta', 'fg3', 'fg3a', 'fg2', 'fg2a', 'ft')}
    lg = {'ts': S['pts'] / (2 * (S['fga'] + .44 * S['fta'])), 'ftr': S['fta'] / S['fga'], 'tpar': S['fg3a'] / S['fga'],
          'fg3': S['fg3'] / S['fg3a'], 'ft': S['ft'] / S['fta'], 'fg2': S['fg2'] / S['fg2a']}
    out = {}
    for pid, a in adv.items():
        t = tot.get(pid)
        mp = _f(a, 'mp')
        if not t or mp <= 0:
            continue
        fga, fta, f3a, f2a = _f(t, 'fga'), _f(t, 'fta'), _f(t, 'fg3a'), _f(t, 'fg2a')
        tsa = fga + .44 * fta
        pos = (a.get('pos') or 'SF').split('-')[0]
        o = {'pid': pid, 'y': season, 'n': a['_n'], 'tm': a.get('_last') or a['_tm'], 'age': _f(a, 'age'), 'mp': mp,
             'g': _f(a, 'games'), 'pos': pos,
             'usage_pct': _f(a, 'usg_pct'), 'tov_pct': _f(a, 'tov_pct'), 'ast_pct': _f(a, 'ast_pct'),
             'orb_pct': _f(a, 'orb_pct'), 'bpm': _f(a, 'bpm'), 'obpm': _f(a, 'obpm'),
             'ts_plus': 100 * (_f(t, 'pts') / (2 * tsa)) / lg['ts'] if tsa else 100.0,
             'ftr_plus': 100 * (fta / fga) / lg['ftr'] if fga else 100.0,
             'threepar_plus': 100 * (f3a / fga) / lg['tpar'] if fga else 100.0,
             'fg3_plus': 100 * (_f(t, 'fg3') / f3a) / lg['fg3'] if f3a else 100.0,
             'ft_plus': 100 * (_f(t, 'ft') / fta) / lg['ft'] if fta else 100.0,
             'fg2_plus': 100 * (_f(t, 'fg2') / f2a) / lg['fg2'] if f2a else 100.0,
             'pts': _f(t, 'pts')}
        for k in ('pg', 'sg', 'sf', 'pf', 'c'):
            o[k + '_pct'] = 100.0 if pos.lower() == k else 0.0
        out[pid] = o
    return out, lg


def ceiling(cf, sx, a):
    """80th percentile next-season XPM with usage up cf['scen'] points (capped at cf['ucap'])"""
    f = cf['fit']
    du = max(0.0, min(cf['scen'], cf['ucap'] - a['usage_pct']))
    age = a['age'] or 25.0
    v = {'sxpm': sx, 'age': age, 'age2': age * age, 'lnmp': math.log(max(a['mp'], 1.0)), 'dU': du, 'dU2': du * du,
         'dU*age': du * age, 'dU*usg': du * a['usage_pct'], 'dU*fg2+': du * a.get('fg2_plus', 100.0),
         'dU*3par+': du * a.get('threepar_plus', 100.0), 'dU*sxpm': du * sx, 'absdU': du, 'usg': a['usage_pct']}
    m = f['b0'] + sum(b * v[c] for b, c in zip(f['b'], f['cols']))
    sp = max(f['floor'], f['c0'] + sum(c * v[k] for c, k in zip(f['c'], f['scol']))) if f['c'] else f['c0']
    return m + f['q'] * sp


def sig_x(fit, X):
    f = fit['breakout']['fit']
    return 1 / (1 + math.exp(-max(-30, min(30, f['b0'] + sum(b * x for b, x in zip(f['b'], X))))))


ROOKIE = os.path.join(ROOT, 'data', 'nba_rookie_bo_fit.json')   # scripts/nba_rookie_bo_research.py


def rookies(rows, cur):
    """this season's drafted rookies (no NBA line last season, so no returner row): odds of a rookie season at the bar
    from the draft slot (data/nba_rookie_bo_fit.json, calibrated held out); rows from the rookies tab
    (static/data/rookies/nba.json, pick = pre)"""
    try:
        ff = json.load(open(ROOKIE))
        rk = json.load(open(os.path.join(ROOT, 'static', 'data', 'rookies', 'nba.json')))
    except (OSError, ValueError):
        return 0
    S = next((x for x in rk['seasons'] if int(x['s']) == cur), None)
    if not S:
        return 0
    have = {r['n'] for r in rows}
    n = 0
    for r in S['rows']:
        if not r.get('pre') or r['n'] in have:
            continue
        z = ff['fit']['b0'] + ff['fit']['b'][0] * -math.log(r['pre'])
        rows.append({'id': 'rk-' + r['n'], 'n': r['n'], 'x': r.get('sx'), 'xc': None, 'tm': r.get('tm'), 'pos': r.get('pos'),
                     'age': r.get('age'), 'ph': r.get('ph'), 'p': round(1 / (1 + math.exp(-max(-30, min(30, z)))), 3), 'best': None,
                     'u': None, 't': [], 'sig': ['draft slot'], 'st': r['pre'], 'fr': 1})
        n += 1
    return n


def main():
    import gzip
    import nba_xpm as X
    fit = json.load(open(FIT))
    HT = json.load(open(HTWT))
    cur = X.current_season()
    if '--hist' in sys.argv:                                   # past seasons, kept in the repo so the daily run reads only this one
        H = {}
        for s in range(cur - 4, cur):
            rs, lg = season_rows(s)
            rs = {pid: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in o.items()}
                  for pid, o in rs.items() if o['mp'] >= 100}
            H[str(s)] = {'lg': lg, 'rows': rs}
        json.dump(H, open(HIST, 'w'), separators=(',', ':'))
        print('wrote', HIST)
        return
    H = json.load(open(HIST))
    seas = {int(s): v['rows'] for s, v in H.items()}
    lg_last = H[str(max(int(s) for s in H))]['lg']
    fn = os.path.join(X.CACHE, f'adv_{cur}.html')
    stale = not os.path.exists(fn) or dt.datetime.now().timestamp() - os.path.getmtime(fn) > 6 * 3600
    seas[cur], lg_cur = season_rows(cur, fresh=stale)
    P = {(pid, s): o for s, rs in seas.items() for pid, o in rs.items()}
    cur_rows = seas.get(cur) or {}
    games = max([o['g'] for o in cur_rows.values()] or [0])
    # base season: the last full season until the current one is half done, then the current one (MP on an 82 pace)
    use_cur = games >= 41
    bs = cur if use_cur else cur - 1
    K = fit['K'].get(str(cur - 1)) or list(fit['K'].values())[-1]
    lgts = (lg_cur if use_cur else lg_last)['ts']
    gh = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
    poss = [g['poss'] for g in gh if g.get('S') == cur - 1 and g.get('poss')]
    pace = sum(poss) / len(poss) if poss else 99.0
    keep = fit['breakout']['keep'] + fit['breakout'].get('keep2', [])
    CB = json.load(open(BEST))
    tiers = [20.0, 25.0, 30.0]
    cf = json.load(open(CEIL))
    XS, PX = {}, {}        # sx0: the Nov 4 shrink the ceiling fit was trained on; PX: the board's pXPM (sxpm), the column shown
    for y in (bs, cur):
        try:
            xr = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{y}.json')))['players']
            XS[y] = {r['id']: r.get('sx0') for r in xr}; PX[y] = {r['id']: r.get('sxpm') for r in xr if not r.get('pr')}
        except (OSError, ValueError):
            XS[y], PX[y] = {}, {}
    rows = []
    for pid, now in cur_rows.items():
        a = dict(P.get((pid, bs)) or {})
        if not a:
            if bs == cur or now['mp'] < 150:
                continue
            a = dict(now)                                      # rookies and newcomers: this season so far
        if a['mp'] < 300:
            continue
        mp_real = a['mp']
        if a['y'] == cur and games:
            a['mp'] = a['mp'] * 82 / games                     # ln MP on a season pace; shrinkage keeps real MP
        hist = [P[(pid, s)] for s in range(bs - 4, bs + 1) if (pid, s) in P]
        if a['y'] == cur and not any(o['y'] == cur for o in hist):
            hist.append(a)
        s0 = shr(a['bpm'], mp_real)
        best = max([CB.get(pid, -9.0)] + [shr(o['bpm'], o['mp']) for o in hist] + [shr(now['bpm'], now['mp'])])
        if best >= BAR:
            continue                                           # already at the bar: a standout, not next up
        prv = P.get((pid, a['y'] - 1))
        bf = bo_feats(a, s0, 0.0, marcel(hist, a['y']), prev=shr(prv['bpm'], prv['mp']) if prv else None)
        xv = bf['base'] + sum([bf[k] for k in keep], [])
        p = sig_x(fit, xv)
        f = fit['breakout']['fit']
        cut, i = {}, 2
        for k in keep:
            for j, x in enumerate(bf[k]):
                lb = BO_LABEL[k][j]
                cut[lb] = cut.get(lb, 0.0) + f['b'][i] * (x - f['mu'][i])
                i += 1
        sig = [lb for lb, c in sorted(cut.items(), key=lambda kv: -kv[1])[:2] if c > 0.15]
        ht = HT.get(pid)
        t = []
        for U in tiers:
            dU = U - a['usage_pct']
            ts = predict(fit, 'ts_plus', a, hist, ht, dU)
            tov = max(3.0, predict(fit, 'tov_pct', a, hist, ht, dU))
            p100 = 2 * ts / 100 * (1 - tov / 100) * U / 100 * K
            t.append([round(p100 * pace / 100 * 36 / 48, 1), round(ts / 100 * lgts * 100, 1), 1 if dU > 9 else 0])
        sxb = XS[a['y']].get(pid) if a['y'] in XS else None
        sxc = PX[cur].get(pid); sxb0 = PX.get(a['y'], {}).get(pid)
        xc = round(ceiling(cf, sxb, a), 1) if sxb is not None else None
        rows.append({'id': pid, 'n': now['n'], 'x': sxc if sxc is not None else sxb0, 'xc': xc, 'tm': X.TEAM.get(now['tm'], now['tm']), 'pos': now['pos'],
                     'age': now['age'], 'ph': None, 'p': round(p, 3), 'best': round(best, 1),
                     'u': round(now['usage_pct'] if now['mp'] >= 60 else a['usage_pct'], 1), 't': t, 'sig': sig})
    # headshots from the XPM board file (ESPN ids)
    try:
        xp = {r['id']: r.get('ph') for r in json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{cur}.json')))['players']}
        for r in rows:
            if xp.get(r['id']):
                r['ph'] = 'https://a.espncdn.com/combiner/i?img=/i/headshots/nba/players/full/%s.png&w=96&h=70&scale=crop' % xp[r['id']]
    except (OSError, KeyError, ValueError):
        pass
    nrk = rookies(rows, cur)
    rows.sort(key=lambda r: -r['p'])
    B = fit['breakout']
    lab = lambda y: f'{y - 1}-{str(y)[2:]}'  # noqa: E731
    out = {'sport': 'nba', 'season': lab(cur), 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'base': lab(bs), 'u': {'lab': 'USG', 'dec': 1},
           'tiers': [{'k': u, 'lab': 'USG %d' % u} for u in tiers],
           'stat': {'lab': 'PTS/36', 'eff': 'TS%', 'dec': 1, 'edec': 1},
           'cur': {'lab': 'pXPM', 't': 'pXPM: predictive XPM, next season from this season and the two before, aged (XPM board)', 'dec': 1},
           'ceil': {'lab': 'CEIL', 't': 'ceiling XPM: 80th percentile season if usage rises %g points' % cf['scen'],
                    'dec': 1},
           'about': (f'players not yet at the bar (best shrunk BPM so far under +{BAR:g}, BPM shrunk to -2 by MP, k 600, about the '
                     f'80th percentile of 1,000+ MP seasons; this season to date counts); breakout = next season 1,000+ MP at +{BAR:g} '
                     f'or better for the first time; base {lab(bs)}; odds = logistic on shrunk BPM, ln MP + {", ".join(keep)} '
                     f'(leave-one-season-out 1990-2026, Holm; final t {B["final"]["t"]}, {B["final"]["won"]}/{B["final"]["seasons"]} seasons; '
                     'draft curve, coaching change, opportunity ahead, trend, splines, boosted trees, Platt tested and failed). '
                     'tiers: next-season TS+ and TOV% at that usage from players whose usage changed, shot profile '
                     '(2P%+, FT%+, FTr, 3PAr) sets how fast efficiency falls; PTS/36 = 2 x TS x (1 - TOV%) x USG x plays; '
                     'usage jumps past 9 points are beyond the data; '
                     f'CEIL = 80th percentile of next-season XPM with usage +{cf["scen"]:g} (cap {cf["ucap"]:g}): ridge on base-season shrunk XPM, '
                     'age, ln MP + usage change x age, usage, 2P%+, 3PAr+, XPM, held-out 80th-percentile loss '
                     f'(t {cf["final"]["t"]}, {cf["final"]["won"]}/{cf["final"]["seasons"]} seasons; '
                     f'{round(100 * cf["coverage"]["up"])}% of usage-up seasons under it)'
                     + (f'; rookies: odds of a rookie season at the bar from the draft slot (-ln pick, drafts 1990-2025, held-out t '
                        f'{json.load(open(ROOKIE))["final_vs_flat"]["t"]} vs the base rate)' if nrk else '')),
           'rows': rows[:400]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(rows), 'base', bs, 'games', games)


if __name__ == '__main__':
    main()
