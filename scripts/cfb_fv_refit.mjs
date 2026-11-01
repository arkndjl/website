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
import { pastAtMean } from './fv_dist.mjs';
import { fvOf } from './fv_scale.mjs';
import { NFLPOS, famOf } from './cfb_nflpos.mjs';
import { Matcher, teamKey } from './names.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SP = path.join(ROOT, 'scripts', '.cache', 'statplus'), SRC = path.join(ROOT, 'scripts', '.cache', 'sources');
const C = path.join(ROOT, 'scripts', '.cache', 'fvrefit');
const OUT = path.join(ROOT, 'data', 'cfb_fv_refit.json');
const CAL = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_calibration.json'), 'utf8'));
const BOARD = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb.json'), 'utf8'));
for (const d of ['247', 'ros']) fs.mkdirSync(path.join(C, d), { recursive: true });
const G7 = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB'];
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55, OL: 65, CB: 55, S: 55 };
// --wide: the 2014-22 classes. PFN starts in 2019, so seasons 2012-18 grade on box-score stand-ins for PFN's line
// (scripts/cfb_fv_boxlines.py: ESPN boxes and season leaderboards, PFN's score fit on 2019-22). --boxonly grades the
// 2019-22 classes on those stand-ins alone, to measure what they lose against PFN. Both read
// scripts/.cache/fvrefit/box_lines.json and write their stages to data/cfb_fv_wide.json (see the --wide block below)
const WIDE = process.argv.includes('--wide'), BOXONLY = process.argv.includes('--boxonly'), BOX = WIDE || BOXONLY;
const FIRST = WIDE ? 2014 : 2019, SEASONS = Array.from({ length: 2023 - FIRST }, (_, i) => FIRST + i), NFL_THROUGH = 2025;
const HIST0 = WIDE ? 2012 : 2019;     // first season with a production line (the 3-season blend and breakouts reach back to it)
// --past: every FBS PFN season 2019-25 graded under the shipped weights, written for the board's past-season grades
// (static/data/cfb-past.json; see the --past block below). OL, CB and S join there: PFN has their lines from 2024
const PAST = process.argv.includes('--past'), ROW_SEASONS = PAST ? [2019, 2020, 2021, 2022, 2023, 2024, 2025] : SEASONS;
const GP = PAST ? [...G7, 'OL', 'CB', 'S'] : G7;
const PFN_SLUG = { QB: 'quarterback', RB: 'running-back', WR: 'wide-receiver', TE: 'tight-end', OL: 'offensive-line', EDGE: 'edge', DL: 'defensive-tackle', LB: 'linebacker', CB: 'cornerback', S: 'safety' };
// the 2026 FBS board's pool per position (static/data/cfb-all.json), so history grades on today's scale
const N26 = { QB: 171, RB: 397, WR: 607, TE: 389, EDGE: 692, DL: 798, LB: 616, OL: 976, CB: 907, S: 458 };

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
const FV_POS_VALUE = { QB: 1, OL: 1, EDGE: 1, WR: 1, CB: 1, DL: 0.7, TE: 0.75, S: 0.75, LB: 0.7, RB: 0.7 }, FV_QB_MID = 1.6, FV_TOP_SLOPE = -0.115, FV_PEAK_SLOPE = -0.173;
const FV_TIER_FLOOR = new Set(['QB']);   // as fetch_cfb.mjs
// --target refits FV_POS_VALUE: tiersOf(g, a, pv) builds one position's tiers at a positional value, setPV swaps them in
const tiersOf = (g, a, pvg = FV_POS_VALUE[g] ?? 1) => {
  const pts = a.filter(([f, n]) => f >= 30 && f <= 55 && n > 0).map(([f, n]) => [f, Math.log(n)]);
  const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length, my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const b = pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  const at = f => f <= 55 ? Math.exp(my + b * (f - mx)) : Math.exp(my + b * (55 - mx) + FV_TOP_SLOPE * (Math.min(f, 60) - 55) + FV_PEAK_SLOPE * Math.max(0, f - 60));
  const pv = f => (1 - (1 - pvg) * Math.min(1, Math.max(0, (f - 50) / 10)))
    * (g === 'QB' ? 1 + (FV_QB_MID - 1) * Math.min(1, Math.max(0, (55 - f) / 10)) : 1);
  const raw = Object.fromEntries(a), top = f => f > 55 && FV_TIER_FLOOR.has(g) ? Math.max(at(f), raw[f] ?? 0) : at(f);
  const out = [80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30].map(f => [f, top(f) * pv(f)]);
  // 55 sits geometrically between 50 and the floored 60, so the curve has no cliff where the measured counts plateau
  if (FV_TIER_FLOOR.has(g)) out[5][1] = Math.max(out[5][1], Math.sqrt(out[4][1] * out[6][1]));
  return out.map(([f, n]) => [f, Math.round(n * 1000) / 1000]);
};
const TIERS = Object.fromEntries(Object.entries(CAL.tiers).map(([g, a]) => [g, tiersOf(g, a)]));
// fvFromRank without the rounding, so the fit sees small moves (anchors cached by position: the fit calls this a lot)
let ANCH = {};
const setPV = pv => { for (const [g, a] of Object.entries(CAL.tiers)) TIERS[g] = tiersOf(g, a, pv[g] ?? 1); ANCH = {}; };
function fvFromRank(rankPerClass, g, poolPerClass) {
  const anchors = ANCH[g + poolPerClass] ||= (() => {
    const a = [...(TIERS[g] || [])].map(([f, n]) => [f, n]);
    a.push([20, Math.max(poolPerClass, (a.at(-1)?.[1] ?? 1) * 2)]);
    for (let i = 1; i < a.length; i++) a[i][1] = Math.max(a[i][1], a[i - 1][1] * 1.08);
    return a.map(([f, n]) => [f, Math.log(n)]);
  })();
  const x = Math.log(rankPerClass);
  if (x <= anchors[0][1]) return anchors[0][0];
  for (let i = 1; i < anchors.length; i++) {
    const [f0, l0] = anchors[i - 1], [f1, l1] = anchors[i];
    if (x <= l1) return f0 + (f1 - f0) * (x - l0) / (l1 - l0);
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
const AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [65, 6.3], [70, 7.2], [75, 8.1], [80, 10.1]];   // as cfb_teams.mjs
const avOf = fv => { for (let i = 1; i < AV_BY_FV.length; i++) { const [f0, a0] = AV_BY_FV[i - 1], [f1, a1] = AV_BY_FV[i]; if (fv <= f1) return a0 + (a1 - a0) * Math.max(0, fv - f0) / (f1 - f0); } return AV_BY_FV.at(-1)[1]; };
const consFV = avg => { const r = Math.max(1, avg); return Math.max(30, Math.min(80, r >= 27 ? 80 - 8.7 * Math.log(r / 2.7) : 60 - Math.log(r / 27) / -FV_PEAK_SLOPE)); };   // as fetch_cfb.mjs

// ---- helpers --------------------------------------------------------------------------------------------------
const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sdv = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const corr = (xs, ys) => { const mx = mean(xs), my = mean(ys); let a = 0, b = 0, c = 0; xs.forEach((x, i) => { a += (x - mx) * (ys[i] - my); b += (x - mx) ** 2; c += (ys[i] - my) ** 2; }); return b && c ? a / Math.sqrt(b * c) : 0; };
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;
const clamp = (x, c) => Math.max(-c, Math.min(c, x));
// log gamma (Lanczos) and the incomplete beta's continued fraction, for Student t p-values (--stage=rw)
const lgam = x => { const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let y = x, t = x + 5.5; t -= (x + 0.5) * Math.log(t); let s = 1.000000000190015; for (const q of c) s += q / ++y; return -t + Math.log(2.5066282746310005 * s / x); };
const betacf = (x, a, b) => { let c = 1, d = 1 - (a + b) * x / (a + 1); d = 1 / (Math.abs(d) < 1e-30 ? 1e-30 : d); let h = d;
  for (let m = 1; m <= 200; m++) { const m2 = 2 * m; let aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2)); d = 1 + aa * d; c = 1 + aa / c; d = 1 / (Math.abs(d) < 1e-30 ? 1e-30 : d); h *= d * c;
    aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1)); d = 1 + aa * d; c = 1 + aa / c; d = 1 / (Math.abs(d) < 1e-30 ? 1e-30 : d); const del = d * c; h *= del; if (Math.abs(del - 1) < 3e-12) break; }
  return h; };
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
const picksAll = PAST ? [] : csv(fs.readFileSync(path.join(SP, 'draft_picks.csv'), 'utf8'));
const picks = picksAll.filter(r => +r.season >= FIRST + 1 && +r.season <= 2025);
// draft capital: AV a season by slot, a + b ln(pick), fit on the 2012-19 drafts
const capital = (() => {
  const S = picksAll.filter(r => +r.season >= 2012 && +r.season <= 2019 && +r.pick > 0), x = S.map(r => Math.log(+r.pick)), y = S.map(r => (+r.w_av || 0) / (NFL_THROUGH - +r.season + 1));
  const mx = mean(x), my = mean(y), b = x.reduce((a, v, i) => a + (v - mx) * (y[i] - my), 0) / x.reduce((a, v) => a + (v - mx) ** 2, 0);
  return pick => Math.max(0, my + b * (Math.log(pick) - mx));
})();
// 247 composite, high school classes 2014-21 (--wide: 2009-21)
const rec = {};
for (let y = WIDE ? 2009 : 2014, rk = 0; y <= (PAST ? 2025 : 2021); y++, rk = 0) for (let pg = 1; pg <= 60; pg++) {
  const h = pull(`247/c_${y}_${pg}.html`, `https://247sports.com/season/${y}-football/compositerecruitrankings/?ViewPath=~/Views/SkyNet/PlayerSportRanking/_SimpleSetForSeason.ascx&Page=${pg}`);
  const items = h.split('rankings-page__list-item"').slice(1); if (!items.length) break;
  for (const x of items) {
    const g = p => (x.match(p) || [])[1], sc = g(/class="score">([\d.]+)/), name = g(/name-link"[^>]*>([^<]*)/); if (!sc || !name) continue;
    const stars = (x.match(/icon-starsolid yellow/g) || []).length, sch = g(/class="img-link"[^>]*>\s*<img alt="([^"]*)"/) || '';
    (rec[nm(name.replace(/&#39;/g, "'"))] ||= []).push({ y, rating: +sc, stars, school: school(sch), sraw: sch, rank: ++rk });
  }
}
// rosters (height, weight, ESPN class) and team schedules (games, start-of-season Elo)
const ros = {}, elo = {}, games = {};
for (let y = WIDE ? 2012 : 2017; y <= (PAST ? 2025 : 2022); y++) {
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
      // keyed with the position family: the last-name-and-school fallback once handed Georgia's Jalen Carter (7) and
      // Broderick Jones (18) to two Georgia receivers, fake top-20 prospects with no NFL career
      if (td.length >= 8 && /^\d+$/.test(td[0])) { const f = famOf(td[4]), k = nm(td[2].replace(/\(.*?\)/g, '')) + '|' + f; if (!(k in board[D])) board[D][k] = +td[0];
        const lk = 'last|' + lastName(td[2]) + '|' + school(td[3]) + '|' + f; board[D][lk] = lk in board[D] ? null : +td[0]; }
    }
  }
}
// --inseason (with --dist; FV audit, Oct 26 2026): the live board grades in October, before the final boards and the
// combine, so the distribution is fit on what it would have seen then: PFF's in-season board (its latest version
// dated by Dec 31 of the final season, as scripts/cfb_draft_pct_backtest.py caches them; the 2020 draft has none)
// in place of DraftTek's final board, and no combine testing
const INSEASON = process.argv.includes('--inseason');
const pffIn = {};
if (INSEASON) {
  const DP = path.join(ROOT, 'scripts', '.cache', 'draftpct'); fs.mkdirSync(DP, { recursive: true });
  for (const D of [2020, 2021, 2022, 2023]) {
    let best = null;
    for (let v = 1; v <= 15; v++) {
      const f = path.join(DP, `pff_${D}_${v}.json`);
      if (!fs.existsSync(f)) execFileSync('curl', ['-sSL', '-m', '60', '-A', 'Mozilla/5.0', '-o', f, `https://www.pff.com/api/college/big_board?season=${D}&version=${v}`]);
      let d; try { d = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { continue; }
      const day = (d.last_updated_at || '').slice(0, 10);
      if ((d.players || []).length && day && day <= `${D - 1}-12-31` && !(best && best.day > day)) best = { day, v, players: d.players };
    }
    pffIn[D] = {};
    for (const x of best?.players || []) {
      if (!x.pff_rank) continue;
      const f = famOf(x.position), k = nm(x.name) + '|' + f; if (!(k in pffIn[D])) pffIn[D][k] = +x.pff_rank;
      const lk = 'last|' + lastName(x.name) + '|' + school(x.college || x.team?.city || '') + '|' + f; pffIn[D][lk] = lk in pffIn[D] ? null : +x.pff_rank;
    }
    console.error('in-season board', D, best ? `v${best.v} ${best.day} ${best.players.length}` : 'none');
  }
}
// combine athletic z (fetchCombine's recipe: invitees at the group since 2010, centred on the mean tester)
const ath = {};
if (!PAST) {
  const combine = csv(fs.readFileSync(path.join(SRC, 'combine.csv'), 'utf8'));
  const GR = { QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', OT: 'OL', OG: 'OL', OL: 'OL', C: 'OL', G: 'OL', T: 'OL', DE: 'EDGE', EDGE: 'EDGE', OLB: 'EDGE', DT: 'DL', DL: 'DL', NT: 'DL', ILB: 'LB', LB: 'LB', CB: 'CB', DB: 'CB', S: 'S', SAF: 'S', FS: 'S', SS: 'S' };
  const met = p => ({ spd: +p.forty && +p.wt ? +p.wt * 200 / (+p.forty) ** 4 : null, vert: +p.vertical || null, broad: +p.broad_jump || null, cone: +p.cone ? -p.cone : null, shut: +p.shuttle ? -p.shuttle : null });
  const pool = {};
  for (const p of combine) { const g = GR[p.pos]; if (!g || +p.season < 2010) continue; for (const [k, v] of Object.entries(met(p))) if (v != null) (pool[g + k] ||= []).push(v); }
  const ms = Object.fromEntries(Object.entries(pool).map(([k, xs]) => [k, [mean(xs), sdv(xs)]]));
  const athOf = (p, g) => { const zs = g ? Object.entries(met(p)).filter(([k, v]) => v != null && ms[g + k]).map(([k, v]) => (v - ms[g + k][0]) / ms[g + k][1]) : []; return zs.length >= 2 ? mean(zs) : null; };
  const tm = {};
  for (const p of combine) { const g = GR[p.pos], a = +p.season >= 2010 ? athOf(p, g) : null; if (a != null) (tm[g] ||= []).push(a); }
  for (const p of combine) { const g = GR[p.pos], a = athOf(p, g); if (a != null && +p.season >= FIRST + 1 && +p.season <= 2023) ath[p.season + '|' + nm(p.player_name)] = { ath: a - mean(tm[g]), school: school(p.school) }; }
}

console.error("data loaded", process.uptime().toFixed(1));
// ---- candidate drivers (Oct 24, 2026: --wide --stage=cand) ---------------------------------------------------------
// raw values from what the board knows at the end of season s; each is z'd within its position-season pool and enters
// the composite at CANDW[k] per SD (k, or k|POS for one position), 0 until a fit sets it. avail/availMin: games played
// over team games (this season / worst season in the blend); slope: z change on last season; peak: best season z;
// recent: this season over the earlier blend; nSeasons: seasons above the pool mean; transfer / transUp: changed schools
// / Elo gained; wtGain: roster pounds a year; hsLrk: -ln 247 national rank; hsXprod: pedigree x production; young1:
// production in years 1-2. Result (data/cfb_fv_candidates.json): nothing ships. nSeasons lifts pooled r (t 2.9, 9/10
// classes) but lowers within-position Spearman (.402 -> .384, --eval --candeval=nSeasons=0.12): a scale effect
// Receiving depth (Oct 26, 2026, WR and TE): PFN's lines carry catches, targets, yards, YAC a catch, catch rate and (WR)
// yards per route run. Caught depth (yards a catch - YAC a catch) and catch rate stand in for aDOT, which the public
// play text only spots from 2026: on 337 2026 WRs the proxy 9.5 + .696 caught depth - .076 catch% has r .857 with true
// aDOT (thrown-to and caught-at spots, ESPN). Blended 5/4/3 like production and shrunk to the pool at RECV_K targets.
// adot / cdep: the proxy and caught depth; croe: catch rate over the pool's line on aDOT; yprrD: YPRR over its line on
// aDOT (efficiency at depth); yacoe: YAC a catch over its line on caught depth; aXy / aXc: z(aDOT) x z(YPRR) and
// x z(catch%); tprr: targets a route; ayprr: air yards caught a route; ypt: yards a target
// Result (Oct 26; `--eval --stage=cand` on the 2019-23 classes, and `--eval --recvcheck=WR,TE` against the AV residual
// of today's grade, one class out): nothing ships. aDOT alone: AV held-out t .47 (last seasons -.37), draft capital t 1.1.
// Depth-adjusted efficiency (yprrD) and air yards a route predict draft capital past model FV (t 7.2 and 3.0, 5/5) but
// not NFL AV (t -.04, .15) and vanish once DraftTek's board is blended in: scouts already pay for them. The aDOT x
// efficiency products lose (t -1.6, -.6). TE: no term helps.
const RECV_KEYS = ['adot', 'cdep', 'croe', 'yprrD', 'yacoe', 'aXy', 'aXc', 'tprr', 'ayprr', 'ypt', 'relYpt', 'relYprr', 'relZ'], RECV_K = 40;
// room-relative terms (same harness, Oct 26): relZ, this season's production z over the snap-weighted z of his
// position-group teammates on PFN's list (every position); relYpt / relYprr (WR, TE): yards a target (route) over the
// rest of the team's receivers, which nets out the quarterback and scheme the room shares, shrunk at RECV_K targets.
// Result: fail. relZ lifts draft capital at EDGE and DL last seasons (t 2.4, 3.4) but not AV, nothing under DraftTek, and
// in the FV refit every version loses held out (relZ pooled t -.49, EDGE -.85, DL -1.6; relYprr WR -.42)
// game-level terms (Oct 26, second round; scripts/cfb_game_splits.py -> scripts/.cache/fvrefit/game_splits.json, this
// season's line, blended 5/4/3 with the earlier ones in the production blend): gNfl, production against future-NFL
// units over his average (receivers vs DBs, backs vs the front, QBs vs both, pass rushers' sacks vs the OL); gComp,
// share of yards with the score within 16 over the team's; gTrend, second half of his season over the first
// gNflR: gNfl's pass-rush version with the opponent OL read from 247 recruiting (signed OL, last five classes), which a
// live board knows; gNfl's next-three-drafts capital is hindsight
// Result (`--eval --stage=cand`, 2019-23 classes): gNfl|EDGE passes (t 2.99, 5/5, weight .12-.2, AV and capital both
// +.002-.003 r, drafted r .471 -> .475) but only with the hindsight OL read; gNflR|EDGE, the version a live board can
// compute, fails (t 1.41, 3/5), DL and LB lose. gComp|RB t 2.0 but 3/5 classes; gComp and gTrend fail everywhere else.
// Not shipped. Retest gNfl with our own OL grades as the opponent read once PFN's 2024+ OL lines have NFL seasons
const GAME_KEYS = ['gNfl', 'gComp', 'gTrend', 'gNflR'];
const GSPL = (() => { try { return JSON.parse(fs.readFileSync(path.join(C, 'game_splits.json'), 'utf8')); } catch { return {}; } })();
// big-time throws proxy (Nov 1 2026, scripts/qb_btt_research.py --cfb-fv -> scripts/.cache/fvrefit/btt.json): QB
// completions gaining 25+ yards a dropback from ESPN play text (2015+; ESPN spots air yards only from 2026, so depth is
// yards gained), each season shrunk to the QB mean at BTT_K dropbacks, blended 5/4/3 like production. bttQ|QB
// Result: FAILED. bttQ|QB fold t -2.45 (1/10 classes), bttV|QB (a team game) t -1.88 (0/10), pooled bttQ = bttQ|QB;
// Spearman .429 -> .428, top 32 AV -.032, forward weight 0. Retest with true air-yard BTT once 2026 spots have NFL years.
const BTT = (() => { try { return JSON.parse(fs.readFileSync(path.join(C, 'btt.json'), 'utf8')); } catch { return {}; } })(), BTT_K = 150;
const BTT_M = (() => { let a = 0, n = 0; for (const v of Object.values(BTT)) { a += v.btt; n += v.db; } return n ? a / n : 0; })();
const GUNIT = { QB: 'qb', RB: 'scr', WR: 'rec', TE: 'rec', EDGE: 'sk', DL: 'sk', LB: 'sk' };
// evaluator and special-teams terms (Oct 31 2026 sweep; scripts/cfb_fv_extras.py -> scripts/.cache/fvrefit/extras.json,
// joined through scripts/names.mjs on name + team, crossTeam none). Honors are announced in early December, after the
// regular season the board grades, so a live board could read season-s honors only from then on.
//   acf / acfB / acfMax  postseason all-conference level this season (1st team 3, 2nd 2, 3rd or HM 1, 0 unhonored;
//                        null when his conference-season has no parsed page), blended 5/4/3 like production, best so far
//   aaB                  All-America selectors (blend), for reference (failed Oct 14 as a source)
//   ret / retTD / isRet  kick + punt return yards a team game, return TDs, 10+ returns (blend; ESPN boxes, all FBS games)
//   krAvg / prAvg        yards a kick (punt) return over his blend, shrunk at 8 returns to 21 (8.5)
//   dPd / dFF / dInt     ESPN season defense: passes defended (2016+), forced fumbles, INT a game (blend)
// Result (`--wide --stage=cand --gates`, 10 classes 2014-23): nothing ships. acf passes the fold rule (t 3.56, 8/10, AV
// r +.011 / +.014, forward +.014 / +.016, Spearman .429 -> .437) but lowers the top 32 a class (AV -.15, t -2.3, 3/10;
// forward 3.51 -> 3.30): it lifts honored fourth-year players over unhonored younger, higher-pedigree ones (--eval
// --swaps --candeval=acf=.12). Every honors variant does the same (acfB, acfMax, acfR, acf0, acfY4) or loses the fold
// rule. acfY|QB (all-conference in years 1-3, QBs) t 3.29 9/10, top 32 AV +.028 but capital -.018 (3/10): fails; retest
// when the 2024 class adds a fold. Returns (ret, retTD, isRet, krAvg, prAvg, pooled and RB/WR) and ESPN defense
// (dPd, dFF, dInt) are noise (|t| < 1.3, dFF -2.3)
const X_KEYS = ['acf', 'acfB', 'acfMax', 'acfR', 'acfY', 'acfY2', 'acfY4', 'acfYc', 'acf1Y', 'acf0', 'aaB', 'ret', 'retTD', 'isRet', 'krAvg', 'prAvg', 'dPd', 'dFF', 'dInt'];
const XM = {}, XC = new Map();
{
  let X = {}; try { X = JSON.parse(fs.readFileSync(path.join(C, 'extras.json'), 'utf8')); } catch { /* no extras: the X terms stay null */ }
  for (const [S, d] of Object.entries(X)) XM[S] = { ret: new Matcher(d.ret, { pos: null }), def: new Matcher(d.def), conf: new Matcher(d.conf, { pos: null }), aa: new Matcher(d.aa, { pos: null }),
    pages: new Set(d.pages), confOf: new Map(Object.entries(d.teamConf).map(([t, c]) => [teamKey(t), c])) };
}
const DPOS = { EDGE: 'DE', DL: 'DT', LB: 'LB' };
function xfind(kind, S, row) {
  const X = XM[S]; if (!X) return undefined;
  const ck = kind + '|' + S + '|' + row.id + '|' + row.name; if (XC.has(ck)) return XC.get(ck);
  const [hit] = X[kind].find(row.name, { team: row.team, pos: kind === 'def' ? DPOS[row._g] ?? null : null, crossTeam: 'none' });
  XC.set(ck, hit); return hit;
}
function xRaw(o, hist, tgOf) {
  const bl = f => { let a = 0, w = 0; for (const h of hist) { const v = f(h); if (v != null && isFinite(v)) { a += CUR.W[h.k] * v; w += CUR.W[h.k]; } } return w ? a / w : null; };
  const acfOf = h => { const X = XM[h.s]; if (!X) return null; const c = X.confOf.get(teamKey(h.row.team)); if (!c || !X.pages.has(c)) return null; return xfind('conf', h.s, h.row)?.lv ?? 0; };
  o.acf = hist[0]?.k === 0 ? acfOf(hist[0]) : null;
  o.acfB = bl(acfOf);
  const am = hist.map(acfOf).filter(v => v != null); o.acfMax = am.length ? Math.max(...am) : null;
  o.aaB = bl(h => XM[h.s] ? xfind('aa', h.s, h.row)?.n ?? 0 : null);
  const rt = h => XM[h.s] ? xfind('ret', h.s, h.row) ?? { kr: 0, kry: 0, krt: 0, pr: 0, pry: 0, prt: 0 } : null;
  o.ret = bl(h => { const x = rt(h); return x ? (x.kry + x.pry) / (tgOf(h) || 12) : null; });
  o.retTD = bl(h => { const x = rt(h); return x ? x.krt + x.prt : null; });
  o.isRet = bl(h => { const x = rt(h); return x ? +(x.kr + x.pr >= 10) : null; });
  let kr = 0, kry = 0, pr = 0, pry = 0, any = false;
  for (const h of hist) { const x = rt(h); if (!x) continue; any = true; const f = CUR.W[h.k] / CUR.W[0]; kr += f * x.kr; kry += f * x.kry; pr += f * x.pr; pry += f * x.pry; }
  o.krAvg = any && kr > 0 ? (kry + 8 * 21) / (kr + 8) : null;
  o.prAvg = any && pr > 0 ? (pry + 8 * 8.5) / (pr + 8) : null;
  const df = (h, k) => { if (!DPOS[h.row._g] || !XM[h.s]) return null; const x = xfind('def', h.s, h.row); if (!x) return null; const g = x.gamesPlayed || tgOf(h) || 12; return x[k] != null ? x[k] / g : null; };
  o.dPd = bl(h => h.s >= 2016 ? df(h, 'passesDefended') : null); o.dFF = bl(h => df(h, 'fumblesForced')); o.dInt = bl(h => df(h, 'interceptions'));
}
// Nov 1 2026 sweep (FV proxy drivers; /mnt/project-files/fv/sweep-nov01/cfb.md):
//   sdS / sdC / sdP / sdH  rolling development effect (scripts/cfb_fv_schooldev.py -> scripts/.cache/fvrefit/schooldev.json):
//                          draft capital over the recruiting rating's expectation, classes <= s - 5 only, shrunk; of the
//                          signing school, the current school, the current school's position group, the current head coach
//   blk / blkS / blkLow    blocked by talent: same-group teammates this season with more snaps who were 4-star+ 247
//                          recruits (count), their summed pedigree z above 0, and blk only when his production is below
//                          the pool mean (low output behind talent is less damning)
//   dShare / dShareY       snap share (snaps / 68 team-game plays) change on last season; dShareY its residual on years
//   ppa / ppaPD / use / usePD / dUse  CFBD player PPA a play (all, passing downs; shrunk at 40 plays) and usage share
//                          (overall, passing downs), blended 5/4/3, and usage change on last season (cfb-game-research
//                          artifact, scripts/.cache/cfb/hist/{ppaplayers,usage}<S>.json, 2015-25; QB, RB, WR, TE)
// Result (`--wide --stage=cand --gates`, 10 classes): nothing ships. Pooled, all 14 fail the fold rule (best sdH t 1.33
// 8/10, usePD .98; dShare -1.71, ppaPD -1.63). By position (55 tests) only sdS|TE (t 2.27, 8/10) and usePD|QB (t 2.14,
// 6/10) clear t 2, both at the grid edge .2, both lower the top 32 (AV -.038 / -.024) and the forward top 32 (3.51 ->
// 3.49): chance level for ~70 tests. dUse and dShare are negative nearly everywhere (share gains read as late bloomers)
const N1_KEYS = ['sdS', 'sdC', 'sdP', 'sdH', 'blk', 'blkS', 'blkLow', 'dShare', 'dShareY', 'ppa', 'ppaPD', 'use', 'usePD', 'dUse'];
const SDV = (() => { try { return JSON.parse(fs.readFileSync(path.join(C, 'schooldev.json'), 'utf8')); } catch { return null; } })();
const CFBD = {};
for (let S = 2015; S <= 2022; S++) {
  const H = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist'), rd = f => { try { return JSON.parse(fs.readFileSync(path.join(H, f), 'utf8')); } catch { return null; } };
  const pp = rd(`ppaplayers${S}.json`), us = rd(`usage${S}.json`); if (!pp || !us) continue;
  const U = new Map(us.map(x => [x.id, x.usage])), R = pp.map(x => ({ ...x, usage: U.get(x.id) || null }));
  CFBD[S] = new Matcher(R, { pos: 'position' });
}
const CFBD_POS = { QB: 'QB', RB: 'RB', WR: 'WR', TE: 'TE' };
const cfbdOf = h => { const M = CFBD[h.s]; if (!M || !CFBD_POS[h.row._g]) return undefined; const ck = 'cfbd|' + h.s + '|' + h.row.id; if (XC.has(ck)) return XC.get(ck);
  const [hit] = M.find(h.row.name, { team: h.row.team, pos: CFBD_POS[h.row._g], crossTeam: 'none' }); XC.set(ck, hit || null); return hit || null; };
const CAND_KEYS = ['bttQ', 'bttV', 'avail', 'availMin', 'slope', 'peak', 'recent', 'nSeasons', 'transfer', 'transUp', 'wtGain', 'hsLrk', 'hsXprod', 'young1', ...RECV_KEYS, ...GAME_KEYS, ...X_KEYS, ...N1_KEYS];
let CANDW = {}, REC_TERMS = false;
function candTerm(p, g) {
  let t = 0;
  for (const [k, w] of Object.entries(CANDW)) { const [c, gg] = k.split('|'); if (gg && gg !== g) continue; t += w * (p.cf?.[c] ?? 0); }
  return t;
}
function candRaw(r, by, hist, rc, rl, n, sch, s, h0, tg) {
  const o = {};
  const share = x => { const g = num(x.gp) ?? num(x.gamesQ); const t = games[x.season]?.[school(x.team)]; return g != null && t ? Math.min(1, g / t) : null; };
  o.avail = share(r);
  const sh = hist.map(h => share(h.row)).filter(x => x != null); o.availMin = sh.length ? Math.min(...sh) : null;
  const z = Object.values(by).filter(x => x.season <= s && x.season >= h0 && x._v >= 100).sort((a, b) => a.season - b.season);
  o.slope = z.length >= 2 && z.at(-1).season === s ? z.at(-1)._z - z.at(-2)._z : null;
  o.peak = z.length ? Math.max(...z.map(x => x._z)) : null;
  o.recent = hist.length >= 2 ? r._z - hist.slice(1).reduce((a, h) => a + h.w * h.z, 0) / hist.slice(1).reduce((a, h) => a + h.w, 0) : null;
  o.nSeasons = z.filter(x => x._z > 0).length;
  const schs = hist.map(h => h.sch); o.transfer = new Set(schs).size > 1 ? 1 : 0;
  const old = hist.find(h => h.sch !== sch); o.transUp = old ? (elo[s][sch] ?? 0) - (elo[old.s]?.[old.sch] ?? 0) : 0;
  const k0 = [3, 2, 1].find(k => (ros[(s - k) + '|' + n] || []).some(x => x.wt)), w0 = k0 && ros[(s - k0) + '|' + n].find(x => x.wt);
  o.wtGain = rl?.wt && w0 ? (rl.wt - w0.wt) / k0 : null;     // pounds a year since his earliest roster weight (up to 3 back)
  o.hsLrk = rc?.rank ? -Math.log(rc.rank) : -Math.log(4000);
  o.hsXprod = (rc ? (rc.rating - 0.86) / 0.04 : -1.5) * r._z;
  o.young1 = rc && s - rc.y + 1 <= 2 ? r._z : 0;
  // receiving sums for the depth terms (finished in the pool loop, which shrinks them to the pool)
  let tar = 0, rec = 0, yds = 0, yac = 0, rt = 0, tr = 0;
  for (const h of hist) {
    const x = h.row, t = num(x.tar), c = num(x.rec), y = num(x.recYds), ya = num(x.yac), f = CUR.W[h.k] / CUR.W[0];
    if (!t || !c || y == null || ya == null) continue;
    tar += f * t; rec += f * c; yds += f * y; yac += f * c * ya;
    const yp = num(x.ypr); if (yp > 0) { rt += f * y / yp; tr += f * t; }
  }
  o._recv = tar >= 10 && rec >= 5 ? { tar, rec, yds, yac, rt, tr } : null;
  const gl = h => GSPL[h.s + '|' + nm(h.row.name) + '|' + school(h.row.team)], u = GUNIT[r._g];
  for (const [k, f] of [['gNfl', x => x['nfl_' + u]], ['gComp', x => r._g === 'EDGE' || r._g === 'DL' || r._g === 'LB' ? null : x.comp], ['gTrend', x => x['trend_' + u]], ['gNflR', x => u === 'sk' ? x.rec_sk : null]]) {
    let a = 0, w = 0; for (const h of hist) { const x = gl(h), v = x ? f(x) : null; if (v != null && isFinite(v)) { a += CUR.W[h.k] * v; w += CUR.W[h.k]; } }
    o[k] = w ? a / w : null;
  }
  { let a = 0, w = 0, v = 0, wv = 0; for (const h of hist) { const x = r._g === 'QB' ? BTT[h.s + '|' + nm(h.row.name) + '|' + school(h.row.team)] : null; if (!x) continue;
      a += CUR.W[h.k] * (x.btt + BTT_K * BTT_M) / (x.db + BTT_K); w += CUR.W[h.k]; const tg = games[h.s]?.[h.sch]; if (tg) { v += CUR.W[h.k] * x.btt / tg; wv += CUR.W[h.k]; } }
    o.bttQ = w ? a / w : null; o.bttV = wv ? v / wv : null; }
  xRaw(o, hist, h => games[h.s]?.[h.sch]);
  // Nov 1 2026 terms (see N1_KEYS)
  const sd = SDV && (k => SDV[k]?.[s]);
  o.sdS = sd && rc?.sraw ? sd('school')?.[teamKey(rc.sraw)] ?? null : null;
  o.sdC = sd ? sd('school')?.[teamKey(r.team)] ?? null : null;
  o.sdP = sd ? sd('pos')?.[teamKey(r.team) + '|' + r._g] ?? null : null;
  { const co = SDV?.hc?.[s]?.[teamKey(r.team)]; o.sdH = sd && co ? sd('coach')?.[co] ?? null : null; }
  const shr = (x, ss) => { const t = games[ss]?.[school(x.team)]; return x._v != null && t ? Math.min(1, x._v / (68 * t)) : null; };
  const prev = by[s - 1] && s - 1 >= h0 ? by[s - 1] : null;
  o.dShare = prev ? (shr(r, s) ?? NaN) - (shr(prev, s - 1) ?? NaN) : null; if (!isFinite(o.dShare)) o.dShare = null;
  const cb = f => { let a = 0, w = 0; for (const h of hist) { const x = cfbdOf(h); const v = x ? f(x) : null; if (v != null && isFinite(v)) { a += CUR.W[h.k] * v; w += CUR.W[h.k]; } } return w ? a / w : null; };
  const pl = (x, k) => x.averagePPA?.[k] ? x.totalPPA[k] / x.averagePPA[k] : 0;
  o.ppa = cb(x => x.totalPPA?.all != null ? x.totalPPA.all / (pl(x, 'all') + 40) : null);
  o.ppaPD = cb(x => x.totalPPA?.passingDowns != null ? x.totalPPA.passingDowns / (pl(x, 'passingDowns') + 40) : null);
  o.use = cb(x => x.usage?.overall ?? null); o.usePD = cb(x => x.usage?.passingDowns ?? null);
  { const a = hist[0]?.k === 0 ? cfbdOf(hist[0]) : null, b = hist.find(h => h.k === 1), bb = b ? cfbdOf(b) : null;
    o.dUse = a?.usage?.overall != null && bb?.usage?.overall != null ? a.usage.overall - bb.usage.overall : null; }
  return o;
}
// the receiving depth terms on one position-season pool: rates shrunk to the pool's target-weighted mean at RECV_K
function recvTerms(P) {
  const X = P.filter(p => p.cr._recv), rate = (a, f, n) => { const v = X.filter(p => n(p.cr._recv) > 0); const m = v.reduce((s, p) => s + n(p.cr._recv) * f(p.cr._recv), 0) / Math.max(1e-9, v.reduce((s, p) => s + n(p.cr._recv), 0));
    for (const p of v) { const N = n(p.cr._recv); p._rv[a] = (N * f(p.cr._recv) + RECV_K * m) / (N + RECV_K); } };
  for (const p of X) p._rv = {};
  rate('cdep', d => (d.yds - d.yac) / d.rec, d => d.rec);
  rate('catch', d => 100 * d.rec / d.tar, d => d.tar);
  rate('yac', d => d.yac / d.rec, d => d.rec);
  rate('ypt', d => d.yds / d.tar, d => d.tar);
  rate('yprr', d => d.yds / d.rt, d => d.rt ? d.tr : 0);
  rate('tprr', d => d.tr / d.rt, d => d.rt ? d.tr : 0);
  rate('ayprr', d => (d.yds - d.yac) * (d.tr / d.tar) / d.rt, d => d.rt ? d.tr : 0);
  for (const p of X) { const v = p._rv; if (v.cdep != null && v.catch != null) v.adot = 9.5 + 0.696 * v.cdep - 0.076 * v.catch; }
  // a target-weighted line of y on x across the pool; the residual is the over-expected rate
  const resid = (y, x) => { const v = X.filter(p => p._rv[y] != null && p._rv[x] != null), w = v.map(p => p.cr._recv.tar), W = w.reduce((a, b) => a + b, 0);
    if (v.length < 20) return new Map(); const mx = v.reduce((a, p, i) => a + w[i] * p._rv[x], 0) / W, my = v.reduce((a, p, i) => a + w[i] * p._rv[y], 0) / W;
    const b = v.reduce((a, p, i) => a + w[i] * (p._rv[x] - mx) * (p._rv[y] - my), 0) / v.reduce((a, p, i) => a + w[i] * (p._rv[x] - mx) ** 2, 0);
    return new Map(v.map(p => [p, p._rv[y] - my - b * (p._rv[x] - mx)])); };
  const zs = k => { const v = X.filter(p => p._rv[k] != null).map(p => p._rv[k]), m = mean(v), sd = sdv(v); return p => p._rv?.[k] != null ? (p._rv[k] - m) / sd : null; };
  const cr = resid('catch', 'adot'), yd = resid('yprr', 'adot'), ya = resid('yac', 'cdep'), za = zs('adot'), zy = zs('yprr'), zc = zs('catch');
  for (const p of P) {
    const v = p._rv || {}, o = p.cr;
    o.adot = v.adot ?? null; o.cdep = v.cdep ?? null; o.ypt = v.ypt ?? null; o.tprr = v.tprr ?? null; o.ayprr = v.ayprr ?? null;
    o.croe = cr.get(p) ?? null; o.yprrD = yd.get(p) ?? null; o.yacoe = ya.get(p) ?? null;
    o.aXy = za(p) != null && zy(p) != null ? za(p) * zy(p) : null; o.aXc = za(p) != null && zc(p) != null ? za(p) * zc(p) : null;
  }
}
function roomTerms(P, g) {
  const T = {}; for (const p of P) (T[school(p.row.team)] ||= []).push(p);
  for (const p of P) {
    const mates = T[school(p.row.team)].filter(q => q !== p && q.row._v > 0), r = p.row;
    const vw = mates.reduce((a, q) => a + q.row._v, 0);
    p.cr.relZ = vw && r._v >= 100 ? r._z - mates.reduce((a, q) => a + q.row._v * q.row._z, 0) / vw : null;
    p.cr.relYpt = p.cr.relYprr = null;
    if (g !== 'WR' && g !== 'TE') continue;
    const t = num(r.tar), y = num(r.recYds); if (!t || y == null) continue;
    const mt = mates.reduce((a, q) => a + (num(q.row.tar) || 0), 0), my = mates.reduce((a, q) => a + (num(q.row.tar) ? num(q.row.recYds) || 0 : 0), 0);
    if (mt >= 20) p.cr.relYpt = (y / t - my / mt) * t / (t + RECV_K);
    const rt = num(r.ypr) > 0 ? y / r.ypr : null, mr = mates.reduce((a, q) => a + (num(q.row.ypr) > 0 && num(q.row.recYds) ? q.row.recYds / q.row.ypr : 0), 0);
    const mry = mates.reduce((a, q) => a + (num(q.row.ypr) > 0 && num(q.row.recYds) ? q.row.recYds : 0), 0);
    if (rt && mr >= 100) p.cr.relYprr = (y / rt - mry / mr) * t / (t + RECV_K);
  }
}
// ---- the board, season by season ------------------------------------------------------------------------------
// every row gets its raw driver values; terms() turns them into composite terms under a set of multipliers
const rows = [];        // one per PFN line 2019-22 (the pools); .final marks a player's last PFN season
const PFN_RAW = {};     // every PFN line, both divisions (--past matches this season's board through it)
async function pfnLines(g) {
  const f = path.join(SP, `pfn_${g}.json`);
  if (!fs.existsSync(f)) {      // as scripts/cfb_statplus_backtest.mjs caches it
    fs.mkdirSync(SP, { recursive: true });
    const html = await (await fetch(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${PFN_SLUG[g]}`, { headers: { 'user-agent': 'Mozilla/5.0' } })).text();
    const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).find(c => c.includes('"packed":'));
    const i = s.indexOf('"packed":') + 9; let d = 0, q = false, k = i;
    for (; k < s.length; k++) { const c = s[k]; if (q) { if (c === '\\') k++; else if (c === '"') q = false; continue; } if (c === '"') q = true; else if (c === '{' || c === '[') d++; else if (c === '}' || c === ']') { d--; if (!d) break; } }
    const packed = JSON.parse(s.slice(i, k + 1));
    fs.writeFileSync(f, JSON.stringify(packed.rows.map(r => Object.fromEntries(packed.cols.map((c, j) => [c, r[j]])))));
  }
  return JSON.parse(fs.readFileSync(f));
}
// box-score stand-ins: --wide puts them under PFN for 2012-18 (linked to a player's PFN id when PFN lists him in
// 2019-22), --boxonly in place of PFN for 2019-22 (each line under its ESPN id)
const BOXL = BOX ? JSON.parse(fs.readFileSync(path.join(C, 'box_lines.json'), 'utf8')) : null;
for (const g of GP) {
  PFN_RAW[g] = await pfnLines(g);
  if (WIDE) PFN_RAW[g] = [...BOXL[g].filter(r => r.season < 2019), ...PFN_RAW[g]];
  if (BOXONLY) PFN_RAW[g] = BOXL[g].filter(r => r.season >= 2019).map(r => ({ ...r, id: r.eid }));
  const all = PFN_RAW[g].filter(r => r.division === 'FBS'), cz = {};
  for (const r of all) (cz[r.season] ||= []).push(r.score);
  for (const s of Object.keys(cz)) cz[s] = [mean(cz[s]), sdv(cz[s])];
  const snaps = r => num(r.snapsQ) ?? num(r.snaps) ?? ((num(r.gp) ?? num(r.gamesQ) ?? 0) * SPG[g]);
  for (const r of all) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = snaps(r); r._g = g; }
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
  for (const s of ROW_SEASONS) {
    const pool = all.filter(r => r.season === s), P = [];
    for (const r of pool) {
      const by = byId[r.id], n = nm(r.name), sch = school(r.team);
      let a = 0, d = 0; const hist = [];
      // --wide: a PFN-era row blends PFN seasons only, as the live board does (box seasons would dilute them)
      const h0 = s >= 2019 ? 2019 : HIST0;
      for (let k = 0; k <= 2; k++) { const x = s - k >= h0 && by[s - k]; if (x) { a += CUR.W[k] * x._v * x._z; d += CUR.W[k] * x._v; hist.push({ w: CUR.W[k] * x._v, z: x._z, row: x, k, s: s - k, sch: school(x.team) }); } }
      // recruiting: a 247 record by name, class 2014 to this season, the school's if there are several
      const cands = (rec[n] || []).filter(x => x.y <= s && x.y >= s - 6), rc = cands.find(x => x.school === sch) || (cands.length === 1 ? cands[0] : null);
      const rl = (ros[s + '|' + n] || []).find(x => x.team === sch) || (ros[s + '|' + n] || [])[0] || null;
      const years = rc ? s - rc.y + 1 : rl && rl.year >= 1 && rl.year <= 5 ? rl.year + 0.5 : 4;
      const brk = Object.values(by).filter(x => x.season <= s && x.season >= h0 && x._z >= 1.04 && x._v >= 150).map(x => x.season).sort()[0];
      const visible = rc && rc.y >= h0;            // PFN starts in 2019: a breakout year is only known from a 2019+ class
      const last = Math.max(...Object.keys(by).map(Number));
      const tg = games[s][sch] || 12, side = 68 * tg;
      P.push({
        g, s, id: r.id, name: r.name, final: last === s, last, lastRow: by[last], row: r, marcel: a / (d + CUR.K), hist, snapsN: r._v,
        share: g === 'RB' && num(r.share) != null ? Math.min(1, r.share / 100) : r._v ? Math.min(1, r._v / side) : null,
        rating: rc?.rating ?? null, stars: rc?.stars ?? 0, walkOn: !rc, years, ht: rl?.ht ?? null, wt: rl?.wt ?? null,
        team: elo[s][sch] ?? null, sos: num(r.sos), breakYear: visible && brk ? brk - rc.y + 1 : null, breakKnown: !!visible,
        badge: Object.fromEntries(Object.keys(bz).map(k => [k, bz[k].get(r) ?? null])),
        cr: candRaw(r, by, hist, rc, rl, n, sch, s, h0, tg),
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
    if (g === 'WR' || g === 'TE') recvTerms(P);
    roomTerms(P, g);
    // honors beyond what the board already reads: acf's residual on production, years and pedigree within the pool
    // (acfR); acf for players in their first three years only (acfY)
    {
      const H = P.filter(p => p.cr.acf != null), X = H.map(p => [1, p.zPfn, p.years, p.hsRaw]), y = H.map(p => p.cr.acf);
      let b = null;
      if (H.length > 30) { const k = 4, A = Array.from({ length: k }, () => Array(k + 1).fill(0)); X.forEach((x, n) => { for (let i = 0; i < k; i++) { A[i][k] += x[i] * y[n]; for (let j = 0; j < k; j++) A[i][j] += x[i] * x[j] + (i === j ? 1e-6 : 0); } });
        for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) if (j !== i) { const f = A[j][i] / A[i][i]; for (let c = 0; c <= k; c++) A[j][c] -= f * A[i][c]; } b = A.map((r, i) => r[k] / r[i]); }
      for (const p of P) { p.cr.acfR = b && p.cr.acf != null ? p.cr.acf - [1, p.zPfn, p.years, p.hsRaw].reduce((a, v, i) => a + v * b[i], 0) : null; p.cr.acfY = p.cr.acf != null ? (p.years <= 3 ? p.cr.acf : 0) : null;
        p.cr.acfY2 = p.cr.acf != null ? (p.years <= 2 ? p.cr.acf : 0) : null; p.cr.acfY4 = p.cr.acf != null ? (p.years <= 4 ? p.cr.acf : 0) : null;
        p.cr.acfYc = p.cr.acf != null ? p.cr.acf * Math.min(1, Math.max(0, (4.5 - p.years) / 2)) : null; p.cr.acf1Y = p.cr.acf != null ? +(p.years <= 3 && p.cr.acf === 3) : null; p.cr.acf0 = p.cr.acf ?? 0; }
    }
    // Nov 1 2026: blocked by talent (same-group teammates ahead of him on snaps, 4-star+ recruits), dShare net of years
    {
      const T = {}; for (const p of P) (T[school(p.row.team)] ||= []).push(p);
      for (const p of P) {
        const ahead = T[school(p.row.team)].filter(q => q !== p && q.snapsN > p.snapsN);
        p.cr.blk = ahead.filter(q => q.rating != null && q.rating >= 0.8900).length;
        p.cr.blkS = ahead.reduce((a, q) => a + Math.max(0, q.hsRaw), 0);
        p.cr.blkLow = p.zPfn < 0 ? p.cr.blk : 0;
      }
      const D = P.filter(p => p.cr.dShare != null), my = mean(D.map(p => p.cr.dShare)), mx = mean(D.map(p => p.years));
      const b = D.reduce((a, p) => a + (p.years - mx) * (p.cr.dShare - my), 0) / Math.max(1e-9, D.reduce((a, p) => a + (p.years - mx) ** 2, 0));
      for (const p of P) p.cr.dShareY = p.cr.dShare != null ? p.cr.dShare - my - b * (p.years - mx) : null;
    }
    // candidate drivers (--stage=cand): z within the pool, missing at the pool mean
    for (const k of CAND_KEYS) {
      const v = P.map(p => p.cr[k]).filter(x => x != null && isFinite(x)), cm = mean(v), cs = sdv(v);
      for (const p of P) (p.cf ||= {})[k] = p.cr[k] != null && isFinite(p.cr[k]) && v.length > 20 ? clamp((p.cr[k] - cm) / cs, 3) : 0;
    }
    rows.push(...P);
  }
}
// outcomes: the draft right after a player's last PFN season, for every row whose player had left college by 2023
// (finals: the last-season rows 2019-22, the main universe; earlier rows feed the earlier-vantage check)
const finals = [], early = [];
const NT = process.argv.includes('--target') ? JSON.parse(fs.readFileSync(path.join(C, 'nfl_targets.json'), 'utf8')) : null;
if (PAST) for (const p of rows) Object.assign(p, { av: 0, ath: null, dt: null });     // graded, never scored
for (const p of PAST ? [] : rows) {
  if (p.last > 2023) continue;
  const D = p.last + 1, n = nm(p.name), tm = school(p.lastRow.team), cand = picks.filter(x => nm(x.pfr_player_name) === n && NFLPOS[p.g].includes(x.position));
  let pk = cand.find(x => +x.season === D && school(x.college) === tm) || cand.find(x => +x.season === D);
  if (!pk && cand.some(x => +x.season > D)) continue;
  // no exact name: the one draftee that year with his last name, position group and school
  if (!pk) { const c = picks.filter(x => +x.season === D && lastName(x.pfr_player_name) === lastName(p.name) && NFLPOS[p.g].includes(x.position) && school(x.college) === tm); if (c.length === 1) pk = c[0]; }
  p.av = pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0;
  p.cap = pk ? capital(+pk.pick) : 0;
  p.pick = pk ? +pk.pick : null; p.pfr = pk?.pfr_player_id || null;
  // --target outcomes (scripts/cfb_fv_target.py): NFL WAR a season since the draft (seasons from 2016) and the second
  // contract's cap % (drafts through 2018; later classes null), undrafted 0
  if (NT) { const t = pk && NT[p.pfr], y0 = Math.max(D, 2016);
    p.war = t ? Object.entries(t.seasons).reduce((a, [y, v]) => a + (+y >= y0 ? v[1] : 0), 0) / (NFL_THROUGH - y0 + 1) : 0;
    p.apy = D <= 2018 ? (t ? t.apy * 100 : 0) : null; }
  p.ap = pk ? +pk.allpro || 0 : 0; p.pb = pk ? +pk.probowls || 0 : 0;
  p.ath = null; p.dt = null;
  if (p.final) {
    const a = ath[D + '|' + n]; p.ath = a && (a.school === tm || pk) && !INSEASON ? a.ath : null;
    const B = INSEASON ? pffIn : board;
    p.dt = B[D]?.[n + '|' + famOf(p.g)] ?? B[D]?.['last|' + lastName(p.name) + '|' + tm + '|' + famOf(p.g)] ?? null;
    finals.push(p);
  } else if (p.s <= 2021) early.push(p);
}
console.log('rows', rows.length, 'finals', finals.length, 'drafted', finals.filter(p => p.pick).length, '247 matched', r3(mean(finals.map(p => +!p.walkOn))),
  'roster ht', r3(mean(finals.map(p => +!!p.ht))), 'elo', r3(mean(finals.map(p => +(p.team != null)))), 'board', finals.filter(p => p.dt).length, 'ath', finals.filter(p => p.ath != null).length);
if (process.argv.includes('--xcov')) for (const k of [...X_KEYS, ...N1_KEYS]) {
  // coverage and a raw read of the extras terms on last seasons: share carried, share nonzero, drafted rate and AV by value
  const S = finals.filter(p => p.cr[k] != null), nz = S.filter(p => p.cr[k] > 0);
  console.log('xcov', k.padEnd(7), 'carried', r3(S.length / finals.length), 'nonzero', r3(nz.length / Math.max(1, S.length)), 'drafted nz/z', r3(mean(nz.map(p => +!!p.pick))), r3(mean(S.filter(p => !(p.cr[k] > 0)).map(p => +!!p.pick))),
    'AV nz/z', r3(mean(nz.map(p => p.av))), r3(mean(S.filter(p => !(p.cr[k] > 0)).map(p => p.av))), 'byPos carried', JSON.stringify(Object.fromEntries(G7.map(g => [g, r3(finals.filter(p => p.g === g && p.cr[k] != null).length / finals.filter(p => p.g === g).length)]))));
}

// ---- grading under a set of multipliers ---------------------------------------------------------------------
// M: multiplier per driver (1 = today). prod_<g> scales FV_PROD_POS, the rest scale one constant each
const KEYS = ['prod_QB', 'prod_RB', 'prod_WR', 'prod_TE', 'prod_EDGE', 'prod_DL', 'prod_LB', 'nonBlue', 'hs', 'team', 'age', 'ageY', 'ageO', 'cls', 'snap', 'sos', 'brk',
  'b_QB_accurate', 'b_QB_deep', 'b_RB_catcher', 'b_TE_catcher', 'b_DL_runstop', 'b_LB_tackler', 'ath', 'athCap', 'frame', 'years', ...(WIDE ? ['prodBox', 'hsBox'] : [])];
const ONE = Object.fromEntries(KEYS.map(k => [k, 1]));
// these change the FV scale's absolute level, not just the order within a position, so they can't be pinned by
// re-normalizing: frame and years are FV points after the scarcity grade
// prodBox, hsBox (--wide): production's and pedigree's weights in the 2014-18 seasons, on box-score stand-ins, relative
// to the PFN seasons. Nuisances every fit gets, so the other drivers aren't asked to make up for a noisier production
// read, and pedigree (which stands in for production when production is noisy) is fit on PFN seasons. Never shipped
const PROD = G7.map(g => 'prod_' + g), FVPTS = new Set(['frame', 'years', 'prodBox', 'hsBox']);
// the composite is standardized within each position, so scaling every composite term by one factor changes nothing:
// composite multipliers count relative to the mean production multiplier (frame and years are FV points, not scaled)
function effective(M) { const s = mean(PROD.map(k => M[k])); return Object.fromEntries(KEYS.map(k => [k, FVPTS.has(k) ? M[k] : M[k] / s])); }
// posM: per-position overrides on top of M0; only: grade one position
function grade(M0, set = rows, posM = null, only = null) {
  const out = new Map(), M1 = effective(M0);
  for (const g of GP) for (const s of ROW_SEASONS) {
    if (only && g !== only) continue;
    const M = posM?.[g] ? effective({ ...M0, ...posM[g] }) : M1;
    const P = (set === rows ? POOLS[g + s] : set.filter(p => p.g === g && p.s === s)) || [];
    if (!P.length) continue;      // OL, CB and S before PFN graded them (2024)
    const am = CUR.agePos[g] ?? 1, brkM = CUR.brkPos[g] ?? 1;
    for (const p of P) {
      const ageEst = 17.9 + p.years, d = CUR.age.pivot - ageEst;
      const gate = Math.min(1, Math.max(0, (Math.max(p.zPfn, -0.6) + 1) / 2.5));
      const a = (d * CUR.age.perYear + (d > 0 ? 0 : CUR.age.curve) * d * Math.abs(d)) * am;
      // the board's youth rarity (data/cfb.json youthRarity: RB, WR x1.4) on the young-side age and first-year terms,
      // scored with --ship=...,rare=1 (FV audit, Oct 26 2026); 0 = without it, as every refit before had it
      const rr = (BOARD.youthRarity?.[g] ?? 1) ** (M0.rare ?? 0);
      const ageZ = a > 0 ? M.ageY * Math.min(a * rr, CUR.age.capYoung * am) * gate : M.ageO * Math.max(a, -CUR.age.capOld * am);
      const runway = Math.max(0, Math.min(4, 5 - p.years));
      let cls = CUR.cls.perYear * (runway - 2.5) * (runway > 2.5 ? gate : 1);
      if (p.years <= 1.5 && (p.snapsN >= 150 || p.zPfn >= 0.3)) cls += CUR.cls.fr * rr;
      const blue = p.stars >= 4, prodEff = p.zPfn * (blue || p.zPfn < 0 ? 1 : 1 - (1 - CUR.nonBlue) * M.nonBlue);
      const brk = p.breakYear == null ? (p.breakKnown && p.years >= 4 ? -0.05 * brkM : 0) : (CUR.brk[Math.max(1, Math.min(p.breakYear, 4)) - 1] ?? 0) * brkM;
      let badge = 0; for (const [k, w] of Object.entries(CUR.badge[g] || {})) if (p.badge[k] != null) badge += w * M[`b_${g}_${k}`] * p.badge[k];
      badge = clamp(badge, CUR.badgeCap);
      const athT = p.ath != null ? clamp(CUR.ath * M.ath * p.ath, CUR.athCap * (M.athCap ?? 1)) : 0;
      p._comp = CUR.pfn * (CUR.prodPos[g] ?? 1) * (M['prod_' + g] ?? 1) * (s < 2019 ? M.prodBox ?? 1 : 1) * prodEff
        + M.hs * (s < 2019 ? M.hsBox ?? 1 : 1) * clamp(CUR.hs.w * p.hsRaw, CUR.hs.cap)
        + M.team * clamp(CUR.team * (p.team ?? 0), CUR.teamCap)
        + M.age * ageZ + M.cls * cls
        + M.snap * clamp(CUR.snap.w * p.shareZ, CUR.snap.cap)
        + (g === 'QB' ? M.sos * clamp(CUR.sos.perSd * p.sosZ, CUR.sos.cap) : 0)
        + M.brk * brk + badge + athT + candTerm(p, g);
      // --stage=rw (driver audit): each live driver's term as it enters the composite (frame and years in FV points)
      if (REC_TERMS) {
        const pc = CUR.pfn * (CUR.prodPos[g] ?? 1) * (M['prod_' + g] ?? 1) * (s < 2019 ? M.prodBox ?? 1 : 1), T = p._t = {};
        T['prod_' + g] = pc * p.zPfn; T.nonBlue = pc * (prodEff - p.zPfn);
        T.hs = M.hs * (s < 2019 ? M.hsBox ?? 1 : 1) * clamp(CUR.hs.w * p.hsRaw, CUR.hs.cap); T.team = M.team * clamp(CUR.team * (p.team ?? 0), CUR.teamCap);
        T.ageY = a > 0 ? M.age * ageZ : 0; T.ageO = a > 0 ? 0 : M.age * ageZ; T.cls = M.cls * cls; T.snap = M.snap * clamp(CUR.snap.w * p.shareZ, CUR.snap.cap);
        T.sos = g === 'QB' ? M.sos * clamp(CUR.sos.perSd * p.sosZ, CUR.sos.cap) : 0; T.brk = M.brk * brk; T.ath = athT;
        for (const [k, w] of Object.entries(CUR.badge[g] || {})) T[`b_${g}_${k}`] = p.badge[k] != null ? w * M[`b_${g}_${k}`] * p.badge[k] : 0;
        T.frame = M.frame * frameFV(g, p.ht, p.wt); T.years = -M.years * Math.max(0, p.years - 3) * (g === 'QB' ? 2 : 1);
      }
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
// Oct 25 2026 (--target, audit #24): years .5, the years-past-three FV debit halved (see the --target block)
// (ageO .5: every focused fold; snap .4: the focused fit, the screen wanted 0; ath 1.6: the last-season joint fit,
// since only last seasons carry a combine). Oct 21 (--wide, the 2014-22 classes): ath x2.1 more (3.36) with its cap
// x2.1, frame 1.4, breakout timing off, the QB deep-ball badge at .15. Oct 26 (--stage=rw, the driver re-weight): the
// combine cap x1.5 more (3.15 = FV_ATH.cap .63)
const SHIP = { ageO: 0.5, snap: 0.4, ath: 3.36, athCap: 3.15, frame: 1.4, brk: 0, b_QB_deep: 0.15, years: 0.5 };
function shipped(M) {
  const G = grade({ ...ONE, ...M }), G0 = grade(ONE), o = {};
  for (const [sn, S] of Object.entries(SETS)) for (const t of ['av', 'cap']) { const a = score(G0, S, t), b = score(G, S, t); o[sn + '_' + t] = { before: [r3(a.pooled), r3(a.within)], after: [r3(b.pooled), r3(b.within)], byPos: { before: a.byPos, after: b.byPos } }; }
  for (const t of ['av', 'cap']) { const a = score(G0, finals, t, 'fc'), b = score(G, finals, t, 'fc'); o['lastCons_' + t] = { before: [r3(a.pooled), r3(a.within)], after: [r3(b.pooled), r3(b.within)] }; }
  return o;
}
const arg = k => (process.argv.find(a => a.startsWith(`--${k}=`)) || '').slice(k.length + 3).split(',').filter(Boolean);
const out = { asof: new Date().toISOString().slice(0, 10), method: 'see scripts/cfb_fv_refit.mjs', n: {} };
for (const g of G7) { const F = finals.filter(p => p.g === g); out.n[g] = { players: F.length, drafted: F.filter(p => p.pick).length, earlierRows: early.filter(p => p.g === g).length }; }
if (process.argv.includes('--poscal')) {
  // calibration by position and FV band (last seasons): NFL AV a season against what avOf(FV) promises, and draft rate
  const G = grade({ ...ONE, ...SHIP });
  for (const g of G7) for (const [lo, hi] of [[45, 50], [50, 55], [55, 60], [60, 81]]) {
    const T = finals.filter(p => p.g === g && G.has(p) && G.get(p).fm >= lo && G.get(p).fm < hi); if (T.length < 5) { console.log(g, lo, 'n', T.length); continue; }
    console.log(g.padEnd(5), lo + '-' + hi, 'n', T.length, 'AV', r3(mean(T.map(p => p.av))), 'avOf', r3(mean(T.map(p => avOf(G.get(p).fm)))), 'drafted', r3(mean(T.map(p => +!!p.pick))), 'R1', r3(mean(T.map(p => +(p.pick && p.pick <= 32)))));
  }
  process.exit(0);
}
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
// ---- --pos: the drivers refit within each position group, shrunk toward the pooled (shipped) weights ---------------
// Each position's composite is standardized within the position, so a position's multipliers only reorder it: the
// fit is the within-position r with NFL AV, one draft class held out, the penalty picked inside the training folds.
// Production's own weight (FV_PROD_POS) is the scale here, so every other driver's multiplier is relative to it.
const POS_KEYS = { QB: ['sos', 'b_QB_accurate', 'b_QB_deep'], RB: ['b_RB_catcher'], TE: ['b_TE_catcher'], DL: ['b_DL_runstop'], LB: ['b_LB_tackler'] };
// position multipliers count on top of the pooled (shipped) weights: 1 = pooled
const toBase = M => Object.fromEntries(Object.entries(M).map(([k, v]) => [k, v * ({ ...ONE, ...SHIP }[k] ?? 1)]));
function posFit(g, S, lam, keys, base) {
  const obj = M => { const G = grade(base, rows, { [g]: toBase(M) }, g), T = S.filter(p => G.has(p)); return corr(T.map(p => G.get(p).fm), T.map(p => p.av)) - lam * keys.reduce((a, k) => a + (M[k] - 1) ** 2, 0); };
  let M = Object.fromEntries(keys.map(k => [k, 1])), best = obj(M);
  for (const step of [0.5, 0.25, 0.1]) for (let sw = 0; sw < 3; sw++) {
    let moved = false;
    for (const k of keys) for (const dir of [1, -1]) { const T = { ...M, [k]: Math.max(-1, Math.min(4, M[k] + dir * step)) }, v = obj(T); if (v > best + 1e-6) { M = T; best = v; moved = true; } }
    if (!moved) break;
  }
  return M;
}
// shipped position overrides (x the pooled weights): only LB and TE beat the pooled weights out of sample
const POS_SHIP = { LB: { hs: 0, nonBlue: 0.4, ath: 1.5 }, TE: { hs: 0.5 } };
// ---- --past: past-season grades for this season's board ----------------------------------------------------------
// Each FBS season 2019-25 graded as the backtest grades it: the board as it stood at the end of that season (3-season
// production blend, 247 pedigree, Elo, age and class from the recruiting class, snap share, SOS at QB, breakout,
// badges, frame, years past three), shipped weights, today's scarcity scale. No On3 grade or consensus (neither has
// history), so a past grade is the model's read on production, pedigree and age alone. A season counts for a board
// player when ESPN's roster that season (cfbfastR, by his ESPN athlete id) has him at that school. PFN's ids are name
// slugs, so a name alone can't tell two players apart (the old name rule gave Notre Dame's edge Bryce Young the
// Alabama QB's seasons). A season at his current school also counts at the same position (ESPN rosters miss some
// players, and a few board ESPN ids point at a namesake), or at a nearby one when he has no ESPN id.
// A player on two position boards keeps the line with more snaps.
// Level check (Oct 16, 2026): last-season grades 2019-24 against NFL AV a season (drafts 2020-25, AV through 2025),
// bucketed by FV against the FV scale's own AV map (AV_BY_FV): within .5 AV a season from 35 up (the pools are PFN's
// qualifiers, graded against the 2026 board's population as the backtest does). Rescaling to the qualifier pool
// (N = pool size x k, k .6-1.2) or matching quantiles to today's board both over-grade (.8-1.4 AV off), so the
// scale stays.
// Scale re-anchor (Oct 16, 2026; 80 = 5+ All-Pro, FV_PEAK_SLOPE, the new AV_BY_FV top): --quick under the shipped weights
// scores the same, all rows AV .524 / .526 and draft slot .593 / .611 (pooled / within) before and after, last seasons
// .597 / .596 -> .598 / .597; the rebuilt 2019-22 boards held one model 80 a class before and none after (top 77)
// Rerun once a season, after the bowls:  node scripts/cfb_fv_refit.mjs --past -> static/data/cfb-past.json
// --teamfv=<file>: every graded row (the board at the end of each season, shipped weights; --wide adds 2014-18 on box
// lines) at the grade and at its mean outcome, with the draft slot that followed (not --past), for the game-model test
// of FV-based team talent and rookie inputs (scripts/fv_mean_games.py)
if (arg('teamfv').length) {
  const G = grade({ ...ONE, ...SHIP, ...(WIDE ? { prodBox: 1, hsBox: 1.25 } : {}) }, rows, Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)])));
  const S = rows.filter(p => G.has(p)).map(p => { const fm = G.get(p).fm, mu = pastAtMean(fm, p.g, p.years);
    return { s: p.s, g: p.g, name: p.name, team: p.row.team, id: p.row.id ?? null, espn: p.row.espn ?? null, years: p.years, snaps: p.snapsN, final: p.final,
      pick: p.pick ?? null, fvg: r3(fm), fvm: r3(mu), avg: r3(avOf(fm)), avm: r3(avOf(mu)) }; });
  fs.writeFileSync(arg('teamfv')[0], JSON.stringify(S));
  console.log('teamfv rows', S.length);
  process.exit(0);
}
if (PAST) {
  const G = grade({ ...ONE, ...SHIP }, rows, Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)])));
  const ALL = JSON.parse(fs.readFileSync(path.join(ROOT, 'static', 'data', 'cfb-all.json'), 'utf8'));
  const ci = Object.fromEntries(ALL.cols.map((c, i) => [c, i])), now = Math.max(...ROW_SEASONS) + 1;
  const byName = {}; for (const p of rows) (byName[nm(p.name)] ||= []).push(p);
  const boardN = {}, boardT = {}; for (const r of ALL.rows) { const n = nm(r[ci.name]); boardN[n] = (boardN[n] || 0) + 1; boardT[n] = r[ci.team]; }
  // PFN's school names to the board's ("Mississippi" is Ole Miss): the majority vote of players whose name is unique on both
  const lines = Object.values(PFN_RAW).flat(), nowN = {}, vote = {};
  for (const r of lines) if (r.season === now) (nowN[nm(r.name)] ||= new Set()).add(r.team);
  for (const r of lines) if (r.season === now && boardN[nm(r.name)] === 1 && nowN[nm(r.name)].size === 1) { const v = vote[r.team] ||= {}; v[boardT[nm(r.name)]] = (v[boardT[nm(r.name)]] || 0) + 1; }
  const tName = t => { const v = vote[t]; if (!v) return t; const [b, c] = Object.entries(v).sort((x, y) => y[1] - x[1])[0]; return c >= 2 ? b : t; };
  // ESPN rosters by athlete id: the schools he was on, season by season
  const espnAt = {};
  for (const y of ROW_SEASONS) for (const r of csv(pull(`ros/r${y}.csv`, `https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/csv/cfb_rosters_${y}.csv`)))
    ((espnAt[r.athlete_id] ||= {})[y] ||= new Set()).add(school(r.team));
  // positions a player plausibly moved between (otherwise a same-school namesake)
  const NEAR = new Set(['EDGE|DL', 'EDGE|LB', 'LB|S', 'CB|S', 'WR|TE', 'RB|WR', 'TE|OL', 'DL|OL']);
  const near = (a, b) => a === b || NEAR.has(a + '|' + b) || NEAR.has(b + '|' + a);
  const G_OF = { DT: 'DL', OT: 'OL', G: 'OL', C: 'OL', IOL: 'OL' };
  const pos = g => g === 'DL' ? 'DT' : g;
  const players = {}, perSeason = {}, pairs = [];
  for (const r of ALL.rows) {
    const n = nm(r[ci.name]), sch = school(r[ci.team]), best = {}, g0 = G_OF[r[ci.pos]] || r[ci.pos];
    const aid = (/\/id\/(\d+)/.exec(r[ci.espnl] || '') || [])[1], at = aid && espnAt[aid];
    for (const p of byName[n] || []) {
      const ps = school(tName(p.row.team));
      if (!at?.[p.s]?.has(ps) && !(ps === sch && (at ? p.g === g0 : near(p.g, g0)))) continue;
      if (!best[p.s] || p.snapsN > best[p.s].snapsN) best[p.s] = p;
    }
    // each past grade at its mean outcome, his years on campus that season (the headline FV since Oct 21 2026)
    const list = Object.values(best).filter(p => G.has(p)).sort((a, b) => b.s - a.s)
      .map(p => { const m = pastAtMean(G.get(p).fm, p.g, (r[ci.elig] ?? 3) - (now - p.s)); return [p.s, fvOf('cfb', m, Math.round(m)), pos(p.g), tName(p.row.team), Math.round(m * 100) / 100]; });
    if (!list.length) continue;
    players[r[ci.name] + '|' + r[ci.team]] = list;
    for (const x of list) perSeason[x[0]] = (perSeason[x[0]] || 0) + 1;
    if (list[0][0] === now - 1 && r[ci.fvx] != null) pairs.push([list[0][4], r[ci.fvx]]);
  }
  const o = { asof: new Date().toISOString().slice(0, 10), seasons: ROW_SEASONS, method: 'scripts/cfb_fv_refit.mjs --past', cols: ['season', 'fv', 'pos', 'team', 'fvx'], scale: 'mean, stretched top (scripts/fv_scale.py)',
    n: { players: Object.keys(players).length, perSeason }, rNow: r3(corr(pairs.map(x => x[0]), pairs.map(x => x[1]))), players };
  fs.writeFileSync(path.join(ROOT, 'static', 'data', 'cfb-past.json'), JSON.stringify(o));
  console.log('past grades', o.n, 'r with FV now', o.rNow, 'n', pairs.length);
  process.exit(0);
}
// --dist=<file>: every scored row graded under the shipped weights, with its NFL outcome, for the FV distribution fit
// (scripts/fv_dist_fit.py)
if (arg('dist').length) {
  const G = grade({ ...ONE, ...SHIP }, rows, Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)])));
  const S = U.filter(p => G.has(p)).map(p => ({ name: p.name, g: p.g, s: p.s, last: p.last, final: p.final, years: p.years, walkOn: p.walkOn, stars: p.stars, snaps: p.snapsN,
    z: r3(p.zPfn), fm: r3(G.get(p).fm), fc: r3(G.get(p).fc), dt: p.dt, av: r3(p.av), pick: p.pick, ap: p.ap, pb: p.pb }));
  fs.writeFileSync(arg('dist')[0], JSON.stringify(S));
  console.log('dist rows', S.length);
  process.exit(0);
}
// --comps=<file> (with --wide; audit #41, Oct 25 2026): every scored row 2014-22 with the profile the comps match on
// (production z, 247 pedigree z, years on campus, listed size, team strength (Elo z), combine testing) and the player's NFL outcome, for
// scripts/cfb_comps.py. Testing is the player's own combine on all his rows (descriptive: live players match on it only
// once they've tested)
if (arg('comps').length) {
  const G = grade({ ...ONE, ...SHIP, ...(WIDE ? { prodBox: 1, hsBox: 1.25 } : {}) }, rows, Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)])));
  const athBy = new Map(finals.filter(p => p.ath != null).map(p => [p.g + '|' + p.id, p.ath]));
  const S = U.filter(p => G.has(p)).map(p => ({ name: p.name, g: p.g, s: p.s, last: p.last, final: p.final, team: p.row.team, years: p.years,
    ht: p.ht, wt: p.wt, z: r3(p.zPfn), hs: r3(p.hsRaw), stars: p.stars, walkOn: p.walkOn, snaps: p.snapsN, ath: athBy.has(p.g + '|' + p.id) ? r3(athBy.get(p.g + '|' + p.id)) : null, lvl: p.team != null ? r3(p.team) : null,
    fm: r3(G.get(p).fm), av: r3(p.av), pick: p.pick, pfr: p.pfr, ap: p.ap, pb: p.pb }));
  fs.writeFileSync(arg('comps')[0], JSON.stringify(S));
  console.log('comp rows', S.length, 'finals', S.filter(p => p.final).length, 'tested', S.filter(p => p.ath != null).length);
  process.exit(0);
}
// --target (audit #24, Oct 25 2026): FV retargeted on NFL value instead of AV a season. Outcomes from
// scripts/cfb_fv_target.py: war (NFL WAR a season since the draft, sub-position lines; seasons 2016-25) and apy (second
// contract, cap %; drafts through 2018). Two questions, both one class held out:
//   posvalue  FV_POS_VALUE from scripts/cfb_fv_posvalue.py (data/cfb_fv_posvalue.json), each held-out class graded with
//             the values fit without its draft; scored on the pooled board (positional value only reorders across
//             positions): r of each target with its training-class isotonic map of FV, and pooled Spearman
//   screen    every driver's multiplier on top of the shipped weights, refit inside the training classes on the WAR
//             target (within-position + pooled Spearman), held-out gains on WAR and AV
// node scripts/cfb_fv_refit.mjs --wide --target [--noscreen] [--cand=k=v,...] -> data/cfb_fv_target.json
// Result (Oct 25 2026; 14,082 rows, drafts 2015-24; apy only 2015-18): positional value fails. Fit on WAR it wins the
// WAR target (pooled r .428 -> .461, t 2.5, 7/10 classes) only by lifting QBs ~2.6x (a QB's WAR at equal rarity is
// 2.9x the pool's), and loses second contracts (-.010) and draft slot (-.009, t -1.7); fit on contracts it doesn't win
// contracts held out (-.003, 1/4); blends and half-way shrinks lose somewhere too. Today's hand-set values beat pure
// rarity (pv 1) on WAR (t 2.1) and AV (t 2.8), so they stay. Retargeting changes no driver call that AV wouldn't make:
// every screen gain on WAR is at or below its gain on AV. The years-past-three debit refits to 0 in all ten folds
// (ranking gains on both targets); 0 over-grades 6th-year players (.144 AV a season promised vs .035), .5 ranks nearly
// as well and keeps every years-on-campus band calibrated, so it ships at .5 (SHIP.years, FV_YEARS_W in fetch_cfb.mjs).
// Smaller youth/old-age debits and the non-blue-chip discount lift Spearman but lower the top 32 a class: not shipped
if (NT) {
  const PV = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_fv_posvalue.json'), 'utf8'));
  const BASE = { ...ONE, ...SHIP, ...(WIDE ? { prodBox: 1, hsBox: 1.25 } : {}) };
  const posO = M => Object.fromEntries(Object.entries(POS_SHIP).map(([g, Q]) => [g, Object.fromEntries(Object.entries(Q).map(([k, v]) => [k, v * (M[k] ?? 1)]))]));
  const gradeAt = (M, pv) => { setPV(pv); return grade(M, rows, posO(M)); };
  const rankAvg = xs => { const o = xs.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]), r = Array(xs.length);
    for (let i = 0; i < o.length;) { let j = i; while (j + 1 < o.length && o[j + 1][0] === o[i][0]) j++; for (let k = i; k <= j; k++) r[o[k][1]] = (i + j) / 2; i = j + 1; } return r; };
  const spear = (x, y) => corr(rankAvg(x), rankAvg(y));
  // isotonic (pool adjacent violators) fit of y on x, read off by linear interpolation between block means
  const iso = (xs, ys) => {
    const o = xs.map((x, i) => [x, ys[i]]).sort((a, b) => a[0] - b[0]), B = [];
    for (const [x, y] of o) { B.push({ x, y, n: 1 }); while (B.length > 1 && B.at(-2).y / B.at(-2).n * 1 >= B.at(-1).y / B.at(-1).n) { const b = B.pop(), a = B.at(-1); a.x = (a.x * a.n + b.x * b.n) / (a.n + b.n); a.y += b.y; a.n += b.n; } }
    const P = B.map(b => [b.x, b.y / b.n]);
    return x => { if (x <= P[0][0]) return P[0][1]; for (let i = 1; i < P.length; i++) if (x <= P[i][0]) return P[i - 1][1] + (P[i][1] - P[i - 1][1]) * (x - P[i - 1][0]) / (P[i][0] - P[i - 1][0]); return P.at(-1)[1]; };
  };
  const TGT = ['war', 'apy', 'av', 'cap'], fvk = 'fm';
  const within = (G, S, t) => mean(G7.map(g => { const T = S.filter(p => p.g === g && G.has(p)); return spear(T.map(p => G.get(p)[fvk]), T.map(p => p[t])); }));
  const res = { asof: new Date().toISOString().slice(0, 10), method: 'node scripts/cfb_fv_refit.mjs --wide --target', n: {}, posvalue: {}, screen: {} };
  for (const t of TGT) { const S = U.filter(p => p[t] != null); res.n[t] = { rows: S.length, classes: [...new Set(S.map(p => p.last + 1))].sort().join(','), drafted: S.filter(p => p.pick).length }; }
  console.log('targets', JSON.stringify(res.n));
  // ---- positional value ----
  const CUR_PV = PV.current, units = { current: () => CUR_PV, ones: () => Object.fromEntries(Object.keys(CUR_PV).map(g => [g, 1])), ...Object.fromEntries(Object.keys(PV.units).map(u => [u, c => PV.units[u].drop[String(c + 1)] ?? PV.units[u].pv])) };
  // part way from today's values to a fit, in log space (lam 1 = the fit)
  const toward = (A, B, lam) => Object.fromEntries(Object.keys(A).map(g => [g, A[g] ** (1 - lam) * B[g] ** lam]));
  for (const u of ['apy', 'war', 'blend']) for (const lam of [0.25, 0.5]) units[u + '@' + lam] = c => toward(CUR_PV, units[u](c), lam);
  const oof = {};
  for (const [u, pvOf] of Object.entries(units)) {
    oof[u] = new Map(); const map = {};
    for (const c of CLASSES) {
      const G = gradeAt(BASE, pvOf(c));
      const tr = U.filter(p => p.last !== c && G.has(p));
      for (const t of TGT) { const T = tr.filter(p => p[t] != null); map[t + c] = iso(T.map(p => G.get(p)[fvk]), T.map(p => p[t])); }
      for (const p of U.filter(q => q.last === c && G.has(q))) oof[u].set(p, { fv: G.get(p)[fvk], fc: G.get(p).fc, pred: Object.fromEntries(TGT.map(t => [t, map[t + c](G.get(p)[fvk])])) });
    }
  }
  const pooledOf = (O, t, S) => { const T = S.filter(p => O.has(p) && p[t] != null); return { r: corr(T.map(p => O.get(p).pred[t]), T.map(p => p[t])), rho: spear(T.map(p => O.get(p).fv), T.map(p => p[t])) }; };
  for (const u of Object.keys(units)) {
    const o = res.posvalue[u] = { pv: Object.fromEntries(Object.entries(units[u](0)).map(([g, v]) => [g, r3(v)])) };
    for (const t of TGT) {
      for (const [sn, S] of [['all', U], ['last', finals], ['drafted', finals.filter(p => p.pick)]]) { const v = pooledOf(oof[u], t, S); o[sn + '_' + t] = [r3(v.r), r3(v.rho)]; }
      // per held-out class, against today's values: pooled r of the isotonic prediction
      const d = CLASSES.map(c => { const S = U.filter(p => p.last === c && p[t] != null); if (S.length < 50) return null; return pooledOf(oof[u], t, S).r - pooledOf(oof.current, t, S).r; }).filter(x => x != null);
      const m = mean(d), se = sdv(d) * Math.sqrt(d.length / Math.max(1, d.length - 1)) / Math.sqrt(d.length);
      o['vsCurrent_' + t] = { gain: r3(m), t: u === 'current' ? null : r3(m / se), won: d.filter(x => x > 1e-9).length + '/' + d.length };
    }
    console.log('posvalue', u.padEnd(8), JSON.stringify(o));
  }
  // calibration on the war target by position and FV band, today's values vs the blend (all rows, held out)
  res.calib = {};
  for (const u of ['current', 'apy', 'war', 'blend']) { res.calib[u] = {};
    for (const g of G7) for (const [lo, hi] of [[50, 55], [55, 60], [60, 81]]) {
      const T = U.filter(p => p.g === g && oof[u].has(p) && oof[u].get(p).fv >= lo && oof[u].get(p).fv < hi);
      if (T.length >= 5) res.calib[u][g + ' ' + lo] = { n: T.length, war: r3(mean(T.map(p => p.war))), pred: r3(mean(T.map(p => oof[u].get(p).pred.war))), drafted: r3(mean(T.map(p => +!!p.pick))) };
    }
  }
  console.log('calib', JSON.stringify(res.calib));
  // --cand=k=v,...: a driver set (multipliers on the shipped weights) against today on every universe, era and target:
  // pooled / within-position Pearson (avOf map) and Spearman, and the top of the board (top 32 model FV per class)
  if (arg('cand').length) {
    setPV(CUR_PV);
    const C = Object.fromEntries(arg('cand').map(x => x.split('=')).map(([k, v]) => [k, (BASE[k] ?? 1) * +v])), M1 = { ...BASE, ...C };
    const G0 = grade(BASE, rows, posO(BASE)), G1 = grade(M1, rows, posO(M1)), cmp = {};
    const ERA = { all: U, last: finals, earlier: early, pfn: U.filter(p => p.s >= 2019), box: U.filter(p => p.s < 2019) };
    for (const [e, S] of Object.entries(ERA)) for (const t of ['av', 'war', 'cap']) {
      const a = score(G0, S, t), b = score(G1, S, t), T = S.filter(p => G0.has(p));
      cmp[e + '_' + t] = { pearson: [r3(b.pooled - a.pooled), r3(b.within - a.within)], spearman: r3(within(G1, T, t) - within(G0, T, t)) };
    }
    // per class, all rows: within-position Spearman and Pearson on AV and WAR, candidate minus today
    for (const t of ['av', 'war']) for (const k of ['sp', 'pe']) {
      const d = CLASSES.map(c => { const S = U.filter(p => p.last === c && G0.has(p)); return k === 'sp' ? within(G1, S, t) - within(G0, S, t) : score(G1, S, t).within - score(G0, S, t).within; });
      const m = mean(d), se = sdv(d) * Math.sqrt(d.length / (d.length - 1)) / Math.sqrt(d.length); cmp['class_' + t + '_' + k] = { gain: r3(m), t: r3(m / se), won: d.filter(x => x > 0).length + '/' + d.length };
    }
    for (const [lab, G] of [['today', G0], ['cand', G1]]) {
      for (const n of [16, 32, 64, 128]) {
        const top = CLASSES.flatMap(c => finals.filter(p => p.last === c && G.has(p)).sort((a, b) => G.get(b).fm - G.get(a).fm).slice(0, n));
        cmp['top' + n + '_' + lab] = { av: r3(mean(top.map(p => p.av))), war: r3(mean(top.map(p => p.war))), drafted: r3(mean(top.map(p => +!!p.pick))), r1: r3(mean(top.map(p => +(p.pick && p.pick <= 32)))) };
      }
    }
    // calibration by years on campus: realized AV / WAR a season against the training-free AV map (avOf) of the grade
    for (const y of [1, 2, 3, 4, 5, 6]) { const T = U.filter(p => Math.min(6, Math.round(p.years)) === y && G0.has(p)); if (T.length < 30) continue;
      cmp['years' + y] = { n: T.length, av: r3(mean(T.map(p => p.av))), avOfToday: r3(mean(T.map(p => avOf(G0.get(p).fm)))), avOfCand: r3(mean(T.map(p => avOf(G1.get(p).fm)))),
        fvToday: r3(mean(T.map(p => G0.get(p).fm))), fvCand: r3(mean(T.map(p => G1.get(p).fm))), mseToday: r3(mean(T.map(p => (p.av - avOf(G0.get(p).fm)) ** 2))), mseCand: r3(mean(T.map(p => (p.av - avOf(G1.get(p).fm)) ** 2))) }; }
    console.log('cand', JSON.stringify(C), JSON.stringify(cmp, null, 0));
    process.exit(0);
  }
  // ---- driver screen on the WAR target ----
  if (!process.argv.includes('--noscreen')) {
    setPV(CUR_PV);
    const grid = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3], keys = KEYS.filter(k => !['prodBox', 'hsBox'].includes(k));
    const G1 = grade(BASE, rows, posO(BASE));
    const obj = (G, S) => within(G, S, 'war') + spear(S.filter(p => G.has(p)).map(p => G.get(p)[fvk]), S.filter(p => G.has(p)).map(p => p.war));
    const gains = (G0, G, S) => Object.fromEntries(['war', 'av'].map(t => { const T = S.filter(p => G.has(p) && G0.has(p));
      return [t, [r3(within(G, T, t) - within(G0, T, t)), r3(spear(T.map(p => G.get(p)[fvk]), T.map(p => p[t])) - spear(T.map(p => G0.get(p)[fvk]), T.map(p => p[t])))]]; }));
    for (const k of keys) {
      const Gs = grid.map(v => { const M = { ...BASE, [k]: (BASE[k] ?? 1) * v }; return grade(M, rows, posO(M)); }), O = new Map(), pick = [];
      for (const c of CLASSES) {
        const tr = U.filter(p => p.last !== c); let bi = grid.indexOf(1), bv = -Infinity;
        Gs.forEach((G, i) => { const v = obj(G, tr); if (v > bv + 1e-9) { bv = v; bi = i; } });
        pick.push(grid[bi]); for (const p of U.filter(q => q.last === c)) if (Gs[bi].has(p)) O.set(p, Gs[bi].get(p));
      }
      res.screen[k] = { folds: pick, ...gains(G1, O, U) };
      console.log('screen', k.padEnd(14), JSON.stringify(res.screen[k]));
    }
  }
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_fv_target.json'), JSON.stringify(res, null, 1) + '\n');
  process.exit(0);
}
if (process.argv.includes('--posquick')) {
  const base = { ...ONE, ...SHIP }, G0 = grade(base), G1 = grade(base, rows, Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)])));
  for (const [sn, S] of Object.entries(SETS)) for (const t of ['av', 'cap']) {
    const a = score(G0, S, t), b = score(G1, S, t);
    console.log(sn, t, 'pooled', r3(a.pooled), '->', r3(b.pooled), 'LB', a.byPos.LB, '->', b.byPos.LB, 'TE', a.byPos.TE, '->', b.byPos.TE);
  }
  process.exit(0);
}
if (process.argv.includes('--pos')) {
  const base = { ...ONE, ...SHIP }, U = [...finals, ...early], res = {};
  // multipliers here are on top of the shipped pooled weights (1 = pooled)
  const common = ['nonBlue', 'hs', 'team', 'ageY', 'ageO', 'cls', 'snap', 'brk', 'ath', 'frame', 'years'];
  const rOf = (G, T, t) => { const X = T.filter(p => G.has(p)); return corr(X.map(p => G.get(p).fm), X.map(p => p[t])); };
  for (const g of G7) {
    const keys = [...common, ...(POS_KEYS[g] || [])], S = U.filter(p => p.g === g), C = [...new Set(S.map(p => p.last))].sort();
    const G0 = grade(base, rows, null, g), oof = new Map(), foldM = [];
    for (const c of C) {
      const tr = S.filter(p => p.last !== c); let bl = 0.1, bv = -Infinity;
      for (const lam of [0.003, 0.01, 0.03, 0.1]) {
        let v = 0; for (const c2 of C.filter(x => x !== c)) { const M = posFit(g, tr.filter(p => p.last !== c2), lam, keys, base); v += rOf(grade(base, rows, { [g]: toBase(M) }, g), tr.filter(p => p.last === c2), 'av'); }
        if (v > bv) { bv = v; bl = lam; }
      }
      const M = posFit(g, tr, bl, keys, base), G = grade(base, rows, { [g]: toBase(M) }, g); foldM.push({ lam: bl, M });
      for (const p of S.filter(q => q.last === c)) oof.set(p, G.get(p));
    }
    const lamAll = foldM.map(f => f.lam).sort((a, b) => a - b)[C.length >> 1], MA = posFit(g, S, lamAll, keys, base);
    const revert = {};
    for (const k of keys) {
      const o = new Map(); C.forEach((c, i) => { const G = grade(base, rows, { [g]: toBase({ ...foldM[i].M, [k]: 1 }) }, g); for (const p of S.filter(q => q.last === c)) o.set(p, G.get(p)); });
      revert[k] = { av: r3(rOf(o, S, 'av') - rOf(oof, S, 'av')), cap: r3(rOf(o, S, 'cap') - rOf(oof, S, 'cap')) };
    }
    res[g] = { n: S.length, drafted: S.filter(p => p.pick).length, av: [r3(rOf(G0, S, 'av')), r3(rOf(oof, S, 'av'))], cap: [r3(rOf(G0, S, 'cap')), r3(rOf(oof, S, 'cap'))],
      last: [r3(rOf(G0, finals.filter(p => p.g === g), 'av')), r3(rOf(oof, finals.filter(p => p.g === g), 'av'))],
      multipliers: Object.fromEntries(keys.map(k => [k, { all: r3(MA[k]), folds: foldM.map(f => r3(f.M[k])) }])), revert, lams: foldM.map(f => f.lam) };
    console.log(g, JSON.stringify({ n: res[g].n, av: res[g].av, cap: res[g].cap, last: res[g].last, lams: res[g].lams }));
    for (const k of keys) console.log('  ', k.padEnd(14), JSON.stringify(res[g].multipliers[k]), JSON.stringify(revert[k]));
  }
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_fv_refit_pos.json'), JSON.stringify({ asof: new Date().toISOString().slice(0, 10), method: 'node scripts/cfb_fv_refit.mjs --pos', base: SHIP, positions: res }, null, 1) + '\n');
  process.exit(0);
}
// ---- --context: past seasons judged in context ------------------------------------------------------------------
// Each season's production z, before the 5/4/3 blend, adjusted by one candidate at a time, then the board regraded:
//   sos     + v x that season's PFN strength of schedule (z within position and season): opponent-adjusted production
//   level   + v x that season's team Elo (start of season, z among FBS): a level-of-program term (v < 0 credits G5 output)
//   cast    - v x that season's best teammate at the receiving end (QB: WR/TE; WR, TE: QB) by NFL draft capital in the
//           next three drafts (z within position and season): production net of the cast around him
//   youth   x (1 + v x (3 - years in school that season)): the same output counts more the younger he was
// v is picked on three final-season classes and scored on the fourth (as the screen does), pooled over positions and
// then within each position alone. Gains are out-of-sample changes in r with NFL AV and draft capital over v = 0.
// Result (Oct 14, 2026; data/cfb_context_backtest.json): nothing gains pooled. At QB all four lose (schedule -.003,
// level -.003, cast 0, youth -.013 AV r); the level folds lean toward discounting low-Elo programs, not crediting
// them. Of 28 position tests only DL schedule clears both outcomes (+.008 AV, +.020 capital), one in 28, not shipped
if (process.argv.includes('--context')) {
  const base = { ...ONE, ...SHIP };
  const ctxOf = new Map();
  { const sp = {}; for (const p of rows) if (num(p.row.sos) != null) (sp[p.g + p.s] ||= []).push(p.row.sos);
    const st = Object.fromEntries(Object.entries(sp).map(([k, v]) => [k, [mean(v), sdv(v)]]));
    const REC = { QB: ['WR', 'TE'], WR: ['QB'], TE: ['QB'] }, cap = {};
    for (const x of picksAll) { const y = +x.season; if (!(y >= 2020 && y <= 2025)) continue;
      for (const [g, gs] of Object.entries(REC)) if (gs.includes(x.position)) for (let s = y - 3; s <= y - 1; s++) { const k = g + s + '|' + school(x.college); cap[k] = Math.max(cap[k] ?? 0, capital(+x.pick)); } }
    const cs = {}; for (const p of rows) for (const h of p.hist) if (REC[p.g]) (cs[p.g + h.s] ||= new Map()).set(h.row, cap[p.g + h.s + '|' + h.sch] ?? 0);
    const cst = Object.fromEntries(Object.entries(cs).map(([k, m]) => [k, [mean([...m.values()]), sdv([...m.values()])]]));
    for (const p of rows) for (const h of p.hist) {
      const sk = st[p.g + h.s], ck = cst[p.g + h.s];
      ctxOf.set(h, { sos: num(h.row.sos) != null && sk ? (h.row.sos - sk[0]) / sk[1] : 0, elo: elo[h.s]?.[h.sch] ?? 0,
        cast: REC[p.g] && ck ? ((cs[p.g + h.s].get(h.row) ?? 0) - ck[0]) / ck[1] : 0, yrs: p.years - h.k });
    }
  }
  const CAND = {
    sos: { grid: [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.5], f: (h, c, v) => h.z + v * c.sos },
    level: { grid: [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3], f: (h, c, v) => h.z + v * c.elo },
    cast: { grid: [-0.2, -0.1, 0, 0.1, 0.2, 0.3], f: (h, c, v) => h.z - v * c.cast, only: ['QB', 'WR', 'TE'] },
    youth: { grid: [-0.15, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2], f: (h, c, v) => h.z * (1 + v * (3 - c.yrs)) },
  };
  const restandardize = () => { for (const P of Object.values(POOLS)) { const m = mean(P.map(p => p.marcel)), sd = sdv(P.map(p => p.marcel)); for (const p of P) p.zPfn = (p.marcel - m) / sd; } };
  const apply = (f, v, gs) => { for (const p of rows) { let a = 0, d = 0; for (const h of p.hist) { a += h.w * (gs.includes(p.g) ? f(h, ctxOf.get(h), v) : h.z); d += h.w; } p.marcel = a / (d + CUR.K); } restandardize(); };
  const rPos = (G, S, g, t) => { const T = S.filter(p => p.g === g && G.has(p)); return corr(T.map(p => G.get(p).fm), T.map(p => p[t])); };
  const res = {};
  for (const [name, c] of Object.entries(CAND)) {
    res[name] = {};
    for (const scope of ['pooled', ...(c.only || G7)]) {
      const gs = scope === 'pooled' ? (c.only || G7) : [scope];
      const PS = Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)]));
      const Gs = c.grid.map(v => { apply(c.f, v, gs); return grade(base, rows, PS); });
      apply(c.f, 0, G7);
      const obj = (G, S) => scope === 'pooled' ? (s => s.pooled + s.within)(score(G, S)) : rPos(G, S, scope, 'av');
      const S = finals, oof = new Map(), pick = [], G0 = Gs[c.grid.indexOf(0)];
      for (const cl of [...new Set(S.map(p => p.last))].sort()) {
        const tr = S.filter(p => p.last !== cl); let bi = c.grid.indexOf(0), bv = -Infinity;
        Gs.forEach((G, i) => { const v = obj(G, tr); if (v > bv + 1e-9) { bv = v; bi = i; } });
        pick.push(c.grid[bi]); for (const p of S.filter(q => q.last === cl)) oof.set(p, Gs[bi].get(p));
      }
      const full = c.grid.map((v, i) => r3(obj(Gs[i], S)));
      res[name][scope] = { folds: pick, inSample: Object.fromEntries(c.grid.map((v, i) => [v, full[i]])),
        oos: scope === 'pooled' ? gain(G0, oof, S) : Object.fromEntries(['av', 'cap'].map(t => [t, r3(rPos(oof, S, scope, t) - rPos(G0, S, scope, t))])) };
      console.log('context', name.padEnd(6), scope.padEnd(6), JSON.stringify(res[name][scope].folds), JSON.stringify(res[name][scope].oos));
    }
  }
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_context_backtest.json'), JSON.stringify({ asof: new Date().toISOString().slice(0, 10), method: 'node scripts/cfb_fv_refit.mjs --context', results: res }, null, 1) + '\n');
  process.exit(0);
}
// --qbcheck: QB pedigree and youth switched off (no fitting, so each is scored on every class as is)
if (process.argv.includes('--qbcheck')) {
  const base = { ...ONE, ...SHIP }, PS = Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)]));
  const rQ = (G, S, t) => { const T = S.filter(p => p.g === 'QB' && G.has(p)); return r3(corr(T.map(p => G.get(p).fm), T.map(p => p[t]))); };
  for (const [lab, M] of [['today', {}], ['hs 0', { hs: 0 }], ['hs 0.5', { hs: 0.5 }], ['hs 1.5', { hs: 1.5 }], ['youth 0', { ageY: 0 }], ['youth 0.5', { ageY: 0.5 }], ['class 0', { cls: 0 }]]) {
    const G = grade(base, rows, { ...PS, QB: toBase(M) }, 'QB');
    console.log('qbcheck', lab.padEnd(10), 'last av', rQ(G, finals, 'av'), 'cap', rQ(G, finals, 'cap'), '| earlier av', rQ(G, early, 'av'), 'cap', rQ(G, early, 'cap'), '| n', finals.filter(p => p.g === 'QB').length, early.filter(p => p.g === 'QB').length);
  }
  process.exit(0);
}
// --mock: the mock draft's expected pick (finishPool in cfb_teams.mjs) on the rebuilt boards: does the model's grade add
// to DraftTek's final board in predicting the slot? Model rank = the rank its FV implies on the consensus scale
// (consFV inverted: 2.7 exp((80 - FV) / 8.7)); ln xPick = w lnP(board rank) + (1 - w) lnP(model rank), lnP = BOARD_PICK;
// undrafted = 290. Scored on board-ranked last seasons (|ln pick - ln xPick|, and MAE for real top-100 picks), w chosen
// leaving one draft out (the model's order is mapped onto the class's board ranks, so only order counts); unranked draftees scored on the model rank against the board-depth fallback
if (process.argv.includes('--mock')) {
  const base = { ...ONE, ...SHIP }, PS = Object.fromEntries(Object.entries(POS_SHIP).map(([g, M]) => [g, toBase(M)]));
  const G = grade(base, rows, PS), lnP = r => { const l = Math.log(Math.max(1, r)); return 0.375 + 0.880 * l + 0.0132 * l * l; };
  const rMod = fv => fv <= 60 ? 2.7 * Math.exp((80 - fv) / 8.7) : 27 * Math.exp(FV_PEAK_SLOPE * (fv - 60)), UND = 290;   // consFV inverted
  const S = finals.filter(p => p.dt && G.has(p)), W = [1, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5, 0.3, 0];
  // the model's order put on the board's scale: within each class, the k-th best model grade gets the k-th best board rank
  const mr = new Map();
  for (const cl of new Set(S.map(p => p.last))) {
    const T = S.filter(p => p.last === cl), rk = T.map(p => p.dt).sort((a, b) => a - b);
    [...T].sort((a, b) => G.get(b).fm - G.get(a).fm).forEach((p, i) => mr.set(p, rk[i]));
  }
  const lx = (p, w) => w * lnP(p.dt) + (1 - w) * lnP(mr.get(p));
  const err = (T, w) => mean(T.map(p => Math.abs(Math.log(Math.min(p.pick ?? UND, UND)) - lx(p, w))));
  const mae = (T, w) => { const U = T.filter(p => p.pick && p.pick <= 100); return mean(U.map(p => Math.abs(p.pick - Math.exp(lx(p, w))))); };
  const classes = [...new Set(S.map(p => p.last))].sort(), res = { n: S.length, byW: {}, folds: [] };
  for (const w of W) res.byW[w] = { lnErr: r3(err(S, w)), mae100: r3(mae(S, w)) };
  let oof = 0, oofB = 0, oofM = 0, oofMB = 0;
  for (const cl of classes) {
    const tr = S.filter(p => p.last !== cl), te = S.filter(p => p.last === cl);
    const w = W.reduce((b, x) => err(tr, x) < err(tr, b) ? x : b, 1);
    res.folds.push({ draft: cl + 1, w, n: te.length, lnErr: r3(err(te, w)), lnErrBoard: r3(err(te, 1)) });
    oof += err(te, w) * te.length; oofB += err(te, 1) * te.length;
  }
  res.oos = { lnErr: r3(oof / S.length), lnErrBoard: r3(oofB / S.length) };
  // draftees with no board rank: model rank vs the board-depth fallback (600-deep boards x 1.3)
  const U = finals.filter(p => !p.dt && p.pick && G.has(p));
  res.unranked = { n: U.length, meanPick: r3(mean(U.map(p => p.pick))), lnErrModel: r3(mean(U.map(p => Math.abs(Math.log(p.pick) - lnP(rMod(G.get(p).fm)))))),
    lnErrDepth: r3(mean(U.map(p => Math.abs(Math.log(p.pick) - lnP(780))))) };
  console.log(JSON.stringify(res, null, 1));
  fs.writeFileSync(path.join(ROOT, 'data', 'cfb_mock_weight_backtest.json'), JSON.stringify({ asof: new Date().toISOString().slice(0, 10), method: 'node scripts/cfb_fv_refit.mjs --mock', ...res }, null, 1) + '\n');
  process.exit(0);
}
// ---- --wide: the refit on the 2014-22 classes ---------------------------------------------------------------------
// Multipliers count on today's weights (1 = the board today: SHIP, with the LB and TE overrides multiplying on top).
// Every stage holds out one class (a player's last college season, so one draft) at a time and scores the held-out
// class; the box-era production weight (prodBox) is a nuisance refit inside every training set, the baseline's too.
// Universes: all (last seasons + earlier seasons of players gone by 2023), last, earlier, pfn (rows from the 2019-22
// seasons, on PFN lines as the live board is) and box (2014-18 seasons). Targets: NFL AV a season, and draft capital.
//   screen    one driver at a time on a grid, the multiplier picked on the training classes
//   joint     every driver at once, shrunk toward today's weights, the penalty picked on three inner folds
//   groups    the joint fit within one family of drivers (age and runway, pedigree, team and schedule, frame and combine)
//   pos       position weights by empirical Bayes: each group's drivers refit within the position, then each
//             multiplier pulled toward the pooled one by tau^2 / (tau^2 + se^2) (se from a class jackknife, tau^2 the
//             spread across positions beyond that noise)
// --eval scores today's weights only (with --boxonly: the 2019-22 classes on box-score lines alone).
// node scripts/cfb_fv_refit.mjs --wide [--stage=screen,joint,groups,pos] -> data/cfb_fv_wide.json
// Result (Oct 21, 2026; 15,533 rows, 7,116 last seasons, 1,038 drafted; data/cfb_fv_wide.json): the stand-ins keep about
// 90% of PFN's r (--boxonly on 2019-22: AV .531 -> .489, draft slot .594 -> .523), and the Oct 14 pooled changes hold up
// on 2014-18, which they never saw (AV .445 / .432 -> .451 / .444, slot .503 / .491 -> .513 / .507). Shipped (SHIP):
// combine slope and cap x2.1, frame x1.4, breakout timing off, QB deep ball x.15. Refit jointly inside each training set,
// held out: AV +.013 / +.010, slot +.012 / +.010 on all rows, the PFN seasons alone +.012 / +.011 and +.013 / +.012,
// 8 of 10 classes. Not shipped: a smaller youth bonus (last seasons gain, underclassmen lose), team strength (gains on
// box seasons only), the full 25-driver joint fit (3 classes lose .05+), empirical-Bayes position weights (PFN seasons
// -.014). The LB and TE overrides stay: they lose on box seasons (pedigree fills in for box tackles at LB), win on PFN
// Rerun Oct 21 2026 after the NFL link fix (scripts/cfb_nflpos.mjs: drafted EDGEs listed as LB/DT had read as 0 AV;
// drafted 1,038 -> 1,116): today's weights score higher on the right outcomes (all rows AV .477 -> .503, slot .541 ->
// .564), and every screen and group pick matches the run above (smaller youth bonus again wins last seasons, loses
// underclassmen; nothing else moves past +/-.003). No weight changes.
if (BOX || process.argv.includes('--eval')) {
  const BASE = { ...ONE, ...SHIP }, t0 = Date.now();
  const abs = M => { const E = effective({ ...ONE, ...M }); return Object.fromEntries(KEYS.map(k => [k, (BASE[k] ?? 1) * E[k]])); };
  const posOf = (A, P = POS_SHIP) => Object.fromEntries(Object.entries(P).map(([g, Q]) => [g, { ...A, ...Object.fromEntries(Object.entries(Q).map(([k, v]) => [k, A[k] * v])) }]));
  const gradeM = (M, P = POS_SHIP, only = null) => { const A = abs(M); return grade(A, rows, posOf(A, P), only); };
  const ERA = { all: U, last: finals, earlier: early, pfn: U.filter(p => p.s >= 2019), box: U.filter(p => p.s < 2019) };
  const report = G => Object.fromEntries(Object.entries(ERA).filter(([, S]) => S.length).flatMap(([e, S]) => ['av', 'cap'].map(t => { const v = score(G, S, t); return [e + '_' + t, [r3(v.pooled), r3(v.within)]]; })));
  const byPos = (G, S, t = 'av') => score(G, S, t).byPos;
  // --eval --stage=cand runs the candidate stage on the PFN seasons alone (2019-22; parts in scripts/.cache/fvrefit/pfn_*)
  if (process.argv.includes('--eval') && !arg('stage').length) {
    if (process.argv.includes('--agecheck')) {
      // drafted players only (nflverse has birthdates for 99.7% of draftees, almost none for the rest): does real age
      // at the start of the final season say more about NFL AV than the board's grade (which reads age from years on
      // campus) or the draft slot? partial r of age with the AV residual, and its t clustered by class
      const dob = {}; for (const r of csv(fs.readFileSync(path.join(SP, 'players.csv'), 'utf8'))) if (r.pfr_id && r.birth_date) dob[r.pfr_id] = r.birth_date;
      const G = gradeM({});
      const D = finals.filter(p => p.pick && p.pfr && dob[p.pfr] && G.has(p)).map(p => ({ p, age: (Date.parse(p.s + '-09-01') - Date.parse(dob[p.pfr])) / 3.156e10, est: 17.9 + p.years, fv: G.get(p).fm }));
      const ols = (X, y) => { const k = X[0].length, A = Array.from({ length: k }, () => Array(k).fill(0)), b = Array(k).fill(0);
        X.forEach((x, i) => { for (let a = 0; a < k; a++) { b[a] += x[a] * y[i]; for (let c = 0; c < k; c++) A[a][c] += x[a] * x[c]; } });
        for (let i = 0; i < k; i++) { let m = i; for (let j = i + 1; j < k; j++) if (Math.abs(A[j][i]) > Math.abs(A[m][i])) m = j; [A[i], A[m]] = [A[m], A[i]]; [b[i], b[m]] = [b[m], b[i]];
          for (let j = 0; j < k; j++) if (j !== i) { const f = A[j][i] / A[i][i]; for (let c = 0; c < k; c++) A[j][c] -= f * A[i][c]; b[j] -= f * b[i]; } }
        return b.map((v, i) => v / A[i][i]); };
      const fe = d => G7.map(g => +(d.p.g === g));
      for (const [lab, ctl] of [['grade', d => [avOf(d.fv)]], ['grade + slot', d => [avOf(d.fv), Math.log(d.p.pick)]], ['slot', d => [Math.log(d.p.pick)]]]) {
        for (const [an, af] of [['age', d => d.age], ['age - estimate', d => d.age - d.est]]) {
          const X = D.map(d => [...fe(d), ...ctl(d), af(d)]), y = D.map(d => d.p.av), w = ols(X, y), res = y.map((v, i) => v - X[i].reduce((a, x, j) => a + x * w[j], 0));
          const X0 = D.map(d => [...fe(d), ...ctl(d)]), w0 = ols(X0, y), r0 = y.map((v, i) => v - X0[i].reduce((a, x, j) => a + x * w0[j], 0));
          // class-clustered t of the age coefficient via the gain in each class held out
          const byC = {}; D.forEach((d, i) => { (byC[d.p.last] ||= []).push(i); });
          const gains = Object.values(byC).map(ix => { const tr = D.map((_, i) => i).filter(i => !ix.includes(i)); const wa = ols(tr.map(i => X[i]), tr.map(i => y[i])), wb = ols(tr.map(i => X0[i]), tr.map(i => y[i]));
            return ix.reduce((a, i) => a + (y[i] - X0[i].reduce((s, x, j) => s + x * wb[j], 0)) ** 2 - (y[i] - X[i].reduce((s, x, j) => s + x * wa[j], 0)) ** 2, 0) / ix.length; });
          const m = mean(gains), se = sdv(gains) * Math.sqrt(gains.length / (gains.length - 1)) / Math.sqrt(gains.length);
          console.log(lab.padEnd(13), an.padEnd(15), 'n', D.length, 'coef AV/yr', r3(w.at(-1)), 'partial r', r3(corr(D.map(af), r0)), 'held-out MSE gain', r3(m), 't', r3(m / se), 'classes won', gains.filter(g => g > 0).length + '/' + gains.length);
        }
      }
      console.log('age sd', r3(sdv(D.map(d => d.age))), 'r(age, estimate)', r3(corr(D.map(d => d.age), D.map(d => d.est))));
      process.exit(0);
    }
    if (arg('recvcheck').length) {
      // --recvcheck=WR,TE: per position, each receiving depth term against the residual of NFL AV (and draft capital)
      // on today's grade (model FV, and FV with DraftTek blended in): partial r, and the held-out MSE gain of adding it
      // to a linear fit on avOf(FV), one class out at a time (t over classes)
      const G = gradeM({});
      const ols = (X, y) => { const k = X[0].length, M = Array.from({ length: k }, () => Array(k + 1).fill(0)); X.forEach((x, i) => { for (let a = 0; a < k; a++) { M[a][k] += x[a] * y[i]; for (let c = 0; c < k; c++) M[a][c] += x[a] * x[c]; } });
        for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) if (j !== i) { const f = M[j][i] / M[i][i]; for (let c = 0; c <= k; c++) M[j][c] -= f * M[i][c]; } return M.map((r, i) => r[k] / r[i]); };
      const R = {};
      for (const g of arg('recvcheck')) for (const [un, S0] of [['all', U], ['last', finals]]) for (const fk of ['fm', 'fc']) for (const t of ['av', 'cap']) {
        const S = S0.filter(p => p.g === g && G.has(p));
        for (const k of [...RECV_KEYS, ...GAME_KEYS]) {
          const x = S.map(p => p.cf[k]), f = S.map(p => avOf(G.get(p)[fk])), y = S.map(p => p[t]);
          const X1 = S.map((p, i) => [1, f[i], x[i]]), X0 = S.map((p, i) => [1, f[i]]), w0 = ols(X0, y), r0 = y.map((v, i) => v - w0[0] - w0[1] * f[i]);
          const gains = CLASSES.map(c => { const tr = S.map((p, i) => i).filter(i => S[i].last !== c), te = S.map((p, i) => i).filter(i => S[i].last === c);
            const a = ols(tr.map(i => X1[i]), tr.map(i => y[i])), b = ols(tr.map(i => X0[i]), tr.map(i => y[i]));
            return te.reduce((s, i) => s + (y[i] - b[0] - b[1] * f[i]) ** 2 - (y[i] - a[0] - a[1] * f[i] - a[2] * x[i]) ** 2, 0) / Math.max(1, te.length); });
          const m = mean(gains), se = sdv(gains) * Math.sqrt(gains.length / (gains.length - 1)) / Math.sqrt(gains.length);
          const key = [g, un, fk, t, k].join(' ');
          R[key] = { n: S.length, partial: r3(corr(x, r0)), coef: r3(ols(X1, y)[2]), gain: r3(m * 1000), t: r3(m / se), won: gains.filter(v => v > 0).length };
          if (fk === 'fm' || t === 'av') console.log(key.padEnd(26), JSON.stringify(R[key]));
        }
      }
      fs.writeFileSync(path.join(C, 'pfn_recvcheck.json'), JSON.stringify(R, null, 1));
      process.exit(0);
    }
    if (arg('candeval').length) {
      // a candidate set held fixed (no refit): within-position Spearman, drafted-only r and calibration by years on campus
      const G0 = gradeM({}); CANDW = Object.fromEntries(arg('candeval').map(x => x.split('=')).map(([k, v]) => [k, +v])); const G1 = gradeM({});
      const rk = xs => { const o = xs.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]), r = []; o.forEach(([, i], j) => r[i] = j); return r; };
      for (const [lab, G] of [['today', G0], ['cand', G1]]) {
        const sp = G7.map(g => { const T = U.filter(p => p.g === g && G.has(p)); return corr(rk(T.map(p => G.get(p).fm)), rk(T.map(p => p.av))); });
        const D = finals.filter(p => p.pick && G.has(p));
        console.log(lab, JSON.stringify(report(G)), 'spearman within', r3(mean(sp)), 'drafted r', r3(corr(D.map(p => G.get(p).fm), D.map(p => p.av))));
        if (lab === 'cand' && process.argv.includes('--swaps')) {
          // who the candidate moves into / out of the top 32 model FV a class (last seasons)
          const top = (G, c) => new Set(finals.filter(p => p.last === c && G.has(p)).sort((a, b) => G.get(b).fm - G.get(a).fm).slice(0, 32));
          const inn = [], out = [];
          for (const c of CLASSES) { const a = top(G0, c), b = top(G1, c); for (const p of b) if (!a.has(p)) inn.push(p); for (const p of a) if (!b.has(p)) out.push(p); }
          const desc = S => ({ n: S.length, av: r3(mean(S.map(p => p.av))), cap: r3(mean(S.map(p => p.cap))), years: r3(mean(S.map(p => p.years))), hs: r3(mean(S.map(p => p.hsRaw))), zPfn: r3(mean(S.map(p => p.zPfn))),
            acf: r3(mean(S.map(p => p.cr.acf ?? -1))), pos: Object.fromEntries(G7.map(g => [g, S.filter(p => p.g === g).length])) });
          console.log('swaps in ', JSON.stringify(desc(inn))); console.log('swaps out', JSON.stringify(desc(out)));
        }
        for (const y of [1, 2, 3, 4, 5]) { const T = U.filter(p => Math.min(5, Math.round(p.years)) === y && G.has(p)); console.log('  years', y, 'n', T.length, 'AV', r3(mean(T.map(p => p.av))), 'avOf FV', r3(mean(T.map(p => avOf(G.get(p).fm)))), 'r', r3(corr(T.map(p => G.get(p).fm), T.map(p => p.av)))); }
      }
      process.exit(0);
    }
    const G = gradeM({}), G0 = grade(ONE), Gp = gradeM({}, {});
    console.log('n', JSON.stringify(out.n), 'classes', CLASSES.join(','), 'grade ms', Date.now() - t0);
    console.log('today', JSON.stringify(report(G)));
    console.log('today byPos all av', JSON.stringify(byPos(G, U)), 'last av', JSON.stringify(byPos(G, finals)));
    console.log('pooled (no LB/TE overrides)', JSON.stringify(report(Gp)));
    console.log('before Oct 14 (ONE)', JSON.stringify(report(G0)));
    process.exit(0);
  }
  const W = { asof: new Date().toISOString().slice(0, 10), method: 'node scripts/cfb_fv_refit.mjs --wide', n: out.n, classes: CLASSES,
    rows: { all: U.length, last: finals.length, drafted: finals.filter(p => p.pick).length, pfn: ERA.pfn.length, box: ERA.box.length } };
  // stages can run as separate processes (--stage=joint ...): each writes its part, --stage=merge joins them
  const OUTW = path.join(ROOT, 'data', 'cfb_fv_wide.json'), PART = st => path.join(C, `${WIDE ? 'wide' : 'pfn'}_${st}.json`);
  const stages = arg('stage').length ? arg('stage') : ['screen', 'joint', 'groups', 'pos'];
  if (stages.includes('merge')) {
    for (const st of ['base', 'screen', 'joint', 'groups', 'pos', 'set', 'fixed', 'cand']) if (fs.existsSync(PART(st))) Object.assign(W, JSON.parse(fs.readFileSync(PART(st), 'utf8')));
    fs.writeFileSync(OUTW, JSON.stringify(W, null, 1) + '\n'); console.log('merged', Object.keys(W).join(' ')); process.exit(0);
  }
  const save = (st, keys) => fs.writeFileSync(PART(st), JSON.stringify(Object.fromEntries(keys.map(k => [k, W[k]]))));
  const obj = (G, S) => { const v = score(G, S); return v.pooled + v.within; };
  // coordinate search on multipliers of today's weights, shrunk toward 1 (composite multipliers relative to production)
  function fitW(S, lam, keys, M0 = {}) {
    let M = { ...M0 }; for (const k of keys) M[k] ??= 1;
    const val = M => { const E = effective({ ...ONE, ...M }); return obj(gradeM(M), S) - lam * keys.reduce((a, k) => a + (NUIS.includes(k) ? 0 : (E[k] - 1) ** 2), 0); };
    let best = val(M);
    for (const step of [0.5, 0.25, 0.1]) for (let sw = 0; sw < 3; sw++) {
      let moved = false;
      for (const k of keys) for (const dir of [1, -1]) {
        const T = { ...M, [k]: Math.max(-1, Math.min(4, M[k] + dir * step * (PROD.includes(k) ? 1 : mean(PROD.map(q => M[q] ?? 1))))) }, v = val(T);
        if (v > best + 1e-6) { M = T; best = v; moved = true; }
      }
      if (!moved) break;
    }
    return M;
  }
  const NUIS = KEYS.filter(k => k.endsWith('Box'));
  const pbOf = S => NUIS.length ? Object.fromEntries(NUIS.map(k => [k, fitW(S, 0, NUIS)[k]])) : {};
  const folds = CLASSES.map(c => ({ c, train: U.filter(p => p.last !== c), test: U.filter(p => p.last === c) }));
  for (const f of folds) f.nuis = pbOf(f.train);
  W.nuisance = Object.fromEntries(NUIS.map(k => [k, folds.map(f => r3(f.nuis[k]))]));
  // out-of-sample grades: each class graded by the multipliers fit without it
  const oofOf = Ms => { const o = new Map(); folds.forEach((f, i) => { const G = gradeM(Ms[i]); for (const p of f.test) o.set(p, G.get(p)); }); return o; };
  const BASEOOF = oofOf(folds.map(f => f.nuis));
  W.today = report(BASEOOF);
  const gainVs = G => Object.fromEntries(Object.entries(report(G)).map(([k, v]) => [k, [r3(v[0] - W.today[k][0]), r3(v[1] - W.today[k][1])]]));
  const foldGain = G => folds.map(f => r3(obj(G, f.test) - obj(BASEOOF, f.test)));
  console.error('wide: folds ready', ((Date.now() - t0) / 1000).toFixed(0) + 's', 'nuisance', JSON.stringify(W.nuisance));
  save('base', ['today', 'nuisance']);
  const FAM = { age: ['ageY', 'ageO', 'cls', 'years', 'snap'], pedigree: ['hs', 'nonBlue', 'brk'], team: ['team', 'sos'], body: ['frame', 'ath'],
    production: PROD, badges: KEYS.filter(k => k.startsWith('b_')) };
  const DRV = KEYS.filter(k => k !== 'age' && !NUIS.includes(k));
  if (stages.includes('screen')) {
    const grid = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3];
    W.screen = {};
    for (const k of DRV) {
      const Gs = new Map();     // per fold nuisance: grade cache by (prodBox, v)
      const gOf = (nu, v) => { const key = JSON.stringify(nu) + '|' + v; if (!Gs.has(key)) Gs.set(key, gradeM({ ...nu, [k]: v })); return Gs.get(key); };
      const pick = folds.map(f => grid.reduce((b, v) => obj(gOf(f.nuis, v), f.train) > obj(gOf(f.nuis, b), f.train) + 1e-9 ? v : b, 1));
      const oof = new Map(); folds.forEach((f, i) => { const G = gOf(f.nuis, pick[i]); for (const p of f.test) oof.set(p, G.get(p)); });
      W.screen[k] = { folds: pick, gain: gainVs(oof), foldGain: foldGain(oof) };
      console.log('screen', k.padEnd(14), JSON.stringify(pick), JSON.stringify({ all: W.screen[k].gain.all_av, cap: W.screen[k].gain.all_cap, pfn: W.screen[k].gain.pfn_av, pfnCap: W.screen[k].gain.pfn_cap }), ((Date.now() - t0) / 1000).toFixed(0) + 's');
    }
    save('screen', ['screen']);
  }
  // nested: the penalty from three inner folds (classes dealt round-robin), then the fit on the whole training set
  const LAMW = [0.003, 0.01, 0.03, 0.1];
  function cvW(keys, label) {
    const Ms = [], lams = [];
    for (const f of folds) {
      const cs = CLASSES.filter(c => c !== f.c), inner = [0, 1, 2].map(j => cs.filter((c, i) => i % 3 === j));
      let bl = LAMW[0], bv = -Infinity;
      for (const lam of LAMW) {
        let v = 0;
        for (const hold of inner) { const tr = f.train.filter(p => !hold.includes(p.last)), te = f.train.filter(p => hold.includes(p.last)); v += obj(gradeM(fitW(tr, lam, [...keys, ...NUIS], f.nuis)), te); }
        if (v > bv) { bv = v; bl = lam; }
      }
      const M = fitW(f.train, bl, [...keys, ...NUIS], f.nuis); Ms.push(M); lams.push(bl);
      console.error(label, 'class', f.c, 'lam', bl, JSON.stringify(Object.fromEntries(keys.map(k => [k, r3(effective({ ...ONE, ...M })[k])]))), ((Date.now() - t0) / 1000).toFixed(0) + 's');
    }
    const oof = oofOf(Ms), res = { keys, lams, gain: gainVs(oof), foldGain: foldGain(oof), multipliers: {}, revert: {} };
    const lamAll = [...lams].sort((a, b) => a - b)[lams.length >> 1], MA = fitW(U, lamAll, [...keys, ...NUIS], pbOf(U)), EA = effective({ ...ONE, ...MA });
    for (const k of keys) {
      res.multipliers[k] = { all: r3(EA[k]), folds: Ms.map(M => r3(effective({ ...ONE, ...M })[k])) };
      // put back at today's weight in every fold's fit: negative = the change helps out of sample
      const o = oofOf(Ms.map(M => ({ ...M, [k]: 1 })));
      res.revert[k] = Object.fromEntries(['all_av', 'all_cap', 'pfn_av', 'pfn_cap'].map(e => { const a = report(o)[e], b = report(oof)[e]; return [e, [r3(a[0] - b[0]), r3(a[1] - b[1])]]; }));
    }
    console.log(label, JSON.stringify({ all: res.gain.all_av, cap: res.gain.all_cap, pfn: res.gain.pfn_av, pfnCap: res.gain.pfn_cap, foldGain: res.foldGain }));
    for (const k of keys) console.log('  ', k.padEnd(14), JSON.stringify(res.multipliers[k]), JSON.stringify(res.revert[k]));
    return res;
  }
  if (stages.includes('joint')) { W.joint = cvW(DRV, 'joint'); save('joint', ['joint']); }
  if (stages.includes('groups')) { W.groups = {}; for (const [fam, keys] of Object.entries(FAM)) { W.groups[fam] = cvW(keys, 'group ' + fam); save('groups', ['groups']); } }
  if (stages.includes('pos')) {
    // position multipliers on top of the pooled weights (today's, without the LB and TE overrides); within-position r
    const common = ['nonBlue', 'hs', 'team', 'ageY', 'ageO', 'cls', 'snap', 'brk', 'ath', 'frame', 'years'];
    const rPos = (G, S, g, t = 'av') => { const T = S.filter(p => p.g === g && G.has(p)); return corr(T.map(p => G.get(p).fm), T.map(p => p[t])); };
    const posGrade = (g, Q, nu) => gradeM(nu, { [g]: Q }, g);
    function fitPos(g, S, keys, nu, lam = 0.003) {
      let Q = Object.fromEntries(keys.map(k => [k, 1]));
      const val = Q => rPos(posGrade(g, Q, nu), S, g) - lam * keys.reduce((a, k) => a + (Q[k] - 1) ** 2, 0);
      let best = val(Q);
      for (const step of [0.5, 0.25, 0.1]) for (let sw = 0; sw < 3; sw++) {
        let moved = false;
        for (const k of keys) for (const dir of [1, -1]) { const T = { ...Q, [k]: Math.max(0, Math.min(4, Q[k] + dir * step)) }, v = val(T); if (v > best + 1e-6) { Q = T; best = v; moved = true; } }
        if (!moved) break;
      }
      return Q;
    }
    // empirical Bayes inside a training set: raw position fits, class-jackknife se, tau^2 across positions, shrink
    function ebFit(S, nu) {
      const raw = {}, se2 = {};
      for (const g of G7) {
        const keys = [...common, ...(POS_KEYS[g] || [])], Sg = S.filter(p => p.g === g), cs = [...new Set(Sg.map(p => p.last))];
        raw[g] = fitPos(g, Sg, keys, nu);
        const jk = cs.map(c => fitPos(g, Sg.filter(p => p.last !== c), keys, nu)), J = jk.length;
        se2[g] = Object.fromEntries(keys.map(k => { const m = mean(jk.map(q => q[k])); return [k, (J - 1) / J * jk.reduce((a, q) => a + (q[k] - m) ** 2, 0)]; }));
      }
      const tau2 = {}, Q = {};
      for (const k of new Set(G7.flatMap(g => Object.keys(raw[g])))) {
        const gs = G7.filter(g => k in raw[g]); if (gs.length < 3) { tau2[k] = 0; continue; }
        const th = gs.map(g => raw[g][k]), m = mean(th);
        tau2[k] = Math.max(0, mean(th.map(x => (x - m) ** 2)) - mean(gs.map(g => se2[g][k])));
      }
      for (const g of G7) Q[g] = Object.fromEntries(Object.entries(raw[g]).map(([k, v]) => { const B = tau2[k] / (tau2[k] + se2[g][k] + 1e-9); return [k, r3(1 + B * (v - 1))]; }));
      return { Q, raw, se2, tau2 };
    }
    const fitsEB = folds.map(f => { const e = ebFit(f.train, f.nuis); console.error('pos EB class', f.c, ((Date.now() - t0) / 1000).toFixed(0) + 's'); return e; });
    const oofEB = new Map(), oofPool = new Map();
    folds.forEach((f, i) => { const A = gradeM(f.nuis, fitsEB[i].Q), B = gradeM(f.nuis, {}); for (const p of f.test) { oofEB.set(p, A.get(p)); oofPool.set(p, B.get(p)); } });
    const full = ebFit(U, pbOf(U));
    W.pos = { today: W.today, pooled: report(oofPool), eb: report(oofEB), gainEB: gainVs(oofEB), gainPooled: gainVs(oofPool), foldGainEB: foldGain(oofEB),
      byPos: Object.fromEntries(G7.map(g => [g, { today: [r3(rPos(BASEOOF, U, g)), r3(rPos(BASEOOF, U, g, 'cap'))], pooled: [r3(rPos(oofPool, U, g)), r3(rPos(oofPool, U, g, 'cap'))], eb: [r3(rPos(oofEB, U, g)), r3(rPos(oofEB, U, g, 'cap'))] }])),
      multipliers: full.Q, raw: Object.fromEntries(G7.map(g => [g, Object.fromEntries(Object.entries(full.raw[g]).map(([k, v]) => [k, [r3(v), r3(Math.sqrt(full.se2[g][k]))]]))])),
      tau: Object.fromEntries(Object.entries(full.tau2).map(([k, v]) => [k, r3(Math.sqrt(v))])) };
    console.log('pos', JSON.stringify({ gainEB: { all: W.pos.gainEB.all_av, cap: W.pos.gainEB.all_cap, pfn: W.pos.gainEB.pfn_av }, gainPooled: { all: W.pos.gainPooled.all_av, cap: W.pos.gainPooled.all_cap }, foldGainEB: W.pos.foldGainEB }));
    console.log('pos byPos', JSON.stringify(W.pos.byPos));
    console.log('pos multipliers', JSON.stringify(W.pos.multipliers), 'tau', JSON.stringify(W.pos.tau));
    save('pos', ['pos']);
  }
  // set: the joint fit on a chosen subset (--set=k,...), scored the same nested way; fixed: --ship=k=v,... applied to
  // every class as is (no refit, so not out of sample for the choice of set), by era, fold and position, with the
  // LB and TE overrides each put back one at a time
  if (stages.includes('set')) { W.set = cvW(arg('set'), 'set'); save('set', ['set']); }
  // cand: each new driver alone at a weight per SD picked on the training classes, scored on the held-out class;
  // --cand=k,k|POS limits the list, --candbase=k=w,... holds earlier picks fixed underneath
  if (stages.includes('cand')) {
    const grid = arg('grid').length ? arg('grid').map(Number) : [-0.2, -0.12, -0.06, -0.03, 0, 0.03, 0.06, 0.12, 0.2];
    const base = Object.fromEntries(arg('candbase').map(x => x.split('=')).map(([k, v]) => [k, +v]));
    const list = arg('cand').length ? arg('cand') : [...CAND_KEYS, ...CAND_KEYS.flatMap(k => G7.map(g => k + '|' + g))];
    CANDW = { ...base };
    const B = oofOf(folds.map(f => f.nuis));
    const bScore = G => { const v = report(G); return v; };
    const b0 = bScore(B), objF = (G, S) => obj(G, S);
    W.cand = { base, results: {} };
    let fwdNu = null;
    for (const k of list) {
      const Gs = new Map();
      const gOf = (nu, v) => { const key = JSON.stringify(nu) + '|' + v; if (!Gs.has(key)) { CANDW = { ...base, [k]: v }; Gs.set(key, gradeM(nu)); CANDW = { ...base }; } return Gs.get(key); };
      const pick = folds.map(f => grid.reduce((b, v) => objF(gOf(f.nuis, v), f.train) > objF(gOf(f.nuis, b), f.train) + 1e-9 ? v : b, 0));
      const oof = new Map(); folds.forEach((f, i) => { const G = gOf(f.nuis, pick[i]); for (const p of f.test) oof.set(p, G.get(p)); });
      const fg = folds.map(f => r3(objF(oof, f.test) - objF(B, f.test))), m = mean(fg), se = sdv(fg) * Math.sqrt(fg.length / (fg.length - 1)) / Math.sqrt(fg.length);
      const v = report(oof), gain = Object.fromEntries(Object.entries(v).map(([e, x]) => [e, [r3(x[0] - b0[e][0]), r3(x[1] - b0[e][1])]]));
      W.cand.results[k] = { folds: pick, gain, foldGain: fg, won: fg.filter(x => x > 0).length, t: r3(m / se) };
      // Oct 31 2026 gates on top of the fold t: within-position Spearman (held out), the top 32 model FV a class (last
      // seasons, AV and capital, held out), and forward (weight picked on the 2014-18 classes, 2019-23 graded)
      if (process.argv.includes('--gates')) {
        const rk = xs => { const o = xs.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]), r = Array(xs.length); for (let i = 0; i < o.length;) { let j = i; while (j + 1 < o.length && o[j + 1][0] === o[i][0]) j++; for (let q = i; q <= j; q++) r[o[q][1]] = (i + j) / 2; i = j + 1; } return r; };
        const spw = G => mean(G7.map(g => { const T = U.filter(p => p.g === g && G.has(p)); return corr(rk(T.map(p => G.get(p).fm)), rk(T.map(p => p.av))); }));
        const top = (G, c) => finals.filter(p => p.last === c && G.has(p)).sort((a, b) => G.get(b).fm - G.get(a).fm).slice(0, 32);
        const t32 = t => { const d = CLASSES.map(c => mean(top(oof, c).map(p => p[t])) - mean(top(B, c).map(p => p[t]))); const mm = mean(d), s2 = sdv(d) / Math.sqrt(d.length); return [r3(mm), r3(mm / s2), d.filter(x => x > 1e-9).length]; };
        const tr = U.filter(p => p.last <= 2018), te = U.filter(p => p.last >= 2019), nu = fwdNu ??= pbOf(tr);
        const wf = grid.reduce((b, v) => objF(gOf(nu, v), tr) > objF(gOf(nu, b), tr) + 1e-9 ? v : b, 0), F1 = gOf(nu, wf), F0 = gOf(nu, 0);
        const cs = CLASSES.filter(c => c >= 2019), fs1 = score(F1, te), fs0 = score(F0, te);
        const fwd = { w: wf, pooled: r3(fs1.pooled - fs0.pooled), within: r3(fs1.within - fs0.within), cap: r3(score(F1, te, 'cap').within - score(F0, te, 'cap').within),
          top32: [r3(mean(cs.map(c => mean(top(F0, c).map(p => p.av))))), r3(mean(cs.map(c => mean(top(F1, c).map(p => p.av)))))] };
        Object.assign(W.cand.results[k], { spearman: [r3(spw(B)), r3(spw(oof))], top32av: t32('av'), top32cap: t32('cap'), forward: fwd });
        console.log('   gates', k, JSON.stringify({ spearman: W.cand.results[k].spearman, top32av: W.cand.results[k].top32av, top32cap: W.cand.results[k].top32cap, forward: fwd }));
      }
      console.log('cand', k.padEnd(16), JSON.stringify(pick), JSON.stringify({ all: gain.all_av, cap: gain.all_cap, pfn: gain.pfn_av, box: gain.box_av, last: gain.last_av, earlier: gain.earlier_av }), 'won', W.cand.results[k].won, 't', W.cand.results[k].t, ((Date.now() - t0) / 1000).toFixed(0) + 's');
    }
    save('cand', ['cand']);
  }
  // ---- rw: the Oct 26 2026 driver re-weight (Noah: "check FV drivers for every sport and re-weight based on outcome
  // correlation"). Every live driver audited against NFL outcomes, then three refits, each scored one class out:
  //   A  every live multiplier at once, no shrink (--rw=A)
  //   B  every live multiplier at once, ridge toward today's weights, the penalty picked on three inner folds of the
  //      training classes (as `joint`, with heavier penalties allowed, up to 1) (--rw=B)
  //   C  one driver at a time on a grid, picked on the training classes; BH at q .10 over drivers on the per-class
  //      primary-metric gains, then the passing drivers' per-fold picks together as a set (--rw=C)
  // Each also refits on the 2014-18 classes and grades 2019-23 (forward). Parts run as separate processes
  // (--folds=0,1,..,fwd for A and B, --keys=... for C) into scripts/.cache/fvrefit/wide_rw_*.json; --rw=report audits
  // the drivers, reads the parts, applies the gate and writes data/cfb_fv_reweight.json.
  // Gate: primary metric (within-position r with NFL AV, all rows) paired t >= 2 and 8 of 10 classes; within-position
  // r with draft capital and both on the PFN seasons no worse held out; top 32 a class (last seasons) no worse on AV and
  // capital; forward test no worse; calibration (realized AV on avOf(FV) slope, band means) unchanged.
  // Result (Oct 26 2026, against the SHIP of that morning, athCap 2.1): A fails (within AV +.001 t .14 6/10, PFN seasons
  // -.008 1/5, top 32 AV 3.30 -> 3.23), B fails (inner folds pick lambda .003-.01, i.e. barely shrunk; +.000 t -.03,
  // top 32 3.30 -> 3.22). C: BH passes athCap (x1.5, t 3.7 10/10), years (x0, t 3.4 9/10) and TE catcher (x.25, t 3.1
  // 8/10); the three together fail the top 32 (3.30 -> 3.22: years 0 lifts sixth-year players, as on Oct 25). athCap
  // alone passes every check (top 32 3.303 -> 3.310, forward +.001 / +.002, calibration slope .844 -> .841) and ships;
  // TE catcher alone gains within position but loses pooled r (-.001 on every universe) and the top 32: kept
  // node scripts/cfb_fv_refit.mjs --wide --stage=rw --rw=A --folds=0,1,2 (...B, C --keys=...), then --rw=report [--cset=k,...]
  if (stages.includes('rw')) {
    const RW = arg('rw')[0] || 'report', FSEL = arg('folds'), KSEL = arg('keys');
    const LIVE = DRV.filter(k => (BASE[k] ?? 1) !== 0);      // brk is off (FV_BREAK_W 0): a multiplier on 0 can't move it
    const fwd = { c: 'fwd', train: U.filter(p => p.last <= 2018), test: U.filter(p => p.last >= 2019) };
    const ALLF = fwd.train.length ? [...folds, fwd] : folds, fIdx = f => f.c === 'fwd' ? 'fwd' : String(folds.indexOf(f));
    const nuisOf = f => f.nuis ??= pbOf(f.train);
    const sel = FSEL.length ? ALLF.filter(f => FSEL.includes(fIdx(f))) : ALLF;
    const LAMB = [0.003, 0.01, 0.03, 0.1, 0.3, 1];
    const rwPart = tag => path.join(C, `${WIDE ? 'wide' : 'pfn'}_rw_${tag}.json`);
    const tst = d => { d = d.filter(x => x != null && isFinite(x)); const m = mean(d), se = sdv(d) * Math.sqrt(d.length / Math.max(1, d.length - 1)) / Math.sqrt(d.length);
      return { gain: r3(m), t: r3(se ? m / se : 0), won: d.filter(x => x > 1e-9).length + '/' + d.length }; };
    if (RW === 'A' || RW === 'B') {
      const o = {};
      for (const f of sel) {
        const nu = nuisOf(f); let lam = 0;
        if (RW === 'B') {
          const cs = [...new Set(f.train.map(p => p.last))].sort(), inner = [0, 1, 2].map(j => cs.filter((c, i) => i % 3 === j));
          let bv = -Infinity; const vs = {};
          for (const l of LAMB) {
            let v = 0; for (const hold of inner) { const tr = f.train.filter(p => !hold.includes(p.last)), te = f.train.filter(p => hold.includes(p.last)); v += obj(gradeM(fitW(tr, l, [...LIVE, ...NUIS], nu)), te); }
            vs[l] = r3(v); if (v > bv) { bv = v; lam = l; }
          }
          console.error('B fold', fIdx(f), 'inner', JSON.stringify(vs));
        }
        const M = fitW(f.train, lam, [...LIVE, ...NUIS], nu);
        o[fIdx(f)] = { lam, M };
        console.error(RW, 'fold', fIdx(f), 'lam', lam, JSON.stringify(Object.fromEntries(LIVE.map(k => [k, r3(effective({ ...ONE, ...M })[k])]))), ((Date.now() - t0) / 1000).toFixed(0) + 's');
        fs.writeFileSync(rwPart(RW + '_' + (FSEL.join('-') || 'all')), JSON.stringify(o));
      }
      process.exit(0);
    }
    if (RW === 'C') {
      const grid = [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3], o = {};
      for (const k of KSEL.length ? KSEL : LIVE) {
        const Gs = new Map(), gOf = (nu, v) => { const key = JSON.stringify(nu) + '|' + v; if (!Gs.has(key)) Gs.set(key, gradeM({ ...nu, [k]: v })); return Gs.get(key); };
        o[k] = Object.fromEntries(ALLF.map(f => [fIdx(f), grid.reduce((b, v) => obj(gOf(nuisOf(f), v), f.train) > obj(gOf(nuisOf(f), b), f.train) + 1e-9 ? v : b, 1)]));
        console.error('C', k, JSON.stringify(o[k]), ((Date.now() - t0) / 1000).toFixed(0) + 's');
        fs.writeFileSync(rwPart('C_' + (KSEL.join('-') || 'all')), JSON.stringify(o));
      }
      process.exit(0);
    }
    // ---- report ----
    const R = { asof: new Date().toISOString().slice(0, 10), method: 'node scripts/cfb_fv_refit.mjs --wide --stage=rw (--rw=A|B|C parts, then --rw=report)', rows: W.rows, classes: CLASSES, today: W.today };
    const avInv = a => { if (a <= 0) return 20; for (let i = 1; i < AV_BY_FV.length; i++) { const [f0, a0] = AV_BY_FV[i - 1], [f1, a1] = AV_BY_FV[i]; if (a <= a1) return f0 + (f1 - f0) * (a - a0) / (a1 - a0); } return 80 + (a - 10.1) * 2; };
    const rk = xs => { const o = xs.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]), r = Array(xs.length); for (let i = 0; i < o.length;) { let j = i; while (j + 1 < o.length && o[j + 1][0] === o[i][0]) j++; for (let q = i; q <= j; q++) r[o[q][1]] = (i + j) / 2; i = j + 1; } return r; };
    const spear = (x, y) => corr(rk(x), rk(y));
    const nuU = pbOf(U), AUD = [...LIVE.filter(k => k !== 'athCap'), 'brk'];
    // terms at today's weights (brk at its old timing weights, for the univariate read only)
    REC_TERMS = true;
    const Gb = gradeM(nuU), Tb = new Map(rows.map(p => [p, { ...p._t, comp: p._comp }]));
    const A1 = { ...abs(nuU), brk: 1 }; grade(A1, rows, posOf(A1)); const Tu = new Map(rows.map(p => [p, p._t]));
    REC_TERMS = false;
    const tv = (T, p, k) => T.get(p)?.[k] ?? 0;
    const yAv = new Map(U.map(p => [p, avInv(p.av)])), yCap = new Map(U.map(p => [p, avInv(p.cap)]));
    // FV points per composite SD by position (slope of model FV on the pool-standardized composite)
    const poolZ = new Map(); for (const P of Object.values(POOLS)) { const m = mean(P.map(p => Tb.get(p).comp)), sd = sdv(P.map(p => Tb.get(p).comp)); for (const p of P) poolZ.set(p, [(Tb.get(p).comp - m) / sd, sd, m]); }
    const fvPerSd = Object.fromEntries(G7.map(g => { const S = U.filter(p => p.g === g && Gb.has(p)), x = S.map(p => poolZ.get(p)[0]), y = S.map(p => Gb.get(p).fm), mx = mean(x), my = mean(y);
      return [g, x.reduce((a, v, i) => a + (v - mx) * (y[i] - my), 0) / x.reduce((a, v) => a + (v - mx) ** 2, 0)]; }));
    R.fvPerCompSd = Object.fromEntries(Object.entries(fvPerSd).map(([g, v]) => [g, r3(v)]));
    // partial: outcome FV on every term at once, position fixed effects, all rows (ridge 1e-6 for the empty columns)
    const ols = (X, y) => { const k = X[0].length, A = Array.from({ length: k }, (_, i) => Array.from({ length: k + 1 }, (_, j) => j === i ? 1e-6 : 0));
      X.forEach((x, n) => { for (let a = 0; a < k; a++) { if (!x[a]) continue; A[a][k] += x[a] * y[n]; for (let c = 0; c < k; c++) A[a][c] += x[a] * x[c]; } });
      for (let i = 0; i < k; i++) { let m = i; for (let j = i + 1; j < k; j++) if (Math.abs(A[j][i]) > Math.abs(A[m][i])) m = j; [A[i], A[m]] = [A[m], A[i]];
        for (let j = 0; j < k; j++) if (j !== i && A[j][i]) { const f = A[j][i] / A[i][i]; for (let c = i; c <= k; c++) A[j][c] -= f * A[i][c]; } }
      return A.map((r, i) => r[k] / r[i]); };
    const XS = U.filter(p => Tu.has(p)), FE = G7.map(g => p => +(p.g === g)), cols = [...AUD.flatMap(k => k === 'prod' ? [] : [k])];
    const Xm = XS.map(p => [...FE.map(f => f(p)), ...cols.map(k => tv(Tu, p, k))]);
    const partial = {};
    for (const [tn, Y] of [['av', yAv], ['cap', yCap]]) {
      const y = XS.map(p => Y.get(p)), b = ols(Xm, y), sy = sdv(y);
      cols.forEach((k, j) => {
        const x = XS.map(p => tv(Tu, p, k)), nz = x.filter(v => v !== 0).length; if (nz < 30) return;
        const Xo = Xm.map(r => r.filter((_, i) => i !== FE.length + j)), bo = ols(Xo, y), ro = y.map((v, i) => v - Xo[i].reduce((a, q, c) => a + q * bo[c], 0));
        const bx = ols(Xo, x), rx = x.map((v, i) => v - Xo[i].reduce((a, q, c) => a + q * bx[c], 0));
        (partial[k] ||= {})[tn] = { beta: r3(b[FE.length + j] * sdv(x) / sy), partial: r3(corr(rx, ro)) };
      });
    }
    // drop-one: each driver at 0 in every class (no refit), the per-class change in the primary metric
    const perClass = (O, O0, S0 = U, filt = () => true) => Object.fromEntries(['av', 'cap'].map(t => [t, tst(folds.map(f => { const S = f.test.filter(filt); return S.length < 200 ? null : score(O, S, t).within - score(O0, S, t).within; }))]));
    const audit = {};
    for (const k of AUD) {
      const o = audit[k] = {};
      // today's weight as it acts: the term's SD over the rows that carry it, as a share of the composite SD and in FV points
      const S = U.filter(p => Tb.has(p) && p.g && (k.startsWith('prod_') || k.startsWith('b_') ? k.split('_')[1] === p.g : true));
      const xs = S.filter(p => tv(Tb, p, k) !== 0);
      o.coverage = r3(xs.length / Math.max(1, S.length));
      if (['frame', 'years'].includes(k)) o.fvPerSd = r3(sdv(xs.map(p => tv(Tb, p, k))));
      else { const sh = xs.map(p => (tv(Tb, p, k) - 0) / poolZ.get(p)[1]); o.compSdShare = r3(sdv(sh)); o.fvPerSd = r3(mean(xs.map(p => fvPerSd[p.g])) * sdv(sh)); }
      o.weight = { brk: 'FV_BREAK_W 0 (off)', ath: 'FV_ATH.w .36 cap .42', snap: 'FV_SNAP .032 cap .048', ageO: 'FV_AGE.oldScale .5', frame: 'FRAME_W 1.4', years: 'FV_YEARS_W .5', b_QB_deep: '.03' }[k] ?? 'x1 of today';
      // univariate, within position (pooled over positions where it varies): Pearson and Spearman with the outcome FV
      for (const [tn, Y] of [['av', yAv], ['cap', yCap]]) {
        const ps = [], ss = [];
        for (const g of G7) { const T = U.filter(p => p.g === g && Tu.has(p)), x = T.map(p => tv(Tu, p, k)); if (new Set(x).size < 3) continue; const y = T.map(p => Y.get(p)); ps.push(corr(x, y)); ss.push(spear(x, y)); }
        o['uni_' + tn] = { pearson: r3(mean(ps)), spearman: r3(mean(ss)) };
      }
      o.partial = partial[k] ?? null;
      if (k !== 'brk') { const Od = oofOf(folds.map(f => ({ ...f.nuis, [k]: 0, ...(k === 'ath' ? { athCap: 0 } : {}) }))); o.dropOne = { all: perClass(Od, BASEOOF), pfn: perClass(Od, BASEOOF, U, p => p.s >= 2019) }; }
      console.error('audit', k, JSON.stringify(o));
    }
    R.audit = audit;
    // ---- candidates ----
    const readParts = c => { const o = {}; for (const f of fs.readdirSync(C).filter(f => f.startsWith(`${WIDE ? 'wide' : 'pfn'}_rw_${c}_`))) Object.assign(o, JSON.parse(fs.readFileSync(path.join(C, f), 'utf8'))); return o; };
    const top = (G, c, n = 32) => finals.filter(p => p.last === c && G.has(p)).sort((a, b) => G.get(b).fm - G.get(a).fm).slice(0, n);
    const calib = O => { const S = U.filter(p => O.has(p)), x = S.map(p => avOf(O.get(p).fm)), y = S.map(p => p.av), mx = mean(x), my = mean(y);
      const slope = x.reduce((a, v, i) => a + (v - mx) * (y[i] - my), 0) / x.reduce((a, v) => a + (v - mx) ** 2, 0);
      const bands = Object.fromEntries([[20, 40], [40, 45], [45, 50], [50, 55], [55, 60], [60, 81]].map(([lo, hi]) => { const T = S.filter(p => O.get(p).fm >= lo && O.get(p).fm < hi); return [lo + '-' + hi, { n: T.length, av: r3(mean(T.map(p => p.av))), avOf: r3(mean(T.map(p => avOf(O.get(p).fm)))) }]; }));
      return { slope: r3(slope), bands }; };
    const evalSet = (Ms, fM) => {
      const O = oofOf(Ms), e = { gain: gainVs(O) };
      e.primary = tst(folds.map(f => score(O, f.test, 'av').within - score(BASEOOF, f.test, 'av').within));
      e.objective = tst(folds.map(f => obj(O, f.test) - obj(BASEOOF, f.test)));
      e.classes = { all: perClass(O, BASEOOF), pfn: perClass(O, BASEOOF, U, p => p.s >= 2019) };
      for (const t of ['av', 'cap']) { const a = CLASSES.map(c => mean(top(O, c).map(p => p[t]))), b = CLASSES.map(c => mean(top(BASEOOF, c).map(p => p[t])));
        e['top32_' + t] = { today: r3(mean(b)), cand: r3(mean(a)), ...tst(a.map((v, i) => v - b[i])) }; }
      e.calib = { today: calib(BASEOOF), cand: calib(O) };
      if (fM) {
        const G1 = gradeM(fM), G0 = gradeM(nuisOf(fwd)), T = fwd.test;
        e.forward = Object.fromEntries(['av', 'cap'].flatMap(t => [['all_' + t, r3(score(G1, T, t).within - score(G0, T, t).within)], ['pfn_' + t, r3(score(G1, T.filter(p => p.s >= 2019), t).within - score(G0, T.filter(p => p.s >= 2019), t).within)]]));
        const cs = [2019, 2020, 2021, 2022, 2023]; e.forward.top32_av = [r3(mean(cs.map(c => mean(top(G0, c).map(p => p.av))))), r3(mean(cs.map(c => mean(top(G1, c).map(p => p.av)))))];
      }
      const c = e.classes, n8 = s => +s.won.split('/')[0] >= 8;
      e.pass = { primary: e.primary.t >= 2 && n8(e.primary), cap: c.all.cap.gain > 0 && c.all.cap.t >= 2, pfn: c.pfn.av.gain > 0 && c.pfn.cap.gain > 0, top32: e.top32_av.gain >= 0 && e.top32_cap.gain >= 0, forward: e.forward ? e.forward.all_av >= 0 && e.forward.all_cap >= 0 : null };
      e.ship = Object.values(e.pass).every(v => v !== false);
      return e;
    };
    const spread = (vals, cur = 1) => { const v = vals.filter(x => x != null), m = mean(v), n = v.length, se = Math.sqrt((n - 1) / n * v.reduce((a, x) => a + (x - m) ** 2, 0));
      return { mean: r3(m), min: r3(Math.min(...v)), max: r3(Math.max(...v)), jackSe: r3(se), excludesToday: Math.abs(m - cur) > 1.96 * se }; };
    R.cand = {};
    for (const c of ['A', 'B']) {
      const P = readParts(c); if (!folds.every((f, i) => P[i])) { console.error('missing parts', c); continue; }
      const Ms = folds.map((f, i) => P[i].M), e = evalSet(Ms, P.fwd?.M);
      e.lams = folds.map((f, i) => P[i].lam);
      e.multipliers = Object.fromEntries(LIVE.map(k => [k, { folds: Ms.map(M => r3(effective({ ...ONE, ...M })[k])), ...spread(Ms.map(M => effective({ ...ONE, ...M })[k])) }]));
      R.cand[c] = e;
      console.log(c, JSON.stringify({ primary: e.primary, classes: e.classes, top32: [e.top32_av, e.top32_cap], forward: e.forward, pass: e.pass }));
    }
    const PC = readParts('C');
    if (Object.keys(PC).length) {
      const each = {};
      for (const k of LIVE.filter(k => PC[k])) {
        const Ms = folds.map((f, i) => ({ ...f.nuis, [k]: PC[k][i] })), O = oofOf(Ms);
        const d = folds.map(f => score(O, f.test, 'av').within - score(BASEOOF, f.test, 'av').within), s = tst(d);
        // two-sided p from t with 9 df (Student t via the regularized incomplete beta, by series)
        const tp = (t, df) => { const x = df / (df + t * t); let a = df / 2, b = 0.5, bt = Math.exp(lgam(a + b) - lgam(a) - lgam(b) + a * Math.log(x) + b * Math.log(1 - x)); return Math.min(1, x < (a + 1) / (a + b + 2) ? bt * betacf(x, a, b) / a : 1 - bt * betacf(1 - x, b, a) / b); };
        each[k] = { picks: folds.map((f, i) => PC[k][i]), fwd: PC[k].fwd, ...spread(folds.map((f, i) => PC[k][i])), ...s, p: r3(s.t > 0 ? tp(s.t, d.length - 1) : 1), cap: tst(folds.map(f => score(O, f.test, 'cap').within - score(BASEOOF, f.test, 'cap').within)) };
        console.log('C', k.padEnd(14), JSON.stringify(each[k]));
      }
      // Benjamini-Hochberg at q .10 over the drivers
      const ks = Object.keys(each).sort((a, b) => each[a].p - each[b].p), m = ks.length; let kmax = 0;
      ks.forEach((k, i) => { if (each[k].p <= 0.10 * (i + 1) / m) kmax = i + 1; });
      const pass = ks.slice(0, kmax); for (const k of ks) each[k].bh = pass.includes(k);
      R.cand.C = { each, bhPass: pass };
      // --cset=k,...: score a chosen subset of the screen picks the same way (diagnostic: which part of the set moves the top)
      for (const cs of arg('cset').length ? [arg('cset')] : []) {
        const Ms = folds.map((f, i) => ({ ...f.nuis, ...Object.fromEntries(cs.map(k => [k, PC[k][i]])) })), e = evalSet(Ms, { ...nuisOf(fwd), ...Object.fromEntries(cs.map(k => [k, PC[k].fwd])) });
        (R.cand.C.subsets ||= {})[cs.join(',')] = e;
        console.log('C subset', cs.join(','), JSON.stringify({ primary: e.primary, classes: e.classes, top32: [e.top32_av, e.top32_cap], forward: e.forward, pass: e.pass, calib: e.calib }));
      }
      if (pass.length) {
        const Ms = folds.map((f, i) => ({ ...f.nuis, ...Object.fromEntries(pass.map(k => [k, PC[k][i]])) })), fM = fwd.train.length ? { ...nuisOf(fwd), ...Object.fromEntries(pass.map(k => [k, PC[k].fwd])) } : null;
        R.cand.C.set = evalSet(Ms, fM);
        console.log('C set', pass.join(','), JSON.stringify({ primary: R.cand.C.set.primary, classes: R.cand.C.set.classes, top32: [R.cand.C.set.top32_av, R.cand.C.set.top32_cap], forward: R.cand.C.set.forward, pass: R.cand.C.set.pass }));
      }
    }
    fs.writeFileSync(path.join(ROOT, 'data', 'cfb_fv_reweight.json'), JSON.stringify(R, null, 1).replace(/\bNaN\b/g, 'null') + '\n');
    console.log('rw report written', ((Date.now() - t0) / 1000).toFixed(0) + 's');
    process.exit(0);
  }
  if (stages.includes('fixed')) {
    const M = Object.fromEntries(arg('ship').map(x => x.split('=')).map(([k, v]) => [k, +v]));
    const oof = oofOf(folds.map(f => ({ ...f.nuis, ...M }))), fg = foldGain(oof), m = mean(fg), se = sdv(fg) * Math.sqrt(fg.length / (fg.length - 1)) / Math.sqrt(fg.length);
    W.fixed = { ship: M, gain: gainVs(oof), foldGain: fg, t: r3(m / se), byPos: Object.fromEntries(['av', 'cap'].map(t => [t, { today: score(BASEOOF, U, t).byPos, ship: score(oof, U, t).byPos }])) };
    const ov = {};
    for (const [lab, P] of [['pooled', {}], ['LB hs 1', { ...POS_SHIP, LB: { ...POS_SHIP.LB, hs: 1 } }], ['LB nonBlue 1', { ...POS_SHIP, LB: { ...POS_SHIP.LB, nonBlue: 1 } }],
      ['LB ath 1', { ...POS_SHIP, LB: { ...POS_SHIP.LB, ath: 1 } }], ['TE hs 1', { ...POS_SHIP, TE: { hs: 1 } }]]) {
      const o = new Map(); folds.forEach(f => { const G = gradeM({ ...f.nuis, ...M }, P); for (const p of f.test) o.set(p, G.get(p)); });
      const rP = (S, g, t) => { const T = S.filter(p => p.g === g && o.has(p)); return r3(corr(T.map(p => o.get(p).fm), T.map(p => p[t]))); };
      ov[lab] = { LB: ['pfn', 'box'].map(e => [rP(ERA[e], 'LB', 'av'), rP(ERA[e], 'LB', 'cap')]), TE: ['pfn', 'box'].map(e => [rP(ERA[e], 'TE', 'av'), rP(ERA[e], 'TE', 'cap')]) };
    }
    const rT = (S, g, t) => { const T = S.filter(p => p.g === g && oof.has(p)); return r3(corr(T.map(p => oof.get(p).fm), T.map(p => p[t]))); };
    ov.today = { LB: ['pfn', 'box'].map(e => [rT(ERA[e], 'LB', 'av'), rT(ERA[e], 'LB', 'cap')]), TE: ['pfn', 'box'].map(e => [rT(ERA[e], 'TE', 'av'), rT(ERA[e], 'TE', 'cap')]) };
    W.fixed.overrides = ov;
    console.log('fixed', JSON.stringify(W.fixed.gain), 'folds', JSON.stringify(fg), 't', W.fixed.t);
    console.log('fixed byPos', JSON.stringify(W.fixed.byPos));
    console.log('overrides [pfn av,cap],[box av,cap]', JSON.stringify(ov));
    save('fixed', ['fixed']);
  }
  console.log('wide done', ((Date.now() - t0) / 1000).toFixed(0) + 's');
  process.exit(0);
}
if (process.argv.includes('--quick')) { const M = arg('ship').length ? Object.fromEntries(arg('ship').map(x => x.split('=')).map(([k, v]) => [k, +v])) : SHIP; console.log(JSON.stringify(shipped(M))); process.exit(0); }
out.screen = screen(arg('screen').length ? arg('screen') : KEYS.filter(k => k !== 'age'));
out.joint = cv(KEYS.filter(k => k !== 'ageY' && k !== 'ageO'));
out.focused = cv(['ageY', 'ageO', 'cls', 'years', 'snap']);
out.shipped = { multipliers: SHIP, ...shipped(SHIP) };
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
console.log(JSON.stringify(out.shipped));
