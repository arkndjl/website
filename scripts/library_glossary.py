# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Build research/library.json (then run scripts/library_build.py): ARKBOARD Reference tab content (glossary + FV conversion charts)."""
import json, re

import pathlib
ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
OUT = ROOT + '/research/library.json'
ld = lambda p: json.load(open(f'{ROOT}/{p}'))

ALLP = ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Hockey', 'Soccer', 'Tennis']


def E(term, short, body, where, sports):
    return {'term': term, 'short': short, 'body': body, 'where': where, 'sports': sports}


sections = []

# ---------------------------------------------------------------- FV and grades
sections.append({'id': 'fv', 'title': 'FV and grades', 'entries': [
    E('FV (future value)', 'Grade on the 20-80 scale of what a prospect becomes at peak: the mean outcome of past players with that profile.',
      ['50 average regular, 60 plus, 70 star, 80 generational. Tiers every 5 points, grades in steps of 1.',
       'Each board has its own outcome and rarity ladder. There is no shared cross-sport FV scale.',
       'Headline = mean of the tier odds (busts and stars included), so it sits below the best case.',
       'Graded on absolute talent from a fixed map fit on pooled history, not on rank within a class or board.',
       'Strong classes get more high grades. Age and validated drivers adjust the grade.'],
      'Every prospect board: CFB, CBB, hockey prospects, soccer prospects, tennis prospects; recruit tabs; MLB boards',
      ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis', 'MLB']),
    E('Outcome ladder', 'The realized outcome each FV tier stands for, set by rarity on each board.',
      ['CFB: NFL career (All-Pro, Pro Bowl, seasons as a starter), 2012-18 drafts.',
       'CBB: peak NBA XPM, as rare as the matching NBA role (7+ All-NBA = 80), careers ending 2008-16.',
       'Hockey: peak NHL pWAR (best 3 of first 7 seasons), rarity in a draft class, 2008-19 classes.',
       'Soccer: peak GAR at ages 22-26, rarity in a birth year and position group, players 22 in 2013-21.',
       'Tennis: peak ranking points above No. 200 at ages 22-28, rarity in a birth year per tour, births 1979-97.',
       'Tennis ATP fit also trains on births after 1997, partial careers imputed to a final outcome.'],
      'fv model tab on each prospect page; FV conversion charts below', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('Stretched top', 'Above each board\'s knot K the headline runs linear to 80 at T, so an 80 comes about once every 5 seasons.',
      ['Mean of a capped outcome cannot reach 80; the stretch makes 80 reachable but rare (Oct 31 2026).',
       'K = mean that about 3 players a season reach; T = one player per about 5 seasons (exponential tail, held out).',
       'K / T: CFB 67.8 / 76.8, CBB 46.6 / 54.7, hockey 54.0 / 72.7, soccer 64.1 / 72.4, ATP 63.4 / 76.4, WTA 60.2 / 75.0.',
       'Order is unchanged. The exact mean (fvx) stays in tooltips; above K the headline reads hotter than realized means.'],
      'Headline FV on every prospect board (data/fv_scale.json)', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('fvx / fvg', 'fvx = exact mean outcome; fvg = the pre-outcome grade the tier odds are computed from.',
      ['Headline FV = round(fvx), stretched above K. fvg feeds fits built on the grade (mock value, recruit stars).',
       'The raw grade is not shown on the site; the outcome step stays (owner decision, Nov 1 2026).'],
      'Data fields on CFB and CBB boards; tooltips', ['CFB', 'CBB']),
    E('FV range and tier odds', 'Each player\'s odds of every outcome tier and their 10th-90th percentile outcome.',
      ['CFB and CBB: location-scale ordered probit of realized outcome on the grade; cut points at 30, 35 ... 70.',
       'Spread terms kept only if held-out RPS improves (CFB: early season x2.1, walk-on, consensus, underclassman).',
       'Held out: CFB RPS .0398 vs .0408 one spread; CBB .0767. Hockey, soccer, tennis: logistic odds per tier.',
       'Shown in the player dropdown only; main boards show the single headline.'],
      'Player dropdowns (outlook), fvd column', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('Tier chances (NBA%, NHL%, Top%, Reg%, Star%)', 'Chance of reaching a set outcome tier.',
      ['CBB NBA% = P(plays in the NBA), first rung of the FV model.',
       'Hockey NHL% = 40+ (top 45 of a class); Reg% = 50+ (NHL regular, top 20 of a class).',
       'Soccer Top% = 40+ (top-flight regular, top 250 of a birth year at position); Reg% = 50+ (top 90); Star% = 60+ (top 20).'],
      'Board columns: CBB, hockey prospects, soccer prospects', ['CBB', 'Hockey', 'Soccer']),
    E('+ (young for the grade)', 'A + marks a player whose star odds beat the next 2.5 FV, from age.',
      ['Rule: + when P(60+ | FV, age) >= P(60+ | FV + 2.5). Only age passed held out as an upside signal.',
       'Soccer held out t 5.0 / 4.1 at 55+ / 60+; tennis ATP t 4.3 / 3.3, WTA 3.9 / 3.1. Shares: tennis ~6%, soccer ~30% of top 2000.',
       'CFB + rule failed held out (t -.71 / -.34) and was removed. CBB and hockey signals: none pass.'],
      'Soccer prospects and tennis prospects boards', ['Soccer', 'Tennis']),
    E('Provisional grade', 'A grade for a player off the source board: starts at the 20 floor and takes every available driver.',
      ['Ranked in FV order with a prov tag. CBB: ridge on height, weight, class, age, recruit rank, team top-8 FV (R2 .77).',
       'Hockey: OHL, WHL, QMJHL, AHL and Liiga draft-eligibles off Tankathon, graded on NHLe, age, weight, position.',
       'Soccer: academy-only and youth-international players get their own provisional line.',
       'CFB: ESPN roster backups and carried-over players graded from the 20 floor.'],
      'Boards (prov tag)', ['CFB', 'CBB', 'Hockey', 'Soccer']),
    E('FV scorecard', 'Held-out check of each board: graded FV band vs what the players became.',
      ['Per band: mean FV given vs reached (90% CI), predicted 40+/50+/60+ odds vs realized share.',
       'Slopes: CFB .99, CBB .97, soccer 1.01, tennis ATP .99 / WTA .97; hockey calibrated.',
       'Known heat: WTA 45-64 runs 2.5-4.8 hot; CFB 40+ odds 6-8 pts hot at FV 40-49.'],
      'fv model tab, fv scorecard window', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('Driver gate (FV)', 'An input enters an FV model only if it cuts held-out error.',
      ['Hockey, soccer, tennis: t >= 2 across held-out classes/seasons/birth years and wins two thirds of them.',
       'CBB: dropping the driver must raise out-of-sample deviance in 4 of 5 folds (whole players held out).',
       'CFB: multipliers refit leaving one draft class out; kept only if within-position r with NFL AV improves.'],
      'fv model tabs (drivers kept, out-of-sample evidence)', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
    E('CFB FV model', 'NFL outcome grade for every FBS and FCS player.',
      ['Composite: production (Stat+, Marcel 5/4/3, regressed), On3 talent, age, frame, combine, badges, XV parts.',
       'Composite rank per class maps to FV by measured NFL outcome counts per position (drafts 2012-18).',
       'Scouting consensus (9 boards + Kiper top 25) blended at weight .5 at full coverage.',
       'Then the outcome step (ordered probit), mean headline, stretched top. Positional value scales elite RB, LB, DL, TE, S.'],
      'CFB board, draft board, fv model tab', ['CFB']),
    E('CBB FV model', 'NBA outcome grade for every D-I player and listed internationals.',
      ['E[FV] = 20 + 10 P(30+) + 10 P(40+) + 10 P(50+) + (mean 60+ career - 50) P(60+); one ridge logistic per rung.',
       'Newcomers: recruit rank (On3, 247, Barttorvik), class. Returners: 3-season BPM, conference power, age, size, rates.',
       'Board stage adds June draft-board rank and guard combine testing. E maps to a grade on pooled 2009-16 boards.',
       'Outcome odds are fit on each board\'s top 300; below that range they scale down to the floor those boards realized (1.8% NBA).',
       'In season: E = (1 - w) preseason + w now, w = minutes / (minutes + k); k 63 newcomers, 128 returners.'],
      'CBB board, fv model tab, in season window', ['CBB']),
    E('Hockey FV model', 'OLS on outcome FV for the draft class and drafted players short of 100 NHL games.',
      ['Draft model kept: log slot (board rank as slot), draft-year NHLe, defense, goalie, CHL first-round pick, class strength.',
       'Leave-one-class-out error 89.86 vs 95.14 for slot alone (2008-19 classes, 2,541 picks).',
       'After the draft: stage models add latest NHLe, pro games, World Juniors spot, NHL games and WAR so far.'],
      'Hockey prospects board, drafted prospects, fv model tab', ['Hockey']),
    E('Soccer FV model', 'OLS on outcome FV for every under-22 in 33 leagues plus academy and feeder leagues.',
      ['Inputs kept include age, market value (deflated to the fit seasons\' level), GAR this and last season,',
       'minutes share, club strength, scoring rate, height, position, PL2 minutes. 53,682 rows, 2013-20.',
       'Detailed position block (centre-back, full-back, defensive / attacking midfield, winger, striker vs central',
       'midfield): season-out error -0.10, t 3.9, 7 of 8 seasons, top 50 and forward test better.',
       'Raw grade = mean of the OLS grade and a gradient-boosted grade (300 trees of depth 3 on every design input,',
       'one set per snapshot): season-out error 55.62 -> 54.62, t 8.7, 8 of 8 seasons. The trees get no missing-height',
       'signal and market values only as dated on a player\'s own lineups.',
       'Held out by birth cohort: error 54.84 vs 64.42 for age and market value alone (R2 .43).'],
      'Soccer prospects board, fv model tab', ['Soccer']),
    E('Tennis FV model', 'Hurdle model for every ATP and WTA player under 22 with a ranking or a pro match in the last year.',
      ['Logistic for any peak value, OLS on outcome FV given value: FV = (1 - p) x 20 + p x mean given value.',
       'ATP kept: age, rank, unranked, Elo, 52-week win rate, years since pro debut, Futures volume.',
       'WTA kept: age, rank, unranked, Elo, rank x age, tour-qualifying volume. Held out by birth year; OOS R2 .50 / .46.',
       'Height is never an input (the archive fills height for players who made it: a leak).',
       'ATP fit also trains on unfinished careers (later births at imputed targets): as-of 2011-18 error 21.45 -> 20.24, t 7.8, 8 of 8.',
       "ATP tree blend (mean with a boosted-tree grade): as-of 20.24 -> 19.86, t 2.7, 7 of 8, p .015; a second form after the first failed, so it counts in the sweep's Holm family of 15 and misses (needs p <= .005): not used. WTA trees failed forward."],
      'Tennis prospects ATP and WTA boards, fv model tab', ['Tennis']),
    E('CS2 prospect FV', 'Projected RWA over the next year against tier-1 starters, 20-80 (50 = average tier-1 starter).',
      ['Prospect = under 20 maps at S-tier events. Projection: rating, age, share of last year\'s rounds at S/A-tier events.',
       'S/A share is negative on top of the rating\'s tier lift (held t -4.9). Rise and every stat line failed.',
       'Quarterly cutoffs, fit 2024-25, held out from Jul 2025; a term ships only past the Bonferroni cut of its batch.',
       'Badges (top 25% on a stat) tested on prospects and the main board: none passed, so CS2 shows none.'],
      'Counter-Strike prospects, player model', ['CS2']),
    E('MLB FV (hand-graded)', 'Baseball boards are graded by hand on the FanGraphs 20-80 tiers.',
      ['No model. Tiers: 80 top 5 overall (7+ WAR a season), 60 All-Star (3.4-4.9), 50 average regular (1.6-2.4).',
       'Boards: 2026 draft hitters v1 (May 7), U19 MiLB prospects, White Sox org top 64.'],
      'Baseball page (draft hitters, U19 MiLB, White Sox org, fv scale)', ['MLB']),
    E('Recruit FV / xFV', 'Projected FV for high school recruits.',
      ['CFB xFV = P(on board) x FV if on + (1 - P(on)) x 20, year 1; hurdle fit on ESPN 2023-26 classes.',
       'CFB recruit profile weighed on NFL outcomes of 2011-19 classes; the board sets the level.',
       'CBB: hurdle on consensus rank and old-for-class; P(reach NBA) then log(FV - 20) given NBA; trained 2009-16.'],
      'Recruits tabs: 2027-2029 classes, class rankings, recruit model', ['CFB', 'CBB']),
    E('ARK stars', 'Recruit star rating cut from the projected FV, not the industry stars.',
      ['CFB: 5-star+ top 6 a class, 5 top 3% of board FV, 4 top 10%, 3 above median, 2 on board, 1 off board (year-3 xFV).',
       'CBB: 5 = 2+ NBA seasons as a starter, 4 = reached the NBA, 3 = D-I starter at BPM +3, 2 = played D-I, 1 = did not.',
       'Arrow = ARK stars minus industry stars.'],
      'Recruits tabs', ['CFB', 'CBB']),
    E('Badges (players)', 'Bronze to platinum trait medals by the name: one stat each, regressed by volume.',
      ['Tiers at the 75/90/97/99th percentile of the position. CFB badges build archetypes.',
       'On other boards a badge shows only if it predicts the sport\'s own outcome held out beyond the value metric.',
       'Display only: no badge feeds FV or projections. Volume and usage traits pass; efficiency rates mostly fail.'],
      'Every board (medals by the name), player cards', ALLP),
    E('All-time FV', 'Each player\'s grade at their best season, listed by position.',
      ['CFB rebuilds every FBS season 2014-25; box-score era (2014-18) means recalibrated to NFL outcomes.',
       'CFB outcome: NFL AV a season since the draft over a class horizon index h (mean 1 on 2020-23 drafts), so old classes\' out-of-league years don\'t count against them.',
       'Other boards read their past lists; only grade-complete rows are used.'],
      'all-time FV tab on CFB, CBB, hockey, soccer and tennis prospect pages', ['CFB', 'CBB', 'Hockey', 'Soccer', 'Tennis']),
]})

# ---------------------------------------------------------------- player value
sections.append({'id': 'value', 'title': 'Player value metrics', 'entries': [
    E('College WAR', 'Wins over a replacement starter in a 12-game season.',
      ['WAR = snap share x (line + weight x quality) x .227; 1 pt of margin a game = .0189 win% (928 FBS team seasons).',
       'Line = margin lost when an average starter sits: QB 2.7, RB 1.7, EDGE 1.4, WR 1.35, CB 1.3, S 1.1, DT 1.0, LB 1.0.',
       'Quality from Stat+, badges and FV. QB keeps 1.25 pts per SD; the rest goes to offensive teammates by snaps.',
       'Replacement lineup wins .18 (2 of 12); an average team\'s starters total 3.8 WAR.'],
      'CFB board, WAR leaders tab, team talent', ['CFB']),
    E('WAA', 'WAR minus snap share x line: wins over an average starter at the position.',
      ['Comparable across positions; below average < 0.'],
      'CFB WAR leaders tab', ['CFB', 'NFL']),
    E('XV', 'WAR with quality from the stat-line parts that track winning.',
      ['CFB: PFN score plus position parts (QB cmp %, yds/att, INT rate; OL pressure rate; DT splash; CB yds/target).',
       'Fit on 2024-25 team margin. Held out team r .88 vs .86 for WAR quality; win% r .73 vs .68.',
       'NFL: same idea fit to team margin per game; on missed games t 4.9 vs 2.1 for AV WAR.',
       'Next-season forecasts tie with WAR, so projections and game models stay on WAR.'],
      'CFB and NFL WAR leaders tabs (XV column)', ['CFB', 'NFL']),
    E('NFL WAR', 'Wins over replacement: .6 x AV WAR + .4 x XV, season to date.',
      ['AV WAR = (AV - replacement AV at the sub-position x snap share) x .091 wins per AV.',
       '.091 from team wins on team AV (160 team seasons 2021-25, r .86). Replacement team wins 3 of 17.',
       'Defensive AV rebuilt from pressures, stops and plays on the ball. Two-way players earn WAR on each side.'],
      'NFL WAR leaders, team WAR, rookies, breakouts', ['NFL']),
    E('Stat+', 'Production index: 100 + 25 x z of the position all-in-one score this season.',
      ['Source score: PFN QB+, RB+, WR+, TE+, OLi, EDGE+, DT+, LB+, CB+, SAF+; K and P by percentile.',
       'z against the snap-weighted position mean, FBS or FCS. 125 = 1 SD above average.',
       'FV production driver; validity vs NFL AV: TE .52, WR .50, QB .48, RB .48, EDGE .40, LB .40, DT .37.'],
      'CFB board, WAR leaders, true freshmen', ['CFB']),
    E('xNIL / yNIL / zNIL', 'xNIL = NIL market worth now; yNIL = estimated pay entering the season; zNIL = xNIL - yNIL.',
      ['xNIL = position price x on-field value (AV at FV, x playing time), shared within P4 and G5 pools.',
       'yNIL = program budget split by a preseason index (P4 ~$20M, G5 ~$3M, FCS ~$0.4M a program).',
       'Not fit to On3 valuations (they move only +18% per 10 FV). zNIL growth is 20% of each coach score.',
       'FCS players at FBS-starter FV priced at 40% of the FBS rate. CBB xNIL: minutes share x (BPM + 3) at school price.'],
      'CFB board, team talent, team builder, fv to xNIL charts; CBB recruits', ['CFB', 'CBB']),
    E('Season AV (college)', 'College on-field value a season: snap share x position weight x quality.',
      ['Quality = Stat+ z + .5 badge z + .25 FV z. Team R2 vs 2026 SRS .63 vs .44 for summed FV value.',
       'Used for college injury cost and team value; NFL value stays on AV at FV.'],
      'CFB team talent (Season AV), fv to war chart', ['CFB']),
    E('rXPM (raw XPM)', 'NBA impact: .5 databallr DPM + .5 Basketball-Reference BPM, points per 100 possessions over average, as played.',
      ['The headline XPM on every NBA board. O-XPM and D-XPM are the same blend of each side.',
       'Feeds VORX, the game models (which shrink it themselves) and the CBB board target. BPM only where no DPM row (*).',
       'XPM and rookie boards default to qualified: 1,000 MP per 82 team games. Qualified rookies 2010-23: rXPM orders next-three-season VORX .607 (VORX .604); all rookies .330.'],
      'NBA VORX/XPM leaders, rookies, team pages, ARKLIST', ['NBA']),
    E('pXPM (predictive XPM)', 'rXPM shrunk by minutes toward what he is expected to be.',
      ['raw x MP / (MP + 600) + mean x 600 / (MP + 600).',
       'Mean = role mean + r x (Marcel prior - role mean), r = H / (H + 1,000), H = MP last season + .5 x MP the season before.',
       'Role mean = -1 + .5 ln(1 + MP82 / 100). Fit on next-season XPM 2011-26, leave one season out: RMSE 1.235 vs 1.259 role mean only, 1.59 raw.'],
      'NBA VORX/XPM leaders (pXPM chip), rookies', ['NBA']),
    E('VORX', 'NBA wins over replacement: .030 x (rXPM + 1.4) x MP / 48.',
      ['Replacement rXPM -1.4; both constants fit to team wins (480 team seasons 2011-26). Default sort of the XPM and rookie boards.',
       'Rookies 2010-23, held out: VORX orders next-three-season VORX best (Spearman .398; pXPM .395, aXPM .379, rXPM .330).',
       'Next-three-season XPM: the rookie 3Y orders it best (.481; aXPM .413, rXPM .417, VORX .351).'],
      'NBA VORX/XPM leaders, projections, contract value', ['NBA']),
    E('1Y / 3Y XPM', 'Projected XPM next season and over the next three, minutes-weighted, given he plays.',
      ['From XPM (proj), age, projected minutes, a hinge above +3, and the two seasons before; coefficients by share of the season played.',
       'Fit on seasons with minutes, weighted by them. The chance he is off the board is not in it.',
       'Held out 2012-23, 1,000+ minutes in the window: 3Y RMSE 1.13, 1Y 1.14; bias within .25 at every level. Display only.'],
      'NBA VORX/XPM leaders (3Y chip), projections', ['NBA']),
    E('XPM (proj)', 'Season-to-date XPM blended with a preseason prior by minutes.',
      ['prior + (XPM - prior) x MP / (k + MP); k 509 veterans, 809 newcomers (7,269 player seasons 2012-26).',
       '80% range covers .806 / .799 held out. Display only.'],
      'NBA contract value, XPM chip', ['NBA']),
    E('Contract value (surplus)', 'Minimum salary + projected VORX x market $ per win, minus salary, every year left.',
      ['$ per win = payroll above the minimum / league projected VORX, refit on each update; +7% a year (assumption).',
       'Player option counted only when it pays the player; team option only when it pays the team.'],
      'NBA contract value tab', ['NBA']),
    E('xAAV', 'The AAV a player would sign for as a free agent now: a share of the cap from position, age and last full season.',
      ['Fit on real signings, held out a signing year at a time against the mean by position x age. Forms pre-registered; live form = lowest held-out MAE whose top end is calibrated (priced 7%+ of the cap -> signed for 85-115% of it). Square root of the cap share, smeared back; clipped to the league minimum and maximum.',
       'NHL: 3,241 CapWages deals 2010-26 (standard, 35+, two-way; no ELCs or extensions). WAR, pWAR, 3Y, points and TOI a game, games, age by F/D/G. MAE .83% of the cap vs 1.70 (t -40, 17/17 seasons; forward 11/11). Points and TOI alone tie it (t -1.4): the market pays for points.',
       'NFL: 12,192 OverTheCap veteran contracts 2014-26 (3+ years after the draft). WAR last two seasons, snaps, games, age by position. MAE .86% vs 1.50 (t -52, 13/13; forward 9/9). WAR adds over snaps alone (t -18). Ceiling = record 24.5% (Burrow 2023).',
       'NBA: 1,334 Basketball-Reference offseason signings 2011-26 (free agent, multi-year or plain contracts; next season salary on the signing team). XPM last two seasons, VORX, minutes, points and minutes a game, games, age, years in the league. MAE 2.60% vs 5.04 (t -19, 16/16; forward 11/11). XPM/VORX add over points and minutes alone (t -6, 14/16). Max 25/30/35% by years in the league; 2026-27 cap $165M (projected).',
       'Soccer: not built. No public wage data reachable (Capology blocks); xMV is the transfer-market equivalent.'],
      'NBA, NFL, NHL contract value tabs', ['NBA', 'NFL', 'NHL']),
    E('xBPM', 'Projected Barttorvik BPM this season.',
      ['Ridge on last season, recruiting, age, size; in season blends to-date BPM.',
       'Team context (Nov 3 2026): returning teammates\' WAR, teammates\' recruiting (top 8 -ln rank), WAA, transfer up/down.',
       'Forward 2020-26 RMSE: returners 2.558 -> 2.462 (t 18), newcomers 3.439 -> 3.229 (t 14). Not an FV input.'],
      'CBB board, true freshmen, breakouts', ['CBB']),
    E('CBB WAR / WAA', 'Wins over a replacement / average D-I player.',
      ['WAR = (BPM + 2) x minutes / 40 x 68 possessions a 40 / 100 x .0143 wins a point; WAA uses BPM.',
       'Replacement BPM -2.0 = the 9th man in team minutes (2025-26). Wins a point fit on 3,485 team seasons 2017-26:',
       'wins = .395 x games + team WAR (r .86). The textbook slope (.0347 at margin sd 11.5) overstates: schedules',
       'pair strong with strong and win odds flatten at the ends. FV test: WAR, WAA, career and 5/4/3 WAR fail.'],
      'CBB WAR leaders, stats, portal, returning', ['CBB']),
    E('Stat+ (CBB)', 'BPM against the position: 100 + 25 x z.',
      ['z = (BPM - position mean) / position sd. Tabs: last season\'s norms (G -.23 / 3.84, F .57 / 4.13, C 1.71 / 4.56),',
       'then this season\'s own once 40 players a position qualify. FV driver norms: G .10 / 3.85, F .50 / 4.05, C .52 / 4.31 (2008-16).',
       'FV driver (Nov 3 2026): passes three fold rules (t 2.9-3.5, 4-5/5), held 2017-19 (+.17) and forward 2020-23 (+.26).'],
      'CBB stats, WAR leaders, portal; FV inputs', ['CBB']),
    E('Game Score', 'Hollinger single-game value.',
      ['PTS + .4 FGM - .7 FGA - .4 (FTA - FTM) + .7 ORB + .3 DRB + STL + .7 AST + .7 BLK - .4 PF - TOV.',
       'FV and xBPM tests (a game, a 40, best game, 20+ games): all fail.'],
      'CBB top performers', ['CBB']),
    E('Breakout watch (CBB)', '1st-2nd year players above their preseason projection.',
      ['xBPM up = live xBPM - preseason xBPM (minutes-blended). Also BPM over x, minutes, usage and FV gains.',
       'Last season view: 2nd-years against their freshman line (WAR, BPM, minutes, usage gains).',
       'FV tests: WAR gain, minutes gain, usage gain, BPM x (1 - minutes share) all fail (low-minute BPM passes the folds, not the top of the board).'],
      'CBB breakouts tab', ['CBB']),
    E('Returning / talent (CBB)', 'Team tables: last season\'s minutes and WAR back; roster grades.',
      ['Ret Min% = last season\'s minutes still on the roster (Barttorvik ids). In WAR = incoming transfers\' WAR.',
       'Talent = mean FV of the top 8. xNBA = sum of NBA%. TvE = talent rank - ARK rank.',
       'FV tests: vacated minutes (opportunity), returning teammates\' WAR, teammates\' recruiting fail; the last two pass for xBPM.'],
      'CBB returning, team talent', ['CBB']),
    E('Peak XPM (CBB scale)', 'CBB FV target: mean of a career\'s best three NBA XPM seasons, each shrunk toward -2 by 500 minutes.',
      ['FV bands start at the XPM as many careers reached as reached the matching NBA role. See the CBB chart.'],
      'CBB fv model tab (fv conversions)', ['CBB']),
    E('NHL WAR', 'Descriptive wins over replacement at goal value.',
      ['5v5 on-ice xG vs teammates, PP xG /5, PK /4, finishing (goals - ixG), penalties, share of team leftover xG.',
       'Goalies: GSAx at full credit. Sums to team goal differential (R2 .991).',
       'Replacement = players outside each team\'s top 13 F / 7 D / 2 G.'],
      'NHL WAR leaders, rookies', ['NHL']),
    E('pWAR / HPM', 'Projected WAR and projected goals per 60 over an average player.',
      ['HPM = Marcel-weighted (1 / .5 / .25) shrunk rates, components weighted by how well they carry to next season.',
       'pWAR = (HPM - replacement) x TOI / 60 / goals per win. LOSO R2 .37 vs .26 before (t 4.24, 15/17 seasons).',
       'Goalie GSAx barely repeats (weight .21), so goalie pWAR ~0.4 while goalie WAR runs ~7.'],
      'NHL WAR leaders, backup watch, rookies; hockey prospect outcome (skaters)', ['NHL', 'Hockey']),
    E('GSAx', 'Goals saved above expected (MoneyPuck xG).',
      ['Goalie tab shows GSAx a game shrunk toward a new goalie\'s level; feeds the NHL totals model.'],
      'NHL goalies tab, NHL WAR', ['NHL']),
    E('NHLe', 'NHL points a full season at a league\'s translation factor.',
      ['Factors fit on every pick\'s career since 2008 from league pairs, a year of age development removed.',
       'Shrunk toward the published factor by link count. CHL leagues ~.10-.12, NCAA ~.21.'],
      'Hockey prospects board, first-year tab', ['Hockey']),
    E('GAR (soccer, senior)', 'Goals above replacement on one scale across leagues.',
      ['Shrunk per-90 rates (on-ice, npxG, xA, xGBuildup, keeper saves) weighted to next-season team goal difference.',
       'Replacement per position = regulars (900+ minutes) on the bottom three sides by goal difference of each finished league-season, pooled: GK -.14, D -.09, M -.05, F .00 a match. League strength counts. Held out R2 .61.',
       'An average side totals about 26 GAR a season. xMV, 1Y / 3Y and backup watch still read GAR over the earlier line (players under 900 minutes) until refit.',
       'PAR = GAR x points per goal of difference (.626).'],
      'Soccer player value, rookies, backup watch', ['Soccer']),
    E('tGAR (soccer prospects)', 'Team-share goals above replacement: minutes / 90 x (club rating - replacement) / 11.',
      ['Club rating = goals a match vs an average big-five club; replacement -2.5 (a bottom Scotland/Greece/Denmark side).',
       'Outcome = mean of the best three tGAR seasons at ages 22-26. Differs from the senior GAR above (about 4-5x larger).'],
      'Soccer prospects board, first-year tab', ['Soccer']),
    E('xMV', 'Estimated market value in EUR millions with no market input.',
      ['Ridge on log Transfermarkt value: GAR now and past two seasons, minutes, age, position, league, club.',
       'Held out R2 .68 (Oct) to .78 (Jul). Gap to TM forecasts TM\'s next move (slope .23, 12/12 seasons).'],
      'Soccer player value, rookies', ['Soccer']),
    E('Elo / Elo+ (tennis)', 'Elo on every pro match since 1991 at every level; Elo+ against players the same age.',
      ['K = 250 / (matches + 5)^0.4, Slams x1.1, start 1500. Elo+ = 100 + 25 per SD vs same-age players with 20+ matches.'],
      'Tennis prospects board, tennis ARK Ranking', ['Tennis']),
    E('RWA (CS2)', 'Round win % a Counter-Strike player adds per round, opponent-adjusted; 0 = average tier-1 starter.',
      ['Box: team round share on its five per-round stat lines (kills, deaths, assists, ADR, KAST, openings, trades,',
       'multi-kills, clutches, headshots, damage taken). Plus-minus: half the round share the box misses, split across the five.',
       'No utility measure: bo3.gg has no flash or utility damage data; utility $ bought failed (t -2.5), accuracy hurt.',
       'Tier lift: +0.5 x share of last year\'s rounds at S/A-tier events (low-tier pools link to the top through few maps).',
       'Opponents credited x1.0, half-life 180 days, 25 rounds of shrink. Held out R2 .131 vs .120 Nov 2, .108 K-D.'],
      'Counter-Strike players, prospects, player model', ['CS2']),
    E('SPW+ / RPW+ / xHold / xBreak', 'Serve and return points won over the average top-100 player, opponent-adjusted.',
      ['Percentage points, hard court. xHold / xBreak = games held or broken vs an average top-100 opponent via the game chain.'],
      'Tennis serve + return tabs', ['Tennis']),
    E('QB value (NFL)', 'Points a game over a replacement QB from the game model\'s QB term.',
      ['Rating = weighted career EPA/play shrunk toward replacement (-0.12) with 250 pseudo-plays.'],
      'NFL QB value tab', ['NFL']),
    E('Yds+ / YOE (returners)', 'Kick and punt return yards over expected, shrunk.',
      ['YOE = return yards minus the mean return from the same spot (5-yard bins, this season). Yards, not EPA (EPA does not repeat).'],
      'special teams tab on NFL and CFB pages', ['NFL', 'CFB']),
    E('Development (school / coach)', 'Outcome per recruit over what their recruiting rating predicted, shrunk by sample.',
      ['CFB: NFL FV per signee, school tau .42 FV, rolling t 5.3 (6/6). CBB NBA FV is null; college BPM delta passes.',
       'CBB head coach BPM over expected: split t 5.1. Shown with +/- 1 SD.'],
      'development tab on CFB and CBB pages', ['CFB', 'CBB']),
]})

# ---------------------------------------------------------------- player odds & projections
sections.append({'id': 'players', 'title': 'Player odds and projections', 'entries': [
    E('Draft%', 'P(declares) x P(picked in the 2027 draft).',
      ['Declare: logit on ln xPick and age on draft day; ranked underclassmen ~94%, seniors ~69%, RS seniors 100%.',
       'Picked: log-normal around the mock xPick; the SD narrows toward the draft (PFF dated boards, 2020-26).'],
      'CFB board, draft board', ['CFB']),
    E('Transfer% (Xfer%)', 'P(on another FBS or FCS roster next season).',
      ['Ridge logit on the 2024-25 and 2025-26 cycles: class, production, role, recruit rank, record, P(HC change), distance from home.',
       'Out-of-time AUC .738. Transfer% + stay + exit = 100%. NIL-era data only (July 2021 on).'],
      'CFB board, portal, team builder', ['CFB']),
    E('FBS%', 'P(on an FBS roster next season) for FCS players.',
      ['Logit on 2023-26 FCS-to-FBS moves: production, team strength, year in school, position. Capped at 1 - Draft%.'],
      'CFB FCS board', ['CFB']),
    E('D-1%', 'P(on a D-I roster next season) for D-II and D-III players.',
      ['Ridge logit on NCAA D-II/III box scores, 2023-24 and 2024-25 move-ups: production, starts, minutes, team SRS, division.',
       'Out of time on 2025-26 to 2026-27: AUC .899, log loss .077 vs .111 base rate.',
       'FV = 20 + D-1% x V. V: his line translated to a first D-I season (shrunk BPM; ridge on 318 movers, out of time r .43/.60),',
       'then what 2009-16 arrivals with that season and class became (Poisson index + monotone map, out-of-fold deviance t 2.8).'],
      'CBB board (D-II / D-III filter)', ['CBB']),
    E('Dec%', 'Chance a college player leaves school for this NBA draft.',
      ['Recruit rank, minutes-shrunk BPM, class, era; plus the midseason board rank. Seniors and internationals 100%.'],
      'CBB mocks', ['CBB']),
    E('P20 / P50 / P80 projections', '20th, 50th and 80th percentile of WAR, VORX and stats, full season and rest of season.',
      ['Rest of season = rate x exposure (minutes, TOI, snaps); rate = Marcel 1 / .7 / .5 with fitted shrink.',
       'Recalibrated per season-left bin; checked by PIT on held-out seasons (+/- .03 overall).'],
      'projections tab on NFL, NBA, NHL pages', ['NFL', 'NBA', 'NHL']),
    E('Player game projections', 'Per-game points, rebounds, assists (NBA, CBB) and fantasy lines (NFL, CFB).',
      ['NBA walks the game model\'s minutes and P(play), plus pace, opponent, minutes freed by teammates out.',
       'Held out 2024-26 PRA MAE 6.20 vs 6.46 for season average; CBB 5.42 vs 5.58.'],
      'Predictions players group', ['NBA', 'CBB', 'NFL', 'CFB']),
    E('NFL fantasy VOR', 'Projection minus the replacement projection at the position, 12-team league.',
      ['Replacement = first non-starter: QB13, RB30, WR31, TE13, K13, DST13. Overall rank by VOR.'],
      'Predictions NFL rankings', ['NFL']),
    E('Breakouts (NFL)', 'Young players\' weekly WAR over expected.',
      ['xWAR = WAR rate a snap before the week (three seasons shrunk to the group, updated in season) x snaps.'],
      'NFL breakouts tab', ['NFL']),
    E('Breakout watch (CFB)', '1st-2nd year QB/RB/WR/TE whose touches and targets are rising.',
      ['Lists usage growth; it is a watch list, not a model grade.'],
      'CFB breakouts tab', ['CFB']),
    E('Backup watch / xGap', 'Second and third-string players graded above a starter.',
      ['Gap = backup value - starter value (FV in college; WAR, XPM, HPM or GAR in the pros). College listed at gap >= 3.',
       'Rank by xGap = the gap projected over two seasons, adding the age (or class) gap; held out t -3.0 to -15.6.'],
      'backup watch tab on every sport page', ['CFB', 'CBB', 'NFL', 'NBA', 'NHL', 'Soccer']),
    E('Comps', 'Nearest historical profiles shown in the player dropdown.',
      ['CFB: nearest 2014-22 profiles. Hockey stage 3-4 comps also feed FV (held-out pass); elsewhere display only.'],
      'Player dropdowns', ['CFB', 'Hockey']),
]})

# ---------------------------------------------------------------- team ratings
sections.append({'id': 'teams', 'title': 'Team ratings', 'entries': [
    E('ARK Ranking', 'Each sport\'s power ranking: the game model\'s neutral-site rating, ranked.',
      ['Same number the game model uses, so picks already read it. Split into parts (Elo, efficiency, talent ...).',
       'Rank range = 80% range of true rank from 4,000 draws at the rating sd measured on past seasons.',
       'CBB 2016-26: ARK picks the winner 77.3% vs AP 76.8%, Coaches 77.1% vs 76.7%.'],
      'ARK Ranking tab on every sport page; ARKRANKING page', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2']),
    E('CFB rating', 'Points vs an average FBS team, neutral field.',
      ['Elo (preseason prior: last season, SP+, 247 talent, returning production, transfers) + opponent-adjusted EPA/play.',
       'Plus home, rest, travel, altitude, FCS (and the FCS side\'s own margin rating), special teams, P4 tier, 4th-down aggressiveness, returning production,',
       'game control. Sim win sd 14.2. Current injuries charged (Inj); Full = at full strength.'],
      'CFB ARK Ranking, games, season odds', ['CFB']),
    E('NFL rating', 'Expected margin vs an average team, neutral field, with this week\'s QB and injuries.',
      ['Fitted terms: Elo, starting QB, rest, home, injuries, market rating from earlier closes, return game.',
       'Injury cost = WAR a game x 36 pts a win x P(miss); questionable .25, doubtful .98.'],
      'NFL ARK Ranking, games, season odds', ['NFL']),
    E('CBB rating', 'Expected margin vs an average D-I team on a neutral floor.',
      ['Fitted terms: adjusted efficiency x possessions, Elo, home, game control, conference home game, injuries,',
       'home x attendance, ESPN BPI, form, preseason injury report. Preseason prior from returning minutes, transfers, top-5 FV.',
       'Luck-stripped: 50% of three-point luck removed.',
       'Market disagreement: each team\'s running gap between its earlier closes and the model (.2 a game, 0 at the season\'s start), spreads and totals. Lined games 2021-26: margin MAE 9.057 -> 9.009 (close 8.986), totals 13.401 -> 13.366.'],
      'CBB ARK Ranking, games, season odds, tournament odds', ['CBB']),
    E('NBA rating', 'Expected margin vs an average team, neutral floor, current roster and today\'s injury report.',
      ['Fitted terms: Elo, net rating, market rating, home, lineup value (XPM x minutes x chance to play), playoff Elo, rest.',
       '25% of three-point luck removed. Proj column (rest-of-season VORX) is display only.'],
      'NBA ARK Ranking, games, season odds', ['NBA']),
    E('NHL rating', 'Win chance from a logistic on Elo, expected-goals rating, back-to-back, home and lineup value.',
      ['xG rating: opponent-adjusted ridge, half-life 120 days, .7 carried over a season. Lineup value follows trades.',
       'Totals use xG, goals, market total and the starting goalie.'],
      'NHL ARK Ranking, games, season odds', ['NHL']),
    E('Soccer rating', 'Goals a match vs an average big-five club, neutral ground; one scale for every league.',
      ['Online Poisson attack and defence within each league; league strength from cross-league matches only.',
       'Inputs blended walk-forward: market-implied goals from earlier closes, xG (Understat, FotMob), squad value.',
       'Dixon-Coles rho -.04. Big five vs close, held out: log loss .972 vs .967.'],
      'Soccer ARK Ranking, league tabs, UEFA cups, MLS', ['Soccer']),
    E('Tennis ARK', 'Win chance vs the average top-50 player, best of three, over the tour\'s 52-week surface mix.',
      ['Surface Elo blended with a games-won rating and opponent-adjusted serve and return point ratings (Markov chain).',
       'Fit on 2012-22 tour main draws; held 2023-26 log loss ~.596 vs Elo .603.'],
      'Tennis ATP / WTA ARK Ranking', ['Tennis']),
    E('CS2 ARK', 'Series win chance vs the average top-20 team.',
      ['Player Elo that follows players between rosters (per map, on round share), bo3.gg team map rating with veto,',
       'region offsets, Valve VRS points and the five players\' mean RWA. Held out log loss .553 vs VRS .667. No picks: no free closing odds history.'],
      'Counter-Strike ARK Ranking, matches, model', ['CS2']),
    E('Elo', 'Results-and-margin rating; 1500 = average.',
      ['CFB Elo starts from a preseason prior. CS2 Elo: +400 = 10 to 1 odds. Tennis Elo on wins, every level.'],
      'Ranking tabs', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Tennis', 'CS2']),
    E('Game control', 'How much of each game a team spent with the win in hand.',
      ['Time-weighted win chance from score and clock only, opponent-adjusted, carried across seasons.',
       'Shipped in CFB (held out MAE t -4.1) and CBB (t -2.0). NBA failed.'],
      'CFB and CBB ARK Ranking (Control)', ['CFB', 'CBB']),
    E('Talent / TvE', 'Talent = projected starters\' value by FV; TvE = Elo vs the Elo talent predicts, in SD.',
      ['CFB Talent = sum over the projected starting 22 of expected college WAR a season at FV. TvE > 0 = above talent.'],
      'CFB team talent, ARK Ranking', ['CFB']),
    E('Season odds', '10,000 simulated seasons from the game model.',
      ['Rating error sd shrinks with the season left (sd^2 = a + b x share left, measured on past seasons).',
       'xW = wins so far + simulated rest. Outputs: conference, playoff, title odds; full NFL tiebreakers.'],
      'season odds tab on every team sport; ARKRANKING', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('CFP odds', 'Committee model plus bracket for the 12-team playoff.',
      ['Plackett-Luce fit on CFP releases 2017-25: losses, wins, rating, wins above bubble, P4. Held out field log loss .029 vs .090.',
       '2026 rules: P4 champions in, best G6 champion, Notre Dame if top 12; top 4 byes.'],
      'CFB season odds (Bye, Semis, Natl title)', ['CFB']),
    E('NCAA tournament odds', 'Committee and bracket sims for bids, seeds and rounds.',
      ['Committee fit on 2015-26 fields from rating and wins above bubble (45th team): 91% of at-large picks.',
       'Conference tournaments and the bracket played with the game model.'],
      'CBB tournament odds tab', ['CBB']),
    E('Futures', 'Our title, conference and division sims vs DraftKings futures (vig removed).',
      ['Display only; win-total backtests found no proven edge (NBA b .22 t 3.0 in sample, held out t 1.5).'],
      'Predictions futures tab; title odds on ARKRANKING', ['NFL', 'NBA']),
    E('Team badges', 'Team trait medals, one stat each, shrunk by games to reliability .5.',
      ['59 of 72 pass the repeat test. NFL Return Game also passed vs the close and is in the NFL model.'],
      'ARK Ranking team dropdowns, team GFX cards', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('Staff score / coach pay', 'Head coach and coordinator scores; coach market value vs public pay.',
      ['Pay is program plus wins (USA Today data); Surplus = Value - Pay. Staff score includes zNIL growth (20%).',
       'Coach value-added does not carry to a new job (failed test); staff weights are set by hand.'],
      'CFB staff, coach pay, coaching jobs tabs', ['CFB']),
]})

# ---------------------------------------------------------------- games & predictions
sections.append({'id': 'games', 'title': 'Game models and predictions', 'entries': [
    E('Game projection', 'Model line, win chance and projected score for every game.',
      ['Margin from the sport\'s rating (see Team ratings); win chance = normal (or logistic) on the margin.',
       'Win sd fit walk-forward: NBA ~12, CBB 11.9, CFB 14.2. Totals: separate model per sport.',
       'Soccer: projected score, over 2.5 and both-score from market totals ratings in 16 leagues (a league term and a lean per club, learned from earlier matches\' closing over/under prices; never the match\'s own). Held out over 2.5 log loss .675 vs .683 before, close .672. 1X2 unchanged.',
       'Predictions is the only page with picks, lines and props; sport pages show projections only.'],
      'games and game table tabs; Predictions', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2']),
    E('Walk-forward test', 'Each game is predicted with a model fit only on games before it.',
      ['Seasons split into tuning (terms enter) and held out (report and veto). Errors clustered by game day.',
       'Game models tab compares live loss to the walk-forward expectation for the same month.'],
      'Predictions game models tab', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('Model ledger', 'Shared rule for every model term.',
      ['Evidence = the held-out t alone (drop-one); the tuning t is shown, not combined. One Benjamini-Hochberg family over all terms with a held-out split.',
       'Keep at q <= .10; drop at q > .10 when held-out loss is no worse without it; otherwise watch. No held-out split = watch.',
       'Terms past 365 days are flagged for re-test.'],
      'Predictions game models tab (ledger view)', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer']),
    E('Edge / gap', 'Model minus the market, in points (spread, total) or chance (moneyline, tennis).',
      ['Edge % on the full table = raw model chance minus the no-vig market chance.',
       'Gaps past 5 sd are treated as bad lines; picks between 3 and 5 sd are staked at the cap.'],
      'Predictions picks, game table', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Pick rule (X)', 'A pick is the model\'s side when |model - line| >= X for that sport and market.',
      ['X = smallest gap whose calibrated return at -103 is > 0 on tuning seasons.',
       'A market or segment is on only if held-out picks beat the close (clvRet > 0, t >= 1.65, n >= 30).',
       'One pick a game per market family. Bet to = worst line that still clears X.'],
      'Predictions picks, picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Calibrated edge', 'Expected return at the price, from held-out picks judged by the close.',
      ['Edge = min(EV, a + b (gap - mean gap)); a blends close value and ROI; b = the market\'s own slope, shrunk.',
       'History priced at Novig -103. TIMING .5 halves every backtest edge (live bets come after part of the move).',
       'Chance at the bet line = the market mid there (from both asks) + the calibrated chance edge; gap measured from the market fair line.',
       'NBA backtest edge also x.5 (history saw tip-time injury news the open did not).'],
      'Predictions picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Kelly %', "Stake as % of bankroll: Kelly on the calibrated edge x the book's live realization, compounding.",
      ['Formerly Dengler Units (DU); 1 DU = 1% of bankroll. Picks qualify where the edge at the price > 0.',
       'Cap 5% a bet (tennis 2%). Joint slate Kelly gave the same growth as per-pick (rho ~0).',
       'Walk-forward: 1x Kelly most log growth at the backtest edge and at half of it.',
       'Stake x: r = close value per point of staked edge on the book\'s live picks, normal update around .5 (sd .25), '
       'clipped 0-1. Walk-forward by game day it beat posted stakes at the close (all books -21.7% -> -6.4% log growth; '
       'NBA +0.81% -> +1.05%).'],
      'Predictions picks, game table, paper book', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Live vs the market', 'Every flagged pick, live and paper, judged out of sample.',
      ['Close value and ROI with 95% ranges clustered by game day; one-sided p on G - 1 df.',
       'Holm across the books (the unit that goes live or paper) and across rules with 8+ game days, family-wise .05.',
       "Win - chance: win rate minus the stake's chance; Brier skill against the close's chance at the pick's price.",
       'Venue: Novig, or Polymarket US after its taker fee (.095 p(1 - p)) when it pays more at the same line.',
       "Polymarket's flag-time price as a signal failed its pre-registered test (143 matched picks: slope t .47; "
       'the filter kept worse picks; a noisier forecast of the close than the posted price).'],
      'Predictions picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Nightly cap', 'Open picks on one ET date, all sports, scaled to at most 40% of bankroll.',
      ['Stake x min(1, 40 / total). Walk-forward: P(50% drawdown) .12 vs .27 uncapped at 1x edge.'],
      'Predictions picks (capped stake)', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Close / CLV / Worth at close', 'Every pick is judged first by the closing line, ROI second.',
      ['Close = last snapshot before the start. CLV = points the line moved our way.',
       'Worth at close (clvRet) = return the pick was worth at the closing price, with t.',
       'CLV needs far fewer bets than results for t 2 (CBB 5+ pts: ~228 vs ~402).'],
      'Predictions picks, paper book, picks backtest', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Bad open filter', 'Opening lines that mirror the close or move more than 6 sd (median-based) are dropped from history.',
      ['Mirrored opens were home/away swaps (mostly 2025-26 CBB neutral sites) that inflated backtests.'],
      'All backtests', ['CFB', 'CBB', 'NBA']),
    E('Close predictor', 'Predicts the close from the open and the model gap (market softness b).',
      ['close - open = b x (model - open) + controls. b: CFB spread .10, CFB total .22, CBB .10, NBA spread .24, total .42.',
       'Break-even gap = where a -110 bet at the open breaks even at the predicted close.'],
      'Predictions picks backtest (close predictor)', ['CFB', 'CBB', 'NBA']),
    E('Totals recentring', 'Model total minus the mean model-line gap over the slate and the season\'s last 100 games.',
      ['Keeps totals picks from being a bet on league scoring level. CFB, NBA and (since Nov 1) CBB.'],
      'Predictions picks', ['CFB', 'CBB', 'NBA']),
    E('Paper book', 'The posted picks graded at posted line, price and Kelly %, compounding.',
      ['Identical to the picks tab since Oct 28 2026; reset Oct 28 15:35Z. No real money.'],
      'Predictions paper book tab', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Rule monitor (CUSUM)', 'Live switch that stops a losing pick rule until a refit.',
      ['Judged after 50+ picks, by game day, each day over 1 + (n - 1) rho (rho = within-slate correlation of close value, held-out picks).',
       'Stop if CUSUM around zero S = max(0, S - clvRet / sd - .25) >= 10, or CUSUM of the log likelihood ratio (no edge vs the stakes\' edge) >= ln 99.',
       'Last-300 clustered t (se floored at iid) is shown, not a stop.'],
      'Predictions picks backtest (rule monitor), game models tab', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Rule drift test (SPRT)', 'Sequential test of each rule\'s live close value vs its backtest.',
      ['H1 = backtest edge x TIMING; H0 = 0; game days deflated by the within-slate correlation of close value. Pause at 19:1 for no edge; confirm at 19:1 for the edge.',
       'About 250 (NBA totals) to 430 (CBB, CFB totals) bets to stop a rule with no edge.'],
      'Predictions picks backtest (new rules)', ['CFB', 'NFL', 'CBB', 'NBA', 'Tennis']),
    E('Growth / DD 25/50', 'Held-out log growth a season at the close, and chance of a 25% / 50% fall from peak.',
      ['Resampled from walk-forward picks. Full Kelly accepts high drawdown risk over long seasons.'],
      'Predictions picks backtest', ['CFB', 'NFL', 'CBB', 'NBA']),
    E('NFL props', 'One prop per player per game, full Kelly at Novig prices, week scaled to a budget.',
      ['P(over) from projection shape by decile, shrunk .414. Held out 2025-26: 3,732 bets 55.3%, t 3.1 at -110.',
       'Weekly budget 50% of bankroll until ~300 props are graded.'],
      'Predictions NFL fantasy (props), picks', ['NFL']),
    E('Tennis picks', 'Model side when it differs from the Novig no-vig price by 4+ points of win chance.',
      ['Calibrated chance = no-vig + .5 x k toward the model (k .25 logits). Cap 2% a bet.',
       'Tour-level main draws; tuned 2025, held out 2026: 1,935 picks, +4.5% worth at close (t 19).'],
      'Predictions picks, game table', ['Tennis']),
    E('Moneyline board / flip', 'Every game whose model winner is -200 to +200, or the market underdog (flip).',
      ['Display only, not a pick rule. Held-out flip record: all +1.2% t .6.'],
      'Predictions picks tab', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL']),
    E('Not picked', 'Markets tested and off because they did not beat the close.',
      ['NHL (ML and totals), soccer (1X2, O/U 2.5, MLS, props), CS2 (no free closing odds), NBA/NHL props.',
       'Their game projections still show; Kelly % reads off.'],
      'Predictions game table', ['NHL', 'Soccer', 'CS2', 'NBA']),
    E("Major Pick'Em (CS2)", "Valve Major Pick'Em picks with the best chance of each coin tier.",
      ['Coin: 11 challenges (Silver 4, Gold 8, Diamond 11); 5 free, 6 skill: 5+ of 10 per Swiss stage, bracket 2 QF / 1 SF / final.',
       'Stage picks: two 3-0, two 0-3, six 3-1 or 3-2 (exact record). Picked once the stage field and round 1 are known.',
       "A stage's picks move only that stage's chance, so every tier wants max P(5+ correct), not max expected correct.",
       'P(5+) from joint stage sims (Valve pairing, Buchholz, Bo1 / Bo3; team strength drawn once per sim, sd .45 logit).',
       'Search: exact max-expected set, then hill-climb on P(5+), scored on a second set of sims. Bracket: max P(all 3).',
       'Held out since Jul 2025, 15 Swiss stages: predicted pass 47%, actual 47% (seed chalk 40%, VRS 47%).',
       'Mean correct 4.00 vs chalk 4.33 (t -0.96): no reliable edge over chalk in Swiss stages.',
       'Max P(5+) and max expected correct pick the same set in 21 of 25 stages; where they differ, < 1 pt of pass chance.',
       '12 held-out brackets: 1.92 of 3 bracket challenges vs chalk 1.42, VRS 1.50.'],
      "Counter-Strike page, pick'em tab", ['CS2']),
]})

# ---------------------------------------------------------------- drafts & mocks
sections.append({'id': 'drafts', 'title': 'Drafts and mocks', 'entries': [
    E('Three mocks', 'Predictive, blended and conviction mock drafts for the NFL, NBA and NHL drafts.',
      ['Predictive = projection of the real draft: consensus boards plus model (CFB board weight .75-.85 backtested).',
       'Conviction = the model board (FV before the consensus blend) plus team fit.',
       'Blended = each slot at the geometric mean of the two xPicks. Predictive and conviction grade each other.'],
      'mock draft group on CFB, CBB, hockey prospects pages', ['CFB', 'CBB', 'Hockey']),
    E('xPick', 'Expected pick: geometric blend of consensus average rank and rank by our draft value.',
      ['Market weight .55 + .3 x sqrt(boards / 9); unranked prospects .65 at 1.3x the boards\' depth.',
       'Past the last pick = projected undrafted (UDFA signings tab).'],
      'CFB mocks, udfa signings', ['CFB']),
    E('Team needs and pick rule', 'Teams pick on -ln(xPick) + need weight x need.',
      ['Need from the whole NFL position room: rookie-deal draft capital or salary, cut for age and expiring deals.',
       'Penalties for doubling up, a set QB and position runs. QB top-pick premium decays by pick.'],
      'CFB mocks (pick reports)', ['CFB']),
    E('Trades', 'Projected trades on Massey-Thaler pick values; real traded picks from Wikipedia.',
      ['Trades in every round (5, 7, 6, 5, 5, 2, 1 a round); next-year picks at .48 of a mid-round pick.',
       'Solid tag = traded pick; dashed tag = projected trade.'],
      'CFB mocks', ['CFB']),
    E('Reach / value', 'A pick the other mock takes 2.5x+ and 16+ picks later (reach) or earlier (value).',
      ['Site table only; the GFX drops the chips.'],
      'Mock tables', ['CFB']),
    E('Mock sims', 'Simulated drafts give each prospect\'s pick range.',
      ['CFB: Gumbel pick noise by round (.40 / .525 / .625), 200 sims. CBB: June board shock sd 1.05 / .90 / .40 by days left.',
       'NBA lottery and NHL order: simulated standings x lottery odds; P(#1).'],
      'Mocks (Range, Sims), lottery tab', ['CFB', 'CBB', 'NBA', 'Hockey']),
    E('Draft order', 'Order from projected standings (NFL tiebreakers in full) and current pick owners.',
      ['NFL order uses the sim\'s expected slot; NHL from projected points and Tankathon owners; NBA from lottery sims.'],
      'Mock drafts', ['CFB', 'CBB', 'Hockey']),
    E('CBB mock inputs', 'Consensus of 2027 boards (.5 median rank + .5 mean) and conviction on slot plus college line.',
      ['xXPM = expected NBA peak XPM vs the average drafted player, given slot and college line.',
       'Entrants: Dec% draws; FV 40+ rule for the pool.'],
      'CBB mocks', ['CBB']),
    E('xSlot (hockey)', 'The draft slot a board rank points to.',
      ['An October board regresses toward the middle by June (Central Scouting January ranks vs June slot).'],
      'Hockey prospects board', ['Hockey']),
]})

# ---------------------------------------------------------------- data & names
sections.append({'id': 'data', 'title': 'Data and names', 'entries': [
    E('Sources: football', 'Free public sources for CFB and NFL.',
      ['CFB: PFN impact rankings, On3, ESPN rosters and play-by-play (2015-26), CFBD (1,000 calls/month), 247, Rotoballer.',
       'Consensus boards: PFN industry (7 analysts), Tankathon, PFF, Kiper. Conference availability reports.',
       'NFL: nflverse (play-by-play, rosters, injuries, draft picks), PFR AV, ESPN.'],
      'CFB, NFL pages', ['CFB', 'NFL']),
    E('Sources: basketball', 'Free public sources for CBB and NBA.',
      ['CBB: Barttorvik (ESPN fallback when blocked), On3, 247, ESPN, Covers injuries, ESPN BPI, NBA draft boards.',
       'NBA: Basketball-Reference BPM and contracts, databallr DPM, LUMA ARC (CC BY 4.0), ESPN, official injury report.'],
      'CBB, NBA pages', ['CBB', 'NBA']),
    E('Sources: hockey, soccer, tennis, CS2', 'Free public sources for the other sports.',
      ['Hockey: NHL API, MoneyPuck xG, Daily Faceoff goalies, Tankathon, Central Scouting, HockeyTech.',
       'Soccer: ESPN, football-data.co.uk closes, Understat and FotMob xG, Transfermarkt values and lineups.',
       'Tennis: Sackmann archive (mirror), weekly tour feed, Tennis Abstract, ESPN. CS2: Valve VRS, Liquipedia, bo3.gg.'],
      'Hockey, soccer, tennis, Counter-Strike pages', ['NHL', 'Hockey', 'Soccer', 'Tennis', 'CS2']),
    E('Odds', 'Novig (free, no key) is the price source; DraftKings via ESPN is the fallback.',
      ['Polymarket prices are a data signal only. Odds snapshots every 30 min, 13-04 UTC, plus 08 and 11 UTC.'],
      'Predictions; game cards', ['CFB', 'NFL', 'CBB', 'NBA', 'NHL', 'Soccer', 'Tennis']),
    E('Refresh cadence', 'Scheduled builds by sport, in season.',
      ['CFB board ~3x daily (Aug-Jan); NFL ~3x daily plus Sunday game windows (Sep-Feb); CBB 3x daily (Nov-Apr).',
       'NBA and NHL 2x daily; soccer 2x daily; tennis 2x daily; CS2 every 4 h; soccer and tennis prospects daily.',
       'Picks refresh every 2 h and on every odds snapshot.'],
      'Window status bars (updated date)', ALLP + ['CS2']),
    E('Freshness / stale tag', 'Each window shows its data date; a feed past its limit is tagged stale.',
      ['In season a feed is stale past 36 h; off season past 10-14 days.'],
      'Every window status bar, ARKBOARD hub', ALLP + ['CS2']),
    E('Name matching', 'One shared matcher joins sources by player name in Python, Node and the browser.',
      ['Prefer a stable id (ESPN, Barttorvik pid, gsis) when both sides have one.',
       'Alias file for spellings the rules miss and common nicknames; matches still check team and position.'],
      'Every board that joins sources', ALLP),
    E('Held out / LOSO / LOCO', 'Out-of-sample checks used across the site.',
      ['Held out = seasons never used to choose terms. LOSO = leave one season out; LOCO = leave one class out.',
       'Prospect fits hold out whole players, classes, birth cohorts or birth years so a player\'s rows stay together.'],
      'Model tabs', ALLP),
    E('Portal era rule', 'Transfer and roster models train only on NIL-era data (July 2021 on).',
      [],
      'CFB Transfer%, team builder, CBB roster terms', ['CFB', 'CBB']),
    E('ARKLIST', 'The owner\'s hand-picked players, one list per sport.',
      ['Not a model output.'],
      'ARKLIST tab on each page; ARKLIST page', ALLP),
]})

# ---------------------------------------------------------------- FV tables
hk = ld('data/hockey.json')
sp = ld('data/soccer_prospects.json')
tf = ld('data/tennis_prospects_fit.json')
tp = ld('data/tennis_prospects.json')
cbb = ld('data/cbb.json')
cfb = ld('data/cfb.json')
fvd = ld('data/fv_dist.json')
scale = ld('data/fv_scale.json')['boards']


def pct(c, n):
    if c == 0:
        return 'none live'
    p = 100 * c / n
    ps = '<0.01%' if p < 0.01 else (f'{p:.2f}%' if p < 1 else f'{p:.1f}%')
    return f'{c:,} of {n:,} ({ps})'


def held(sc):
    out = {}
    for b in sc['bands']:
        o = {x['t']: x['real'] for x in b['odds']}
        lab = f"{b['lo']}+" if b['hi'] is None else f"{b['lo']}-{b['hi']}"
        out[b['lo']] = f"{lab}: {b['pred']} -> {b['real']} (n {b['n']}, 50+ {round(100 * o[50])}%)"
    return out


def knot(b, name):
    s = scale[b]
    return f"{name}: headline = mean up to {s['K']:.1f}, linear above to 80 at {s['T']:.1f} (80 about once per 5 seasons)."


fv_tables = []

# all boards at a glance (fvglance)
hkc = {str(c[0]): c[1] for c in hk['fit']['cuts']}
hper = {'80': '1 in 4 classes', '75': '1 in 2 classes', '70': '#1 / class', '65': 'top 2 / class', '60': 'top 5 / class',
        '55': 'top 10 / class', '50': 'top 20 / class', '45': 'top 30 / class', '40': 'top 45 / class'}
sper = {'80': '#1 / 2 birth years', '75': '#1 / birth year', '70': 'top 3 / birth year', '65': 'top 8 / birth year',
        '60': 'top 20 / birth year', '55': 'top 45 / birth year', '50': 'top 90 / birth year (big-five regular)',
        '45': 'top 150 / birth year', '40': 'top 250 / birth year (top-flight regular)'}
gl = [('80', 'generational', '5+ time All-Pro', '7+ All-NBA teams', 'top 5 overall'),
      ('70', 'star', '2-time All-Pro', '3+ All-NBA teams', 'top 10 overall'),
      ('60', 'plus', 'Pro Bowler', '2+ All-Star', 'All-Star / #3 SP'),
      ('55', 'above average', '6+ seasons starting', 'above-avg starter', 'above-average regular'),
      ('50', 'average', '4+ seasons starting', 'average starter', 'average regular'),
      ('45', 'below average', '2+ seasons starting', 'low-end starter', 'low-end regular / platoon'),
      ('40', 'bench', 'rotational', 'end of rotation', 'bench'),
      ('30', 'organizational', 'camp body', 'two-way / fringe', 'up and down'),
      ('20', 'non-pro', 'non-NFL', 'G-League', 'organizational')]
rows = []
for f, tier, fb, bb, mlb in gl:
    h = {'30': 'some NHL games', '20': 'no NHL games'}.get(f) or f"{hper[f]}, {hkc[f]:.2f}+ peak WAR"
    s = {'30': 'some senior value', '20': 'no senior value'}.get(f) or sper[f]
    rows.append([f, tier, fb, bb, h, s, mlb])
fv_tables.append({'board': 'All boards: the 20-80 scale', 'note': 'Tier labels per sport, as on the ARKBOARD hub (fv at a glance). Each board keeps its own ladder.',
                  'cols': ['FV', 'tier', 'football', 'basketball', 'hockey', 'soccer', 'baseball'], 'rows': rows})

# CFB / NFL
cd = cfb['dist']['all']
ncfb = sum(cd.values())
ge = lambda t: sum(c for f, c in cd.items() if int(f) >= t)
hc = held(fvd['cfb']['scorecard'])
cfb_rows = [
    ('80', '5+ time All-Pro (generational)', '~1', '1.04 / 0.47', 'No. 1 pick'),
    ('75', '3+ time All-Pro', '~1', '0.89 / 0.29', 'top 2 pick'),
    ('70', '2-time All-Pro', '~3', '0.67 / 0.23', 'top 5 pick'),
    ('65', 'All-Pro or 3+ Pro Bowls', '~7', '0.49 / 0.17', 'top 10 pick'),
    ('60', 'Pro Bowler', '~16', '0.40 / 0.13', '1st round'),
    ('55', '6+ seasons as a starter', '~25', '0.31 / 0.10', 'late 1st / 2nd round'),
    ('50', '4+ seasons as a starter', '~32', '0.19 / 0.07', 'rounds 2-3'),
    ('45', '2+ seasons as a starter', '~43', '0.09 / 0.05', 'rounds 3-4'),
    ('40', 'rotation, 48+ games', '~64', '0 / 0.02', 'rounds 4-6'),
    ('35', 'backup, 16+ games', '~98', '0 / 0.01', 'late round'),
    ('30', 'drafted / camp roster', '~150', '0 / 0', 'late round / UDFA'),
    ('20', 'non-NFL', '-', '- / 0', '-')]
rows = []
for f, m, pc, war, dv in cfb_rows:
    fi = int(f)
    rows.append([f, m, pc, pct(ge(fi), ncfb) if fi > 20 else 'all', war, dv, hc.get(fi, '-') if fi < 65 else (hc[65] if fi == 65 else '-')])
fv_tables.append({'board': 'CFB / NFL prospects',
                  'note': f'Outcome = NFL career, 2012-18 drafts; per class = players in the band per draft class. pct = live FBS+FCS board '
                          f'({ncfb:,} graded) at FV or higher. {knot("cfb", "Stretch")}',
                  'cols': ['FV', 'meaning', 'per class', 'pct', 'NFL WAR prime / a year', 'draft value', 'held out: graded -> reached'],
                  'rows': rows})

# CBB / NBA
cbbrows = ld('static/data/cbb-all.json')
ci = cbbrows['cols'].index('fv')
cv = [r[ci] for r in cbbrows['rows'] if isinstance(r[ci], (int, float))]
hb = held(fvd['cbb']['scorecard'])
ANCH = {80: '7+ All-NBA', 75: '5+ All-NBA', 70: '3+ All-NBA', 65: 'All-NBA', 60: '2+ All-Star',
        55: 'All-Star or 6+ seasons as a starter', 50: '4+ seasons as a starter', 45: '2+ seasons as a starter',
        40: 'rotation, 3+ seasons', 35: 'bench, 100+ games', 30: 'reached the NBA', 20: 'non-NBA'}
rows = []
for r in cbb['fvTable']:
    f = r['fv']
    if r['xpmLo'] is None:
        xr = f"below {r['xpmHi']:+.1f}"
    elif r['xpmHi'] is None:
        xr = f"{r['xpmLo']:+.1f} and up"
    else:
        xr = f"{r['xpmLo']:+.1f} to {r['xpmHi']:+.1f}"
    meaning = f"{ANCH[f]}; most common: {r['role']} ({round(100 * r['roleShare'])}%)"
    perc = f"{r['perClass']:.2f}" if r['perClass'] < 10 else f"{r['perClass']:.0f}"
    perb = '-' if r['perBoard'] is None else (f"{r['perBoard']:.1f}" if r['perBoard'] < 10 else f"{r['perBoard']:.0f}")
    pk = f"median pick {r['medPick']}, {round(100 * r['drafted'])}% drafted"
    c = sum(1 for x in cv if x >= f)
    rows.append([str(f), meaning, perc, pct(c, len(cv)) if f > 20 else 'all', xr, perb, pk, hb.get(f, '-')])
fv_tables.append({'board': 'CBB / NBA prospects',
                  'note': f'Outcome = peak NBA XPM, careers ending 2008-16; per class = careers per college class in the band; per board = players '
                          f'on a preseason board reaching that FV or better. pct = live D-I board ({len(cv):,}). {knot("cbb", "Stretch")}',
                  'cols': ['FV', 'meaning (rarity anchor; most common role in band)', 'per class', 'pct', 'peak XPM', 'per board', 'draft slot', 'held out: graded -> reached'],
                  'rows': rows})

# Hockey
cal = {c['band']: c for c in hk['fit']['calib']}
per_class_picks = hk['fit']['picks'] / (hk['fit']['classes'][1] - hk['fit']['classes'][0] + 1)
rank_in_class = {'80': .25, '75': .5, '70': 1, '65': 2, '60': 5, '55': 10, '50': 20, '45': 30, '40': 45}
hlab = {'80': 'one in four classes', '75': 'one in two classes', '70': 'the best of a class', '65': 'top 2 of a class',
        '60': 'top 5 of a class', '55': 'top 10', '50': 'top 20 (NHL regular)', '45': 'top 30', '40': 'top 45 (NHL career)'}
hbv = [r.get('fv') for r in hk['board'] if r.get('fv') is not None]
hpv = [r.get('fv') for r in hk['pipe'] if r.get('fv') is not None]
hlive = lambda t: f"{sum(1 for x in hbv if x >= t)} / {sum(1 for x in hpv if x >= t)}"
rows = []
for f, w in hk['fit']['cuts']:
    k = str(f)
    c = cal.get(f)
    hcell = f"{f}-{f + 4}: {c['pred']} -> {c['real']} (n {c['n']}, NHL {round(100 * c['nhl'])}%)" if c else '-'
    rows.append([k, f'{w:.2f}+ peak WAR a season', hlab[k], f"top {100 * rank_in_class[k] / per_class_picks:.1f}% of picks", hlive(f), hcell])
for f, m, b in [(30, 'some NHL games', 30), (20, 'no NHL games', 20)]:
    c = cal[b]
    rows.append([str(f), m, '-', '-', hlive(f) if f > 20 else f"{len(hbv)} / {len(hpv)}", f"{b}-{b + 4}: {c['pred']} -> {c['real']} (n {c['n']}, NHL {round(100 * c['nhl'])}%)"])
fv_tables.append({'board': 'Hockey prospects (NHL)',
                  'note': f"Outcome = mean of best three WAR seasons in the first 7 after the draft; goalies by the same rarity among goalies. "
                          f"pct = share of a draft class (~{per_class_picks:.0f} picks, 2008-19). live = 2027 board / drafted prospects at FV or higher. "
                          f"{knot('hockey', 'Stretch')}",
                  'cols': ['FV', 'meaning', 'per class', 'pct', 'live', 'held out: graded band -> reached'],
                  'rows': rows})

# Soccer
sb = sp['board']
pool = sp['pool']
sv = [r.get('fv') for r in sb if r.get('fv') is not None]
scal = {c['band']: c for c in sp['fit']['calib']}
slab = {'80': 'one in two birth years', '75': 'the best of a birth year', '70': 'top 3 of a birth year', '65': 'top 8',
        '60': 'top 20', '55': 'top 45', '50': 'top 90 (big-five regular)', '45': 'top 150', '40': 'top 250 (top-flight regular)'}
rows = []
for f, g, d, m, fw in sp['fit']['cuts']:
    k = str(f)
    c = sum(1 for x in sv if x >= f)
    cc = scal.get(f)
    hcell = f"{f}-{f + 4}: {cc['pred']} -> {cc['real']} (n {cc['n']}, 50+ {round(100 * cc['p50'])}%)" if cc else '-'
    rows.append([k, f'peak GAR a season GK {g:.1f} / D {d:.1f} / M {m:.1f} / F {fw:.1f}', slab[k] + ' at the position', pct(c, pool), hcell])
for f, m in [(30, 'some senior value'), (20, 'no senior value')]:
    cc = scal[f]
    c = sum(1 for x in sv if x >= f)
    rows.append([str(f), m, '-', pct(c, pool) if f > 20 else 'all', f"{f}-{f + 4}: {cc['pred']} -> {cc['real']} (n {cc['n']}, 50+ {round(100 * cc['p50'])}%)"])
fv_tables.append({'board': 'Soccer prospects',
                  'note': f"Outcome = best three GAR seasons at ages 22-26; rarity within birth year and position group (players 22 in 2013-21). "
                          f"pct = live pool of {pool:,} under-22s. {knot('soccer', 'Stretch')}",
                  'cols': ['FV', 'meaning', 'per class', 'pct', 'held out: graded band -> reached'],
                  'rows': rows})

# Tennis
tlab = {'80': 'one in eight birth years', '75': 'one in four birth years', '70': 'one in two birth years', '65': 'the best of a birth year',
        '60': 'top 2 of a birth year', '55': 'top 4', '50': 'top 7', '45': 'top 10', '40': 'top 13 (top-100 regular)'}
for tour, TL in [('atp', 'ATP'), ('wta', 'WTA')]:
    fit = tf[tour]
    cr = {str(a): b for a, b in fit['cutRank']}
    tv = [r.get('fv') for r in tp[tour]['board'] if r.get('fv') is not None]
    tpool = tp[tour]['pool']
    ht = held(fit['scorecard'])
    rows = []
    for f, share in fit['cuts']:
        k = str(f)
        c = sum(1 for x in tv if x >= f)
        hcell = ht.get(f) if f < 65 else (ht[65] if f == 65 else '-')
        rows.append([k, f'peak like year-end No. {cr[k]}', tlab[k], pct(c, tpool), hcell or '-'])
    rows.append(['30', 'some value: peak between No. 200 and No. 100', '-', pct(sum(1 for x in tv if x >= 30), tpool), ht.get(30, '-')])
    rows.append(['20', 'never above No. 200 at ages 22-28', '-', 'all', ht.get(20, '-')])
    fv_tables.append({'board': f'Tennis prospects ({TL})',
                      'note': f"Outcome = best three seasons at ages 22-28 of year-end points above No. 200, as a share of the top 100's mean; "
                              f"births 1979-97. pct = live pool of {tpool} under-22s. {knot(tour, 'Stretch')}",
                      'cols': ['FV', 'meaning', 'per class', 'pct', 'held out: graded -> reached'],
                      'rows': rows})

# MLB (hand-graded, FanGraphs tiers)
mlb = [('80', 'top 5 overall', '#1 (top 1-3 arm)', '-', '7.0+'), ('75', 'top 5-10', '#1/2', '-', '6.0'),
       ('70', 'top 10 overall', '#2', '-', '5.0-7.0'), ('65', 'perennial All-Star', '#2/3', '-', '4.2'),
       ('60', 'All-Star', '#3', 'high closer', '3.4-4.9'), ('55', 'above-average regular', '#3/4', 'mid closer', '2.5-3.3'),
       ('50', 'average everyday player', '#4', 'low closer / high setup', '1.6-2.4'),
       ('45', 'low-end regular / platoon', '#4/5', 'low setup', '0.8-1.5'),
       ('40', 'bench', 'back-end / spot starter', 'middle relief', '0.0-0.7'),
       ('35', 'emergency call-up', 'emergency call-up', 'emergency call-up', '~0'),
       ('30', 'up and down', 'up and down', 'up and down', 'below -0.1'),
       ('20', 'organizational', 'organizational', 'organizational', '-')]
fv_tables.append({'board': 'MLB prospects (hand-graded)',
                  'note': 'FanGraphs primer tiers; hand grades, no model, no live rarity or held-out check. WAR = per season at peak.',
                  'cols': ['FV', 'hitter', 'starting pitcher', 'reliever', 'WAR / season'],
                  'rows': [list(r) for r in mlb]})

lib = {'asof': '2026-11-02',
       'about': 'ARKBOARD Reference: definitions and methods for every metric and model, plus FV conversion charts per board.',
       'sections': sections, 'fv_tables': fv_tables}

# ---------------------------------------------------------------- copy checks
bad = re.compile(r'\b(delve|robust|leverage|comprehensive|seamless|cutting-edge|unlock|empower|game-changer|elevate)\b', re.I)
problems = []


def chk(s, where):
    if '—' in s or '–' in s:
        problems.append(f'dash: {where}: {s}')
    if bad.search(s):
        problems.append(f'word: {where}: {s}')
    if re.search('[\U0001F300-\U0001FAFF☀-➿]', s):
        problems.append(f'emoji: {where}: {s}')


for sec in sections:
    for e in sec['entries']:
        for k in ('term', 'short', 'where'):
            chk(e[k], e['term'])
        for line in e['body']:
            chk(line, e['term'])
            if len(line) > 130:
                problems.append(f'long {len(line)}: {e["term"]}: {line}')
for t in fv_tables:
    chk(t['note'], t['board'])
    for r in t['rows']:
        assert len(r) == len(t['cols']), (t['board'], r)
        for c in r:
            chk(str(c), t['board'])
for p in problems:
    print(p)
json.dump(lib, open(OUT, 'w'), indent=1, ensure_ascii=False)
print('sections', len(sections), 'entries', sum(len(s['entries']) for s in sections), 'tables', len(fv_tables), 'problems', len(problems))
for s in sections:
    print(' ', s['id'], len(s['entries']))
