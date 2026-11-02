"""Parse Match Charting Project point files into one compact table (pickle in the scratch dir).
Run: python3 -I parse_mcp.py <mcp_dir> <out.pkl>"""
import csv, re, sys
import pandas as pd

SRC, OUT = sys.argv[1], sys.argv[2]
FILES = {'M': ['charting-m-points-to-2009.csv', 'charting-m-points-2010s.csv', 'charting-m-points-2020s.csv'],
         'W': ['charting-w-points-to-2009.csv', 'charting-w-points-2010s.csv', 'charting-w-points-2020s.csv']}
PV = {'0': 0, '15': 1, '30': 2, '40': 3, 'AD': 4}


def sdir(code):
    s = code.lstrip('c')
    return s[0] if s[:1] in ('4', '5', '6') else ''


def fault(code):
    s = code.lstrip('c')
    if s == 'V':
        return True
    m = re.match(r'^[0456]?[+;^]*(.)', s)
    return bool(m) and m.group(1) in 'nwdxge!V'


def ptsum(pts):
    try:
        a, b = pts.split('-')
        return (PV[a] + PV[b]) if a in PV and b in PV else int(a) + int(b)
    except Exception:
        return -1


rows = []
for g, fl in FILES.items():
    players = {}
    for r in csv.DictReader(open(f'{SRC}/charting-{g.lower()}-matches.csv', encoding='utf-8', errors='replace')):
        players[r['match_id']] = (r['Player 1'], r['Player 2'], r['Date'], r['Surface'], r['Best of'])
    for f in fl:
        for r in csv.DictReader(open(f'{SRC}/{f}', encoding='utf-8', errors='replace')):
            mid = r['match_id']
            if mid not in players:
                continue
            s1, s2 = r['1st'].strip(), r['2nd'].strip()
            if not s1 or s1[0] in 'SRPQ':
                continue
            try:
                svr, win = int(r['Svr']), int(r['PtWinner'])
                st1, st2, g1, g2 = int(r['Set1']), int(r['Set2']), int(r['Gm1']), int(r['Gm2'])
                pt = int(r['Pt'])
            except ValueError:
                continue
            if svr not in (1, 2) or win not in (1, 2):
                continue
            p1, p2, date, surf, bo = players[mid]
            f1 = bool(s2)
            df = fault(s2) if f1 else False
            if f1 and df and win == svr:
                continue                      # inconsistent record
            if f1 and not df and s2[:1] in 'SRPQ':
                continue
            rows.append((g, mid, pt, st1, st2, g1, g2, r['Pts'], ptsum(r['Pts']), r['TbSet'], svr,
                         p1 if svr == 1 else p2, p2 if svr == 1 else p1, sdir(s1), f1, sdir(s2) if f1 else '',
                         df, win == svr, date[:4], surf, bo))
df = pd.DataFrame(rows, columns=['g', 'mid', 'pt', 'set1', 'set2', 'gm1', 'gm2', 'pts', 'ptsum', 'tbset', 'svr',
                                 'server', 'returner', 'dir1', 'fault1', 'dir2', 'df', 'won', 'year', 'surface', 'bo'])
for c in ('g', 'mid', 'server', 'returner', 'dir1', 'dir2', 'year', 'surface', 'bo', 'tbset', 'pts'):
    df[c] = df[c].astype('category')
df.to_pickle(OUT)
print(df.groupby('g').agg(points=('pt', 'size'), matches=('mid', 'nunique')))
