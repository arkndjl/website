"""Extra season lines for the CFB FV candidate stage (scripts/cfb_fv_refit.mjs --wide --stage=cand), Oct 31 2026 sweep:
  returns  kick and punt returns from ESPN box scores (CFB_BOX_RETURNS=1 python3 scripts/cfb_roster_hist.py 2012 2022),
           summed by season and ESPN athlete: returns, yards, TDs, games, team (the team he played most games for)
  defense  ESPN's season leaderboard (cfb_roster_hist.py --def): tackles, sacks, TFL, passes defended, FF, INT, games
  honors   postseason all-conference teams (Wikipedia "<year> All-<conference> football team", every FBS conference
           with a page) and the All-America page: best team level per selector (1st 3, 2nd 2, 3rd / HM 1)
Rows carry the player's name and school as the source writes them; the harness joins them through scripts/names.mjs
(Matcher on name + team + position).
  python3 scripts/cfb_fv_extras.py [first] [last] -> scripts/.cache/fvrefit/extras.json
"""
import collections
import csv
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402  (scripts/names.py, the shared matcher)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EH = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist')
RO = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'ros')
WK = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'wiki')
OUT = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'extras.json')
UA = {'User-Agent': 'Mozilla/5.0 (arkndjl.net research)'}


def teams(S):
    t, conf = {}, {}
    for r in csv.DictReader(open(os.path.join(RO, f's{S}.csv'))):
        for a in ('home', 'away'):
            t[r[a + '_id']] = r[a + '_team']
            if r.get(a + '_division') == 'fbs':
                conf[r[a + '_team']] = r.get(a + '_conference') or None
    return t, conf


def returns(S, T):
    ids = set()
    for f in glob.glob(os.path.join(EH, f'sb{S}_80_*.json')):
        ids |= {g['id'] for g in json.load(open(f)) or [] if g['done']}
    L = {}
    for i in ids:
        p = os.path.join(EH, 'box', f'{i}.json')
        if not os.path.exists(p):
            continue
        for tid, P in json.load(open(p)).items():
            for aid, r in P.items():
                x = L.setdefault(aid, {'n': r['n'], 'tm': collections.Counter(), 'gp': 0, 'kr': 0, 'kry': 0, 'krt': 0, 'pr': 0, 'pry': 0, 'prt': 0})
                x['tm'][tid] += 1
                x['gp'] += 1
                for k, src in (('kr', 'kic_NO'), ('kry', 'kic_YDS'), ('krt', 'kic_TD'), ('pr', 'pun_NO'), ('pry', 'pun_YDS'), ('prt', 'pun_TD')):
                    x[k] += r.get(src) or 0
    out = []
    for aid, x in L.items():
        if x['kr'] + x['pr'] <= 0:
            continue
        tid = x['tm'].most_common(1)[0][0]
        out.append({'eid': aid, 'name': x['n'], 'team': T.get(tid, ''), 'gp': x['gp'], **{k: x[k] for k in ('kr', 'kry', 'krt', 'pr', 'pry', 'prt')}})
    return out


def defense(S, T):
    p = os.path.join(EH, f'def{S}.json')
    if not os.path.exists(p):
        return []
    return [{'eid': x['id'], 'name': x['n'], 'pos': x.get('pos'), 'team': T.get(str(x.get('team')), ''),
             **{k: x.get(k) for k in ('gamesPlayed', 'totalTackles', 'soloTackles', 'sacks', 'tacklesForLoss', 'passesDefended', 'fumblesForced', 'interceptions')}}
            for x in json.load(open(p))]


# ---- honors -------------------------------------------------------------------------------------------------------
# page -> cfbfastR conference name (a team-season whose conference has no page is unknown, not unhonored)
CONF_OF = {'All-SEC': 'SEC', 'All-Big Ten Conference': 'Big Ten', 'All-Big 12 Conference': 'Big 12', 'All-Atlantic Coast Conference': 'ACC',
           'All-ACC': 'ACC', 'All-Pac-12 Conference': 'Pac-12', 'All-American Athletic Conference': 'American Athletic',
           'All-Mountain West Conference': 'Mountain West', 'All-Mid-American Conference': 'Mid-American', 'All-Conference USA': 'Conference USA',
           'All-Sun Belt Conference': 'Sun Belt', 'All-Big East Conference': 'Big East'}
SEASON_ART = {'SEC': 'Southeastern Conference', 'Big Ten': 'Big Ten Conference', 'Big 12': 'Big 12 Conference', 'ACC': 'Atlantic Coast Conference',
              'Pac-12': 'Pac-12 Conference', 'American Athletic': 'American Athletic Conference', 'Mountain West': 'Mountain West Conference',
              'Mid-American': 'Mid-American Conference', 'Conference USA': 'Conference USA', 'Sun Belt': 'Sun Belt Conference', 'Big East': 'Big East Conference'}
CONFS = ['All-SEC', 'All-Big Ten Conference', 'All-Big 12 Conference', 'All-Atlantic Coast Conference', 'All-ACC', 'All-Pac-12 Conference',
         'All-American Athletic Conference', 'All-Mountain West Conference', 'All-Mid-American Conference', 'All-Conference USA',
         'All-Sun Belt Conference', 'All-Big East Conference']


def wiki(title):
    os.makedirs(WK, exist_ok=True)
    f = os.path.join(WK, re.sub(r'[^\w-]', '_', title) + '.txt')
    if not os.path.exists(f):
        u = 'https://en.wikipedia.org/w/index.php?action=raw&title=' + urllib.parse.quote(title)
        txt = ''
        for i in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                    txt = r.read().decode('utf8')
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                time.sleep(4 * (i + 1))
            except Exception:
                time.sleep(4 * (i + 1))
        # follow a #REDIRECT
        m = re.match(r'\s*#REDIRECT\s*\[\[([^\]#]+)', txt, re.I)
        if m:
            return wiki(m[1].strip())
        open(f, 'w').write(txt)
        time.sleep(1)
    return open(f).read()


def clean(s):
    s = re.sub(r'\{\{sortname\|([^|}]+)\|([^|}]+)[^}]*\}\}', r'\1 \2', s)
    s = re.sub(r'\{\{(?:nowrap|nobr|center|centre|small|big|bold|nbsp)\|([^}]*)\}\}', r'\1', s, flags=re.I)
    s = re.sub(r'<ref[^>]*/>|<ref[^>]*>.*?</ref>|<nowiki>.*?</nowiki>', '', s)
    s = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]+)\]\]', r'\1', s)
    s = re.sub(r"<[^>]+>|'''|''|\{\{[^}]*\}\}", '', s)
    return s.strip()


LEVEL = [(re.compile(r'(?:\b|-)(?:1|1st|first)(?:\b|-)', re.I), 3), (re.compile(r'(?:\b|-)(?:2|2nd|second)(?:\b|-)', re.I), 2),
         (re.compile(r'(?:\b|-)(?:3|3rd|third)(?:\b|-)|\bHM\b|honou?rable', re.I), 1)]


def level_of(tag):
    for rx, v in LEVEL:
        if rx.search(tag):
            return v
    return None


def honors_page(txt):
    """Bulleted honors: '* Name, School (AP-1, Coaches-2)' or '* [[Name]], [[School|x]] <small>(AP, FWAA)</small>'. A page
    whose sections are first / second team (no per-line tags) takes the section's level. Returns [(name, school, best level,
    n selectors at that level, section heading)]"""
    out, sec, sec_lv = [], '', None
    for line in txt.split('\n'):
        h = re.match(r'^(=+)\s*(.*?)\s*\1\s*$', line)
        if h:
            sec = clean(h[2])
            lv = level_of(sec) if re.search(r'team|selection', sec, re.I) else None
            if lv is not None or int(len(h[1])) <= 2:
                sec_lv = lv
            continue
        m = re.match(r'^\*+\s*(.+)$', line)
        if not m:
            continue
        body = m[1]
        tags = re.findall(r'\(([^()]*)\)', clean(body.replace('<small>', '(').replace('</small>', ')') if '<small>' in body and '(' not in body else body))
        main = clean(re.sub(r'\([^()]*\)', '', re.sub(r'<small>.*?</small>', '', body)))
        if ',' not in main:
            continue
        name, sch = [x.strip() for x in main.split(',', 1)]
        sch = re.split(r'[;(]', sch)[0].strip()
        if not name or len(name.split()) < 2 or len(name) > 40:
            continue
        lvls = []
        for t in tags:
            for part in re.split(r'[;,]', t):
                v = level_of(part)
                if v:
                    lvls.append(v)
                elif part.strip() and sec_lv:
                    lvls.append(sec_lv)
        if not tags and sec_lv:
            lvls = [sec_lv]
        if not lvls:
            continue
        b = max(lvls)
        out.append((name, sch, b, sum(1 for v in lvls if v == b), sec))
    return out


TEAM_FIX = {'missst': 'mississippistate', 'mississippist': 'mississippistate', 'olemiss': 'mississippi', 'ncstate': 'northcarolinastate',
            'miamifl': 'miami', 'miamiflorida': 'miami', 'miamiohio': 'miamioh', 'usc': 'southerncalifornia', 'ucf': 'centralflorida',
            'smu': 'southernmethodist', 'tcu': 'texaschristian', 'byu': 'brighamyoung', 'unlv': 'nevadalasvegas', 'utsa': 'texassanantonio',
            'utep': 'texaselpaso', 'fiu': 'floridainternational', 'fau': 'floridaatlantic', 'uab': 'alabamabirmingham', 'usf': 'southflorida',
            'ulm': 'louisianamonroe', 'ulmonroe': 'louisianamonroe', 'ullafayette': 'louisiana', 'louisianalafayette': 'louisiana',
            'appstate': 'appalachianstate', 'pitt': 'pittsburgh', 'gatech': 'georgiatech', 'vatech': 'virginiatech', 'sjsu': 'sanjosestate',
            'umass': 'massachusetts', 'uconn': 'connecticut', 'niu': 'northernillinois', 'wmu': 'westernmichigan', 'cmu': 'centralmichigan',
            'emu': 'easternmichigan', 'okstate': 'oklahomastate', 'kstate': 'kansasstate', 'tamu': 'texasam', 'lsu': 'louisianastate',
            'southernmiss': 'southernmississippi', 'wku': 'westernkentucky', 'mtsu': 'middletennessee', 'middletennesseestate': 'middletennessee',
            'latech': 'louisianatech', 'ecu': 'eastcarolina', 'usu': 'utahstate', 'csu': 'coloradostate', 'hawai': 'hawaii', 'sanjose': 'sanjosestate',
            'texasstatesanmarcos': 'texasstate', 'buffalobulls': 'buffalo', 'ohiostatebuckeyes': 'ohiostate'}


def tkey(s):
    k = names.team_key(s or '')
    return TEAM_FIX.get(k, k)


def resolver(members):
    """a Wikipedia school string -> that conference-season's cfbfastR team, or None"""
    M = {}
    for t in members:
        M.setdefault(tkey(t), t)
        M.setdefault(names.team_key(t), t)

    def res(x):
        x = re.sub(r'\(.*?\)|[*†‡#^]', '', x or '').strip()
        if not x or len(x) > 40:
            return None
        k = tkey(x)
        if k in M:
            return M[k]
        c = {t for kk, t in M.items() if len(k) >= 5 and (kk.startswith(k) or k.startswith(kk))}
        return c.pop() if len(c) == 1 else None
    return res


POSW = re.compile(r'^(quarterback|running|wide|receiver|tight|tackle|guard|center|offensive|defensive|lineman|linemen|linebacker|end|'
                  r'cornerback|safety|safeties|back|kicker|punter|specialist|return|all[- ]purpose|athlete|position|player|school|name|team|'
                  r'first|second|third|honorable|offense|defense|special|coach|freshman|newcomer)\b', re.I)


def lvl(x):
    x = clean(x)
    if re.search(r'honou?rable', x, re.I):
        return 1
    if re.search(r'\b(first|1st)[- ]?team\b|^\s*first\s*$', x, re.I):
        return 3
    if re.search(r'\b(second|2nd)[- ]?team\b|^\s*second\s*$', x, re.I):
        return 2
    if re.search(r'\b(third|3rd)[- ]?team\b|^\s*third\s*$', x, re.I):
        return 1
    return None


def generic_section(txt, res, whole=False):
    """all-conference honorees out of a season article's honors section (or a whole dedicated page), whatever the
    layout: tables with one level per table, levels side by side, or bullets under level labels. A row holding several
    player-school pairs takes the levels of the last multi-level header in order"""
    L = txt.split('\n')
    heads = [(i, len(m[1]), clean(m[2])) for i, l in enumerate(L) for m in [re.match(r'^(=+)\s*(.*?)\s*=+\s*$', l)] if m]
    spans = []
    if whole:
        spans = [(0, len(L))]
    else:
        for j, (i, lv, h) in enumerate(heads):
            if re.search(r'^all[- ]?\S*\s*(conference|team|honors|selections)?', h, re.I) and re.search(r'^all', h, re.I) \
                    and not re.search(r'^all[- ]americans?\b(?!\s*athletic)|academic|preseason|freshman|time', h, re.I):
                end = next((k for k, l2, _ in heads[j + 1:] if l2 <= lv), len(L))
                spans.append((i + 1, end))
    out = []
    for a, b in spans:
        cur, multi, rows, buf, tbl = None, [], [], [], 0

        def flush():
            nonlocal buf
            if buf:
                rows.append((cur, tbl, buf))
            buf = []
        for l in L[a:b]:
            st = l.strip()
            if not st:
                continue
            if re.match(r'^=+.*=+$', st) or re.match(r"^('''|;)", st):
                flush()
                v = lvl(st)
                if v:
                    cur, multi = v, []
                continue
            if st.startswith('{|') or st.startswith('|-') or st.startswith('|}'):
                flush()
                tbl += st.startswith('{|')
                continue
            if st[0] in '|!':
                for c in re.split(r'\|\||!!', st[1:]):
                    m = re.match(r'\s*((?:colspan|rowspan|style|align|class|width|scope|bgcolor)[^|]*)\|(.*)$', c)
                    if m:
                        c = m[2]
                    buf.append(clean(c))
                continue
            if st.startswith('*'):
                flush()
                v = lvl(st)
                item = re.sub(r'^\*+\s*', '', st)
                item = re.sub(r'^[A-Za-z/ .]{1,25}:\s*', '', item)       # "QB: Name, School"
                parts = [clean(x) for x in re.split(r',|\s[-–]\s', re.sub(r'\([^()]*\)', '', item))]
                sch = next((res(x) for x in parts[1:] if res(x)), None)
                nmx = re.sub(r'[*†‡#^]+$', '', parts[0] if parts else '').strip()
                if sch and (v or cur) and len(nmx.split()) >= 2 and not POSW.match(nmx):
                    out.append((nmx, sch, v or cur))
                elif v and not sch:
                    cur, multi = v, []
                continue
            flush()
            v = lvl(st)
            if v and len(st) < 60:
                cur, multi = v, []
        flush()
        last, tcur, tmulti = None, None, []
        for c0, tb, r in rows:
            if (tb, c0) != last:
                last, tcur, tmulti = (tb, c0), None, []
            labs = [lvl(c) for c in r]
            if any(labs) and not any(res(c) for c in r):
                ls = [x for x in labs if x]
                if len(ls) >= 2:
                    tmulti = ls
                else:
                    tcur, tmulti = ls[0], []
                continue
            c0 = tcur or c0
            multi = tmulti
            pairs, pend = [], None
            for c in r:
                c2 = re.sub(r'[*†‡#^]+$', '', c).strip()
                t = res(c2)
                if t and pend:
                    pairs.append((pend, t))
                    pend = None
                elif not t and len(c2.split()) >= 2 and len(c2) <= 35 and not POSW.match(c2) and not re.search(r'\d', c2):
                    pend = c2
            for k, (n, t) in enumerate(pairs):
                v = multi[k] if multi and k < len(multi) else c0
                if v:
                    out.append((n, t, v))
    return out


def honors(S, CF):
    rows, have = [], set()
    for c in CONFS:
        cf = CONF_OF[c]
        if cf in have:
            continue
        res = resolver([t for t, x in CF.items() if x == cf])
        best = []
        t = wiki(f'{S} {c} football team')
        if t:
            H = [(n, res(s), lv, k) for n, s, lv, k, _ in honors_page(t)]
            best = [h for h in H if h[1]]
            if len(best) < 30:
                best = [(n, s, lv, 1) for n, s, lv in generic_section(t, res, whole=True)]
        if len(best) < 30 and SEASON_ART.get(cf):
            t2 = wiki(f'{S} {SEASON_ART[cf]} football season')
            g = [(n, s, lv, 1) for n, s, lv in generic_section(t2, res)] if t2 else []
            if len(g) > len(best):
                best = g
        allteams = {tkey(t) for t in CF}
        best = [h for h in best if not re.search(r'[\d•@]|stadium|bowl|field\b', h[0], re.I) and tkey(h[0]) not in allteams]
        n3, n2 = sum(1 for h in best if h[2] == 3), sum(1 for h in best if h[2] == 2)
        # no page, a stub, or a layout parsed in part (a first team is ~24-28 players with specialists; partial
        # coverage would read honorees as unhonored)
        if n3 < 22 or n2 < 18:
            print('  ', S, cf, 'skipped', len(best), flush=True)
            continue
        have.add(cf)
        seen = {}
        for n, s, lv, k in best:
            kk = (names.key(n), s)
            if kk not in seen or seen[kk]['lv'] < lv:
                seen[kk] = {'name': n, 'team': s, 'lv': lv, 'n': k, 'conf': cf}
        rows += list(seen.values())
    aa = []
    t = wiki(f'{S} All-America college football team')
    for m in re.finditer(r'^\*+\s*(.+?),\s*\[\[[^\]|]*\|?([^\]]*)\]\][^\n]*?<small>\s*\(([^)]*)\)', t, re.M):
        aa.append({'name': clean(m[1]), 'team': clean(m[2]), 'n': len([x for x in m[3].split(',') if x.strip()])})
    return rows, aa, sorted(have)


if __name__ == '__main__':
    lo, hi = (int(x) for x in (sys.argv[1:3] if len(sys.argv) > 2 else (2012, 2022)))
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for S in range(lo, hi + 1):
        T, CF = teams(S)
        h, aa, have = honors(S, CF)
        out[str(S)] = {'ret': returns(S, T), 'def': defense(S, T), 'conf': h, 'aa': aa, 'pages': have, 'teamConf': CF}
        print(S, 'returners', len(out[str(S)]['ret']), 'def', len(out[str(S)]['def']), 'all-conf', len(h), have,
              collections.Counter(r['conf'] for r in h).most_common(), 'AA', len(aa), flush=True)
    json.dump(out, open(OUT, 'w'))
