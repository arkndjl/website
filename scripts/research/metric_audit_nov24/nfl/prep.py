#!/usr/bin/env python3
"""Replay the NFL WAR board for 2016-25 (full season and weeks 1-9) and keep what the audit harness needs:
player-team-side rows (AV, AV WAR, share on a 17-game scale), the XV stat-line rows (so XV can be rebuilt on weights fit
without the scored seasons), special teams credit, the board rows, and team points by week.
    python3 scripts/research/metric_audit_nov24/nfl/prep.py [years]      -> scripts/.cache/nfl/audit_<y>_<full|h1>.json
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nfl_war as W, nfl_xv as X, nfl_st_war as STW  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
HALF = 10      # first half = weeks before 10
CAP = {}


def _wrap():
    tr, bx, sv = W.team_rows, X.board_xv, STW.values

    def team_rows(sd, b, ros):
        out = tr(sd, b, ros)
        lines, value, spread = W.sub_lines()
        CAP['rows'] = [{'pfr': o['pfr'], 't': o['t'], 'g': o['g'], 'sub': o['sub'], 'side': o['side'], 'snaps': o['snaps'],
                        'av': o['av'], 'sh': o['share'] * sd['team'][o['t']]['g'] / 17,
                        'war': W.war_of(o['av'], o['share'] * sd['team'][o['t']]['g'] / 17, o['sub'], lines, value, spread)}
                       for o in out]
        CAP['teams'] = {t: {'g': v['g'], 'pf': v['pf'], 'pa': v['pa']} for t, v in sd['team'].items()}
        return out

    def board_xv(y, sd, ros, b, fresh=False, rows_out=None, sides=None):
        ro = [] if rows_out is None else rows_out
        r = bx(y, sd, ros, b, fresh, ro, sides)
        CAP['xrows'] = [{k: p[k] for k in ('pfr', 't', 'sub', 'g', 'share', 'sh', 'snaps', 'c')} for p in ro]
        return r

    def values(y, thru=None):
        v = sv(y, thru)
        CAP['st'] = {gs: {'pts': x['pts'], 't': dict(x['t']), 'g': x.get('g', 0)} for gs, x in v.items()}
        return v
    W.team_rows, X.board_xv, STW.values = team_rows, board_xv, values


def run(y, thru):
    CAP.clear()
    out, _, alpha = W.board(y, thru=thru)
    keep = ('id', 't', 'tm', 'pos', '_g', '_sub', 'sn', 'sh', 'war', 'wav', 'xv', 'stw', 'waa', '_avg', '_tg', 'g', 'two', 'ax', 'n')
    d = {'y': y, 'thru': thru, 'alpha': alpha, 'board': [{k: p.get(k) for k in keep} for p in out], **CAP}
    ros, _ = W.rosters(y)
    d['gsis'] = {pfr: r.get('gsis_id', '') for pfr, r in ros.items() if r.get('gsis_id')}
    with open(os.path.join(CACHE, f'audit_{y}_{"full" if thru is None else "h1"}.json'), 'w') as f:
        json.dump(d, f, separators=(',', ':'))
    print(y, thru, len(out), len(d.get('rows', [])), len(d.get('xrows', [])), len(d.get('st', {})), flush=True)


if __name__ == '__main__':
    _wrap()
    ys = [int(a) for a in sys.argv[1:]] or list(range(2016, 2026))
    for y in ys:
        run(y, None)
        run(y, HALF)
