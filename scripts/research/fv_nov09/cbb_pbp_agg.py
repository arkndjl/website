# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026, tests C1-C4 (research only): ESPN play-by-play (hoopR release files) -> per player-season
unassisted rim makes, unassisted threes and assisted share, joined to the Barttorvik careers.

    python3 scripts/cbb_careers_kit.py
    python3 scripts/research/fv_nov09/cbb_pbp_agg.py [pbp dir, default /tmp/pbp]   # -> scripts/.cache/cbb/pbp_shots.json

Per season file (play_by_play_{Y}.parquet saved as p{Y}.parquet; Y = season end year, Barttorvik's year):
  made field goals = scoring_play and score_value >= 2, with a shooter id and a team id
  rim    = type_text holds layup / dunk / tip (LayupShot, LayUpShot, DunkShot, TipShot)
  three  = score_value == 3 (2020 files type some threes as JumpShot)
  assisted = text holds "Assisted by"
  covered team-game = the team has 10+ made field goals in the file and at least one is assisted (2008: 30% of
    team-games carry no assists at all; those are untracked, not unassisted)
Only makes in covered team-games count. Join: ESPN team id -> Barttorvik team through cbb_games.bt_map (the possessions
join; 2014+ games, ids are stable), else the ESPN school name against the Barttorvik name by names.same_team; players by
names.Matcher on that season's Barttorvik rows, the team must agree (cross_team='none').
Output rows: {pid, year, fgm, ast, uarim, ua3, rimm, tpm, cg (covered team games), tg (team games, Barttorvik: the most
any player on the team played)}."""
import json, os, sys
from collections import defaultdict, Counter
import pyarrow.parquet as pq
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_data as D
import cbb_games as G
import names as N

PBP = next((a for a in sys.argv[1:] if not a.startswith('-')), '/tmp/pbp')
OUT = os.path.join(D.CACHE, 'pbp_shots.json')
COLS = ['type_text', 'text', 'scoring_play', 'score_value', 'team_id', 'athlete_id_1', 'athlete_name_1', 'game_id',
        'home_team_id', 'away_team_id', 'home_team_name', 'away_team_name']


def bt_ids():
    m = defaultdict(Counter)
    for g in G.load_hist():
        if 'hb' in g:
            m[str(g['home'])][g['hb']] += 1; m[str(g['away'])][g['ab']] += 1
    return {t: c.most_common(1)[0][0] for t, c in m.items() if sum(c.values()) >= 3}


def season(y, BT, bt_rows, tg):
    t = pq.read_table(os.path.join(PBP, f'p{y}.parquet'), columns=COLS).to_pandas()
    ngames = t.game_id.nunique()
    ename = {}
    for a, b in (('home_team_id', 'home_team_name'), ('away_team_id', 'away_team_name')):
        for i, n in t[[a, b]].drop_duplicates().itertuples(index=False):
            if i == i and n: ename[str(int(i))] = n
    mk = t[(t.scoring_play == True) & (t.score_value >= 2) & t.team_id.notna() & t.athlete_id_1.notna()].copy()
    mk['team'] = mk.team_id.astype(int).astype(str)
    mk['pl'] = mk.athlete_id_1.astype(int).astype(str)
    txt = mk.text.fillna('')
    mk['ast'] = txt.str.contains('Assisted by', case=False)
    mk['rim'] = mk.type_text.fillna('').str.lower().str.contains('layup|dunk|tip')
    mk['three'] = mk.score_value == 3
    # the shooter's name: the file's column, else the words before " made " in the text
    nm = mk.athlete_name_1.where(mk.athlete_name_1.notna(), txt.str.extract(r'^(.*?)\s+made\s', expand=False))
    mk['nm'] = nm
    tgm = mk.groupby(['game_id', 'team']).agg(n=('ast', 'size'), a=('ast', 'sum'))
    cov = tgm[(tgm.n >= 10) & (tgm.a >= 1)]
    cg = cov.reset_index().groupby('team').size().to_dict()
    mk = mk.merge(cov.reset_index()[['game_id', 'team']], on=['game_id', 'team'])
    mk['uarim'] = mk.rim & ~mk.ast; mk['ua3'] = mk.three & ~mk.ast
    mk['rimm'] = mk.rim; mk['tpm'] = mk.three
    agg = mk.groupby(['team', 'pl']).agg(fgm=('ast', 'size'), ast=('ast', 'sum'), uarim=('uarim', 'sum'), ua3=('ua3', 'sum'),
                                         rimm=('rimm', 'sum'), tpm=('tpm', 'sum'),
                                         nm=('nm', lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None)).reset_index()
    M = N.Matcher(bt_rows, name='name', team='team', pos=None, sport='basketball', team_eq=lambda a, b: a == b or N.same_team(a, b))
    out = {}; st = Counter()
    for r in agg.itertuples(index=False):
        team = BT.get(r.team) or ename.get(r.team)
        if not r.nm or not team: st['no name/team'] += 1; continue
        if r.team not in BT: st['team by name'] += 1
        row, how = M.find(r.nm, team=team, cross_team='none')
        if not row:
            st['unmatched'] += 1; st['unmatched fgm'] += int(r.fgm); continue
        st[how] += 1; st['matched fgm'] += int(r.fgm)
        btteam = row['team']
        o = out.setdefault(row['pid'], {'pid': row['pid'], 'year': y, 'fgm': 0, 'ast': 0, 'uarim': 0, 'ua3': 0, 'rimm': 0, 'tpm': 0,
                                        'cg': cg.get(r.team, 0), 'tg': tg.get((btteam, y), 0)})
        for k in ('fgm', 'ast', 'uarim', 'ua3', 'rimm', 'tpm'): o[k] += int(getattr(r, k))
        o['cg'] = max(o['cg'], cg.get(r.team, 0))
    print(y, 'games', ngames, 'covered team-games', len(cov), 'of', len(tgm), 'players', len(agg), dict(st)); sys.stdout.flush()
    return list(out.values()), {'games': int(ngames), 'team_games': int(len(tgm)), 'covered_team_games': int(len(cov)), 'pbp_players': int(len(agg)),
                                **{k: int(v) for k, v in st.items()}}


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    BT = bt_ids()
    by = defaultdict(list); tg = defaultdict(float)
    for c in careers:
        for s in c['seasons']:
            by[s['year']].append({'pid': c['pid'], 'name': s.get('name') or c['name'], 'team': s['team']})
            tg[(s['team'], s['year'])] = max(tg[(s['team'], s['year'])], s['gp'] or 0)
    rows, meta = [], {}
    for y in range(2008, 2021):
        if not os.path.exists(os.path.join(PBP, f'p{y}.parquet')): print(y, 'no file'); continue
        r, m = season(y, BT, by[y], tg)
        rows += r; meta[y] = m
    json.dump({'rows': rows, 'meta': meta}, open(OUT, 'w'))
    print(len(rows), 'player-seasons ->', OUT)


if __name__ == '__main__':
    main()
