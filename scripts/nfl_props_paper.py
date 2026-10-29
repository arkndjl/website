#!/usr/bin/env python3
"""The NFL props paper book (Oct 29 2026, ARK Edge Sweep): paper bets on player props from nfl_fantasy's stat lines,
on a rule that passed held out before its first live bet (scripts/nfl_props_research.py -> data/nfl_props_research.json).

    python3 scripts/nfl_props_paper.py     # the odds-snap workflow runs it after scripts/props_snap.py

Reads the NFL snapshots (scripts/data/props/nfl-*.jsonl) and data/nfl_props_fit.json, writes data/props_paper_nfl.json.

Rule nfl-prop-60 (registered 2026-10-29; changing RULE restarts its record):
    stats   passing yards and TDs, rushing yards, receiving yards, receptions, rushing + receiving yards
    entry   a prop's first snapshot with our stat line and a price (Novig's asks; ESPN gives DraftKings' NFL lines without
            prices), before kickoff
    side    the side whose P (the 2016-23 shape of result / projection by projection decile, at line / projection) is
            .60 or more: the tune-season pick from .52-.60. Held out (2025 ESPN BET, 2026 DraftKings opens, graded at
            -110): 3,600 bets hit 55.6%, +6.2% a bet, t 3.3 (299 games as clusters); +4.0% at -115
    stake   the book's rule (scripts/units.py): full Kelly on the calibrated edge (chance = .5 + c (P - .5), c from the tune
            season: P is too sure) times TIMING, at the entry price, times the slate scale 1 / (1 + (NB - 1) rho) for the
            week's NB props settling together, then no more than BUDGET / NB (the week's props share BUDGET % of the
            bankroll; Oct 29 2026, see data/nfl_props_research.json stakes), quarter units from .25; nothing if the
            chance doesn't beat the price
Since Oct 29 2026 (Noah: "add the NFL props to the pick board") the bets are also the Predictions picks: written as
data/games_picks_nflprops.json in the picks logs' shape (mk 'prop'), so the picks tab, the paper book and the bets
alerts (scripts/paper_book.py, scripts/bets_today.py) carry them. Before kickoff a bet whose current line and price no
longer clear the rule is a pass, as on the picks tab.

Graded on ESPN box scores; a player missing from the box voids (as the books void a player who doesn't play). Judged by
the close too: the bet's return at the close's no-vig chance, moved along our shape when the line moved.
"""
import bisect
import datetime
import hashlib
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from props_paper import dec, nv, sec  # noqa: E402

ROOT = os.path.dirname(HERE)
PROPS = os.path.join(HERE, 'data', 'props')
FIT = os.path.join(ROOT, 'data', 'nfl_props_fit.json')
RES = os.path.join(ROOT, 'data', 'nfl_props_research.json')
OUT = os.path.join(ROOT, 'data', 'props_paper_nfl.json')
PICKS = os.path.join(ROOT, 'data', 'games_picks_nflprops.json')
GAMES = os.path.join(ROOT, 'data', 'nfl_games.json')
NB = 60               # Novig-priced props the rule takes a week (63 in its first week)
BUDGET = 100.0        # % of bankroll the week's props share at most
LABEL = {'py': 'pass yds', 'ptd': 'pass TD', 'ry': 'rush yds', 'wy': 'rec yds', 'rc': 'rec', 'rwy': 'rush+rec yds'}
SUMMARY = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'


def load_fit():
    return json.load(open(FIT))


def rule_of(F):
    import units as U
    return {'name': 'nfl-prop-60', 'stats': sorted(F['stats']), 'pstar': F['pstar'], 'c': F['c'], 'rho': F.get('rho', 0.0),
            'timing': U.TIMING, 'nb': NB, 'budget': BUDGET, 'cap': min(U.BOOK_CAP, BUDGET / NB), 'kelly': 1.0,
            'registered': F['registered']}


def stake(R, ch, o):
    """% of bankroll on a prop at calibrated chance ch and American price o (0: no edge at that price)"""
    b = dec(o) - 1
    e = ch * b - (1 - ch)
    if e <= 0:
        return 0.0
    f = R['kelly'] * R['timing'] * e / b * 100 / (1 + (R['nb'] - 1) * R['rho'])
    return min(math.floor(R['cap'] * 4) / 4, max(.25, round(f * 4) / 4))


def p_over(F, s, mu, L):
    """P(result > L) from the fit's shape: the projection's decile, then the share of its result / projection over L / mu"""
    parts, edges, qs = F['stats'][s]
    if not mu or mu <= 0:
        return None
    b = qs[min(len(qs) - 1, max(0, bisect.bisect_right(edges, mu) - 1))]
    r = L / mu
    if r <= b[0]:
        return 1 - .5 / len(b)
    if r >= b[-1]:
        return .5 / len(b)
    i = bisect.bisect_right(b, r)
    lo, hi = b[i - 1], b[i]
    f = (i - 1 + ((r - lo) / (hi - lo) if hi > lo else 0)) / (len(b) - 1)
    return 1 - f


def load():
    rows = defaultdict(list)
    if not os.path.isdir(PROPS):
        return rows
    for fn in sorted(os.listdir(PROPS)):
        if not (fn.startswith('nfl-') and fn.endswith('.jsonl')):
            continue
        for ln in open(os.path.join(PROPS, fn)):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get('a') == 'game':
                continue
            r['t'], r['k'] = sec(r['t']), sec(r['k'])
            rows[(r['id'], r['a'], r['s'])].append(r)
    return rows


def entry(F, R, snaps):
    for r in snaps:
        if r['t'] >= r['k']:
            return None
        if r.get('m') is None or r.get('oO') is None or r.get('oU') is None:
            continue
        po = p_over(F, r['s'], r['m'], r['L'])
        if po is None:
            return None
        for side, p, o in (('o', po, r['oO']), ('u', 1 - po, r['oU'])):
            if p < R['pstar']:
                continue
            ch = .5 + R['c'] * (p - .5)
            u = stake(R, ch, o)
            if u <= 0:
                return None
            return {'side': side, 'p': round(p, 3), 'ch': round(ch, 3), 'mkt': round(nv(r['oO'], r['oU']) if side == 'o' else 1 - nv(r['oO'], r['oU']), 3),
                    'o': o, 'u': u, 't': r['t'], 'L': r['L'], 'm': r['m'], 'bk': r.get('src', 'dk')}
        return None
    return None


def box(gid):
    """{espn athlete id: {stat: value}} once the game is final, else None"""
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request(SUMMARY + gid, headers={'User-Agent': UA}), timeout=30))
    except Exception:
        return None
    try:
        if not j['header']['competitions'][0]['status']['type']['completed']:
            return None
    except (KeyError, IndexError):
        return None
    out = defaultdict(lambda: defaultdict(float))
    want = {'passing': {'passingYards': 'py', 'passingTouchdowns': 'ptd', 'interceptions': 'pint'},
            'rushing': {'rushingYards': 'ry'}, 'receiving': {'receptions': 'rc', 'receivingYards': 'wy'}}
    for t in (j.get('boxscore') or {}).get('players', []):
        for st in t.get('statistics', []):
            keys = st.get('keys') or []
            for a in st.get('athletes', []):
                aid = str((a.get('athlete') or {}).get('id'))
                row = out[aid]                    # anyone listed in any category played
                for k, s in want.get(st.get('name'), {}).items():
                    if k in keys:
                        try:
                            row[s] += float(a['stats'][keys.index(k)])
                        except (ValueError, IndexError):
                            pass
    for row in out.values():
        row['rwy'] = row['ry'] + row['wy']
    return out


def main():
    F = load_fit()
    R = rule_of(F)
    rid = hashlib.sha1(json.dumps(R, sort_keys=True).encode()).hexdigest()[:10]
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        old = json.load(open(OUT))
        done = {(b['id'], b['a'], b['s']): b for b in old.get('bets', []) if b.get('res')} if old.get('ruleId') == rid else {}
    except (OSError, ValueError):
        old, done = None, {}
    bets = []
    for (gid, a, s), lst in load().items():
        if s not in F['stats']:
            continue
        if (gid, a, s) in done:
            bets.append(done[(gid, a, s)])
            continue
        b = entry(F, R, lst)
        if not b:
            continue
        b.update({'id': gid, 'a': a, 's': s, 'k': lst[0]['k'], 'n': next((r['n'] for r in lst if r.get('n')), None)})
        pre = [r for r in lst if r['t'] < r['k'] and r['t'] >= b['t'] and r.get('oO') is not None and r.get('oU') is not None]
        if pre and b['k'] > now:
            c = pre[-1]
            pn = p_over(F, s, c['m'] if c.get('m') is not None else b['m'], c['L'])
            ps = pn if b['side'] == 'o' else 1 - (pn if pn is not None else 1)
            o = c['oO'] if b['side'] == 'o' else c['oU']
            un = stake(R, .5 + R['c'] * (ps - .5), o) if pn is not None and ps >= R['pstar'] else 0.0
            b['now'] = {'L': c['L'], 'o': o, 'u': un}
        if pre and b['k'] <= now:
            c = pre[-1]
            q = nv(c['oO'], c['oU'])
            if c['L'] != b['L']:
                q += p_over(F, s, b['m'], b['L']) - p_over(F, s, b['m'], c['L'])
                q = min(max(q, .01), .99)
            pc = q if b['side'] == 'o' else 1 - q
            b['close'] = {'L': c['L'], 'oO': c['oO'], 'oU': c['oU'], 'p': round(pc, 3), 'bk': c.get('src', 'dk')}
            b['clv'] = round(pc * dec(b['o']) - 1, 4)
        bets.append(b)
    boxes = {}
    for b in bets:
        if b['k'] > now or b.get('res'):
            continue
        if b['id'] not in boxes:
            boxes[b['id']] = box(b['id'])
        bx = boxes[b['id']]
        if not bx:
            continue
        if b['a'] not in bx:
            b['res'] = 'void'
            continue
        x = bx[b['a']][b['s']]
        b['x'] = x
        if x == b['L']:
            b['res'], b['ret'] = 'push', 0.0
        else:
            win = x > b['L'] if b['side'] == 'o' else x < b['L']
            b['res'], b['ret'] = ('w' if win else 'l'), round(dec(b['o']) - 1 if win else -1.0, 4)
    bets.sort(key=lambda b: (b['k'], b['id'], -b['p']))
    graded = [b for b in bets if b.get('res') in ('w', 'l', 'push')]
    cl = [b for b in bets if 'clv' in b]

    def clustered(xs):
        if len(xs) < 2:
            return None, None
        by = defaultdict(list)
        for g, v in xs:
            by[g].append(v)
        n = len(xs)
        mu = sum(v for _, v in xs) / n
        var = sum(sum(v - mu for v in vs) ** 2 for vs in by.values()) / n ** 2
        return mu, (mu / math.sqrt(var) if var > 0 else None)
    cm, ct = clustered([(b['id'], b['clv']) for b in cl])
    rm, rt = clustered([(b['id'], b['ret']) for b in graded])
    try:
        rs = json.load(open(RES))
        bt = {'held': rs['versions']['full']['held'], 'wed': rs['versions']['wed']['held'], 'byStat': rs['versions']['full']['heldByStat'],
              'bySeason': rs['versions']['full']['heldBySeason'], 'graded': rs['graded'], 'book': rs['book'], 'calib': rs.get('calib')}
    except (OSError, ValueError, KeyError):
        bt = None
    res = {'rule': R, 'ruleId': rid, 'asof': now, 'backtest': bt,
           'record': {'n': len(bets), 'graded': len(graded), 'w': sum(b['res'] == 'w' for b in graded),
                      'l': sum(b['res'] == 'l' for b in graded), 'push': sum(b['res'] == 'push' for b in graded),
                      'clvN': len(cl), 'clvRet': None if cm is None else round(cm, 4), 'clvT': None if ct is None else round(ct, 2),
                      'roi': None if rm is None else round(rm, 4), 'roiT': None if rt is None else round(rt, 2),
                      'units': round(sum(b['u'] * b['ret'] for b in graded), 2), 'staked': round(sum(b['u'] for b in graded), 2)},
           'bets': bets[-400:]}
    write_picks(R, bets, now, res['record'])
    if old and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in res.items() if k != 'asof'}:
        return print('nfl props paper: no change')
    with open(OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print('nfl props paper:', len(bets), 'bets,', len(graded), 'graded,', len(cl), 'with a close')


def write_picks(R, bets, now, rec):
    """the bets as a picks log (data/games_picks_<sport>.json's shape) for the picks tab, the paper book and the alerts"""
    try:
        gm = {str(g['espn']): g for g in json.load(open(GAMES)).get('games', []) if g.get('espn')}
    except (OSError, ValueError):
        gm = {}
    log = []
    for b in bets:
        g = gm.get(b['id']) or {}
        bo = dec(b['o']) - 1
        e = {'id': f"{b['id']}-{b['a']}-{b['s']}", 'espn': b['id'], 'sport': 'nflprops', 'kick': b['k'],
             'home': g.get('home') or '', 'away': g.get('away') or '', 'mk': 'prop', 'side': 'over' if b['side'] == 'o' else 'under',
             'line': b['L'], 'price': b['o'], 'player': b.get('n') or b['a'], 'stat': b['s'], 'statN': LABEL.get(b['s'], b['s']),
             'proj': b['m'], 'p': b['ch'], 'pDU': b['ch'], 'pRaw': b['p'], 'ev': round(b['ch'] * bo - (1 - b['ch']), 4),
             'evDU': round(b['ch'] * bo - (1 - b['ch']), 4),
             'edge': round((b['p'] - .5) * 100, 1), 'x': round((R['pstar'] - .5) * 100), 'units': b['u'], 'flagged': b['t'], 'bk': b['bk']}
        if b.get('close'):
            e['close'] = b['close']['L']
        if b.get('clv') is not None:
            e['clvRet'] = b['clv']
        if b.get('res') in ('w', 'l'):
            e['res'] = b['res']
        elif b.get('res') == 'push':
            e['res'] = 'p'
        elif b.get('res') == 'void':
            e['pass'], e['void'] = True, True          # he didn't play: no bet, out of the record
        if b.get('x') is not None:
            e['score'] = b['x']
        nw = b.get('now')
        if nw and b['k'] > now:
            e['now'] = {'mk': 'prop', 'side': e['side'], 'line': nw['L'], 'price': nw['o'], 'units': nw['u']}
            if not nw['u']:
                e['pass'] = True
        log.append(e)
    picks = [e for e in log if e['kick'] > now or (e['kick'] > (datetime.datetime.fromisoformat(now.replace('Z', '+00:00')) - datetime.timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%SZ'))]
    out = {'sport': 'nflprops', 'name': 'NFL props', 'asof': now, 'rule': R, 'picks': picks, 'withdrawn': [], 'board': [],
           'record': {'n': rec['graded'], 'w': rec['w'], 'l': rec['l'], 'clvN': rec['clvN'], 'clvRet': rec['clvRet'], 'clvT': rec['clvT'],
                      'sized': {'units': rec['units'], 'roi': rec['roi']}},
           'log': log}
    try:
        old = json.load(open(PICKS))
        if {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in out.items() if k != 'asof'}:
            return
    except (OSError, ValueError):
        pass
    with open(PICKS, 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)


if __name__ == '__main__':
    main()
