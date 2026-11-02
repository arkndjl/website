"""Position-purpose FV drivers for CFB (Nov 2 2026): does a number built from what each position is FOR explain NFL
outcomes beyond the shipped FV?
    python3 scripts/cfb_espn_pbp.py 2011 2022          # ESPN slim play-by-play (one summary call per FBS game)
    python3 scripts/research/pos_drivers/cfb/pos_drivers.py --parse   # credits per player-season -> .cache
    python3 scripts/research/pos_drivers/cfb/pos_drivers.py           # tests -> scripts/research/pos_drivers/cfb/results.json

PRE-REGISTERED (written before any outcome was looked at; 11 primaries, Holm across all of them):
  role purpose -> driver (career to date through the graded season; plays with |margin| > 28 in the 2nd half dropped)
  QB  move the chains when the defense knows a pass is coming
      qbMD  3rd/4th down & 4+ dropbacks (passes, sacks, INTs): conversions over the season's expected rate by distance,
            per dropback, shrunk (k 40)
  RB  get the yards the down asks for
      rbSR  rush success (40% of the distance on 1st, 60% on 2nd, all of it on 3rd/4th) over expected by down x distance,
            per carry, shrunk (k 100)
      rbSY  short yardage: 3rd/4th & 1-2 carries converted over expected, per carry, shrunk (k 15)
  WR  win on the money downs: the catch that moves the chains on 3rd/4th
      wrMD  3rd/4th-down targets: conversions over expected (by distance), a team game in seasons targeted
      wrMDr same, per target, shrunk (k 20)
  TE  chain mover + red-zone target (blocking: no data)
      teMD  as wrMD
      teRZ  red-zone (inside the 20) targets: TDs over the season's expected TD rate, a team game in seasons targeted
  EDGE finish the QB when the offense must pass
      edPD  sacks on passing downs (2nd & 8+, 3rd/4th & 5+; shared sacks split) per opponent passing-down dropback in
            games he made any defensive credit, shrunk to the EDGE mean (k 150 dropbacks)
  DL  stop the run at the line
      dlStuff  carries ended at or behind the line with him in the tackle (shared split) per opponent carry in games
            he appeared, shrunk to the DL mean (k 200)
  LB  fill the gap, make the stop short of the sticks
      lbStop  carries that failed the success standard with him in the tackle, per opponent carry, shrunk (k 200)
      lbCov   3rd/4th-down completions he tackled short of the sticks, per opponent 3rd/4th completion, shrunk (k 30)
  OL / CB / S  no graded rows in the all-time history (the board grades QB-LB only before PFN 2019) -> untestable.
Gate: draft classes held out one at a time (2015-23), fold t on the squared-error gain, most folds better, forward
(fit earlier classes only) not worse, top 10 per class at the position by prediction not worse; positive coefficient
expected (one-sided p from t with folds-1 df), Holm over the 11.
Outcome: NFL AV a season (undrafted 0), the board's target. Draft pick shown as a diagnostic.
"""
import gzip
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCR)
sys.path.insert(0, os.path.join(SCR, 'research', 'st_value'))
import names as NM  # noqa: E402

ROOT = os.path.dirname(SCR)
PBP = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_pbp')
HIST = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist')
CRED = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'pos_credits.json.gz')
TEAMS = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_teams.json')
OUT = os.path.join(HERE, 'results.json')

NAME = r"([A-Z][\w.'\-]*(?: (?:[A-Z][\w.'\-]*|de|da|del|la|le|van|von|St\.))*?(?: (?:Jr\.?|Sr\.?|II|III|IV|V))?)"
END = r"(?=,| for | and | to | return| \(|\s*$|\.\s)"
R_PASS = re.compile(NAME + r" pass (complete|incomplete|intercepted)(?: to " + NAME + END + r")?")
R_PASS_TD = re.compile(NAME + r" \d+ Yd pass from " + NAME + r"(?= \(|,|\s*$| for )")
R_RUSH = re.compile(NAME + r" (?:rush|run) for ")
R_RUSH_TD = re.compile(NAME + r" \d+ Yd Run")
R_SACK = re.compile(NAME + r" sacked by " + NAME + END + r"(?: and " + NAME + END + r")?")
R_TKL = re.compile(r"tackled by " + NAME + END + r"(?: and " + NAME + END + r")?")
PASS_T = ('Pass Reception', 'Pass Completion', 'Pass Incompletion', 'Pass Interception Return', 'Pass Interception',
          'Passing Touchdown', 'Interception Return Touchdown', 'Sack')
RUSH_T = ('Rush', 'Rushing Touchdown')


def cl(n):
    """sentence-final full stop off a name (keeps Jr. / Sr. / initials)"""
    if n and n.endswith('.') and not re.search(r'(?:\b(?:Jr|Sr)|\b[A-Z])\.$', n):
        return n[:-1]
    return n


def dbin(d):
    return 0 if d <= 2 else 1 if d <= 3 else 2 if d <= 6 else 3 if d <= 10 else 4


def success(dn, ds, y, td):
    if td:
        return 1
    need = ds * (0.4 if dn == 1 else 0.6 if dn == 2 else 1.0)
    return int(y >= need)


def parse():
    """credits per (season, team id, name), opponent volumes per (season, team id, game), plus season expectations"""
    seasons = {}
    for S in range(2011, 2023):
        p = os.path.join(HIST, f'games{S}.json')
        if os.path.exists(p):
            for g in json.load(open(p)):
                if g['done'] and g.get('grp') == 'fbs':
                    seasons[g['id']] = S
    plays = defaultdict(list)          # season -> list of parsed plays
    tg = defaultdict(set)              # (S, team) -> games
    tkl_seen = defaultdict(int)
    for gid, S in seasons.items():
        fp = os.path.join(PBP, f'{gid}.json.gz')
        if not os.path.exists(fp):
            continue
        g = json.load(gzip.open(fp, 'rt'))
        ids = [t['id'] for t in g['teams']]
        home = next((t['id'] for t in g['teams'] if t['ha'] == 'home'), None)
        for t in ids:
            tg[(S, t)].add(gid)
        for dr in g['drives']:
            for p in dr['plays']:
                t, x = p.get('t'), p.get('x') or ''
                if t not in PASS_T and t not in RUSH_T:
                    continue
                if p.get('pen') or 'NO PLAY' in x.upper():
                    continue
                dn, ds, yl, off = p.get('dn'), p.get('ds'), p.get('yl'), p.get('st')
                if not dn or dn > 4 or ds is None or off not in ids:
                    continue
                q = p.get('q') or 1
                hs, as_ = p.get('hs') or 0, p.get('as') or 0
                if q >= 3 and abs(hs - as_) > 28:
                    continue
                de = ids[1] if ids[0] == off else ids[0]
                y = p.get('y') or 0
                td = bool(p.get('sc')) and 'TD' in x.upper() or 'TOUCHDOWN' in x.upper()
                conv = int(td or y >= ds or '1ST DOWN' in x.upper())
                r = {'g': gid, 'o': off, 'd': de, 'dn': dn, 'ds': ds, 'yl': yl, 'y': y, 'td': int(td), 'cv': conv}
                tk = R_TKL.search(x)
                if tk:
                    r['tk'] = [cl(n) for n in tk.groups() if n]
                    tkl_seen[S] += 1
                if t in RUSH_T:
                    m = R_RUSH.match(x) or R_RUSH_TD.match(x)
                    if not m:
                        continue
                    r.update(k='R', ru=cl(m.group(1)), sc=success(dn, ds, y, td))
                elif t == 'Sack' or ' sacked by ' in x:
                    m = R_SACK.match(x)
                    if not m:
                        continue
                    r.update(k='S', qb=cl(m.group(1)), sk=[cl(n) for n in m.groups()[1:] if n], cv=0)
                else:
                    m = R_PASS.match(x)
                    if m:
                        r.update(k='P', qb=cl(m.group(1)), rc=cl(m.group(3)) if m.group(2) != 'intercepted' else None,
                                 cmp=int(m.group(2) == 'complete'))
                    else:
                        m = R_PASS_TD.match(x)
                        if not m:
                            continue
                        r.update(k='P', qb=cl(m.group(2)), rc=cl(m.group(1)), cmp=1)
                    if m.re is R_PASS and m.group(2) == 'intercepted':
                        r['cv'] = r['td'] = 0
                    if r['rc'] in ('N/A', 'Team', 'TEAM'):
                        r['rc'] = None
                plays[S].append(r)
    print('tackler text by season', dict(sorted(tkl_seen.items())))
    # season expectations
    exp = {}
    for S, ps in plays.items():
        acc = defaultdict(lambda: [0, 0])
        for r in ps:
            b = (min(r['dn'], 3), dbin(r['ds']))
            if r['k'] in ('P', 'S'):
                a = acc[('db',) + b]; a[0] += r['cv']; a[1] += 1
                if r['k'] == 'P' and r['rc'] and r['yl'] is not None and r['yl'] <= 20:
                    a = acc[('rz', min(r['yl'] // 5, 3))]; a[0] += r['td']; a[1] += 1
            else:
                a = acc[('rs',) + b]; a[0] += r['sc']; a[1] += 1
                a = acc[('rc',) + b]; a[0] += r['cv']; a[1] += 1
        exp[S] = {k: v[0] / v[1] for k, v in acc.items() if v[1]}
    cred = defaultdict(lambda: defaultdict(float))       # (S, team, name) -> stat -> value
    games_in = defaultdict(set)                           # (S, team, name) -> games with a defensive credit
    opp = defaultdict(lambda: defaultdict(float))         # (S, def team, game) -> opponent volumes
    for S, ps in plays.items():
        E = exp[S]
        for r in ps:
            b = (min(r['dn'], 3), dbin(r['ds']))
            mdown = r['dn'] >= 3
            pdown = (r['dn'] == 2 and r['ds'] >= 8) or (r['dn'] >= 3 and r['ds'] >= 5)
            O = opp[(S, r['d'], r['g'])]
            if r['k'] in ('P', 'S'):
                e = E.get(('db',) + b, 0)
                if mdown and r['ds'] >= 4:
                    c = cred[(S, r['o'], r['qb'])]; c['qn'] += 1; c['qx'] += r['cv'] - e
                if pdown:
                    O['pd'] += 1
                if r['k'] == 'S':
                    for n in r['sk']:
                        games_in[(S, r['d'], n)].add(r['g'])
                        if pdown:
                            cred[(S, r['d'], n)]['pds'] += 1 / len(r['sk'])
                    continue
                if mdown and r.get('cmp'):
                    O['mdc'] += 1
                    if not r['cv'] and r.get('tk'):
                        for n in r['tk']:
                            cred[(S, r['d'], n)]['cov'] += 1 / len(r['tk'])
                if r.get('tk'):
                    for n in r['tk']:
                        games_in[(S, r['d'], n)].add(r['g'])
                if r['rc']:
                    c = cred[(S, r['o'], r['rc'])]
                    c['tgt'] += 1
                    if mdown:
                        c['mn'] += 1; c['mx'] += r['cv'] - e
                    if r['yl'] is not None and r['yl'] <= 20:
                        c['zn'] += 1; c['zx'] += r['td'] - E.get(('rz', min(r['yl'] // 5, 3)), 0)
            else:
                O['ru'] += 1
                if r.get('tk'):
                    O['rut'] += 1
                c = cred[(S, r['o'], r['ru'])]
                c['rn'] += 1; c['rx'] += r['sc'] - E.get(('rs',) + b, 0)
                if r['dn'] >= 3 and r['ds'] <= 2:
                    c['yn'] += 1; c['yx'] += r['cv'] - E.get(('rc',) + b, 0)
                if r.get('tk'):
                    for n in r['tk']:
                        games_in[(S, r['d'], n)].add(r['g'])
                        cc = cred[(S, r['d'], n)]
                        cc['tk'] += 1 / len(r['tk'])
                        if r['y'] <= 0 and not r['td']:
                            cc['stf'] += 1 / len(r['tk'])
                        if not r['sc']:
                            cc['stp'] += 1 / len(r['tk'])
    out = []
    for (S, t, n), c in cred.items():
        gs = games_in.get((S, t, n), set())
        o = {'s': S, 'tid': t, 'name': n, 'tg': len(tg[(S, t)]), 'gin': len(gs), **{k: round(v, 3) for k, v in c.items()}}
        if gs:
            o['opd'] = sum(opp[(S, t, g)]['pd'] for g in gs)
            o['oru'] = sum(opp[(S, t, g)]['rut'] for g in gs)     # carries with a tackler named (the stuff/stop base)
            o['omd'] = sum(opp[(S, t, g)]['mdc'] for g in gs)
        out.append(o)
    tpd = defaultdict(float)
    for (S, t, g), O in opp.items():
        tpd[f'{S}|{t}'] += O['pd']
    os.makedirs(os.path.dirname(CRED), exist_ok=True)
    json.dump({'rows': out, 'tkl': tkl_seen, 'tpd': tpd}, gzip.open(CRED, 'wt'))
    print('credit rows', len(out))


def teams():
    if not os.path.exists(TEAMS):
        import urllib.request
        d = json.load(urllib.request.urlopen('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000'))
        json.dump({t['team']['id']: t['team'].get('location') for t in d['sports'][0]['leagues'][0]['teams']}, open(TEAMS, 'w'))
    return json.load(open(TEAMS))


KEYS = ('qn', 'qx', 'rn', 'rx', 'yn', 'yx', 'mn', 'mx', 'zn', 'zx', 'tgt', 'pds', 'opd', 'stf', 'stp', 'oru', 'cov', 'omd', 'tk')


def build():
    loc = teams()
    CJ = json.load(gzip.open(CRED, 'rt'))
    C, TPD = CJ['rows'], CJ['tpd']
    tid_of = {}
    for t, l in loc.items():
        if l:
            tid_of.setdefault(NM.team_key(l), t)
    by_s = defaultdict(list)
    for r in C:
        r['team'] = loc.get(r['tid'], '')
        by_s[r['s']].append(r)
    M = {s: NM.Matcher(rs, name='name', team='team', pos=None) for s, rs in by_s.items()}
    rows = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_alltime_rows.json.gz'), 'rt'))
    hist = defaultdict(list)
    for r in rows:
        hist[r['id']].append(r)
    hit = tot = 0

    def find(s, name, team):
        m = M.get(s)
        if not m:
            return None
        f, _ = m.find(name, team=team, cross_team='none')
        return f

    final = [r for r in rows if r['final'] and r['last'] <= 2022 and (r['draft'] is None or r['draft'] <= 2023)]
    data = []
    for r in final:
        ss = sorted(hist[r['id']], key=lambda h: h['s'])
        acc = defaultdict(float)
        tgs = {}                       # seasons with any offensive credit -> team games
        seen = set()
        lines = [(h['s'], h['name'], h['team']) for h in ss]
        # seasons before the first graded one (2011+): same name and team
        for s in range(max(2011, ss[0]['s'] - 4), ss[0]['s']):
            lines.insert(0, (s, ss[0]['name'], ss[0]['team']))
        gpd = gsk = 0.0          # edPD2: graded seasons only, team-season denominators
        for h in ss:
            if h['s'] > 2022:
                continue
            t = tid_of.get(NM.team_key(h['team']))
            if t:
                gpd += TPD.get(f"{h['s']}|{t}", 0)
                f = find(h['s'], h['name'], h['team'])
                gsk += (f or {}).get('pds', 0) or 0
        for s, n, t in lines:
            if s in seen or s > 2022:
                continue
            tot += s == r['s']
            f = find(s, n, t)
            if not f:
                continue
            seen.add(s)
            hit += s == r['s']
            for k in KEYS:
                acc[k] += f.get(k, 0) or 0
            if f.get('mn') or f.get('zn') or f.get('tgt'):
                tgs[s] = f['tg']
        tgames = max(1, sum(tgs.values()))
        d = {'cls': r['draft'] or (r['last'] + 1), 'g': r['g'], 'fvx': r['fvx'], 'av': r['av'] or 0.0, 'pick': r['pick'],
             'name': r['name'], 'n_seasons': len(seen), 'raw': dict(acc, gpd=gpd, gsk=gsk), 'tgames': tgames}
        data.append(d)
    print('final rows', len(data), '| final-season joins', hit, 'of', tot)
    # drivers (pre-registered)
    for d in data:
        a = d['raw'] = defaultdict(float, d['raw'])
        d['qbMD'] = a['qx'] / (a['qn'] + 40)
        d['rbSR'] = a['rx'] / (a['rn'] + 100)
        d['rbSY'] = a['yx'] / (a['yn'] + 15)
        d['wrMD'] = d['teMD'] = a['mx'] / d['tgames']
        d['wrMDr'] = a['mx'] / (a['mn'] + 20)
        d['teRZ'] = a['zx'] / d['tgames']
    for g, num, den, k, nm in (('EDGE', 'pds', 'opd', 150, 'edPD'), ('DL', 'stf', 'oru', 200, 'dlStuff'),
                               ('LB', 'stp', 'oru', 200, 'lbStop'), ('LB', 'cov', 'oru', 30, 'lbCov'),
                               ('EDGE', 'gsk', 'gpd', 150, 'edPD2')):
        P = [d for d in data if d['g'] == g]
        N = sum(d['raw'][num] for d in P); D = sum(d['raw'][den] for d in P)
        m = N / D if D else 0
        for d in P:
            d[nm] = (d['raw'][num] + k * m) / (d['raw'][den] + k)
            d[nm + '_n'] = d['raw'][den]
    return data


# ---- test harness (as scripts/research/st_value/cfb_fv_ret_test.py, top 10 per class at the position) ----
def pav(x, y):
    o = np.argsort(x); xs, ys = x[o], y[o].astype(float)
    blocks = []
    for xi, yi in zip(xs, ys):
        blocks.append([yi, 1, xi])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            a = blocks.pop(); blocks[-1][0] += a[0]; blocks[-1][1] += a[1]; blocks[-1][2] = a[2]
    xm = np.array([b[2] for b in blocks]); vm = np.array([b[0] / b[1] for b in blocks])
    return lambda z: vm[np.minimum(np.searchsorted(xm, z), len(vm) - 1)]


def avgrank(a):
    a = np.asarray(a, float); o = np.argsort(a, kind='mergesort'); r = np.empty(len(a)); sa = a[o]; i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sa[j + 1] == sa[i]:
            j += 1
        r[o[i:j + 1]] = (i + j) / 2; i = j + 1
    return r


def spear(a, b):
    return np.corrcoef(avgrank(a), avgrank(b))[0, 1]


def fitpred(D, cand, tr, te):
    f = np.array([d['fvx'] for d in D]); y = np.array([d['av'] for d in D])
    g = pav(f[tr], y[tr]); b0 = g(f)
    if not cand:
        return b0[te], 0.0
    x = np.array([d[cand] for d in D], float)
    xc = x - x[tr].mean()
    b = float(((y[tr] - b0[tr]) * xc[tr]).sum() / (xc[tr] ** 2).sum())
    return b0[te] + b * xc[te], b


def tcdf(t, df):
    """one-sided p = P(T > t), Student t (regularized incomplete beta via continued fraction)"""
    if t == 0 or df < 1:
        return 0.5
    x = df / (df + t * t)

    def betacf(a, b, x):
        qab, qap, qam = a + b, a + 1, a - 1
        c, d = 1.0, 1 - qab * x / qap
        d = 1 / d; h = d
        for m in range(1, 200):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2)); d = 1 + aa * d; c = 1 + aa / c; d = 1 / d; h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)); d = 1 + aa * d; c = 1 + aa / c; d = 1 / d; h *= d * c
        return h
    a, b = df / 2, 0.5
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    ib = bt * betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * betacf(b, a, 1 - x) / b
    return ib / 2 if t > 0 else 1 - ib / 2


def test(D, cand, label, K=10):
    y = np.array([d['av'] for d in D]); cls = np.array([d['cls'] for d in D])
    gains, top0, top1, imp, coefs, fwd = [], [], [], 0, [], []
    p0all, p1all = np.zeros(len(D)), np.zeros(len(D))
    C = sorted(set(cls))
    for c in C:
        tr, te = cls != c, cls == c
        p0, _ = fitpred(D, None, tr, te); p1, b = fitpred(D, cand, tr, te)
        coefs.append(b); p0all[te], p1all[te] = p0, p1
        g = ((y[te] - p0) ** 2).mean() - ((y[te] - p1) ** 2).mean()
        gains.append(g); imp += g > 0
        k = min(K, int(te.sum()))
        top0.append(y[te][np.argsort(-p0, kind='mergesort')[:k]].mean()); top1.append(y[te][np.argsort(-p1, kind='mergesort')[:k]].mean())
        if c >= C[3]:
            trf = cls < c
            q0, _ = fitpred(D, None, trf, te); q1, _ = fitpred(D, cand, trf, te)
            fwd.append(((y[te] - q0) ** 2).mean() - ((y[te] - q1) ** 2).mean())
    g = np.array(gains); t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g))) if g.std() > 0 else 0
    dt = np.array(top1) - np.array(top0)
    fw = np.array(fwd)
    x = np.array([d[cand] for d in D], float)
    o = {'cand': cand, 'set': label, 'n': len(D), 'folds': len(g), 'gainT': round(float(t), 2), 'p1': round(tcdf(float(t), len(g) - 1), 4),
         'better': int(imp), 'coef': round(float(np.mean(coefs)), 3), 'sd': round(float(x.std()), 4),
         'coefSD': round(float(np.mean(coefs) * x.std()), 3),
         'rawR': round(float(np.corrcoef(x, y)[0, 1]), 3),
         'spearman': [round(float(spear(p0all, y)), 4), round(float(spear(p1all, y)), 4)],
         'top10': [round(float(np.mean(top0)), 3), round(float(np.mean(top1)), 3)], 'top10Better': int((dt > 0).sum()),
         'top10Worse': int((dt < 0).sum()), 'fwdGain': round(float(fw.mean()), 4) if len(fw) else None, 'fwdBetter': f'{int((fw > 0).sum())}/{len(fw)}'}
    print(o)
    return o


PRIMARY = [('QB', 'qbMD'), ('RB', 'rbSR'), ('RB', 'rbSY'), ('WR', 'wrMD'), ('WR', 'wrMDr'), ('TE', 'teMD'), ('TE', 'teRZ'),
           ('EDGE', 'edPD'), ('DL', 'dlStuff'), ('LB', 'lbStop'), ('LB', 'lbCov'),
           ('EDGE', 'edPD2')]   # edPD2 added after the first run: edPD's 'games he appeared' base is only sack games
                                 # after 2013 (no tackler text), so the base is the team's season instead (variant 12)


def holm(res):
    o = sorted(range(len(res)), key=lambda i: res[i]['p1'])
    m = len(res); ok = True
    for j, i in enumerate(o):
        a = 0.05 / (m - j)
        res[i]['holmAlpha'] = round(a, 4)
        ok = ok and res[i]['p1'] <= a
        res[i]['holmPass'] = ok


if __name__ == '__main__':
    if '--parse' in sys.argv:
        parse()
        sys.exit()
    D = build()
    res, untest = [], []
    cov = {g: [sum(1 for d in D if d['g'] == g and d['n_seasons']), sum(1 for d in D if d['g'] == g)] for g in ('QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB')}
    print('rows with any pbp season', cov)
    for g, cand in PRIMARY:
        P = [d for d in D if d['g'] == g]
        if cand in ('dlStuff', 'lbStop', 'lbCov'):
            P = [d for d in P if d[cand + '_n'] > 0]      # seasons with tackler text only
        if len(set(d['cls'] for d in P)) < 5 or len(P) < 100:
            untest.append({'cand': cand, 'set': g, 'n': len(P), 'why': 'ESPN names tacklers only 2011-13; too few graded rows'})
            print('untestable', g, cand, len(P))
            continue
        res.append(test(P, cand, g))
    holm(res)
    for r in res:
        r['ship'] = bool(r['holmPass'] and r['better'] > r['folds'] / 2 and (r['fwdGain'] or 0) >= 0 and r['top10'][1] >= r['top10'][0])
        print(r['set'], r['cand'], 't', r['gainT'], 'p', r['p1'], 'holm', r['holmPass'], 'ship', r['ship'])
    json.dump({'method': __doc__.strip(), 'registered': len(PRIMARY), 'tested': len(res), 'coverage': cov, 'untestable': untest, 'results': res}, open(OUT, 'w'), indent=1)
