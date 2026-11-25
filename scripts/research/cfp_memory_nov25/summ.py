import json, math, numpy as np, sys
r = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'sim.json'))['rows']
M = ['nomem', 'live', 'linwl', 'new']
def t(x):
    x = np.array(x, float); return round(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))), 2) if len(x) > 1 and x.std() > 0 else 0
for part in ('tune', 'hold', 'all'):
    for wl in (5, 4, 3, 2, 1, 'all'):
        rr = [x for x in r if (part == 'all' or x['part'] == part) and (wl == 'all' or x['wl'] == wl)]
        line = f'{part:4s} wl{wl!s:3s} n{len(rr):2d} '
        for m in M:
            line += f"{m}: ex {np.mean([x[m]['exact'] for x in rr]):.2f} fd {np.mean([x[m]['field'] for x in rr]):.2f} sLL {np.mean([v for x in rr for v in x[m]['seedLL']]):.3f} fLL {np.mean([v for x in rr for v in x[m]['fieldLL']]):.4f} | "
        line += f"today ex {np.mean([x['today']['exact'] for x in rr]):.2f} fd {np.mean([x['today']['field'] for x in rr]):.2f}"
        dS = [a - b for x in rr for a, b in zip(x['live']['seedLL'], x['new']['seedLL'])]
        dF = [a - b for x in rr for a, b in zip(x['live']['fieldLL'], x['new']['fieldLL'])]
        dE = [x['new']['exact'] - x['live']['exact'] for x in rr]
        dT = [x['new']['exact'] - x['today']['exact'] for x in rr]
        print(line); print(f'      new vs live: t seedLL {t(dS)} fieldLL {t(dF)} exact {t(dE)} | new vs today exact t {t(dT)}')
