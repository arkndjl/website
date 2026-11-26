# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""On3/Rivals recruitment detail (scripts/recruit_on3_visits.mjs) joined to the ESPN classes of
scripts/recruit_commit_fit.py: for each recruit, per listed school, what was known before a cutoff date
(the On3 commitment date - H days in tests; tomorrow for live recruits).
Columns (COLS): ov official visit (0/1), luv log(1 + unofficial visits), vlast the school is his latest visit,
vrec a visit there in the 90 days before the cutoff, esh confidence-weighted share of On3 expert picks on the
school, eany he has picks and none on the school, lrpm log RPM % at the last leader snapshot (floor .5, 0 = floor),
rpm_has he has a snapshot and the school is not in it."""
import json, math, os, sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'recruit_on3')
COLS = ['ov', 'luv', 'vlast', 'vrec', 'esh', 'eany', 'lrpm', 'rpm_has']
TEAMS = {'cfb': 'football', 'cbb': 'basketball'}
CHOSE = ('Committed', 'Signed', 'Enrolled')


def slug_map(sp):
    """On3 school slug -> ESPN team id (ESPN's own team slug is the same 'georgia-bulldogs' form)"""
    f = os.path.join(CACHE, f'espn_teams_{TEAMS[sp]}.json')
    if not os.path.exists(f):
        import requests
        lg = 'football/college-football' if sp == 'cfb' else 'basketball/mens-college-basketball'
        os.makedirs(CACHE, exist_ok=True)
        open(f, 'w').write(requests.get(f'https://site.api.espn.com/apis/site/v2/sports/{lg}/teams?limit=1500', timeout=60).text)
    d = json.load(open(f))
    out = {t['team']['slug']: str(t['team']['id']) for t in d['sports'][0]['leagues'][0]['teams']}
    norm = lambda s: '-'.join(w for w in s.split('-') if w not in DROP)
    loose = defaultdict(list)
    for s, i in out.items(): loose[norm(s)].append(i)
    m = dict(out)
    for s, e in ALIAS.items():
        if e in out: m[s] = out[e]
    return _Loose(m, {k: v[0] for k, v in loose.items() if len(v) == 1}, norm)


DROP = {'state', 'university', 'fightin'}
ALIAS = {'usf-bulls': 'south-florida-bulls', 'connecticut-huskies': 'uconn-huskies', 'appalachian-state-mountaineers': 'app-state-mountaineers',
         'fiu-golden-panthers': 'florida-international-panthers', 'louisiana-monroe-warhawks': 'ul-monroe-warhawks',
         'miami-ohio-redhawks': 'miami-oh-redhawks', 'southern-university-jaguars': 'southern-jaguars'}


class _Loose(dict):
    """exact slug, then the slug without 'state' / 'university' / 'fightin' when that is unique"""
    def __init__(self, m, loose, norm): super().__init__(m); self.loose, self.norm = loose, norm
    def __contains__(self, s): return s is not None and (dict.__contains__(self, s) or self.norm(s) in self.loose)
    def __getitem__(self, s): return dict.__getitem__(self, s) if dict.__contains__(self, s) else self.loose[self.norm(s)]


HIST = os.path.join(ROOT, 'scripts', 'data', 'recruit_on3_hist.json.gz')   # finished classes
LIVEP = os.path.join(ROOT, 'scripts', 'data', 'recruit_on3_live.json.gz')  # uncommitted recruits of the live classes, daily
KEEP = ('slug', 'name', 'state', 'cdate', 'visits', 'picks', 'lead')
_HIST = {}


def pack(years, dest):
    """cached classes into a packed file kept in git (HIST: finished classes, so a refit needs no re-pull; LIVEP: the
    live pull, so the runs between daily pulls reuse it): {sport: {class: [recruit, ...]}}"""
    import gzip
    out = {}
    for sp in TEAMS:
        for y in years:
            rows = read(sp, y, pack_ok=False)
            if rows: out.setdefault(sp, {})[str(y)] = [{**{k: r.get(k) for k in KEEP}, 'cdate': commit_date(r)} for r in rows]
    with gzip.open(dest, 'wt') as fh: json.dump(out, fh, separators=(',', ':'))
    print('wrote', dest, {sp: {y: len(v) for y, v in d.items()} for sp, d in out.items()})


COMP = os.path.join(ROOT, 'scripts', 'data', 'recruit_on3_committed.json.gz')   # committed recruits' visits, live classes (the GFX cards)


def pack_committed(years):
    """the committed recruits of the live classes (recruit_on3_visits.mjs --committed): name, state and dated visits,
    for the recruit cards (scripts/player_moves.py). A class the pull did not reach keeps its last rows."""
    import gzip
    out = json.load(gzip.open(COMP, 'rt')) if os.path.exists(COMP) else {}
    for sp in TEAMS:
        for y in years:
            f = os.path.join(CACHE, f'{sp}-{y}-committed.jsonl')
            if not os.path.exists(f): continue
            rows = {}
            for l in open(f):
                if l.strip():
                    r = json.loads(l); rows[r['slug']] = {k: r.get(k) for k in ('slug', 'name', 'state', 'visits')}
            if rows: out.setdefault(sp, {})[str(y)] = [r for r in rows.values() if r.get('visits')]
    with open(COMP, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as fh:
        fh.write(json.dumps(out, separators=(',', ':'), sort_keys=True).encode())
    print('wrote', COMP, {sp: {y: len(v) for y, v in d.items()} for sp, d in out.items()})


def read(sp, y, pack_ok=True):
    f = os.path.join(CACHE, f'{sp}-{y}.jsonl')
    if not os.path.exists(f):
        if not pack_ok: return []
        if not _HIST:
            import gzip
            for p in (HIST, LIVEP):
                if os.path.exists(p):
                    for k, v in json.load(gzip.open(p, 'rt')).items(): _HIST.setdefault(k, {}).update(v)
        return _HIST.get(sp, {}).get(str(y), [])
    out = {}
    for l in open(f):
        if l.strip():
            r = json.loads(l); out[r['slug']] = r
    return list(out.values())


def commit_date(r):
    if r.get('cdate'): return r['cdate']
    for t in r.get('teams') or []:
        if t[1] in CHOSE and t[5]: return t[5]
    return None


def asof(r, cutoff, smap):
    """{espn id: [8 columns]} plus the recruit flags, from events dated before cutoff (ISO date)"""
    f = defaultdict(lambda: [0.0] * len(COLS))
    vis = sorted((v for v in r.get('visits') or [] if v[2] and v[2] < cutoff and v[0] in smap), key=lambda v: v[2])
    rec = (date.fromisoformat(cutoff) - timedelta(days=90)).isoformat()
    uv = defaultdict(int)
    for s, typ, d in vis:
        t = smap[s]
        if typ == 'Official': f[t][0] = 1.0
        else: uv[t] += 1
        if d >= rec: f[t][3] = 1.0
    for t, n in uv.items(): f[t][1] = math.log1p(n)
    if vis: f[smap[vis[-1][0]]][2] = 1.0
    pk, tot = defaultdict(float), 0.0
    for d, org, ex, conf, frm, pd, pconf in r.get('picks') or []:
        if d and d < cutoff: s, c = org, conf
        elif pd and pd < cutoff: s, c = (frm or org), pconf
        else: continue
        if not s: continue
        w = (c if c else 50) / 100; tot += w
        if s in smap: pk[smap[s]] += w
    for t, w in pk.items(): f[t][4] = w / tot
    snap = None
    for d, tt in r.get('lead') or []:
        if d and d < cutoff and (snap is None or d >= snap[0]): snap = (d, tt)
    rp = {}
    if snap:
        for s, cur, _ in snap[1]:
            if s in smap: rp[smap[s]] = math.log(max(cur or 0, .5) / .5)
    for t, v in rp.items(): f[t][6] = v
    return {'f': dict(f), 'hasP': tot > 0, 'hasR': bool(snap), 'rp': set(rp)}


def alt_feats(ex, t):
    if not ex: return [0.0] * len(COLS)
    v = list(ex['f'].get(t, [0.0] * len(COLS)))
    v[5] = float(ex['hasP'] and v[4] == 0)
    v[7] = float(ex['hasR'] and t not in ex['rp'])
    return v


def attach(sp, cls, H=30, live_years=()):
    """set x['ex'] on each ESPN recruit that has an On3 record: as of the commitment date - H (tests) or tomorrow
    (live_years, uncommitted). Returns coverage counts by class."""
    smap = slug_map(sp); cov = {}
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for y, rows in cls.items():
        on3 = read(sp, y)
        if not on3: continue
        by = defaultdict(list)
        for r in on3: by[names.key(r['name'] or '')].append(r)
        n = defaultdict(int)
        for x in rows:
            cand = [r for r in by.get(names.key(x['name'] or ''), []) if not x['st'] or not r.get('state') or r['state'] == x['st']]
            if len(cand) != 1: continue
            r = cand[0]
            if y in live_years and not x['chose']: cut = tomorrow
            else:
                cd = commit_date(r)
                if not cd: continue
                cut = (date.fromisoformat(cd) - timedelta(days=H)).isoformat()
            x['ex'] = asof(r, cut, smap); n['matched'] += 1
            if any(v[0] or v[1] for v in x['ex']['f'].values()): n['V'] += 1
            if x['ex']['hasP']: n['E'] += 1
            if x['ex']['hasR']: n['R'] += 1
        cov[y] = dict(n)
    return {'byClass': cov}


if __name__ == '__main__':
    #   python3 scripts/recruit_on3_join.py --pack 2026        finished classes (2010..2026) -> HIST
    #   python3 scripts/recruit_on3_join.py --live 2027 2028 2029   -> LIVEP
    ys = [int(a) for a in sys.argv[1:] if a.isdigit()]
    if '--pack' in sys.argv: pack(range(2010, ys[0] + 1), HIST)
    if '--live' in sys.argv: pack(ys, LIVEP)
    if '--committed' in sys.argv: pack_committed(ys)
