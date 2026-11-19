#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Head-coach pages from pro-football-history.com (robots: crawl-delay 1): the index and one bio page a coach.

    python3 pfh_pull.py <cache dir>"""
import os
import re
import sys
import time
import urllib.request

UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
BASE = 'https://pro-football-history.com'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    idx = os.path.join(out, 'coaches.html')
    if not os.path.exists(idx):
        open(idx, 'wb').write(get(BASE + '/coaches'))
        time.sleep(1.3)
    links = sorted(set(re.findall(r'href="(/coach/\d+/[^"]+-bio)"', open(idx, encoding='utf-8', errors='replace').read())))
    print(len(links), 'coaches', flush=True)
    for l in links:
        fn = os.path.join(out, l.strip('/').replace('/', '_') + '.html')
        if os.path.exists(fn) and os.path.getsize(fn) > 5000:
            continue
        for k in range(3):
            try:
                open(fn, 'wb').write(get(BASE + l))
                break
            except Exception as e:
                print(l, e, flush=True)
                time.sleep(20)
        time.sleep(1.3)
    print('done', flush=True)


if __name__ == '__main__':
    main()
