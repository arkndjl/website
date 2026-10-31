// Do the conference availability reports (scripts/cfb_avail_reports.mjs) sharpen the college P(plays)? Every offensive
// player with a box score in two or more of his team's earlier games this season (scripts/cfb_avail.mjs states), for
// each game his team filed a report for (2025-26: SEC, ACC; 2026 also MAC, American), against whether he is in that
// game's box score (ESPN lists a player only when he records an offensive stat, the same outcome the P(plays) fit uses).
//   box      P(plays) from the box scores alone (the live model for a player with no status)
//   current  the report's designation at the live status rates (cfb_avail_fit.json status: measured on the board's
//            news log and the NFL), box where he isn't listed: what reading the reports in alone would do
//   fit      a logistic on logit(box) and the designation (not listed is its own level), fit on one season, scored on
//            the other (2025 -> 2026 and 2026 -> 2025)
// Two reads: the last report before game day (what the daily refreshes see) and the game-day report.
//   node scripts/cfb_avail_reports_backtest.mjs [--game]   # -> data/cfb_avail_reports_backtest.json
// --game: each team's expected PPR lost to the reports (the fit's P(plays) under the box-only P(plays), times his
// line per game played) against the closing spread's miss (scripts/data/games_wf/cfb.json.gz), and on top of the
// walk-forward model's margin.
import fs from 'node:fs';
import zlib from 'node:zlib';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames } from './cfb_teams.mjs';
import { fetchBoxes } from './cfb_box.mjs';
import { timelines, states, pBox, logisticFit, PPR, statusPlay, reportPlay } from './cfb_avail.mjs';
import { loadReports, boardStatus, matchGames } from './cfb_avail_reports.mjs';
import { Matcher } from './names.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const SEASONS = [2025, 2026], MIN_K = 2;
const FIT = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_avail_fit.json'), 'utf8'));
const r3 = x => Math.round(x * 1000) / 1000;
const clip = p => Math.min(0.995, Math.max(0.005, p));
const logit = p => Math.log(clip(p) / (1 - clip(p)));
const sig = z => 1 / (1 + Math.exp(-z));
const ll = (p, y) => -(y ? Math.log(clip(p)) : Math.log(1 - clip(p)));

const seasonGames = {}, boxes = {};
for (const s of SEASONS) {
  const f = path.join(CACHE, `bt_games${s}.json`);
  let g = null; try { g = JSON.parse(fs.readFileSync(f, 'utf8')); } catch {}
  if (!g || s === 2026) { g = await fetchGames(s); fs.mkdirSync(CACHE, { recursive: true }); fs.writeFileSync(f, JSON.stringify(g)); }
  seasonGames[s] = g;
  Object.assign(boxes, await fetchBoxes(g, { log: false }));
}

// report rows by game (the ESPN game on the report's date with both teams matching)
const { rows } = loadReports();
const rep = matchGames(rows, SEASONS.flatMap(s => seasonGames[s]));
const nm = Object.values(rep).reduce((a, r) => a + r.length, 0);
console.log(`reports: ${rows.length} rows, ${Object.keys(rep).length} team games, ${rows.length - nm} rows unmatched`);

// the population: every player with box history on a team that filed for the game
const obs = [];
for (const s of SEASONS) {
  const tl = timelines(seasonGames[s], boxes);
  for (const [tid, list] of Object.entries(tl)) for (let k = MIN_K; k < list.length; k++) {
    const R = rep[list[k].gid + '|' + tid]; if (!R) continue;
    const S = states(list, k, FIT.m ?? 0);
    const M = new Matcher(Object.entries(S).map(([pid, x]) => ({ pid, name: x.n, team: tid })), { team: 'team' });
    const st = {};
    for (const r of R) { const [hit] = M.find(r.p, { team: tid }); if (hit) st[hit.pid] = r; }
    for (const [pid, x] of Object.entries(S)) {
      // pre: the last report before game day; a team that files only on game day (MAC, American) has none
      const r = st[pid], preRaw = r ? [...r.s.slice(0, 3)].reverse().find(Boolean) : null, filedPre = R.some(q => q.s.slice(0, 3).some(Boolean));
      const pre = !filedPre ? 'Unfiled' : preRaw ? boardStatus(preRaw) || 'Listed' : 'None', gd = r ? boardStatus(r.s[3]) || boardStatus(preRaw) || 'Listed' : 'None';
      obs.push({ s, tid, gid: list[k].gid, pid, p0: pBox(FIT.coef, x), ml: x.streak >= 1, ppg: x.ppg, line: PPR(x.v), listed: !!r, qb: x.qb,
        pre, gd, y: list[k].players[pid] ? 1 : 0 });
    }
  }
}
const LEVELS = ['None', 'Unfiled', 'Active', 'Probable', 'Questionable', 'Game Time Decision', 'Doubtful', 'Out', 'Listed'];
const rates = view => Object.fromEntries(LEVELS.map(L => { const o = obs.filter(x => x[view] === L); return [L, { n: o.length, played: o.reduce((a, x) => a + x.y, 0), rate: o.length ? r3(o.reduce((a, x) => a + x.y, 0) / o.length) : null, box: o.length ? r3(o.reduce((a, x) => a + x.p0, 0) / o.length) : null }]; }).filter(([, v]) => v.n));
console.log(`population: ${obs.length} player games (${obs.filter(o => o.listed).length} listed)`);
console.log('pre-game-day designation:', JSON.stringify(rates('pre')));
console.log('game-day designation:', JSON.stringify(rates('gd')));

// models
const X = (o, view, lv) => [1, logit(o.p0), ...lv.slice(1).map(L => o[view] === L ? 1 : 0), o.ml && o[view] === 'Questionable' ? 1 : 0];
const current = (o, view) => o[view] === 'None' || o[view] === 'Listed' ? o.p0 : statusPlay(FIT, o[view] === 'Game Time Decision' ? 'Questionable' : o[view], o.ml) ?? o.p0;
const score = (os, f) => { let a = 0, b = 0; for (const o of os) { const p = f(o); a += ll(p, o.y); b += (p - o.y) ** 2; } return { n: os.length, ll: r3(a / os.length * 1000) / 1000, brier: r3(b / os.length * 1000) / 1000 }; };
const res = {};
for (const view of ['pre', 'gd']) {
  const O = obs.filter(o => o[view] !== 'Unfiled');
  const lv = LEVELS.filter(L => obs.some(o => o[view] === L && o.s === 2025) && obs.some(o => o[view] === L && o.s === 2026));
  const out = {};
  for (const [tr, te] of [[2025, 2026], [2026, 2025]]) {
    const b = logisticFit(O.filter(o => o.s === tr).map(o => [X(o, view, lv), o.y]));
    // flat: each designation's played share on the training season (beta-binomial on the live rate, weight 10)
    const flatR = Object.fromEntries(lv.slice(1).map(L => { const o = O.filter(x => x.s === tr && x[view] === L), cur = statusPlay(FIT, L === 'Game Time Decision' ? 'Questionable' : L, false) ?? 0.5;
      return [L, (o.reduce((a, x) => a + x.y, 0) + 10 * cur) / (o.length + 10)]; }));
    const flat = o => flatR[o[view]] ?? o.p0;
    const fitP = o => sig(X(o, view, lv).reduce((s, v, i) => s + v * b[i], 0));
    const T = O.filter(o => o.s === te), Tl = T.filter(o => o.listed), Tc = T.filter(o => o.ml || o.listed);
    out[`${tr}->${te}`] = { coef: Object.fromEntries(['const', 'logit box', ...lv.slice(1), 'Q x missed last'].map((k, i) => [k, r3(b[i])])),
      all: { box: score(T, o => o.p0), current: score(T, o => current(o, view)), flat: score(T, flat), fit: score(T, fitP) },
      listed: { box: score(Tl, o => o.p0), current: score(Tl, o => current(o, view)), flat: score(Tl, flat), fit: score(Tl, fitP) },
      'listed or missed last': { box: score(Tc, o => o.p0), current: score(Tc, o => current(o, view)), flat: score(Tc, flat), fit: score(Tc, fitP) }, flatRates: Object.fromEntries(Object.entries(flatR).map(([k, v]) => [k, r3(v)])) };
    // paired per player game: the fit against box and against current, t by team-game clusters
    for (const [nm, f] of [['box', o => o.p0], ['current', o => current(o, view)], ['flat', flat]]) {
      const C = {}; for (const o of T) { C[o.gid + o.tid] = (C[o.gid + o.tid] || 0) + ll(fitP(o), o.y) - ll(f(o), o.y); }
      const v = Object.values(C), m = v.reduce((a, x) => a + x, 0) / v.length, sd = Math.sqrt(v.reduce((a, x) => a + (x - m) ** 2, 0) / (v.length - 1));
      out[`${tr}->${te}`][`fit vs ${nm}`] = { dLLperGame: r3(m), t: r3(m / (sd / Math.sqrt(v.length))) };
    }
    { const C = {}; for (const o of T) { C[o.gid + o.tid] = (C[o.gid + o.tid] || 0) + ll(flat(o), o.y) - ll(current(o, view), o.y); }
      const v = Object.values(C), m = v.reduce((a, x) => a + x, 0) / v.length, sd = Math.sqrt(v.reduce((a, x) => a + (x - m) ** 2, 0) / (v.length - 1));
      out[`${tr}->${te}`]['flat vs current'] = { dLLperGame: r3(m), t: r3(m / (sd / Math.sqrt(v.length))) }; }
    for (const o of T) o['p_' + view] = fitP(o);
  }
  res[view] = { rates: rates(view), levels: lv, folds: out };
  console.log(view, JSON.stringify(out, null, 1));
}
// the board's fit: both seasons pooled, every designation with 15+ player games; pre for the reports before game day
// (and news statuses), gd for the game-day report. p0Starter: the typical box P(plays) of a starter (8+ PPR a game),
// for a starter without a box score (line, defense) in the game model
const pooled = {};
for (const view of ['pre', 'gd']) {
  const O = obs.filter(o => o[view] !== 'Unfiled' && o[view] !== 'Listed');
  const lv = LEVELS.filter(L => L !== 'Unfiled' && L !== 'Listed' && O.filter(o => o[view] === L).length >= 15);
  const b = logisticFit(O.filter(o => lv.includes(o[view])).map(o => [X(o, view, lv), o.y]));
  pooled[view] = Object.fromEntries(['const', 'logitBox', ...lv.slice(1), 'QmissedLast'].map((k, i) => [k, r3(b[i])]));
}
const st = obs.filter(o => o.ppg >= 8).map(o => o.p0).sort((a, b) => a - b);
const fitFile = path.join(ROOT, 'data', 'cfb_avail_fit.json'), F = JSON.parse(fs.readFileSync(fitFile, 'utf8'));
F.reports = { asof: new Date().toISOString().slice(0, 10), n: obs.length, listed: obs.filter(o => o.listed).length, p0Starter: r3(st[st.length >> 1]), ...pooled,
  source: 'scripts/cfb_avail_reports_backtest.mjs' };
// a typical starter's chance by designation (the projections tab's note)
F.reports.starter = Object.fromEntries(['Probable', 'Questionable', 'Game Time Decision', 'Doubtful'].map(L => [L, r3(reportPlay(F, L, F.reports.p0Starter, false))]));
fs.writeFileSync(fitFile, JSON.stringify(F, null, 1) + '\n');
console.log('pooled fit', JSON.stringify(F.reports));
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_avail_reports_backtest.json'), JSON.stringify({ asof: new Date().toISOString().slice(0, 10), n: obs.length, listed: obs.filter(o => o.listed).length, ...res }, null, 1) + '\n');
fs.writeFileSync(path.join(CACHE, 'avail_reports_obs.json'), JSON.stringify(obs));
