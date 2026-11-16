#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Upload a sport's model output to the private TLS feed (ops/tls-feed/worker.js) after its build.

    python3 scripts/tls_upload.py nfl          # in the sport's workflow, after the build and its commit
    python3 scripts/tls_upload.py nfl --dry    # list what would go up

Needs TLS_FEED_URL (the worker's https://... address) and TLS_UPLOAD_TOKEN in the environment (repository secrets);
without them it prints one line and exits 0. A failed upload is printed and never fails the build.
The sim draws (scripts/.cache/draws/<sport>.json.gz, written with ARK_DRAWS=1) go up only from this upload: they are
never committed.
"""
import gzip
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAWS = 'scripts/.cache/draws/{}.json.gz'
FILES = {      # feed name -> repo file
    'nfl': {'games.json': 'data/nfl_games.json', 'fantasy.json': 'static/data/nfl-fantasy.json',
            'draws.json.gz': DRAWS.format('nfl')},
    'nba': {'games.json': 'data/nba_games.json', 'projections.json': 'static/data/nba-proj.json',
            'draws.json.gz': DRAWS.format('nba')},
    'cbb': {'games.json': 'data/cbb_games.json', 'draws.json.gz': DRAWS.format('cbb')},
    'cfb': {'games.json': 'data/cfb_games.json', 'model.json': 'data/cfb_model.json', 'rank.json': 'data/cfb_rank.json',
            'draws.json.gz': DRAWS.format('cfb')},
}


def asof(path):
    try:
        op = gzip.open if path.endswith('.gz') else open
        with op(path, 'rt', encoding='utf-8') as f:
            return str(json.load(f).get('asof') or '')
    except Exception:
        return ''


def main(argv):
    sport = argv[1] if len(argv) > 1 else ''
    if sport not in FILES:
        print('usage: tls_upload.py nfl|nba|cbb|cfb [--dry]')
        return 2
    dry = '--dry' in argv
    url, token = os.environ.get('TLS_FEED_URL', '').rstrip('/'), os.environ.get('TLS_UPLOAD_TOKEN', '')
    if not dry and not (url and token):
        print('tls feed: TLS_FEED_URL / TLS_UPLOAD_TOKEN not set, nothing uploaded')
        return 0
    for name, rel in FILES[sport].items():
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f'tls feed: {rel} missing, skipped')
            continue
        size = os.path.getsize(path)
        if dry:
            print(f'tls feed: would put {sport}/{name} <- {rel} ({size / 1e6:.2f} MB)')
            continue
        with open(path, 'rb') as f:
            body = f.read()
        req = urllib.request.Request(f'{url}/v1/{sport}/{name}', data=body, method='PUT', headers={
            'authorization': f'Bearer {token}', 'content-type': 'application/octet-stream', 'x-asof': asof(path),
            'user-agent': 'ark-tls-upload'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                print(f'tls feed: {sport}/{name} ({size / 1e6:.2f} MB) -> {r.status} {r.read().decode()[:200]}')
        except Exception as e:
            print(f'tls feed: {sport}/{name} failed: {e!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
