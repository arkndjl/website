#!/usr/bin/env python3
"""School development (scripts/school_dev.py, CBB): the college outcomes on rXPM in place of BPM.
  col: peak minutes share x (rate + 3)+ over his first four seasons;  rate: minutes-weighted rate over those seasons.
Same out-of-sample tests (rolling: effects from earlier classes scored on class t; odd / even class reliability).
A descriptive outcome passes when a school's past effect predicts its next classes better: rolling held-out MSE gain, slope t,
split-half r.  -> school_dev.json"""
import csv, json, os, sys
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import school_dev as SD
KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit')
X = {}
for r in csv.DictReader(open(os.path.join(KIT, 'college_seasons_nba.csv'))):
    if r['rec_class'] and r['on3rk'] and r['bpm'] and r['min_per']:
        k = (int(r['rec_class']), int(float(r['on3rk'])), int(r['year']), round(float(r['bpm']), 2))
        X[k] = C.get(r['pid'], int(r['year']), 'xpm')
import gzip
D = json.load(gzip.open(os.path.join(C.ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))
miss = tot = 0
for r in D['recruits']:
    for y, v in (r.get('col') or {}).items():
        x = X.get((r['cls'], r['rk'], int(y), v[2])); tot += 1; miss += x is None
        v.append(x if x is not None else v[2])
print('college seasons', tot, 'without rXPM', miss)
out = {}
for lab, ix in (('BPM', 2), ('rXPM', 3)):
    import io
    _gz = SD.gzip.open
    class F:
        def __init__(s, *a, **k): pass
    SD.json_load = json.load
    orig = SD.json.load
    def fake(f, *a, **k):
        d = orig(f, *a, **k)
        return d
    # rebuild rows from the patched recruit list
    def rows():
        T = D['teams']; R = []
        for r in D['recruits']:
            c = r.get('college')
            if not c or not r.get('rk'): continue
            y1 = c['y1']; peak = bw = bs = 0.0
            for k, v in (r.get('col') or {}).items():
                g, mn, b = v[0], v[1], v[ix]
                if y1 <= int(k) <= y1 + 3:
                    peak = max(peak, mn / 100 * max(0.0, b + 3)); w = g * mn / 100; bw += w; bs += w * b
            y = {}
            if y1 + 3 <= 2026: y['col'] = peak
            if y1 + 3 <= 2026 and bw >= 5: y['bpm'] = bs / bw
            R.append({'school': c['team'], 'team': c['team'], 'cls': r['cls'], 'grp': 'all', 'b': SD.hinge(SD.math.log(r['rk']), SD.KNOTS_RK),
                      'prog': T.get(str(y1 - 1), {}).get(c['team']), 'y': y, 'name': r['name'], 'rk': r['rk']})
        return R
    R = rows(); out[lab] = {}
    for key in ('col', 'bpm'):
        SD.loso_expect(R, key); Q = [r for r in R if key in r['y']]; classes = sorted({r['cls'] for r in Q}); SD.net_of_program(R, key)
        t = SD.tests(R, key, 'd', classes)
        out[lab][key] = {'rolling': {k: t['rolling'][k] for k in ('n', 'slope', 't', 'mseGainPct', 'r', 'classesWon')}, 'halves': t['halves']}
        print(lab, key, out[lab][key], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'school_dev.json'), 'w'), indent=1)
