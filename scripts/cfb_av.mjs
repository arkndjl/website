// Season AV for the College Football ARKBOARD: what a player is worth to his college team this season, in AV
// a season, measured from what he has done (Stat+ x snaps x position value), next to avOf(fv) in cfb_teams.mjs,
// which stays the expected NFL value by FV. Called by scripts/fetch_cfb.mjs on every FBS row (sets row.sav).
//
//   points   share x SAV_W[pos] x (q + 1): points of team margin a game over a replacement player, where
//            share = snap share, q = quality in SD of the position's starter pool (the top STARTERS x teams
//            by score), and replacement is a starter 1 SD below the average one (SAV_REPL)
//   q        Stat+ z + SAV_Q.badge x badge-points z + SAV_Q.fv x FV z, re-standardized on the starter pool
//   AV       points / SAV_PTS (floored at 0): one AV is 0.42 points a game, about 5 points of margin over a
//            12-game season, the rate the game model already charges a missing starter (8 Elo per AV)
//
// Backtest: scripts/cfb_av_backtest.mjs -> data/cfb_av_backtest.json (PFN 2019-26, ESPN results, team margin
// as opponent-adjusted SRS). SAV_W is fit on 2024-25 team seasons (the two with all ten positions graded,
// ridge toward a common weight) and tested on 2026: summed over each team's starters it explains 62% of
// margin (r .79), against 44% for summed avOf(fv) (r .66). Badges and FV add to that within 2026 (t 3.2 and
// 2.5, cross-validated); their weights are half the fitted ones. Context (cast, SOS, over-expected) adds
// little once those are in, and regressing by snaps did not help. Season AV is a college measure: it predicts NFL AV no better than Stat+
// (pooled r .35 vs .40), so FV and avOf stay the NFL measure. Added to FV's production term (Marcel blend, K 3000)
// it fails FV's bar at every position (backtest fvTest): partial r -.14 QB, -.11 WR, -.17 TE (more college volume at
// the same production rate, fewer NFL AV), |t| < 2 elsewhere, pooled -.03. So season AV does not feed FV. WAA (wins
// over an average starter at the position, below) fails the same bar (fvTest waa, 2026-10-13): pooled partial r
// .01 (t .7), every position |t| < 2 and no out-of-sample gain, QB -.10, DT +.07 the largest. FV is already graded
// within position, so WAA's cross-position scale adds nothing, and what is left of it is playing time, which
// production already holds. The QB's shared credit only takes receivers from -.10 (own WAA) to 0.
// Refit on more seasons (2026-10-14): pooling 2019-25 (OL, CB and S graded only since 2024) tested worse on 2026
// (Stat+ only r^2 .639 vs .656, board quality .667 vs .684) and pushed QB to 4.05, since the ungraded spots' worth
// loads on the graded ones; 2023-25 and 2021-25 fits and heavier ridge did no better. The 2024-25 fit stays.
export const SAV_W = { QB: 2.75, RB: 0.82, WR: 0.55, TE: 0.28, OL: 0.17, EDGE: 0.83, DL: 0.23, LB: 0.4, CB: 0.72, S: 0.74 };
export const SAV_REPL = -1;
export const SAV_Q = { badge: 0.5, fv: 0.25 };
export const SAV_PTS = 0.42;

// Football WAR: wins above replacement a season, the unit the site shows in place of AV. Backtest:
// scripts/cfb_war_backtest.mjs -> data/cfb_war_backtest.json.
//   college  cWAR = snap share x (CWAR_V[pos] + SAV_W[pos] x q) x 12 games x CWAR_WP_PER_PT: the season-AV points of
//            margin a game, measured over a replacement starter CWAR_V points below the average FBS starter (2.73 at QB,
//            from missed games and the NFL's line; the lineup total is 2 SD = CWAR_REPL at every spot; season AV keeps its 1 SD line; a QB's slope is
//            CWAR_QB_OWN, the rest shared with his offense), times the win% a point of average margin is worth: .0189, fit on 928 FBS team seasons
//            2019-25 (r .91; each season .018-.020), tested on 2026 (r .88). About 4.4 points of margin a game over a
//            season is one win. CWAR_REPL is set so team WAR adds up to wins over a replacement team, the NFL anchor
//            (3 wins in 17, .176): at the 1 SD line a lineup of replacement starters projected to .376 win% (2026
//            teams), far too good for freely available players; at 2 SD it is .18 and the average FBS team's starters
//            sum to 3.9 WAR, its 6 wins of 12 less 2.1. One season AV is still .095 WAR (CWAR_PER_AV) for gains
//   NFL      nWAR = (NFL AV - NFL_REPL_AV x snap share) x NWAR_PER_AV (the board, scripts/nfl_war.py, uses a line by
//            position, NFL_REPL there: part-timers' AV rate, TE 2.6 to RB 9.0, averaging this one; defense's AV splits
//            its pool by EPA credits, pressures not sacks, data/nfl_war_def.json). NWAR_PER_AV .091 is wins per team AV, fit on
//            2021-25 team seasons (160, r .85; leaving out each season .086-.096); the points route (3.83 points an AV,
//            35.5 points a win) gave .108, which ran team WAR to 2x wins. NFL_REPL_AV 6.2 is the AV a replacement
//            player earns in a full season of snaps, prorated by snaps played, set so a replacement team (22 starters
//            at full snaps, 137 AV) wins 3 of 17: team nWAR then sums to wins - 3 (mean 5.5 against 8.5 wins). By FV
//            (no snaps yet) nWAR is measured, not derived: NFL_WAR_BY_AV is what drafted players (2016-21 classes,
//            seasons through 2025) at each mean AV a season active earned a season active on the board's position
//            lines (data/nfl_war_pos.json careerCurve, `python3 scripts/nfl_war.py --positions`), floored at 0:
//            FV 80 = .32, FV 60 = .13, FV 50 = .07, FV 40 = .02 nWAR a season. That is the expected season, busts
//            and backup years in; a season at the FV's outcome tier is far more (the prime column of the FV table,
//            seasonPct in the same file: the top 4% of regulars' seasons, All-Pro, is .67)
//   by FV    college roster tools (team talent, team builder, recruits, portal) value a player by FV on the FV
//            curve (avOf). Summed over each team's projected starters it matches team season AV one for one
//            (through-origin slope 1.06, 2026), so it converts at the college rate. A college curve fit from
//            this season's starters (sav by FV tier) predicts team margin no better (cross-validated r .56 vs .555),
//            so the curve's shape stays, and AV at FV x CWAR_PER_AV is expected college WAR at that FV
// Models stay linear in AV inside (team builder, recruit sims, xNIL worth, game-model features), so WAR is the
// same value in other units and no model's behavior changes. Old AV fields stay as they were; WAR fields sit beside.
export const CWAR_WP_PER_PT = 0.0189, CWAR_GAMES = 12, CWAR_REPL = -2;
// by position (scripts/cfb_war_pos_backtest.mjs): the replacement line sits CWAR_SUB_V points a game below an average
// full-time starter at his spot. Team margin can't set these (every team fields every spot, so a position's level is
// nearly constant across teams); three measures can, blended by precision (the backtest's subBlend):
//   missed  what a team lost when an average regular sat, 4,995 regular-season FBS-vs-FBS games (2019-25, ESPN box
//           scores, team-season and opponent fixed effects): QB 2.65 (SE .56; 2.66 in 2019-22, 2.54 in 2023-25), the rest
//           within one to two SE of zero to 1.5 (box scores can't see linemen, and before 2024 most carry no defensive
//           lines). A QB counts absent when he didn't play (under 10% of the passes); bowls are out (opt-outs). The old
//           measure, 5.24, kept bowls and counted a QB pulled mid-game as partly absent, which tied absence to the score
//   NFL     the NFL's lines by sub-position (data/nfl_war_pos.json: missed games, contracts and AV, tested on held-out
//           seasons), as shares of a lineup's value scaled to the college lineup, with a 40% SD for the move down a level
//   grade   2 SD of the position's PFN grade x SAV_W (the line before), with a 50% SD: it ties a position's worth to how well
//           its grade tracks margin, which undersells linemen, whose grades track it worst
// Sub-positions: OL by PFN's spot (tackles vs guards and centers), the team's third WR by snaps in the slot (SWR) and
// its third CB at nickel (NCB). Non-QB values are scaled together so the lineup totals 2 SD x SAV_W at every spot
// (25.8 points, a replacement team's .18).
// QB credit: a better QB's absence costs .97 points a SD more (SE .42), well under his grade's 2.75 slope with margin,
// so much of what a QB grade tracks is the offense around him, which stays when he sits. His own slope is CWAR_QB_OWN
// points a SD (the split that best predicts next season's margin from returning players, 2020-25); the rest of SAV_W.QB x his quality x his
// share goes to his offensive teammates by snap share, so a team's WAR, and its fit to margin, is unchanged
const r2 = x => Math.round(x * 100) / 100;
export const CWAR_SUB_V = { QB: 2.73, RB: 1.67, WR: 1.35, SWR: 1.21, TE: 0.81, OT: 0.9, IOL: 0.77, EDGE: 1.38, DL: 1, LB: 0.98, CB: 1.26, NCB: 1.13, S: 1.11 };
const SUB_SLOTS = { WR: ['WR', 'WR', 'SWR'], OL: ['OT', 'OT', 'IOL', 'IOL', 'IOL'], CB: ['CB', 'CB', 'NCB'] };
// by position: the mean over its starting slots (a lineman with no spot, team totals by position)
export const CWAR_V = Object.fromEntries(Object.keys(SAV_W).map(g => [g, SUB_SLOTS[g] ? r2(SUB_SLOTS[g].reduce((a, k) => a + CWAR_SUB_V[k], 0) / SUB_SLOTS[g].length) : CWAR_SUB_V[g]]));
// sub-position: rank = his order by snap share among the team's players at the position (0 = most), spot = PFN's OL spot
export const subOf = (g, rank, spot) => g === 'WR' ? (rank < 2 ? 'WR' : 'SWR') : g === 'CB' ? (rank < 2 ? 'CB' : 'NCB')
  : g === 'OL' ? (!spot ? null : /T$/.test(spot) ? 'OT' : 'IOL') : g;
const subV = (g, rank, spot) => CWAR_SUB_V[subOf(g, rank, spot)] ?? CWAR_V[g];
export const CWAR_QB_OWN = 1.25;
export const CWAR_PER_PT = CWAR_GAMES * CWAR_WP_PER_PT;              // WAR a season per point of margin a game
export const CWAR_PER_AV = SAV_PTS * CWAR_PER_PT;                    // .0953
export const NWAR_PER_AV = 0.091, NFL_REPL_AV = 6.2;
// college WAR from college AV (season AV, or AV at FV on a college roster)
export const cwar = av => (av == null ? null : r2(av * CWAR_PER_AV));
// a specialist's college WAR from his points over an average kicker or punter (field goals over expected, punt field
// position) in his team's games: per game, x 12 games x the win rate. Kickers and punters are freely available, so
// the average one stands in for replacement and the number can be negative
export const specialistWar = (pts, games) => (pts == null ? null : r2(pts / Math.max(1, games) * CWAR_GAMES * CWAR_WP_PER_PT));
// NFL WAR a season active by mean NFL AV a season active, drafted players 2016-21 (data/nfl_war_pos.json careerCurve,
// bin means): [AV, WAR]
export const NFL_WAR_BY_AV = [[0.13, -0.005], [0.84, 0.003], [1.74, 0.022], [2.76, 0.048], [3.70, 0.071], [4.85, 0.120], [6.21, 0.167], [7.97, 0.277], [11.08, 0.555]];
const nflWarByAv = av => {
  const T = NFL_WAR_BY_AV; if (av <= T[0][0]) return T[0][1];
  for (let i = 1; i < T.length; i++) if (av <= T[i][0]) { const [a, x] = T[i - 1], [b, y] = T[i]; return x + (y - x) * (av - a) / (b - a); }
  return T[T.length - 1][1];
};
// NFL WAR from NFL AV a season and the snap share played (a full season = 1); without a share (by FV), the measured
// WAR of drafted players at that AV, floored at 0
export const nwar = (av, share) => (av == null ? null : share == null
  ? r2(Math.max(0, nflWarByAv(av))) : r2((av - NFL_REPL_AV * share) * NWAR_PER_AV));
const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const TIER = { b: 1, s: 2, g: 3, p: 4 };
const OFF = ['QB', 'RB', 'WR', 'TE', 'OL'];

const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
export const badgePoints = p => (p.badges || []).reduce((a, b) => a + (TIER[Array.isArray(b) ? b[1] : b.tier?.[0]] || 0), 0);

// z of f(p) on each position's starter pool, for every row with a value
function poolZ(rows, f, nTeams, posOf = p => p.pos) {
  const out = new Map(), by = {};
  for (const p of rows) { const v = f(p); if (v != null && Number.isFinite(v)) (by[posOf(p)] ||= []).push([p, v]); }
  for (const [g, list] of Object.entries(by)) {
    const pool = list.map(x => x[1]).sort((a, b) => b - a).slice(0, (STARTERS[g] || 1) * nTeams), m = mean(pool), s = sd(pool);
    for (const [p, v] of list) out.set(p, (v - m) / s);
  }
  return out;
}

// sets p.sav (AV a season, college), p.war (college WAR a season, over the CWAR_V line), p.waa (over an average starter at
// his position) and p.savQ (quality, SD of the starter pool) on every row with a PFN score
// and a snap share; the rest get null. rows: one division's graded players; posOf: the position field
// (board rows: p.pos; fetch_cfb.mjs build() players: p.g). opts.warOnly (FCS): set p.war only, leaving p.sav and
// p.savQ null, so the FCS xNIL block keeps pricing on FV. FCS WAR is wins over an FCS replacement starter, on the
// FBS position weights and win rate (no FCS fit of its own)
export function seasonAv(rows, posOf = p => p.pos, opts = {}) {
  const spotOf = opts.spotOf || (p => p.pfnPos ?? p.spot);
  const nTeams = new Set(rows.map(p => p.tid).filter(Boolean)).size || 1;
  const live = rows.filter(p => SAV_W[posOf(p)] != null && p.pfn != null && p.snapShare != null);
  const zs = poolZ(live, p => p.pfn, nTeams, posOf), zb = poolZ(live, badgePoints, nTeams, posOf), zf = poolZ(live, p => p.fv, nTeams, posOf);
  const q = poolZ(live, p => zs.get(p) + SAV_Q.badge * (zb.get(p) ?? 0) + SAV_Q.fv * (zf.get(p) ?? 0), nTeams, posOf);
  for (const p of rows) { p.sav = null; p.savQ = null; p.war = null; p.waa = null; }
  // each player's line: his sub-position's (WR and CB by his snap order on the team)
  const order = {}, line = new Map();
  for (const p of live) (order[p.tid + '|' + posOf(p)] ||= []).push(p);
  for (const ps of Object.values(order)) ps.sort((a, b) => b.snapShare - a.snapShare).forEach((p, i) => line.set(p, subV(posOf(p), i, spotOf(p))));
  const pts = new Map(), shared = {};
  for (const p of live) {
    const g = posOf(p), s = Math.min(1, p.snapShare);
    p.savQ = Math.round(q.get(p) * 100) / 100;
    p.sav = Math.round(Math.max(0, s * SAV_W[g] * (p.savQ - SAV_REPL)) / SAV_PTS * 10) / 10;
    pts.set(p, s * (line.get(p) + (g === 'QB' ? CWAR_QB_OWN : SAV_W[g]) * p.savQ));
    if (g === 'QB') shared[p.tid] = (shared[p.tid] || 0) + s * (SAV_W.QB - CWAR_QB_OWN) * p.savQ;
  }
  // the QB's shared credit, to the offensive teammates by snap share
  const mates = {};
  for (const p of live) if (OFF.includes(posOf(p)) && posOf(p) !== 'QB') (mates[p.tid] ||= []).push(p);
  for (const [tid, ps] of Object.entries(mates)) {
    const tot = ps.reduce((a, p) => a + Math.min(1, p.snapShare), 0);
    for (const p of ps) if (tot > 0) pts.set(p, pts.get(p) + (shared[tid] || 0) * Math.min(1, p.snapShare) / tot);
  }
  for (const p of live) {
    p.war = r2(Math.max(0, pts.get(p)) * CWAR_PER_PT);
    // waa: wins over an average starter at his position for the same snaps (WAR less his share of CWAR_V), so
    // players compare across positions by how far above the usual starter they are; below average is negative
    p.waa = r2((pts.get(p) - Math.min(1, p.snapShare) * line.get(p)) * CWAR_PER_PT);
    if (opts.warOnly) { p.sav = null; p.savQ = null; }
  }
  return rows;
}
// points of margin a game over replacement (signed), from p.savQ and p.snapShare
export const savPoints = p => p.savQ == null ? null : Math.min(1, p.snapShare) * SAV_W[p.pos] * (p.savQ - SAV_REPL);

// a team's season AV: its starters by snap share (STARTERS slots, a part-timer filling what is left), in AV;
// repl: the replacement line (SD), SAV_REPL for AV, CWAR_REPL for teamWar
function teamPts(ps, line) {
  let pts = 0;
  for (const [g, n] of Object.entries(STARTERS)) {
    let left = n;
    ps.filter(p => p.pos === g && p.savQ != null).sort((a, b) => b.snapShare - a.snapShare).forEach((p, i) => {
      const s = Math.min(p.snapShare, left); if (s <= 0) return;
      pts += s * (line(g, i, p) + SAV_W[g] * p.savQ); left -= s;
    });
  }
  return pts;
}
export const teamSeasonAv = (ps, repl = SAV_REPL) => Math.round(teamPts(ps, g => -SAV_W[g] * repl) / SAV_PTS * 10) / 10;
// a team's college WAR this season: its starters over replacement starters CWAR_V points a game below average (the QB's
// shared credit stays inside the team, so the team sum uses his full SAV_W)
export const teamWar = ps => r2(teamPts(ps, (g, i, p) => subV(g, i, p.pfnPos ?? p.spot)) * CWAR_PER_PT);
// college WAR a full-time starter at pos adds by moving the line from SAV_REPL to the WAR line (CWAR_V below average):
// AV-at-FV totals of starters (team talent) convert as cwar(AV) + the sum of this over the starters
export const starterReplWar = pos => (SAV_W[pos] == null ? 0 : (CWAR_V[pos] + SAV_W[pos] * SAV_REPL) * CWAR_PER_PT);
// the same over a full starting lineup (every team's 22 slots), and its offense and defense halves: added to
// AV-at-FV starter totals x CWAR_PER_AV (team talent, next season's starters) by the templates
const lineupRepl = keep => r2(Object.entries(STARTERS).filter(([g]) => keep(g)).reduce((a, [g, n]) => a + n * starterReplWar(g), 0));
export const TEAM_REPL_WAR = { all: lineupRepl(() => true), off: lineupRepl(g => OFF.includes(g)), def: lineupRepl(g => !OFF.includes(g)) };
