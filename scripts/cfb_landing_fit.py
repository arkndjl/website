"""Where transfers land: a destination-choice model for the team builder's landing odds.

For every 2024 and 2025 transfer with a known hometown (scripts/cfb_transfer_fit.py's build, cached in
scripts/.cache/transfer/rows.json), the school he picked is set against every other FBS and FCS school
that season (a conditional logit). A school's pull on him:
  - the level step: where he comes from (P4, G5, FCS) x where it is (P4, G5; FCS the base)
  - program talent (its roster's mean recruiting grade, as a z-score) and the prestige gap: talent x his
    current school's talent (players move between like programs), x his recruiting grade, x his production
  - winning (its record that season)
  - playing time on offer: the share of its players at his position who left that season
  - home: miles from his hometown (log) and a home-state school
  - his role, by direction: a step down a level (P4 to G5, G5 to FCS) x his recruiting grade, x his production
    and x a starter (a starter or a blue-chip rarely drops a level: in 2025, 4% of recruited P4 starters who
    moved went down, against 53% of unranked P4 backups), and a step up x his production
  - coaching (Oct 25 2026): a school with a new head coach next season, his own school's new head coach x a step
    down, and private schools (see EXTRA); players who go with their head coach are a mixture share (`follow`)
Tested out of time both ways (fit on 2024 moves, scored on 2025's, and back), then refit on both. Writes `landing`
into data/cfb_transfer_fit.json, with each school's level, talent and money for scoring the live season.
Run after scripts/cfb_transfer_fit.py: python3 scripts/cfb_landing_fit.py

PRE-REGISTERED: the January 2027 window, a third NIL-era cycle (fixed 2026-10-25, before the window opens).
    python3 scripts/cfb_landing_fit.py --freeze      writes scripts/data/ledger/landing_2027.json (done Oct 25 2026)
    python3 scripts/cfb_landing_fit.py --score       once ESPN has 2027 rosters (after spring practice, ~May 2027)
  movers    2026 players new on another FBS/FCS team's 2027 list (scripts/cfb_transfer_fit.py's rules), hometown known.
  models    the frozen coefficients only, no refit: `base` (the terms before Oct 25 2026, HC_FOLLOW .39) and `full`
            (with newhc, newhc_from, private and the fitted follow share). Head coaches: the 2026 and 2027
            season-start infoboxes (scripts/cfb_optout.py --hc writes scripts/data/cfb_hc_start.json).
  metrics   per-mover log likelihood of the school he picked (full - base: mean, t), median rank of that school,
            top-10 hit rate, skill vs a uniform pick; the follow share among movers whose head coach took another job.
  pass      full - base > 0 with t >= 2. Otherwise the coaching terms come out at the next refit. A failure is a result.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROWS = os.path.join(ROOT, 'scripts', '.cache', 'transfer', 'rows.json')
LOC = os.path.join(ROOT, 'scripts', 'geo', 'team_loc.json')
FIT = os.path.join(ROOT, 'data', 'cfb_transfer_fit.json')
LAM = 2.0
NAMES = ['dP4_oP4', 'dP4_oG5', 'dP4_oFCS', 'dG5_oP4', 'dG5_oG5', 'dG5_oFCS', 'tal', 'tal_from', 'tal_rec', 'tal_prod', 'winp', 'open', 'logdist', 'inState',
         'down_rec', 'down_prod', 'down_st', 'up_prod']
RANK = {'P4': 2, 'G5': 1, 'FCS': 0}


def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def schools(rows):
    """per season: each school's level, talent z, record, and share leaving at each position"""
    by = defaultdict(list)
    for r in rows: by[(r['season'], r['tid'])].append(r)
    out = defaultdict(dict)
    for (s, tid), rs in by.items():
        g = [x['rec'] for x in rs if x['rec']]
        pos = defaultdict(lambda: [0, 0])
        for x in rs:
            if x['played']: pos[x['g']][0] += x['y'] != 'stay'; pos[x['g']][1] += 1
        out[s][tid] = {'level': rs[0]['level'], 'rec': float(np.mean(g)) if len(g) >= 5 else None,
                       'winp': rs[0]['winp'] if rs[0]['winp'] is not None else 0.5,
                       'open': {k: v[0] / v[1] for k, v in pos.items() if v[1]}}
    for s, d in out.items():   # talent z within the season; schools with few graded recruits get the level's low end
        v = np.array([x['rec'] for x in d.values() if x['rec'] is not None]); mu, sd = v.mean(), v.std()
        lo = {lv: np.percentile([x['rec'] for x in d.values() if x['rec'] is not None and x['level'] == lv] or [mu], 10) for lv in ('P4', 'G5', 'FCS')}
        for x in d.values(): x['tal'] = ((x['rec'] if x['rec'] is not None else lo[x['level']]) - mu) / sd
        opens = defaultdict(list)
        for x in d.values():
            for k, v in x['open'].items(): opens[k].append(v)
        for x in d.values(): x['openMean'] = {k: float(np.mean(v)) for k, v in opens.items()}
    return out


def feats(m, j, sch, loc, tfrom=0.0, ctx=None):
    """one mover m against one school j (tfrom: his current school's talent z; ctx: the coaching, conference and
    money terms, EXTRA)"""
    lv, o = sch['level'], m['level']
    rz = (m['rec'] - 80) / 5 if m['rec'] else -1.0
    prod = (m['pct'] - 0.5) if m['pct'] is not None else 0.0
    st = loc[j][2] if j in loc else None
    d = miles(m['home'], loc[j]) if j in loc else 600
    op = sch['open'].get(m['g'], sch['openMean'].get(m['g'], 0.3))
    dn, up = float(RANK[lv] < RANK[o]), float(RANK[lv] > RANK[o])
    return [lv == 'P4' and o == 'P4', lv == 'P4' and o == 'G5', lv == 'P4' and o == 'FCS', lv == 'G5' and o == 'P4', lv == 'G5' and o == 'G5', lv == 'G5' and o == 'FCS',
            sch['tal'], sch['tal'] * tfrom, sch['tal'] * rz, sch['tal'] * prod, sch['winp'] - 0.5, op, math.log1p(d / 100), float(st is not None and st == m['homeState']),
            dn * max(rz, -1.0), dn * prod, dn * (m['starter'] or 0), up * prod] + (extra(m, j, sch, ctx, rz, prod) if ctx else [])


# ---- coaching, conference and money (Oct 25 2026) ---------------------------------------------------------
# newhc   the school has a new head coach for next season (live: the coaching market's chance the job opens)
# follow  the school's next head coach is the one he played for (live: his coach's chance of taking that job,
#         the market's flows). Before this, HC_FOLLOW (.39) was laid over the fit as a mixture.
# newhc_from  a new head coach where he is now x a step down: a coaching change frees players to drop a level
# sameConf    a school in his own conference (scheme, travel, film he knows)
# don     the school's donor money: log contributions to athletics, FY2022 (USA Today NCAA finances, public
#         schools; private schools and gaps at their level's median, flagged), z across schools. The NIL outside
#         option: the market a school's boosters can fund. don_gap: money there over money where he is now,
#         x his recruiting grade and x his production (a good player's offers rise most with money)
# private  no public finances: private schools (Notre Dame, USC, Stanford, the Ivies...) and service academies,
#         which admit fewer transfers (credits, admissions)
EXTRA = ['newhc', 'follow', 'newhc_from', 'sameConf', 'don', 'private', 'don_gap_rec', 'don_gap_prod']


def extra(m, j, sch, ctx, rz, prod):
    co, cj = ctx['conf'].get(m['tid']), ctx['conf'].get(j)
    dj, do = ctx['don'].get(j), ctx['don'].get(m['tid'])
    lvj, lvo = sch['level'], m['level']
    dzj = dj if dj is not None else ctx['donLevel'][lvj]
    dzo = do if do is not None else ctx['donLevel'][lvo]
    dn = float(RANK[lvj] < RANK[lvo])
    return [ctx['newhc'].get(j, 0.0), ctx['follow'].get((m['tid'], j), 0.0), ctx['newhc'].get(m['tid'], 0.0) * dn,
            float(co is not None and co == cj and 'Independent' not in co), dzj, float(dj is None),
            (dzj - dzo) * max(rz, -1.0), (dzj - dzo) * prod]


def design(movers, S, loc, C=None):
    Xs, idx = [], []
    for m in movers:
        cand = [j for j in S[m['season']] if j != m['tid'] and j in loc]
        if m['to'] not in cand: continue
        cand.remove(m['to']); cand.insert(0, m['to'])
        tf = S[m['season']].get(m['tid'], {}).get('tal', 0.0)
        ctx = C[m['season']] if C else None
        Xs.append(np.array([feats(m, j, S[m['season']][j], loc, tf, ctx) for j in cand], float)); idx.append(m)
    return Xs, idx


FIN = 'https://sportsdata.usatoday.com/ncaa/finances'
FIN_ALIAS = {'mississippi': 'olemiss', 'northcarolinastate': 'ncstate', 'connecticut': 'uconn', 'centralflorida': 'ucf',
             'nevadalasvegas': 'unlv', 'californiadavis': 'ucdavis', 'sanjosestate': 'sanjosstate', 'appalachianstate': 'appstate',
             'alabamaatbirmingham': 'uab', 'texassanantonio': 'utsa', 'miamiohio': 'miamioh', 'californiapolytechnic': 'calpoly',
             'texaselpaso': 'utep', 'louisianalafayette': 'louisiana', 'southernmississippi': 'southernmiss', 'albany': 'ualbany',
             'samhoustonstate': 'samhouston', 'tennesseechattanooga': 'chattanooga', 'louisianamonroe': 'ulmonroe', 'citadel': 'thecitadel',
             'texasaandmcorpuschristi': 'texasamcorpuschristi', 'tennesseemartin': 'utmartin', 'mcneesestate': 'mcneese',
             'northwesternstatela': 'northwesternstate', 'gramblingstate': 'grambling',
             'nichollsstate': 'nicholls', 'marylandeasternshore': 'marylandeasternshore', 'southeasternlouisiana': 'selouisiana',
             'texasriograndevalley': 'utriograndevalley', 'northcarolinawilmington': 'uncwilmington'}


def finances(names):
    """donor money by school: log contributions (FY2022 or the latest year the school page has), {tid: z}"""
    import html as H
    import re
    import cfb_transfer_fit as T
    page = T.get(FIN) or ''
    out = {}
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', page, re.S)[1:]:
        c = [H.unescape(re.sub('<[^>]+>', '', x)).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', r, re.S)]
        sid = re.findall(r'/ncaa/finances/(\d+)', r)
        k = T.norm(c[1]); k = FIN_ALIAS.get(k, k)
        if k not in names or not sid: continue
        d = T.get(f'{FIN}/{sid[0]}') or ''
        for rr in re.findall(r'<tr[^>]*>(.*?)</tr>', d, re.S)[1:]:
            cc = [H.unescape(re.sub('<[^>]+>', '', x)).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', rr, re.S)]
            if len(cc) >= 4 and cc[0].isdigit() and int(cc[0]) <= 2022:
                v = int(re.sub(r'[^0-9]', '', cc[3]) or 0)
                if v > 0: out[names[k]] = math.log(v); break
    v = np.array(list(out.values())); mu, sd = v.mean(), v.std()
    return {t: (x - mu) / sd for t, x in out.items()}


def head_coaches():
    """{(season, tid): [head coaches, season-start first]} for FBS 2024-26: Wikipedia season infoboxes
    (scripts/cfb_coach_va.py's cache) and this season's start (scripts/data/cfb_hc_start.json)"""
    import cfb_coach_va as V
    V.OFFLINE = True
    _, _, _, _, coach = V.pull()
    out = {k: [V.norm(n) for n in v] for k, v in coach.items() if v and k[0] >= 2023}
    hs = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_hc_start.json')))
    for t, v in hs['coaches'].items(): out[(int(hs['season']), t)] = [V.norm(n) for n in v]
    return out


def contexts(rows, S):
    """per season s0: next season's new head coaches, who each school's next coach coached in s0, conferences, money"""
    import cfb_transfer_fit as T
    hc = head_coaches()
    names = {}
    for r in rows: names.setdefault(T.norm(r['team']), r['tid'])
    don = finances(names)
    C = {}
    for s0 in S:
        s1 = s0 + 1
        newhc, follow, conf = {}, {}, {}
        prev = defaultdict(list)
        for (s, t), v in hc.items():
            if s == s0:
                for n in v: prev[n].append(t)
        for j in S[s0]:
            a, b = hc.get((s0, j)), hc.get((s1, j))
            if a and b:
                newhc[j] = float(b[0] not in a)
                if b[0] not in a:
                    for o in prev.get(b[0], []): follow[(o, j)] = 1.0
            info = T.team_info(s0, j, 'FCS' if S[s0][j]['level'] == 'FCS' else 'FBS')
            conf[j] = info.get('conf')
        lv = defaultdict(list)
        for j, x in S[s0].items():
            if j in don: lv[x['level']].append(don[j])
        C[s0] = {'newhc': newhc, 'follow': follow, 'conf': conf, 'don': don, 'donLevel': {k: float(np.median(v)) if v else -1.0 for k, v in lv.items()} | {
            k: -1.0 for k in ('P4', 'G5', 'FCS') if k not in lv}}
        print(s0, 'new head coaches', int(sum(newhc.values())), 'of', len(newhc), 'follow pairs', len(follow), 'money', sum(j in don for j in S[s0]), 'of', len(S[s0]))
    return C


def clogit(Xs, lam=LAM, iters=50):
    k = Xs[0].shape[1]; b = np.zeros(k)
    for _ in range(iters):
        g = -lam * b; H = -lam * np.eye(k)
        for X in Xs:
            u = X @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
            xb = p @ X
            g += X[0] - xb
            H -= (X * p[:, None]).T @ X - np.outer(xb, xb)
        step = np.linalg.solve(H, g); b -= step
        if np.abs(step).max() < 1e-7: break
    return b, np.sqrt(np.diag(np.linalg.inv(-H)))


def evaluate(Xs, b):
    ll, ranks, top10 = 0.0, [], 0
    for X in Xs:
        u = X @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
        ll += math.log(p[0]); r = int((p > p[0]).sum()) + 1; ranks.append(r); top10 += r <= 10
    n = len(Xs); base = -sum(math.log(X.shape[0]) for X in Xs)
    return {'n': n, 'logLik': round(ll / n, 3), 'logLikUniform': round(base / n, 3), 'skill': round(1 - ll / base, 3),
            'medianRank': int(np.median(ranks)), 'top10': round(top10 / n, 3), 'schools': int(np.median([X.shape[0] for X in Xs]))}


def paired(Xa, ba, Xb, bb):
    """per-mover log-lik gain of model b over model a on the same movers: mean and t"""
    def ll(Xs, b):
        out = []
        for X in Xs:
            u = X @ b; u -= u.max(); out.append(u[0] - math.log(np.exp(u).sum()))
        return np.array(out)
    d = ll(Xb, bb) - ll(Xa, ba)
    return round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)


def mixture_ll(Xs, b, cols, fi, h):
    """held-out log lik per mover under the follow mixture: with chance h he goes where his head coach went (split
    evenly if the coach is at two schools' lists), else the logit picks among the other schools"""
    out = []
    for X in Xs:
        u = X[:, cols] @ b; u -= u.max(); p = np.exp(u); p /= p.sum()
        j = X[:, fi] > 0
        if not j.any(): out.append(math.log(p[0])); continue
        pm = h * float(j[0]) / j.sum() + (1 - h) * (0.0 if j[0] else p[0] / (1 - p[j].sum()))
        out.append(math.log(max(pm, 1e-12)))
    return np.array(out)


def main():
    rows = json.load(open(ROWS)); loc = json.load(open(LOC))
    S = schools(rows)
    C = contexts(rows, S)
    movers = [r for r in rows if r['y'] == 'transfer' and r['home'] and r['to'] and not r['abroad']]
    old = [m for m in movers if m['season'] == 2024]; new = [m for m in movers if m['season'] == 2025]
    Xo, _ = design(old, S, loc, C); Xn, _ = design(new, S, loc, C)
    nb = len(NAMES); fi = nb + EXTRA.index('follow')
    base = list(range(nb))
    # players who went with their head coach are the mixture's (HC_FOLLOW in cfb_transfer.mjs), not the logit's:
    # the logit is fit on everyone else (a follow term inside the logit is near-deterministic and blows up)
    lg = lambda Xs: [X for X in Xs if X[0, fi] == 0]
    folds = [('2024->2025', Xo, Xn), ('2025->2024', Xn, Xo)]
    h_of = lambda Xs: float(np.mean([X[0, fi] > 0 for X in Xs if X[:, fi].max() > 0]))

    def run(cols, h=None):
        """held-out per-mover log-lik gain of cols over the old terms (both under the follow mixture): mean, t"""
        out = []
        for _, A, B in folds:
            hh = h_of(A) if h is None else h
            b0, _ = clogit([X[:, base] for X in lg(A)]); b1, _ = clogit([X[:, cols] for X in lg(A)])
            d = mixture_ll(B, b1, cols, fi, hh) - mixture_ll(B, b0, base, fi, hh)
            out.append((round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)))
        return out
    terms = {}
    for k, n in enumerate(EXTRA):
        if n == 'follow': continue
        cols = base + [nb + k] + ([nb + EXTRA.index('don')] if n.startswith('don_') else [])
        terms[n] = run(cols)
        print(n, terms[n])
    # kept: gains held out in both directions, Stouffer t of the two folds >= 2
    keep = [n for n, r in terms.items() if all(g > 0 for g, _ in r) and sum(t for _, t in r) / math.sqrt(2) >= 2]
    print('kept', keep)
    cols = base + [nb + EXTRA.index(n) for n in keep]
    names = NAMES + keep
    # the follow share: out of time both ways (the share from one cycle scoring the other) against no follow at all
    fol = []
    for f, A, B in folds:
        hh = h_of(A); b0, _ = clogit([X[:, cols] for X in lg(A)])
        d = mixture_ll([X for X in B if X[:, fi].max() > 0], b0, cols, fi, hh) - mixture_ll([X for X in B if X[:, fi].max() > 0], b0, cols, fi, 0.0)
        fol.append({'fold': f, 'h': round(hh, 3), 'exposed': int(sum(X[:, fi].max() > 0 for X in A)), 'll': round(float(d.mean()), 3),
                    't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)})
    print('follow', fol)
    hAll = h_of(Xo + Xn)
    bo, _ = clogit([X[:, cols] for X in lg(Xo)]); test = evaluate([X[:, cols] for X in Xn], bo)
    bb, _ = clogit([X[:, base] for X in lg(Xo)]); test['before'] = evaluate([X[:, base] for X in Xn], bb)
    test['gain'] = [dict(zip(('fold', 'll', 't'), (f, *g))) for (f, _, _), g in zip(folds, run(cols))]
    test['terms'] = {n: [dict(zip(('ll', 't'), g)) for g in r] for n, r in terms.items()}
    test['follow'] = fol
    print('landing, out of time', test)
    b, se = clogit([X[:, cols] for X in lg(Xo + Xn)])
    print({n: (round(float(x), 3), round(float(s), 3)) for n, x, s in zip(names, b, se)}, 'follow share', round(hAll, 3))
    latest = max(S)
    fit = json.load(open(FIT))
    don = C[latest]['don']
    fit['landing'] = {'names': names, 'coef': [round(float(x), 4) for x in b], 'se': [round(float(x), 4) for x in se], 'test': test,
                      'n': len(Xo) + len(Xn), 'season': latest, 'follow': round(hAll, 3),
                      # each school: level, talent z, and (when the money term or its flag is in) donor money z or null
                      'schools': {j: [x['level'], round(x['tal'], 3), round(don[j], 3) if j in don else None] for j, x in S[latest].items() if j in loc},
                      'conf': {j: C[latest]['conf'].get(j) for j in S[latest] if j in loc}}
    json.dump(fit, open(FIT, 'w'), indent=1)
    print('wrote landing into', FIT)


LEDGER = os.path.join(ROOT, 'scripts', 'data', 'ledger', 'landing_2027.json')


def freeze():
    """write the pre-registered models (both) before the January 2027 window"""
    fit = json.load(open(FIT))['landing']
    rows = json.load(open(ROWS)); loc = json.load(open(LOC)); S = schools(rows); C = contexts(rows, S)
    movers = [r for r in rows if r['y'] == 'transfer' and r['home'] and r['to'] and not r['abroad']]
    X, _ = design(movers, S, loc, C); nb = len(NAMES); fi = nb + EXTRA.index('follow')
    b0, _ = clogit([x[:, list(range(nb))] for x in X if x[0, fi] == 0])
    out = {'frozen': '2026-10-25', 'season': 2026,
           'base': {'names': NAMES, 'coef': [round(float(v), 4) for v in b0], 'follow': 0.39},
           'full': {'names': fit['names'], 'coef': fit['coef'], 'follow': fit['follow']}}
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(out, open(LEDGER, 'w'), indent=1)
    print('froze', LEDGER)


def score():
    """the pre-registered score of the January 2027 window (see the docstring); writes data/cfb_landing_2027.json"""
    import cfb_transfer_fit as T
    reg = json.load(open(LEDGER))
    T.PAIRS = [(2026, 2027)]; T.SEASONS = [2026, 2027]
    tdiv, info, rosters, ath = T.collect()
    rows, loc = T.build(tdiv, info, rosters, ath, T.recruits(), T.pfn())
    S = schools(rows); C = contexts(rows, S)
    movers = [r for r in rows if r['y'] == 'transfer' and r['home'] and r['to'] and not r['abroad']]
    X, _ = design(movers, S, loc, C); nb = len(NAMES); fi = nb + EXTRA.index('follow')
    res = {}
    for k in ('base', 'full'):
        m = reg[k]; cols = [NAMES.index(n) if n in NAMES else nb + EXTRA.index(n) for n in m['names']]
        res[k] = mixture_ll(X, np.array(m['coef']), cols, fi, m['follow'])
        res[k + 'Eval'] = evaluate([x[:, cols] for x in X], np.array(m['coef']))
    d = res['full'] - res['base']
    exp = [x for x in X if x[:, fi].max() > 0]
    out = {'n': len(X), 'gain': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
           'base': res['baseEval'], 'full': res['fullEval'], 'followShare': round(float(np.mean([x[0, fi] > 0 for x in exp])), 3) if exp else None,
           'exposed': len(exp)}
    out['pass'] = bool(out['gain'] > 0 and out['t'] >= 2)
    json.dump(out, open(os.path.join(ROOT, 'data', 'cfb_landing_2027.json'), 'w'), indent=1)
    print(out)


if __name__ == '__main__':
    freeze() if '--freeze' in sys.argv else score() if '--score' in sys.argv else main()
