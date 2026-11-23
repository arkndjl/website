"""Award lists parsed from the cached Wikipedia pages (fetch_wiki.py): one record per (season, player).

football(season) -> {'heis': [(name, school, points)], 'aa': [(name, school)], 'award': [(name, school)]}
basketball(season) -> {'aa': [(name, school, team 1-3)], 'poy': [(name, school)], 'cpoy': [(name, school)]}
(basketball season = the spring year: 2023 = the 2022-23 season)

Joins to board rows go through scripts/names.py (Matcher) in the test scripts."""
import os, re
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
C = os.path.join(ROOT, 'scripts', '.cache', 'mocks_nov23', 'wiki')
SKIP = re.compile(r'award|trophy|football|basketball|team|university|college|conference|player of the year|coach|'
                  r'association|club|news|press|league|division|ncaa|wikipedia|cite|ref', re.I)


def _read(name):
    p = os.path.join(C, name)
    return open(p, encoding='utf-8', errors='replace').read() if os.path.exists(p) else ''


def clean(s):
    s = re.sub(r'<ref[^>]*/>', '', s); s = re.sub(r'<ref.*?</ref>', '', s, flags=re.S)
    s = re.sub(r'\{\{\s*[Ss]ortname\s*\|([^|}]*)\|([^|}]*)[^}]*\}\}', r'\1 \2', s)
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)
    s = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', s)
    s = re.sub(r"'''?|<[^>]+>", '', s)
    return s.replace('&nbsp;', ' ').strip()


def _namey(s):
    s = re.sub(r'^\s*(rowspan|align|style|colspan)[^|]*\|', '', s).strip().strip('*').strip()
    w = s.split()
    return (2 <= len(w) <= 4 and not SKIP.search(s) and all(x[:1].isupper() or x[:1] in "'(" or x.lower() in ('de', 'van', 'la', 'jr.', 'ii', 'iii', 'iv')
            for x in w) and not re.search(r'\d', s)) and s or None


def _section(t, start, stops):
    i = t.find(start)
    if i < 0: return ''
    j = min([k for k in (t.find(s, i + len(start)) for s in stops) if k > 0] or [len(t)])
    return t[i:j]


def football(y):
    t = _read(f'fbs_{y}.txt')
    out = {'heis': [], 'aa': [], 'award': []}
    hs = _section(t, 'Heisman Trophy voting', ['|}'])
    for row in hs.split('|-')[1:]:
        c = [clean(x) for x in re.split(r'\|\||\n\|', row) if x.strip()]
        c = [x for x in c if x]
        if len(c) >= 4 and _namey(c[0]):
            try: pts = int(c[-1].replace(',', ''))
            except ValueError: pts = None
            out['heis'].append((_namey(c[0]), c[1], pts))
    # every national award below the Heisman table, up to the coaches' awards
    i = t.find('Heisman Trophy voting'); i = t.find('|}', i) if i >= 0 else -1
    j = t.find('===Coaches', i) if i >= 0 else -1
    aw = t[i:j if j > 0 else i + 15000] if i >= 0 else ''
    seen = set()
    for ln in aw.split('\n'):
        if re.search(r'campbell|wuerffel|academic|humanitarian|walk-on|holder|joe moore', ln, re.I): continue
        txt = clean(ln)
        if ln.lstrip().startswith('*') and ':' in txt:
            rest = txt.split(':', 1)[1]
            nm = _namey(rest.split(',')[0])
            sch = rest.split(',')[1].strip() if ',' in rest else None
            if nm and nm not in seen: seen.add(nm); out['award'].append((nm, sch))
        else:
            for cell in re.split(r'\|\||^\|', ln):
                nm = _namey(clean(cell))
                if nm and nm not in seen: seen.add(nm); out['award'].append((nm, None))
    a = _read(f'aa_fb_{y}.txt')
    k = a.find('==Offense==')
    for ln in a[k:].split('\n'):
        m = re.match(r"\*\s*'''\[\[(?:[^|\]]*\|)?([^\]]+)\]\]'''\*?\s*,\s*(.*?)(?:<small>|\(|$)", ln)
        if m: out['aa'].append((m.group(1).strip(), clean(m.group(2)).strip(' ,')))
    return out


def _derefs(s):
    s = re.sub(r'<ref[^>]*/>', '', s); s = re.sub(r'<ref.*?</ref>', '', s, flags=re.S)
    for _ in range(3): s = re.sub(r'\{\{(?:[Cc]ite|[Ww]eb)[^{}]*\}\}', '', s)
    return s


def _cells(row):
    return [clean(x).strip() for x in re.split(r'\|\||\n\|', row)]


def basketball(y):
    out = {'aa': [], 'poy': [], 'cpoy': []}
    a = _derefs(_read(f'aa_bb_{y}.txt'))
    # every player on a major selector's first, second or third team: the individual teams table ("By player")
    k = a.find('==Individual All-America teams'); e = a.find('===By team', k)
    for row in a[k:e if e > 0 else None].split('|-')[1:]:
        c = [x for x in _cells(row) if x]
        for ci, x in enumerate(c[:2]):
            nm = _namey(x)
            if nm:
                out['aa'].append((nm, c[ci + 1] if ci + 1 < len(c) else None, None)); break
    t = _derefs(_read(f'mbb_{y}.txt'))
    k = t.find('ajor player of the year'); e = t.find('\n==', k + 30)
    for ln in t[k:e].split('\n'):
        if ':' in clean(ln):
            rest = clean(ln).split(':', 1)[1]
            nm = _namey(rest.split(',')[0].strip(" '"))
            if nm: out['poy'].append((nm, rest.split(',')[1].strip() if ',' in rest else None))
    k = t.find('conference players of the year|'); k2 = t.find('\n|}', k)
    for row in t[k:k2].split('|-')[1:]:
        c = _cells(row)
        c = [x for x in c if x != '']
        if len(c) >= 3:
            for part in re.split(r'<br\s*/?>|\n', c[2]):
                txt = clean(part)
                nm = _namey(txt.split(',')[0])
                if nm: out['cpoy'].append((nm, txt.split(',')[1].strip() if ',' in txt else None))
    return out


if __name__ == '__main__':
    import json, sys
    y = int(sys.argv[2]) if len(sys.argv) > 2 else 2023
    f = football if sys.argv[1:2] == ['fb'] else basketball
    print(json.dumps(f(y), indent=0)[:4000])
