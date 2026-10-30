#!/usr/bin/env python3
"""Build the College Basketball ARKBOARD (data/cbb.json, static/data/cbb-all.json): every player on a 2026-27 D-I
roster, graded on the 20-80 FV scale by the model fit in scripts/cbb_fit.py (data/cbb_fit.json).

    python3 scripts/fetch_cbb.py            # refetch ESPN rosters and Barttorvik's 2026-27 rosters, rebuild
    python3 scripts/fetch_cbb.py --offline  # rebuild from the cache (scripts/.cache/cbb/)
    node scripts/cbb_on3.mjs 2026 2027      # (first) On3 industry rankings for the incoming classes

Rosters: ESPN (name, position, height, weight, class, photo). Returners are matched to their Barttorvik careers
through Barttorvik's 2026-27 rosters (which carry each returner's last line under his new team, transfers too), by
name and team; a returner Barttorvik hasn't placed is matched by name among last season's players when only one
fits. Newcomers (freshmen, international, JUCO) get their recruiting grades from On3 and 247 by name and class.
"""
import json, math, os, re, sys, time
from collections import defaultdict, Counter
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import cbb_combine as CB
import names as N
from fv_dist import fv_dist, fvd_of, cbb_z, at_mean

SEASON = 2027                     # Barttorvik's year for 2026-27
OFFLINE = '--offline' in sys.argv
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball'
CLS = {'Freshman': 'Fr', 'Sophomore': 'So', 'Junior': 'Jr', 'Senior': 'Sr', 'Graduate': 'Gr', 'Graduate Student': 'Gr', 'Redshirt Freshman': 'Fr'}
ELIG = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4, 'Gr': 5}
POS = {'G': 'G', 'PG': 'G', 'SG': 'G', 'F': 'F', 'SF': 'F', 'PF': 'F', 'C': 'C'}
LABEL = {   # driver names for the scouting report
    'lrank': 'recruiting rank', 'top': 'top-25 recruit', 'top5': 'top-5 recruit', 'rated': 'ranked recruit', 'grade': 'recruiting grade',
    'on3': 'On3 grade', 'r247': '247 grade', 'btrec': 'recruit score', 'ht': 'height', 'yr': 'class', 'bpm': 'BPM', 'bpm3': '3-season BPM',
    'obpm': 'offensive BPM', 'dbpm': 'defensive BPM', 'trend': 'BPM trend', 'min_per': 'minutes', 'usg': 'usage', 'ast': 'assist rate',
    'to': 'turnover rate', 'stl': 'steal rate', 'blk': 'block rate', 'orb': 'offensive rebounding', 'drb': 'defensive rebounding',
    'ft': 'FT%', 'tp': '3P%', 'tpa100': '3PA rate', 'ftr': 'FT rate', 'rim': 'rim finishing', 'dunk': 'dunks', 'ortg': 'ORtg',
    'porpag': 'offensive value (PORPAG)', 'dporpag': 'defensive value (D-PORPAG)', 'power': 'power conference', 'age': 'age',
    'young': 'young for class', 'bpm_x_young': 'production for age', 'ht_g': 'size for role', 'guard': 'guard', 'big': 'big',
    'nprev': 'seasons played', 'transfer': 'transfer', 'bpm_rel': 'BPM vs role', 'obpm_rel': 'offensive BPM vs role',
    'dbpm_rel': 'defensive BPM vs role', 'bpm_x_age': 'production for age', 'rg_lrk': 'recruiting rank (On3, 247, Barttorvik)',
    'unranked2': 'unranked', 'boards': 'draft boards (consensus)', 'prpg': 'PRPG!', 'dprpg': 'D-PRPG', 'age2': 'age curve', 'dunk_rel': 'dunk rate for role',
    'combine': 'combine testing'}


def local_logo(url):
    """the school logo as the site serves it (static/img/cfb/logos, ESPN team ids, shared with football) when the
    file is there: a hotlinked logo can't be drawn into a GFX that saves"""
    m = re.search(r'teamlogos/ncaa/500/(\d+)\.png', url or '')
    return f'/img/cfb/logos/{m[1]}.png' if m and os.path.exists(os.path.join(D.ROOT, 'static', 'img', 'cfb', 'logos', f'{m[1]}.png')) else url


def espn_get(url, path):
    if OFFLINE and os.path.exists(path): return json.load(open(path))
    D.fetch(url, path, 0.15)
    return json.load(open(path))


def load_espn():
    teams = espn_get(f'{ESPN}/teams?limit=500', os.path.join(D.CACHE, 'espn', 'teams.json'))['sports'][0]['leagues'][0]['teams']
    out = []
    for t in teams:
        t = t['team']
        try:
            d = espn_get(f'{ESPN}/teams/{t["id"]}/roster', os.path.join(D.CACHE, 'espn', f'r{t["id"]}.json'))
        except Exception as e:
            print('ESPN roster', t['id'], e); continue
        out.append({'id': t['id'], 'name': t['location'], 'full': t['displayName'], 'abbr': t.get('abbreviation'), 'color': t.get('color'),
                    'logo': (t.get('logos') or [{}])[0].get('href') or f'https://a.espncdn.com/i/teamlogos/ncaa/500/{t["id"]}.png',
                    'players': [{'id': a['id'], 'name': a['fullName'], 'key': D.norm(a['fullName']), 'pos': POS.get((a.get('position') or {}).get('abbreviation'), 'F'),
                                 'ht': a.get('displayHeight'), 'hti': a.get('height'), 'wt': a.get('weight'), 'cls': CLS.get((a.get('experience') or {}).get('displayValue'), 'Fr'),
                                 'photo': (a.get('headshot') or {}).get('href'), 'jersey': a.get('jersey'),
                                 'home': ', '.join(x for x in ((a.get('birthPlace') or {}).get('city'), (a.get('birthPlace') or {}).get('state') or (a.get('birthPlace') or {}).get('country')) if x)}
                                for a in d.get('athletes', [])]})
    return out


def main():
    # Barttorvik's 2026-27 file turns from last season's lines into this season's once games start: a fresh pull
    # then would grade players on a few games as if they were last season. In season the board is scripts/cbb_live.py's.
    if not OFFLINE and time.strftime('%Y-%m-%d') >= '2026-11-01' and '--force' not in sys.argv:
        sys.exit('fetch_cbb.py: the 2026-27 season has started; rebuild with --offline from the preseason cache (or --force)')
    fit = json.load(open(F.OUT))
    careers = {c['pid']: c for c in json.load(open(os.path.join(D.CACHE, 'careers.json')))}
    if not OFFLINE:
        for y in (SEASON - 1, SEASON):
            D.fetch(f'https://barttorvik.com/getadvstats.php?year={y}&csv=1', os.path.join(D.CACHE, 'bt', f'adv{y}.csv'), 1)
    bt_now = D.load_bt(SEASON)           # 2026-27 rosters, last season's lines
    espn = load_espn()
    print(f'ESPN: {len(espn)} teams, {sum(len(t["players"]) for t in espn)} players; Barttorvik 2026-27 rosters: {len(bt_now)} returners')

    # ESPN team -> Barttorvik team: the Barttorvik team whose returners share the most names with the ESPN roster
    bt_by_team = defaultdict(list)
    for r in bt_now: bt_by_team[r['team']].append(r)
    team_conf = {t: Counter(r['conf'] for r in rs).most_common(1)[0][0] for t, rs in bt_by_team.items()}
    last = D.load_bt(SEASON - 1)
    for r in last: team_conf.setdefault(r['team'], r['conf'])
    keyteam = defaultdict(set)
    for r in bt_now: keyteam[r['key']].add(r['team'])
    for t in espn:
        votes = Counter(bt for p in t['players'] for bt in keyteam.get(p['key'], ()))
        best = votes.most_common(1)
        guess = next((b for b in bt_by_team if F.D.norm(b).replace('st', 'state') == D.norm(t['name']).replace('st', 'state')), None)
        t['bt'] = best[0][0] if best and best[0][1] >= 3 else guess
        t['conf'] = team_conf.get(t['bt']) if t['bt'] else None
    print('ESPN teams without a Barttorvik match:', [t['name'] for t in espn if not t['bt']][:20])

    # On3 / 247 for newcomers, by name: incoming class first, then the class before (prep years, reclassed)
    rec = {}
    for cls in (SEASON - 2, SEASON - 1):
        # no On3 cache = every newcomer graded as unranked (the Oct 2026 board did this; scripts/cbb_prior_rec.py repaired it)
        if not D.load_on3(cls): sys.exit(f'no On3 {cls} class cached: node scripts/cbb_on3.mjs {SEASON - 2} {SEASON - 1}')
        for r in D.load_on3(cls): rec.setdefault(r['key'], {}).update({'on3': r['cons'], 'on3rk': r['consRank'], 'on3slug': r['slug'], 'on3img': r.get('img'), 'cls': cls})
        for r in D.load_247(cls): rec.setdefault(r['key'], {}).update({'r247': r['r247'], 'rk247': r['rank247']})
    # Barttorvik's 2026-27 rosters by name at the team, then last season's players by name alone (a transfer Barttorvik
    # hasn't placed), through the shared matcher (scripts/names.py): accents, suffixes, Neo / Neoklis, Cam / Cameron
    last_rows = [{'name': c['name'], 'team': c['seasons'][-1]['team'], 'c': c} for c in careers.values() if c['last'] == SEASON - 1]
    m_now = N.Matcher(bt_now, name='name', team='team', pos=None, sport='basketball')
    m_last = N.Matcher(last_rows, name='name', team='team', pos=None, sport='basketball')
    rec_rows = [dict(v, name=k) for k, v in rec.items()]
    m_rec = N.Matcher(rec_rows, name='name', team=None, pos=None, sport='basketball')

    rows = []
    for t in espn:
        for p in t['players']:
            r_bt, _ = m_now.find(p['name'], t['bt']) if t['bt'] else (None, None)
            if r_bt and not N.same_team(r_bt['team'], t['bt']): r_bt = None     # another team's returner: the name step below
            c = careers.get(r_bt['pid']) if r_bt else None
            how = 'barttorvik' if c else None
            if not c:
                hit, h = m_last.find(p['name'], t['bt'], cross_team='variant')
                # same school, or a class step that fits (a transfer Barttorvik hasn't placed: a year on, or the same
                # class after a redshirt; a senior last season isn't a sophomore now)
                was = ELIG.get(hit['c']['seasons'][-1].get('yr'), 1) if hit else 1
                if hit and (N.same_team(hit['team'], t['bt']) or 2 <= ELIG.get(p['cls'], 1) and ELIG.get(p['cls'], 1) >= was):
                    c, how = hit['c'], 'name'
            hti = p['hti'] or (c['seasons'][-1]['hti'] if c else None) or 77
            srow = {'year': SEASON, 'team': t['bt'] or t['name'], 'conf': t['conf'], 'yr': p['cls'] if p['cls'] != 'Gr' else 'Sr', 'hti': hti,
                    'rec': None, 'role': c['seasons'][-1]['role'] if c else None}
            if c:
                cc = dict(c, seasons=[s for s in c['seasons'] if s['year'] < SEASON] + [srow])
            else:
                g = rec.get(p['key'])
                if g is None:
                    hit, _ = m_rec.find(p['name'])
                    g = {k: v for k, v in hit.items() if k != 'name'} if hit else None
                cc = {'pid': None, 'name': p['name'], 'dob': None, 'rec': g, 'seasons': [srow]}
            f = F.features(cc, len(cc['seasons']) - 1)
            rows.append({'p': p, 't': t, 'c': c, 'cc': cc, 'f': f, 'how': how})
    print(f'{len(rows)} rostered players; {sum(1 for r in rows if r["c"])} returners matched to Barttorvik '
          f'({sum(1 for r in rows if r["how"] == "name")} by name only), {sum(1 for r in rows if not r["c"] and r["cc"]["rec"])} newcomers with recruiting grades')

    # score: E[FV], P(NBA), each driver's share, projected BPM
    def model(grp):
        m = fit['models'][grp]
        return m, np.array(m['mean']), np.array(m['sd']), [np.array(w) for w in m['w']]
    for r in rows:
        grp = 'newcomer' if r['f']['newcomer'] else 'returner'
        m, mu, sd, W = model(grp)
        x = np.array([r['f'].get(k) if r['f'].get(k) is not None else np.nan for k in m['kept']], float)
        z = np.clip(np.nan_to_num((x - mu) / sd), -4, 4)
        def ev(z):
            cs = [1 / (1 + math.exp(-max(-30, min(30, w[0] + w[1:] @ z)))) for w in W]
            ps = list(np.cumprod(cs))      # continuation ladder: P(30+), P(40+), P(50+), P(60+)
            return ps[0], F.FLOOR + 10 * (ps[0] + ps[1] + ps[2]) + (m['topMean'] - 50) * ps[3]
        p, e = ev(z)
        r['nbaP'], r['e'] = p, e
        parts = []
        for j, k in enumerate(m['kept']):
            z0 = z.copy(); z0[j] = 0
            parts.append((k, e - ev(z0)[1], x[j]))
        r['parts'] = parts
        xb = fit['xbpm'][grp]
        xx = np.array([r['f'].get(k) if r['f'].get(k) is not None else np.nan for k in xb['cols']], float)
        zz = np.clip(np.nan_to_num((xx - np.array(xb['mean'])) / np.array(xb['sd'])), -4, 4)
        r['xbpm'] = float(xb['w'][0] + np.array(xb['w'][1:]) @ zz)
    # the board stage: where the draft boards have him (cbb_fit.board_stage)
    for r, lr in zip(rows, F.live_consensus([(r['p']['name'], r['t']['bt'] or r['t']['name']) for r in rows])):
        e2, p2 = F.board_e(r['e'], lr, fit.get('boards'))
        if p2 is None: continue
        r['parts'].append(('boards', e2 - r['e'], lr if lr is not None else float('nan')))
        r['e'], r['nbaP'] = e2, p2
    # the combine stage (scripts/cbb_combine.py): a tester's athletic numbers on top of the boards
    for r, c in zip(rows, CB.combine_terms([(r['p']['name'], r['t']['bt'] or r['t']['name']) for r in rows], [r['p']['pos'] for r in rows])):
        if c: r['e'] += c[0]; r['parts'].append(('combine', c[0], c[1]))
    sc = np.array([r['e'] for r in rows])
    # one fixed map from E[FV] to FV (cbb_fit.emap_fit, Oct 26 2026): no longer the rank on this board
    fv, plus, fvx = F.live_grade(sc, fit)
    for r, a, b, c in zip(rows, fv, plus, fvx): r['fv'], r['plus'], r['fvx'] = int(a), bool(b), round(float(c), 2)
    for r in rows: restate(r, r['p']['cls'], not r['c'], r['p']['pos'])
    rows.sort(key=lambda r: (-r['fvx'], -r['e']))
    posrk = Counter()

    # typical age by class (Barttorvik birth dates, last season), for players without one
    ages = defaultdict(list)
    for x in last:
        a = D.age_on(x['dob'], 2026, 10, 16)
        nxt = {'Fr': 'So', 'So': 'Jr', 'Jr': 'Sr', 'Sr': 'Gr'}.get(x['yr'])   # last season's class, one year on
        if a and nxt: ages[nxt].append(a)
    age_est = {k: round(float(np.median(v)), 1) for k, v in ages.items()}
    age_est['Fr'] = round(age_est.get('So', 20.0) - 1, 1)
    today = time.gmtime()

    cols = ['name', 'team', 'logo', 'conf', 'pos', 'role', 'ovr', 'posRank', 'fv', 'plus', 'fvx', 'nbaP', 'xbpm', 'cls', 'elig', 'age', 'ageEst',
            'ht', 'wt', 'photo', 'new', 'last', 'rec', 'parts', 'report', 'links', 'fvd', 'fvg']
    out = []
    for k, r in enumerate(rows, 1):
        p, t, c, f = r['p'], r['t'], r['c'], r['f']
        posrk[p['pos']] += 1
        age = D.age_on(c['dob'], today.tm_year, today.tm_mon, today.tm_mday) if c and c['dob'] else None
        L = c['seasons'][-1] if c else None
        last_line = None
        if L:
            last_line = {'season': f"{L['year'] - 1}-{str(L['year'])[2:]}", 'team': L['team'], 'gp': int(L['gp'] or 0), 'mpg': round(L['mp'] or 0, 1),
                         'ppg': round(L['pts_g'] or 0, 1), 'rpg': round(L['treb_g'] or 0, 1), 'apg': round(L['ast_g'] or 0, 1),
                         'bpm': round(L['bpm'] or 0, 1), 'obpm': round(L['obpm'] or 0, 1), 'dbpm': round(L['dbpm'] or 0, 1),
                         'ortg': round(L['ortg'] or 0, 1), 'usg': round(L['usg'] or 0, 1), 'ts': round(L['ts'] or 0, 1),
                         'tp': round((L['tp'] or 0) * 100, 1), 'tpa': int(L['tpa'] or 0), 'ft': round((L['ft'] or 0) * 100, 1),
                         'ast': round(L['ast'] or 0, 1), 'stl': round(L['stl'] or 0, 1), 'blk': round(L['blk'] or 0, 1), 'role': L['role'],
                         'to': round(L['to'] or 0, 1), 'ftr': round(L['ftr'] or 0, 1), 'orb': round(L['orb'] or 0, 1),
                         'prpg': round((L['porpag'] or 0) * (L['min_per'] or 0) / 100, 1), 'conf': L['conf'],
                         'seasons': len([s for s in c['seasons'] if s['year'] < SEASON])}
        g = r['cc'].get('rec') or {}
        recd = {k2: g.get(k2) for k2 in ('on3', 'on3rk', 'r247', 'rk247', 'cls') if g.get(k2) is not None}
        if f.get('btrec') and not recd: recd = {'bt': f['btrec']}
        parts = [[LABEL.get(k2, k2), round(float(v), 2), None if x != x else round(float(x), 3)] for k2, v, x in r['parts']]
        rep = report(r, f, last_line)
        links = {'espn': f'https://www.espn.com/mens-college-basketball/player/_/id/{p["id"]}'}
        if L: links['bt'] = f"https://barttorvik.com/playerstat.php?year={L['year']}&p={L['name'].replace(' ', '%20')}&t={L['team'].replace(' ', '%20')}"
        if g.get('on3slug'): links['on3'] = f"https://www.on3.com/rivals/{g['on3slug']}/"
        out.append([p['name'], t['name'], local_logo(t['logo']), t['conf'], p['pos'], L['role'] if L else None, k, posrk[p['pos']], r['fv'], r['plus'], r['fvx'],
                    round(r['nbaP'], 4), round(r['xbpm'], 1), p['cls'], ELIG.get(p['cls'], 1), round(age, 1) if age else None,
                    None if age else age_est.get(p['cls']), p['ht'], int(p['wt']) if p['wt'] else None, p['photo'], 0 if c else 1,
                    last_line, recd or None, parts, rep, links, fvd_of(fv_dist('cbb', r['fvg'], cbb_z(p['cls'], not c, p['pos'], r['fvg']))), r['fvg']])
    os.makedirs(os.path.join(D.ROOT, 'static', 'data'), exist_ok=True)
    json.dump({'cols': cols, 'rows': out}, open(os.path.join(D.ROOT, 'static', 'data', 'cbb-all.json'), 'w'), separators=(',', ':'))
    # the preseason board and each player's career as graded, frozen for scripts/cbb_live.py's in-season blend
    import cbb_live
    cbb_live.write_prior(rows, cols, out)
    # historical comps for the dropdown (display only; scripts/cbb_comps.py)
    import cbb_comps
    cbb_comps.write([(r['p']['name'] + '|' + r['t']['name'], r['f']) for r in rows])
    tiers = Counter(r['fv'] for r in rows)
    summary = {'asof': time.strftime('%Y-%m-%d'), 'season': '2026-27', 'population': len(out),
               'teams': sorted({t['name'] for t in espn}), 'confs': sorted({t['conf'] for t in espn if t['conf']}),
               'tiers': {str(k): v for k, v in sorted(tiers.items(), reverse=True)},
               'top': [[o[0], o[1], o[8], o[9]] for o in out[:30]], 'fvTable': fit['fvTable'], 'backtest': fit['backtest'],
               'models': {g: {'kept': [LABEL.get(k, k) for k in m['kept']], 'r2': m['r2'],
                              'evidence': [dict(e, driver=LABEL.get(e['driver'], e['driver'])) for e in m['evidence']]} for g, m in fit['models'].items()},
               'xbpmR': {g: v['r'] for g, v in fit['xbpm'].items()}, 'train': fit['train'], 'cuts': fit['cuts'],
               'calib': calib_groups(fit.get('calibMean') or fit['calib'])}
    json.dump(summary, open(os.path.join(D.ROOT, 'data', 'cbb.json'), 'w'), indent=1)
    print('FV tiers:', dict(sorted(tiers.items(), reverse=True)))
    for o in out[:25]: print(f'{o[6]:3d} {o[0]:24s} {o[1]:18s} {o[4]} {o[13]} FV {o[8]}{"+" if o[9] else ""} NBA {o[11]:.2f} xBPM {o[12]}')


def restate(r, cls, new, pos):
    """the headline FV at the mean outcome (Oct 21 2026, as on the football board): fvx the mean of his outcome odds,
    fv its whole number, fvg the grade (the scale the cuts, the mocks and the provisional fit work on)"""
    g = r['fvx']
    m = at_mean('cbb', g, cbb_z(cls, new, pos, g))
    r['fvg'], r['fvx'], r['fv'], r['plus'] = g, round(m, 2), int(round(m)), False
    return r


def calib_groups(cal):
    """graded FV -> what those players became (out of fold, 2009-16 boards), the top tiers pooled: 16 players a tier is too few."""
    out = []
    for lo, hi in ((70, 80), (60, 65), (55, 55), (50, 50), (45, 45), (40, 40), (35, 35), (30, 30), (20, 20)):
        g = [cal[k] for k in cal if lo <= int(k) <= hi]
        n = sum(x['n'] for x in g)
        if not n: continue
        avg = lambda f: sum(x[f] * x['n'] for x in g) / n
        out.append({'lo': lo, 'hi': hi, 'n': n, 'meanFv': round(avg('meanFv'), 1), 'nba': round(avg('nba'), 3),
                    'starter': round(avg('starter'), 3), 'star': round(avg('star'), 3)})
    return out


def report(r, f, L):
    """template-built scouting lines from the drivers that move him most, with the numbers behind them."""
    net = {}
    parts = sorted(r['parts'], key=lambda t: -abs(t[1]))
    g = r['cc'].get('rec') or {}
    for k, v, x in parts[:8]:
        if abs(v) < 0.15: continue
        name = LABEL.get(k, k)
        if k in ('lrank', 'rg_lrk', 'unranked2', 'top', 'top5', 'rated', 'grade', 'on3', 'r247', 'btrec'):
            rk = g.get('on3rk') or g.get('rk247')
            line = f"recruiting pedigree: {'No. ' + str(rk) + ' in the class' if rk else 'unranked'}" + (f", On3 {g['on3']:.1f}" if g.get('on3') else '')
        elif k == 'age' or k == 'young':
            line = f"age: {f['age']:.1f} entering the season"
        elif k in ('ht', 'ht_g'):
            line = f"size: {r['p']['ht'] or '?'} for a {('guard' if f.get('guard') else 'big' if f.get('big') else 'wing') if not f['newcomer'] else r['p']['pos']}"
        elif k == 'yr':
            line = f"class: {r['p']['cls']}"
        elif L and k in ('bpm', 'bpm3', 'obpm', 'dbpm', 'trend', 'bpm_rel', 'obpm_rel', 'dbpm_rel', 'bpm_x_age', 'porpag', 'dporpag', 'ortg'):
            line = f"production: {L['bpm']:+.1f} BPM ({L['obpm']:+.1f} O, {L['dbpm']:+.1f} D) in {L['mpg']} mpg"
        elif L and k == 'usg':
            line = f"usage: {L['usg']}% of possessions"
        elif L and k == 'ast':
            line = f"passing: {L['ast']}% assist rate"
        elif L and k == 'ft':
            line = f"shooting touch: {L['ft']}% FT"
        elif L and k == 'tpa100':
            line = f"3-point volume: {L['tpa']} 3PA ({L['tp']}%)"
        elif L and k == 'stl':
            line = f"hands: {L['stl']}% steal rate"
        elif L and k == 'prpg':
            line = f"PRPG!: {L['prpg']:+.1f} points over replacement a game"
        elif L and k == 'to':
            line = f"ball security: {L['to']}% turnover rate"
        elif L and k == 'ftr':
            line = f"gets to the line: {L['ftr']} FT rate"
        elif L and k == 'orb':
            line = f"offensive glass: {L['orb']}% OREB rate"
        elif L and k == 'power':
            line = f"level: {L['conf']}, {'a power' if f.get('power') else 'a non-power'} conference"
        elif L and k == 'nprev':
            line = f"experience: {L['seasons']} D-I season{'s' if L['seasons'] != 1 else ''}"
        elif k == 'boards':
            line = f"draft boards: consensus No. {round(math.exp(-x))}" if x == x else 'draft boards: on none of the 2027 boards'
        elif k == 'combine':
            line = f"combine: athletic testing {x:+.1f} SD for a guard"
        elif k == 'transfer':
            line = 'new school this season'
        elif k in ('big', 'guard'):
            line = f"role family: {'big' if f.get('big') else 'guard' if f.get('guard') else 'wing'}"
        elif L and k == 'min_per':
            line = f"role: {L['mpg']} minutes a game"
        else:
            line = f"{name}: {x:.2f}" if x == x else name
        net[line] = net.get(line, 0.0) + v
    # several drivers can read the same line (3-season BPM up, offensive BPM vs role down): it goes where they net out
    return {'plus': [k for k, v in net.items() if v > 0][:4], 'minus': [k for k, v in net.items() if v < 0][:4]}


if __name__ == '__main__':
    main()
