"""CFB recruit position: ESPN's high school listing + size + grade -> the position group he is listed at on
college rosters (cfbfastR rosters, years 2-4, matched by ESPN athlete id). Held out by class.
    python3 scripts/research/recruit_pos_nov28/cfb_pos.py [--rosters DIR]"""
import csv, gzip, json, math, os, sys
from collections import Counter, defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mnl

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ROS = sys.argv[sys.argv.index('--rosters') + 1] if '--rosters' in sys.argv else os.path.join(ROOT, 'scripts', '.cache', 'cfb_rosters')
G = ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB', 'ST']
RMAP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'G': 'OL', 'OT': 'OL', 'C': 'OL',
        'DL': 'DL', 'DT': 'DL', 'NT': 'DL', 'DE': 'DL', 'EDGE': 'DL', 'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB',
        'DB': 'DB', 'S': 'DB', 'CB': 'DB', 'PK': 'ST', 'P': 'ST', 'LS': 'ST'}
# ESPN high school codes -> family (the size terms are fit within family)
FAM = {'QB-DT': 'QB', 'QB-PP': 'QB', 'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE-Y': 'TE', 'TE-H': 'TE', 'TE': 'TE',
       'OT': 'OL', 'OG': 'OL', 'OC': 'OL', 'IOL': 'OL', 'DT': 'DL', 'DL': 'DL', 'DE': 'ED', 'EDGE': 'ED', 'OLB': 'ED',
       'ILB': 'LB', 'LB': 'LB', 'CB': 'DB', 'S': 'DB', 'ATH': 'ATH', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
CODES = sorted(FAM)
FAMS = sorted(set(FAM.values()))


def rosters():
    out = defaultdict(list)
    for f in sorted(os.listdir(ROS)):
        y = int(f[1:5])
        for r in csv.DictReader(open(os.path.join(ROS, f))):
            g = RMAP.get(r['position'])
            if g: out[r['athlete_id']].append((y, g))
    return out


def target(c, seen):
    s = [g for y, g in seen if c + 1 <= y <= c + 3] or [g for y, g in seen if y == c]
    if not s: return None
    v = np.zeros(len(G))
    for g in s: v[G.index(g)] += 1
    return v / v.sum()


SZ = {}   # size centring, set once from the training rows


def feats(code, ht, wt, grade, extra=(), size=True, gr=True):
    """intercept, code one-hot, then within-family size (ht, wt, wt^2 standardised) and grade"""
    x = [1.0] + [1.0 if code == c else 0.0 for c in CODES]
    fam = FAM.get(code)
    h = ((ht or SZ['ht']) - SZ['ht']) / SZ['hs']; w = ((wt or SZ['wt']) - SZ['wt']) / SZ['ws']
    if size:
        for f in FAMS: x += [h, w, w * w, h * w] if fam == f else [0.0] * 4
        x += [0.0 if ht else 1.0]
    if gr:
        g = ((grade or SZ['gr']) - SZ['gr']) / SZ['gs']
        for f in FAMS: x += [g] if fam == f else [0.0]
    return x + list(extra)


def load():
    d = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'arkstars_hist_cfb.json.gz')))
    C = {k: i for i, k in enumerate(d['cols'])}
    ros = rosters(); rows = []
    for y, rs in d['classes'].items():
        y = int(y)
        for r in rs:
            i = r[C['id']]; code = r[C['pos']]
            if not i or code not in FAM: continue
            t = target(y, ros.get(i, []))
            if t is None: continue
            rows.append({'c': y, 'id': i, 'name': r[C['name']], 'code': code, 'ht': r[C['ht']], 'wt': r[C['wt']],
                         'grade': r[C['grade']], 'tid': r[C['tid']], 'y': t})
    return rows


def run(rows, mk, lam):
    """leave one class out; returns per-row log loss and P"""
    cls = sorted({r['c'] for r in rows})
    X = np.array([mk(r) for r in rows]); Y = np.array([r['y'] for r in rows]); c = np.array([r['c'] for r in rows])
    P = np.zeros_like(Y)
    for k in cls:
        tr = c != k
        B = mnl.fit(X[tr], Y[tr], lam)
        P[~tr] = mnl.predict(X[~tr], B)
    return mnl.logloss(P, Y), P


def main():
    rows = [r for r in load() if 2014 <= r['c'] <= 2024]
    hs = [r['ht'] for r in rows if r['ht']]; ws = [r['wt'] for r in rows if r['wt']]; gs = [r['grade'] for r in rows if r['grade']]
    SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)), gr=float(np.mean(gs)), gs=float(np.std(gs)))
    print('rows', len(rows), Counter(r['code'] for r in rows)['ATH'], 'ATH', flush=True)
    c = np.array([r['c'] for r in rows]); ath = np.array([r['code'] == 'ATH' for r in rows])
    Y = np.array([r['y'] for r in rows])
    specs = {'listed': (lambda r: feats(r['code'], r['ht'], r['wt'], r['grade'], size=False, gr=False), 1.0),
             'size': (lambda r: feats(r['code'], r['ht'], r['wt'], r['grade'], gr=False), 1.0),
             'size+grade': (lambda r: feats(r['code'], r['ht'], r['wt'], r['grade']), 1.0)}
    res = {}
    for nm, (mk, lam) in specs.items():
        ll, P = run(rows, mk, lam)
        top = (P.argmax(1) == Y.argmax(1))
        res[nm] = {'ll': ll, 'P': P}
        print(nm, 'LL %.4f  acc %.3f  ATH LL %.4f acc %.3f' % (ll.mean(), top.mean(), ll[ath].mean(), top[ath].mean()), flush=True)
    for a, b in [('listed', 'size'), ('size', 'size+grade')]:
        dl = [res[a]['ll'][c == k].mean() - res[b]['ll'][c == k].mean() for k in sorted(set(c))]
        da = [res[a]['ll'][(c == k) & ath].mean() - res[b]['ll'][(c == k) & ath].mean() for k in sorted(set(c))]
        t = lambda v: np.mean(v) / (np.std(v, ddof=1) / math.sqrt(len(v)))
        print(a, '->', b, 'all t %.2f wins %d/%d | ATH t %.2f wins %d' % (t(dl), sum(x > 0 for x in dl), len(dl), t(da), sum(x > 0 for x in da)))


if __name__ == '__main__':
    main()


def school_feats(rows, a=4.0):
    """for ATH rows: the signing school's earlier ATH signees (classes before his), where they played, shrunk to
    the all-school ATH mix with a prior of a recruits; log ratio to the mix. Zero for everyone else."""
    by = defaultdict(list)
    for r in rows:
        if r['code'] == 'ATH': by[r['tid']].append(r)
    mix = np.mean([r['y'] for r in rows if r['code'] == 'ATH'], 0) + 1e-3
    for r in rows:
        r['sch'] = [0.0] * len(G)
        if r['code'] != 'ATH' or not r['tid']: continue
        past = [q['y'] for q in by[r['tid']] if q['c'] < r['c']]
        s = (np.sum(past, 0) if past else 0) + a * mix
        r['sch'] = list(np.log(s / (len(past) + a) / mix))
        r['nsch'] = len(past)


def main2():
    rows = [r for r in load() if 2014 <= r['c'] <= 2024]
    hs = [r['ht'] for r in rows if r['ht']]; ws = [r['wt'] for r in rows if r['wt']]; gs = [r['grade'] for r in rows if r['grade']]
    SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)), gr=float(np.mean(gs)), gs=float(np.std(gs)))
    school_feats(rows)
    c = np.array([r['c'] for r in rows]); ath = np.array([r['code'] == 'ATH' for r in rows]); Y = np.array([r['y'] for r in rows])
    keep = c >= 2016    # two classes of school history first
    res = {}
    for nm, mk in {'size+grade': lambda r: feats(r['code'], r['ht'], r['wt'], r['grade']),
                   '+school': lambda r: feats(r['code'], r['ht'], r['wt'], r['grade'], extra=r['sch'])}.items():
        ll, P = run(rows, mk, 1.0); res[nm] = ll
        top = P.argmax(1) == Y.argmax(1)
        print(nm, 'ATH 2016+ LL %.4f acc %.3f' % (ll[ath & keep].mean(), top[ath & keep].mean()))
    da = [res['size+grade'][(c == k) & ath].mean() - res['+school'][(c == k) & ath].mean() for k in range(2016, 2025)]
    print('school t %.2f wins %d/%d' % (np.mean(da) / (np.std(da, ddof=1) / math.sqrt(len(da))), sum(x > 0 for x in da), len(da)))
