#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Launch Madden team sheets (madden_pull.py) -> one table: {season: [[name, team, position, overall], ...]}.

    python3 -I madden_parse.py <sheets dir> <out json>

Only the per-team launch sheets are read (never roster updates, final rosters or all-star teams). Edition E is the
season 2000 + E - 1."""
import glob
import json
import os
import re
import sys

import openpyxl

TEAMS = {'arizona_cardinals': 'ARI', 'atlanta_falcons': 'ATL', 'baltimore_ravens': 'BAL', 'buffalo_bills': 'BUF', 'carolina_panthers': 'CAR',
         'chicago_bears': 'CHI', 'cincinnati_bengals': 'CIN', 'cleveland_browns': 'CLE', 'dallas_cowboys': 'DAL', 'denver_broncos': 'DEN',
         'detroit_lions': 'DET', 'green_bay_packers': 'GB', 'houston_texans': 'HOU', 'indianapolis_colts': 'IND', 'jacksonville_jaguars': 'JAX', 'jacksonville_jagaurs': 'JAX',
         'kansas_city_chiefs': 'KC', 'las_vegas_raiders': 'LV', 'oakland_raiders': 'LV', 'los_angeles_chargers': 'LAC', 'san_diego_chargers': 'LAC',
         'los_angeles_rams': 'LA', 'st._louis_rams': 'LA', 'miami_dolphins': 'MIA', 'minnesota_vikings': 'MIN', 'new_england_patriots': 'NE',
         'new_orleans_saints': 'NO', 'new_york_giants': 'NYG', 'new_york_jets': 'NYJ', 'philadelphia_eagles': 'PHI', 'pittsburgh_steelers': 'PIT',
         'san_francisco_49ers': 'SF', 'seattle_seahawks': 'SEA', 'tampa_bay_buccaneers': 'TB', 'tennessee_titans': 'TEN',
         'washington_redskins': 'WAS', 'washington_football_team': 'WAS', 'washington_commanders': 'WAS'}


def norm(h):
    return re.sub(r'[^a-z]', '', str(h or '').lower())


def sheet(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    head = [norm(h) for h in next(it)]
    ix = lambda *names: next((head.index(n) for n in names if n in head), None)
    fi, li, ni = ix('firstname'), ix('lastname'), ix('fullname', 'name', 'player')
    pi, oi = ix('position', 'pos'), ix('ovr', 'overallrating', 'overall')
    out = []
    for r in it:
        try:
            name = f'{r[fi]} {r[li]}' if fi is not None and li is not None else str(r[ni])
            out.append([name.strip(), str(r[pi]).strip(), int(float(r[oi]))])
        except (TypeError, ValueError, IndexError):
            continue
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    out = {}
    for d in sorted(os.listdir(src)):
        rows = []
        for f in sorted(glob.glob(os.path.join(src, d, '*.xlsx'))):
            b = os.path.basename(f).lower()
            t = next((v for k, v in TEAMS.items() if b.startswith(k)), None)
            if not t or 'madden_nfl_' + d not in b.replace('(', '_').replace('__', '_'):
                continue
            rows += [[n, t, p, o] for n, p, o in sheet(f)]
        if len({r[1] for r in rows}) == 32:
            out[str(2000 + int(d) - 1)] = rows
        print(d, len(rows), len({r[1] for r in rows}), flush=True)
    json.dump(out, open(dst, 'w'))


if __name__ == '__main__':
    main()
