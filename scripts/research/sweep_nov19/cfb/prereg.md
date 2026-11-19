# CFB sweep leads: pre-registration (written before any scoring; Nov 19 2026)

Worker: cfb. Leads 1, 3, 5, 6, 7, 8, 9, 10, 11, 12 of /mnt/project-files/research-sweep-nov19/cfb.md.
Lockbox: no 2026 CFB game from week 11 on is read by any test. Zero CFBD API calls.
Environment fact fixed before the specs: the container has no scripts/.cache (the cfbhist / cfb Actions caches and the
7-day cfb-research artifact are not reachable; the last artifact expired). Each spec below names the reference it uses instead.

Common pass rule (predictive leads): paired t clustered at the stated unit >= 2 in the right direction on the held
split, tune and held share sign, majority of held seasons/folds same sign, Holm within family P (all predictive tests
actually run: 3, 5, 6, 7a, 7b, 9, 11, 12). Parity/coverage leads (1, 8, 10) pass on the stated tolerance, no Holm.
No retune after held is seen; no rescue tests.

## 1. Board off CFBD via sportsdataverse mirrors (parity)
- Mirror: cfbfastR_cfb_pbp/play_by_play_2026.parquet, weeks 1-10 only (week filter applied on load).
- Reference (CFBD-built): the board files committed by the cfb-board run of 2026-11-10 11:12Z (commit 4993af3c), which was
  built from CFBD pulls after week 10 finished and before week 11 kicked off (teams file says weeks 10, 685 games).
- 1a plays feed -> player lines. Mirror plays, mapped to the slim shape, through the unchanged scripts/cfb_pbp.mjs
  (pbpByGame/pbpPlayers). Rebuild the report strings fetch_cfb writes: RB with 20+ carries "EPA/carry x.xx; 15+ yd n%; n TD
  (n RZ car)"; WR/TE with 12+ targets "20+ yd catch n% of tgt; n TD (n RZ tgt)". Rows = FBS players whose reference
  report carries the string. Pass = string identical for >= 99% of rows (EPA within .01 counted as identical: rounding).
- 1b plays feed -> team season style (stands in for stats/season/advanced: "own numbers from plays"). From mirror plays:
  run rate, offensive and defensive success rate, PPA a play, explosiveness, with CFBD's garbage-time rule. Reference =
  teams[].style in the Nov 10 cfb_teams.json (2 dp). Pass per field = |diff| <= .01 for >= 99% of FBS teams; a field
  that fails stays on CFBD (or on its ESPN fallback) and is reported; havoc is reported only.
- 1c margins. The live game model is fit on ESPN play-by-play (liveInput); a code trace must show no CFBD plays/drives/
  advanced input reaches runModel on the live path. Pass = margins identical by construction (0.00 <= .05); if a CFBD
  input does reach the live margin, 1c = not shown and the lead cannot pass on 1a alone.
- 1d coverage/lag: share of week 1-10 FBS games (ESPN schedule release) present in the mirror; pass >= 99%.
- Ship rule: each endpoint switches to the mirror only if its own check passes; ESPN play-by-play stays the fallback
  for a week the mirror does not have yet; portal, 247 composite, SP+ stay on CFBD. Report the CFBD calls a run before/after.

## 3. Transfer% on five cycles instead of two
- Rows: cfbfastR-data CFBD roster CSVs 2018-2026 (athlete id, team; first roster season 2018+ gives year in school).
  Player on an FBS roster in S and on any roster in S+1: label 1 = another team, 0 = same team (exits dropped).
  Cycles C = 2021->22 ... 2025->26. S+1 = 2026 uses the roster file only (membership, no game results).
- Features, the same for every cycle (self-contained, not the live PFN set): years since first roster season (1,2,3,4+),
  position group, level (P4/G5), games with a box line / team games in S (espn_cfb_player_box), home distance (log miles,
  roster lat/lon to team) and home-state flag, missing-home flag. Ridge logit (lambda 1, standardised).
- Baseline B = today's scheme: fit on the single cycle before the held one (the live fit's one out-of-time fold).
  Candidate A = fit on every cycle before the held one (4 cycles for 2025->26).
- Held = 2025->26. Earlier folds 2024->25 (B: 2023->24; A: 2021->24) and 2023->24 (B: 2022->23; A: 2021->23) are the tune/sign folds.
- Metric: per-player log loss difference B - A, t clustered by team (S). Also AUC both.
- Pass: t >= 2 on 2025->26 and A better on both earlier folds.
- Second test (same family, reported, not shipped on its own): recency weights half-life 1 cycle vs equal, on A.
- The lead's landing term (247 transfer rating x destination level) needs the CFBD portal pulls in the cfbhist cache:
  not reachable -> BLOCKED sub-item, no test.
- Ship path if pass: older cycles into scripts/cfb_transfer_fit.py. The live fit cannot be rerun here (no transfer
  cache; its HC labels zero out from this container), so a pass is recorded with the refit command for CI; no
  coefficient file is committed from this container.

## 5. Pre-draft team meetings in the mock's team choice
- Source: WalterFootball ProspectMeetingsByTeam{2024,2025,2026}.php. A page is used only if its last-update stamp
  predates round 1 of that draft; if a page carries post-draft information that cannot be removed, that draft is dropped
  and with fewer than 3 drafts the lead is BLOCKED.
- Rows: real picks 1-100 of the 2024-2026 drafts in real order (nflverse draft_picks). Choice set at each pick = the 40
  best-ranked players still available on the DraftTek final board (existing harness source) plus the real pick.
- Baseline utility: b0 * (-ln board rank) + b1 * rep (team took this position group in round 1-2 of the previous draft).
  Candidate adds m1 * (T30 or PRI meeting with this team) + m2 * (COM/SR/PRO/VIR/LOC/WOR only).
- Leave one draft out (fit on two, score the third). Metric: log likelihood of the real pick per row, candidate - baseline.
- Pass: pooled held t >= 2 clustered by draft-team, 3 of 3 drafts positive. Ship = MEET_W in mockDraft, dormant until the
  2027 page exists, registered as a named variant in the draft ledger.

## 6. Deep final boards for Draft% (rounds 4-7)
- Source: WalterFootball draft{Y}{POS}.php position boards with "Projected Round", classes 2020-2025 (the drafts the
  DraftTek final boards in the existing harness cover). A page stamped after day 1 of its draft is dropped.
- Rows: prospects on a WF position board who are outside the top 100 of that class's DraftTek final board.
- Baseline: P(drafted) from the live final-stage curve Phi((ln 265 - ln xPick)/.56) on the DraftTek rank (unranked on
  DraftTek = the class base rate of unranked WF names in the training drafts). The live board's own baseline for this
  group (leftover picks in FV order) cannot be rebuilt for past drafts (no historical FV): stated limitation.
- Candidate: logistic on baseline logit + WF projected round (midpoint; UDFA/FA = 8), leave one draft out.
- Metric: log loss of drafted yes/no. Pass: t >= 2 by class (6 clusters), majority of classes. Ship = dormant
  final-stage input (pages are overwritten, fall/winter weight untestable).
- Time rule: run after leads 1, 3, 7, 8, 10, 11, 12; if the 3-hour box is spent first -> BLOCKED (time), no partial scoring.

## 7. Coach-level development effect
- Rows: scripts/school_dev.py cfb rows (ESPN/247 classes 2011-19, outcome NFL FV via cfb_recruit_retarget.dataset,
  delta = outcome - leave-one-school-out expectation, exactly as the shipped school version).
- Head coach at signing: the head coach of the signing school in the class-year season, from the committed
  scripts/data/coach_alltime_src.json.gz (cfb rows: team, year, coaches with share; the coach with the largest share).
- 7a rolling, net of program: for class t, coach effect (precision-weighted, shrunk as school_dev does) from his classes
  < t at any school; regress held delta (net of program strength at signing, as school_dev's net option) on the prior
  effect; slope t clustered by coach. Pass t >= 2.
- 7b movers: coaches with classes at two schools. Effect at the first school (all classes there) predicts the mean
  residual of his classes at the second school, where the residual is net of the second school's own effect estimated
  without that coach's classes. Slope t >= 2 (clustered by coach).
- Lead passes only if 7a and 7b both pass. Display only (coach column on the development tab); never into xFV/FV.

## 8. Coordinators from Wikipedia season infoboxes
- Source: en.wikipedia.org/wiki/{2026 Team football team}?action=raw (article path; /w/ is disallowed by robots.txt).
- Test: team-roles (OC, DC) where the infobox has a value, against data/cfb_staff.json as committed.
  Agreement = the two name sets share at least one coach (scripts/names.py keys).
- Pass (coverage): pages answer for >= 90% of teams, agreement >= 90% of team-roles, and a hand read of up to 20
  disagreements finds the infobox wrong in at most 25% of them. Ship = sync applies infobox differences with a "prev"
  record and logs each one; scheme labels stored (display field).

## 9. Ourlads dated depth charts (absence flag)
- Design: OL/DB starters dropped between consecutive snapshots, 2025 and 2026 weeks 1-10, flag vs the game model residual;
  pass t >= 2 in both seasons, snapshot date before kickoff.
- Fetch budget: 138 teams x the in-season archive snapshots of two seasons is 1,100-2,000 pages from a commercial
  scouting site the lead itself says to read once a week slowly. If the archive index confirms more than ~45 minutes of
  polite fetching (>= 2 s a page), the lead is BLOCKED with no scoring.

## 10. ESPN-to-recruit id crosswalk
- Source: espn_cfb_rosters/cfb_rosters_{Y}.parquet (athlete_id, cfbd_recruit_ids).
- Coverage test: CFBD recruit rows in scripts/data/cfb_recruits_cfbd.json.gz with no ESPN athlete id: share that gain one
  through the crosswalk; precision = share of linked pairs whose names agree through scripts/names.py (sample all).
- Label test: draftees 2014-25 (nflverse) that the retarget dataset left unmatched to a 2011-19 recruit and that the
  crosswalk links (recruit id -> ESPN college athlete id -> draft pick by name+college).
- Pass: precision >= 98% and (coverage gain >= 2 points of the unmatched rows or >= 50 recovered draftee labels), and
  then the recruit gate rerun (held-out rho, 247 block t) is not lower. If the gate rerun cannot be done in the time
  box, the crosswalk file is built and the gate rerun is listed as the command that decides the ship; nothing wired.

## 11. EADA football expenses in the landing model
- Source: ope.ed.gov EADA zips (fiscal years 2022-23 for 2024 moves, 2023-24 for 2025 moves: the year that ended
  before the window).
- The live landing rows (scripts/.cache/transfer/rows.json) are not in the container. Proxy design, fixed here: moves =
  roster-file transfers of lead 3 between FBS/FCS schools present in data/cfb_transfer_fit.json landing school table;
  conditional logit over those schools: level step (from x to), talent z, log home miles, home-state, plus money.
  Baseline money = the table's donor money + private flag (as live). Candidate = log football expenses (EADA) instead.
- Fit 2024->25 moves, hold 2025->26. Metric: per-move log likelihood of the chosen school, candidate - baseline,
  t clustered by origin team. Pass t >= 2 held, same sign on the swapped fold.
- A pass on the proxy does not refit the live file from here (same constraint as lead 3): recorded with the refit
  command; display use of the federal numbers in yNIL is not a tested claim and is not built.

## 12. Team-specific preseason uncertainty from incoming transfers
- Rows: scripts/data/games_wf/cfb.json.gz, FBS v FBS (fcs = 0), weeks 1-4, model margin m and sigma as stored.
- z = z-score across FBS within season of offIn (skill yards brought in by transfers, scripts/data/cfb_roster_feats.json);
  game value = mean of the two teams' z (a missing team = 0).
- sigma'^2 = sigma^2 x max(.25, 1 + c x zbar); p(home) = Phi(m / sigma'). c on the grid -.30 ... +.30 step .05.
- Tune 2022-23 (pick c by log loss), hold 2024, 2025, 2026 (weeks 1-4, all before week 11).
- Metric: log loss, tuned c vs c = 0, paired by game, t clustered by season-week. Pass: t <= -2 held, 2 of 3 held seasons
  better, tune better (c != 0).
