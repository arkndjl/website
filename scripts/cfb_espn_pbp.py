"""ESPN college football play-by-play, drives and venues for every FBS game (free, no CFBD quota), slimmed and
cached per game, for the ESPN-built game-model history (scripts/cfb_espn_md.py).
  python3 scripts/cfb_espn_pbp.py [first season] [last season]
  python3 scripts/cfb_espn_pbp.py --current        # this season, refreshing unfinished weeks (the cfb-board workflow)
Runs scripts/cfb_espn_hist.py's season pull first (scoreboards and closing lines), then one summary call per
finished game with an FBS side. Slim summaries go to scripts/.cache/cfb/espn_pbp/<id>.json.gz; the lines part is
also written where cfb_espn_hist.py keeps it (sum/<id>.json), and the box score where cfb_roster_hist.py does
(box/<id>.json), so none of them pulls the summary twice.
"""
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_espn_hist as H  # noqa: E402
import cfb_roster_hist as R  # noqa: E402

PBP = os.path.join(H.DIR, '..', 'espn_pbp')


def slim(d):
    comp = (d.get('header') or {}).get('competitions') or [{}]
    c = comp[0]
    teams = [{'id': x.get('id'), 'ha': x.get('homeAway'), 'score': x.get('score')} for x in c.get('competitors') or []]
    gi = d.get('gameInfo') or {}
    v = gi.get('venue') or {}
    drives = []
    for i, dr in enumerate((d.get('drives') or {}).get('previous') or []):
        st, en = dr.get('start') or {}, dr.get('end') or {}
        plays = []
        for p in dr.get('plays') or []:
            s, e = p.get('start') or {}, p.get('end') or {}
            plays.append({'t': (p.get('type') or {}).get('text'), 'x': p.get('text'), 'q': (p.get('period') or {}).get('number'),
                          'c': (p.get('clock') or {}).get('displayValue'), 'hs': p.get('homeScore'), 'as': p.get('awayScore'),
                          'y': p.get('statYardage'), 'sc': p.get('scoringPlay'), 'sv': p.get('scoreValue'),
                          'pen': p.get('isPenalty'), 'to': p.get('isTurnover'),
                          'st': (s.get('team') or {}).get('id'), 'dn': s.get('down'), 'ds': s.get('distance'), 'yl': s.get('yardsToEndzone'),
                          'et': (e.get('team') or {}).get('id'), 'edn': e.get('down'), 'eds': e.get('distance'), 'eyl': e.get('yardsToEndzone')})
        drives.append({'n': i + 1, 'tm': (dr.get('team') or {}).get('id'), 'res': dr.get('result'), 'dres': dr.get('displayResult'),
                       'sq': (st.get('period') or {}).get('number'), 's': st.get('yardLine'), 'e': en.get('yardLine'),
                       'np': dr.get('offensivePlays'), 'yds': dr.get('yards'), 'score': dr.get('isScore'), 'plays': plays})
    return {'date': c.get('date'), 'neutral': c.get('neutralSite'), 'conf': c.get('conferenceCompetition'), 'teams': teams,
            'venue': {'id': v.get('id'), 'name': v.get('fullName'), 'city': (v.get('address') or {}).get('city'),
                      'state': (v.get('address') or {}).get('state'), 'grass': v.get('grass')},
            'lines': H.slim_summary(d)['lines'], 'drives': drives}


def pull(i):
    p = os.path.join(PBP, f'{i}.json.gz')
    if os.path.exists(p):
        return True
    d = H.get(f'{H.BASE}/summary?event={i}')
    if d is None:
        return False
    s = slim(d)
    with gzip.open(p, 'wt') as f:
        json.dump(s, f)
    bp = os.path.join(R.BOX, f'{i}.json')     # box scores for the roster prior (scripts/cfb_roster_hist.py)
    if not os.path.exists(bp):
        with open(bp, 'w') as f:
            json.dump(R.slim_box(d), f)
    sp = os.path.join(H.DIR, 'sum', f'{i}.json')
    if not os.path.exists(sp):
        with open(sp, 'w') as f:
            json.dump({'lines': s['lines']}, f)
    return True


def load(i):
    p = os.path.join(PBP, f'{i}.json.gz')
    if not os.path.exists(p):
        return None
    with gzip.open(p, 'rt') as f:
        return json.load(f)


_once = H.once


def once(name, url, slim_=lambda x: x):
    # season()'s lines pull: take the summary through pull(), which keeps the plays too
    if name.startswith('sum/'):
        pull(name[4:-5])
    return _once(name, url, slim_)


H.once = once

if __name__ == '__main__':
    for x in ('sum', 'odds', 'box'):
        os.makedirs(os.path.join(H.DIR, x), exist_ok=True)
    os.makedirs(PBP, exist_ok=True)
    if sys.argv[1:2] == ['--current']:
        # this season (August on), for the live game model: scoreboards with an unfinished game are pulled again
        import datetime
        now = datetime.date.today()
        a = b = now.year if now.month >= 8 else now.year - 1
        for f in os.listdir(H.DIR):
            if f.startswith(f'sb{a}_'):
                with open(os.path.join(H.DIR, f)) as fh:
                    if any(not g['done'] for g in json.load(fh)):
                        os.remove(os.path.join(H.DIR, f))
    else:
        a, b = (int(x) for x in (sys.argv[1:3] if len(sys.argv) > 2 else (2015, 2026)))
    for S in range(a, b + 1):
        H.season(S)
        with open(os.path.join(H.DIR, f'games{S}.json')) as f:
            games = json.load(f)
        ids = [g['id'] for g in games if g['done'] and g.get('grp') == 'fbs']
        with ThreadPoolExecutor(16) as ex:
            ok = list(ex.map(pull, ids))
        print(S, len(ids), 'FBS-side games,', sum(ok), 'with a summary', flush=True)
