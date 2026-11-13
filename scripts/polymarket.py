#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Polymarket US as a second venue next to Novig: each side's price after Polymarket's taker fee, at the same line, so a
pick takes whichever venue pays more (paper only). Stdlib only.

    python3 scripts/polymarket.py nba          # today's priced games, matched to ESPN, against Novig
    python3 scripts/polymarket.py --test

Public, no key: gateway.polymarket.us v2/leagues/{league}/events (listing), v1/events/slug/{slug} (every market of a
game: moneyline aec-, spread asc-, total tsc-). A market quotes its long side: bestBidQuote / bestAskQuote; the short
side is bought at 1 - the long bid. Taker fee per contract = feeCoefficient x p x (1 - p) at the price paid (0.095 on
every sports market, Nov 13 2026), so a 50/50 side costs about 0.524: -110, against Novig's ~-103. Polymarket's flag-time
price as an edge signal failed its pre-registered test (scripts/poly_signal.py), so it is a venue only.
"""
import concurrent.futures
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names  # noqa: E402

API = 'https://gateway.polymarket.us'
LEAGUE = {'cfb': 'cfb', 'nfl': 'nfl', 'cbb': 'cbb', 'nba': 'nba', 'nhl': 'nhl'}
HOURS = 48                      # games starting within this many hours get their full market list
MAX_EVENTS = 120
UA = 'arkndjl.net arkboard (odds research)'
FEE = 0.095


def get(path):
    for k in range(3):
        try:
            r = subprocess.run(['curl', '-sS', '--compressed', '-m', '25', '-A', UA, API + path], capture_output=True, text=True, timeout=35)
            return json.loads(r.stdout)
        except (ValueError, subprocess.TimeoutExpired):
            time.sleep(1 + k)
    return None


def cost(p, coef=FEE):
    """what one contract that pays 1 costs at price p, with the taker fee"""
    return p + coef * p * (1 - p)


def american(c):
    """a contract's all-in cost as American odds"""
    c = min(max(float(c), .01), .99)
    return round(-100 * c / (1 - c)) if c >= .5 else round(100 * (1 - c) / c)


def _v(q):
    try:
        return float((q or {}).get('value'))
    except (TypeError, ValueError):
        return None


def asks(m):
    """(long side's all-in cost, short side's all-in cost) or None when the book is one-sided"""
    b, a = _v(m.get('bestBidQuote')), _v(m.get('bestAskQuote'))
    if a is None or b is None or not (0 < b < a < 1):
        return None
    coef = m.get('feeCoefficient')
    coef = FEE if coef is None else float(coef)
    return cost(a, coef), cost(1 - b, coef)


def handicap(desc):
    try:
        return float(str(desc).replace('+', ''))
    except ValueError:
        return None


def listing(sport, now):
    out, off = [], 0
    while len(out) < MAX_EVENTS:
        j = get(f'/v2/leagues/{LEAGUE[sport]}/events?limit=50&offset={off}')
        ev = (j or {}).get('events') or []
        if not ev:
            break
        for e in ev:
            try:
                t = datetime.datetime.fromisoformat((e.get('startTime') or '').replace('Z', '+00:00'))
            except ValueError:
                continue
            if not e.get('live') and not e.get('ended') and now < t < now + datetime.timedelta(hours=HOURS):
                out.append(e)
        if len(ev) < 50:
            break
        off += 50
    return out


def game(e):
    """{'teams': {team id: names}, 'k': start, 'ml': {team id: cost}, 'sp': {(team id, handicap): cost}, 'tot': {(over?, line): cost}}"""
    j = get(f"/v1/events/slug/{e['slug']}")
    ev = (j or {}).get('event') or j or {}
    g = {'teams': {t['id']: [x for x in (t.get('name'), t.get('alias'), t.get('safeName'), t.get('abbreviation'), t.get('displayAbbreviation')) if x]
                   for t in ev.get('teams') or []},
         'k': ev.get('startTime') or e.get('startTime'), 'slug': e['slug'], 'ml': {}, 'sp': {}, 'tot': {}}
    for m in ev.get('markets') or []:
        if m.get('closed') or not m.get('active', True):
            continue
        ax = asks(m)
        if not ax:
            continue
        sides = m.get('marketSides') or []
        lg = [s for s in sides if s.get('long')]
        sh = [s for s in sides if not s.get('long')]
        if not lg or not sh:
            continue
        lg, sh = lg[0], sh[0]
        typ = m.get('sportsMarketTypeV2') or ''
        if typ.endswith('MONEYLINE'):
            if lg.get('teamId') is not None and sh.get('teamId') is not None:
                g['ml'][lg['teamId']], g['ml'][sh['teamId']] = ax
        elif typ.endswith('SPREAD'):
            h = handicap(lg.get('description'))
            if h is not None and lg.get('teamId') is not None and sh.get('teamId') is not None:
                g['sp'][(lg['teamId'], h)] = ax[0]
                g['sp'][(sh['teamId'], -h)] = ax[1]
        elif typ.endswith('TOTAL'):
            try:
                x = float(m.get('line'))
            except (TypeError, ValueError):
                continue
            over = (lg.get('description') or '').lower().startswith('over')
            g['tot'][(over, x)], g['tot'][(not over, x)] = ax
    return g


def games(sport, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ev = listing(sport, now)
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        return [g for g in ex.map(game, ev) if g]


def match(pm, espn):
    """{index in pm: (espn id, home team id, away team id)} by both teams' names and a start within 3 hours"""
    out = {}
    for i, g in enumerate(pm):
        try:
            t = datetime.datetime.fromisoformat(g['k'].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        ks = {tid: {names.team_key(x) for x in ns} for tid, ns in g['teams'].items()}
        hit = []
        for gid, (h, a, k, _) in espn.items():
            if k:
                try:
                    if abs((datetime.datetime.fromisoformat(k.replace('Z', '+00:00')) - t).total_seconds()) > 3 * 3600:
                        continue
                except ValueError:
                    pass
            hk, ak = {names.team_key(x) for x in h}, {names.team_key(x) for x in a}
            th = [tid for tid, s in ks.items() if s & hk]
            ta = [tid for tid, s in ks.items() if s & ak]
            if len(th) == 1 and len(ta) == 1 and th[0] != ta[0]:
                hit.append((gid, th[0], ta[0]))
        if len(hit) == 1:
            out[i] = hit[0]
    return out


def prices(sport, now=None, espn=None):
    """{espn id: {'sp': {home handicap: (home price, away price)}, 'tot': {line: (over, under)}, 'ml': (home, away)}} as
    American odds after the fee; {} when Polymarket can't be read"""
    if sport not in LEAGUE:
        return {}
    try:
        import novig
        pm = games(sport, now)
        ids = match(pm, espn if espn is not None else novig.espn_games(sport, (-1, 2)))
    except Exception as ex:
        print(f'polymarket {sport}: failed ({ex})')
        return {}
    out = {}
    for i, (gid, th, ta) in ids.items():
        g = pm[i]
        r = {'sp': {}, 'tot': {}, 'ml': None, 'slug': g['slug']}
        for (tid, h), c in g['sp'].items():
            if tid == th and (ta, -h) in g['sp']:
                r['sp'][h] = (american(c), american(g['sp'][(ta, -h)]))
        for (over, x), c in g['tot'].items():
            if over and (False, x) in g['tot']:
                r['tot'][x] = (american(c), american(g['tot'][(False, x)]))
        if th in g['ml'] and ta in g['ml']:
            r['ml'] = (american(g['ml'][th]), american(g['ml'][ta]))
        out[str(gid)] = r
    return out


def dec(o):
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / -o)


KEYS = (('oH', 'sp', 'L', 0), ('oA', 'sp', 'L', 1), ('oO', 'tot', 'T', 0), ('oU', 'tot', 'T', 1))


def better(g, pm):
    """{price key: Polymarket price} for each side of g (an ESPN-keyed board game carrying Novig's L/T and prices)
    where Polymarket pays more at the SAME line; moneylines as mlH/mlA"""
    out = {}
    for k, mk, lk, i in KEYS:
        line, o = g.get(lk), g.get(k)
        if line is None or o is None:
            continue
        # L is the home margin the line sets (novig.games: home handicap -L); totals key on the line itself
        q = (pm.get(mk) or {}).get(-float(line) if mk == 'sp' else float(line))
        if q and q[i] is not None and dec(q[i]) > dec(o) + 1e-9:
            out[k] = q[i]
    if pm.get('ml'):
        for k, i in (('mlH', 0), ('mlA', 1)):
            if g.get(k) is not None and dec(pm['ml'][i]) > dec(g[k]) + 1e-9:
                out[k] = pm['ml'][i]
    return out


def test():
    assert abs(cost(.5) - .52375) < 1e-9
    assert american(cost(.5)) == -110
    m = {'bestBidQuote': {'value': '0.31'}, 'bestAskQuote': {'value': '0.32'}, 'feeCoefficient': 0.095}
    a, b = asks(m)
    assert abs(a - (0.32 + 0.095 * .32 * .68)) < 1e-9 and abs(b - (0.69 + 0.095 * .69 * .31)) < 1e-9
    g = {'L': -3.5, 'oH': -105, 'oA': -101, 'T': 220.5, 'oO': -102, 'oU': -104, 'mlH': -160, 'mlA': 140}
    pm = {'sp': {3.5: (-110, 102)}, 'tot': {220.5: (-110, -110)}, 'ml': (-170, 150)}
    assert better(g, pm) == {'oA': 102, 'mlA': 150}
    print('polymarket: ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
        sys.exit()
    sport = sys.argv[1] if len(sys.argv) > 1 else 'nba'
    import novig
    now = datetime.datetime.now(datetime.timezone.utc)
    esp = novig.espn_games(sport, (-1, 2))
    pm = prices(sport, now, esp)
    nv = novig.prices(sport, now, esp)
    n = wins = sides = 0
    for gid, r in pm.items():
        g = nv.get(gid)
        if not g:
            continue
        n += 1
        b = better(g, r)
        sides += sum(1 for k in ('oH', 'oA', 'oO', 'oU', 'mlH', 'mlA') if g.get(k) is not None)
        wins += len(b)
        print(gid, r['slug'], 'L', g.get('L'), 'T', g.get('T'), 'novig', {k: g.get(k) for k in ('oH', 'oA', 'oO', 'oU', 'mlH', 'mlA')}, 'poly better', b)
    print(f'{sport}: {len(pm)} Polymarket games matched, {n} also on Novig; Polymarket pays more on {wins} of {sides} sides')
