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

  python3 scripts/agencies.py            join and write
  python3 scripts/agencies.py --test     the shrinkage and matcher checks
"""
import json, math, os, sys
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
    'lift sports': 'LIFT Sports Management', 'lift sports management': 'LIFT Sports Management',
    'octagon': 'Octagon', 'octagon football': 'Octagon', 'octagon basketball': 'Octagon',
    'the familie': 'The Familie', 'familie': 'The Familie',
    'network': 'NETWORK', 'network sports': 'NETWORK',
    'jsg': 'Jordan Sports Group', 'jordan sports group': 'Jordan Sports Group',
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


def board(clients):
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
    rows.sort(key=lambda r: (r['agency'] in SPECIAL, -(r['zShr'] if r['zShr'] is not None else -1e12), -r['n']))
    return rows, dict(k=round(k, 1), mu=round(mu), nZ=len(allz))


def main():
    led = load('data/agencies.json', {'rows': []})['rows']
    out = {'asof': None, 'sports': {}}
    look = {}
    for sp, col, rec in (('cfb', cfb_rows(), cfb_recruits()), ('cbb', cbb_rows(), cbb_recruits())):
        clients, miss = join(led, sp, col, rec)
        rows, fit = board(clients)
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
    print('ok')


if __name__ == '__main__':
    _test() if '--test' in sys.argv else main()
