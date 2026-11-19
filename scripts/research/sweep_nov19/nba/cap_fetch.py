# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Basketball-Reference team-season salary tables -> scripts/data/nba_salary_hist.json ({season: {bbref id: salary}}).

    python3 cap_fetch.py [from to]      # season end years, default 2012 2026; one page per team-season, 3.5 s apart

A player on several teams' tables in one season keeps his largest figure. Frozen history: rerun only to add a season."""
import html, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..', '..')
OUT = os.path.join(ROOT, 'scripts', 'data', 'nba_salary_hist.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
TEAMS = 'ATL BOS BRK CHO CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHO POR SAC SAS TOR UTA WAS'.split()


def code(tm, y):
    if tm == 'BRK' and y <= 2012: return 'NJN'
    if tm == 'NOP' and y <= 2013: return 'NOH'
    if tm == 'CHO' and y <= 2014: return 'CHA'
    return tm


def page(url):
    for k in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60).read().decode('utf-8', 'replace')
        except Exception as e:
            print(url, e, flush=True); time.sleep(30 * (k + 1))
    return ''


def parse(h):
    m = re.search(r'<table[^>]*id="salaries2".*?</table>', h, re.S)
    out = {}
    if not m: return out
    for row in re.findall(r'<tr.*?</tr>', m.group(0), re.S):
        p = re.search(r'/players/\w/(\w+)\.html', row)
        s = re.search(r'data-stat="salary"[^>]*>([^<]*)<', row)
        if p and s:
            v = re.sub(r'[^\d]', '', html.unescape(s.group(1)))
            if v: out[p.group(1)] = max(out.get(p.group(1), 0), int(v))
    return out


def main():
    a, b = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (2012, 2026)
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    done = set(json.load(open(OUT + '.done'))) if os.path.exists(OUT + '.done') else set()
    for y in range(a, b + 1):
        d = res.setdefault(str(y), {})
        for tm in TEAMS:
            key = f'{code(tm, y)}/{y}'
            if key in done: continue
            got = parse(page(f'https://www.basketball-reference.com/teams/{key}.html'))
            time.sleep(3.5)
            if not got:
                print('no table', key, flush=True); continue
            for pid, v in got.items(): d[pid] = max(d.get(pid, 0), v)
            done.add(key)
        json.dump(res, open(OUT, 'w'), separators=(',', ':'), sort_keys=True)
        json.dump(sorted(done), open(OUT + '.done', 'w'))
        print(y, len(d), flush=True)


if __name__ == '__main__':
    main()
