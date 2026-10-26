// True aDOT, pre-registered (Oct 26, 2026). ESPN's play text spots every throw from 2026 on ("caught at NMSU24",
// "thrown to NMSU36"), so 2026 is the first season with real depth of target; earlier seasons only have the PFN proxy
// (scripts/cfb_fv_refit.mjs RECV_KEYS), which failed as an FV input. This freezes each receiver's 2026 line so the real
// stat can be scored once the 2026 class has NFL seasons.
//   node scripts/cfb_adot_prereg.mjs [season]     -> scripts/data/cfb_adot_<season>.json  (rerun after the bowls)
// Per receiver with 20+ spotted targets: targets, spotted targets, aDOT, air yards a game, deep share (15+ air yards),
// catch rate, and catch rate over the FBS line on air-yard bucket (CROE at depth).
// Pre-registered test (score after the 2028 season, drafts 2027-28): add z(aDOT), z(CROE at depth) and air yards a
// target x catch rate to the WR grade on the 2026 board, against NFL AV a season and draft capital, the same
// --recvcheck way (held out by draft class). Pass bar: AV gain t >= 2 with the board's grade in, and nothing worse
// once consensus is blended in. Proxy result to beat: aDOT AV t .47, depth-adjusted YPRR capital t 7.2 / AV t -.04.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parsePlays, airB } from './cfb_oe.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const year = +(process.argv[2] || 2026);
const B = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football';
const json = async u => { for (let i = 0; i < 4; i++) { try { const r = await fetch(u); if (r.ok) return await r.json(); } catch {} await new Promise(r => setTimeout(r, 1000 * 2 ** i)); } return null; };
const ids = new Map();
for (const [st, w] of [...Array(16).keys()].map(w => [2, w + 1]).concat([[3, 1]])) {
  const s = await json(`${B}/scoreboard?dates=${year}&seasontype=${st}&week=${w}&groups=80&limit=400`);
  for (const e of s?.events || []) if (e.status?.type?.completed) ids.set(e.id, e.competitions[0]);
}
const plays = [], names = {}, list = [...ids.entries()];
await Promise.all([...Array(12)].map(async () => {
  while (list.length) {
    const [id, comp] = list.shift(), g = await json(`${B}/summary?event=${id}`); if (!g) continue;
    const cs = comp.competitors, home = cs.find(c => c.homeAway === 'home'), away = cs.find(c => c.homeAway === 'away');
    names[home.team.id] = home.team.displayName; names[away.team.id] = away.team.displayName;
    for (const d of g.drives?.previous || []) for (const p of d.plays || []) {
      const o = p.teamParticipants?.find(t => t.type === 'offense')?.id || p.start?.team?.id;
      const df = p.teamParticipants?.find(t => t.type === 'defense')?.id || (o === home.team.id ? away.team.id : home.team.id);
      plays.push({ g: id, o, d: df, ytg: p.start?.yardsToEndzone, dn: p.start?.down, ds: p.start?.distance, y: p.statYardage, t: p.type?.text, x: p.text });
    }
  }
}));
const ev = parsePlays(plays).filter(e => e.kind === 'drop' && !e.sack && e.target && !e.int);
// catch rate by air-yard bucket across FBS, for CROE at depth
const cell = {}; for (const e of ev) if (e.air != null) { const c = cell[airB(e.air)] ||= [0, 0]; c[0] += e.comp ? 1 : 0; c[1]++; }
const A = {};
for (const e of ev) {
  const a = A[e.target + '|' + e.team] ||= { name: e.target, team: names[e.team], tar: 0, n: 0, air: 0, deep: 0, rec: 0, xc: 0, games: new Set() };
  a.tar++; a.games.add(e.g); if (e.comp) a.rec++;
  if (e.air != null && Math.abs(e.air) < 70) { a.n++; a.air += e.air; a.deep += e.air >= 15 ? 1 : 0; const c = cell[airB(e.air)]; a.xc += c[0] / c[1]; }
}
const r3 = x => Math.round(x * 1000) / 1000;
const rows = Object.values(A).filter(a => a.n >= 20).map(a => ({ name: a.name, team: a.team, tar: a.tar, spotted: a.n, adot: r3(a.air / a.n),
  airPg: r3(a.air / a.games.size), deep: r3(a.deep / a.n), catch: r3(a.rec / a.tar), croe: r3((a.rec - a.xc * a.tar / a.n) / a.tar) }));
const out = { season: year, asof: new Date().toISOString().slice(0, 10), games: ids.size, receivers: rows.length, rows: rows.sort((a, b) => b.tar - a.tar) };
fs.writeFileSync(path.join(ROOT, 'scripts', 'data', `cfb_adot_${year}.json`), JSON.stringify(out));
console.log(year, ids.size, 'games', rows.length, 'receivers');
