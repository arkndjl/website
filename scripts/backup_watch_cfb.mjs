// Backup watch, college football (Noah, Oct 23 2026): second- and third-string players who out-produce a starter at
// their position (production, not FV: Noah, Nov 5 2026, as the CBB, NFL, NBA, NHL and soccer tabs). Writes data/backup_cfb.json for the backup watch tab (layouts/shortcodes/backupwatch.html).
//
// ESPN keeps no college depth charts, so the depth chart is playing time this season, within team and position:
//   snaps      PFN's season snaps (QB, TE, OL, DT, EDGE, LB, CB, S; and every FCS spot)
//   touches    FBS RB carries + catches and WR catches from ESPN box scores (PFN lists games, not snaps, there)
// The top STARTERS[pos] players are the starters (the team builder's counts, scripts/cfb_teams.mjs), the next two
// rows of that many are the 2nd and 3rd string. A player with no playing time isn't on the chart. The grade is the
// board's college WAR at a full-time snap share (WAR a season / snap share; scripts/cfb_av.mjs), shrunk toward
// replacement (0) with K snaps, as the NFL tab's WAR a snap. FBS backs and receivers have no PFN snap count, so their
// sample is snap share x the team's offensive snaps (its most-used lineman). A backup needs MIN snaps and is listed
// when he beats the lowest-graded starter at his spot by GAP or more (a starter needs MIN snaps to be graded), and is compared with him.
//     node scripts/backup_watch_cfb.mjs            (after fetch_cfb.mjs; box scores are cached once a game is final)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames, STARTERS } from './cfb_teams.mjs';
import { fetchBoxes } from './cfb_box.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const OUT = path.join(ROOT, 'data', 'backup_cfb.json');
const K = 300, MIN = 50, GAP = 0.1;    // the NFL tab's shrink and minimum (scripts/backup_watch.py NFL_K, NFL_MIN); GAP:
                                       // a tenth of a win a full season over the starter (the median listed edge is .05)
const BOX_POS = { RB: p => (p.car || 0) + (p.rec || 0), WR: p => p.rec || 0 };

const all = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'data', 'cfb-all.json'), 'utf8'));
const ci = Object.fromEntries(all.cols.map((k, i) => [k, i]));
const rows = all.rows.map(r => Object.fromEntries(all.cols.map(k => [k, r[ci[k]]])));
// photo 1 = ESPN's standard headshot for his ESPN id (fetch_cfb.mjs photoCode)
for (const r of rows) if (r.photo === 1) { const id = /\/id\/(\d+)/.exec(r.espnl || '')?.[1]; r.photo = id ? `https://a.espncdn.com/i/headshots/college-football/players/full/${id}.png` : null; }

// this season's games: fetch_cfb's cached pull when it ran first, else ESPN's scoreboard
let games = null;
try { games = JSON.parse(fs.readFileSync(path.join(CACHE, 'games.json'), 'utf8')); } catch {}
if (!games?.length) games = await fetchGames();
const boxes = await fetchBoxes(games.filter(g => g.done));
const touch = {};                      // ESPN athlete id -> { RB, WR, yds }
for (const b of Object.values(boxes))
  for (const P of Object.values(b.teams))
    for (const [aid, p] of Object.entries(P)) {
      const t = (touch[aid] ||= { RB: 0, WR: 0, yds: 0 });
      t.RB += BOX_POS.RB(p); t.WR += BOX_POS.WR(p); t.yds += (p.rushYds || 0) + (p.recYds || 0);
    }

const espnId = r => /\/id\/(\d+)/.exec(r.espnl || '')?.[1] || /\/(\d+)\.png/.exec(r.photo || '')?.[1] || null;
const usage = r => {
  if (BOX_POS[r.pos] && r.div === 'FBS') {
    const t = touch[espnId(r)];
    return t && t[r.pos] > 0 ? { v: t[r.pos] + t.yds / 1e5, n: t[r.pos], unit: r.pos === 'RB' ? 'touches' : 'catches' } : null;
  }
  return r.snaps > 0 ? { v: r.snaps, n: r.snaps, unit: 'snaps' } : null;
};

// sample snaps: PFN's count, else snap share x the team's offensive snaps (its most-used lineman's)
const olSnaps = {};
for (const r of rows) if (r.pos === 'OL' && r.snaps > 0 && r.team) olSnaps[r.team] = Math.max(olSnaps[r.team] || 0, r.snaps);
const sample = r => r.snaps > 0 ? r.snaps : r.snapShare > 0 && olSnaps[r.team] ? Math.round(r.snapShare * olSnaps[r.team]) : 0;
// WAA a season at a full-time snap share (wins over an average starter; WAR is floored at replacement, so it can't
// tell two sub-replacement players apart), shrunk toward the position's replacement line (median -(WAR - WAA) / share)
// with K snaps; null without a WAR line
const repl = {};
{
  const by = {};
  for (const r of rows) if (r.war > 0 && r.waa != null && r.snapShare > 0) (by[r.pos] ||= []).push(-(r.war - r.waa) / Math.min(1, r.snapShare));
  for (const [p, v] of Object.entries(by)) { v.sort((a, b) => a - b); repl[p] = v[Math.floor(v.length / 2)]; }
}
const grade = r => {
  if (r.waa == null || !(r.snapShare > 0) || repl[r.pos] == null) return null;
  const n = sample(r);
  return { g: Math.round(100 * ((r.waa / Math.min(1, r.snapShare)) * n + K * repl[r.pos]) / (n + K)) / 100, n };
};

const byTeam = {};
for (const r of rows) {
  if (r.fv == null || !STARTERS[r.pos] || !r.team) continue;
  const u = usage(r); if (!u) continue;
  (byTeam[r.team + '|' + r.pos] ||= []).push({ r, u, gr: grade(r) });
}
const tag = ({ r, u, gr }) => ({ name: r.name, g: gr?.g ?? null, n: gr?.n ?? 0, fv: r.fv, use: u.n, unit: u.unit, cls: r.cls, inj: r.inj || null });
const out = [];
let teams = new Set(), slots = 0;
for (const [k, L] of Object.entries(byTeam)) {
  const n = STARTERS[L[0].r.pos];
  L.sort((a, b) => b.u.v - a.u.v);
  const st = L.slice(0, n); if (st.length < n) continue;
  teams.add(L[0].r.team); slots++;
  const graded = st.filter(x => x.gr && x.gr.n >= MIN);
  if (!graded.length) continue;
  const low = graded.reduce((a, b) => (b.gr.g < a.gr.g ? b : a));
  L.slice(n, 3 * n).forEach((b, i) => {
    if (!b.gr || b.gr.n < MIN || b.gr.g - low.gr.g < GAP - 1e-9) return;
    const r = b.r;
    out.push({ ...tag(b), str: i < n ? 2 : 3, pos: r.pos === 'DL' ? 'DT' : r.pos, team: r.team, logo: r.logo, conf: r.conf, div: r.div,
      photo: r.photo, starter: tag(low), gap: Math.round(100 * (b.gr.g - low.gr.g)) / 100 });
  });
}
out.sort((a, b) => b.gap - a.gap || b.g - a.g || b.use - a.use);
// ranked by xGap (scripts/backup_age.py, same lines): the gap projected two seasons on from today's gap and the class
// gap to the starter (Fr 1 .. Sr 4, a redshirt keeps his eligibility year), terms from scripts/backup_age_fit.py
try {
  const T = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'backup_age.json'), 'utf8')).sports.cfb;
  const CLS = { Fr: 1, So: 2, Jr: 3, Sr: 4, Gr: 5 }, num = c => (c ? CLS[c.replace(/^RS-/, '')] : undefined);
  for (const r of out) {
    const b = num(r.cls), s = num(r.starter.cls), ag = b == null || s == null ? 0 : s - b;
    r.xgap = Math.round(1000 * (T.a + T.b * r.gap + T.c * ag)) / 1000;
  }
  out.sort((a, b) => b.xgap - a.xgap || b.gap - a.gap);
} catch (e) { console.log('backup watch cfb: no age term (' + e.message + ')'); }

// the depth chart tab (layouts/shortcodes/depthchart.html): every team's rooms in the same playing-time order, three
// deep at each starting spot; players with no playing time yet fill out the room after them, best FV first. A player
// is [name, grade, playing time, injury, class, percentile]: the percentile ranks his grade at his position
// nationally among players with MIN snaps, and colours the tile (as the NFL chart)
const ROOMS = [['offense', ['QB', 'RB', 'WR', 'TE', 'OL']], ['defense', ['EDGE', 'DL', 'LB', 'CB', 'S']]];
const depth = {};
for (const [k, L] of Object.entries(byTeam)) (depth[k.split('|')[0]] ||= {})[L[0].r.pos] = L;
const idle = rows.filter(r => r.fv != null && STARTERS[r.pos] && r.team && !usage(r)).sort((a, b) => b.fv - a.fv);
for (const r of idle) if (depth[r.team]) ((depth[r.team][r.pos] ||= [])).push({ r, u: null });
const pool = {};
for (const L of Object.values(byTeam)) for (const { r, gr } of L) if (gr && gr.n >= MIN) (pool[r.pos] ||= []).push(gr.g);
for (const v of Object.values(pool)) v.sort((a, b) => a - b);
const pctOf = (pos, gr) => {
  const L = pool[pos]; if (!gr || gr.n < MIN || !L || L.length < 2) return null;
  let lo = 0, hi = 0; for (const v of L) { if (v < gr.g) lo++; if (v <= gr.g) hi++; }
  return Math.round(100 * ((lo + hi - 1) / 2) / (L.length - 1));
};
const useTxt = x => x ? x.n + ' ' + (x.n === 1 ? x.unit.replace(/(che)?s$/, m => m === 'ches' ? 'ch' : '') : x.unit) : null;
const dteams = Object.keys(depth).sort().map(t => {
  const R = depth[t], any = Object.values(R)[0][0].r;
  return { t, n: t, logo: any.logo, grp: any.conf, div: any.div,
    units: ROOMS.map(([u, ps]) => ({ u, s: ps.filter(p => R[p]).map(p => [p === 'DL' ? 'DT' : p,
      R[p].slice(0, 3 * STARTERS[p]).map(({ r, u: x, gr }) => [r.name, gr?.g ?? null, useTxt(x), r.inj || null, r.cls || null, pctOf(r.pos, gr)])]) })) };
});
fs.mkdirSync(path.join(ROOT, 'static', 'data', 'depth'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'static', 'data', 'depth', 'cfb.json'), JSON.stringify({ sport: 'cfb', asof: all.asof, grade: 'WAA/FT', use: 'playing time', fmt: 2, min: MIN, k: K, starters: STARTERS, teams: dteams }));
fs.writeFileSync(OUT, JSON.stringify({ asof: all.asof, teams: teams.size, slots, n: out.length, k: K, min: MIN, gap: GAP, starters: STARTERS, repl: Object.fromEntries(Object.entries(repl).map(([p, v]) => [p, Math.round(100 * v) / 100])), rows: out }, null, 1));
console.log(`backup watch cfb: ${out.length} backups above a starter (${teams.size} teams, ${slots} position rooms, ${Object.keys(boxes).length} box scores)`);
