#!/usr/bin/env node
// Build the College Football ARKBOARD (data/cfb.json) from public sources.
//
//     node scripts/fetch_cfb.mjs            # fetch everything, rebuild data/cfb.json
//     node scripts/fetch_cfb.mjs --offline  # rebuild from the cached pulls (re-tune the model)
//     node scripts/fetch_cfb.mjs --skip-on3 # refetch PFN + ESPN, reuse cached ON3
//     add --no-dob to skip the date-of-birth lookups
//
// Sources
//   PFN  impact rankings (QB+, RB+, WR+, TE+, OLi, EDGE+, DT+, LB+, CB+, SAF+), every FBS/FCS
//        player and every season since 2019, embedded as packed JSON in each page.
//   ON3  college roster rankings (the On3 college grade), every position, every page. ON3 sits
//        behind Cloudflare, so it is read through headless Chromium (Playwright).
//   ESPN team list (logos, colors) and every FBS roster (class year, height, weight, headshot).
//   Dates of birth (for decimal age) for everyone on the board: Wikidata (P569), then the Wikipedia
//        infobox (Wikidata wins when they disagree).
//        Found dates are kept in data/cfb_dob.json (committed, so each player is looked up once);
//        misses are retried after a week.
//   data/cfb_manual.json  hand-kept dates of birth and player notes (see the file). Grades are the model's only.
//
// Board rules (any one puts a player on the board):
//   PFN score >= 89.5 · ON3 grade >= 95 · (PFN + ON3) / 2 >= 88
//   freshman with an ON3 grade · freshman with PFN >= 80
//
// The FV model (20-80, see FV_* below and the ARKBOARD page) grades every FBS player, not just the
// board, so a grade is a rank against the whole population. Raw pulls are cached in
// scripts/.cache/cfb/ (gitignored). Needs Node 18+ and, for ON3, the playwright package
// (`npm i -D playwright`, or a global install).
import { sameName, variant } from './cfb_names.mjs';
import { pbpKey, pbpPlayers, pbpByGame, splitHalf, pbpTeamDowns, rbRoles, RB_ROLE_NAME } from './cfb_pbp.mjs';
import { parsePlays, overExpected, oeContext } from './cfb_oe.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { runModel, slimDrives, sitByGame } from './cfb_model.mjs';
import { assignBadges, archetypeOf } from './cfb_badges.mjs';
import { teamRankings, readPolls } from './cfb_rank.mjs';
import { loadGeo, pfnIndex, transferOdds, teamBuilder } from './cfb_transfer.mjs';
import { fetchRotoballer, statusOf, headlineClauses, seasonOut, fetchQbr, topPerformers, TOP_GROUPS } from './cfb_teams.mjs';
import { avOf } from './cfb_teams.mjs';
import { playerRates, fetchGames, fetchInjuries, cfbd, teamModels, gamesModel, staffModels, mockDraft, draftOdds, fetchCombine, fetchNflOrder, fetchNflNeeds, fetchNflTrades, applyNflTrades } from './cfb_teams.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const OUT = path.join(ROOT, 'data', 'cfb.json');
const MANUAL = path.join(ROOT, 'data', 'cfb_manual.json');
const LOGOS = path.join(ROOT, 'static', 'img', 'cfb', 'logos');
const DOBS = path.join(ROOT, 'data', 'cfb_dob.json');
const CAL = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_calibration.json'), 'utf8'));
const HISTORY = path.join(ROOT, 'data', 'cfb_history.json');
const ALL_OUT = path.join(ROOT, 'static', 'data', 'cfb-all.json');
const TEAMS_OUT = path.join(ROOT, 'data', 'cfb_teams.json');
const MOCK_OUT = path.join(ROOT, 'data', 'cfb_mock.json');
const NFL_LOGOS = path.join(ROOT, 'static', 'img', 'nfl');
const STAFF_IN = path.join(ROOT, 'data', 'cfb_staff.json');
const PROJ_OUT = path.join(ROOT, 'data', 'cfb_proj.json');
const GAMES_OUT = path.join(ROOT, 'data', 'cfb_games.json');
const SEASON = 2026;
const ARGS = new Set(process.argv.slice(2));
const OFFLINE = ARGS.has('--offline');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';

// ---- board rules ---------------------------------------------------------------------------
const RULES = { pfn: 89.5, on3: 95, avg: 88, frPfn: 80 };
// PFN grades FBS and FCS on separate curves (rankSeason restarts), so a 95 at Colgate is not a 95 at
// Georgia: FCS players are graded in a second pass (see FCS_* below) and translated onto the FBS scale.

// PFN board slug -> our position group, PFN's score label, matching ON3 position(s)
const POS = [
  { pfn: 'quarterback',      g: 'QB',   label: 'QB+',   on3: ['QB'] },
  { pfn: 'running-back',     g: 'RB',   label: 'RB+',   on3: ['RB'] },
  { pfn: 'wide-receiver',    g: 'WR',   label: 'WR+',   on3: ['WR'] },
  { pfn: 'tight-end',        g: 'TE',   label: 'TE+',   on3: ['TE'] },
  { pfn: 'offensive-line',   g: 'OL',   label: 'OLi',   on3: ['OT', 'IOL'] },
  { pfn: 'edge',             g: 'EDGE', label: 'EDGE+', on3: ['EDGE'] },
  { pfn: 'defensive-tackle', g: 'DL',   label: 'DT+',   on3: ['DL'] },
  { pfn: 'linebacker',       g: 'LB',   label: 'LB+',   on3: ['LB'] },
  { pfn: 'cornerback',       g: 'CB',   label: 'CB+',   on3: ['CB'] },
  { pfn: 'safety',           g: 'S',    label: 'SAF+',  on3: ['S'] },
];
const ON3_POS = ['QB', 'RB', 'WR', 'TE', 'OT', 'IOL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH'];
const ON3_TO_G = Object.fromEntries(POS.flatMap(p => p.on3.map(o => [o, p.g])));
ON3_TO_G.ATH = 'ATH';

// ---- FV model --------------------------------------------------------------------------------
// 1. Production: each season's PFN score as a z-score on that season's FBS curve, blended
//    Marcel-style over three seasons (5/4/3, by snaps) and regressed toward average with FV_K
//    weighted snaps, so five games in October can't outvote two full seasons.
// 2. Talent: the ON3 college grade, as a percentile of the FBS population at the position
//    (unranked players share the percentile band below the last ranked player).
// 3. Both turn into z-scores (inverse normal of the percentile); the composite is their
//    weighted mean plus an age term (younger at the same level = more projection), a frame term
//    (height/weight for the position) and a strength-of-schedule term.
// 4. FV is scarcity: within each position, the k-th best composite is compared to how many
//    players per NFL draft class reach each outcome tier, scaled by that position's share of
//    the 22 NFL starting spots. "+" marks talent well ahead of production in a young player.
const FV_WEIGHTS = { 2026: 5, 2025: 4, 2024: 3 };
// regression, in weighted snaps (~600 current-season snaps). Stat+ backtest (scripts/cfb_statplus_backtest.mjs,
// data/cfb_statplus_backtest.json: PFN 2019-22 final seasons against NFL AV): more regression predicts better at
// every tested position, r .488 -> .497 (offense) and .386 -> .389 (defense) going from 1500 to 3000, and up to
// .51 / .40 by 12000; 3000 takes most of it without burying a breakout in his first half-season. The 5/4/3
// season weights are within .01 of the best blend on either side of the ball
const FV_K = 3000;
// talent vs production: two-predictor regression weights, b1 = (r1 - r12 r2) / (1 - r12^2), with
// scouting-grade validity ~.70 (draft slot tracks NFL careers better than production does),
// production validity ~.62 (backtest, selection-corrected) and ~.5 between them -> .52 / .36,
// normalized to .6 / .4. The other feeders are smaller, capped adjustments on top.
// Weights measured against NFL outcomes (backtest, out of sample): production carries about twice the
// signal of recruiting pedigree (R .54 vs .33 alone); team strength adds ~.12, age ~.10. On3's college
// grade has no history to test, but it is a current scouting read (the closest thing to an NFL board),
// so it shares the load with production: talent .40, production .40, pedigree (247 composite, FV_HS)
// .15 (half when On3 grades the player, since its grade already folds pedigree in), team strength .05.
const FV_W = { on3: 0.40, pfn: 0.40 };
// production weight by position: how well Stat+ (the PFN score behind production) predicts NFL AV at each position
// (same backtest, 5/4/3 blend at FV_K: TE .52, WR .50, QB .48, RB .48, EDGE .40, LB .40, DT .37; mean .45), as
// 1 + (r / mean - 1) / 2, halfway to equal. OL, CB and S have PFN lines only from 2024, so they stay at 1
const FV_PROD_POS = { QB: 1.03, RB: 1.03, WR: 1.06, TE: 1.08, EDGE: 0.94, DL: 0.92, LB: 0.94 };
const FV_TEAM = 0.05;           // per SD of last season's SP+ for the player's team
// age on a curve: z = perYear x d + curve x d|d| for d years younger than the pivot, so the outliers move
// most (a producing 18-year-old gains ~.8, a 24-year-old loses ~.9); the young side is capped at capYoung,
// the old at capOld (each x the position's draft-age effect below)
// Backtest (nflverse drafts 2005-18, career AV against the pick's expectation, by draft age): the effect is
// linear on the young side (20: +4.6 AV, 21: +2.5, 22: +1.6) and steeper on the old (23: -1.6, 24: -2.9,
// 25: -6.8); a symmetric curve didn't beat linear in cross-validation. So the curve applies to the old tail
// only, and youth stays linear up to its cap (plus the class and first-year terms below).
const FV_AGE = { pivot: 21.0, perYear: 0.25, curve: 0.06, curveYoung: 0, capYoung: 1.1, capOld: 0.9 };
// class: development runway (years left before the draft, 5 minus years on campus, centred at 2.5) and a
// first-year bonus for freshmen already playing (150+ snaps or above-average production), scaled by how
// rare young contributors are at the position (below). With real birthdates, being young for the class
// counts again (up to a year either way): the user-requested double count of the age driver
const FV_CLASS = { perYear: 0.06, fr: 0.12, youngForClass: 0.1 };
// youth rarity: how uncommon first-year contributors are at the position (share of 150+ snap players
// in their first year, against all positions), as sqrt(pooled / position), clamped to [.75, 1.4]
const FV_RARE = { snaps: 150, lo: 0.75, hi: 1.4 };
// frame by age: weight is projected to 22 along the position's age-weight slope (measured across FBS
// players with birthdates, clamped to 0-8 lb a year), and frame counts more for younger players (x up to
// 1.6, +.2 a year under 21) since a young frame is more of a projection than a finished body
const FV_FRAME_AGE = { to: 22, perYear: 0.2, max: 1.6, slopeMax: 8 };
// health: a season-ending injury costs FV (lost development year, re-injury risk): -1, -2 for an ACL,
// Achilles or other major reconstruction
const FV_HEALTH = { season: -1, major: -2 };
// snap share: this season's snaps over the team's plays on that side of the ball (CFBD, garbage time out,
// so shares run a little high; capped at 1), PFN's own share for backs. Playing time is the coaches' read,
// worth a little on top of production: FV_SNAP.w per SD within the position (60+ snaps), capped
const FV_SNAP = { w: 0.08, cap: 0.12 };
const FV_QBR = 0.12;
// supporting cast: production partly reflects the talent around a player (Julian Sayin throwing to Jeremiah
// Smith). Cast = talent (On3 grade z; ungraded -1) of the players he works with, by snaps:
//   QB  .7 x his best target (top 3 WRs + top TE) + .3 x his line (top 5 OL)
//   WR/TE  .7 x his QB + .3 x the line;  RB  .7 x the line + .3 x the QB
// z'd within the position, then each run fits production (PFN z) = a + b1 x own talent + b x cast over the
// position's graded 150+ snap players. Talent, not production, measures the cast so a QB's numbers can't
// inflate his receivers' cast score and back. The fitted b is shrunk toward a prior (prior .15 SD of
// production per SD of cast, sd .10) by its standard error, and b x cast comes off his production term
// (FV_W.pfn) so the grade credits what he did beyond his context. October 2026 fit (QBs, n 73): own talent
// 1.02, cast -0.03 (se .10) on the talent measure: once a QB's own grade is known, his cast adds ~nothing,
// so the posterior is small (~.06). Measured by the best target's FV instead (partly circular: the QB's
// production is in it) the cast effect is .20; the prior sits between the two
const FV_CAST = { prior: 0.15, priorSd: 0.10, snaps: 150, min: 25, cap: 0.4,
  spec: { QB: [[['WR', 3, 'max'], ['TE', 1, 'max']], 0.7, [['OL', 5, 'mean']], 0.3], WR: [[['QB', 1, 'max']], 0.7, [['OL', 5, 'mean']], 0.3],
          TE: [[['QB', 1, 'max']], 0.7, [['OL', 5, 'mean']], 0.3], RB: [[['OL', 5, 'mean']], 0.7, [['QB', 1, 'max']], 0.3] } };
let castFit = {};
// actual vs expected (scripts/cfb_oe.mjs): each play's gain against what down, distance, field position, the
// defense and, on throws, the other half of the pass predict, as ridge effects (rushing yards over expected, ANY/A
// a dropback over expected crediting passer and target separately, completion % over expected). The FV term is the
// context correction: (over expected - his raw numbers, both shrunk the same) / SD of over expected at the
// position, so a QB whose targets carried his numbers (Julian Sayin and Jeremiah Smith) gives some back and one
// whose targets let him down gains. Seasons blend 5/4 by plays, like production.
// Weights: FV_W.pfn x the share of the production signal the over-expected version carries x 1/2. Share from the
// backtest (scripts/cfb_oe_backtest.mjs, data/cfb_oe_backtest.json; ESPN play-by-play 2017-26, nflverse drafts
// 2018-23): regress the outcome on raw and over expected together, share = b_oe / (b_raw + b_oe) clamped to 0-1,
// over next season's raw rate, the same for transfers, and NFL weighted AV a season (counted twice):
//   rushing   share .97 (partial r of RYOE beyond raw: NFL +.29, next season +.08, transfers +.02); halved again
//             because PFN's grades already adjust backs for opponents, which is most of a back's context
//   CPOE      share 1 (NFL +.22, next season +.16, transfers +.16)
//   dropback  share .5 (next season +.14, transfers +.22, NFL -.06: drafts still follow raw production)
//   targets   share .38 (transfers +.09, next season +.03, NFL -.13); catch rate over expected never beat raw: none
// The half is credibility: the history has raw box-score production where the board has PFN grades.
const FV_OE = { k: { QB: { drop: 0.1, cmp: 0.2 }, RB: { rush: 0.1 }, WR: { tgt: 0.08 }, TE: { tgt: 0.08 } },
  min: { rush: 30, drop: 60, cmp: 50, tgt: 15 }, cap: 0.2 };
// inverse of a 3x3 matrix (null when singular)
function inv3(m) {
  const [[a, b, c], [d, e, f], [g, h, i]] = m, A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-9) return null;
  return [[A, -(b * i - c * h), b * f - c * e], [B, a * i - c * g, -(a * f - c * d)], [C, -(a * h - b * g), a * e - b * d]].map(r => r.map(v => v / det));
}
const ESPN_GROUP = p => ({ DE: 'EDGE', DT: 'DL', NT: 'DL', DL: 'DL', OLB: 'LB', ILB: 'LB', MLB: 'LB', LB: 'LB', CB: 'CB', DB: 'CB', S: 'S', FS: 'S', SS: 'S', QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', PK: 'K', K: 'K', P: 'P' })[p] || null;
const OFF_G = new Set(['QB', 'RB', 'WR', 'TE', 'OL']);
// draft-age effect by position (nflverse 2010-19, outcome-z per year younger at the same pick:
// WR .21, EDGE .18, OL .14, RB .13, pooled .11, QB .07, CB .02), shrunk halfway to the pooled effect
const FV_AGE_POS = { WR: 1.45, EDGE: 1.3, OL: 1.15, RB: 1.1, QB: 0.8, CB: 0.6 };
// frame: z of height and weight against FBS players at the position, weighted by how much the
// NFL pays for each at that spot (CB/QB height, OL/EDGE/DL mass, RB weight). Capped at ±FV_SIZE_CAP.
// [height, weight, BMI] per SD, for the position. Calibration found no size effect once draft slot is
// held constant, but FV predicts careers before the draft: size moves outcomes largely through draft
// capital and opportunity (small QBs go later and start less), so the unconditional effect is the
// right one. Mass helps backs and linemen, leanness receivers and corners; QBs need height and frame.
const FV_SIZE = { QB: [0.15, 0.1, 0.05], RB: [0, 0.05, 0.1], WR: [0.1, 0.05, -0.05], TE: [0.1, 0.05, 0], OL: [0.1, 0.05, 0.05],
                  EDGE: [0.1, 0.1, 0], DL: [0.05, 0.05, 0.1], LB: [0.05, 0.05, 0], CB: [0.15, 0, -0.05], S: [0.05, 0.05, 0] };
const FV_SIZE_CAP = 0.3;
const FV_SOS = { perSd: 0.1, cap: 0.2 };   // PFN strength of schedule, z within the position
// position-specific efficiency stats from PFN's line, beyond its composite score: [name, weight
// (sign = direction), optional getter for a derived rate]. z within the position (FBS, 60+ snaps),
// regressed by snaps (n / (n + 150)). At QB, RB, WR, TE, EDGE, DT and LB the NFL-outcome fit has replaced them
// (FV_BADGE below): none of the old stats added to production there out of sample, so those lists are empty.
// OL, CB and S keep the provisional weights until PFN has enough history at those spots to test
const r1 = x => Math.round(x * 10) / 10;
const nz = v => (typeof v === 'number' && isFinite(v) ? v : null);
const FV_STATS = {
  QB: [], RB: [], WR: [], TE: [], EDGE: [], DL: [], LB: [],
  OL: [['prsRate', -1], ['skAllwd', -0.5]],
  CB: [['fi', 1], ['catchAllowed', -0.7, r => nz(r.catch)], ['rtg', -0.5]],
  S: [['fi', 1], ['tacklePct', 0.5, r => nz(r.mt) != null ? 100 - r.mt : null], ['rtg', -0.5]],
};
const FV_STAT = { w: 0.15, cap: 0.3 };
// badges that predict NFL careers beyond production (scripts/cfb_badge_backtest.mjs, data/cfb_badge_backtest.json:
// PFN final seasons 2019-22 against NFL AV, each badge's stat as the board measures it, regressed by its own k).
// A badge counts only if its partial r holding production fixed is positive with t >= 2 AND it improves the
// out-of-sample fit (leave one season out). Weight = FV_W.pfn x b_badge / b_prod (standardized, fitted jointly) x 1/2,
// on the badge stat's z at the position. Passed: QB Deep Ball (partial .17, t 2.7) and Accurate (.15, t 2.4), RB
// Pass Catcher (.25, t 4.6, +4.1 pts of out-of-sample R^2), TE Pass Catcher (.17, t 3.1), DT Run Stopper (.11,
// t 2.3), LB Tackler (missed-tackle rate, .19, t 4.6). Nothing at WR or EDGE adds to production, and neither do RB
// rushing efficiency or TE blocking. Negative drivers face the same test: QB Scrambler (partial -.12) misses at
// t -1.95, and with Deep Ball and Accurate in the model its beta halves to -.06, so it gets no weight
const FV_BADGE = { w: { QB: { accurate: 0.13, deep: 0.2 }, RB: { catcher: 0.13 }, TE: { catcher: 0.24 }, DL: { runstop: 0.07 }, LB: { tackler: 0.1 } }, cap: 0.3 };
// stat weights scale with how well each stat repeats: its season-to-season correlation for the same player
// (PFN lines 2019 on, both seasons at 150+ snaps' worth of volume), as r / FV_REL.pivot, clamped. Pressure
// rate repeats (r ~.5), sack conversion doesn't (~0), so pressure carries the pass rush. Measured each run.
const FV_REL = { pivot: 0.35, lo: 0.1, hi: 1.5, minVol: 150, minPairs: 40 };
let statRel = {};
function statReliability(pfnAll) {
  const out = {};
  for (const [g, list] of Object.entries(FV_STATS)) {
    const rows = (pfnAll[g] || []).filter(r => volume(r, false, g) >= FV_REL.minVol), by = {};
    for (const r of rows) (by[r.id] ||= {})[r.season] = r;
    out[g] = {};
    for (const [f, , get] of list) {
      const val = r => { const v = get ? get(r) : r[f]; return typeof v === 'number' && isFinite(v) ? v : null; };
      const xs = [], ys = [];
      for (const v of Object.values(by)) for (const sn of Object.keys(v).map(Number)) if (v[sn + 1]) { const a = val(v[sn]), b = val(v[sn + 1]); if (a != null && b != null) { xs.push(a); ys.push(b); } }
      if (xs.length < FV_REL.minPairs) { out[g][f] = null; continue; }
      const n = xs.length, mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n;
      let sxy = 0, sxx = 0, syy = 0; xs.forEach((x, i) => { sxy += (x - mx) * (ys[i] - my); sxx += (x - mx) ** 2; syy += (ys[i] - my) ** 2; });
      out[g][f] = sxx && syy ? Math.round(sxy / Math.sqrt(sxx * syy) * 100) / 100 : null;
    }
  }
  return out;
}
// play-by-play rates (scripts/cfb_pbp.mjs) that hold up in a split-half test this season (odd vs even games,
// reliability >= FV_PBP.minRel): rushing EPA per carry for backs, explosive catches per target for receivers
// and tight ends. Each: z within the position, regressed by volume, x its reliability.
// Red zone stays out (shown in the report only). Backtest (cfbfastR 2014-20 college play-by-play against
// nflverse 2015-21 drafts, AV per season, controls log pick + production + EPA): red-zone TD rate barely
// repeats (year to year r .08 RB, .11 WR/TE; NFL RBs .10) and adds nothing past slot and production
// (partial r .06 RB n=137, .00 WR/TE n=276); red-zone share repeats (.29-.35) but is a stand-in for workload
// (partial r .00-.02 once production is in). RB role by down: no signal past slot and production either.
const FV_PBP = { w: 0.1, cap: 0.15, minRel: 0.25,
  stats: { RB: [['rEpaCar', a => a.car >= 20 ? a.rEpa / a.car : null, a => a.car / (a.car + 40)]],
    WR: [['xRecTgt', a => a.tgt >= 12 ? a.cExp / a.tgt : null, a => a.tgt / (a.tgt + 24)]],
    TE: [['xRecTgt', a => a.tgt >= 10 ? a.cExp / a.tgt : null, a => a.tgt / (a.tgt + 24)]] } };
const FV_HS = { w: 0.15, cap: 0.3 };
// breakout timing: bonus by the college season of the first top-15% year (1st, 2nd, 3rd, 4th+),
// a small debit for a 4th-year+ player with a track record who never got there; bigger for skill spots
const FV_BREAKOUT = [0.15, 0.1, 0.03, 0];
const FV_BREAK_POS = { WR: 1.3, TE: 1.3, RB: 1.3, QB: 0.8, OL: 0.7, CB: 1, S: 1, EDGE: 1, DL: 1, LB: 1 };        // On3 high school grade: recruiting pedigree, z over graded players
const FV_COHORTS = 4;         // classes in the playing population
const FV_POS_STRENGTH = 0.5;  // how much of a position's talent gap vs other positions carries into FV
let posStrength = {}, youthRarity = {};
// prospect risk: the composite is a noisy read of NFL talent, so grade the expected talent, not the
// observed rank. With a standardized composite c, expected talent is r * c (normal prior and noise),
// and its percentile sets an expected rank: N * (1 - Phi(r * c)). r = 1 would trust the board
// completely; lower r pulls everyone toward the middle of the scale.
// reliability: the out-of-sample correlation of the pre-draft composite with NFL career tier (backtest,
// all FBS, each class predicted from the others), +.05 for On3 and PFN, which it didn't have; OL's .32
// reflects that box scores have no OL production, so OL uses .6 (PFN and On3 grade blocking)
const FV_RELIABILITY = Object.fromEntries(Object.entries(CAL.reliability).map(([g, r]) => [g, g === 'OL' ? 0.6 : Math.round((r + 0.05) * 100) / 100]));
// cumulative players per draft class at or above each grade, all positions, measured on the 2010-19
// drafts (nflverse): 80 = 3+ All-Pro, 75 = 2, 70 = 1, 65 = 3+ Pro Bowls, 60 = 1, 55/50/45 = 6/4/2
// seasons as a starter, 40 = 48+ games, 35 = 16+, 30 = drafted. Undrafted players aren't in the
// data, so the 30-55 counts carry an allowance for undrafted starters (~10-25%).
const FV_TIERS = [[80, 4], [75, 6], [70, 12], [65, 19], [60, 34], [55, 55], [50, 80],
                  [45, 115], [40, 160], [35, 230], [30, 320]];
// ---- FCS ---------------------------------------------------------------------------------------
// FCS players are graded in their own world first (every input measured against FCS players at the
// position, PFN's FCS curve for production), then the composite is translated onto the FBS scale and
// graded against the same NFL scarcity tiers. Measured on CFBD box scores 2022-26 (the seasons with every
// FCS game; earlier years only carry FCS games against FBS teams) and nflverse drafts 2015-25:
//   - FCS supplies 4.8% of draft picks, 4.3% of 2+ year starters and 4.2% of Pro Bowlers per class, and
//     its picks match FBS picks at the same slot (career AV +0.4, p .84): the NFL prices them fairly.
//   - the average FCS team is ~9 points a game worse than the average FBS team (SRS over FBS+FCS games,
//     -1.1 to -1.2 FBS SDs); movers' next-season production puts the player-level gap at ~1.2-1.4 SDs.
//   - move-up (on an FBS roster the next season, 2022->26, 314 players; out-of-sample AUC .73):
//     production .73 per SD, conference strength .27, team strength .16, recruiting .15, youth .42 a year.
// FCS_TR: the FCS composite in FBS units, off + slope x z above the FCS mean (1 below it: the bottom of the FCS
// is as spread out as it looks). slope: how much of an FCS production SD carries to FBS: movers' next-season production (FCS->FBS movers' slope over FBS stayers', n 229) is .28 (90% CI .03-.55),
// shaded up to .5 because production ranks FCS players as well as FBS players for the draft (logit slope 1.14 vs
// 1.03). off is then set (node scripts/fetch_cfb.mjs --offline --calibrate-fcs) so FCS players hold the FCS draft
// share of the board (FV 30+ 4.8%). The compressed slope leaves few FCS players above 45 (FCS's share of 2+ year
// NFL starters is ~4%, but which FCS players get there is far less predictable), and the top thin, as FCS's share
// of early picks is (4.9% of all picks, 2.9% of rounds 1-3, 1.7% of first-rounders, 2015-25)
const FCS_TR = { off: -0.4, slope: 0.5 };
// the FCS composite: the On3 talent slot becomes level of play (team and conference SRS, z within FCS),
// weighted against production as in the move-up fit (production .40 = .73 logit/SD)
const FCS_W = { team: 0.087, conf: 0.149, hs: 0.08 };
// FBS seasons in an FCS player's history count on the FCS curve at z + shift (FBS-to-FCS movers' next
// season, n 51: +0.37; the symmetric division gap: ~+1.2)
const FCS_HIST = { shift: 0.8 };
// move-up odds: P(on an FBS roster next season), the fitted logit
let FCS_GAP = 9;     // points a game, set each run from the SRS
const FCS_UP = { c: -2.376, prod: 0.727, team: 0.158, conf: 0.271, young: 0.423, hs: 0.145, flag: 0.3 };
const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const STARTER_TOTAL = Object.values(STARTERS).reduce((a, b) => a + b, 0);

// ---- helpers ---------------------------------------------------------------------------------
const sleep = ms => new Promise(r => setTimeout(r, ms));
const cachePath = name => path.join(CACHE, name);
const readCache = name => JSON.parse(fs.readFileSync(cachePath(name), 'utf8'));
const writeCache = (name, v) => fs.writeFileSync(cachePath(name), JSON.stringify(v));
const hasCache = name => fs.existsSync(cachePath(name));

async function get(url, as = 'text') {
  for (let i = 0; ; i++) {
    try {
      const r = await fetch(url, { headers: { 'user-agent': UA } });
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return as === 'json' ? await r.json() : await r.text();
    } catch (e) {
      if (i >= 3) throw e;
      await sleep(2000 * 2 ** i);
    }
  }
}

export function norm(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '').replace(/[^a-z0-9]/g, '');
}

// scan a JSON value that starts at s[i] and return its end index
function jsonEnd(s, i) {
  let depth = 0, inStr = false;
  for (let j = i; j < s.length; j++) {
    const c = s[j];
    if (inStr) { if (c === '\\') j++; else if (c === '"') inStr = false; continue; }
    if (c === '"') inStr = true;
    else if (c === '{' || c === '[') depth++;
    else if (c === '}' || c === ']') { if (--depth === 0) return j + 1; }
  }
  throw new Error('unterminated JSON');
}

// ---- PFN -------------------------------------------------------------------------------------
async function fetchPfn() {
  const out = {};
  for (const p of POS) {
    const html = await get(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${p.pfn}`);
    const chunks = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)]
      .map(m => JSON.parse(m[1]));
    const s = chunks.find(c => c.includes('"packed":'));
    if (!s) throw new Error(`PFN ${p.pfn}: no packed data (page layout changed?)`);
    const i = s.indexOf('"packed":') + 9;
    const packed = JSON.parse(s.slice(i, jsonEnd(s, i)));
    out[p.g] = packed.rows.map(r => Object.fromEntries(packed.cols.map((c, k) => [c, r[k]])));
    console.log(`PFN ${p.label.padEnd(5)} ${out[p.g].length} player-seasons`);
  }
  return out;
}

// PFN industry consensus big board for the next draft: one record per prospect with the average rank
// and each analyst's rank, in the page's RSC payload
async function fetchConsensus() {
  const html = await get('https://www.profootballnetwork.com/nfl-draft-hq/industry-consensus-big-board');
  const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).join('');
  const out = {};
  for (const m of s.matchAll(/\{"id":"/g)) {
    try { const d = JSON.parse(s.slice(m.index, jsonEnd(s, m.index))); if (d.avgRank != null && d.name) out[d.id] = d; } catch {}
  }
  const list = Object.values(out).sort((a, b) => a.rank - b.rank);
  if (list.length < 50) throw new Error(`consensus board: only ${list.length} prospects (page layout changed?)`);
  const rows = list.map(d => ({ rank: d.rank, name: d.name, pos: d.position, school: d.school, avg: d.avgRank, ranks: { ...(d.analystRanks || {}) } }));
  // Tankathon's NFL big board (~570 prospects) as an eighth board: folded into each average, and prospects
  // only it ranks join with one board (their consensus weight scales with the boards that rank them)
  // and PFF's big board (top 75, with each player's PFF grade this season, free on the board) as a ninth
  for (const [key, fetcher] of [['tankathon', fetchTankathon], ['pff', fetchPffBoard]]) try {
    const tk = await fetcher(), byName = {};
    for (const r of rows) (byName[norm(r.name)] ||= []).push(r);
    for (const t of tk) {
      const c = byName[norm(t.name)] || [], r = c.length > 1 ? c.find(x => norm(x.school) === norm(t.school)) || c[0] : c[0];
      if (r) { const n = Object.keys(r.ranks).length || 1; r.avg = (r.avg * n + t.rank) / (n + 1); r.ranks[key] = t.rank; if (t.grade != null) r.pffGrade = t.grade; }
      else rows.push({ name: t.name, pos: t.pos, school: t.school, avg: t.rank, ranks: { [key]: t.rank }, ...(t.grade != null ? { pffGrade: t.grade } : {}) });
    }
    console.log(`consensus: + ${tk.length} ${key}`);
  } catch (e) { console.log(`${key}: ${e.message.slice(0, 100)}`); }
  rows.sort((a, b) => a.avg - b.avg).forEach((r, i) => { r.rank = i + 1; r.avg = Math.round(r.avg * 10) / 10; });
  return rows;
}
async function fetchPffBoard() {
  const d = JSON.parse(await get(`https://www.pff.com/api/college/big_board?season=${SEASON + 1}&version=1`));
  const out = (d.players || []).filter(p => p.pff_rank).map(p => ({ rank: p.pff_rank, name: p.name, pos: p.position, school: p.college || p.team?.city,
    grade: p.grade_1?.value || null }));
  if (out.length < 30) throw new Error(`only ${out.length} prospects`);
  return out;
}
async function fetchTankathon() {
  const page = await get('https://www.tankathon.com/nfl/big_board');
  // the page repeats prospects in its other views (by school, by position): only the big board's own list
  const i = page.indexOf('id="big-board"'), j = page.indexOf('class="mock-rows"', page.indexOf('class="mock-rows"', i) + 20);
  const html = i >= 0 ? page.slice(i, j > i ? j : undefined) : page;
  const out = [], seen = new Set();
  for (const m of html.matchAll(/class="mock-row-name">([^<]+)<\/div><div class="mock-row-school-position">([^|<]+)\|\s*([^<]+?)\s*<\/div>/g))
    if (!seen.has(m[1].trim()) && seen.add(m[1].trim())) out.push({ rank: out.length + 1, name: m[1].trim().replace(/&#39;/g, "'").replace(/&amp;/g, '&'), pos: m[2].trim(), school: m[3].trim().replace(/&amp;/g, '&') });
  if (out.length < 100) throw new Error(`only ${out.length} prospects`);
  return out;
}

// ---- ON3 -------------------------------------------------------------------------------------
async function loadPlaywright() {
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) {
    try { return await import(spec); } catch {}
  }
  throw new Error('ON3 needs playwright: npm i -D playwright && npx playwright install chromium');
}

async function fetchOn3() {
  const { chromium } = await loadPlaywright();
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch(proxy ? { proxy: { server: proxy } } : {});
  const ctx = await browser.newContext({ userAgent: UA, ignoreHTTPSErrors: !!proxy });
  const page = await ctx.newPage();
  // skip images, fonts, ads: only the server-rendered __NEXT_DATA__ is needed
  await page.route(/\.(png|jpe?g|svg|gif|webp|woff2?|css)(\?|$)|doubleclick|amazon-adsystem|googletag|ketch|confiant|recurly/,
    r => r.abort());
  const nextData = async url => {
    for (let i = 0; ; i++) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
        const t = await page.evaluate(() => document.getElementById('__NEXT_DATA__')?.textContent);
        if (!t) throw new Error('no __NEXT_DATA__ (blocked?)');
        return JSON.parse(t).props.pageProps;
      } catch (e) {
        if (i >= 3) throw e;
        console.log(`  retry ${url}: ${e.message.slice(0, 80)}`);
        await sleep(3000 * 2 ** i);
      }
    }
  };
  const rows = [];
  for (const pos of ON3_POS) {
    for (let pg = 1, pages = 1; pg <= pages; pg++) {
      const url = `https://www.on3.com/college/rankings/player/football/${SEASON}/?position=${pos.toLowerCase()}${pg > 1 ? `&page=${pg}` : ''}`;
      const { playerRankings: pr } = await nextData(url);
      pages = pr.pagination.pageCount;
      for (const it of pr.list) {
        const p = it.person;
        rows.push({
          name: p.name, slug: p.slug, pos: it.positionAbbreviation || p.positionAbbreviation,
          grade: p.rating?.rating ?? it.ratings?.find(r => r.type === 'On3')?.rating ?? null,
          posRank: it.positionRank, overallRank: it.overallRank, stars: p.rating?.stars,
          classYear: p.classYear, classRank: p.classRank, ht: p.formattedHeight, wt: p.weight,
          team: it.collegeTeam?.fullName || null, teamSlug: it.collegeTeam?.slug || p.status?.committedOrganizationSlug,
          teamLogo: it.collegeTeam?.assetUrl || null, color: it.collegeTeam?.primaryColor || null,
          hsGrade: it.highSchoolRating?.rating ?? null, hsStars: it.highSchoolRating?.stars ?? null,
          hsRank: it.highSchoolRating?.nationalRank ?? null,
          transfer: !!p.status?.isTransfer, headshot: p.defaultAssetUrl || null, nil: it.nilValue ?? null,
        });
      }
      console.log(`ON3 ${pos.padEnd(4)} page ${pg}/${pages}`);
    }
  }
  await browser.close();
  return rows;
}

// ---- ESPN ------------------------------------------------------------------------------------
async function fetchEspn(teamNames) {
  const all = (await get('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000', 'json'))
    .sports[0].leagues[0].teams.map(t => t.team);
  const teams = {};
  for (const t of all) {
    teams[t.id] = { id: t.id, name: t.location, full: t.displayName, abbr: t.abbreviation, color: t.color,
                    logo: t.logos?.[0]?.href || `https://a.espncdn.com/i/teamlogos/ncaa/500/${t.id}.png` };
  }
  const want = new Set(teamNames.map(n => teamIndex(teams).resolve(n)).filter(Boolean));
  const rosters = await fetchRosters(want, teams);
  console.log(`ESPN ${Object.keys(rosters).length} rosters`);
  return { teams, rosters };
}
async function fetchRosters(want, teams) {
  const rosters = {};
  for (const id of want) {
    try {
      const d = await get(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/${id}/roster?limit=200`, 'json');
      const hc = d.coach?.[0];
      if (hc && teams[id]) teams[id].coach = `${hc.firstName} ${hc.lastName}`.trim();
      rosters[id] = d.athletes.flatMap(g => g.items).map(a => ({
        id: a.id, name: a.fullName, pos: a.position?.abbreviation, ht: a.displayHeight, wt: a.weight,
        cls: a.experience?.abbreviation, years: a.experience?.years, dob: a.dateOfBirth || null,
        headshot: a.headshot?.href || null, home: a.birthPlace ? [a.birthPlace.city || null, a.birthPlace.state || null, a.birthPlace.country || null] : null,
      }));
    } catch (e) { console.log(`ESPN roster ${id}: ${e.message}`); }
    await sleep(150);
  }
  return rosters;
}

// school names differ between sources; resolve everything to an ESPN team id
const TEAM_ALIAS = {
  'miami(fl)': 'Miami', mississippi: 'Ole Miss', northcarolinastate: 'NC State', connecticut: 'UConn',
  louisianamonroe: 'UL Monroe', usf: 'South Florida', appalachianstate: 'App State',
  floridainternational: 'Florida International', hawaii: "Hawai'i", sanjosestate: 'San José State',
  fiugoldenpanthers: 'Florida International', connecticuthuskies: 'UConn', usfbulls: 'South Florida',
  appalachianstatemountaineers: 'App State', samhoustonstatebearkats: 'Sam Houston', delawarefightinbluehens: 'Delaware',
  // FCS (PFN's names)
  uni: 'Northern Iowa', stthomasmn: 'St. Thomas', gramblingstate: 'Grambling', southeasternlouisiana: 'SE Louisiana',
  etsu: 'East Tennessee State', sfa: 'Stephen F. Austin', uiw: 'Incarnate Word', liu: 'Long Island University',
  penn: 'Pennsylvania', centralconnecticutstate: 'Central Connecticut',
};
function teamIndex(teams) {
  const byLoc = {}, byFull = {};
  for (const t of Object.values(teams)) {
    (byLoc[norm(t.name)] ||= []).push(t);
    byFull[norm(t.full)] = t;
  }
  return {
    resolve(name) {
      if (!name) return null;
      const n = norm(name), raw = name.toLowerCase().replace(/\s+/g, '');
      const alias = TEAM_ALIAS[raw] || TEAM_ALIAS[n];
      if (alias) return byLoc[norm(alias)]?.[0]?.id ?? null;
      if (byFull[n]) return byFull[n].id;
      // pick the FBS-looking team when a location is shared (lowest id = oldest program entry)
      const hits = byLoc[n];
      return hits?.length ? hits.sort((a, b) => a.id - b.id)[0].id : null;
    },
  };
}

// sample size in snaps. PFN's current season carries snapsQ (or snaps); past seasons only carry
// games for the skill positions and the secondary (see SNAPS_PER_GAME). strict: snaps or nothing.
function volume(r, strict = false, g = null) {
  const n = v => (typeof v === 'number' && isFinite(v) ? v : null);
  // PFN's FCS interior-line board carries the score only: a nominal 150 snaps (regressed about halfway)
  if (r.division === 'FCS' && n(r.snapsQ) == null && n(r.snaps) == null && n(r.gp) == null && n(r.gamesQ) == null) return 150;
  const sn = n(r.snapsQ) ?? n(r.snaps);
  if (strict || sn != null) return sn ?? null;
  return (n(r.gp) ?? n(r.gamesQ) ?? 0) * (SNAPS_PER_GAME[g] ?? 55);
}
// past seasons carry games, not snaps, at the skill spots and in the secondary: a typical starter's
// snaps per game there, so a past season doesn't outweigh this one by the wrong units
const SNAPS_PER_GAME = { QB: 65, RB: 30, WR: 40, TE: 40, CB: 55, S: 55, OL: 65, EDGE: 50, DL: 45, LB: 55 };

// ---- model -----------------------------------------------------------------------------------
// standard normal CDF (Abramowitz-Stegun 7.1.26)
function phi(z) {
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
  const e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2);
  return z >= 0 ? (1 + e) / 2 : (1 - e) / 2;
}

// Acklam's inverse normal CDF
function probit(p) {
  p = Math.min(Math.max(p, 1e-4), 1 - 1e-4);
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const lo = 0.02425;
  if (p < lo) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p > 1 - lo) { const q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  const q = p - 0.5, r = q * q;
  return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}

const CLASS_NAMES = ['Fr', 'So', 'Jr', 'Sr', 'Gr'];
// eligibility class for fall SEASON from the high school class year and the redshirt flag
function classFrom(classYear, redshirt) {
  const years = SEASON + 1 - classYear;               // seasons on campus, this one included
  const elig = Math.max(1, years - (redshirt ? 1 : 0));
  return { years, elig, label: (redshirt ? 'RS-' : '') + CLASS_NAMES[Math.min(elig, 5) - 1] };
}

function ageOn(dob, when) {
  return Math.round(((when - new Date(dob)) / (365.2425 * 864e5)) * 10) / 10;
}

// FV from an expected rank, per position, against measured outcome counts: CAL.tiers[g] holds the mean
// number of players per draft class at or above each grade at that position (drafts 2012-18: QBs ~2.9
// Pro Bowlers a class, OL ~6.4, TEs ~1.7). A rank between two anchors interpolates on a log scale; the
// bottom anchor (20) is the whole graded pool at the position per class.
// The measured counts are noisy at the top (one Pro Bowl more or less in seven drafts moves a tier), so
// each position's curve is smoothed: log-linear in FV over 30-55, where every position has plenty of
// players; above 55 it falls at the pooled rate of all positions (-0.115 log points per FV point,
// measured over 60-80), and then is scaled by positional value: an elite RB or LB is worth less on the
// NFL draft board than an equally rare QB, EDGE or tackle (APY and draft-slot value by position).
const FV_POS_VALUE = { QB: 1, OL: 1, EDGE: 1, WR: 1, CB: 1, DL: 0.7, TE: 0.75, S: 0.75, LB: 0.7, RB: 0.7 };
// the 35-50 tiers are games-played thresholds, which undercount QBs: one plays, so a starter-quality
// backup can sit for years. QB counts there x1.6, easing back to the measured curve by 55.
const FV_QB_MID = 1.6;
// scouting consensus: PFN's industry consensus big board (the average of seven analyst boards: PFN,
// CBS, ESPN, James Foster, NBC, The Athletic, Yahoo). In the backtest (2015-19 drafts, players on a
// pre-draft board) consensus rank alone explained 34% of NFL outcome (R .52) against 4% for box-score
// production and recruiting, so it is blended into FV rather than added to the composite: the rank
// maps onto the FV scale by the measured per-class counts (rank 2.7 -> 80, 27 -> 60, 126 -> 45:
// 80 - 8.7 ln(rank / 2.7)), weighted CONS_W at full coverage, less when fewer analysts rank him.
const CONS_W = 0.35, CONS_BOARDS = 9;   // PFN's seven analyst boards + Tankathon's and PFF's big boards
const RISER = { gap: 6, unranked: 55 };
// xNIL program budgets (football, per season) and the fitted split (see the xNIL block in build())
// FCS programs: no revenue sharing at almost every FCS school, so NIL is collective and booster money only,
// ~$0.4M a program (an assumption, scaled like the FBS budgets by level: x e^(.3 z) on the FCS team SRS)
const XNIL = { p4: 20e6, g5: 3e6, fcs: 0.4e6, fcsMove: 0.4, tilt: 0.3, k: 1.1 };
// FCS NIL discount at equal FV: FCS median xNIL / FBS median xNIL per 5-point FV tier (both with 3+ players),
// overall = geometric mean of the tier ratios weighted by FCS players in the tier
const nilDiscount = (fcs, fbs) => {
  const tiers = {}; let lw = 0, n = 0;
  for (const [t, c] of Object.entries(fcs || {})) {
    const b = fbs?.[t]; if (!b?.p50 || !c.p50) continue;
    const r = c.p50 / b.p50; tiers[t] = Math.round(r * 1000) / 1000; lw += c.n * Math.log(r); n += c.n;
  }
  return { tiers, all: n ? Math.round(Math.exp(lw / n) * 1000) / 1000 : null, n };
};
let nilFit = {}, nilMarket = null;      // nilMarket: the FBS price curves, reused to price FCS players
const consFV = avg => Math.max(30, Math.min(80, 80 - 8.7 * Math.log(Math.max(1, avg) / 2.7)));
const FV_TOP_SLOPE = -0.115;
const TIERS = Object.fromEntries(Object.entries(CAL.tiers).map(([g, a]) => {
  const pts = a.filter(([f, n]) => f >= 30 && f <= 55 && n > 0).map(([f, n]) => [f, Math.log(n)]);
  const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length, my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const b = pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  const at = f => f <= 55 ? Math.exp(my + b * (f - mx)) : Math.exp(my + b * (55 - mx) + FV_TOP_SLOPE * (f - 55));
  const pv = f => (1 - (1 - (FV_POS_VALUE[g] ?? 1)) * Math.min(1, Math.max(0, (f - 50) / 10)))
    * (g === 'QB' ? 1 + (FV_QB_MID - 1) * Math.min(1, Math.max(0, (55 - f) / 10)) : 1);
  return [g, [80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30].map(f => [f, Math.round(at(f) * pv(f) * 1000) / 1000])];
}));
function fvFromRank(rankPerClass, g, poolPerClass) {
  const anchors = [...(TIERS[g] || [])].map(([f, n]) => [f, n]);
  anchors.push([20, Math.max(poolPerClass, (anchors.at(-1)?.[1] ?? 1) * 2)]);
  for (let i = 1; i < anchors.length; i++) anchors[i][1] = Math.max(anchors[i][1], anchors[i - 1][1] * 1.08);   // strictly rising
  const x = Math.log(rankPerClass);
  if (x <= Math.log(anchors[0][1])) return anchors[0][0];
  for (let i = 1; i < anchors.length; i++) {
    const [f0, n0] = anchors[i - 1], [f1, n1] = anchors[i];
    if (x <= Math.log(n1)) return Math.round(f0 + (f1 - f0) * (x - Math.log(n0)) / (Math.log(n1) - Math.log(n0)));
  }
  return 20;
}

// NFL frame: FV points from the draft-slot effect of size against drafted players at the position
// (combine 2010-25): below the 10th percentile costs per SD short, between p10 and p90 a small slope,
// above p90 (EDGE weight, RB/TE height) costs too. Halved: size moves draft slot more than careers.
function frameFV(p) {
  const key = p.g === 'OL' ? (/T$/.test(p.pfnPos || '') ? 'OT' : 'IOL') : p.g, n = CAL.size[key];
  if (!n || !p.htIn || !p.wtLb) return 0;
  let fv = 0;
  for (const [m, x] of [['ht', p.htIn], ['wt', p.wtLb]]) {
    const q = n[m], h = n.hinge || {};
    if (!q) continue;
    if (x < q.p10) fv -= Math.abs(h[m + '_lo'] ?? 0) * (q.p10 - x) / q.sd;
    else if (x > q.p90) fv += (h[m + '_hi'] ?? 0) < 0 ? h[m + '_hi'] * (x - q.p90) / q.sd : 0;
    else fv += Math.max(0, h[m + '_mid'] ?? 0) * (x - q.p50) / q.sd * 0.5;
  }
  fv = Math.max(-8, Math.min(3, fv * 0.5));
  // an edge rusher far below NFL edge weight (10+ lb under the 10th percentile, 244) projects to an off-ball or
  // rush-linebacker role at the next level: -0.25 FV a pound past that, up to -5
  if (p.g === 'EDGE') fv += -Math.min(5, Math.max(0, n.wt.p10 - 10 - p.wtLb) * 0.25);
  return fv;
}

// div: which division's players to grade ('FBS' or 'FCS'). other: the other division's pool ({ n: players per
// position, posShift }) so both grade against one merged NFL scarcity scale. ctx (FCS): team and conference
// strength by ESPN team id. recByName: recruits keyed by name + school (most FCS recruits have no athlete id).
function build({ pfn, on3, espn, manual, dobStore = {}, recruits = {}, recByName = {}, teamSp = {}, consensus = [], health = {}, teamPlays = {}, qbr = {}, pbp = {}, pbpRel = {}, pbpDowns = {}, oe = {}, div = 'FBS', other = null, ctx = {} }) {
  const FCS = div === 'FCS';
  statRel = statReliability(pfn);
  const asof = new Date();
  const idx = teamIndex(espn.teams);
  const rosterByTeam = {};
  for (const [tid, list] of Object.entries(espn.rosters)) {
    rosterByTeam[tid] = {};
    for (const a of list) (rosterByTeam[tid][norm(a.name)] ||= []).push(a);
  }
  const espnFind = (tid, name) => rosterByTeam[tid]?.[norm(name)]?.[0] || variant(espn.rosters[tid], name);

  // ON3 by normalized name, disambiguated by team
  const on3ByName = {}, on3ByTeam = {};
  for (const o of on3) {
    o.tid = idx.resolve(o.team) || idx.resolve((o.teamSlug || '').replace(/-/g, ' '));
    (on3ByName[norm(o.name)] ||= []).push(o);
    if (o.tid) (on3ByTeam[o.tid] ||= []).push(o);
  }
  const on3Find = (name, tid, g) => {
    const hits = on3ByName[norm(name)] || [];
    return hits.find(o => o.tid === tid) || (hits.length === 1 && hits[0].tid == null ? hits[0] : null)
        || hits.find(o => ON3_TO_G[o.pos] === g && hits.length === 1)
        || (tid ? variant((on3ByTeam[tid] || []).filter(o => !ON3_TO_G[o.pos] || ON3_TO_G[o.pos] === g), name) : null) || null;   // "Sammy" on PFN, "Samuel" on On3
  };

  const players = [];
  const usedOn3 = new Set();
  // every FBS season since 2019, by player name, on its own curve: z within (position, season). PFN
  // changes ids (Jr. suffixes) and positions (S to CB), so careers are keyed by name and checked by school
  const careers = {};
  for (const p of POS) {
    const seasons = pfn[p.g], curve = {};
    for (const r of seasons) if (r.division === 'FBS' || r.division === 'FCS') (curve[r.division + r.season] ||= []).push(r.score);
    for (const k of Object.keys(curve)) {
      const xs = curve[k], m = xs.reduce((a, b) => a + b, 0) / xs.length;
      curve[k] = { m, sd: Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length) || 1 };
    }
    // a season in the other division counts on this division's curve, shifted by FCS_HIST.shift
    for (const r of seasons) if (curve[r.division + r.season]) {
      const c = curve[r.division + r.season], z = (r.score - c.m) / c.sd;
      (careers[norm(r.name)] ||= []).push({ g: p.g, team: r.team, tid: idx.resolve(r.team), season: r.season, cross: r.division !== div,
        z: r.division === div ? z : z + (FCS ? FCS_HIST.shift : -FCS_HIST.shift), vol: volume(r, false, p.g) });
    }
    for (const r of seasons.filter(x => x.season === SEASON)) {
      if (r.division !== div) continue;
      const tid = idx.resolve(r.team);
      const o = on3Find(r.name, tid, p.g);
      if (o) usedOn3.add(o);
      players.push({ name: r.name, g: p.g, label: p.label, pfnId: r.id, pfnPos: r.pos || null,
        team: r.team, tid, conf: r.conf, div: r.division, pfn: r.score, snaps: volume(r, true), gp: r.gp ?? r.gamesQ ?? null,
        sos: typeof r.sos === 'number' ? r.sos : null, row: r, on3: o });
    }
  }
  // a player PFN lists at two positions (EDGE and LB, S and CB) is one player: keep the line with
  // more snaps this season, so he isn't double-counted in either pool or drafted twice
  {
    const best = new Map();
    for (const p of players) {
      const k = norm(p.name) + '|' + p.tid, cur = best.get(k);
      if (!cur || (p.snaps ?? 0) > (cur.snaps ?? 0)) best.set(k, p);
    }
    const keep = new Set(best.values());
    for (let i = players.length - 1; i >= 0; i--) if (!keep.has(players[i])) players.splice(i, 1);
  }
  // PFN's FCS boards fold safeties into the corner board: ESPN's roster position splits them back out
  if (FCS) for (const p of players) if (p.g === 'CB' && p.tid) {
    const e = espnFind(p.tid, p.name);
    if (e && ESPN_GROUP(e.pos) === 'S') { p.g = 'S'; p.label = 'SAF+'; }
  }
  // ON3-ranked FBS players with no PFN line this season (injured, not yet playing, ATH)
  for (const o of FCS ? [] : on3) {
    if (usedOn3.has(o) || o.grade == null) continue;
    // already on the board under another spelling ("Samuel" on On3, "Sammy" on PFN): attach, don't add
    const dup = o.tid && players.find(q => q.tid === o.tid && !q.on3 && sameName(q.name, o.name) && (!ON3_TO_G[o.pos] || ON3_TO_G[o.pos] === q.g));
    if (dup) { dup.on3 = o; usedOn3.add(o); continue; }
    const g = ON3_TO_G[o.pos] || 'ATH';
    players.push({ name: o.name, g, label: POS.find(p => p.g === g)?.label || null, team: o.team, tid: o.tid,
      conf: null, div: 'FBS', pfn: null, snaps: null, gp: null, on3: o, noLine: true });
  }

  // production, Marcel-style for everyone: the last three seasons (5/4/3, by snaps), any position,
  // regressed to average (z = 0) with FV_K weighted snaps. A season counts when it was at the player's
  // current school, or when his name is unique in FBS that season (so transfers keep their history
  // and namesakes don't share it). A player with no line at all sits at average production.
  const nameCount = {}, curNames = {};
  for (const list of Object.values(pfn)) for (const r of new Map(list.filter(x => x.season === SEASON).map(x => [norm(x.name) + '|' + x.team, x])).values()) curNames[norm(r.name)] = (curNames[norm(r.name)] || 0) + 1;
  for (const [n, list] of Object.entries(careers)) for (const h of list) {
    const k = n + '|' + h.season; nameCount[k] = (nameCount[k] || new Set()).add(h.tid);
  }
  for (const p of players) {
    const n = norm(p.name), bySeason = {};
    for (const h of careers[n] || []) {
      if (!FV_WEIGHTS[h.season]) continue;
      if (h.tid !== p.tid && nameCount[n + '|' + h.season].size > 1) continue;
      // a season in the other division only counts for a name that's unique on both boards this season
      if (h.cross && h.tid !== p.tid && (curNames[n] || 0) > 1) continue;
      if (!bySeason[h.season] || h.vol > bySeason[h.season].vol) bySeason[h.season] = h;   // one line per season
    }
    let num = 0, w = 0, numPre = 0, wPre = 0;
    for (const h of Object.values(bySeason)) {
      const x = FV_WEIGHTS[h.season] * h.vol; num += x * h.z; w += x;
      if (h.season < SEASON) { numPre += x * h.z; wPre += x; }       // what was known before this season (yNIL)
    }
    p.marcel = num / (w + FV_K); p.marcelW = w; p.seasons = Object.keys(bySeason).length;
    p.tidBy = Object.fromEntries(Object.values(bySeason).map(h => [h.season, h.tid]));
    p.marcelPre = numPre / (wPre + FV_K); p.marcelPreW = wPre;
    p.priorOnly = !!p.noLine && p.seasons > 0;
  }
  // production z: the regressed blend standardized within the position (no rank step, so the
  // regression survives: a small sample stays near the middle)
  for (const g of [...new Set(players.map(p => p.g))]) {
    const grp = players.filter(p => p.g === g), xs = grp.map(p => p.marcel);
    const m = xs.reduce((a, b) => a + b, 0) / xs.length, sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length) || 1;
    for (const p of grp) p.zPfn = (p.marcel - m) / sd;
    const ys = grp.map(p => p.marcelPre), mp = ys.reduce((a, b) => a + b, 0) / ys.length, sp = Math.sqrt(ys.reduce((a, b) => a + (b - mp) ** 2, 0) / ys.length) || 1;
    for (const p of grp) p.zPre = (p.marcelPre - mp) / sp;
  }
  // breakout: the first college season at a top-15% level (z >= 1.04 on that season's curve, real
  // volume) and how early it came, counted from the high school class
  for (const p of players) {
    const first = (careers[norm(p.name)] || []).filter(h => h.z >= 1.04 && h.vol >= 150 && (h.tid === p.tid || nameCount[norm(p.name) + '|' + h.season].size === 1))
      .map(h => h.season).sort()[0];
    p.firstBreak = first ?? null;
  }

  // identity, class, age
  const dobs = manual.dob || {};
  for (const p of players) {
    const e = p.tid ? espnFind(p.tid, p.name) : null;
    const t = p.tid ? espn.teams[p.tid] : null;
    const o = p.on3;
    let cls = null;
    if (o?.classYear) cls = classFrom(o.classYear, /redshirt/i.test(o.classRank || ''));
    // ESPN's class is eligibility with no redshirt flag (about half of players are a year further
    // along): half a year added for age, and draft eligibility read off the eligibility class
    else if (e?.years) cls = { years: e.years + 0.5, elig: e.years, label: CLASS_NAMES[Math.min(e.years, 5) - 1] };
    const key = `${p.name}|${t?.name || p.team}`;
    const dob = dobs[key] || dobs[p.name] || (plausible(dobStore[key]?.dob) ? dobStore[key].dob : null) || e?.dob || null;
    const age = dob ? ageOn(dob, asof) : null;
    const ageEst = age ?? (cls ? 17.9 + cls.years : null);       // ~18.9 for a first-year in October
    p.rec = (e ? recruits[e.id] : null) || recByName[norm(p.name) + '|' + p.tid] || null;   // CFBD 247 composite, by ESPN athlete id (else name + school)
    Object.assign(p, { espn: e, team: t?.name || p.team, logo: t?.logo || o?.teamLogo || null,
      color: t?.color ? `#${t.color}` : o?.color || null, cls, dob, age, ageEst });
  }

  // talent: On3's order within the position as a normal score (rank-normal, so every position has the
  // same shape). Grade ties at 99 break by On3's overall rank, then position rank. Unranked players fill
  // the band below (see the unranked note).
  const tieKey = o => o.overallRank ?? 1e4 + (o.posRank ?? 99) * 11;
  // FCS: On3 doesn't grade FCS players; the slot holds level of play instead (team and conference SRS)
  if (FCS) for (const p of players) {
    const c = ctx[p.tid] || {};
    p.lvl = c; p.zOn3 = null;
    p.ctxZ = FCS_W.team * (c.teamZ ?? 0) + FCS_W.conf * (c.confZ ?? 0);
  }
  for (const g of FCS ? [] : [...new Set(players.map(p => p.g))]) {
    const grp = players.filter(p => p.g === g), N = grp.length;
    const ranked = grp.filter(p => p.on3?.grade != null).sort((a, b) => b.on3.grade - a.on3.grade || tieKey(a.on3) - tieKey(b.on3));
    ranked.forEach((p, i) => { p.zOn3 = probit(1 - (i + 0.5) / N); });
    // unranked isn't "bad": On3 grades 75 per position and can miss. Order them by production and
    // recruiting pedigree together and spread them through their band at 0.8 strength, so a productive,
    // well-recruited unranked player sits near the cutoff instead of in a flat block
    const pm = grp.reduce((a, p) => a + p.marcel, 0) / N, psd = Math.sqrt(grp.reduce((a, p) => a + (p.marcel - pm) ** 2, 0) / N) || 1;
    const key = p => 0.6 * (p.marcel - pm) / psd + 0.4 * (p.rec?.rating != null ? (p.rec.rating - 0.85) / 0.04 : -1);
    const rest = grp.filter(p => p.on3?.grade == null).sort((a, b) => key(b) - key(a));
    const zMid = probit((N - ranked.length) / 2 / N);
    rest.forEach((p, j) => { const zr = probit(1 - (ranked.length + j + 0.5) / N); p.zOn3 = zMid + 0.8 * (zr - zMid); });
  }
  // position strength uses the On3 grade itself (one scale across positions): the mean grade->z of
  // each position's top (5 x starting spots) ranked players against the average position
  {
    const pts = players.filter(p => p.on3?.grade != null && p.zOn3 != null);
    const mx = pts.reduce((a, p) => a + p.on3.grade, 0) / pts.length, my = pts.reduce((a, p) => a + p.zOn3, 0) / pts.length;
    const b = pts.reduce((a, p) => a + (p.on3.grade - mx) * (p.zOn3 - my), 0) / pts.reduce((a, p) => a + (p.on3.grade - mx) ** 2, 0);
    for (const p of pts) p.zGrade = my + b * (p.on3.grade - mx);
  }

  for (const p of players) {
    const classYear = p.on3?.classYear ?? (p.cls ? Math.round(SEASON + 1 - p.cls.years) : null);
    p.breakYear = p.firstBreak && classYear ? p.firstBreak - classYear + 1 : null;     // 1 = first season on campus
    const m = FV_BREAK_POS[p.g] ?? 1;
    p.breakZ = p.breakYear == null ? (p.cls?.years >= 4 && p.seasons >= 2 ? -0.05 * m : 0)
      : (FV_BREAKOUT[Math.max(1, Math.min(p.breakYear, 4)) - 1] ?? 0) * m;
  }

  // composite and FV
  const inches = h => { const m = /^(\d)\D+(\d+(?:\.\d+)?)/.exec(h || ''); return m ? +m[1] * 12 + +m[2] : null; };
  const zOf = (xs, x) => {
    const v = xs.filter(n => n != null);
    const m = v.reduce((a, b) => a + b, 0) / v.length, sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length) || 1;
    return x == null ? 0 : (x - m) / sd;
  };
  const clamp = (x, c) => Math.max(-c, Math.min(c, x));
  for (const p of players) {
    p.htIn = inches(p.on3?.ht) ?? inches(p.espn?.ht) ?? (p.rec?.ht || null);
    p.wtLb = p.on3?.wt || p.espn?.wt || p.rec?.wt || null;
  }
  for (const p of players) p.bmi = p.htIn && p.wtLb ? 703 * p.wtLb / p.htIn ** 2 : null;
  const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
  // recruiting pedigree: the 247 composite rating (CFBD) for nearly every scholarship player, else On3's
  // high school grade rescaled; no record at all (walk-on) sits at the bottom of the recruited range
  const hsAll = players.map(p => p.rec?.rating ?? null).filter(v => v != null);
  const hsMean = hsAll.reduce((a, b) => a + b, 0) / Math.max(1, hsAll.length);
  const hsSd = Math.sqrt(hsAll.reduce((a, b) => a + (b - hsMean) ** 2, 0) / Math.max(1, hsAll.length)) || 1;
  for (const p of players) {
    p.hsRaw = p.rec?.rating != null ? (p.rec.rating - hsMean) / hsSd
      : p.on3?.hsGrade != null ? (p.on3.hsGrade / 100 - hsMean) / hsSd : p.espn ? -1.5 : null;
  }
  const frameSlope = {};
  for (const g of Object.keys(FV_SIZE)) {
    const grp = players.filter(p => p.g === g), [cH, cW, cB] = FV_SIZE[g];
    // frame by age: the age-weight slope at the position, then every weight projected to FV_FRAME_AGE.to
    const aw = grp.filter(p => p.age != null && p.wtLb);
    if (aw.length > 30) {
      const ma = aw.reduce((a, p) => a + p.age, 0) / aw.length, mw = aw.reduce((a, p) => a + p.wtLb, 0) / aw.length;
      const b = aw.reduce((a, p) => a + (p.age - ma) * (p.wtLb - mw), 0) / (aw.reduce((a, p) => a + (p.age - ma) ** 2, 0) || 1);
      frameSlope[g] = Math.max(0, Math.min(FV_FRAME_AGE.slopeMax, b));
    } else frameSlope[g] = 3;
    for (const p of grp) {
      p.wtProj = p.wtLb ? p.wtLb + frameSlope[g] * Math.max(0, FV_FRAME_AGE.to - (p.ageEst ?? FV_FRAME_AGE.to)) : null;
      p.bmiProj = p.wtProj && p.htIn ? 703 * p.wtProj / p.htIn ** 2 : null;
    }
    const hs = grp.map(p => p.htIn), ws = grp.map(p => p.wtProj), bs = grp.map(p => p.bmiProj), ss = grp.map(p => p.sos);
    // efficiency stats: z among FBS players at the position with 60+ snaps this season
    const qual = grp.filter(p => (p.snaps ?? 0) >= 60);
    const cols = (FV_STATS[g] || []).map(([f, w0, get]) => {
      const val = r => (r ? (get ? nz(get(r)) : num(r[f])) : null), rel = statRel[g]?.[f];
      const w = rel == null ? w0 : w0 * Math.max(FV_REL.lo, Math.min(FV_REL.hi, rel / FV_REL.pivot));
      return { w, f, val, xs: qual.map(p => val(p.row)) };
    });
    for (const p of grp) {
      const fm = Math.min(FV_FRAME_AGE.max, 1 + FV_FRAME_AGE.perYear * Math.max(0, 21 - (p.ageEst ?? 21)));
      p.sizeZ = clamp(fm * (cH * zOf(hs, p.htIn) + cW * zOf(ws, p.wtProj) + cB * zOf(bs, p.bmiProj)), FV_SIZE_CAP * fm);
      // PFN's grades already adjust for opponents everywhere but QB (score and SOS correlate +.24 to
      // +.46 at other spots, -.29 at QB), so schedule only counts for quarterbacks
      p.sosZ = g === 'QB' ? clamp(FV_SOS.perSd * zOf(ss, p.sos), FV_SOS.cap) : 0;
      let sz = 0, sw = 0;
      p.statDetail = [];
      if (p.row && (p.snaps ?? 0) >= 60) for (const c of cols) {
        const v = c.val(p.row); if (v == null) continue;
        const z = zOf(c.xs, v);
        sz += c.w * z; sw += Math.abs(c.w);
        p.statDetail.push({ f: c.f, v, z: Math.sign(c.w) * z });   // z signed so + is always good
      }
      const rel = (p.snaps ?? 0) / ((p.snaps ?? 0) + 150);
      p.statZ = sw ? clamp(FV_STAT.w * rel * sz / sw, FV_STAT.cap) : 0;
      p.hsZ = p.hsRaw != null ? clamp((FCS ? FCS_W.hs : FV_HS.w) * p.hsRaw, FV_HS.cap) * (p.on3?.grade != null ? 0.5 : 1) : 0;
    }
  }
  // snap share, and the snap term in the composite
  for (const p of players) {
    const tp = teamPlays[p.tid], side = OFF_G.has(p.g) ? tp?.off : tp?.def;
    p.snapShare = p.g === 'RB' && p.row?.share != null ? Math.min(1, p.row.share / 100) : side && p.snaps ? Math.min(1, p.snaps / side) : null;
  }
  for (const g of Object.keys(STARTERS)) {
    const grp = players.filter(p => p.g === g && p.snapShare != null && (p.snaps ?? 0) >= 60), xs = grp.map(p => p.snapShare);
    for (const p of grp) p.snapZ = clamp(FV_SNAP.w * zOf(xs, p.snapShare), FV_SNAP.cap);
  }
  // ESPN's schedule-adjusted QBR, a QB's efficiency against the defenses he faced: z among qualifying QBs,
  // regressed by action plays (n / (n + 150)), FV_QBR per SD into the stats term
  {
    const qs = players.filter(p => p.g === 'QB' && qbr[p.espn?.id]?.qbr != null), xs = qs.map(p => qbr[p.espn.id].qbr);
    for (const p of qs) {
      const q = qbr[p.espn.id], rel = (q.plays || 0) / ((q.plays || 0) + 150);
      p.qbr = Math.round(q.qbr * 10) / 10; p.qbrZ = clamp(FV_QBR * rel * zOf(xs, q.qbr), 0.2); p.statZ = (p.statZ ?? 0) + p.qbrZ;
    }
  }
  // play-by-play rates that pass the split-half test (FV_PBP), plus the line shown in the report
  {
    const byTid = {};
    for (const a of Object.values(pbp)) { const t = idx.resolve(a.team); if (t) byTid[t + '|' + a.key] = a; }
    for (const p of players) { const a = p.tid ? byTid[p.tid + '|' + pbpKey(p.name)] : null; if (a) p.pbp = a; }
    // running back roles (early-down, 3rd-down, every-down) from estimated snaps by down (rbRoles in cfb_pbp.mjs);
    // every back with a play-by-play line counts toward his backfield's totals, 100+ snap backs get a label
    const backs = players.map((p, id) => ({ p, id })).filter(({ p }) => p.g === 'RB' && p.pbp)
      .map(({ p, id }) => ({ id, team: p.pbp.team, snapShare: (p.snaps ?? 0) >= 100 ? p.snapShare : null, sdO: p.pbp.sdO, pdO: p.pbp.pdO, sdT: p.pbp.sdT, pdT: p.pbp.pdT }));
    const roles = rbRoles(backs, pbpDowns);
    for (const b of backs) { const p = players[b.id], x = roles[b.id]; p.rbRole = x?.role ?? null; p.rbSd = x?.sd ?? null; p.rbPd = x?.pd ?? null; }
    for (const [g, list] of Object.entries(FV_PBP.stats)) {
      const grp = players.filter(p => p.g === g && p.pbp);
      for (const [f, val, shrink] of list) {
        const rel = pbpRel[f]; if (rel == null || rel < FV_PBP.minRel) continue;
        const xs = grp.map(p => val(p.pbp));
        for (const p of grp) { const v = val(p.pbp); if (v == null) continue; p.pbpZ = (p.pbpZ ?? 0) + FV_PBP.w * rel * shrink(p.pbp) * zOf(xs, v); }
      }
      for (const p of grp) if (p.pbpZ != null) { p.pbpZ = clamp(p.pbpZ, FV_PBP.cap); p.statZ = (p.statZ ?? 0) + p.pbpZ; }
    }
  }
  // actual vs expected (FV_OE): each season's line by school + name, the context correction z'd by the SD of over
  // expected among the position's qualifiers that season, blended by FV_WEIGHTS x plays
  if (!FCS) {
    const lines = {};
    for (const [sn, O] of Object.entries(oe)) for (const a of Object.values(O)) { const t = idx.resolve(a.team); if (t) (lines[sn] ||= {})[t + '|' + a.key] = a; }
    for (const p of players) {
      if (!FV_OE.k[p.g]) continue;
      p.oe = {};
      for (const sn of Object.keys(lines)) { const t = +sn === SEASON ? p.tid : p.tidBy?.[sn]; const a = t ? lines[sn][t + '|' + pbpKey(p.name)] : null; if (a) p.oe[sn] = a; }
    }
    oeContext(players, FV_OE, FV_WEIGHTS);
  }
  // percentiles at the position from this season's PFN line (100+ snaps, this division), for the position-fit
  // notes below. Archetypes and badges come from cfb_badges.mjs: bronze-to-platinum trait badges cut at
  // percentiles of each stat regressed by volume, and a few general archetypes per position picked from them
  const Q = {};          // Q[g][field](x): x's percentile among the position's 100+ snap players
  const qOf = (g, f, get) => {
    const k = g + '|' + f;
    if (!Q[k]) {
      const xs = players.filter(p => p.g === g && (p.snaps ?? 0) >= 100 && p.row).map(p => get(p)).filter(v => typeof v === 'number' && isFinite(v)).sort((a, b) => a - b);
      Q[k] = x => { if (x == null || !xs.length) return null; let lo = 0, hi = xs.length; while (lo < hi) { const m = (lo + hi) >> 1; if (xs[m] < x) lo = m + 1; else hi = m; } return lo / xs.length; };
    }
    return Q[k];
  };
  const pct = (p, f, get = q => q.row?.[f]) => { const v = get(p); return v == null ? null : qOf(p.g, f, get)(v); };
  const perSnap = f => q => q.row?.[f] != null && q.snaps ? q.row[f] / q.snaps : null;
  const recPg = q => q.row?.recYds != null ? q.row.recYds / Math.max(1, q.row.gp || q.row.gamesQ || 1) : null;
  assignBadges(players);
  // badges that predict NFL careers (FV_BADGE), into the stats term
  for (const p of players) {
    const ws = FV_BADGE.w[p.g]; if (!ws || !p.badgeZ) continue;
    let z = 0; for (const [k, w] of Object.entries(ws)) if (p.badgeZ[k] != null) z += w * p.badgeZ[k];
    if (z) { p.badgeFV = Math.max(-FV_BADGE.cap, Math.min(FV_BADGE.cap, z)); p.statZ = (p.statZ ?? 0) + p.badgeFV; }
  }
  for (const p of players) p.arch = archetypeOf(p);
  // position fit: a player whose frame and production profile fit another NFL position better (size against
  // drafted NFL players at both spots, CAL.size; production as percentiles at his position). Every rule reads
  // weight at 22 (wp: listed weight plus the position's frame slope to age 22, never below today's), since the
  // NFL drafts the body a player grows into. Each move has several paths, loose like the edge-to-DT rule: a
  // frame that clearly fits the new spot with a game that leans there, or an extreme frame with a neutral game.
  // The flag, not the grade: FV stays at the listed position
  const SZ = CAL.size, ftIn = n => `${Math.floor(n / 12)}-${n % 12}`;
  const fits = (k, ht, wt, slack = 0) => { const n = SZ[k]; return !!n && ht >= n.ht.p10 - 1 - slack && ht <= n.ht.p90 + 1 + slack && wt >= n.wt.p10 - 8 - 4 * slack && wt <= n.wt.p90 + 8 + 4 * slack; };
  const th = x => { const n = Math.round(100 * x), t = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th'; return `${n}${t} pct`; };
  const ge = (x, v) => x != null && x >= v, le = (x, v) => x != null && x <= v;
  for (const p of players) {
    p.move = null;
    const r = p.row, ht = p.htIn, wt = p.wtLb;
    if (!r || (p.snaps ?? 0) < 100 || !ht || !wt) continue;
    const wp = Math.round(Math.max(wt, p.wtProj || 0)), grow = wp - wt >= 3 ? ` (~${wp} lb by 22)` : '';
    const sz = `${ftIn(ht)}, ${wt} lb${grow}`, P = (f, get) => pct(p, f, get);
    const mv = (to, why) => { p.move = { to, why }; };
    if (p.g === 'DL') {
      const pr = P('prsRate'), tk = P('tklSnap', perSnap('tkl'));
      // outside fit: under DT weight even at 22, and a rusher (the shorter the frame, the better the rush must be)
      if (wp < SZ.DL.wt.p10 && ge(pr, 0.6) && ht >= SZ.EDGE.ht.p10 - (ge(pr, 0.85) ? 2 : 1) && wp >= SZ.EDGE.wt.p10 - 10)
        mv('EDGE', `undersized inside (${sz}; NFL DTs: 10th pct ${Math.round(SZ.DL.wt.p10)} lb) but rushes like an edge: ${r.prsRate}% pressure rate (${th(pr)} of DTs)`);
      else if (wp < SZ.DL.wt.p25 && ht >= SZ.EDGE.ht.p50 && ge(pr, 0.75) && fits('EDGE', ht, wp))
        mv('EDGE', `an edge frame (${sz}; NFL edges ${ftIn(SZ.EDGE.ht.p50)}, ${Math.round(SZ.EDGE.wt.p50)} lb at the median) with an edge's rush (${r.prsRate}% pressure, ${th(pr)} of DTs): a big end / 5-tech who rushes outside`);
      else if (wp < SZ.DL.wt.p10 - 15 && ge(pr, 0.4) && le(tk, 0.6) && fits('EDGE', ht, wp))
        mv('EDGE', `edge weight even at 22 (${sz}), ${Math.round(SZ.DL.wt.p10 - wp)} lb under the lightest NFL DTs: an end`);
    } else if (p.g === 'EDGE') {
      const pr = P('prsRate'), tk = P('tklSnap', perSnap('tkl'));
      // inside fit: DT size by 22, or a 5-tech frame (6-3+, edge 75th pct weight or more by 22, room for the
      // ~15 lb an end adds inside) whose game is stopping the run, not the rush
      if (wp > SZ.EDGE.wt.p90 && le(pr, 0.4) && fits('DL', ht, wp)) mv('DL', `DT-sized (${sz}; NFL edges: 90th pct ${Math.round(SZ.EDGE.wt.p90)} lb) with a modest rush off the edge (${r.prsRate}% pressure, ${th(pr)})${tk >= 0.5 ? ' and stout against the run' : ''}: a 3-tech / 5-tech fit`);
      else if (ht >= 75 && wp >= SZ.EDGE.wt.p75 && le(pr, 0.45) && tk - pr >= 0.25 && fits('DL', ht, wp + 15)) mv('DL', `a run stopper first (${th(tk)} in tackles per snap, ${th(pr)} in pressure rate) with a frame that can carry DT weight (${sz}): a 5-tech / big end fit`);
      else if (wp >= SZ.EDGE.wt.p90 + 8 && le(pr, 0.6) && fits('DL', ht, wp)) mv('DL', `already DT weight by 22 (${sz}) without a rush that keeps him outside (${th(pr)}): a 3-tech fit`);
      // off-ball fit: light for an edge even at 22
      else if (wp < SZ.EDGE.wt.p10 && le(pr, 0.35) && ge(tk, 0.55) && fits('LB', ht, wp)) mv('LB', `light for an NFL edge (${sz}) and not a high-volume rusher (${r.prsRate}% pressure, ${th(pr)}): an off-ball linebacker frame`);
      else if (wp < SZ.EDGE.wt.p10 - 8 && le(pr, 0.5) && fits('LB', ht, wp)) mv('LB', `linebacker weight even at 22 (${sz}; NFL edges: 10th pct ${Math.round(SZ.EDGE.wt.p10)} lb) and an average rush (${th(pr)}): an off-ball / SAM fit`);
    } else if (p.g === 'LB') {
      const ps = P('prsSnap', perSnap('prs')), cov = (r.tgt ?? 0) >= 10 ? P('rtg') : null;
      if (ge(ps, 0.8) && (r.prs || 0) >= 5 && ht >= SZ.EDGE.ht.p10 - 1 && wp >= SZ.EDGE.wt.p10 - 5) mv('EDGE', `edge frame (${sz}) and his best work comes as a rusher: ${r.prs} pressures (${th(ps)} of LBs per snap)`);
      else if (wp >= SZ.EDGE.wt.p25 && ht >= SZ.EDGE.ht.p25 && ge(ps, 0.65) && (r.prs || 0) >= 4) mv('EDGE', `edge size by 22 (${sz}) and a rusher's knack (${th(ps)} of LBs in pressures per snap): a SAM / stand-up edge fit`);
      else if (wp < SZ.LB.wt.p10 - 5 && le(cov, 0.3) && (r.tgt ?? 0) >= 10 && fits('S', ht, wp)) mv('S', `safety-sized even at 22 (${sz}) and holds up in coverage (${r.rtg} rating allowed, better than ${Math.round(100 * (1 - cov))}% of LBs)`);
      else if (wp <= SZ.S.wt.p90 && le(cov, 0.4) && fits('S', ht, wp)) mv('S', `safety weight at 22 (${sz}; NFL safeties: 90th pct ${Math.round(SZ.S.wt.p90)} lb) and steady in coverage (${th(1 - cov)} of LBs): a box safety / dime fit`);
    } else if (p.g === 'S') {
      const cov = (r.tar ?? 0) >= 7 ? P('rtg') : null, mt = r.mt != null ? P('mt') : null, fi = P('fi'), tk = P('tklSnap', perSnap('tkl'));
      if (wp >= SZ.S.wt.p90 && ge(cov, 0.6) && le(mt, 0.5) && fits('LB', ht, wp)) mv('LB', `linebacker frame (${sz}), tackles well (${r.mt}% missed) but coverage trails (${r.rtg} rating allowed): a box / WILL fit`);
      else if (wp >= SZ.LB.wt.p10 - 3 && ge(tk, 0.7) && fits('LB', ht, wp)) mv('LB', `linebacker weight by 22 (${sz}; NFL LBs: 10th pct ${Math.round(SZ.LB.wt.p10)} lb) and a box tackler (${th(tk)} in tackles per snap): a WILL / big-nickel fit`);
      else if (wp <= SZ.S.wt.p25 && ht <= SZ.CB.ht.p90 && le(cov, 0.3) && ge(fi, 0.6)) mv('CB', `corner-sized (${sz}) with corner-quality coverage (${r.rtg} rating allowed, ${r.fi}% forced incompletions): a nickel / CB fit`);
      else if (wp <= SZ.S.wt.p10 && ht <= SZ.CB.ht.p90 && le(cov, 0.4)) mv('CB', `corner weight even at 22 (${sz}; NFL safeties: 10th pct ${Math.round(SZ.S.wt.p10)} lb) and sound in coverage (${th(1 - cov)}): a nickel fit`);
    } else if (p.g === 'CB') {
      const cov = (r.tar ?? 0) >= 12 ? P('rtg') : null, mt = r.mt != null ? P('mt') : null, yr = P('ydsRec'), tk = P('tklSnap', perSnap('tkl'));
      if ((ht >= SZ.S.ht.p50 + 1 || wp >= SZ.S.wt.p25 + 3) && cov != null && (cov >= 0.65 || ge(yr, 0.8)) && le(mt, 0.45) && fits('S', ht, wp))
        mv('S', `safety frame (${sz}) and sure tackling (${r.mt}% missed, ${th(1 - mt)}) while the coverage numbers trail on the outside (${r.rtg} rating allowed${r.ydsRec != null ? `, ${r.ydsRec} yds a catch` : ''}): a safety / big-nickel fit`);
      else if (wp >= SZ.S.wt.p50 && ge(tk, 0.6) && le(mt, 0.5) && fits('S', ht, wp))
        mv('S', `safety weight by 22 (${sz}; NFL safeties ${Math.round(SZ.S.wt.p50)} lb at the median) and a willing tackler (${th(tk)} in tackles per snap): a safety fit`);
    } else if (p.g === 'WR') {
      const yac = P('yac');
      if (ht >= 76 && wp >= 225 && le(yac, 0.45) && fits('TE', ht, wp + 10)) mv('TE', `tight-end frame (${sz}) and he wins with size, not after the catch (${r.yac} YAC, ${th(yac)}): a move-TE fit`);
      else if (ht >= SZ.TE.ht.p25 && wp >= SZ.TE.wt.p10 - 5 && fits('TE', ht, wp)) mv('TE', `tight-end size by 22 (${sz}; NFL TEs: 10th pct ${Math.round(SZ.TE.wt.p10)} lb): a move-TE / big-slot fit`);
    } else if (p.g === 'TE') {
      const b = P('blk'), rc = P('recPg', recPg);
      if (wp < SZ.TE.wt.p10 && le(b, 0.4) && ge(rc, 0.65)) mv('WR', `receiver-weight for a TE even at 22 (${sz}), a light blocker (${th(b)}) but a real receiving threat (${th(rc)}): a big-slot fit`);
      else if (wp < SZ.TE.wt.p10 - 10 && ge(rc, 0.5) && fits('WR', ht, wp)) mv('WR', `receiver weight at 22 (${sz}; NFL TEs: 10th pct ${Math.round(SZ.TE.wt.p10)} lb) and productive as a receiver (${th(rc)}): a big-slot fit`);
    } else if (p.g === 'OL') {
      const tackle = /T$/.test(p.pfnPos || ''), inside = /^(LG|RG|C|G)$/.test(p.pfnPos || ''), pb = P('pbScore');
      if (tackle && ht < SZ.OT.ht.p10 && (r.rbScore ?? 0) - (r.pbScore ?? 0) >= 4) mv('IOL', `short for an NFL tackle (${sz}; 10th pct ${ftIn(SZ.OT.ht.p10)}) and a better run blocker (${r.rbScore}) than pass protector (${r.pbScore}): kick inside to guard`);
      else if (tackle && ht <= SZ.OT.ht.p10 && le(pb, 0.35) && wp >= SZ.IOL.wt.p25) mv('IOL', `guard build (${sz}; NFL tackles: 10th pct ${ftIn(SZ.OT.ht.p10)}) and pass sets that trail at tackle (${th(pb)}): a guard fit`);
      else if (inside && ht >= SZ.OT.ht.p50 + 1 && ge(pb, 0.75)) mv('OT', `tackle length (${sz}) and pass sets to match (${r.pbScore} pass-block score, ${th(pb)}): a tackle fit`);
      else if (inside && ht >= SZ.OT.ht.p50 && wp >= SZ.OT.wt.p25 && ge(pb, 0.85)) mv('OT', `tackle size by 22 (${sz}) and some of the best pass sets inside (${th(pb)}): a swing tackle fit`);
    } else if (p.g === 'RB') {
      const recShare = (r.recYds || 0) / Math.max(1, (r.ryds || 0) + (r.recYds || 0)), yc = P('ypc');
      if (recShare >= 0.35 && wp <= 200 && le(yc, 0.45)) mv('WR', `light (${sz}) and most dangerous as a receiver (${Math.round(100 * recShare)}% of his yards) while the runs lag (${r.ypc} ypc): a slot / gadget fit`);
      else if (wp < SZ.RB.wt.p10 - 5 && recShare >= 0.25 && fits('WR', ht, wp)) mv('WR', `receiver weight even at 22 (${sz}; NFL backs: 10th pct ${Math.round(SZ.RB.wt.p10)} lb) with real receiving work (${Math.round(100 * recShare)}% of his yards): a slot fit`);
    } else if (p.g === 'QB') {
      const ny = P('nypa'), ry = (r.ryds || 0) / Math.max(1, r.gp || 1);
      if (ry >= 50 && le(ny, 0.25) && ht <= SZ.QB.ht.p10) mv('ATH', `a runner first (${Math.round(ry)} rush yds a game) whose passing trails (${r.nypa} yds an attempt, ${th(ny)}) at ${ftIn(ht)}: an athlete (RB / WR) fit`);
    }
  }
  // sack conversion (sacks per pressure) doesn't repeat (season-to-season r ~0; pressure rate ~.5), so it's
  // context only: a pass rusher far above or below the average conversion is due to regress
  {
    const rush = players.filter(p => (p.g === 'EDGE' || p.g === 'DL') && (p.row?.prs ?? 0) >= 10);
    const avg = rush.reduce((a, p) => a + (p.row.sk || 0), 0) / Math.max(1, rush.reduce((a, p) => a + p.row.prs, 0));
    for (const p of rush) p.conv = { rate: (p.row.sk || 0) / p.row.prs, avg, sk: p.row.sk || 0, prs: p.row.prs };
  }
  // youth rarity by position: first-year share of the 150+ snap players
  const rare = {};
  {
    const play = players.filter(p => (p.snaps ?? 0) >= FV_RARE.snaps && p.cls);
    const pool = play.filter(p => p.cls.elig === 1).length / Math.max(1, play.length);
    for (const g of Object.keys(STARTERS)) {
      const grp = play.filter(p => p.g === g), sh = grp.filter(p => p.cls.elig === 1).length / Math.max(1, grp.length);
      rare[g] = Math.round(Math.max(FV_RARE.lo, Math.min(FV_RARE.hi, sh > 0 ? Math.sqrt(pool / sh) : FV_RARE.hi)) * 100) / 100;
    }
  }
  youthRarity = rare;
  // supporting cast (FV_CAST): cast z, the fitted context effect, and production over expectation
  if (!FCS) {
    const tz = q => q.on3?.grade != null && q.zOn3 != null ? q.zOn3 : -1;
    const byT = {};
    for (const q of players) if (q.tid && (q.snaps ?? 0) > 0) (byT[q.tid] ||= []).push(q);
    const pick = (ps, self, [g, n, how]) => {
      const xs = ps.filter(q => q.g === g && q !== self).sort((a, b) => (b.snaps ?? 0) - (a.snaps ?? 0)).slice(0, n).map(tz);
      return xs.length ? (how === 'max' ? Math.max(...xs) : xs.reduce((a, b) => a + b, 0) / xs.length) : -1;
    };
    castFit = {};
    for (const [g, [A, wa, B, wb]] of Object.entries(FV_CAST.spec)) {
      const grp = players.filter(p => p.g === g && p.tid && (p.snaps ?? 0) >= 100 && p.zPfn != null);
      const raw = grp.map(p => { const ps = byT[p.tid] || []; return wa * Math.max(...A.map(x => pick(ps, p, x))) + wb * Math.max(...B.map(x => pick(ps, p, x))); });
      const m = raw.reduce((a, b) => a + b, 0) / Math.max(1, raw.length), sd = Math.sqrt(raw.reduce((a, x) => a + (x - m) ** 2, 0) / Math.max(1, raw.length)) || 1;
      grp.forEach((p, i) => { p.castRaw = (raw[i] - m) / sd; });
      // OLS on [1, own talent, cast] over the graded regulars
      const fit = grp.filter(p => (p.snaps ?? 0) >= FV_CAST.snaps && p.on3?.grade != null && p.zOn3 != null);
      let b = [0, 0, 0], se = null;
      if (fit.length >= FV_CAST.min) {
        const X = fit.map(p => [1, p.zOn3, p.castRaw]), y = fit.map(p => p.zPfn);
        const xtx = [0, 1, 2].map(i => [0, 1, 2].map(j => X.reduce((a, r) => a + r[i] * r[j], 0))), xty = [0, 1, 2].map(i => X.reduce((a, r, k) => a + r[i] * y[k], 0));
        const inv = inv3(xtx);
        if (inv) {
          b = [0, 1, 2].map(i => inv[i].reduce((a, v, j) => a + v * xty[j], 0));
          const res = y.map((v, k) => v - X[k].reduce((a, x, j) => a + x * b[j], 0)), s2 = res.reduce((a, r) => a + r * r, 0) / Math.max(1, fit.length - 3);
          se = Math.sqrt(s2 * inv[2][2]);
        }
      }
      const wD = se ? 1 / se ** 2 : 0, wP = 1 / FV_CAST.priorSd ** 2;
      const post = Math.max(0, Math.min(FV_CAST.cap, (wD * b[2] + wP * FV_CAST.prior) / (wD + wP)));
      const rd = x => Math.round(x * 100) / 100;
      castFit[g] = { n: fit.length, a: rd(b[0]), talent: rd(b[1]), cast: rd(b[2]), se: se == null ? null : rd(se), post: rd(post) };
      for (const p of grp) {
        p.castZ = p.castRaw; p.castAdj = -FV_W.pfn * post * p.castRaw;
        // production over expectation, given his own talent grade and his cast (graded players only)
        p.prodOver = p.on3?.grade != null && p.zOn3 != null && se ? p.zPfn - (b[0] + b[1] * p.zOn3 + b[2] * p.castRaw) : null;
        const best = (byT[p.tid] || []).filter(q => q !== p && (g === 'QB' ? (q.g === 'WR' || q.g === 'TE') : g === 'RB' ? q.g === 'OL' : q.g === 'QB') && (q.snaps ?? 0) >= 60)
          .sort((x, y) => tz(y) - tz(x))[0];
        p.castBest = best ? best.name : null;
      }
    }
  }
  for (const p of players) {
    const am = FV_AGE_POS[p.g] ?? 1, rr = rare[p.g] ?? 1, d = p.ageEst == null ? 0 : FV_AGE.pivot - p.ageEst;
    // youth is worth something when the player is already producing or graded as a top talent: the bonus
    // scales with the better of production and 0.6 x the talent grade; being old costs in full either way
    const gate = Math.min(1, Math.max(0, (Math.max(p.zPfn, 0.6 * (p.zOn3 ?? -1)) + 1) / 2.5));
    let a = (d * FV_AGE.perYear + (d > 0 ? FV_AGE.curveYoung : FV_AGE.curve) * d * Math.abs(d)) * am;
    p.ageZ = a > 0 ? Math.min(a * rr, FV_AGE.capYoung * am) * gate : Math.max(a, -FV_AGE.capOld * am);
    // class: runway, first-year bonus, young for the class
    let c = 0;
    if (p.cls) {
      const runway = Math.max(0, Math.min(4, 5 - p.cls.years));
      c += FV_CLASS.perYear * (runway - 2.5) * (runway > 2.5 ? gate : 1);
      if (p.cls.elig === 1 && ((p.snaps ?? 0) >= FV_RARE.snaps || p.zPfn >= 0.3)) c += FV_CLASS.fr * rr;
      if (p.age != null) c += FV_CLASS.youngForClass * clamp(17.9 + p.cls.years - p.age, 1) * (p.age < 17.9 + p.cls.years ? gate : 1);
    }
    p.classZ = c;
    p.sizeZ ??= 0; p.sosZ ??= 0; p.statZ ??= 0; p.snapZ ??= 0; p.hsZ ??= 0; p.breakZ ??= 0;
    // production counts less for players who were never blue-chips (backtest: tier = 22.5 + 3.2 prod +
    // 3.1 bluechip + 3.2 prod x bluechip, i.e. half as much); On3 and PFN partly re-rate them, so 0.75
    const blue = FCS || (p.rec?.stars ?? 0) >= 4 || p.on3?.grade != null;
    p.prodEff = p.zPfn * (blue || p.zPfn < 0 ? 1 : 0.75);
    p.teamZ = clamp(FV_TEAM * (teamSp[p.tid] ?? 0), 0.15);
    p.talentTerm = FCS ? p.ctxZ : FV_W.on3 * p.zOn3;
    p.castAdj ??= 0; p.oeZ ??= 0;
    p.prodW = FV_W.pfn * (FV_PROD_POS[p.g] ?? 1);
    p.comp = p.talentTerm + p.prodW * p.prodEff + p.ageZ + p.classZ + p.snapZ + p.breakZ + p.sosZ + p.statZ + p.hsZ + p.teamZ + p.castAdj + p.oeZ;
  }
  // FCS move-up odds: P(on an FBS roster next season), FCS_UP fitted on 2022-26 movers; a move-up candidate
  // clears FCS_UP.flag (about 3x the base rate)
  if (FCS) for (const p of players) {
    const young = p.cls?.elig != null ? 3 - Math.min(5, p.cls.elig) : 0;
    const x = FCS_UP.c + FCS_UP.prod * p.zPfn + FCS_UP.team * (p.lvl?.teamZ ?? 0) + FCS_UP.conf * (p.lvl?.confZ ?? 0) + FCS_UP.young * young + FCS_UP.hs * (p.hsRaw ?? -1);
    p.upOdds = 1 / (1 + Math.exp(-x)); p.moveUp = p.upOdds >= FCS_UP.flag;
  }
  // the composite as a rank-normal score within the position (every position the same shape, honest
  // tails), shifted by position strength: a position whose top players grade lower on On3's one scale
  // gets fewer high grades (FV_POS_STRENGTH of the gap). Then expected talent = r * z, where r is the
  // composite's validity, and its percentile sets an expected rank for the scarcity tiers.
  const topTalent = {};
  for (const g of Object.keys(STARTERS)) {
    const top = players.filter(p => p.g === g && p.zGrade != null).map(p => p.zGrade).sort((a, b) => b - a).slice(0, 5 * STARTERS[g]);
    topTalent[g] = top.reduce((a, b) => a + b, 0) / Math.max(1, top.length);
  }
  const avgTop = Object.values(topTalent).reduce((a, b) => a + b, 0) / Object.keys(topTalent).length;
  const posShift = {};
  for (const g of Object.keys(STARTERS)) {
    const grp = players.filter(p => p.g === g).sort((a, b) => b.comp - a.comp), N = grp.length;
    // standardized, not ranked: a player far ahead of the next one (a Jeremiah Smith) keeps the gap
    const m = grp.reduce((a, q) => a + q.comp, 0) / N, sd = Math.sqrt(grp.reduce((a, q) => a + (q.comp - m) ** 2, 0) / N) || 1;
    // FCS takes the FBS position-strength shift (a property of the position, not the division)
    const shift = FCS ? other?.posShift?.[g] ?? 0 : FV_POS_STRENGTH * (topTalent[g] - avgTop), r = FV_RELIABILITY[g];
    posShift[g] = shift;
    // one NFL scarcity scale for both divisions: expected talent t in FBS units (an FCS player's is
    // FCS_TR.off + slope x r x z), ranked against FBS talent ~ N(0, 1) and FCS talent ~ N(off, slope^2)
    const nFbs = FCS ? other?.n?.[g] ?? 0 : N, nFcs = FCS ? N : other?.n?.[g] ?? 0;
    // FCS talent in FBS units: a split normal at off (sd slope above, 1 below)
    const fcsAbove = t => t >= FCS_TR.off ? 0.5 * 2 * (1 - phi((t - FCS_TR.off) / FCS_TR.slope)) : 1 - phi(t - FCS_TR.off);
    const rankAt = t => nFbs * (1 - phi(t)) + nFcs * fcsAbove(t);
    grp.forEach((p, i) => {
      p.compZ = (p.comp - m) / sd + shift;
      p.talentT = FCS ? FCS_TR.off + (p.compZ > 0 ? FCS_TR.slope : 1) * r * p.compZ : r * p.compZ;
      const expRank = Math.max(0.5, rankAt(p.talentT));
      p.fvBase = fvFromRank(expRank / FV_COHORTS, g, (nFbs + nFcs) / FV_COHORTS);
      // after the scarcity grade: NFL frame, and time spent in college (-1 per year past three, -2 at
      // QB and S: each extra year at the same draft slot costs ~0.8-2 tiers in the backtest)
      p.frameFV = Math.round(frameFV(p) * 10) / 10;
      const extra = Math.max(0, (p.cls?.years ?? 3) - 3);
      p.yearsFV = -extra * (g === 'QB' || g === 'S' ? 2 : 1);
      // fvx: the unrounded grade, carried through every adjustment below; it breaks ties within a displayed FV
      p.fvx = Math.max(20, Math.min(80, p.fvBase + p.frameFV + p.yearsFV));
      p.fv = Math.round(p.fvx);
      p.posRank = i + 1;
    });
  }
  // scouting consensus (draft-eligible prospects on PFN's industry board): FV moves toward the grade
  // the consensus rank implies, by CONS_W x sqrt(share of the seven boards that rank him)
  const byName = {};
  for (const p of players) (byName[norm(p.name)] ||= []).push(p);
  const divTeams = new Set(players.map(p => p.tid).filter(Boolean)), otherTeams = new Set(other?.tids || []);
  for (const c of consensus || []) {
    const cands = byName[norm(c.name)] || [], tid = idx.resolve(c.school);
    // a unique name stands in for a school that doesn't resolve, never for a school in the other division
    const p = cands.find(q => q.tid === tid) || (cands.length === 1 && (!tid || !divTeams.has(tid)) && !otherTeams.has(tid) ? cands[0] : null) || variant(players.filter(q => q.tid === tid), c.name);
    if (!p || p.fv == null) continue;
    const n = Object.keys(c.ranks || {}).length, w = CONS_W * Math.sqrt(Math.min(n, CONS_BOARDS) / CONS_BOARDS), cf = consFV(c.avg);
    p.cons = { rank: c.rank, avg: c.avg, n, fv: Math.round(cf) };
    p.fvModel = p.fv; p.consAdj = Math.round((cf - p.fv) * w * 10) / 10;
    p.fv = Math.max(20, Math.min(80, Math.round(p.fv + (cf - p.fv) * w)));
    p.fvx = Math.max(20, Math.min(80, p.fvx + (cf - p.fvx) * w));
  }
  // health (data/cfb_injuries.json): out for the season costs FV_HEALTH
  for (const p of players) {
    const i = (health[p.tid] || []).find(x => norm(x.name) === norm(p.name));
    p.inj = i?.status || null; p.healthFV = 0;
    if (p.fv != null && i && /season/i.test(i.status)) {
      p.healthFV = /acl|achilles|reconstruct|torn/i.test(i.detail || '') ? FV_HEALTH.major : FV_HEALTH.season;
      p.fv = Math.max(20, p.fv + p.healthFV); p.fvx = Math.max(20, p.fvx + p.healthFV);
    }
  }
  // riser: a draft-eligible prospect the model grades well above the consensus boards (RISER.gap FV over
  // the grade his consensus rank implies), or a 55+ the boards don't rank at all
  const consLoaded = (consensus || []).length >= 50;
  for (const p of players) {
    const draft = (p.cls?.years ?? 0) >= 3;
    p.riser = !!(p.fv != null && draft && (p.cons ? p.fvModel - p.cons.fv >= RISER.gap : consLoaded && p.fv >= RISER.unranked));
    p.riserWhy = p.riser ? (p.cons ? `model ${p.fvModel} FV vs consensus ${p.cons.fv} (#${p.cons.rank})` : 'not ranked on the consensus boards') : null;
  }
  // stars: hand-picked favourites (cfb_manual.json stars), the ARKLIST
  const stars = new Set(manual.stars || []);
  for (const p of players) p.star = stars.has(`${p.name}|${p.team}`) || stars.has(p.name);
  // position rank by the final grade (the composite breaks ties)
  for (const g of Object.keys(STARTERS)) players.filter(p => p.g === g && p.fv != null)
    .sort((a, b) => b.fv - a.fv || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || b.comp - a.comp).forEach((p, i) => { p.posRank = i + 1; });
  if (!FCS) posStrength = Object.fromEntries(Object.entries(topTalent).map(([g, v]) => [g, Math.round((v - avgTop) * 100) / 100]));
  for (const p of players) {
    if (p.fv == null) p.fv = null;                  // ATH: no NFL position to grade against yet
    // "+": a young, highly ranked talent whose production hasn't caught up yet
    p.plus = p.fv != null && p.fv < 80 && p.on3?.grade != null && p.zOn3 >= 1.5 && p.ageEst != null && p.ageEst <= 20.5 && p.zOn3 - p.zPfn >= 0.75;
  }

  // NIL, three numbers (FCS players priced off the FBS fit, see the FCS block below), all fitted to On3's NIL valuations (~270
  // players, the top of the market) with ridge regressions on log(valuation):
  //   yNIL (year NIL): what he was likely paid going into the season. Only what was known before it: last
  //     seasons' production (the Marcel blend without this season), On3 grade, 247 recruiting rating,
  //     position, QB x production, the prior-season playing time. Pay comes out of a program's budget, so
  //     each program splits one: the House settlement revenue-share cap ($20.5M, ~75% to football) plus
  //     outside NIL, ~$20M at Power 4 and Notre Dame, ~$3M in the Group of Five, tilted by roster talent
  //     (x e^(.3 z)); shares follow e^(1.1 x index) (calibrated to On3's valuations: R^2 .47, mean error ~0)
  //   xNIL (expected NIL): what he's worth on the open market now, wherever he plays: on-field value (the
  //     expected AV at this season's FV, and playing time) at his position's market price, program held out.
  //     On3's prices alone barely move with FV once position and program are known (+18% per 10 FV), so
  //     they set position prices only, and the FV scale sets value. Two markets (Power 4, Group of Five), each priced off its own programs' total pay;
  //     a G5 player good enough to start at P4 is priced in the P4 market, as the portal would
  //   zNIL = xNIL - yNIL: value gained (or lost) since the season's pay was set. Summed by team it measures
  //     development: how much a staff grew its roster's market value
  {
    const P4 = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC', 'IND (FBS)']);
    const posList = Object.keys(STARTERS), dummies = p => posList.slice(1).map(g => (p.g === g ? 1 : 0));
    // ridge on log(On3 NIL); returns the coefficient vector
    const ridge = (X, y, lam = 0.5) => {
      const k = X[0].length;
      const A = Array.from({ length: k }, (_, i) => Array.from({ length: k }, (_, j) => X.reduce((a, r) => a + r[i] * r[j], 0) + (i === j && i ? lam : 0)));
      const bv = Array.from({ length: k }, (_, i) => X.reduce((a, r, n) => a + r[i] * y[n], 0));
      for (let c = 0; c < k; c++) {           // Gauss-Jordan
        const piv = A[c][c] || 1e-9;
        for (let j = c; j < k; j++) A[c][j] /= piv; bv[c] /= piv;
        for (let r = 0; r < k; r++) if (r !== c) { const f = A[r][c]; for (let j = c; j < k; j++) A[r][j] -= f * A[c][j]; bv[r] -= f * bv[c]; }
      }
      return bv;
    };
    const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
    // preseason features (yNIL)
    const preF = p => { const z = p.zPre ?? 0; return [1, z, z * z, P4.has(p.conf) ? 1 : 0, ...dummies(p), p.g === 'QB' ? z : 0,
      Math.min(1, (p.marcelPreW ?? 0) / 1500), ((p.on3?.grade ?? 85) - 90) / 5, p.rec?.rating != null ? (p.rec.rating - 0.85) / 0.04 : -1]; };
    // worth-now features (xNIL); slot 3 is the Power 4 control, zeroed when pricing
    const nowF = (p, p4 = P4.has(p.conf) ? 1 : 0) => { const f = (p.fv - 50) / 10; return [1, f, f * f, p4, ...dummies(p), p.g === 'QB' ? f : 0, Math.min(1, (p.snaps ?? 0) / 250)]; };
    const train = players.filter(p => p.fv != null && p.on3?.nil > 0);
    if (!FCS && train.length > 50) {
      const y = train.map(p => Math.log(p.on3.nil));
      const bPre = ridge(train.map(preF), y), bNow = ridge(train.map(p => nowF(p)), y);
      const byTeam = {};
      for (const p of players) if (p.fv != null && p.tid) (byTeam[p.tid] ||= []).push(p);
      // roster talent: mean On3 talent z of each team's projected starters, as z across FBS
      const tal = Object.fromEntries(Object.entries(byTeam).map(([tid, ps]) => {
        const st = [];
        for (const [g, n] of Object.entries(STARTERS)) st.push(...ps.filter(p => p.g === g).sort((a, b) => b.zOn3 - a.zOn3).slice(0, n));
        return [tid, st.reduce((a, p) => a + p.zOn3, 0) / Math.max(1, st.length)];
      }));
      const tv = Object.values(tal), tm = tv.reduce((a, b) => a + b, 0) / tv.length, tsd = Math.sqrt(tv.reduce((a, b) => a + (b - tm) ** 2, 0) / tv.length) || 1;
      let pool = 0;
      for (const [tid, ps] of Object.entries(byTeam)) {
        const budget = (P4.has(ps[0].conf) ? XNIL.p4 : XNIL.g5) * Math.exp(XNIL.tilt * (tal[tid] - tm) / tsd);
        const w = ps.map(p => Math.exp(XNIL.k * dot(preF(p), bPre))), sw = w.reduce((a, b) => a + b, 0);
        ps.forEach((p, i) => { p.ynil = Math.round(budget * w[i] / sw / 1000) * 1000; pool += p.ynil; });
      }
      // two markets, each sharing its own programs' total pay (yNIL) by worth: Power 4 and Group of Five. A G5
      // player good enough to start at P4 (FV at or above the median P4 projected starter at his position) is
      // priced on the P4 curve, as the portal would
      const all = Object.values(byTeam).flat(), isP4 = p => P4.has(p.conf);
      const fvP4 = {};                         // per position: the median FV of P4 projected starters
      for (const [g, n] of Object.entries(STARTERS)) {
        const st = [];
        for (const [tid, ps] of Object.entries(byTeam)) if (isP4(ps[0])) st.push(...ps.filter(p => p.g === g).sort((a, b) => b.fv - a.fv).slice(0, n).map(p => p.fv));
        st.sort((a, b) => a - b); fvP4[g] = st[Math.floor(st.length / 2)] ?? 50;
      }
      // worth = position price (the fit's position and QB terms: what the market pays a QB over a guard at the
      // same grade) x on-field value: expected NFL AV a season at his FV (avOf, the FV scale's own value
      // curve) plus a floor (AV at FV 30) so a depth player is worth something, x playing time (half for
      // being on the roster, half for snaps)
      const mkt = p => isP4(p) || p.fv >= (fvP4[p.g] ?? 99) ? 'p4' : 'g5';
      const posTerm = p => { const v = nowF(p, 0); return dot(v.slice(4, 4 + posList.length - 1), bNow.slice(4, 4 + posList.length - 1)) + (p.g === 'QB' ? bNow[4 + posList.length - 1] * (p.fv - 50) / 10 : 0); };
      const val = new Map(all.map(p => [p, { pos: posTerm(p), v: (avOf(p.fv) + avOf(30)) * (0.5 + 0.5 * Math.min(1, (p.snaps ?? 0) / 250)) }]));
      const pools = { p4: 0, g5: 0 }; for (const p of all) pools[isP4(p) ? 'p4' : 'g5'] += p.ynil;
      const curve = a => { const z = { p4: 0, g5: 0 }, w = p => { const x = val.get(p); return Math.exp(x.pos) * x.v ** a; };
        for (const p of all) z[isP4(p) ? 'p4' : 'g5'] += w(p); return p => pools[mkt(p)] * w(p) / z[mkt(p)]; };
      // linear in value ($ per AV, like $ per WAR): fitting the exponent to On3 drives it to the floor (On3's
      // prices ignore grade), which would make xNIL another estimate of pay. On3 is kept as a diagnostic
      const kNow = 1, pr = curve(kNow);
      const best = train.filter(p => p.ynil != null).reduce((e, p) => e + (Math.log(p.on3.nil) - Math.log(pr(p))) ** 2, 0);
      for (const p of all) { p.xnil = Math.round(pr(p) / 1000) * 1000; p.znil = p.xnil - p.ynil; p.nilMkt = mkt(p); }
      // the FBS curves for the FCS build: worth weight sums by market, pools, starter lines, coefficients
      const fvG5 = {};
      for (const [g, n] of Object.entries(STARTERS)) {
        const st = [];
        for (const ps of Object.values(byTeam)) if (!isP4(ps[0])) st.push(...ps.filter(p => p.g === g).sort((a, b) => b.fv - a.fv).slice(0, n).map(p => p.fv));
        st.sort((a, b) => a - b); fvG5[g] = st[Math.floor(st.length / 2)] ?? 40;
      }
      const zs = { p4: 0, g5: 0 }; for (const p of all) { const x = val.get(p); zs[isP4(p) ? 'p4' : 'g5'] += Math.exp(x.pos) * x.v; }
      nilMarket = { bPre, bNow, fvP4, fvG5, pools, zs, price: { p4: pools.p4 / zs.p4, g5: pools.g5 / zs.g5 } };
      nilFit = { n: train.length, pool: Math.round(pool), fvP4, kNow: Math.round(kNow * 100) / 100, rmseLog: Math.round(Math.sqrt(best / train.length) * 100) / 100,
        pre: bPre.map(x => Math.round(x * 1000) / 1000), now: bNow.map(x => Math.round(x * 1000) / 1000) };
    }
  }

  // FCS NIL, from the FBS fit (On3 values no FCS players). yNIL: each FCS program splits XNIL.fcs (tilted by
  // its SRS) by the FBS preseason index. xNIL: worth (position price x on-field value, as in FBS) in the
  // market he could play in: an FCS player at or above the median G5 starter's FV at his position is priced on
  // the G5 curve (P4 starter's FV: P4 curve), as a move-up would be paid; everyone else shares the FCS pool
  // (the yNIL total) by worth. The discount is the budgets: an FCS dollar pool is ~1/8 of a G5 program's
  if (FCS && nilMarket) {
    const { bPre, bNow, fvP4, fvG5, pools, zs } = nilMarket, posList = Object.keys(STARTERS), nd = posList.length - 1;
    const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0), dummies = p => posList.slice(1).map(g => (p.g === g ? 1 : 0));
    const preF = p => { const z = p.zPre ?? 0; return [1, z, z * z, 0, ...dummies(p), p.g === 'QB' ? z : 0,
      Math.min(1, (p.marcelPreW ?? 0) / 1500), -1, p.rec?.rating != null ? (p.rec.rating - 0.85) / 0.04 : -1]; };
    const posTerm = p => dot(dummies(p), bNow.slice(4, 4 + nd)) + (p.g === 'QB' ? bNow[4 + nd] * (p.fv - 50) / 10 : 0);
    const worth = p => Math.exp(posTerm(p)) * (avOf(p.fv) + avOf(30)) * (0.5 + 0.5 * Math.min(1, (p.snaps ?? 0) / 250));
    const byTeam = {};
    for (const p of players) if (p.fv != null && p.tid) (byTeam[p.tid] ||= []).push(p);
    let pool = 0;
    for (const ps of Object.values(byTeam)) {
      const budget = XNIL.fcs * Math.exp(XNIL.tilt * (ps[0].lvl?.teamZ ?? 0));
      const w = ps.map(p => Math.exp(XNIL.k * dot(preF(p), bPre))), sw = w.reduce((a, b) => a + b, 0);
      ps.forEach((p, i) => { p.ynil = Math.round(budget * w[i] / sw / 1000) * 1000; pool += p.ynil; });
    }
    const all = Object.values(byTeam).flat(), mkt = p => p.fv >= (fvP4[p.g] ?? 99) ? 'p4' : p.fv >= (fvG5[p.g] ?? 99) ? 'g5' : 'fcs';
    const zf = all.filter(p => mkt(p) === 'fcs').reduce((a, p) => a + worth(p), 0) || 1;
    for (const p of all) {
      // a move-up's price is only collected if he transfers up, so it's discounted (XNIL.fcsMove), never below his FCS price
      const m = mkt(p), xf = pool * worth(p) / zf, x = m === 'fcs' ? xf : Math.max(xf, XNIL.fcsMove * pools[m] * worth(p) / zs[m]);
      p.xnil = Math.round(x / 1000) * 1000; p.znil = p.xnil - p.ynil; p.nilMkt = m;
    }
    nilMarket.price.fcs = pool / zf;    // $ per unit of worth in the FCS pool (the team builder reprices move-ups)
  }

  // one row per graded player; the board is the subset that meets a board rule
  const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100;
  const rows = [];
  for (const p of players) {
    const on3g = p.on3?.grade ?? null;
    const fr = p.cls ? p.cls.elig === 1 : false;
    const avg = p.pfn != null && on3g != null ? (p.pfn + on3g) / 2 : null;
    const why = [];
    if (p.pfn != null && p.pfn >= RULES.pfn) why.push('pfn');
    if (on3g != null && on3g >= RULES.on3) why.push('on3');
    if (avg != null && avg >= RULES.avg) why.push('avg');
    if (fr && on3g != null) why.push('fr-on3');
    if (fr && p.pfn != null && p.pfn >= RULES.frPfn) why.push('fr-pfn');
    const m = manual.players?.[`${p.name}|${p.team}`] || manual.players?.[p.name] || {};
    rows.push({
      name: p.name, pos: p.g, spot: p.pfnPos || (p.on3?.pos && p.on3.pos !== p.g ? p.on3.pos : null),
      team: p.team, tid: p.tid || null, logo: p.logo, color: p.color, conf: p.conf, div: p.div,
      cls: p.cls?.label ?? null, elig: p.cls?.elig ?? null, rs: !!p.cls?.label?.startsWith('RS'),
      age: p.age, ageEst: p.age == null && p.ageEst != null ? r1(p.ageEst) : null, dob: p.dob,
      ht: p.on3?.ht || p.espn?.ht?.replace(/[' "]+/g, '-').replace(/-$/, '') || null, wt: p.on3?.wt || p.espn?.wt || null,
      pfn: p.pfn, pfnLabel: p.label, snaps: p.snaps, gp: p.gp,
      on3: on3g, on3Rank: p.on3?.overallRank ?? null, on3PosRank: p.on3?.posRank ?? null,
      hsStars: p.on3?.hsStars ?? null, hsGrade: p.on3?.hsGrade ?? null, transfer: p.on3?.transfer ?? null,
      xnil: p.xnil ?? null, ynil: p.ynil ?? null, znil: p.znil ?? null, nilMkt: p.nilMkt ?? null,
      cons: p.cons?.avg ?? null, consRk: p.cons?.rank ?? null, consN: p.cons?.n ?? null, fvModel: p.fvModel ?? null, consAdj: p.consAdj ?? null,
      avg: avg == null ? null : r1(avg),
      photo: p.espn?.headshot || null, qbr: p.qbr ?? null, arch: p.arch, badges: p.badges?.length ? p.badges.map(b => [b.name, b.tier[0], b.pct, b.stat]) : null, rbRole: p.rbRole || null, rbSd: p.rbRole ? p.rbSd : null, rbPd: p.rbRole ? p.rbPd : null, snapShare: p.snapShare != null ? r2(p.snapShare) : null,
      move: p.move?.to ?? null, moveWhy: p.move?.why ?? null, up: p.upOdds != null ? r2(p.upOdds) : null, moveUp: p.moveUp || null,
      fv: p.fv, fvx: p.fvx != null ? Math.round(p.fvx * 100) / 100 : null, plus: p.plus, star: p.star || null, riser: p.riser || null, riserWhy: p.riserWhy, inj: p.inj, healthFV: p.healthFV || null,
      posRank: p.posRank ?? null,
      comp: Math.round(p.comp * 1000) / 1000, prodZ: r2(p.zPfn), talentZ: r2(p.zOn3),
      castZ: p.castZ != null ? r2(p.castZ) : null, castAdj: p.castAdj ? r2(p.castAdj) : null, oeZ: p.oeZ ? r2(p.oeZ) : null, prodOver: p.prodOver != null ? r2(p.prodOver) : null,
      ageZ: r2(p.ageZ), classZ: r2(p.classZ), wtProj: p.wtProj ? Math.round(p.wtProj) : null, sizeZ: r2(p.sizeZ), sosZ: r2(p.sosZ), statZ: r2(p.statZ), hsZ: r2(p.hsZ),
      // what each feeder adds to the composite (weighted), in the order the breakdown shows them
      parts: [p.talentTerm, p.prodW * p.prodEff, p.ageZ + p.classZ, p.breakZ, p.statZ + p.snapZ, p.hsZ, p.sosZ + p.teamZ + p.castAdj + p.oeZ, p.frameFV / 10].map(r2),
      fvBase: p.fvBase, frameFV: p.frameFV, yearsFV: p.yearsFV,
      breakYear: p.breakYear, priorOnly: !!p.priorOnly,
      report: scoutReport(p),
      bmi: p.bmi ? r1(p.bmi) : null,
      draft27: p.cls ? p.cls.years >= 3 : null,
      note: m.note || null, why,
      links: {
        on3: p.on3 ? `https://www.on3.com/rivals/${p.on3.slug}/` : null,
        espn: p.espn ? `https://www.espn.com/college-football/player/_/id/${p.espn.id}` : null,
      },
    });
  }
  const byFv = (a, b) => (b.fv ?? -1) - (a.fv ?? -1) || (b.plus - a.plus) || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || b.comp - a.comp;
  rows.sort(byFv);
  // positional rank by grade (hand grades included), e.g. WR3
  const seen = {};
  for (const r of rows) r.posRank = r.fv == null ? null : (seen[r.pos] = (seen[r.pos] || 0) + 1);
  rows.forEach((r, i) => { r.ovr = i + 1; });
  // the players worth exact birthdates and a place in data/cfb.json: the top 400 by FV
  const board = rows.filter(r => r.fv != null).slice(0, 400);
  board.forEach((p, i) => { p.rk = i + 1; });
  // FV distribution, 5-point tiers: the whole graded population and the board
  const dist = (list) => {
    const d = {};
    for (const r of list) if (r.fv != null) { const t = Math.min(80, Math.floor(r.fv / 5) * 5); d[t] = (d[t] || 0) + 1; }
    return d;
  };
  // FV -> xNIL ranges by 5-point tier: 10th/25th/50th/75th/90th percentile, and the QBs' median (QBs price higher)
  const nilCurve = {};
  for (let t = 20; t <= 80; t += 5) {
    const tier = rows.filter(r => r.xnil && r.fv != null && Math.min(80, Math.floor(r.fv / 5) * 5) === t);
    if (tier.length < 3) continue;
    const q = (xs, f) => { const v = xs.map(r => r.xnil).sort((a, b) => a - b); return v[Math.min(v.length - 1, Math.floor(f * v.length))]; };
    const qbs = tier.filter(r => r.pos === 'QB');
    nilCurve[t] = { n: tier.length, p10: q(tier, 0.1), p25: q(tier, 0.25), p50: q(tier, 0.5), p75: q(tier, 0.75), p90: q(tier, 0.9), qb: qbs.length >= 2 ? q(qbs, 0.5) : null };
  }
  const unmatched = players.filter(p => !p.tid).map(p => p.team);
  if (unmatched.length) console.log('teams without an ESPN match:', [...new Set(unmatched)].join(', '));
  return {
    asof: asof.toISOString().slice(0, 10), season: SEASON, rules: RULES, div, posShift,
    population: rows.filter(r => r.fv != null).length, count: board.length,
    dist: { all: dist(rows), draft: dist(rows.filter(r => r.draft27)) }, nilCurve, nilFit: FCS ? null : nilFit,
    summary: { graded: rows.filter(r => r.fv != null).length, n60: rows.filter(r => r.fv >= 60).length, n50: rows.filter(r => r.fv >= 50).length,
      draft: rows.filter(r => r.draft27 && r.fv != null).length, fr: rows.filter(r => r.elig === 1 && r.fv != null).length },
    posStrength, youthRarity, frameSlope, statRel, pbpRel, model: { stats: Object.fromEntries(Object.entries(FV_STATS).map(([g, l]) => [g, l.map(([f, w]) => [f, w])])), stat: FV_STAT, hs: FV_HS, weights: FV_WEIGHTS, k: FV_K, w: FV_W, prodPos: FV_PROD_POS, age: FV_AGE, agePos: FV_AGE_POS, size: FV_SIZE, sos: FV_SOS, cohorts: FV_COHORTS, reliability: FV_RELIABILITY, consensus: { w: CONS_W, boards: CONS_BOARDS }, tiers: TIERS, posValue: FV_POS_VALUE, starters: STARTERS, team: FV_TEAM, cast: { ...FV_CAST, fit: castFit }, oe: FV_OE, badge: FV_BADGE },
    players: board,
    all: rows,
  };
}

// ---- scouting report ------------------------------------------------------------------------------
// The FV feeders as a short report: a role on the football FV chart, then strengths (+) and concerns (-),
// each a stat line in scout shorthand ("Pressure rate 17.2% (94th pct EDGE)"). Thresholds are on the same
// z scale as the model; percentiles are within the position group.
const ROLE = [[80, 'MVP-level'], [75, 'perennial All-Pro'], [70, 'All-Pro'], [65, 'multi-time Pro Bowler'], [60, 'Pro Bowler'],
  [55, 'above-avg starter'], [50, 'avg starter'], [45, 'low-end starter / top rotation'], [40, 'rotation / spot starter'],
  [35, 'backup'], [30, 'practice squad'], [20, 'non-NFL']];
const STAT_NAME = { ypr: 'YPRR', intRate: 'INT rate', rushYpg: 'Rush yds/g', recYpg: 'Rec yds/g', yac: 'YAC',
  skAllwd: 'Sacks allowed', skRate: 'Sack rate', tacklePct: 'Tackle rate', tflRate: 'TFL rate', catchAllowed: 'Catch rate allowed', nypa: 'Y/A', cmpPct: 'Comp', elu: 'Elusive rating', ypc: 'YPC', tgtSh: 'Target share',
  epaTar: 'EPA/target', blk: 'Block grade', prsRate: 'Pressure rate', rbScore: 'Run-block score', mt: 'Missed tackles',
  rtg: 'Rating allowed', fi: 'Forced inc rate' };
const STAT_PCT = new Set(['intRate', 'skRate', 'tacklePct', 'catchAllowed', 'cmpPct', 'tgtSh', 'prsRate', 'fi']);
const nth = n => n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');
function scoutReport(p) {
  const plus = [], minus = [], g = p.g;
  const pct = z => `${nth(Math.min(99, Math.max(1, Math.round(100 * phi(z)))))} pct ${g}`;   // z signed so + is good
  const sg = (x, d) => (x >= 0 ? '+' : '') + x.toFixed(d), comp = x => `${sg(x, 2)} comp`;
  const role = p.fv == null ? null : ROLE.find(([f]) => p.fv >= f)?.[1];
  const o = p.on3;
  // talent
  if (o?.grade != null) {
    const line = `On3 ${o.grade}${o.posRank ? ` (#${o.posRank} ${o.pos})` : ''}`;
    (p.zOn3 >= 1 ? plus : minus).push(line);
  } else if (p.div === 'FCS') {
    // FCS: level of play stands in for the talent grade
    const l = p.lvl || {}, lz = (l.teamZ ?? 0) + (l.confZ ?? 0);
    const at = [l.teamRank && l.teams ? `#${l.teamRank}/${l.teams} FCS SRS` : null, l.conf ? `${l.conf}${l.confRank ? ` (#${l.confRank} conf)` : ''}` : null].filter(Boolean).join(', ');
    if (lz >= 1.2 || lz <= -1.2) (lz > 0 ? plus : minus).push(`FCS level: ${at}`);
    minus.push(`FCS, FBS-translated (avg FCS team ${FCS_GAP} pts/g below avg FBS)`);
  } else minus.push(`On3: outside top 75 ${g}`);
  // scouting consensus (moves FV after the model grade)
  if (p.cons) {
    const line = `Consensus #${p.cons.rank} (avg ${p.cons.avg}, ${p.cons.n}/${CONS_BOARDS} boards); model FV ${p.fvModel}, ${sg(Math.round(p.consAdj), 0)} FV`;
    (p.consAdj >= 1 || (p.consAdj > -1 && p.cons.n > 2) ? plus : minus).push(line);
  }
  // production: this season's score and the regressed blend's standing are separate facts
  const span = p.seasons > 1 ? `${p.seasons}-yr blend` : '1-yr, regressed';
  if (p.pfn != null || p.priorOnly) {
    const line = `${p.label} ${p.pfn != null ? p.pfn.toFixed(1) : 'prior yrs'} (${pct(p.zPfn)}, ${span})`;
    if (p.zPfn >= 0.75) plus.push(line); else if (p.zPfn < 0) minus.push(line);
    if (p.marcelW < 1000) minus.push(`Sample: ${p.snaps ?? 0} snaps${p.seasons > 1 ? '' : ', no prior year'} (heavy regression)`);
  }
  // supporting cast and production over expectation (FV_CAST)
  if (p.castZ != null && Math.abs(p.castZ) >= 1) {
    const who = p.castBest ? `; ${p.g === 'QB' ? 'top target' : p.g === 'RB' ? 'top OL' : 'QB'} ${p.castBest}` : '';
    (p.castZ >= 1 ? minus : plus).push(`Cast talent ${pct(p.castZ)}${who}${p.castAdj ? `; ${comp(p.castAdj)}` : ''}`);
  }
  if (p.prodOver != null && Math.abs(p.prodOver) >= 1) (p.prodOver > 0 ? plus : minus).push(`Prod vs expected ${sg(p.prodOver, 1)} SD (talent + cast)`);
  // actual vs expected (FV_OE): this season's rate over expected when it stands out, and the context correction
  {
    const o = p.oe?.[SEASON], d = o?.drop, c = o?.cmp, r = o?.rush, t = o?.tgt;
    if (g === 'QB' && d?.n >= FV_OE.min.drop && d.oe != null && Math.abs(d.oe) >= 0.5)
      (d.oe > 0 ? plus : minus).push(`ANY/A over exp ${sg(d.oe, 2)}/db${c?.n >= FV_OE.min.cmp && c.oe != null ? `, CPOE ${sg(100 * c.oe, 1)}%` : ''} (${d.n} db)`);
    if (g === 'RB' && r?.n >= FV_OE.min.rush && r.oe != null && Math.abs(r.oe) >= 0.25)
      (r.oe > 0 ? plus : minus).push(`RYOE ${sg(r.oe, 2)}/carry (${r.n} car)`);
    if ((g === 'WR' || g === 'TE') && t?.n >= FV_OE.min.tgt && t.oe != null && Math.abs(t.oe) >= 0.25)
      (t.oe > 0 ? plus : minus).push(`ANY/A over exp ${sg(t.oe, 2)}/target (${t.n} tgt)`);
    if (p.oeZ && Math.abs(p.oeZ) >= 0.02) (p.oeZ < 0 ? minus : plus).push(`Context adj ${comp(p.oeZ)} (raw ${p.oeZ < 0 ? 'above' : 'below'} over-expected)`);
  }
  if (p.priorOnly) minus.push(`No PFN line this season (${p.seasons} prior yr${p.seasons > 1 ? 's' : ''})`);
  else if (p.pfn == null) minus.push('No PFN line (injury, depth or redshirt)');
  // badges that predict NFL careers (FV_BADGE)
  if (p.badgeFV && Math.abs(p.badgeFV) >= 0.03) {
    const names = Object.keys(FV_BADGE.w[p.g] || {}).map(k => (p.badges || []).find(b => b.k === k)).filter(Boolean).map(b => `${b.tier[0].toUpperCase() + b.tier.slice(1)} ${b.name}`);
    (p.badgeFV > 0 ? plus : minus).push(`NFL-predictive badges: ${names.length ? names.join(', ') : p.badgeFV > 0 ? 'above avg' : 'below avg'} (${comp(p.badgeFV)})`);
  }
  // efficiency stats
  for (const d of p.statDetail || []) {
    const v = (Number.isInteger(d.v) ? d.v : d.v.toFixed(1)) + (STAT_PCT.has(d.f) ? '%' : ''), line = `${STAT_NAME[d.f] || d.f} ${v} (${pct(d.z)})`;
    if (d.z >= 1.25) plus.push(line); else if (d.z <= -1) minus.push(line);
  }
  // age
  const age = p.age ?? p.ageEst, est = p.age == null ? '~' : '';
  if (age != null && Math.abs(p.ageZ) >= 0.3) (p.ageZ > 0 ? plus : minus).push(`Age ${est}${age.toFixed(1)} (${p.ageZ > 0 ? 'young' : 'old'} for output)`);
  // pedigree and development: the model credits the high school grade (hsZ); the rise since is shown
  // as context, never as a plus the model doesn't give
  if (o?.hsGrade != null && o.grade != null) {
    const dev = o.grade - o.hsGrade, line = `HS ${o.hsStars ? `${o.hsStars}-star` : 'recruit'} (${Math.round(o.hsGrade)})${dev >= 6 ? `, now ${o.grade}` : ''}`;
    if (p.hsZ >= 0.05) plus.push(line); else if (p.hsZ <= -0.05) minus.push(line);
    if (dev <= -4) minus.push(`On3 ${o.grade} vs HS ${Math.round(o.hsGrade)} (${Math.round(dev)})`);
  }
  // schedule and frame
  if (Math.abs(p.sosZ) >= 0.12) (p.sosZ > 0 ? plus : minus).push(`SOS ${comp(p.sosZ)}`);   // QBs only (see sosZ)
  const frame = [p.on3?.ht || p.espn?.ht?.replace(/[' "]+/g, '-').replace(/-$/, ''), p.wtLb ? `${p.wtLb} lb` : null,
    p.bmi ? `BMI ${p.bmi.toFixed(1)}` : null].filter(Boolean).join(', ');
  if (Math.abs(p.sizeZ) >= 0.06) (p.sizeZ > 0 ? plus : minus).push(`Frame ${frame} (${comp(p.sizeZ)})`);
  if (p.plus) plus.push('"+" flag: On3 grade ahead of production, young');
  // playing time, QBR, class, availability, consensus
  if (p.snapShare != null && (p.snaps ?? 0) >= 100) {
    const pc = Math.round(p.snapShare * 100);
    if (pc >= 85) plus.push(`Snap share ${pc}%`);
    else if (pc >= 50 && (p.cls?.elig ?? 9) <= 2) plus.push(`Snap share ${pc}% (yr ${p.cls.elig})`);
    else if (pc < 35 && p.cls?.years >= 3) minus.push(`Snap share ${pc}% (yr ${p.cls.years})`);
  }
  if (p.qbr != null && Math.abs(p.qbrZ) >= 0.06) (p.qbrZ > 0 ? plus : minus).push(`QBR ${p.qbr} (SOS-adj)`);
  if (p.classZ >= 0.12) plus.push(`Early contributor: ${p.cls?.label}${youthRarity[g] ? ` (rarity x${youthRarity[g]})` : ''}`);
  if (p.rbRole) plus.push(`${RB_ROLE_NAME[p.rbRole]}: ${Math.round(p.rbSd * 100)}% SD / ${Math.round(p.rbPd * 100)}% PD snaps (est)`);
  if (p.riser) plus.push(`Riser: ${p.riserWhy}`);
  // play-by-play rates (shown when he has the volume) and pass-rush conversion
  const pb = p.pbp, side = p.pbpZ >= 0.03 ? plus : p.pbpZ <= -0.03 ? minus : [];
  if (pb && g === 'RB' && pb.car >= 20) side.push(`EPA/carry ${sg(pb.rEpa / pb.car, 2)}; 15+ yd ${Math.round(100 * pb.rExp / pb.car)}%; ${pb.rTd} TD (${pb.rzCar} RZ car)`);
  if (pb && (g === 'WR' || g === 'TE') && pb.tgt >= 12) side.push(`20+ yd catch ${Math.round(100 * pb.cExp / pb.tgt)}% of tgt; ${pb.cTd} TD (${pb.rzTgt} RZ tgt)`);
  const cv = p.conv, conv = cv && `Sack conv ${Math.round(100 * cv.rate)}% vs ${Math.round(100 * cv.avg)}% avg (${cv.sk} sk / ${cv.prs} prs)`;
  if (cv && cv.sk >= 4 && cv.rate >= 1.6 * cv.avg) minus.push(`${conv}: regression risk`);
  if (cv && cv.prs >= 20 && cv.rate <= 0.5 * cv.avg) plus.push(`${conv}: due to rise`);
  if (p.inj) minus.push(`Injury: ${p.inj}${p.healthFV ? ` (${p.healthFV} FV)` : ''}`);
  return { role, plus, minus, type: p.arch ? p.arch + (p.rbRole ? ' · ' + RB_ROLE_NAME[p.rbRole] : '') : null };
}

// ---- pixel logos -----------------------------------------------------------------------------
// ESPN's 500 px logos squeezed to a 20 px grid, 24 colours, then doubled with nearest-neighbour so
// they read as pixel art at 20 css px (crisp on 2x screens). Needs ImageMagick; without it the
// board hotlinks ESPN's logo instead.
async function pixelLogos(out) {
  let im = null;
  for (const bin of ['magick', 'convert']) {
    try { execFileSync(bin, ['-version'], { stdio: 'ignore' }); im = bin; break; } catch {}
  }
  if (!im) { console.log('no ImageMagick: hotlinking ESPN logos'); return; }
  fs.mkdirSync(LOGOS, { recursive: true });
  const done = {};
  for (const p of out.all) {
    const m = /teamlogos\/ncaa\/500\/(\d+)\.png/.exec(p.logo || '');
    if (!m) continue;
    const id = m[1], file = path.join(LOGOS, `${id}.png`);
    if (!(id in done)) {
      done[id] = fs.existsSync(file);
      if (!done[id]) {
        try {
          const r = await fetch(p.logo, { headers: { 'user-agent': UA } });
          if (!r.ok) throw new Error(r.status);
          const tmp = path.join(CACHE, `logo-${id}.png`);
          fs.writeFileSync(tmp, Buffer.from(await r.arrayBuffer()));
          execFileSync(im, [tmp, '-trim', '+repage', '-resize', '20x20', '-background', 'none', '-gravity', 'center',
            '-extent', '20x20', '-channel', 'A', '-threshold', '50%', '+channel', '-colors', '24',
            '-filter', 'point', '-resize', '40x40', '-strip', file]);
          done[id] = true;
        } catch (e) { console.log(`logo ${id}: ${e.message}`); }
      }
    }
    if (done[id]) p.logo = `/img/cfb/logos/${id}.png`;
  }
  console.log(`logos: ${Object.values(done).filter(Boolean).length} pixel logos`);
}

// NFL team logos for the mock draft: ESPN's PNGs through the same pixel step
async function nflLogos(picks) {
  let im = null;
  for (const bin of ['magick', 'convert']) { try { execFileSync(bin, ['-version'], { stdio: 'ignore' }); im = bin; break; } catch {} }
  fs.mkdirSync(NFL_LOGOS, { recursive: true });
  const done = {};
  for (const k of picks) {
    const a = k.team.toLowerCase(), file = path.join(NFL_LOGOS, `${a}.png`), url = `https://a.espncdn.com/i/teamlogos/nfl/500/${a}.png`;
    if (!(a in done)) {
      done[a] = fs.existsSync(file);
      if (!done[a] && im) {
        try {
          const r = await fetch(url, { headers: { 'user-agent': UA } }); if (!r.ok) throw new Error(r.status);
          const tmp = path.join(CACHE, `nfl-${a}.png`); fs.writeFileSync(tmp, Buffer.from(await r.arrayBuffer()));
          execFileSync(im, [tmp, '-trim', '+repage', '-resize', '20x20', '-background', 'none', '-gravity', 'center', '-extent', '20x20',
            '-channel', 'A', '-threshold', '50%', '+channel', '-colors', '24', '-filter', 'point', '-resize', '40x40', '-strip', file]);
          done[a] = true;
        } catch (e) { console.log(`nfl logo ${a}: ${e.message}`); }
      }
    }
    k.teamLogo = done[a] ? `/img/nfl/${a}.png` : url;
  }
}

// ---- dates of birth --------------------------------------------------------------------------
const WIKI_UA = 'arkndjl.net ARKBOARD (https://arkndjl.net; site maintenance)';
async function getRetry(url, ua = WIKI_UA) {
  for (let i = 0; ; i++) {
    const r = await fetch(url, { headers: { 'user-agent': ua, accept: 'application/json,text/html' } });
    if (r.status === 404) return null;
    if (r.status === 429 && i < 4) { await sleep(1000 * (+r.headers.get('retry-after') || 20)); continue; }
    if (!r.ok) throw new Error(`${r.status} ${url.slice(0, 80)}`);
    return r.text();
  }
}

async function wikidataDobs(names) {
  const vals = names.map(n => JSON.stringify(n) + '@en').join(' ');
  const q = `SELECT ?name ?dob (GROUP_CONCAT(DISTINCT ?tl; separator="|") AS ?teams) WHERE {
    VALUES ?name { ${vals} } ?p rdfs:label ?name; wdt:P106 wd:Q19204627; wdt:P569 ?dob.
    OPTIONAL { ?p wdt:P54|wdt:P69 ?t. ?t rdfs:label ?tl FILTER(lang(?tl)="en") } } GROUP BY ?name ?p ?dob`;
  const t = await getRetry('https://query.wikidata.org/sparql?format=json&query=' + encodeURIComponent(q));
  const out = {};
  for (const b of JSON.parse(t).results.bindings)
    (out[b.name.value] ||= []).push({ dob: b.dob.value.slice(0, 10), teams: b.teams.value.toLowerCase() });
  return out;
}

async function wikipediaDobs(titles) {
  const u = 'https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&rvsection=0'
    + '&redirects=1&format=json&formatversion=2&titles=' + encodeURIComponent(titles.join('|'));
  const r = JSON.parse(await getRetry(u)).query;
  const back = {};
  for (const x of [...(r.redirects || []), ...(r.normalized || [])]) back[x.to] = back[x.from] || x.from;
  const out = {};
  for (const p of r.pages || []) {
    const wt = p.revisions?.[0]?.slots?.main?.content || '';
    const m = /\{\{\s*birth[ _]date(?: and age)?\s*\|(?:\s*\w+\s*=[^|}]*\|)*\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})/i.exec(wt);
    out[back[p.title] || p.title] = { dob: m ? `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}` : null, wt: wt.toLowerCase() };
  }
  return out;
}

const dayGap = (a, b) => Math.abs(new Date(a) - new Date(b)) / 864e5;
// a college player is 16-27; anything else is a namesake
const plausible = d => !!d && +d.slice(0, 4) >= SEASON - 27 && +d.slice(0, 4) <= SEASON - 16;

async function fetchDobs(players, store) {
  const today = new Date().toISOString().slice(0, 10);
  const todo = players.filter(p => {
    const s = store[`${p.name}|${p.team}`];
    return !s || (!s.dob && dayGap(s.checked, today) >= 7);
  });
  if (!todo.length) return 0;
  const names = [...new Set(todo.map(p => p.name))];
  const wd = {}, wp = {};
  for (let i = 0; i < names.length; i += 60) {
    try { Object.assign(wd, await wikidataDobs(names.slice(i, i + 60))); } catch (e) { console.log(`wikidata: ${e.message}`); }
  }
  const titles = names.flatMap(n => [`${n} (American football)`, n]);
  for (let i = 0; i < titles.length; i += 50) {
    try { Object.assign(wp, await wikipediaDobs(titles.slice(i, i + 50))); } catch (e) { console.log(`wikipedia: ${e.message}`); }
    await sleep(1000);
  }
  let found = 0;
  for (const p of todo) {
    const school = p.team.toLowerCase(), first = school.split(' ')[0];
    const hits = wd[p.name] || [];
    let a = hits.find(h => h.teams.includes(school) || h.teams.includes(`${first} `))?.dob || null;  // school must match
    if (!plausible(a)) a = null;
    let b = null;
    for (const t of [`${p.name} (American football)`, p.name]) {
      const w = wp[t];
      if (plausible(w?.dob) && w.wt.includes('football') && w.wt.includes(first)) { b = w.dob; break; }
    }
    let dob = a || b, src = a ? 'wikidata' : b ? 'wikipedia' : null;
    if (a && b && dayGap(a, b) > 3) src = 'wikidata (wikipedia disagrees)';   // structured source wins
    store[`${p.name}|${p.team}`] = dob ? { dob, src } : { dob: null, checked: today };
    if (dob) found++;
  }
  console.log(`dates of birth: ${found} found of ${todo.length} looked up`);
  return todo.length;
}

// ---- main ------------------------------------------------------------------------------------
fs.mkdirSync(CACHE, { recursive: true });
const manual = fs.existsSync(MANUAL) ? JSON.parse(fs.readFileSync(MANUAL, 'utf8')) : {};
let pfn, on3, espn;
if (OFFLINE) {
  pfn = readCache('pfn.json'); on3 = readCache('on3.json'); espn = readCache('espn.json');
} else {
  pfn = await fetchPfn(); writeCache('pfn.json', pfn);
  if (ARGS.has('--skip-on3') && hasCache('on3.json')) on3 = readCache('on3.json');
  else {
    try { on3 = await fetchOn3(); }
    catch (e) {   // a Cloudflare challenge shouldn't sink the update: reuse the last good pull
      if (!hasCache('on3.json')) throw e;
      console.log(`ON3 failed (${e.message.slice(0, 120)}); using the cached pull`);
      on3 = readCache('on3.json');
    }
  }
  writeCache('on3.json', on3);
  const names = [...new Set([...Object.values(pfn).flat().filter(r => r.season === SEASON && r.division === 'FBS').map(r => r.team),
                             ...on3.map(o => o.team).filter(Boolean)])];
  espn = await fetchEspn(names); writeCache('espn.json', espn);
}
// team-level inputs: games, the projected draft order and needs, coaching staffs. Each falls back
// to its last good pull (cache) so one bad source doesn't stop the update.
async function source(name, fn) {
  if (OFFLINE && hasCache(name)) return readCache(name);
  try { const v = await fn(); writeCache(name, v); return v; }
  catch (e) { console.log(`${name}: ${e.message.slice(0, 120)}${hasCache(name) ? '; using the cached pull' : ''}`); return hasCache(name) ? readCache(name) : null; }
}
const games = await source('games.json', () => fetchGames(SEASON));
const lastGames = await source(`games${SEASON - 1}.json`, () => hasCache(`games${SEASON - 1}.json`) ? readCache(`games${SEASON - 1}.json`) : fetchGames(SEASON - 1));
const espnInjuries = await source('injuries.json', fetchInjuries) || {};
// availability log (data/cfb_injuries.json): Rotoballer's news (the last ~5 days, read for a status) and
// ESPN's report, matched to rosters; the newest item per player wins. Short-term statuses lapse after 9
// days without news; season-ending ones stand until news says he's back. Manual entries (cfb_manual.json)
// override both.
const INJ_LOG = path.join(ROOT, 'data', 'cfb_injuries.json');
const injuries = await (async () => {
  const log = fs.existsSync(INJ_LOG) ? JSON.parse(fs.readFileSync(INJ_LOG, 'utf8')) : { players: {} };
  const P = log.players;
  const people = [];
  for (const [tid, list] of Object.entries(espn.rosters)) for (const a of list) people.push({ ...a, tid, n: norm(a.name) });
  const byNorm = {}; for (const a of people) (byNorm[a.n] ||= []).push(a);
  const teamNames = Object.fromEntries(Object.entries(espn.teams).map(([id, t]) => [id, [t.name, t.full].filter(Boolean).map(x => x.toLowerCase())]));
  const put = (a, status, date, note, src) => { const k = a.id; if (P[k] && P[k].date > date && P[k].src !== 'manual') return;
    P[k] = { name: a.name, tid: a.tid, pos: a.pos, status, date, note: note?.slice(0, 160) || null, src }; };
    const news = await source('rotoballer.json', () => fetchRotoballer()) || [];
    let matched = 0;
    const findIn = (words, body) => {
      const toks = words.replace(/[^A-Za-z.'\- ]/g, ' ').split(/\s+/).filter(Boolean);
      for (let i = 0; i < toks.length; i++) for (let j = Math.min(toks.length, i + 4); j > i + 1; j--) {
        const cands = byNorm[norm(toks.slice(i, j).join(' '))]; if (!cands) continue;
        const b = body.toLowerCase(), hit = cands.length === 1 ? cands[0] : cands.find(c => teamNames[c.tid]?.some(n => b.includes(n)));
        if (hit) return hit;
      }
      return null;
    };
    for (const it of news) {
      // each headline clause: its player and its status; the blurb's first sentence when the headline has none
      const clauses = headlineClauses(it.title);
      const firstSentence = it.body.split(/(?<=\.)\s/)[0] || '';
      for (const c of clauses) {
        const a = findIn(c.text, it.body); if (!a) continue;
        const st = c.status || statusOf(firstSentence); if (!st) continue;
        matched++; put(a, st, it.date, it.title, 'rotoballer');
      }
    }
    for (const [tid, list] of Object.entries(espnInjuries)) for (const i of list) {
      const a = (byNorm[norm(i.name)] || []).find(x => x.tid === tid); if (!a) continue;
      const st = /season/i.test(i.detail || '') ? 'Out (season)' : /^out/i.test(i.status || '') ? 'Out' : i.status;
      put(a, st, i.date, i.detail, 'espn');
    }
    // manual: by name and school
    const ix = teamIndex(espn.teams);
    for (const m of manual.injuries || []) {
      const tid = ix.resolve(m.team), a = (byNorm[norm(m.name)] || []).find(x => !tid || x.tid === tid);
      if (a) P[a.id] = { name: a.name, tid: a.tid, pos: a.pos, status: m.status, date: new Date().toISOString(), note: m.note || null, src: 'manual' };
    }
    const now = Date.now();
    for (const [k, e] of Object.entries(P)) {
      const manualStill = e.src !== 'manual' || (manual.injuries || []).some(m => norm(m.name) === norm(e.name));
      if (!manualStill || e.status === 'Active' && now - Date.parse(e.date) > 9 * 864e5 || !seasonOut(e.status) && now - Date.parse(e.date) > 9 * 864e5) delete P[k];
    }
    log.asof = new Date().toISOString().slice(0, 10);
    fs.writeFileSync(INJ_LOG, JSON.stringify(log, null, 1) + '\n');
    console.log(`availability: ${news.length} news items, ${matched} matched to a player; ${Object.keys(P).length} listed, ${Object.values(P).filter(e => seasonOut(e.status)).length} out for the season`);
    const out = {};
    for (const e of Object.values(P)) if (e.status !== 'Active') (out[e.tid] ||= []).push({ name: e.name, pos: e.pos, status: e.status, detail: e.note, date: e.date, src: e.src });
    return out;
})();
// CFBD: last season's SP+ (once; it doesn't change) and this season's advanced team stats (each run)
const spLast = await source(`sp${SEASON - 1}.json`, () => hasCache(`sp${SEASON - 1}.json`) ? readCache(`sp${SEASON - 1}.json`) : cfbd(`ratings/sp?year=${SEASON - 1}`));
const advanced = await source('advanced.json', () => cfbd(`stats/season/advanced?year=${SEASON}&excludeGarbageTime=true`));
// 2027 draft order (projected from current NFL standings) and team needs (depth charts + contracts), ESPN
const tank = await source('nfl_order.json', async () => { const o = await fetchNflOrder(SEASON); o.needs = await fetchNflNeeds(o.teams); return o; });
// picks already traded for that draft (Wikipedia's list of trades): each moves to the team that holds it, keeping its original team
const nflTrades = await source(`nfl_trades${SEASON + 1}.json`, () => fetchNflTrades(SEASON + 1));
if (tank) applyNflTrades(tank.order, nflTrades, tank.teams);
// recruiting (CFBD, 247 composite): every high school and JUCO class since 2019, keyed by ESPN athlete id.
// Past classes never change, so each is fetched once and cached; the newest class refreshes each run.
const recruitNames = [];   // [name, school, record]: most FCS recruits carry no athlete id
async function fetchRecruits() {
  const out = {};
  for (let y = SEASON - 7; y <= SEASON; y++) for (const kind of ['HighSchool', 'JUCO']) {
    const name = `recruits-${y}-${kind}.json`;
    let list = hasCache(name) && y < SEASON ? readCache(name) : null;
    if (!list) { try { list = await cfbd(`recruiting/players?year=${y}&classification=${kind}`); writeCache(name, list); } catch (e) { console.log(`recruits ${y} ${kind}: ${e.message}`); list = hasCache(name) ? readCache(name) : []; } }
    for (const r of list) {
      const v = { year: r.year, kind, stars: r.stars, rating: r.rating, rank: r.ranking, pos: r.position, ht: r.height, wt: r.weight };
      if (r.athleteId) out[r.athleteId] = v;
      if (r.committedTo) recruitNames.push([r.name, r.committedTo, v]);
    }
  }
  return out;
}
// team strength for the FV composite: last season's SP+ by ESPN team id, as z across FBS
const teamSp = (() => {
  const ix = teamIndex(espn.teams), list = (spLast || []).filter(x => x.rating != null);
  const m = list.reduce((a, x) => a + x.rating, 0) / Math.max(1, list.length), sd = Math.sqrt(list.reduce((a, x) => a + (x.rating - m) ** 2, 0) / Math.max(1, list.length)) || 1;
  return Object.fromEntries(list.map(x => [ix.resolve(x.team), (x.rating - m) / sd]).filter(([k]) => k));
})();
const recruits = process.env.CFBD_API_KEY || hasCache(`recruits-${SEASON - 1}-HighSchool.json`) ? await fetchRecruits() : {};
console.log(`recruits: ${Object.keys(recruits).length} with ESPN ids`);
// this season's team plays (CFBD advanced box scores) for snap shares; refreshed each run, and the game model
// below reuses the box scores
const advNow = await source(`gameadv${SEASON}.json`, () => cfbd(`stats/game/advanced?year=${SEASON}&excludeGarbageTime=true`)) || [];
const teamPlays = (() => {
  const ix = teamIndex(espn.teams), o = {};
  for (const r of advNow) { const t = ix.resolve(r.team); if (!t) continue; const x = (o[t] ||= { off: 0, def: 0 }); x.off += r.offense?.plays || 0; x.def += r.defense?.plays || 0; }
  return o;
})();
const qbr = await source(`qbr${SEASON}.json`, () => fetchQbr(SEASON)) || {};
// play-by-play (CFBD plays, one call a week, slim): a finished week is pulled once; the latest is refreshed
const playsNow = [];
{
  const weeks = [...new Set((games || []).filter(g => g.done).map(g => g.week))].sort((a, b) => a - b);
  const last = weeks.at(-1);
  for (const w of weeks) {
    const name = `plays${SEASON}w${w}.json`;
    const pull = async () => (await cfbd(`plays?year=${SEASON}&week=${w}&seasonType=regular&classification=fbs`)).map(p => ({ g: p.gameId, o: p.offense, d: p.defense, h: p.home,
      q: p.period, ytg: p.yardsToGoal, dn: p.down, ds: p.distance, y: p.yardsGained, t: p.playType, x: p.playText, ppa: p.ppa, sc: p.scoring }));
    const list = hasCache(name) && (w !== last || OFFLINE) ? readCache(name) : await source(name, pull);
    if (list) playsNow.push(...list);
  }
}
const pbpGames = pbpByGame(playsNow), pbp = Object.fromEntries(Object.entries(pbpGames).map(([k, a]) => { const { _byGame, ...rest } = a; return [k, rest]; }));
// pbpByGame keeps per-game splits; the season line is the sum
for (const [k, a] of Object.entries(pbpGames)) {
  const t = pbp[k]; for (const f of ['car', 'ry', 'rEpa', 'rExp', 'rzCar', 'rTd', 'tgt', 'rec', 'recY', 'cEpa', 'cExp', 'rzTgt', 'cTd', 'hur', 'sk', 'sdO', 'pdO', 'sdT', 'pdT']) t[f] = 0;
  t.games = {};
  for (const [g, x] of Object.entries(a._byGame)) { for (const f of ['car', 'ry', 'rEpa', 'rExp', 'rzCar', 'rTd', 'tgt', 'rec', 'recY', 'cEpa', 'cExp', 'rzTgt', 'cTd', 'hur', 'sk', 'sdO', 'pdO', 'sdT', 'pdT']) t[f] += x[f]; t.games[g] = (x.car + x.tgt); }
}
const pbpRel = {
  rEpaCar: splitHalf(Object.values(pbpGames), v => v.rEpa, v => v.car, 40).r,
  xRecTgt: splitHalf(Object.values(pbpGames), v => v.cExp, v => v.tgt, 24).r,
  rzTd: splitHalf(Object.values(pbpGames), v => v.rTd + v.cTd, v => v.rzCar + v.rzTgt, 12).r,
  xRushCar: splitHalf(Object.values(pbpGames), v => v.rExp, v => v.car, 40).r,
  cEpaTgt: splitHalf(Object.values(pbpGames), v => v.cEpa, v => v.tgt, 24).r,
};
const pbpDowns = pbpTeamDowns(playsNow);
// actual vs expected (scripts/cfb_oe.mjs) for this season and last; last season's plays are pulled once (a week a call) and kept
const playsLast = [];
for (const w of [...new Set((lastGames || []).filter(g => g.done && g.week <= 16).map(g => g.week))].sort((a, b) => a - b)) {
  const name = `plays${SEASON - 1}w${w}.json`;
  const list = hasCache(name) ? readCache(name) : process.env.CFBD_API_KEY ? await source(name, async () => (await cfbd(`plays?year=${SEASON - 1}&week=${w}&seasonType=regular&classification=fbs`))
    .map(p => ({ g: p.gameId, o: p.offense, d: p.defense, ytg: p.yardsToGoal, dn: p.down, ds: p.distance, y: p.yardsGained, t: p.playType, x: p.playText }))) : null;
  if (list) playsLast.push(...list);
}
const oeSeasons = {};
for (const [sn, list] of [[SEASON, playsNow], [SEASON - 1, playsLast]]) if (list.length) oeSeasons[sn] = overExpected(parsePlays(list));
console.log('actual vs expected:', Object.entries(oeSeasons).map(([sn, O]) => `${sn} ${Object.keys(O).length} players`).join(', ') || 'no plays');
console.log(`play-by-play: ${playsNow.length} plays, ${Object.keys(pbp).length} players; split-half reliability`, pbpRel);
const staffData = fs.existsSync(STAFF_IN) ? JSON.parse(fs.readFileSync(STAFF_IN, 'utf8')) : null;
const dobStore = fs.existsSync(DOBS) ? JSON.parse(fs.readFileSync(DOBS, 'utf8')) : {};
const consensus = await source('consensus.json', fetchConsensus) || [];
// ---- FCS inputs: ESPN rosters for every FCS team on PFN's FCS boards (class, size, headshots), cached;
// recruits by name + school; team and conference strength from an SRS over this season's FBS + FCS games
const fcsNames = [...new Set(Object.values(pfn).flat().filter(r => r.season === SEASON && r.division === 'FCS').map(r => r.team))];
const idxAll = teamIndex(espn.teams);
const espnFcs = { teams: espn.teams, rosters: OFFLINE && hasCache('espn_fcs.json') ? readCache('espn_fcs.json')
  : await source('espn_fcs.json', async () => { const r = await fetchRosters(new Set(fcsNames.map(n => idxAll.resolve(n)).filter(id => id && !espn.rosters[id])), espn.teams); console.log(`ESPN ${Object.keys(r).length} FCS rosters`); return r; }) || {} };
const recByName = {};
for (const [n, school, v] of recruitNames) { const t = idxAll.resolve(school); if (t) recByName[norm(n) + '|' + t] = v; }
const gamesCfbdNow = await source(`games${SEASON}cfbd.json`, () => cfbd(`games?year=${SEASON}&seasonType=both`));
const gamesCfbdLast = await source(`games${SEASON - 1}cfbd.json`, () => hasCache(`games${SEASON - 1}cfbd.json`) ? readCache(`games${SEASON - 1}cfbd.json`) : cfbd(`games?year=${SEASON - 1}&seasonType=both`));
const fcsCtx = (() => {
  // SRS: margin (capped at 28) = home - away + 2.5 home field, solved by Gauss-Seidel with a ridge toward last
  // season's rating (worth 4 games), so a team two games in isn't rated on two games alone
  const srs = (games, prior = {}, lam = 2) => {
    const gs = (games || []).filter(g => g.completed && g.homePoints != null && ['fbs', 'fcs'].includes(g.homeClassification) && ['fbs', 'fcs'].includes(g.awayClassification));
    const r = {}, by = {}, cls = {}, conf = {};
    for (const g of gs) {
      const m = Math.max(-28, Math.min(28, g.homePoints - g.awayPoints)) - (g.neutralSite ? 0 : 2.5);
      (by[g.homeTeam] ||= []).push([g.awayTeam, m]); (by[g.awayTeam] ||= []).push([g.homeTeam, -m]);
      cls[g.homeTeam] = g.homeClassification; cls[g.awayTeam] = g.awayClassification; conf[g.homeTeam] = g.homeConference; conf[g.awayTeam] = g.awayConference;
    }
    for (const t of Object.keys(by)) r[t] = prior[t] ?? 0;
    for (let it = 0; it < 200; it++) for (const [t, list] of Object.entries(by))
      r[t] = (list.reduce((a, [o, m]) => a + m + r[o], 0) + lam * (prior[t] ?? 0)) / (list.length + lam);
    return { r, cls, conf };
  };
  const last = srs(gamesCfbdLast), now = srs(gamesCfbdNow, last.r, 4);
  const teams = Object.keys(now.r).length ? now : last;
  const fcsT = Object.keys(teams.r).filter(t => teams.cls[t] === 'fcs'), fbsT = Object.keys(teams.r).filter(t => teams.cls[t] === 'fbs');
  const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length), sdv = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
  const fv = fcsT.map(t => teams.r[t]), m = mean(fv), sd = sdv(fv);
  FCS_GAP = Math.round(mean(fbsT.map(t => teams.r[t])) - m);
  const confs = {};
  for (const t of fcsT) (confs[teams.conf[t] || 'FCS Independents'] ||= []).push(teams.r[t]);
  const cm = Object.fromEntries(Object.entries(confs).filter(([, v]) => v.length >= 4).map(([c, v]) => [c, mean(v)]));
  const cmv = Object.values(cm), cmm = mean(cmv), cms = sdv(cmv);
  const confRank = Object.fromEntries(Object.entries(cm).sort((a, b) => b[1] - a[1]).map(([c], i) => [c, i + 1]));
  const order = fcsT.slice().sort((a, b) => teams.r[b] - teams.r[a]);
  const out = {};
  order.forEach((t, i) => {
    const tid = idxAll.resolve(t); if (!tid) return;
    const c = teams.conf[t] || null;
    out[tid] = { team: t, srs: Math.round(teams.r[t] * 10) / 10, teamZ: (teams.r[t] - m) / sd, conf: c, confZ: cm[c] != null ? (cm[c] - cmm) / cms : 0,
      confRank: confRank[c] ?? null, teamRank: i + 1, teams: order.length };
  });
  console.log(`FCS SRS: ${order.length} teams, average FCS team ${FCS_GAP} points a game below the average FBS team; ${Object.keys(cm).length} conferences`);
  return out;
})();
const pfnCount = d => Object.fromEntries(POS.map(p => [p.g, new Set(pfn[p.g].filter(r => r.season === SEASON && r.division === d).map(r => norm(r.name) + '|' + r.team)).size]));
const nFbs = pfnCount('FBS'), nFcs = pfnCount('FCS');
const baseIn = () => ({ pfn, on3, espn, manual, dobStore, recruits, recByName, teamSp, consensus, health: injuries || {}, teamPlays, qbr, pbp, pbpRel, pbpDowns, oe: oeSeasons });
const gradeAll = () => {
  const fcsTids = [...new Set([...Object.keys(fcsCtx), ...Object.keys(espnFcs.rosters)])];
  const fbs0 = build({ ...baseIn(), other: { n: nFcs, tids: fcsTids } });
  const fcs = build({ ...baseIn(), espn: espnFcs, div: 'FCS', ctx: fcsCtx, other: { n: nFbs, posShift: fbs0.posShift, tids: Object.keys(espn.rosters) } });
  // again with the FCS pool as graded (safeties split off the corner board by ESPN position)
  const nGraded = {}; for (const r of fcs.all) nGraded[r.pos] = (nGraded[r.pos] || 0) + 1;
  const fbs = build({ ...baseIn(), other: { n: nGraded, tids: fcsTids } });
  return [fbs, fcs];
};
// calibration (--calibrate-fcs): the FCS translation offset that gives FCS players their share of NFL outcomes
if (ARGS.has('--calibrate-fcs')) {
  const share = (a, b, f) => { const x = b.all.filter(r => r.fv >= f).length, y = a.all.filter(r => r.fv >= f).length; return x / Math.max(1, x + y); };
  if (process.env.SLOPE) FCS_TR.slope = +process.env.SLOPE;
  for (const off of (process.env.OFFS || '-1.0,-1.1,-1.2,-1.3,-1.4,-1.5').split(',').map(Number)) {
    FCS_TR.off = off; const [a, b] = gradeAll();
    const top = b.all.slice(0, 3).map(r => `${r.name} ${r.fv}`).join(', ');
    console.log(`slope ${FCS_TR.slope} off ${off}: top ${top}; FCS share FV30+ ${share(a, b, 30).toFixed(3)} (target .048) 40+ ${share(a, b, 40).toFixed(3)} 45+ ${share(a, b, 45).toFixed(3)} (.043) 50+ ${share(a, b, 50).toFixed(3)} (.040) 55+ ${share(a, b, 55).toFixed(3)} (.026) 60+ ${share(a, b, 60).toFixed(3)} (.02-.04) 70+ ${share(a, b, 70).toFixed(3)} (.018)`);
  }
  process.exit(0);
}
let [out, outFcs] = gradeAll();
if (!ARGS.has('--no-dob') && await fetchDobs(out.players, dobStore)) {
  const sorted = Object.fromEntries(Object.entries(dobStore).sort(([a], [b]) => a.localeCompare(b)));
  fs.writeFileSync(DOBS, JSON.stringify(sorted, null, 1) + '\n');
  [out, outFcs] = gradeAll();   // ages feed the model, so grade again
}
await pixelLogos(out);
await pixelLogos(outFcs);
{
  const share = f => { const x = outFcs.all.filter(r => r.fv >= f).length, y = out.all.filter(r => r.fv >= f).length; return Math.round(1000 * x / Math.max(1, x + y)) / 1000; };
  out.fcs = { population: outFcs.population, gap: FCS_GAP, tr: FCS_TR, w: FCS_W, up: FCS_UP, hist: FCS_HIST,
    share: { 30: share(30), 45: share(45), 50: share(50), 60: share(60) }, target: { 30: 0.048, 45: 0.043, 50: 0.04, 60: 0.042 },
    moveUp: outFcs.all.filter(r => r.moveUp).length, dist: outFcs.dist.all, nilCurve: outFcs.nilCurve, nilDiscount: nilDiscount(outFcs.nilCurve, out.nilCurve),
    teams: [...new Set(outFcs.all.map(r => r.team))].sort(), confs: [...new Set(outFcs.all.map(r => r.conf).filter(Boolean))].sort() };
  console.log('FCS:', JSON.stringify({ population: out.fcs.population, share: out.fcs.share, moveUp: out.fcs.moveUp }));
}

// movers: each update keeps a snapshot of every grade; the board shows the change since the last
// snapshot from an earlier day (re-runs on the same day replace that day's snapshot). Snapshots carry
// the model version, so a model change starts the movers over instead of reporting its own churn.
const MODEL_VERSION = 'cal-2026-10';
const key = r => `${r.name}|${r.team}|${r.pos}`;
const hist = fs.existsSync(HISTORY) ? JSON.parse(fs.readFileSync(HISTORY, 'utf8')) : { snapshots: [] };
const base = hist.snapshots.filter(h => h.date < out.asof && h.v === MODEL_VERSION).at(-1);
out.since = base?.date ?? null;
// FBS and FCS in one list, ranked together (ovr): the holistic board
const merged = () => {
  const e = [...out.all, ...outFcs.all].sort((a, b) => (b.fv ?? -1) - (a.fv ?? -1) || (b.plus - a.plus) || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || (b.comp ?? 0) - (a.comp ?? 0));
  e.forEach((r, i) => { r.ovr = i + 1; });
  return e;
};
const everyone = merged();
for (const r of everyone) {
  const was = base?.fv[key(r)];
  // FCS players are new to the snapshots: no movers for them until a snapshot carries them
  r.delta = base && r.fv != null && (r.div !== 'FCS' || base.fcs) ? (was == null ? 'new' : r.fv - was) : null;
}
hist.snapshots = hist.snapshots.filter(h => h.date !== out.asof);
hist.snapshots.push({ date: out.asof, v: MODEL_VERSION, fcs: true, fv: Object.fromEntries(everyone.filter(r => r.fv != null).map(r => [key(r), r.fv])) });
hist.snapshots = hist.snapshots.slice(-6);
fs.writeFileSync(HISTORY, JSON.stringify(hist) + '\n');

// every graded player, for the database view: column arrays keep it small (fetched by the page)
for (const r of everyone) { r.on3l = r.links.on3; r.espnl = r.links.espn; }
const COLS = ['report', 'on3l', 'espnl', 'photo', 'star', 'riser', 'riserWhy', 'inj', 'arch', 'badges', 'rbRole', 'rbSd', 'rbPd', 'snapShare', 'name', 'pos', 'spot', 'team', 'logo', 'conf', 'cls', 'elig', 'age', 'ageEst', 'ht', 'wt', 'pfn', 'pfnLabel',
              'snaps', 'on3', 'cons', 'consRk', 'consN', 'xnil', 'ynil', 'znil', 'fv', 'plus', 'posRank', 'ovr', 'draft27', 'parts', 'bmi', 'delta', 'div', 'move', 'moveWhy', 'up', 'moveUp', 'draftP', 'kp', 'fvx',
              'transferP', 'stayP', 'tWhy', 'homeMi', 'inState'];
fs.mkdirSync(path.dirname(ALL_OUT), { recursive: true });
const PRIORS = path.join(ROOT, 'data', 'cfb_draft_priors.json');
// the draft year's combine (nflverse), empty until it's held in late February
const combine = await source(`combine${SEASON + 1}.json`, () => fetchCombine(SEASON + 1));
const draftPriors = () => ({ ...(fs.existsSync(PRIORS) ? JSON.parse(fs.readFileSync(PRIORS, 'utf8')) : {}), combine });
// Draft% (draftOdds in cfb_teams.mjs) is refreshed on every write, so it follows the latest FV and consensus;
// Transfer% (cfb_transfer.mjs) once its inputs are in (tctx, below), after Draft%, which sets its floor on leaving
let tctx = null;
const writeAll = () => { draftOdds([...out.all, ...outFcs.all], draftPriors());
  if (tctx) transferOdds([...out.all, ...outFcs.all], tctx);
  fs.writeFileSync(ALL_OUT, JSON.stringify({ asof: out.asof, cols: COLS, rows: merged().map(r => COLS.map(c => r[c] ?? null)) })); };
writeAll();
// teams, staff, mock draft
const fbsIds = new Set(Object.keys(espn.rosters));
const idxTeams = teamIndex(espn.teams);
const byEspn = (list, f) => Object.fromEntries((list || []).map(x => [idxTeams.resolve(x.team), f(x)]).filter(([k]) => k));
const gone = new Set(out.all.filter(r => /season/i.test(r.inj || '')).map(r => `${r.name}|${r.team}|${r.pos}`));
const teamList = games ? teamModels(out.all, espn.teams, games, fbsIds, { gone,
  lastGames, sp: byEspn(spLast, x => x.rating), adv: byEspn(advanced, x => x) }) : [];
// the coming week: the earliest week with unplayed games
const nextWeek = games?.filter(g => !g.done).map(g => g.week).sort((a, b) => a - b)[0] ?? null;
// projected top performers: this season's player stat lines (CFBD, one call a run)
// the game model (scripts/cfb_model.mjs): CFBD games, advanced box scores and closing lines for this season
// and the two before (past seasons pulled once), venues, talent, returning production, QB EPA; weather from
// Open-Meteo, cached by game. A failed source falls back to its cache; with none, the slate keeps Elo alone.
const once = (name, q) => source(name, () => hasCache(name) ? readCache(name) : cfbd(q));
const cur = (name, q) => source(name, () => cfbd(q));
const MD = { games: {}, adv: {}, lines: {}, sp: {}, talent: {}, returning: {}, drives: {} };
for (const S of [SEASON - 2, SEASON - 1, SEASON]) {
  const get = S === SEASON ? cur : once;
  MD.games[S] = S === SEASON && gamesCfbdNow?.length ? gamesCfbdNow : S === SEASON - 1 && gamesCfbdLast?.length ? gamesCfbdLast : await get(`games${S}cfbd.json`, `games?year=${S}&seasonType=both`);
  MD.adv[S] = S === SEASON && advNow.length ? advNow : await get(`gameadv${S}.json`, `stats/game/advanced?year=${S}&excludeGarbageTime=true`);
  // drives (special teams), kept slim: a season of raw drives is ~15 MB
  MD.drives[S] = await source(`drives${S}.json`, async () => S < SEASON && hasCache(`drives${S}.json`) ? readCache(`drives${S}.json`) : slimDrives(await cfbd(`drives?year=${S}`)));
  if (S > SEASON - 2) {
    MD.lines[S] = await get(`lines${S}.json`, `lines?year=${S}`);
    MD.talent[S] = await once(`talent${S}.json`, `talent?year=${S}`);
    MD.returning[S] = await once(`returning${S}.json`, `player/returning?year=${S}`);
  }
  if (S < SEASON) MD.sp[S] = await once(`sp${S}.json`, `ratings/sp?year=${S}`);
}
// situational splits (early downs, 3rd downs, red zone) and coach decisions (4th downs, pass rate by situation)
// for this season and last, from CFBD plays: one call per
// week, reduced on arrival to counts per game and offense (sitByGame); finished weeks pulled once, the latest refreshed
MD.sit = {};
for (const S of [SEASON - 1, SEASON]) {
  const weeks = [...new Set((MD.games[S] || []).filter(g => g.completed).map(g => `${g.seasonType}|${g.week}`))]
    .map(k => k.split('|')).sort((a, b) => (a[0] === b[0] ? 0 : a[0] === 'postseason' ? 1 : -1) || a[1] - b[1]);
  MD.sit[S] = {};
  for (const [i, [type, w]] of weeks.entries()) {
    const name = `sit2-${S}${type === 'postseason' ? 'p' : 'w'}${w}.json`, latest = S === SEASON && i === weeks.length - 1;
    const pull = async () => sitByGame((await cfbd(`plays?year=${S}&week=${w}&seasonType=${type}&classification=fbs`)).map(p => ({ g: p.gameId, o: p.offense,
      q: p.period, ytg: p.yardsToGoal, dn: p.down, ds: p.distance, y: p.yardsGained, t: p.playType,
      sm: p.offenseScore != null && p.defenseScore != null ? p.offenseScore - p.defenseScore : null })));
    const v = hasCache(name) && (!latest || OFFLINE) ? readCache(name) : await source(name, pull);
    Object.assign(MD.sit[S], v || {});
  }
  console.log(`situational splits ${S}: ${Object.keys(MD.sit[S]).length} team games`);
}
MD.venues = await once('venues.json', 'venues');
MD.teamsFbs = await once(`teamsfbs.json`, `teams/fbs?year=${SEASON}`);
MD.ppaqb = await cur(`ppaqb${SEASON}.json`, `ppa/players/season?year=${SEASON}&position=QB&excludeGarbageTime=true`);
MD.weather = hasCache('weather.json') ? readCache('weather.json') : {};
// returning production for the game model, a backtestable stand-in for FV (which has no history): each team's
// players in season S valued at their season S-1 PFN score (z within position and season, either division on the FBS
// curve) times S-1 snaps (per 700), transfers included; the QB (the team's highest) and everyone else, each as a z
// across FBS. Membership comes from PFN's season S rows (who has played there)
MD.pfnRet = {};
for (const S of [SEASON - 1, SEASON]) {
  const T = {};
  for (const p of POS) {
    const rows = pfn[p.g] || [], prev = rows.filter(r => r.season === S - 1 && r.division === 'FBS');
    if (!prev.length) continue;
    const m = prev.reduce((a, r) => a + r.score, 0) / prev.length, sd = Math.sqrt(prev.reduce((a, r) => a + (r.score - m) ** 2, 0) / prev.length) || 1;
    const by = {}; for (const r of rows) if (r.season === S - 1) by[norm(r.name)] = r;
    for (const r of rows) if (r.season === S && r.division === 'FBS') {
      const tid = idxTeams.resolve(r.team), q = by[norm(r.name)]; if (!tid) continue;
      const t = (T[tid] ||= { qb: null, rest: 0 });
      if (!q) continue;
      const v = (q.score - m) / sd * Math.min(1.3, (volume(q, false, p.g) || 0) / 700);
      if (p.g === 'QB') t.qb = Math.max(t.qb ?? -Infinity, v); else t.rest += v;
    }
  }
  const z = k => { const xs = Object.values(T).map(t => t[k] ?? 0), mm = xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
    const ss = Math.sqrt(xs.reduce((a, b) => a + (b - mm) ** 2, 0) / Math.max(1, xs.length)) || 1; return t => ((t[k] ?? 0) - mm) / ss; };
  const zq = z('qb'), zr = z('rest');
  MD.pfnRet[S] = Object.fromEntries(Object.entries(T).map(([tid, t]) => [tid, { qb: Math.round(zq(t) * 100) / 100, rest: Math.round(zr(t) * 100) / 100 }]));
  console.log(`returning production ${S}: ${Object.keys(T).length} teams`);
}
let model = null;
try {
  if (Object.values(MD.games).every(x => x?.length) && Object.values(MD.adv).every(x => x?.length)) {
    // FV team talent (projected starters' expected NFL value), z across FBS: the model's live talent input
    const tl = teamList.filter(t => t.talent != null), tm = tl.reduce((x, t) => x + t.talent, 0) / Math.max(1, tl.length);
    const ts = Math.sqrt(tl.reduce((x, t) => x + (t.talent - tm) ** 2, 0) / Math.max(1, tl.length)) || 1;
    model = await runModel(MD, SEASON, { talentZ: Object.fromEntries(tl.map(t => [String(t.tid), (t.talent - tm) / ts])) });
    writeCache('weather.json', MD.weather);
    const t = model.report.test || model.report.train;
    console.log(`model: test ${model.report.seasons.test ?? model.report.seasons.train} log loss ${t.logLoss} · MAE ${t.mae} (market ${t.maeMarket}) · ATS ${t.ats.all.pct}`);
  }
} catch (e) { console.log(`model: ${e.stack?.slice(0, 400)}`); }
const pstats = await source('player_stats.json', () => cfbd(`stats/player/season?year=${SEASON}`));
const gp = {}; for (const g of games || []) if (g.done) for (const id of [g.home, g.away]) gp[id] = (gp[id] || 0) + 1;
// kickers and punters (no PFN or On3 grades): each team's field goals over expected and punt value (from
// CFBD drives, scripts/cfb_model.mjs) credited to its kickers and punters by share of attempts, regressed
// (8 kicks, 10 punts), as z across FBS specialists with the longest make (K) and gross average (P). FV on
// a specialist's scale: an NFL team carries one of each and drafts few, so the best college kicker is a
// 50, an average starter ~37. The primary kicker's points over expected per game also price his absence
// in the game projections (special-teams weight from the game model).
const kp = (() => {
  if (!model?.units || !pstats) return { rows: [], byTeam: {} };
  const S = {};
  for (const x of pstats) if (x.category === 'kicking' || x.category === 'punting') {
    const k = `${x.category}|${x.playerId}`; (S[k] ||= { cat: x.category, id: String(x.playerId), name: x.player, team: x.team })[x.statType] = +x.stat;
  }
  const list = Object.values(S).map(r => ({ ...r, tid: idxTeams.resolve(r.team) })).filter(r => r.tid && fbsIds.has(r.tid));
  const tot = {}; for (const r of list) { const t = (tot[r.tid] ||= { fga: 0, no: 0 }); if (r.cat === 'kicking') t.fga += r.FGA || 0; else t.no += r.NO || 0; }
  const z = (xs, x) => { const v = xs.filter(n => n != null), m = v.reduce((a, b) => a + b, 0) / Math.max(1, v.length), sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, v.length)) || 1; return x == null ? 0 : (x - m) / sd; };
  const K = [], P = [];
  for (const r of list) {
    const u = model.units[r.team] || null; if (!u) continue;
    if (r.cat === 'kicking' && ((r.FGA || 0) >= 1 || (r.XPA || 0) >= 3)) {
      const share = tot[r.tid].fga ? (r.FGA || 0) / tot[r.tid].fga : 0, poe = u.fgPoe * share;
      K.push({ ...r, pos: 'K', poe, rate: poe / ((r.FGA || 0) + 8), poeG: poe / Math.max(1, u.games), xp: r.XPA ? r.XPM / r.XPA : null });
    }
    if (r.cat === 'punting' && (r.NO || 0) >= 3) {
      const share = tot[r.tid].no ? r.NO / tot[r.tid].no : 0, val = u.puntVal * share;
      P.push({ ...r, pos: 'P', val, rate: val / (r.NO + 10), ypp: r.YPP ?? (r.YDS / r.NO), in20: r['In 20'] != null ? r['In 20'] / r.NO : null });
    }
  }
  const qk = K.filter(k => (k.FGA || 0) >= 3), qp = P.filter(p => p.NO >= 8);
  for (const k of K) k.score = z(qk.map(x => x.rate), k.rate) + 0.25 * z(qk.map(x => x.LONG), k.LONG) + 0.15 * z(qk.map(x => x.xp), k.xp);
  for (const p of P) p.score = 0.6 * z(qp.map(x => x.rate), p.rate) + 0.3 * z(qp.map(x => x.ypp), p.ypp) + 0.1 * z(qp.map(x => x.in20), p.in20);
  const T = Object.fromEntries(teamList.map(t => [t.tid, t])), stars = new Set(manual.stars || []);
  const rows = [];
  for (const s of [...K, ...P]) {
    const e = (espn.rosters[s.tid] || []).find(a => a.id === s.id) || (espn.rosters[s.tid] || []).find(a => norm(a.name) === norm(s.name)) || {};
    const t = espn.teams[s.tid] || {}, years = e.years ?? null;
    const fvx = Math.max(25, Math.min(50, 37 + 4.5 * s.score)), fv = Math.round(fvx);
    const line = s.pos === 'K' ? `${s.FGM ?? 0}/${s.FGA ?? 0} FG (long ${s.LONG ?? '—'}), ${s.XPM ?? 0}/${s.XPA ?? 0} XP · ${s.poe >= 0 ? '+' : ''}${r1(s.poe)} pts over expected`
      : `${s.NO} punts, ${r1(s.ypp)} avg, ${s['In 20'] ?? 0} inside the 20 · ${s.val >= 0 ? '+' : ''}${r1(s.val)} pts of field position`;
    const age = e.dob ? (Date.now() - Date.parse(e.dob)) / 31557600000 : null;
    rows.push({ name: e.name || s.name, pos: s.pos, spot: null, team: t.name || s.team, tid: s.tid, logo: T[s.tid]?.logo || t.logo || null, color: t.color ? `#${t.color}` : null,
      conf: T[s.tid]?.conf || null, cls: years ? CLASS_NAMES[Math.min(years, 5) - 1] : null, elig: years, age: age ? r1(age) : null, ageEst: !age && years ? r1(18.4 + years) : null,
      ht: e.ht?.replace(/[' "]+/g, '-').replace(/-$/, '') || null, wt: e.wt || null, pfn: null, pfnLabel: line, snaps: null, on3: null, cons: null, xnil: null,
      fv, fvx: Math.round(fvx * 100) / 100, plus: false, star: stars.has(`${e.name || s.name}|${t.name}`) || stars.has(e.name || s.name) || null, draft27: years ? years >= 3 : null, parts: null,
      report: { role: s.pos === 'K' ? 'a kicker' : 'a punter', plus: s.score >= 0.5 ? [line] : [], minus: s.score <= -0.5 ? [line] : [], line },
      espnl: e.id ? `https://www.espn.com/college-football/player/_/id/${e.id}` : null, photo: e.headshot || null, poeG: s.poeG, score: s.score });
  }
  for (const g of ['K', 'P']) rows.filter(r => r.pos === g).sort((a, b) => b.score - a.score).forEach((r, i) => { r.posRank = i + 1; });
  // K+ / P+ for the board's Stat+ column: PFN has no specialist score, so a specialist's percentile at his position
  // is read off the FBS PFN distribution (the same percentile on the scale every other position uses)
  const pf = out.all.map(r => r.pfn).filter(x => x != null).sort((a, b) => a - b);
  for (const g of ['K', 'P']) { const gs = rows.filter(r => r.pos === g);
    for (const r of gs) r.kp = pf.length ? r1(pf[Math.min(pf.length - 1, Math.floor((1 - (r.posRank - 0.5) / gs.length) * pf.length))]) : null; }
  const byTeam = {};
  for (const r of rows.filter(r => r.pos === 'K')) if (!byTeam[r.tid] || (K.find(k => k.name === r.name)?.FGA || 0) > (byTeam[r.tid].fga || 0))
    byTeam[r.tid] = { name: r.name, poeG: r.poeG, fga: K.find(k => k.name === r.name)?.FGA || 0 };
  console.log(`specialists: ${rows.filter(r => r.pos === 'K').length} K, ${rows.filter(r => r.pos === 'P').length} P`);
  return { rows, byTeam };
})();
if (kp.rows.length) {
  out.all = [...out.all.filter(r => r.pos !== 'K' && r.pos !== 'P'), ...kp.rows].sort((a, b) => (b.fv ?? -1) - (a.fv ?? -1) || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || (b.comp ?? 0) - (a.comp ?? 0));
  out.all.forEach((r, i) => { r.ovr = i + 1; });
  writeAll();
}
// Transfer% (scripts/cfb_transfer.mjs, fit in data/cfb_transfer_fit.json by scripts/cfb_transfer_fit.py): ESPN's
// recruiting grades (class year and rank; past classes pulled once), PFN this season, who has played (CFBD stat
// lines), team records (CFBD games, FBS and FCS), hometowns (ESPN rosters) and this season's transfers in (CFBD portal)
const TFIT = path.join(ROOT, 'data', 'cfb_transfer_fit.json');
const portal = await source(`portal${SEASON}.json`, () => cfbd(`player/portal?year=${SEASON}`)) || [];
const geo = loadGeo(ROOT);
if (fs.existsSync(TFIT)) {
  const ESPN_CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football';
  const espnRec = {};
  for (let y = SEASON - 10; y <= SEASON; y++) {
    const name = `espnrec-${y}.json`;
    let list = hasCache(name) && (y < SEASON || OFFLINE) ? readCache(name) : null;
    if (!list) {
      list = await source(name, async () => {
        const acc = [];
        for (let pg = 1; pg <= 10; pg++) {
          const d = await get(`${ESPN_CORE}/recruiting/${y}/athletes?limit=1000&page=${pg}`, 'json');
          for (const it of d.items || []) if (it.athlete?.alternateId) acc.push([it.athlete.alternateId, +it.grade || 0]);
          if (pg >= (d.pageCount || 1)) break;
          await sleep(150);
        }
        return acc;
      }) || [];
    }
    for (const [id, grade] of list) espnRec[id] = { year: y, grade };
  }
  const roster = {};
  for (const src of [espn.rosters, espnFcs.rosters]) for (const list of Object.values(src || {})) for (const a of list) roster[a.id] = a;
  const winp = {}, wl = {};
  for (const g of gamesCfbdNow || []) if (g.completed && g.homePoints != null && g.awayPoints != null) {
    const h = idxAll.resolve(g.homeTeam), a = idxAll.resolve(g.awayTeam);
    if (h) { const x = (wl[h] ||= [0, 0]); x[g.homePoints > g.awayPoints ? 0 : 1]++; }
    if (a) { const x = (wl[a] ||= [0, 0]); x[g.awayPoints > g.homePoints ? 0 : 1]++; }
  }
  for (const [tid, [w, l]] of Object.entries(wl)) if (w + l) winp[tid] = w / (w + l);
  const newcomers = new Set();
  for (const m of portal) { const to = m.destination ? idxAll.resolve(m.destination) : null; if (to) newcomers.add(to + '|' + norm(`${m.firstName} ${m.lastName}`)); }
  tctx = { fit: JSON.parse(fs.readFileSync(TFIT, 'utf8')), season: SEASON, geo, norm, roster, recruits: espnRec, winp, newcomers,
    pfnIx: pfnIndex(pfn, SEASON, n => idxAll.resolve(n), norm, volume), played: new Set((pstats || []).map(x => String(x.playerId))) };
  writeAll();
  const all = [...out.all, ...outFcs.all], tp = all.filter(r => r.transferP != null);
  console.log(`transfer%: ${tp.length} players, mean ${(tp.reduce((a, r) => a + r.transferP, 0) / Math.max(1, tp.length)).toFixed(3)}; ` +
    `${Object.keys(espnRec).length} ESPN recruits, ${tp.filter(r => r.homeMi != null).length} with a hometown`);
  // team builder (static/data/cfb-builder.json, loaded by the page on demand): each FBS program's offseason plan
  if (teamList.length && nilMarket?.price) {
    const tb = teamBuilder(all, teamList, { fit: tctx.fit, geo, price: nilMarket.price, season: SEASON });
    fs.writeFileSync(path.join(ROOT, 'static', 'data', 'cfb-builder.json'), JSON.stringify({ asof: out.asof, ...tb }));
    console.log(`team builder: ${tb.teams.length} plans, ${tb.teams.reduce((a, t) => a + t.plan.length, 0)} signings`);
  }
  for (const r of all) delete r._home;
}
const slate = nextWeek ? gamesModel(games.filter(g => g.week === nextWeek && !g.done), teamList, out.all, injuries || {},
  { adv: byEspn(advanced, x => x), rates: playerRates(pstats, n => idxTeams.resolve(n), games), gp, model, kickers: kp.byTeam }) : [];
fs.writeFileSync(GAMES_OUT, JSON.stringify({ asof: out.asof, week: nextWeek, injuriesAsof: injuries ? out.asof : null, games: slate }, null, 1) + '\n');
// top performers (data/cfb_top.json): the latest week with nearly every game played, from CFBD box scores
// (one call a week; a played week's box scores don't change, so each is cached)
{
  const wk = {}; for (const g of games || []) { const x = (wk[g.week] ||= { n: 0, done: 0 }); x.n++; if (g.done) x.done++; }
  const last = Object.entries(wk).filter(([, x]) => x.done / x.n >= 0.8).map(([w]) => +w).sort((a, b) => b - a)[0];
  if (last) {
    const name = `gplayers${SEASON}w${last}.json`;
    const boxes = hasCache(name) && readCache(name).length >= 0.8 * wk[last].n * 0.5 ? readCache(name)
      : await source(name, () => cfbd(`games/players?year=${SEASON}&week=${last}&seasonType=regular&classification=fbs`));
    const byEspnId = {}; for (const r of out.all) { const id = /\/id\/(\d+)/.exec(r.espnl || '')?.[1]; if (id) byEspnId[id] = r; }
    const roster = {}; for (const [tid, list] of Object.entries(espn.rosters)) for (const a of list) roster[a.id] = { ...a, tid };
    const TL = Object.fromEntries(teamList.map(t => [t.tid, t]));
    const posOf = (id, nm, team) => byEspnId[id]?.pos || ESPN_GROUP(roster[id]?.pos);
    const teamOf = x => { const r = byEspnId[x.id], tid = r?.tid || roster[x.id]?.tid || idxTeams.resolve(x.team), t = TL[tid];
      return { team: t?.team || x.team, logo: t?.logo || null, fv: r?.fv ?? null, star: r?.star || null, cls: r?.cls || null }; };
    const top = boxes ? topPerformers(boxes, posOf, teamOf) : null;
    if (top) fs.writeFileSync(path.join(ROOT, 'data', 'cfb_top.json'), JSON.stringify({ asof: out.asof, week: last, groups: TOP_GROUPS, top }, null, 1) + '\n');
  }
}
// transfer portal (data/cfb_portal.json): CFBD's portal list for this season matched to the board at the
// destination school (FV, position, class), with each team's net: expected NFL value (AV a season by FV)
// brought in minus sent out
{
  const byTeamName = {}; for (const r of out.all) if (r.tid) byTeamName[r.tid + '|' + norm(r.name)] = r;
  const TL = Object.fromEntries(teamList.map(t => [t.tid, t]));
  const moves = [];
  for (const m of portal) {
    const name = `${m.firstName} ${m.lastName}`.trim(), to = m.destination ? idxTeams.resolve(m.destination) : null, from = idxTeams.resolve(m.origin);
    const r = to ? byTeamName[to + '|' + norm(name)] || variant(out.all.filter(x => x.tid === to), name) : null;
    if (!r && !(from && TL[from]) && !(to && TL[to])) continue;
    moves.push({ name: r?.name || name, pos: r?.pos || m.position, fv: r?.fv ?? null, star: r?.star || null, cls: r?.cls || null,
      from: TL[from]?.team || m.origin, fromLogo: TL[from]?.logo || null, to: to ? TL[to]?.team || m.destination : m.destination || null, toLogo: to ? TL[to]?.logo || null : null,
      stars: m.stars ?? null, rating: m.rating ?? null, date: m.transferDate?.slice(0, 10) || null, fromTid: from, toTid: to });
  }
  const net = {};
  for (const mv of moves) if (mv.fv != null) {
    const av = avOf(mv.fv);
    if (mv.toTid && TL[mv.toTid]) { const x = (net[mv.toTid] ||= { in: 0, out: 0, nIn: 0, nOut: 0 }); x.in += av; x.nIn++; }
    if (mv.fromTid && TL[mv.fromTid]) { const x = (net[mv.fromTid] ||= { in: 0, out: 0, nIn: 0, nOut: 0 }); x.out += av; x.nOut++; }
  }
  const teams = Object.entries(net).map(([tid, x]) => ({ team: TL[tid].team, logo: TL[tid].logo, conf: TL[tid].conf, in: r1(x.in), out: r1(x.out), net: r1(x.in - x.out), nIn: x.nIn, nOut: x.nOut }))
    .sort((a, b) => b.net - a.net);
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_portal.json'), JSON.stringify({ asof: out.asof, season: SEASON,
    moves: moves.sort((a, b) => (b.fv ?? 0) - (a.fv ?? 0) || (b.rating ?? 0) - (a.rating ?? 0)).map(({ fromTid, toTid, ...m }) => m), teams }, null, 1) + '\n');
  console.log(`portal: ${moves.length} moves, ${moves.filter(m => m.fv != null).length} graded`);
}
// breakout watch (data/cfb_breakout.json): first- and second-year players whose touches + targets per game
// over their last two games run well ahead of their earlier games (play-by-play), with their FV
{
  const when = Object.fromEntries((games || []).map(g => [String(g.id), g.date]));
  const byKey = {}; for (const r of out.all) if (r.tid && ['QB', 'RB', 'WR', 'TE'].includes(r.pos)) byKey[r.tid + '|' + pbpKey(r.name)] = r;
  const list = [];
  for (const a of Object.values(pbp)) {
    const tid = idxTeams.resolve(a.team), r = tid ? byKey[tid + '|' + a.key] : null;
    if (!r || !(r.elig <= 2)) continue;
    const gs = Object.entries(a.games || {}).sort((x, y) => (when[x[0]] || '').localeCompare(when[y[0]] || '')).map(([, n]) => n);
    if (gs.length < 4) continue;
    const last = (gs.at(-1) + gs.at(-2)) / 2, before = gs.slice(0, -2).reduce((s, n) => s + n, 0) / (gs.length - 2);
    if (last >= 6 && last - before >= 4 && last >= 1.5 * Math.max(1, before) && gs.at(-1) > before)
      list.push({ name: r.name, pos: r.pos, team: r.team, logo: r.logo, cls: r.cls, fv: r.fv, star: r.star || null, games: gs, before: r1(before), last: r1(last), jump: r1(last - before) });
  }
  list.sort((a, b) => b.jump - a.jump);
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_breakout.json'), JSON.stringify({ asof: out.asof, players: list.slice(0, 60) }, null, 1) + '\n');
  console.log(`breakouts: ${list.length}`);
}
// scheme fingerprints for the staff tab: offense tempo (plays a game), run rate, 4th-down go rate (plays
// on 4th down that aren't punts or field goals, of all 4th-down decisions), defense havoc, stuff rate and
// explosiveness allowed (CFBD advanced season stats and play-by-play); percentile among FBS teams
const scheme = (() => {
  const gpT = {}; for (const g of games || []) if (g.done) for (const id of [g.home, g.away]) gpT[id] = (gpT[id] || 0) + 1;
  const go = {};
  for (const p of playsNow) if (p.dn === 4 && !/Penalty|Timeout|End|Kickoff/.test(p.t || '')) {
    const tid = idxTeams.resolve(p.o); if (!tid) continue;
    const x = (go[tid] ||= { go: 0, n: 0 }); x.n++; if (!/Punt|Field Goal/.test(p.t)) x.go++;
  }
  const S = {};
  for (const a of advanced || []) {
    const tid = idxTeams.resolve(a.team); if (!tid || !gpT[tid]) continue;
    S[tid] = { tempo: (a.offense?.plays ?? 0) / gpT[tid], run: a.offense?.rushingPlays?.rate ?? null, go: go[tid]?.n >= 5 ? go[tid].go / go[tid].n : null,
      havoc: a.defense?.havoc?.total ?? null, stuff: a.defense?.stuffRate ?? null, xpl: a.defense?.explosiveness ?? null,
      // over the league's rate in the same situations (game model, scripts/cfb_model.mjs): 4th-down go rate, pass rate
      goOe: model?.coach?.[tid]?.f4n >= 5 ? model.coach[tid].goOe : null, proe: model?.coach?.[tid]?.pn >= 100 ? model.coach[tid].proe : null };
  }
  const pct = (k, low = false) => { const v = Object.values(S).map(x => x[k]).filter(x => x != null).sort((a, b) => a - b);
    for (const x of Object.values(S)) if (x[k] != null) { const i = v.findIndex(y => y >= x[k]); x[k + 'P'] = Math.round(100 * (low ? 1 - i / v.length : i / v.length)); } };
  for (const k of ['tempo', 'run', 'go', 'goOe', 'proe', 'havoc', 'stuff']) pct(k); pct('xpl', true);
  return S;
})();
// edge log (data/cfb_edges.json): each run records the model's line on every coming game with a market line,
// replacing the earlier entry until kickoff; played games are graded against the closing line (CFBD), so the
// record by edge size is the model's, at the price it would have been bet
const EDGES = path.join(ROOT, 'data', 'cfb_edges.json');
const edgeLog = fs.existsSync(EDGES) ? JSON.parse(fs.readFileSync(EDGES, 'utf8')) : { games: {} };
for (const g of slate) if (g.proj && g.market != null && Date.parse(g.date) > Date.now())
  edgeLog.games[g.id] = { week: nextWeek, date: g.date, home: g.home.name, away: g.away.name, model: r1(-g.proj.margin), market: g.market,
    total: g.proj.total, ou: g.total ?? null, at: out.asof };
const closing = Object.fromEntries((MD.lines[SEASON] || []).map(l => [String(l.id), l]));
const bucket = e => e < 3 ? '0-3' : e < 7 ? '3-7' : '7+';
const rec = { all: { w: 0, l: 0, p: 0 }, '0-3': { w: 0, l: 0, p: 0 }, '3-7': { w: 0, l: 0, p: 0 }, '7+': { w: 0, l: 0, p: 0 } }, ouRec = { w: 0, l: 0, p: 0 };
for (const [id, e] of Object.entries(edgeLog.games)) {
  const c = closing[id], ln = c?.lines?.find(l => l.provider === 'consensus') || c?.lines?.find(l => l.provider === 'ESPN Bet') || c?.lines?.find(l => l.spread != null);
  if (!c || c.homeScore == null || c.awayScore == null || ln?.spread == null) continue;
  // spreads from the home side, negative = home favoured; the model's side is the one it likes more than the close
  const edge = ln.spread - e.model, cover = (c.homeScore - c.awayScore) + ln.spread;
  e.close = ln.spread; e.result = `${c.awayScore}-${c.homeScore}`; e.edge = r1(Math.abs(edge));
  e.ats = Math.abs(edge) < 0.5 ? null : cover === 0 ? 'P' : Math.sign(edge) === Math.sign(cover) ? 'W' : 'L';
  if (e.ats) for (const k of ['all', bucket(Math.abs(edge))]) rec[k][e.ats.toLowerCase()]++;
  if (e.total != null && ln.overUnder != null) {
    const d = e.total - ln.overUnder, actual = c.homeScore + c.awayScore - ln.overUnder;
    e.ou = Math.abs(d) < 1 ? null : actual === 0 ? 'P' : Math.sign(d) === Math.sign(actual) ? 'W' : 'L';
    if (e.ou) ouRec[e.ou.toLowerCase()]++;
  }
}
edgeLog.record = rec; edgeLog.ou = ouRec; edgeLog.asof = out.asof;
fs.writeFileSync(EDGES, JSON.stringify(edgeLog, null, 1) + '\n');
// the model report and season simulation: data/cfb_model.json
if (model) {
  const T = Object.fromEntries(teamList.map(t => [t.tid, t]));
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_model.json'), JSON.stringify({ asof: out.asof, report: model.report, live: { record: rec, ou: ouRec },
    sim: model.sim.filter(s => T[s.tid]).map(s => ({ ...s, team: T[s.tid].team, abbr: T[s.tid].abbr, logo: T[s.tid].logo, rating: r1(model.rating[s.tid] ?? 0), situ: model.situ?.[s.tid] || null,
      ratingRk: null })).sort((a, b) => b.rating - a.rating).map((s, i) => ({ ...s, ratingRk: i + 1 })) }, null, 1) + '\n');
}
// player projections for the week (PPR), top 300: data/cfb_proj.json
fs.writeFileSync(PROJ_OUT, JSON.stringify({ asof: out.asof, week: nextWeek, players: (slate.players || []).slice(0, 300) }) + '\n');
const coaches = teamList.length ? staffModels(out.all, teamList, staffData?.teams) : [];
const r2s = x => x == null ? null : Math.round(x * 100) / 100;
// coach photos: each coach's Wikipedia article image (pageimages, 50 titles a call), cached by title; the
// staff tab and the coach GFX card frame them, falling back to the team logo
{
  const store = hasCache('coachphotos.json') ? readCache('coachphotos.json') : {};
  const titleOf = u => decodeURIComponent((/\/wiki\/([^#?]+)/.exec(u || '') || [])[1] || '').replace(/_/g, ' ');
  const want = [...new Set(coaches.flatMap(c => [c.wiki, ...Object.values(c.wikis || {})]).map(titleOf).filter(t => t && !(t in store)))];
  for (let i = 0; i < want.length; i += 50) {
    try {
      const q = `https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages&piprop=thumbnail&pithumbsize=400&redirects=1&titles=${encodeURIComponent(want.slice(i, i + 50).join('|'))}`;
      const d = JSON.parse(await getRetry(q));
      const back = {}; for (const n of d.query?.normalized || []) back[n.to] = n.from; for (const n of d.query?.redirects || []) back[n.to] = back[n.from] || n.from;
      for (const pg of Object.values(d.query?.pages || {})) store[back[pg.title] || pg.title] = pg.thumbnail?.source || null;
      for (const t of want.slice(i, i + 50)) if (!(t in store)) store[t] = null;
    } catch (e) { console.log(`coach photos: ${e.message.slice(0, 80)}`); break; }
  }
  writeCache('coachphotos.json', store);
  for (const c of coaches) {
    const ts = c.wikis ? Object.values(c.wikis).map(titleOf) : [titleOf(c.wiki)];
    c.photo = ts.map(t => store[t]).find(Boolean) || null;
  }
  console.log(`coach photos: ${coaches.filter(c => c.photo).length} of ${coaches.length}`);
}
for (const c of coaches) { const x = scheme?.[c.tid]; if (!x) continue;
  c.scheme = c.role === 'DC' ? { havoc: r2s(x.havoc), havocP: x.havocP, stuff: r2s(x.stuff), stuffP: x.stuffP, xpl: r2s(x.xpl), xplP: x.xplP }
    : c.role === 'OC' ? { tempo: Math.round(x.tempo), tempoP: x.tempoP, run: r2s(x.run), runP: x.runP, proe: x.proe, proeP: x.proeP }
    : { go: r2s(x.go), goP: x.goP, goOe: x.goOe, goOeP: x.goOeP, tempo: Math.round(x.tempo), run: r2s(x.run), proe: x.proe, proeP: x.proeP }; }
fs.writeFileSync(TEAMS_OUT, JSON.stringify({ asof: out.asof, games: games?.filter(g => g.done).length ?? 0,
  weeks: games?.length ? Math.max(...games.filter(g => g.done).map(g => g.week)) : 0, teams: teamList, coaches }, null, 1) + '\n');
// team rankings (data/cfb_rank.json, scripts/cfb_rank.mjs): the AP and Coaches polls (and the CFP's once it
// ranks) from ESPN, next to our power ranking of every FBS team, with the backtest against the polls (CFBD's weekly
// polls, the past season pulled once)
if (model && teamList.length) {
  try {
    const RANK_OUT = path.join(ROOT, 'data', 'cfb_rank.json');
    const espnPolls = await source('polls.json', () => get('https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings', 'json'));
    const hist = {};
    for (const S of [SEASON - 1, SEASON]) hist[S] = await (S < SEASON ? once : cur)(`rankings${S}.json`, `rankings?year=${S}&seasonType=regular`);
    const tl = teamList.filter(t => t.talent != null), tm = tl.reduce((x, t) => x + t.talent, 0) / Math.max(1, tl.length);
    const ts = Math.sqrt(tl.reduce((x, t) => x + (t.talent - tm) ** 2, 0) / Math.max(1, tl.length)) || 1;
    const prev = fs.existsSync(RANK_OUT) ? JSON.parse(fs.readFileSync(RANK_OUT, 'utf8')) : null;
    const weeksPlayed = games?.some(g => g.done) ? Math.max(...games.filter(g => g.done).map(g => g.week)) : 0;
    const R = teamRankings({ model, teamList, coaches, talentZ: Object.fromEntries(tl.map(t => [String(t.tid), (t.talent - tm) / ts])), late: (nextWeek ?? 0) >= 5,
      polls: readPolls(espnPolls), hist, resolve: n => idxTeams.resolve(n), prev, week: weeksPlayed });
    fs.writeFileSync(RANK_OUT, JSON.stringify({ asof: out.asof, ...R }, null, 1) + '\n');
    const ev = R.evidence;
    console.log(`rankings: ${R.teams.length} teams · polls ${Object.keys(R.polls).join(', ')} · staff ${R.staffUsed.join(', ') || 'none'} · ` +
      (ev.vsPolls || []).map(v => `${v.season} ${v.poll} ${v.pollPct} vs ours ${v.oursPct} (n ${v.n})`).join(' · '));
  } catch (e) { console.log(`rankings: ${e.stack?.slice(0, 400)}`); }
}
if (tank) {
  const picks = mockDraft([...out.all, ...outFcs.all], tank, 7, draftPriors());
  await nflLogos(picks);
  fs.writeFileSync(MOCK_OUT, JSON.stringify({ asof: out.asof, rounds: Math.max(...picks.map(p => p.round)), picks }, null, 1) + '\n');
}
console.log(`teams: ${teamList.length} (${games?.length ?? 0} games) · coaches: ${coaches.length} · mock: ${tank ? 'yes' : 'no'}`);
const { all, ...boardOut } = out;
fs.writeFileSync(OUT, JSON.stringify(boardOut, null, 1) + '\n');
const tiers = {};
for (const p of out.players) { const t = Math.floor(p.fv / 5) * 5; tiers[t] = (tiers[t] || 0) + 1; }
console.log(`board: ${out.count} players of ${out.population} graded · FV tiers`, tiers);
