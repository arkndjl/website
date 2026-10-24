#!/usr/bin/env python3
"""Round-2 research harness for NFL XV parts (results: data/nfl_xv_round2.json, note research/round2-nfl-xv.md).

    python3 scripts/nfl_xv_round2.py --extract DIR   # compact plays from pbp + pbp_participation (+ FTN) in DIR
    python3 scripts/nfl_xv_round2.py --rapm          # idea 1: OL RAPM, forward team test
    python3 scripts/nfl_xv_round2.py --xv DIR        # ideas 1-3 as XV parts in nfl_xv's own fit
    python3 scripts/nfl_xv_round2.py --proj DIR      # idea 2 for projections: next-season per-game PPR / yards

DIR holds the downloaded nflverse files: part_<y>.csv (pbp_participation 2016-25), ngs_{passing,rushing,receiving}.csv.gz,
ftn_<y>.csv (2022-25). Play-by-play comes through nfl_war.get (scripts/.cache/nfl).

Gates, set before any result was seen:
  1 OL RAPM. Ridge per season of each dropback's pressure, sack and EPA on the five OL on the field (+1 each), with the
    defense and the passer as nuisance columns; each lineman shrunk toward decay x his rating through last season.
    Forward: next season's team pressure / sack rate / EPA per dropback from last season's team rate, with and without
    the new season's OL (dropback-weighted ratings through last season). Leave one season pair out; pass = paired t >= 2
    on squared error, most pairs better, and 2021-25 targets not worse; lambda / decay tuned on 2017-20 targets only.
    XV: an OL part from the rating (z, shrunk) must be kept (positive) by nfl_xv's NNLS and raise leave-one-season-out
    team r without lowering the missed-games XV SSE drop.
  2 NGS parts (RYOE/att RB; separation, cushion, YAC over expected WR/TE; time to throw, aggressiveness, CPOE QB) as
    XV parts, same XV gate. Projections: next-season PPR a game and yards a game, players with 6+ games both seasons,
    ridge on last season's line (ppg, volume, efficiency) with and without the NGS rates; leave one season pair out,
    t >= 2 on absolute error, most folds better.
  3 FTN (drops, catchable, contested, play action, created receptions, interception-worthy, QB-fault sacks), 2022-25:
    XV fit on 2022-25 only, leave one season out, base parts vs base + FTN parts, same XV gate.
"""
import csv
import gzip
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W   # noqa: E402
import nfl_xv as X    # noqa: E402

ROOT = W.ROOT
OUT = os.path.join(ROOT, 'data', 'nfl_xv_round2.json')
PLAYS = os.path.join(W.CACHE, 'r2plays_{}.pkl')
YEARS = list(range(2016, 2026))
OLPOS = {'T', 'G', 'C', 'OL', 'OT', 'OG'}


def ol_ids(y):
    ids = set()
    for r in W.rows(W.get(f'roster_{y}.csv', f'{W.REL}/rosters/roster_{y}.csv')):
        if r['position'] in OLPOS or r.get('depth_chart_position') in OLPOS:
            ids.add(r['gsis_id'])
    return ids


def extract(D):
    for y in YEARS:
        part = {}
        with open(os.path.join(D, f'part_{y}.csv'), newline='') as f:
            for r in csv.DictReader(f):
                part[(r['nflverse_game_id'], r['play_id'])] = (r['offense_players'], r['was_pressure'], r.get('offense_positions', ''),
                                                               r['time_to_throw'])
        ftn = {}
        fp = os.path.join(D, f'ftn_{y}.csv')
        if os.path.exists(fp):
            with open(fp, newline='') as f:
                for r in csv.DictReader(f):
                    ftn[(r['nflverse_game_id'], r['nflverse_play_id'])] = tuple(r[k] == 'TRUE' for k in (
                        'is_play_action', 'is_catchable_ball', 'is_contested_ball', 'is_created_reception', 'is_drop',
                        'is_interception_worthy', 'is_throw_away', 'is_qb_fault_sack'))
        ol = ol_ids(y)
        out = []
        src = W.get(f'play_by_play_{y}.csv.gz', f'{W.REL}/pbp/play_by_play_{y}.csv.gz')
        with gzip.open(src, 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['season_type'] != 'REG' or r['epa'] in ('', 'NA') or r['play_type'] not in ('pass', 'run'):
                    continue
                db = r['qb_dropback'] == '1'
                if not db and r['play_type'] != 'run':
                    continue
                k = (r['game_id'], r['play_id'])
                p = part.get(k)
                if not p:
                    continue
                offp = p[0].split(';')
                if p[2]:
                    lin = [g for g, ps in zip(offp, p[2].split(';')) if ps in OLPOS]
                else:
                    lin = [g for g in offp if g in ol]
                out.append({'g': r['game_id'], 'w': int(r['week']), 'o': r['posteam'], 'd': r['defteam'], 'db': db,
                            'qb': r['passer_player_id'] if db else '', 'ol': lin, 'sk': r['sack'] == '1',
                            'pr': p[1] == 'TRUE', 'epa': float(r['epa']), 'rec': r['receiver_player_id'] if r['receiver_player_id'] not in ('NA',) else '',
                            'cp': r['complete_pass'] == '1', 'ftn': ftn.get((r['game_id'], r['play_id']))})
        with open(PLAYS.format(y), 'wb') as f:
            pickle.dump(out, f)
        n5 = sum(1 for p in out if len(p['ol']) == 5)
        print(y, len(out), 'plays', n5, 'with 5 OL', sum(1 for p in out if p['db']), 'dropbacks', len(ftn), 'ftn', flush=True)


def plays(y):
    with open(PLAYS.format(y), 'rb') as f:
        return pickle.load(f)


# ---------------------------------------------------------------- idea 1: OL RAPM
def rapm_season(P, prior, lam, lam_n=300.0, target='pr'):
    """{gsis: rating} (per-play effect, up = more of the target) for one season's dropbacks (runs for target 'repa')."""
    import numpy as np
    if target == 'repa':
        P = [p for p in P if not p['db'] and 3 <= len(p['ol']) <= 6]
        yv = np.array([p['epa'] for p in P])
    else:
        P = [p for p in P if p['db'] and 3 <= len(p['ol']) <= 6]
        yv = np.array([float(p['pr']) if target == 'pr' else float(p['sk']) if target == 'sk' else p['epa'] for p in P])
    yv = yv - yv.mean()
    ids = {}
    for p in P:
        for g in p['ol']:
            ids.setdefault(g, len(ids))
    nol = len(ids)
    nus = {}
    for p in P:
        nus.setdefault('d' + p['d'], len(nus))
        if p['qb']:
            nus.setdefault('q' + p['qb'], len(nus))
    n = nol + len(nus)
    M = np.zeros((n, n)); b = np.zeros(n)
    for p, v in zip(P, yv):
        c = [ids[g] for g in p['ol']] + [nol + nus['d' + p['d']]] + ([nol + nus['q' + p['qb']]] if p['qb'] else [])
        M[np.ix_(c, c)] += 1; b[c] += v
    pv = np.zeros(n)
    for g, j in ids.items():
        pv[j] = prior.get(g, 0.0)
    reg = np.full(n, lam_n); reg[:nol] = lam
    beta = np.linalg.solve(M + np.diag(reg), b + reg * pv)
    cnt = Counter(g for p in P for g in p['ol'])
    return {g: float(beta[j]) for g, j in ids.items()}, cnt


def rapm_chain(target, lam, decay, years=YEARS):
    """ratings through each season: {y: {gsis: rating}} using seasons <= y, and plays counts."""
    prior, out, cnts = {}, {}, {}
    for y in years:
        r, c = rapm_season(plays(y), {g: decay * v for g, v in prior.items()}, lam, target=target)
        # carry players who sat out a season at their decayed prior
        new = {g: decay * v for g, v in prior.items()}
        new.update(r)
        out[y], cnts[y] = new, c
        prior = new
    return out, cnts


def team_rates(y):
    acc = defaultdict(lambda: [0, 0, 0, 0.0])
    olsh = defaultdict(Counter)
    for p in plays(y):
        if not p['db']:
            continue
        a = acc[p['o']]; a[0] += 1; a[1] += p['pr']; a[2] += p['sk']; a[3] += p['epa']
        for g in p['ol']:
            olsh[p['o']][g] += 1
    return {t: {'pr': a[1] / a[0], 'sk': a[2] / a[0], 'epa': a[3] / a[0], 'n': a[0]} for t, a in acc.items()}, olsh


def forward_rapm(demean=True, grid=((500, .5), (500, .8), (2000, .5), (2000, .8), (8000, .5), (8000, .8))):
    import numpy as np
    TR = {y: team_rates(y) for y in YEARS}
    res = {}
    for tgt in ('pr', 'sk', 'epa'):
        res[tgt] = {}
        for lam, decay in grid:
            R, _ = rapm_chain(tgt, lam, decay)
            rows = []
            for y in YEARS[:-1]:
                t0, _ = TR[y]; t1, sh1 = TR[y + 1]
                for t, v in t1.items():
                    if t not in t0:
                        continue
                    ol = sum(c * R[y].get(g, 0.0) for g, c in sh1[t].items()) / v['n']   # per dropback, 5 OL summed
                    rows.append((y + 1, t0[t][tgt], ol, v[tgt]))
            rows = np.array(rows)
            if demean:   # pressure charting levels jump by season (2018, 2023): score deviations from the season's mean
                for yt in set(rows[:, 0]):
                    m = rows[:, 0] == yt
                    for c in (1, 3):
                        rows[m, c] -= rows[m, c].mean()
            e0, e1 = [], []
            for yt in sorted(set(rows[:, 0])):
                tr, te = rows[rows[:, 0] != yt], rows[rows[:, 0] == yt]
                for cols, e in (([1], e0), ([1, 2], e1)):
                    A = np.column_stack([np.ones(len(tr))] + [tr[:, c] for c in cols])
                    cf = np.linalg.lstsq(A, tr[:, 3], rcond=None)[0]
                    At = np.column_stack([np.ones(len(te))] + [te[:, c] for c in cols])
                    e.append((yt, (te[:, 3] - At @ cf) ** 2))
            fold = {}
            d_all = []
            for (yt, a), (_, b_) in zip(e0, e1):
                fold[int(yt)] = round(float(a.mean() - b_.mean()) / float(a.mean()) * 100, 2)   # % SSE cut
                d_all.append((yt, a - b_))
            def tstat(sel):
                d = np.concatenate([x for yt, x in d_all if sel(yt)])
                return round(float(d.mean() / (d.std() / math.sqrt(len(d)))), 2)
            r_ol = float(np.corrcoef(rows[:, 2], rows[:, 3])[0, 1])
            res[tgt][f'{lam}/{decay}'] = {'pctSseCutByTarget': fold, 'tAll': tstat(lambda yt: True), 'tTune1720': tstat(lambda yt: yt <= 2020),
                                         'tHeld2125': tstat(lambda yt: yt >= 2021), 'rOlNext': round(r_ol, 3),
                                         'foldsBetter': sum(1 for v in fold.values() if v > 0), 'folds': len(fold)}
            print(tgt, lam, decay, res[tgt][f'{lam}/{decay}'], flush=True)
    return res


if __name__ == '__main__' and '--extract' in sys.argv:
    extract(sys.argv[sys.argv.index('--extract') + 1])
if __name__ == '__main__' and '--rapm' in sys.argv:
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d['olRapmForwardRaw'] = forward_rapm(False)
    d['olRapmForward'] = forward_rapm(True)
    json.dump(d, open(OUT, 'w'), indent=1)


# ---------------------------------------------------------------- XV parts
def ngs(D):
    """{(gsis, season): {part: [sum of value x n, n]}} from NGS weekly rows (weeks 1+, volume-weighted; the week-0
    season rows only carry qualified players)."""
    spec = {'rushing': [('ryoe', 'rush_yards_over_expected_per_att', 'rush_attempts')],
            'receiving': [('sep', 'avg_separation', 'targets'), ('cush', 'avg_cushion', 'targets'),
                          ('yacx', 'avg_yac_above_expectation', 'receptions')],
            'passing': [('ttt', 'avg_time_to_throw', 'attempts'), ('aggr', 'aggressiveness', 'attempts'),
                        ('xcpoe', 'completion_percentage_above_expectation', 'attempts')]}
    out = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for k, fields in spec.items():
        with gzip.open(os.path.join(D, f'ngs_{k}.csv.gz'), 'rt') as f:
            for r in csv.DictReader(f):
                if r['season_type'] != 'REG' or r['week'] == '0':
                    continue
                for part, col, ncol in fields:
                    v, n = r[col], W.num(r[ncol])
                    if v in ('', 'NA') or not n:
                        continue
                    a = out[(r['player_gsis_id'], int(r['season']))][part]
                    a[0] += float(v) * n; a[1] += n
    return out


def ftn_counts():
    """{(gsis, season): Counter} of FTN flags for passers and targeted receivers, 2022-25."""
    out = defaultdict(Counter)
    for y in (2022, 2023, 2024, 2025):
        for p in plays(y):
            f = p['ftn']
            if not p['db'] or not f:
                continue
            pa, catch, cont, created, drop, intw, away, qfs = f
            if p['qb']:
                q = out[(p['qb'], y)]
                q['db'] += 1; q['pa'] += pa; q['qfs'] += qfs
                if not p['sk'] and p['rec'] and not away:
                    q['aim'] += 1; q['catch'] += catch; q['intw'] += intw
            if p['rec']:
                r = out[(p['rec'], y)]
                r['tgt'] += 1; r['cont'] += cont; r['created'] += created; r['drop'] += drop
                if catch:
                    r['catchable'] += 1
                if cont:
                    r['cont_c'] += p['cp']
    return out


BASE = {g: list(v) for g, v in X.PARTS.items()}
BASE_K = dict(X.K)
BASE_RATES = X.rates


def set_parts(extra, K_extra):
    """extra: {group: {part: fn(p) -> (rate up = good, sample)}}: nfl_xv's PARTS / K / COLS / rates with these added."""
    for g in X.PARTS:
        X.PARTS[g] = BASE[g] + [p for p in extra.get(g, {}) if p not in BASE[g]]
    X.K.clear(); X.K.update(BASE_K); X.K.update(K_extra)
    X.COLS[:] = [(g, part) for g in X.GROUPS for part in X.PARTS[g]]

    def rates(p):
        r = BASE_RATES(p)
        for part, fn in extra.get(X.GROUP_OF[p['sub']], {}).items():
            r[part] = fn(p)
        return r
    X.rates = rates


def xv_eval(S, ys=None, lams=(5, 20, 50, 150)):
    """what nfl_xv.backtest judges a part by: leave-one-season-out team r by lambda (and each held-out season's team
    predictions), weights kept on all seasons, the missed-games test and the forward test on held-out XV."""
    X.zscore(S)
    _, value, _ = W.sub_lines()
    ys = ys or sorted(S)
    Ss = {y: S[y] for y in ys}
    cv, fold_r = {}, {}
    for lam in lams:
        pr, ac, fr = [], [], {}
        for y in ys:
            w = X.fit_w(Ss, [v for v in ys if v != y], lam)
            _, Xm, Y = X.team_matrix(Ss, [y])
            pr += list(Xm @ w); ac += list(Y); fr[y] = (list(Xm @ w), list(Y))
        cv[lam] = round(X.corr(pr, ac), 4); fold_r[lam] = fr
    lam = max(cv, key=cv.get)
    xv = {}
    for y in ys:
        w = X.fit_w(Ss, [v for v in ys if v != y], lam)
        xv[y] = X.xv_of(Ss, y, w, value)
    war = {y: [p['war'] for p in S[y]['players']] for y in ys}
    wall = X.fit_w(Ss, ys, lam)
    wd = {f'{g}.{part}': round(float(v), 4) for (g, part), v in zip(X.COLS, wall)}
    fw = X.forward_test(Ss, {'war': war, 'xv': xv})['xv'] if len(ys) > 3 else None
    return {'lambda': lam, 'lambdaCv': cv, 'missed': X.missed_test(Ss, {'xv': xv})['xv'], 'forward': fw,
            'weights': wd, '_fold': fold_r[lam]}


def compare(base, cand, new_parts):
    import numpy as np
    def sq(fold):
        out = {}
        for y, (p, a) in fold.items():
            p, a = np.array(p), np.array(a)
            out[y] = (a - a.mean() - (p - p.mean())) ** 2
        return out
    b, c = sq(base['_fold']), sq(cand['_fold'])
    d = np.concatenate([b[y] - c[y] for y in sorted(b)])
    later = [y for y in sorted(b)][len(b) // 2:]
    dl = np.concatenate([b[y] - c[y] for y in later])
    tt = lambda v: round(float(v.mean() / (v.std() / math.sqrt(len(v)))), 2)
    return {'teamR': [max(base['lambdaCv'].values()), max(cand['lambdaCv'].values())],
            'tTeamSq': tt(d), 'tTeamSqLaterHalf': tt(dl),
            'foldsBetter': sum(1 for y in b if b[y].mean() > c[y].mean()), 'folds': len(b),
            'kept': {k: v for k, v in cand['weights'].items() if k.split('.')[1] in new_parts},
            'missed': [base['missed'], cand['missed']], 'forward': [base['forward'], cand['forward']]}


def rate_of(tab, key, part, sign=1.0):
    def fn(p):
        a = tab.get((p['gsis'], p['y']), {}).get(part)
        return (sign * a[0] / a[1], a[1]) if a and a[1] else (None, 0)
    return fn


def run_xv(D):
    S = X.load()
    res = {}
    set_parts({}, {})
    base = xv_eval(S)
    res['base'] = {k: v for k, v in base.items() if not k.startswith('_')}
    print('base', res['base']['lambdaCv'], res['base']['missed'], flush=True)

    def trial(name, extra, Kx, ys=None, b=None):
        set_parts(extra, Kx)
        c = xv_eval(S, ys)
        new = {p for g in extra.values() for p in g}
        res[name] = compare(b or base, c, new)
        print(name, json.dumps(res[name]), flush=True)
        set_parts({}, {})

    # idea 1: OL RAPM, lambda / decay picked on the 2017-20 forward targets (least bad per target)
    tabs = {}
    for tgt, lam, dec, sign in (('pr', 8000, .8, -1), ('sk', 8000, .8, -1), ('epa', 8000, .5, 1)):
        R, C = rapm_chain(tgt, lam, dec)
        for y in R:
            for g, v in R[y].items():
                tabs.setdefault((g, y), {})['ol' + tgt] = [sign * v * max(1, C[y].get(g, 0)), max(1, C[y].get(g, 0))]
    ol = {f'ol{t}': rate_of(tabs, None, f'ol{t}') for t in ('pr', 'sk', 'epa')}
    K1 = {k: 1 for k in ol}
    trial('olRapm', {'OL': ol}, K1)
    # leak check: the in-season rating is fit on the on/off games the missed-games test scores, so also score last
    # season's rating (through y-1, decayed) as the part
    prev = {}
    for (g, y), v in tabs.items():
        prev[(g, y + 1)] = v
    trial('olRapm_prev_olepa', {'OL': {'olepa': rate_of(prev, None, 'olepa')}}, {'olepa': 1})
    for k in ol:
        trial('olRapm_' + k, {'OL': {k: ol[k]}}, {k: 1})
    # idea 2: NGS
    N = ngs(D)
    q = {'xcpoe': rate_of(N, None, 'xcpoe'), 'ttt_fast': rate_of(N, None, 'ttt', -1), 'ttt_slow': rate_of(N, None, 'ttt'),
         'aggr': rate_of(N, None, 'aggr'), 'aggr_safe': rate_of(N, None, 'aggr', -1)}
    rec = {'sep': rate_of(N, None, 'sep'), 'cush': rate_of(N, None, 'cush'), 'cush_tight': rate_of(N, None, 'cush', -1),
           'yacx': rate_of(N, None, 'yacx')}
    rb = {'ryoe': rate_of(N, None, 'ryoe')}
    K2 = {'xcpoe': 150, 'ttt_fast': 150, 'ttt_slow': 150, 'aggr': 150, 'aggr_safe': 150, 'sep': 100, 'cush': 100,
          'cush_tight': 100, 'yacx': 60, 'ryoe': 100}
    trial('ngs', {'QB': q, 'WR': rec, 'TE': rec, 'RB': rb}, K2)
    trial('ngs_QB', {'QB': q}, K2)
    trial('ngs_WRTE', {'WR': rec, 'TE': rec}, K2)
    trial('ngs_RB', {'RB': rb}, K2)
    # idea 3: FTN, 2022-25 only
    F = ftn_counts()
    def fr(num, den, sign=1.0):
        def fn(p):
            c = F.get((p['gsis'], p['y']))
            return (sign * c[num] / c[den], c[den]) if c and c[den] else (None, 0)
        return fn
    fq = {'catchr': fr('catch', 'aim'), 'intw': fr('intw', 'aim', -1), 'qfs': fr('qfs', 'db', -1), 'par': fr('pa', 'db')}
    frc = {'dropc': fr('drop', 'catchable', -1), 'contc': fr('cont_c', 'cont'), 'created': fr('created', 'tgt')}
    K3 = {'catchr': 150, 'intw': 300, 'qfs': 300, 'par': 150, 'dropc': 40, 'contc': 20, 'created': 100}
    ys4 = [2022, 2023, 2024, 2025]
    set_parts({}, {})
    b4 = xv_eval(S, ys4)
    res['base2225'] = {k: v for k, v in b4.items() if not k.startswith('_')}
    trial('ftn', {'QB': fq, 'WR': frc, 'TE': frc}, K3, ys4, b4)
    trial('ftn_QB', {'QB': fq}, K3, ys4, b4)
    trial('ftn_WRTE', {'WR': frc, 'TE': frc}, K3, ys4, b4)
    return res


PROJ_NGS = {'QB': ['xcpoe', 'ttt', 'aggr'], 'RB': ['ryoe'], 'WR': ['sep', 'cush', 'yacx'], 'TE': ['sep', 'cush', 'yacx']}
PROJ_K = {'xcpoe': 150, 'ttt': 150, 'aggr': 150, 'ryoe': 100, 'sep': 100, 'cush': 100, 'yacx': 60}
YDS = {'QB': 'passing_yards', 'RB': 'rushing_yards', 'WR': 'receiving_yards', 'TE': 'receiving_yards'}


def run_proj(D):
    """idea 2 for projections: next season's PPR a game and yards a game from last season's line, with and without the
    NGS rates (shrunk to the position mean by volume). Leave one season pair out, ridge."""
    import numpy as np
    N = ngs(D)
    seas = {}
    for y in range(2018, 2026):
        acc = defaultdict(lambda: defaultdict(float))
        for r in W.rows(W.get(f'stats_player_week_{y}.csv', f'{W.REL}/stats_player/stats_player_week_{y}.csv')):
            if r['season_type'] != 'REG' or r['position'] not in YDS:
                continue
            a = acc[r['player_id']]
            a['g'] += 1; a['pos_' + r['position']] += 1
            for k in ('fantasy_points_ppr', 'attempts', 'carries', 'targets', 'passing_yards', 'rushing_yards', 'receiving_yards',
                      'passing_epa', 'rushing_epa', 'receiving_epa', 'receptions'):
                a[k] += W.num(r.get(k))
        seas[y] = acc
    res = {}
    for pos in ('QB', 'RB', 'WR', 'TE'):
        rows = []
        for y in range(2018, 2025):
            # NGS rate means at the position this season, for shrinkage
            for gid, a in seas[y].items():
                if a['pos_' + pos] < a['g'] / 2 or a['g'] < 6:
                    continue
                b = seas[y + 1].get(gid)
                if not b or b['g'] < 6:
                    continue
                g = a['g']
                base = [a['fantasy_points_ppr'] / g, a[YDS[pos]] / g, a['attempts'] / g, a['carries'] / g, a['targets'] / g,
                        a['receptions'] / g, (a['passing_epa'] + a['rushing_epa'] + a['receiving_epa']) / g]
                ng = []
                for part in PROJ_NGS[pos]:
                    v = N.get((gid, y), {}).get(part)
                    ng.append((v[0] / v[1], v[1]) if v and v[1] else (None, 0))
                rows.append((y + 1, base, ng, b['fantasy_points_ppr'] / b['g'], b[YDS[pos]] / b['g']))
        # shrink NGS toward the position mean among these rows, by volume
        ngx = []
        for j, part in enumerate(PROJ_NGS[pos]):
            vals = [r[2][j] for r in rows if r[2][j][0] is not None]
            m = sum(v * n for v, n in vals) / sum(n for _, n in vals)
            ngx.append([m + (r[2][j][0] - m) * r[2][j][1] / (r[2][j][1] + PROJ_K[part]) if r[2][j][0] is not None else m for r in rows])
        B = np.array([r[1] for r in rows]); Ng = np.array(ngx).T; yr = np.array([r[0] for r in rows])
        out = {'n': len(rows), 'coverage': round(float(np.mean([any(x[0] is not None for x in r[2]) for r in rows])), 3)}
        for ti, tname in ((3, 'ppg'), (4, 'ypg')):
            T = np.array([r[ti] for r in rows])
            errs = {}
            for name, M in (('base', B), ('ngs', np.column_stack([B, Ng]))):
                e = np.zeros(len(rows))
                for yt in sorted(set(yr)):
                    tr, te = yr != yt, yr == yt
                    mu, sd = M[tr].mean(0), M[tr].std(0) + 1e-9
                    Z = (M[tr] - mu) / sd
                    A = np.column_stack([np.ones(tr.sum()), Z])
                    cf = np.linalg.solve(A.T @ A + np.diag([0] + [1.0] * Z.shape[1]), A.T @ T[tr])
                    e[te] = np.abs(T[te] - np.column_stack([np.ones(te.sum()), (M[te] - mu) / sd]) @ cf)
                errs[name] = e
            d = errs['base'] - errs['ngs']
            folds = {int(yt): round(float(d[yr == yt].mean()), 3) for yt in sorted(set(yr))}
            out[tname] = {'maeBase': round(float(errs['base'].mean()), 3), 'maeNgs': round(float(errs['ngs'].mean()), 3),
                          't': round(float(d.mean() / (d.std() / math.sqrt(len(d)))), 2), 'foldGain': folds,
                          'foldsBetter': sum(1 for v in folds.values() if v > 0)}
        res[pos] = out
        print(pos, json.dumps(out), flush=True)
    return res


if __name__ == '__main__' and '--proj' in sys.argv:
    r = run_proj(sys.argv[sys.argv.index('--proj') + 1])
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d['ngsProjections'] = r
    json.dump(d, open(OUT, 'w'), indent=1)
if __name__ == '__main__' and '--xv' in sys.argv:
    r = run_xv(sys.argv[sys.argv.index('--xv') + 1])
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d['xvParts'] = r
    json.dump(d, open(OUT, 'w'), indent=1)
