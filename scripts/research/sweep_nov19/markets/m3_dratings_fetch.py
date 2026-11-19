# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M3 fetch: DRatings completed-prediction pages (one request a second, robots.txt allows all).
    python3 m3_dratings_fetch.py <nhl-hockey|nba-basketball> <first page> <out.jsonl>
Keeps the completed table's rows dated Oct 1 2021..Sep 30 2026; rows of the 2026-27 season are dropped before
anything but their date is read. Stops at the first page whose rows are all older than Oct 2021."""
import html, json, re, subprocess, sys, time
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
LO, HI = '2021-10-01', '2026-10-01'


def page(lg, n):
    u = f'https://www.dratings.com/predictor/{lg}-predictions/completed/{n}'
    for a in range(3):
        r = subprocess.run(['curl', '-sL', '--compressed', '--max-time', '60', '-A', UA, u], capture_output=True, timeout=90)
        time.sleep(1.05)
        if r.stdout and b'<tbody' in r.stdout: return r.stdout.decode('utf-8', 'replace')
        time.sleep(5)
    return ''


def rows(h):
    i = h.find('Completed Games')
    if i < 0: return []
    b = re.search(r'<tbody.*?</tbody>', h[i:], re.S)
    out = []
    for tr in re.findall(r'<tr>(.*?)</tr>', b.group(0) if b else '', re.S):
        d = re.search(r'datetime="([^"]+)"', tr)
        if not d: continue
        day = d.group(1)
        if not (LO <= day[:10] < HI): out.append({'t': day, 'skip': 1}); continue
        td = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        tm = [html.unescape(x) for x in re.findall(r'<a href="/teams/[^"]+">([^<]+)</a>', td[1])]
        pc = re.findall(r'([\d.]+)%', td[2])
        txt = lambda s: [x.strip() for x in re.sub(r'<br\s*/?>', '\n', re.sub(r'<(?!br)[^>]+>', '', s)).split('\n') if x.strip()]
        sc = None
        for c in td[3:]:
            v = txt(c)
            if len(v) == 2 and all(re.fullmatch(r'\d+', x) for x in v) and 'sportsbook' not in c: sc = v
        ml = txt(td[3])
        if len(tm) == 2 and len(pc) == 2 and sc:
            out.append({'t': day, 'a': tm[0], 'h': tm[1], 'pa': float(pc[0]) / 100, 'ph': float(pc[1]) / 100,
                        'as': int(sc[0]), 'hs': int(sc[1]), 'ml': ml[:2]})
    return out


if __name__ == '__main__':
    lg, n, fn = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    with open(fn, 'a') as f:
        while n < 900:
            R = rows(page(lg, n))
            keep = [r for r in R if not r.get('skip')]
            for r in keep: f.write(json.dumps(r) + '\n')
            f.flush()
            if n % 25 == 0: print(lg, n, len(R), len(keep), R[0]['t'] if R else None, flush=True)
            if not R or (not keep and R[-1]['t'][:10] < LO): break
            n += 1
