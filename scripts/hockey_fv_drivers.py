#!/usr/bin/env python3
"""Hockey prospects FV driver search (Noah, Oct 24 2026): new draft-time and post-draft candidates for
scripts/hockey_prospects.py, tested on the same outcome FV, the same leave-one-class-out rule (t >= 2, 8 of 12
classes) and two extra checks a driver has to pass before it ships:

  top     the first 64 picks of each class, out-of-class grades: MSE and Spearman against the outcome
  forward fit 2008-15, grade 2016-19 (classes the fit never saw): MSE, and Spearman among the top 64

    python3 scripts/hockey_fv_drivers.py --pull   # full NHL landing pages + CHL (HockeyTech) seasons -> scripts/.cache/hockey
    python3 scripts/hockey_fv_drivers.py          # candidates -> data/hockey_fv_drivers.json

Data (free): NHL landing pages (every season line: league, team, GP, G, A, PIM, +/-, playoffs, WJC/U18 lines) and
HockeyTech's public CHL feeds (OHL/WHL/QMJHL skater seasons: power-play and short-handed points, +/-, team, birth
date). CHL seasons join the picks by birth date plus the shared name matcher (scripts/names.py), an exact join.
"""
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hockey_prospects as H
import names as NM
import nhl_data as D

FULL = os.path.join(H.CACHE, 'full')
CHLD = os.path.join(H.CACHE, 'chl')
OUT = os.path.join(ROOT, 'data', 'hockey_fv_drivers.json')
HT = 'https://lscluster.hockeytech.com/feed/?feed=modulekit&fmt=json&lang=en&key=%s&client_code=%s'
HTKEY = {'ohl': 'f1aa699db3d81487', 'whl': '41b145a848f4bd67', 'lhjmq': 'f322673b6bcae299'}   # the leagues' public site keys
HTLG = {'ohl': 'OHL', 'whl': 'WHL', 'lhjmq': 'QMJHL'}
PRO = .38


# -- pulls --------------------------------------------------------------------------------------------------------
def _get(u):
    for _ in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': D.UA}), timeout=90).read())
        except Exception:
            pass
    return None


def pull():
    rows = json.load(gzip.open(H.ROWS, 'rt'))
    ids = sorted({r['id'] for r in rows if r.get('id')})
    os.makedirs(FULL, exist_ok=True); os.makedirs(CHLD, exist_ok=True)

    def land(i):
        fn = os.path.join(FULL, f'{i}.json')
        if os.path.exists(fn):
            return
        j = D.get(f'https://api-web.nhle.com/v1/player/{i}/landing')
        if j:
            keep = {k: j.get(k) for k in ('playerId', 'birthDate', 'position', 'shootsCatches')}
            keep['seasons'] = [{**{k: v for k, v in s.items() if not isinstance(v, dict)}, 'team': (s.get('teamName') or {}).get('default')}
                               for s in j.get('seasonTotals') or []]
            json.dump(keep, open(fn, 'w'), separators=(',', ':'))
    with ThreadPoolExecutor(12) as ex:
        list(ex.map(land, ids))
    jobs = []
    for c, k in HTKEY.items():
        for s in (_get(HT % (k, c) + '&view=seasons') or {}).get('SiteKit', {}).get('Seasons') or []:
            m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
            if m and 2006 <= int(m.group(1)) <= 2025:
                jobs.append((c, k, s['season_id'], int(m.group(1)) + 1))

    def season(j):
        c, k, sid, yr = j
        fn = os.path.join(CHLD, f'{c}_{yr}.json')
        if not os.path.exists(fn):
            d = _get(HT % (k, c) + f'&view=statviewtype&type=topscorers&season_id={sid}&first=0&limit=3000&stat=all&order_direction=')
            if d:
                json.dump(d['SiteKit'].get('Statviewtype'), open(fn, 'w'))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(season, jobs))
    print(len(ids), 'landing', len(os.listdir(FULL)), 'cached;', len(os.listdir(CHLD)), 'CHL seasons')


# -- CHL seasons ----------------------------------------------------------------------------------------------------
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def chl_tables():
    """{(league, season end year): {'players': [...], 'gf': {team: goals}, 'gp': {team: games}}}"""
    T = {}
    for fn in os.listdir(CHLD):
        c, yr = fn[:-5].split('_')
        d = json.load(open(os.path.join(CHLD, fn))) or []
        gf, tg = {}, {}
        ps = []
        for p in d:
            bd = None
            try:
                bd = dt.datetime.strptime(p.get('birthdate') or '', '%b %d, %Y').date().isoformat()
            except ValueError:
                pass
            parts = p.get('team_breakdown') or [p]
            for q in parts:
                gf[q['team_name']] = gf.get(q['team_name'], 0) + _num(q.get('goals'))
            nm = p['name']
            if ', ' in nm:                                  # QMJHL's feed writes 'Last, First'
                a, _, b = nm.partition(', '); nm = f'{b} {a}'
            ps.append({'name': nm, 'birth': bd, 'gp': _num(p['games_played']), 'g': _num(p['goals']), 'a': _num(p['assists']),
                       'pts': _num(p['points']), 'ppp': _num(p.get('power_play_goals')) + _num(p.get('power_play_assists')),
                       'shp': _num(p.get('short_handed_goals')) + _num(p.get('short_handed_assists')), 'pm': _num(p.get('plus_minus')),
                       'ppg_g': _num(p.get('power_play_goals')), 'ug': _num(p.get('unassisted_goals')), 'pim': _num(p.get('penalty_minutes')),
                       'parts': [(q['team_name'], _num(q.get('games_played')), _num(q.get('points')), _num(q.get('plus_minus'))) for q in parts]})
        # team games: the most games any player had for the team (a full season), team GF per game
        for p in ps:
            for t, g, _, _ in p['parts']:
                tg[t] = max(tg.get(t, 0), g)
        T[(HTLG[c], int(yr))] = {'players': ps, 'gf': gf, 'tg': tg,
                                 'by_birth': _index(ps)}
    return T


def _index(ps):
    out = {}
    for p in ps:
        if p['birth']:
            out.setdefault(p['birth'], []).append(p)
    return out


def chl_line(T, lg, yr, name, birth):
    t = T.get((lg, yr))
    if not t:
        return None
    for p in t['by_birth'].get(birth or '', []):
        if NM.same(p['name'], name):
            return p, t
    return None


def chl_feats(T, lg, yr, name, birth):
    hit = chl_line(T, lg, yr, name, birth)
    if not hit:
        return None
    p, t = hit
    if p['gp'] < 10:
        return None
    # team goals while he was there: each stint's share of the team's goals per game
    tgf = sum(t['gf'].get(tm, 0) / max(t['tg'].get(tm, 1), 1) * g for tm, g, _, _ in p['parts'])
    esp = p['pts'] - p['ppp'] - p['shp']
    return {'esppg': esp / p['gp'], 'ppsh': p['ppp'] / max(p['pts'], 1), 'tsh': p['pts'] / max(tgf, 1),
            'gsht': p['g'] / max(tgf, 1), 'pmpg': p['pm'] / p['gp'], 'pimpg': p['pim'] / p['gp'], 'gfpg': tgf / p['gp'],
            'ppg': p['pts'] / p['gp']}


# -- landing lines --------------------------------------------------------------------------------------------------
def full(pid):
    fn = os.path.join(FULL, f'{pid}.json')
    return json.load(open(fn)) if pid and os.path.exists(fn) else None


INTL = re.compile(r'^(WJC|WJ18|U18|Hlinka|U17|WHC-17|WC|OG)', re.I)


def intl_feats(seasons, y):
    """tournament play up to the draft (seasons ending in y or earlier): WJC (U20) and U18 lines"""
    wjc, wjcgp, wjcp, u18gp, u18p = 0, 0, 0, 0, 0
    for s in seasons:
        sid = s['season'] // 10000 + 1
        if sid > y:
            continue
        lg = s.get('leagueAbbrev') or ''
        gp, pts = s.get('gamesPlayed') or 0, s.get('points') or 0
        if lg.startswith('WJC'):
            wjc = 1; wjcgp += gp; wjcp += pts
        elif lg.startswith(('WJ18', 'U18', 'Hlinka', 'U17', 'WHC-17')):
            u18gp += gp; u18p += pts
    return {'wjc': wjc, 'wjcppg': wjcp / wjcgp if wjcgp else None, 'u18gp': u18gp, 'u18ppg': u18p / u18gp if u18gp else None}


def season_feats(seasons, sid, goalie):
    """every regular-season club line of one season: pro games, playoff ppg, PIM, +/-"""
    ls = [s for s in seasons if s['season'] == sid and not H.TOURN.match(s.get('leagueAbbrev') or '')]
    reg = [s for s in ls if s.get('gameTypeId') == 2]
    po = [s for s in ls if s.get('gameTypeId') == 3]
    progp = sum(s.get('gamesPlayed') or 0 for s in reg if H.is_pro(s['leagueAbbrev']))
    gp = sum(s.get('gamesPlayed') or 0 for s in reg)
    pogp = sum(s.get('gamesPlayed') or 0 for s in po)
    pop = sum(s.get('points') or 0 for s in po)
    pof = max((H.nhle_of(s['leagueAbbrev']) for s in po), default=0)
    sv = [(s.get('savePctg'), s.get('gamesPlayed') or 0, s['leagueAbbrev']) for s in reg if s.get('savePctg')]
    return {'progp': progp, 'gp': gp, 'pogp': pogp, 'ponhle': 82 * pof * pop / pogp if pogp >= 4 else None, 'sv': sv}


# -- the frame ------------------------------------------------------------------------------------------------------
def build_rows():
    W = H.war_tables()
    rows = H.read_rows(W)
    H.nhl_so_far(rows, W)
    T = chl_tables()
    # league-season schedule length and goalie save% norms from the cached lines
    sched, svn = {}, {}
    land = {}
    for r in rows:
        L = full(r['id'])
        land[r['id']] = L
        for s in (L or {}).get('seasons') or []:
            if s.get('gameTypeId') == 2 and not H.TOURN.match(s.get('leagueAbbrev') or ''):
                k = (s['leagueAbbrev'], s['season'])
                sched[k] = max(sched.get(k, 0), s.get('gamesPlayed') or 0)
                if s.get('savePctg') and (s.get('gamesPlayed') or 0) >= 10:
                    svn.setdefault(k, []).append((s['savePctg'], s['gamesPlayed']))
    svm = {k: sum(a * b for a, b in v) / sum(b for _, b in v) for k, v in svn.items() if len(v) >= 3}
    # drafted teammates: picks on the same club line in a season (a team-strength proxy) and their points
    team_picks = {}
    for r in rows:
        for s in (land.get(r['id']) or {}).get('seasons') or []:
            if s.get('gameTypeId') == 2 and s.get('team'):
                team_picks.setdefault((s['leagueAbbrev'], s['team'], s['season']), []).append((r['id'], r['year'], s.get('points') or 0))
    for r in rows:
        L = land.get(r['id']) or {}
        ss = L.get('seasons') or []
        y = r['year']
        sid0, sidm = (y - 1) * 10000 + y, (y - 2) * 10000 + y - 1
        r['x'] = x = {}
        x['shoots'] = L.get('shootsCatches')
        x['intl'] = intl_feats(ss, y)
        x['s0'] = season_feats(ss, sid0, r['G'])
        x['sm'] = season_feats(ss, sidm, r['G'])
        d0 = r.get('d0')
        x['sched0'] = sched.get((d0['lg'], sid0)) if d0 else None
        x['chl0'] = chl_feats(T, d0['lg'], y, r['name'], r.get('birth')) if d0 and d0['lg'] in H.CHL else None
        dm = r.get('dm1')
        x['chlm'] = chl_feats(T, dm['lg'], y - 1, r['name'], r.get('birth')) if dm and dm['lg'] in H.CHL else None
        # drafted teammates in the draft year (picks from earlier or the same class or later, on his main club line)
        main = H.main_line(ss, sid0)
        if main and main.get('team'):
            tp = team_picks.get((main['leagueAbbrev'], main['team'], sid0), [])
            x['tm_n'] = len([1 for i, _, _ in tp if i != r['id']])
            x['tm_pts'] = sum(p for i, _, p in tp if i != r['id'])
        else:
            x['tm_n'], x['tm_pts'] = None, None
        # goalie: games-weighted save% above the league-season norm
        gsv = [(sv - svm[(lg, sid0)], g) for sv, g, lg in x['s0']['sv'] if (lg, sid0) in svm and g >= 5]
        x['gsv'] = sum(a * b for a, b in gsv) / sum(b for _, b in gsv) if gsv else None
        x['ggp'] = sum(b for _, b in gsv) if gsv else 0
        # post-draft seasons: tournament play (WJC after the draft), CHL usage, pro games
        x['post'] = {}
        for k in range(1, 5):
            sid = (y + k - 1) * 10000 + y + k
            q = r['post'].get(k)
            x['post'][k] = {'sf': season_feats(ss, sid, r['G']),
                            'wjc': int(any((s.get('leagueAbbrev') or '').startswith('WJC') and s['season'] == sid for s in ss)),
                            'chl': chl_feats(T, q['lg'], y + k, r['name'], r.get('birth')) if q and q['lg'] in H.CHL else None}
    return rows


# -- candidates -----------------------------------------------------------------------------------------------------
def cand_feats(r):
    f = H.feats(r)
    x = r['x']
    sk = not r['G']
    d0 = r.get('d0') or {}
    nh = d0.get('nhle')
    age = r['age'] if r.get('age') is not None else 18.5
    b = r.get('birth') or ''
    mon = int(b[5:7]) if len(b) >= 7 else 6
    c0, cm = x.get('chl0'), x.get('chlm')
    f1 = H.nhle_of(d0.get('lg')) if d0 else 0
    I = x['intl']
    f.update({
        # age, nonlinear: the young for the class (born after June) and overagers (19+ at the draft)
        'late': int(mon >= 7 and age < 18.5), 'over': int(age >= 19.0),
        'nhleAge': 0.0 if not sk or nh is None else nh / 10 * (1 + .35 * (18.5 - age)) - nh / 10,
        # two-year NHLe and the year before alone
        'nhle2': 0.0 if not sk or nh is None else ((r.get('dm1') or {}).get('nhle') or nh) / 10 - nh / 10,
        'dm1gp': min(((r.get('dm1') or {}).get('gp') or 0), 68) / 68 * int(sk and (r.get('dm1') or {}).get('grp') == d0.get('grp')),
        # availability: share of the league schedule played in the draft year
        'avail': 0.0 if not sk or not d0 or not x.get('sched0') else min(d0['gp'] / x['sched0'], 1) - .85,
        'progp': min(x['s0']['progp'], 60) / 60 * int(sk),
        'po': 0.0 if not sk or x['s0']['ponhle'] is None or nh is None else (x['s0']['ponhle'] - nh) / 10,
        'pim': 0.0,
        # CHL detail (HockeyTech): even-strength points, PP share, share of team goals, +/- per game, team scoring
        'chlES': 0.0 if not c0 else 82 * f1 * c0['esppg'] / 10 - 82 * f1 * c0['ppg'] / 10 * .62,
        'chlPP': 0.0 if not c0 else c0['ppsh'] - .32,
        'chlTsh': 0.0 if not c0 else (c0['tsh'] - .25) * 10,
        'chlGsh': 0.0 if not c0 else (c0['gsht'] - .1) * 10,
        'chlPM': 0.0 if not c0 else c0['pmpg'] * 3,
        'chlGF': 0.0 if not c0 else c0['gfpg'] - 3.3,
        'chlPIM': 0.0 if not c0 else c0['pimpg'] - .8,
        'chlTshG': 0.0 if not c0 or not cm else (c0['tsh'] - cm['tsh']) * 10,
        # international play to the draft: a WJC (U20) roster spot, U18 scoring
        'wjc': I['wjc'] * int(sk), 'wjcG': I['wjc'] * r['G'],
        'u18': 0.0 if not sk or I['u18ppg'] is None else I['u18ppg'] - .6,
        'u18any': int(I['u18gp'] > 0),
        # team strength by drafted teammates
        'tmN': 0.0 if x['tm_n'] is None else min(x['tm_n'], 8) - 2,
        # league-specific NHLe slopes
        'nhleCHL': 0.0 if not sk or nh is None else int(d0.get('grp') == 'chl') * nh / 10,
        'nhleEU': 0.0 if not sk or nh is None else int(d0.get('grp') in ('epro', 'ejr')) * nh / 10,
        'nhleUS': 0.0 if not sk or nh is None else int(d0.get('grp') in ('usjr', 'ncaa')) * nh / 10,
        'lnhle': 0.0 if not sk or nh is None else math.log(max(nh, 1)) - math.log(15) - (nh / 10 - 1.5) * .4,
        # positions: centres; right-shot defence
        'C': int(r['pos'] == 'C'), 'rD': int(r['D'] and x.get('shoots') == 'R'),
        # goalies: draft-year save% over the league norm, games
        'gsv': 0.0 if not r['G'] or x['gsv'] is None else x['gsv'] * 100, 'ggp': 0.0 if not r['G'] else min(x['ggp'], 60) / 60 - .5,
    })
    return f


CANDS = ['late', 'over', 'nhleAge', 'nhle2', 'dm1gp', 'avail', 'progp', 'po', 'chlES', 'chlPP', 'chlTsh', 'chlGsh', 'chlPM',
         'chlGF', 'chlPIM', 'chlTshG', 'wjc', 'wjcG', 'u18', 'u18any', 'tmN', 'nhleCHL', 'nhleEU', 'nhleUS', 'lnhle', 'C', 'rD',
         'gsv', 'ggp']


def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def checks(F, y, cls, picks, cols):
    """top-of-board (first 64 picks, out-of-class) and forward (fit 2008-15, grade 2016-19) checks"""
    _, p = H.score(F, y, cls, cols)
    top = picks <= 64
    out = {'topMse': float(np.mean((p[top] - y[top]) ** 2)), 'topRho': spearman(p[top], y[top]),
           'r1Rho': float(np.mean([spearman(p[(cls == c) & (picks <= 32)], y[(cls == c) & (picks <= 32)]) for c in sorted(set(cls))]))}
    X = np.array([[f[c] for c in cols] for f in F])
    tr, te = cls <= 2015, cls >= 2016
    b = H.ols(X[tr], y[tr]); q = np.clip(H.pred(b, X[te]), 20, 80)
    tt = te & (picks <= 64)
    out.update({'fwdMse': float(np.mean((q - y[te]) ** 2)), 'fwdTopMse': float(np.mean((q[tt[te]] - y[tt]) ** 2)),
                'fwdTopRho': spearman(q[tt[te]], y[tt])})
    return {k: round(v, 4) for k, v in out.items()}


def stage_cands(r, k, fv0):
    f = H.stage_feats(r, k, fv0)
    x = r['x']['post'].get(k) or {}
    q = r['post'].get(k) or {}
    d0 = r.get('d0') or {}
    sk = not r['G']
    nh0, nh = d0.get('nhle'), q.get('nhle')
    c = x.get('chl')
    f.update({'sgrow': 0.0 if not sk or nh is None or nh0 is None or f['pro'] else (nh - nh0) / 10,
              'swjc': x.get('wjc', 0) * int(sk), 'swjcG': x.get('wjc', 0) * r['G'],
              'sprogp': min((x.get('sf') or {}).get('progp', 0), 70) / 70,
              'sTsh': 0.0 if not c else (c['tsh'] - .3) * 10, 'sES': 0.0 if not c else (c['esppg'] - .7),
              'sPM': 0.0 if not c else c['pmpg'] * 3})
    return f


SCANDS = ['sgrow', 'swjc', 'swjcG', 'sprogp', 'sTsh', 'sES', 'sPM']


def main():
    rows = build_rows()
    W = None
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); picks = np.array([r['pick'] for r in tr])
    F = [cand_feats(r) for r in tr]
    fitd = json.load(open(H.FIT))
    base = fitd['kept']
    cov = {'chl0': sum(1 for r in tr if r['x']['chl0']), 'chl_d0': sum(1 for r in tr if (r.get('d0') or {}).get('grp') == 'chl'),
           'landing': sum(1 for r in tr if full(r['id'])), 'wjc': sum(1 for r in tr if r['x']['intl']['wjc']),
           'u18': sum(1 for r in tr if r['x']['intl']['u18gp']), 'gsv': sum(1 for r in tr if r['x']['gsv'] is not None)}
    print('coverage', cov, 'of', len(tr))
    s0, _ = H.score(F, y, cls, base)
    c0 = checks(F, y, cls, picks, base)
    print('current', base, 'mse', round(s0.mean(), 3), c0)
    single = {}
    for c in CANDS:
        s, _ = H.score(F, y, cls, base + [c])
        d = s0 - s
        t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0
        ck = checks(F, y, cls, picks, base + [c])
        X = np.array([[f[k] for k in base + [c]] for f in F]); b = H.ols(X, y)
        single[c] = {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum()), 'b': round(float(b[-1]), 3),
                     'nz': int(sum(1 for f in F if f[c] != 0)), **{k: round(ck[k] - c0[k], 4) for k in ck}}
        print(f'{c:9s}', single[c])
    kept, ev, cur = H.select(F, y, cls, base, CANDS, log=print)
    fin = checks(F, y, cls, picks, kept)
    print('selected', kept, 'mse', round(cur.mean(), 3), fin)
    # stages
    oof = {id(r): float(p) for r, p in zip(tr, H.score(F, y, cls, kept)[1])}
    oof0 = {id(r): float(p) for r, p in zip(tr, H.score(F, y, cls, base)[1])}
    stages = {}
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season()]
        Fk = [stage_cands(r, k, oof0[id(r)]) for r in sub]
        yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub])
        sb = fitd['stages'][str(k)]['kept']
        sk0, _ = H.score(Fk, yk, ck, sb)
        one = {}
        for c in SCANDS:
            s, _ = H.score(Fk, yk, ck, sb + [c]); d = sk0 - s
            t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0
            one[c] = {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum())}
        kk, _, curk = H.select(Fk, yk, ck, sb, SCANDS)
        pk = np.array([r['pick'] for r in sub])
        stages[k] = {'base': sb, 'mse': round(float(sk0.mean()), 3), 'kept': kk, 'mseNew': round(float(curk.mean()), 3), 'single': one,
                     'checksBase': checks(Fk, yk, ck, pk, sb), 'checksNew': checks(Fk, yk, ck, pk, kk)}
        print('stage', k, stages[k])
    out = {'asof': dt.date.today().isoformat(), 'coverage': cov, 'picks': len(tr), 'base': base, 'baseMse': round(float(s0.mean()), 3),
           'baseChecks': c0, 'single': single, 'selected': kept, 'selectedMse': round(float(cur.mean()), 3), 'selectedChecks': fin,
           'stages': stages}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    if '--pull' in sys.argv:
        pull()
    else:
        main()
