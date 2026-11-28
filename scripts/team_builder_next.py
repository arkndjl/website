#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Team builder, next season: adds to each plan in static/data/cfb-builder.json (scripts/cfb_transfer.mjs teamBuilder)
and static/data/cbb-builder.json (scripts/cbb_market.py) what the page needs to read it as next season's team.

    python3 scripts/team_builder_next.py          # after fetch_cfb.mjs / cbb_market.py (cfb-board.yml, cbb.yml)
    python3 scripts/team_builder_next.py --test

Per team:
  nx    next season's strength. CFB: Elo from the plan's AV a season (this season's Elo on this season's AV across FBS,
        least squares with a Power 4 step; r2 kept), before the portal (ret), with the usual portal (exp) and after the
        plan. CBB: the builder's ARK rating (returning, after). Rank among FBS / D-I teams on the same projection.
  xw    wins over a conference schedule at those strengths: CFB 12 games, each Elo's win chance against every
        conference mate at its own projection (1 / (1 + 10^(-d/400))); CBB 31 games, P(win) = Phi(d x .68 / 11.4) (the
        rating is points per 100 possessions; 68 a game, the game model's margin sd 11.4)
  war   wins over a replacement team (the 10th percentile projection) on the same schedule
  eff   NIL dollars a win over replacement: next season's spend (kept roster + class + plan) / war, and its rank
  bud   the reported budget for next season (data/nil_budgets.json, low and high, x the market's yearly growth)
  cls   the incoming class: FV, Y1 FV, ARK stars, On% (CFB), $ (xNIL)
  dect  DECT on returners and departures (Declare / Even / College / Transfer), where the draft boards carry it
  pot   potential recruits: uncommitted recruits this school is in on, next class ("next", counted in the projection)
        and the one after ("later", listed), each with P(he signs here):
          1. the ARK lean model's chance for this school when the model has him (its top three schools; the held-out
             calibrated LIST model, data/recruit_commit_top.json; CFB already reads visits and expert picks),
          2. else On3's RPM share for the school at its latest reading,
          3. else his visits: the rate at which recruits who took k official visits signed with one of those schools,
             and for an unofficial-only school the same by unofficial count, read from the committed recruits' On3
             visit lists (scripts/data/recruit_on3_committed.json.gz; visits after the commitment are in there, so
             the rates run high). Per recruit the schools' chances are scaled to sum to 1 at most.
        Expert picks are shown beside it (k experts on the school of n). gain = P x his value added to the plan:
        CFB P x On% x the AV his Y1 FV adds to the room (the room's depth weights), in Elo; CBB P x the ARK rating
        his projected BPM adds to the rotation. nx.pot = the plan with every next-class target's expected gain.
"""
import gzip, json, math, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SD = os.path.join(ROOT, 'static', 'data')
CFB_GAMES, CBB_GAMES = 12, 31
CBB_POSS, CBB_SD = 0.68, 11.4
REPL_Q = 0.10


def ncdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def lsq(X, y):
    """ordinary least squares, small dense (no numpy needed here)"""
    k = len(X[0]); A = [[sum(X[i][a] * X[i][b] for i in range(len(X))) for b in range(k)] for a in range(k)]
    v = [sum(X[i][a] * y[i] for i in range(len(X))) for a in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c])); A[c], A[p] = A[p], A[c]; v[c], v[p] = v[p], v[c]
        for r in range(k):
            if r != c and A[c][c]:
                f = A[r][c] / A[c][c]; A[r] = [x - f * y_ for x, y_ in zip(A[r], A[c])]; v[r] -= f * v[c]
    return [v[i] / A[i][i] for i in range(k)]


def quant(xs, q):
    s = sorted(xs); return s[min(len(s) - 1, max(0, int(q * len(s))))] if s else None


def sched(teams, key, conf_of, pwin, games):
    """xw for every team at strength key, against its conference mates (all teams when it has none)"""
    by = {}
    for t in teams: by.setdefault(conf_of(t), []).append(t)
    def xw(t, s):
        opp = [o for o in by.get(conf_of(t), []) if o is not t] or [o for o in teams if o is not t]
        return games * sum(pwin(s, key(o)) for o in opp) / len(opp)
    return xw


def budget_next(sport, team, season_next):
    B = json.load(open(os.path.join(ROOT, 'data', 'nil_budgets.json')))[sport]
    v = B['teams'].get(team)
    if not v: return None
    g = B.get('growth', 1.0) ** max(0, season_next - B.get('season', season_next))
    return [round(v[0] * g * 1e6, -4), round(v[1] * g * 1e6, -4)]


def rank(teams, key):
    o = sorted(teams, key=lambda t: -key(t)); return {id(t): i + 1 for i, t in enumerate(o)}


def r1(x): return None if x is None else round(x, 1)


def J(*a, gz=False):
    f = os.path.join(ROOT, *a)
    if not os.path.exists(f): return {}
    return json.load(gzip.open(f) if gz else open(f))


# ---------------------------------------------------------------------------------------------- potential recruits
POT_MIN = 0.05   # a school under a 5% chance is not a target
POT_N = 15


def top_by_year(rows):
    """the POT_N likeliest-and-best targets of each class"""
    out = []
    for y in sorted({o['yr'] for o in rows}):
        L = sorted([o for o in rows if o['yr'] == y], key=lambda o: -((o['p'] or 0) * (o['fv'] or 0) + (o['fv'] or 0) / 1e3))
        out += L[:POT_N]
    return out


def visit_rates():
    """(official?, k) -> share of committed recruits' visited schools that he signed with, both sports pooled; k = his
    count of official visits (unofficial-only schools: his unofficial count), 5 = five or more. k = 1 official reads
    the k = 2 rate (a lone official is usually the school he already picked)"""
    sys.path.insert(0, HERE)
    import names, player_moves as PM
    from recruit_on3_join import slug_map
    d = J('scripts', 'data', 'recruit_on3_committed.json.gz', gz=True); agg = defaultdict(lambda: [0, 0])
    for sp, cl in d.items():
        sm = slug_map(sp); rec = PM.site_recruits(sp)
        for y, rows in cl.items():
            m = names.Matcher(rec.get(int(y)) or [], team=None)
            for o in rows:
                r, _ = m.find(o.get('name'))
                ch = r and (str(r['tid']) if r.get('tid') else CBB_ID.get(names.team_key(r.get('team') or '')))
                if not ch: continue
                ov = {sm[v[0]] for v in o.get('visits') or [] if v[1] == 'Official' and v[0] in sm}
                uv = {sm[v[0]] for v in o.get('visits') or [] if v[1] != 'Official' and v[0] in sm} - ov
                for x in ov: a = agg[(1, min(len(ov), 5))]; a[0] += x == ch; a[1] += 1
                if not ov:
                    for x in uv: a = agg[(0, min(len(uv), 5))]; a[0] += x == ch; a[1] += 1
    R = {}
    for o in (1, 0):
        for k in range(1, 6):
            a = agg[(o, k)]; R[(o, k)] = (a[0] + 1) / (a[1] + 4) if a[1] else None   # +1 / +4: a small prior on thin cells
        R[(1, 1)] = R[(1, 2)]
    return R, {f"{'ov' if o else 'uv'}{k}": [round(v, 3), agg[(o, k)][1]] for (o, k), v in R.items() if v is not None}


def pot_sources(sp, classes):
    """{year: [recruit row + {'sch': {espn id: {p, src, lean, rpm, ex, ov, uv}}}]} for the uncommitted recruits of the
    given classes ({year: rows})"""
    sys.path.insert(0, HERE)
    import names
    from recruit_on3_join import slug_map
    sm = slug_map(sp)
    top = J('data', 'recruit_commit_top.json').get(sp, {}); lean1 = J('data', 'recruit_commit_leans.json').get(sp, {})
    rpm1 = J('data', 'recruit_rpm.json').get(sp, {}); ex = J('data', 'recruit_expert_picks.json').get(sp, {})
    live = J('scripts', 'data', 'recruit_on3_live.json.gz', gz=True).get(sp, {})
    R, _ = RATES
    out = {}
    for y, rows in classes.items():
        ys = str(y); m = names.Matcher(rows, team=None); on3 = {}
        for o in live.get(ys) or []:
            r, _ = m.find(o.get('name'))
            if r and not (o.get('state') and r.get('home') and not r['home'].endswith(o['state'])): on3[r['name']] = o
        res = []
        for r in rows:
            if r.get('team') or r.get('tid') or r.get('status') not in (None, 'uncommitted'): continue
            S = defaultdict(dict)
            L = top.get(ys, {}).get(r['name']) or ([lean1[ys][r['name']]] if r['name'] in lean1.get(ys, {}) else [])
            for nm, pc, tid in L: S[str(tid)]['lean'] = pc
            o = on3.get(r['name']) or {}
            lead = max(o.get('lead') or [], key=lambda x: x[0], default=None)
            for row in (lead[1] if lead else []) or []:
                if row and row[0] in sm and row[1]: S[sm[row[0]]]['rpm'] = round(row[1])
            if not lead and r['name'] in rpm1.get(ys, {}):
                nm, pc, tid = rpm1[ys][r['name']]; S[str(tid)]['rpm'] = round(pc)
            if r['name'] in ex.get(ys, {}):
                nm, k, n, tid = ex[ys][r['name']]; S[str(tid)]['ex'] = [k, n]
            ov = {sm[v[0]] for v in o.get('visits') or [] if v[1] == 'Official' and v[0] in sm}
            uv = {sm[v[0]] for v in o.get('visits') or [] if v[1] != 'Official' and v[0] in sm} - ov
            for x in ov: S[x]['ov'] = 1
            for x in uv: S[x]['uv'] = 1
            for t, v in S.items():
                if L: v['p'], v['src'] = (v['lean'] / 100, 'lean') if 'lean' in v else (None, None)
                elif 'rpm' in v: v['p'], v['src'] = v['rpm'] / 100, 'rpm'
                elif v.get('ov') and R[(1, min(len(ov), 5))]: v['p'], v['src'] = R[(1, min(len(ov), 5))], 'visit'
                elif v.get('uv') and not ov and R[(0, min(len(uv), 5))]: v['p'], v['src'] = R[(0, min(len(uv), 5))], 'visit'
                else: v['p'], v['src'] = None, None
            tot = sum(v['p'] or 0 for v in S.values())
            if tot > 1:
                for v in S.values():
                    if v['p']: v['p'] /= tot
            S = {t: v for t, v in S.items() if (v['p'] or 0) >= POT_MIN or v.get('ex')}
            if S: res.append(dict(r, sch=S))
        out[y] = res
    return out


def pot_row(r, v, yr, cfb):
    o = {'name': r['name'], 'pos': r.get('pos'), 'yr': yr, 'fv': r1(r.get('xfv') if cfb else r.get('fv')), 'y1': r1(r.get('fvOn') if cfb else r.get('y1fv')),
         'ark': r.get('ark'), 'stars': r.get('stars'), 'rk': r.get('rank') if cfb else r.get('rk'), 'x': r.get('xnil'),
         'p': None if v['p'] is None else round(v['p'], 3), 'src': v['src']}
    if cfb: o['on'] = r.get('pOn')
    for k in ('lean', 'rpm', 'ex', 'ov', 'uv'):
        if v.get(k) is not None: o[k] = v[k]
    return o


def cfb_room(src):
    """roomAv's constants from scripts/cfb_transfer.mjs and scripts/cfb_teams.mjs (read, not copied)"""
    a = open(os.path.join(HERE, 'cfb_teams.mjs')).read(); b = open(os.path.join(HERE, 'cfb_transfer.mjs')).read()
    avt = json.loads(re.search(r'const AV_BY_FV = (\[\[.*?\]\]);', a).group(1))
    st = json.loads(re.sub(r'(\w+):', r'"\1":', re.search(r'export const STARTERS = (\{.*?\});', a).group(1)))
    dw = json.loads(re.sub(r'(\w+):', r'"\1":', re.search(r'const DEPTH_W = (\{.*?\});', b, re.S).group(1).replace('\n', ' ')))
    fill = float(re.search(r'const FILL = (\d+)', b).group(1))
    def avOf(f):
        for (f0, a0), (f1, a1) in zip(avt, avt[1:]):
            if f <= f1: return a0 + (a1 - a0) * max(0, f - f0) / (f1 - f0)
        return avt[-1][1]
    def room(fvs, g, repl):
        fvs = sorted(fvs, reverse=True); W = dw[g]; n = st.get(g, 1)
        return sum(W[k] * avOf(max(fvs[k] if k < len(fvs) else repl, repl) if k < n else (fvs[k] if k < len(fvs) else fill)) for k in range(len(W)))
    return room, set(dw)


# ------------------------------------------------------------------------------------------- seasons 2 and 3
# scripts/team_years.py (the roster chain) with the fit in data/team_years_fit.json (scripts/research/team_years_nov28):
# a season k out = mean + sd x (a + b z(strength now) + c z(roster chain talent k)), z across this builder's teams
import team_years as TY  # noqa: E402

CFB_G = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OT': 'OL', 'OG': 'OL', 'C': 'OL', 'OL': 'OL', 'IOL': 'OL', 'DE': 'EDGE',
         'EDGE': 'EDGE', 'OLB': 'LB', 'DT': 'DL', 'DL': 'DL', 'ILB': 'LB', 'LB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S', 'ATH': 'WR', 'K': 'K', 'P': 'P'}
CBB_G = {'PG': 'G', 'SG': 'G', 'G': 'G', 'G/F': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'PF/C': 'C', 'C': 'C'}


def rec_pos(sp, year, name, fallback):
    """the projected college position (data/recruit_pos.json, PR #1364), first spot of a hybrid label"""
    v = RPOS.get(sp, {}).get(f'{year}|{name}')
    lab = (v[0] if v else fallback) or ''
    return lab.split('/')[0] if sp == 'cfb' else lab


RPOS = J('data', 'recruit_pos.json')


def rec_lab(sp, year, name, fallback):
    """the projected position label as the class tables show it (hybrids kept)"""
    v = RPOS.get(sp, {}).get(f'{year}|{name}')
    return v[0] if v else fallback


def season_proj(T, now, tal, fit, key):
    """{id(team): {k: z}} for k = 1, 2, 3 (k = 1: the roster chain's own next season, beside the plan)"""
    zs = lambda d: (lambda v: {i: (x - v.mean()) / (v.std() or 1) for i, x in d.items()})(__import__('numpy').array(list(d.values()), float))
    zn, out = zs({id(t): now(t) for t in T}), {}
    for k in (1, 2, 3):
        zt = zs({id(t): tal[k].get(key(t), 0.0) for t in T})
        for t in T: out.setdefault(id(t), {})[k] = TY.predict(fit['h'][str(k)], zn[id(t)], zt[id(t)])
    return out


def put_years(T, Z, now_of, conf, pw, games, unit, rnd):
    import numpy as np
    v = np.array([now_of(t) for t in T], float); m, sd = float(v.mean()), float(v.std())
    for k in (1, 2, 3):
        S = {id(t): m + sd * Z[id(t)][k] for t in T}
        xw = sched(T, lambda o: S[id(o)], conf, pw, games); rk = rank(T, lambda o: S[id(o)])
        for t in T: t['nx']['y%d' % k] = {unit: rnd(S[id(t)]), 'rk': rk[id(t)], 'xw': round(xw(t, S[id(t)]), 1)}


def cfb_years(D, T, conf, pw):
    """seasons 2 and 3 and the roster by season (static/data/cfb-builder-ros.json: per team, every graded player and
    commit with P(on this roster) in each of the next three seasons)"""
    fit = J('data', 'team_years_fit.json').get('cfb')
    if not fit: return None
    stay = {int(c): v for c, v in fit['live']['stay'].items()}; dev = {int(c): v for c, v in fit['live']['dev'].items()}
    by = TY.cfb_index(J('scripts', 'data', 'cfb_recruits_cfbd.json.gz', gz=True))
    A = J('static', 'data', 'cfb-all.json'); c = {k: i for i, k in enumerate(A['cols'])}
    tids = {t['team']: str(t['tid']) for t in T}; y0 = int(D['next']) - 1
    rows, ros = [], defaultdict(list)
    for r in A['rows']:
        tm = r[c['team']]
        if tm not in tids: continue
        cl = TY.CFB_CLS.get(r[c['cls']] or '')
        if not cl: continue
        _, comp = TY.cfb_recruit(by, r[c['name']], tm, y0)
        p0 = r[c['stayP']]
        rows.append({'t': tids[tm], 'c': cl, 'v': TY.cfb_value(comp), 'p0': p0})
        p1 = p0 if p0 is not None else stay[cl]; p2 = p1 * stay[min(4, cl + 1)]; p3 = p2 * stay[min(4, cl + 2)]
        dl = r[c['dectL']] if 'dectL' in c else None
        ros[tids[tm]].append([r[c['name']], r[c['pos']], r[c['cls']], r[c['fv']], round(p1, 2), round(p2, 2), round(p3, 2), 'back', dl])
    R = J('static', 'data', 'cfb-recruits.json'); nx = int(R['next'])
    groups = [(nx, R.get('class') or [])] + [(int(f['year']), f.get('list') or []) for f in R.get('future') or []]
    for yr, L in groups:
        for x in L:
            if not x.get('tid') or x.get('status') not in ('committed', 'signed', 'enrolled'): continue
            if yr == nx: rows.append({'t': str(x['tid']), 'c': 1, 'new': 1, 'v': TY.cfb_value(x.get('comp'))})
            k = yr - nx; ps = [0.0] * k + [1.0]
            while len(ps) < 3: ps.append(ps[-1] * stay[min(4, len(ps) - k)])
            ros[str(x['tid'])].append([x['name'], CFB_G.get(rec_pos('cfb', yr, x['name'], x.get('pos')), x.get('g')), 'HS ' + str(yr), r1(x.get('xfv')), *[round(v, 2) for v in ps[:3]], 'cls', None])
    later = defaultdict(list)
    for yr, L in groups[1:]:
        for x in L:
            if x.get('tid') and x.get('status') in ('committed', 'signed', 'enrolled'):
                later[str(x['tid'])].append({'name': x['name'], 'pos': rec_lab('cfb', yr, x['name'], x.get('pos')), 'yr': yr, 'fv': r1(x.get('xfv')), 'y1': r1(x.get('fvOn')),
                                             'ark': x.get('ark'), 'stars': x.get('stars'), 'rk': x.get('rank'), 'x': x.get('xnil')})
    for t in T: t['cls2'] = sorted(later.get(str(t['tid']), []), key=lambda c: (c['yr'], -(c['fv'] or 0)))
    tal = {k: TY.chain(rows, stay, dev, k) for k in (1, 2, 3)}
    Z = season_proj(T, lambda t: t['nx']['now']['e'], tal, fit, lambda t: str(t['tid']))
    put_years(T, Z, lambda t: t['nx']['now']['e'], conf, pw, CFB_GAMES, 'e', round)
    for t in T:
        for pl in t.get('plan') or []:
            cl = min(4, TY.CFB_CLS.get(pl.get('cls') or '', 3) + 1)
            ros[str(t['tid'])].append([pl['name'], pl.get('slot') or pl.get('pos'), pl.get('cls'), r1(pl.get('fv')), 1.0, round(stay[cl], 2), round(stay[cl] * stay[min(4, cl + 1)], 2), 'new', None])
    out = {tid: sorted(L, key=lambda x: -(x[3] or 0)) for tid, L in ros.items()}
    json.dump({'cols': ['name', 'pos', 'cls', 'fv', 'p1', 'p2', 'p3', 'kind', 'dect'], 'next': nx, 'teams': out},
              open(os.path.join(SD, 'cfb-builder-ros.json'), 'w'), separators=(',', ':'), allow_nan=False)
    return {'stay': fit['live']['stay'], 'h': {k: {x: v[x] for x in ('pass', 't', 'r2_0', 'r2_1', 'n')} for k, v in fit['h'].items()}}


DEVC = TY.curve_of(J('data', 'team_years_dev.json').get('cbb'))


def dev_path(v1, c1, age1, m):
    """pXPM in each of the next three seasons: next season's projection, then the development curve (class, age,
    level, role; data/team_years_dev.json, passed held out) a season at a time"""
    if v1 is None or not DEVC: return [v1, None, None]
    out, v, c, a = [round(v1, 1)], v1, min(4, c1), age1
    for _ in range(2):
        v += DEVC(c, a, v, m); c = min(4, c + 1); a = a + 1 if a else None; out.append(round(v, 1))
    return out


def cbb_years(D, T, conf, pw):
    fit = J('data', 'team_years_fit.json').get('cbb')
    if not fit: return None
    stay = {int(c): v for c, v in fit['live']['stay'].items()}; dev = {int(c): v for c, v in fit['live']['dev'].items()}
    F = J('data', 'cbb_market_fit.json'); fb, fm = F['fresh']['bpm'], F['fresh']['min']
    sch = F.get('minsched') or [0.78, 0.74, 0.68, 0.6, 0.52, 0.42, 0.32, 0.22, 0.14, 0.08, 0.05, 0.03, 0.02]
    REP = -3.0
    rows, ros = [], defaultdict(list)
    for t in T:
        L = [(x, x['p']) for x in t.get('back') or []] + [(x, x['back']) for x in t.get('leave') or []]
        L.sort(key=lambda a: -(a[0].get('bpm') if a[0].get('bpm') is not None else -9))
        for i, (x, p0) in enumerate(L):
            cl = TY.CLS.get(x.get('cls'))
            if not cl: continue
            if x.get('bpm') is not None:
                m = x['mn'] if x.get('mn') is not None else (sch[i] if i < len(sch) else 0.0)
                rows.append({'t': t['t'], 'c': cl, 'v': x['bpm'] - REP, 'm': m, 'p0': p0})
            p2 = p0 * stay[min(4, cl + 1)]; p3 = p2 * stay[min(4, cl + 2)]
            vs = dev_path(x.get('bpm'), cl + 1, (x.get('age') or 0) + 1 or None, x.get('mn') or 0.0)
            ros[t['t']].append([x['name'], x.get('pos'), x.get('cls'), x.get('fv'), round(p0, 2), round(p2, 2), round(p3, 2), 'back', (x.get('dect') or [None])[0], *vs])
    R = J('data', 'cbb_recruits.json'); nx = int(D['season'])
    for g in R.get('classes') or []:
        yr = int(g['year'])
        for x in g.get('list') or []:
            if not x.get('team') or yr < nx or yr > nx + 2: continue
            if yr == nx and x.get('rk'):
                l = -math.log(x['rk'])
                rows.append({'t': x['team'], 'c': 1, 'new': 1, 'v': fb[0] + fb[1] * l - REP, 'm': (fm[0] + fm[1] * l) / 100})
            k = yr - nx; ps = [0.0] * k + [1.0]
            while len(ps) < 3: ps.append(ps[-1] * stay[min(4, len(ps) - k)])
            vs = [None, None, None]
            if x.get('rk'):
                l = -math.log(x['rk']); vs = [None] * k + dev_path(round(fb[0] + fb[1] * l, 1), 1, None, (fm[0] + fm[1] * l) / 100)[:3 - k]
            ros[x['team']].append([x['name'], CBB_G.get(rec_pos('cbb', yr, x['name'], x.get('pos')), x.get('pos')), 'HS ' + str(yr), x.get('fv'), *[round(v, 2) for v in ps[:3]], 'cls', None, *vs])
    later = defaultdict(list)
    for g in R.get('classes') or []:
        yr = int(g['year'])
        if yr <= nx: continue
        for x in g.get('list') or []:
            if x.get('team'):
                later[x['team']].append({'name': x['name'], 'pos': rec_lab('cbb', yr, x['name'], x.get('pos')), 'yr': yr, 'fv': r1(x.get('fv')), 'y1': r1(x.get('y1fv')),
                                         'ark': x.get('ark'), 'stars': x.get('stars'), 'rk': x.get('rk'), 'x': x.get('xnil')})
    for t in T: t['cls2'] = sorted(later.get(t['t'], []), key=lambda c: (c['yr'], -(c['fv'] or 0)))
    tal = {k: TY.chain(rows, stay, dev, k) for k in (1, 2, 3)}
    Z = season_proj(T, lambda t: t['now'], tal, fit, lambda t: t['t'])
    put_years(T, Z, lambda t: t['now'], conf, pw, CBB_GAMES, 'r', lambda v: round(v, 1))
    for t in T:
        for pl in t.get('plan') or []:
            cl = min(4, TY.CLS.get(pl.get('cls') or '', 3) + 1)
            ros[t['t']].append([pl['name'], pl.get('pos'), pl.get('cls'), pl.get('fv'), 1.0, round(stay[cl], 2), round(stay[cl] * stay[min(4, cl + 1)], 2), 'keep' if pl.get('kind') == 'keep' else 'new', None,
                                *dev_path(pl.get('bpm'), cl, None, 0.5)])
    out = {tm: sorted(L, key=lambda x: -(x[3] or 0)) for tm, L in ros.items()}
    json.dump({'cols': ['name', 'pos', 'cls', 'fv', 'p1', 'p2', 'p3', 'kind', 'dect', 'v1', 'v2', 'v3'], 'next': nx, 'teams': out, 'vLab': 'pXPM'},
              open(os.path.join(SD, 'cbb-builder-ros.json'), 'w'), separators=(',', ':'), allow_nan=False)
    return {'stay': fit['live']['stay'], 'h': {k: {x: v[x] for x in ('pass', 't', 'r2_0', 'r2_1', 'n')} for k, v in fit['h'].items()}}


RATES = None
CBB_ID = {}   # team key -> ESPN id (the CBB class rows name the school only)


# ---------------------------------------------------------------------------------------------------------- CFB
def cfb():
    p = os.path.join(SD, 'cfb-builder.json')
    if not os.path.exists(p): return None
    D = json.load(open(p)); T = D['teams']
    tj = json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))
    elo = {t['tid']: t.get('elo') for t in tj['teams'] if t.get('elo') is not None}
    # this season's Elo on this season's roster AV (FV-based, depth-weighted), with a Power 4 step
    fit = [t for t in T if t['tid'] in elo]
    X = [[1.0, t['av26'], 1.0 if t['level'] == 'P4' else 0.0] for t in fit]; y = [elo[t['tid']] for t in fit]
    b = lsq(X, y)
    pred = [sum(bi * xi for bi, xi in zip(b, x)) for x in X]; my = sum(y) / len(y)
    r2 = 1 - sum((a - c) ** 2 for a, c in zip(y, pred)) / sum((a - my) ** 2 for a in y)
    E = lambda av, t: b[0] + b[1] * av + b[2] * (t['level'] == 'P4')
    pw = lambda a, c: 1 / (1 + 10 ** (-(a - c) / 400))
    for t in T:
        t['_e'] = {'now': elo.get(t['tid'], E(t['av26'], t)), 'ret': E(t['av27'], t), 'exp': E(t['avExp'], t), 'plan': E(t['avPlan'], t)}
    conf = lambda t: t.get('conf') if t.get('conf') and not str(t.get('conf')).startswith('IND') else '_' + t['level']
    WK = json.load(open(os.path.join(ROOT, 'data', 'cfb_war_backtest.json')))['constants']['cwarPerAv']
    out = {}
    for k in ('now', 'ret', 'exp', 'plan'):
        xw = sched(T, lambda o: o['_e']['plan' if k != 'now' else 'now'], conf, pw, CFB_GAMES)
        rk = rank(T, lambda o: o['_e'][k])
        for t in T: out.setdefault(id(t), {})[k] = {'e': round(t['_e'][k]), 'rk': rk[id(t)], 'xw': round(xw(t, t['_e'][k]), 1)}
    rep = quant([t['_e']['plan'] for t in T], REPL_Q)
    xwp = sched(T, lambda o: o['_e']['plan'], conf, pw, CFB_GAMES)
    for t in T:
        war = out[id(t)]['plan']['xw'] - xwp(t, rep)
        spend = t['budget'] - t['left']
        t['nx'] = out[id(t)]; t['war'] = r1(max(0.0, war)); t['spendNext'] = int(spend)
        t['eff'] = int(round(spend / max(war, 0.5), -3))
        t['warSea'] = r1(t['avPlan'] * WK)
        t['bud'] = budget_next('cfb', t['team'], D['next'])
    er = rank(T, lambda o: -o['eff'])
    for t in T: t['effRk'] = er[id(t)]
    # the class (static/data/cfb-recruits.json) and the redshirts and young players' next FV are already in the chart;
    # here the committed class with its grades
    try:
        R = json.load(open(os.path.join(SD, 'cfb-recruits.json')))
        cls = {}
        for x in R.get('class') or []:
            if x.get('tid') and x.get('status') in ('committed', 'signed', 'enrolled'):
                cls.setdefault(x['tid'], []).append({'name': x['name'], 'pos': rec_lab('cfb', int(R['next']), x['name'], x.get('pos')), 'fv': r1(x.get('xfv')), 'y1': r1(x.get('fvOn')), 'on': x.get('pOn'),
                                                     'ark': x.get('ark'), 'stars': x.get('stars'), 'rk': x.get('rank'), 'x': x.get('xnil')})
        for t in T: t['cls'] = sorted(cls.get(t['tid'], []), key=lambda c: -(c['fv'] or 0))
    except (OSError, ValueError): pass
    # potential recruits
    try:
        R = json.load(open(os.path.join(SD, 'cfb-recruits.json')))
        room, G = cfb_room(None)
        cls_by = {int(R['next']): R.get('class') or []}
        for f in R.get('future') or []: cls_by[int(f['year'])] = f.get('list') or []
        nxt_y = int(R['next']); later = [y for y in sorted(cls_by) if y > nxt_y][:2]
        src = pot_sources('cfb', {y: cls_by[y] for y in [nxt_y] + later})
        byT = defaultdict(lambda: {'next': [], 'later': []})
        for y, rows in src.items():
            for r in rows:
                for tid, v in r['sch'].items(): byT[tid]['next' if y == nxt_y else 'later'].append((r, v, y))
        gs = lambda g: ['WR', 'RB', 'CB', 'S'] if g == 'ATH' else ['DL'] if g == 'DT' else [g]
        for t in T:
            P = {pz['g']: pz for pz in t['positions']}; gain = 0.0; pot = {}
            for k in ('next', 'later'):
                rows = []
                for r, v, y in byT.get(str(t['tid']), {}).get(k, []):
                    o = pot_row(r, v, y, True)
                    if k == 'next' and o['p'] and o['y1'] is not None:
                        best = 0.0
                        for g in gs(r.get('g') or r.get('pos')):
                            pz = P.get(g)
                            if not pz or g not in G: continue
                            base = [c['fv'] for c in pz.get('chart') or [] if c.get('kind') != 'open' and c.get('fv') is not None]
                            best = max(best, room(base + [o['y1']], g, pz['repl']) - room(base, g, pz['repl']))
                        o['av'] = round(o['p'] * (o['on'] or 0) * best, 2); o['g'] = round(o['av'] * b[1]); gain += o['av']
                    rows.append(o)
                pot[k] = top_by_year(rows)
            t['pot'] = pot; t['_e']['pot'] = t['_e']['plan'] + b[1] * gain
            t['potX'] = int(round(sum((o['p'] or 0) * (o['x'] or 0) for o in pot['next']), -3))
        xw = sched(T, lambda o: o['_e']['pot'], conf, pw, CFB_GAMES); rk = rank(T, lambda o: o['_e']['pot'])
        for t in T: t['nx']['pot'] = {'e': round(t['_e']['pot']), 'rk': rk[id(t)], 'xw': round(xw(t, t['_e']['pot']), 1)}
    except (OSError, ValueError, KeyError) as e: print('cfb pot', repr(e))
    # DECT from the draft board (cfb-all.json rows carry dectL once the board run writes it)
    try:
        A = json.load(open(os.path.join(SD, 'cfb-all.json'))); c = {k: i for i, k in enumerate(A['cols'])}
        dk = {}
        if 'dectL' in c:
            for r in A['rows']:
                if r[c['dectL']]: dk[(r[c['name']], r[c['team']])] = [r[c['dectL']], r[c['dect']] if 'dect' in c else None, r[c['dectP']] if 'dectP' in c else None]
        for t in T:
            for L in (t.get('leaving') or [], t.get('keep') or [], t.get('priced') or []):
                for x in L:
                    v = dk.get((x['name'], t['team']))
                    if v: x['dect'] = v
            for pz in t['positions']:
                for x in pz.get('chart') or []:
                    v = dk.get((x.get('name'), t['team']))
                    if v and x.get('kind') == 'back': x['dect'] = v
    except (OSError, ValueError, KeyError): pass
    for t in T: t.pop('_e', None)
    try: yrs = cfb_years(D, T, conf, pw)
    except (OSError, ValueError, KeyError) as e: print('cfb years', repr(e)); yrs = None
    D['nxFit'] = {'years': yrs, 'b': [round(v, 3) for v in b], 'r2': round(r2, 3), 'n': len(fit), 'games': CFB_GAMES, 'replQ': REPL_Q, 'warPerAv': WK,
                  'pot': pot_fit(T, 'cfb')}
    json.dump(D, open(p, 'w'), separators=(',', ':'), allow_nan=False)
    return D['nxFit']


# ---------------------------------------------------------------------------------------------------------- CBB
def cbb():
    p = os.path.join(SD, 'cbb-builder.json')
    if not os.path.exists(p): return None
    D = json.load(open(p)); T = D['teams']
    pw = lambda a, c: ncdf((a - c) * CBB_POSS / CBB_SD)
    conf = lambda t: t.get('conf') or '_'
    out = {}
    for k, key in (('now', 'now'), ('ret', 'ret'), ('plan', 'after')):
        xw = sched(T, lambda o: o['after'] if k != 'now' else o['now'], conf, pw, CBB_GAMES)
        rk = rank(T, lambda o: o[key])
        for t in T: out.setdefault(id(t), {})[k] = {'r': t[key], 'rk': rk[id(t)], 'xw': round(xw(t, t[key]), 1)}
    rep = quant([t['after'] for t in T], REPL_Q)
    xwp = sched(T, lambda o: o['after'], conf, pw, CBB_GAMES)
    for t in T:
        war = out[id(t)]['plan']['xw'] - xwp(t, rep)
        t['nx'] = out[id(t)]; t['war'] = r1(max(0.0, war))
        t['eff'] = int(round(t['spend'] / max(war, 0.5), -3))
        t['bud'] = budget_next('cbb', t['t'], D['season'])
    er = rank(T, lambda o: -o['eff'])
    for t in T: t['effRk'] = er[id(t)]
    try:
        R = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))
        cls = {}
        for c in R.get('classes') or []:
            if c.get('year') != D['season']: continue
            for x in c.get('list') or []:
                if x.get('team'):
                    cls.setdefault(x['team'], {})[x['name']] = {'pos': rec_lab('cbb', c['year'], x['name'], x.get('pos')), 'fv': r1(x.get('fv')), 'y1': r1(x.get('y1fv')), 'ark': x.get('ark'), 'stars': x.get('stars')}
        for t in T:
            for cm in t.get('commits') or []:
                cm.update({k: v for k, v in (cls.get(t['t'], {}).get(cm['name']) or {}).items() if v is not None})
    except (OSError, ValueError): pass
    # potential recruits: the rotation sum (cbb_market.py rate) on the ARK scale, fit back from the plan's own numbers
    try:
        F = J('data', 'cbb_market_fit.json'); sch = F.get('minsched') or [0.78, 0.74, 0.68, 0.6, 0.52, 0.42, 0.32, 0.22, 0.14, 0.08, 0.05, 0.03, 0.02]
        sch = [v / sum(sch) * 5 for v in sch]; fb = F['fresh']['bpm']; REP = float(re.search(r'REP_BPM = (-?[\d.]+)', open(os.path.join(HERE, 'cbb_recruit_fit.py')).read()).group(1))
        def rate(bs):
            b = sorted(bs, reverse=True)[:len(sch)]; b += [REP] * (len(sch) - len(b)); return sum(a * c for a, c in zip(sch, b))
        cur = lambda t: [x['bpm'] for x in t.get('back') or []] + [x['bpm'] for x in t.get('commits') or []] + [x['bpm'] for x in t.get('plan') or []]
        ra, rk_ = lsq([[1.0, rate(cur(t))] for t in T], [t['after'] for t in T])
        R = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))
        cls_by = {int(c['year']): c.get('list') or [] for c in R.get('classes') or []}
        nxt_y = int(D['season']); later = [y for y in sorted(cls_by) if y > nxt_y][:2]
        src = pot_sources('cbb', {y: cls_by[y] for y in [nxt_y] + later if y in cls_by})
        byT = defaultdict(lambda: {'next': [], 'later': []})
        for y, rows in src.items():
            for r in rows:
                for tid, v in r['sch'].items(): byT[tid]['next' if y == nxt_y else 'later'].append((r, v, y))
        for t in T:
            c0 = cur(t); r0 = rate(c0); gain = 0.0; pot = {}
            for k in ('next', 'later'):
                rows = []
                for r, v, y in byT.get(str(t['id']), {}).get(k, []):
                    o = pot_row(r, v, y, False)
                    if k == 'next' and o['p'] and r.get('rk'):
                        o['bpm'] = round(fb[0] + fb[1] * -math.log(r['rk']), 1)
                        o['g'] = round(o['p'] * rk_ * (rate(c0 + [o['bpm']]) - r0), 2); gain += o['g']
                    rows.append(o)
                pot[k] = top_by_year(rows)
            t['pot'] = pot; t['_pot'] = t['after'] + gain
            t['potX'] = int(round(sum((o['p'] or 0) * (o['x'] or 0) for o in pot['next']), -3))
        xw = sched(T, lambda o: o['_pot'], conf, pw, CBB_GAMES); rk = rank(T, lambda o: o['_pot'])
        for t in T: t['nx']['pot'] = {'r': round(t['_pot'], 1), 'rk': rk[id(t)], 'xw': round(xw(t, t['_pot']), 1)}
        for t in T: del t['_pot']
        potfit = dict(pot_fit(T, 'cbb'), rot=[round(ra, 2), round(rk_, 3)])
    except (OSError, ValueError, KeyError) as e: print('cbb pot', repr(e)); potfit = None
    # DECT: the draft board tab rows (scripts/cbb_tabs.py) carry dectL by name and school
    dk = {}
    def walk(o):
        if isinstance(o, dict):
            if o.get('dectL') and o.get('n'): dk[(o['n'], o.get('tm'))] = [o['dectL'], o.get('dect'), o.get('dectP')]
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    try: walk(json.load(open(os.path.join(SD, 'cbb', 'draft.json'))))
    except (OSError, ValueError): pass
    for t in T:
        for L in (t.get('back') or [], t.get('leave') or []):
            for x in L:
                v = dk.get((x['name'], t['t']))
                if v: x['dect'] = v
    try: yrs = cbb_years(D, T, conf, pw)
    except (OSError, ValueError, KeyError) as e: print('cbb years', repr(e)); yrs = None
    D['nxFit'] = {'years': yrs, 'games': CBB_GAMES, 'poss': CBB_POSS, 'sd': CBB_SD, 'replQ': REPL_Q, 'pot': potfit}
    json.dump(D, open(p, 'w'), separators=(',', ':'), allow_nan=False)
    return D['nxFit']


def pot_fit(T, sp):
    n = [o for t in T for o in (t.get('pot') or {}).get('next', [])]
    by = defaultdict(int)
    for o in n: by[o['src']] += 1
    return {'rates': RATES[1], 'min': POT_MIN, 'rows': len(n), 'recruits': len({o['name'] for o in n}), 'src': dict(by)}


def test():
    assert abs(ncdf(0) - 0.5) < 1e-9
    b = lsq([[1, 0], [1, 1], [1, 2]], [1, 3, 5]); assert abs(b[0] - 1) < 1e-9 and abs(b[1] - 2) < 1e-9
    T = [{'c': 'A', 's': 0}, {'c': 'A', 's': 0}, {'c': 'A', 's': 0}]
    xw = sched(T, lambda o: o['s'], lambda o: o['c'], lambda a, c: 0.5 if a == c else 1.0, 12)
    assert xw(T[0], 0) == 6 and xw(T[0], 1) == 12
    print('ok')


if __name__ == '__main__':
    if '--test' in sys.argv: test(); sys.exit()
    sys.path.insert(0, HERE)
    import names as _n
    CBB_ID.update({_n.team_key(t['t']): str(t['id']) for t in J('static', 'data', 'cbb-builder.json').get('teams') or []})
    try: RATES = visit_rates()
    except Exception as e:   # no On3 pack or no ESPN team list: visits read nothing, the lean model and RPM still do
        print('visit rates', repr(e)); RATES = ({(o, k): None for o in (0, 1) for k in range(1, 6)}, {})
    print('visit rates', RATES[1])
    bad = []
    for sp, fn in (('cfb', cfb), ('cbb', cbb)):   # one sport failing still writes the other
        try: print(sp, fn())
        except Exception:
            import traceback; traceback.print_exc(); bad.append(sp)
    if bad: sys.exit(f'team builder next: {", ".join(bad)} not updated')
