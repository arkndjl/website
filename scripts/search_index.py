# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The site search's player and team index: static/data/search-players.json.

    python3 scripts/search_index.py          # rewrite it (skips the write when only asof would change)

Every ARKBOARD player and team list that the boards read, flattened into one compact list for the search bar
(assets/js/search.js). The rest of the index (pages, tabs, glossary, ARKLIBRARY, ST. CLAIRE, 1NT, LAURSEN_111,
articles) is written by Hugo on each build (layouts/_default/list.searchindex.json), so it always follows the site.

Rows are [board, name, sub, img, w, pid?, q?]:
  board  index into "boards": [page, tab, kind]; page = the content file's stem (Hugo maps it to the page's URL and
         title at build time, so a moved page keeps its links), tab = the wintabs tab the row opens, kind "p" player
         or "t" team. The link is <page url>#<tab slug>:q=<name>[&p=<pid>] (wintabs.html opens the tab, the board's
         own filter reads q and p: tablefilter.js, cfb.js, cbb.js, nflwar.html's __hp).
  sub    position, team (scouting-report style, no prose)
  pid    the board's row key (opens the scouting report), or 0; q the filter text when the board shows another name
  img    index into "imgs" (a team logo, full colour), or -1
  w      0-99: the row's standing on its own board (rank percentile), the search's tie-break prior
Stdlib only. Run by .github/workflows/search-index.yml after the board workflows."""
import glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'static/data/search-players.json')


def load(rel):
    p = os.path.join(ROOT, rel)
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError) as e:
        print(f'  skip {rel}: {e}', file=sys.stderr); return None


def latest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)), key=lambda f: int(re.sub(r'\D', '', os.path.basename(f)) or 0))
    return os.path.relpath(fs[-1], ROOT) if fs else None


def slug(s):
    return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()))


def exists(rel):
    return os.path.exists(os.path.join(ROOT, 'static', rel.lstrip('/')))


class Index:
    def __init__(self):
        self.boards, self.bix, self.imgs, self.iix, self.rows = [], {}, [], {}, []

    def board(self, page, tab, kind='p'):
        k = (page, tab, kind)
        if k not in self.bix: self.bix[k] = len(self.boards); self.boards.append(list(k))
        return self.bix[k]

    def img(self, path):
        if not path or not exists(path): return -1
        if path not in self.iix: self.iix[path] = len(self.imgs); self.imgs.append(path)
        return self.iix[path]

    def add(self, page, tab, items, kind='p'):
        """items: (name, sub, img path, score or None, pid); w = rank percentile of score on this list (higher better)"""
        items = [x for x in items if x[0]]
        if not items: return 0
        b = self.board(page, tab, kind)
        scored = sorted((x[3] for x in items if isinstance(x[3], (int, float))))
        n = len(scored)
        def pct(s):
            if not n or not isinstance(s, (int, float)): return 20
            lo, hi = 0, n
            while lo < hi:
                m = (lo + hi) // 2
                if scored[m] < s: lo = m + 1
                else: hi = m
            return min(99, int(100 * lo / n))
        seen = set()
        for name, sub, im, sc, pid, *q in items:
            key = (name.lower(), sub.lower())
            if key in seen: continue
            seen.add(key)
            row = [b, name.strip(), sub, self.img(im), pct(sc)]
            if pid or q: row.append(pid or 0)
            if q: row.append(q[0])   # the board's filter text when it shows the row by another name (a team code)
            self.rows.append(row)
        return len(seen)


def sub(*parts):
    return ' · '.join(str(p) for p in parts if p not in (None, '', '-'))


def cfb(ix):
    d = load('static/data/cfb-all.json')
    if not d: return
    c = {k: i for i, k in enumerate(d['cols'])}
    items, teams = [], {}
    for r in d['rows']:
        name, team, logo = r[c['name']], r[c['team']], r[c['logo']]
        m = re.search(r'/id/(\d+)', r[c['espnl']] or '')
        pid = 'e' + m.group(1) if m else slug(f'{name} {team}')
        items.append((name, sub(r[c['pos']], team), logo, r[c['fv']], pid))
        if team and team not in teams: teams[team] = (team, sub(r[c['conf']], r[c['div']]), logo)
    print('cfb players', ix.add('arkboard-college-football', 'all', items))
    rk = load('data/cfb_rank.json') or {}
    order = {}
    for t in rk.get('teams') or []:
        if isinstance(t, dict) and t.get('team'):
            order[t['team']] = t.get('rating')
            if t['team'] not in teams: teams[t['team']] = (t['team'], t.get('conf') or '', t.get('logo'))
            elif t.get('abbr'): teams[t['team']] = (t['team'], sub(t['abbr'], t.get('conf')), teams[t['team']][2] or t.get('logo'))
    print('cfb teams', ix.add('arkboard-college-football', 'ARK Ranking',
                              [(n, s, lo, order.get(n), None) for n, s, lo in teams.values()], 't'))


def cbb(ix):
    d = load('static/data/cbb-all.json')
    if d:
        c = {k: i for i, k in enumerate(d['cols'])}
        items = []
        for r in d['rows']:
            name, team = r[c['name']], r[c['team']]
            l = r[c['links']] or {}
            m, b = re.search(r'/id/(\d+)', l.get('espn') or ''), re.search(r'/players/([^/.]+)', l.get('bbref') or '')
            pid = 'e' + m.group(1) if m else 'b' + b.group(1) if b else slug(f'{name} {team}')
            items.append((name, sub(r[c['pos']], team), r[c['logo']], r[c['fv']], pid))
        print('cbb players', ix.add('arkboard-college-basketball', 'cbb', items))
    g = load('data/cbb_games.json')
    if g:
        print('cbb teams', ix.add('arkboard-college-basketball', 'ARK Ranking',
                                  [(t['t'], t.get('conf') or '', t.get('logo'), -(t.get('rk') or 999), None) for t in g.get('power') or []], 't'))


PRO = {'nfl': ('arkboard-nfl', 'WAR leaders', 'static/data/nfl-war.json', 't', 'war'),
       'nba': ('arkboard-nba', 'VORX/XPM leaders', None, 'tm', 'vorx'),
       'nhl': ('arkboard-nhl', 'WAR leaders', None, 'tm', 'war')}


def pro(ix):
    names = load('data/pro_team_names.json') or {}
    for sp, (page, tab, src, tk, met) in PRO.items():
        src = src or latest(f'static/data/{sp}-{"xpm" if sp == "nba" else "war"}/*.json')
        d = load(src) if src else None
        if d:
            items = [(p['n'], sub(p.get('pos'), p.get(tk)), f'/img/{sp}/{str(p.get(tk) or "").lower()}.png', p.get(met), None)
                     for p in d.get('players') or []]
            if sp == 'nfl':   # QBs have their own board (QBs tab, layouts/shortcodes/nflqb.html)
                qb = [it for it, p in zip(items, d.get('players') or []) if p.get('pos') == 'QB']
                items = [it for it, p in zip(items, d.get('players') or []) if p.get('pos') != 'QB']
                print(sp, 'qbs', ix.add(page, 'QBs', qb))
            print(sp, 'players', ix.add(page, tab, items))
        g = load(f'data/{sp}_games.json')
        if g:
            nm = names.get(sp, {})
            items = []
            for t in g.get('power') or []:
                full = nm.get(t['t']) or t['t']
                items.append((full, sub(t['t'], t.get('dv') or t.get('div') or t.get('cname')), f'/img/{sp}/{t["t"].lower()}.png', t.get('rating'), None, t['t']))
            print(sp, 'teams', ix.add(page, 'ARK Ranking', items, 't'))


def soccer(ix):
    src = latest('static/data/soccer-war/*.json')
    d = load(src) if src else None
    logos = (load('data/soccer_logos.json') or {}).get('espn', {})
    def logo(team):
        i = logos.get(team)
        return f'/img/soccer/{i}.png' if i else None
    if d:
        print('soccer players', ix.add('arkboard-soccer', 'GAR leaders',
                                       [(p['n'], sub(p.get('pos'), p.get('team')), logo(p.get('team')), p.get('gar'), None) for p in d.get('players') or []]))
    g = load('data/soccer_games.json')
    if g:
        print('soccer teams', ix.add('arkboard-soccer', 'ARK Ranking',
                                     [(t['n'], sub(t.get('ab'), t.get('lg')), f'/img/soccer/{t["id"]}.png', t.get('rating'), None) for t in g.get('power') or []], 't'))
    sp = load('data/soccer_prospects.json')
    if sp:
        print('soccer prospects', ix.add('arkboard-soccer-prospects', 'big board',
                                         [(p['name'], sub(p.get('pos'), p.get('club')), logo(p.get('club')), p.get('fvx'), None) for p in sp.get('board') or []]))


def hockey(ix):
    d = load('data/hockey.json')
    if not d: return
    print('hockey board', ix.add('arkboard-hockey-prospects', 'draft board',
                                 [(p['name'], sub(p.get('pos'), p.get('club')), None, p.get('fvx'), None) for p in d.get('board') or []]))
    print('hockey pipe', ix.add('arkboard-hockey-prospects', 'drafted prospects',
                                [(p['name'], sub(p.get('pos'), p.get('team')), f'/img/nhl/{str(p.get("team") or "").lower()}.png', p.get('fvx'), None)
                                 for p in d.get('pipe') or []]))


def tennis(ix):
    d = load('data/tennis.json')
    if d:
        for tour in ('atp', 'wta'):
            t = (d.get('tours') or {}).get(tour) or {}
            print(tour, ix.add('arkboard-tennis', f'{tour.upper()} ARK Ranking',
                               [(p['n'], sub(tour.upper(), (p.get('nat') or '').upper()), f'/img/flags/{p.get("nat")}.png' if p.get('nat') else None, p.get('ark'), None)
                                for p in t.get('players') or []]))
    d = load('data/tennis_prospects.json')
    if d:
        for tour in ('atp', 'wta'):
            print(tour, 'prospects', ix.add('arkboard-tennis-prospects', f'{tour.upper()} big board',
                                            [(p['name'], sub(tour.upper(), (p.get('nat') or '').upper()), f'/img/flags/{p.get("nat")}.png' if p.get('nat') else None, p.get('fvx'), None)
                                             for p in (d.get(tour) or {}).get('board') or []]))


def cs2(ix):
    d = load('data/cs2_players.json')
    if d:
        def row(p, k):
            return (p['n'], sub(p.get('tm')), f'/img/cs2/{p["tk"]}.png' if p.get('logo') and p.get('tk') else None, p.get(k), None)
        print('cs2 players', ix.add('arkboard-counter-strike', 'RWA leaders', [row(p, 'rwa') for p in d.get('board') or []]))
        print('cs2 prospects', ix.add('arkboard-counter-strike', 'prospects', [row(p, 'rwa') for p in d.get('prospects') or []]))
    g = load('data/cs2.json')
    if g:
        print('cs2 teams', ix.add('arkboard-counter-strike', 'ARK Ranking',
                                  [(t['n'], sub(t.get('rg')), f'/img/cs2/{t["k"]}.png' if t.get('logo') else None, t.get('ark'), None) for t in g.get('teams') or []], 't'))


def baseball(ix):
    # the baseball boards are markdown tables in posts (shortcodes/board.html): the player column by its header
    for post, tab in (('ARKBOARD-MLB-DRAFT-HITTERS-v1', 'draft hitters'), ('u19-milb-evaluations-may26', 'U19 MiLB'),
                      ('prospect-grades-chicago-white-sox', 'White Sox org')):
        try:
            with open(os.path.join(ROOT, f'content/posts/{post}.md'), encoding='utf-8') as f: text = f.read()
        except OSError: continue
        lines = [l for l in text.splitlines() if l.startswith('|')]
        if len(lines) < 3: continue
        cells = lambda l: [re.sub(r'[*\\]', '', x).strip() for x in l.strip().strip('|').split('|')]
        head = [h.lower() for h in cells(lines[0])]
        ni = next((i for i, h in enumerate(head) if h in ('player', 'prospect', 'name')), None)
        if ni is None: continue
        pi = next((i for i, h in enumerate(head) if h in ('pos', 'h-pos')), None)
        ti = next((i for i, h in enumerate(head) if h in ('school', 'team', 'org/lvl')), None)
        fi = next((i for i, h in enumerate(head) if h == 'fv'), None)
        items = []
        for l in lines[2:]:
            c = cells(l)
            if len(c) <= ni or not c[ni] or not re.search('[A-Za-z]', c[ni]): continue
            try: fv = float(c[fi]) if fi is not None else None
            except ValueError: fv = None
            items.append((c[ni], sub(c[pi] if pi is not None and pi < len(c) else '', c[ti] if ti is not None and ti < len(c) else ''), None, fv, None))
        print('baseball', tab, ix.add('arkboard-baseball', tab, items))


def main():
    ix = Index()
    for f in (cfb, cbb, pro, soccer, hockey, tennis, cs2, baseball):
        try: f(ix)
        except Exception as e: print(f'  {f.__name__} failed: {e!r}', file=sys.stderr)
    asof = max((str((load(p) or {}).get('asof') or '') for p in ('static/data/cfb-all.json', 'data/nfl_games.json')), default='')
    out = {'asof': asof, 'boards': ix.boards, 'imgs': ix.imgs, 'rows': ix.rows}
    body = lambda o: json.dumps({k: v for k, v in o.items() if k != 'asof'}, separators=(',', ':'), ensure_ascii=False)
    try:
        with open(OUT, encoding='utf-8') as f: old = json.load(f)
        if body(old) == body(out): print('search index unchanged'); return
    except (OSError, ValueError): pass
    with open(OUT, 'w', encoding='utf-8') as f: json.dump(out, f, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    print(f'{len(ix.rows)} rows, {len(ix.boards)} boards, {len(ix.imgs)} images, {os.path.getsize(OUT) / 1e6:.2f} MB -> {os.path.relpath(OUT, ROOT)}')


if __name__ == '__main__':
    main()
