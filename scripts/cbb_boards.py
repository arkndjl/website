#!/usr/bin/env python3
"""The 2027 NBA draft boards the College Basketball ARKBOARD reads (scripts/data/cbb_boards/), and the map from a
board rank on a given day to the June rank it predicts (audit item #23, Oct 25 2026).

    python3 scripts/cbb_boards.py --pull    # weekly (cbb-boards.yml): re-pull the live boards into scripts/data/cbb_boards/
    python3 scripts/cbb_boards.py --fit     # the dated rank -> June map and its backtest -> scripts/data/cbb_board_att.json
                                            # (needs the board history in /mnt/project-files/cbb/boards or $CBB_BOARDS)

Pull. Boards that change through the season, each kept only if the pull parses at least MIN_ROWS players (a failed or
empty pull keeps last week's file): Tankathon's big board and CBS (live pages), No Ceilings' newest 2027 composite
(Substack API), ESPN's core API (Givony/Woo; empty until ESPN fills its 2027 database near the draft) and NBADraft.net
(empty for 2027 so far). The one-off articles (Bleacher Report, SI, FanSided, ESPN's June mock) stay as pulled.

Fit. The board stage (cbb_fit.board_stage) is trained on June ranks: the mean -ln rank on ESPN's and NBADraft.net's final
boards. The live board only has today's boards, so a player's rank today is mapped to the June rank it predicts,
-ln June = a + b (-ln rank today) + e, e ~ N(0, sd). That map was fit once, on No Ceilings' first board each year
(Nov-Dec), and used all season. Tested on every dated No Ceilings version 2022-26 (36 boards before the draft), leave
one draft out, Gaussian log score of the held-out June ranks:
  - a, b and ln sd linear (and quadratic) in ln days to the draft, fit on all dates: better overall (t 5) but worse than
    the first-board map on the Nov-Feb boards, so before CUT days the live map stays;
  - from CUT days (late February) on, a late map (a, b fixed, ln sd linear in ln days, fit on the boards under CUT
    days): the spread narrows from about .73 at CUT to .40 in draft week. This is what ships (keep in cbb_board_att.json).
"""
import csv, datetime, html, json, math, os, re, subprocess, sys, time
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D

BOARDS = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
LIVE_DIR = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_boards')
ATT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_board_att.json')
DRAFT = {2022: '2022-06-23', 2023: '2023-06-22', 2024: '2024-06-26', 2025: '2025-06-25', 2026: '2026-06-24',
         2027: '2027-06-24'}   # 2027: the NBA's usual last-Thursday-in-June slot, until the league sets it
YEAR = 2027
MIN_ROWS = 25
COLS = ['source', 'draft_year', 'board_date', 'rank', 'name', 'school', 'pos']
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'


def days_to_draft(date, year=YEAR):
    d = (datetime.date.fromisoformat(DRAFT[year]) - datetime.date.fromisoformat(date)).days
    return max(1, d)


# ---------------------------------------------------------------- the dated map
CUT = 120     # days to the draft (late February) where the late map takes over


def att_at(A, days):
    """a, b, sd of the map on a board `days` before the draft. A = cbb_board_att.json 'fit': a and b fixed, ln sd
    linear in ln days."""
    L = math.log(max(1, min(days, A['maxDays'])))
    return {'a': A['a'], 'b': A['b'], 'sd': math.exp(A['s'][0] + A['s'][1] * L)}


def live_att(C):
    """the map for today's boards: from CUT days out, the late map at the boards' median date (when
    cbb_board_att.json ships it); before that, and whenever the file or a date is missing, the board stage's own map
    (C = cbb_fit.json 'boards', fit on No Ceilings' first board)."""
    try:
        A = json.load(open(ATT))
        dates = []
        for f in os.listdir(LIVE_DIR):
            if f.endswith('.csv'):
                with open(os.path.join(LIVE_DIR, f), newline='', encoding='utf-8') as fh:
                    r = next(csv.DictReader(fh), None)
                if r and re.match(r'\d{4}-\d\d-\d\d$', r['board_date'] or ''): dates.append(r['board_date'])
        if not A.get('keep') or not dates: return C['att']
        days = days_to_draft(sorted(dates)[len(dates) // 2])
        return dict(att_at(A['fit'], days), days=days) if days < A['cut'] else C['att']
    except (OSError, ValueError, KeyError):
        return C['att']


def june_ranks():
    """the board stage's target (cbb_fit.june_ranks): -ln June consensus rank by (draft year, name key)."""
    import cbb_fit as F
    F.BOARDS = BOARDS
    return F.june_ranks()


def nc_versions():
    by = defaultdict(lambda: defaultdict(dict))
    with open(os.path.join(BOARDS, 'noceilings.csv'), newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            y = int(r['draft_year'])
            if y in DRAFT and y < YEAR: by[y][r['board_date']][D.norm(r['name'])] = int(r['rank'])
    return by


def rows():
    """one row per player on a dated No Ceilings board 2022-26: draft year, ln days to draft, -ln rank, -ln June rank."""
    jr = june_ranks()
    fill = -math.log(150)      # on neither June board (cbb_fit.CONS_FILL)
    out = []
    for y, vs in nc_versions().items():
        for date, b in vs.items():
            if date >= DRAFT[y]: continue          # the post-draft repost of the final board
            first = date == min(vs)
            for k, rk in b.items():
                out.append({'y': y, 'date': date, 'L': math.log(days_to_draft(date, y)), 'x': -math.log(rk),
                            'yj': jr.get((y, k), fill), 'first': first})
    return out


def fit_late(R, iters=8):
    """-ln June = a + b x by weighted least squares, ln sd = s0 + s1 ln days refit on the squared residuals."""
    L = np.array([r['L'] for r in R]); x = np.array([r['x'] for r in R]); y = np.array([r['yj'] for r in R])
    X = np.column_stack([np.ones(len(R)), x]); S = np.column_stack([np.ones(len(R)), L]); w = np.ones(len(R))
    for _ in range(iters):
        beta = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
        e2 = (y - X @ beta) ** 2
        s = np.linalg.lstsq(S, np.log(e2 + 1e-6) + 1.27, rcond=None)[0] / 2     # E ln chi2_1 = -1.27
        c = math.sqrt(float(np.mean(e2 / np.exp(S @ s) ** 2))); s[0] += math.log(c)
        w = 1 / np.exp(S @ s) ** 2
    return {'a': float(beta[0]), 'b': float(beta[1]), 's': [float(s[0]), float(s[1])], 'maxDays': float(math.exp(L.max()))}


def fit_const(R):
    """the board stage's map (cbb_fit.preseason_att) on these rows: one a, b, sd."""
    x = np.array([r['x'] for r in R]); y = np.array([r['yj'] for r in R])
    b, a = np.polyfit(x, y, 1)
    return {'a': float(a), 'b': float(b), 's': [math.log(float(np.std(y - a - b * x, ddof=2))), 0.0], 'maxDays': 400.0}


def score(A, R):
    ll, se = [], []
    for r in R:
        m = att_at(A, math.exp(r['L']))
        mu = m['a'] + m['b'] * r['x']
        ll.append(-0.5 * math.log(2 * math.pi * m['sd'] ** 2) - 0.5 * ((r['yj'] - mu) / m['sd']) ** 2)
        se.append((r['yj'] - mu) ** 2)
    return np.array(ll), np.array(se)


def backtest(R):
    """leave one draft out on the boards under CUT days: the late map vs the live map (first board, constant) and vs a
    constant fit on the same late rows."""
    late = [r for r in R if math.exp(r['L']) < CUT]
    years = sorted({r['y'] for r in R})
    res = defaultdict(list)
    for t in years:
        te = [r for r in late if r['y'] == t]
        for name, A in (('live', fit_const([r for r in R if r['y'] != t and r['first']])),
                        ('lateConst', fit_const([r for r in late if r['y'] != t])),
                        ('late', fit_late([r for r in late if r['y'] != t]))):
            res[name].append((t,) + score(A, te) + (te,))
    out = {'rows': len(late), 'cut': CUT}
    for name in res:
        ll = np.concatenate([x[1] for x in res[name]]); se = np.concatenate([x[2] for x in res[name]])
        out[name] = {'logScore': round(float(ll.mean()), 4), 'rmse': round(float(np.sqrt(se.mean())), 4),
                     'byDraft': {x[0]: round(float(x[1].mean()), 4) for x in res[name]}}
    for name in ('live', 'lateConst'):
        d = np.concatenate([b[1] - a[1] for a, b in zip(res[name], res['late'])])
        per = [float((b[1] - a[1]).mean()) for a, b in zip(res[name], res['late'])]
        out[f'late vs {name}'] = {'logGain': round(float(d.mean()), 4), 'tRow': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                                  'draftsBetter': int(sum(p > 0 for p in per)), 'of': len(per)}
    out['byWindow'] = []
    for lab, lo, hi in (('Mar-Apr', 60, CUT), ('May-Jun', 0, 60)):
        row = {'window': lab}
        for name in res:
            ll = np.concatenate([x[1][[lo <= math.exp(r['L']) < hi for r in x[3]]] for x in res[name]])
            row[name] = {'n': int(len(ll)), 'logScore': round(float(ll.mean()), 4) if len(ll) else None}
        out['byWindow'].append(row)
    # before CUT the live map stays: the dated alternatives tested there lost Nov-Feb (see the module notes)
    return out


def main_fit():
    R = rows()
    print(len(R), 'board rows,', len({(r['y'], r['date']) for r in R}), 'dated No Ceilings boards')
    bt = backtest(R)
    for k, v in bt.items():
        if k != 'byWindow': print(k, v)
    for w in bt['byWindow']: print('  ', w)
    A = fit_late([r for r in R if math.exp(r['L']) < CUT])
    g = bt['late vs live']
    keep = g['logGain'] > 0 and g['tRow'] >= 2 and g['draftsBetter'] >= 3
    curve = [{'days': d, **{k: round(v, 4) for k, v in att_at(A, d).items()}} for d in (119, 90, 60, 30, 14, 3)]
    print('kept' if keep else 'not kept', curve)
    json.dump({'asof': time.strftime('%Y-%m-%d'), 'keep': bool(keep), 'cut': CUT,
               'target': 'mean -ln rank on ESPN + NBADraft.net final boards (cbb_fit.june_ranks)',
               'boards': 'No Ceilings composites 2022-26, every dated version before the draft', 'rows': len(R),
               'fit': {k: ([round(x, 6) for x in v] if isinstance(v, list) else round(v, 6)) for k, v in A.items()},
               'curve': curve, 'backtest': bt, 'draft': DRAFT}, open(ATT, 'w'), indent=1)
    print('wrote', ATT)


# ---------------------------------------------------------------- pulls
def curl(url, tries=3):
    for i in range(tries):
        r = subprocess.run(['curl', '-sL', '-m', '60', '-A', UA, url], capture_output=True)
        if r.returncode == 0 and r.stdout: return r.stdout.decode('utf-8', 'replace')
        time.sleep(2 * (i + 1))
    return ''


def consecutive(rows):
    """the first run of ranks 1, 2, 3, ... (drops side lists)"""
    out = []
    for r in rows:
        if r[0] == len(out) + 1: out.append(r)
    return out


def pull_tankathon():
    h = curl('https://www.tankathon.com/big-board')
    seg = h[h.find('id="big-board"'):]
    rows = []
    for rk, nm, sp in re.findall(r'<div class="mock-row-pick-number">(\d+)</div>.*?<div class="mock-row-name">(.*?)</div>'
                                 r'<div class="mock-row-school-position">(.*?)</div>', seg, flags=re.S):
        pos, _, school = html.unescape(re.sub(r'<[^>]+>', '', sp)).partition('|')
        rows.append((int(rk), html.unescape(nm).strip(), school.strip(), pos.strip()))
    return 'tankathon', time.strftime('%Y-%m-%d'), consecutive(rows)


def pull_cbs():
    h = curl('https://www.cbssports.com/nba/draft/prospect-rankings/')
    t = h[h.find('table-base-nba-prospect-rankings'):]
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, flags=re.S):
        c = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', x))).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S)]
        if len(c) >= 5 and c[0].isdigit(): rows.append((int(c[0]), c[1], c[2], c[4]))
    return 'cbs', time.strftime('%Y-%m-%d'), consecutive(rows)


def _nc_lines(body):
    t = re.sub(r'<(?!/?(?:a|span|strong|em|b|i)\b)[^>]+>', '\n', body)
    t = html.unescape(re.sub(r'<[^>]+>', '', t)).replace('\xa0', ' ')
    return [re.sub(r'\s+', ' ', l).strip() for l in t.split('\n') if l.strip()]


def pull_noceilings():
    """the newest 2027 No Ceilings composite ('#N. Name | POS | School', their 2025+ layout)."""
    api = 'https://www.noceilingsnba.com/api/v1'
    try: arr = json.loads(curl(f'{api}/archive?sort=new&search=big%20board&offset=0&limit=50') or '[]')
    except ValueError: arr = []
    posts = sorted((p for p in arr if re.match(rf'^{YEAR}-nba-draft-big-board(-v\d+)?$', p.get('slug', ''))), key=lambda p: p['post_date'])
    if not posts: return 'noceilings', None, []
    p = posts[-1]
    try: body = json.loads(curl(f"{api}/posts/{p['slug']}") or '{}').get('body_html') or ''
    except ValueError: body = ''
    out, seen = [], set()
    for l in _nc_lines(body):
        m = re.match(r"^#?\s*(\d{1,3})\s*\.\s+([A-Za-zÀ-ɏ'][^|]*?)\s*\|\s*(.*)$", l)
        if not m or re.search(r'PTS|REB|AST|FG%|PPG', l): continue
        rk, name = int(m.group(1)), m.group(2).strip()
        parts = [x.strip() for x in m.group(3).split('|')]
        if rk in seen or len(name) > 40: continue
        seen.add(rk)
        out.append((rk, name, parts[-1], parts[0] if len(parts) >= 2 else ''))
    return 'noceilings', p['post_date'][:10], consecutive(sorted(out))


def pull_espn():
    """ESPN's core API: each athlete's 'overall' attribute is the Givony/Woo big-board rank."""
    base = f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{YEAR}/draft/athletes?limit=500'
    try: items = json.loads(curl(base) or '{}').get('items') or []
    except ValueError: items = []
    rows, colleges = [], {}
    for it in items[:300]:
        try: a = json.loads(curl(it['$ref'].replace('http://', 'https://')) or '{}')
        except ValueError: continue
        rk = next((int(x['value']) for x in a.get('attributes', []) if x.get('name') == 'overall'), None)
        if not rk: continue
        school = ''
        cref = (a.get('college') or {}).get('$ref')
        if cref:
            if cref not in colleges:
                try: c = json.loads(curl(cref.replace('http://', 'https://')) or '{}')
                except ValueError: c = {}
                colleges[cref] = c.get('name') or c.get('shortName') or ''
            school = colleges[cref]
        rows.append((rk, ' '.join((a.get('displayName') or '').split()), school, (a.get('position') or {}).get('abbreviation', '')))
    return 'espn', time.strftime('%Y-%m-%d'), consecutive(sorted(rows))


def pull_nbadraftnet():
    h = curl(f'https://www.nbadraft.net/ranking/bigboard/?year-ranking={YEAR}')
    strip = lambda s: html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'</span><span>', ' ', re.sub(r'<noscript>.*?</noscript>', '', s, flags=re.S)))).strip()
    rows = []
    for tr in re.findall(r'<tr class="(?:odd|even)">(.*?)</tr>', h, flags=re.S):
        c = dict(re.findall(r'<td class="([a-z]+)">(.*?)</td>', tr, flags=re.S))
        if 'rank' in c and strip(c['rank']).isdigit():
            rows.append((int(strip(c['rank'])), strip(c.get('name', '')), strip(c.get('team', '')), strip(c.get('teamposition', ''))))
    return 'nbadraftnet', time.strftime('%Y-%m-%d'), consecutive(sorted(rows))


def main_pull():
    os.makedirs(LIVE_DIR, exist_ok=True)
    changed = 0
    for fn in (pull_tankathon, pull_cbs, pull_noceilings, pull_espn, pull_nbadraftnet):
        try: src, date, rows = fn()
        except Exception as e:      # one source down never stops the others
            print(fn.__name__, 'failed:', e); continue
        if len(rows) < MIN_ROWS or not date:
            print(f'{src}: {len(rows)} rows, kept the last pull'); continue
        p = os.path.join(LIVE_DIR, f'{src}_{YEAR}.csv')
        with open(p, 'w', newline='', encoding='utf-8') as o:
            w = csv.writer(o); w.writerow(COLS)
            w.writerows([[src, YEAR, date, rk, nm, sc, ps] for rk, nm, sc, ps in rows])
        changed += 1
        print(f'{src}: {len(rows)} rows ({date}), top 3:', ', '.join(r[1] for r in rows[:3]))
    print(changed, 'boards refreshed')


if __name__ == '__main__':
    if '--fit' in sys.argv: main_fit()
    elif '--pull' in sys.argv: main_pull()
    else: sys.exit(__doc__)
