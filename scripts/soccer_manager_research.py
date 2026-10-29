#!/usr/bin/env python3
"""Manager changes in soccer (Oct 2026 edge sweep): does the close or the game model miss a club's first matches
under a new head coach?

    python3 scripts/soccer_manager_research.py      # -> data/soccer_manager_research.json

Data: Wikidata head-coach statements (P286 on the club, start date at day precision), joined to ESPN clubs through
the Transfermarkt club id (P7223 -> soccer_squad_mv.json.gz espn2tm). A change is a stint whose coach differs from
the club's previous stint; caretakers count (a later permanent appointment starts a new count). Mid-season: the club
had played 5+ league matches that season before the change; else summer.
Tests, tune 2013-22 vs held out 2023+, every league with a closing 1X2 price:
  1. vs the close: points won minus the close's expected points for the side in matches 1-6 after a change, and a
     fitted 1X2 tilt p_home x exp(b z), p_away x exp(-b z) on the Shin close (z = new-coach home minus away).
  2. vs the model: the same residual against the walk-forward model; a log-rate shift for the new-coach side; the
     early-match learning-rate boost restarted at a change (n = 0)."""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soccer_data as D
import soccer_games as G

OUT = os.path.join(G.ROOT, 'data', 'soccer_manager_research.json')
WDC = os.path.join(D.CACHE, 'wd_coaches.json')
SPARQL = ('SELECT ?club ?tm ?coach ?start ?prec ?end WHERE { ?club wdt:P7223 ?tm . ?club p:P286 ?st . '
          '?st ps:P286 ?coach . ?st pqv:P580 ?sv . ?sv wikibase:timeValue ?start . ?sv wikibase:timePrecision ?prec . '
          'OPTIONAL {?st pq:P582 ?end} }')
LEAGUES = [lg for lg in D.FD_DIV] + list(D.FD_NEW)
NMAX = 6


def wikidata():
    """every dated head-coach stint on a club with a Transfermarkt id (query.wikidata.org allows ~1 query a minute)"""
    if os.path.exists(WDC):
        return json.load(open(WDC))
    u = 'https://query.wikidata.org/sparql?' + urllib.parse.urlencode({'query': SPARQL, 'format': 'json'})
    for _ in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'arkndjl-research/1.0 (https://arkndjl.net)'}), timeout=300)
            b = json.load(r)['results']['bindings']
            json.dump(b, open(WDC, 'w'))
            return b
        except Exception:
            time.sleep(65)
    raise SystemExit('wikidata unreachable')


def changes():
    """ESPN club id -> sorted change days"""
    e2t = D.load(G.MVF)['espn2tm']
    t2e = defaultdict(list)
    for e, t in e2t.items():
        t2e[str(t)].append(e)
    st = defaultdict(list)
    for b in wikidata():
        if b['prec']['value'] != '11':
            continue
        st[b['tm']['value']].append((b['start']['value'][:10], b['coach']['value'].rsplit('/', 1)[-1]))
    out = {}
    for tm, L in st.items():
        L.sort()
        ch = [L[i][0] for i in range(1, len(L)) if L[i][1] != L[i - 1][1] and L[i][0] >= '2011-07-01']
        for e in t2e.get(tm, []):
            out[e] = ch
    return out


def tag(rows, ch):
    """on each row: hk/ak = the side's match number under its new coach (1..) if a change came in the last NMAX
    matches, hm/am = 1 if that change was mid-season"""
    played = defaultdict(list)            # club -> days of matches played
    lgn = defaultdict(int)                # (club, season) -> league matches so far
    since = {}                            # club -> (change day, matches since, mid)
    for r in rows:
        if r.get('hs') is None:
            continue
        for s, t in (('h', r['h']), ('a', r['a'])):
            cs = ch.get(t)
            k, mid = 0, 0
            if cs:
                last = played[t][-1] if played[t] else '0000'
                new = [c for c in cs if last < c <= r['day']]
                if new:
                    S = D.season_of(new[-1], r['lg'])
                    since[t] = [new[-1], 0, int(lgn[(t, S)] >= 5)]
                if t in since:
                    since[t][1] += 1
                    k, mid = since[t][1], since[t][2]
                    if k > 40:
                        del since[t]
            r[s + 'k'], r[s + 'm'] = k, mid
        played[r['h']].append(r['day']); played[r['a']].append(r['day'])
        if r['lg'] not in D.EURO and r['lg'] not in D.CUPS:
            S = D.season_of(r['day'], r['lg'])
            lgn[(r['h'], S)] += 1; lgn[(r['a'], S)] += 1
    return rows


def z_of(r, lo=1, hi=NMAX, mid=None):
    f = lambda s: 1.0 if lo <= r[s + 'k'] <= hi and (mid is None or r[s + 'm'] == mid) else 0.0
    return f('h') - f('a')


def resid(xs, prob, lo, hi, mid):
    """points minus expected points for each new-coach side (home and away rows pooled), clustered by day"""
    d, k = [], []
    for r in xs:
        p = prob(r)
        if not p:
            continue
        y = G.res(r)
        for s, sign in (('h', 1), ('a', -1)):
            if lo <= r[s + 'k'] <= hi and (mid is None or r[s + 'm'] == mid):
                if s == 'h':
                    d.append((3 if y == 0 else 1 if y == 1 else 0) - (3 * p[0] + p[1]))
                else:
                    d.append((3 if y == 2 else 1 if y == 1 else 0) - (3 * p[2] + p[1]))
                k.append(r['day'])
    return {'n': len(d), 'pts': round(sum(d) / max(1, len(d)), 3), 't': G.cl_t(d, k)}


def tilt(p, b, z):
    a, c = p[0] * math.exp(b * z), p[2] * math.exp(-b * z)
    s = a + p[1] + c
    return [a / s, p[1] / s, c / s]


def tilt_test(tune, hold, zf):
    """fit b on tune by grid, report held-out log loss change vs the plain close"""
    def ll(xs, b):
        return [G.ll_of(tilt(r['_c'], b, zf(r)), G.res(r)) - G.ll_of(r['_c'], G.res(r)) for r in xs if zf(r)]
    grid = [i / 100 for i in range(-30, 31)]
    best = min(grid, key=lambda b: sum(ll(tune, b)))
    if best == 0:
        return {'b': 0.0, 'note': 'no tilt helps on tune'}
    dt_, dh = ll(tune, best), ll(hold, best)
    kt = [r['day'] for r in tune if zf(r)]; kh = [r['day'] for r in hold if zf(r)]
    return {'b': best, 'tune': {'n': len(dt_), 'dLL': round(sum(dt_) / max(1, len(dt_)) * 1e4, 2), 't': G.cl_t(dt_, kt)},
            'hold': {'n': len(dh), 'dLL': round(sum(dh) / max(1, len(dh)) * 1e4, 2), 't': G.cl_t(dh, kh)}}


def run(rows, P, scored, shift=0.0, restart=False, mid=None):
    """G.run with every league in `scored` scored, a log-rate shift for the new-coach side and an optional restart of
    the early-match learning-rate boost at a change. Returns id -> (S, day, lg, logloss, probs)"""
    out = {}
    R = G.Ratings(P)
    R.set_membership(rows)
    for r in rows:
        if r.get('hs') is None:
            continue
        R.prep(r)
        if restart:
            for s, t in (('h', r['h']), ('a', r['a'])):
                if r[s + 'k'] == 1 and (mid is None or r[s + 'm'] == mid):
                    R.n[t] = 0
        if r['lg'] in scored and r['st'] == 'FT':
            S = D.season_of(r['day'], r['lg'])
            if S >= G.SCORE_FROM:
                lh, la = R.lambdas(r)
                z = z_of(r, mid=mid) if shift else 0.0
                if z:
                    lh, la = lh * math.exp(shift * z), la * math.exp(-shift * z)
                p = G.wdl(lh, la, P['rho'])
                out[r['id']] = (S, r['day'], r['lg'], G.ll_of(p, G.res(r)), p)
        R.update(r)
    return out


def compare(base, new, lo, hi, only=None):
    d, k = [], []
    for i, b in base.items():
        if lo <= b[0] <= hi and (only is None or only(i)):
            d.append(new[i][3] - b[3]); k.append(b[1])
    return {'n': len(d), 'dLL': round(sum(d) / max(1, len(d)) * 1e4, 2), 't': G.cl_t(d, k)}


def main():
    ch = changes()
    rows = G.add_inj(G.add_mv(G.add_market(D.load(G.HIST))))
    tag(rows, ch)
    P = G.params()
    res = {'clubs': len(ch), 'changes': sum(len(v) for v in ch.values())}
    xs = [r for r in rows if r['lg'] in LEAGUES and r.get('hs') is not None and r['st'] == 'FT']
    for r in xs:
        r['_c'] = G.close_probs(r) or G.novig(r.get('nc'))
    xs = [r for r in xs if r['_c'] and D.season_of(r['day'], r['lg']) >= G.SCORE_FROM]
    tune = [r for r in xs if D.season_of(r['day'], r['lg']) <= G.TUNE[1]]
    hold = [r for r in xs if D.season_of(r['day'], r['lg']) >= G.HOLD_FROM]
    res['coverage'] = {'rowsWithClose': len(xs), 'newCoachSides': sum((0 < r['hk'] <= NMAX) + (0 < r['ak'] <= NMAX) for r in xs)}
    cov = defaultdict(lambda: [0, 0])
    for r in xs:
        for s in 'ha':
            if r[s + 'k'] == 1:
                cov[r['lg']][r[s + 'm']] += 1
    res['changesSeenByLeague'] = {lg: {'summer': v[0], 'mid': v[1]} for lg, v in sorted(cov.items())}
    # 1. vs the close
    vc = {}
    for nm, lo, hi, mid in (('1-6 mid', 1, 6, 1), ('1-6 summer', 1, 6, 0), ('1-3 mid', 1, 3, 1), ('4-6 mid', 4, 6, 1),
                            ('7-12 mid', 7, 12, 1)):
        vc[nm] = {'tune': resid(tune, lambda r: r['_c'], lo, hi, mid), 'hold': resid(hold, lambda r: r['_c'], lo, hi, mid),
                  'tilt': tilt_test(tune, hold, lambda r, lo=lo, hi=hi, mid=mid: z_of(r, lo, hi, mid))}
        if nm == '1-6 mid':
            vc[nm]['bySeason'] = {S: resid([r for r in xs if D.season_of(r['day'], r['lg']) == S], lambda r: r['_c'], lo, hi, mid)
                                  for S in range(G.SCORE_FROM, 2028)}
        print('close', nm, json.dumps(vc[nm]), flush=True)
    res['vsClose'] = vc
    # 2. vs the model
    scored = set(LEAGUES) | G.SCORED
    base = run(rows, P, scored)
    pm = {i: v[4] for i, v in base.items()}
    tune_m = [r for r in tune if r['id'] in pm]; hold_m = [r for r in hold if r['id'] in pm]
    vm = {}
    for nm, lo, hi, mid in (('1-6 mid', 1, 6, 1), ('1-6 summer', 1, 6, 0), ('1-3 mid', 1, 3, 1), ('7-12 mid', 7, 12, 1)):
        vm[nm] = {'tune': resid(tune_m, lambda r: pm[r['id']], lo, hi, mid), 'hold': resid(hold_m, lambda r: pm[r['id']], lo, hi, mid)}
        print('model', nm, json.dumps(vm[nm]), flush=True)
    res['vsModel'] = vm
    terms = []
    flagged = lambda i: i in fl
    fl = {r['id'] for r in rows if (0 < r.get('hk', 0) <= NMAX) or (0 < r.get('ak', 0) <= NMAX)}
    for nm, kw in (('shift +.02 mid', {'shift': 0.02, 'mid': 1}), ('shift +.05 mid', {'shift': 0.05, 'mid': 1}), ('shift -.05 mid', {'shift': -0.05, 'mid': 1}),
                   ('shift +.05 all', {'shift': 0.05}), ('shift -.05 all', {'shift': -0.05}),
                   ('boost restart mid', {'restart': True, 'mid': 1}), ('boost restart all', {'restart': True})):
        s = run(rows, P, scored, **kw)
        t = {'name': nm, 'tune': compare(base, s, *G.TUNE), 'hold': compare(base, s, G.HOLD_FROM, 2100),
             'tuneFlagged': compare(base, s, *G.TUNE, flagged), 'holdFlagged': compare(base, s, G.HOLD_FROM, 2100, flagged)}
        terms.append(t)
        print(json.dumps(t), flush=True)
    res['modelTerms'] = terms
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
