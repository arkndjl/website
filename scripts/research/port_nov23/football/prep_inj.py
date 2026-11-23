#!/usr/bin/env python3
"""Warm the NFL caches the game-model tests need: games, player-week stats, injury history (nfl_games.injury_history)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nfl_games as N
games, box, qbs = N.load(2025)
N.index_qbs(qbs, games); N.load_qb_teams(2025)
inj = N.injury_history(games, range(N.INJ_FIRST, 2026))
print('done', len(inj))
