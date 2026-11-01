"""The NBA's official injury reports, 2019-20 on, as status history for the game model's play chances
(scripts/nba_games.py --fit). One report per game day at 5 PM ET, plus noon on days with an earlier tip; each game
takes the last report before it. Needs pdftotext (poppler-utils). Research only: the daily build reads ESPN's report.

    python3 scripts/nba_inj_hist.py 2020 2026     # seasons from..to; writes scripts/.cache/nba/inj_hist.json
"""
import datetime as dt, json, os, re, subprocess, sys, time, urllib.request
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_espn as E

CACHE = os.path.join(E.ROOT, 'scripts', '.cache', 'nba', 'injrep')
OUT = os.path.join(E.ROOT, 'scripts', '.cache', 'nba', 'inj_hist.json')
ET = ZoneInfo('America/New_York')
URL = 'https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf'
STATUS = ('Out', 'Doubtful', 'Questionable', 'Probable', 'Available')
LINE = re.compile(r'([A-Z][^,\d]{1,40}?, [^\s].{0,40}?)\s{2,}(' + '|'.join(STATUS) + r')\b')
MATCH = re.compile(r'\b([A-Z]{2,3})@([A-Z]{2,3})\b')


def fetch(d, hour):
    """the report's text, or '' when there was none at that hour"""
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'{d}_{hour:02d}.txt')
    if os.path.exists(fn):
        return open(fn).read()
    h12 = hour - 12 if hour > 12 else hour
    ap = 'PM' if hour >= 12 else 'AM'
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
                time.sleep(2 * (i + 1))
            except Exception:
                time.sleep(2 * (i + 1))
    open(fn, 'w').write('')
    return ''


def parse(txt):
    """{(away, home): {name: status}}; names come as 'Last, First' and go out as 'First Last'"""
    out, cur = {}, None
    for ln in txt.splitlines():
        m = MATCH.search(ln)
        if m:
            cur = (E.team(m.group(1)), E.team(m.group(2)))
        if not cur:
            continue
        for nm, st in LINE.findall(ln):
            last, first = [x.strip() for x in nm.split(',', 1)]
            last = re.split(r'\s{2,}', last)[-1]
            out.setdefault(cur, {})[f'{first} {last}'] = st
    return out


ABBR = {'NOP': 'NO', 'NYK': 'NY', 'GSW': 'GS', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH', 'PHO': 'PHX', 'BRK': 'BKN'}


def build(lo, hi):
    hist = {}
    for S in range(lo, hi + 1):
        gs = [g for g in E.games(S) if g['final']]
        byday = {}
        for g in gs:
            # ET with DST: a flat UTC-4 put winter tips an hour late, so 4:30-5:30 pm tips took the 5 PM report
            tip = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')).astimezone(ET)
            byday.setdefault(tip.date().isoformat(), []).append((g, tip.hour + tip.minute / 60))
        jobs = []
        for d, lst in byday.items():
            jobs.append((d, 17))
            if any(h < 17.5 for _, h in lst):
                jobs.append((d, 12))
        with ThreadPoolExecutor(6) as ex:
            texts = dict(zip(jobs, ex.map(lambda j: fetch(*j), jobs)))
        n = 0
        for d, lst in byday.items():
            reps = {h: parse(texts.get((d, h), '')) for h in (12, 17)}
            for g, hr in lst:
                rep = reps[12] if hr < 17.5 and reps[12] else reps[17]
                key = (g['a'], g['h'])
                found = {k: v for (a, h), v in ((tuple(ABBR.get(x, x) for x in k2), v2) for k2, v2 in rep.items()) for k in [(a, h)] if (E.team(a), E.team(h)) == key}
                if found:
                    hist[g['id']] = list(found.values())[0]; n += 1
        print(S, len(gs), 'games', n, 'with a report', flush=True)
    E.save(OUT, hist)


if __name__ == '__main__':
    build(int(sys.argv[1]), int(sys.argv[2]))
