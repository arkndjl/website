# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The NBA's official injury reports, 2019-20 on, as status history for the game model's play chances. Each game
takes the latest report out at least half an hour before its tip: 5 PM ET for evening games, an earlier one (11 AM to
2 PM) for matinees. Needs pdftotext (poppler-utils).

    python3 scripts/nba_inj_hist.py 2020 2026     # seasons from..to; writes scripts/data/nba_inj_hist.json.gz

The finished seasons are committed (scripts/data/nba_inj_hist.json.gz), so the fit (nba_games.py --fit, also the
scheduled refit) and the daily build walk the same statuses; the daily build reads the season in progress with
reports() (its PDFs cached in scripts/.cache/nba/injrep). Until Nov 4 2026 the history sat in a local cache only: a fit
run without it had no statuses at all, and the daily build walked every past game with none.
"""
import datetime as dt, gzip, json, os, re, subprocess, sys, time, urllib.request
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_espn as E

CACHE = os.path.join(E.ROOT, 'scripts', '.cache', 'nba', 'injrep')
OUT = os.path.join(E.ROOT, 'scripts', 'data', 'nba_inj_hist.json.gz')
ET = ZoneInfo('America/New_York')
URL = 'https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf'
STATUS = ('Out', 'Doubtful', 'Questionable', 'Probable', 'Available')
LINE = re.compile(r'([A-Z][^,\d]{1,40}?, [^\s].{0,40}?)\s{2,}(' + '|'.join(STATUS) + r')\b')
MATCH = re.compile(r'\b([A-Z]{2,3})@([A-Z]{2,3})\b')
GDATE = re.compile(r'\s*(\d{2})/(\d{2})/(\d{4})\s')


def fetch(d, hour):
    """the report's text, or '' when there was none at that hour"""
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'{d}_{hour:02d}.txt')
    if os.path.exists(fn):
        return open(fn).read()
    h12 = hour - 12 if hour > 12 else hour
    ap = 'PM' if hour >= 12 else 'AM'
    missing = True
    for t in (f'{h12:02d}{ap}', f'{h12:02d}_00{ap}'):
        for i in range(3):
            try:
                req = urllib.request.Request(URL.format(d=d, t=t), headers={'User-Agent': E.UA})
                pdf = urllib.request.urlopen(req, timeout=30).read()
                txt = subprocess.run(['pdftotext', '-layout', '-', '-'], input=pdf, capture_output=True).stdout.decode('utf-8', 'replace')
                open(fn, 'w').write(txt)
                return txt
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break
                missing = False
                time.sleep(2 * (i + 1))
            except Exception:
                missing = False
                time.sleep(2 * (i + 1))
    if missing:                 # no report at that hour; a failed pull is tried again next time
        open(fn, 'w').write('')
    return ''


def parse(txt, day=None):
    """{(away, home): {name: status}}; names come as 'Last, First' and go out as 'First Last'. With day (a date), only
    the games the report dates that day: a report also lists the next day's games, and one from late the night before
    lists today's under its own date"""
    out, cur, gd = {}, None, None
    for ln in txt.splitlines():
        d = GDATE.match(ln)
        if d:
            gd = dt.date(int(d.group(3)), int(d.group(1)), int(d.group(2)))
        m = MATCH.search(ln)
        if m:
            cur = (E.team(m.group(1)), E.team(m.group(2))) if day is None or gd == day else None
        if not cur:
            continue
        for nm, st in LINE.findall(ln):
            last, first = [x.strip() for x in nm.split(',', 1)]
            last = re.split(r'\s{2,}', last)[-1]
            out.setdefault(cur, {})[f'{first} {last}'] = st
    return out


ABBR = {'NOP': 'NO', 'NYK': 'NY', 'GSW': 'GS', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH', 'PHO': 'PHX', 'BRK': 'BKN'}


# early tips (before 5:30 pm ET) take the latest of these reports out by the tip. 2019-20 and 2020-21 had no noon
# report (1, 5 and 8 PM; the bubble 11 AM, 2 and 5 PM): falling back to the 5 PM report gave ~180 matinee games
# statuses published after their tip
EARLY = (11, 12, 13, 14)


def before(reps, hr):
    """the latest report out at least half an hour before a tip at hr (ET hours; 5 PM for tips from 5:30 pm, as
    before); {} when none was"""
    ok = [h for h in sorted(reps) if reps[h] and h + 0.5 <= hr]
    return reps[ok[-1]] if ok else {}


def reports(gs):
    """{game id: {name: status}} for finished games (rows with id, tip (UTC), a, h), each from the latest report out
    before its tip (before())"""
    byday = {}
    for g in gs:
        # ET with DST: a flat UTC-4 put winter tips an hour late, so 4:30-5:30 pm tips took the 5 PM report
        tip = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')).astimezone(ET)
        byday.setdefault(tip.date().isoformat(), []).append((g, tip.hour + tip.minute / 60))
    jobs = []
    for d, lst in byday.items():
        jobs.append((d, 17))
        if any(h < 17.5 for _, h in lst):
            jobs += [(d, h) for h in EARLY]
    with ThreadPoolExecutor(6) as ex:
        texts = dict(zip(jobs, ex.map(lambda j: fetch(*j), jobs)))
    out = {}
    for d, lst in byday.items():
        # the day's games only: a report also lists tomorrow's, and 2020-21's two-game series met on back-to-back days
        reps = {h: parse(texts.get((d, h), ''), dt.date.fromisoformat(d)) for h in (17,) + EARLY}
        for g, hr in lst:
            rep = before(reps, hr)
            key = (g['a'], g['h'])
            found = {k: v for (a, h), v in ((tuple(ABBR.get(x, x) for x in k2), v2) for k2, v2 in rep.items()) for k in [(a, h)] if (E.team(a), E.team(h)) == key}
            if found:
                out[g['id']] = list(found.values())[0]
    return out


def load():
    """the committed history: {game id: {name: status}}"""
    try:
        with gzip.open(OUT, 'rt') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def build(lo, hi):
    hist = load()
    for S in range(lo, hi + 1):
        gs = [g for g in E.games(S) if g['final']]
        ids = {g['id'] for g in gs}
        hist = {k: v for k, v in hist.items() if k not in ids}
        rep = reports(gs)
        hist.update(rep)
        print(S, len(gs), 'games', len(rep), 'with a report', flush=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump(dict(sorted(hist.items())), f, separators=(',', ':'))


if __name__ == '__main__':
    build(int(sys.argv[1]), int(sys.argv[2]))
