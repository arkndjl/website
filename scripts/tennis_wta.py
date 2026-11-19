#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""WTA lower-level results (ITF, WTA 125, tour qualifying) since the Sackmann archive froze, from the WTA's own
public API, as history rows for scripts/tennis_data.py.

Tennis Abstract's pages (scripts/tennis_ta.py) stopped carrying ITF rows in August 2026, so women ranked 100-400 who
play ITF events had no recent match on file. api.wtatennis.com/tennis/players/<id>/matches lists every match of a
player (all levels, entry rank, round, score from the winner's side); the pool is the top POOL of the WTA's ranking
list. Each run reads the stalest pages inside a time budget, keeps singles matches of events that started after CUT
below tour main-draw level, and merges them into scripts/data/tennis_wta.jsonl (committed, one match a line).
tennis_data.build() adds the rows no other source holds (the same two players inside ten days = the same match).

    python3 scripts/tennis_wta.py            # refresh inside the budget, print the counts
    python3 scripts/tennis_wta.py --all      # no budget (first fill: about 8 minutes)
    python3 scripts/tennis_wta.py --check    # cached pages against the history: tour main-draw rows, winner and score
    python3 scripts/tennis_wta.py --test     # self-check, no network
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tennis_ta as TA  # noqa: E402

CACHE = os.path.join(HERE, '.cache', 'tennis', 'wta_api')
STORE = os.path.join(HERE, 'data', 'tennis_wta.jsonl')
API = 'https://api.wtatennis.com/tennis/'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
CUT = TA.CUT
POOL = 400
MAX_AGE = 3 * 86400
BUDGET = 300
PAUSE = 1.05
LEVEL = {'ITF': 'S', 'C': 'C'}                       # tour levels (GS, PM, P, IS): qualifying only
ROUND = {'F': 'F', 'S': 'SF', 'Q': 'QF'}
SURF = {'HARD': 'H', 'CLAY': 'C', 'GRASS': 'G', 'CARPET': 'H'}
_last = [0.0]


def get(path, name, max_age=MAX_AGE, fetch=True):
    """(json or None, 1 when fetched now)"""
    f = os.path.join(CACHE, name + '.json')
    if os.path.exists(f) and (not fetch or time.time() - os.path.getmtime(f) < max_age):
        try:
            return json.load(open(f)), 0
        except ValueError:
            pass
    if not fetch:
        return None, 0
    w = PAUSE - (time.time() - _last[0])
    if w > 0: time.sleep(w)
    _last[0] = time.time()
    try:
        r = subprocess.run(['curl', '-sS', '--compressed', '-m', '40', '-A', UA, API + path], capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout)
    except (ValueError, subprocess.SubprocessError, OSError):
        return None, 1
    os.makedirs(CACHE, exist_ok=True)
    json.dump(d, open(f, 'w'), separators=(',', ':'))
    return d, 1


def bday(s):
    return (s or '')[:10].replace('-', '')


def score(m):
    s = re.sub(r'\s+', ' ', (m.get('scores') or '').strip())
    if not s: return None
    return s + ' RET' if m.get('reason_code') == 'R' else s


def derive(pid, ms, find):
    """a player's API rows as history rows (tennis_data COLS + the event name): singles, played, started after CUT,
    below tour main-draw level. Scores are the winner's."""
    out = []
    for m in ms:
        if m.get('s_d_flag') != 'S' or m.get('reason_code') not in ('W', 'R') or m.get('winner') not in (1, 2): continue
        d = bday(m.get('StartDate'))
        if not d.isdigit() or int(d) <= CUT: continue
        qual = m.get('qpm_flag') == 'Q'
        lv = LEVEL.get(m.get('TournamentLevel'))
        if lv is None:
            if not qual or m.get('TournamentLevel') not in ('GS', 'PM', 'P', 'IS'): continue
            lv = 'Q'
        rn = (m.get('round_name') or '').strip()
        rd = f"Q{m.get('tourn_round') or 1}" if qual else ROUND.get(rn, rn)
        sc = score(m)
        o = m.get('opponent') or {}
        if not rd or not sc or not o.get('fullName'): continue
        opp = find(o['fullName'], bday(o.get('dateOfBirth')), o.get('countryCode'), '', None)
        if not opp or opp == pid: continue
        won = m['winner'] == 1
        w, l = (pid, opp) if won else (opp, pid)
        r1, r2 = m.get('rank_1'), m.get('rank_2')
        wr, lr = (r1, r2) if won else (r2, r1)
        nm = (m.get('TournamentName') or '').strip().title()
        tid = f"wwt{d}-{re.sub(r'[^a-z0-9]+', '-', nm.lower()).strip('-')}"
        out.append([int(d), 'wta', lv, SURF.get((m.get('Surface') or '').upper(), 'H'), rd, 3, tid, w, l, sc, None, None,
                    wr if isinstance(wr, int) else None, lr if isinstance(lr, int) else None, None, None, nm])
    return out


def load():
    rows, bios = {}, {}
    try:
        with open(STORE, encoding='utf-8') as fh:
            for line in fh:
                x = json.loads(line)
                if isinstance(x, dict): bios[x['id']] = x['bio']
                else: rows[TA.key(x)] = x
    except OSError:
        pass
    return rows, bios


def save(rows, bios):
    with open(STORE, 'w', encoding='utf-8') as fh:
        for pid in sorted(bios):
            fh.write(json.dumps({'id': pid, 'bio': bios[pid]}, separators=(',', ':'), ensure_ascii=False) + '\n')
        for k in sorted(rows):
            fh.write(json.dumps(rows[k], separators=(',', ':'), ensure_ascii=False) + '\n')


def pool(fetch=True):
    """the WTA's ranking list, top POOL: [{id, fullName, dateOfBirth, countryCode}]"""
    mon = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    out = []
    for pg in range(POOL // 100):
        d, _ = get(f'players/ranked?page={pg}&pageSize=100&type=rankSingles&sort=asc&name=&metric=SINGLES&at={mon}&nationality=',
                   f'rank_{pg}', max_age=86400, fetch=fetch)
        out += [x['player'] for x in (d or []) if x.get('player')]
    return out


def refresh(bios, fetch=True, budget=BUDGET):
    """read the stalest pool pages inside the budget, merge their matches into the store; returns (rows, new bios)"""
    rows, tb = load()
    for pid, b in tb.items(): bios.setdefault(pid, b)
    find = TA.finder(bios, 'wta', tb)
    t0, got, seen = time.time(), 0, 0
    ps = pool(fetch)

    def age(p):
        f = os.path.join(CACHE, f"p_{p['id']}.json")
        return os.path.getmtime(f) if os.path.exists(f) else 0
    for p in sorted(ps, key=age):
        d, new = get(f"players/{p['id']}/matches/?page=0&pageSize=40&sort=desc", f"p_{p['id']}", fetch=fetch and time.time() - t0 < budget)
        got += new
        if not d: continue
        seen += 1
        pid = find(p.get('fullName'), bday(p.get('dateOfBirth')), p.get('countryCode'), '', None)
        if not pid: continue
        for r in derive(pid, d.get('matches') or [], find):
            rows.setdefault(TA.key(r), r)
    save(rows, tb)
    print(f'WTA API: {seen} pages on file ({got} read now), {len(rows)} lower-level matches since the archive froze, '
          f'{len(tb)} players new to the history')
    return list(rows.values()), tb


def add(hist, rows):
    """the rows no other source holds: the same two players inside ten days = the same match"""
    def dn(d): return dt.date(d // 10000, d // 100 % 100, d % 100).toordinal()
    have = {}
    for r in hist:
        if r[0] >= CUT - 100: have.setdefault(frozenset((r[7], r[8])), []).append(dn(r[0]))
    out = []
    for r in sorted(rows, key=lambda r: r[0]):
        k = frozenset((r[7], r[8]))
        if any(abs(dn(r[0]) - x) <= 10 for x in have.get(k, ())): continue
        have.setdefault(k, []).append(dn(r[0]))
        out.append(r)
    return out


def check():
    """cached pages against the history on tour main-draw rows: same pair inside ten days, winner and score"""
    import tennis_data as T
    hist, players, _ = T.load()
    bios = {pid: {'n': b.get('n', ''), 'ioc': '', 'dob': b.get('dob')} for pid, b in players.items()}
    find = TA.finder(bios, 'wta', {})
    idx = {}
    for r in hist:
        if r[1] == 'wta' and r[0] >= 20260101 and r[2] in ('G', 'M', 'A') and not T.is_qual(r[4]):
            idx.setdefault(frozenset((r[7], r[8])), []).append(r)
    n = same = win = 0
    for p in pool(fetch=False):
        d, _ = get('', f"p_{p['id']}", fetch=False)
        pid = find(p.get('fullName'), bday(p.get('dateOfBirth')), p.get('countryCode'), '', None)
        for m in (d or {}).get('matches') or []:
            if m.get('s_d_flag') != 'S' or m.get('qpm_flag') != 'M' or m.get('TournamentLevel') not in ('GS', 'PM', 'P', 'IS'): continue
            if m.get('reason_code') != 'W' or not m.get('opponent'): continue
            o = m['opponent']
            opp = find(o['fullName'], bday(o.get('dateOfBirth')), o.get('countryCode'), '', None)
            c = idx.get(frozenset((pid, opp)), [])
            day = dt.date.fromisoformat(m['StartDate'][:10]).toordinal()
            c = [r for r in c if abs(dt.date(r[0] // 10000, r[0] // 100 % 100, r[0] % 100).toordinal() - day) <= 10]
            if not c: continue
            n += 1
            r = c[0]
            win += (r[7] == pid) == (m['winner'] == 1)
            a = re.sub(r'\(\d+\)', '', score(m) or ''); b = re.sub(r'\(\d+\)', '', r[9] or '')
            same += a.split() == b.split()
    print(f'tour main-draw rows on both sides: {n}; same winner {win}; same score {same}')
    return n, win, same


def test():
    m = {'s_d_flag': 'S', 'reason_code': 'R', 'winner': 2, 'StartDate': '2026-09-21T00:00:00+00:00', 'qpm_flag': 'M',
         'TournamentLevel': 'C', 'round_name': 'S', 'tourn_round': '4', 'scores': '5-7  5-3', 'Surface': 'CLAY',
         'TournamentName': 'TOLENTINO 125', 'rank_1': 246, 'rank_2': 120,
         'opponent': {'fullName': 'Test Opponent', 'dateOfBirth': '2001-02-03', 'countryCode': 'ITA'}}
    bios, new = {'w1': {'n': 'Some Player', 'dob': 19990101, 'ioc': 'SLO'}}, {}
    find = TA.finder(bios, 'wta', new)
    r = derive('w1', [m, dict(m, s_d_flag='D'), dict(m, reason_code='B'), dict(m, StartDate='2026-05-01T00:00:00+00:00'),
                      dict(m, TournamentLevel='PM'), dict(m, TournamentLevel='PM', qpm_flag='Q', tourn_round='2', reason_code='W', winner=1)], find)
    assert len(r) == 2, r
    assert r[0][:10] == [20260921, 'wta', 'C', 'C', 'SF', 3, 'wwt20260921-tolentino-125', 'wtatestopponent010203', 'w1', '5-7 5-3 RET'], r[0]
    assert r[0][12:14] == [120, 246] and r[1][2] == 'Q' and r[1][4] == 'Q2' and r[1][7] == 'w1'
    h = [[20260921, 'wta', 'C', 'C', 'SF', 3, 'x', 'w1', 'wtatestopponent010203', '', None, None, None, None, None, None, 'x']]
    assert add(h, r) == [r[1]] or len(add(h, r)) == 0
    assert len(add([], r)) == 1                      # the two rows are one pair inside ten days
    print('ok')


if __name__ == '__main__':
    if '--test' in sys.argv: test()
    elif '--check' in sys.argv: check()
    else:
        import tennis_data as T
        bios = T.sack_players()
        try:
            _, players, _ = T.load()
            for pid, b in players.items(): bios.setdefault(pid, {'n': b.get('n', ''), 'ioc': '', 'dob': b.get('dob')})
        except OSError:
            pass
        refresh(bios, budget=10 ** 9 if '--all' in sys.argv else BUDGET)
