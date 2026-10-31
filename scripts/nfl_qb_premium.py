"""QB premium at the top of the NFL draft, for the CFB mock drafts (mockDraftOnce in scripts/cfb_teams.mjs).

    python3 scripts/nfl_qb_premium.py      # run scripts/draft_backtest.py first (DraftTek boards, nflverse picks);
                                           # writes data/cfb_qb_premium.json

Teams draft quarterbacks above their board rank near the top of the draft: 20 of the 27 #1 picks since 2000 were
QBs. Two parts:
  history  nflverse 2000-26: the team at each top-10 slot, its QB need the season before (the rule in
           scripts/draft_sim_backtest.py: main passer outside the top 14 in EPA a play on 250+ attempts, 35 or older
           or under 60% of the attempts, and no first-round QB in the two drafts before) and whether it took a QB
  boards   PFF's dated big boards (fall = the latest Sep-Nov version, 2021-25; winter = Dec-Mar; final = April) and
           DraftTek's final boards (2020-26): each real pick in rounds 1-2 as a choice among the declared players
           still on the board (conditional logit; utility = scale x -ln xPick from BOARD_PICK plus the mock's QB need
           and set-QB block), and the candidate QB terms on top of that, fit leaving one draft out:
             need x top    a QB-needy team's extra pull to a QB near the top, decaying with the slot (exp(-(pick-1)/TAU))
             first QB      the best QB left on the board (scarcity: the league pays for the one it can start)
             qb            a flat QB shift (fall boards underrate or overrate QBs as a group)
           scored on held-out log likelihood of the real picks, on the replayed draft's pick error (each team takes its
           best utility in the real order) and on P(QB at #1).
"""
import os, sys, csv, json, math, datetime, collections, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N
import cfb_draft_pct_backtest as B

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, 'scripts', '.cache', 'draft')
NV = 'https://github.com/nflverse/nflverse-data/releases/download/'
get = lambda out, url: os.path.exists(out) or subprocess.run(['curl', '-sSLf', '-o', out, url])
TF = {'OAK': 'LV', 'LVR': 'LV', 'SD': 'LAC', 'SDG': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'RAM': 'LA', 'PHO': 'ARI', 'SFO': 'SF', 'KAN': 'KC',
      'TAM': 'TB', 'GNB': 'GB', 'NWE': 'NE', 'NOR': 'NO'}   # PFR draft codes to nflverse stats codes
tf = lambda t: TF.get(t, t)
BP = (0.375, 0.880, 0.0132)          # BOARD_PICK (cfb_teams.mjs)
lnx = lambda rk: (lambda l: BP[0] + BP[1] * l + BP[2] * l * l)(math.log(max(1, rk)))
UND = 290

# ---- QB need by team and draft, 2000-26 ---------------------------------------------------------------------
dp = list(csv.DictReader(open(os.path.join(W, 'draft_picks.csv'))))
get(os.path.join(W, 'players.csv'), NV + 'players/players.csv')
born = {r['gsis_id']: r['birth_date'] for r in csv.DictReader(open(os.path.join(W, 'players.csv')))}
def qb_need(Y):
    f = os.path.join(W, f'ps_{Y - 1}.csv'); get(f, NV + f'stats_player/stats_player_reg_{Y - 1}.csv')
    by = collections.defaultdict(list)
    for r in csv.DictReader(open(f)):
        if r['position'] == 'QB': by[tf(r.get('recent_team') or r.get('team') or '')].append(r)
    prim = {}
    for t, L in by.items():
        r = max(L, key=lambda r: int(float(r['attempts'] or 0))); n = lambda k: int(float(r.get(k) or 0))
        bd = born.get(r['player_id']) or ''
        prim[t] = dict(att=n('attempts'), epa=(float(r['passing_epa'] or 0) + float(r['rushing_epa'] or 0)) / max(1, n('attempts') + n('carries') + n('sacks_suffered')),
                       age=Y - int(bd[:4]) if bd[:4].isdigit() else 28, share=n('attempts') / max(1, sum(int(float(x['attempts'] or 0)) for x in L)))
    top = sorted([t for t in prim if prim[t]['att'] >= 250], key=lambda t: -prim[t]['epa'])[:14]
    r1 = {tf(r['team']) for r in dp if r['position'] == 'QB' and r['round'] == '1' and Y - 2 <= int(r['season']) <= Y - 1}
    return {t: 0 if (t in top and p['age'] <= 34 and p['share'] >= 0.6) or t in r1 else 1 for t, p in prim.items()}
NEED = {Y: qb_need(Y) for Y in range(2000, 2027)}
need = lambda Y, t: NEED[Y].get(tf(t), 1)

def history():
    """P(QB) at slots 1-10 by the picking team's QB need, 2000-26 (and 2011-26, the rookie wage scale)."""
    out = {}
    for lab, ys in (('2000-26', range(2000, 2027)), ('2011-26', range(2011, 2027))):
        c = collections.defaultdict(lambda: [0, 0])
        for r in dp:
            Y, pk = int(r['season']), int(r['pick'])
            if Y in ys and pk <= 10:
                band = '1' if pk == 1 else '2-3' if pk <= 3 else '4-10'
                c[(band, need(Y, r['team']))][0] += r['position'] == 'QB'; c[(band, need(Y, r['team']))][1] += 1
        out[lab] = {f'{b} need {n}': [q, t, round(q / t, 3) if t else None] for (b, n), (q, t) in sorted(c.items())}
    ones = {int(r['season']): [r['position'], tf(r['team']), need(int(r['season']), r['team'])] for r in dp if r['pick'] == '1' and int(r['season']) >= 2000}
    return out, ones

# ---- boards ---------------------------------------------------------------------------------------------------
picks = collections.defaultdict(list)
for r in dp:
    if int(r['season']) >= 2020: picks[int(r['season'])].append(r)
def match(y, name, qb):
    c = [r for r in picks[y] if N.key(r['pfr_player_name']) == N.key(name)] or [r for r in picks[y] if N.same(r['pfr_player_name'], name)]
    if len(c) > 1: c = [r for r in c if (r['position'] == 'QB') == qb]
    return c[0] if len(c) == 1 else None
dtb = json.load(open(os.path.join(W, 'boards.json')))
final_dt = collections.defaultdict(list)
for b in dtb: final_dt[b['year']].append(b)
DT26 = os.path.join(W, 'dt26.json')
def boards():
    """{(label, draft): [(rank, name, isQB, declared, pickRow)]}: PFF fall/winter/final and DraftTek final."""
    out = {}
    raw = B.pff_boards(); latest = {}
    for y, v, date, P in raw:
        days = (datetime.date.fromisoformat(B.DRAFT_DAY[y]) - datetime.date.fromisoformat(date)).days
        lab = 'fall' if 140 <= days <= 240 else 'winter' if 50 <= days < 140 else 'final' if days <= 30 else None
        if lab and ((lab, y) not in latest or days < latest[(lab, y)][0]): latest[(lab, y)] = (days, P)
    dtnames = {y: [b['name'] for b in L] for y, L in final_dt.items()}
    for (lab, y), (days, P) in latest.items():
        L = []
        for p in P:
            if not p.get('pff_rank'): continue
            qb = p['position'] == 'QB'; m = match(y, p['name'], qb)
            dec = m is not None or any(N.same(p['name'], n) for n in dtnames.get(y, []))
            L.append((p['pff_rank'], p['name'], qb, dec, m))
        out[('pff ' + lab, y)] = (days, L)
    for y, Lb in final_dt.items():
        out[('drafttek final', y)] = (0, [(b['rank'], b['name'], b['pos'] == 'QB', True, match(y, b['name'], b['pos'] == 'QB')) for b in Lb])
    return out

TAU = 4.0
FEATS = ['need x top', 'first QB', 'qb']
def states(L, y, maxpick=64):
    """Each real pick 1..maxpick: (pick, team need, chosen index or None, [(lnx, isQB, firstQB)] of the declared players left)."""
    pool = [(lnx(r), qb, m and int(m['pick']), n) for r, n, qb, dec, m in L if dec and r <= 300]
    pool.sort(key=lambda p: p[0])
    order = sorted([(int(r['pick']), tf(r['team'])) for r in picks[y] if int(r['pick']) <= maxpick])
    S = []; gone = set()
    for pk, t in order:
        avail = [i for i, p in enumerate(pool) if not (p[2] and p[2] < pk)]
        ch = next((i for i in avail if pool[i][2] == pk), None)
        fq = next((i for i in avail if pool[i][1]), None)
        S.append(dict(pick=pk, team=t, need=need(y, t), ch=ch, idx=avail, X=[(pool[i][0], pool[i][1], i == fq) for i in avail]))
    return S, pool

def fmat(s, feats):
    """Feature columns of the players left at state s: -lnx plus the mock's QB need / set-QB block (one column,
    weight tied to the board), then the candidate QB terms."""
    lx = np.array([x[0] for x in s['X']]); q = np.array([x[1] for x in s['X']], float); f = np.array([x[2] for x in s['X']], float)
    cols = [-lx + q * (BASE['needw'] * (s['need'] - 0.5) - (0 if s['need'] or s['pick'] > 96 else BASE['block']))]
    if 'need x top' in feats: cols.append(q * s['need'] * math.exp(-(s['pick'] - 1) / TAU))
    if 'first QB' in feats: cols.append(f * s['need'])
    if 'qb' in feats: cols.append(q)
    return np.stack(cols, 1)
BASE = dict(needw=0.45, block=0.8)       # the mock now (NEED_W, QB_BLOCK_LN)
RIDGE = 1.0                              # on the QB terms (logit units)
def util(s, th, feats):
    """th: utilities in log-pick units ([scale, QB terms...]); returns logit utilities."""
    F = fmat(s, feats); return th[0] * (F[:, 0] + F[:, 1:] @ np.array(th[1:])) if len(th) > 1 else th[0] * F[:, 0]
def chosen_pos(s): return s['idx'].index(s['ch'])
def fit(SS, feats, maxpick=32):
    """Conditional logit, linear in b = (a, a x th): Newton steps. Returns th = (a, b1/a, ...)."""
    D = [(fmat(s, feats), chosen_pos(s)) for s in SS if s['ch'] is not None and s['pick'] <= maxpick]
    k = 1 + len(feats); b = np.zeros(k); b[0] = 2.5; R = np.diag([0.0] + [RIDGE] * len(feats))
    for _ in range(50):
        g = -R @ b; H = -R.copy()
        for F, c in D:
            u = F @ b; e = np.exp(u - u.max()); p = e / e.sum(); m = p @ F
            g += F[c] - m; H -= (F * p[:, None]).T @ F - np.outer(m, m)
        step = np.linalg.solve(H, g); b -= step
        if np.abs(step).max() < 1e-7: break
    return [b[0]] + list(b[1:] / b[0])
def loglik(th, SS, feats, maxpick=32, each=None):
    t = 0.0
    for s in SS:
        if s['ch'] is None or s['pick'] > maxpick: continue
        u = util(s, th, feats); m = u.max(); v = u[chosen_pos(s)] - m - math.log(np.exp(u - m).sum()); t += v
        if each is not None: each.append(v)
    return t

def replay(pool, y, th, feats, maxpick=100):
    """Draft in the real order: each team takes its best utility (no noise); returns {pool index: pick}."""
    order = sorted([(int(r['pick']), tf(r['team'])) for r in picks[y] if int(r['pick']) <= maxpick])
    taken = {}; avail = list(range(len(pool))); tq = collections.Counter()
    for pk, t in order:
        if not avail: break
        fq = next((i for i in avail if pool[i][1]), None)
        s = dict(pick=pk, need=need(y, t) if not tq[t] else 0, X=[(pool[i][0], pool[i][1], i == fq) for i in avail])
        u = util(s, th, feats)
        for j, i in enumerate(avail):
            if pool[i][1] and tq[t]: u[j] -= 3          # a second QB (QB_DUP_LN-ish)
        j = int(np.argmax(u)); i = avail.pop(j); taken[i] = pk
        if pool[i][1]: tq[t] += 1
    return taken
def p_first(s, th, feats):
    u = util(s, th, feats); e = np.exp(u - u.max()); e /= e.sum()
    return float(sum(e[j] for j, x in enumerate(s['X']) if x[1]))

EACH = {}
def main():
    global TAU
    hist, ones = history()
    BD = boards()
    res = {'_readme': __doc__.strip().split('\n\n')[0], 'history': hist, 'firstPicks': ones, 'tau': TAU, 'boards': {}}
    variants = {'mock now': [], 'need x top': ['need x top'], 'first QB': ['first QB'], 'need x top + first QB': ['need x top', 'first QB'],
                'qb': ['qb'], 'all three': ['need x top', 'first QB', 'qb']}
    for lab in ('pff fall', 'pff winter', 'pff final', 'drafttek final'):
        ys = sorted(y for (l, y) in BD if l == lab)
        data = {y: states(BD[(lab, y)][1], y) for y in ys}
        R = {}
        for vn, feats in variants.items():
            ll = []; e32 = []; e100 = []; p1 = []; lt10 = []; folds = {}; each = []
            for y in ys:
                tr = [s for yy in ys if yy != y for s in data[yy][0]]
                th = fit(tr, feats)
                S, pool = data[y]
                te = [s for s in S if s['ch'] is not None and s['pick'] <= 32]
                lly = loglik(th, te, feats, each=each)
                ll.append(lly); folds[y] = round(lly / max(1, len(te)), 4)
                tk = replay(pool, y, th, feats)
                for i, p in enumerate(pool):
                    if p[2] and p[2] <= 100:
                        err = abs(p[2] - tk.get(i, UND)); e100.append(err)
                        if p[2] <= 32: e32.append(err)
                        if p[2] <= 10: lt10.append(abs(math.log(p[2]) - math.log(tk.get(i, UND))))
                s1 = S[0]; pq = p_first(s1, th, feats)
                isq = s1['ch'] is not None and pool[s1['ch']][1]
                p1.append((y, round(pq, 3), bool(isq)))
            EACH[(lab, vn)] = each
            n32 = sum(1 for y in ys for s in data[y][0] if s['ch'] is not None and s['pick'] <= 32)
            d = np.array(each) - np.array(EACH[(lab, 'mock now')]); br = lambda L: round(float(np.mean([(p - q) ** 2 for _, p, q in L])), 4)
            R[vn] = dict(t=round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if d.std() > 0 else None,
                         foldsBetter=sum(folds[y] > R['mock now']['folds'][y] for y in ys) if vn != 'mock now' else None, brierQb1=br(p1), ll32=round(sum(ll) / n32, 4), folds=folds, mae32=round(float(np.mean(e32)), 2), mae100=round(float(np.mean(e100)), 2),
                         lnTop10=round(float(np.mean(lt10)), 3), qbAt1=p1, theta=[round(float(x), 3) for x in fit([s for y in ys for s in data[y][0]], feats)])
            print(lab, vn, json.dumps(R[vn], default=float))
        tg = {}
        for tau in (2.0, 4.0, 8.0, 16.0):
            TAU = tau; ll = []
            for y in ys:
                th = fit([s for yy in ys if yy != y for s in data[yy][0]], ['need x top'])
                ll.append(loglik(th, [s for s in data[y][0] if s['ch'] is not None and s['pick'] <= 32], ['need x top']))
            tg[tau] = round(sum(ll) / n32, 4)
        TAU = 4.0
        print(lab, 'tau', tg)
        res['boards'][lab] = dict(drafts=ys, days=[BD[(lab, y)][0] for y in ys], n32=n32, tauGrid=tg, variants=R)
    json.dump(res, open(os.path.join(ROOT, "data", "cfb_qb_premium.json"), "w"), indent=1, default=float)

if __name__ == '__main__':
    main()
