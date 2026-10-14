#!/usr/bin/env python3
"""Draft% backtest (draftOdds in scripts/cfb_teams.mjs): DRAFT_SD, DRAFT_CUT and DECLARE.

    python3 scripts/cfb_draft_pct_backtest.py   # pulls into scripts/.cache/draftpct/, writes data/cfb_draft_pct_backtest.json

Data: PFF's college big board API keeps dated versions of each draft's board (season=<draft year>&version=<n>):
every version for the 2020-26 drafts, September through April, with PFF's rank and class. nflverse draft picks are
the outcome; DraftTek's final 600-deep boards plus the picks mark who declared. Names match on last name and first
name prefix (Olu / Olumuyiwa, Greg / Gregory). A player picked in an earlier draft is dropped.

What it measures (xPick = the board-rank-to-pick curve, BOARD_PICK in cfb_teams.mjs):
  1. selection: P(drafted | declared) = Phi((ln cut - ln xPick) / sd) by how far out the board was: each
     draft's latest board in the window, pooled, (cut, sd) by maximum likelihood
  2. declaring: P(declared) on the fall boards (Sep-Nov), a logistic in ln xPick for each class group (PFF
     "Sr./RS Sr./G" vs underclassmen; on the board, eligibility class 4+ vs 1-3), on the NIL-era drafts
     (2024-25) and on all five; the chain test fits grads on their own curve, as the history had them
  3. the whole chain, leave one draft out, against the old settings (sd .70 at all dates, cutoff solved near
     pick 254, seniors all declaring, underclassmen half at pick 150): log loss, Brier, calibration
Every class label on these boards is the player's year in school, not his eligibility (Cade Klubnik and Drew
Allar were "Sr." in 2024 as third- and fourth-years), and both groups are measured on the same labels the board
uses, so the class split is what the data supports and nothing finer.
"""
import collections, csv, datetime, glob, hashlib, html, json, math, os, re, subprocess, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'draftpct')
OUT = os.path.join(ROOT, 'data', 'cfb_draft_pct_backtest.json')
os.makedirs(CACHE, exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
DRAFTS = range(2020, 2027)
DRAFT_DAY = {2020: '2020-04-23', 2021: '2021-04-29', 2022: '2022-04-28', 2023: '2023-04-27', 2024: '2024-04-25', 2025: '2025-04-24', 2026: '2026-04-23'}
SR = {'Sr.', 'RS Sr.', 'G'}   # 4th-years and up; 'Sr.' alone is the board's plain Sr (eligibility class 4, no redshirt flag)


def fetch(url, name):
    f = os.path.join(CACHE, name)
    if not os.path.exists(f):
        subprocess.run(['curl', '-sSL', '-m', '60', '-A', UA, '-o', f, url])
        time.sleep(0.2)
    return f


def pff_boards():
    out = []
    for y in DRAFTS:
        for v in range(1, 16):
            try: d = json.load(open(fetch(f'https://www.pff.com/api/college/big_board?season={y}&version={v}', f'pff_{y}_{v}.json')))
            except ValueError: continue
            if d.get('players') and d.get('last_updated_at'): out.append((y, v, d['last_updated_at'][:10], d['players']))
    return out


def drafttek():
    rows = []
    for y in DRAFTS:
        for p in range(1, 7):
            f = fetch(f'https://www.drafttek.com/{y}-NFL-Draft-Big-Board/Top-NFL-Draft-Prospects-{y}-Page-{p}.asp', f'dt_{y}_{p}.html')
            s = re.sub(r'<!--.*?-->', '', open(f, encoding='latin1').read(), flags=re.S)
            for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
                tds = [html.unescape(re.sub('<[^>]+>', '', t)).strip() for t in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
                if len(tds) >= 8 and tds[0].isdigit(): rows.append((y, int(tds[0]), tds[2]))
    return {(y, r): n for y, r, n in rows}


def parts(n):
    n = re.sub(r"[.'’]", '', n.lower()); n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    w = [re.sub(r'[^a-z-]', '', x) for x in n.split()]; w = [x for x in w if x]
    return (w[0] if w else ''), ''.join(w[1:]).replace('-', '')


ALIAS = {'greg': 'gregory', 'pat': 'patrick', 'sam': 'samuel', 'dax': 'daxton', 'olumuyiwa': 'olu', 'mike': 'michael', 'matt': 'matthew', 'chris': 'christopher', 'nick': 'nicholas', 'tony': 'anthony'}
def fmatch(a, b):
    a, b = a.replace('-', ''), b.replace('-', '')
    return a == b or a.startswith(b) or b.startswith(a) or ALIAS.get(a) == b or ALIAS.get(b) == a or (min(len(a), len(b)) >= 3 and a[:3] == b[:3])


lnPick = lambda r: (lambda l: 0.723 + 0.753 * l + 0.0252 * l * l)(math.log(max(1, r)))   # BOARD_PICK
Phi = np.vectorize(lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2))))
clip = lambda p: np.clip(p, 1e-6, 1 - 1e-6)
ll = lambda p, y: float(np.sum(y * np.log(clip(p)) + (1 - y) * np.log(clip(1 - p))))


def fit_sel(lx, y):
    best = max((ll(Phi((c - lx) / s), y), c, s) for c in np.arange(4.8, 7.5, 0.02) for s in np.arange(0.3, 2.2, 0.02))
    return best[1], best[2]


def fit_decl(lx, y):
    best = max((ll(1 / (1 + np.exp(s * (lx - m))), y), m, s) for m in np.arange(3.0, 10.0, 0.02) for s in np.arange(0.0, 3.0, 0.02))
    return best[1], best[2]


def main():
    picks = collections.defaultdict(list)
    for r in csv.DictReader(open(fetch('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv', 'draft_picks.csv'))):
        if int(r['season']) >= 2018:
            f, l = parts(r['pfr_player_name']); picks[l].append((int(r['season']), int(r['pick']), f))
    dt = drafttek(); dtnames = collections.defaultdict(list)
    for (y, _), n in dt.items(): f, l = parts(n); dtnames[(y, l)].append(f)
    boards = pff_boards()
    rows = []
    for y, v, date, players in boards:
        days = (datetime.date.fromisoformat(DRAFT_DAY[y]) - datetime.date.fromisoformat(date)).days
        for p in players:
            if not p.get('pff_rank'): continue
            f, l = parts(p['name']); c = [x for x in picks.get(l, []) if fmatch(f, x[2])]
            if any(x[0] < y for x in c): continue
            same = [x for x in c if x[0] == y]
            rows.append({'draft': y, 'ver': v, 'date': date, 'days': days, 'rank': p['pff_rank'], 'name': p['name'], 'pos': p['position'],
                         'sr': (p.get('class') or '') in SR, 'cls': p.get('class') or '', 'drafted': int(bool(same)),
                         'declared': int(bool(same) or any(fmatch(f, F) for F in dtnames.get((y, l), [])))})
    print('board rows', len(rows), 'boards', len(boards))
    out = {'_readme': __doc__.split('\n\n')[2].strip(), 'boards': [{'draft': y, 'version': v, 'date': d, 'n': len(p)} for y, v, d, p in boards]}

    # 1. selection by window (the latest board per draft in each window, declared players)
    W = {'fall': (140, 240), 'winter': (50, 139), 'final': (0, 30)}
    sel = {}
    for w, (a, b) in W.items():
        latest = {}
        for r in rows:
            if a <= r['days'] <= b and (r['draft'] not in latest or r['days'] < latest[r['draft']]): latest[r['draft']] = r['days']
        s = [r for r in rows if latest.get(r['draft']) == r['days'] and r['declared']]
        lx = np.array([lnPick(r['rank']) for r in s]); y = np.array([r['drafted'] for r in s])
        c, sd = fit_sel(lx, y)
        sel[w] = {'days': [a, b], 'drafts': sorted(latest), 'n': len(s), 'drafted': round(float(y.mean()), 3), 'cut': round(math.exp(c)), 'sd': round(sd, 2),
                  'logLoss': round(-ll(Phi((c - lx) / sd), y) / len(s), 4), 'logLossOld': round(-ll(Phi((math.log(254) - lx) / 0.7), y) / len(s), 4)}
        print('selection', w, sel[w])
    out['selection'] = sel

    # the fall boards: each draft's latest Sep-Nov board
    latest = {}
    for r in rows:
        if 140 <= r['days'] <= 240 and (r['draft'] not in latest or r['days'] < latest[r['draft']]): latest[r['draft']] = r['days']
    fall = [r for r in rows if latest.get(r['draft']) == r['days']]
    bands = [(1, 32), (33, 64), (65, 100), (101, 150), (151, 250)]
    out['fallBands'] = [{'ranks': f'{a}-{b}', **{g: {'n': len(s), 'declared': round(sum(r['declared'] for r in s) / len(s), 3), 'drafted': round(sum(r['drafted'] for r in s) / len(s), 3)}
                         for g, s in (('seniors', [r for r in fall if a <= r['rank'] <= b and r['sr']]), ('underclass', [r for r in fall if a <= r['rank'] <= b and not r['sr']]),
                                      ('all', [r for r in fall if a <= r['rank'] <= b])) if s}} for a, b in bands]

    # 2. declaring, by class group
    dec = {}
    # seniors: PFF "Sr." (the board's plain Sr); 5th-years and grads ("RS Sr.", "G") were mostly coming back on the
    # COVID year, gone by 2026, so the board sends its RS-Sr and Gr players out (reported here, not used)
    for g, keep in (('seniors', lambda r: r['cls'] == 'Sr.'), ('grads', lambda r: r['cls'] in ('RS Sr.', 'G')), ('underclass', lambda r: not r['sr'])):
        for era, ds in (('nil', (2024, 2025)), ('all', tuple(latest))):
            s = [r for r in fall if keep(r) and r['draft'] in ds]
            lx = np.array([lnPick(r['rank']) for r in s]); y = np.array([r['declared'] for r in s])
            m, k = fit_decl(lx, y)
            old = np.ones(len(s)) if g != 'underclass' else 1 / (1 + np.exp(1.2 * (lx - math.log(150))))
            dec[f'{g}_{era}'] = {'n': len(s), 'declared': round(float(y.mean()), 3), 'mid': round(math.exp(m)), 'slope': round(k, 2),
                                 'logLoss': round(-ll(1 / (1 + np.exp(k * (lx - m))), y) / len(s), 4), 'logLossOld': round(-ll(old, y) / len(s), 4)}
            print('declare', g, era, dec[f'{g}_{era}'])
    out['declare'] = dec

    # 3. the whole chain on the fall boards, leave one draft out
    pred_new, pred_old, ys, keys = [], [], [], []
    for d in sorted(latest):
        tr = [r for r in fall if r['draft'] != d]; te = [r for r in fall if r['draft'] == d]
        trd = [r for r in tr if r['declared']]
        c, sd = fit_sel(np.array([lnPick(r['rank']) for r in trd]), np.array([r['drafted'] for r in trd]))
        grp = lambda r: 'sr' if r['cls'] == 'Sr.' else 'grad' if r['sr'] else 'under'
        dm = {}
        for g in ('sr', 'grad', 'under'):
            s = [r for r in tr if grp(r) == g]; dm[g] = fit_decl(np.array([lnPick(r['rank']) for r in s]), np.array([r['declared'] for r in s]))
        for r in te:
            lx = lnPick(r['rank']); m, k = dm[grp(r)]
            pred_new.append(1 / (1 + math.exp(k * (lx - m))) * float(Phi((c - lx) / sd)))
            pred_old.append((1 if r['sr'] else 1 / (1 + math.exp(1.2 * (lx - math.log(150))))) * float(Phi((math.log(254) - lx) / 0.7)))
            ys.append(r['drafted']); keys.append(r)
    pn, po, y = np.array(pred_new), np.array(pred_old), np.array(ys)
    def calib(p):
        e = [0, .2, .4, .6, .8, 1.01]
        return [{'pred': f'{a:.1f}-{b:.1f}', 'n': int(((p >= a) & (p < b)).sum()), 'mean': round(float(p[(p >= a) & (p < b)].mean()), 3), 'actual': round(float(y[(p >= a) & (p < b)].mean()), 3)}
                for a, b in zip(e, e[1:]) if ((p >= a) & (p < b)).sum()]
    out['chain'] = {'n': len(y), 'drafted': round(float(y.mean()), 3),
                    'new': {'logLoss': round(-ll(pn, y) / len(y), 4), 'brier': round(float(np.mean((pn - y) ** 2)), 4), 'mean': round(float(pn.mean()), 3), 'calib': calib(pn)},
                    'old': {'logLoss': round(-ll(po, y) / len(y), 4), 'brier': round(float(np.mean((po - y) ** 2)), 4), 'mean': round(float(po.mean()), 3), 'calib': calib(po)},
                    'byBand': [{'ranks': f'{a}-{b}', 'n': sum(1 for r in keys if a <= r['rank'] <= b), 'actual': round(float(np.mean([r['drafted'] for r in keys if a <= r['rank'] <= b])), 3),
                                'new': round(float(np.mean([p for p, r in zip(pn, keys) if a <= r['rank'] <= b])), 3), 'old': round(float(np.mean([p for p, r in zip(po, keys) if a <= r['rank'] <= b])), 3)} for a, b in bands]}
    print('chain', json.dumps(out['chain']))
    out['asof'] = datetime.date.today().isoformat()
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
