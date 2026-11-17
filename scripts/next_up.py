# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up tab (Potential Breakout) on every sport page: turns static/data/next-up/<sport>.json (written by each
sport's *_breakout.py) into the shared leaderboard shape layouts/shortcodes/rookies.html renders
(static/data/next-up/<sport>-tab.json).

    python3 scripts/next_up.py [sport ...]      # default: every sport file present. stdlib only"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DIR = os.path.join(ROOT, 'static', 'data', 'next-up')
BEST = {'nba': ('best BPM', 'best season BPM so far, shrunk by minutes; breakout bar +1.0', 's1'),
        'cbb': ('best BPM', 'best season BPM so far, shrunk by minutes; breakout bar +2.8', 's1'),
        'nhl': ('best WAR/1k', 'best season WAR a 1,000 minutes so far, shrunk; breakout bar 1.19', 's2'),
        'soccer': ('best GAR/90', 'best season GAR/90 so far, shrunk; breakout bar .090', '3'),
        'nfl': ('best PPR/G', 'best season PPR points a game so far, shrunk; breakout bar 12 (TE 9)', '1'),
        'cfb': ('best z', 'best season PFN score z so far, shrunk; breakout bar .32', 's2')}
POS = ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'QB', 'RB', 'WR', 'TE', 'D', 'LW', 'RW', 'FW', 'AM', 'W', 'MF', 'CM',
       'DM', 'DF', 'FB', 'CB', 'GK']


def short(lab):
    return lab.split('/')[0]


def convert(sport):
    src = json.load(open(os.path.join(DIR, sport + '.json')))
    tiers, st = src.get('tiers') or [], src.get('stat') or {}
    u = src.get('u') or {}
    cols = [{'k': 'p', 'l': 'BO%', 't': 'breakout odds next season', 'f': 'p', 'ph': 0, 'num': 1},
            {'k': 'sig', 'l': 'Signals', 't': 'signals pushing his odds up most', 'f': 's', 'ph': 1},
            {'k': 'u', 'l': u.get('lab', 'USE'), 't': u.get('t') or (u.get('lab', 'workload') + ' now'),
             'f': str(u.get('dec', 1)), 'ph': 1, 'num': 1}]
    if any(r.get('best') is not None for r in src.get('rows') or []) and sport in BEST:
        lb, tt, f = BEST[sport]
        cols.append({'k': 'best', 'l': 'Best', 't': tt, 'f': f, 'ph': 1, 'num': 1})
    views = [['p', 'BO%', 'breakout odds next season']]
    sl, el = short(st.get('lab', '')), short(st.get('eff') or '')
    if sl == el:                                               # P/82 and P/60: keep the rate part
        sl, el = st.get('lab', ''), st.get('eff') or ''
    for i, t in enumerate(tiers):
        k = str(t['k']).rstrip('0').rstrip('.') if isinstance(t['k'], float) else str(t['k'])
        cols.append({'k': 's%d' % i, 'l': '%s@%s' % (sl, k),
                     't': '%s at %s' % (st.get('lab', ''), t['lab']), 'f': str(st.get('dec', 1)), 'ph': 1, 'num': 1})
        if st.get('eff'):
            cols.append({'k': 'e%d' % i, 'l': '%s@%s' % (el, k),
                         't': '%s at %s' % (st['eff'], t['lab']), 'f': str(st.get('edec', 1)), 'ph': 1, 'num': 1})
        views.append(['s%d' % i, '%s@%s' % (sl, k), '%s at %s' % (st.get('lab', ''), t['lab'])])
    rows, seen = [], set()
    for r in src.get('rows') or []:
        o = {'n': r['n'], 'tm': r.get('tm') or '', 'pos': r.get('pos') or '', 'age': r.get('age'), 'ph': r.get('ph'),
             'lo': r.get('lo'), 'sub': r.get('sub') or '', 'p': None if r.get('p') is None else round(100 * r['p'], 1),
             'u': r.get('u'), 'sig': ' · '.join(r.get('sig') or []), 'best': r.get('best')}
        if o['lo'] is None and sport in ('nba', 'nfl', 'nhl') and o['tm']:
            o['lo'] = '/img/%s/%s.png' % (sport, o['tm'].split('/')[0].lower())
        for i, c in enumerate(r.get('t') or []):
            if c:
                o['s%d' % i] = c[0]
                if len(c) > 1:
                    o['e%d' % i] = c[1]
        rows.append(o)
        seen.add(o['pos'])
    pos = [p for p in POS if p in seen] + sorted(p for p in seen if p and p not in POS)
    out = {'sport': sport, 'asof': src.get('asof'), 'title': 'next up', 'key': 'p', 'def': src.get('about', ''),
           'views': views, 'cols': cols, 'pos': pos if len(pos) <= 12 else [],
           'seasons': [{'s': src.get('season', ''), 'l': src.get('season', '') + (' · base ' + src['base'] if src.get('base') and src.get('base') != src.get('season') else ''), 'rows': rows}]}
    json.dump(out, open(os.path.join(DIR, sport + '-tab.json'), 'w'), separators=(',', ':'))
    print(sport, len(rows))


def main():
    sp = sys.argv[1:] or sorted(f[:-5] for f in os.listdir(DIR) if f.endswith('.json') and not f.endswith('-tab.json'))
    for s in sp:
        if os.path.exists(os.path.join(DIR, s + '.json')):
            convert(s)


if __name__ == '__main__':
    main()
