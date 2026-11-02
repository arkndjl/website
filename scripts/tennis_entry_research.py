"""Tennis entry status as a match-model term (research; Nov 2 2026). New information the shipped model lacks: how a
player got into the draw (Sackmann's winner_entry / loser_entry).
  q   came through qualifying (Q) or as a lucky loser (LL): match-sharp, on site, and the Elo already moved on the
      qualifying wins only if they are in the data
  pr  protected ranking (PR) or special exempt (SE): back from a long injury, so the rating is stale
  wc  wildcard (WC): home federation picks, often young risers the rating lags
Each A minus B on top of the shipped blend's walk-forward chance (tennis_model.wf_probs, every context term in), fit
on all earlier years (walk-forward), tune 2014-22, held out 2023-26, paired log loss t clustered by tournament; the
shipped close only covers 2025+, so the close test is 2026 fit on 2025.
Needs the tennis research cache (rebuilt from /mnt/project-files/tennis/matches.csv.gz like
scripts/sweep_oct31/tennis_home.py) and the Sackmann archive (sackmann.tgz) unpacked; pass its folder as argv[1].
Result (Nov 2 2026, 63.4k scored main-draw rows 2012-26): FAILED. q tune t +1.99 / held +0.41, pr +1.35 / +0.26,
wc -0.14 / +1.23, all three +1.04 / +1.25 (positive = worse). The model already has rest, matches in 30 days and age.
Writes data/tennis_entry_research.json."""
import csv
import glob
import gzip
import json
import math
import os
import shutil
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import tennis_data as T  # noqa: E402

SACK = sys.argv[1]
os.makedirs(T.CACHE, exist_ok=True)
if not os.path.exists(T.HIST):
    def num(x, f=int):
        return f(x) if x not in ('', None) else None
    rows, tn = [], {}
    for r in csv.reader(gzip.open('/mnt/project-files/tennis/matches.csv.gz', 'rt')):
        if r[0] == 'd':
            continue
        ws = [num(x) for x in r[11:20]]; ls = [num(x) for x in r[20:29]]
        rows.append([int(r[0]), r[1], r[2], r[3], r[4], int(r[5]), r[6], r[7], r[8], r[9],
                     ws if any(v is not None for v in ws) else None, ls if any(v is not None for v in ls) else None,
                     num(r[29]), num(r[30]), num(r[31], float), num(r[32], float)])
        tn[r[6]] = r[10]
    json.dump({'rows': rows, 'tn': tn}, gzip.open(T.HIST, 'wt'))
    shutil.copy('/mnt/project-files/tennis/players.json.gz', T.PLAYERS)

ENT = {}
for tour, pre in (('atp', 'a'), ('wta', 'w')):
    for f in glob.glob(os.path.join(SACK, tour, f'{tour}_matches_*.csv')):
        for r in csv.DictReader(open(f, encoding='utf-8', errors='replace')):
            ENT[(pre + r['tourney_id'], pre + r['winner_id'], pre + r['loser_id'])] = ((r.get('winner_entry') or '').upper(),
                                                                                      (r.get('loser_entry') or '').upper())
print('entries', len(ENT), flush=True)

import tennis_model as M  # noqa: E402
import harness as HH  # noqa: E402
rows, players, tn = T.load()
P = json.load(open(ROOT + '/data/tennis_fit.json'))['params']
_, rec = M.run(rows, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100))
pw = M.wf_probs(rec, P)


def flags(e):
    return [float(e in ('Q', 'LL')), float(e in ('PR', 'SE')), float(e == 'WC')]


X, P0, G, Y, C, hit = [], [], [], [], [], 0
for x, p in zip(rec, pw):
    r = x[0]
    yr = r[0] // 10000
    if yr < 2012:
        continue
    e = ENT.get((r[6], r[7], r[8]))
    if e is None:
        continue
    hit += 1
    fw, fl = flags(e[0]), flags(e[1])
    X.append([a - b for a, b in zip(fw, fl)]); P0.append(p); G.append(r[6]); Y.append(yr)
    C.append(r[14] if r[14] and 0 < r[14] < 1 else None)
X = np.array(X); P0 = np.array(P0); Y = np.array(Y); G = np.array(G)
z0 = np.log(P0 / (1 - P0))
print('scored rows with entry', hit, 'share nonzero', (X != 0).mean(0).round(3).tolist(), flush=True)


def fit(idx, cols, base):
    F = X[idx][:, cols]; Z = base[idx]
    Xf = np.vstack([F, -F]); off = np.r_[Z, -Z]; yy = np.r_[np.ones(len(F)), np.zeros(len(F))]
    b = np.zeros(len(cols))
    for _ in range(25):
        p = 1 / (1 + np.exp(-(off + Xf @ b)))
        H = (Xf * (p * (1 - p))[:, None]).T @ Xf + 1e-3 * np.eye(len(cols))
        b += np.linalg.solve(H, Xf.T @ (yy - p))
    return b


def test(cols, base, years, label):
    nl, ol, gg = [], [], []
    for yr in years:
        tr = (Y < yr) & ~np.isnan(base); te = (Y == yr) & ~np.isnan(base)
        if tr.sum() < 2000 or te.sum() == 0:
            continue
        b = fit(tr, cols, base)
        z = base[te] + X[te][:, cols] @ b
        nl += list(np.log1p(np.exp(-z))); ol += list(np.log1p(np.exp(-base[te]))); gg += list(G[te])
    r = HH.paired(nl, ol, cluster=np.array(gg))
    ok = ~np.isnan(base)
    out = dict(t=round(r['t'], 2), dLL_e4=round(float(r['d']) * 1e4, 2), n=r['n'],
               b=[round(float(v), 3) for v in fit(ok, cols, base)])
    print(label, out, flush=True)
    return out


out = {'note': __doc__.split('\n')[0], 'nRows': int(len(X)), 'shareNonzero': dict(zip(['q', 'pr', 'wc'], (X != 0).mean(0).round(4).tolist()))}
for cols, nm in (([0], 'q'), ([1], 'pr'), ([2], 'wc'), ([0, 1, 2], 'all three')):
    out[nm] = {'tune': test(cols, z0, range(2014, 2023), nm + ' tune'), 'held': test(cols, z0, range(2023, 2027), nm + ' held')}
cz = np.array([math.log(c / (1 - c)) if c else np.nan for c in C])
for cols, nm in (([0], 'q'), ([1], 'pr'), ([2], 'wc')):
    out[nm]['vsClose2026'] = test(cols, cz, range(2026, 2027), nm + ' vs close 2026 (fit 2025)')
json.dump(out, open(os.path.join(ROOT, 'data', 'tennis_entry_research.json'), 'w'), indent=1)
