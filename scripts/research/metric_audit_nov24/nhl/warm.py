"""warm the NHL caches (MoneyPuck season summaries, stats-API games + regular-season logs), seasons 2008..2026 only"""
import os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nhl_players as P, nhl_data as D
def one(S):
    for k in ('skaters', 'goalies', 'teams'): P.mp_file(k, S)
    D.games(S)
    if S >= 2009: P.team_split(S)
    print('ok', S, flush=True)
with ThreadPoolExecutor(6) as ex: list(ex.map(one, range(2008, 2027)))
