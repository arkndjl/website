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
// (pooled r .35 vs .40), so FV and avOf stay the NFL measure.
export const SAV_W = { QB: 2.75, RB: 0.82, WR: 0.55, TE: 0.28, OL: 0.17, EDGE: 0.83, DL: 0.23, LB: 0.4, CB: 0.72, S: 0.74 };
export const SAV_REPL = -1;
export const SAV_Q = { badge: 0.5, fv: 0.25 };
export const SAV_PTS = 0.42;
const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const TIER = { b: 1, s: 2, g: 3, p: 4 };

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

// sets p.sav (AV a season, college) and p.savQ (quality, SD of the starter pool) on every row with a PFN score
// and a snap share; the rest get null. rows: one division's graded players (FBS); posOf: the position field
// (board rows: p.pos; fetch_cfb.mjs build() players: p.g)
export function seasonAv(rows, posOf = p => p.pos) {
  const nTeams = new Set(rows.map(p => p.tid).filter(Boolean)).size || 1;
  const live = rows.filter(p => SAV_W[posOf(p)] != null && p.pfn != null && p.snapShare != null);
  const zs = poolZ(live, p => p.pfn, nTeams, posOf), zb = poolZ(live, badgePoints, nTeams, posOf), zf = poolZ(live, p => p.fv, nTeams, posOf);
  const q = poolZ(live, p => zs.get(p) + SAV_Q.badge * (zb.get(p) ?? 0) + SAV_Q.fv * (zf.get(p) ?? 0), nTeams, posOf);
  for (const p of rows) { p.sav = null; p.savQ = null; }
  for (const p of live) {
    p.savQ = Math.round(q.get(p) * 100) / 100;
    p.sav = Math.round(Math.max(0, Math.min(1, p.snapShare) * SAV_W[posOf(p)] * (p.savQ - SAV_REPL)) / SAV_PTS * 10) / 10;
  }
  return rows;
}
// points of margin a game over replacement (signed), from p.savQ and p.snapShare
export const savPoints = p => p.savQ == null ? null : Math.min(1, p.snapShare) * SAV_W[p.pos] * (p.savQ - SAV_REPL);

// a team's season AV: its starters by snap share (STARTERS slots, a part-timer filling what is left), in AV
export function teamSeasonAv(ps) {
  let pts = 0;
  for (const [g, n] of Object.entries(STARTERS)) {
    let left = n;
    for (const p of ps.filter(p => p.pos === g && p.savQ != null).sort((a, b) => b.snapShare - a.snapShare)) {
      const s = Math.min(p.snapShare, left); if (s <= 0) break;
      pts += s * SAV_W[g] * (p.savQ - SAV_REPL); left -= s;
    }
  }
  return Math.round(pts / SAV_PTS * 10) / 10;
}
