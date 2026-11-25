"""MoneyPuck column swap for the NHL audit: raw, sva (score + venue adjusted 5v5 on-ice xG), fsva (flurry + score +
venue adjusted 5v5 on-ice xG and ixG); off-ice xG scaled by the team's 5v5 adjusted / raw ratio"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nhl_players as P, nhl_data as D

_mp = P.mp_file
def variant(kind):
    def mp(k, S, fresh=False):
        rows = _mp(k, S, fresh)
        if k != 'skaters' or kind == 'raw':
            return rows
        tm = {(D.team(r['team']), r['situation']): r for r in _mp('teams', S)}
        sfx = 'scoreVenueAdjustedxGoals' if kind == 'sva' else 'flurryScoreVenueAdjustedxGoals'
        out = []
        for r in rows:
            r = dict(r)
            if r['situation'] == '5on5':
                t = tm.get((D.team(r['team']), '5on5'))
                for s in ('F', 'A'):
                    raw, adj = float(r[f'OnIce_{s}_xGoals'] or 0), float(r[f'OnIce_{s}_{sfx}'] or 0)
                    tr = float(t[f'xGoals{"For" if s == "F" else "Against"}']) if t else 0
                    ta = float(t[sfx + ('For' if s == 'F' else 'Against')]) if t else 0
                    r[f'OnIce_{s}_xGoals'] = adj
                    r[f'OffIce_{s}_xGoals'] = float(r[f'OffIce_{s}_xGoals'] or 0) * (ta / tr if tr else 1)
            if kind == 'fsva' and r['situation'] == 'all':
                r['I_F_xGoals'] = r['I_F_flurryScoreVenueAdjustedxGoals']
            out.append(r)
        return out
    return mp


