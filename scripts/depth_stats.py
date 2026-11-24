# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Key stats on every depth chart player, for the depth chart GFX card: python3 scripts/depth_stats.py [sport ...].

Reads static/data/depth/<sport>.json (written by the backup watch scripts) and the sport's board data, joins each
listed player through scripts/names.py (name + team), and writes back into the same file:
    "stats": [[label, fmt, tip], ...]      the sport's headline metrics
    player row [6] = [[value, pct], ...]   one pair a stat (null when the player has no line), pct = percentile among
                                           the players on every team's chart with a value
Run after the depth chart is written in each sport's workflow; a missing source leaves that file as it was.
"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names  # noqa: E402

DATA = os.path.join(ROOT, 'static', 'data')


def latest(d):
    f = sorted(glob.glob(os.path.join(DATA, d, '*.json')))
    return f[-1] if f else None


def load(p):
    with open(p) as fh: return json.load(fh)


def g60(p):
    return None if (p.get('toi') or 0) < 100 or p.get('gar') is None else 60 * p['gar'] / p['toi']   # a rate on under 100 minutes is noise


def rows_cfb():
    d = load(os.path.join(DATA, 'cfb-all.json')); c = d['cols']
    return [dict(zip(c, r)) for r in d['rows']]


def rows_cbb():
    """the board (FV for everyone on it) with this season's WAR line where he has one"""
    d = load(os.path.join(DATA, 'cbb-all.json')); c = d['cols']
    board = [dict(zip(c, r)) for r in d['rows']]
    war = load(os.path.join(DATA, 'cbb', 'war.json'))['seasons'][0]['rows']
    M = names.Matcher(war, name='n', team='tm', pos=None, sport='other')
    seen = set()
    for b in board:
        r, _ = M.find(b['name'], team=b['team'], cross_team='none')
        if r: b['war'], b['splus'] = r.get('war'), r.get('splus'); seen.add(id(r))
    # a line for someone off the board still counts
    board += [dict(name=r['n'], team=r['tm'], war=r.get('war'), splus=r.get('splus'), fv=r.get('fv')) for r in war if id(r) not in seen]
    return board


# sport: source rows, name/team fields, team match (pro codes exact), stats [label, fmt, getter, tip]
SPORTS = {
    'nba': (lambda: load(latest('nba-xpm'))['players'], 'n', 'tm', 'code',
            [['XPM', 's1', lambda p: p.get('txpm', p.get('xpm')), 'XPM this season: points a 100 possessions over average'],
             ['VORX', 's1', 'vorx', 'value over replacement on XPM, this season']]),
    'nfl': (lambda: load(os.path.join(DATA, 'nfl-war.json'))['players'], 'n', 't', 'code',
            [['WAR', 's2', 'war', 'wins above replacement this season'],
             ['pXP/60', 's2', 'pxp', 'predictive rate: expected points a 60 snaps, shrunk']]),
    'nhl': (lambda: load(latest('nhl-war'))['players'], 'n', 'tm', 'code',
            [['WAR', 's1', 'war', 'wins above replacement this season'],
             ['GAR/60', 's2', g60, 'goals above replacement a 60 this season, 100+ minutes']]),
    'soccer': (lambda: load(latest('soccer-war'))['players'], 'n', 'team', 'club',
               [['GAR', 's1', 'gar', 'goals above replacement this season'],
                ['p/90', 's2', 'pg90', 'predictive GAR a 90']]),
    'cbb': (rows_cbb, 'name', 'team', 'club',
            [['FV', 'i', 'fv', 'FV now'],
             ['WAR', 's2', 'war', 'wins above replacement this season'],
             ['Stat+', 'i', 'splus', 'BPM against his position, 100 + 25 z']]),
    'cfb': (rows_cfb, 'name', 'team', 'club',
            [['FV', 'i', 'fv', 'FV now'],
             ['WAR', 's2', 'war', 'wins above replacement this season'],
             ['WAA', 's2', 'waa', 'wins above an average player this season']]),
}


def pct(vals, v):
    lo = sum(1 for x in vals if x < v); eq = sum(1 for x in vals if x == v)
    return round(100 * (lo + 0.5 * max(0, eq - 1)) / max(1, len(vals) - 1))


def run(sport):
    path = os.path.join(DATA, 'depth', sport + '.json')
    if not os.path.exists(path): return print(sport, 'no depth chart')
    src, nf, tf, how, stats = SPORTS[sport]
    try:
        pool = src()
    except Exception as e:  # noqa: BLE001
        return print(sport, 'source not read:', e)
    eq = (lambda a, b: a == b) if how == 'code' else names.same_team
    M = names.Matcher(pool, name=nf, team=tf, pos=None, sport='football' if sport in ('nfl', 'cfb') else 'other', team_eq=eq)
    D = load(path)
    got, miss, memo, rows = 0, 0, {}, []
    for T in D['teams']:
        for u in T['units']:
            for s in u['s']:
                for p in s[1]:
                    k = (T['t'], p[0])
                    if k not in memo:
                        r, _ = M.find(p[0], team=T['t'])
                        memo[k] = r
                        got, miss = (got + 1, miss) if r else (got, miss + 1)
                    r = memo[k]
                    vals = []
                    for st in stats:
                        v = None if r is None else (st[2](r) if callable(st[2]) else r.get(st[2]))
                        vals.append(None if v is None or v != v else (round(float(v)) if st[1] == 'i' else round(float(v), int(st[1][1:]))))
                    while len(p) < 6: p.append(None)
                    del p[6:]
                    p.append(vals)
                    rows.append((k, p))
    # percentile a stat among the distinct players carrying it
    for i in range(len(stats)):
        seen = {}
        for k, p in rows:
            if p[6][i] is not None: seen[k] = p[6][i]
        vals = list(seen.values())
        for k, p in rows:
            v = p[6][i]
            if isinstance(v, (int, float)): p[6][i] = [v, pct(vals, v)]
    D['stats'] = [[st[0], st[1], st[3]] for st in stats]
    with open(path, 'w') as fh: json.dump(D, fh, separators=(',', ':'), ensure_ascii=False)
    print(sport, 'matched', got, 'of', got + miss)


if __name__ == '__main__':
    for s in sys.argv[1:] or list(SPORTS): run(s)
