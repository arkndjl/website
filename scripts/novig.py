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
            j = odds_snap.get(f'https://site.api.espn.com/apis/site/v2/sports/{odds_snap.ESPN[sport]}/scoreboard?dates={day}{odds_snap.QUERY[sport]}')
        except Exception as ex:
            print(f'{sport} {day}: scoreboard failed ({ex})')
            continue
        for ev in j.get('events', []):
            c = (ev.get('competitions') or [{}])[0]
            comp = {x.get('homeAway'): (x.get('team') or {}) for x in c.get('competitors', [])}
            if 'home' not in comp or 'away' not in comp:
                continue
            nm = {s: {comp[s].get(k) for k in ('location', 'displayName', 'shortDisplayName', 'name', 'abbreviation') if comp[s].get(k)} for s in comp}
            o = odds_snap.dk(c)
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
    print(f'novig {sport}: {len(nv)} games, {len(ids)} matched to ESPN, {len(new)} rows')
    return len(new)


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


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--snap' in args:
        sp = [a for a in args if a in LEAGUE] or ['cfb', 'nfl', 'cbb', 'nba']
        for s in sp:
            snap(s)
    else:
        for s in [a for a in args if a in LEAGUE]:
            for r in compare(s):
                print(json.dumps(r))
