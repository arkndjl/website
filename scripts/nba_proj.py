"""NBA XPM (proj) and contract surplus for the NBA ARKBOARD (static/data/nba-proj.json, data/nba_proj_fit.json).

XPM (proj): each player's XPM to date blended with his preseason prior (nba_xpm.prior_xpm: his two seasons before,
aged, shrunk toward a newcomer), weighted by minutes,

    proj = prior + (XPM to date - prior) x MP / (k + MP),   80% interval proj +/- 1.28 x tau x sqrt(k / (k + MP))

tau^2 (spread of true talent around the prior) and sigma^2 (noise per minute; k = sigma^2 / tau^2) are fit on every
player-season 2012-26 from season-end XPM against the prior: E[(XPM - prior)^2] = tau^2 + sigma^2 / MP, separately for
veterans (500+ MP in the two seasons before) and newcomers. Held out one season at a time, the 80% interval for a
season's XPM covers 80% (see --fit). Display only: the same posterior failed as a game model input (Oct 23,
scripts/nba_inseason.py), where team ratings and the line already carry it.

Contract surplus: projected VORX x $ per win minus salary (Basketball-Reference contracts, y1 = this season).
  season VORX = VORX to date + rest of season at XPM (proj) x his minutes per game x his share of games played
  $ per win   = league payroll above the minimum / league projected VORX (the market's going rate this season)
  later years = XPM (proj) aged on the game model's aging curve (nba_games.aging_curve), same minutes and games share,
                $ per win grown CAP_G a year with the cap. A player option is a year he takes only when it pays him more
                than he is worth (team surplus min(0, value - salary)); a team option one the team takes only when he
                is worth more (max(0, value - salary)).

  python3 scripts/nba_proj.py --fit     # refit tau / sigma (data/nba_proj_fit.json) with the held-out coverage check
  python3 scripts/nba_proj.py           # this season's projections and surplus (refetches the contracts page)
Stdlib only."""
import datetime as dt, html, json, math, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_xpm as X

ROOT = X.ROOT
FIT = os.path.join(ROOT, 'data', 'nba_proj_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'nba-proj.json')
CONTRACTS = os.path.join(X.CACHE, 'contracts.html')
Z80 = 1.2816
VET_MP = 500                       # minutes over the two seasons before that make a veteran
G0 = 15                            # games of last season's minutes per game the current pace is blended with
CAP_G = 0.07                       # yearly growth of $ per win in later contract years (the cap's recent growth)


def load(s):
    fn = os.path.join(X.OUT, f'{s}.json')
    return json.load(open(fn)) if os.path.exists(fn) else None


def past_mp(season):
    m = {}
    for k in (1, 2):
        d = load(season - k)
        for p in (d['players'] if d else []):
            m[p['id']] = m.get(p['id'], 0) + p['mp']
    return m


def lsq(rows):
    """(tau2, sig2) from e^2 = tau2 + sig2 / mp, least squares"""
    n = len(rows); a = sum(1 / m for m, _ in rows); b = sum(1 / m ** 2 for m, _ in rows)
    y = sum(e * e for _, e in rows); yz = sum(e * e / m for m, e in rows)
    det = n * b - a * a
    return (y * b - a * yz) / det, (n * yz - a * y) / det


def fit(lo=2012, hi=2026):
    rows = {'vet': {}, 'new': {}}
    for s in range(lo, hi + 1):
        d = load(s)
        if not d: continue
        prior, old = X.prior_xpm(s), past_mp(s)
        for p in d['players']:
            if p.get('pr') or p['mp'] < 50 or p.get('xpm') is None: continue
            g = 'vet' if old.get(p['id'], 0) >= VET_MP else 'new'
            rows[g].setdefault(s, []).append((p['mp'], p['xpm'] - prior(p['id'])[0]))
    out = {'seasons': [lo, hi], 'z80': Z80}
    for g, by in rows.items():
        allr = [r for v in by.values() for r in v]
        t2, s2 = lsq(allr)
        cov = {}
        for s, te in by.items():                            # leave one season out: refit, cover the held-out season
            a, b = lsq([r for k, v in by.items() if k != s for r in v])
            cov[s] = sum(abs(e) < Z80 * math.sqrt(a + b / m) for m, e in te) / len(te)
        c = sorted(cov.values())
        out[g] = {'n': len(allr), 'tau2': round(t2, 3), 'sig2': round(s2, 1), 'k': round(s2 / t2),
                  'cover80': round(sum(c) / len(c), 3), 'coverMin': round(c[0], 3), 'coverMax': round(c[-1], 3)}
        print(g, out[g])
    json.dump(out, open(FIT, 'w'), indent=1)


def contracts(fresh=True):
    if fresh or not os.path.exists(CONTRACTS):
        req = urllib.request.Request('https://www.basketball-reference.com/contracts/players.html', headers={'User-Agent': X.UA})
        for attempt in range(4):
            try:
                open(CONTRACTS, 'w', encoding='utf-8').write(urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace'))
                break
            except Exception as e:
                print('contracts', e, flush=True); time.sleep(20 * (attempt + 1))
    h = open(CONTRACTS, encoding='utf-8').read()
    tb = re.search(r'<table[^>]*id="player-contracts"[^>]*>(.*?)</table>', h, re.S)
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb.group(1) if tb else h, re.S):
        pid = re.search(r'data-append-csv="(\w+)"', tr)
        if not pid or pid.group(1) in out: continue
        yrs = []
        for i in range(1, 7):
            c = re.search(r'<td class="right ([a-z-]*)\s*" data-stat="y%d"[^>]*?(?:csk="(\d+)")?\s*>' % i, tr)
            if not c or not c.group(2): break
            yrs.append((int(c.group(2)), {'salary-pl': 'P', 'salary-tm': 'T'}.get(c.group(1), '')))
        tm = re.search(r'data-stat="team_id"[^>]*>(?:<a[^>]*>)?([A-Z]{3})', tr)
        if yrs: out[pid.group(1)] = {'tm': tm and tm.group(1), 'yrs': yrs}
    return out


def project(fresh=True):
    f = json.load(open(FIT))
    idx = json.load(open(X.INDEX)); season = idx['current']
    cur, last = load(season), load(season - 1)
    prior, old = X.prior_xpm(season), past_mp(season)
    lastp = {p['id']: p for p in (last['players'] if last else [])}
    gp = cur['games'] if cur else 0                         # team games played so far (the most by any player)
    left = max(0, 82 - gp)
    curp = {p['id']: p for p in (cur['players'] if cur else [])}
    con = contracts(fresh)
    lastn = {}
    if last:
        for p in last['players']: lastn[p['id']] = p
    ids = set(curp) | {i for i in con if i in lastp}
    aging = __import__('nba_games').aging_curve(season)
    rows = []
    for pid in ids:
        c, l = curp.get(pid), lastp.get(pid)
        g = 'vet' if old.get(pid, 0) >= VET_MP else 'new'
        t2, k = f[g]['tau2'], f[g]['k']
        q = prior(pid)
        mp = c['mp'] if c and not c.get('pr') else 0
        x = c['xpm'] if mp else None
        w = mp / (k + mp)
        pv = [q[i] + ((c[key] - q[i]) * w if mp else 0) for i, key in enumerate(('xpm', 'oxpm', 'dxpm'))]
        sd = math.sqrt(t2 * k / (k + mp))
        # minutes: this season's pace blended with last season's over G0 games; games: his share of last season's
        lmpg = l['mp'] / l['g'] if l and l['g'] else None
        cg = c['g'] if c else 0
        mpg = ((lmpg * G0 + mp) / (G0 + cg)) if lmpg is not None else (mp / cg if cg else None)
        if mpg is None: continue
        share = ((l['g'] if l else 0) + 0.8 * 20) / ((last['games'] if l else 0) + 20)
        share = min(1.0, share)
        vorx0 = c['vorx'] if mp else 0.0
        vrest = X.VORX_K * (pv[0] - X.VORX_REP) * mpg * share * left / 48
        r = {'id': pid, 'n': (c or l)['n'], 'tm': (con.get(pid) or {}).get('tm') or (c or l)['tm'], 'pos': (c or l)['pos'],
             'age': (c['age'] if c else (l['age'] or 0) + 1 if l else None), 'mp': mp, 'xpm': x,
             'prior': round(q[0], 1), 'pxpm': round(pv[0], 1), 'poxpm': round(pv[1], 1), 'pdxpm': round(pv[2], 1),
             'lo': round(pv[0] - Z80 * sd, 1), 'hi': round(pv[0] + Z80 * sd, 1), 'w': round(w, 2),
             'pmp': round(mp + mpg * share * left), 'pvorx': round(vorx0 + vrest, 2),
             'mpg82': mpg * share * 82}
        if pid in con: r['sal'] = con[pid]['yrs']
        rows.append(r)
    # the market's $ per win this season: payroll above the minimum over the projected wins it buys
    paid = [r for r in rows if r.get('sal')]
    sal1 = sorted(r['sal'][0][0] for r in paid)
    mn = max(set(sal1), key=sal1.count)                     # the most common salary is the league minimum
    dpw = sum(max(0, s - mn) for s in sal1) / sum(r['pvorx'] for r in paid)
    for r in rows:
        mpg82 = r.pop('mpg82')
        if not r.get('sal'): continue
        yrs, tot, by = r.pop('sal'), 0.0, []
        for j, (s, opt) in enumerate(yrs):
            if j == 0: v = r['pvorx']
            else:
                xj = r['pxpm'] + (sum(aging(r['age'] + i) for i in range(1, j + 1)) if aging and r['age'] else 0)
                v = X.VORX_K * (xj - X.VORX_REP) * mpg82 / 48
            val = v * dpw * (1 + CAP_G) ** j
            sp = val - s
            if j and opt == 'P': sp = min(0.0, sp)       # this season's options are already decided
            elif j and opt == 'T': sp = max(0.0, sp)
            by.append([round(s / 1e6, 2), round(val / 1e6, 2), opt if j else '']); tot += sp
        r['sal'] = by[0][0]; r['val'] = by[0][1]; r['sur'] = round(by[0][1] - by[0][0], 2)
        r['yrs'] = by; r['csur'] = round(tot / 1e6, 1)
    try:            # headshots: the XPM board's ESPN ids (scripts/faces.py) for this season
        ph = {p['id']: p['ph'] for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{season}.json')))['players'] if p.get('ph')}
        for r in rows:
            if r['id'] in ph: r['ph'] = ph[r['id']]
    except Exception as e:
        print('faces skipped', e)
    rows.sort(key=lambda r: -r['pxpm'])
    out = {'season': season, 'label': f'{season - 1}-{str(season)[2:]}',
           'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'games': gp,
           'dpw': round(dpw / 1e6, 2), 'min': round(mn / 1e6, 2), 'capG': CAP_G,
           'k': {g: f[g]['k'] for g in ('vet', 'new')}, 'players': rows}
    old = json.load(open(OUT)) if os.path.exists(OUT) else None
    if old and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in out.items() if k != 'asof'}:
        print('unchanged'); return
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print(f"{season}: {len(rows)} players, {len(paid)} with contracts, $/win {dpw / 1e6:.2f}M, min {mn / 1e6:.2f}M")


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
    else: project(fresh='--cached' not in sys.argv)
