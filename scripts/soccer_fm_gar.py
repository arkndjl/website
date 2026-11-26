#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""fGAR / fSV: soccer GAR and SV rebuilt from FotMob's season stat lists, the stand-in while Understat is down
(Understat's league endpoint has served a "come back soon" page since Nov 1 2026). data/soccer_fm_gar_fit.json.

    python3 scripts/soccer_fm_gar.py --fit      # fit on the finished seasons both sources cover (2020-21 on), write the fit
    python3 scripts/soccer_fm_gar.py --pull     # FotMob lists for this season into the cache (the live run does it itself)
    (the live run: scripts/soccer_players.py write() calls overlay() on the season in progress)

What FotMob has (data.fotmob.com/stats/<league>/season/<id>/<stat>.json, the lists scripts/soccer_more.py already
reads): season totals per player (minutes, goals, penalty goals, assists, xG, xA, xG on target, chances and big
chances created, shots, passes, dribbles, defensive actions, its match rating, keepers' saves and goals prevented) and
per team (xG for and against, goals for and against). What it does not have: who was on the pitch for which shot, so
no on/off, no xG plus-minus and no xGBuildup, the part of GAR that splits a side's xG between its players.
The stand-in: a ridge regression per position from FotMob's rates (a 90, relative to the league-season, shrunk toward
the position mean by minutes like GAR's own rates) and the side's xG for and against a match to the player's Understat
value a 90 (GAR's league-relative value, and SV's), fit on the seasons both sources cover. GAR's fit also reads the
player's own Understat value a 90 from the season before (GAR's plus-minus spans three seasons; the earlier seasons
are complete on file). League strength and the replacement line are GAR's and SV's own.
Live (overlay): for a league whose Understat files trail the results (soccer_players.staleness), each player's rate
is rate = w x his frozen Understat rate + (1 - w) x the FotMob estimate, w from the share of his minutes Understat saw
(the fit's blend table, measured on past seasons frozen at a quarter, half and three quarters); totals = rate x
FotMob's minutes. A player Understat never saw gets the FotMob estimate alone. When Understat is back in step the
staleness list is empty and the season file is Understat's again.
"""
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402
import names as NM  # noqa: E402

ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'soccer_fm_gar_fit.json')
CACHE = os.path.join(D.CACHE, 'fmg')
FMB5 = {'eng.1': 47, 'esp.1': 87, 'ger.1': 54, 'ita.1': 55, 'fra.1': 53}
FIRST = 2021                       # 2020-21: the first season FotMob lists xG for every big-five player

# FotMob list -> (our key, kind): 'tot' the list's value is the season total; 'p90' it is a 90 (unqualified players
# are not on the list); 'sub' also keep the list's second value under the given key
PSTATS = {
    'mins_played': ('min', 'tot', 'mp'), 'goals': ('g', 'tot', 'pg'), 'goal_assist': ('a', 'tot'),
    'expected_goals': ('xg', 'tot'), 'expected_assists': ('xa', 'tot'), 'expected_goalsontarget': ('xgot', 'tot'),
    'total_att_assist': ('kp', 'tot'), 'big_chance_created': ('bcc', 'tot'), 'big_chance_missed': ('bcm', 'tot'),
    'total_scoring_att': ('sh', 'p90'), 'ontarget_scoring_att': ('sot', 'p90'), 'accurate_pass': ('ps', 'p90'),
    'accurate_long_balls': ('lb', 'p90'), 'won_contest': ('dr', 'p90'), 'defensive_contributions': ('dc', 'p90'),
    'total_tackle': ('tk', 'p90'), 'interception': ('it', 'p90'), 'effective_clearance': ('cl', 'p90'),
    'outfielder_block': ('bl', 'p90'), 'ball_recovery': ('rc', 'p90'), 'poss_won_att_3rd': ('pw', 'p90'),
    'fouls': ('fo', 'p90'), 'penalty_won': ('pwn', 'tot'), 'penalty_conceded': ('pcn', 'tot'),
    'yellow_card': ('yc', 'tot'), 'red_card': ('rcd', 'tot'), 'rating': ('rt', 'val'),
    'saves': ('sv', 'p90'), '_goals_prevented': ('gp', 'tot'), 'goals_conceded': ('gc', 'p90'),
}
TSTATS = {'expected_goals_team': 'txg', 'expected_goals_conceded_team': 'txga', 'goals_team_match': 'tg',
          'goals_conceded_team_match': 'tga'}


def pos_of(code):
    """FotMob's position id -> GK / D / M / F (as scripts/soccer_more.py: wingers with the forwards)"""
    if code == 11:
        return 'GK'
    if 30 <= code < 40:
        return 'D'
    if 50 <= code < 80:
        return 'M'
    if code >= 80:
        return 'F'
    return 'M'


def season_bases(lg):
    d = D.get(f'https://www.fotmob.com/api/data/leagues?id={FMB5[lg]}') or {}
    out = {}
    for L in (d.get('stats') or {}).get('seasonStatLinks') or []:
        out.setdefault(int(L['Name'][-4:]), 'https://data.fotmob.com/' + L['RelativePath'].rsplit('/', 1)[0] + '/')
    return out


def _lists(base, raw=None):
    """{stat: [rows]} for the lists we read (raw: a research dump of every list, {stat: [{rows}]})"""
    out = {}
    if raw is not None:
        for st in list(PSTATS) + list(TSTATS):
            out[st] = [r for t in raw.get(st) or [] for r in t['rows']]
        return out
    have = {s.get('StatName') for s in (D.get(base + 'topstats.json') or {}).get('TopLists') or []}
    for st in list(PSTATS) + list(TSTATS):
        if st in have:
            x = D.get(base + st + '.json', tries=2) or {}
            out[st] = [r for t in x.get('TopLists') or [] for r in t.get('StatList') or []]
            time.sleep(0.1)
    return out


def table(lg, S, base=None, raw=None, fresh=6 * 3600):
    """league lg's season S on FotMob: {'players': [{p, n, team, tid, pos, min, mp, <stat totals; None = not on the
    list>}], 'teams': {tid: {mp, txg, txga, tg, tga} a match}}; cached (a finished season for good)"""
    p = os.path.join(CACHE, f'{lg}_{S}.json.gz')
    if raw is None and os.path.exists(p) and (S < D.current_season() or time.time() - os.path.getmtime(p) < fresh):
        return D.load(p)
    if raw is None and base is None:
        base = season_bases(lg).get(S)
        if not base:
            return None
    L = _lists(base, raw)
    P = {}
    for r in L.get('mins_played') or []:
        i = str(r.get('ParticiantId'))
        P[i] = {'p': 'fm' + i, 'n': r.get('ParticipantName'), 'team': r.get('TeamName'), 'tid': str(r.get('TeamId')),
                'pos': pos_of((r.get('Positions') or [0])[0] or 0), 'min': int(r.get('StatValue') or 0),
                'mp': int(r.get('SubStatValue') or r.get('MatchesPlayed') or 0), 'cc': r.get('ParticipantCountryCode')}
    for st, spec in PSTATS.items():
        k, kind = spec[0], spec[1]
        if st == 'mins_played' or st not in L:
            continue
        for r in L[st]:
            o = P.get(str(r.get('ParticiantId')))
            if o is None or r.get('StatValue') is None:
                continue
            v = float(r['StatValue'])
            o[k] = round(v * o['min'] / 90, 3) if kind == 'p90' else v
            if len(spec) > 2 and r.get('SubStatValue') is not None:
                o[spec[2]] = float(r['SubStatValue'])
    T = {}
    for st, k in TSTATS.items():
        for r in L.get(st) or []:
            t = T.setdefault(str(r.get('TeamId')), {'mp': 0})
            mp = int(r.get('MatchesPlayed') or 0)
            t['mp'] = max(t['mp'], mp)
            v = float(r.get('StatValue') or 0)
            t[k] = v if k in ('tg', 'tga') else v / max(mp, 1)
    out = {'players': [o for o in P.values() if o['min'] > 0], 'teams': T, 'has': sorted(k for k in L if L[k])}
    if raw is None and out['players']:
        D.save(p, out)
    return out


# ---------------------------------------------------------------- features
TOT = ['g', 'pg', 'a', 'xg', 'xa', 'xgot', 'kp', 'bcc', 'bcm', 'pwn', 'pcn', 'yc', 'rcd']     # every player (absent = 0)
QUAL = ['sh', 'sot', 'ps', 'lb', 'dr', 'dc', 'tk', 'it', 'cl', 'bl', 'rc', 'pw', 'fo']          # qualified players only
GKS = ['sv', 'gp', 'gc']
FEATS = (['npxg', 'xa', 'fin', 'kp', 'bcc', 'bcm', 'xgotd', 'pg', 'pwn', 'pcn', 'yc', 'rcd'] + QUAL
         + ['rt', 'txg', 'txga', 'tfin', 'tsav', 'share'])
GK_FEATS = ['sv', 'gp', 'gc', 'ps', 'lb', 'rt', 'txg', 'txga', 'tfin', 'tsav', 'share']


def features(tab, shrink=900):
    """feature rows for one league-season table: each rate a 90 relative to the league-season (minutes-weighted),
    shrunk toward the position mean by min / (min + shrink); a rate the player has no list entry for sits at the
    position mean. Team terms (xG for / against a match, goals less xG for and against) are relative to the league
    and not shrunk. share = his minutes / the side's."""
    ps = [dict(o) for o in tab['players']]
    T = tab['teams']
    mu = lambda k: float(np.mean([t.get(k, 0.0) for t in T.values()])) if T else 0.0
    tm = {k: mu(k) for k in ('txg', 'txga', 'tg', 'tga')}
    for o in ps:
        m90 = max(o['min'], 1) / 90
        raw = {}
        for k in TOT:
            raw[k] = (o.get(k) or 0.0) / m90
        raw['npxg'] = ((o.get('xg') or 0.0) - (o.get('pg') or 0.0)) / m90          # a penalty scored ~ one penalty's xG taken
        raw['fin'] = ((o.get('g') or 0.0) - (o.get('xg') or 0.0)) / m90
        raw['xgotd'] = ((o.get('xgot') or 0.0) - (o.get('xg') or 0.0)) / m90 if o.get('xgot') is not None else 0.0
        for k in QUAL + GKS + ['rt']:
            raw[k] = None if o.get(k) is None else (o[k] if k == 'rt' else o[k] / m90)
        if o['pos'] != 'GK':
            for k in GKS:
                raw[k] = None
        o['_raw'] = raw
        t = T.get(o['tid']) or {}
        o['txg'] = t.get('txg', tm['txg']) - tm['txg']; o['txga'] = -(t.get('txga', tm['txga']) - tm['txga'])
        o['tfin'] = (t.get('tg', tm['tg']) - t.get('txg', tm['txg'])) - (tm['tg'] - tm['txg'])
        o['tsav'] = -((t.get('tga', tm['tga']) - t.get('txga', tm['txga'])) - (tm['tga'] - tm['txga']))
        o['share'] = o['min'] / max(1, 90 * (t.get('mp') or max(q['mp'] for q in ps)))
    keys = [k for k in ps[0]['_raw']] if ps else []
    for k in keys:
        have = [o for o in ps if o['_raw'][k] is not None]
        tot = sum(o['min'] for o in have) or 1
        m = sum(o['_raw'][k] * o['min'] for o in have) / tot
        for pos in ('GK', 'D', 'M', 'F'):
            g = [o for o in have if o['pos'] == pos]
            pm = sum(o['min'] for o in g) or 1
            pmu = sum((o['_raw'][k] - m) * o['min'] for o in g) / pm
            for o in ps:
                if o['pos'] != pos:
                    continue
                if o['_raw'][k] is None:
                    o[k] = pmu if g else 0.0
                else:
                    w = o['min'] / (o['min'] + shrink)
                    o[k] = w * (o['_raw'][k] - m) + (1 - w) * pmu
    for o in ps:
        del o['_raw']
    return ps


# ---------------------------------------------------------------- Understat side
def us_season(S, F=None, FS=None, LS=None):
    """Understat's season file S as one row per (league, player): minutes, the league-relative GAR value a 90 (gv) and
    SV value a 90 (sv_), and the lines to put back (league strength, replacement)"""
    import soccer_players as P
    import soccer_sv as SV
    F = F or P._fit(); FS = FS or SV._fit(); LS = LS or P.league_strength()
    d = json.load(open(os.path.join(P.SDIR, f'{S}.json')))
    agg = {}
    for o in d['players']:
        a = agg.setdefault((o['lg'], o['p']), {'p': o['p'], 'n': o['n'], 'lg': o['lg'], 'team': o['team'], 'pos': o['pos'],
                                              'min': 0, 'mx': 0, 'gar': 0.0, 'svar': 0.0, 'teams': []})
        a['min'] += o['min']; a['gar'] += o['gar']; a['svar'] += o.get('svar') or 0.0; a['teams'].append(o['team'])
        if o['min'] > a['mx']:
            a['mx'], a['team'], a['pos'] = o['min'], o['team'], o['pos']
    for a in agg.values():
        m90 = a['min'] / 90
        a['gar90'] = a['gar'] / m90; a['sv'] = a['svar'] / m90
        a['gv'] = a['gar90'] + F['repl'][a['pos']] - lg_g(F, LS, a['lg'], S)
        a['sv_'] = a['sv'] + FS['repl'][a['pos']] - lg_s(FS, LS, a['lg'], S)
    return list(agg.values())


def lg_g(F, LS, lg, S):
    import soccer_players as P
    return (F.get('lgScale') or {}).get('k', 0.0) * P.lg_of(LS, lg, S)


def lg_s(FS, LS, lg, S):
    import soccer_players as P
    return FS['lgScale']['k'] * P.lg_of(LS, lg, S)


def link(fm, us, ahead=0):
    """FotMob rows -> Understat rows of the same league-season, through scripts/names.py. Clubs are paired first (a
    FotMob club id -> the Understat title most of its exact-name players carry: FC Köln / FC Cologne), then each
    player by name + club, then by an exact name alone (a mid-season move files him under one club on FotMob).
    Minutes must agree, so same-name players stay apart; ahead = matches FotMob has that Understat does not (the
    live overlay). Returns {fm p: us row}"""
    def near(r, o):
        tol = max(200, .25 * max(r['min'], o['min']))
        return r['min'] - tol <= o['min'] <= r['min'] + tol + 96 * ahead
    byk = defaultdict(list)
    for r in us:
        byk[NM.key(r['n'])].append(r)
    votes = defaultdict(lambda: defaultdict(int))
    for o in fm:
        c = [r for r in byk.get(NM.key(o['n'] or ''), []) if near(r, o)]
        if len(c) == 1:
            votes[o['tid']][c[0]['team']] += 1
    club = {t: max(v, key=v.get) for t, v in votes.items()}
    M = NM.Matcher(us, name='n', team='team', pos=None, sport='soccer', team_eq=lambda want, have: club.get(want) == have)
    out, used = {}, set()
    for o in sorted(fm, key=lambda o: -o['min']):
        r, how = M.find(o['n'] or '', team=o['tid'])
        if r is not None and id(r) not in used and near(r, o):
            out[o['p']] = r; used.add(id(r))
    return out


# ---------------------------------------------------------------- model
def _xy(rows, feats, target, prior):
    X = np.array([[r[f_] for f_ in feats] + ([r['pv'], r['pn']] if prior else []) + [1.0] for r in rows])
    return X, np.array([r[target] for r in rows]), np.array([r['min'] for r in rows], float)


def ridge(X, y, w, lam):
    """weighted ridge on standardised columns (the intercept free); returns coefficients on the raw columns"""
    sd = X[:, :-1].std(0); sd[sd == 0] = 1
    Z = np.column_stack([X[:, :-1] / sd, X[:, -1]])
    A = Z.T @ (Z * w[:, None]); pen = lam * w.sum() / len(w) * np.eye(Z.shape[1]); pen[-1, -1] = 0
    b = np.linalg.solve(A + pen, Z.T @ (w * y))
    b[:-1] /= sd
    return b


def fit_models(rows, lam, target, prior):
    """{pos: coefficient list} (feature order: feats(pos) [+ pv, pn] + intercept)"""
    out = {}
    for pos in ('GK', 'D', 'M', 'F'):
        g = [r for r in rows if r['pos'] == pos]
        X, y, w = _xy(g, feats_of(pos), target, prior)
        out[pos] = [round(float(x), 6) for x in ridge(X, y, w, lam)]
    return out


def feats_of(pos):
    return GK_FEATS if pos == 'GK' else FEATS


def predict(r, co, prior):
    f = feats_of(r['pos'])
    x = [r[f_] for f_ in f] + ([r.get('pv', 0.0), r.get('pn', 1.0)] if prior else []) + [1.0]
    return float(np.dot(co[r['pos']], x))


def prior_of(us_prev, p, k=900):
    """(his Understat GAR value a 90 the season before, shrunk to 0 by minutes; 1 if he has none)"""
    q = us_prev.get(p)
    if not q:
        return 0.0, 1.0
    return q['gv'] * q['min'] / (q['min'] + k), 0.0


def dataset(seasons, raws=None, shrink=900):
    """training rows: FotMob features of season S joined to the Understat row (gv, sv_) and the prior (pv, pn)"""
    import soccer_players as P
    import soccer_sv as SV
    F, FS, LS = P._fit(), SV._fit(), P.league_strength()
    US = {S: us_season(S, F, FS, LS) for S in sorted(set(seasons) | {S - 1 for S in seasons})}
    out = []
    for S in seasons:
        prev = defaultdict(dict)
        for r in US[S - 1]:
            q = prev[r['p']]
            if not q or r['min'] > q['min']:
                prev[r['p']] = r
        for lg in FMB5:
            tab = table(lg, S, raw=raws[(lg, S)] if raws else None)
            if not tab:
                continue
            fr = features(tab, shrink)
            us = [r for r in US[S] if r['lg'] == lg]
            L = link(fr, us)
            for o in fr:
                u = L.get(o['p'])
                o['S'], o['lg'] = S, lg
                if u is None:
                    continue
                o['us'] = u['p']; o['upos'] = u['pos']; o['umin'] = u['min']
                o['gv'], o['sv_'] = u['gv'], u['sv_']
                o['pv'], o['pn'] = prior_of(prev, u['p'])
                out.append(o)
    return out


LAM, SHRINK = 3, 450              # picked on the training seasons in every outer fold (research/soccer_fotmob_nov26)
RESEARCH = os.path.join(HERE, 'research', 'soccer_fotmob_nov26', 'results.json')
TARGETS = {'gar': ('gv', True), 'sv': ('sv_', False)}


def fit():
    """the models on every finished season both sources cover; the blend table and the held-out record come from the
    research run (it needs the Understat match cache for the freezes)"""
    seasons = list(range(FIRST, D.current_season()))
    ds = dataset(seasons, shrink=SHRINK)
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'seasons': [seasons[0], seasons[-1]],
           'rows': len(ds), 'lam': LAM, 'shrink': SHRINK, 'feats': FEATS, 'gkFeats': GK_FEATS,
           'co': {m: fit_models(ds, LAM, tg, pr) for m, (tg, pr) in TARGETS.items()}}
    try:
        old = json.load(open(FIT))
    except OSError:
        old = {}
    out['blend'], out['test'] = old.get('blend'), old.get('test')
    if os.path.exists(RESEARCH):
        R = json.load(open(RESEARCH))
        out['blend'] = R['blend']
        out['test'] = {'seasons': R['seasons'], 'matchedMinutes': round(float(np.mean(list(R['matchedMinutes'].values()))), 3),
                       'r': {m: round(float(np.mean([v['r'] for v in R['emulator'][m].values()])), 3) for m in TARGETS},
                       'freeze': {k: {x: v[x] for x in ('rmse', 'describe', 'top150', 't_C3_vs_C0', 't_C3_vs_C1',
                                                         'won_C3_vs_C0', 'won_C3_vs_C1', 'n')} for k, v in R['freeze'].items()},
                       'blendUp': R['blendUp']}
    json.dump(out, open(FIT, 'w'), indent=1, allow_nan=False)
    print(json.dumps({k: v for k, v in out.items() if k != 'co'}, indent=1))
    return out


_FIT = []


def _fit():
    if not _FIT:
        try:
            _FIT.append(json.load(open(FIT)))
        except OSError:
            _FIT.append(None)
    return _FIT[0]


def blend_at(G, m, depth):
    """(a, k) of w = a x umin / (umin + k) at this depth (the share of the played matches Understat saw): the table's
    points joined by straight lines, and from the deepest one to (1, a 1, k 0)"""
    pts = sorted((float(f), a, k) for f, (a, k) in G['blend'][m].items()) + [(1.0, 1.0, 0.0)]
    if depth <= pts[0][0]:
        return pts[0][1], pts[0][2]
    for (f0, a0, k0), (f1, a1, k1) in zip(pts, pts[1:]):
        if depth <= f1:
            t = (depth - f0) / (f1 - f0)
            return a0 + t * (a1 - a0), k0 + t * (k1 - k0)
    return 1.0, 0.0


def _spread(o, delta):
    """a change in his total over the league average, onto off / def / oth by their size"""
    tot = abs(o['off']) + abs(o['def']) + abs(o['oth'])
    sh = {k: abs(o[k]) / tot for k in ('off', 'def', 'oth')} if tot > 0 else \
        {'off': 0.0 if o['pos'] in ('GK', 'D') else 1.0, 'def': 1.0 if o['pos'] in ('GK', 'D') else 0.0, 'oth': 0.0}
    for k in ('off', 'def', 'oth'):
        o[k] = round(o[k] + sh[k] * delta, 2)


def overlay(S, out, stale, F, FS, LS):
    """the season file's rows (Understat's, as far as it got) moved onto FotMob for each league in `stale`
    (soccer_players.staleness): minutes and counting stats to date, GAR and SV at the blended rate. Players Understat
    never saw are added (p = 'fm' + FotMob id). Returns {lg: {us, fm, n, new}} for the leagues moved; a league FotMob
    cannot serve stays as it was."""
    G = _fit()
    if not G or not G.get('blend') or not stale:
        return {}
    prev = {}
    try:
        for r in us_season(S - 1, F, FS, LS):
            if r['p'] not in prev or r['min'] > prev[r['p']]['min']:
                prev[r['p']] = r
    except OSError:
        pass
    moved = {}
    for lg in sorted({x['lg'] for x in stale}):
        try:
            tab = table(lg, S)
        except Exception as e:                         # the stand-in never stops the build
            print(f'fotmob {lg}: {e!r}', file=sys.stderr)
            continue
        us = [o for o in out if o['lg'] == lg]
        usg = max([o['mp'] for o in us] or [0])
        if not tab or not tab['teams'] or 'expected_goals' not in tab['has'] or 'expected_goals_team' not in tab['has']:
            continue
        fmg = max(t['mp'] for t in tab['teams'].values())
        if fmg <= usg:
            continue
        fr = features(tab, G['shrink'])
        L = link(fr, us, ahead=fmg - usg)
        depth = usg / fmg
        (ag, kg), (as_, ks) = blend_at(G, 'gar', depth), blend_at(G, 'sv', depth)
        title = defaultdict(lambda: defaultdict(int))
        for o in fr:
            if o['p'] in L:
                title[o['tid']][L[o['p']]['team']] += 1
        byp = defaultdict(list)
        for o in us:
            byp[o['p']].append(o)
        n = new = 0
        for o in fr:
            u = L.get(o['p'])
            pos = u['pos'] if u else o['pos']
            o['pv'], o['pn'] = prior_of(prev, u['p']) if u else (0.0, 1.0)
            eg = predict(o, G['co']['gar'], True) + lg_g(F, LS, lg, S) - F['repl'][pos]
            es = predict(o, G['co']['sv'], False) + lg_s(FS, LS, lg, S) - FS['repl'][pos]
            pg = o.get('pg') or 0.0
            fm = {'g': int(o.get('g') or 0), 'a': int(o.get('a') or 0), 'xg': o.get('xg') or 0.0, 'xa': o.get('xa') or 0.0,
                  'npxg': max(0.0, (o.get('xg') or 0.0) - pg), 'kp': int(o.get('kp') or 0)}
            if u is None:
                if o['min'] < 90:
                    continue
                t = title.get(o['tid'])
                row = {'p': o['p'], 'n': o['n'], 'team': max(t, key=t.get) if t else o['team'], 'lg': lg, 'pos': pos,
                       'mp': o['mp'], 'min': o['min'], 'g': fm['g'], 'a': fm['a'], 'npxg': round(fm['npxg'], 2),
                       'xa': round(fm['xa'], 2), 'xg': round(fm['xg'], 2), 'sh': round(o.get('sh') or 0), 'kp': fm['kp'],
                       'ch': 0.0, 'bu': 0.0, 'st': min(o['mp'], round(o['min'] / 90)), 'onxgd': 0.0, 'off': 0.0, 'def': 0.0, 'oth': 0.0, 'fph': o['p'][2:]}
                _spread(row, (eg + F['repl'][pos]) * o['min'] / 90)
                rg, rs = eg, es
                out.append(row); u = row; new += 1
            else:
                oth = [q for q in byp[u['p']] if q is not u]
                um = u['min']
                nmin = max(um, o['min'] - sum(q['min'] for q in oth))
                wg, ws = ag * um / (um + kg), as_ * um / (um + ks)
                rg = wg * u['gar90'] + (1 - wg) * eg
                rs = ws * u.get('sv', u['gar90']) + (1 - ws) * es
                x = nmin / max(um, 1)
                _spread(u, (rg + F['repl'][pos]) * nmin / 90 - (u['off'] + u['def'] + u['oth']))
                for k in ('g', 'a', 'kp'):
                    u[k] = max(u[k], fm[k] - sum(q[k] for q in oth))
                for k in ('xg', 'xa', 'npxg'):
                    u[k] = round(max(0.0, fm[k] - sum(q[k] for q in oth)), 2) if not oth else round(u[k] * x, 2)
                if o.get('sh') is not None and not oth:
                    u['sh'] = round(o['sh'])
                else:
                    u['sh'] = round(u['sh'] * x)
                u['ch'], u['bu'], u['st'] = round(u['ch'] * x, 2), round(u['bu'] * x, 2), round(u['st'] * x)
                u['mp'] = max(u['mp'], o['mp'] - sum(q['mp'] for q in oth))
                u['min'] = nmin
                n += 1
            m90 = u['min'] / 90
            u['gar90'], u['v90'] = round(rg, 3), round(rg + F['repl'][pos], 3)
            u['gar'] = round(rg * m90, 2); u['par'] = round(u['gar'] * F['ptsPerGoal'], 2)
            u['sv'], u['svar'] = round(rs, 3), round(rs * m90, 2)
            u['fm'] = 1
        # a regular on both sides with no partner is likely one player under two spellings: data/name_aliases.json
        got = {id(r) for r in L.values()}
        miss = [f"{r['n']} ({r['team']})" for r in us if id(r) not in got and r['min'] >= 300]
        if miss:
            print(f'fotmob stand-in {lg}: no FotMob match for', '; '.join(miss), file=sys.stderr)
        moved[lg] = {'us': usg, 'fm': fmg, 'n': n, 'new': new}
        print('fotmob stand-in', lg, moved[lg], f'depth {depth:.2f} w {ag:.2f}/{as_:.2f}', flush=True)
    return moved


def preview(S=None):
    """--overlay: the committed season file moved onto FotMob in place (a file already moved is left alone; the live
    run rebuilds from Understat's rows each time)"""
    import soccer_players as P
    import soccer_sv as SV
    S = S or D.current_season()
    path = os.path.join(P.SDIR, f'{S}.json')
    d = json.load(open(path))
    if d.get('fmg') or not d.get('stale'):
        print('nothing to do:', 'already on FotMob' if d.get('fmg') else 'Understat in step')
        return
    F, FS, LS = P._fit(), SV._fit(), P.league_strength()
    d['fmg'] = overlay(S, d['players'], d['stale'], F, FS, LS)
    P.finish(S, d['players'], S)
    d['games'] = max(o['mp'] for o in d['players'])
    d['asof'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    open(path, 'w').write(json.dumps(d, separators=(',', ':'), allow_nan=False))
    top = json.load(open(P.OUT))
    top['asof'], top['players'] = d['asof'], d['players'][:300]
    json.dump(top, open(P.OUT, 'w'), separators=(',', ':'), allow_nan=False)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--overlay' in sys.argv:
        preview()
    elif '--pull' in sys.argv:
        for lg in FMB5:
            t = table(lg, D.current_season(), fresh=0)
            print(lg, len(t['players']) if t else None, flush=True)
