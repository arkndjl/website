# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L4 fee check (validation, not a gate): does the held-out xMV gap at Jul 1 forecast the summer fee over the
Transfermarkt value? ewenme/transfers outgoing summer moves from the big five, 2015-2022.

    python3 scripts/research/sweep_nov19/soccer/l4_fees.py <ewenme dir>
"""
import csv
import glob
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
import names as N
import soccer_data as D
import soccer_mv as MV
import soccer_players as SP

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')


def main():
    H = D.load(MV.HIST)['h']
    nm = {}
    for r in D.load(SP.ROWS):
        nm.setdefault((r['S'], str(r['p'])), r['n'])
    res = {}
    pairs = []
    for fn in glob.glob(os.path.join(sys.argv[1], '*.csv')):
        for r in csv.DictReader(open(fn, encoding='utf-8')):
            if r['transfer_movement'] != 'out' or r['transfer_period'] != 'Summer':
                continue
            try:
                fee, y = float(r['fee_cleaned']), int(r['year'])
            except ValueError:
                continue
            if fee <= 0.5 or not 2015 <= y <= 2022:
                continue
            pairs.append((y, r['player_name'], fee))
    hit = []
    for S in range(2015, 2023):
        h = H.get(str(S)) or {}
        M = N.Matcher([{'name': nm.get((S, p)), 'p': p} for p in h if nm.get((S, p))])
        for y, n, fee in pairs:
            if y != S:
                continue
            row, _ = M.find(n)
            if row:
                xmv, mv = h[row['p']]
                if xmv and mv:
                    hit.append((S, math.log(xmv / mv), math.log(fee / mv)))
    a = np.array(hit)
    b = np.polyfit(a[:, 1], a[:, 2], 1)
    res = {'n': len(a), 'corr': round(float(np.corrcoef(a[:, 1], a[:, 2])[0, 1]), 3), 'slope': round(float(b[0]), 3),
           'meanFeeOverTm': round(float(np.mean(a[:, 2])), 3),
           'bySeasonCorr': {int(s): round(float(np.corrcoef(a[a[:, 0] == s, 1], a[a[:, 0] == s, 2])[0, 1]), 3) for s in np.unique(a[:, 0])}}
    json.dump(res, open(os.path.join(OUT, 'l4_fees.json'), 'w'), indent=1)
    print(res)


if __name__ == '__main__':
    main()
