# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared pieces for the sweep tests: the XPM test's team-season frame, id crosswalks by name (scripts/names.py),
paired clustered t, Holm."""
import csv, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import names as NM

FRAME = os.environ.get('XPM_FRAME', '/mnt/project-files/cbb/xpm/')
SCR = os.environ.get('NBA_SCRATCH', '/home/user/scratch-nba')
IMPL = '/mnt/project-files/research-sweep-nov19/impl/nba/'


def num(s):
    try: return float(s)
    except (TypeError, ValueError): return None


def frame():
    """(player seasons {(year, pid): row}, team rows {(year, tm): row}, stints [(year, pid, tm, mp, pos, awards)])"""
    ps = {(int(r['year']), r['pid']): r for r in csv.DictReader(open(os.path.join(FRAME, 'nba_player_seasons.csv')))}
    tm = {(int(r['year']), r['tm']): r for r in csv.DictReader(open(os.path.join(FRAME, 'teams.csv')))}
    st = [(int(r['year']), r['pid'], r['tm'], num(r['mp']) or 0.0, r['pos'], r['awards'], r['name'])
          for r in csv.DictReader(open(os.path.join(FRAME, 'players.csv')))]
    return ps, tm, st


def matcher(pairs):
    """pairs [(id, name)] -> find(name) -> id or None"""
    m = NM.Matcher([{'name': n, 'id': i} for i, n in pairs], name='name', team=None, pos=None, sport='basketball')
    def find(name):
        r = m.find(name)
        r = r[0] if isinstance(r, tuple) else r
        return r['id'] if r else None
    return find


def paired(d, cl):
    """mean of d and its t with clusters cl (cluster sums)"""
    s = {}
    for v, c in zip(d, cl): s[c] = s.get(c, 0.0) + float(v)
    v = list(s.values()); n = len(v)
    if n < 2: return {'d': sum(d) / max(len(d), 1), 't': float('nan'), 'k': n}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return {'d': float(sum(d) / len(d)), 't': float(m / (sd / math.sqrt(n))) if sd > 0 else float('nan'), 'k': n}


def p2(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t == t else 1.0


def holm(ps):
    """{name: p} -> {name: Holm-adjusted p}"""
    order = sorted(ps, key=ps.get); m = len(order); out = {}; run = 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, ps[k] * (m - i))); out[k] = run
    return out
