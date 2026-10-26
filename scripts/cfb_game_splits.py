#!/usr/bin/env python3
"""Game-level splits for the CFB FV driver search (Oct 26 2026), from the ESPN summaries scripts/cfb_espn_pbp.py caches
(play-by-play in scripts/.cache/cfb/espn_pbp, box scores in scripts/.cache/cfb/espn_hist/box) and nflverse draft picks.
    python3 scripts/cfb_espn_pbp.py 2015 2022 && python3 scripts/cfb_game_splits.py [first] [last]   # default 2015 2022
Writes scripts/.cache/fvrefit/game_splits.json: {"<season>|<name key>|<school key>": {...}} with, per player-season:
  nfl      production against future-NFL units: games weighted by the opponent unit's draft capital over the next three
           drafts (receivers vs DBs, backs vs the front, QBs vs both, pass rushers' sacks vs the OL), as a log ratio to
           his own average, shrunk by the weight of his top-third games
  comp     share of his yards gained with the score within 16, over his team's share (garbage-time padding < 0)
  trend    second half of his games over the first, per game, over his average (shrunk by games)
  pen      accepted penalties a game charged to him by name (holding, interference, false start, ...)
Production: rushing plus receiving yards (QBs passing plus rushing) from the box scores; sacks from the play text.
"""
import csv
import glob
import gzip
import json
import math
import os
import re
import sys
import unicodedata
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
C = os.path.join(HERE, '.cache')
OUT = os.path.join(C, 'fvrefit', 'game_splits.json')
PICKS = os.path.join(C, 'statplus', 'draft_picks.csv')


def nm(s):   # as cfb_fv_refit.mjs nm()
    s = unicodedata.normalize('NFKD', (s or '').lower())
    s = re.sub(r'[^a-z ]', '', s)
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def school(s):   # as cfb_fv_refit.mjs school()
    s = re.sub(r'\bstate\b', 'st', nm(s))
    s = re.sub(r'\buniversity\b|\bof\b', '', s)
    return re.sub(r'\s+', ' ', s).strip().split(' ')[0] if s.strip() else ''


UNIT = {'DB': {'CB', 'S', 'DB', 'SAF', 'FS', 'SS'}, 'FRONT': {'DE', 'DT', 'DL', 'NT', 'LB', 'OLB', 'ILB', 'MLB', 'EDGE'},
        'OL': {'OT', 'T', 'OG', 'G', 'C', 'OL'}}


def ol_recruits():
    """{(school key, season): OL recruiting talent}: 247 composite ratings over .80 of the OL signed in the last five
    classes (classes s-4..s), from the pages scripts/cfb_fv_refit.mjs caches in scripts/.cache/fvrefit/247. Known at
    the time, unlike the draft capital, so a live board can compute it."""
    by = defaultdict(float)
    for fn in glob.glob(os.path.join(C, 'fvrefit', '247', 'c_*.html')):
        y = int(os.path.basename(fn).split('_')[1])
        for it in open(fn, encoding='utf-8', errors='ignore').read().split('rankings-page__list-item"')[1:]:
            pos = re.search(r'class="position">\s*([A-Z]+)', it)
            sc = re.search(r'class="score">([\d.]+)', it)
            sch = re.search(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"', it)
            if pos and sc and sch and pos.group(1) in ('OT', 'IOL', 'OG', 'OC', 'OL'):
                for s in range(y, y + 5):
                    by[(school(sch.group(1)), s)] += max(0.0, float(sc.group(1)) - 0.80)
    return by


def capital():
    """{(school key, season): {unit: capital}} from the next three drafts (AV a season by slot, roughly)"""
    cap = defaultdict(lambda: defaultdict(float))
    for r in csv.DictReader(open(PICKS)):
        try:
            d, pk = int(r['season']), int(r['pick'])
        except ValueError:
            continue
        v = max(0.0, 5.5 - 0.85 * math.log(pk))
        for u, ps in UNIT.items():
            if r['position'] in ps:
                for s in (d - 1, d - 2, d - 3):
                    cap[(school(r['college']), s)][u] += v
    return cap


RUSH = re.compile(r"^([A-Z][A-Za-z'.\- ]+?) (?:run|rush) for (-?\d+|no gain|a loss of \d+)")
PASS = re.compile(r"^([A-Z][A-Za-z'.\- ]+?) pass complete to ([A-Z][A-Za-z'.\- ]+?) for (-?\d+|no gain|a loss of \d+)")
SACK = re.compile(r"sacked by ([A-Z][A-Za-z'.\- ]+?)(?: and ([A-Z][A-Za-z'.\- ]+?))? for")
PEN = re.compile(r"([A-Z][A-Z .&'()\-]+?) Penalty, ([^(]+?) \(([A-Z][A-Za-z'.\- ]+?)\)")


def yds(t):
    if t == 'no gain':
        return 0
    m = re.match(r'a loss of (\d+)', t)
    return -int(m.group(1)) if m else int(t)


def main():
    a, b = (int(x) for x in sys.argv[1:3]) if len(sys.argv) > 2 else (2015, 2022)
    cap = capital()
    olr = ol_recruits()
    P = defaultdict(lambda: {'g': [], 'cy': 0, 'ay': 0, 'pen': 0, 'sk': []})
    team_comp = defaultdict(lambda: [0, 0])
    tg, skd, pen = defaultdict(list), defaultdict(lambda: defaultdict(float)), defaultdict(int)
    for y in range(a, b + 1):
        games = json.load(open(os.path.join(C, 'cfb', 'espn_hist', f'games{y}.json')))
        for g in games:
            fb = os.path.join(C, 'cfb', 'espn_hist', 'box', f"{g['id']}.json")
            fp = os.path.join(C, 'cfb', 'espn_pbp', f"{g['id']}.json.gz")
            if not os.path.exists(fb) or not os.path.exists(fp):
                continue
            box = json.load(open(fb))
            name = {g['h']: g['hn'], g['a']: g['an']}
            opp = {g['h']: g['a'], g['a']: g['h']}
            capu = {t: cap.get((school(name[t]), y), {}) for t in name}
            gp = defaultdict(set)   # (team, name key) -> played
            for t, ps in box.items():
                if t not in name:
                    continue
                o = capu[opp[t]]
                for p in ps.values():
                    k = (y, nm(p['n']), school(name[t]))
                    ry, cy, py = p.get('rus_YDS') or 0, p.get('rec_YDS') or 0, p.get('pas_YDS') or 0
                    P[k]['g'].append((g['date'], {'rec': cy, 'scr': ry + cy, 'qb': py + ry},
                                      {'rec': o.get('DB', 0), 'scr': o.get('FRONT', 0), 'qb': o.get('DB', 0) + o.get('FRONT', 0)}))
                    gp[t].add(k)
            sk = defaultdict(float)
            d = json.load(gzip.open(fp))
            for dr in d.get('drives') or []:
                for p in dr.get('plays') or []:
                    x, off = (p.get('x') or '').strip(), p.get('st')
                    if off not in name:
                        continue
                    dfn = opp[off]
                    if p.get('pen') or p.get('t') == 'Penalty':
                        m = PEN.search(x)
                        if m:
                            t = next((t for t in (off, dfn) if school(m.group(1)) == school(name[t])), None)
                            if t:
                                pen[(y, nm(m.group(3)), school(name[t]))] += 1
                        if p.get('t') == 'Penalty':
                            continue
                    comp = abs((p.get('hs') or 0) - (p.get('as') or 0)) <= 16
                    m = SACK.search(x)
                    if m:
                        for i, n in enumerate([m.group(1), m.group(2)]):
                            if n:
                                sk[(y, nm(n), school(name[dfn]))] += 1 if not m.group(2) else 0.5
                        continue
                    m = PASS.match(x)
                    who, v = (m.group(2), yds(m.group(3))) if m else (None, None)
                    if not m:
                        m = RUSH.match(x)
                        if m:
                            who, v = m.group(1), yds(m.group(2))
                    if who is None:
                        continue
                    k = (y, nm(who), school(name[off]))
                    tc = team_comp[(y, school(name[off]))]
                    tc[1] += v; tc[0] += v * comp
                    P[k]['ay'] += v; P[k]['cy'] += v * comp
            # pass rushers: box scores before 2024 rarely list defenders, so a sacker is taken to have played
            # every team game (sacks a team game)
            for t in name:
                tg[(y, school(name[t]))].append((g['date'], capu[opp[t]].get('OL', 0), olr.get((school(name[opp[t]]), y), 0.0)))
            for k, n in sk.items():
                skd[k][g['date']] += n
    for k in pen:
        P[k]
    for k, d in skd.items():
        P[k]['sk'] = [(dt, d.get(dt, 0.0), o, orr) for dt, o, orr in tg[(k[0], k[2])]]
    out = {}
    for k, v in list(P.items()):
        r = {}
        gs = sorted(v['g'], key=lambda q: q[0])
        if len(gs) >= 4:
            for u in ('rec', 'scr', 'qb'):
                ys = [q[1][u] for q in gs]
                m = sum(ys) / len(ys)
                if m < 15:
                    continue
                ws = [q[2][u] for q in gs]
                thr = sorted(ws)[len(ws) * 2 // 3]
                top = [yy for yy, w in zip(ys, ws) if w >= thr and w > 0]
                if top:
                    r['nfl_' + u] = math.log(max(5, sum(top) / len(top)) / m) * len(top) / (len(top) + 3)
                h = len(ys) // 2
                r['trend_' + u] = (sum(ys[h:]) / (len(ys) - h) - sum(ys[:h]) / h) / m * len(ys) / (len(ys) + 6)
            r['gp'] = len(gs)
        sks = sorted(v['sk'], key=lambda q: q[0])
        if len(sks) >= 4 and sum(s[1] for s in sks) >= 2:
            m = sum(s[1] for s in sks) / len(sks)
            thr = sorted(s[2] for s in sks)[len(sks) * 2 // 3]
            top = [s[1] for s in sks if s[2] >= thr and s[2] > 0]
            if top:
                r['nfl_sk'] = math.log(max(0.1, sum(top) / len(top)) / m) * len(top) / (len(top) + 3)
            thr = sorted(s[3] for s in sks)[len(sks) * 2 // 3]
            top = [s[1] for s in sks if s[3] >= thr and s[3] > 0]
            if top:
                r['rec_sk'] = math.log(max(0.1, sum(top) / len(top)) / m) * len(top) / (len(top) + 3)
            h = len(sks) // 2
            r['trend_sk'] = (sum(s[1] for s in sks[h:]) / (len(sks) - h) - sum(s[1] for s in sks[:h]) / h) / max(m, 0.2) * len(sks) / (len(sks) + 6)
        if v['ay'] >= 100:
            tc = team_comp[(k[0], k[2])]
            r['comp'] = (v['cy'] / v['ay'] - tc[0] / max(tc[1], 1)) * v['ay'] / (v['ay'] + 300)
        if k in pen:
            r['pen'] = pen[k] / max(1, len(tg[(k[0], k[2])]))
        if r:
            out[f'{k[0]}|{k[1]}|{k[2]}'] = r
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'))
    print(len(out), 'player-seasons;', sum('comp' in r for r in out.values()), 'with comp;', sum('nfl_sk' in r for r in out.values()), 'with sacks;',
          sum(r.get('pen', 0) > 0 for r in out.values()), 'with penalties')


if __name__ == '__main__':
    main()
