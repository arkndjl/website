"""static/data/lineups/soccer.json for the soccer "lineups" tab (layouts/shortcodes/soccerlineups.html): every big-five
club's league lineups this season from Understat match rosters (scripts/soccer_data.py us_match, cached by the soccer
run). Per club:
  fm     formations used, most first: [shape, starts]. The shape is read off Understat's starting positions
         (D* = defence, DM* / M* / AM* = the midfield bands, FW* = attack), so a back three with wing-backs listed as
         DMR/DML reads 3-4-x.
  xi     the most-used XI in the most-used formation: [position code, name, starts at that code in that shape]
         (greedy by starts, a player used once).
  chg    mean starters changed from the previous league match; last = the last league XI (names, position order).
  pairs  the 8 outfield pairs with the most league minutes on the pitch together: [a, b, minutes, team xG for - against per 90
         while both were on]. Minutes come from Understat's minutes played (a starter from 0, a sub to 90), shots by
         minute, so stoppage time is folded into 90.
Run after scripts/soccer_players.py in the soccer workflow (the cache is warm by then).
Research on lineup continuity as a game-model term: scripts/soccer_lineup_research.py (failed, see its json)."""
import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import soccer_data as D

OUT = os.path.join(ROOT, 'static', 'data', 'lineups', 'soccer.json')
BAND = {'GK': 0, 'DR': 1, 'DC': 1, 'DL': 1, 'DMR': 2, 'DMC': 2, 'DML': 2, 'MR': 3, 'MC': 3, 'ML': 3,
        'AMR': 4, 'AMC': 4, 'AML': 4, 'FWR': 5, 'FW': 5, 'FWL': 5}
SIDE = lambda c: 0 if c.endswith('L') else 2 if c.endswith('R') else 1   # left, centre, right


def shape(codes):
    """formation string; wide holding players (DML / DMR, Understat's wing-backs) count on the midfield line"""
    n = Counter(3 if c in ('DML', 'DMR') else BAND.get(c, 3) for c in codes)
    parts = [n[1]] + [n[b] for b in (2, 3, 4) if n[b]] + [n[5]]
    return '-'.join(str(x) for x in parts)


def order(codes):
    """position codes in pitch order: back to front, left to right"""
    return sorted(codes, key=lambda c: (BAND.get(c, 3), SIDE(c)))


def interval(p):
    t = min(int(p.get('time') or 0), 90)
    return (0, t) if p['position'] != 'Sub' else (90 - t, 90)


def gk_sub(p, ro):
    """a substitute who came on for the keeper (Understat lists subs as 'Sub')"""
    return any(q['position'] == 'GK' and q.get('roster_in') == p['id'] for q in ro)


def club(matches):
    """matches: [(kickoff, roster list, shots for, shots against)] in date order"""
    fm, use, last, chg = Counter(), defaultdict(Counter), None, []
    pm, pxf, pxa = Counter(), Counter(), Counter()
    names = {}
    for _, ro, sf, sa in matches:
        st = [p for p in ro if p['position'] != 'Sub']
        if len(st) < 10:
            continue
        for p in ro:
            names[p['player_id']] = p['player']
        f = shape(p['position'] for p in st)
        fm[f] += 1
        for p in st:
            use[f][(p['position'], p['player_id'])] += 1
        ids = [p['player_id'] for p in st]
        if last is not None:
            chg.append(len(set(ids) - set(q['player_id'] for q in last)))
        last = st
        on = [(p['player_id'], interval(p)) for p in ro if int(p.get('time') or 0) > 0 and p['position'] != 'GK'
              and not (p['position'] == 'Sub' and gk_sub(p, ro))]
        for i in range(len(on)):
            for j in range(i + 1, len(on)):
                (a, ia), (b, ib) = on[i], on[j]
                lo, hi = max(ia[0], ib[0]), min(ia[1], ib[1])
                if hi <= lo:
                    continue
                k = tuple(sorted((a, b)))
                pm[k] += hi - lo
                pxf[k] += sum(float(s[1] or 0) for s in sf if lo <= min(int(s[0] or 0), 90) < hi)
                pxa[k] += sum(float(s[1] or 0) for s in sa if lo <= min(int(s[0] or 0), 90) < hi)
    if not fm:
        return None
    top = fm.most_common(1)[0][0]
    # most-used XI in the top shape: fill the shape's slots (its most common code multiset) greedily by starts
    slots = Counter()
    for _, ro, _, _ in matches:
        st = [p['position'] for p in ro if p['position'] != 'Sub']
        if len(st) >= 10 and shape(st) == top:
            slots[tuple(order(st))] += 1
    want = list(slots.most_common(1)[0][0])
    xi, used = [], set()
    for (code, pid), n in use[top].most_common():
        if code in want and pid not in used:
            want.remove(code); used.add(pid)
            xi.append([code, names[pid], n])
    xi.sort(key=lambda r: (BAND.get(r[0], 3), SIDE(r[0])))
    pairs = [[names[a], names[b], m, round(90 * (pxf[(a, b)] - pxa[(a, b)]) / m, 2)] for (a, b), m in pm.most_common(8)]
    return {'fm': [[k, v] for k, v in fm.most_common()], 'xi': xi,
            'chg': round(sum(chg) / len(chg), 1) if chg else None,
            'last': [[p['position'], p['player']] for p in sorted(last, key=lambda p: (BAND.get(p['position'], 3), SIDE(p['position'])))],
            'm': sum(fm.values()), 'pairs': pairs}


def espn_ids():
    """Understat club id -> ESPN club id (the logo file names): from matches joined in the frozen history
    (scripts/soccer_games_hist.json.gz 'us' = Understat match id), then by name within the league against the live
    power table (data/soccer_games.json) for clubs new to the big five"""
    import gzip
    import names as NM
    hist = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
    by_us = {r['us']: r for r in hist if r.get('us')}
    out = {}
    for S in (D.current_season() - 1, D.current_season() - 2):
        for lg in D.BIG5:
            for mt in (D.us_league(lg, S) or {}).get('matches', []):
                e = by_us.get(str(mt['id']))
                if e:
                    out.setdefault(str(mt['hid']), e['h']); out.setdefault(str(mt['aid']), e['a'])
    try:
        power = json.load(open(os.path.join(ROOT, 'data', 'soccer_games.json')))['power']
    except Exception:  # noqa: BLE001
        power = []
    return out, lambda title, lg: next((p['id'] for p in power if p.get('lg') == lg and NM.same_team(p['n'], title)), None)


def main():
    S = D.current_season()
    out = []
    ids, by_name = espn_ids()
    for lg in D.BIG5:
        d = D.us_league(lg, S)
        if not d:
            continue
        per = defaultdict(list)
        for mt in d['matches']:
            if not mt['res']:
                continue
            m = D.us_match(mt['id'])
            if not m:
                continue
            for s, o, tid in (('h', 'a', mt['hid']), ('a', 'h', mt['aid'])):
                per[tid].append((mt.get('t') or '', m['ro'][s], m['sh'][s], m['sh'][o]))
        for tid, ms in per.items():
            ms.sort(key=lambda x: x[0])
            c = club(ms)
            if c:
                title = d['teams'][tid]['title']
                eid = ids.get(str(tid)) or by_name(title, lg)
                c.update({'t': title, 'logo': f'/img/soccer/{eid}.png' if eid else None, 'grp': D.NAME.get(lg, lg)})
                out.append(c)
    out.sort(key=lambda c: c['t'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'asof': dt.date.today().isoformat(), 'teams': out},
              open(OUT, 'w'), separators=(',', ':'), allow_nan=False, ensure_ascii=False)
    print('lineups:', len(out), 'clubs')


if __name__ == '__main__':
    main()
