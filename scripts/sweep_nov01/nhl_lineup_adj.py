"""NHL lineup-adjusted rating updates (Nov 1 2026 sweep; the NBA's lk_opp idea, PR #353, never tried in the NHL).
Each game's xG / goals / Elo update is cleaned of how far each side's dressed lineup that night sat from the team's
own season-to-date mean lineup (goals a game, lineup_value()), split half attack, half defence. Variants:
lk in {.5, 1, 1.5} (both sides: in a joint fit that equals each side counting its opponent at its lineup).
Scored as the live fit does: walk-forward logistic on the shipped feats, log loss 2017-23 every game (tune) and
2024-26 (held), and on lined games vs the close."""
import os, sys, json, math
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import nhl_games as N
import harness as H
ROOT = os.path.dirname(HERE)
ELO_PER_GOAL = 105.0   # rv coef .331 a goal vs elo .317 a 100 points

orig_update = N.Model.update

def make_update(lk, mode):
    def update(self, g):
        if g.get('hs') is None or lk == 0:
            return orig_update(self, g)
        h, a = g['h'], g['a']
        if not hasattr(self, '_lb'):
            self._lb = {}
        if getattr(self, '_lbS', None) != g['S']:
            self._lb = {}; self._lbS = g['S']
        dev = {}
        for t in (h, a):
            v = N.lineup_value(g['S'], g['id'], t)
            s = self._lb.get(t)
            dev[t] = (v - s[0] / s[1]) if (v is not None and s and s[1] >= 3) else 0.0
            if v is not None:
                s = s or [0.0, 0]
                self._lb[t] = [s[0] + v, s[1] + 1]
        dh, da = lk * dev[h], lk * dev[a]
        xh_shift, xa_shift = (da - dh) / 2, (dh - da) / 2   # remove both nights' deviations (in a joint fit
        # this is the same as each side counting its opponent at the lineup it dressed)
        x = g.get('x')
        g2 = dict(g)
        if x:
            xh, xa = list(x['h']), list(x['a'])
            for i in (0, 2, 3):
                xh[i] = xh[i] + xh_shift; xa[i] = xa[i] + xa_shift
            g2['x'] = {'h': xh, 'a': xa}
        # Elo: rate the result against lineup-adjusted strengths (shift ratings for this update only)
        e = (dh - da) * ELO_PER_GOAL
        self.elo.r[h] += e / 2; self.elo.r[a] -= e / 2
        orig_update(self, g2)
        self.elo.r[h] -= e / 2; self.elo.r[a] += e / 2
    return update

def run(lk, mode, hist, P, feats):
    N.Model.update = make_update(lk, mode)
    _, rows, _ = N.walk(hist, P)
    S, y, mg, tot, pc, tc, day = N.arrays(rows)
    p_all = N.walk_logit(N.design(rows, [f for f in feats if f != 'mkt']), y, S, N.SCORE_FROM + 1)
    return rows, S, y, pc, day, p_all

if __name__ == '__main__':
    fit = json.load(open(os.path.join(ROOT, 'data', 'nhl_games_fit.json')))
    P, feats = fit['params'], fit['feats']
    hist = N.load_hist()
    base = run(0, 'both', hist, P, feats)
    S, y, pc, day, pb = base[1], base[2], base[3], base[4], base[5]
    tune = (S >= 2017) & (S <= 2023); held = S >= 2024; lined = ~np.isnan(pc)
    lb = H.logloss(pb, y)
    out = {'base': {'tune': float(lb[tune].mean()), 'held': float(lb[held].mean())}}
    lc = H.logloss(np.where(lined, pc, .5), y)
    for lk, mode in ((0.5, 'both'), (1.0, 'both'), (1.5, 'both')):
        r = run(lk, mode, hist, P, feats)
        l = H.logloss(r[5], y)
        rt = H.paired(l[tune], lb[tune], day[tune]); rh = H.paired(l[held], lb[held], day[held])
        # vs close: does the change move the model toward results beyond the close? (lined held games)
        m = held & lined
        rc = H.paired(l[m], lb[m], day[m])
        out[f'{mode}{lk}'] = {'tune_t': round(rt['t'], 2), 'tune_d': round(rt['d'] * 1000, 3), 'held_t': round(rh['t'], 2),
                              'held_d': round(rh['d'] * 1000, 3), 'held_lined_t': round(rc['t'], 2)}
        print(mode, lk, out[f'{mode}{lk}'], flush=True)
    json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nhl_lineup_adj.json'), 'w'), indent=1)
