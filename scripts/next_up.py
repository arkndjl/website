# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up tab (Potential Breakout) on every sport page: turns static/data/next-up/<sport>.json (written by each
sport's *_breakout.py) into the shared leaderboard shape layouts/shortcodes/rookies.html renders
(static/data/next-up/<sport>-tab.json).

    python3 scripts/next_up.py [sport ...]      # default: every sport file present. stdlib only"""
import json
import math
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
STATUS = os.path.join(ROOT, 'data', 'next_up_status.json')  # scripts/next_up_status_research.py: odds from status alone
POS = ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'QB', 'RB', 'WR', 'TE', 'D', 'LW', 'RW', 'FW', 'AM', 'W', 'MF', 'CM',
       'DM', 'DF', 'FB', 'CB', 'GK']


def short(lab):
    return lab.split('/')[0]


def board(sport):
    """college: class + FV from the board (static/data/<sport>-all.json) by ESPN id, else the shared name matcher;
    NFL: pXP/60 from static/data/nfl-war.json (the predictive rate within a position, no FV in the pros; WAR a 17
    games until Nov 27 2026: a predictive tab shows the predictive rate)"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import names as NM
    if sport in ('cfb', 'cbb'):
        d = json.load(open(os.path.join(ROOT, 'static', 'data', sport + '-all.json')))
        ix = {c: i for i, c in enumerate(d['cols'])}
        rows, sp = [], {}
        if sport == 'cfb':      # Stat+ = 100 + 25 z against the snap-weighted mean and SD at the position and division, as assets/js/cfb.js
            raw = lambda r: r[ix['pfn']] if r[ix['pfn']] is not None else r[ix['kp']] if 'kp' in ix else None
            grp = lambda r: (r[ix['pos']], r[ix['div']] or 'FBS')
            N = {}
            for r in d['rows']:
                if raw(r) is not None:
                    n = N.setdefault(grp(r), [0, 0]); n[0] += 1; n[1] += bool(r[ix['snaps']])
            M = {}
            for r in d['rows']:
                x = raw(r)
                if x is None:
                    continue
                w = (r[ix['snaps']] or 1) if N[grp(r)][1] >= N[grp(r)][0] / 2 else 1
                m = M.setdefault(grp(r), [0, 0, 0]); m[0] += w; m[1] += x * w; m[2] += x * x * w
            for r in d['rows']:
                x, m = raw(r), M.get(grp(r))
                if x is not None and m:
                    mu = m[1] / m[0]
                    sp[id(r)] = round(100 + 25 * (x - mu) / max(1e-3, (max(1e-6, m[2] / m[0] - mu * mu)) ** .5))
        for r in d['rows']:
            lk = r[ix['espnl']] if 'espnl' in ix else (r[ix['links']] or {}).get('espn') if 'links' in ix else None
            eid = lk.rstrip('/').split('/id/')[1].split('/')[0] if lk and '/id/' in lk else None
            now = r[ix['now']] if 'now' in ix else None
            sn = r[ix['snapShare']] if 'snapShare' in ix else None
            rows.append({'name': r[ix['name']], 'team': r[ix['team']], 'pos': r[ix['pos']], 'id': eid,
                         'cls': r[ix['cls']], 'fv': r[ix['fv']],
                         'mpg': (now or {}).get('mpg') if sport == 'cbb' else None,                  # usage: minutes a game this season
                         'xx': r[ix['xbpm']] if sport == 'cbb' and 'xbpm' in ix else None,           # rate: xXPM, the board's projection
                         'splus': sp.get(id(r)),                                                    # rate: Stat+ (100 = average at the position)
                         'snp': round(100 * sn, 1) if sport == 'cfb' and isinstance(sn, (int, float)) else None})   # usage: share of team snaps
        if sport == 'cbb' and os.path.exists(os.path.join(ROOT, 'static', 'data', 'cbb-intl.json')):   # international prospects
            d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-intl.json')))
            ix = {c: i for i, c in enumerate(d['cols'])}
            rows += [{'name': r[ix['name']], 'team': r[ix['team']], 'pos': r[ix['pos']], 'id': None, 'cls': 'Intl',
                      'fv': r[ix['fv']], 'mpg': r[ix['mpg']] if 'mpg' in ix else None} for r in d['rows']]
        return NM.Matcher(rows, id='id', sport='football' if sport == 'cfb' else 'basketball')
    if sport == 'nba':          # rate: XPM this season (raw, points per 100 over average); usage: minutes a game
        fs = sorted(f for f in os.listdir(os.path.join(ROOT, 'static', 'data', 'nba-xpm')) if f[:4].isdigit())
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', fs[-1])))
        return NM.Matcher([{'name': p['n'], 'team': p.get('tm'), 'pos': p.get('pos'), 'xpm': p.get('txpm', p.get('xpm')),
                            'mpg': round(p['mp'] / p['g'], 1) if p.get('g') else None} for p in d['players']], sport='basketball')
    if sport == 'soccer':       # usage: league minutes an appearance
        fs = sorted(f for f in os.listdir(os.path.join(ROOT, 'static', 'data', 'soccer-war')) if f[:4].isdigit())
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'soccer-war', fs[-1])))
        return NM.Matcher([{'name': p['n'], 'team': p.get('team'), 'pos': p.get('pos'),
                            'mpg': round(p['min'] / p['mp']) if p.get('mp') else None, 'pg90': p.get('pg90')}   # rate: p/90 (metric audit Nov 24)
                           for p in d['players']], sport='soccer')
    if sport == 'nfl':
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nfl-war.json')))
        return NM.Matcher([{'name': p['n'], 'team': p.get('tm'), 'pos': p.get('pos'), 'pxp': p.get('pxp'),
                            'snpg': round(p['sn'] / p['g'], 1) if p.get('g') and p.get('sn') else None}
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


def status_x(sport, v):
    """v: recruit rank (cbb), stars (cfb), pick (nba, nfl), market value EUR M (soccer); None = unranked / undrafted / missing"""
    if sport == 'cbb':
        lr = -math.log(min(500.0, v)) if v else -math.log(500)
        return [lr, 0.0 if v else 1.0, max(0.0, lr + math.log(100))]
    if sport == 'cfb':
        return [float(v) if v else 2.0, 0.0 if v else 1.0]
    if sport in ('nba', 'nfl'):
        return [-math.log(v if v else (61 if sport == 'nba' else 270)), 0.0 if v else 1.0]
    if sport == 'soccer':
        return [math.log(v + 0.1) if v else math.log(5.1), 0.0 if v else 1.0]


def convert(sport):
    src = json.load(open(os.path.join(DIR, sport + '.json')))
    Y = json.load(open(YOUNG)) if os.path.exists(YOUNG) else {}
    SF = (json.load(open(STATUS)) if os.path.exists(STATUS) else {}).get(sport)
    if SF:
        DR = json.load(open(os.path.join(ROOT, 'scripts', 'nba_draft_picks.json'))) if sport == 'nba' else {}

    def edge(r):
        """BO% minus the odds his status alone gives (points); a first-year's odds are his status's, so 0"""
        if not SF or r.get('p') is None or r.get('intl'):
            return None
        if r.get('fr'):
            return 0.0
        st = r.get('st')
        if sport == 'nba':
            st = (DR.get(str(r.get('id'))) or [None, None])[1]
        x = status_x(sport, st)
        z = SF['fit']['b0'] + sum(b * v for b, v in zip(SF['fit']['b'], x))
        return round(100 * r['p'] - 100 / (1 + math.exp(-max(-30, min(30, z)))), 1)
    try:
        M = board(sport)
    except (OSError, ValueError, KeyError) as e:
        print(sport, 'board join skipped:', e)
        M = None
    tiers, st = src.get('tiers') or [], src.get('stat') or {}
    u = src.get('u') or {}
    cols = [{'k': 'p', 'l': 'BO%', 't': 'breakout odds next season', 'f': 'p', 'ph': 0, 'num': 1}]
    if SF:
        cols = [{'k': 'e', 'l': 'EDGE', 't': 'BO%% minus the breakout odds of his status alone (%s), points'
                 % {'cbb': 'recruiting rank', 'cfb': 'recruiting stars', 'nba': 'draft slot', 'nfl': 'draft slot',
                    'soccer': 'market value'}[sport], 'f': 's1', 'num': 1}] + cols
    if sport in ('cfb', 'cbb'):
        cols += [{'k': 'yr', 'l': 'Class', 't': 'class this season', 'f': 't', 'num': 0},
                 {'k': 'fv', 'l': 'FV', 't': 'future value (board)', 'f': '0', 'num': 1}]
    elif sport == 'nfl':
        cols.append({'k': 'pxp', 'l': 'pXP/60', 't': 'pXP/60: points of margin over an average regular at his position per 60 snaps, this season and the two before, shrunk (the NFL board predictive rate)', 'f': 's2', 'num': 1})
    cols += [
            {'k': 'sig', 'l': 'Signals', 't': 'signals pushing his odds up most', 'f': 's', 'ph': 1},
            {'k': 'u', 'l': u.get('lab', 'USE'), 't': u.get('t') or (u.get('lab', 'workload') + ' now'),
             'f': str(u.get('dec', 1)), 'ph': 1, 'num': 1}]
    # Noah (Nov 23): every sport shows a rate stat (XPM in the NBA, Stat+ in CFB) and a minutes-type usage figure
    cols += {'nba': [{'k': 'mpg', 'l': 'MPG', 't': 'minutes a game this season', 'f': '1', 'ph': 1, 'num': 1},
                     {'k': 'xpm', 'l': 'XPM', 't': 'XPM this season: Cross Plus-Minus, points per 100 over average (raw)', 'f': 's1', 'ph': 1, 'num': 1}],
             'cbb': [{'k': 'mpg', 'l': 'MPG', 't': 'minutes a game this season', 'f': '1', 'ph': 1, 'num': 1}],
             'cfb': [{'k': 'snp', 'l': 'Snap%', 't': 'share of team snaps this season', 'f': 'p', 'ph': 1, 'num': 1},
                     {'k': 'splus', 'l': 'Stat+', 't': 'Stat+ this season: 100 + 25 z of the position score (PFN), 100 = average at the position', 'f': '0', 'ph': 1, 'num': 1}],
             'nfl': [{'k': 'snpg', 'l': 'Snaps/G', 't': 'snaps a game this season', 'f': '1', 'ph': 1, 'num': 1}],
             'soccer': [{'k': 'mpg', 'l': 'Min/G', 't': 'league minutes an appearance this season', 'f': 'i', 'ph': 1, 'num': 1},
                        {'k': 'pg90', 'l': 'p/90', 't': 'p/90 this season: SV a 90 this season and the two before at weights 1, .5, .25, shrunk to the position mean, less .008 a year over 29 (the soccer board predictive rate)', 'f': 's3', 'ph': 1, 'num': 1}]}.get(sport, [])
    # soccer: p/90, the predictive rate, stands in for best GAR/90 (metric audit Nov 24 2026); the bar stays in the model
    if any(r.get('best') is not None for r in src.get('rows') or []) and sport in BEST and sport != 'soccer':
        lb, tt, f = BEST[sport]
        cols.append({'k': 'best', 'l': 'Best', 't': tt, 'f': f, 'ph': 1, 'num': 1})
    views = ([['e', 'EDGE', 'BO% minus the odds his status alone gives']] if SF else []) + [['p', 'BO%', 'breakout odds next season']]
    # CBB: the rate beside the odds is xXPM (the predictive pick where freshmen are in the table; Nov 27 2026, context
    # rule), not the file's shrunk BPM; the bar and the ceiling stay on BPM, the model's own units
    CBX = sport == 'cbb' and M is not None
    if CBX and src.get('cur'): src['cur'] = {'lab': 'xXPM', 't': 'projected XPM this season', 'dec': 1}
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
             'xc': r.get('xc'), 'e': edge(r)}
        if CBX: o['x'] = None
        if M is not None:
            m, _ = M.find(o['n'], team=o['tm'], pos=o['pos'] or None,
                          id=str(r.get('id') or '') or None if sport == 'cfb' else None)   # CBB rows carry Barttorvik ids
            if m:
                for k in ('fv', 'pxp', 'xpm', 'mpg', 'splus', 'snp', 'snpg', 'pg90'):
                    if m.get(k) is not None:
                        o[k] = m[k]
                if CBX: o['x'] = m.get('xx')
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
    mob = ['fv', 'splus'] if sport == 'cfb' else ['fv', 'x'] if sport == 'cbb' else ['pxp'] if sport == 'nfl' else ['x']   # phones: + pos, class, age on the team line
    who = ('Fr/So only' if y.get('rule') == 'cls' else 'age %d and under' % y['max_age'] if y.get('max_age') else '')
    mob = (['p'] if SF else []) + mob
    # EDGE leads where its held-out top 25s found more breakouts beyond their status than BO%'s did
    lead = bool(SF) and (SF['top_by_edge']['breakouts'] - SF['top_by_edge']['status_implied']
                         > SF['top_by_bo']['breakouts'] - SF['top_by_bo']['status_implied'])
    if SF and not lead:
        views[0], views[1] = views[1], views[0]
        cols[0], cols[1] = cols[1], cols[0]
    out = {'sport': sport, 'asof': src.get('asof'), 'title': 'next up', 'key': 'e' if lead else 'p', 'mob': mob,
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
