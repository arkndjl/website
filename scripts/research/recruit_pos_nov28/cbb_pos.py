"""CBB recruit position: the high school listing (PG, SG, CG, SF, PF, C) + height, weight and rank -> where he plays in
college, from Barttorvik's role (minutes-weighted, first two seasons) put on five spots: Pure/Scoring PG = PG,
Combo G = half PG half SG, Wing G = SG, Wing F = SF, Stretch 4 = PF, PF/C = half PF half C, C = C. Held out by class.
    python3 scripts/research/recruit_pos_nov28/cbb_pos.py"""
import gzip, json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import mnl
import cbb_data as D

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
S5 = ['PG', 'SG', 'SF', 'PF', 'C']
ROLE = {'Pure PG': {'PG': 1}, 'Scoring PG': {'PG': 1}, 'Combo G': {'PG': .5, 'SG': .5}, 'Wing G': {'SG': 1},
        'Wing F': {'SF': 1}, 'Stretch 4': {'PF': 1}, 'PF/C': {'PF': .5, 'C': .5}, 'C': {'C': 1}}
CODES = ['PG', 'SG', 'CG', 'SF', 'PF', 'C']
FAM = {'PG': 'G', 'SG': 'G', 'CG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'B'}
SZ = {}


def bt_index(years):
    idx = defaultdict(list)
    for y in years:
        for r in D.load_bt(y):
            if r.get('role') in ROLE: idx[(y, r['key'])].append(r)
    return idx


def target(rec, idx):
    c = rec.get('college') or {}
    y1 = c.get('y1') or rec['cls'] + 1
    v = np.zeros(5); tm = D.N.key(c.get('team') or '')
    for y in (y1, y1 + 1):
        for r in idx.get((y, D.N.key(rec['name'])), []):
            if tm and D.N.key(r['team']) != tm and y == y1: continue
            m = (r['min_per'] or 0) * (r['gp'] or 0)
            for s, f in ROLE[r['role']].items(): v[S5.index(s)] += m * f
    return v / v.sum() if v.sum() > 0 else None


def feats(code, ht, wt, rk, size=True, rank=True):
    x = [1.0] + [1.0 if code == c else 0.0 for c in CODES]
    if size:
        h = ((ht or SZ['ht']) - SZ['ht']) / SZ['hs']; w = ((wt or SZ['wt']) - SZ['wt']) / SZ['ws']
        for f in 'GFB': x += [h, w, h * h] if FAM.get(code) == f else [0.0] * 3
        x += [0.0 if wt else 1.0]
    if rank:
        lr = (math.log(rk) if rk else math.log(400)) - SZ['lr']
        x += [lr, lr * (((ht or SZ['ht']) - SZ['ht']) / SZ['hs'])]
    return x


def load():
    d = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))['recruits']
    idx = bt_index(range(2010, 2027))
    rows = []
    for r in d:
        if r.get('pos') not in FAM: continue
        t = target(r, idx)
        if t is None: continue
        rows.append({'c': r['cls'], 'name': r['name'], 'code': r['pos'], 'ht': r['ht'], 'wt': r['wt'], 'rk': r['rk'], 'y': t})
    return rows


def ttest(v):
    return np.mean(v) / (np.std(v, ddof=1) / math.sqrt(len(v)))


def main():
    rows = load()
    hs = [r['ht'] for r in rows if r['ht']]; ws = [r['wt'] for r in rows if r['wt']]
    SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)),
              lr=float(np.mean([math.log(r['rk']) for r in rows if r['rk']])))
    print('rows', len(rows), Counter(r['c'] for r in rows))
    X = {}; Y = np.array([r['y'] for r in rows]); c = np.array([r['c'] for r in rows])
    specs = {'listed': lambda r: feats(r['code'], r['ht'], r['wt'], r['rk'], False, False),
             'size': lambda r: feats(r['code'], r['ht'], r['wt'], r['rk'], True, False),
             'size+rank': lambda r: feats(r['code'], r['ht'], r['wt'], r['rk'])}
    res = {}
    for nm, mk in specs.items():
        Xm = np.array([mk(r) for r in rows]); P = np.zeros_like(Y)
        for k in sorted(set(c)):
            B = mnl.fit(Xm[c != k], Y[c != k], 1.0); P[c == k] = mnl.predict(Xm[c == k], B)
        ll = mnl.logloss(P, Y); res[nm] = ll
        print(nm, 'LL %.4f acc %.3f' % (ll.mean(), (P.argmax(1) == Y.argmax(1)).mean()))
    for a, b in [('listed', 'size'), ('size', 'size+rank')]:
        dl = [res[a][c == k].mean() - res[b][c == k].mean() for k in sorted(set(c))]
        print(a, '->', b, 't %.2f wins %d/%d' % (ttest(dl), sum(x > 0 for x in dl), len(dl)))


if __name__ == '__main__':
    main()
