#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Polymarket US, the site's price source since Nov 15 2026 (Noah: "use Polymarket instead of Novig across the site"):
each side's all-in price after Polymarket's taker fee, at its main lines; Novig only where Polymarket has no game or no
two-sided market, DraftKings (ESPN) after that. Paper only. Stdlib only.

    python3 scripts/polymarket.py nba          # today's priced games, matched to ESPN, against Novig
    python3 scripts/polymarket.py --test

book()          game lines {espn id: {L, oH, oA, T, oO, oU, mlH, mlA, src}} (novig.prices' shape) for every board,
                the picks (games_picks.dk_prices), the odds snapshots and so the closes the picks are judged by
h2h_book()      tennis and Counter-Strike match winners (novig.h2h's shape; nid 'pm:<slug>' in the shared archive)
soccer_prices() 1X2 and the goals line; props() NBA / NFL player props; futures_board.pm_futures() title/conf/div odds

Public, no key: gateway.polymarket.us v2/leagues/{league}/events (listing), v1/events/slug/{slug} (every market of a
game). Only full-game markets count (an event also lists halves, quarters, periods and team totals under the same
types). A market quotes its long side: bestBidQuote / bestAskQuote; the short side is bought at 1 - the long bid. Taker
fee per contract = feeCoefficient x p x (1 - p) at the price paid (0.095 on every sports market, Nov 2026), so a 50/50
side costs about 0.529 all in: -112, against Novig's ~-103 (same line, Nov 15 2026: 2.1 cents a side dearer in the NBA,
NHL, NFL and CBB, about even in CFB and tennis). Polymarket's flag-time price as an edge signal failed its pre-registered
test (scripts/poly_signal.py), so it is a venue only.
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
HOURS = 24 * 7                  # games starting within this many hours get their full market list
MAX_EVENTS = 400
# full-game markets only: an event also lists halves, quarters, periods and team totals under the same SPREAD/TOTAL
# types (sportsMarketType basketball_team_first_half_spread, football_team_points_full_game_total, ...)
FULL = ('_full_game_spread', '_full_game_total', '_full_game_winner')
HOLD = 0.15                     # a main rung's all-in hold at most this (a 50/50 side after the fee holds ~5-6%)
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


def mid(m):
    """the long side's mid chance (no fee)"""
    return (_v(m.get('bestBidQuote')) + _v(m.get('bestAskQuote'))) / 2


def handicap(desc):
    try:
        return float(str(desc).replace('+', ''))
    except ValueError:
        return None


def full_game(m):
    t = m.get('sportsMarketType') or ''
    return t.endswith(FULL) and 'points_full_game' not in t


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
         'k': ev.get('startTime') or e.get('startTime'), 'slug': e['slug'], 'ml': {}, 'sp': {}, 'tot': {}, 'mid': {}}
    for m in ev.get('markets') or []:
        if m.get('closed') or not m.get('active', True) or not full_game(m):
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
                g['mid'][('sp', lg['teamId'], h)] = mid(m)
        elif typ.endswith('TOTAL'):
            try:
                x = float(m.get('line'))
            except (TypeError, ValueError):
                continue
            over = (lg.get('description') or '').lower().startswith('over')
            g['tot'][(over, x)], g['tot'][(not over, x)] = ax
            g['mid'][('tot', x)] = mid(m) if over else 1 - mid(m)
    return g


def games(sport, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ev = listing(sport, now)
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
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


def main(g, th, ta):
    """{L, oH, oA, T, oO, oU, mlH, mlA} at a game's main rungs (the two-sided rung nearest 50/50, all-in hold <= HOLD),
    American after the fee, in novig.prices' shape: L is the home margin (home handicap -L)"""
    px, sp = {}, []
    for (tid, h), c in g['sp'].items():
        if tid != th or (ta, -h) not in g['sp']:
            continue
        ca = g['sp'][(ta, -h)]
        mh = g['mid'].get(('sp', th, h))
        mh = 1 - g['mid'][('sp', ta, -h)] if mh is None and ('sp', ta, -h) in g['mid'] else mh
        if mh is not None and c + ca - 1 <= HOLD:
            sp.append((abs(mh - .5), c + ca, h, c, ca))
    if sp:
        _, _, h, c, ca = min(sp)
        px['L'], px['oH'], px['oA'] = -h, american(c), american(ca)
    tot = [(abs(g['mid'][('tot', x)] - .5), c + g['tot'][(False, x)], x, c, g['tot'][(False, x)])
           for (over, x), c in g['tot'].items() if over and (False, x) in g['tot'] and ('tot', x) in g['mid'] and c + g['tot'][(False, x)] - 1 <= HOLD]
    if tot:
        _, _, x, co, cu = min(tot)
        px['T'], px['oO'], px['oU'] = x, american(co), american(cu)
    if th in g['ml'] and ta in g['ml'] and g['ml'][th] + g['ml'][ta] - 1 <= HOLD:
        px['mlH'], px['mlA'] = american(g['ml'][th]), american(g['ml'][ta])
    return px


def lines(sport, now=None, espn=None):
    """{espn id: main lines} on Polymarket US, after the fee; {} when it can't be read"""
    if sport not in LEAGUE:
        return {}
    try:
        import novig
        pm = games(sport, now)
        ids = match(pm, espn if espn is not None else novig.espn_games(sport))
    except Exception as ex:
        print(f'polymarket {sport}: failed ({ex})')
        return {}
    return {str(gid): main(pm[i], th, ta) for i, (gid, th, ta) in ids.items() if main(pm[i], th, ta)}


_BOOK = {}


def book(sport, now=None, espn=None):
    """the site's price source (Nov 15 2026, Noah: "use Polymarket instead of Novig across the site"): {espn id: {L, oH,
    oA, T, oO, oU, mlH, mlA, src}} at Polymarket US's main lines after its taker fee; Novig's (no fee) only for a game
    Polymarket doesn't list, or a market of it Polymarket has no two-sided rung on; callers keep DraftKings (ESPN)
    for the rest"""
    import novig
    hit = _BOOK.get(sport)
    if espn is None and hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        esp = espn if espn is not None else novig.espn_games(sport)
    except Exception as ex:
        print(f'espn {sport}: failed ({ex})')
        esp = None
    pm = lines(sport, now, esp) if esp is not None else {}
    try:
        nv = novig.prices(sport, now, esp) if esp is not None else {}
    except Exception as ex:
        print(f'novig {sport}: failed ({ex})')
        nv = {}
    out = {}
    for gid in set(pm) | set(nv):
        p, n = pm.get(gid) or {}, nv.get(gid) or {}
        r = {'src': 'poly' if p else 'novig'}
        for keys in (('L', 'oH', 'oA'), ('T', 'oO', 'oU'), ('mlH', 'mlA')):
            q = p if all(p.get(k) is not None for k in keys) else n if all(n.get(k) is not None for k in keys) else {}
            r.update({k: q.get(k) for k in keys if q})
            if q is n and n and p:
                r.setdefault('fill', []).append(keys[0])
        out[gid] = r
    k = sum(1 for r in out.values() if r['src'] == 'poly')
    print(f'{sport}: {k} games on Polymarket, {len(out) - k} on Novig only')
    if espn is None:
        _BOOK[sport] = (time.time(), out)
    return out


# head-to-head sports (Nov 15 2026): tennis and Counter-Strike match winners, in novig.h2h's shape so the same
# h2h_find / h2h_price / h2h_snap work on either venue's list; nid 'pm:<slug>' keeps the two apart in the archive
H2H = {'tennis': ('atp', 'wta'), 'cs2': ('cs2',)}
H2H_TYPE = ('tennis_match_winner', 'esports_match_winner')


def h2h(sport, now=None):
    """[{nid, lg, k, a, b, p (no-vig chance of b), h (hold after the fee), oa, ob (all-in, American), vol, ml, src}]
    for the sport's pregame match winners; b is the market's long side"""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = []
    for lg in H2H[sport]:
        off = 0
        while off < 1000:
            j = get(f'/v2/leagues/{lg}/events?limit=50&offset={off}')
            ev = (j or {}).get('events') or []
            for e in ev:
                try:
                    t = datetime.datetime.fromisoformat((e.get('startTime') or '').replace('Z', '+00:00'))
                except ValueError:
                    continue
                if e.get('live') or e.get('ended') or not now < t < now + datetime.timedelta(hours=HOURS):
                    continue
                tm = {x['id']: x.get('name') for x in e.get('teams') or []}
                for m in e.get('markets') or []:
                    if (m.get('sportsMarketType') or '') not in H2H_TYPE or m.get('closed'):
                        continue
                    sides = m.get('marketSides') or []
                    lgs = [x for x in sides if x.get('long')]
                    shs = [x for x in sides if not x.get('long')]
                    if not lgs or not shs:
                        continue
                    b = tm.get(lgs[0].get('teamId')) or lgs[0].get('description')
                    a = tm.get(shs[0].get('teamId')) or shs[0].get('description')
                    g = {'nid': 'pm:' + e['slug'], 'lg': lg.upper(), 'ml': m.get('slug'), 'k': t.strftime('%Y-%m-%dT%H:%M:%SZ'),
                         'a': a, 'b': b, 'p': None, 'h': None, 'oa': None, 'ob': None, 'vol': round(float(m.get('volume') or 0)), 'src': 'poly'}
                    ax = asks(m)
                    if ax and ax[0] + ax[1] - 1 <= HOLD:
                        g.update(p=round(mid(m), 4), h=round(ax[0] + ax[1] - 1, 4), ob=american(ax[0]), oa=american(ax[1]))
                    out.append(g)
                    break
            if len(ev) < 50:
                break
            off += 50
    return out


def h2h_book(sport, now=None):
    """Polymarket's match winners first, then Novig's for a match Polymarket doesn't price (two-sided)"""
    import novig
    try:
        pm = [g for g in h2h(sport, now) if g['p'] is not None]
    except Exception as ex:
        print(f'polymarket {sport}: failed ({ex})')
        pm = []
    try:
        nv = novig.h2h(sport)
    except Exception as ex:
        print(f'novig {sport}: failed ({ex})')
        nv = []
    team = sport == 'cs2'
    rest = [dict(g, src='novig') for g in nv if g.get('p') is not None and not novig.h2h_find(pm, g['a'], g['b'], team=team)[0]]
    print(f'{sport}: {len(pm)} matches on Polymarket, {len(rest)} on Novig only')
    return pm + rest


# soccer (Nov 15 2026): ESPN league -> Polymarket US leagues; '_intl' is every national-team listing
SOCCER = {'eng.1': ('epl',), 'esp.1': ('lal',), 'ger.1': ('bun',), 'ita.1': ('sea',), 'usa.1': ('mls',),
          'uefa.champions': ('ucl',), '_intl': ('uefa', 'fwc')}


def soccer_prices(matches):
    """matches [(espn id, ESPN league or '_intl', home name, away name, day)] -> {espn id: {h, d, a, ou}} in
    novig.soccer_prices' shape: h/d/a each a Yes bought at its ask plus the fee, ou the main goals line"""
    import novig
    want = {}
    for gid, lg, hn, an, day in matches:
        for pl in SOCCER.get(lg, ()):
            want.setdefault(pl, []).append((gid, names.team_key(hn), names.team_key(an), day))
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {}
    for pl, ms in want.items():
        off, ev = 0, []
        while off < 500:
            j = get(f'/v2/leagues/{pl}/events?limit=50&offset={off}')
            got = (j or {}).get('events') or []
            ev += [e for e in got if not e.get('live') and not e.get('ended')]
            if len(got) < 50:
                break
            off += 50
        for e in ev:
            try:
                t = datetime.datetime.fromisoformat((e.get('startTime') or '').replace('Z', '+00:00'))
            except ValueError:
                continue
            if t < now:
                continue
            tm = e.get('teams') or []
            if len(tm) != 2:
                continue
            ks = {x['id']: names.team_key(x.get('name') or '') for x in tm}
            day = t.date()
            hit = []
            for gid, h, a, d in ms:
                if abs((datetime.date.fromisoformat(d) - day).days) > 1:
                    continue
                th = [i for i, k in ks.items() if k == h or novig.loose(h, {k})]
                ta = [i for i, k in ks.items() if k == a or novig.loose(a, {k})]
                if len(th) == 1 and len(ta) == 1 and th != ta:
                    hit.append((gid, th[0], ta[0]))
            if len(hit) != 1:
                continue
            gid, th, ta = hit[0]
            j = get(f"/v1/events/slug/{e['slug']}")
            full = (j or {}).get('event') or j or {}
            px, tots = {}, []
            for m in full.get('markets') or []:
                typ = m.get('sportsMarketType') or ''
                if m.get('closed'):
                    continue
                ax = asks(m)
                if not ax:
                    continue
                if typ == 'soccer_team_full_time_winner':
                    lgs = [x for x in m.get('marketSides') or [] if x.get('long')]
                    tid = lgs[0].get('teamId') if lgs else None
                    px['h' if tid == th else 'a' if tid == ta else 'd'] = american(ax[0])
                elif typ == 'soccer_team_full_game_total' and ax[0] + ax[1] - 1 <= HOLD:
                    try:
                        tots.append((abs(mid(m) - .5), float(m.get('line'))))
                    except (TypeError, ValueError):
                        pass
            if tots:
                px['ou'] = min(tots)[1]
            if all(k in px for k in ('h', 'd', 'a')):
                out[gid] = px
    return out


# player props (Nov 15 2026): Polymarket lists each as "at least N" (Yes/No), so a rung at N is over/under N - 0.5
NBA_PROPS = {'basketball_player_points': 'pts', 'basketball_player_rebounds': 'reb', 'basketball_player_assists': 'ast',
             'basketball_player_points_rebounds_assists': 'pra', 'basketball_player_threes': 'fg3'}
NFL_PROPS = {'football_player_passing_yards': 'py', 'football_player_passing_touchdowns': 'ptd',
             'football_player_passing_completions': 'pc', 'football_player_passing_attempts': 'pa',
             'football_player_interceptions_thrown': 'pint', 'football_player_rushing_yards': 'ry',
             'football_player_rushing_attempts': 'ca', 'football_player_receiving_yards': 'wy',
             'football_player_receptions': 'rc', 'football_player_scrimmage_yards': 'rwy'}


def prop_name(q):
    """'Will Anthony Davis record at least 10 points in ...?' -> 'Anthony Davis'"""
    q = (q or '').strip()
    if not q.startswith('Will ') or ' record ' not in q:
        return None
    return q[5:].split(' record ')[0].strip()


def props(sport='nba', types=None, espn=None, now=None):
    """{espn game id: {(player name, stat): [line, over, under]}} at the main rung (nearest 50/50, all-in hold <= HOLD),
    American after the fee, in novig.props' shape; {} when Polymarket can't be read"""
    types = types or (NBA_PROPS if sport == 'nba' else NFL_PROPS)
    try:
        import novig
        now = now or datetime.datetime.now(datetime.timezone.utc)
        ev = listing(sport, now)
        stub = [{'teams': {t['id']: [x for x in (t.get('name'), t.get('alias'), t.get('safeName'), t.get('abbreviation')) if x]
                           for t in e.get('teams') or []}, 'k': e.get('startTime')} for e in ev]
        ids = match(stub, espn if espn is not None else novig.espn_games(sport, (-1, 2)))
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            full = dict(zip(ids, ex.map(lambda i: get(f"/v1/events/slug/{ev[i]['slug']}"), ids)))
    except Exception as ex:
        print(f'polymarket {sport} props: failed ({ex})')
        return {}
    rungs = {}
    for i, j in full.items():
        gid = str(ids[i][0])
        for m in ((j or {}).get('event') or j or {}).get('markets') or []:
            st = types.get(m.get('sportsMarketType') or '')
            if not st or m.get('closed'):
                continue
            ax, name = asks(m), prop_name(m.get('question'))
            try:
                x = float(m.get('line'))
            except (TypeError, ValueError):
                continue
            if not ax or not name or ax[0] + ax[1] - 1 > HOLD:
                continue
            x = x - .5 if x == int(x) else x
            rungs.setdefault((gid, name, st), []).append((abs(mid(m) - .5), x, ax[0], ax[1]))
    out = {}
    for (gid, name, st), v in rungs.items():
        _, x, co, cu = min(v)
        out.setdefault(gid, {})[(name, st)] = [x, float(american(co)), float(american(cu))]
    return out


GROUPS = (('L', 'oH', 'oA'), ('T', 'oO', 'oU'), ('mlH', 'mlA'))


def merge(bk, dk):
    """one game's lines from the book (polymarket.book row) market by market, DraftKings' (odds_snap.dk shape) for a
    market the book has no two-sided price on -> (lines, {'L'|'T'|'mlH': source})"""
    out, src = {}, {}
    for keys in GROUPS:
        for row, s in ((bk or {}, None), (dk or {}, 'dk')):
            if all(row.get(k) is not None for k in keys):
                out.update({k: row[k] for k in keys})
                src[keys[0]] = s or ('novig' if keys[0] in (row.get('fill') or ()) else row.get('src', 'poly'))
                break
    return out, src


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
