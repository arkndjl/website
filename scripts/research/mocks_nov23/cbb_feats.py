"""Per-player CBB drivers for the Nov 23 mock tests (prereg.md F3/F4): awards (awards_wiki.py), age, BPM trend,
high-major, height and the combine guard composite, joined through scripts/names.py (careers by name + team,
combine by Barttorvik pid)."""
import collections, json, math, os
import numpy as np
from common import ROOT
import cbb_data as D
import names as N
import awards_wiki as AW

KEYS = ['aa', 'poy', 'cpoy', 'aa_prev', 'age_c', 'trend', 'hm', 'comb', 'ht']
HM = {'ACC', 'B10', 'B12', 'BE', 'SEC', 'P12', 'P10'}
AGE0 = 20.8
_C = {}


def careers():
    if 'c' not in _C:
        _C['c'] = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    return _C['c']


def season_index(y):
    """Matcher over every college player with a season in spring year y (team = that season's team)"""
    k = ('idx', y)
    if k not in _C:
        rows = []
        for c in careers():
            s = [x for x in c['seasons'] if x['year'] == y]
            if s: rows.append({'name': c['name'], 'team': s[0]['team'], 'c': c, 's': s[0]})
        _C[k] = N.Matcher(rows, name='name', team='team', pos=None, sport='basketball')
    return _C[k]


def award_index(y):
    k = ('aw', y)
    if k not in _C:
        d = AW.basketball(y)
        _C[k] = {a: N.Matcher(list({N.key(x[0]): {'name': x[0], 'team': x[1]} for x in v}.values()), name='name', team='team', pos=None, sport='basketball') for a, v in d.items()}
    return _C[k]


def has_award(kind, name, team, y):
    ix = award_index(y)[kind]
    return 1.0 if ix.find(name, team)[0] is not None else 0.0


def combine_ath():
    """pid -> {year: G_ath} from the research frame with the committed norms (cbb_combine.zcols)"""
    if 'comb' not in _C:
        import pandas as pd
        import cbb_combine as CC
        d = pd.read_csv(os.path.join(CC.FRAME, 'combine_linked.csv'), low_memory=False)
        d = d[d.pid.notna() & d.grp.notna()].copy()
        norms = json.load(open(CC.OUT))['norms']
        d, _ = CC.zcols(d, norms)
        out = collections.defaultdict(dict)
        for p, y, g in zip(d.pid, d.YEAR, d.G_ath):
            out[str(int(p))][int(y)] = float(g)
        _C['comb'] = out
    return _C['comb']


def attach(p, y, final_season=True):
    """p: a pool dict (name, school); y: draft year. final_season: the board is after the season (ESPN finals), else a
    Nov-Dec board (only seasons before y and facts known before it)."""
    r = season_index(y).find(p['name'], p['school'])[0]
    for k in KEYS: p[k] = 0.0
    if r is None:
        p['college'] = False
        return p
    c, s = r['c'], r['s']; p['college'] = True
    age = D.age_on(c.get('dob'), y, 6, 25) if c.get('dob') else None
    p['age'] = age; p['age_c'] = (age - AGE0) if age is not None else 0.0
    p['hm'] = 1.0 if s.get('conf') in HM else 0.0
    p['ht'] = (s.get('hti') - 78.0) if s.get('hti') else 0.0
    bp = {x['year']: x.get('bpm') for x in c['seasons'] if x.get('bpm') is not None and (x.get('min_per') or 0) >= 10}
    a, b = (y, y - 1) if final_season else (y - 1, y - 2)
    p['trend'] = (bp[a] - bp[b]) if a in bp and b in bp else 0.0
    if final_season:
        p['aa'] = has_award('aa', p['name'], s['team'], y)
        p['poy'] = has_award('poy', p['name'], s['team'], y)
        p['cpoy'] = has_award('cpoy', p['name'], s['team'], y)
        g = combine_ath().get(str(c['pid']), {}).get(y)
        p['comb'] = max(-2.0, min(2.0, g)) if g is not None and g == g else 0.0
    if y - 1 >= 2009:
        p['aa_prev'] = has_award('aa', p['name'], None, y - 1)
    return p
