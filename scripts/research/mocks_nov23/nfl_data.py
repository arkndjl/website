"""NFL/CFB inputs for the Nov 23 mock driver tests (prereg.md F1, F2): DraftTek final boards (draft_backtest.py cache),
PFF dated boards (cfb_draft_pct_backtest.py cache), nflverse picks and combine, award lists (awards_wiki.py).
Every name join goes through scripts/names.py."""
import collections, csv, datetime, glob, json, math, os, re
from common import ROOT
import names as N
import awards_wiki as AW

DR = os.path.join(ROOT, 'scripts', '.cache', 'draft')
DP = os.path.join(ROOT, 'scripts', '.cache', 'draftpct')
PULLED = datetime.date(2026, 11, 23)     # the day this run pulled PFF (its "age" is age on the pull date)
DRAFT_DAY = {2020: '2020-04-23', 2021: '2021-04-29', 2022: '2022-04-28', 2023: '2023-04-27', 2024: '2024-04-25', 2025: '2025-04-24', 2026: '2026-04-23'}
NGRP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'OT': 'OL', 'G': 'OL', 'OG': 'OL', 'C': 'OL', 'OL': 'OL', 'DE': 'EDGE',
        'EDGE': 'EDGE', 'OLB': 'EDGE', 'DT': 'DL', 'DL': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S',
        'SAF': 'S', 'FS': 'S', 'SS': 'S', 'HB': 'RB', 'ED': 'EDGE', 'DI': 'DL', 'K': 'K', 'P': 'K', 'LS': 'K', 'PK': 'K'}
SEC0 = {'Alabama', 'Arkansas', 'Auburn', 'Florida', 'Georgia', 'Kentucky', 'LSU', 'Ole Miss', 'Mississippi State', 'South Carolina', 'Tennessee', 'Vanderbilt'}
B10_0 = {'Illinois', 'Indiana', 'Iowa', 'Michigan', 'Michigan State', 'Minnesota', 'Nebraska', 'Northwestern', 'Ohio State', 'Penn State', 'Purdue', 'Wisconsin'}
JOIN = {('Missouri', 2012), ('Texas A&M', 2012), ('Texas', 2024), ('Oklahoma', 2024), ('Maryland', 2014), ('Rutgers', 2014), ('USC', 2024),
        ('UCLA', 2024), ('Oregon', 2024), ('Washington', 2024)}


def sec_b10(school, season):
    if not school: return 0.0
    for s in SEC0 | B10_0:
        if N.same_team(school, s): return 1.0 if not (s == 'Nebraska' and season < 2011) else 0.0
    for s, y in JOIN:
        if N.same_team(school, s): return 1.0 if season >= y else 0.0
    return 0.0


def picks():
    out = collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(DR, 'draft_picks.csv'))):
        out[int(r['season'])].append(r)
    return out


def combine():
    """per draft year a list of combine rows with g, ath (live fetchCombine composite), forty z, notest."""
    rows = list(csv.DictReader(open(os.path.join(DR, 'combine.csv'))))
    met = lambda p: {'spd': float(p['wt']) * 200 / float(p['forty']) ** 4 if p['forty'] and p['wt'] else None,
                     'vert': float(p['vertical']) if p['vertical'] else None, 'broad': float(p['broad_jump']) if p['broad_jump'] else None,
                     'cone': -float(p['cone']) if p['cone'] else None, 'shut': -float(p['shuttle']) if p['shuttle'] else None}
    pool = collections.defaultdict(list); fz = collections.defaultdict(list)
    for p in rows:
        g = NGRP.get(p['pos'])
        if not g or int(p['season']) < 2010: continue
        for k, v in met(p).items():
            if v is not None: pool[g + k].append(v)
        if p['forty']: fz[g].append(float(p['forty']))
    ms = {k: (sum(v) / len(v), (sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)) ** .5 or 1) for k, v in pool.items()}
    fs = {g: (sum(v) / len(v), (sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)) ** .5 or 1) for g, v in fz.items()}

    def ath(p, g):
        zs = [(v - ms[g + k][0]) / ms[g + k][1] for k, v in met(p).items() if v is not None and g + k in ms]
        return sum(zs) / len(zs) if len(zs) >= 2 else None
    tm = collections.defaultdict(list)
    for p in rows:
        g = NGRP.get(p['pos'])
        if g and int(p['season']) >= 2010:
            a = ath(p, g)
            if a is not None: tm[g].append(a)
    tmm = {g: sum(v) / len(v) for g, v in tm.items()}
    by = collections.defaultdict(list)
    for p in rows:
        g = NGRP.get(p['pos']); a = ath(p, g) if g else None
        drills = [p[k] for k in ('forty', 'bench', 'vertical', 'broad_jump', 'cone', 'shuttle')]
        by[int(p['season'])].append({'name': p['player_name'], 'school': p['school'], 'pos': p['pos'], 'g': g,
                                     'ath': (a - tmm[g]) if a is not None else None,
                                     'forty': (float(p['forty']) - fs[g][0]) / fs[g][1] if p['forty'] and g in fs else None,
                                     'notest': 0.0 if any(drills) else 1.0})
    return by


def pff_versions():
    out = collections.defaultdict(list)
    for f in glob.glob(os.path.join(DP, 'pff_*.json')):
        try: d = json.load(open(f))
        except ValueError: continue
        if not d.get('players') or not d.get('last_updated_at'): continue
        y = int(os.path.basename(f).split('_')[1])
        out[y].append((d['last_updated_at'][:10], d['players']))
    for y in out: out[y].sort(key=lambda x: x[0])
    return out


def pick_board(vers, y, lo, hi):
    """latest PFF version of draft y dated in [lo, hi] (ISO strings)"""
    c = [v for v in vers.get(y, []) if lo <= v[0] <= hi]
    return c[-1] if c else None


def pff_matcher(players):
    rows = [{'name': f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or p['name'], 'team': p.get('college') or (p.get('team') or {}).get('city'),
             'pos': p.get('position'), 'p': p} for p in players]
    return N.Matcher(rows, name='name', team='team', pos=None)


def age_at_draft(p, y):
    try: a = float(p.get('age'))
    except (TypeError, ValueError): return None
    dd = datetime.date.fromisoformat(DRAFT_DAY.get(y, f'{y}-04-25'))
    return a - (PULLED - dd).days / 365.25


_AW = {}
def awards(season):
    if season not in _AW:
        d = AW.football(season)
        _AW[season] = {k: N.Matcher(list({N.key(x[0]): {'name': x[0], 'team': x[1] if len(x) > 1 else None, 'pts': x[2] if len(x) > 2 else None} for x in v}.values()),
                                    name='name', team='team', pos=None) for k, v in d.items()}
    return _AW[season]


def award_feats(name, school, season):
    a = awards(season); out = {}
    for k in ('heis', 'aa', 'award'):
        r, _ = a[k].find(name, school)
        if r is None and k == 'award': r, _ = a[k].find(name)      # plain lists carry no school on some lines
        out[k] = 1.0 if r is not None else 0.0
    return out
