# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Price history of CLOSED Polymarket (global) outright events: awards, titles, playoff fields.

    python3 scripts/poly_hist.py                 # every event in EVENTS not yet archived
    python3 scripts/poly_hist.py nba:mvp:2026    # one event (sport:kind:season), refetched
    python3 scripts/poly_hist.py --list          # what is archived

One file an event: scripts/data/poly_hist/<sport>_<kind>_<season>.json.gz
  {slug, title, sport, kind, season, start, closed, markets: [{name, won, vol, start, closed, h: [[unix, price], ...]}]}
h = the Yes token's daily price (clob prices-history, fidelity 1440). interval=max can return only the last months of
a long market, so the days before its first point are walked in 14-day windows (the longest the API takes); a
market with no point at all never traded.

Readers: load(sport, kind, season) and asof(event, day) -> {name: price} (last point at or before `day` 00:00 UTC,
markets not yet listed or already closed left out; prices are raw Yes prices, not renormalised).

Research and benchmarks only: closed events of finished seasons, never an open market, never a sport page.
Hosts: gamma-api.polymarket.com (event -> markets, tokens, resolution) and clob.polymarket.com (history). Read only.
Fetches go through curl (the hosts refuse Python's urllib from some runners)."""
import datetime as dt, gzip, json, os, subprocess, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DIR = os.path.join(ROOT, 'scripts', 'data', 'poly_hist')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
PAUSE = .35
WIN = 14 * 86400

# (sport, kind, season end year) -> gamma event slug. Closed events only.
EVENTS = {
    ('nba', 'mvp', 2025): 'nba-mvp-2024-25', ('nba', 'mvp', 2026): 'nba-mvp-694',
    ('nba', 'dpoy', 2025): 'nba-defensive-player-of-the-year', ('nba', 'dpoy', 2026): 'nba-2025-26-defensive-player-of-the-year',
    ('nba', 'roy', 2025): 'nba-rookie-of-the-year', ('nba', 'roy', 2026): 'nba-rookie-of-the-year-873',
    ('nba', 'mip', 2025): 'nba-most-improved-player', ('nba', 'mip', 2026): 'nba-2025-26-most-improved-player',
    ('nba', 'title', 2025): 'nba-champion-2024-2025', ('nba', 'title', 2026): '2026-nba-champion',
    ('nba', 'playoffs', 2025): 'which-teams-will-make-the-nba-playoffs', ('nba', 'playoffs', 2026): 'which-teams-will-make-the-nba-playoffs-138',
    ('nhl', 'hart', 2025): 'hart-trophy-winner', ('nhl', 'hart', 2026): 'nhl-2025-26-hart-memorial-trophy',
    ('nhl', 'norris', 2026): 'nhl-2025-26-james-norris-memorial-trophy', ('nhl', 'vezina', 2026): 'nhl-2025-26-vezina-trophy',
    ('nhl', 'calder', 2026): 'nhl-2025-26-calder-memorial-trophy',
    ('nhl', 'title', 2025): 'stanley-cup-winner', ('nhl', 'title', 2026): '2026-nhl-stanley-cup-champion',
    ('nhl', 'playoffs', 2026): 'which-teams-will-make-the-nhl-playoffs',
    ('nfl', 'mvp', 2024): 'nfl-mvp-1', ('nfl', 'mvp', 2025): 'nfl-mvp-355',
    ('nfl', 'opoy', 2024): 'nfl-offensive-player-of-the-year', ('nfl', 'opoy', 2025): 'nfl-offensive-player-of-the-year-996',
    ('nfl', 'oroy', 2024): 'nfl-offensive-rookie-of-the-year', ('nfl', 'oroy', 2025): 'nfl-offensive-rookie-of-the-year-267',
    ('nfl', 'droy', 2024): 'nfl-defensive-rookie-of-the-year', ('nfl', 'droy', 2025): 'nfl-defensive-rookie-of-the-year-345',
    ('nfl', 'dpoy', 2024): 'nfl-defensive-player-of-the-year', ('nfl', 'dpoy', 2025): 'nfl-defensive-player-of-the-year-612',
    ('nfl', 'title', 2025): 'super-bowl-champion-2026-731',
    ('nfl', 'playoffs', 2024): 'which-nfl-teams-will-make-the-playoffs', ('nfl', 'playoffs', 2025): 'which-nfl-teams-will-make-the-playoffs-167',
    ('cfb', 'heisman', 2024): 'heisman-winner', ('cfb', 'heisman', 2025): 'heisman-trophy-winner',
    ('cfb', 'title', 2024): 'college-football-champion-2025', ('cfb', 'title', 2025): 'college-football-champion-2026-684',
    ('cfb', 'playoff', 2024): 'which-teams-will-make-the-college-football-playoff',
    ('cfb', 'playoff', 2025): 'college-football-playoff-which-teams-make-it',
    ('cbb', 'wooden', 2025): 'wooden-award-winner', ('cbb', 'naismith', 2026): '2025-2026-naismith-college-player-of-the-year',
    ('cbb', 'title', 2025): '2025-ncaa-tournament-winner', ('cbb', 'title', 2026): '2026-ncaa-tournament-winner',
}


def curl(url, tries=4):
    for a in range(tries):
        try:
            r = subprocess.run(['curl', '-s', '--compressed', '--max-time', '60', '-A', UA, url], capture_output=True, timeout=90)
            time.sleep(PAUSE)
            if r.stdout: return json.loads(r.stdout)
        except Exception as e:
            print(url[:100], e, flush=True)
        time.sleep(3 * (a + 1))
    return None


def ts(s):
    """gamma time string -> unix seconds (None when absent)"""
    if not s: return None
    s = s.replace(' ', 'T').replace('+00', '').rstrip('Z')[:19]
    try: return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp())
    except ValueError: return None


def history(token, start, end):
    """daily [[unix, price]] of one token from its listing to its close"""
    d = curl(f'https://clob.polymarket.com/prices-history?market={token}&interval=max&fidelity=1440') or {}
    h = [(int(x['t']), float(x['p'])) for x in d.get('history') or []]
    if not h: return []                                           # never traded
    first = h[0][0]
    lo = start
    while lo is not None and lo < first - 86400:                 # days the max interval left out
        hi = min(lo + WIN, first)
        d = curl(f'https://clob.polymarket.com/prices-history?market={token}&startTs={lo}&endTs={hi}&fidelity=1440') or {}
        h += [(int(x['t']), float(x['p'])) for x in d.get('history') or []]
        lo = hi
    seen, out = set(), []
    for t, p in sorted(h):
        day = t // 86400
        if day in seen: continue
        seen.add(day); out.append([t, round(p, 4)])
    return out


def path(key):
    return os.path.join(DIR, '%s_%s_%d.json.gz' % key)


def fetch(key):
    slug = EVENTS[key]
    d = curl('https://gamma-api.polymarket.com/events?slug=' + slug)
    if not d: print('no event', slug); return None
    e = d[0]
    if not e.get('closed'): print('still open, skipped', slug); return None
    out = {'slug': slug, 'title': e.get('title'), 'sport': key[0], 'kind': key[1], 'season': key[2],
           'start': ts(e.get('startDate')), 'closed': ts(e.get('closedTime')), 'vol': round(float(e.get('volume') or 0)), 'markets': []}
    for m in e.get('markets', []):
        name = m.get('groupItemTitle') or m.get('question') or ''
        try:
            tok = json.loads(m.get('clobTokenIds') or '[]')
            px = json.loads(m.get('outcomePrices') or '[]')
        except ValueError: continue
        vol = float(m.get('volumeNum') or 0)
        if not tok or not name: continue
        won = bool(px) and float(px[0]) > .5
        h = history(tok[0], ts(m.get('startDate')), ts(m.get('closedTime')))
        out['markets'].append({'name': name, 'won': won, 'vol': round(vol), 'start': ts(m.get('startDate')),
                               'closed': ts(m.get('closedTime')), 'h': h})
    os.makedirs(DIR, exist_ok=True)
    with gzip.open(path(key), 'wt') as f: json.dump(out, f, separators=(',', ':'))
    k = sum(1 for m in out['markets'] if m['h'])
    print(key, slug, 'markets', len(out['markets']), 'with history', k,
          'winner', [m['name'] for m in out['markets'] if m['won']][:3], flush=True)
    return out


def load(sport, kind, season):
    p = path((sport, kind, season))
    return json.load(gzip.open(p)) if os.path.exists(p) else None


def asof(ev, day):
    """{market name: Yes price} at the last point at or before `day` 00:00 UTC ('YYYY-MM-DD'); a market is left out
    before its first point and from its close on"""
    t0 = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())
    out = {}
    for m in ev['markets']:
        if m.get('closed') and m['closed'] <= t0: continue
        p = None
        for t, v in m['h']:
            if t > t0 + 300: break
            p = v
        if p is not None: out[m['name']] = p
    return out


def liquid(px, winners=1):
    """the history is book midpoints (about .50 on an empty book): prices are usable only when the Yes prices sum to
    within 25% of the number of winners"""
    return bool(px) and abs(sum(px.values()) - winners) <= .25 * winners


def main(argv):
    if '--list' in argv:
        for k in sorted(EVENTS):
            e = load(*k)
            print(k, 'missing' if not e else (len(e['markets']), sum(len(m['h']) for m in e['markets'])))
        return
    want = [tuple(a.split(':')[:2]) + (int(a.split(':')[2]),) for a in argv if a.count(':') == 2]
    for k in sorted(EVENTS):
        if want and k not in want: continue
        if not want and os.path.exists(path(k)): continue
        fetch(k)


if __name__ == '__main__':
    main(sys.argv[1:])
