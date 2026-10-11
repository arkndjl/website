// Backtest for actual vs expected (scripts/cfb_oe.mjs), which sets the FV_OE weights in fetch_cfb.mjs. Run by hand:
//   node scripts/cfb_oe_backtest.mjs            (pulls what's missing, then writes data/cfb_oe_backtest.json)
// Data: ESPN play-by-play for every FBS game 2017-26 (the same feed CFBD's play text comes from; slimmed and kept
// in scripts/.cache/espn_pbp) and nflverse draft picks. Per metric (rushing yards over expected, ANY/A a dropback
// over expected, ANY/A a target over expected, CPOE, catch rate over expected), the over-expected rate `oe` is set
// against the player's raw rate shrunk the same way (`nv`), and both predict:
//   next      the next season's raw rate, same player (2021-26 pairs; names unique among qualifiers both years)
//   movers    the same, for players who changed schools: the context changed, so only portable skill carries
//   nfl       weighted career AV a season for the final college season (2017-22 seasons, drafts 2018-23,
//             undrafted = 0, players who played again later dropped from that season)
// Reported: each one's correlation with the outcome, the partial correlation of oe beyond nv, and the standardized
// betas with both in the model; FV_OE's share is b_oe / (b_nv + b_oe), clamped to 0-1.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parsePlays, overExpected, OE } from './cfb_oe.mjs';
import { pbpKey } from './cfb_pbp.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'espn_pbp');
const OUT = path.join(ROOT, 'data', 'cfb_oe_backtest.json');
const YRS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
const B = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football';
fs.mkdirSync(CACHE, { recursive: true });
const json = async u => { for (let i = 0; i < 4; i++) { try { const r = await fetch(u); if (r.ok) return await r.json(); } catch {} await new Promise(r => setTimeout(r, 1000 * 2 ** i)); } return null; };

// one season of FBS games -> plays (CFBD-like slim fields) and games (week, teams)
async function season(year) {
  const pf = path.join(CACHE, `plays${year}.json`), gf = path.join(CACHE, `games${year}.json`);
  if (fs.existsSync(pf) && fs.existsSync(gf) && year < 2026) return [JSON.parse(fs.readFileSync(pf)), JSON.parse(fs.readFileSync(gf))];
  const ids = new Map();
  for (const [st, w] of [...Array(16).keys()].map(w => [2, w + 1]).concat([[3, 1]])) {
    const s = await json(`${B}/scoreboard?dates=${year}&seasontype=${st}&week=${w}&groups=80&limit=400`);
    for (const e of s?.events || []) if (e.status?.type?.completed) ids.set(e.id, { week: st === 3 ? 16 : w, comp: e.competitions[0] });
  }
  const plays = [], games = {}, list = [...ids.entries()];
  await Promise.all([...Array(8)].map(async () => {
    while (list.length) {
      const [id, meta] = list.shift(), g = await json(`${B}/summary?event=${id}`); if (!g) continue;
      const cs = meta.comp.competitors, home = cs.find(c => c.homeAway === 'home'), away = cs.find(c => c.homeAway === 'away');
      games[id] = { week: meta.week, home: home.team.id, away: away.team.id, hn: home.team.displayName, an: away.team.displayName };
      for (const d of g.drives?.previous || []) for (const p of d.plays || []) {
        const o = p.teamParticipants?.find(t => t.type === 'offense')?.id || p.start?.team?.id;
        const df = p.teamParticipants?.find(t => t.type === 'defense')?.id || (o === home.team.id ? away.team.id : home.team.id);
        plays.push({ g: id, w: meta.week, o, d: df, ytg: p.start?.yardsToEndzone, dn: p.start?.down, ds: p.start?.distance, y: p.statYardage, t: p.type?.text, x: p.text });
      }
    }
  }));
  fs.writeFileSync(pf, JSON.stringify(plays)); fs.writeFileSync(gf, JSON.stringify(games));
  console.log(year, Object.keys(games).length, 'games', plays.length, 'plays');
  return [plays, games];
}

const corr = (xs, ys) => { const n = xs.length; if (n < 10) return null; const mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n; let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const partial = (x, z, y) => { const rxy = corr(x, y), rxz = corr(x, z), rzy = corr(z, y); return (rxy - rxz * rzy) / Math.sqrt((1 - rxz ** 2) * (1 - rzy ** 2)); };
const betas = (x1, x2, y) => { const r1 = corr(x1, y), r2 = corr(x2, y), r12 = corr(x1, x2), d = 1 - r12 * r12; return [(r1 - r12 * r2) / d, (r2 - r12 * r1) / d]; };
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;
const norm = s => (s || '').toLowerCase().replace(/\bst\.?$/, 'state').replace(/[^a-z ]/g, '').trim();
// metric: the line on a player, minimum plays (both seasons / NFL), NFL positions
const MET = { rush: { min: [60, 40, 80], pos: ['RB'], noQB: true }, drop: { min: [120, 80, 150], pos: ['QB'] }, tgt: { min: [25, 20, 35], pos: ['WR', 'TE', 'RB'], noQB: true },
  cmp: { min: [120, 80, 150], pos: ['QB'] } };
const isQB = p => (p.drop?.n || 0) >= 50;

const data = {}; for (const y of YRS) data[y] = await season(y);
const picks = await (async () => {
  const f = path.join(CACHE, 'draft_picks.csv');
  if (!fs.existsSync(f)) fs.writeFileSync(f, await (await fetch('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv')).text());
  const [h, ...rows] = fs.readFileSync(f, 'utf8').trim().split('\n'), H = h.split(',');
  return rows.map(l => { const v = l.split(','); return Object.fromEntries(H.map((k, i) => [k, v[i]])); }).filter(r => +r.season >= 2018 && +r.season <= 2024);
})();
const teamName = {}; for (const y of YRS) for (const g of Object.values(data[y][1])) { teamName[g.home] = g.hn; teamName[g.away] = g.an; }
const F = Object.fromEntries(YRS.map(y => [y, overExpected(parsePlays(data[y][0]), OE)]));
const byKey = O => { const m = {}; for (const [k, p] of Object.entries(O)) (m[p.key] ||= []).push(k); return m; };
const NFL_THROUGH = 2025;

const out = { asof: new Date().toISOString().slice(0, 10), config: OE, metrics: {} };
for (const [f, M] of Object.entries(MET)) {
  const ps = [];
  for (let i = YRS.indexOf(2021); i + 1 < YRS.length; i++) {
    const A = F[YRS[i]], Bn = F[YRS[i + 1]], ka = byKey(A), kb = byKey(Bn);
    for (const a of Object.values(A)) {
      const sa = a[f]; if (!sa || sa.oe == null || sa.n < M.min[0] || (M.noQB && isQB(a))) continue;
      const cA = ka[a.key].filter(x => A[x][f]?.n >= M.min[0]), cB = (kb[a.key] || []).filter(x => Bn[x][f]?.n >= M.min[1]);
      if (cA.length !== 1 || cB.length !== 1) continue;
      const b = Bn[cB[0]], sb = b[f]; if (sb.oe == null || (M.noQB && isQB(b))) continue;
      const raw = s => (s.y ?? s.v ?? s.c) / s.n;
      ps.push({ moved: b.team !== a.team, nv: sa.nv, oe: sa.oe, next: raw(sb) });
    }
  }
  const nfl = [];
  for (const y of [2017, 2018, 2019, 2021, 2022]) {
    const D = y + 1;
    for (const p of Object.values(F[y])) {
      const s = p[f]; if (!s || s.oe == null || s.n < M.min[2] || (M.noQB && isQB(p))) continue;
      const tn = norm(teamName[p.team]);
      const cand = picks.filter(r => pbpKey(r.pfr_player_name) === p.key && M.pos.includes(r.position) && tn.startsWith(norm(r.college).split(' ')[0]));
      const pk = cand.find(r => +r.season === D);
      if (!pk && (cand.some(r => +r.season > D) || YRS.some(z => z > y && Object.values(F[z]).some(q => q.key === p.key && q.team === p.team)))) continue;
      nfl.push({ nv: s.nv, oe: s.oe, out: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0, drafted: !!pk });
    }
  }
  const test = (rows, y) => { const g = k => rows.map(r => r[k]); if (rows.length < 15) return { n: rows.length };
    const [bNv, bOe] = betas(g('nv'), g('oe'), g(y));
    return { n: rows.length, rNv: r3(corr(g('nv'), g(y))), rOe: r3(corr(g('oe'), g(y))), partialOe: r3(partial(g('oe'), g('nv'), g(y))), bNv: r3(bNv), bOe: r3(bOe),
      share: r3(Math.max(0, Math.min(1, bOe / (bNv + bOe) || 0))) }; };
  const t = { next: test(ps, 'next'), movers: test(ps.filter(p => p.moved), 'next'), nfl: { ...test(nfl, 'out'), drafted: nfl.filter(r => r.drafted).length } };
  t.share = r3(((t.next.share ?? 0) + (t.movers.share ?? 0) + 2 * (t.nfl.share ?? 0)) / 4);
  out.metrics[f] = t;
  console.log(f.padEnd(5), JSON.stringify(t));
}
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
console.log('wrote', path.relative(ROOT, OUT));
