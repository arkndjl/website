#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Per-draw season simulation output for the private TLS feed (ops/tls-feed, scripts/tls_upload.py).

The season sims (nfl_games.py, nba_games_build.py, cbb_games_live.py; cfb_model.mjs has its own copy) average their
draws into the odds on the site. With ARK_DRAWS=1 in the environment they also keep every draw here, and the file
goes to the private feed, never to git: scripts/.cache/draws/<sport>.json.gz.

File: gzip JSON {sport, season, asof, sims, teams: [id, ...], fields: {name: meaning}, draws: {name: [[value per team]
per draw]}}. Team order is `teams`; draw k of every field comes from the same simulated season.
"""
import datetime as dt
import gzip
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'scripts', '.cache', 'draws')


def on():
    return os.environ.get('ARK_DRAWS') == '1'


class Draws:
    """Collects one row per simulated season. A disabled collector (ARK_DRAWS unset) does nothing."""

    def __init__(self, sport, season, teams, fields):
        self.sport, self.season, self.teams, self.fields = sport, season, list(teams), dict(fields)
        self.on = on()
        self.rows = {f: [] for f in self.fields}

    def add(self, **cols):
        """cols: field -> {team: value} (missing teams get 0) or a list in team order."""
        if not self.on:
            return
        for f in self.fields:
            v = cols.get(f, {})
            self.rows[f].append(list(v) if isinstance(v, (list, tuple)) else [v.get(t, 0) for t in self.teams])

    def write(self):
        if not self.on or not any(self.rows.values()):
            return None
        os.makedirs(DIR, exist_ok=True)
        n = len(next(iter(self.rows.values())))
        out = {'sport': self.sport, 'season': self.season,
               'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'sims': n,
               'teams': self.teams, 'fields': self.fields, 'draws': self.rows}
        path = os.path.join(DIR, f'{self.sport}.json.gz')
        with gzip.open(path, 'wt', encoding='utf-8', compresslevel=6) as f:
            json.dump(out, f, separators=(',', ':'))
        print(f'{self.sport} draws: {n} sims x {len(self.teams)} teams -> {os.path.relpath(path, ROOT)} '
              f'({os.path.getsize(path) / 1e6:.2f} MB)', flush=True)
        return path
