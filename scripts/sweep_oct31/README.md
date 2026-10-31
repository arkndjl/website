Oct 31 2026 structural sweep (research only, nothing shipped). Walk-forward weights from earlier seasons, t clustered by
day (tennis: tournament). Bar: tune t <= -1.5, held t <= 0, helps vs the close. Results in data/sweep_oct31/.

- hfa.py: team-specific home edge (EB-shrunk home minus road residual) and persistent team bias, on every
  scripts/data/games_wf file (NBA, NFL, CBB, CFB, NHL, soccer). All fail; closest CBB home edge vs model
  (tune -1.42, held -2.33) but vs close +1.39 / -0.43.
- tennis_home.py (+ tn_country.py, tour-level event -> host country / indoor): home country tune -0.67, held +0.99,
  2026 close +0.26; indoor form +0.69 / -0.40. Rebuilds the tennis history cache from /mnt/project-files/tennis.
- soccer_xi.py: starting-XI value (prior-season GAR/90) minus the team's usual XI. Tonight's XI helps the model
  (t -0.88 / -1.01) but not vs the close (+0.21 / -0.05); last match's XI tune -1.48, held +1.30. Needs the Understat
  match cache (/mnt/project-files/soccer/understat_cache.tgz untarred into scripts/.cache/soccer).
