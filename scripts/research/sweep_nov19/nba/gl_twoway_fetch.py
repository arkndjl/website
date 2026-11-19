# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Basketball-Reference season transaction pages -> two-way signings and conversions (lead 6c).

    python3 gl_twoway_fetch.py OUT.json     # seasons 2018-2025, one page each, 4 s apart

Rows: [season, date, kind (sign | convert | waive), bbref id, name]."""
import datetime as dt, html, json, re, sys, time, urllib.request

UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
out = []
for y in range(2018, 2026):
    h = urllib.request.urlopen(urllib.request.Request(f'https://www.basketball-reference.com/leagues/NBA_{y}_transactions.html', headers={'User-Agent': UA}), timeout=60).read().decode('utf-8', 'replace')
    time.sleep(4)
    n = 0
    for li in re.findall(r'<li><span>(.*?)</span>(.*?)</li>', h, re.S):
        try: d = dt.datetime.strptime(html.unescape(li[0]).strip(), '%B %d, %Y').date()
        except ValueError: continue
        for p in re.findall(r'<p[^>]*>(.*?)</p>', li[1], re.S):
            t = html.unescape(re.sub(r'<[^>]+>', '', p))
            ids = re.findall(r'/players/\w/(\w+)\.html[^>]*>([^<]+)<', p)
            if not ids: continue
            kind = 'convert' if re.search(r'converted .* from a two-way', t) else 'sign' if re.search(r'signed .* to a two-way contract', t) else 'waive' if re.search(r'\bwaived\b', t) else None
            if kind:
                for pid, nm in ids:
                    out.append([y, str(d), kind, pid, html.unescape(nm)]); n += 1
    print(y, n, flush=True)
json.dump(out, open(sys.argv[1], 'w'))
