#!/usr/bin/env python3
"""Provisional grades for hockey draft prospects off the board (audit item 33, Oct 25 2026; Noah's Oct 21 rule: unboarded
players start at the 20 floor, take every available driver, and are ranked on the board like boarded players, tagged
provisional).

    python3 scripts/hockey_fv_drivers.py --pull     # CHL seasons (HockeyTech) and pick careers, once
    python3 scripts/hockey_provisional.py --fit     # class-out fit -> data/hockey_prov_fit.json
    (scripts/hockey_prospects.py build calls live() for the coming class)

Population  Every draft-eligible skater (first, second or third year of eligibility, not drafted before) with a line in
            the OHL, WHL or QMJHL in classes 2008-19 and not on the pre-draft board. The board then is Central Scouting's
            final top BOARD_N North American skaters (about as many North American skaters as Tankathon's board holds).
Outcome     The same NHL outcome FV as the board (scripts/hockey_prospects.py): drafted players through their pick row;
            undrafted players through the NHL WAR tables, joined by the shared name matcher and age (most are 20, no
            NHL games).
Model       Ridge on outcome FV: the draft-year NHLe (fitted factors, data/hockey_nhle.json) and candidates (defence,
            age, size, games, the year before, NHLe squared) kept on the board's class-out rule (t >= 2, 8 of 12).
            Compared with the alternative the audit named (the board's draft model at a late slot), and a flat mean.
Live        The 2027 class: OHL/WHL/QMJHL and AHL draft-eligibles from HockeyTech's public feeds, Liiga U20 players from
            liiga.fi (birth date and size from each player's page, so the eligibility check and age drivers apply);
            NHLe shrunk to the population's mean with NHLE_K games, the rate drivers (+/-, PIM) shrunk to neutral the
            same way. Rows join the board with prov = 1.
Oct 29 2026 (Noah: feed provisional grades every driver available, and an approximate age where the birth date is
            missing). Every other field on the HockeyTech line went in as a candidate (centre, right-shot D, import,
            league rookie, born July+, goal share, PP share, SH points, +/-, PIM, share of team goals, team goals, age
            squared). Kept on the class-out rule: +/- a game and PIM a game, a line the year before missing, second or
            third year of eligibility; weight and defence fell out. MSE 11.16 -> 11.06 against the Oct 25 set (t 3.2,
            9 of 12 classes). Approximate age, tested by hiding every birth date: an age fitted on the line (rookie,
            games, size, NHLe; MAE .40 yr vs .57 for a flat 18.5) grades no better than the flat 18.5 (t -0.4), and the
            true age is worth t 4.5 over either, so the fix is real birth dates: Liiga's player pages have them (the
            old flat 18.5 there also let over-age and under-age Liiga players onto the board). AGE_EST stays the
            fallback when a page fails.
"""
import datetime as dt
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hockey_prospects as H
import names as NM
import nhl_data as D

CHLD = os.path.join(H.CACHE, 'chl')
CSSD = os.path.join(H.CACHE, 'css')
FIT = os.path.join(ROOT, 'data', 'hockey_prov_fit.json')
HTLG = {'ohl': 'OHL', 'whl': 'WHL', 'lhjmq': 'QMJHL'}
HT = 'https://lscluster.hockeytech.com/feed/?feed=modulekit&fmt=json&lang=en&key=%s&client_code=%s'
HTKEY = {'ohl': 'f1aa699db3d81487', 'whl': '41b145a848f4bd67', 'lhjmq': 'f322673b6bcae299', 'ahl': 'ccb91f29d6744675'}
LIIGA = 'https://liiga.fi/api/v2/players/stats/summed/%d/%d/runkosarja/true?dataType=basicStats'
LIIGA_INFO = 'https://liiga.fi/api/v2/players/info/%s'
CHL_LG = ('OHL', 'WHL', 'QMJHL')
BOARD_N, NHLE_K, MIN_GP = 55, 20, 10


# -- data --------------------------------------------------------------------------------------------------------
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _birth(s):
    try:
        return dt.datetime.strptime(s or '', '%b %d, %Y').date().isoformat()
    except ValueError:
        return None


def _ht(s):
    """HockeyTech height '6.02' = 6 ft 2 in"""
    m = re.match(r'^(\d)\.(\d{1,2})$', str(s or '').strip())
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def _flip(s):
    """QMJHL's feed writes 'Last, First' (names and clubs)"""
    a, sep, b = (s or '').partition(', ')
    return f'{b} {a}'.strip() if sep else s


CA_PROV = {'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'}
US_ST = set('AK AL AR AZ CA CO CT DC DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT NC ND NE NH NJ NM NV NY OH OK '
            'OR PA RI SC SD TN TX UT VA VT WA WI WV WY'.split())


def ht_nat(p):
    """a HockeyTech player's country (the flag only, not a model input): home country, else birth country, else the
    home province or state (WHL rows often leave the country blank; a 3-letter province is a country code)"""
    pv = (p.get('homeprov') or '').strip().upper()
    return (p.get('homecntry') or p.get('birthcntry') or ('Canada' if pv in CA_PROV else 'United States' if pv in US_ST else pv)
            or None)


def ht_players(d, lg):
    out = []
    for p in d or []:
        if (p.get('position') or '') == 'G':
            continue
        cn = p.get('homecntry') or ''
        out.append({'name': _flip(p.get('name') or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()), 'birth': _birth(p.get('birthdate')),
                    'pos': 'D' if p.get('position') == 'D' else 'F', 'ht': _ht(p.get('height')), 'wt': _num(p.get('weight')) or None,
                    'gp': _num(p.get('games_played')), 'pts': _num(p.get('points')), 'g': _num(p.get('goals')), 'lg': lg,
                    'club': _flip(p.get('team_name')), 'pid': p.get('player_id'), 'nat': ht_nat(p),
                    'C': int(p.get('position') == 'C'), 'shoots': p.get('shoots') or None, 'rookie': int(p.get('rookie') == '1'),
                    'imp': int(bool(cn) and cn not in ('Canada', 'United States')), 'ppp': _num(p.get('power_play_points')),
                    'shp': _num(p.get('short_handed_points')), 'pm': _num(p.get('plus_minus')), 'pim': _num(p.get('penalty_minutes')),
                    'parts': [(_flip(q.get('team_name')), _num(q.get('games_played')), _num(q.get('goals'))) for q in p.get('team_breakdown') or [p]]})
    return out


def team_totals(players):
    """(team goals, team games) by club in one league season: goals summed over every player's line for the team, games
    the most any player had for it"""
    gf, tg = {}, {}
    for p in players:
        for t, g, gl in p.get('parts') or [(p['club'], p['gp'], p['g'])]:
            tg[t] = max(tg.get(t, 0), g)
            gf[t] = gf.get(t, 0) + gl
    return gf, tg


def with_team(players):
    """each player's share of his club's goals (points over team goals, by games with the main club) and the club's goals a game"""
    gf, tg = team_totals(players)
    for p in players:
        t = p['club']
        if gf.get(t) and tg.get(t):
            p['tsh'] = p['pts'] / (gf[t] * max(p['gp'], 1) / tg[t]) if p['gp'] else None
            p['tgf'] = gf[t] / tg[t]
    return players


def chl_seasons():
    """{season end year: [players]} for the three CHL leagues, from the cached topscorers"""
    T = {}
    for fn in os.listdir(CHLD):
        c, yr = fn[:-5].split('_')
        T.setdefault(int(yr), []).extend(with_team(ht_players(json.load(open(os.path.join(CHLD, fn))), HTLG[c])))
    return T


def css(y):
    """Central Scouting final ranks, North American skaters: [(name, birth, rank)]"""
    fn = os.path.join(CSSD, f'{y}.json')
    if not os.path.exists(fn):
        j = D.get(f'https://api-web.nhle.com/v1/draft/rankings/{y}/1') or {}
        os.makedirs(CSSD, exist_ok=True)
        json.dump([(f"{r.get('firstName', '')} {r.get('lastName', '')}".strip(), r.get('birthDate'), r.get('finalRank') or r.get('midtermRank'))
                   for r in j.get('rankings') or []], open(fn, 'w'))
    return json.load(open(fn))


def eligible(birth, y):
    """first, second or third year of draft eligibility in class y (18 by Sept 15 of the draft year, not past 20)"""
    return bool(birth) and f'{y - 20}-09-16' <= birth <= f'{y - 18}-09-15'


def _match(name, birth, pool):
    return [q for q in pool.get(birth, []) if NM.same(q['name'], name)]


# -- the population -------------------------------------------------------------------------------------------------
def population(rows, W, sc, years):
    T = chl_seasons()
    by_birth = {}
    for r in rows:
        if r.get('birth'):
            by_birth.setdefault(r['birth'], []).append(r)
    war_idx = {}
    for S, t in W.items():
        for pid, p in t.items():
            tk = NM.tokens(p.get('n') or '')
            if tk:
                war_idx.setdefault(tk[-1], []).append((S, pid, p))
    cur = D.current_season()
    out = []
    for y in years:
        ranks = css(y)
        top = {(b, n) for n, b, rk in ranks if rk and rk <= BOARD_N}
        prev = {}
        for p in T.get(y - 1, []):
            if p['birth']:
                prev.setdefault(p['birth'], []).append(p)
        seen = set()
        for p in T.get(y, []):
            if not eligible(p['birth'], y) or p['gp'] < 1 or (p['birth'], p['name']) in seen:
                continue
            seen.add((p['birth'], p['name']))
            if any(NM.same(n, p['name']) for b, n in top if b == p['birth']):
                continue                                        # on the pre-draft board
            picks = [r for r in by_birth.get(p['birth'], []) if NM.same(r['name'], p['name'])]
            if any(r['year'] < y for r in picks):
                continue                                        # drafted in an earlier class
            pick = next((r for r in picks if r['year'] == y), None)
            if pick:
                fv = H.fv_of(pick, sc)
            else:
                age0 = H.age_at(p['birth'], y)
                tk = NM.tokens(p['name'])
                ids = {pid for S, pid, q in war_idx.get(tk[-1] if tk else '', []) if y < S <= y + H.WINDOW and NM.same(q['n'], p['name'])
                       and q.get('age') is not None and abs(q['age'] - (age0 + (S - y))) <= 1.5}
                r = {'year': y, 'id': next(iter(ids)) if len(ids) == 1 else None, 'G': 0}
                H.outcome(r, W, cur)
                fv = H.fv_of(r, sc) if r['id'] else 20.0
            pm = [q for q in prev.get(p['birth'], []) if NM.same(q['name'], p['name']) and q['gp'] >= MIN_GP]
            out.append({**p, 'year': y, 'fv': fv, 'picked': pick['pick'] if pick else None,
                        'prev': max(pm, key=lambda q: q['gp']) if pm else None})
    return out


def feats(p, prior=None):
    """prior: (target NHLe, games) to shrink a short season's NHLe toward (live); history uses full seasons"""
    f0 = H.nhle_of(p['lg'])
    gp = p['gp']
    raw = 82 * f0 * p['pts'] / gp if gp else 0.0
    if prior:
        nh = (raw * gp + prior[0] * prior[1]) / (gp + prior[1])
    else:
        nh = raw if gp >= MIN_GP else None
    age = H.age_at(p['birth'], p['year'])
    age_na = age is None
    if age_na:
        age = p.get('ageEst') or AGE_EST                         # no birth date: the approximate age (age_est)
    pm = p.get('prev')
    nhm = 82 * H.nhle_of(pm['lg']) * pm['pts'] / pm['gp'] if pm else None
    D_ = int(p['pos'] == 'D')
    # rate drivers: full seasons (MIN_GP+) in history; live, any games, shrunk to neutral with the NHLe prior's games
    w = gp / (gp + prior[1]) if prior and gp else (1.0 if gp >= MIN_GP else 0.0)
    x = 0.0 if nh is None else nh / 10
    return {'nhle': x, 'nhle_na': int(nh is None), 'nhle2': x * x, 'D': D_, 'nhleD': D_ * x, 'age': age - 18.5,
            'over': int(age >= 19.0), 'agenh': (age - 18.5) * x, 'ht': (p.get('ht') or 72.5) - 72.5,
            'wt': ((p.get('wt') or 185) - 185) / 10, 'gp': min(gp, 68) / 68 - .8,
            'nhm': 0.0 if nhm is None or nh is None else nhm / 10 - x, 'nhm_na': int(nhm is None),
            # Oct 29 candidates: everything else the HockeyTech line carries (neutral where a feed lacks it)
            'C': int(p.get('C') or 0), 'rD': D_ * int(p.get('shoots') == 'R'), 'imp': int(p.get('imp') or 0),
            'rook': int(p.get('rookie') or 0), 'late': int(not age_na and int(p['birth'][5:7]) >= 7 and age < 18.5),
            'gsh': (p['g'] / p['pts'] - .38) if p['pts'] >= 5 else 0.0,
            'ppsh': (p['ppp'] / p['pts'] - .3) if p.get('ppp') is not None and p['pts'] >= 5 else 0.0,
            'shpg': min(p['shp'] / gp, .3) * 10 if p.get('shp') is not None and gp >= MIN_GP else 0.0,
            'pmpg': w * max(-1, min(1, p['pm'] / gp)) if p.get('pm') is not None and w else 0.0,
            'pimpg': w * (min(p['pim'] / gp, 4) - .8) if p.get('pim') is not None and w else 0.0,
            'tsh': (min(p['tsh'], .6) - .1) * 10 if p.get('tsh') is not None and gp >= MIN_GP else 0.0,
            'tgf': p['tgf'] - 3.3 if p.get('tgf') else 0.0,
            'age2': (age - 18.5) ** 2}


BASE = ['nhle']
CANDS = ['nhle_na', 'nhle2', 'D', 'nhleD', 'age', 'over', 'agenh', 'ht', 'wt', 'gp', 'nhm', 'nhm_na',
         'C', 'rD', 'imp', 'rook', 'late', 'gsh', 'ppsh', 'shpg', 'pmpg', 'pimpg', 'tsh', 'tgf', 'age2']
AGE_EST = 18.5
OLD_KEPT = ['nhle', 'agenh', 'nhle_na', 'wt', 'D']
AGE_X = ['rook', 'gp', 'ht', 'wt', 'D', 'nhle', 'nhm_na', 'over_ppg']


def age_x(p, f):
    """what a line shows about age when the birth date is missing: first season in the league, games, size, position,
    NHLe, no line the year before"""
    return [f['rook'], f['gp'], f['ht'], f['wt'], f['D'], f['nhle'], f['nhm_na'], f['nhle'] * f['rook']]


def age_feats(f, age, birth):
    """the age-driven features at a given age (the approximate age when the birth date is missing)"""
    a = age - 18.5
    return {'age': a, 'over': int(age >= 19.0), 'agenh': a * f['nhle'], 'age2': a * a,
            'late': int(bool(birth) and int(birth[5:7]) >= 7 and age < 18.5)}


def fit():
    W = H.war_tables()
    rows = H.read_rows(W)
    H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    pop = population(rows, W, sc, range(H.FIRST, H.LAST_FIT + 1))
    y = np.array([p['fv'] for p in pop]); cls = np.array([p['year'] for p in pop])
    F = [feats(p) for p in pop]
    picked = np.array([p['picked'] is not None for p in pop])
    nhl = np.array([p['fv'] > 20 for p in pop])
    print(len(pop), 'eligible off-board CHL skaters', int(picked.sum()), 'drafted', int(nhl.sum()), 'with NHL games;',
          'mean FV', round(y.mean(), 2))
    # flat: the class-out mean
    flat = np.array([y[cls != c].mean() for c in cls])
    per = lambda p: np.array([np.mean((p[cls == c] - y[cls == c]) ** 2) for c in sorted(set(cls))])
    sflat = per(flat)
    # the board's draft model at a late slot (the slot chosen on the other classes)
    fitd = json.load(open(H.FIT))
    def late(S):
        g = []
        for p in pop:
            f = feats(p)
            r = {'pick': S, 'G': 0, 'D': f['D'], 'ht': p.get('ht'), 'wt': p.get('wt'), 'age': H.age_at(p['birth'], p['year']),
                 'd0': None if f['nhle_na'] else {'nhle': f['nhle'] * 10, 'gsh': .4, 'grp': 'chl'}, 'css': None}
            g.append(H.grade(fitd, H.feats(r)))
        return np.array(g)
    lates = {S: late(S) for S in (120, 160, 200, 250, 300)}
    plate = np.zeros(len(y))
    for c in sorted(set(cls)):
        m = cls == c
        S = min(lates, key=lambda S: np.mean((lates[S][~m] - y[~m]) ** 2))
        plate[m] = lates[S][m]
    slate = per(plate)
    s0, _ = H.score(F, y, cls, BASE)
    kept, ev, cur = H.select(F, y, cls, BASE, CANDS, log=print)
    _, p = H.score(F, y, cls, kept)
    X = np.array([[f[c] for c in kept] for f in F]); b = H.ols(X, y)
    # the earlier driver set (Oct 25) on the same class-out test
    s_old, _ = H.score(F, y, cls, OLD_KEPT)
    # approximate age (Noah, Oct 29): a player with no birth date in the feed. Hide every birth date and grade with the
    # kept drivers at (a) the old flat 18.5, (b) an age fitted on what the line still shows (first season in the league,
    # games, size, scoring, position, a line the year before), each class's age model fit on the other classes
    A = np.array([age_x(p, f) for p, f in zip(pop, F)]); ages = np.array([f['age'] + 18.5 for f in F])
    est = np.zeros(len(y))
    for c in sorted(set(cls)):
        m = cls == c
        est[m] = np.column_stack([np.ones(m.sum()), A[m]]) @ H.ols(A[~m], ages[~m], lam=0.0)
    am = H.ols(A, ages, lam=0.0)
    def masked(av):
        G = [{**f, **age_feats(f, a, None)} for f, a in zip(F, av)]
        return H.score(G, y, cls, kept)[0]
    s_flat_age, s_est_age = masked(np.full(len(y), 18.5)), masked(est)
    age_mae = lambda q: round(float(np.mean(np.abs(q - ages))), 3)
    coef = dict(zip(['const'] + kept, [round(float(v), 4) for v in b]))

    def cmp(a, bb):
        d = a - bb
        return {'gain': round(float(d.mean()), 3), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
    sub = lambda q, m: round(float(np.mean((q[m] - y[m]) ** 2)), 2)
    rho = lambda q, m: round(float(np.corrcoef(np.argsort(np.argsort(q[m])), np.argsort(np.argsort(y[m])))[0, 1]), 3)
    # how the grade sorts the eventual NHL players: the top 5% of each class by grade vs the rest
    top = np.zeros(len(y), bool)
    for c in sorted(set(cls)):
        m = np.where(cls == c)[0]; top[m[np.argsort(-p[m])[:max(1, len(m) // 20)]]] = True
    calib = []
    for lo in range(20, 50, 2):
        m = (p >= lo) & (p < lo + 2)
        if m.sum() >= 20:
            calib.append({'band': lo, 'n': int(m.sum()), 'pred': round(float(p[m].mean()), 2), 'real': round(float(y[m].mean()), 2),
                          'drafted': round(float(picked[m].mean()), 3), 'nhl': round(float(nhl[m].mean()), 3)})
    out = {'asof': dt.date.today().isoformat(), 'classes': [H.FIRST, H.LAST_FIT], 'boardN': BOARD_N, 'n': len(pop),
           'drafted': int(picked.sum()), 'nhl': int(nhl.sum()), 'meanFv': round(float(y.mean()), 2),
           'kept': kept, 'coef': coef, 'ev': ev, 'mse': round(float(cur.mean()), 3), 'mseNhle': round(float(s0.mean()), 3),
           'mseFlat': round(float(sflat.mean()), 3), 'mseLate': round(float(slate.mean()), 3),
           'vsFlat': cmp(sflat, cur), 'vsLate': cmp(slate, cur), 'oldKept': OLD_KEPT, 'mseOld': round(float(s_old.mean()), 3), 'vsOld': cmp(s_old, cur),
           'ageEst': {'cols': AGE_X, 'b': [round(float(v), 4) for v in am], 'maeFlat': age_mae(np.full(len(y), 18.5)), 'maeEst': age_mae(est),
                      'mseTrue': round(float(cur.mean()), 3), 'mseFlat': round(float(s_flat_age.mean()), 3), 'mseEst': round(float(s_est_age.mean()), 3),
                      'estVsFlat': cmp(s_flat_age, s_est_age), 'trueVsEst': cmp(s_est_age, cur)},
           'picks': {'n': int(picked.sum()), 'mse': sub(p, picked), 'mseFlat': sub(flat, picked), 'mseLate': sub(plate, picked),
                     'rho': rho(p, picked), 'rhoLate': rho(plate, picked)},
           'top5': {'nhlRate': round(float(nhl[top].mean()), 3), 'restRate': round(float(nhl[~top].mean()), 3),
                    'draftRate': round(float(picked[top].mean()), 3)},
           'calib': calib, 'odds': H.odds_fit(p, y, tuple((f'p{c}', c) for c in (30, 40, 50, 60))),
           'mean': {k: round(float(np.mean([f[k] for f in F])), 4) for k in kept}, 'nhleMean': round(float(np.mean([f['nhle'] * 10 for f in F if not f['nhle_na']])), 2), 'nhleK': NHLE_K}
    json.dump(out, open(FIT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ('ev', 'calib')}, indent=1))
    print(out['calib'])


# -- live ---------------------------------------------------------------------------------------------------------
def _get(u):
    try:
        return D.get(u)
    except Exception as e:
        print('provisional feed:', u.split('?')[0], e, file=sys.stderr)
        return None


def ht_current(code, key, season_end):
    """the regular season ending in season_end from a HockeyTech feed"""
    for s in ((_get(HT % (key, code) + '&view=seasons') or {}).get('SiteKit') or {}).get('Seasons') or []:
        m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?(AHL )?Regular Season$', s['season_name'].strip())
        if m and int(m.group(1)) + 1 == season_end:
            d = _get(HT % (key, code) + f"&view=statviewtype&type=topscorers&season_id={s['season_id']}&first=0&limit=3000&stat=all&order_direction=")
            return ((d or {}).get('SiteKit') or {}).get('Statviewtype')
    return None


def liiga_info(pid):
    """a Liiga player's page: birth date, height (cm), weight (kg), shot"""
    j = _get(LIIGA_INFO % pid) or {}
    ht, wt = _num(j.get('height')), _num(j.get('weight'))
    return {'birth': j.get('dateOfBirth') or None, 'ht': round(ht / 2.54) if ht else None, 'wt': round(wt * 2.2046) if wt else None,
            'shoots': {'L': 'L', 'R': 'R'}.get(j.get('handedness'))}


def liiga_current(season_end):
    """Liiga skaters this season who are under 20 (the draft-eligible pool there). The stats feed has no birth dates, so
    each one's player page gives his birth date and size; a page that fails leaves the approximate age (AGE_EST)."""
    out = []
    for p in _get(LIIGA % (season_end, season_end)) or []:
        if p.get('goalkeeper') or not p.get('isU20') or not p.get('playedGames'):
            continue
        info = liiga_info(p['playerId']) if p.get('playerId') else {}
        out.append({'name': f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(), 'birth': info.get('birth'),
                    'pos': 'D' if (p.get('role') or '').endswith('P') else 'F', 'ht': info.get('ht'), 'wt': info.get('wt'),
                    'shoots': info.get('shoots'), 'gp': float(p['playedGames']), 'pts': float(p.get('points') or 0),
                    'g': float(p.get('goals') or 0), 'lg': 'Liiga', 'club': p.get('teamName'), 'nat': p.get('nationality')})
    return out


def neutral_off_chl(p):
    """the line-detail drivers (+/-, penalty minutes, team share) were fit on CHL lines only: elsewhere they sit at neutral"""
    if p['lg'] not in CHL_LG:
        for k in ('pm', 'pim', 'ppp', 'shp', 'tsh', 'tgf'):
            p[k] = None
    return p


def live(year, board, rows):
    """provisional rows for the coming class: [{name, pos, club, league, age, gp, pts, nhle, fv, fvx, prov}]"""
    if not os.path.exists(FIT):
        return []
    P = json.load(open(FIT))
    season_end = year                                            # the 2027 draft follows the 2026-27 season
    pool, prev = [], {}
    for code, lg in (('ohl', 'OHL'), ('whl', 'WHL'), ('lhjmq', 'QMJHL'), ('ahl', 'AHL')):
        pool += with_team(ht_players(ht_current(code, HTKEY[code], season_end), lg))
        if lg in CHL_LG:                                         # last season's CHL lines (the 'year before' drivers)
            for q in ht_players(ht_current(code, HTKEY[code], season_end - 1), lg):
                if q['birth'] and q['gp'] >= MIN_GP:
                    prev.setdefault(q['birth'], []).append(q)
    pool += liiga_current(season_end)
    pool = [neutral_off_chl(p) for p in pool]
    drafted = {}
    for r in rows:
        drafted.setdefault(NM.tokens(r['name'])[-1] if NM.tokens(r['name']) else '', []).append(r)
    on_board = [b['name'] for b in board]
    out, seen = [], set()
    for p in pool:
        if p['birth'] and not eligible(p['birth'], year):
            continue
        if not p['birth'] and p['lg'] != 'Liiga':
            continue
        tk = NM.tokens(p['name'])
        if not tk or (p['name'], p['lg']) in seen:
            continue
        seen.add((p['name'], p['lg']))
        if any(NM.same(n, p['name']) for n in on_board):
            continue
        if any(NM.same(r['name'], p['name']) and (not p['birth'] or r.get('birth') == p['birth']) for r in drafted.get(tk[-1], [])):
            continue
        pm = [q for q in prev.get(p['birth'], []) if NM.same(q['name'], p['name'])] if p['birth'] else []
        q = {**p, 'year': year, 'prev': max(pm, key=lambda r: r['gp']) if pm else None}
        f = feats(q, prior=(P['nhleMean'], P['nhleK']))
        b = P['coef']
        x = min(80.0, max(20.0, b['const'] + sum(b[k] * f[k] for k in P['kept'])))
        odds = {k: round(1 / (1 + math.exp(-(a + bb * (x - 30)))), 3) for k, (a, bb) in P['odds'].items()}
        parts = [[k, round(b[k] * (f[k] - P['mean'][k]), 2)] for k in P['kept'] if abs(b[k] * (f[k] - P['mean'][k])) >= .05]
        age = H.age_at(p['birth'], year) if p['birth'] else None
        out.append({'rk': None, 'name': p['name'], 'pos': p['pos'], 'posFull': p['pos'], 'club': p['club'], 'league': p['lg'],
                    'nat': H.nat(p.get('nat')),
                    'grp': H.group_of(p['lg']), 'ht': p.get('ht'), 'wt': int(p['wt']) if p.get('wt') else None,
                    'age': round(age, 1) if age else None, 'gp': int(p['gp']), 'pts': int(p['pts']),
                    'pm': int(p['pm']) if p.get('pm') is not None else None, 'pim': int(p['pim']) if p.get('pim') is not None else None,
                    'prevLine': int(q['prev'] is not None),
                    'nhle': round(82 * H.nhle_of(p['lg']) * p['pts'] / p['gp'], 1) if p['gp'] else None,
                    'xslot': None, 'fvx': round(x, 2), 'fv': int(round(x)), **odds,
                    'parts': sorted(parts, key=lambda q: -abs(q[1])), 'prov': 1})
    out.sort(key=lambda r: -r['fvx'])
    return out


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--live' in sys.argv:
        r = live(2027, [], [])
        print(len(r)); print(r[:15])
