#!/usr/bin/env python3
"""The NBA and NHL props paper books (Oct 31 2026, Noah: "NBA/NHL player props in the same way we did NFL ones"): paper
bets on player props from our projections, on rules that passed held out before their first live bet
(scripts/nba_props_research.py, scripts/nhl_props.py --test -> data/<sport>_props_fit.json). The NFL book's rules
(scripts/nfl_props_paper.py) on daily slates.

    python3 scripts/props_daily.py nba nhl   # the odds-snap workflow runs it after scripts/props_snap.py

Reads the snapshots (scripts/data/props/<sport>-*.jsonl) and the fit, writes data/games_picks_<sport>props.json in the
picks logs' shape (mk 'prop'), so the picks tab, the paper book and the bets alerts carry them; a fit marked 'paper'
writes data/props_paper_<sport>.json instead (same shape, read by nothing on the picks side).

Oct 31 2026: NBA props failed held out at the book's prices (data/nba_props_research.json, no fit passes, no book);
NHL props failed except saves, which Noah picked to paper-test (data/nhl_props_fit.json, rule nhl-saves-56).

    entry   a prop's first snapshot with our projection and a price (Novig's asks where Novig lists it, DraftKings'
            through ESPN otherwise), before tip, regular season
    side    the fit's sides (NBA: unders only; see the fit's note) whose P (negative binomial at our mean with the fit's
            spread and shape correction, scripts/props_model.py) is p* or more
    stake   the book's rule (scripts/units.py): full Kelly on the calibrated edge (chance = .5 + c (P - .5), c from the
            tune season) times TIMING, at the entry price, times the slate scale 1 / (1 + (n - 1) rho) for the day's n
            props; ONE prop a player a game (his best edge at its price); the day's stakes then scaled together to fit
            the fit's daily budget, quarter units from .25, at most the book's cap; nothing if the chance doesn't beat
            the price
Before tip a bet whose current line and price no longer clear the rule is a pass, as on the picks tab. Graded on ESPN box
scores; a player missing from the box voids. Judged by the close too: the bet's return at the close's no-vig chance,
moved along our distribution when the line moved.
"""
import datetime
import hashlib
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from props_paper import dec, nv, sec  # noqa: E402

ROOT = os.path.dirname(HERE)
PROPS = os.path.join(HERE, 'data', 'props')
SP = {
    'nba': {'name': 'NBA props', 'games': os.path.join(ROOT, 'data', 'nba_players.json'),
            'label': {'pts': 'pts', 'reb': 'reb', 'ast': 'ast', 'pra': 'pts+reb+ast', 'pr': 'pts+reb', 'pa': 'pts+ast',
                      'ar': 'reb+ast'}},
    'nhl': {'name': 'NHL props', 'games': os.path.join(ROOT, 'data', 'nhl_props.json'),
            'label': {'sog': 'shots', 'g': 'goals', 'ast': 'assists', 'pts': 'points', 'blk': 'blocks', 'hit': 'hits',
                      'sv': 'saves'}},
}


def fit_file(sport):
    return os.path.join(ROOT, 'data', f'{sport}_props_fit.json')


def rule_of(sport, F):
    import units as U
    return {'name': F['rule'], 'stats': sorted(F['stats']), 'sides': F['sides'], 'pstar': F['pstar'], 'c': F['c'],
            'rho': F.get('rho', 0.0), 'timing': U.TIMING, 'budget': F['budget'], 'cap': U.BOOK_CAP, 'kelly': 1.0,
            'onePerPlayer': True, 'registered': F['registered']}


def p_over(F, s, mu, L):
    import props_model as M
    if mu is None or mu <= 0 or s not in F['shape']:
        return None
    return M.p_over(F['shape'][s], mu, L)


def kelly(R, ch, o, n=1):
    b = dec(o) - 1
    e = ch * b - (1 - ch)
    if e <= 0:
        return 0.0
    return R['kelly'] * R['timing'] * e / b * 100 / (1 + (n - 1) * R['rho'])


def units(R, f, scale):
    return 0.0 if f <= 0 else min(R['cap'], max(.25, round(f * scale * 4) / 4))


def slate(k):
    """the slate: the game's US Eastern date (tips in UTC; a 10 PM ET tip is the next day UTC)"""
    d = datetime.datetime.fromisoformat(k.replace('Z', '+00:00')) - datetime.timedelta(hours=5)
    return d.date().isoformat()


def load(sport):
    rows = defaultdict(list)
    if not os.path.isdir(PROPS):
        return rows
    for fn in sorted(os.listdir(PROPS)):
        if not (fn.startswith(sport + '-') and fn.endswith('.jsonl')):
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


def side_of(F, R, r):
    """(side, P, price) the rule bets on this snapshot row, or None"""
    if r.get('m') is None or r.get('oO') is None or r.get('oU') is None or r.get('po'):
        return None
    po = p_over(F, r['s'], r['m'], r['L'])
    if po is None:
        return None
    for side, p, o in (('o', po, r['oO']), ('u', 1 - po, r['oU'])):
        if side in R['sides'] and p >= R['pstar']:
            return side, p, o
    return None


def entry(F, R, snaps, since):
    for r in snaps:
        if r['t'] >= r['k']:
            return None
        if r['t'] < since:
            continue                                # before the rule was registered
        x = side_of(F, R, r)
        if not x:
            if r.get('m') is not None and r.get('oO') is not None:
                return None                          # its first priced row with our number didn't qualify
            continue
        side, p, o = x
        ch = .5 + R['c'] * (p - .5)
        if kelly(R, ch, o) <= 0:
            return None
        return {'side': side, 'p': round(p, 3), 'ch': round(ch, 3),
                'mkt': round(nv(r['oO'], r['oU']) if side == 'o' else 1 - nv(r['oO'], r['oU']), 3),
                'o': o, 't': r['t'], 'L': r['L'], 'm': r['m'], 'bk': r.get('src', 'dk')}
    return None


def nba_box(gid):
    import nba_players as NP
    b = NP.pbox(gid, final=True)
    if not b:
        return None
    out = {}
    for t in b.values():
        for r in t:
            pts, reb, ast = r[5], r[6], r[7]
            out[str(r[0])] = {'pts': pts, 'reb': reb, 'ast': ast, 'pra': pts + reb + ast, 'pr': pts + reb,
                              'pa': pts + ast, 'ar': ast + reb}
    return out


def nhl_box(gid, k):
    import nhl_pbox as B
    os.makedirs(B.CACHE, exist_ok=True)
    b = B.box(gid, k, False)
    if not b:
        return None
    out = {}
    for t in b['p'].values():
        for r in t:
            out[str(r[0])] = {'g': r[5], 'ast': r[6], 'pts': r[5] + r[6], 'sog': r[7], 'blk': r[8], 'hit': r[9]}
    for t in b['gk'].values():
        for r in t:
            out[str(r[0])] = {'sv': r[4]}
    return out


def run(sport):
    try:
        F = json.load(open(fit_file(sport)))
    except (OSError, ValueError):
        return print(f'{sport} props: no fit')
    if F.get('verdict') != 'pass':
        return print(f'{sport} props: rule did not pass held out; no book')
    R = rule_of(sport, F)
    rid = hashlib.sha1(json.dumps(R, sort_keys=True).encode()).hexdigest()[:10]
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    # a paper test (the fit's 'paper': NHL saves, Noah Oct 31 2026) stays off the picks tab and the paper book
    out_fn = os.path.join(ROOT, 'data', f'props_paper_{sport}.json' if F.get('paper') else f'games_picks_{sport}props.json')
    try:
        old = json.load(open(out_fn))
        same = (old.get('rule') or {}).get('id') == rid
        prev = {(e['espn'], e['a'], e['stat']): e for e in old.get('log', [])} if same else {}
    except (OSError, ValueError):
        old, prev = None, {}
    since = F['registered'] + 'T00:00:00Z' if len(F['registered']) == 10 else F['registered']
    bets = []
    for (gid, a, s), lst in load(sport).items():
        if s not in F['stats']:
            continue
        pe = prev.get((gid, a, s))
        if pe and pe.get('_b', {}).get('res'):
            bets.append(pe['_b'])
            continue
        b = entry(F, R, lst, since)
        if not b:
            continue
        b.update({'id': gid, 'a': a, 's': s, 'k': lst[0]['k'], 'n': next((r['n'] for r in lst if r.get('n')), None)})
        if pe:
            b['u0'] = pe['_b'].get('u')
        pre = [r for r in lst if b['t'] <= r['t'] < r['k'] and r.get('oO') is not None and r.get('oU') is not None]
        if pre:
            c = pre[-1]
            m = c['m'] if c.get('m') is not None else b['m']
            pn = p_over(F, s, m, c['L'])
            if b['k'] > now:
                ps = None if pn is None else (pn if b['side'] == 'o' else 1 - pn)
                o = c['oO'] if b['side'] == 'o' else c['oU']
                ok = ps is not None and ps >= R['pstar']
                b['now'] = {'L': c['L'], 'o': o, 'p': None if ps is None else round(ps, 4),
                            'f': kelly(R, .5 + R['c'] * (ps - .5), o) if ok else 0.0}
            else:
                q = nv(c['oO'], c['oU'])
                if c['L'] != b['L']:
                    q += (p_over(F, s, b['m'], b['L']) or 0) - (p_over(F, s, b['m'], c['L']) or 0)
                    q = min(max(q, .01), .99)
                pc = q if b['side'] == 'o' else 1 - q
                b['close'] = {'L': c['L'], 'oO': c['oO'], 'oU': c['oU'], 'p': round(pc, 3), 'bk': c.get('src', 'dk')}
                b['clv'] = round(pc * dec(b['o']) - 1, 4)
        bets.append(b)
    # one prop a player a game (the most Kelly at its entry price); the day's stakes scaled together to fit the budget
    top = {}
    for b in bets:
        f = kelly(R, b['ch'], b['o'])
        if f > top.get((b['id'], b['a']), (-1, None))[0]:
            top[(b['id'], b['a'])] = (f, b['s'])
    bets = [b for b in bets if top[(b['id'], b['a'])][1] == b['s']]
    day = defaultdict(list)
    for b in bets:
        day[slate(b['k'])].append(b)
    for bs in day.values():
        raw = {id(b): kelly(R, b['ch'], b['o'], len(bs)) for b in bs}
        tot = sum(raw.values())
        sc = min(1.0, R['budget'] / tot) if tot > 0 else 1.0
        while sc > .01 and sum(units(R, f, sc) for f in raw.values()) > R['budget']:
            sc *= .98
        for b in bs:
            if b.get('res'):
                continue
            if b['k'] <= now and b.get('u0') is not None:
                b['u'] = b['u0']                     # started: the stake it was posted at
            else:
                b['u'], b['scale'] = units(R, raw[id(b)], sc), round(sc, 4)
            nw = b.get('now')
            if nw:
                nw['u'] = units(R, nw['f'] / max(1e-9, kelly(R, b['ch'], b['o'])) * raw[id(b)], sc) if nw['f'] else 0.0
    boxes = {}
    for b in bets:
        if b['k'] > now or b.get('res'):
            continue
        if b['id'] not in boxes:
            boxes[b['id']] = nba_box(b['id']) if sport == 'nba' else nhl_box(b['id'], b['k'])
        bx = boxes[b['id']]
        if not bx:
            continue
        if b['a'] not in bx or b['s'] not in bx[b['a']]:
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
    write(sport, R, rid, F, bets, now, out_fn, old)


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


def teams(sport):
    """espn game id -> (home, away)"""
    try:
        if sport == 'nba':
            return {g['id']: (g['h'], g['a']) for g in json.load(open(SP['nba']['games'])).get('games', [])}
        return {g['id']: (g['h'], g['a']) for g in json.load(open(SP['nhl']['games'])).get('games', [])}
    except (OSError, ValueError, KeyError):
        return {}


def write(sport, R, rid, F, bets, now, out_fn, old):
    graded = [b for b in bets if b.get('res') in ('w', 'l', 'push')]
    cm, ct = clustered([(b['id'], b['clv']) for b in bets if 'clv' in b])
    rm, rt = clustered([(b['id'], b['ret']) for b in graded])
    tm = teams(sport)
    if old:
        for e in old.get('log', []):
            if e.get('espn') in tm:
                continue
            tm[e['espn']] = (e.get('home'), e.get('away'))
    lab = SP[sport]['label']
    log = []
    for b in bets:
        h, a = tm.get(b['id'], ('', ''))
        bo = dec(b['o']) - 1
        e = {'id': f"{b['id']}-{b['a']}-{b['s']}", 'espn': b['id'], 'a': b['a'], 'sport': f'{sport}props', 'kick': b['k'],
             'home': h or '', 'away': a or '', 'mk': 'prop', 'side': 'over' if b['side'] == 'o' else 'under',
             'line': b['L'], 'price': b['o'], 'player': b.get('n') or b['a'], 'stat': b['s'], 'statN': lab.get(b['s'], b['s']),
             'proj': b['m'], 'p': b['ch'], 'pDU': b['ch'], 'pRaw': b['p'], 'ev': round(b['ch'] * bo - (1 - b['ch']), 4),
             'evDU': round(b['ch'] * bo - (1 - b['ch']), 4), 'edge': round((b['p'] - .5) * 100, 1),
             'x': round((R['pstar'] - .5) * 100), 'units': b.get('u', 0.0), 'flagged': b['t'], 'bk': b['bk']}
        if b.get('close'):
            e['close'] = b['close']['L']
        if b.get('clv') is not None:
            e['clvRet'] = b['clv']
        if b.get('res') in ('w', 'l'):
            e['res'] = b['res']
        elif b.get('res') == 'push':
            e['res'] = 'p'
        elif b.get('res') == 'void':
            e['pass'], e['void'] = True, True
        if b.get('x') is not None:
            e['score'] = b['x']
        nw = b.get('now')
        if nw and b['k'] > now:
            e['now'] = {'mk': 'prop', 'side': e['side'], 'line': nw['L'], 'price': nw['o'], 'units': nw['u']}
            if not nw['u']:
                e['pass'] = True
        e['_b'] = {k: v for k, v in b.items() if k not in ('now', 'u0')}
        log.append(e)
    cut = (datetime.datetime.fromisoformat(now.replace('Z', '+00:00')) - datetime.timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
    picks = [e for e in log if e['kick'] > cut]
    out = {'sport': f'{sport}props', 'name': SP[sport]['name'], 'asof': now, 'rule': dict(R, id=rid),
           'backtest': F.get('backtest'), 'picks': picks, 'withdrawn': [], 'board': [],
           'record': {'n': len(graded), 'w': sum(b['res'] == 'w' for b in graded), 'l': sum(b['res'] == 'l' for b in graded),
                      'clvN': sum('clv' in b for b in bets), 'clvRet': None if cm is None else round(cm, 4),
                      'clvT': None if ct is None else round(ct, 2),
                      'sized': {'units': round(sum(b['u'] * b['ret'] for b in graded), 2), 'roi': None if rm is None else round(rm, 4)}},
           'log': log[-1500:]}
    if old and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in out.items() if k != 'asof'}:
        return print(f'{sport} props: no change')
    with open(out_fn, 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    print(f'{sport} props:', len(bets), 'bets,', len(graded), 'graded')


if __name__ == '__main__':
    for sp in sys.argv[1:] or ('nba', 'nhl'):
        try:
            run(sp)
        except Exception as ex:
            print(f'{sp} props failed:', ex)
