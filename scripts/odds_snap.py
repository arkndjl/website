#!/usr/bin/env python3
"""Dense odds snapshots for the paper book (ARK Betting Plan item 1, Oct 21 2026). Free data only: DraftKings through
ESPN's scoreboard (Noah: "Let's just use DraftKings through ESPN"), one scoreboard request per sport and day a run.

    python3 scripts/odds_snap.py            # every sport in season; the odds-snap workflow runs it every 30 minutes
    python3 scripts/odds_snap.py nba cbb    # some sports

Each run reads the scoreboard for the days around now and appends to scripts/data/odds_dense/<sport>-<yyyy-mm>.jsonl
one row per game whose line, price or our model's number changed since its last row:

    {t, id, k (start), L (home-margin line: home -3 is L = +3), oH, oA, T, oO, oU, mlH, mlA, m, tm}

m and tm are our model's margin and total as they stood at that moment (data/<sport>_games.json, the last build), so the
book never bets on news the line didn't have. A game's first row also carries its names and conferences and ESPN's
opening numbers (open: {...}); a finished game gets one row {t, id, fin: [home, away]}. The close is a game's last row
before its start. Unchanged games write nothing, so a row's numbers hold until the next row.

Cadence: the workflow runs every 30 minutes through the US afternoon and evening (UTC 13-04) and a few times
overnight. The plan asked for 15 minutes near the open and the start; on a private repo that costs about 2,900
Actions minutes a month, twice the 30-minute schedule, so 30 it is until the minutes allow more.
"""
import datetime
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DENSE = os.path.join(HERE, 'data', 'odds_dense')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')
ESPN = {'cfb': 'football/college-football', 'nfl': 'football/nfl', 'cbb': 'basketball/mens-college-basketball', 'nba': 'basketball/nba'}
# the scoreboard's query per sport: FBS only for college football, all of Division I for college basketball
QUERY = {'cfb': '&groups=80&limit=400', 'nfl': '&limit=100', 'cbb': '&groups=50&limit=500', 'nba': '&limit=100'}
# days around today to read: yesterday for finals, then the next lines that are likely posted
DAYS = {'cfb': (-1, 6), 'nfl': (-1, 6), 'cbb': (-1, 2), 'nba': (-1, 2)}
SEASON = {'cfb': (8, 9, 10, 11, 12, 1), 'nfl': (9, 10, 11, 12, 1, 2), 'cbb': (11, 12, 1, 2, 3, 4), 'nba': (10, 11, 12, 1, 2, 3, 4, 5, 6)}
KEYS = ('L', 'oH', 'oA', 'T', 'oO', 'oU', 'mlH', 'mlA', 'm', 'tm', 'src')
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return json.load(urllib.request.urlopen(req, timeout=30))


def num(x):
    if x in (None, ''):
        return None
    s = str(x).strip().lower().lstrip('ou')
    if s in ('even', 'ev'):
        return 100.0
    if s in ('pk', 'pick'):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def dk(c):
    """DraftKings' current and opening numbers from a scoreboard competition, or None"""
    odds = [o for o in c.get('odds') or [] if 'draftkings' in ((o.get('provider') or {}).get('name') or '').lower()]
    if not odds:
        return None
    o = odds[0]
    ps, tt, ml = o.get('pointSpread') or {}, o.get('total') or {}, o.get('moneyline') or {}

    def side(block, s, when, k):
        return num(((block.get(s) or {}).get(when) or {}).get(k))

    def pack(when):
        hl = side(ps, 'home', when, 'line')
        r = {'L': None if hl is None else -hl, 'oH': side(ps, 'home', when, 'odds'), 'oA': side(ps, 'away', when, 'odds'),
             'T': side(tt, 'over', when, 'line'), 'oO': side(tt, 'over', when, 'odds'), 'oU': side(tt, 'under', when, 'odds'),
             'mlH': side(ml, 'home', when, 'odds'), 'mlA': side(ml, 'away', when, 'odds')}
        return r
    cur = pack('close')                  # ESPN's "close" is the current number until the start
    if cur['L'] is None and o.get('spread') is not None:
        cur['L'] = -float(o['spread'])
    if cur['T'] is None and o.get('overUnder') is not None:
        cur['T'] = float(o['overUnder'])
    if cur['L'] is None and cur['T'] is None and cur['mlH'] is None:
        return None
    return cur, pack('open')


def models(sport):
    """{espn id: (model margin, model total, home conf, away conf)} from the sport's last build"""
    out = {}
    try:
        d = json.load(open(os.path.join(ROOT, 'data', f'{sport}_games.json')))
    except (OSError, ValueError):
        return out
    for g in d.get('games', []):
        h, a = g.get('home'), g.get('away')
        conf = ((h or {}).get('conf') if isinstance(h, dict) else None, (a or {}).get('conf') if isinstance(a, dict) else None)
        if sport == 'cfb':
            p = g.get('proj') or {}
            out[str(g['id'])] = (p.get('margin'), p.get('total'), *conf)
        else:
            out[str(g.get('espn') or g['id'])] = (g.get('margin'), g.get('total'), *conf)
    return out


def rows_of(sport):
    rows = []
    if os.path.isdir(DENSE):
        for fn in sorted(os.listdir(DENSE)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                with open(os.path.join(DENSE, fn)) as f:
                    rows += [json.loads(x) for x in f if x.strip()]
    return rows


def snap(sport, now):
    M = models(sport)
    last, done, seen = {}, set(), set()
    for r in rows_of(sport):
        if 'fin' in r:
            done.add(r['id'])
        else:
            last[r['id']] = r
            seen.add(r['id'])
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    lo, hi = DAYS[sport]
    events, fails = {}, 0
    for dd in range(lo, hi + 1):                 # one day a request (the scoreboard refuses date ranges)
        day = (now + datetime.timedelta(days=dd)).strftime('%Y%m%d')
        try:
            j = get(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard?dates={day}{QUERY[sport]}')
        except Exception as e:
            fails += 1
            print(f'{sport} {day}: scoreboard failed ({e})')
            continue
        for ev in j.get('events', []):
            events[str(ev['id'])] = ev
    # Novig's main lines and asks are the book since Oct 27 2026 (Noah: "Replace DK with Novig now"); DraftKings fills
    # games Novig doesn't list. ESPN's (DraftKings') opening numbers stay in a game's first row as `open`.
    try:
        import novig
        nv = novig.prices(sport, now)
    except Exception as e:
        print(f'{sport}: Novig prices failed ({e})')
        nv = {}
    new = []
    for ev in events.values():
        c = (ev.get('competitions') or [{}])[0]
        gid = str(ev['id'])
        st = (c.get('status') or {}).get('type') or {}
        comp = {x.get('homeAway'): x for x in c.get('competitors', [])}
        if st.get('completed'):
            if gid in seen and gid not in done and 'home' in comp and 'away' in comp:
                try:
                    new.append({'t': stamp, 'id': gid, 'fin': [float(comp['home']['score']), float(comp['away']['score'])]})
                except (KeyError, TypeError, ValueError):
                    pass
            continue
        kick = ev.get('date') or c.get('date')
        if not kick or st.get('state') != 'pre':
            continue
        kick = datetime.datetime.fromisoformat(kick.replace('Z', '+00:00')).strftime('%Y-%m-%dT%H:%M:%SZ')
        o = dk(c)
        if not o and gid not in nv:
            continue
        cur, op = o if o else ({}, None)
        src = 'dk'
        if gid in nv:
            cur, src = {k: nv[gid].get(k) for k in ('L', 'oH', 'oA', 'T', 'oO', 'oU', 'mlH', 'mlA')}, 'novig'
        m = M.get(gid) or (None, None, None, None)
        row = {**cur, 'm': None if m[0] is None else round(float(m[0]), 2), 'tm': None if m[1] is None else round(float(m[1]), 2), 'src': src}
        prev = last.get(gid)
        if prev and all(prev.get(k) == row[k] for k in KEYS) and prev.get('k') == kick:
            continue
        r = {'t': stamp, 'id': gid, 'k': kick, **row}
        if gid not in seen:
            tm = {s: ((comp.get(s) or {}).get('team') or {}) for s in ('home', 'away')}
            r.update({'h': tm['home'].get('abbreviation') or tm['home'].get('displayName'),
                      'a': tm['away'].get('abbreviation') or tm['away'].get('displayName'),
                      'hc': m[2], 'ac': m[3], 'neutral': bool(c.get('neutralSite')), 'open': op})
        new.append(r)
    if new:
        os.makedirs(DENSE, exist_ok=True)
        with open(os.path.join(DENSE, f'{sport}-{now:%Y-%m}.jsonl'), 'a') as f:
            for r in new:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    print(f'{sport}: {len(new)} rows ({sum(1 for r in new if "fin" in r)} finals)')
    return len(new)


if __name__ == '__main__':
    now = datetime.datetime.now(datetime.timezone.utc)
    want = [a for a in sys.argv[1:] if a in SPORTS] or [s for s in SPORTS if now.month in SEASON[s]]
    for s in want:
        snap(s, now)
    # Novig's exchange prices beside DraftKings' (scripts/novig.py, Oct 27 2026): a second, low-hold reference, own archive
    try:
        import novig
        for s in want:
            novig.snap(s, now)
        # tennis and Counter-Strike, year-round: Novig is their only free closing line, so the archive starts here
        for s in novig.H2H:
            novig.h2h_snap(s, now)
    except Exception as e:
        print(f'novig: failed ({e})')
    # Counter-Strike: Thunderpick's prices as bo3.gg shows them (scripts/cs2_bo3.py, Oct 28 2026), pre-start only
    try:
        import cs2_bo3
        cs2_bo3.odds_snap(now)
    except Exception as e:
        print(f'thunderpick cs2: failed ({e})')
