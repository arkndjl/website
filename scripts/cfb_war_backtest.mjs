// Backtest for football WAR (scripts/cfb_av.mjs): the points-per-win rates that turn season AV (college) and NFL
// AV into wins above replacement. Run by hand: node scripts/cfb_war_backtest.mjs -> data/cfb_war_backtest.json
// The site's templates read data/cfb_war_backtest.json constants (the scripts/cfb_av.mjs values).
// Data: ESPN results 2019-26 (FBS), nflverse schedules 2002-25 (regular season), this season's board
// (data/cfb_teams.json: team season AV and record).
//   college   team-season win% (FBS vs FBS, ties none) on average margin a game: least squares slope b, fit on
//             2019-25 and tested on 2026; wins per point of margin a game over a 12-game season = 12 b
//   nfl       team-season wins (ties half) on point differential over 17 games, fit on 2010-22, tested on
//             2023-25; league points per team-season (the 2021-25 average) set the points one NFL AV is worth:
//             AV's team pools are 100 per side at league-average scoring per drive (Drinen 2008), so one AV is
//             about lgPts / 100 points of margin
//   team      2026 teams: summed college WAR of the starters against FBS-vs-FBS win%; the intercept is the
//             win% of a lineup of replacement starters, the slope should be near 1/12 a WAR
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames } from './cfb_teams.mjs';
import { SAV_PTS, CWAR_PER_AV, NWAR_PER_AV, NFL_REPL_AV } from './cfb_av.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'av');
const OUT = path.join(ROOT, 'data', 'cfb_war_backtest.json');
fs.mkdirSync(CACHE, { recursive: true });
const YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026], TEST = 2026;
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const r4 = x => Math.round(x * 1e4) / 1e4, r3 = x => Math.round(x * 1000) / 1000;
// least squares y = a + b x
function line(x, y) { const mx = mean(x), my = mean(y); let sxy = 0, sxx = 0; x.forEach((v, i) => { sxy += (v - mx) * (y[i] - my); sxx += (v - mx) ** 2; }); const b = sxy / sxx; return { a: my - b * mx, b }; }
const corr = (x, y) => { const mx = mean(x), my = mean(y); let a = 0, b = 0, c = 0; x.forEach((v, i) => { a += (v - mx) * (y[i] - my); b += (v - mx) ** 2; c += (y[i] - my) ** 2; }); return a / Math.sqrt(b * c); };
const rmse = (y, p) => Math.sqrt(mean(y.map((v, i) => (v - p[i]) ** 2)));

// ---- college: win% on margin ---------------------------------------------------------------------------------
async function games(y) {
  const f = path.join(CACHE, `games${y}.json`); if (fs.existsSync(f) && y < TEST) return JSON.parse(fs.readFileSync(f));
  const g = await fetchGames(y); fs.writeFileSync(f, JSON.stringify(g)); return g;
}
const TS = [];   // { y, tid, g, wp, m }
for (const y of YEARS) {
  const G = (await games(y)).filter(g => g.done), cnt = {};
  for (const g of G) for (const t of [g.home, g.away]) cnt[t] = (cnt[t] || 0) + 1;
  const fbs = new Set(Object.keys(cnt).filter(t => cnt[t] >= (y === 2020 ? 3 : 5))), acc = {};
  for (const g of G) {
    if (!fbs.has(g.home) || !fbs.has(g.away) || g.hs === g.as) continue;
    for (const [t, d] of [[g.home, g.hs - g.as], [g.away, g.as - g.hs]]) { const a = (acc[t] ||= { g: 0, w: 0, m: 0 }); a.g++; a.w += d > 0; a.m += d; }
  }
  for (const [tid, a] of Object.entries(acc)) if (a.g >= (y === 2020 ? 3 : 4)) TS.push({ y, tid, g: a.g, wp: a.w / a.g, m: a.m / a.g });
}
const tr = TS.filter(r => r.y < TEST), te = TS.filter(r => r.y === TEST);
const cf = line(tr.map(r => r.m), tr.map(r => r.wp));
const cPred = te.map(r => cf.a + cf.b * r.m);
const college = {
  teamSeasons: tr.length, slope: r4(cf.b), intercept: r4(cf.a), winsPerPtSeason: r3(12 * cf.b), ptsPerWinGame: r3(1 / (12 * cf.b)),
  fitR: r3(corr(tr.map(r => r.m), tr.map(r => r.wp))),
  test2026: { teams: te.length, r: r3(corr(te.map(r => r.m), te.map(r => r.wp))), rmseWinPct: r3(rmse(te.map(r => r.wp), cPred)) },
  // by season: the slope is stable
  bySeason: Object.fromEntries(YEARS.filter(y => y < TEST).map(y => { const s = tr.filter(r => r.y === y); return [y, r4(line(s.map(r => r.m), s.map(r => r.wp)).b)]; })),
  warPerAv: r4(SAV_PTS * 12 * cf.b),
};

// ---- NFL: wins on point differential -------------------------------------------------------------------------
const csv = await (await fetch('https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv')).text();
const [head, ...lines] = csv.trim().split('\n'), H = head.split(',');
const col = k => H.indexOf(k);
const NT = {};
for (const l of lines) {
  const c = l.split(','); if (c[col('game_type')] !== 'REG' || c[col('home_score')] === 'NA') continue;
  const y = +c[col('season')], hs = +c[col('home_score')], as = +c[col('away_score')];
  for (const [t, d, pf] of [[c[col('home_team')], hs - as, hs], [c[col('away_team')], as - hs, as]]) {
    const a = (NT[y + t] ||= { y, g: 0, w: 0, d: 0, pf: 0 }); a.g++; a.w += d > 0 ? 1 : d === 0 ? 0.5 : 0; a.d += d; a.pf += pf;
  }
}
const nrows = Object.values(NT).filter(r => r.y >= 2002 && r.y <= 2025 && r.g >= 16).map(r => ({ ...r, w17: r.w * 17 / r.g, d17: r.d * 17 / r.g, pf17: r.pf * 17 / r.g }));
const ntr = nrows.filter(r => r.y >= 2010 && r.y <= 2022), nte = nrows.filter(r => r.y >= 2023);
const nf = line(ntr.map(r => r.d17), ntr.map(r => r.w17));
const lgPts = mean(nrows.filter(r => r.y >= 2021).map(r => r.pf17));
const nfl = {
  teamSeasons: ntr.length, winsPerPt: r4(nf.b), ptsPerWin: r3(1 / nf.b), fitR: r3(corr(ntr.map(r => r.d17), ntr.map(r => r.w17))),
  test2023_25: { teams: nte.length, r: r3(corr(nte.map(r => r.d17), nte.map(r => r.w17))), rmseWins: r3(rmse(nte.map(r => r.w17), nte.map(r => nf.a + nf.b * r.d17))) },
  lgPts17: r3(lgPts), ptsPerAv: r3(lgPts / 100), warPerAv: r4(lgPts / 100 * nf.b),
};

// ---- 2026 teams: summed college WAR against record -----------------------------------------------------------
const wp26 = Object.fromEntries(te.map(r => [r.tid, r.wp]));
const T = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_teams.json'), 'utf8')).teams.filter(t => t.value != null && wp26[t.tid] != null);
const war = T.map(t => t.value * CWAR_PER_AV), wp = T.map(t => wp26[t.tid]);
const tl = line(war, wp);
const team = { teams: T.length, r: r3(corr(war, wp)), replWinPct: r3(tl.a), winPctPerWar: r3(tl.b), expectedPerWar: r3(1 / 12),
  avgTeamWar: r3(mean(war)) };

// the constants the site uses (scripts/cfb_av.mjs, rounded from the fits above); the templates read these
const constants = { cwarPerAv: r4(CWAR_PER_AV), nwarPerAv: r4(NWAR_PER_AV), nflReplAv: NFL_REPL_AV };
const out = { asof: new Date().toISOString().slice(0, 10), constants, college, nfl, team };
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
console.log(JSON.stringify(out, null, 1));
