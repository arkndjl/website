# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESPN pulls for the sweep tests (one host, 1.15 s apart, resumable):

    python3 espn_fetch.py pre OUTDIR     # preseason box scores, seasons 2019-2026 -> OUTDIR/pre_<S>.json
    python3 espn_fetch.py tv OUTDIR      # broadcast markets + notes per regular-season game day 2020-2026 -> OUTDIR/tv_<S>.json

Preseason rows: [event id, date, team, espn player id, name, minutes, starter]. TV rows: {event id: [national
network names, note headlines]}."""
import datetime as dt, gzip, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..', '..')
SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}{x}'
SUM = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={e}'


def get(url):
    for k in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40)
            time.sleep(1.15)
            return json.load(r)
        except Exception as e:
            print(url, e, flush=True); time.sleep(5 * (k + 1))
    return {}


def days():
    G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
    by = {}
    for g in G:
        if g.get('t') == 2 or g.get('t') is None or True:
            d = (dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')) - dt.timedelta(hours=6)).date()
            by.setdefault(g['S'], set()).add(d)
    return by


def pre(out):
    by = days()
    for S in range(2019, 2027):
        fn = os.path.join(out, f'pre_{S}.json')
        if os.path.exists(fn): continue
        first = min(by[S]); rows = []
        for k in range(1, 26):
            d = first - dt.timedelta(days=k)
            for ev in get(SB.format(d=d.strftime('%Y%m%d'), x='&seasontype=1')).get('events', []):
                if ev.get('season', {}).get('type') != 1: continue
                s = get(SUM.format(e=ev['id']))
                for tm in s.get('boxscore', {}).get('players', []):
                    ab = tm['team'].get('abbreviation')
                    for st in tm.get('statistics', []):
                        keys = st.get('keys') or st.get('names') or []
                        mi = next((i for i, k_ in enumerate(keys) if k_.lower() in ('minutes', 'min')), None)
                        for a in st.get('athletes', []):
                            m = a['stats'][mi] if mi is not None and a.get('stats') and len(a['stats']) > mi else None
                            try: m = float(m)
                            except (TypeError, ValueError): m = 0.0
                            if not a.get('athlete', {}).get('id'): continue
                            rows.append([ev['id'], ev['date'][:10], ab, a['athlete']['id'], a['athlete'].get('displayName'), m, int(bool(a.get('starter')))])
        json.dump(rows, open(fn, 'w'))
        print('pre', S, len({r[0] for r in rows}), 'games', len(rows), 'rows', flush=True)


def tv(out):
    by = days()
    for S in range(2020, 2027):
        fn = os.path.join(out, f'tv_{S}.json')
        if os.path.exists(fn): continue
        res = {}
        for d in sorted(by[S]):
            for ev in get(SB.format(d=d.strftime('%Y%m%d'), x='')).get('events', []):
                c = ev['competitions'][0]
                res[ev['id']] = [[b['media']['shortName'] for b in c.get('geoBroadcasts', []) if b.get('market', {}).get('type') == 'National'],
                                 [n.get('headline') for n in c.get('notes', [])]]
        json.dump(res, open(fn, 'w'))
        print('tv', S, len(res), flush=True)


if __name__ == '__main__':
    os.makedirs(sys.argv[2], exist_ok=True)
    {'pre': pre, 'tv': tv}[sys.argv[1]](sys.argv[2])
