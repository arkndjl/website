#!/usr/bin/env python3
"""NIL agencies for college football and basketball players and high school recruits.

data/agencies.json is the ledger: one row a player, the agency (or "Family" when a relative handles his deals, or "None"
when a source says he has no agent), the source URL, its date and a confidence (high / medium / low). Nothing in it is
guessed: a player no source names stays out. This script joins the ledger to the boards and writes

  data/agencies_board.json     the Agencies tabs (layouts/shortcodes/agencies.html): one row an agency per sport, and the
                               client rows
  static/data/agencies.json    the player and recruit cards (assets/js/gfx.js): name key -> [team key, agency, confidence]

zNIL = xNIL - yNIL, as on the NIL boards. Above zero the client is worth more on the market than he is paid; below zero
he is paid more than he is worth. An agency's mean zNIL is shrunk toward the mean of every represented college player,
by n / (n + k) with k = within-agency variance / between-agency variance (method of moments), so an agency with two
clients does not top the board on one outlier.

Drafted clients are tracked from the 2027 drafts on, never backfilled (Noah, Nov 28 2026): once a year's NFL draft (for
football) or NBA draft (basketball) is complete on ESPN, every college player in the ledger who was picked is written to
data/agency_pros.json with the agency the ledger gave him that day, and the year is marked done. The board counts them
per agency (Drafted, 1st rd, Pro% = drafted / (drafted + college clients now)).

  python3 scripts/agencies.py            record a finished draft, join and write
  python3 scripts/agencies.py --test     the shrinkage and matcher checks
  python3 scripts/agencies.py --draft nfl 2026 --dry    match a past draft against the ledger without writing it
"""
import datetime as dt, json, math, os, re, sys, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names  # noqa: E402

P = lambda *a: os.path.join(ROOT, *a)

# one spelling per agency (sources write the same shop several ways)
ALIAS = {
    'athletes first nil': 'Athletes First', 'athletes first': 'Athletes First',
    'caa': 'CAA Sports', 'caa sports': 'CAA Sports', 'creative artists agency': 'CAA Sports', 'caa football': 'CAA Sports', 'caa basketball': 'CAA Sports',
    'wme': 'WME Sports', 'wme sports': 'WME Sports', 'wme basketball': 'WME Sports',
    'excel': 'Excel Sports Management', 'excel sports': 'Excel Sports Management', 'excel sports management': 'Excel Sports Management',
    'klutch': 'Klutch Sports Group', 'klutch sports': 'Klutch Sports Group', 'klutch sports group': 'Klutch Sports Group',
    'wasserman': 'Wasserman', 'wasserman media group': 'Wasserman',
    'roc nation': 'Roc Nation Sports', 'roc nation sports': 'Roc Nation Sports', 'roc nation sports international': 'Roc Nation Sports',
    'young money apaa': 'Young Money APAA Sports', 'young money apaa sports': 'Young Money APAA Sports', 'ymapaa': 'Young Money APAA Sports',
    'vaynersports': 'VaynerSports', 'vayner sports': 'VaynerSports',
    'everett sports marketing': 'Everett Sports Marketing', 'esm': 'Everett Sports Marketing',
    'rosenhaus sports representation': 'Rosenhaus Sports', 'valiant management': 'Valiant Management Group',
    'lift sports': 'LIFT Sports Management', 'lift sports management': 'LIFT Sports Management',
    'octagon': 'Octagon', 'octagon football': 'Octagon', 'octagon basketball': 'Octagon',
    'the familie': 'The Familie', 'familie': 'The Familie',
    'network': 'NETWORK', 'network sports': 'NETWORK',
    'jsg': 'Jordan Sports Group', 'jordan sports group': 'Jordan Sports Group',
    'the biz of athlete': 'The Business of Athletes', 'the business of athletes': 'The Business of Athletes', 'biz of athletes': 'The Business of Athletes',
    'priority sports': 'Priority Sports', 'priority sports & entertainment': 'Priority Sports', 'esm sports': 'Everett Sports Marketing',
    'family': 'Family', 'none': 'None', 'self': 'None', 'unrepresented': 'None',
}
SPECIAL = ('Family', 'None')


def canon(a):
    if a is None: return None
    s = ' '.join(str(a).replace('’', "'").split())
    return ALIAS.get(s.lower().rstrip('.'), s)


def load(p, default=None):
    try: return json.load(open(P(p)))
    except FileNotFoundError: return default


# ---- the boards -----------------------------------------------------------------------------------------------------

def cfb_rows():
    a = load('static/data/cfb-all.json'); I = {k: i for i, k in enumerate(a['cols'])}
    hs = (load('data/arkstars_hs.json', {}).get('cfb') or {}).get('by', {})
    out = []
    for r in a['rows']:
        g = lambda k: r[I[k]]
        out.append(dict(name=g('name'), team=g('team'), pos=g('pos'), cls=g('cls'), logo=g('logo'), fv=g('fv'),
                        x=g('xnil'), y=g('ynil'), z=g('znil'), ark=hs.get('%s|%s' % (g('name'), g('team'))), kind='college'))
    return out


def cfb_recruits():
    rc = load('static/data/cfb-recruits.json'); out = []
    lists = [(rc['next'], rc['class'])] + [(f['year'], f['list']) for f in rc.get('future', [])]
    for yr, l in lists:
        for r in l:
            out.append(dict(name=r['name'], team=r.get('team'), pos=r.get('pos'), cls=yr, logo=r.get('logo'), fv=r.get('xfv'),
                            x=r.get('xnil'), y=None, z=None, ark=r.get('ark'), kind='recruit'))
    return out


def cbb_rows():
    a = load('static/data/cbb-all.json'); I = {k: i for i, k in enumerate(a['cols'])}
    m = {(r['name'], r['team']): r for r in load('data/cbb_market.json')['nil']}
    hs = (load('data/arkstars_hs.json', {}).get('cbb') or {}).get('by', {})
    out = []
    for r in a['rows']:
        g = lambda k: r[I[k]]
        n = m.get((g('name'), g('team'))) or {}
        out.append(dict(name=g('name'), team=g('team'), pos=g('pos'), cls=g('cls'), logo=g('logo'), fv=g('fv'),
                        x=n.get('x'), y=n.get('y'), z=n.get('z'), ark=hs.get('%s|%s' % (g('name'), g('team'))), kind='college'))
    return out


def cbb_recruits():
    d = load('data/cbb_recruits.json'); out = []
    for c in d['classes']:
        for r in c['list']:
            out.append(dict(name=r['name'], team=r.get('team'), pos=r.get('pos'), cls=c['year'], logo=r.get('logo'), fv=r.get('fv'),
                            x=r.get('xnil'), y=None, z=None, ark=r.get('ark'), kind='recruit'))
    return out


# ---- shrinkage ------------------------------------------------------------------------------------------------------

def shrink_k(groups, floor=1.0, cap=40.0):
    """k = within-group variance / between-group variance of the true means (method of moments). groups: lists of values."""
    gs = [g for g in groups if len(g) >= 2]
    if len(gs) < 3: return 8.0
    if sum(1 for g in groups if len(g) >= 3) < 8: floor = max(floor, 8.0)   # too few agencies with 3+ clients to trust the between spread
    allv = [v for g in groups for v in g]; mu = sum(allv) / len(allv)
    within = sum(sum((v - sum(g) / len(g)) ** 2 for v in g) for g in gs) / max(1, sum(len(g) - 1 for g in gs))
    means = [(sum(g) / len(g), len(g)) for g in gs]
    between = sum((m - mu) ** 2 for m, _ in means) / (len(means) - 1) - within * sum(1 / n for _, n in means) / len(means)
    if between <= 0: return cap
    return max(floor, min(cap, within / between))


# ---- the join -------------------------------------------------------------------------------------------------------

def join(ledger, sport, college, recruits):
    mc = names.Matcher(college, sport='football' if sport == 'cfb' else 'basketball')
    mr = names.Matcher(recruits, sport='football' if sport == 'cfb' else 'basketball')
    out, miss = [], []
    for e in ledger:
        if e.get('sport') != sport or not e.get('agency'): continue
        row, how = (None, None)
        if e.get('cls'):
            row, how = mr.find(e['player'], team=e.get('school'), pos=e.get('pos'))
        if row is None:
            row, how = mc.find(e['player'], team=e.get('school'), pos=e.get('pos'))
        if row is None and not e.get('cls'):
            row, how = mr.find(e['player'], team=e.get('school'), pos=e.get('pos'))
        if row is None: miss.append(e); continue
        out.append(dict(row, agency=canon(e['agency']), agent=e.get('agent'), conf=e.get('confidence') or 'medium',
                        src=e.get('source'), date=e.get('source_date'), how=how, scope=e.get('scope')))
    # one row a player: the highest confidence, then the newest source
    best = {}
    rank = {'high': 3, 'medium': 2, 'low': 1}
    for r in out:
        k = (r['name'], r['team'], r['kind'])
        o = best.get(k)
        if o is None or (rank.get(r['conf'], 0), r.get('date') or '') > (rank.get(o['conf'], 0), o.get('date') or ''): best[k] = r
    return list(best.values()), miss


# ---- drafted clients (tracked forward from the 2027 drafts) ------------------------------------------------------------

LEAGUE = {'cfb': ('nfl', 'football/leagues/nfl', (4, 20)), 'cbb': ('nba', 'basketball/leagues/nba', (6, 15))}
FIRST = 2027              # the first draft tracked; earlier drafts are not backfilled
ESPN = 'http://sports.core.api.espn.com/v2/sports/%s/seasons/%d/draft'


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            err = e
    print('espn:', url, err); return None


def draft_picks(sp, year):
    """Every pick of a finished draft as {round, pick, name, team (college)}; None while any pick is still to be made."""
    d = _get(ESPN % (LEAGUE[sp][1], year) + '/rounds?limit=20')
    if not d or not d.get('items'): return None
    picks, colleges = [], {}
    for rd in d['items']:
        for k in rd.get('picks', []):
            if (k.get('status') or {}).get('name') != 'SELECTION_MADE' or 'athlete' not in k: return None
            a = _get(k['athlete']['$ref']) or {}
            team = None
            ref = (a.get('college') or {}).get('$ref')
            if ref:
                if ref not in colleges: colleges[ref] = (_get(ref) or {}).get('name')
                team = colleges[ref]
            picks.append(dict(round=k['round'], pick=k['overall'], name=a.get('fullName') or a.get('displayName'), team=team))
    return picks


def cutoff(sp, year):
    """the start of the draft process: an agency signed after it (the pro agent) did not send the player"""
    return '%d-12-01' % (year - 1) if sp == 'cfb' else '%d-03-15' % year


def match_drafts(ledger, sp, picks, year=None):
    """Ledger college players (no recruit class) found among the picks, with the agency the ledger gave them before the
    draft process (a ledger row dated after the cutoff is the pro agent and does not count)."""
    m = names.Matcher(picks, pos=None, sport='football' if sp == 'cfb' else 'basketball')
    rank = {'high': 3, 'medium': 2, 'low': 1}
    best = {}
    for e in ledger:
        if e.get('sport') != sp or not e.get('agency') or e.get('cls'): continue
        if year and (e.get('source_date') or '9999') > cutoff(sp, year): continue
        k = names.key(e['player'])
        o = best.get(k)
        if o is None or (rank.get(e.get('confidence'), 0), e.get('source_date') or '') > (rank.get(o.get('confidence'), 0), o.get('source_date') or ''):
            best[k] = e
    out = []
    for e in best.values():
        row, how = m.find(e['player'], team=e.get('school'), cross_team='none')   # same name at another school is not him
        if row is None: continue
        out.append(dict(player=e['player'], school=e.get('school'), pos=e.get('pos'), agency=canon(e['agency']),
                        conf=e.get('confidence') or 'medium', round=row['round'], pick=row['pick'], src=e.get('source')))
    return sorted(out, key=lambda r: r['pick'])


def record_drafts(ledger, today=None):
    """Write each newly finished draft's ledger clients to data/agency_pros.json (once a year a league)."""
    today = today or dt.date.today()
    pros = load('data/agency_pros.json', None) or {'done': {}, 'rows': []}
    changed = False
    for sp, (lg, _, (mo, dy)) in LEAGUE.items():
        y = today.year
        if y < FIRST or today < dt.date(y, mo, dy) or y in pros['done'].get(lg, []): continue
        picks = draft_picks(sp, y)
        if picks is None: continue
        got = match_drafts(ledger, sp, picks, y)
        pros['rows'] += [dict(r, sport=sp, league=lg, year=y) for r in got]
        pros['done'].setdefault(lg, []).append(y); changed = True
        print('%s %d draft: %d of %d picks were ledger clients' % (lg, y, len(got), len(picks)))
    if changed or not os.path.exists(P('data/agency_pros.json')):
        json.dump(pros, open(P('data/agency_pros.json'), 'w'), indent=1)
    return pros['rows']


# ---- tendency scores (Noah, Nov 28: "+" scores in place of the x/y/zNIL columns, 100 = the average agency) -----------

TEND_TEST = 'research/agency_tendency.json'     # scripts/research/agencies_nov28/tendency.py, rerun by hand


def tendencies(pool):
    """per-client values for the tendency scores, each against every board player like him.
    Deal: -zNIL over the sport's zNIL SD (1st-99th percentile clamp), so above zero = paid more than he is worth.
    Breakout: FV - the mean FV of board players with his ARK stars (half stars) and class."""
    zs = sorted(r['z'] for r in pool if r.get('z') is not None)
    if not zs: return {}
    m = sum(zs) / len(zs); sd = (sum((v - m) ** 2 for v in zs) / len(zs)) ** .5 or 1.0
    lo, hi = zs[int(.01 * len(zs))], zs[int(.99 * len(zs)) - 1]
    cell = defaultdict(list)
    for r in pool:
        if r.get('ark') and r.get('fv') is not None: cell[(round(r['ark'] * 2), r.get('cls'))].append(r['fv'])
    allv = [v for l in cell.values() for v in l]; mu = sum(allv) / len(allv) if allv else 0.0
    base = lambda r: (sum(cell[(round(r['ark'] * 2), r.get('cls'))]) / len(cell[(round(r['ark'] * 2), r.get('cls'))])
                      if len(cell.get((round(r['ark'] * 2), r.get('cls')), [])) >= 15 else mu)
    return {
        'Deal': lambda c: None if c['kind'] != 'college' or c.get('z') is None or c.get('conf') == 'low' else -max(lo, min(hi, c['z'])) / sd,
        'Breakout': lambda c: None if c['kind'] != 'college' or not c.get('ark') or c.get('fv') is None else c['fv'] - base(c),
    }


def shipped(sp):
    """the scores that passed the split-half test for this sport (p < .05 weighted and unweighted)"""
    t = (load(TEND_TEST, {}) or {}).get(sp, {})
    return [k for k in ('Deal', 'Breakout') if (t.get(k) or {}).get('ship')]


def plus_scores(rows, by, sp, pool):
    """Deal+ / Breakout+: the agency's mean client value shrunk toward the mean of every represented client by n / (n + k),
    then 100 + 25 x (score - mean agency score) / SD of agency scores, over the agencies (not Family or None)."""
    fs = tendencies(pool); fit = {}
    for name in shipped(sp):
        f = fs.get(name)
        if f is None: continue
        vals = {a: [v for v in (f(c) for c in l) if v is not None] for a, l in by.items()}
        allv = [v for a, l in vals.items() if a not in SPECIAL for v in l]
        if not allv: continue
        mu = sum(allv) / len(allv); k = shrink_k([l for a, l in vals.items() if a not in SPECIAL])
        shr = {a: (sum(l) + k * mu) / (len(l) + k) for a, l in vals.items() if l}
        ag = [v for a, v in shr.items() if a not in SPECIAL]
        m = sum(ag) / len(ag); sd = (sum((v - m) ** 2 for v in ag) / len(ag)) ** .5 or 1.0
        key = name[0].lower() + name[1:] + 'P'
        for r in rows:
            v = shr.get(r['agency']); r[key] = round(100 + 25 * (v - m) / sd) if v is not None else None
        fit[key] = dict(k=round(k, 1), n=len(allv))
    return fit


def components(clients, pros, sp, pool):
    """per agency: the shipped tendency scores as the shrunk edge e = sum(v - mu) / ((n + k) x sd), times the clients when e is
    above zero, so the same edge counts for more the more players it covers and a below-average edge is not multiplied;
    sent = picks the agency had before the draft process; vol = log(1 + clients). score = the mean of the z-scored parts the
    sport uses (shipped tendencies + sent; COMPOSITE)."""
    fs = tendencies(pool); by = defaultdict(list)
    for c in clients: by[c['agency']].append(c)
    out = defaultdict(dict)
    for name in ('Deal', 'Breakout'):
        f = fs.get(name)
        if not f: continue
        vals = {a: [v for v in (f(c) for c in l) if v is not None] for a, l in by.items()}
        allv = [v for a, l in vals.items() if a not in SPECIAL for v in l]
        if len(allv) < 3: continue
        mu = sum(allv) / len(allv); sd = (sum((v - mu) ** 2 for v in allv) / len(allv)) ** .5 or 1.0
        k = shrink_k([l for a, l in vals.items() if a not in SPECIAL])
        for a, l in vals.items():
            # clients x the shrunk edge = n x sum(v - mu) / (n + k), in SDs: one client counts for 1 / (1 + k) of himself,
            # a big roster for close to all of its total
            # an edge above the mean counts once per client (volume); one below it counts once, as the shrunk mean, so a big
            # roster is not charged per player for the depth players every big roster carries (Noah, Nov 28)
            e = sum(v - mu for v in l) / ((len(l) + k) * sd) if l else 0.0
            out[a][name.lower()] = e * len(l) if e > 0 else e
    for p in pros: out[canon(p['agency'])]['sent'] = out[canon(p['agency'])].get('sent', 0) + 1
    for a, l in by.items(): out[a]['vol'] = math.log1p(len(l))
    use = [k.lower() for k in shipped(sp)] + ['sent']
    ag = [a for a in out if a not in SPECIAL]
    z = {}
    for k in use:
        v = [out[a].get(k, 0.0) for a in ag]; m = sum(v) / len(v) if v else 0; s = (sum((x - m) ** 2 for x in v) / len(v)) ** .5 if v else 0
        z[k] = (m, s or 1.0)
    for a in out:
        out[a]['score'] = sum((out[a].get(k, 0.0) - z[k][0]) / z[k][1] for k in use) / len(use) if use else 0.0
    return out


def board(clients, pros=(), sp='cfb', pool=()):
    by = defaultdict(list)
    for c in clients: by[c['agency']].append(c)
    zs = {a: [c['z'] for c in l if c['kind'] == 'college' and c['z'] is not None and c['conf'] != 'low'] for a, l in by.items() if a not in SPECIAL}
    allz = [v for l in zs.values() for v in l]
    mu = sum(allz) / len(allz) if allz else 0.0
    k = shrink_k(list(zs.values()))
    rows = []
    for a, l in by.items():
        col = [c for c in l if c['kind'] == 'college']; rec = [c for c in l if c['kind'] == 'recruit']
        z = [c['z'] for c in col if c['z'] is not None and c['conf'] != 'low']
        n = len(z); s = sum(z); mean = s / n if n else None
        shr = (s + k * mu) / (n + k) if n else None
        fv = [c['fv'] for c in l if c['fv'] is not None]
        ark = [c['ark'] for c in l if c['ark'] is not None]
        xs = [c['x'] for c in col if c['x'] is not None]; ys = [c['y'] for c in col if c['y'] is not None]
        top = sorted(l, key=lambda c: -(c['fv'] or 0))[:3]
        rows.append(dict(agency=a, n=len(l), nCol=len(col), nRec=len(rec), nZ=n,
                         z=round(s) if n else None, zMean=round(mean) if n else None, zShr=round(shr) if n else None,
                         zPct=round(s / sum(ys), 3) if n and ys and sum(ys) else None,
                         x=round(sum(xs)) if xs else None, y=round(sum(ys)) if ys else None,
                         recX=round(sum(c['x'] for c in rec if c['x'] is not None)) or None,
                         fv=round(sum(fv), 1) if fv else None, fvTop=max(fv) if fv else None,
                         ark=round(sum(ark) / len(ark), 2) if ark else None, ark5=sum(1 for v in ark if v and v > 5),
                         high=round(sum(1 for c in l if c['conf'] == 'high') / len(l), 2),
                         top=[[c['name'], c['pos'], c['fv'], c['logo']] for c in top],
                         logos=sorted({c['logo'] for c in l if c['logo']})[:12]))
    # drafted clients: an agency whose clients have all gone pro still gets a row
    dr = defaultdict(list)
    for r in pros:
        if r.get('conf') != 'low': dr[canon(r['agency'])].append(r)   # low confidence: kept in the file, not counted
    have = {r['agency'] for r in rows}
    for a in dr:
        if a not in have:
            rows.append(dict(agency=a, n=0, nCol=0, nRec=0, nZ=0, z=None, zMean=None, zShr=None, zPct=None, x=None, y=None, recX=None,
                             fv=None, fvTop=None, ark=None, ark5=0, high=0, top=[], logos=[]))
    for r in rows:
        d = dr.get(r['agency'], [])
        r['pro'] = len(d); r['pro1'] = sum(1 for p in d if p['round'] == 1)
        r['proPct'] = round(len(d) / (len(d) + r['nCol']), 3) if d and r['nCol'] else None   # no college clients on file: no share
    pf = plus_scores(rows, by, sp, pool)
    # Agency+: the composite (components), 100 + 25 x score / SD over the agencies
    cp = components(clients, [p for p in pros if p.get('conf') != 'low'], sp, pool)
    ag = [cp[r['agency']]['score'] for r in rows if r['agency'] not in SPECIAL and r['agency'] in cp]
    m = sum(ag) / len(ag) if ag else 0.0; sd = (sum((v - m) ** 2 for v in ag) / len(ag)) ** .5 if ag else 1.0
    for r in rows:
        c = cp.get(r['agency'])
        r['agencyP'] = round(100 + 25 * (c['score'] - m) / (sd or 1.0)) if c else None
    pf['agencyP'] = dict(parts=[k.lower() for k in shipped(sp)] + ['sent'])
    lead = 'agencyP'
    rows.sort(key=lambda r: (r['agency'] in SPECIAL, -(r[lead] if lead and r.get(lead) is not None else -1e12), -(r['fv'] or 0), -r['n']))
    return rows, dict(k=round(k, 1), mu=round(mu), nZ=len(allz), plus=pf, lead=lead)


def main():
    led = load('data/agencies.json', {'rows': []})['rows']
    pros = record_drafts(led)
    out = {'asof': None, 'sports': {}}
    look = {}
    for sp, col, rec in (('cfb', cfb_rows(), cfb_recruits()), ('cbb', cbb_rows(), cbb_recruits())):
        clients, miss = join(led, sp, col, rec)
        rows, fit = board(clients, [p for p in pros if p['sport'] == sp], sp, col)
        clients.sort(key=lambda c: (c['agency'] in SPECIAL, c['agency'], -(c['fv'] or 0)))
        out['sports'][sp] = dict(fit=fit, agencies=rows,
                                 clients=[{k: c[k] for k in ('name', 'team', 'logo', 'pos', 'cls', 'kind', 'fv', 'x', 'y', 'z', 'ark', 'agency', 'agent', 'conf', 'src', 'date')} for c in clients],
                                 unmatched=[{k: e.get(k) for k in ('player', 'school', 'cls', 'agency', 'source')} for e in miss])
        L = look.setdefault(sp, {})
        for c in clients:
            L.setdefault(names.key(c['name']), []).append([names.team_key(c['team'] or ''), c['agency'], c['conf'], c['kind']])
        print('%s: %d ledger rows matched, %d unmatched, %d agencies, k = %.1f' % (sp, len(clients), len(miss), len(rows), fit['k']))
    dates = [r.get('source_date') for r in led if r.get('source_date')]
    out['asof'] = max(dates) if dates else None
    json.dump(out, open(P('data/agencies_board.json'), 'w'), separators=(',', ':'))
    json.dump(look, open(P('static/data/agencies.json'), 'w'), separators=(',', ':'))


def _test():
    k = shrink_k([[1, 1.1, 0.9], [5, 5.2, 4.8], [-3, -3.1, -2.9], [0, 0.1, -0.1]])
    assert k <= 8.0, k               # tight groups far apart: little shrinkage (the floor while few agencies have 3+ clients)
    k2 = shrink_k([[1, -1, 2, -2], [0.5, -0.5, 1, -1], [2, -2, 0, 0]])
    assert k2 >= 20, k2               # same means, noisy: heavy shrinkage
    assert canon('Athletes First NIL') == 'Athletes First' and canon('family') == 'Family' and canon(' Klutch  Sports ') == 'Klutch Sports Group'
    picks = [dict(round=1, pick=3, name='Jeremiyah Love', team='Notre Dame'), dict(round=2, pick=40, name='John Smith', team='Ohio State')]
    led = [dict(player='Jeremiyah Love', school='Notre Dame', sport='cfb', agency='CAA', confidence='high'),
           dict(player='John Smith', school='Alabama', sport='cfb', agency='WME', confidence='high'),
           dict(player='Jeremiyah Love', school='Notre Dame', sport='cfb', agency='CAA', confidence='high', cls=2026)]
    got = match_drafts(led, 'cfb', picks)
    assert [(g['player'], g['agency'], g['round']) for g in got] == [('Jeremiyah Love', 'CAA Sports', 1)], got   # same name, other school: not him
    late = [dict(player='Jeremiyah Love', school='Notre Dame', sport='cfb', agency='CAA', confidence='high', source_date='2026-01-10')]
    assert match_drafts(late, 'cfb', picks, 2026) == []          # signed after Dec 1: the pro agent, not counted
    rows, _ = board([], [dict(agency='CAA', round=1)])
    assert rows[0]['agency'] == 'CAA Sports' and rows[0]['pro'] == 1 and rows[0]['pro1'] == 1 and rows[0]['proPct'] is None   # no college clients on file
    print('ok')


def _dry(lg, y):
    sp = {'nfl': 'cfb', 'nba': 'cbb'}[lg]
    picks = draft_picks(sp, y)
    print(len(picks or []), 'picks;', sum(1 for p in picks or [] if p['team']), 'with a college')
    for r in match_drafts(load('data/agencies.json', {'rows': []})['rows'], sp, picks or []): print(r)


if __name__ == '__main__':
    if '--test' in sys.argv: _test()
    elif '--draft' in sys.argv: i = sys.argv.index('--draft'); _dry(sys.argv[i + 1], int(sys.argv[i + 2]))
    else: main()
