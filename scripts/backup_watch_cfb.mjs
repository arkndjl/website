// Backup watch, college football (Noah, Oct 23 2026): second- and third-string players whose FV beats a starter's at
// their position. Writes data/backup_cfb.json for the backup watch tab (layouts/shortcodes/backupwatch.html).
//
// ESPN keeps no college depth charts, so the depth chart is playing time this season, within team and position:
//   snaps      PFN's season snaps (QB, TE, OL, DT, EDGE, LB, CB, S; and every FCS spot)
//   touches    FBS RB carries + catches and WR catches from ESPN box scores (PFN lists games, not snaps, there)
// The top STARTERS[pos] players are the starters (the team builder's counts, scripts/cfb_teams.mjs), the next two
// rows of that many are the 2nd and 3rd string. A player with no playing time isn't on the chart. A backup is
// listed when his FV (headline = mean outcome) beats the lowest-graded starter at his spot by FV_GAP or more, and is
// compared with him.
//     node scripts/backup_watch_cfb.mjs            (after fetch_cfb.mjs; box scores are cached once a game is final)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames, STARTERS } from './cfb_teams.mjs';
import { fetchBoxes } from './cfb_box.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const OUT = path.join(ROOT, 'data', 'backup_cfb.json');
const FV_GAP = 3;                      // FV points over the starter to be listed: a 1-2 point edge at the 20 floor is noise
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

const byTeam = {};
for (const r of rows) {
  if (r.fv == null || !STARTERS[r.pos] || !r.team) continue;
  const u = usage(r); if (!u) continue;
  (byTeam[r.team + '|' + r.pos] ||= []).push({ r, u });
}
const tag = ({ r, u }) => ({ name: r.name, fv: r.fv, use: u.n, unit: u.unit, cls: r.cls, inj: r.inj || null });
const out = [];
let teams = new Set(), slots = 0;
for (const [k, L] of Object.entries(byTeam)) {
  const n = STARTERS[L[0].r.pos];
  L.sort((a, b) => b.u.v - a.u.v);
  const st = L.slice(0, n); if (st.length < n) continue;
  teams.add(L[0].r.team); slots++;
  const low = st.reduce((a, b) => (b.r.fv < a.r.fv ? b : a));
  L.slice(n, 3 * n).forEach((b, i) => {
    if (b.r.fv - low.r.fv < FV_GAP) return;
    const r = b.r;
    out.push({ ...tag(b), str: i < n ? 2 : 3, pos: r.pos === 'DL' ? 'DT' : r.pos, team: r.team, logo: r.logo, conf: r.conf, div: r.div,
      photo: r.photo, starter: tag(low), gap: r.fv - low.r.fv });
  });
}
out.sort((a, b) => b.gap - a.gap || b.fv - a.fv || b.use - a.use);

// the depth chart tab (layouts/shortcodes/depthchart.html): every team's rooms in the same playing-time order, three
// deep at each starting spot; players with no playing time yet fill out the room after them, best FV first. A player
// is [name, FV, playing time, injury, class, null] (FV colours the tile)
const ROOMS = [['offense', ['QB', 'RB', 'WR', 'TE', 'OL']], ['defense', ['EDGE', 'DL', 'LB', 'CB', 'S']]];
const depth = {};
for (const [k, L] of Object.entries(byTeam)) (depth[k.split('|')[0]] ||= {})[L[0].r.pos] = L;
const idle = rows.filter(r => r.fv != null && STARTERS[r.pos] && r.team && !usage(r)).sort((a, b) => b.fv - a.fv);
for (const r of idle) if (depth[r.team]) ((depth[r.team][r.pos] ||= [])).push({ r, u: null });
const useTxt = x => x ? x.n + ' ' + (x.n === 1 ? x.unit.replace(/(che)?s$/, m => m === 'ches' ? 'ch' : '') : x.unit) : null;
const dteams = Object.keys(depth).sort().map(t => {
  const R = depth[t], any = Object.values(R)[0][0].r;
  return { t, n: t, logo: any.logo, grp: any.conf, div: any.div,
    units: ROOMS.map(([u, ps]) => ({ u, s: ps.filter(p => R[p]).map(p => [p === 'DL' ? 'DT' : p,
      R[p].slice(0, 3 * STARTERS[p]).map(({ r, u: x }) => [r.name, r.fv, useTxt(x), r.inj || null, r.cls || null, null])]) })) };
});
fs.mkdirSync(path.join(ROOT, 'static', 'data', 'depth'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'static', 'data', 'depth', 'cfb.json'), JSON.stringify({ sport: 'cfb', asof: all.asof, grade: 'FV', use: 'playing time', fmt: 0, starters: STARTERS, teams: dteams }));
fs.writeFileSync(OUT, JSON.stringify({ asof: all.asof, teams: teams.size, slots, n: out.length, gap: FV_GAP, starters: STARTERS, rows: out }, null, 1));
console.log(`backup watch cfb: ${out.length} backups above a starter (${teams.size} teams, ${slots} position rooms, ${Object.keys(boxes).length} box scores)`);
