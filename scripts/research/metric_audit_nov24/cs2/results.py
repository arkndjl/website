#!/usr/bin/env python3
"""Collects harness.json, candidates.json, team.json -> results.json (CS2 metric audit, Nov 24 2026)."""
import json
from pathlib import Path
H = Path(__file__).parent
h, c, t = (json.loads((H / f).read_text()) for f in ('harness.json', 'candidates.json', 'team.json'))
out = {'sport': 'cs2', 'lockbox': 'maps and series before 2026-11-11 only; months 2024-07..2026-10',
       'prereg_sha256': 'd3515dc6405a998c0567e5ff8bd0caa0c91872ebe295f8516f5e62ef2050e947',
       'player': {k: {a: b for a, b in v.items() if 'ByMonth' not in a} for k, v in h['metrics'].items()},
       'playerPairs': len(h['pairs']), 'mapsDescribe': h['nMapsDescribe'], 'mapsPredict': h['nMapsPredict'], 'vsOurs': h['vsOurs'],
       'team': t, 'candidates': c,
       'bestPredictive': {'player': 'RWA rating', 'team': 'ARK Ranking live blend (still best with duplicates dropped)'},
       'bestDescriptive': {'player in sample': 'season RWA', 'player held out': 'RWA rating .151 vs season RWA with D4 .147 (intervals overlap)',
                           'team': 'ARK player Elo at month end'},
       'passed': ['P2 player x map offsets (kmap 1000)', 'D4 season RWA shrunk toward the window start rating (k 400)'],
       'esea_existing': 'data/esea_rwa_fit.json held S58-S59: ESEA RWA ll .6216 vs player Elo .6317 vs 1NT ARK .6683 (not rescored here)'}
(H / 'results.json').write_text(json.dumps(out, indent=1))
