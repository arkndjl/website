#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-stage ledger for a Counter-Strike Major: a copy and a sha256 of the pick'em and event odds files as they stood
before each stage began.

    python3 scripts/cs2_ledger.py           record the open stage (the cs2 workflow, after the model step)
    python3 scripts/cs2_ledger.py --test    self-check

Reads data/cs2_pickem.json and data/cs2_events.json. While the stage named in the pick'em file has not started
(now < start and not locked), each build replaces
  scripts/data/ledger/cs2/<event>/<stage>-pickem.json and <stage>-events.json   (byte copies)
and the stage's entry in scripts/data/ledger/cs2/<event>/index.json: {stage, start, recorded, asof and sha256 of both}.
The last build before the start is the one that stays: once the stage has started or locked the entry is marked
`closed` and its files are never touched again. Event odds are also kept once before the event's first day (`pre`).

SCORING (fixed with the event odds and pick'em backtests; scored once after the event ends): the stage's nine picks
and their P(pass), the 3-0 / 0-3 / advance odds (Brier by team) and the title and placement odds (Brier and log loss
by team) are read from these copies, not from a later rebuild."""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICK = os.path.join(ROOT, 'data', 'cs2_pickem.json')
EVENTS = os.path.join(ROOT, 'data', 'cs2_events.json')
STORE = os.path.join(ROOT, 'scripts', 'data', 'ledger', 'cs2')


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')


def sha(path):
    with open(path, 'rb') as h:
        return hashlib.sha256(h.read()).hexdigest()


def when(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def record(pick=PICK, events=EVENTS, store=STORE, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    with open(pick) as h:
        p = json.load(h)
    with open(events) as h:
        e = json.load(h)
    if not p.get('event') or not p.get('stage') or not p.get('start'):
        print('cs2 ledger: no open stage'); return None
    folder = os.path.join(store, slug(p['event']))
    idx_f = os.path.join(folder, 'index.json')
    idx = {'event': p['event'], 'stages': {}}
    if os.path.exists(idx_f):
        with open(idx_f) as h:
            idx = json.load(h)
    done = []

    def keep(tag, start, files, open_now):
        cur = idx['stages'].get(tag)
        if cur and cur.get('closed'):
            return
        if not open_now:
            if cur:
                cur['closed'] = True; done.append(tag + ' closed')
            return
        os.makedirs(folder, exist_ok=True)
        ent = {'stage': tag, 'start': start, 'recorded': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'files': {}}
        for kind, src, asof in files:
            dst = f'{tag}-{kind}.json'
            shutil.copyfile(src, os.path.join(folder, dst))
            ent['files'][kind] = {'file': dst, 'asof': asof, 'sha256': sha(src)}
        if cur and all(cur['files'].get(k, {}).get('sha256') == v['sha256'] for k, v in ent['files'].items()):
            return      # same bytes as the last record: keep its time
        idx['stages'][tag] = ent; done.append(tag)

    same_event = e.get('name') == p['event']
    first = (e.get('dates') or [None])[0]
    if same_event and first:
        keep('pre', first, [('events', events, e.get('asof'))], now.date().isoformat() < first)
    files = [('pickem', pick, p.get('asof'))] + ([('events', events, e.get('asof'))] if same_event else [])
    keep(slug(p['stage']), p['start'], files, (not p.get('locked')) and now < when(p['start']))
    if done:
        os.makedirs(folder, exist_ok=True)
        with open(idx_f, 'w') as h:
            json.dump(idx, h, indent=1, ensure_ascii=False)
            h.write('\n')
    print('cs2 ledger:', ', '.join(done) if done else 'nothing new')
    return idx


def test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        pf, ef, st = os.path.join(tmp, 'p.json'), os.path.join(tmp, 'e.json'), os.path.join(tmp, 's')
        p = {'event': 'Test Major 2026', 'stage': 'Stage 1', 'start': '2026-11-24T04:00:00.000+00:00', 'locked': False, 'asof': 'a', 'ev': 4.7}
        e = {'name': 'Test Major 2026', 'dates': ['2026-11-24'], 'asof': 'b'}
        json.dump(p, open(pf, 'w')); json.dump(e, open(ef, 'w'))
        t0 = dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc)
        i = record(pf, ef, st, t0)
        assert set(i['stages']) == {'pre', 'stage-1'} and i['stages']['stage-1']['files']['pickem']['sha256'] == sha(pf)
        f = os.path.join(st, 'test-major-2026', 'stage-1-pickem.json')
        before = open(f, 'rb').read()
        assert before == open(pf, 'rb').read()
        p['ev'] = 9.9; json.dump(p, open(pf, 'w'))          # the stage has started: the copy must not move
        i = record(pf, ef, st, dt.datetime(2026, 11, 24, 5, tzinfo=dt.timezone.utc))
        assert open(f, 'rb').read() == before and i['stages']['stage-1']['closed'] and i['stages']['pre']['closed']
        p.update(stage='Stage 2', start='2026-11-28T04:00:00.000+00:00'); json.dump(p, open(pf, 'w'))
        i = record(pf, ef, st, dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc))
        assert 'stage-2' in i['stages'] and open(f, 'rb').read() == before and 'events' in i['stages']['stage-2']['files']
    print('cs2_ledger: ok')


if __name__ == '__main__':
    test() if '--test' in sys.argv else record()
