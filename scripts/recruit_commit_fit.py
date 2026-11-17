# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Where a high school recruit commits: a destination-choice model (conditional logit) for CFB and CBB, with
hometown-to-campus distance terms tested walk-forward by class.

Data: ESPN recruiting classes (scripts/recruit_commit_pull.py; cache scripts/.cache/recruit_commit).
Two choice sets: LIST (the schools in ESPN's recruitment list, 3+ located) and OPEN (every program with a signee
in the prior 3 classes). School terms come only from earlier classes. Pre-registration:
/mnt/project-files/recruits/commit-distance/prereg.md
  python3 scripts/recruit_commit_fit.py            walk-forward tests, then the live fit and leans
  python3 scripts/recruit_commit_fit.py --live     live fit and leans only, with the terms in data/recruit_commit_fit.json
  python3 scripts/recruit_commit_fit.py --refit [cfb|cbb]   the stored tests kept, the live models fit again, then the leans

CFB LIST model, Nov 16 2026 (tests: scripts/research/recruits_cfb_nov16/commit_tests.py, each on top of the kept terms,
walk-forward 2018-26, Holm): the school's conversion rate (signed / listed, prior three classes), its on-field
strength (final Elo z of the last season and the change from the one before), and recency weights on the training
classes (.75 a class). Failed there: top-tier / nearest school in his list, high-school pipeline.

Nov 17 2026 (scripts/research/recruit_visits_nov17/, as of the On3 commitment date - 30 days): CFB adds On3/Rivals
visits (official, unofficial count, latest, last 90 days) and the expert picks' confidence-weighted share
(scripts/recruit_on3_join.py). Failed: RPM % on top of those (CFB), every On3 term in CBB.
"""
import csv, json, math, os, sys, time
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'recruit_commit')
OUT = os.path.join(ROOT, 'data', 'recruit_commit_fit.json')
LEANS = os.path.join(ROOT, 'data', 'recruit_commit_leans.json')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cfb_transfer_fit import geocode, miles  # noqa: E402
import recruit_on3_join as ON3  # noqa: E402

CHOSE = ('Signed', 'Enrolled', 'Committed', 'Verbal')
YEARS = {'cfb': (2012, 2029), 'cbb': (2010, 2029)}
HELD = {'cfb': range(2018, 2027), 'cbb': range(2015, 2027)}
LIVE = (2027, 2028, 2029)
BASE = ['pull', 'tier', 'gxt', 'gap']
DIST = ['ld', 'inst', 'pipe', 'ld_tier', 'ld_g']
MORE = ['conv', 'elo', 'delo']
ON3_H = 30   # On3 visits / expert picks / RPM as of the commitment date - 30 days in training; live: everything to date
EXTRA = {'cfb': {'list': ['conv', 'elo', 'delo', 'ov', 'luv', 'vlast', 'vrec', 'esh', 'eany']}}   # added to the kept terms of that sport's model
DECAY = {'cfb': {'list': 0.75}}                      # weight of a training class, per class back from the newest
SCHED = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'ros')
LAM = 1.0
NALT = 40
RNG = np.random.default_rng(7)


def load(sp):
    teams = json.load(open(os.path.join(ROOT, 'scripts', 'geo', 'recruit_campus.json')))[sp]
    loc = {}
    for t, v in teams.items():
        g = v and v.get('city') and geocode(v['city'], v['state'])
        if g: loc[t] = (g[0], g[1], v['state'], v['name'])
    cls = {}
    for y in range(YEARS[sp][0], YEARS[sp][1] + 1):
        p = os.path.join(CACHE, f'{sp}-{y}.json')
        if not os.path.exists(p): continue
        rows = []
        for r in json.load(open(p)):
            home = geocode(r['city'], r['state']) or geocode(r.get('hsCity'), r.get('hsState'))
            if not home: continue
            ch = sorted((s for s in r['schools'] if s[1] in CHOSE), key=lambda s: CHOSE.index(s[1]))
            st = r['state'] or r.get('hsState')
            rows.append({'rid': r['rid'], 'name': r['name'], 'pos': r['pos'], 'grade': r['grade'] or 0, 'home': home, 'st': st,
                         'chose': ch[0][0] if ch else None, 'list': list(dict.fromkeys(s[0] for s in r['schools'] if s[0] in loc))})
        g = np.array([x['grade'] for x in rows if x['grade'] > 0]); mu, sd = (g.mean(), g.std()) if len(g) else (0, 1)
        lo = np.percentile(g, 5) if len(g) else 0
        for x in rows: x['g'] = ((x['grade'] if x['grade'] > 0 else lo) - mu) / sd
        cls[y] = rows
    ON3.attach(sp, cls, ON3_H, live_years=LIVE)
    return loc, cls


_ELO = {}


def elo_z(season):
    """CFB: each program's final Elo of a season as a z among FBS programs (cfbfastR schedules, as
    scripts/cfb_recruit_retarget.py programs_hist; FCS 0). {} when the file can't be read: the terms then stay neutral."""
    if season in _ELO: return _ELO[season]
    f = os.path.join(SCHED, f's{season}.csv'); out = {}
    stale = os.path.exists(f) and season >= time.gmtime().tm_year - 1 and time.time() - os.path.getmtime(f) > 72000   # a season still being played
    if not os.path.exists(f) or not os.path.getsize(f) or stale:
        os.makedirs(SCHED, exist_ok=True)
        os.system(f'curl -sSLf -m 120 -o {f}.tmp "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/csv/cfb_schedules_{season}.csv" && mv {f}.tmp {f}')
    if os.path.exists(f) and os.path.getsize(f):
        last, div = {}, {}
        for r in sorted(csv.DictReader(open(f)), key=lambda r: (int(r['week'] or 0), r['season_type'] == 'postseason')):
            for sd in ('home', 'away'):
                t = r[sd + '_id']; div[t] = r[sd + '_division']
                if r[sd + '_postgame_elo'] not in ('', 'NA'): last[t] = float(r[sd + '_postgame_elo'])
        fbs = [last[t] for t in last if div.get(t) == 'fbs']
        if len(fbs) > 50:
            m, sd_ = float(np.mean(fbs)), float(np.std(fbs))
            out = {t: ((last.get(t, m) - m) / sd_ if d == 'fbs' else 0.0) for t, d in div.items() if d in ('fbs', 'fcs')}
    _ELO[season] = out
    return out


def school_stats(cls, y, loc, sp=None):
    """from classes y-3..y-1: signee count, tier (shrunk mean grade z), signees by home state, times listed by a
    recruit; CFB: the program's Elo z of season y-1 and of season y-2"""
    n, s, bys, listed = defaultdict(int), defaultdict(float), defaultdict(int), defaultdict(int)
    for k in (y - 3, y - 2, y - 1):
        for x in cls.get(k, []):
            for t in x['list']: listed[t] += 1
            if x['chose'] in loc: n[x['chose']] += 1; s[x['chose']] += x['g']; bys[(x['chose'], x['st'])] += 1
    allm = sum(s.values()) / max(1, sum(n.values()))
    tier = {t: (s[t] + 5 * allm) / (n[t] + 5) for t in n}
    e1, e0 = (elo_z(y - 1), elo_z(y - 2)) if sp == 'cfb' else ({}, {})
    return n, tier, bys, listed, e1, e0


def feats(x, alts, st, loc):
    n, tier, bys, listed, e1, e0 = st
    F = []
    for t in alts:
        lat, lon, sst, _ = loc[t]
        ld = math.log1p(miles(x['home'], (lat, lon)) / 100); tr = tier.get(t, -1.0)
        F.append([math.log1p(n.get(t, 0)), tr, x['g'] * tr, abs(x['g'] - tr), ld, float(sst == x['st']),
                  math.log1p(bys.get((t, x['st']), 0)), ld * tr, ld * x['g'],
                  math.log((n.get(t, 0) + 1) / (listed.get(t, 0) + 5)), e1.get(t, 0.0), e1.get(t, 0.0) - e0.get(t, e1.get(t, 0.0))]
                 + ON3.alt_feats(x.get('ex'), t))
    return np.array(F)


COLS = BASE + DIST + MORE + ON3.COLS


def build(sp, loc, cls, years, mode, sample):
    X, grp, yv, meta = [], [], [], []
    for y in years:
        st = school_stats(cls, y, loc, sp); active = [t for t in st[0] if t in loc]
        for x in cls.get(y, []):
            c = x['chose']
            if mode == 'list':
                alts = x['list']
                if c is None or c not in alts or len(alts) < 3: continue
            else:
                if c is None or c not in st[0]: continue
                alts = active
                if sample:
                    others = [t for t in active if t != c]
                    alts = [c] + list(RNG.choice(others, size=min(NALT, len(others)), replace=False))
            X.append(feats(x, alts, st, loc)); yv.append(alts.index(c)); meta.append((y, x['rid'])); grp.append(len(alts))
    return X, np.array(yv), meta


def fit(X, yv, cols, lam=LAM, w=None):
    """ridge conditional logit; w: a weight on each recruit (mean 1)"""
    idx = [COLS.index(c) for c in cols]; w = np.ones(len(X)) if w is None else np.asarray(w, float) / np.mean(w)
    A = np.vstack([x[:, idx] for x in X]); mu, sd = A.mean(0), A.std(0) + 1e-9
    off = np.cumsum([0] + [len(x) for x in X]); Z = (A - mu) / sd; ch = off[:-1] + yv
    n = np.diff(off); b = np.zeros(len(idx)); wr = np.repeat(w, n)
    def obj(b):
        u = Z @ b; m = np.maximum.reduceat(u, off[:-1]); e = np.exp(u - np.repeat(m, n)); s = np.add.reduceat(e, off[:-1])
        return -(w * (u[ch] - m - np.log(s))).sum() + lam * b @ b, e / np.repeat(s, n)
    f0, p = obj(b)
    for _ in range(100):   # damped Newton on the ridge conditional logit (convex)
        zb = np.add.reduceat(p[:, None] * Z, off[:-1])
        gr = (w[:, None] * Z[ch]).sum(0) - (w[:, None] * zb).sum(0) - 2 * lam * b
        H = ((wr * p)[:, None] * Z).T @ Z - (w[:, None] * zb).T @ zb + 2 * lam * np.eye(len(b))
        step, a = np.linalg.solve(H, gr), 1.0
        while a > 1e-6:
            f1, p1 = obj(b + a * step)
            if f1 <= f0 + 1e-10: break
            a /= 2
        b, f0, p = b + a * step, f1, p1
        if np.abs(a * step).max() < 1e-8: break
    return {'cols': cols, 'b': (b / sd).tolist(), 'mu': mu.tolist(), 'sd': sd.tolist(), 'b_std': b.tolist()}


def probs(m, F):
    idx = [COLS.index(c) for c in m['cols']]
    u = F[:, idx] @ np.array(m['b']); u = u - u.max(); e = np.exp(u); return e / e.sum()


def score(m, X, yv):
    ll, br, t1, t3 = [], [], [], []
    for F, c in zip(X, yv):
        p = probs(m, F); ll.append(math.log(max(p[c], 1e-12))); o = np.zeros(len(p)); o[c] = 1
        br.append(((p - o) ** 2).sum()); r = (p > p[c]).sum(); t1.append(r == 0); t3.append(r < 3)
    return np.array(ll), np.array(br), np.array(t1), np.array(t3)


def walk(sp, loc, cls, mode, cols_list):
    """per held class: fit each model on all earlier classes, score the class"""
    res = {k: defaultdict(list) for k in range(len(cols_list))}
    start = YEARS[sp][0] + 3
    for y in HELD[sp]:
        Xt, yt, _ = build(sp, loc, cls, range(start, y), mode, True)
        Xh, yh, mh = build(sp, loc, cls, [y], mode, False)
        for k, cols in enumerate(cols_list):
            m = fit(Xt, yt, cols); ll, br, t1, t3 = score(m, Xh, yh)
            for key, v in (('ll', ll), ('br', br), ('t1', t1), ('t3', t3)): res[k][key].append(v)
            res[k]['yr'].append(np.full(len(ll), y))
        print(sp, mode, y, len(yh), [round(float(np.mean(res[k]['ll'][-1])), 4) for k in res], flush=True)
    return {k: {kk: np.concatenate(v) for kk, v in d.items()} for k, d in res.items()}


def gate(a, b):
    """b vs a: mean LL gain per recruit, paired t, share of held classes positive, NIL-era gain + t"""
    d = b['ll'] - a['ll']; t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    yrs = sorted(set(a['yr'])); pos = sum(d[a['yr'] == y].mean() > 0 for y in yrs) / len(yrs)
    nil = d[a['yr'] >= 2022]; tn = nil.mean() / (nil.std(ddof=1) / math.sqrt(len(nil)))
    return {'gain': float(d.mean()), 't': float(t), 'classesPos': round(float(pos), 3), 'nilGain': float(nil.mean()), 'nilT': float(tn),
            'pass': bool(d.mean() > 0 and t >= 2 and pos >= 2 / 3), 'byClass': {int(y): round(float(d[a['yr'] == y].mean()), 4) for y in yrs}}


def summ(r):
    return {'ll': float(r['ll'].mean()), 'brier': float(r['br'].mean()), 'top1': float(r['t1'].mean()), 'top3': float(r['t3'].mean()), 'n': int(len(r['ll']))}


def forward(sp, loc, cls, mode):
    """pre-registered order: base, then D1..D5 forward; also pull-only"""
    kept, log = list(BASE), []
    r0 = walk(sp, loc, cls, mode, [['pull'], kept])
    pull, cur = r0[0], r0[1]
    out = {'pullOnly': summ(pull), 'base': summ(cur), 'baseVsPull': gate(pull, cur)}
    for term in DIST:
        r = walk(sp, loc, cls, mode, [kept + [term]])[0]
        g = gate(cur, r); g['term'] = term; g['with'] = summ(r); log.append(g)
        print(sp, mode, term, g, flush=True)
        if g['pass']: kept.append(term); cur = r
    out['tests'] = log; out['kept'] = kept; out['final'] = summ(cur)
    out['finalVsBase'] = gate(walk(sp, loc, cls, mode, [list(BASE)])[0], cur) if kept != BASE else None
    out['finalVsPull'] = gate(pull, cur)
    return out


def distance_table(loc, cls, years):
    bins = [0, 50, 100, 250, 500, 1000, 1e9]; c = np.zeros(len(bins) - 1)
    for y in years:
        for x in cls.get(y, []):
            if x['chose'] in loc:
                mi = miles(x['home'], loc[x['chose']][:2]); c[np.searchsorted(bins, mi, side='right') - 1] += 1
    return {f'{bins[i]}-{bins[i + 1] if bins[i + 1] < 1e9 else "+"}': round(float(c[i] / c.sum()), 3) for i in range(len(c))}


def live(sp, loc, cls, spec, refit=True):
    """fit on every finished class (or reuse the stored fit), lean for each uncommitted 2027-29 recruit"""
    out, models = [], {}
    last = max(HELD[sp])
    for mode in ('list', 'open'):
        if not refit and spec.get('models', {}).get(mode): models[mode] = spec['models'][mode]; continue
        cols = spec[mode]['kept'] + [c for c in EXTRA.get(sp, {}).get(mode, []) if c not in spec[mode]['kept']]
        yrs = range(2022 if spec[mode].get('nilOnly') else YEARS[sp][0] + 3, last + 1)
        X, yv, meta = build(sp, loc, cls, yrs, mode, True); dec = DECAY.get(sp, {}).get(mode)
        models[mode] = fit(X, yv, cols, w=[dec ** (last - y) for y, _ in meta] if dec else None)
    for y in LIVE:
        st = school_stats(cls, min(y, last + 1), loc, sp); active = [t for t in st[0] if t in loc]
        for x in cls.get(y, []):
            if x['chose']: continue
            mode = 'list' if len(x['list']) >= 3 else 'open'
            alts = x['list'] if mode == 'list' else active
            if not alts: continue
            p = probs(models[mode], feats(x, alts, st, loc)); o = np.argsort(-p)[:3]
            out.append({'year': y, 'name': x['name'], 'st': x['st'], 'set': mode,
                        'lean': [[alts[i], loc[alts[i]][3], round(float(p[i]), 3)] for i in o]})
    return models, out


def site_keys(sp, leans):
    """match each lean to the recruit's row on the site (data/cfb_recruits.json future lists, data/cbb_recruits.json
    classes) with the shared name rules plus home state; the page reads leans by year and the row's own name"""
    import names
    f = os.path.join(ROOT, 'data', f'{sp}_recruits.json')
    if not os.path.exists(f): return {}
    d = json.load(open(f))
    groups = d.get('future', []) if sp == 'cfb' else d.get('classes', [])
    by = defaultdict(list)
    leans = [x for x in leans if x['set'] == 'list']   # shown: the list model only (calibrated held out; the open field reads overconfident)
    for x in leans: by[(x['year'], names.key(x['name']))].append(x)
    out = defaultdict(dict)
    for g in groups:
        for r in g.get('list', []):
            if r.get('team') or r.get('school') or r.get('status') not in (None, 'uncommitted'): continue
            st = (r.get('home') or '').split(', ')[-1]
            cand = [x for x in by.get((g['year'], names.key(r['name'])), []) if not st or not x['st'] or x['st'] == st]
            if not cand:   # spelling the key misses: same-class strength test
                cand = [x for x in leans if x['year'] == g['year'] and (not st or x['st'] == st) and names.same(x['name'], r['name'])]
            if len(cand) == 1:
                t, nm, pr = cand[0]['lean'][0]
                out[str(g['year'])][r['name']] = [nm, round(pr * 100), t]
    return out


def main():
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    refit = '--refit' in sys.argv
    which = [a for a in sys.argv[sys.argv.index('--refit') + 1:] if a in YEARS] if refit else []   # --refit cfb: that sport only
    only_live = '--live' in sys.argv or refit
    res = prev if only_live else {}
    if only_live:   # the live classes change daily; the school terms read the last three finished classes
        from recruit_commit_pull import pull, teams
        for sp in ('cfb', 'cbb'):
            for y in range(min(LIVE) - 3, max(LIVE) + 1): pull(sp, y, force=y in LIVE)
        teams()
    leans = {}
    for sp in ('cfb', 'cbb'):
        loc, cls = load(sp)
        if not only_live:
            res[sp] = {'distance': distance_table(loc, cls, HELD[sp])}
            for mode in ('list', 'open'):
                res[sp][mode] = forward(sp, loc, cls, mode)
                if prev.get(sp, {}).get(mode, {}).get('more'): res[sp][mode]['more'] = prev[sp][mode]['more']   # the added terms' own tests
            for mode in ('list', 'open'):
                k = res[sp][mode]; nil = [g for g in k['tests'] if g['term'] in k['kept'] and g['nilGain'] < 0 and g['nilT'] <= -1]
                k['nilOnly'] = bool(nil)
        models, lv = live(sp, loc, cls, res[sp], refit=(refit and (not which or sp in which)) or not only_live)
        res[sp]['models'] = models
        leans[sp] = site_keys(sp, lv)
        if refit or not only_live: json.dump(res, open(OUT, 'w'), indent=1)
    json.dump(leans, open(LEANS, 'w'), separators=(',', ':'))
    print('wrote', LEANS, {sp: {y: len(v) for y, v in d.items()} for sp, d in leans.items()})


if __name__ == '__main__':
    main()
