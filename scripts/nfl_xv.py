#!/usr/bin/env python3
"""XV for the NFL: WAR with each player's quality measured by the parts of his stat line that track team margin, in
place of AV's split of his team's points. The NFL twin of the college XV (scripts/cfb_xv_backtest.py).

    python3 scripts/nfl_xv.py --prep     # per player-season stat lines and missed games, 2018-25 (scripts/.cache/nfl/xv_<y>.json)
    python3 scripts/nfl_xv.py --fit      # fit and backtest: data/nfl_xv.json

Why it can differ from AV: the board's AV (scripts/nfl_war.py) is top-down. Each team's points scored and allowed set
an offense and a defense pool, and players split them by snaps and production, so a team's AV adds up to its points by
construction and the only thing AV can get right or wrong is the split inside a team. XV is bottom-up: a player's
rates (per snap, per carry, per target), z-scored inside his sub-position, are weighted by how much they move team
margin, and nothing ties a team's XV to its scoreboard.

  parts      per position group, rates oriented so up is good (PARTS below), from nflverse stats_player_week (EPA,
             CPOE, sacks, first downs, penalties), PFR's advanced stats via nflverse pfr_advstats (pressures, missed
             tackles, coverage allowed, yards after contact, broken tackles, drops; 2018 on) and play-by-play stops (the
             board's defensive credits). z on the season's regulars at the sub-position (40%+ of the side's snaps),
             each rate shrunk toward the mean by its sample (z x n / (n + K)), capped at 3 SD
  fit        team margin a game on each part's team sum of season share x z, ridge (lambda LAM on standardized sums),
             a part is kept only with the sign football says (non-negative least squares on the oriented parts)
  value      XV = what an average regular at his sub-position adds (data/nfl_war_pos.json value, the same line WAR uses)
             x share + share x quality, quality = sum of w x z in points a game at a full share, over 35.5 points a win
  tests      every season's XV is built from weights fit with that season left out (and the next one for the forward test)
    team       held-out team margin r (AV adds up to points by construction, so its r is a ceiling, not a rival)
    missed     the split inside a team: game margin on team-season ratings, home field, and each side's absent regulars'
               value a game (in points), XV against WAR, alone and together (which one survives the other)
    forward    next season's margin a game from returning players' value summed at their new team, alone and with
               last season's margin, leave one season pair out
    market     rank of the season's value against the rank of the next veteran contract (cap %), as nfl_war.py checks WAR
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W   # noqa: E402

ROOT = W.ROOT
CACHE = W.CACHE
REL = W.REL
OUT = os.path.join(ROOT, 'data', 'nfl_xv.json')
YEARS = list(range(2018, 2026))
PTS_PER_WIN = 35.5
GROUPS = {'QB': ['QB'], 'RB': ['RB'], 'WR': ['WR', 'SWR'], 'TE': ['TE'], 'OL': ['OT', 'IOL'], 'EDGE': ['EDGE'], 'DT': ['DT'],
          'LB': ['LB'], 'DB': ['CB', 'NCB', 'S']}
GROUP_OF = {s: g for g, ss in GROUPS.items() for s in ss}
OFF = {'QB', 'RB', 'WR', 'TE', 'OL'}
# the parts each group may load on, up is good; (name, numerator, denominator, shrink K in denominator units)
PARTS = {
    'QB': ['epa', 'cpoe', 'sackr', 'intr', 'bad', 'rush'],
    'RB': ['repa', 'fd', 'yco', 'btk', 'recv'],
    'WR': ['recv', 'tgt', 'fd', 'drop', 'btk'],
    'TE': ['recv', 'tgt', 'fd', 'drop', 'pen'],
    'OL': ['pen'],   # on-field pressure, sacks, line yards, run/pass EPA, gap runs, yards before contact: scripts/nfl_ol.py (all fail)
    'EDGE': ['prss', 'sk', 'stop', 'tfl', 'mtk', 'pen'],
    'DT': ['prss', 'sk', 'stop', 'tfl', 'mtk', 'pen'],
    'LB': ['stop', 'tfl', 'prss', 'mtk', 'covy', 'rtg', 'ball'],
    'DB': ['covy', 'rtg', 'ball', 'stop', 'mtk', 'pen'],
}
K = {'epa': 150, 'cpoe': 150, 'sackr': 150, 'intr': 300, 'bad': 150, 'rush': 300, 'repa': 100, 'fd': 300, 'yco': 100, 'btk': 150,
     'recv': 300, 'tgt': 300, 'drop': 40, 'pen': 500, 'prss': 300, 'sk': 600, 'stop': 300, 'tfl': 600, 'mtk': 30, 'covy': 300,
     'rtg': 30, 'ball': 400}


def num(x):
    return W.num(x)


# ---------------------------------------------------------------- prep
def season_players(y, sd=None, ros=None, b=None, fresh=False):
    """Player-team seasons with their AV, WAR and stat-line counts, and each regular's games for the missed-games test.
    sd, ros, b: the season data, rosters and AV coefficients when the caller (nfl_war.py build) already has them."""
    if b is None:
        with open(W.FIT) as f:
            b = json.load(f)['coef']
    sd = sd or W.season_data(y)
    if ros is None:
        ros, by_name = W.rosters(y)
        for (pfr, t), s_ in sd['snaps'].items():
            if pfr not in ros and (W.NM.key(s_['name']), t) in by_name:
                ros[pfr] = by_name[(W.NM.key(s_['name']), t)]
    lines, value, spread = W.sub_lines()
    team_alias = {a_: b_ for a_, b_ in (('LV', 'OAK'), ('OAK', 'LV'), ('LA', 'LAR'), ('LAR', 'LA'), ('LAC', 'SD'), ('SD', 'LAC'))
                  if a_ not in sd['team'] and b_ in sd['team']}
    tm = lambda t: team_alias.get(t, t)
    games = [g for g in W.rows(W.get('games.csv', W.GAMES)) if g['season'] == str(y) and g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    played_ids = {g['game_id'] for g in games}
    # extra play stats by (gsis, team)
    X = defaultdict(lambda: defaultdict(float))
    for r in W.rows(W.get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv')):
        if r['season_type'] != 'REG' or r.get('game_id') not in played_ids:
            continue
        x = X[(r['player_id'], tm(r['team']))]
        att, cp = num(r['attempts']), r.get('passing_cpoe', '')
        x['att'] += att; x['cmp'] += num(r['completions']); x['sk'] += num(r['sacks_suffered'] if 'sacks_suffered' in r else r.get('sacks'))
        x['pepa'] += num(r['passing_epa']); x['pint'] += num(r['passing_interceptions'])
        if cp not in ('', 'NA') and att:
            x['cpoe_w'] += num(cp) * att; x['cpoe_n'] += att
        x['car'] += num(r['carries']); x['repa'] += num(r['rushing_epa']); x['rfd'] += num(r['rushing_first_downs'])
        x['tgt'] += num(r['targets']); x['recepa'] += num(r['receiving_epa']); x['recfd'] += num(r['receiving_first_downs'])
        x['pen'] += num(r.get('penalties'))
        x['fum'] += num(r.get('rushing_fumbles_lost')) + num(r.get('receiving_fumbles_lost')) + num(r.get('sack_fumbles_lost'))
    # PFR advanced
    A = defaultdict(lambda: defaultdict(float))
    for kind, fields in (('def', ['def_targets', 'def_completions_allowed', 'def_yards_allowed', 'def_receiving_td_allowed', 'def_ints',
                                  'def_missed_tackles', 'def_tackles_combined']),
                         ('rush', ['carries', 'rushing_yards_after_contact', 'rushing_broken_tackles', 'receiving_broken_tackles']),
                         ('rec', ['receiving_drop', 'receiving_broken_tackles']),
                         ('pass', ['passing_bad_throws', 'times_pressured', 'passing_drops'])):
        p = W.get(f'advstats_week_{kind}_{y}.csv', f'{REL}/pfr_advstats/advstats_week_{kind}_{y}.csv', fresh and kind != 'def')
        for r in W.rows(p):
            if r['game_type'] != 'REG':
                continue
            a = A[(r['pfr_player_id'], tm(r['team']))]
            for f_ in fields:
                a[kind + ':' + f_] += num(r.get(f_))
    D = W.def_model()
    # missed games: snaps by game
    gl = sorted(games, key=lambda g: (int(g['week']), g['game_id']))
    snap, gmax = defaultdict(dict), defaultdict(lambda: [0.0, 0.0])
    for r in W.rows(W.get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv')):
        if r['game_type'] == 'REG' and r['game_id'] in played_ids:
            o, d = num(r['offense_snaps']), num(r['defense_snaps'])
            snap[(r['game_id'], r['team'])][r['pfr_player_id']] = (o, d)
            m = gmax[(r['game_id'], r['team'])]; m[0] = max(m[0], o); m[1] = max(m[1], d)
    tg = defaultdict(list)
    for g in gl:
        for t in (g['home_team'], g['away_team']):
            tg[t].append(g['game_id'])
    last = {}
    for t, ids in tg.items():
        for gid in ids:
            for pid in snap.get((gid, t), {}):
                last[pid] = max(last.get(pid, ('', '')), (gid[5:7] + gid, t))
    out = []
    for o in W.team_rows(sd, b, ros):
        pfr, t = o['pfr'], o['t']
        gsis = ros.get(pfr, {}).get('gsis_id', '')
        share17 = o['share'] * sd['team'][t]['g'] / 17
        st, x, a = o['st'], X.get((gsis, t), {}), A.get((pfr, t), {})
        pl = sd['dplay'].get((gsis, t), (0, 0, 0)) if 'dplay' in sd else (0, 0, 0)
        adv = sd['adv'].get((pfr, t)) if sd.get('adv') else None
        rec = {'pfr': pfr, 'gsis': gsis, 't': t, 'y': y, 'n': o['name'], 'sub': o['sub'], 'g': o['g'], 'av': o['av'], 'share': o['share'],
               'sh': share17, 'snaps': o['snaps'], 'games': o['games'],
               'war': W.war_of(o['av'], share17, o['sub'], lines, value, spread),
               'c': {**{k_: v for k_, v in x.items()}, **{k_: v for k_, v in a.items()},
                     'stopR': pl[0], 'stopP': pl[1], 'rtfl': pl[2], 'dsk': st.get('sack', 0.0), 'tkl': st.get('tkl', 0.0), 'tfl': st.get('tfl', 0.0),
                     'int': st.get('int', 0.0), 'pd': st.get('pd', 0.0), 'ff': st.get('ff', 0.0), 'prss': adv['prss'] if adv else 0.0,
                     'rec': st.get('rec', 0.0), 'rush': st.get('rush', 0.0)}}
        # regular: 6+ games and 60%+ of his side's snaps when he plays; absent games after his first, unless he moved on
        side = 0 if o['g'] in W.OFFENSE else 1
        ids = tg.get(t, [])
        played = [i for i, gid in enumerate(ids) if snap.get((gid, t), {}).get(pfr, (0, 0))[side] > 0]
        if len(played) >= 6:
            sh = [snap[(ids[i], t)][pfr][side] / max(1, gmax[(ids[i], t)][side]) for i in played]
            if sum(sh) / len(sh) >= 0.6:
                end = len(ids) if last.get(pfr, ('', t))[1] == t else played[-1] + 1
                rec['reg'] = {'gp': len(played), 'gsh': sum(sh) / len(sh), 'start': played[0], 'end': end, 'played': played}
        out.append(rec)
    sched = [{'id': g['game_id'], 'h': g['home_team'], 'a': g['away_team'], 'hs': num(g['home_score']), 'as': num(g['away_score']),
              'neutral': g.get('location') == 'Neutral'} for g in gl]
    teams = {t: {'g': v['g'], 'pf': v['pf'], 'pa': v['pa']} for t, v in sd['team'].items()}
    return {'players': out, 'sched': sched, 'tg': tg, 'teams': teams}


def prep(y):
    d = season_players(y)
    with open(os.path.join(CACHE, f'xv_{y}.json'), 'w') as f:
        json.dump(d, f, separators=(',', ':'))
    print(f'xv prep {y}: {len(d["players"])} player-team seasons, {sum(1 for r in d["players"] if "reg" in r)} regulars', flush=True)


if __name__ == '__main__':
    if '--prep' in sys.argv:
        ys = [int(a) for a in sys.argv[2:]] or YEARS
        for y in ys:
            prep(y)


# ---------------------------------------------------------------- parts
def rating(cmp_, att, yds, td, ints):
    """NFL passer rating."""
    if att <= 0:
        return None
    c = lambda v: max(0.0, min(2.375, v))
    return (c((cmp_ / att - .3) * 5) + c((yds / att - 3) * .25) + c(td / att * 20) + c(2.375 - ints / att * 25)) / 6 * 100


def rates(p):
    """{part: (rate up = good, sample)} for one player-team season."""
    c, grp, sn = p['c'], GROUP_OF[p['sub']], max(1.0, p['snaps'])
    g = lambda k: c.get(k, 0.0)
    per = lambda a, b_: (a / b_, b_) if b_ > 0 else (None, 0)
    if grp == 'QB':
        drop = g('att') + g('sk')
        return {'epa': per(g('pepa') + g('repa'), drop + g('car')), 'cpoe': per(g('cpoe_w'), g('cpoe_n')), 'sackr': per(-g('sk'), drop),
                'intr': per(-g('pint'), g('att')), 'bad': per(-g('pass:passing_bad_throws'), g('att')), 'rush': per(g('rfd'), drop + g('car'))}
    if grp == 'RB':
        return {'repa': per(g('repa'), g('car')), 'fd': per(g('rfd') + g('recfd'), sn), 'yco': per(g('rush:rushing_yards_after_contact'), g('rush:carries')),
                'btk': per(g('rush:rushing_broken_tackles') + g('rush:receiving_broken_tackles'), g('car') + g('tgt')), 'recv': per(g('recepa'), sn)}
    if grp in ('WR', 'TE'):
        return {'recv': per(g('recepa'), sn), 'tgt': per(g('tgt'), sn), 'fd': per(g('recfd'), sn), 'drop': per(-g('rec:receiving_drop'), g('tgt')),
                'btk': per(g('rec:receiving_broken_tackles'), g('tgt')), 'pen': per(-g('pen'), sn)}
    if grp == 'OL':
        return {'pen': per(-g('pen'), sn)}
    tk = g('def:def_tackles_combined') + g('def:def_missed_tackles')
    rt = rating(g('def:def_completions_allowed'), g('def:def_targets'), g('def:def_yards_allowed'), g('def:def_receiving_td_allowed'), g('def:def_ints'))
    return {'prss': per(g('prss'), sn), 'sk': per(g('dsk'), sn), 'stop': per(g('stopR') + g('stopP'), sn), 'tfl': per(g('rtfl'), sn),
            'mtk': per(-g('def:def_missed_tackles'), tk), 'pen': per(-g('pen'), sn), 'covy': per(-g('def:def_yards_allowed'), sn),
            'rtg': ((-rt, g('def:def_targets')) if rt is not None else (None, 0)), 'ball': per(g('int') + g('pd') + g('ff'), sn)}


def load():
    S = {}
    for y in YEARS:
        p = os.path.join(CACHE, f'xv_{y}.json')
        if os.path.exists(p):
            with open(p) as f:
                S[y] = json.load(f)
    return S


def zscore(S):
    """p['z'][part]: shrunk z on the season's regulars at the sub-position, capped at 3."""
    for y, d in S.items():
        by = defaultdict(list)
        for p in d['players']:
            p['r'] = rates(p)
            by[p['sub']].append(p)
        for sub, L in by.items():
            pool = [p for p in L if p['share'] >= 0.4]
            for part in PARTS[GROUP_OF[sub]]:
                v = [p['r'][part][0] for p in pool if p['r'][part][0] is not None]
                if len(v) < 8:
                    m, s = 0.0, None
                else:
                    m = sum(v) / len(v); s = math.sqrt(sum((x - m) ** 2 for x in v) / len(v)) or None
                for p in L:
                    r, n = p['r'][part]
                    p.setdefault('z', {})[part] = 0.0 if r is None or s is None else max(-3, min(3, (r - m) / s)) * n / (n + K[part])


COLS = [(g, part) for g in GROUPS for part in PARTS[g]]


def team_matrix(S, ys):
    import numpy as np
    keys, X, Y = [], [], []
    for y in ys:
        d = S[y]
        T = defaultdict(lambda: np.zeros(len(COLS)))
        for p in d['players']:
            g = GROUP_OF[p['sub']]
            row = T[p['t']]
            for j, (gg, part) in enumerate(COLS):
                if gg == g:
                    row[j] += p['share'] * p['z'][part]
        for t, tm in d['teams'].items():
            keys.append((y, t)); X.append(T[t]); Y.append((tm['pf'] - tm['pa']) / tm['g'])
    return keys, np.array(X), np.array(Y)


def nnls(A, b, iters=None):
    import numpy as np
    n = A.shape[1]; P = np.zeros(n, bool); w = np.zeros(n)
    for _ in range(iters or 3 * n):
        grad = A.T @ (b - A @ w)
        if P.all() or grad[~P].max() <= 1e-10:
            break
        P[np.argmax(np.where(~P, grad, -np.inf))] = True
        while True:
            s = np.zeros(n); s[P] = np.linalg.lstsq(A[:, P], b, rcond=None)[0]
            if (s[P] > 0).all():
                w = s; break
            m = P & (s <= 0)
            alpha = np.min(w[m] / (w[m] - s[m]))
            w = w + alpha * (s - w); P &= w > 1e-12
    return w


def fit_w(S, ys, lam):
    """Weights (points a game per unit of share x z) on team margin a game, sign-constrained ridge."""
    import numpy as np
    _, X, Y = team_matrix(S, ys)
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
    Xs = (X - mu) / sd
    A = np.vstack([Xs, math.sqrt(lam) * np.eye(len(COLS))]); b_ = np.concatenate([Y - Y.mean(), np.zeros(len(COLS))])
    w = nnls(A, b_)
    return w / sd


def quality(p, w):
    """points a game at a full share over an average regular at the sub-position (before centering)"""
    g = GROUP_OF[p['sub']]
    return sum(w[g + '.' + part] * p['z'][part] for part in PARTS[g])


def q_means(S, w):
    """snap-weighted mean quality of the regulars (6+ games, 60%+ of the snaps when playing) by sub-position over the
    seasons in S, so an average regular gets value[sub], as on WAR, and part-timers' lower rates come out below it"""
    acc = defaultdict(lambda: [0.0, 0.0])
    for d in S.values():
        for p in d['players']:
            if 'reg' not in p:
                continue
            a = acc[p['sub']]; a[0] += p['share'] * quality(p, w); a[1] += p['share']
    return {s: a[0] / a[1] for s, a in acc.items() if a[1]}


def xv_of(S, y, w, value, qm=None):
    """XV for each player-team row of season y on weights w ({'QB.epa': ...}): share x (value + quality in wins)."""
    if not isinstance(w, dict):
        w = {f'{g}.{part}': float(v) for (g, part), v in zip(COLS, w)}
    qm = qm if qm is not None else q_means(S, w)
    return [p['sh'] * (value[p['sub']] + (quality(p, w) - qm.get(p['sub'], 0.0)) * 17 / PTS_PER_WIN) for p in S[y]['players']]


# ---------------------------------------------------------------- tests
def corr(a, b_):
    import numpy as np
    return float(np.corrcoef(a, b_)[0, 1])


def missed_test(S, vals):
    """Game margin on team-season ratings + home field + absent regulars by sub-position (counts) and each measure's
    value a game above the sub-position's mean regular (points). vals: {name: {y: [value per player]}}. Returns the
    coefficient (1 = a point of value is a point of margin), its t, and the SSE drop over the counts-only model."""
    import numpy as np
    SUBS = W.SUBS
    names = list(vals)
    eqs, fe = [], {}
    for y, d in S.items():
        P = d['players']
        regs = defaultdict(list)
        per = {n: [] for n in names}
        for i, p in enumerate(P):
            if 'reg' in p:
                regs[p['t']].append(i)
        mu = {n: {} for n in names}
        for n in names:
            acc = defaultdict(list)
            for t, L in regs.items():
                for i in L:
                    acc[P[i]['sub']].append(vals[n][y][i] / P[i]['reg']['gp'] * PTS_PER_WIN)
            mu[n] = {s: sum(v) / len(v) for s, v in acc.items()}
        for g in d['sched']:
            x = np.zeros(len(SUBS) + len(names))
            for t, sgn in ((g['h'], 1), (g['a'], -1)):
                gi = d['tg'][t].index(g['id'])
                for i in regs.get(t, []):
                    r = P[i]['reg']
                    if r['start'] <= gi < r['end'] and gi not in r['played']:
                        x[SUBS.index(P[i]['sub'])] += sgn
                        for j, n in enumerate(names):
                            x[len(SUBS) + j] += sgn * (vals[n][y][i] / r['gp'] * PTS_PER_WIN - mu[n][P[i]['sub']])
            eqs.append((fe.setdefault((y, g['h']), len(fe)), fe.setdefault((y, g['a']), len(fe)), 0 if g['neutral'] else 1, x,
                        max(-35.0, min(35.0, g['hs'] - g['as']))))
    nf = len(fe)

    def run(cols):
        ne = len(SUBS) + len(cols)
        A = np.zeros((len(eqs), nf + 1 + ne)); Y = np.zeros(len(eqs))
        for i, (h, a_, hfa, x, m) in enumerate(eqs):
            A[i, h] = 1; A[i, a_] = -1; A[i, nf] = hfa; A[i, nf + 1:nf + 1 + len(SUBS)] = x[:len(SUBS)]
            for j, c in enumerate(cols):
                A[i, nf + 1 + len(SUBS) + j] = x[len(SUBS) + names.index(c)]
            Y[i] = m
        reg = np.zeros(A.shape[1]); reg[:nf] = 2
        M = A.T @ A + np.diag(reg); cf = np.linalg.solve(M, A.T @ Y); res = Y - A @ cf
        cov = (res @ res / (len(Y) - A.shape[1])) * np.linalg.inv(M)
        return cf, cov, float(res @ res)
    _, _, sse0 = run([])
    out = {'games': len(eqs)}
    for n in names:
        cf, cov, sse = run([n])
        j = nf + 1 + len(SUBS)
        out[n] = {'coef': round(float(-cf[j]), 3), 't': round(float(-cf[j] / math.sqrt(cov[j, j])), 2), 'sseDrop': round(sse0 - sse, 1)}
    if len(names) == 2:
        cf, cov, _ = run(names)
        j = nf + 1 + len(SUBS)
        out['together'] = {n: {'coef': round(float(-cf[j + k]), 3), 't': round(float(-cf[j + k] / math.sqrt(cov[j + k, j + k])), 2)} for k, n in enumerate(names)}
    return out


def forward_test(S, vals):
    """Next season's margin a game from returning players' value at their new team (alone, and with last margin);
    leave one season pair out. vals: {name: {(y, pair_next): [values in season y]}} -> R^2 and paired t against the first."""
    import numpy as np
    pairs = [y for y in sorted(S) if y + 1 in S]
    names = list(vals)
    data = defaultdict(list)   # (name, mode) -> rows (pair, x..., target)
    for y in pairs:
        P0, d1 = S[y]['players'], S[y + 1]
        tot = {n: defaultdict(float) for n in names}
        for i, p in enumerate(P0):
            for n in names:
                tot[n][p['pfr']] += vals[n][y][i]
        where = {}
        for p in d1['players']:
            if p['snaps'] > where.get(p['pfr'], ('', -1))[1]:
                where[p['pfr']] = (p['t'], p['snaps'])
        ret = {n: defaultdict(float) for n in names}
        for pfr, (t, _) in where.items():
            for n in names:
                ret[n][t] += tot[n].get(pfr, 0.0)
        for t, tm in d1['teams'].items():
            last = S[y]['teams'].get(t) or S[y]['teams'].get({'LV': 'OAK', 'LAR': 'LA', 'LAC': 'SD'}.get(t, t))
            lm = (last['pf'] - last['pa']) / last['g'] if last else 0.0
            target = (tm['pf'] - tm['pa']) / tm['g']
            for n in names:
                data[(n, 'alone')].append((y, [ret[n][t]], target))
                data[(n, 'withLast')].append((y, [ret[n][t], lm], target))
    data[('lastMargin', 'alone')] = [(y, [x[1]], tgt) for y, x, tgt in data[(names[0], 'withLast')]]
    out = {}
    errs = {}
    for (n, mode), R in data.items():
        e = []
        for y in pairs:
            tr = [r for r in R if r[0] != y]; te = [r for r in R if r[0] == y]
            A = np.array([[1] + r[1] for r in tr]); b_ = np.array([r[2] for r in tr])
            cf = np.linalg.lstsq(A, b_, rcond=None)[0]
            e += [(r[2] - np.array([1] + r[1]) @ cf) ** 2 for r in te]
        tg = np.array([r[2] for r in R])
        errs[(n, mode)] = np.array(e)
        out.setdefault(n, {})[mode] = {'r2': round(1 - float(np.mean(e)) / float(tg.var()), 3)}
    for n in names[1:]:
        for mode in ('alone', 'withLast'):
            d_ = errs[(names[0], mode)] - errs[(n, mode)]
            out[n][mode]['tVs' + names[0]] = round(float(d_.mean() / (d_.std() / math.sqrt(len(d_)))), 2)
    return out


def market_test(S, vals):
    """Rank by the season's value against rank by cap % of the next veteran contract (3+ years after the draft),
    players with 30%+ of the snaps (summed over teams), seasons before the last."""
    import gzip, io
    import numpy as np
    norm = W.NM.key
    raw = gzip.open(W.get('historical_contracts.csv.gz', W.CONTRACTS)).read().decode('utf-8')
    con = {}
    import csv
    for c_ in csv.DictReader(io.StringIO(raw)):
        try:
            ys_, cap, dy = int(c_['year_signed']), float(c_['apy_cap_pct']), c_['draft_year']
        except ValueError:
            continue
        if dy not in ('', 'NA') and ys_ - int(dy) >= 3:
            con.setdefault((norm(c_['player']), ys_), []).append((cap, c_['position']))
    names = list(vals)
    rowsm = []
    for y in sorted(S)[:-1]:
        agg = {}
        for i, p in enumerate(S[y]['players']):
            a = agg.setdefault(p['pfr'], {'n': p['n'], 'sub': p['sub'], 'sh': 0.0, **{n: 0.0 for n in names}})
            a['sh'] += p['share']
            for n in names:
                a[n] += vals[n][y][i]
        for a in agg.values():
            # one name can be two players: the contract whose position fits his
            c_ = max((cap for cap, pos in con.get((norm(a['n']), y + 1), []) if W.NM.pos_fits(pos, a['sub'])), default=None)
            if c_ and a['sh'] >= 0.3:
                rowsm.append((a, c_))
    rank = lambda v: np.argsort(np.argsort(v)) / len(v)
    rc = rank([c_ for _, c_ in rowsm])
    return {'contracts': len(rowsm), **{n: round(corr(rank([a[n] for a, _ in rowsm]), rc), 3) for n in names}}


def backtest(lams=(5, 20, 50, 150, 400)):
    import numpy as np
    S = load(); zscore(S)
    _, value, _ = W.sub_lines()
    ys = sorted(S)
    # lambda by leave-one-season-out team r
    cv = {}
    for lam in lams:
        pr, ac = [], []
        for y in ys:
            w = fit_w(S, [v for v in ys if v != y], lam)
            keys, X, Y = team_matrix(S, [y])
            pr += list(X @ w); ac += list(Y)
        cv[lam] = round(corr(pr, ac), 4)
    lam = max(cv, key=cv.get)
    # held-out XV (season left out) and the forward set (next season left out too)
    xv, xvf, war, av = {}, {}, {}, {}
    team = {'xv': [], 'war': [], 'margin': []}
    for y in ys:
        w = fit_w(S, [v for v in ys if v != y], lam)
        xv[y] = xv_of(S, y, w, value)
        w2 = fit_w(S, [v for v in ys if v not in (y, y + 1)], lam)
        xvf[y] = xv_of(S, y, w2, value)
        war[y] = [p['war'] for p in S[y]['players']]
        av[y] = [p['av'] for p in S[y]['players']]
        T = defaultdict(lambda: [0.0, 0.0])
        for p, a, b_ in zip(S[y]['players'], xv[y], war[y]):
            T[p['t']][0] += a; T[p['t']][1] += b_
        for t, tm in S[y]['teams'].items():
            team['xv'].append(T[t][0]); team['war'].append(T[t][1]); team['margin'].append((tm['pf'] - tm['pa']) / tm['g'])
    wall = fit_w(S, ys, lam)
    # the board's WAR: a blend of AV's WAR and XV, alpha on XV; the missed-games slope is 1 when a point of value is a
    # point of margin, so the blend is read off where it lands near 1 without giving up the forward or market tests
    blends = {}
    for a in ALPHAS:
        bl = {y: [a * u + (1 - a) * v for u, v in zip(xv[y], war[y])] for y in ys}
        blf = {y: [a * u + (1 - a) * v for u, v in zip(xvf[y], war[y])] for y in ys}
        m = missed_test(S, {'war': war, 'b': bl} if a else {'b': bl})
        halves = [missed_test({y: S[y] for y in h}, {'b': {y: bl[y] for y in h}})['b'] for h in (ys[:len(ys) // 2], ys[len(ys) // 2:])]
        f_ = forward_test(S, {'war': war, 'b': blf})['b'] if a else forward_test(S, {'b': blf})['b']
        blends[a] = {'missed': m['b'], 'missedTogetherWithWar': m.get('together'), 'missedHalves': halves,
                     'forward': {k_: v for k_, v in f_.items()}, 'market': market_test(S, {'b': bl})['b']}
    res = {'lambdaCv': cv, 'lambda': lam, 'blends': blends,
           'teamR': {'xv': round(corr(team['xv'], team['margin']), 3), 'war': round(corr(team['war'], team['margin']), 3)},
           'missed': missed_test(S, {'war': war, 'xv': xv}),
           'forward': forward_test(S, {'war': war, 'xv': xvf, 'av': av}),
           'market': market_test(S, {'war': war, 'xv': xv, 'av': av})}
    wd = {f'{g}.{part}': round(float(v), 4) for (g, part), v in zip(COLS, wall)}
    T = defaultdict(float)
    for y in ys:
        for p, v in zip(S[y]['players'], xv[y]):
            T[(y, p['t'])] += v
    Tw = defaultdict(float)
    for y in ys:
        for p in S[y]['players']:
            Tw[(y, p['t'])] += p['war']
    res['meanTeam'] = {'xv': round(sum(T.values()) / len(T), 2), 'war': round(sum(Tw.values()) / len(Tw), 2)}
    # alpha: where a point of blended value lost to an absence costs a point of margin (slope nearest 1)
    alpha = min(blends, key=lambda a: abs(blends[a]['missed']['coef'] - 1))
    model = {'alpha': alpha, 'lambda': lam, 'ptsPerWin': PTS_PER_WIN, 'K': K, 'parts': PARTS, 'weights': wd,
             'qMean': {s_: round(v, 4) for s_, v in q_means(S, wd).items()}}
    return res, model


ALPHAS = (0, 0.25, 0.4, 0.5, 0.6, 0.75, 1)


def board_xv(y, sd, ros, b, fresh=False, rows_out=None):
    """{pfr id: XV} for this season (nfl_war.py build), on the weights in data/nfl_xv.json; None without the file.
    z pools are this season's regulars (40%+ of the snaps so far), so mid-season rates shrink more (smaller samples).
    rows_out: a list that gets the season's player-team rows (the badges read their counts, scripts/nfl_badges.py)."""
    try:
        with open(OUT) as f:
            M = json.load(f)['model']
    except (OSError, KeyError, ValueError):
        return None, None
    _, value, _ = W.sub_lines()
    S = {y: season_players(y, sd, ros, b, fresh)}
    if rows_out is not None:
        rows_out.extend(S[y]['players'])
    zscore(S)
    out = defaultdict(float)
    for p, v in zip(S[y]['players'], xv_of(S, y, M['weights'], value, M['qMean'])):
        out[p['pfr']] += v
    return out, M['alpha']


if __name__ == '__main__' and '--fit' in sys.argv:
    r, model = backtest()
    import datetime
    with open(OUT, 'w') as f:
        json.dump({'asof': datetime.date.today().isoformat(), 'years': [YEARS[0], YEARS[-1]], 'model': model, 'backtest': r}, f, indent=1)
        f.write('\n')
    print(json.dumps({k_: v for k_, v in r.items() if k_ != 'weights'}, indent=1))
