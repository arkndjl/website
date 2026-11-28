# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Season calendar for every sport (Nov 28 2026): one place that says which season, phase, draft year, recruit class and
post day each sport is in on a given date. Read by scripts/season_roll.py (the rollover runner), data_health.py,
rank_moves.py, scripts/season.mjs (Node) and the ARKLOG calendar tab.

The calendar is data/seasons/<sport>.json:
  events   league dates for the calendar tab: [{d, to?, k, t, est?, src?}]  (k: pre, reg, reg_end, post, champ, draft,
           portal, sign, deadline, major, other; est = 1 when the league has not published the date yet)
  keys     step values by date: {"phase": [["2026-08-01", "preseason"], ...], "season": [["2026-08-01", 2026], ...]}.
           A key's value on a day is the last entry dated on or before it (New York date).
  steps    site transitions the runner carries out on their date: archive, bump, run, dispatch, alert (season_roll.py)
  bumps    hard-coded constants that follow a key: {key, file, rx, off, auto}

    python3 scripts/season.py              # today's state for every sport
    python3 scripts/season.py --on 2027-02-01
    python3 scripts/season.py --get cfb class [--on DATE] [--add 2]   # one value (workflows: Y=$(...))
    python3 scripts/season.py --test
"""
import datetime as dt
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'data', 'seasons')
PHASES = ('preseason', 'regular', 'postseason', 'offseason')
WD = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
# boards that post with a sport's calendar (rank_moves.POST names)
ALIAS = {'soccerm': 'soccer', 'soccerb': 'soccer', 'soccerp': 'soccer', 'tennisp': 'tennis', 'nbaproj': 'nba',
         'hockey': 'nhl', 'esea': 'cs2', '1nt': 'cs2'}
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
except Exception:          # pragma: no cover
    ET = dt.timezone(dt.timedelta(hours=-5))

_CAL = None


def load(refresh=False):
    global _CAL
    if _CAL is None or refresh:
        _CAL = {}
        for f in sorted(glob.glob(os.path.join(DIR, '*.json'))):
            d = json.load(open(f))
            _CAL[d['sport']] = d
    return _CAL


def today():
    return dt.datetime.now(dt.timezone.utc).astimezone(ET).date()


def _day(on):
    if on is None:
        return today()
    if isinstance(on, dt.datetime):
        return on.astimezone(ET).date() if on.tzinfo else on.date()
    if isinstance(on, str):
        return dt.date.fromisoformat(on[:10])
    return on


def sport_of(sport):
    return ALIAS.get(sport, sport)


def entries(sport, key):
    c = load().get(sport_of(sport))
    return (c or {}).get('keys', {}).get(key) or []


def value(sport, key, on=None, default=None):
    """the key's value on the day `on` (date, ISO string or datetime; default today in New York)"""
    d = _day(on).isoformat()
    v = default
    for a, x in entries(sport, key):
        if a <= d:
            v = x
        else:
            break
    return v


def changes(sport, key):
    """[(date, old, new)] for every change of the key"""
    out, prev = [], None
    for a, x in entries(sport, key):
        if prev is not None and x != prev:
            out.append((dt.date.fromisoformat(a), prev, x))
        prev = x
    return out


def next_change(sport, key, on=None):
    d = _day(on)
    for a, old, new in changes(sport, key):
        if a > d:
            return a, old, new
    return None


def phase(sport, on=None):
    return value(sport, 'phase', on, 'regular')


def season(sport, on=None):
    return value(sport, 'season', on)


def post_wd(sport, on=None, default=None):
    """the weekly post weekday (Monday = 0) on a day, or default when the calendar has no post key"""
    v = value(sport, 'post', on)
    return WD[v] if v in WD else default


def last_post(sport, day, default_wd=None, days=7):
    """the most recent post day before `day` under the post day in force on each day (so the first post after a
    schedule change still counts from the last post under the old one); None when the sport has no post day"""
    day = _day(day)
    for back in range(1, 15):
        d = day - dt.timedelta(days=back)
        wd = post_wd(sport, d, default_wd)
        if wd is None:
            return None
        if d.weekday() == wd:
            return d
    return day - dt.timedelta(days=days)


def state(on=None):
    """{sport: {phase, season, every key's value, next: [date, key, new]}}"""
    d = _day(on)
    out = {}
    for s, c in load().items():
        st = {k: value(s, k, d) for k in c.get('keys', {})}
        nxt = []
        for k in c.get('keys', {}):
            n = next_change(s, k, d)
            if n:
                nxt.append([n[0].isoformat(), k, n[2]])
        st['next'] = sorted(nxt)[:3]
        out[s] = st
    return out


def events(on=None, ahead=None):
    """every league event and site step as calendar rows, sorted by date"""
    d = _day(on)
    rows = []
    for s, c in load().items():
        for e in c.get('events', []):
            rows.append(dict(e, sport=s, kind='league'))
        for st in c.get('steps', []):
            rows.append({'d': st['on'], 'k': 'site', 't': st.get('t') or st['id'], 'sport': s, 'kind': 'site',
                         'id': st['id']})
    rows.sort(key=lambda r: (r['d'], r['sport']))
    if ahead is not None:
        hi = (d + dt.timedelta(days=ahead)).isoformat()
        rows = [r for r in rows if d.isoformat() <= (r.get('to') or r['d']) and r['d'] <= hi]
    return rows


def check():
    """structural checks on the calendar files: sorted keys, known phases, ISO dates, steps with ids"""
    errs = []
    for s, c in load(refresh=True).items():
        for k, es in c.get('keys', {}).items():
            ds = [a for a, _ in es]
            if ds != sorted(ds):
                errs.append(f'{s}.{k}: dates out of order')
            for a in ds:
                try:
                    dt.date.fromisoformat(a)
                except ValueError:
                    errs.append(f'{s}.{k}: bad date {a}')
            if k == 'phase':
                errs += [f'{s}.phase: unknown {x}' for _, x in es if x not in PHASES]
            if k == 'post':
                errs += [f'{s}.post: unknown {x}' for _, x in es if x not in WD]
        ids = [st.get('id') for st in c.get('steps', [])]
        if len(ids) != len(set(ids)) or None in ids:
            errs.append(f'{s}: step ids missing or repeated')
        for st in c.get('steps', []):
            try:
                dt.date.fromisoformat(st['on'])
            except (KeyError, ValueError):
                errs.append(f'{s}.{st.get("id")}: bad on')
            if st.get('do') == 'bump' and not any(b['key'] == st.get('key') for b in c.get('bumps', [])):
                errs.append(f'{s}.{st["id"]}: bump step with no bumps for key {st.get("key")}')
        for e in c.get('events', []):
            for f in ('d', 'to'):
                if e.get(f):
                    try:
                        dt.date.fromisoformat(e[f])
                    except ValueError:
                        errs.append(f'{s} event {e.get("t")}: bad {f}')
    return errs


def _test():
    errs = check()
    assert not errs, errs
    c = load()
    assert {'cfb', 'cbb', 'nfl', 'nba', 'nhl', 'soccer', 'tennis', 'cs2'} <= set(c), sorted(c)
    # CFB: Wednesday posts through Dec 6, Monday from Dec 7 (Noah, Nov 28 2026), the Dec 7 post counts from Dec 2
    assert post_wd('cfb', '2026-12-02') == 2 and post_wd('cfb', '2026-12-07') == 0
    assert last_post('cfb', '2026-12-07') == dt.date(2026, 12, 2)
    assert last_post('cfb', '2026-12-08') == dt.date(2026, 12, 7)
    assert last_post('cfb', '2026-12-05') == dt.date(2026, 12, 2)
    assert phase('cfb', '2026-12-10') == 'postseason' and phase('cfb', '2027-03-01') == 'offseason'
    assert season('cbb', '2026-11-28') == 2027 and season('nba', '2026-11-28') == 2027
    assert season('cfb', '2026-11-28') == 2026 and value('cfb', 'draft', '2026-11-28') == 2027
    assert value('cfb', 'draft', '2027-05-03') == 2028
    assert value('cfb', 'class', '2026-11-28') == 2027 and value('cfb', 'class', '2027-01-02') == 2028
    assert post_wd('hockey', '2026-11-28') == 5 and post_wd('soccerp', '2026-11-28') == 0
    # every sport has a phase today, and the rows sort
    st = state('2026-11-28')
    assert all(v['phase'] in PHASES for v in st.values()), st
    ev = events('2026-11-28', ahead=60)
    assert ev and [r['d'] for r in ev] == sorted(r['d'] for r in ev)
    print(f'season ok: {len(c)} sports, {sum(len(x.get("events", [])) for x in c.values())} events, '
          f'{sum(len(x.get("steps", [])) for x in c.values())} steps')


if __name__ == '__main__':
    if '--test' in sys.argv:
        _test()
        sys.exit(0)
    on = sys.argv[sys.argv.index('--on') + 1] if '--on' in sys.argv else None
    if '--get' in sys.argv:
        i = sys.argv.index('--get')
        v = value(sys.argv[i + 1], sys.argv[i + 2], on)
        if v is None:
            sys.exit(f'no {sys.argv[i + 2]} for {sys.argv[i + 1]}')
        if '--add' in sys.argv:
            v = int(v) + int(sys.argv[sys.argv.index('--add') + 1])
        print(v)
        sys.exit(0)
    errs = check()
    for e in errs:
        print('calendar:', e)
    for s, v in state(on).items():
        print(f"{s:7} {v.get('phase', ''):10} season {v.get('season')}  " +
              ' '.join(f'{k}={v[k]}' for k in v if k not in ('phase', 'season', 'next')) +
              (f"  next {v['next'][0]}" if v['next'] else ''))
    sys.exit(1 if errs else 0)
