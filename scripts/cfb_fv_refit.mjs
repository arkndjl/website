// Joint refit of the FV drivers: rebuild the board as it would have stood at the end of each season 2019-22 (every
// FBS PFN line at QB, RB, WR, TE, EDGE, DT and LB, every input the way fetch_cfb.mjs computes it), grade it with FV's
// own scarcity scale, and score each player's last college season against his NFL career. Then refit a multiplier
// on every driver jointly (1 = today's weight), leave one draft class out, shrunk toward today's weights with the
// penalty chosen inside each training fold, and report which multipliers beat today's weights out of sample.
// Run by hand after scripts/cfb_statplus_backtest.mjs (PFN boards, nflverse picks) and scripts/cfb_source_backtest.mjs
// (DraftTek boards, combine):  node scripts/cfb_fv_refit.mjs -> data/cfb_fv_refit.json
// Extra pulls, cached in scripts/.cache/fvrefit: 247Sports composite classes 2014-21 (pedigree and class year),
// cfbfastR rosters (listed height and weight) and schedules (team games, Elo as the team-strength read; SP+ needs
// CFBD, which this script doesn't call).
// Outcomes: weighted NFL AV a season through 2025 (undrafted 0), and draft capital (the AV a season the slot returns,
// fit on the 2012-19 drafts), each player's draft right after his last PFN season; players in a later draft dropped.
// Accuracy: Pearson r of avOf(FV) (the board's own FV -> NFL AV map) with the outcome, pooled over positions, and the
// mean within-position r. Model FV (before consensus) is the fitted quantity; FV with DraftTek's final board blended
// in at CONS_W is shown as a check (the final board is better informed than an in-season one).
// Not testable here (no history, or covered by its own backtest): On3's college grade, supporting cast, injuries,
// actual-vs-expected (scripts/cfb_oe_backtest.mjs), QBR and play-by-play rates, real birthdates.
// Stages: screen (one driver at a time on four universes), joint (every driver at once), focused (the age and class
// group plus snap share), shipped (the changes kept, scored). Flags: --quick [--ship=k=v,...] scores a set only,
// --calib prints calibration by years on campus.
// Result (Oct 14, 2026; 3,213 last seasons, 503 drafted, plus 2,557 earlier-season rows): the full joint refit gains
// nothing out of sample (its fit on last seasons costs the underclassmen), so today's weights stand except three:
//   old-side age debit x.5 (all five held-out classes chose .5; within-position r with NFL AV .507 -> .518 and with
//   draft slot .586 -> .602; old players were under-graded against their NFL AV), snap share x.4 (alone it fits at 0),
//   combine testing x1.6 (last seasons). Together: AV r .513 -> .520 pooled, .507 -> .525 within position; draft slot
//   .577 -> .590 and .586 -> .610. Production by position, pedigree, team, class, SOS, breakout, badges, frame and years
//   past three all refit within noise of today's weights (reverting them costs nothing).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { BADGES } from './cfb_badges.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SP = path.join(ROOT, 'scripts', '.cache', 'statplus'), SRC = path.join(ROOT, 'scripts', '.cache', 'sources');
const C = path.join(ROOT, 'scripts', '.cache', 'fvrefit');
const OUT = path.join(ROOT, 'data', 'cfb_fv_refit.json');
const CAL = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_calibration.json'), 'utf8'));
const BOARD = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb.json'), 'utf8'));
for (const d of ['247', 'ros']) fs.mkdirSync(path.join(C, d), { recursive: true });
const G7 = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB'];
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 };
const NFLPOS = { QB: ['QB'], RB: ['RB', 'FB'], WR: ['WR'], TE: ['TE'], EDGE: ['DE', 'OLB', 'EDGE', 'DL'], DL: ['DT', 'DE', 'DL', 'NT'], LB: ['LB', 'ILB', 'OLB', 'MLB'] };
const SEASONS = [2019, 2020, 2021, 2022], NFL_THROUGH = 2025;
// the 2026 FBS board's pool per position (static/data/cfb-all.json), so history grades on today's scale
const N26 = { QB: 171, RB: 397, WR: 607, TE: 389, EDGE: 692, DL: 798, LB: 616 };

// ---- today's FV constants (scripts/fetch_cfb.mjs) ------------------------------------------------------------
const CUR = {
  K: 3000, W: { 0: 5, 1: 4, 2: 3 }, pfn: 0.40, prodPos: { QB: 1.03, RB: 1.03, WR: 1.06, TE: 1.08, EDGE: 0.94, DL: 0.92, LB: 0.94 },
  nonBlue: 0.75, team: 0.05, teamCap: 0.15, age: { pivot: 21.0, perYear: 0.25, curve: 0.06, capYoung: 1.1, capOld: 0.9 },
  agePos: { WR: 1.45, EDGE: 1.3, RB: 1.1, QB: 0.8 }, cls: { perYear: 0.06, fr: 0.12 }, snap: { w: 0.08, cap: 0.12 },
  sos: { perSd: 0.1, cap: 0.2 }, hs: { w: 0.15, cap: 0.3 }, brk: [0.15, 0.1, 0.03, 0], brkPos: { WR: 1.3, TE: 1.3, RB: 1.3, QB: 0.8 },
  badge: { QB: { accurate: 0.13, deep: 0.2 }, RB: { catcher: 0.13 }, TE: { catcher: 0.24 }, DL: { runstop: 0.07 }, LB: { tackler: 0.1 } }, badgeCap: 0.3,
  ath: 0.106, athCap: 0.2, cons: 0.5,
};
const POS_SHIFT = BOARD.posShift, FV_POS_STRENGTH = 1;   // data/cfb.json posShift already carries FV_POS_STRENGTH
const RELI = Object.fromEntries(Object.entries(CAL.reliability).map(([g, r]) => [g, Math.round((r + 0.05) * 100) / 100]));
const FV_POS_VALUE = { QB: 1, OL: 1, EDGE: 1, WR: 1, CB: 1, DL: 0.7, TE: 0.75, S: 0.75, LB: 0.7, RB: 0.7 }, FV_QB_MID = 1.6, FV_TOP_SLOPE = -0.115;
const TIERS = Object.fromEntries(Object.entries(CAL.tiers).map(([g, a]) => {
  const pts = a.filter(([f, n]) => f >= 30 && f <= 55 && n > 0).map(([f, n]) => [f, Math.log(n)]);
  const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length, my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const b = pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  const at = f => f <= 55 ? Math.exp(my + b * (f - mx)) : Math.exp(my + b * (55 - mx) + FV_TOP_SLOPE * (f - 55));
  const pv = f => (1 - (1 - (FV_POS_VALUE[g] ?? 1)) * Math.min(1, Math.max(0, (f - 50) / 10)))
    * (g === 'QB' ? 1 + (FV_QB_MID - 1) * Math.min(1, Math.max(0, (55 - f) / 10)) : 1);
  return [g, [80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30].map(f => [f, Math.round(at(f) * pv(f) * 1000) / 1000])];
}));
// fvFromRank without the rounding, so the fit sees small moves
function fvFromRank(rankPerClass, g, poolPerClass) {
  const anchors = [...(TIERS[g] || [])].map(([f, n]) => [f, n]);
  anchors.push([20, Math.max(poolPerClass, (anchors.at(-1)?.[1] ?? 1) * 2)]);
  for (let i = 1; i < anchors.length; i++) anchors[i][1] = Math.max(anchors[i][1], anchors[i - 1][1] * 1.08);
  const x = Math.log(rankPerClass);
  if (x <= Math.log(anchors[0][1])) return anchors[0][0];
  for (let i = 1; i < anchors.length; i++) {
    const [f0, n0] = anchors[i - 1], [f1, n1] = anchors[i];
    if (x <= Math.log(n1)) return f0 + (f1 - f0) * (x - Math.log(n0)) / (Math.log(n1) - Math.log(n0));
  }
  return 20;
}
function frameFV(g, ht, wt) {
  const n = CAL.size[g]; if (!n || !ht || !wt) return 0;
  let fv = 0;
  for (const [m, x] of [['ht', ht], ['wt', wt]]) {
    const q = n[m], h = n.hinge || {}; if (!q) continue;
    if (x < q.p10) fv -= Math.abs(h[m + '_lo'] ?? 0) * (q.p10 - x) / q.sd;
    else if (x > q.p90) fv += (h[m + '_hi'] ?? 0) < 0 ? h[m + '_hi'] * (x - q.p90) / q.sd : 0;
    else fv += Math.max(0, h[m + '_mid'] ?? 0) * (x - q.p50) / q.sd * 0.5;
  }
  fv = Math.max(-8, Math.min(3, fv * 0.5));
  if (g === 'EDGE') fv += -Math.min(5, Math.max(0, n.wt.p10 - 10 - wt) * 0.25);
  return fv;
}
const AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [70, 6.6], [80, 8.5]];
const avOf = fv => { for (let i = 1; i < AV_BY_FV.length; i++) { const [f0, a0] = AV_BY_FV[i - 1], [f1, a1] = AV_BY_FV[i]; if (fv <= f1) return a0 + (a1 - a0) * Math.max(0, fv - f0) / (f1 - f0); } return 8.5; };
const consFV = avg => Math.max(30, Math.min(80, 80 - 8.7 * Math.log(Math.max(1, avg) / 2.7)));

// ---- helpers --------------------------------------------------------------------------------------------------
const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sdv = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const corr = (xs, ys) => { const mx = mean(xs), my = mean(ys); let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return b && c ? a / Math.sqrt(b * c) : 0; };
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;
const clamp = (x, c) => Math.max(-c, Math.min(c, x));
const phi = x => { const t = 1 / (1 + 0.2316419 * Math.abs(x)), d = 0.3989423 * Math.exp(-x * x / 2), p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return x > 0 ? 1 - p : p; };
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
// last name for the fallback match (boards and PFR spell some first names differently: Cam / Cameron Ward)
const lastName = s => nm((s || '').replace(/\(.*?\)/g, '')).split(' ').at(-1) || '';
const school = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').replace(/\s+/g, ' ').trim().split(' ')[0];
function csv(text) {
  const rows = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true; else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n') { row.push(cur.replace(/\r$/, '')); rows.push(row); row = []; cur = ''; } else cur += c;
  }
  if (cur || row.length) { row.push(cur); rows.push(row); }
  const [h, ...b] = rows; return b.filter(r => r.length === h.length).map(r => Object.fromEntries(h.map((k, i) => [k, r[i]])));
}
// 247 and raw.githubusercontent through curl (247 refuses some clients)
function pull(file, url) {
  const f = path.join(C, file);
  if (!fs.existsSync(f) || !fs.statSync(f).size) { try { execFileSync('curl', ['-sSLf', '-A', 'Mozilla/5.0', '-o', f, url]); } catch { fs.writeFileSync(f, ''); } }
  return fs.readFileSync(f, 'utf8');
}

// ---- data -----------------------------------------------------------------------------------------------------
const picksAll = csv(fs.readFileSync(path.join(SP, 'draft_picks.csv'), 'utf8'));
const picks = picksAll.filter(r => +r.season >= 2020 && +r.season <= 2025);
// draft capital: AV a season by slot, a + b ln(pick), fit on the 2012-19 drafts
const capital = (() => {
  const S = picksAll.filter(r => +r.season >= 2012 && +r.season <= 2019 && +r.pick > 0), x = S.map(r => Math.log(+r.pick)), y = S.map(r => (+r.w_av || 0) / (NFL_THROUGH - +r.season + 1));
  const mx = mean(x), my = mean(y), b = x.reduce((a, v, i) => a + (v - mx) * (y[i] - my), 0) / x.reduce((a, v) => a + (v - mx) ** 2, 0);
  return pick => Math.max(0, my + b * (Math.log(pick) - mx));
})();
// 247 composite, high school classes 2014-21
const rec = {};
for (let y = 2014; y <= 2021; y++) for (let pg = 1; pg <= 60; pg++) {
  const h = pull(`247/c_${y}_${pg}.html`, `https://247sports.com/season/${y}-football/compositerecruitrankings/?ViewPath=~/Views/SkyNet/PlayerSportRanking/_SimpleSetForSeason.ascx&Page=${pg}`);
  const items = h.split('rankings-page__list-item"').slice(1); if (!items.length) break;
  for (const x of items) {
    const g = p => (x.match(p) || [])[1], sc = g(/class="score">([\d.]+)/), name = g(/name-link"[^>]*>([^<]*)/); if (!sc || !name) continue;
    const stars = (x.match(/icon-starsolid yellow/g) || []).length, sch = g(/class="img-link"[^>]*>\s*<img alt="([^"]*)"/) || '';
    (rec[nm(name.replace(/&#39;/g, "'"))] ||= []).push({ y, rating: +sc, stars, school: school(sch) });
  }
}
// rosters (height, weight, ESPN class) and team schedules (games, start-of-season Elo)
const ros = {}, elo = {}, games = {};
for (let y = 2017; y <= 2022; y++) {
  for (const r of csv(pull(`ros/r${y}.csv`, `https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/csv/cfb_rosters_${y}.csv`))) {
    const k = y + '|' + nm(r.first_name + ' ' + r.last_name);
    (ros[k] ||= []).push({ team: school(r.team), ht: +r.height || null, wt: +r.weight || null, year: +r.year });
  }
  const S = csv(pull(`ros/s${y}.csv`, `https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/csv/cfb_schedules_${y}.csv`))
    .filter(r => r.completed === 'TRUE').sort((a, b) => a.start_date < b.start_date ? -1 : 1);
  elo[y] = {}; games[y] = {};
  for (const r of S) for (const side of ['home', 'away']) {
    if (r[side + '_division'] !== 'fbs') continue;
    const t = school(r[side + '_team']); games[y][t] = (games[y][t] || 0) + 1;
    if (!(t in elo[y]) && +r[side + '_pregame_elo']) elo[y][t] = +r[side + '_pregame_elo'];
  }
  const v = Object.values(elo[y]), m = mean(v), s = sdv(v); for (const t of Object.keys(elo[y])) elo[y][t] = (elo[y][t] - m) / s;
}
// DraftTek final boards (cached by cfb_source_backtest.mjs)
const board = {};
for (const D of [2020, 2021, 2022, 2023]) {
  board[D] = {};
  for (let pg = 1; pg <= 6; pg++) {
    const f = path.join(SRC, `dt_${D}_${pg}.html`); if (!fs.existsSync(f)) continue;
    const s = fs.readFileSync(f, 'latin1').replace(/<!--.*?-->/gs, '');
    for (const tr of s.matchAll(/<tr[^>]*>(.*?)<\/tr>/gs)) {
      const td = [...tr[1].matchAll(/<td[^>]*>(.*?)<\/td>/gs)].map(m => m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").trim());
      if (td.length >= 8 && /^\d+$/.test(td[0])) { const k = nm(td[2].replace(/\(.*?\)/g, '')); if (!(k in board[D])) board[D][k] = +td[0];
        const lk = 'last|' + lastName(td[2]) + '|' + school(td[3]); board[D][lk] = lk in board[D] ? null : +td[0]; }
    }
  }
}
// combine athletic z (fetchCombine's recipe: invitees at the group since 2010, centred on the mean tester)
const ath = {};
{
  const combine = csv(fs.readFileSync(path.join(SRC, 'combine.csv'), 'utf8'));
  const GR = { QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', OT: 'OL', OG: 'OL', OL: 'OL', C: 'OL', G: 'OL', T: 'OL', DE: 'EDGE', EDGE: 'EDGE', OLB: 'EDGE', DT: 'DL', DL: 'DL', NT: 'DL', ILB: 'LB', LB: 'LB', CB: 'CB', DB: 'CB', S: 'S', SAF: 'S', FS: 'S', SS: 'S' };
  const met = p => ({ spd: +p.forty && +p.wt ? +p.wt * 200 / (+p.forty) ** 4 : null, vert: +p.vertical || null, broad: +p.broad_jump || null, cone: +p.cone ? -p.cone : null, shut: +p.shuttle ? -p.shuttle : null });
  const pool = {};
  for (const p of combine) { const g = GR[p.pos]; if (!g || +p.season < 2010) continue; for (const [k, v] of Object.entries(met(p))) if (v != null) (pool[g + k] ||= []).push(v); }
  const ms = Object.fromEntries(Object.entries(pool).map(([k, xs]) => [k, [mean(xs), sdv(xs)]]));
  const athOf = (p, g) => { const zs = g ? Object.entries(met(p)).filter(([k, v]) => v != null && ms[g + k]).map(([k, v]) => (v - ms[g + k][0]) / ms[g + k][1]) : []; return zs.length >= 2 ? mean(zs) : null; };
  const tm = {};
  for (const p of combine) { const g = GR[p.pos], a = +p.season >= 2010 ? athOf(p, g) : null; if (a != null) (tm[g] ||= []).push(a); }
  for (const p of combine) { const g = GR[p.pos], a = athOf(p, g); if (a != null && +p.season >= 2020 && +p.season <= 2023) ath[p.season + '|' + nm(p.player_name)] = { ath: a - mean(tm[g]), school: school(p.school) }; }
}

console.error("data loaded", process.uptime().toFixed(1));
// ---- the board, season by season ------------------------------------------------------------------------------
// every row gets its raw driver values; terms() turns them into composite terms under a set of multipliers
const rows = [];        // one per PFN line 2019-22 (the pools); .final marks a player's last PFN season
for (const g of G7) {
  const all = JSON.parse(fs.readFileSync(path.join(SP, `pfn_${g}.json`))).filter(r => r.division === 'FBS'), cz = {};
  for (const r of all) (cz[r.season] ||= []).push(r.score);
  for (const s of Object.keys(cz)) cz[s] = [mean(cz[s]), sdv(cz[s])];
  const snaps = r => num(r.snapsQ) ?? num(r.snaps) ?? ((num(r.gp) ?? num(r.gamesQ) ?? 0) * SPG[g]);
  for (const r of all) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = snaps(r); }
  // badge z, as the badge backtest measures it: regressed by the badge's k, z within position-season (100+ snaps)
  const bz = {};
  for (const [key, , val, vol, half] of BADGES[g] || []) {
    if (Array.isArray(val) || !CUR.badge[g]?.[key]) continue;
    bz[key] = new Map();
    for (const s of Object.keys(cz)) {
      const pool = all.filter(r => r.season === +s && r._v >= 100).map(r => ({ r, v: num(val(r)), n: Math.max(0, num(vol(r)) ?? 0) })).filter(x => x.v != null);
      if (pool.length < 20) continue;
      const nw = pool.reduce((a, x) => a + x.n, 0), m = nw ? pool.reduce((a, x) => a + x.n * x.v, 0) / nw : mean(pool.map(x => x.v));
      for (const x of pool) x.reg = m + (x.v - m) * x.n / (x.n + half);
      const mm = mean(pool.map(x => x.reg)), sd = sdv(pool.map(x => x.reg));
      for (const x of pool) bz[key].set(x.r, (x.reg - mm) / sd);
    }
  }
  const byId = {}; for (const r of all) (byId[r.id] ||= {})[r.season] = r;
  for (const s of SEASONS) {
    const pool = all.filter(r => r.season === s), P = [];
    for (const r of pool) {
      const by = byId[r.id], n = nm(r.name), sch = school(r.team);
      let a = 0, d = 0; for (let k = 0; k <= 2; k++) { const x = by[s - k]; if (x) { a += CUR.W[k] * x._v * x._z; d += CUR.W[k] * x._v; } }
      // recruiting: a 247 record by name, class 2014 to this season, the school's if there are several
      const cands = (rec[n] || []).filter(x => x.y <= s && x.y >= s - 6), rc = cands.find(x => x.school === sch) || (cands.length === 1 ? cands[0] : null);
      const rl = (ros[s + '|' + n] || []).find(x => x.team === sch) || (ros[s + '|' + n] || [])[0] || null;
      const years = rc ? s - rc.y + 1 : rl && rl.year >= 1 && rl.year <= 5 ? rl.year + 0.5 : 4;
      const brk = Object.values(by).filter(x => x.season <= s && x._z >= 1.04 && x._v >= 150).map(x => x.season).sort()[0];
      const visible = rc && rc.y >= 2019;          // PFN starts in 2019: a breakout year is only known from a 2019+ class
      const last = Math.max(...Object.keys(by).map(Number));
      const tg = games[s][sch] || 12, side = 68 * tg;
      P.push({
        g, s, id: r.id, name: r.name, final: last === s, last, lastRow: by[last], row: r, marcel: a / (d + CUR.K), snapsN: r._v,
        share: g === 'RB' && num(r.share) != null ? Math.min(1, r.share / 100) : r._v ? Math.min(1, r._v / side) : null,
        rating: rc?.rating ?? null, stars: rc?.stars ?? 0, walkOn: !rc, years, ht: rl?.ht ?? null, wt: rl?.wt ?? null,
        team: elo[s][sch] ?? null, sos: num(r.sos), breakYear: visible && brk ? brk - rc.y + 1 : null, breakKnown: !!visible,
        badge: Object.fromEntries(Object.keys(bz).map(k => [k, bz[k].get(r) ?? null])),
      });
    }
    // within-pool standardizations, as the board does them
    const zs = P.map(p => p.marcel), m = mean(zs), sd = sdv(zs);
    const rt = P.map(p => p.rating).filter(v => v != null), hm = mean(rt), hsd = sdv(rt);
    const sh = P.filter(p => p.share != null && p.snapsN >= 60).map(p => p.share), shm = mean(sh), shs = sdv(sh);
    const so = P.map(p => p.sos).filter(v => v != null), som = mean(so), sos = sdv(so);
    for (const p of P) {
      p.zPfn = (p.marcel - m) / sd;
      p.hsRaw = p.rating != null ? (p.rating - hm) / hsd : -1.5;
      p.shareZ = p.share != null && p.snapsN >= 60 ? (p.share - shm) / shs : 0;
      p.sosZ = p.sos != null ? (p.sos - som) / sos : 0;
    }
    rows.push(...P);
  }
}
// outcomes: the draft right after a player's last PFN season, for every row whose player had left college by 2023
// (finals: the last-season rows 2019-22, the main universe; earlier rows feed the earlier-vantage check)
const finals = [], early = [];
for (const p of rows) {
  if (p.last > 2023) continue;
  const D = p.last + 1, n = nm(p.name), tm = school(p.lastRow.team), cand = picks.filter(x => nm(x.pfr_player_name) === n && NFLPOS[p.g].includes(x.position));
  let pk = cand.find(x => +x.season === D && school(x.college) === tm) || cand.find(x => +x.season === D);
  if (!pk && cand.some(x => +x.season > D)) continue;
  // no exact name: the one draftee that year with his last name, position group and school
  if (!pk) { const c = picks.filter(x => +x.season === D && lastName(x.pfr_player_name) === lastName(p.name) && NFLPOS[p.g].includes(x.position) && school(x.college) === tm); if (c.length === 1) pk = c[0]; }
  p.av = pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0;
  p.cap = pk ? capital(+pk.pick) : 0;
  p.pick = pk ? +pk.pick : null;
  p.ath = null; p.dt = null;
  if (p.final) {
    const a = ath[D + '|' + n]; p.ath = a && (a.school === tm || pk) ? a.ath : null;
    p.dt = board[D]?.[n] ?? board[D]?.['last|' + lastName(p.name) + '|' + tm] ?? null;
    finals.push(p);
  } else if (p.s <= 2021) early.push(p);
}
console.log('rows', rows.length, 'finals', finals.length, 'drafted', finals.filter(p => p.pick).length, '247 matched', r3(mean(finals.map(p => +!p.walkOn))),
  'roster ht', r3(mean(finals.map(p => +!!p.ht))), 'elo', r3(mean(finals.map(p => +(p.team != null)))), 'board', finals.filter(p => p.dt).length, 'ath', finals.filter(p => p.ath != null).length);

// ---- grading under a set of multipliers ---------------------------------------------------------------------
// M: multiplier per driver (1 = today). prod_<g> scales FV_PROD_POS, the rest scale one constant each
const KEYS = ['prod_QB', 'prod_RB', 'prod_WR', 'prod_TE', 'prod_EDGE', 'prod_DL', 'prod_LB', 'nonBlue', 'hs', 'team', 'age', 'ageY', 'ageO', 'cls', 'snap', 'sos', 'brk',
  'b_QB_accurate', 'b_QB_deep', 'b_RB_catcher', 'b_TE_catcher', 'b_DL_runstop', 'b_LB_tackler', 'ath', 'frame', 'years'];
const ONE = Object.fromEntries(KEYS.map(k => [k, 1]));
// these change the FV scale's absolute level, not just the order within a position, so they can't be pinned by
// re-normalizing: frame and years are FV points after the scarcity grade
const PROD = G7.map(g => 'prod_' + g), FVPTS = new Set(['frame', 'years']);
// the composite is standardized within each position, so scaling every composite term by one factor changes nothing:
// composite multipliers count relative to the mean production multiplier (frame and years are FV points, not scaled)
function effective(M) { const s = mean(PROD.map(k => M[k])); return Object.fromEntries(KEYS.map(k => [k, FVPTS.has(k) ? M[k] : M[k] / s])); }
function grade(M0, set = rows) {
  const out = new Map(), M = effective(M0);
  for (const g of G7) for (const s of SEASONS) {
    const P = set === rows ? POOLS[g + s] : set.filter(p => p.g === g && p.s === s);
    const am = CUR.agePos[g] ?? 1, brkM = CUR.brkPos[g] ?? 1;
    for (const p of P) {
      const ageEst = 17.9 + p.years, d = CUR.age.pivot - ageEst;
      const gate = Math.min(1, Math.max(0, (Math.max(p.zPfn, -0.6) + 1) / 2.5));
      const a = (d * CUR.age.perYear + (d > 0 ? 0 : CUR.age.curve) * d * Math.abs(d)) * am;
      const ageZ = a > 0 ? M.ageY * Math.min(a, CUR.age.capYoung * am) * gate : M.ageO * Math.max(a, -CUR.age.capOld * am);
      const runway = Math.max(0, Math.min(4, 5 - p.years));
      let cls = CUR.cls.perYear * (runway - 2.5) * (runway > 2.5 ? gate : 1);
      if (p.years <= 1.5 && (p.snapsN >= 150 || p.zPfn >= 0.3)) cls += CUR.cls.fr;
      const blue = p.stars >= 4, prodEff = p.zPfn * (blue || p.zPfn < 0 ? 1 : 1 - (1 - CUR.nonBlue) * M.nonBlue);
      const brk = p.breakYear == null ? (p.breakKnown && p.years >= 4 ? -0.05 * brkM : 0) : (CUR.brk[Math.max(1, Math.min(p.breakYear, 4)) - 1] ?? 0) * brkM;
      let badge = 0; for (const [k, w] of Object.entries(CUR.badge[g] || {})) if (p.badge[k] != null) badge += w * M[`b_${g}_${k}`] * p.badge[k];
      badge = clamp(badge, CUR.badgeCap);
      const athT = p.ath != null ? clamp(CUR.ath * M.ath * p.ath, CUR.athCap) : 0;
      p._comp = CUR.pfn * CUR.prodPos[g] * M['prod_' + g] * prodEff
        + M.hs * clamp(CUR.hs.w * p.hsRaw, CUR.hs.cap)
        + M.team * clamp(CUR.team * (p.team ?? 0), CUR.teamCap)
        + M.age * ageZ + M.cls * cls
        + M.snap * clamp(CUR.snap.w * p.shareZ, CUR.snap.cap)
        + (g === 'QB' ? M.sos * clamp(CUR.sos.perSd * p.sosZ, CUR.sos.cap) : 0)
        + M.brk * brk + badge + athT;
    }
    const m = mean(P.map(p => p._comp)), sd = sdv(P.map(p => p._comp)), r = RELI[g], N = N26[g];
    for (const p of P) {
      if (p.av == null) continue;
      const t = r * ((p._comp - m) / sd + (POS_SHIFT[g] ?? 0) * FV_POS_STRENGTH);
      const base = fvFromRank(Math.max(0.5, N * (1 - phi(t))) / 4, g, N / 4);
      const fm = Math.max(20, Math.min(80, base + M.frame * frameFV(g, p.ht, p.wt) - M.years * Math.max(0, p.years - 3) * (g === 'QB' ? 2 : 1)));
      const fc = p.dt ? fm + (consFV(p.dt) - fm) * CUR.cons : fm;
      out.set(p, { fm, fc });
    }
  }
  return out;
}
console.error("board built", process.uptime().toFixed(1));
const POOLS = {}; for (const p of rows) (POOLS[p.g + p.s] ||= []).push(p);
// accuracy over a set of final-season players: pooled r of avOf(FV) with the target, and the mean within-position r
function score(G, set, target = 'av', fvKey = 'fm') {
  const S = set.filter(p => G.has(p)), x = S.map(p => avOf(G.get(p)[fvKey])), y = S.map(p => p[target]);
  const within = G7.map(g => { const T = S.filter(p => p.g === g); return corr(T.map(p => G.get(p)[fvKey]), T.map(p => p[target])); });
  return { pooled: corr(x, y), within: mean(within), byPos: Object.fromEntries(G7.map((g, i) => [g, r3(within[i])])) };
}
// objective: the pooled r on AV (the main target), plus the within-position r, minus the shrinkage toward today
const objective = (M, set, lam) => { const G = grade(M), s = score(G, set), E = effective(M); return s.pooled + s.within - lam * KEYS.reduce((a, k) => a + (E[k] - 1) ** 2, 0); };
// coordinate search over multipliers on a shrinking step (the objective is piecewise, so no gradients)
function fit(set, lam, keys = KEYS) {
  let M = { ...ONE }, best = objective(M, set, lam);
  for (const step of [0.5, 0.25, 0.1]) {
    for (let sweep = 0; sweep < 3; sweep++) {
      let moved = false;
      for (const k of keys) for (const dir of [1, -1]) {
        const T = { ...M, [k]: Math.max(-1, Math.min(4, M[k] + dir * step * (PROD.includes(k) ? 1 : mean(PROD.map(q => M[q]))))) }, v = objective(T, set, lam);
        if (v > best + 1e-6) { M = T; best = v; moved = true; }
      }
      if (!moved) break;
    }
  }
  return M;
}

// ---- stage 1, screen: one driver at a time, its multiplier refit leaving one draft class out ---------------------
// universes: last (last seasons 2019-22), exact (those with a 247 class, so class year and age are known), earlier
// (earlier seasons 2019-21 of players gone by 2023: the board grades underclassmen too), all (last + earlier)
const U = [...finals, ...early], CLASSES = [...new Set(U.map(p => p.last))].sort();
const SETS = { last: finals, exact: finals.filter(p => !p.walkOn), earlier: early, all: U };
const gain = (G0, G1, S) => Object.fromEntries(['av', 'cap'].map(t => { const a = score(G0, S, t), b = score(G1, S, t); return [t, [r3(b.pooled - a.pooled), r3(b.within - a.within)]]; }));
function screen(keys) {
  const grid = [0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1, 1.25, 1.5, 1.75, 2, 2.5, 3], out = {}, G1 = grade(ONE);
  for (const k of keys) {
    out[k] = {};
    const Gs = grid.map(v => grade({ ...ONE, [k]: v }));
    for (const [sn, S] of Object.entries(SETS)) {
      const oof = new Map(), pick = [];
      for (const c of [...new Set(S.map(p => p.last))].sort()) {
        const tr = S.filter(p => p.last !== c); let bi = grid.indexOf(1), bv = -Infinity;
        Gs.forEach((G, i) => { const sc = score(G, tr); if (sc.pooled + sc.within > bv + 1e-9) { bv = sc.pooled + sc.within; bi = i; } });
        pick.push(grid[bi]); for (const p of S.filter(q => q.last === c)) oof.set(p, Gs[bi].get(p));
      }
      out[k][sn] = { folds: pick, ...gain(G1, oof, S) };
    }
    console.log('screen', k.padEnd(14), JSON.stringify(out[k]));
  }
  return out;
}
// ---- stage 2, joint: the drivers refit together, leave one draft class out, penalty picked inside the training folds
const LAMS = [0.003, 0.01, 0.03, 0.1];
const summary = G => {
  const o = {};
  for (const [sn, S] of [['all', U], ['last', finals], ['earlier', early]]) for (const t of ['av', 'cap']) { const v = score(G, S, t, 'fm'); o[sn + '_' + t] = { pooled: r3(v.pooled), within: r3(v.within), byPos: v.byPos }; }
  for (const t of ['av', 'cap']) { const v = score(G, finals, t, 'fc'); o['lastCons_' + t] = { pooled: r3(v.pooled), within: r3(v.within) }; }
  return o;
};
function cv(keys) {
  const res = { keys, folds: [], current: {}, refit: {}, multipliers: {}, revert: {} };
  const oofCur = new Map(), oofFit = new Map(), foldM = [], G0 = grade(ONE);
  for (const c of CLASSES) {
    const train = U.filter(p => p.last !== c), test = U.filter(p => p.last === c);
    let bestLam = LAMS[0], bestV = -Infinity;
    for (const lam of LAMS) {
      let v = 0;
      for (const c2 of CLASSES.filter(x => x !== c)) { const sc = score(grade(fit(train.filter(p => p.last !== c2), lam, keys)), train.filter(p => p.last === c2)); v += sc.pooled + sc.within; }
      if (v > bestV) { bestV = v; bestLam = lam; }
    }
    const M = effective(fit(train, bestLam, keys)), G = grade(M);
    for (const p of test) { oofFit.set(p, G.get(p)); oofCur.set(p, G0.get(p)); }
    foldM.push(M);
    res.folds.push({ draft: c + 1, lam: bestLam, current: r3(score(G0, test).pooled), refit: r3(score(G, test).pooled) });
    console.log('cv', keys.length, 'draft', c + 1, 'lam', bestLam, 'current', r3(score(G0, test).pooled), 'refit', r3(score(G, test).pooled));
  }
  res.current = summary(oofCur); res.refit = summary(oofFit);
  const lamAll = res.folds.map(f => f.lam).sort((a, b) => a - b)[CLASSES.length >> 1], MA = effective(fit(U, lamAll, keys));
  // revert: each fold's refit with one driver put back at today's weight, scored out of sample (negative = the change helps)
  for (const k of keys) {
    res.multipliers[k] = { all: r3(MA[k]), folds: foldM.map(M => r3(M[k])) };
    const oof = new Map();
    CLASSES.forEach((c, i) => { const G = grade({ ...foldM[i], [k]: 1 }); for (const p of U.filter(q => q.last === c)) oof.set(p, G.get(p)); });
    res.revert[k] = gain(oofFit, oof, U);
  }
  return res;
}
// ---- stage 3, shipped: the changes that held up, scored on every universe -----------------------------------------
// (ageO .5: every focused fold; snap .4: the focused fit, the screen wanted 0; ath 1.6: the last-season joint fit,
// since only last seasons carry a combine)
const SHIP = { ageO: 0.5, snap: 0.4, ath: 1.6 };
function shipped(M) {
  const G = grade({ ...ONE, ...M }), G0 = grade(ONE), o = {};
  for (const [sn, S] of Object.entries(SETS)) for (const t of ['av', 'cap']) { const a = score(G0, S, t), b = score(G, S, t); o[sn + '_' + t] = { before: [r3(a.pooled), r3(a.within)], after: [r3(b.pooled), r3(b.within)], byPos: { before: a.byPos, after: b.byPos } }; }
  for (const t of ['av', 'cap']) { const a = score(G0, finals, t, 'fc'), b = score(G, finals, t, 'fc'); o['lastCons_' + t] = { before: [r3(a.pooled), r3(a.within)], after: [r3(b.pooled), r3(b.within)] }; }
  return o;
}
const arg = k => (process.argv.find(a => a.startsWith(`--${k}=`)) || '').slice(k.length + 3).split(',').filter(Boolean);
const out = { asof: new Date().toISOString().slice(0, 10), method: 'see scripts/cfb_fv_refit.mjs', n: {} };
for (const g of G7) { const F = finals.filter(p => p.g === g); out.n[g] = { players: F.length, drafted: F.filter(p => p.pick).length, earlierRows: early.filter(p => p.g === g).length }; }
if (process.argv.includes('--calib')) {
  // calibration by years on campus: mean NFL AV and draft capital against what avOf(FV) promised, today vs shipped
  const G0 = grade(ONE), G1 = grade({ ...ONE, ...SHIP });
  for (const [sn, S] of [['last', finals], ['earlier', early]]) for (const y of [1, 2, 3, 4, 5, 6]) {
    const T = S.filter(p => Math.min(6, Math.round(p.years)) === y && G0.has(p)); if (T.length < 30) continue;
    console.log(sn, 'years', y, 'n', T.length, 'AV', r3(mean(T.map(p => p.av))), 'cap', r3(mean(T.map(p => p.cap))), 'avOf FV now', r3(mean(T.map(p => avOf(G0.get(p).fm)))), 'shipped', r3(mean(T.map(p => avOf(G1.get(p).fm)))),
      'FV now', r3(mean(T.map(p => G0.get(p).fm))), 'shipped', r3(mean(T.map(p => G1.get(p).fm))), 'drafted', r3(mean(T.map(p => +!!p.pick))));
  }
  process.exit(0);
}
if (process.argv.includes('--quick')) { const M = arg('ship').length ? Object.fromEntries(arg('ship').map(x => x.split('=')).map(([k, v]) => [k, +v])) : SHIP; console.log(JSON.stringify(shipped(M))); process.exit(0); }
out.screen = screen(arg('screen').length ? arg('screen') : KEYS.filter(k => k !== 'age'));
out.joint = cv(KEYS.filter(k => k !== 'ageY' && k !== 'ageO'));
out.focused = cv(['ageY', 'ageO', 'cls', 'years', 'snap']);
out.shipped = { multipliers: SHIP, ...shipped(SHIP) };
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
console.log(JSON.stringify(out.shipped));
