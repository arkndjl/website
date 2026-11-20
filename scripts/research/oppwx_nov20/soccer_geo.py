# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Stadium coordinates for the clubs of the big five's first and second divisions (research only, Nov 20 2026):
Wikidata (home venue P115 -> coordinates P625, one SPARQL call saved as wd_clubs.json), joined to ESPN club names.
    python3 scripts/research/oppwx_nov20/soccer_geo.py WD_JSON OUT_JSON
"""
import gzip, json, os, re, sys, unicodedata
from collections import defaultdict, Counter
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')
STOP = {'fc', 'cf', 'ac', 'as', 'sc', 'afc', 'ssc', 'us', 'ss', 'rc', 'cd', 'ud', 'sd', 'rcd', 'ca', 'sv', 'vfl', 'vfb', 'tsg', 'fsv', '1',
        'club', 'de', 'calcio', 'football', 'futbol', 'association', 'the', 'og', 'ogc', 'losc', 'bsc', 'sco', 'aj', 'ea', 'es', 'stade',
        'olympique', 'real', 'athletic', 'atletico', 'sporting', 'racing', 'deportivo', 'union', 'sociedad', 'balompie', 'e', 'v', 'spvgg',
        '04', '05', '1846', '1899', '1909', '1913', '1907', '1919', '1898', 'bc', 'ssd', 'acf', 'uc', 'srl', 'spa', 'fk', 'sk', 'rb', 'tsv', 'mainz'}
CC = {'eng': ('United Kingdom', 'England', 'Wales'), 'esp': ('Spain',), 'ger': ('Germany',), 'ita': ('Italy',), 'fra': ('France', 'Monaco')}
def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    t = [w for w in s.split() if w not in STOP]
    return ' '.join(t) or s.strip()
wd = json.load(open(sys.argv[1]))['results']['bindings']
W = defaultdict(list)
for b in wd:
    m = re.match(r'Point\(([-\d.]+) ([-\d.]+)\)', b['coord']['value'])
    W[b['cLabel']['value']].append((norm(b['clubLabel']['value']), b['clubLabel']['value'], float(m.group(2)), float(m.group(1))))
names = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'soccer_teams.json.gz')))
hist = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
home = defaultdict(Counter)
for r in hist:
    if r['lg'][:3] in CC and r['lg'][4:] in ('1', '2') and r['day'] >= '2012-07-01':
        home[r['h']][r['lg'][:3]] += 1
out, miss = {}, []
for tid, c in home.items():
    cc = c.most_common(1)[0][0]
    nm = (names.get(tid) or [''])[0]
    n = norm(nm)
    pool = [x for k in CC[cc] for x in W.get(k, [])]
    hit = [x for x in pool if x[0] == n] or [x for x in pool if n and (set(n.split()) <= set(x[0].split()) or set(x[0].split()) <= set(n.split())) and x[0]]
    if hit:
        # several rows (women's / reserve sides share a ground or a name): the shortest label is the first team
        h = sorted(hit, key=lambda x: (len(x[1]), x[1]))[0]
        out[tid] = [nm, h[1], round(h[2], 4), round(h[3], 4), sum(c.values())]
    else:
        miss.append((sum(c.values()), tid, nm, cc))
json.dump(out, open(sys.argv[2], 'w'), indent=0)
print(len(out), 'matched', len(miss), 'missed, home matches missed', sum(m[0] for m in miss), 'of', sum(sum(c.values()) for c in home.values()))
for m in sorted(miss, reverse=True)[:60]: print(m)
