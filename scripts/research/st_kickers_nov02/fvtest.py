"""Kicker and punter grades, Nov 2 2026 research (scripts/st_kickers.py). CFB K/P FV driver test, rows: college grades (final seasons 2011-20) joined to NFL seasons as the primary K/P (names.py matcher)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out") + "/"
os.makedirs(OUT, exist_ok=True)
import sys, json, math, csv, collections
import numpy as np

import st_kickers as K
from collections import defaultdict
SP = OUT
KK = json.load(open(SP + 'res_cfb.json'))
pl, names, D = K.cfb_plays(range(2009, 2027))
# FG expected over all seasons
fg = pl['fg']; b = K.logit_fit([K.fg_feats(r) for r in fg], [r['m'] for r in fg])
for r in fg:
    z = sum(x * y for x, y in zip(b, K.fg_feats(r))); r['xm'] = 1 / (1 + math.exp(-z)); r['poe'] = 3 * (r['m'] - r['xm'])
rate = defaultdict(list)
for r in pl['xp']: rate[r['s']].append(r['m'])
for r in pl['xp']: r['poe'] = r['m'] - K.mean(rate[r['s']])
K.expect(pl['ko'], 'v', 'poe', lambda r: (r['s'], int(r['yl'] // 5)))
for fld in ('v', 'gross', 'net', 'i20'):
    K.expect(pl['pu'], fld, fld + '_oe', lambda r: (r['s'], int(min(99, r['yl']) // 3)))
k = {x: KK[lab]['k'] for x, lab in (('fg', 'fg poe (career k)'), ('xp', 'xp'), ('ko', 'ko all'), ('pin', 'punt pin'), ('far', 'punt far'), ('pu', 'punt pts'))}
print('k', k)
# player-season aggregates
A = defaultdict(lambda: defaultdict(float))
for part in ('fg', 'xp', 'ko'):
    for r in pl[part]:
        a = A[(r['p'], r['s'])]; a[part + 'n'] += 1; a[part + 'poe'] += r['poe']
        if part == 'fg': a['fgm'] += r['m']; a['lng'] = max(a['lng'], r['d'] if r['m'] else 0)
        if part == 'xp': a['xpm'] += r['m']
for r in pl['pu']:
    a = A[(r['p'], r['s'])]; a['pun'] += 1; a['puv'] += r['v_oe']; a['gross'] += r['gross']; a['i20'] += r['i20']; a['goe'] += r['gross_oe']; a['noe'] += r['net_oe']
    sd = 'pin' if r['yl'] <= 50 else 'far'; a[sd + 'n'] += 1; a[sd] += r['v_oe']
seasons = defaultdict(list)
for (p, s), a in A.items(): seasons[p].append(s)
# NFL outcomes
pe = {}
for x in csv.DictReader(open(os.path.join(ROOT, 'scripts', '.cache') + '/nfl/players.csv')):
    if x['espn_id'] and x['espn_id'] != 'NA':
        pe[x['gsis_id']] = (x['espn_id'].split('.')[0], x['draft_round'])
nfl = defaultdict(lambda: defaultdict(lambda: [0, 0]))
import csv as _c, gzip
npl = K.nfl_plays(range(2012, 2026))
for r in npl['fg']: nfl[r['p']][r['s']][0] += 1
for r in npl['pu']: nfl[r['p']][r['s']][1] += 1
import names as NM, cfb_espn_hist as EH, os
tname = {}
for yy in range(2009, 2027):
    gp = os.path.join(EH.DIR, f'games{yy}.json')
    if os.path.exists(gp):
        for g in json.load(open(gp)):
            tname[g['h']] = g['hn']; tname[g['a']] = g['an']
kindof = {}
for r in pl['fg']: kindof.setdefault(r['p'], 'K')
for r in pl['pu']: kindof.setdefault(r['p'], 'P')
crow = [{'name': nm, 'team': tname.get(tid, ''), 'pos': kindof.get(aid, 'K'), 'id': aid} for aid, (nm, tid) in names.items() if aid in kindof]
M = NM.Matcher(crow, id='id', team_eq=lambda want, have: bool(want) and NM.team_key(have).startswith(NM.team_key(want)))
byespn = {}; how = collections.Counter()
for x in csv.DictReader(open(os.path.join(ROOT, 'scripts', '.cache') + '/nfl/players.csv')):
    if x['position'] not in ('K', 'P') or x['gsis_id'] not in nfl: continue
    col = (x['college_name'] or '').split(';')[-1].strip()
    eid = (x['espn_id'] or '').split('.')[0]
    r, h = (M.by_id[eid][0], 'id') if eid in M.by_id else (None, None)
    if not r:   # ESPN keeps a separate NFL id for many players: name + school
        r, h = M.find(x['display_name'], team=col, pos=x['position'])
    how[h] += 1
    if r: byespn[r['id']] = nfl[x['gsis_id']]
print('NFL K/P linked to college:', dict(how))
drafted = {e: rd for g, (e, rd) in pe.items()}
rows = []
for p, ss in seasons.items():
    fin = max(ss)
    if not (2011 <= fin <= 2020): continue
    a = A[(p, fin)]
    kind = 'k' if a['fgn'] >= 10 else 'p' if a['pun'] >= 25 else None
    if kind is None: continue
    sea = byespn.get(p, {})
    y = sum(1 for s in range(fin + 1, fin + 6) if (sea.get(s, [0, 0])[0] >= 10 if kind == 'k' else sea.get(s, [0, 0])[1] >= 30))
    # career pooled
    C = defaultdict(float)
    for s in ss:
        for kk, v in A[(p, s)].items():
            if kk != 'lng': C[kk] += v
    C['lng'] = max(A[(p, s)]['lng'] for s in ss)
    def adjK(a):
        return sum(a[x + 'poe'] / (a[x + 'n'] + k[x]) for x in ('fg', 'xp', 'ko') if a[x + 'n'])  # shrunk rates summed (per attempt units)
    def adjKtot(a):
        return sum(a[x + 'poe'] / (a[x + 'n'] + k[x]) * a[x + 'n'] for x in ('fg', 'xp', 'ko') if a[x + 'n'])
    def adjP(a):
        return (a['pin'] / (a['pinn'] + k['pin']) * a['pinn'] + a['far'] / (a['farn'] + k['far']) * a['farn']) / max(1, a['pun'])
    r = {'p': p, 'fin': fin, 'kind': kind, 'y': y, 'nm': names.get(p, ('',))[0], 'dr': drafted.get(p, '')}
    if kind == 'k':
        r.update(old_rate=a['fgpoe'] / (a['fgn'] + 8), old_long=a['lng'], old_xp=a['xpm'] / a['xpn'] if a['xpn'] else None,
                 new=adjKtot(a), new_rate=adjK(a), new_c=adjKtot(C), fgr=a['fgpoe'] / (a['fgn'] + k['fg']), fgc=C['fgpoe'] / (C['fgn'] + k['fg']),
                 kor=a['kopoe'] / (a['kon'] + k['ko']) if a['kon'] else 0, koc=C['kopoe'] / (C['kon'] + k['ko']) if C['kon'] else 0, kon=a['kon'],
                 lngc=C['lng'], fga=a['fgn'], fgac=C['fgn'])
    else:
        r.update(old_rate=a['puv'] / (a['pun'] + 10), old_ypp=a['gross'] / a['pun'], old_i20=a['i20'] / a['pun'],
                 new=adjP(a), new_c=adjP(C), goe=a['goe'] / (a['pun'] + 16), goec=C['goe'] / (C['pun'] + 16), noe=a['noe'] / (a['pun'] + 14),
                 noec=C['noe'] / (C['pun'] + 14), pun=a['pun'], punc=C['pun'])
    rows.append(r)
json.dump(rows, open(SP + 'fvrows.json', 'w'))
for kind in ('k', 'p'):
    R = [r for r in rows if r['kind'] == kind]
    print(kind, len(R), 'players;', sum(1 for r in R if r['y'] > 0), 'with an NFL season; mean y', round(np.mean([r['y'] for r in R]), 3))
# coverage: NFL primary K/P seasons 2016-2025 by players whose college ESPN id we have
cov=defaultdict(lambda:[0,0])
pos={x['gsis_id']:(x['position'],x['rookie_season'],x['college_name']) for x in csv.DictReader(open(os.path.join(ROOT, 'scripts', '.cache') + '/nfl/players.csv'))}
for g,sea in nfl.items():
    for s,(nf,npu) in sea.items():
        if s<2016: continue
        kind='k' if nf>=10 else 'p' if npu>=30 else None
        if not kind: continue
        cov[kind][0]+=1; cov[kind][1]+= int(any(v is sea for v in byespn.values()))
        if s==2025 and not any(v is sea for v in byespn.values()): print('unmatched 2025',kind,g,pos.get(g))
print('coverage of NFL primary seasons 2016-25 by college-linked players',dict(cov))
# broader target: any NFL attempt within 5 yrs
for r in rows:
    sea=byespn.get(r['p'],{})
    r['y2']=int(any(sum(sea.get(s,[0,0]))>0 for s in range(r['fin']+1,r['fin']+6)))
json.dump(rows, open(SP + 'fvrows.json', 'w'))
print('any NFL attempt:', {kd: sum(r['y2'] for r in rows if r['kind']==kd) for kd in 'kp'})
