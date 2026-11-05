#!/usr/bin/env python3
"""Every board's roster vs RotoWire's clubs (Noah, Nov 5 2026: "go back through the past of this season to make sure
all rosters are accurate").

RotoWire's club for each player its news feed named this season (scripts/rotowire_moves.py: teams) is the reference.
Each published file that puts a player on a club is read: the depth charts (static/data/depth/*.json) and every
player list with a name ('n') and a club ('t' current club, or 'tm'). A row is joined to RotoWire through the shared
name matcher (scripts/names.py): name + club first, then the exact name on another club (position must fit; two
players with one name are left alone). Flags:
  moved     RotoWire has him on another club
  released  RotoWire has him as a free agent (waived, released, cut, practice squad cut)
  exit      college: RotoWire news says he left the program (dismissed, portal, medical retirement) after the
            site's last game for him; he is still on the chart

Writes data/roster_audit.json: {asof, sports: {sport: {rows, joined, ok, flags: [...], by_file: {...}}}}.

  python3 scripts/roster_audit.py            # audit
  python3 scripts/roster_audit.py --show     # print the flags
  python3 scripts/roster_audit.py --fix      # retag the published boards now (the builds do the same each run)
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rotowire_moves as RM  # noqa: E402

ROOT = RM.RW.ROOT
OUT = os.path.join(ROOT, 'data', 'roster_audit.json')
SP = RM.SITE


def _files(sport):
    out = [f'static/data/depth/{sport}.json']
    pat = {'nfl': ['nfl-war.json', 'xaav-nfl.json', 'pctl-nfl.json', 'nfl-fantasy.json', 'personnel/*.json'],
           'nba': ['nba-proj.json', 'nba-xpm/2027.json', 'xaav-nba.json', 'pctl-nba.json'],
           'nhl': ['nhl-war/2027.json', 'xaav-nhl.json', 'pctl-nhl.json', 'lines/nhl.json'],
           'cfb': [], 'cbb': []}[sport]
    for p in pat:
        out += sorted(os.path.relpath(f, ROOT) for f in glob.glob(os.path.join(ROOT, 'static', 'data', p)))
    return out


def rows(path):
    """(name, club, pos, field) for each player the file puts on a club"""
    d = json.load(open(os.path.join(ROOT, path)))
    out = []
    if '/depth/' in path:
        for t in d.get('teams') or []:
            for u in t.get('units') or []:
                for slot, ps in u.get('s') or []:
                    for p in ps:
                        if p and isinstance(p[0], str):
                            out.append((p[0], t['t'], slot, 'depth'))
        return out

    def walk(o):
        if isinstance(o, dict):
            n, t = o.get('n'), o.get('t') if isinstance(o.get('t'), str) and len(o.get('t') or '') <= 4 else o.get('tm')
            if isinstance(n, str) and isinstance(t, str) and t and ' ' in n.strip():
                out.append((n, t, o.get('pos') or o.get('p'), 't' if t == o.get('t') else 'tm'))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return out


def audit(sport):
    R = RM.Ref(sport)
    res = {'rows': 0, 'joined': 0, 'flags': [], 'by_file': {}}
    seen = set()
    for f in _files(sport):
        try:
            rs = rows(f)
        except (OSError, ValueError):
            continue
        bf = res['by_file'].setdefault(f, {'rows': 0, 'flags': 0})
        for name, club, pos, fld in rs:
            bf['rows'] += 1
            res['rows'] += 1
            c = R.check(name, club, pos)
            if c and c['flag'] == 'minors' and fld != 'depth':
                c = None          # an AHL assignment keeps him the club's; only charts drop him
            if not c or (f, name, club) in seen:
                continue
            seen.add((f, name, club))
            bf['flags'] += 1
            res['flags'].append(dict(c, file=f, field=fld, player=name, site=club, pos=pos))
    res['players'] = len(R.rows)
    return res


# the published files the builds retag (same calls as the builds: scripts/nfl_war.py, xaav.py, nba_proj.py,
# nfl_fantasy.py, player_pctl.py, nba_xpm.py, nhl_players.py), for --fix between builds
FIX = [('nfl', 'static/data/nfl-war.json', dict(club='t', pos='pos', hist='tm')),
       ('nfl', 'static/data/xaav-nfl.json', dict(club='tm', released=True)),
       ('nfl', 'static/data/nfl-fantasy.json', dict(club='t', pos='pos', released=True)),
       ('nfl', 'static/data/pctl-nfl.json', dict(club='tm')),
       ('nba', 'static/data/nba-proj.json', dict(club='tm', released=True)),
       ('nba', 'static/data/pctl-nba.json', dict(club='tm')),
       ('nba', 'static/data/nba-xpm/2027.json', dict(club='tm')),
       ('nhl', 'static/data/xaav-nhl.json', dict(club='tm', released=True)),
       ('nhl', 'static/data/pctl-nhl.json', dict(club='tm')),
       ('nhl', 'static/data/nhl-war/2027.json', dict(club='tm'))]


def fix():
    for sport, f, kw in FIX:
        fn = os.path.join(ROOT, f)
        try:
            d = json.load(open(fn))
        except (OSError, ValueError):
            continue
        if RM.retag(sport, d.get('players') or [], label=f.split('/')[-1], **kw):
            with open(fn, 'w') as fh:
                json.dump(d, fh, separators=(',', ':'), allow_nan=False)


def main():
    if '--fix' in sys.argv:
        fix()
    out = {'asof': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'sports': {}}
    for s in SP:
        r = audit(s)
        out['sports'][s] = r
        print(f"{s}: {r['rows']} rows, {r['players']} RotoWire players, {len(r['flags'])} flags")
        if '--show' in sys.argv:
            for x in r['flags']:
                print('   ', x['flag'], x['file'].split('static/data/')[-1], x['field'], x['player'], x['site'], '->', x['rotowire'],
                      x['d'], x['head'])
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1, sort_keys=True)
    return out


if __name__ == '__main__':
    main()
