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
            season: P is too sure) times TIMING, at the entry price, times the slate scale 1 / (1 + (n - 1) rho) for the
            week's n props settling together, on ONE prop a player a game (his best edge at its price; the rest pass);
            then the week's stakes scaled together to fit BUDGET % of the bankroll (Oct 29 2026, see
            data/nfl_props_research.json stakes, data/nfl_props_onebet_research.json), quarter units from .25, at most
            the book's cap; nothing if the chance doesn't beat the price
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
BUDGET = 50.0         # % of bankroll the week's props share at most: every stake that week scaled down together to fit
# (Noah, Oct 29 2026: "50% a week until 300 graded". The backtest beat archived ESPN BET opens at an assumed -110; live
# bets face Novig asks (median -113) on lines that may be sharper. At -113, a true hit rate of 53% instead of the
# held-out 55.3% gives a 25% drawdown 87% of the time at 100% a week, 1% at 50%. Revisit with live CLV at 300 graded.)
# one player's props in a game settle together (receptions, receiving yards and rush + rec yards move as one; results
# correlate .42), so only his best prop is bet (Noah, Oct 29 2026: "why not just choose the most profitable pick as the
# one pick for each player, or list them all as a parlay?"). Held out 2025-26 at a 100% week (-103, wed projections):
# best prop +10.4% log growth a week against +9.6% sharing one stake across his props (paired t 1.4; 2024 tune t 4.7),
# worst week -6.5% vs -4.5%; a same-player Novig parlay +9.5% even
# priced at the fair joint chance (scripts/nfl_props_onebet_research.py)
ONE_A_PLAYER = True
LABEL = {'py': 'pass yds', 'ptd': 'pass TD', 'ry': 'rush yds', 'wy': 'rec yds', 'rc': 'rec', 'rwy': 'rush+rec yds'}
SUMMARY = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'


def load_fit():
    return json.load(open(FIT))


def rule_of(F):
    import units as U
    return {'name': 'nfl-prop-60', 'stats': sorted(F['stats']), 'pstar': F['pstar'], 'c': F['c'], 'rho': F.get('rho', 0.0),
            'timing': U.TIMING, 'budget': BUDGET, 'cap': U.BOOK_CAP, 'kelly': 1.0, 'onePerPlayer': ONE_A_PLAYER, 'withMean': True,
            'registered': F['registered']}


def kelly(R, ch, o, nw=1):
    """% of bankroll before the week's budget: full Kelly on the calibrated edge x TIMING at American price o, for one of
    nw props this week (the week's slate scale); 0 with no edge at that price"""
    b = dec(o) - 1
    e = ch * b - (1 - ch)
    if e <= 0:
        return 0.0
    return R['kelly'] * R['timing'] * e / b * 100 / (1 + (nw - 1) * R['rho'])


def units(R, f, scale):
    """the posted stake: f times the week's budget scale, quarter units from .25, never past the book's cap"""
    return 0.0 if f <= 0 else min(R['cap'], max(.25, round(f * scale * 4) / 4))


def week(k):
    """an NFL week (Thursday to Monday, kickoffs in UTC: Monday night is Tuesday) as the ISO week two days before kickoff"""
    d = datetime.datetime.fromisoformat(k.replace('Z', '+00:00')) - datetime.timedelta(days=2)
    return d.isocalendar()[:2]


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
            if not with_mean(side, r['L'], r['m']):
                return None
            ch = .5 + R['c'] * (p - .5)
            u = kelly(R, ch, o)
            if u <= 0:
                return None
            return {'side': side, 'p': round(p, 3), 'ch': round(ch, 3), 'mkt': round(nv(r['oO'], r['oU']) if side == 'o' else 1 - nv(r['oO'], r['oU']), 3),
                    'o': o, 'u': u, 't': r['t'], 'L': r['L'], 'm': r['m'], 'bk': r.get('src', 'dk')}
        return None
    return None


def with_mean(side, L, m):
    """our mean projection is on the bet's side of the line. The shape's skew alone can put P(under) past .60 with the line
    below our mean (a low median); those unders lost: 45.6% on 217 in the 2024 tune season, 51.7% on 582 held out
    2025-26, against 56.0% for the rest held out (Noah, Oct 29 2026: "Why are all of our prop bets unders?")"""
    return L >= m if side == 'u' else L <= m


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
        posted = {(b['id'], b['a'], b['s']): b['u'] for b in old.get('bets', [])} if old.get('ruleId') == rid else {}
    except (OSError, ValueError):
        old, done, posted = None, {}, {}
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
            un = kelly(R, .5 + R['c'] * (ps - .5), o) if pn is not None and ps >= R['pstar'] and with_mean(b['side'], c['L'], c['m'] if c.get('m') is not None else b['m']) else 0.0
            b['now'] = {'L': c['L'], 'o': o, 'u': un, 'p': None if pn is None else round(ps, 4)}
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
    # stakes: one prop a player a game (the most Kelly at its entry price), then the week's props are scaled together to
    # fit BUDGET (graded bets and bets already kicked off keep what they were posted at)
    top, wk = {}, defaultdict(list)
    for b in bets:
        f = kelly(R, b['ch'], b['o'])
        if f > top.get((b['id'], b['a']), (-1, None))[0]:
            top[(b['id'], b['a'])] = (f, b['s'])
    bets = [b for b in bets if top[(b['id'], b['a'])][1] == b['s']]   # his other props are not bets
    for b in bets:
        wk[week(b['k'])].append(b)
    for bs in wk.values():
        raw = {id(b): kelly(R, b['ch'], b['o'], len(bs)) for b in bs}
        # stakes already fixed (graded, or started at a posted stake) use up their share of the budget first
        fixed = {id(b): (done.get(k) or {}).get('u', posted.get(k)) for b in bs
                 for k in [(b['id'], b['a'], b['s'])] if k in done or (b['k'] <= now and k in posted)}
        free = [raw[id(b)] for b in bs if id(b) not in fixed]
        room = max(0.0, R['budget'] - sum(fixed.values()))
        sc = min(1.0, room / sum(free)) if sum(free) > 0 else 1.0
        while sc > .01 and sum(units(R, f, sc) for f in free) > room:
            sc *= .98                                # rounding and the .25 floor stay inside the budget
        for b in bs:
            key = (b['id'], b['a'], b['s'])
            if key in done:
                continue
            if b['k'] <= now and key in posted:
                b['u'] = posted[key]                 # started: the stake it was posted at
            else:
                b['u'], b['scale'] = units(R, raw[id(b)], sc), round(sc, 4)
            nw = b.get('now')
            if nw and nw['u']:
                nw['u'] = units(R, kelly(R, .5 + R['c'] * (nw['p'] - .5), nw['o'], len(bs)), sc)
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
        return mu, (mu / math.sqrt(var) if var > 0 and len(by) > 1 else None)
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
                      'sized': {'units': rec['units'], 'risked': rec['staked'],
                                'roi': round(rec['units'] / rec['staked'], 3) if rec['staked'] else None}},
           'log': log}
    try:
        old = json.load(open(PICKS))
        if {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in out.items() if k != 'asof'}:
            return
    except (OSError, ValueError):
        pass
    with open(PICKS, 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    import night_cap      # the nightly exposure cap over every sport's picks (Noah, Nov 1 2026: 40% a night)
    night_cap.apply(['nflprops'])


if __name__ == '__main__':
    main()
