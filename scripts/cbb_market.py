#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College Basketball market tabs, scored daily: NIL (xNIL / yNIL / zNIL), staff, coaching jobs, coach pay and the
team builder. Models from data/cbb_market_fit.json (scripts/cbb_market_fit.py); players from static/data/cbb-all.json.

    python3 scripts/cbb_market.py          # -> data/cbb_market.json, static/data/cbb-builder.json

NIL, per player (CFB definitions, Noah):
  yNIL  what he was likely paid going into the season: each program's budget (cbb_recruit_fit.XNIL by level: high
        major / mid-major / low major, tilted by program strength x e^(.3 z)) split by a preseason index, his
        preseason value^k. The index uses only what was known before the season (last season's college value, else
        the freshman projection from recruiting rank; FV). Frozen per season on first run (scripts/data/cbb_ynil.json).
  xNIL  what he is worth on the open market now: on-field value (college value this season = minutes share x BPM over
        -3, plus a x NBA value at his FV, the XPM over replacement (-1.4, VORX) at the board's cuts) at his market's price; each level's
        pool is its programs' total yNIL; a player at a higher level's rotation standard is priced in that market.
  zNIL  xNIL - yNIL.
  k and a are chosen by fit to On3's valuations (log RMSE; On3 values only the top ~60 players, so a diagnostic).
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cbb_market_fit as M  # noqa: E402
import names as N  # noqa: E402
from cbb_recruit_fit import XNIL, REP_BPM, LEVELS  # noqa: E402
from nba_xpm import VORX_REP  # noqa: E402

ALL = os.path.join(ROOT, 'static', 'data', 'cbb-all.json')
GAMES = os.path.join(ROOT, 'data', 'cbb_games.json')
FIT = os.path.join(ROOT, 'data', 'cbb_market_fit.json')
PMIN = os.path.join(HERE, 'data', 'cbb_proj_min.json')
MOCK = os.path.join(ROOT, 'data', 'cbb_mock.json')
RECS = os.path.join(ROOT, 'data', 'cbb_recruits.json')
DEV = os.path.join(ROOT, 'data', 'school_dev.json')
CBBFIT = os.path.join(ROOT, 'data', 'cbb_fit.json')
YNIL = os.path.join(HERE, 'data', 'cbb_ynil.json')
OUT = os.path.join(ROOT, 'data', 'cbb_market.json')
BUILD = os.path.join(ROOT, 'static', 'data', 'cbb-builder.json')
HM = LEVELS['HM']
ROSTER = 15            # men's basketball roster limit (House settlement, 2025-26 on)
NBA_REPL = VORX_REP    # replacement XPM, the VORX line
FLOOR = 0.3            # value floor: a 10% minutes player at BPM 0 (depth is worth something)
LEVEL_FIT = os.environ.get('CBB_NIL_LEVEL', '0') == '1'   # off: On3's top-42 tail would put the average high-major budget near $18M
SOFT = 0.25            # the NIL budget is a soft target: P(over) cost rises over 25% of budget (as the CFB builder)


def lvl(conf):
    return 'HM' if conf in HM else 'MM' if conf in LEVELS['MM'] else 'LM'


def r0(x, d=0):
    return None if x is None else round(float(x), d) if d else int(round(float(x)))


def money(x):
    return None if x is None else int(round(x / 1000.0) * 1000)


def ht_in(h):
    import re
    m = re.match(r"(\d+)'\s*(\d+)", str(h or ''))
    return int(m[1]) * 12 + int(m[2]) if m else None


def lrk(rec):
    if not rec:
        return -6.2
    v = [-math.log(r) for r in (rec.get('on3rk'), rec.get('rk247')) if r]
    return float(np.mean(v)) if v else -6.2


def xpm_of(fv, cuts):
    pts = sorted((int(k), v) for k, v in cuts.items())
    if fv is None:
        return pts[0][1]
    if fv <= pts[0][0]:
        return pts[0][1] + (fv - pts[0][0]) * (pts[1][1] - pts[0][1]) / (pts[1][0] - pts[0][0])
    for (a, x), (b, y) in zip(pts, pts[1:]):
        if fv <= b:
            return x + (y - x) * (fv - a) / (b - a)
    return pts[-1][1]


def load_players():
    d = json.load(open(ALL))
    c = d['cols']
    P = [dict(zip(c, r)) for r in d['rows']]
    pm = json.load(open(PMIN))['min'] if os.path.exists(PMIN) else {}
    for p in P:
        m = pm.get(f"{p['name']}|{p['team']}")
        if m is None:
            m = (p.get('now') or {}).get('mpg')
            m = m / 40 * 100 if m else 8.0
        p['min'] = max(0.0, min(95.0, m)) / 100
        last = p.get('last') or {}
        p['lastV'] = None
        if last.get('bpm') is not None and last.get('mpg'):
            p['lastV'] = max(0.0, last['mpg'] / 40 * (last['bpm'] - REP_BPM))
        nw = p.get('now') or {}
        u = [(last.get('usg'), min(30, last.get('gp') or 0)), (nw.get('usg'), nw.get('gp') or 0)]
        u = [(a, w) for a, w in u if a is not None and w]
        p['usg'] = sum(a * w for a, w in u) / sum(w for _, w in u) if u else 18.0
        p['hti'] = ht_in(p.get('ht'))
        p['lrk'] = lrk(p.get('rec'))
        p['level'] = lvl(p.get('conf'))
    return P


def team_power():
    g = json.load(open(GAMES))
    return {p['t']: p for p in g['power']}, g


# ---- coaches ---------------------------------------------------------------------------------------------------
def current_coaches(raw, power, B):
    """team -> {name, slug (Sports Reference id), ten}: ESPN's roster feed (cached in data/cbb_market.json between
    runs), matched to last season's Sports Reference coach at the school, else the same name anywhere"""
    import cbb_roster as R
    try:
        E = R.espn_coaches()
    except Exception:
        E = {}
    old = {}
    try:
        old = {c['team']: c for c in json.load(open(OUT)).get('staff', [])}
    except (OSError, ValueError):
        pass
    last = max(raw)
    by_name = defaultdict(list)
    for s in sorted(raw):
        for t, v in raw[s].items():
            by_name[N.key(' '.join(x for x in v['coach'].split('-') if not x.isdigit()))].append((s, v['coach']))
    tp = json.load(open(os.path.join(HERE, 'data', 'cbb_team_prior.json'))).get(str(last + 1), {})
    out = {}
    for t in power:
        b = B.get(t, t)
        c = E.get(b)
        L = raw[last].get(b)
        if c:
            nm = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
            slug = L['coach'] if L and R.same_coach(c, L['coach']) else None
            if slug is None:
                cands = sorted(by_name.get(N.key(nm), []))
                slug = cands[-1][1] if cands else None
        elif t in old:
            nm, slug = old[t]['name'], old[t].get('slug')
        elif L:
            slug = L['coach']; nm = ' '.join(x.capitalize() for x in slug.split('-') if not x.isdigit())
        else:
            continue
        ten = tp.get(b, {}).get('tenure')
        ten = int(round(ten * 10)) if ten is not None and ten < 1 else None
        if ten is None:
            ten = (L.get('ten', 0) + 1) if L and slug == L['coach'] else 1
        out[t] = {'name': nm, 'slug': slug, 'ten': max(1, ten), 'cres': tp.get(b, {}).get('cres', 0.0)}
    return out


# ---- scoring helpers -------------------------------------------------------------------------------------------
def mnl_score(model, rows):
    X = np.array(rows, float)
    F = model['feats']
    mu, sd, B = np.array(model['mu']), np.array(model['sd']), np.array(model['B'])
    return M.mnl_p((X - mu) / sd, B)


def pick(full, model_feats, all_feats):
    return [full[all_feats.index(f)] for f in model_feats]


def main():
    fit = json.load(open(FIT))
    P = load_players()
    power, G = team_power()
    season = int(str(G.get('season', '2026-27'))[:4]) + 1 if '-' in str(G.get('season', '')) else 2027
    TS, bt = M.team_seasons()
    loc = M.geo(bt)
    raw, miss = M.coaches()
    src = json.load(gzip.open(M.SRC))
    cuts = json.load(open(CBBFIT))['xpmCuts']
    # SRS scale for this season's ratings (the fits use margin SRS)
    srs_sd = float(np.std([x['srs'] for (s, _), x in TS.items() if s == season - 1]))
    rt_sd = float(np.std([p['rating'] for p in power.values()])) or 1
    srs_now = {t: p['rating'] * srs_sd / rt_sd for t, p in power.items()}
    lastconf = {}
    for p in P:
        lastconf.setdefault(p['team'], p['conf'])
    # power and the players use ESPN's school names; history (TS, coaches, arenas) uses Barttorvik's: B maps them
    B = {t: bt.get(p['id'], t) for t, p in power.items()}
    M.P6 = set(HM)          # this season's high majors (the new Pac-12 is a mid-major)
    for t, p in power.items():
        M.CONF[(season, B[t])] = p.get('conf') or lastconf.get(t)
    # conferences of past seasons for the hire/vacancy features
    rows = M.player_rows()
    for y, rs in rows.items():
        for r in rs:
            M.CONF.setdefault((y, r['team']), r['conf'])
    CO = current_coaches(raw, power, B)

    # ---- coaching jobs: P(open) = hired away + out ----------------------------------------------------------
    vac = fit['vacancy']
    jobs = {}
    for t, p in power.items():
        c = CO.get(t)
        if not c:
            continue
        wp = p['xW'] / max(1e-9, p['xW'] + p['xL'])
        nc = p.get('nc') or {}
        ncw = sum(nc.get(k, 0) for k in ('r32', 's16', 'e8', 'f4', 'final', 'champ'))
        full = M.feats_vac(TS, season, B[t], wp, srs_now[t], c['ten'], (p.get('conf') in HM), ncw, nc.get('bid', 0) >= .5, c['cres'] or 0.0)
        # feats_vac's bid flag is 0/1; use the probability
        full[M.VAC_F.index('bid')] = nc.get('bid', 0.0)
        pr = mnl_score(vac, [pick(full, vac['feats'], M.VAC_F)])[0]
        _, wpn = M.prog_norm(TS, season, B[t])
        jobs[t] = {'stay': float(pr[0]), 'moved': float(pr[1]), 'out': float(pr[2]), 'wp': wp, 'vsNorm': wp - (wpn if wpn is not None else wp), 'ncw': ncw}

    # ---- Transfer% (back / moved / gone) ---------------------------------------------------------------------
    mv = fit['move']
    byteam = defaultdict(list)
    for p in P:
        byteam[p['team']].append(p)
    for t, ps in byteam.items():
        for i, p in enumerate(sorted(ps, key=lambda q: -q['min'])):
            p['minrk'] = i + 1
    feats = []
    for p in P:
        r = {'bpm': p.get('xbpm'), 'min_per': p['min'] * 100, 'usg': p['usg'], 'yr': p.get('cls') or 'Fr', 'rg_lrk': p['lrk'], 'hti': p['hti'],
             'gp': 30, 'age': p.get('age')}
        cc = 1 - jobs.get(p['team'], {}).get('stay', 0.85)
        tr = bool((p.get('last') or {}).get('team')) and (p.get('last') or {}).get('team') != p['team']
        full = M.feats_move(r, srs_now.get(p['team']), p.get('conf') in HM, p['minrk'], tr, cc, 0.0)
        feats.append(pick(full, mv['feats'], M.MOVE_F))
    PR = mnl_score(mv, feats)
    # the draft: a 2027 mock pick or a listed returner's declare odds put a floor under "gone"
    mk = json.load(open(MOCK))
    dec = {}
    for x in mk['mocks']['pred']:
        dec[(N.key(x['name']), x.get('school'))] = x.get('declare', 1.0)
    for x in mk.get('staying', []):
        dec[(N.key(x['name']), x.get('school'))] = x.get('declare', 0.0)
    for p, pr in zip(P, PR):
        back, moved, gone = map(float, pr)
        d = dec.get((N.key(p['name']), p['team']))
        p['draft'] = d
        if d is not None and d > gone:
            k = (1 - d) / max(1e-9, back + moved)
            back, moved, gone = back * k, moved * k, d
        p['pBack'], p['pMove'], p['pGone'] = back, moved, gone

    # ---- NIL -----------------------------------------------------------------------------------------------
    for p in P:
        nba = max(0.0, xpm_of(p.get('fv'), cuts) - NBA_REPL)
        p['vNba'] = nba
        p['vCol'] = max(0.0, p['min'] * ((p.get('xbpm') or REP_BPM) - REP_BPM))
        if p['lastV'] is not None:
            p['vPre'] = p['lastV']
        else:   # freshmen and newcomers with no D-I line: the freshman projection from recruiting rank
            fb, fm = fit['fresh']['bpm'], fit['fresh']['min']
            p['vPre'] = max(0.0, max(0.05, min(0.85, (fm[0] + fm[1] * p['lrk']) / 100)) * (fb[0] + fb[1] * p['lrk'] - REP_BPM)) if p.get('rec') else 0.2
    # program strength z (preseason prior rating), within level, and budgets
    pz = {}
    for L in ('HM', 'MM', 'LM'):
        ts = [t for t, p in power.items() if lvl(p.get('conf')) == L]
        v = np.array([power[t]['prior'] for t in ts]); m, s = v.mean(), v.std() or 1
        norm = float(np.mean(np.exp(XNIL['tilt'] * (v - m) / s)))
        for t in ts:
            pz[t] = (power[t]['prior'] - m) / s
            power[t]['_budget'] = XNIL[L] * math.exp(XNIL['tilt'] * pz[t]) / norm
    # On3 valuations for the fit
    on3 = []
    for x in src['on3']['nil100']:
        on3.append((x['name'], None, x['val']))
    for x in src['on3']['portal'].get(str(season - 1), []):
        if x.get('val'):
            on3.append((x['name'], x.get('to'), x['val']))
    mt = N.Matcher(P, name='name', team='team', sport='basketball')
    on3v = {}
    for nm, tm, v in on3:
        r = mt.find(nm, team=tm)[0] if tm else None
        r = r or mt.find(nm)[0]
        if r is not None and v:
            on3v[id(r)] = max(on3v.get(id(r), 0), v)
    fitset = [p for p in P if id(p) in on3v]

    frozen = {}
    if os.path.exists(YNIL):
        f0 = json.load(open(YNIL))
        if f0.get('season') == season:
            frozen = f0['ynil']

    def build(a, kappa, m=1.0):
        val = {id(p): p['vCol'] + a * p['vNba'] + FLOOR for p in P}
        pre = {id(p): p['vPre'] + a * p['vNba'] + FLOOR for p in P}
        yn = {}
        for t, ps in byteam.items():
            if t not in power:
                continue
            w = np.array([pre[id(p)] ** kappa for p in ps]); w = w / w.sum()
            for p, x in zip(ps, w):
                yn[id(p)] = m * power[t]['_budget'] * x
        # markets: a player at a higher level's rotation standard (median value of the level's top-5) is priced there
        std = {}
        for L in ('HM', 'MM'):
            v = []
            for t, ps in byteam.items():
                if t in power and lvl(power[t].get('conf')) == L:
                    v += sorted((val[id(p)] for p in ps), reverse=True)[:5]
            std[L] = float(np.median(v)) if v else 99
        mkt = {}
        for p in P:
            L = p['level']
            mkt[id(p)] = 'HM' if L == 'HM' or val[id(p)] >= std['HM'] else 'MM' if L == 'MM' or val[id(p)] >= std['MM'] else 'LM'
        pool = defaultdict(float); z = defaultdict(float)
        for p in P:
            if id(p) in yn:
                pool[lvl(power[p['team']].get('conf'))] += yn[id(p)]
            z[mkt[id(p)]] += val[id(p)]
        xn = {id(p): pool[mkt[id(p)]] * val[id(p)] / z[mkt[id(p)]] for p in P}
        return yn, xn, mkt, {k: pool[k] / z[k] for k in pool}, std

    def rmse(d):
        e = [(math.log(on3v[id(p)]) - math.log(max(1e3, d[id(p)]))) for p in fitset if id(p) in d]
        return float(np.sqrt(np.mean(np.square(e)))) if e else None, float(np.mean(e)) if e else None
    # On3 values only the top of the market (its NIL 100 and the valued portal entrants), so it is matched as a tail,
    # not player by player, and for shape only: a (the NBA-value weight) by the matched players' log error with the
    # level removed; k (yNIL concentration) so the top-N yNIL quantiles match On3's with the level removed, N = On3's
    # valued players (reported only, see below). The level stays the assumed budgets (cbb_recruit_fit.XNIL): matching On3's level (m, CBB_NIL_LEVEL=1)
    # needs ~3x, an average high-major near $18M, above every reported roster figure (On3's valuations add endorsements)
    def sd_err(d):
        e = [(math.log(on3v[id(p)]) - math.log(max(1e3, d[id(p)]))) for p in fitset if id(p) in d]
        return float(np.std(e)) if e else None
    o3 = sorted(on3v.values(), reverse=True); nq = len(o3)
    grid = {}
    for a in (0.0, 0.5, 1.0, 2.0, 4.0):
        _, xn, _, _, _ = build(a, 1.0)
        grid[a] = sd_err(xn)
    a = min(grid, key=lambda k: grid[k] if grid[k] is not None else 9)
    _, xn, _, _, _ = build(a, 1.0)
    top = sorted(xn.values(), reverse=True)[:nq]
    tail = sum(o3) / sum(top) if nq else None
    mlev = tail if LEVEL_FIT and nq >= 20 else 1.0
    kg = {}
    for kappa in (0.75, 1.0, 1.25, 1.5, 2.0, 2.5):
        yn, _, _, _, _ = build(a, kappa, mlev)
        ty = sorted(yn.values(), reverse=True)[:nq]
        kg[kappa] = float(np.std([math.log(x) - math.log(max(1e3, y)) for x, y in zip(o3, ty)]))
    # kTest is reported, not used: k = 1 keeps yNIL on xNIL's linear form, so zNIL measures value gained or lost and
    # budget against market, not a difference of curves (On3's tail alone would pick k = 2.5+, every star "overpaid")
    kappa = 1.0
    yn, xn, mkt, price, std = build(a, kappa, mlev)
    for p in P:
        f = frozen.get(f"{p['name']}|{p['team']}")
        p['ynil'] = money(f if f is not None else yn.get(id(p)))
        p['xnil'] = money(xn[id(p)])
        p['znil'] = None if p['ynil'] is None else p['xnil'] - p['ynil']
        p['mkt'] = mkt[id(p)]
        p['on3'] = on3v.get(id(p))
    if not frozen:
        with open(YNIL, 'w') as h:
            json.dump({'season': season, 'asof': G.get('asof'), 'ynil': {f"{p['name']}|{p['team']}": p['ynil'] for p in P if p['ynil'] is not None}}, h, separators=(',', ':'))
    xr, xb = rmse({id(p): p['xnil'] for p in P}); yr, yb = rmse({id(p): p['ynil'] or 1e3 for p in P})
    nilfit = {'a': a, 'k': kappa, 'n': len(fitset), 'valueTest': {str(k): r0(v, 3) for k, v in grid.items()}, 'kTest': {str(k): r0(v, 3) for k, v in kg.items()},
              'rmseX': r0(xr, 3), 'biasX': r0(xb, 3), 'rmseY': r0(yr, 3), 'biasY': r0(yb, 3), 'price': {k: money(v) for k, v in price.items()},
              'budget': {k: money(XNIL[k] * mlev) for k in ('HM', 'MM', 'LM')}, 'level': r0(mlev, 3), 'levelFit': LEVEL_FIT, 'on3Tail': r0(tail, 2), 'nTail': nq, 'tilt': XNIL['tilt'], 'rep': REP_BPM}
    print('nil', nilfit)

    # ---- team NIL --------------------------------------------------------------------------------------------
    tnil = {}
    for t, ps in byteam.items():
        if t not in power:
            continue
        y = sum(p['ynil'] or 0 for p in ps); x = sum(p['xnil'] for p in ps)
        top = sorted(ps, key=lambda p: -p['xnil'])[:3]
        tnil[t] = {'y': y, 'x': x, 'z': x - y, 'g': math.log((x + 250e3) / (y + 250e3)), 'top': [[p['name'], p['pos'], p['xnil']] for p in top]}

    # ---- coach pay + value -----------------------------------------------------------------------------------
    val = fit['value']
    yrs = val['years']; vb = np.array(val['b'])
    pay = {}
    inv = {b: t for t, b in B.items()}
    names = set(inv)
    for r in src['pay']['list']:
        bn = M.match_team(r['school'], names)
        if bn:
            pay[inv[bn]] = r
    def value_of(t, ten):
        f = M.val_feats(TS, season, B[t], ten, 0.0, power[t].get('conf') in HM)
        x = [1.0] + [float(z == yrs[-1]) for z in yrs[1:]] + [f[M.VAL_F.index(k)] for k in val['feats']]
        return float(math.exp(np.dot(x, vb)))

    # ---- staff -----------------------------------------------------------------------------------------------
    devrows = {r['id']: r for r in json.load(open(DEV)).get('cbb', {}).get('rows', [])} if os.path.exists(DEV) else {}
    staff = []
    for t, c in CO.items():
        p = power[t]
        d = devrows.get(p['id'])
        cdev = d.get('cdev') if d and d.get('coach') and N.same(d['coach'], c['name']) else None
        tn = tnil.get(t, {})
        pr = pay.get(t)
        paid = pr['pay'] if pr and N.same(pr['name'], c['name']) else None
        v = value_of(t, c['ten'])
        jb = jobs.get(t, {})
        staff.append({'team': t, 'id': p['id'], 'logo': p.get('logo'), 'conf': p.get('conf'), 'name': c['name'], 'slug': c.get('slug'), 'ten': c['ten'],
                      'rating': p['rating'], 'rk': p['rk'], 'over': c['cres'] or 0.0, 'thisOver': round(p['rating'] - p['prior'], 2) if p.get('g') else None,
                      'dev': cdev, 'znil': tn.get('z'), 'znilG': tn.get('g'), 'xnil': tn.get('x'), 'ynil': tn.get('y'),
                      'value': money(v), 'pay': money(paid), 'payYr': yrs[-1] if paid else None, 'buyout': money(pr.get('buyout')) if paid and pr.get('buyout') else None,
                      'surplus': money(v - paid) if paid else None, 'leave': round(1 - jb.get('stay', 0.85), 3), 'lvl': lvl(p.get('conf'))})
    def z(vals):
        a = np.array([x if x is not None else np.nan for x in vals], float)
        m, s = np.nanmean(a), np.nanstd(a) or 1
        return np.where(np.isnan(a), 0.0, (a - m) / s)
    zr, zo, zd = z([s['rating'] for s in staff]), z([s['over'] for s in staff]), z([s['dev'] for s in staff])
    zg = np.zeros(len(staff))
    for L in ('HM', 'MM', 'LM'):
        ix = [i for i, s in enumerate(staff) if s['lvl'] == L]
        zz = z([staff[i]['znilG'] for i in ix])
        for i, v in zip(ix, zz):
            zg[i] = max(-2.5, min(2.5, v))
    rawsc = 0.8 * (0.4 * zr + 0.4 * zo + 0.2 * zd) + 0.2 * zg
    rawsc = (rawsc - rawsc.mean()) / (rawsc.std() or 1)
    for s, x in zip(staff, rawsc):
        s['score'] = int(round(100 + 10 * x))
    staff.sort(key=lambda s: -s['score'])
    for i, s in enumerate(staff):
        s['srk'] = i + 1
    znr = sorted(staff, key=lambda s: -(s['znilG'] or -9))
    for i, s in enumerate(znr):
        s['znilRk'] = i + 1

    # ---- hires: who fills each job if it opens ---------------------------------------------------------------
    hf = fit['hires']; hb = np.array(hf['b'])
    for s_, c in CO.items():
        TS[(season, B[s_])] = {**TS.get((season, B[s_]), {}), 'wp': jobs.get(s_, {}).get('wp', .5), 'srs': srs_now.get(s_, 0.0)}
    cand = [(t, c) for t, c in CO.items()]
    hires = {}
    for t in jobs:
        X, who = [], []
        for s, c in cand:
            if s == t:
                continue
            f = M.feats_hire(TS, season, B[t], B[s], c['cres'] or 0.0, loc, c['ten'])
            X.append(f); who.append((s, c))
        u = np.array(X) @ hb; u -= u.max(); e = np.exp(u); e /= e.sum()
        o = np.argsort(-e)[:3]
        hires[t] = [{'name': who[i][1]['name'], 'from': who[i][0], 'p': round(float(e[i] * hf['fromHC']), 3)} for i in o]
    jl = []
    for t, j in jobs.items():
        p = power[t]
        jl.append({'team': t, 'logo': p.get('logo'), 'conf': p.get('conf'), 'hc': CO[t]['name'], 'ten': CO[t]['ten'], 'open': round(1 - j['stay'], 3),
                   'out': round(j['out'], 3), 'moved': round(j['moved'], 3), 'wp': round(j['wp'], 3), 'vsNorm': round(j['vsNorm'], 3), 'hires': hires.get(t, [])})
    jl.sort(key=lambda x: -x['open'])

    # ---- landing odds for likely movers ----------------------------------------------------------------------
    lf = fit['land']; lb = np.array(lf['b'])
    teams = sorted(power)
    tconf = {t: power[t].get('conf') for t in teams}
    openm = {}
    for t, ps in byteam.items():
        tot = sum(p['min'] for p in ps) or 1
        openm[t] = sum(p['min'] * (1 - p['pBack']) for p in ps) / tot
    newhc = {t: 1 - jobs.get(t, {}).get('stay', .85) for t in teams}
    pool = [p for p in P if p['pMove'] >= 0.12 and p['team'] in power]
    land = {}
    for p in pool:
        o = p['team']
        r = {'bpm': p.get('xbpm')}
        X = [M.feats_land(r, o, t, srs_now.get(t), srs_now.get(o), p.get('conf'), tconf[t], loc.get(B[o]), loc.get(B[t]), False, newhc[t], openm.get(t, .5)) for t in teams]
        X = np.array(X, float)
        # the land fit's power flags are the high-major set (P12 was one through 2024)
        u = X @ lb; u -= u.max(); e = np.exp(u); e /= e.sum()
        land[id(p)] = dict(zip(teams, e)); p['_lmax'] = float(e.max())
    # follow-the-coach: a coach who may move takes players along (odds through the jobs model's hire candidates)

    # ---- team builder ----------------------------------------------------------------------------------------
    sched = fit.get('minsched') or [0.78, 0.74, 0.68, 0.6, 0.52, 0.42, 0.32, 0.22, 0.14, 0.08, 0.05, 0.03, 0.02]
    sched = np.array(sched) / sum(sched) * 5
    dev = fit['dev']

    def nxt(p, to=None):
        """next-season BPM: projected BPM + the NIL-era change by class. No level step for a transfer: Barttorvik's BPM
        is schedule-adjusted and credits team strength (movers gain ~1.0 BPM per 10 points of SRS stepped up, fit 'step'),
        so a step would count the new team's strength twice in the rotation sum"""
        return (p.get('xbpm') or REP_BPM) + dev.get(p.get('cls') or 'Fr', 0.5)

    def rate(bpms):
        """next season's team rating (points per 100 over an average D-I team): the rotation's minutes schedule
        (NIL-era mean minutes by rank within a team) on the best BPMs, empty spots at replacement (-3)"""
        b = sorted(bpms, reverse=True)[:len(sched)]
        b += [REP_BPM] * (len(sched) - len(b))
        return float(sum(s * x for s, x in zip(sched, b)))
    # the rotation sum on the ARK rating's scale: ARK rating now on this season's projected rotations, across D-I
    xs = [(rate([p.get('xbpm') or REP_BPM for p in byteam[t]]), power[t]['rating']) for t in byteam if t in power]
    A = np.array([[1, a] for a, _ in xs]); ra, rk = np.linalg.lstsq(A, np.array([b for _, b in xs]), rcond=None)[0]
    ark = lambda v: float(ra + rk * v)
    print('rotation -> ARK', round(float(ra), 2), round(float(rk), 3))
    recs = json.load(open(RECS)) if os.path.exists(RECS) else {'classes': []}
    commits = defaultdict(list)
    fb = fit['fresh']['bpm']
    for cl in recs.get('classes', []):
        if cl.get('year') != season:
            continue
        for r in cl.get('list', []):
            if r.get('team') and r.get('rk'):
                l = -math.log(r['rk'])
                commits[r['team']].append({'name': r['name'], 'pos': r.get('pos'), 'rk': r['rk'], 'bpm': round(fb[0] + fb[1] * l, 1), 'fv': r.get('fv'),
                                           'x': r.get('xnil')})
    out_b = []
    for t, ps in byteam.items():
        if t not in power:
            continue
        pw = power[t]
        L = lvl(pw.get('conf'))
        budget = (tnil.get(t, {}).get('y') or pw['_budget']) * 1.04
        back = sorted([p for p in ps if p['pBack'] >= 0.5], key=lambda p: -nxt(p))
        leave = sorted([p for p in ps if p['pBack'] < 0.5], key=lambda p: -p['xnil'])
        cm = commits.get(t, [])
        cost = sum(p['xnil'] for p in back) + sum(c.get('x') or 0 for c in cm)
        base = [nxt(p) for p in back] + [c['bpm'] for c in cm]
        r_ret = rate(base)
        spots = max(0, ROSTER - len(back) - len(cm))
        # the offseason as a GM would run it (the CFB builder's order): the incoming class is held, returners likely back
        # (P(back) >= .5) are paid at market (xNIL), then the money left buys the most team rating among two pools:
        #   keep  his own likely transfers (P(back) < .5, not leaving D-I: P(gone) < .5), retained at market price;
        #   sign  likely movers for whom this school is a real destination (landing share at least a fifth of his best
        #         school's and 2x random), at market price
        # chosen greedily by marginal rating gain less a Lagrange price on dollars, the price set so spend meets the
        # budget (soft: up to +25%), within the 15-man roster and at most 8 signings
        cands = []
        for q in ps:
            if q['pBack'] < 0.5 and q['pGone'] < 0.5:
                cands.append(('keep', q, 1 - q['pGone'], max(25e3, q['xnil'])))
        for q in pool:
            if q['team'] == t or q['pBack'] >= 0.5:
                continue
            lp = land[id(q)].get(t, 0)
            if lp < max(2.0 / len(teams), 0.2 * q['_lmax']):
                continue
            if rate(base + [nxt(q, t)]) - r_ret < 0.25:
                continue
            cands.append(('sign', q, q['pMove'] * lp, max(25e3, q['xnil'])))
        room = max(0.0, budget * (1 + SOFT) - cost)

        def choose(lam):
            chosen, cur, sp, ns = [], list(base), 0.0, 0
            while len(chosen) < spots:
                r_now = rate(cur)
                best = None
                for kind, q, odds, c in cands:
                    if (kind == 'sign' and ns >= 8) or sp + c > room or any(q is x[1] for x in chosen):
                        continue
                    g = rate(cur + [nxt(q, t)]) - r_now
                    sc = g - lam * c / 1e6
                    if g >= 0.25 and sc > 0 and (best is None or sc > best[0]):
                        best = (sc, kind, q, odds, g, c)
                if not best:
                    break
                chosen.append(best[1:]); cur.append(nxt(best[2], t)); sp += best[5]; ns += best[1] == 'sign'
            return chosen, cur, sp
        lo, hi = 0.0, 50.0
        for _ in range(18):
            mid = (lo + hi) / 2
            _, _, sp = choose(mid)
            if sp > budget - cost and sp > 0:
                lo = mid
            else:
                hi = mid
        chosen, cur, sp = choose(hi)
        spend = cost + sp
        kept = {id(q) for k, q, *_ in chosen if k == 'keep'}
        plan = [{'kind': k, 'name': q['name'], 'team': q['team'], 'logo': q.get('logo'), 'pos': q['pos'], 'cls': q.get('cls'), 'fv': q.get('fv'),
                 'bpm': round(nxt(q, t), 1), 'cost': money(c), 'odds': round(odds, 4), 'gain': round(g * rk, 2), 'tp': round(q['pMove'], 3)} for k, q, odds, g, c in chosen]
        leave = [p for p in leave if id(p) not in kept]
        why = lambda p: 'draft' if (p.get('draft') or 0) >= max(p['pMove'], 0.3) else 'eligibility' if p.get('cls') == 'Sr' and p['pGone'] >= p['pMove'] else 'transfer' if p['pMove'] >= p['pGone'] else 'leaves D-I'
        out_b.append({'t': t, 'id': pw['id'], 'logo': pw.get('logo'), 'conf': pw.get('conf'), 'coach': CO.get(t, {}).get('name'), 'rk': pw['rk'],
                      'budget': money(budget), 'spend': money(spend), 'now': round(pw['rating'], 1), 'ret': round(ark(r_ret), 1), 'after': round(ark(rate(cur)), 1),
                      'back': [{'name': p['name'], 'pos': p['pos'], 'cls': p.get('cls'), 'fv': p.get('fv'), 'bpm': round(nxt(p), 1), 'p': round(p['pBack'], 2), 'x': p['xnil']} for p in back],
                      'leave': [{'name': p['name'], 'pos': p['pos'], 'cls': p.get('cls'), 'fv': p.get('fv'), 'why': why(p), 'back': round(p['pBack'], 2), 'tp': round(p['pMove'], 2), 'x': p['xnil']} for p in leave],
                      'commits': cm, 'plan': plan})
    out_b.sort(key=lambda x: x['rk'])

    # ---- outputs ---------------------------------------------------------------------------------------------
    nil = sorted(P, key=lambda p: -p['xnil'])[:400]
    nil_rows = [{'name': p['name'], 'team': p['team'], 'logo': p.get('logo'), 'conf': p.get('conf'), 'pos': p['pos'], 'cls': p.get('cls'), 'fv': p.get('fv'),
                 'x': p['xnil'], 'y': p['ynil'], 'z': p['znil'], 'on3': p['on3'], 'mkt': p['mkt'], 'tp': round(p['pMove'], 3), 'back': round(p['pBack'], 3)} for p in nil]
    teams_nil = sorted([{'team': t, 'logo': power[t].get('logo'), 'conf': power[t].get('conf'), **{k: v for k, v in d.items() if k != 'g'}, 'g': round(d['g'], 3)}
                        for t, d in tnil.items()], key=lambda x: -x['x'])
    tp_rows = sorted([p for p in P if p['team'] in power], key=lambda p: -p['pMove'])[:300]
    transfer = [{'name': p['name'], 'team': p['team'], 'logo': p.get('logo'), 'conf': p.get('conf'), 'pos': p['pos'], 'cls': p.get('cls'), 'fv': p.get('fv'),
                 'bpm': p.get('xbpm'), 'tp': round(p['pMove'], 3), 'back': round(p['pBack'], 3), 'gone': round(p['pGone'], 3), 'x': p['xnil']} for p in tp_rows]
    out = {'asof': G.get('asof'), 'season': season, 'nilFit': nilfit, 'nil': nil_rows, 'teamsNil': teams_nil, 'staff': staff, 'jobs': jl,
           'transfer': transfer, 'tests': {k: fit[k]['test'] for k in ('move', 'land', 'vacancy', 'hires')}, 'value': {k: fit['value'][k] for k in ('feats', 'n', 'looR2', 'looRmse')},
           'eOpen': round(sum(x['open'] for x in jl), 1)}
    with open(OUT, 'w') as h:
        json.dump(out, h, separators=(',', ':'))
    with open(BUILD, 'w') as h:
        json.dump({'asof': G.get('asof'), 'season': season, 'roster': ROSTER, 'teams': out_b}, h, separators=(',', ':'))
    print('staff', len(staff), 'jobs', len(jl), 'E[open]', out['eOpen'], 'builder', len(out_b), 'movers pool', len(pool))


if __name__ == '__main__':
    main()
