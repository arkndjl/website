#!/usr/bin/env python3
"""Novig exchange prices as a second free odds source next to DraftKings (Oct 27 2026).

Novig publishes an unauthenticated, cacheable catalog (https://docs.novig.com, `/v3/public/catalog/*`, no key, no
account): every listed event and market with the best bid on each outcome. Pregame game markets carry no taker fee
(fee.charged WHEN_LIVE), so the cost of a bet is the bid-ask spread alone. A side's ask is 1 minus the other side's bid.

Per game this module keeps
    ml   home/away best bids on the moneyline -> pH (mid, no-vig) and hold (askH + askA - 1)
    L    fair home margin from the whole spread ladder: each two-sided rung (home -h) gives L = -h + s x z(mid)
    T    fair total from the totals ladder the same way
    Lm/Tm the busiest rung (most volume) and its hold, the line a bettor would see as "the" number
and the market ids, so the daily public trades file (data.novig.com, every fill with a timestamp) can later give the
last traded price before the start. Settled markets drop out of the public catalog, so a game must be seen pregame to
be joined to the trades file: the history starts with the first snapshot.

    python3 scripts/novig.py nfl            # print today's Novig games next to DraftKings (ESPN)
    python3 scripts/novig.py --snap         # append changed games to scripts/data/odds_novig/<sport>-<yyyy-mm>.jsonl
"""
import datetime
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names  # noqa: E402

API = 'https://api.novig.com/v3/public/catalog'
OUT = os.path.join(HERE, 'data', 'odds_novig')
LADDER = os.path.join(HERE, 'data', 'odds_novig_ladder')   # every two-sided rung at its asks (Oct 28 2026: the alt-line test)
LAD_PTS, LAD_HOLD = 6.0, 0.15      # rungs kept: within 6 points of the main line, hold 15% or less (off-centre rungs run 6-15%)
LEAGUE = {'cfb': 'NCAAF', 'nfl': 'NFL', 'cbb': 'NCAAB', 'nba': 'NBA', 'nhl': 'NHL'}
# margin and total sd that turn a rung's mid chance into points (the game models' own: clv_fit / rank_sd scale)
SD = {'cfb': (16.0, 14.0), 'nfl': (13.5, 10.0), 'cbb': (11.0, 16.0), 'nba': (12.0, 14.5), 'nhl': (2.3, 2.3)}
UA = 'arkndjl.net arkboard (odds research)'
KEYS = ('pH', 'hML', 'L', 'T', 'Lm', 'hL', 'Tm', 'hT')


def get(path, **q):
    q = {k: v for k, v in q.items() if v is not None}
    url = f'{API}/{path}?{urllib.parse.urlencode(q)}'
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))


def pages(path, **q):
    items, after = [], None
    while True:
        d = get(path, limit=5000 if path == 'markets' else 500, after=after, **q)
        items += d.get('items') or []
        after = d.get('next')
        if not after:
            return items
        time.sleep(.25)


def bid(o):
    b = o.get('bid') or {}
    try:
        return float(b['price'])
    except (KeyError, TypeError, ValueError):
        return None


def zinv(p):
    """inverse standard normal (Acklam), enough for points off a mid chance"""
    a = (-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924)
    b = (-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857)
    c = (-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878)
    d = (0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742)
    if p < .02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - .02425:
        return -zinv(1 - p)
    q = p - .5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def two_sided(m):
    """(mid chance of outcome 0, hold) when both outcomes have a bid, else None"""
    oc = m.get('outcomes') or []
    if len(oc) != 2:
        return None
    b0, b1 = bid(oc[0]), bid(oc[1])
    if b0 is None or b1 is None or b0 <= 0 or b1 <= 0:
        return None
    ask0, ask1 = 1 - b1, 1 - b0
    return (b0 + ask0) / 2, ask0 + ask1 - 1, ask0, ask1


def handicap(name):
    """'IND -1.5' -> ('IND', -1.5)"""
    t, _, h = name.rpartition(' ')
    try:
        return t, float(h)
    except ValueError:
        return name, None


def fair(points, s):
    """points [(x, p, hold, vol, id)] with p = P(result > x): the fair median, tight rungs near 50/50 weighted most"""
    num = den = 0.0
    for x, p, hold, *_ in points:
        if not .08 < p < .92 or hold > .12:
            continue
        w = p * (1 - p) / max(hold, .005)
        num += w * (x + s * zinv(p))
        den += w
    return None if den == 0 else round(num / den * 4) / 4      # quarter points: finer is book noise, and every change is a row


def games(sport):
    """{novig event id: game} for the league's pregame events"""
    lg = LEAGUE[sport]
    ev = {e['eventId']: e for e in pages('events', league=lg, status='OPEN_PREGAME')}
    mk = pages('markets', league=lg, marketType='MONEY,SPREAD,TOTAL', eventStatus='OPEN_PREGAME')
    sm, st = SD[sport]
    out = {}
    for eid, e in ev.items():
        away, _, home = (e.get('description') or '').partition(' @ ')
        if not home:
            continue
        out[eid] = {'nid': eid, 'k': datetime.datetime.fromtimestamp(e['startsTs'] / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'h': home, 'a': away, 'ids': {}, '_s': [], '_t': [], 'vol': 0, 'px': {}}
    for m in mk:
        g = out.get(m.get('eventId'))
        if not g:
            continue
        ts = two_sided(m)
        vol = float(m.get('volume') or 0)
        g['vol'] += vol
        typ = m.get('marketType')
        if typ == 'MONEY':
            g['ids']['ml'] = m['marketId']
            if ts:
                # outcome 0 is the home side (checked against DraftKings, Oct 27 2026)
                g['pH'], g['hML'] = round(ts[0], 4), round(ts[1], 4)
                g['px']['mlH'], g['px']['mlA'] = american(ts[2]), american(ts[3])
        elif typ == 'SPREAD' and ts:
            _, h = handicap(m['outcomes'][0]['name'])
            if h is None:
                continue
            # outcome 0 is the home side at handicap h: it covers when the home margin > -h
            g['_s'].append((-h, ts[0], ts[1], vol, m['marketId'], ts[2], ts[3]))
        elif typ == 'TOTAL' and ts:
            try:
                x = float(m.get('strike'))
            except (TypeError, ValueError):
                continue
            over = (m['outcomes'][0].get('name') or '').lower().startswith('over')
            ao, au = (ts[2], ts[3]) if over else (ts[3], ts[2])
            g['_t'].append((x, ts[0] if over else 1 - ts[0], ts[1], vol, m['marketId'], ao, au))
    for g in out.values():
        s, t = g.pop('_s'), g.pop('_t')
        g['L'], g['T'] = fair(s, sm), fair(t, st)
        for pts, lk, hk, idk in ((s, 'Lm', 'hL', 'sp'), (t, 'Tm', 'hT', 'tot')):
            if pts:
                top = max(pts, key=lambda r: (r[3], -abs(r[1] - .5)))
                if top[3] == 0:
                    top = min(pts, key=lambda r: abs(r[1] - .5))
                g[lk], g[hk], g['ids'][idk] = top[0], round(top[2], 4), top[4]
        # the main line a bettor takes: the two-sided rung nearest 50/50 (busiest on a tie), priced at its asks
        for pts, lk, ak, bk in ((s, 'L', 'oH', 'oA'), (t, 'T', 'oO', 'oU')):
            ok = [r for r in pts if r[2] <= .12]
            if ok:
                r = min(ok, key=lambda r: (round(abs(r[1] - .5), 3), -r[3]))
                g['px'][lk], g['px'][ak], g['px'][bk] = r[0], american(r[5]), american(r[6])
        g['vol'] = round(g['vol'])
        # the ladder (Oct 28 2026, Noah asked to tailor picks to Novig): every rung near the main line at its asks, so
        # scripts/novig_ladder_test.py can price the best rung for a pick against the main one once picks grade
        g['lad'] = {}
        for pts, lk in ((s, 'L'), (t, 'T')):
            mid = g['px'].get(lk)
            if mid is None:
                continue
            g['lad'][lk] = sorted([r[0], round(r[5], 2), round(r[6], 2)] for r in pts
                                  if r[2] <= LAD_HOLD and abs(r[0] - mid) <= LAD_PTS)
    return out


def american(p):
    """a contract price (chance) as American odds; Novig charges no fee before the start"""
    p = min(max(float(p), .01), .99)
    return round(-100 * p / (1 - p)) if p >= .5 else round(100 * (1 - p) / p)


def prices(sport, now=None, espn=None):
    """{espn id: {L, oH, oA, T, oO, oU, mlH, mlA}} at Novig's main lines and asks, the shape odds_snap.dk() gives (the
    price source since Oct 27 2026, Noah: "Replace DK with Novig now"); {} when the catalog can't be read"""
    try:
        nv = games(sport)
    except Exception as ex:
        print(f'novig {sport}: catalog failed ({ex})')
        return {}
    ids = match(nv, espn if espn is not None else espn_games(sport))
    return {ids[n]: dict(g['px']) for n, g in nv.items() if n in ids and g['px']}


def espn_games(sport, days=(-1, 6)):
    """ESPN scoreboard events {id: (home names, away names, start, DraftKings now)} for matching and comparison"""
    import odds_snap
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {}
    for dd in range(days[0], days[1] + 1):
        day = (now + datetime.timedelta(days=dd)).strftime('%Y%m%d')
        try:
            path, query = {**odds_snap.ESPN, 'nhl': 'hockey/nhl'}[sport], {**odds_snap.QUERY, 'nhl': '&limit=100'}[sport]
            j = odds_snap.get(f'https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day}{query}')
        except Exception as ex:
            print(f'{sport} {day}: scoreboard failed ({ex})')
            continue
        for ev in j.get('events', []):
            c = (ev.get('competitions') or [{}])[0]
            comp = {x.get('homeAway'): (x.get('team') or {}) for x in c.get('competitors', [])}
            if 'home' not in comp or 'away' not in comp:
                continue
            nm = {s: {comp[s].get(k) for k in ('location', 'displayName', 'shortDisplayName', 'name', 'abbreviation') if comp[s].get(k)} for s in comp}
            o = odds_snap.dk(c) if sport in odds_snap.ESPN else None
            out[str(ev['id'])] = (nm['home'], nm['away'], ev.get('date'), o[0] if o else None)
    return out


def match(nv, espn):
    """{novig event id: espn id} by both team names (names.team_key) and a start within 3 hours"""
    def keys(ns):
        return {names.team_key(n) for n in ns}
    idx = [(gid, keys(h), keys(a), datetime.datetime.fromisoformat(k.replace('Z', '+00:00')) if k else None) for gid, (h, a, k, _) in espn.items()]
    out = {}
    for nid, g in nv.items():
        kh, ka = names.team_key(g['h']), names.team_key(g['a'])
        t = datetime.datetime.fromisoformat(g['k'].replace('Z', '+00:00'))
        near = [(gid, hk, ak) for gid, hk, ak, et in idx if et is None or abs((et - t).total_seconds()) < 3 * 3600]
        hit = [gid for gid, hk, ak in near if kh in hk and ka in ak]
        if not hit:     # one side exact, the other a loose fit (Appalachian State / App State, Southern Mississippi / Southern Miss)
            hit = [gid for gid, hk, ak in near if (kh in hk and loose(ka, ak)) or (ka in ak and loose(kh, hk))]
        if len(hit) == 1:
            out[nid] = hit[0]
    return out


def loose(k, ks):
    return any(k[:4] == x[:4] or k in x or x in k for x in ks if len(x) >= 3)


def snap(sport, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        nv = games(sport)
    except Exception as ex:
        print(f'novig {sport}: catalog failed ({ex})')
        return 0
    if not nv:
        print(f'novig {sport}: no pregame events')
        return 0
    espn = espn_games(sport)
    ids = match(nv, espn)
    last = {}
    if os.path.isdir(OUT):
        for fn in sorted(os.listdir(OUT)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                for x in open(os.path.join(OUT, fn)):
                    if x.strip():
                        r = json.loads(x)
                        last[r['nid']] = r
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    new = []
    for nid, g in nv.items():
        row = {k: g.get(k) for k in KEYS}
        prev = last.get(nid)
        if prev and prev.get('k') == g['k'] and all(prev.get(k) == row[k] for k in ('L', 'T', 'Lm', 'Tm')) and \
                (prev.get('pH') is None) == (row['pH'] is None) and abs((prev.get('pH') or 0) - (row['pH'] or 0)) < .01:
            continue        # a row when a line or the moneyline (a point of chance) moves; holds ride along
        r = {'t': stamp, 'nid': nid, 'id': ids.get(nid), 'k': g['k'], **row, 'vol': g['vol']}
        if not prev:
            r.update({'h': g['h'], 'a': g['a'], 'ids': g['ids']})
        new.append(r)
    if new:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f'{sport}-{now:%Y-%m}.jsonl'), 'a') as f:
            for r in new:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    nl = snap_ladder(sport, nv, ids, stamp, now)
    print(f'novig {sport}: {len(nv)} games, {len(ids)} matched to ESPN, {len(new)} rows, {nl} ladders')
    return len(new)


def snap_ladder(sport, nv, ids, stamp, now):
    """scripts/data/odds_novig_ladder/<sport>-<ym>.jsonl: a game's ladder {L: [[line, ask home, ask away]], T: [[total,
    ask over, ask under]]} (asks as chances, to the cent) whenever it changes; L is the home margin, as everywhere"""
    last = {}
    if os.path.isdir(LADDER):
        for fn in sorted(os.listdir(LADDER)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                for x in open(os.path.join(LADDER, fn)):
                    if x.strip():
                        r = json.loads(x)
                        last[r['nid']] = r['lad']
    rows = [{'t': stamp, 'nid': nid, 'id': ids.get(nid), 'k': g['k'], 'lad': g['lad']} for nid, g in nv.items()
            if g.get('lad') and last.get(nid) != g['lad']]
    if rows:
        os.makedirs(LADDER, exist_ok=True)
        with open(os.path.join(LADDER, f'{sport}-{now:%Y-%m}.jsonl'), 'a') as f:
            for r in rows:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    return len(rows)


def no_vig(a, b):
    def p(o):
        return None if o is None else (100 / (o + 100) if o > 0 else -o / (-o + 100))
    pa, pb = p(a), p(b)
    if pa is None or pb is None:
        return None, None
    return pa / (pa + pb), pa + pb - 1


def compare(sport):
    nv = games(sport)
    espn = espn_games(sport)
    ids = match(nv, espn)
    rows = []
    for nid, g in sorted(nv.items(), key=lambda kv: kv[1]['k']):
        gid = ids.get(nid)
        dk = (espn.get(gid) or (None,) * 4)[3] if gid else None
        dpH, dh = no_vig(dk.get('mlH'), dk.get('mlA')) if dk else (None, None)
        _, dhs = no_vig(dk.get('oH'), dk.get('oA')) if dk else (None, None)
        rows.append({'game': f"{g['a']} @ {g['h']}", 'k': g['k'], 'espn': gid, 'nv_pH': g.get('pH'), 'dk_pH': None if dpH is None else round(dpH, 4),
                     'nv_hML': g.get('hML'), 'dk_hML': None if dh is None else round(dh, 4), 'nv_L': g.get('L'), 'nv_Lm': g.get('Lm'), 'nv_hL': g.get('hL'),
                     'dk_L': dk and dk.get('L'), 'dk_hL': None if dhs is None else round(dhs, 4), 'nv_T': g.get('T'), 'dk_T': dk and dk.get('T'), 'vol': g['vol']})
    return rows


SOCCER = {'eng.1': 'EPL', 'esp.1': 'La Liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1', 'usa.1': 'MLS',
          'mex.1': 'Liga MX', 'uefa.champions': 'Champions League', 'uefa.europa': 'Europa League'}


def soccer_prices(matches):
    """matches [(espn id, ESPN league, home name, away name, day)] -> {espn id: {h, d, a, ou}} at Novig's asks: h/d/a the
    three-way prices (each a Yes/No market, Yes bought at 1 - No's bid), ou the main goals line (the shape soccer_data's dk)"""
    want = {}
    for gid, lg, hn, an, day in matches:
        if lg in SOCCER:
            want.setdefault(SOCCER[lg], []).append((gid, names.team_key(hn), names.team_key(an), day))
    out = {}
    for lg, ms in want.items():
        try:
            ev = {e['eventId']: e for e in pages('events', league=lg, status='OPEN_PREGAME')}
            mk = pages('markets', league=lg, marketType='MONEYLINE_3_WAY_WIN,MONEYLINE_3_WAY_DRAW,TOTAL', eventStatus='OPEN_PREGAME')
        except Exception as ex:
            print(f'novig {lg}: catalog failed ({ex})')
            continue
        by = {}
        for m in mk:
            by.setdefault(m.get('eventId'), []).append(m)
        for eid, e in ev.items():
            away, _, home = (e.get('description') or '').partition(' @ ')
            day = datetime.datetime.fromtimestamp(e['startsTs'] / 1000, datetime.timezone.utc).date().isoformat()
            kh, ka = names.team_key(home), names.team_key(away)
            hit = [gid for gid, h, a, d in ms if abs((datetime.date.fromisoformat(d) - datetime.date.fromisoformat(day)).days) <= 1
                   and (h == kh or loose(h, {kh})) and (a == ka or loose(a, {ka}))]
            if len(hit) != 1:
                continue
            px, tots = {}, []
            for m in by.get(eid, []):
                oc = m.get('outcomes') or []
                if m['marketType'] in ('MONEYLINE_3_WAY_WIN', 'MONEYLINE_3_WAY_DRAW') and len(oc) == 2:
                    no = next((bid(o) for o in oc if (o.get('name') or '').lower() == 'no'), None)
                    if no is None:
                        continue
                    who = (m.get('description') or '').split(' MONEYLINE')[0].strip()
                    k = 'd' if m['marketType'] == 'MONEYLINE_3_WAY_DRAW' else 'h' if names.team_key(who) and loose(names.team_key(who), {kh}) else 'a'
                    px[k] = american(1 - no)
                elif m['marketType'] == 'TOTAL':
                    ts = two_sided(m)
                    if ts and ts[1] <= .12:
                        tots.append((abs(ts[0] - .5), float(m['strike'])))
            if tots:
                px['ou'] = min(tots)[1]
            if all(k in px for k in ('h', 'd', 'a')):
                out[hit[0]] = px
    return out


PROPS = {'POINTS': 'pts', 'REBOUNDS': 'reb', 'ASSISTS': 'ast', 'POINTS_REBOUNDS_ASSISTS': 'pra', 'THREE_POINTERS_MADE': 'fg3'}
# NFL player props (Oct 29 2026): the stat keys of scripts/props_snap.py's NFL rows and nfl_fantasy's stat lines
NFL_PROPS = {'PASSING_YARDS': 'py', 'PASSING_TOUCHDOWNS': 'ptd', 'PASSING_COMPLETIONS': 'pc', 'PASSING_ATTEMPTS': 'pa',
             'INTERCEPTIONS_THROWN': 'pint', 'RUSHING_YARDS': 'ry', 'RUSHING_ATTEMPTS': 'ca', 'RECEIVING_YARDS': 'wy',
             'RECEPTIONS': 'rc', 'RUSHING_AND_RECEIVING_YARDS': 'rwy', 'PASSING_AND_RUSHING_YARDS': 'pry'}


def props(sport='nba', types=PROPS, espn=None):
    """{espn game id: {(player name, stat): [line, over, under]}} at Novig's main prop rung (the two-sided strike
    nearest 50/50, hold <= .12) and its asks; {} when the catalog can't be read"""
    try:
        nv = games(sport)
        ids = match(nv, espn if espn is not None else espn_games(sport))
        mk = pages('markets', league=LEAGUE[sport], marketType=','.join(types), eventStatus='OPEN_PREGAME')
    except Exception as ex:
        print(f'novig {sport} props: catalog failed ({ex})')
        return {}
    rungs = {}
    for m in mk:
        gid, s, ts = ids.get(m.get('eventId')), types.get(m.get('marketType')), two_sided(m)
        if not gid or not s or not ts or ts[1] > .12:
            continue
        try:
            x = float(m['strike'])
        except (KeyError, TypeError, ValueError):
            continue
        over = (m['outcomes'][0].get('name') or '').lower().startswith('over')
        po, ao, au = (ts[0], ts[2], ts[3]) if over else (1 - ts[0], ts[3], ts[2])
        name = (m.get('description') or '').rsplit(' ', 2)[0]      # 'Jayson Tatum 29.5 POINTS'
        rungs.setdefault((gid, name, s), []).append((abs(po - .5), x, ao, au))
    out = {}
    for (gid, name, s), v in rungs.items():
        _, x, ao, au = min(v)
        out.setdefault(gid, {})[(name, s)] = [x, float(american(ao)), float(american(au))]
    return out


def nba_props(espn=None):
    return props('nba', PROPS, espn)


DERIV = 'SPREAD_1H,TOTAL_1H,MONEY_1H,TEAM_TOTAL'


def derivs(sport='nfl', espn=None):
    """{espn game id: {key: [line, price, price]}} for the game's derivative markets at Novig's main rung (nearest 50/50,
    hold <= .12) and asks (Oct 29 2026): '1hs' first-half home-margin line (home -3 is +3) [L, home, away], '1ht'
    first-half total [T, over, under], '1hml' [None, home, away], 'ttH' / 'ttA' team totals [T, over, under]"""
    try:
        espn = espn if espn is not None else espn_games(sport)
        nv = games(sport)
        ids = match(nv, espn)
        mk = pages('markets', league=LEAGUE[sport], marketType=DERIV, eventStatus='OPEN_PREGAME')
    except Exception as ex:
        print(f'novig {sport} derivatives: catalog failed ({ex})')
        return {}
    keys = {gid: tuple({names.team_key(n) for n in espn[gid][i]} for i in (0, 1)) for gid in espn}
    rungs = {}
    for m in mk:
        gid, ts = ids.get(m.get('eventId')), two_sided(m)
        if not gid or not ts or ts[1] > .12 or gid not in keys:
            continue
        hk, ak = keys[gid]
        typ, oc = m.get('marketType'), m['outcomes']
        o0 = oc[0].get('name') or ''
        if typ in ('SPREAD_1H', 'MONEY_1H'):
            t0, h = handicap(o0) if typ == 'SPREAD_1H' else (o0, 0.0)
            if h is None:
                continue
            k0 = names.team_key(t0)
            home0 = k0 in hk or (k0 not in ak and loose(k0, hk))
            ph, ah, aa = (ts[0], ts[2], ts[3]) if home0 else (1 - ts[0], ts[3], ts[2])
            if typ == 'SPREAD_1H':
                rungs.setdefault((gid, '1hs'), []).append((abs(ph - .5), -h if home0 else h, ah, aa))
            else:
                rungs.setdefault((gid, '1hml'), []).append((0, None, ah, aa))
            continue
        try:
            x = float(m['strike'])
        except (KeyError, TypeError, ValueError):
            continue
        over = o0.lower().startswith('over')
        po, ao, au = (ts[0], ts[2], ts[3]) if over else (1 - ts[0], ts[3], ts[2])
        if typ == 'TOTAL_1H':
            rungs.setdefault((gid, '1ht'), []).append((abs(po - .5), x, ao, au))
        elif typ == 'TEAM_TOTAL':
            k = names.team_key((m.get('description') or '').rsplit(' ', 2)[0])     # 'Buffalo Bills 29.5 TEAM_TOTAL'
            side = 'ttH' if k in hk else 'ttA' if k in ak else None
            if side:
                rungs.setdefault((gid, side), []).append((abs(po - .5), x, ao, au))
    out = {}
    for (gid, k), v in rungs.items():
        _, x, a, b = min(v, key=lambda r: r[0])
        out.setdefault(gid, {})[k] = [x, float(american(a)), float(american(b))]
    return out


# head-to-head sports with no ESPN game feed of their own here: two players or teams, a moneyline, no home side
# (Oct 27 2026). Tennis lists every ATP and WTA match it prices; Counter-Strike has no fixed league name, so any open
# event whose sport or league reads as CS is taken (Novig listed CS2 but carried no events on Oct 27 2026).
H2H = {'tennis': ('ATP', 'WTA'), 'cs2': None}


def _cs(e):
    s = f"{e.get('sport') or ''} {e.get('league') or ''}".upper()
    return 'COUNTER' in s or 'CS2' in s or 'CSGO' in s or 'CS:GO' in s


def _full(part, short):
    """'Federico Cina Round of 16', 'F. Cina' -> 'Federico Cina': the description carries the round after the name"""
    last = (short or '').split('. ')[-1].strip()
    i = part.rfind(last) if last else -1
    return part[:i + len(last)].strip() if i >= 0 else part.strip()


def h2h(sport):
    """[{nid, lg, k, a, b, p (no-vig chance of b, the side after '@'), h (hold), oa, ob (asks, American), vol, ml}]
    for the sport's pregame moneylines; outcome 0 is the side after '@', as for every Novig game"""
    lgs = H2H[sport]
    ev = []
    if lgs:
        for lg in lgs:
            ev += pages('events', league=lg, status='OPEN_PREGAME')
    else:
        ev = [e for e in pages('events', status='OPEN_PREGAME') if _cs(e)]
    out = []
    for lg in sorted({e['league'] for e in ev}):
        evs = {e['eventId']: e for e in ev if e['league'] == lg}
        for m in pages('markets', league=lg, marketType='MONEY', eventStatus='OPEN_PREGAME'):
            e = evs.get(m.get('eventId'))
            oc = m.get('outcomes') or []
            if not e or len(oc) != 2:
                continue
            away, _, home = (e.get('description') or '').partition(' @ ')
            if not home:
                continue
            g = {'nid': e['eventId'], 'lg': lg, 'ml': m['marketId'],
                 'k': datetime.datetime.fromtimestamp(e['startsTs'] / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'a': _full(away, oc[1].get('name')), 'b': _full(home, oc[0].get('name')),
                 'p': None, 'h': None, 'oa': None, 'ob': None, 'vol': round(float(m.get('volume') or 0))}
            ts = two_sided(m)
            if ts:
                g.update(p=round(ts[0], 4), h=round(ts[1], 4), ob=american(ts[2]), oa=american(ts[3]))
            out.append(g)
    return out


def h2h_find(games_, a, b, lg=None, team=False):
    """the Novig game between a and b (either order) -> (game, flipped); flipped = a is Novig's 'b' side"""
    same = names.same_team if team else names.same
    for g in games_:
        if lg and g['lg'] != lg:
            continue
        if same(a, g['a']) and same(b, g['b']):
            return g, False
        if same(a, g['b']) and same(b, g['a']):
            return g, True
    return None, False


def h2h_price(games_, a, b, lg=None, team=False):
    """{p: no-vig chance of a, h: hold, o: [ask a, ask b] American, vol} at Novig, or None (unlisted or one-sided)"""
    g, fl = h2h_find(games_, a, b, lg, team)
    if not g or g['p'] is None:
        return None
    pa, oa, ob = (g['p'], g['ob'], g['oa']) if fl else (round(1 - g['p'], 4), g['oa'], g['ob'])
    return {'p': pa, 'h': g['h'], 'o': [oa, ob], 'vol': g['vol']}


def h2h_snap(sport, now=None):
    """append a row per game when its no-vig chance moves a point (or it first appears) to
    scripts/data/odds_novig/<sport>-<yyyy-mm>.jsonl: the archive closing lines for tennis and CS2 picks must come from"""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        gs = h2h(sport)
    except Exception as ex:
        print(f'novig {sport}: catalog failed ({ex})')
        return 0
    if not gs:
        print(f'novig {sport}: no pregame events')
        return 0
    last = {}
    if os.path.isdir(OUT):
        for fn in sorted(os.listdir(OUT)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                for x in open(os.path.join(OUT, fn)):
                    if x.strip():
                        r = json.loads(x)
                        last[r['nid']] = r
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    new = []
    for g in gs:
        prev = last.get(g['nid'])
        if prev and prev.get('k') == g['k'] and (prev.get('p') is None) == (g['p'] is None) and \
                abs((prev.get('p') or 0) - (g['p'] or 0)) < .01:
            continue
        r = {'t': stamp, 'nid': g['nid'], 'k': g['k'], 'p': g['p'], 'h': g['h'], 'vol': g['vol']}
        if not prev:
            r.update({'lg': g['lg'], 'a': g['a'], 'b': g['b'], 'ml': g['ml']})
        new.append(r)
    if new:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f'{sport}-{now:%Y-%m}.jsonl'), 'a') as f:
            for r in new:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    print(f'novig {sport}: {len(gs)} matches, {sum(g["p"] is not None for g in gs)} two-sided, {len(new)} rows')
    return len(new)


def write_live(sport):
    """scripts/data/novig_live/<sport>.json for builds that read it as a file (the CFB board, in Node)"""
    px = prices(sport)
    d = os.path.join(HERE, 'data', 'novig_live')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f'{sport}.json'), 'w') as f:
        json.dump({'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'games': px}, f, separators=(',', ':'))
    print(f'novig {sport}: {len(px)} games priced -> novig_live')


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--live' in args:
        for s in [a for a in args if a in LEAGUE]:
            write_live(s)
    elif '--snap' in args:
        sp = [a for a in args if a in LEAGUE or a in H2H] or ['cfb', 'nfl', 'cbb', 'nba']
        for s in sp:
            h2h_snap(s) if s in H2H else snap(s)
    elif '--h2h' in args:
        for s in [a for a in args if a in H2H]:
            for g in h2h(s):
                print(json.dumps(g))
    else:
        for s in [a for a in args if a in LEAGUE]:
            for r in compare(s):
                print(json.dumps(r))
