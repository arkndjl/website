# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""A5: Wooden model with winner-only labels vs rank-ordered labels from All-America consensus points.
    python3 a5_cbb_labels.py <dir with aa_<year>.txt raw wikitext> <out.json>
Pools as scripts/awards_cbb.py; team columns from the in-repo game archive (win share, mean margin)."""
import collections, csv, gzip, json, math, os, re, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as NM, awards_engine as E, awards_cbb as C
from awards_research import t_sf
COLS = ['bpm', 'ppg', 'wp', 'marg', 'mpg', 'p5']
SEASONS = range(2014, 2026)


def aa(fn):
    """[(name, school, consensus points)] from the selector table (3/2/1 points per first/second/third team)"""
    s = open(fn, encoding='utf-8').read()
    i = s.find('wikitable sortable')
    out = []
    for row in s[i:s.find('|}', i)].split('|-'):
        c = [x.strip() for x in row.strip().lstrip('|').split('||')]
        if len(c) < 7: continue
        m = re.search(r'\{\{sortname\|([^|}]+)\|([^|}]+)', c[0])
        name = f'{m.group(1)} {m.group(2)}' if m else re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', c[0]).strip()
        school = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', c[1]).strip()
        pts = 0
        for x in c[2:6]:
            t = re.search(r'Center\|(\d)', x)
            if t: pts += 4 - int(t.group(1))
        if name and pts: out.append((name, school, pts))
    return out


def teams():
    T = collections.defaultdict(lambda: [0, 0, 0.0])
    for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_games_hist.json.gz'))):
        if g.get('hs') is None or g.get('as') is None or g.get('stype', 2) == 3: continue
        for nm, d in ((g['hn'], g['hs'] - g['as']), (g['an'], g['as'] - g['hs'])):
            t = T[(g['season'], NM.team_key(nm))]
            t[0] += d > 0; t[1] += 1; t[2] += d
    return T


def main(wdir, outfn=None):
    W = C.winners()
    T = teams()
    by = collections.defaultdict(list)
    for r in csv.DictReader(open(C.SEASONS_CSV)):
        if int(r['year']) in SEASONS: by[int(r['year'])].append(r)
    races1, races3, seas, info = [], [], [], []
    for s in SEASONS:
        pool = []
        for r in by[s]:
            if float(r['min_per'] or 0) < 40 or float(r['gp'] or 0) < 20: continue
            x = C.row(r, {})
            t = T.get((s, NM.team_key(r['team'])))
            if not t or t[1] < 10: x['wp'], x['marg'] = .5, 0.0
            else: x['wp'], x['marg'] = t[0] / t[1], t[2] / t[1]
            pool.append(x)
        m = NM.Matcher(pool, name='n', team='tm', pos=None, sport='basketball')
        hit, _ = m.find(W[s][0], team=W[s][1])
        if hit is None: hit, _ = m.find(W[s][0])
        if hit is None: print(s, 'winner outside pool', W[s]); continue
        w = pool.index(hit)
        lab = sorted(aa(os.path.join(wdir, f'aa_{s}.txt')), key=lambda a: (-a[2], a[0]))
        order = [w]
        for name, school, pts in lab:
            h, _ = m.find(name, team=school)
            if h is None: h, _ = m.find(name)
            if h is None: continue
            i = pool.index(h)
            if i not in order: order.append(i)
            if len(order) == 3: break
        X = [[c[k] for k in COLS] for c in pool]
        races1.append((X, [w])); races3.append((X, order)); seas.append(s)
        info.append((s, hit['n'], [pool[i]['n'] for i in order], len(lab), len(pool)))
        print(info[-1], flush=True)
    d = []
    for k, s in enumerate(seas):
        tr1 = [r for j, r in enumerate(races1) if j != k]; tr3 = [r for j, r in enumerate(races3) if j != k]
        X, o = races1[k]
        b1, mu1, sd1 = E.fit(tr1, depth=1); b3, mu3, sd3 = E.fit(tr3, depth=3)
        p1 = max(E.prob(X, b1, mu1, sd1)[o[0]], 1e-3); p3 = max(E.prob(X, b3, mu3, sd3)[o[0]], 1e-3)
        d.append((s, -math.log(p1), -math.log(p3)))
        print(s, round(p1, 3), round(p3, 3), flush=True)
    diff = [c - a for _, a, c in d]
    n = len(diff); m = sum(diff) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in diff) / (n - 1))
    t = m / (sd / math.sqrt(n))
    out = {'seasons': n, 'll_winner_only': round(sum(a for _, a, _ in d) / n, 4), 'll_rank3': round(sum(c for _, _, c in d) / n, 4),
           'd': round(m, 4), 't': round(t, 2), 'p': round(t_sf(-t, n - 1), 5), 'better': sum(x < 0 for x in diff),
           'hits_winner_only': None, 'rows': d}
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}))
    if outfn: json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(*sys.argv[1:])
