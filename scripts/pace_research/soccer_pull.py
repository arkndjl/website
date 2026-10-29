import sys, json, gzip
import os
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
sys.path.insert(0, SC)
import soccer_games as SG
from core import OUT
rows = json.load(gzip.open(SC + 'soccer_games_hist.json.gz'))
BIG = {'eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1'}
rows = [dict(r, hn='', an='') for r in rows if r['lg'] in BIG]
SG.attach(rows)
keep = ['id', 'lg', 'day', 'h', 'a', 'hs', 'as', 'hsh', 'ash', 'hst', 'ast', 'hx', 'ax', 'ouc', 'ouac', 'oubc', 'oubb']
json.dump([{k: r.get(k) for k in keep} for r in rows], gzip.open(OUT + 'soccer_big5.json.gz', 'wt'))
print(len(rows), sum(1 for r in rows if r.get('hsh') is not None), sum(1 for r in rows if r.get('ouc') or r.get('ouac')))
