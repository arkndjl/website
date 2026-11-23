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
YOUNG = os.path.join(ROOT, 'data', 'next_up_young.json')   # scripts/next_up_young_research.py: who counts as young
UNDER = ('Fr', 'So', 'RS-Fr', 'RS-So')
POS = ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'QB', 'RB', 'WR', 'TE', 'D', 'LW', 'RW', 'FW', 'AM', 'W', 'MF', 'CM',
       'DM', 'DF', 'FB', 'CB', 'GK']


def short(lab):
    return lab.split('/')[0]


def board(sport):
    """college: class + FV from the board (static/data/<sport>-all.json) by ESPN id, else the shared name matcher;
    NFL: WAR a 17 games from static/data/nfl-war.json (rate stat, no FV in the pros)"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import names as NM
    if sport in ('cfb', 'cbb'):
        d = json.load(open(os.path.join(ROOT, 'static', 'data', sport + '-all.json')))
        ix = {c: i for i, c in enumerate(d['cols'])}
        rows = []
        for r in d['rows']:
            lk = r[ix['espnl']] if 'espnl' in ix else (r[ix['links']] or {}).get('espn') if 'links' in ix else None
            eid = lk.rstrip('/').split('/id/')[1].split('/')[0] if lk and '/id/' in lk else None
            rows.append({'name': r[ix['name']], 'team': r[ix['team']], 'pos': r[ix['pos']], 'id': eid,
                         'cls': r[ix['cls']], 'fv': r[ix['fv']]})
        if sport == 'cbb' and os.path.exists(os.path.join(ROOT, 'static', 'data', 'cbb-intl.json')):   # international prospects
            d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-intl.json')))
            ix = {c: i for i, c in enumerate(d['cols'])}
            rows += [{'name': r[ix['name']], 'team': r[ix['team']], 'pos': r[ix['pos']], 'id': None, 'cls': 'Intl',
                      'fv': r[ix['fv']]} for r in d['rows']]
        return NM.Matcher(rows, id='id', sport='football' if sport == 'cfb' else 'basketball')
    if sport == 'nfl':
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))
        return NM.Matcher([{'name': p['n'], 'team': p.get('tm'), 'pos': p.get('pos'), 'war': p.get('pace')}
                           for p in d['players']], sport='football')
    return None


def young(sport, r, Y):
    y = Y.get(sport)
    if not y:
        return True
    if y['rule'] == 'cls':
        if r.get('yr'):
            return r['yr'] in y['keep'] or r['yr'] == 'Intl'      # board internationals are all draft-age prospects
        return r.get('age') is not None and r['age'] < 21            # no class found: a true underclassman's age
    return r.get('age') is not None and int(r['age']) <= y['max_age']


def convert(sport):
    src = json.load(open(os.path.join(DIR, sport + '.json')))
    Y = json.load(open(YOUNG)) if os.path.exists(YOUNG) else {}
    try:
        M = board(sport)
    except (OSError, ValueError, KeyError) as e:
        print(sport, 'board join skipped:', e)
        M = None
    tiers, st = src.get('tiers') or [], src.get('stat') or {}
    u = src.get('u') or {}
    cols = [{'k': 'p', 'l': 'BO%', 't': 'breakout odds next season', 'f': 'p', 'ph': 0, 'num': 1}]
    if sport in ('cfb', 'cbb'):
        cols += [{'k': 'yr', 'l': 'Class', 't': 'class this season', 'f': 't', 'num': 0},
                 {'k': 'fv', 'l': 'FV', 't': 'future value (board)', 'f': '0', 'num': 1}]
    elif sport == 'nfl':
        cols.append({'k': 'war', 'l': 'WAR/17', 't': 'WAR a 17 games this season', 'f': 's2', 'num': 1})
    cols += [
            {'k': 'sig', 'l': 'Signals', 't': 'signals pushing his odds up most', 'f': 's', 'ph': 1},
            {'k': 'u', 'l': u.get('lab', 'USE'), 't': u.get('t') or (u.get('lab', 'workload') + ' now'),
             'f': str(u.get('dec', 1)), 'ph': 1, 'num': 1}]
    if any(r.get('best') is not None for r in src.get('rows') or []) and sport in BEST:
        lb, tt, f = BEST[sport]
        cols.append({'k': 'best', 'l': 'Best', 't': tt, 'f': f, 'ph': 1, 'num': 1})
    views = [['p', 'BO%', 'breakout odds next season']]
    for k, m in (('x', src.get('cur')), ('xc', src.get('ceil'))):     # current value and its usage-up ceiling
        if m:
            cols.append({'k': k, 'l': m['lab'], 't': m['t'], 'f': str(m.get('dec', 1)), 'ph': 1, 'num': 1})
            views.append([k, m['lab'], m['t']])
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
             'u': r.get('u'), 'sig': ' · '.join(r.get('sig') or []), 'best': r.get('best'), 'x': r.get('x'),
             'xc': r.get('xc')}
        if M is not None:
            m, _ = M.find(o['n'], team=o['tm'], pos=o['pos'] or None,
                          id=str(r.get('id') or '') or None if sport == 'cfb' else None)   # CBB rows carry Barttorvik ids
            if m:
                for k in ('fv', 'war'):
                    if m.get(k) is not None:
                        o[k] = m[k]
                if m.get('cls'):
                    o['yr'] = m['cls']
        if sport == 'cfb' and r.get('cls') and not o.get('yr'):
            o['yr'] = r['cls']
        if not young(sport, o, Y):
            continue
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
    y = Y.get(sport) or {}
    mob = ['fv'] if sport in ('cfb', 'cbb') else ['war'] if sport == 'nfl' else ['x']   # phones: + pos, class, age on the team line
    who = ('Fr/So only' if y.get('rule') == 'cls' else 'age %d and under' % y['max_age'] if y.get('max_age') else '')
    out = {'sport': sport, 'asof': src.get('asof'), 'title': 'next up', 'key': 'p', 'mob': mob,
           'def': (src.get('about', '') + (' · ' + who if who else '')).strip(' ·'),
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
