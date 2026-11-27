#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Head coach, offensive and defensive coordinators of every FBS and FCS team, seasons 2021-26, from each
'<season> <team> football team' Wikipedia infobox (one raw page per request; the batch API answers 429 from cloud hosts).

    python3 scripts/research/coach_loyalty_nov27/cfb_staff.py   # -> scripts/data/cfb_staff_hist.json
Needs scripts/cfb_transfer_fit.py's team cache (scripts/.cache/transfer) for the team names."""
import json
import os
import re
import sys
import time
import urllib.parse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
OUT = os.path.join(ROOT, 'scripts', 'data', 'cfb_staff_hist.json')
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cfbstaff')
UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)'
SEASONS = range(2021, 2027)
os.makedirs(CACHE, exist_ok=True)


def raw(title):
    f = os.path.join(CACHE, re.sub(r'[^A-Za-z0-9]+', '_', title) + '.txt')
    if os.path.exists(f):
        return open(f).read()
    url = 'https://en.wikipedia.org/w/index.php?action=raw&section=0&title=' + urllib.parse.quote(title.replace(' ', '_'))
    txt = ''
    for k in range(5):
        r = requests.get(url, headers={'User-Agent': UA}, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get('retry-after') or 20 * 2 ** k)); continue
        txt = r.text if r.status_code == 200 else ''
        break
    else:
        return None
    m = re.match(r'\s*#REDIRECT\s*\[\[([^\]|#]+)', txt, re.I)
    if m and m.group(1) != title:
        txt = raw(m.group(1)) or ''
    open(f, 'w').write(txt)
    time.sleep(0.35)
    return txt


def people(txt, field):
    out = []
    for m in re.finditer(r'\|\s*' + field + r'\d?\s*=([^\n]*)', txt or ''):
        v = m.group(1)
        names = re.findall(r'\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]', v)
        if not names:
            names = [x.strip() for x in re.split(r'<br\s*/?>|,|/|\(|&', re.sub(r'<ref.*', '', v)) if x.strip() and not re.match(r'^[\d\W]|.*\)$|interim|season|games?\b', x.strip(), re.I)][:2]
        out += [re.sub(r'\s*\(.*?\)', '', n).strip() for n in names]
    return [n for n in dict.fromkeys(out) if n and len(n.split()) >= 2 and not re.search(r'coach|coordinator|football|\d', n, re.I)]


def main():
    import cfb_transfer_fit as T
    T.OFFLINE = True
    full = {}
    for s in (2026, 2025, 2024):
        for tid, div in T.teams_of(s).items():
            if tid not in full:
                t = T.get(f'{T.CORE}/seasons/{s}/teams/{tid}') or {}
                if t.get('displayName'): full[tid] = t['displayName']
    print('teams', len(full), flush=True)
    out = {}
    for s in SEASONS:
        out[str(s)] = {}
        for tid, nm in sorted(full.items()):
            txt = raw(f'{s} {nm} football team')
            if txt is None: print('gave up (429)', s, nm); continue
            v = {'hc': people(txt, 'head_coach'), 'oc': people(txt, 'off_coach'), 'dc': people(txt, 'def_coach')}
            if v['hc']: out[str(s)][tid] = v
        print(s, len(out[str(s)]), 'of', len(full), 'oc', sum(bool(v['oc']) for v in out[str(s)].values()), flush=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), sort_keys=True)


if __name__ == '__main__':
    main()
