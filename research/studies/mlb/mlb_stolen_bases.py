# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Study mlb-stolen-bases: steal success vs break-even, 2021-22 vs 2023-25 (Retrosheet PBP)."""
import importlib.util, numpy as np, pandas as pd, json
spec = importlib.util.spec_from_file_location("c", "/home/user/website/research/studies/mlb/mlb_common.py"); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
d = c.load()
we = c.WE(d)
d = d[d.season >= 2021].copy()
d['pa_id'] = d.groupby('gid').pa.cumsum() - d.pa
d['era'] = np.where(d.season >= 2023, 'new', 'old')
clean_evt = (d.pa == 0) | (d.k == 1)
def outcome(rows, runner_col):
    r = rows[runner_col]
    ok = (rows.br2_post == r) | (rows.br3_post == r) | (rows.run1 == r) | (rows.run2 == r) | (rows.run_b == r)
    return ok.fillna(False).astype(int)
s2 = d[(d.bases == 1) & ((d.sb2 == 1) | (d.cs2 == 1)) & clean_evt & (d.sb3 == 0) & (d.cs3 == 0)].copy()
s2['succ'] = outcome(s2, 'br1_pre'); s2['tgt'] = 2
s3 = d[(d.bases == 2) & ((d.sb3 == 1) | (d.cs3 == 1)) & clean_evt].copy()
s3['succ'] = outcome(s3, 'br2_pre'); s3['tgt'] = 4
att = pd.concat([s2, s3])
RE = {'old': c.re_table(d, [2021, 2022]), 'new': c.re_table(d, [2023, 2024, 2025])}
def re(era, o, b): return 0.0 if o >= 3 else RE[era].loc[(o, b)]
for era in ['old', 'new']:
    for b, tgt in [(1, 2), (2, 4)]:
        print(era, b, [round((re(era,o,b) - re(era,o+1,0)) / (re(era,o,tgt) - re(era,o+1,0)), 3) for o in range(3)])
att['re_val'] = [ (re(e,o,t) if s else re(e,o+1,0)) - re(e,o,b) for e,o,b,t,s in zip(att.era, att.outs_pre, att.bases, att.tgt, att.succ)]
att['be_re'] = [ (re(e,o,b) - re(e,o+1,0)) / (re(e,o,t) - re(e,o+1,0)) for e,o,b,t in zip(att.era, att.outs_pre, att.bases, att.tgt)]
# WE break-even per attempt (batting-team view)
sign = np.where(att.home_bat == 1, 1, -1)
w0 = we.pre(att.inning.values, att.home_bat.values, att.outs_pre.values, att.bases.values, att.diff_home.values, att.ghost.values)
ws = we.pre(att.inning.values, att.home_bat.values, att.outs_pre.values, att.tgt.values, att.diff_home.values, att.ghost.values)
wf = we.post(att.inning.values, att.home_bat.values, att.outs_pre.values + 1, np.zeros(len(att), int), att.diff_home.values, att.season.values)
att['be_we'] = (w0 - wf) / (ws - wf)
att['we_val'] = sign * (np.where(att.succ == 1, ws, wf) - w0)
print(att.groupby(['era', 'tgt']).agg(succ=('succ', 'mean'), n=('succ', 'size'), be_re=('be_re', 'mean'), be_we=('be_we', 'median'), re_val=('re_val', 'mean'), we_val=('we_val', 'mean')))
late = (att.inning >= 7) & (att.diff_home.abs() <= 1)
print(att[late].groupby(['era', 'tgt']).agg(succ=('succ', 'mean'), n=('succ', 'size'), be_we=('be_we', 'mean')))
print(att.groupby(['era','tgt','outs_pre']).agg(succ=('succ','mean'), n=('succ','size'), be=('be_re','mean')).round(3))
# opportunities
for b in [1, 2]:
    op = d[(d.bases == b) & (d.outs_pre < 3)].drop_duplicates(['gid', 'pa_id'])
    o = op.groupby('era').size(); a = att[att.bases == b].groupby('era').succ.agg(['size', 'sum'])
    print(b, o.to_dict(), (a['size'] / o).round(4).to_dict(), (a['sum'] / o).round(4).to_dict())
    m = ((a['sum']/o)['new'] - (a['sum']/o)['old']) / ((a['size']/o)['new'] - (a['size']/o)['old'])
    print('marginal success', round(m, 3))

# ---- per-season check (steal of 2nd, runner on 1st only)
RE_s = {y: c.re_table(d, [y]) for y in range(2021, 2026)}
seas = []
for y in range(2021, 2026):
    a = att[(att.season == y) & (att.tgt == 2)]
    op = d[(d.season == y) & (d.bases == 1)].drop_duplicates(['gid', 'pa_id']).shape[0]
    be = np.mean([(RE_s[y].loc[(o, 1)] - (0 if o == 2 else RE_s[y].loc[(o + 1, 0)])) /
                  (RE_s[y].loc[(o, 2)] - (0 if o == 2 else RE_s[y].loc[(o + 1, 0)])) for o in a.outs_pre])
    seas.append((y, len(a), a.succ.mean(), be, len(a) / op, a.re_val.mean()))
    print(y, len(a), round(a.succ.mean(), 3), round(be, 3), round(len(a) / op, 4), round(a.re_val.mean(), 4))

# ---- JSON
lab = {(2, 0): '2nd, 0 out', (2, 1): '2nd, 1 out', (2, 2): '2nd, 2 out', (4, 0): '3rd, 0 out', (4, 1): '3rd, 1 out', (4, 2): '3rd, 2 out'}
ser = {'old': [], 'new': [], 'be': []}
for (t, o), L in lab.items():
    for era in ['old', 'new']:
        a = att[(att.era == era) & (att.tgt == t) & (att.outs_pre == o)]
        lo, hi = c.wilson(a.succ.sum(), len(a))
        ser[era].append({'x': L, 'y': round(a.succ.mean(), 3), 'lo': round(lo, 3), 'hi': round(hi, 3), 'n': int(len(a))})
    b = 1 if t == 2 else 2
    ser['be'].append({'x': L, 'y': round((re('new', o, b) - re('new', o + 1, 0)) / (re('new', o, t) - re('new', o + 1, 0)), 3),
                      'n': int(((att.era == 'new') & (att.tgt == t) & (att.outs_pre == o)).sum())})
def summ(era, t, o=None):
    a = att[(att.era == era) & (att.tgt == t) & ((att.outs_pre == o) if o is not None else True)]
    lo, hi = c.wilson(a.succ.sum(), len(a))
    m, vlo, vhi = c.cluster_mean_ci(a.re_val, a.gid)
    return a, a.succ.mean(), lo, hi, a.be_re.mean(), m, vlo, vhi
a2n, sn, lon, hin, ben, vn, vnlo, vnhi = summ('new', 2)
a2o, so, loo, hio, beo, vo, volo, vohi = summ('old', 2)
a1, s1, lo1, hi1, be1, _, _, _ = summ('new', 2, 1)
a0, s0, lo0, hi0, be0, _, _, _ = summ('new', 2, 0)
ar_old = att[(att.era == 'old') & (att.tgt == 2)].shape[0] / d[(d.era == 'old') & (d.bases == 1)].drop_duplicates(['gid', 'pa_id']).shape[0]
ar_new = att[(att.era == 'new') & (att.tgt == 2)].shape[0] / d[(d.era == 'new') & (d.bases == 1)].drop_duplicates(['gid', 'pa_id']).shape[0]
n_all = int(len(att))
tsr = att[att.era == 'new'].re_val.sum() / 90
print('runs per team-season', tsr)
res = {
    "id": "mlb-stolen-bases", "sport": "MLB",
    "question": "After the 2023 base and pickoff rules, do runners still steal too little?",
    "answer": f"Slightly. Steals of 2nd succeed {sn:.1%} vs {ben:.1%} break-even, +{tsr:.1f} runs per team-season. At 1 out, no edge.",
    "findings": [
        f"Steal of 2nd: {so:.1%} success 2021-22 (n={len(a2o):,}) to {sn:.1%} 2023-25 (n={len(a2n):,}, CI {lon:.1%}-{hin:.1%}).",
        f"Attempts per PA with runner on 1st only: {ar_old:.1%} to {ar_new:.1%}. Success fell each year: {seas[2][2]:.1%}, {seas[3][2]:.1%}, {seas[4][2]:.1%}.",
        f"Run value per attempt 2023-25: +{vn:.3f} (CI {vnlo:+.3f} to {vnhi:+.3f}); 2021-22: {vo:+.3f} (CI {volo:+.3f} to {vohi:+.3f}).",
        f"1 out: {s1:.1%} vs {be1:.1%} break-even (n={len(a1):,}). 0 out: {s0:.1%} vs {be0:.1%} (n={len(a0):,}).",
    ],
    "method": "Steal attempts from clean states (runner on 1st only, or 2nd only), incl. pickoff-CS and K+CS. Break-even from era RE24 "
              "(innings 1-8). Run value uses the steal outcome only. Average success above break-even does not prove the marginal try pays.",
    "data": f"Retrosheet play-by-play, 2021-2025 regular season, {n_all:,} steal attempts in clean states.",
    "n": n_all, "robust": True, "interest": 3,
    "split_check": "Success above break-even in each season 2023, 2024, 2025 for steals of 2nd; gap shrinks from "
                   f"{seas[2][2]-seas[2][3]:+.1%} to {seas[4][2]-seas[4][3]:+.1%}.",
    "chart": {"type": "bar", "title": "Steal success vs break-even by base and outs",
              "x_label": "base stolen, outs", "y_label": "success %", "y_fmt": "pct", "x_reverse": False, "ref": None, "mark": None,
              "series": [{"name": "2021-22", "points": ser['old']}, {"name": "2023-25", "points": ser['new']},
                         {"name": "break-even 2023-25", "points": ser['be']}]},
}
json.dump(res, open(c.OUT + '/mlb-stolen-bases.json', 'w'), indent=2)
print(json.dumps(res, indent=1)[:3000])
