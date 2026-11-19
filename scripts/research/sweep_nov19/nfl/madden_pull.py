#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Launch-roster Madden rating sheets from maddenratings.net (one page an edition, one .xlsx a team).

    python3 madden_pull.py <out dir> [editions...]

Raw sheets stay outside the repo; madden_parse.py turns them into one frozen table."""
import os
import re
import sys
import time
import urllib.request

UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
BASE = 'https://www.maddenratings.net'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def main():
    out = sys.argv[1]
    eds = sys.argv[2:] or [str(e) for e in range(16, 26)] + ['27']
    for ed in eds:
        d = os.path.join(out, ed)
        os.makedirs(d, exist_ok=True)
        try:
            page = get(f'{BASE}/madden-nfl-{ed}.html').decode('utf-8', 'replace')
        except Exception as e:
            print(ed, 'page', e, flush=True)
            continue
        time.sleep(1.1)
        links = sorted(set(re.findall(r"href=['\"](/uploads/[^'\"]+\.xlsx)['\"]", page)))
        print(ed, len(links), 'files', flush=True)
        for l in links:
            fn = os.path.join(d, os.path.basename(l))
            if os.path.exists(fn) and os.path.getsize(fn) > 2000:
                continue
            try:
                b = get(BASE + l)
                open(fn, 'wb').write(b)
            except Exception as e:
                print(ed, l, e, flush=True)
            time.sleep(1.1)


if __name__ == '__main__':
    main()
