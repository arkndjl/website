# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S1 (descriptive): the CFB season sim's P(in the playoff field) at weeks 6, 9 and 12 of 2025 vs the Polymarket
(global) make-the-playoff prices on the same dates. Committee coefficients = the 2017-21 fit (betaTune).
    python3 s1_cfp_vs_market.py <out.json>"""
import datetime as dt, json, math, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cfb_cfp as C, names as NM, poly_hist as PH


def main(outfn):
    hist, polls, wf = C.load()
    games = {int(S): g for S, g in hist['games'].items()}
    by_id = {str(g['id']): g for S in games for g in games[S]}
    wfr = C.wf_rows(wf, by_id)
    info = {S: C.season_info(games[S], S) for S in games}
    S = 2025
    rs = sorted([r for r in polls['releases'] if r['poll'] == 'cfp' and r['S'] == S], key=lambda r: r['date'])
    fr = C.release_rows(S, rs[-1], info[S], wfr, True)
    fit = json.load(open(C.OUT))
    cols = [C.FEATS_ALL.index(f) for f in fit['feats']]; beta = np.array(fit['betaTune'])
    name = {}
    for g in games[S]:
        name[str(g['homeId'])] = g.get('homeTeam'); name[str(g['awayId'])] = g.get('awayTeam')
    ev = PH.load('cfb', 'playoff', S)
    mkey = {NM.team_key(m['name']): m['name'] for m in ev['markets']}
    af = C.actual_field(fr)
    rng = np.random.default_rng(7)
    out = []
    for wk in (6, 9, 12):
        D = C.sim_draws(S, wk, fr, info, wfr, rng)
        teams, T, N, champ, feats = D['teams'], D['T'], D['N'], D['champ'], D['feats']
        snew = sum(beta[k] * feats[C.FEATS_ALL[c]] for k, c in enumerate(cols))
        pn = np.zeros(T); gum = rng.gumbel(size=(N, T))
        for n in range(N): pn[C.pick12(np.argsort(-(snew[n] + gum[n])), champ[n].astype(bool))] += 1
        pn /= N
        last = max(str(g['startDate'])[:10] for g in games[S] if g['seasonType'] == 'regular' and g['week'] <= wk)
        day = (dt.date.fromisoformat(last) + dt.timedelta(days=2)).isoformat()     # the week's last games are in the sim's inputs
        px = PH.asof(ev, day)
        if not PH.liquid(px, 12):
            out.append({'S': S, 'wk': wk, 'day': day, 'illiquid': round(sum(px.values()), 2)}); print(out[-1]); continue
        bm = bk = lm = lk = 0.0; n = 0
        cl = lambda v: min(max(v, 1e-3), 1 - 1e-3)
        for i, t in enumerate(teams):
            k = mkey.get(NM.team_key(name.get(t) or ''))
            if not k or k not in px: continue
            y = 1.0 if i in af else 0.0
            p, q = float(pn[i]), px[k]
            bm += (p - y) ** 2; bk += (q - y) ** 2; n += 1
            lm += -math.log(cl(p) if y else 1 - cl(p)); lk += -math.log(cl(q) if y else 1 - cl(q))
        r = {'S': S, 'wk': wk, 'day': day, 'teams': n, 'brier_model': round(bm / max(n, 1), 5), 'brier_market': round(bk / max(n, 1), 5),
             'll_model': round(lm / max(n, 1), 4), 'll_market': round(lk / max(n, 1), 4)}
        out.append(r); print(r, flush=True)
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1])
