#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pro team builder (NFL, NBA, NHL; teams > team builder): each team's contracts by year, the verdict on every player
(extend, let walk, keep, trade), its future picks with their value, and the money by season. Reads the payroll files
(data/payrolls/<lg>.json, scripts/payrolls.py) and the two tests below; writes static/data/builder/<lg>.json, fetched by
layouts/shortcodes/probuilder.html when the tab opens. The depth chart beside it is static/data/depth/<sport>.json.

    python3 scripts/pro_builder.py [nba nfl nhl]     # the live files
    python3 scripts/pro_builder.py --test             # checks on the files it wrote

Verdict (research/pro_builder_verdicts.json, scripts/research/pro_builder_nov28/verdicts.py): the read of his surplus over the
next three seasons that won held out for the league.
  priced projection (NHL, NFL)  three seasons' value = c0 + c1 v + c2 pay, by age group (v = last full season, pay = cap share
                                of the three seasons' pay above the minimum, a season past his deal at his xAAV), x the league's
                                $ a win, less that pay
  one-season Surplus (NBA)      v x $ a win - (cap hit - minimum): the priced projection did not beat it (t -.41)
A player in the last season of his deal: Extend when the read is >= 0 at his xAAV, else Let walk. Under contract beyond it:
Keep when >= 0, else Trade. No value row = no verdict.
Picks: NHL = CapWages team pages (owned, own and acquired, 2027-30); NFL = the Wikipedia draft pages' pick trades
(2027, 2028; each team's seven picks moved by every "A -> B" line, compensatory picks not yet known); NBA = the 2027 own picks
before trades from the season sims (data/nba_draft_order.json), no free source lists NBA pick trades. Value = the slot curve
(research/pro_pick_value.json) at the league's $ a win, less the slot's rookie pay above the minimum: NBA 2027 over the sims'
slots, NFL 2027 at the slot from this season's xW (data/futures_board_nfl.json), every other pick at its round's mean slot."""
import json
import math
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'static', 'data', 'builder')
CACHE = os.path.join(HERE, '.cache', 'pro_builder')
VER = os.path.join(ROOT, 'research', 'pro_builder_verdicts.json')
PV = os.path.join(ROOT, 'research', 'pro_pick_value.json')
EFF = os.path.join(ROOT, 'research', 'payroll_efficiency.json')
UA = {'User-Agent': 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'}
BINS = [(0, 24), (25, 27), (28, 30), (31, 33), (34, 99)]
ROUNDS = {'nba': 2, 'nfl': 7, 'nhl': 7}
PER = {'nba': 30, 'nfl': 32, 'nhl': 32}       # picks a round (NFL compensatory picks sit past 224 and are not counted)
# rookie pay over the cheap years, $M at this season's cap: NBA by slot (data/dect_fit.json nba rookie byPick), NFL the
# rookie scale (dect_fit rookie.scale, four seasons), NHL the entry-level deal (at the minimum, so none above it)
YEARS_CHEAP = {'nba': 4, 'nfl': 4, 'nhl': 3}
NFL_TEAMS = {'Arizona': 'ARI', 'Atlanta': 'ATL', 'Baltimore': 'BAL', 'Buffalo': 'BUF', 'Carolina': 'CAR', 'Chicago': 'CHI',
             'Cincinnati': 'CIN', 'Cleveland': 'CLE', 'Dallas': 'DAL', 'Denver': 'DEN', 'Detroit': 'DET', 'Green Bay': 'GB',
             'Houston': 'HOU', 'Indianapolis': 'IND', 'Jacksonville': 'JAX', 'Kansas City': 'KC', 'LA Chargers': 'LAC',
             'LA Rams': 'LAR', 'Las Vegas': 'LV', 'Miami': 'MIA', 'Minnesota': 'MIN', 'New England': 'NE', 'New Orleans': 'NO',
             'NY Giants': 'NYG', 'NY Jets': 'NYJ', 'Philadelphia': 'PHI', 'Pittsburgh': 'PIT', 'Seattle': 'SEA',
             'San Francisco': 'SF', 'Tampa Bay': 'TB', 'Tennessee': 'TEN', 'Washington': 'WSH'}


def r2(x, d=1):
    return None if x is None else round(x, d)


def load(p, d=None):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return d


def bin_of(a):
    return next(i for i, (lo, hi) in enumerate(BINS) if lo <= a <= hi)


def rate_now(lg, cap):
    """the last full season's $ a win (research/payroll_efficiency.json), carried to this season's cap"""
    R = (load(EFF, {}).get(lg) or {}).get('ratePerWin') or {}
    yrs = sorted(int(y) for y in R)
    y = yrs[-1] if lg != 'nfl' else max(y for y in yrs if y <= 2025)     # NFL 2026 is a season to date
    caps = {'nfl': {2025: 279.2}, 'nba': {2026: 154.647}, 'nhl': {2026: 95.5}}
    c0 = caps[lg].get(y) or cap
    return R[str(y)] * cap / c0


_DF = {}


def rookie_cost(lg, slot, cap):
    if 'd' not in _DF:
        _DF['d'] = load(os.path.join(ROOT, 'data', 'dect_fit.json'), {})
    D = _DF['d']
    if lg == 'nhl':
        return 0.0
    if lg == 'nba':
        bands = [(5, 46.8), (14, 25.2), (30, 13.9), (45, 9.2), (60, 4.0)]
        try:
            bands = [(int(b['picks'].split('-')[1]), b['mean']) for b in D['nba']['rookie']['byPick']]
        except (KeyError, TypeError, ValueError):
            pass
        tot = next(v for hi, v in bands if slot <= hi) if slot <= bands[-1][0] else bands[-1][1]
        return max(tot * cap / (D.get('nba', {}).get('cap') or cap) - YEARS_CHEAP[lg] * 1.272, 0.0)
    sc = (D.get('rookie') or {}).get('scale') or [[1, 48.8], [257, 4.2]]
    for (p0, v0), (p1, v1) in zip(sc, sc[1:]):
        if p0 <= slot <= p1:
            t = (math.log(slot) - math.log(p0)) / ((math.log(p1) - math.log(p0)) or 1)
            tot = v0 + t * (v1 - v0)
            break
    else:
        tot = sc[-1][1]
    return max(tot * cap / (D.get('cap') or cap) - YEARS_CHEAP[lg] * 0.885, 0.0)


def pick_value(lg, slots, rate, cap):
    """mean $ value over a list of overall slots (each slot equally likely)"""
    if lg not in _DF:
        _DF[lg] = (load(PV, {}).get(lg) or {}).get('table') or []
    T = _DF[lg]
    if not T or not slots:
        return None
    vals = [rate * T[min(s, len(T)) - 1] - rookie_cost(lg, s, cap) for s in slots]
    return sum(vals) / len(vals)


# ---------------------------------------------------------------- picks
def get(url, fn, age_h=20):
    p = os.path.join(CACHE, fn)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < age_h * 3600:
        return open(p, encoding='utf-8').read()
    os.makedirs(CACHE, exist_ok=True)
    for k in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode('utf-8', 'replace')
            open(p, 'w', encoding='utf-8').write(b)
            time.sleep(1.5)
            return b
        except Exception as e:  # noqa: BLE001
            print('pro_builder:', url, repr(e)); time.sleep(8 * (k + 1))
    return open(p, encoding='utf-8').read() if os.path.exists(p) else ''


def nfl_picks(year):
    """{team: [[year, round, original team, conditional], ...]} from the Wikipedia draft page's pick trades"""
    raw = get(f'https://en.wikipedia.org/w/index.php?title={year}_NFL_draft&action=raw', f'wiki_nfl_{year}.txt')
    hold = {(t, r): [t] for t in NFL_TEAMS.values() for r in range(1, 8)}    # (holder, round) -> original teams of the picks held
    cond = {}
    i = raw.find('==Trades involving draft picks==')
    if i < 0:
        return None
    rnd = None
    names = sorted(NFL_TEAMS, key=len, reverse=True)
    pat = re.compile(r"'''\s*(?:The\s+)?(" + '|'.join(map(re.escape, names)) + r")\s*→\s*(" + '|'.join(map(re.escape, names)) + r")")
    for line in raw[i:].split('\n'):
        m = re.match(r'^=+\s*Round\s+(\d)\s*=+', line.strip())
        if m:
            rnd = int(m.group(1)); continue
        if line.startswith('==') and not line.startswith('==='):
            if 'Trades' not in line:
                break
        if not rnd or not line.startswith('*'):
            continue
        m = pat.search(line)
        if not m or '(D)' in line[:m.end() + 8]:
            continue
        a, b = NFL_TEAMS[m.group(1)], NFL_TEAMS[m.group(2)]
        held = hold.get((a, rnd)) or []
        if not held:
            continue
        orig = a if a in held else held[0]           # his own pick first, else one he had acquired
        held.remove(orig)
        hold.setdefault((b, rnd), []).append(orig)
        if re.search(r'conditional|whichever|protected|if ', line, re.I):
            cond[(orig, rnd)] = 1
    out = {}
    for (t, r), origs in hold.items():
        for o in origs:
            out.setdefault(t, []).append([year, r, o, cond.get((o, r), 0)])
    return out


def nba_slots():
    D = load(os.path.join(ROOT, 'data', 'nba_draft_order.json'), {})
    S = {t: {1: [], 2: []} for t in D.get('teams', [])}
    for o in D.get('orders', []):
        for k, ti in enumerate(o):
            S[D['teams'][ti]][1 if k < 30 else 2].append(k + 1)
    return S, D.get('season')


def nfl_slots():
    rows = (load(os.path.join(ROOT, 'data', 'futures_board_nfl.json'), {}) or {}).get('rows') or []
    order = sorted(rows, key=lambda r: r.get('xW') or 0)
    return {r['t']: k + 1 for k, r in enumerate(order)}


def team_picks(lg, T, rate, cap):
    """[[year, round, from (team code or name), conditional, slot or None, $M], ...] by team, and the source line"""
    out = {}
    if lg == 'nhl':
        import unicodedata
        def nk(x):
            return unicodedata.normalize('NFKD', x or '').encode('ascii', 'ignore').decode().lower().replace('.', '').strip()
        name2tm = {nk(t['name']): t['tm'] for t in T['teams']}
        name2tm.update({'utah hockey club': 'UTA', 'arizona coyotes': 'UTA'})
        for t in T['teams']:
            rows = []
            for y, r, o, c in t.get('picks') or []:
                mid = [(r - 1) * PER[lg] + k for k in range(1, PER[lg] + 1)]
                rows.append([y, r, name2tm.get(nk(o), o), c, None, r2(pick_value(lg, mid, rate, cap))])
            out[t['tm']] = sorted(rows)
        return out, 'CapWages team pages (owned picks, 2027-30)'
    if lg == 'nfl':
        slot = nfl_slots()
        for y in (2027, 2028):
            P = nfl_picks(y)
            if P is None:
                continue
            for tm, rows in P.items():
                for yy, r, o, c in rows:
                    s0 = slot.get(o) if yy == 2027 else None
                    if s0:
                        sl = [(r - 1) * 32 + min(max(s0 + d, 1), 32) for d in range(-3, 4)]
                        v = pick_value(lg, sl, rate, cap)
                        sp = (r - 1) * 32 + s0
                    else:
                        v = pick_value(lg, [(r - 1) * 32 + k for k in range(1, 33)], rate, cap); sp = None
                    out.setdefault(tm, []).append([yy, r, o, c, sp, r2(v)])
        for tm in out:
            out[tm].sort()
        return out, 'Wikipedia NFL draft pages, pick trades (2027-28)'
    S, season = nba_slots()
    for tm, d in S.items():
        rows = []
        for r in (1, 2):
            if d[r]:
                med = sorted(d[r])[len(d[r]) // 2]
                rows.append([season, r, tm, 0, med, r2(pick_value(lg, d[r], rate, cap))])
        out[tm] = rows
    return out, 'own 2027 picks before trades (season sims)'


# ---------------------------------------------------------------- verdicts
AGE = os.path.join(ROOT, 'research', 'payroll_aging.json')


def develop(lg, v, age):
    """his value in each of the next three seasons on the age curve (research/payroll_aging.json: a_k + b_k v by age
    group, beat the same line with no age groups walk-forward in all three leagues), from his last full season"""
    A = (load(AGE, {}) or {}).get(lg) or {}
    if v is None or age is None or not A.get('curve'):
        return None
    b = '%d-%d' % BINS[bin_of(age - 1)]
    return [r2(A['curve'][str(k)][b][0] + A['curve'][str(k)][b][1] * v, 2) for k in (1, 2, 3)]


def verdicts(lg, T, rate):
    V = load(VER, {}).get(lg) or {}
    read = V.get('read')
    cap, mn = T['cap'], T['min']
    live = V.get('live') or {}
    out = []
    for p in T['players']:
        if p.get('dead') or p.get('nr') or not p.get('tm') or not p.get('h'):
            continue
        h = p['h']
        left = sum(1 for x in h if x is not None)
        last_year = left <= 1 or p.get('fa')
        v, x, age = p.get('v'), p.get('x'), p.get('age')
        row = {'n': p['n'], 'id': p.get('id'), 'tm': p['tm'], 'pos': p.get('pos') or '', 'age': age, 'h': h,
               'thru': p.get('thru'), 'left': left, 'st': p.get('st'), 'o': p.get('o'), 'v': v, 'x': x,
               'aav': p.get('aav'), 'gtd': p.get('gtd'), 'ph': p.get('ph'), 'cl': p.get('cl'), 'ltir': p.get('ltir')}
        row['dev'] = develop(lg, v, age)
        s = None
        if v is not None and read == 'last' and h[0] is not None:
            s = rate * v - max(h[0] - mn, 0)
        elif v is not None and read == 'agedp' and age is not None and live.get('b'):
            costs = []
            for k in range(3):
                c = h[k] if k < len(h) and h[k] is not None else (x if x is not None else mn)
                costs.append(max(c - mn, 0))
            b = live['b'][bin_of(age - 1)]
            e3 = b[0] + b[1] * v + b[2] * sum(costs) / cap
            s = rate * e3 - sum(costs)
            row['e3'] = r2(e3, 2)
        if s is not None:
            row['s'] = r2(s)   # the verdict reads the shown surplus, so a -$0.04M never shows $0.0M beside Trade
            row['vd'] = ('E' if row['s'] >= 0 else 'W') if last_year else ('K' if row['s'] >= 0 else 'T')
        out.append(row)
    return out, read, V


def build(lg):
    T = load(os.path.join(ROOT, 'data', 'payrolls', f'{lg}.json'))
    if not T:
        print('pro_builder:', lg, 'no payroll file'); return
    cap = T['cap']
    rate = rate_now(lg, cap)
    players, read, V = verdicts(lg, T, rate)
    picks, psrc = team_picks(lg, T, rate, cap)
    PVf = load(PV, {}).get(lg) or {}
    depth = load(os.path.join(ROOT, 'static', 'data', 'depth', f'{lg}.json'), {}) or {}
    logos = {t['t']: t.get('logo') for t in depth.get('teams', [])}
    teams = []
    for t in T['teams']:
        pl = [p for p in players if p['tm'] == t['tm']]
        pk = picks.get(t['tm'], [])
        cnt = {k: sum(1 for p in pl if p.get('vd') == k) for k in 'EWKT'}
        teams.append({'tm': t['tm'], 'name': t.get('name'), 'logo': t.get('logo') or logos.get(t['tm']), 'pay': t.get('pay'),
                      'space': t.get('space') if t.get('space') is not None else r2(cap - (t.get('pay') or 0), 2),
                      'dead': t.get('dead'), 'ltir': t.get('ltir'), 'tax': t.get('tax'), 'apron1': t.get('apron1'),
                      'c': t.get('c'), 'exp': t.get('exp'), 'nfa': t.get('nfa'), 'n': len(pl), 'vd': cnt,
                      's': r2(sum(p.get('s') or 0 for p in pl)), 'picks': pk, 'pv': r2(sum(x[5] or 0 for x in pk))})
    for t, rk in zip(sorted(teams, key=lambda t: -(t['pv'] or 0)), range(1, len(teams) + 1)):
        t['pvRk'] = rk
    teams.sort(key=lambda t: t['name'] or t['tm'])
    out = {'lg': lg, 'vl': {'nba': 'VORX', 'nfl': 'WAR', 'nhl': 'WAR'}[lg], 'season': T['season'], 'label': T['label'], 'asof': T['asof'], 'years': T['years'], 'cap': cap,
           'min': T['min'], 'rate': r2(rate, 2), 'read': read, 'tax': T.get('tax'), 'apron1': T.get('apron1'), 'apron2': T.get('apron2'),
           'test': {k: V.get(k) for k in ('n', 'years', 'acc', 'pass', 'realized')} if V else None,
           'testVs': (V.get('agedp_vs') if read == 'agedp' else V.get('last_vs')) if V else None,
           'pickTest': {k: PVf.get(k) for k in ('n', 'drafts', 'unit', 'maeCurve', 'maeRound', 't', 'won', 'pass')},
           'pickSrc': psrc, 'src': T.get('src'), 'teams': teams, 'players': players}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f'{lg}.json'), 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    nv = sum(1 for p in players if p.get('vd'))
    print(f'pro_builder {lg}: {len(teams)} teams, {len(players)} players ({nv} verdicts, read {read}), {sum(len(t["picks"]) for t in teams)} picks')


def test():
    bad = 0
    for lg in ('nba', 'nfl', 'nhl'):
        d = load(os.path.join(OUT, f'{lg}.json'))
        if not d:
            print('missing', lg); bad += 1; continue
        if len(d['teams']) < 30:
            print(lg, 'teams', len(d['teams'])); bad += 1
        for t in d['teams']:
            n1 = sum(1 for p in t['picks'] if p[1] == 1)
            if lg != 'nba' and n1 > 8:
                print(lg, t['tm'], 'first-round picks', n1); bad += 1
        if lg == 'nfl':
            tot = sum(1 for t in d['teams'] for p in t['picks'] if p[0] == 2027)
            if tot and tot != 224:
                print('nfl 2027 picks', tot); bad += 1
        vs = [p for p in d['players'] if p.get('vd')]
        if d.get('read') and len(vs) < 0.5 * len(d['players']):
            print(lg, 'verdicts', len(vs), 'of', len(d['players'])); bad += 1
    print('pro_builder test:', 'ok' if not bad else f'{bad} problems')
    return bad


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        sys.exit(1 if test() else 0)
    for lg in a or ['nba', 'nfl', 'nhl']:
        build(lg)
