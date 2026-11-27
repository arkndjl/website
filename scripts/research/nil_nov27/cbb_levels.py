"""Mid- and low-major basketball budget levels against the College Sports Commission's men's basketball revenue-share
percentiles outside the power conferences (school report, payments Jul 1 2025 to Apr 6 2026, all rostered players,
n 3,667: 90th $165,000, 75th $50,000, median $8,500). The board's frozen yNIL (scripts/data/cbb_ynil.json, written at
$1.2M / $0.25M) for every team outside the ACC, Big Ten, Big 12 and SEC (the Ivy and Patriot leagues opted out), a
level change scaling its teams' players, deflated one season (x 1/1.113). Nothing is fit: two candidate pairs."""
import json, math, numpy as np
W = '/home/user/website/'
d = json.load(open(W + 'static/data/cbb-all.json')); ci, ti = d['cols'].index('conf'), d['cols'].index('team')
conf = {r[ti]: r[ci] for r in d['rows']}
bt = json.load(open(W + 'data/nil_budgets.json'))['cbb']['teams']
A4, MM = {'ACC', 'B10', 'B12', 'SEC'}, {'A10', 'MWC', 'WCC', 'Amer', 'MVC', 'P12'}
P = []
for k, v in json.load(open(W + 'scripts/data/cbb_ynil.json'))['ynil'].items():
    t = k.rsplit('|', 1)[1]; c = conf.get(t)
    if c is None or c in A4 or c in ('Ivy', 'Pat'): continue
    P.append(('HM' if (t in bt or c == 'BE') else 'MM' if c in MM else 'LM', v))
CSC = {90: 165000, 75: 50000, 50: 8500}
def score(mm, lm, base=(1.2, .25)):
    v = np.array([x * {'HM': 1, 'MM': mm / base[0], 'LM': lm / base[1]}[L] / 1.113 for L, x in P])
    e = {q: math.log(np.percentile(v, q) / t) for q, t in CSC.items()}
    return round(float(np.sqrt(np.mean(np.square(list(e.values()))))), 3), {q: round(x, 2) for q, x in e.items()}
if __name__ == '__main__':
    # base = the levels the frozen file was written at; pass the current ones when it has been rewritten
    import sys
    base = tuple(float(x) for x in sys.argv[1:3]) if len(sys.argv) > 2 else (1.2, .25)
    for mm, lm in ((1.2, .25), (2.3, .525), (2.3, .25), (1.2, .525), (1.75, .4)):
        print(mm, lm, score(mm, lm, base))
