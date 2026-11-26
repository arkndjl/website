"""Draft-night pick deals from the parsed notes (parse.py -> picks.json): two-team deals with no players, each side's
current picks, future firsts/seconds and cash. Writes scripts/.cache/nba_trades/deals.json"""
import json, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse as PA
C = PA.C
P = json.load(open(os.path.join(C, 'picks.json')))
TEAMNAMES = set(PA.NICK) | set(PA.T)


sys.path.insert(0, os.path.join(PA.ROOT, 'scripts'))
import names as N
BB = json.load(open(os.path.join(PA.ROOT, 'scripts', 'nba_draft.json')))
NUM = {'two': 2, 'three': 3, 'four': 4, 'a': 1, 'an': 1, 'one': 1}


def pick_of(name, y):
    for r in BB.get(str(y), []):
        if N.same(name, r[2]): return r[0]
    return None


def side_stuff(txt, y):
    t = re.sub(r"''", '', txt)
    t = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', t)            # unlink
    cur = set()
    for m in re.finditer(r'\(No\. ?(\d+)[^)]*\)|No\. ?(\d+) (?:overall )?pick|\b(\d+)(?:st|nd|rd|th) (?:overall )?pick', t):
        cur.add(int(next(g for g in m.groups() if g)))
    t2 = re.sub(r'\(No\. ?\d+[^)]*\)|No\. ?\d+ (?:overall )?pick|\b\d+(?:st|nd|rd|th) (?:overall )?pick', ' ', t)
    for m in re.finditer(r'(?:the )?draft rights to (?:the )?([A-Z][^,;()]*?)(?=,| and |\(|$| from )', t2):
        k = pick_of(m.group(1).strip(), y)
        if k: cur.add(k)
    t3 = re.sub(r'(?:the )?draft rights to (?:the )?[A-Z][^,;()]*?(?=,| and |\(|$| from )', ' ', t2)
    # a current pick named by owner: "Atlanta's first-round pick" with no year, in a deal this draft -> counted via cur
    f1 = f2 = 0
    for m in re.finditer(r'(?:\b(two|three|four|a|an|one)\s+)?([^,;]{0,60}?)\b(first|second)[- ]round', t3):
        pre = m.group(2)
        yrs = [int(x) for x in re.findall(r'20\d\d', pre)]
        if yrs and max(yrs) <= y: continue
        if not yrs and not re.search(r'future|two|three|four', (m.group(1) or '') + pre) and re.search(r"'s?\s*$|' $", pre): continue
        w = re.findall(r'\b(two|three|four)\b', ((m.group(1) or '') + ' ' + pre).lower())
        k = NUM[w[0]] if w else 1
        if m.group(3) == 'first': f1 += k
        else: f2 += k
    cash = bool(re.search(r'cash', t3))
    players = [x.strip() for x in re.findall(r'(?:^|, |and )([A-Z][a-z]+(?: [A-Z][a-zA-Z.\'-]+)+)(?=,| and |$| \()', t3)
               if not any(w in x for w in TEAMNAMES) and not re.search(r'round|pick|cash|rights|Draft', x)]
    return dict(f1=f1, f2=f2, cash=cash, players=players, curText=sorted(cur))


def deals():
    by = collections.defaultdict(list)
    for p in P:
        for n in p['notes']: by[(p['y'], n[:200])].append(p)
    out = []
    for (y, k), picks in by.items():
        note = next(n for n in picks[0]['notes'] if n[:200] == k)
        if re.search(r'(three|four|five|six|seven)-team', note): continue
        bullets = re.findall(r'^\*\s*(.+)$', note, re.M)
        if len(bullets) != 2: continue
        sides = {}
        for b in bullets:
            m = re.match(r'(.+?)\s+acquired\s+(.*)', re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', lambda z: '[[' + z.group(0)[2:-2] + ']]', b))
            if not m: break
            tm = PA.team(m.group(1).replace("''", '').strip())
            if not tm: break
            sides[tm] = side_stuff(m.group(2), y)
        if len(sides) != 2: continue
        A, B = list(sides)
        for t in sides: sides[t]['cur'] = sorted(set(sides[t]['curText']) | {p['pick'] for p in picks if p['acq'] == t and p['holder'] in sides})
        # every pick of this draft that changed hands between the two, even if its own note is elsewhere
        if any(sides[t]['players'] for t in sides): continue
        if not (sides[A]['cur'] or sides[B]['cur']): continue
        out.append(dict(y=y, sides=sides))
    return out


if __name__ == '__main__':
    D = deals()
    print(len(D), 'pure-pick two-team deals')
    for d in D[-25:]: print(d['y'], {t: (s['cur'], s['f1'], s['f2'], s['cash']) for t, s in d['sides'].items()})
    json.dump(D, open(os.path.join(C, 'deals.json'), 'w'))
