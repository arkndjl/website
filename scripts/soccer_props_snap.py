#!/usr/bin/env python3
"""Soccer player prop snapshots (Oct 31 2026): Novig's asks for the next two days'
matches, so the soccer props test (scripts/soccer_props_research.py) can be rerun at the prices a bet would really get.
That test passed only at holds tighter than Novig's (Oct 31: Novig's asks sat .06 over the fair chance on anytime
goalscorer, .07 on assists, .18 on 1+ shots on target), and Novig keeps no history, so the archive starts now.

    python3 scripts/soccer_props_snap.py     # odds-snap workflow, every run -> scripts/data/props/soccer-<yyyy-mm>.jsonl

Matches within 48 hours of kickoff. Rows: one per match {ev (Novig event), k (kickoff), lg, h, a}, then a row per
player market when its asks move: {t, ev, n (player), s (ags|sot|ast|sav), x (rung: s >= x), ao, au (asks for yes /
no, as chances; None when that side has no bid)}. DraftKings' prices aren't snapped: ESPN still serves them after the
match (scripts/soccer_props_archive.py), and the box score there grades the rows, by player name."""
import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novig

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'props')
LG = {'eng.1': 'EPL', 'esp.1': 'La Liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1', 'usa.1': 'MLS'}
NT = {'PLAYER_GOALS': 'ags', 'SHOTS_ON_TARGET': 'sot', 'ASSISTS': 'ast', 'SAVES': 'sav'}


def novig_rows(lg, now):
    out, seen = [], set()
    try:
        ev = {e['eventId']: e for e in novig.pages('events', league=LG[lg], status='OPEN_PREGAME')}
        mk = novig.pages('markets', league=LG[lg], marketType=','.join(NT), eventStatus='OPEN_PREGAME')
    except Exception as ex:
        print('novig', lg, 'failed:', ex)
        return out
    for m in mk:
        oc, e = m.get('outcomes') or [], ev.get(m.get('eventId'))
        if len(oc) != 2 or not e:
            continue
        b0, b1 = novig.bid(oc[0]), novig.bid(oc[1])
        if not (oc[0].get('name') or '').lower().startswith('over'):
            b0, b1 = b1, b0
        try:
            x = math.floor(float(m['strike'])) + 1
        except (KeyError, TypeError, ValueError):
            continue
        a, _, h = (e.get('description') or '').partition(' @ ')
        k = dt.datetime.fromtimestamp(e['startsTs'] / 1000, dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ') if e.get('startsTs') else None
        if k and k > (now + dt.timedelta(hours=48)).strftime('%Y-%m-%dT%H:%MZ') or not (b0 or b1):
            continue
        if m['eventId'] not in seen:
            seen.add(m['eventId'])
            out.append({'ev': m['eventId'], 'k': k, 'lg': lg, 'h': h, 'a': a})
        out.append({'ev': m['eventId'], 'n': (m.get('description') or '').rsplit(' ', 2)[0], 's': NT[m['marketType']], 'x': x,
                    'ao': round(1 - b1, 4) if b1 else None, 'au': round(1 - b0, 4) if b0 else None})
    return out


def key(r):
    return (r['ev'], r.get('n'), r.get('s'), r.get('x'))


def main():
    now = dt.datetime.now(dt.timezone.utc)
    fn = os.path.join(OUT, f'soccer-{now:%Y-%m}.jsonl')
    prev = os.path.join(OUT, f'soccer-{(now.replace(day=1) - dt.timedelta(days=1)):%Y-%m}.jsonl')
    last = {}
    for f in (prev, fn):
        if os.path.exists(f):
            for ln in open(f):
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                last[key(r)] = r
    rows = []
    for lg in LG:
        for r in novig_rows(lg, now):
            o = last.get(key(r))
            if o and all(o.get(p) == r.get(p) for p in ('ao', 'au')):
                continue
            if 'n' in r:
                r['t'] = now.strftime('%Y-%m-%dT%H:%MZ')
            last[key(r)] = r
            rows.append(r)
    os.makedirs(OUT, exist_ok=True)
    with open(fn, 'a') as f:
        for r in rows:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')
    print('soccer props:', len(rows), 'rows')


if __name__ == '__main__':
    main()
