"""NBA questionable players by the injury report's reason (Nov 1 2026 sweep; the NFL practice-status idea's NBA twin).
The official report gives each listed player a reason ("Injury/Illness - Left Ankle; Sprain", "Rest", "Illness",
"Return to Competition Reconditioning", ...). The game model prices a questionable player by games missed in a row
only (fit P: Questionable0-4). Here: P(plays) by reason category x streak bucket, fit on 2019-20..2021-22, scored
(Brier, players with 0 vs >0 minutes) on 2022-23..2025-26 against the shipped table. Reads the PDF texts cached by
scripts/nba_inj_hist.py and the frozen box minutes in scripts/nba_games_hist.json.gz."""
import datetime as dt, gzip, json, os, re, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import nba_espn as E
import nba_games as G
import harness as H
import names as NMOD
ROOT = os.path.dirname(HERE)
TXT = os.path.join(ROOT, 'scripts', '.cache', 'nba', 'injrep')
ABBR = {'NOP': 'NO', 'NYK': 'NY', 'GSW': 'GS', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH', 'PHO': 'PHX', 'BRK': 'BKN'}
ST = r'(Out|Doubtful|Questionable|Probable|Available)'
ROW = re.compile(r'([A-Z][^,\d]{1,40}?, [^\s].{0,40}?)\s{2,}' + ST + r'\b(.*)$')
MATCH = re.compile(r'\b([A-Z]{2,3})@([A-Z]{2,3})\b')

def cat(reason):
    r = re.sub(r'^injury/illness\s*-\s*', '', reason.strip().lower())
    for k, pat in (('rest', r'\brest\b|injury management|load management|schedule'), ('return', r'recondition|return to competition'),
                   ('illness', r'illness|covid|health and safety|protocol|non-covid'), ('personal', r'personal|family|bereavement'),
                   ('sore', r'sore|tight|stiff|fatigue|spasm|discomfort'), ('sprain', r'sprain'), ('strain', r'strain'),
                   ('contusion', r'contusion|bruise'), ('tendon', r'tendin|tendon'), ('glea', r'g league|two-way')):
        if re.search(pat, r):
            return k
    return 'other'

def parse(txt):
    out, cur = {}, None
    lines = txt.splitlines()
    for i, ln in enumerate(lines):
        m = MATCH.search(ln)
        if m:
            cur = (ABBR.get(m.group(1), m.group(1)), ABBR.get(m.group(2), m.group(2)))
        if not cur:
            continue
        mm = ROW.search(ln)
        if not mm:
            continue
        nm, st, tail = mm.group(1), mm.group(2), mm.group(3)
        reason = re.split(r'\s{3,}', tail.strip())[0] if tail.strip() else ''
        if not reason or reason == '-':       # wrapped reason: the lines just above and below
            reason = ' '.join(x.strip() for x in (lines[i - 1] if i else '', lines[i + 1] if i + 1 < len(lines) else '') if not ROW.search(x))
        last, first = [x.strip() for x in nm.split(',', 1)]
        last = re.split(r'\s{2,}', last)[-1]
        out.setdefault(cur, {})[NMOD.key(f'{first} {last}')] = (st, cat(reason))
    return out

hist = json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))
names = hist['names']
P = json.load(open(os.path.join(ROOT, 'data', 'nba_games_fit.json')))['P']
games = sorted([g for g in hist['games'] if g['S'] >= 2020 and g.get('pl')], key=lambda g: g['tip'])
streak = defaultdict(int)
rows = []   # (S, day, cat, bucket, played)
cache = {}
for g in games:
    tip = dt.datetime.fromisoformat(g['tip'].replace('Z', '+00:00')) - dt.timedelta(hours=4)
    d = tip.date().isoformat(); hr = tip.hour + tip.minute / 60
    rep = {}
    for h in ((12, 17) if hr < 17.5 else (17,)):
        fn = os.path.join(TXT, f'{d}_{h:02d}.txt')
        if (d, h) not in cache:
            cache[(d, h)] = parse(open(fn).read()) if os.path.exists(fn) else {}
        if cache[(d, h)]:
            rep = cache[(d, h)]
            if h == 12:
                break
    found = None
    for (a, h_), v in rep.items():
        if (E.team(a), E.team(h_)) == (g['a'], g['h']):
            found = v
    for t in (g['h'], g['a']):
        for pid, mins in g['pl'].get(t, []):
            nm = names.get(pid)
            nm = nm[0] if isinstance(nm, list) else nm
            if found is not None and nm:
                s = found.get(NMOD.key(nm))
                if s and s[0] == 'Questionable':
                    rows.append((g['S'], d, s[1], G.bucket(streak[pid]), float(mins > 0)))
            streak[pid] = 0 if mins > 0 else streak[pid] + 1
print('questionable rows', len(rows))
S = np.array([r[0] for r in rows]); y = np.array([r[4] for r in rows]); days = np.array([r[1] for r in rows])
tune = S <= 2022; held = S >= 2023
base = np.array([P.get(f'Questionable{r[3]}', P['Questionableall']) for r in rows])
cnt = defaultdict(lambda: [0.0, 0])
for r, t in zip(rows, tune):
    if t:
        cnt[r[2]][0] += r[4]; cnt[r[2]][1] += 1
lvl = y[tune].mean()
# category effect as a logit shift on the shipped streak table, shrunk (n0 50)
shift = {}
for c, (a, n) in cnt.items():
    p = (a + 50 * lvl) / (n + 50)
    shift[c] = float(np.log(p / (1 - p)) - np.log(lvl / (1 - lvl)))
newp = np.array([1 / (1 + np.exp(-(np.log(b / (1 - b)) + shift.get(r[2], 0.0)))) for b, r in zip(base, rows)])
out = {'n': {'tune': int(tune.sum()), 'held': int(held.sum())},
       'byCat': {c: {'tune_n': cnt[c][1], 'tune_played': round(cnt[c][0] / max(cnt[c][1], 1), 3),
                     'held_n': int(sum(1 for r, h in zip(rows, held) if h and r[2] == c)),
                     'held_played': round(float(np.mean([r[4] for r, h in zip(rows, held) if h and r[2] == c] or [np.nan])), 3),
                     'shift': round(shift.get(c, 0), 3)} for c in sorted(cnt)}}
for lab, m in (('tune', tune), ('held', held)):
    r = H.paired((y[m] - newp[m]) ** 2, (y[m] - base[m]) ** 2, cluster=days[m])
    out[lab] = {'brier_new': round(float(((y[m] - newp[m]) ** 2).mean()), 4), 'brier_old': round(float(((y[m] - base[m]) ** 2).mean()), 4), 't': round(r['t'], 2)}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nba_inj_reason.json'), 'w'), indent=1)
