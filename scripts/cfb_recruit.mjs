// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Recruit FV for the College Football ARKBOARD: what each incoming recruit and each player who hasn't played
// yet is projected to be, and next season's roster with them on it. Fit by scripts/cfb_recruit_fit.py
// (data/cfb_recruit_fit.json) on ESPN's 2023-26 classes followed to this season's board; blocks() mirrors the
// fit's blocks() by name.
//
//   P(on)  the chance he is on the board (has PFN snaps, FBS or FCS) in year k of college
//   FV(on) his FV if he is
//   xFV    P(on) x FV(on) + (1 - P(on)) x 20, the board floor
//
// Three groups: the next class (ESPN commitments, year 1 next season); players on a roster now who have no
// snaps (redshirts and buried freshmen), scored at year k + 1 with the redshirt recalibration (sitters
// measured on last season's rosters and games played); and low-snap young players on the board, whose
// next-season FV blends the board FV with the recruit projection by snaps (w = snaps / (snaps + one game's snaps)).
// Next season's roster: the builder's returners (FV, stay chance) plus redshirts and the class, each in the
// depth chart with his chance of being there, run through the same slot simulation as the team builder.
//
// Run on its own (node scripts/cfb_recruit.mjs [--offline]) from the board files, or from fetch_cfb.mjs.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { avOf, STARTERS } from './cfb_teams.mjs';
import { compact, key, sameTeam, teamKey } from './names.mjs';
import { fvDist, cfbZ } from './fv_dist.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'cfb');
const CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football';
const SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const P4_CONF = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC']);
const SNAPS_PER_GAME = { QB: 65, RB: 30, WR: 40, TE: 40, CB: 55, S: 55, OL: 65, EDGE: 50, DL: 45, LB: 55 };
const BLEND_GAMES = 1;   // a young player's own snaps count half against the recruit projection at one full game's worth
const SIMS = 400;
const r1 = x => Math.round(x * 10) / 10, r3 = x => Math.round(x * 1000) / 1000;
const sig = z => 1 / (1 + Math.exp(-z));
const sleep = ms => new Promise(r => setTimeout(r, ms));
function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }

export const norm = compact;   // the shared name key (scripts/names.mjs), no spaces
// last name + first initial, for nicknames (Samuel -> Sam); the fit links the same way
export function short(s) {
  const w = key(s).split(' ').filter(Boolean);
  return w.length > 1 ? '~' + w.slice(1).join('') + w[0][0] : '~';
}

// ESPN recruiting positions -> board groups (as in the fit)
const POS = { QB: 'QB', 'QB-DT': 'QB', 'QB-PP': 'QB', RB: 'RB', APB: 'RB', WR: 'WR', TE: 'TE', 'TE-Y': 'TE', 'TE-H': 'TE',
  OT: 'OL', OG: 'OL', OC: 'OL', IOL: 'OL', OL: 'OL', C: 'OL', G: 'OL', T: 'OL', DE: 'EDGE', WDE: 'EDGE', SDE: 'EDGE', EDGE: 'EDGE',
  DT: 'DL', DL: 'DL', LB: 'LB', ILB: 'LB', OLB: 'LB', CB: 'CB', S: 'S', SAF: 'S', DB: 'S' };
export function group(pos, wt) {
  if (POS[pos]) return POS[pos];
  if (pos === 'ATH' || !pos) return wt && wt >= 240 ? 'EDGE' : 'ATH';
  return null;
}
const GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH'];
const TOP_STATES = ['TX', 'FL', 'GA', 'CA', 'AL', 'LA', 'OH'];

// ---- the fit's feature blocks (scripts/cfb_recruit_fit.py blocks()) --------------------------------------
function blocks(r, sz, KMAX, index) {
  const gr = r.grade, k = r.k, rated = gr >= 60, g = rated ? (gr - 75) / 5 : 0;
  const [hm, hs, wm, ws] = sz[r.g], rk = r.rank || 0, pr = r.posRank || 0;
  const h80 = rated ? Math.max(0, gr - 80) / 5 : 0;
  const o = {
    grade: { g, unrated: rated ? 0 : 1 },
    hinge: { g80: h80, g85: rated ? Math.max(0, gr - 85) / 5 : 0 },
    rank: { lrank: rk ? Math.log(400) - Math.log(rk) : 0 },
    posrank: { lpos: pr ? Math.log(100) - Math.log(Math.min(pr, 100)) : 0 },
    pos: {}, year: {}, pos_year1: {},
    grade_year: { g_k: g * (k - 1), g80_k: h80 * (k - 1) },
    size: { htz: r.ht ? (r.ht - hm) / hs : 0, wtz: r.wt ? (r.wt - wm) / ws : 0 },
    level: { G5: r.level === 'G5' ? 1 : 0, FCS: r.level === 'FCS' ? 1 : 0 },
    elo: { eloZ: r.eloZ, elo_k1: r.eloZ * (k === 1 ? 1 : 0) },
    elo_grade: { elo_g: r.eloZ * g },
    dev: { dev: r.dev || 0 },
    // round-2 drivers (the fit keeps the ones that pass; the rest carry no weight)
    bmi: { bmiz: r.ht && r.wt && sz.bmi?.[r.g] ? (703 * r.wt / r.ht ** 2 - sz.bmi[r.g][0]) / sz.bmi[r.g][1] : 0 },
    frame: { htz2: r.ht ? Math.min(9, ((r.ht - hm) / hs) ** 2) : 0, wtz2: r.wt ? Math.min(9, ((r.wt - wm) / ws) ** 2) : 0 },
    offers: { offRes: r.offRes || 0 },
    offer_q: { offElo: r.offElo ?? 0, offTop: r.offTop ?? 0, p4Res: r.p4Res || 0, noOff: r.offElo == null ? 1 : 0 },
    comp: { compz: r.comp ? (r.comp - 0.87) / 0.04 : 0, noComp: r.comp ? 0 : 1 },
    gap: { gapEspn: r.comp && rated && !r.mapped ? (r.comp - 0.87) / 0.04 - g : 0, gap247: r.cRank && r.r247 ? Math.log(r.cRank) - Math.log(r.r247) : 0 },
    hs: { lHs: r.hsN != null ? Math.log1p(r.hsN) : 0 },
    // the 247 composite as CFBD holds it (the composite index only: indexOf)
    c247: { c247z: r.c247 ? (r.c247 - 0.87) / 0.04 : 0, noC247: r.c247 ? 0 : 1 },
    cqOff: r.cqOff || 0,
    // On3's industry table: the rating, 247 and ESPN against it, commit timing centred on the index's history
    on3: { indz: r.ind && !r.byRank ? (r.ind - 85) / 5 : 0, noInd: r.ind ? 0 : 1 },   // a class read by rank: its mapped grade already holds the rank, so the rating stays neutral
    svc: { g247: r.g247 || 0, gEspn: r.gEspn || 0 },
    tm: (t => ({ commitM: t ? t[0] - (index?.tm?.[0] ?? 0) : 0, commitEarly: t ? t[1] - (index?.tm?.[1] ?? 0) : 0 }))(commitTiming(r)),
    state: {},
    grade_k4: { g_k4: k === 4 ? g : 0, g80_k4: k === 4 ? h80 : 0 },
  };
  for (const x of TOP_STATES) o.state['s_' + x] = r.state === x ? 1 : 0;
  for (const p of GROUPS) if (p !== 'WR') { o.pos['p_' + p] = r.g === p ? 1 : 0; o.pos_year1['p1_' + p] = r.g === p && k === 1 ? 1 : 0; }
  for (let j = 2; j <= KMAX; j++) o.year['k' + j] = k === j ? 1 : 0;
  // the recruit-profile index (scripts/cfb_recruit_retarget.py): the profile weighed by what 2011-19 recruits became
  // in the NFL, put on the board's scale by year and position in the fit (Oct 25 2026)
  if (index) {
    const ip = indexParts(index, o), iOn = Object.values(ip.on).reduce((a, x) => a + x, 0), iFv = Object.values(ip.fv).reduce((a, x) => a + x, 0);
    o.idx = { iOn, iFv, iOn_k: iOn * (k - 1), iFv_k: iFv * (k - 1) };
  }
  return o;
}
// months committed before the December signing day of his senior year (0-24) and committed before his senior season;
// null with no date or a later transfer's (scripts/cfb_recruit_fit.py commit_timing). A recruit of the class now
// signing who has not committed is timed as if he committed today (the latest he still can be: no credit for waiting
// that he has not shown yet); the classes further out stay neutral until their own cycle.
const TODAY = new Date();
function commitTiming(r) {
  const y = r.year, sign = Date.UTC(y - 1, 11, 20), senior = Date.UTC(y - 1, 8, 1);
  let d = r.commit ? Date.parse(r.commit + 'T00:00:00Z') : null;
  if (d != null && d > Date.UTC(y, 7, 1)) d = null;
  if (d == null) { if (!r.asOf || TODAY.getTime() > sign) return null; d = TODAY.getTime(); }
  return [Math.max(0, Math.min(24, (sign - d) / 864e5 / 30.4)), d < senior ? 1 : 0];
}
// each index part's linear term by source block
function indexParts(index, b) {
  const out = {};
  for (const part of ['on', 'fv']) {
    const m = index[part]; out[part] = {};
    for (const u of m.blocks) out[part][u] = m.names.reduce((a, n, i) => a + (b[u][n] ?? 0) * m.coef[i], 0);
    if (index.shift) out[part].c247 = (out[part].c247 || 0) + index.shift[part] - (part === 'on' ? b.cqOff : 0);
  }
  return out;
}
// The index a recruit is read through. A class CFBD's copy of the 247 composite covers (r.cq, set by attachCfbd)
// takes the index fit with the composite ('indexComp'); every other class the one without. The fit put the index on
// the board's scale without its intercept, so the composite index carries its intercept's distance to the other's
// (shift), held with the composite's own term. The composite re-orders the recruits of a class and does not move the
// class's level: r.cqOff (centreCq) is the class's mean distance between the two indexes, taken back out.
function indexOf(fit, r) {
  const ic = fit.indexComp;
  if (!r.cq || !ic || !fit.index) return fit.index;
  ic.shift ||= { on: ic.on.b0 - fit.index.on.b0, fv: ic.fv.b0 - fit.index.fv.b0 };
  return ic;
}
export function predict(fit, r) {
  const b = blocks(r, fit.sizeNorms, fit.classes[1] - fit.classes[0] + 1, indexOf(fit, r));
  const lin = m => { const row = {}; for (const u of m.blocks) Object.assign(row, b[u]); return m.names.reduce((a, n, i) => a + (row[n] ?? 0) * m.coef[i], m.b0); };
  const pOn = sig(lin(fit.model.on)), fvOn = Math.max(fit.floor, lin(fit.model.fv));
  return atMeanOn(fit, r, pOn, fvOn);
}
// The recruit index's expected NFL outcome on the FV scale (scripts/cfb_recruit_retarget.py index_score): the chance
// he is drafted times the FV a drafted recruit of his profile reaches, the floor otherwise. No year or board terms.
export function indexScore(fit, r) {
  const ix = indexOf(fit, r); if (!ix) return null;
  const b = blocks(r, fit.sizeNorms, fit.classes[1] - fit.classes[0] + 1, ix);
  const p = sig(fit.index.on.b0 + b.idx.iOn), f = Math.max(fit.floor, fit.index.fv.b0 + b.idx.iFv);
  return p * f + (1 - p) * fit.floor;
}
// the fit projects the board's grade (it was fit on grades); FV if on and xFV are shown at the mean outcome, as the
// board's FV is since Oct 21 2026 (scripts/fv_dist.mjs atMean). g keeps the grade-scale numbers: the ARK star cuts and
// the redshirt shifts were set on them
export const meanOn = (r, fv) => fvDist('cfb', fv, cfbZ({ pos: r.g, years: r.k ?? 1, fv }))?.mean ?? fv;
function atMeanOn(fit, r, pOn, fvOnG) {
  const fvOn = Math.max(fit.floor, meanOn(r, fvOnG));
  return { pOn, fvOn, xfv: pOn * fvOn + (1 - pOn) * fit.floor, g: { fvOn: fvOnG, xfv: pOn * fvOnG + (1 - pOn) * fit.floor } };
}
// ---- what goes into one xFV: each input's share against the average signee of the last class ----------
// Each block's linear term against the reference (the average signee's value of the same inputs). Playing time
// is split along the logit path (block share of the logit gap x the P(on) gap / the whole gap, which sums
// exactly), and xFV - 20 = P(on) x (FV - 20) is split as dP x mean(FV - 20) + dFV x mean(P), also exact.
const WHY_LABEL = { grade: 'ESPN grade and rank', hinge: 'ESPN grade and rank', grade_year: 'ESPN grade and rank', grade_k4: 'ESPN grade and rank', posrank: 'ESPN grade and rank', rank: 'ESPN grade and rank',
  pos: 'position', pos_year1: 'position', year: 'year in school', size: 'height and weight', bmi: 'height and weight', frame: 'height and weight',
  offer_q: 'offer quality', offers: 'offer count', gap: '247 ratings', comp: '247 ratings', c247: '247 composite', on3: 'industry rating', svc: '247 and ESPN vs industry', tm: 'commit timing', hs: 'high school pipeline', state: 'home state',
  elo: 'program strength', elo_grade: 'program strength', level: 'program level', dev: 'program development' };
function linParts(fit, m, r, KMAX) {
  const b = blocks(r, fit.sizeNorms, KMAX, indexOf(fit, r)), out = {};
  for (const u of m.blocks) {
    if (u === 'idx') {   // the index's term goes back to the inputs it is made of (ESPN grade, 247, size, program)
      const ip = indexParts(indexOf(fit, r), b), c = n => m.coef[m.names.indexOf(n)] ?? 0, k1 = (r.k ?? 1) - 1;
      for (const [part, w] of [['on', c('iOn') + c('iOn_k') * k1], ['fv', c('iFv') + c('iFv_k') * k1]])
        for (const [s, v] of Object.entries(ip[part])) out[s] = (out[s] || 0) + w * v;
      continue;
    }
    let v = 0; for (const [n, x] of Object.entries(b[u])) { const i = m.names.indexOf(n); if (i >= 0) v += x * m.coef[i]; } out[u] = (out[u] || 0) + v;
  }
  return out;
}
export function whyOf(fit, r, ref, redshirt = false) {
  const KMAX = fit.classes[1] - fit.classes[0] + 1, M = fit.model, F = fit.floor;
  const on = linParts(fit, M.on, r, KMAX), fv = linParts(fit, M.fv, r, KMAX);
  const sum = o => Object.values(o).reduce((a, x) => a + x, 0);
  const z0 = M.on.b0 + sum(ref.on), z1 = M.on.b0 + sum(on), f0 = M.fv.b0 + sum(ref.fv);
  const rs = fit.redshirt, D = {};
  for (const u of Object.keys(on)) D[u] = (on[u] - (ref.on[u] || 0)) * (redshirt ? rs.b : 1);
  const zEnd = redshirt ? rs.a + rs.b * z1 + rsExtra(fit, r) : z1, zMid = z0 + sum(D);   // redshirts: the recalibration is its own row
  const p0 = sig(z0), p1 = sig(zEnd), f1 = Math.max(F, M.fv.b0 + sum(fv) + (redshirt ? rs.fvShift : 0));
  const dz = zEnd - z0, dp = p1 - p0, k = Math.abs(dz) > 1e-6 ? dp / dz : p0 * (1 - p0);
  const gBar = (f0 - F + f1 - F) / 2, pBar = (p0 + p1) / 2, rows = {};
  const addRow = (lab, dpp, dfv) => { const x = rows[lab] ||= [0, 0, 0]; x[0] += dpp * gBar + dfv * pBar; x[1] += dpp; x[2] += dfv; };
  for (const u of new Set([...Object.keys(on), ...Object.keys(fv)])) addRow(WHY_LABEL[u] || u, (D[u] || 0) * k, u in fv ? fv[u] - (ref.fv[u] || 0) : 0);
  if (redshirt) addRow('sat out last season', (zEnd - zMid) * k, rs.fvShift);
  const x0 = p0 * (f0 - F) + F, x1 = p1 * (f1 - F) + F, got = x0 + Object.values(rows).reduce((a, x) => a + x[0], 0);
  if (Math.abs(x1 - got) >= 0.05) addRow('FV floor (20)', 0, 0), rows['FV floor (20)'][0] = x1 - got;
  const out = Object.entries(rows).sort((a, b) => Math.abs(b[1][0]) - Math.abs(a[1][0])).map(([lab, x]) => [lab, r1(x[0]), Math.round(x[1] * 1000) / 10, r1(x[2])]);
  // rounding: the largest row carries it, so the rows add up to the xFV shown
  if (out.length) out[0][1] = r1(out[0][1] + r1(x1) - r1(x0) - out.reduce((a, x) => a + x[1], 0));
  return { x0: r1(x0), p0: r3(p0), f0: r1(f0), rows: out.filter(x => Math.abs(x[1]) >= 0.05 || Math.abs(x[2]) >= 0.5 || Math.abs(x[3]) >= 0.05) };
}
// a player on a roster who hasn't played: next season (year k + 1), recalibrated on last season's sitters
// the sitters' test inputs (scripts/cfb_recruit_fit.py RS_EXTRA); a current redshirt has no snaps, so games is 0
const RS_EXTRA = { games: r => ({ gp14: r.gpLast >= 1 && r.gpLast <= 4 ? 1 : 0 }), grade: (r, b) => b.grade, offer_q: (r, b) => b.offer_q, gap: (r, b) => b.gap, hs: (r, b) => b.hs,
  bmi: (r, b) => b.bmi, size: (r, b) => b.size, level: r => ({ p4: r.level === 'P4' ? 1 : 0 }), moved: r => ({ moved: r.signedTid && r.tid !== r.signedTid ? 1 : 0 }) };
function rsExtra(fit, r) {
  const rs = fit.redshirt; if (!rs.names?.length) return 0;
  const b = blocks(r, fit.sizeNorms, fit.classes[1] - fit.classes[0] + 1, indexOf(fit, r)), ex = Object.assign({}, ...(rs.extra || []).map(u => RS_EXTRA[u](r, b)));
  return rs.names.reduce((a, n, i) => a + (ex[n] ?? 0) * rs.coef[i], 0);
}
export function predictRedshirt(fit, r) {
  const base = predict(fit, r), z = Math.log(base.pOn / (1 - base.pOn)), rs = fit.redshirt;
  const pOn = sig(rs.a + rs.b * z + rsExtra(fit, r)), fvOn = Math.max(fit.floor, base.g.fvOn + rs.fvShift);
  return atMeanOn(fit, r, pOn, fvOn);
}
// two seasons on (the year after next), recalibrated on the recruits who sat two seasons ago
export function predictRedshirt2(fit, r) {
  const t = fit.redshirt.two; if (!t) return null;
  const base = predict(fit, r), z = Math.log(base.pOn / (1 - base.pOn));
  const pOn = sig(t.a + t.b * z), fvOn = Math.max(fit.floor, base.g.fvOn + t.fvShift);
  return atMeanOn(fit, r, pOn, fvOn);
}

// ---- pulls (cached in scripts/.cache/cfb, which the board's Action keeps) --------------------------------
const cachePath = name => path.join(CACHE, name);
const hasCache = name => fs.existsSync(cachePath(name));
const readCache = name => JSON.parse(fs.readFileSync(cachePath(name), 'utf8'));
const writeCache = (name, v) => { fs.mkdirSync(CACHE, { recursive: true }); fs.writeFileSync(cachePath(name), JSON.stringify(v)); };
async function getJson(url) {
  for (let i = 0; i < 4; i++) {
    try { const r = await fetch(url, { headers: { 'user-agent': UA } }); if (r.status === 404) return null; if (!r.ok) throw new Error(r.status); return await r.json(); }
    catch (e) { if (i === 3) { console.log('recruits: fail', url, e.message); return null; } await sleep(1000 * 2 ** i); }
  }
}
async function pool(xs, n, fn) { const out = new Array(xs.length); let i = 0; await Promise.all(Array.from({ length: n }, async () => { while (i < xs.length) { const j = i++; out[j] = await fn(xs[j]); } })); return out; }

// ESPN's high school field names a college for some signees: no high school at all (see not_hs in cfb_recruit_fit.py)
const notHs = n => /university|college/i.test(n || '') && !/prep|high|academy|school/i.test(n || '');

// a whole ESPN class: athlete id once enrolled, name, position, size, grade, ranks, committed or signed school
async function espnClass(y, fresh, offline) {
  const name = `espnclass2-${y}.json`;   // v2: with the schools in each recruitment
  if (hasCache(name) && (!fresh || offline)) return readCache(name);
  if (offline) return [];
  const acc = [];
  for (let pg = 1; pg <= 12; pg++) {
    const d = await getJson(`${CORE}/recruiting/${y}/athletes?limit=1000&page=${pg}`);
    if (!d) break;
    for (const it of d.items || []) {
      const a = it.athlete || {}, at = Object.fromEntries((it.attributes || []).map(x => [x.name, x.value]));
      const sch = (it.schools || []).filter(s => s.status?.id && s.team).map(s => [s.status.description, /\/teams\/(\d+)/.exec(s.team.$ref)?.[1]]);
      const school = sch.find(([st]) => ['Signed', 'Enrolled', 'Verbal', 'Committed'].includes(st));
      acc.push({ rid: a.id, id: a.alternateId || null, name: a.fullName, pos: a.position?.abbreviation || null, ht: a.height || null, wt: a.weight || null,
        grade: +it.grade || 0, rank: at.rank || null, posRank: at.positionRank || null, city: a.hometown?.city || null, state: a.hometown?.stateAbbreviation || null,
        status: it.status?.description || null, tid: school ? school[1] : null, year: y, stRank: at.stateRank || null, hs: notHs(a.highSchool?.name) ? null : a.highSchool?.id || null,
        offers: (it.schools || []).filter(s => s.team).map(s => /\/teams\/(\d+)/.exec(s.team.$ref)?.[1]), visits: (it.schools || []).filter(s => s.visit).length });
    }
    if (pg >= (d.pageCount || 1)) break;
    await sleep(150);
  }
  if (acc.length) writeCache(name, acc);
  return acc.length ? acc : hasCache(name) ? readCache(name) : [];
}
// The composite for class y: {name, state, comp (247's 0-1 scale), cRank, r247}. 247's pages sit behind a bot check
// (Nov 2026), so a class still being recruited reads On3's industry table (scripts/data/cfb_on3_live.json, pulled daily
// by scripts/cfb_on3.mjs and packed by scripts/cfb_on3_pack.py), its rating put on the composite's scale by the packed
// line; signed classes, and 247's own early list (kind 'own'), come from the last snapshot (scripts/cfb_recruit_247.json).
let ON3 = null;
function on3Rows(y) {
  if (!ON3) {
    ON3 = {};
    try { Object.assign(ON3, JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'cfb_on3_hist.json.gz'))))); } catch {}
    try { const L = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'cfb_on3_live.json'), 'utf8')); ON3.map = L.map; Object.assign(ON3, L.classes || {}); } catch {}
  }
  return ON3[y] || [];
}
// A class two or three years out is rated low across the board this early (the top 2029 recruit is an 89 where a signed
// class tops out near 99), so its ratings are read by rank: each recruit takes the rating that the same industry rank
// holds in the reference class (the next class to sign).
const byRank = y => { const o3 = on3Rows(y); return o3.length > 0 && y > season0 && on3Rows(season0).length > 0 && Math.max(...o3.map(o => o[2])) < 95; };
function on3Class(y) {
  const o3 = on3Rows(y), ref = on3Rows(season0);
  if (!byRank(y)) return o3;
  const rr = ref.map(o => o[2]).sort((a, b) => b - a);
  return o3.map(o => { const c = o.slice(); if (o[3]) c[2] = rr[Math.min(o[3], rr.length) - 1]; return c; });
}
async function rank247(y, kind, snap, offline) {
  const fromSnap = () => (snap?.[kind]?.[y] || []).map(([name, state, comp, cRank, r247]) => ({ name, state, comp, cRank, r247 }));
  const o3 = on3Class(y);
  if (kind === 'composite' && y >= season0 && o3.length && ON3.map)
    return o3.map(([name, state, ind, indRank, r247]) => ({ name, state, comp: Math.min(1, ON3.map[0] + ON3.map[1] * ind), cRank: indRank, r247 }));
  return fromSnap();
}
// each recruit's On3 row: name + home state, else a name that is unique in the class (scripts/cfb_recruit_fit.py attach_on3)
function attachOn3(cl, y, asOf) {
  const o3 = on3Class(y), by = {}, n = {};
  for (const o of o3) n[norm(o[0])] = (n[norm(o[0])] || 0) + 1;
  for (const o of o3) { (by[norm(o[0]) + '|' + o[1]] ||= []).push(o); if (n[norm(o[0])] === 1) (by[norm(o[0]) + '|'] ||= []).push(o); }
  for (const r of cl) {
    const m = by[norm(r.name) + '|' + r.state] || by[norm(r.name) + '|'] || [], o = m.length === 1 ? m[0] : [];
    r.ind = o[2] ?? null; r.indRank = o[3] ?? null; r.g247 = o[5] ?? null; r.gEspn = o[6] ?? null; r.commit = o[7] ?? null; r.rRiv = o[8] ?? null; r.sRiv = o[9] ?? null; r.asOf = asOf; r.byRank = byRank(y);
    if (o[4] && !r.r247) r.r247 = o[4];
  }
  return cl;
}
// CFBD's copy of the 247 composite for a class being recruited (scripts/data/cfb_recruits_cfbd_live.json, pulled weekly
// by scripts/cfb_recruits_cfbd.mjs --live; 247's own pages are never requested): each recruit's composite by name + home
// state, else a name that is unique in the class. The class reads the composite index (cq) only when CFBD covers it as
// it covered the classes the index was fit on: at least CQ_MIN of CQ_N or more ESPN-graded recruits matched (2011-19:
// .86 to .94). Returns the coverage for the output.
const CQ_MIN = 0.8, CQ_N = 100;
let CFBD_LIVE = null;
function attachCfbd(cl, y) {
  if (!CFBD_LIVE) { try { CFBD_LIVE = JSON.parse(fs.readFileSync(path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd_live.json'), 'utf8')); } catch { CFBD_LIVE = { at: {}, classes: {} }; } }
  const rows = y >= season0 ? CFBD_LIVE.classes?.[y] || [] : [];
  if (!rows.length) return null;
  const by = {}, n = {};
  for (const c of rows) n[key(c[0])] = (n[key(c[0])] || 0) + 1;
  for (const c of rows) { (by[key(c[0]) + '|' + (c[7] || '')] ||= []).push(c); if (n[key(c[0])] === 1) (by[key(c[0]) + '|'] ||= []).push(c); }
  let rated = 0, hit = 0;
  for (const r of cl) {
    const m = by[key(r.name) + '|' + (r.state || '')] || by[key(r.name) + '|'] || [];
    r.c247 = m.length === 1 ? m[0][1] : null;
    if (r.grade >= 60) { rated++; if (r.c247) hit++; }
  }
  const on = rated >= CQ_N && hit / rated >= CQ_MIN;
  for (const r of cl) r.cq = on;
  return { year: y, at: CFBD_LIVE.at?.[y] || null, rows: rows.length, graded: rated, matched: rated ? Math.round(1000 * hit / rated) / 1000 : null, on };
}
// the mean distance of the composite index's P term from the other index's over a class's scored rows, set on each
// row (and on its source record, for the rows built from it later)
function centreCq(fit, rs) {
  rs = rs.filter(r => r && r.cq);
  if (!rs.length || !fit.indexComp || !fit.index) return;
  const KMAX = fit.classes[1] - fit.classes[0] + 1, iOn = r => blocks(r, fit.sizeNorms, KMAX, indexOf(fit, r)).idx.iOn;
  const off = rs.reduce((a, r) => a + iOn({ ...r, cqOff: 0 }) - iOn({ ...r, cq: false }), 0) / rs.length;
  for (const r of rs) r.cqOff = off;
}
let season0 = 9999;   // the first class still being recruited (set by recruitBoard)
const unescapeHtml = s => s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
function attach247(cl, comp) {
  const by = {};
  for (const c of comp) for (const k of [norm(c.name) + '|' + c.state, short(c.name) + '|' + c.state]) (by[k] ||= []).push(c);
  for (const r of cl) {
    const m = by[norm(r.name) + '|' + r.state] || by[short(r.name) + '|' + r.state] || [];
    const c = m.length === 1 ? m[0] : null;
    r.comp = c?.comp ?? null; r.cRank = c?.cRank ?? null; r.r247 = c?.r247 ?? null;
  }
  return cl;
}
// the fit's candidate drivers for a class (scripts/cfb_recruit_fit.py enrich()): the programs in his recruitment,
// his high school's output, and offer counts as residuals on grade within the class
// Commitment changes ESPN hasn't caught up to: the latest commit / flip / decommit headline (247Sports, On3:
// data/recruit_news.json, scripts/recruit_news.py) from the last NEWS_DAYS days moves the recruit's school. A
// signing ESPN shows stays.
const NEWS_DAYS = 21;
export function applyNews(cl, prog, news = readNews(), today = new Date()) {
  const cut = new Date(today.getTime() - NEWS_DAYS * 864e5).toISOString().slice(0, 10), tidOf = {};
  for (const [tid, p] of Object.entries(prog)) if (p.team) tidOf[teamKey(p.team)] ??= tid;
  const last = {};
  for (const n of news) if (['commit', 'flip', 'decommit'].includes(n.k) && n.d >= cut && (!last[key(n.n)] || n.d > last[key(n.n)].d)) last[key(n.n)] = n;
  const toward = {};   // schools a recent commit / flip story took him to: a decommit story without a school is about the old one
  for (const n of news) if (['commit', 'flip'].includes(n.k) && n.d >= cut && n.to) (toward[key(n.n)] ||= new Set()).add(teamKey(n.to));
  let moved = 0;
  for (const c of cl) {
    const n = last[key(c.name)];
    if (!n || (n.cls && c.year && n.cls !== c.year) || c.year <= today.getUTCFullYear() || c.status === 'Signed' || c.status === 'Enrolled') continue;
    if (n.k === 'decommit') {
      if (c.tid && (n.fr ? sameTeam(n.fr, prog[c.tid]?.team) : !toward[key(c.name)]?.has(teamKey(prog[c.tid]?.team || '')))) { console.error(`  ${c.name} (${c.year}): ${prog[c.tid]?.team} decommitted (${n.d})`); c.tid = null; c.status = null; c.news = n.d; moved++; }
    } else {
      const tid = tidOf[teamKey(n.to)];
      if (tid && tid !== c.tid) { console.error(`  ${c.name} (${c.year}): ${prog[c.tid]?.team || '-'} -> ${n.to} (${n.k} ${n.d})`); c.tid = tid; c.status = 'Verbal'; c.news = n.d; moved++; }
    }
  }
  return moved;
}
// Reclassifications (recruit news, any age): a recruit reported moving from class A to B leaves A's list and joins B's
// with his ESPN row, until ESPN lists him in B itself.
export async function reclassed(y, cl, load, news = readNews()) {
  const rc = news.filter(n => n.k === 'reclass' && n.cls && n.ocls);
  if (!rc.length) return cl;
  const have = new Set(cl.map(c => key(c.name)));
  const out = cl.filter(c => !rc.some(n => n.ocls === y && key(n.n) === key(c.name)) || rc.some(n => n.cls === y && key(n.n) === key(c.name)));
  for (const oy of [...new Set(rc.filter(n => n.cls === y && !have.has(key(n.n))).map(n => n.ocls))]) {
    const from = await load(oy);
    for (const n of rc.filter(n => n.cls === y && n.ocls === oy && !have.has(key(n.n)))) {
      const c = from.find(c => key(c.name) === key(n.n));
      if (c) { out.push({ ...c, year: y, reclass: oy }); have.add(key(c.name)); console.error(`  ${c.name}: class ${oy} -> ${y} (reclass ${n.d})`); }
    }
  }
  return out;
}
function readNews() {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'recruit_news.json'), 'utf8')).cfb || []; } catch { return []; }
}

function enrich(cl, prog, hsN) {
  for (const r of cl) {
    const offs = [...new Set(r.offers || [])].map(t => prog[t]).filter(Boolean), fbs = offs.filter(o => o.level !== 'FCS');
    r.nOff = offs.length; r.nVis = r.visits || 0; r.offP4 = offs.filter(o => o.level === 'P4').length;
    r.offElo = fbs.length ? fbs.reduce((a, o) => a + o.eloZ, 0) / fbs.length : null;
    r.offTop = fbs.length ? Math.max(...fbs.map(o => o.eloZ)) : null;
    r.hsN = r.hs ? Math.max(0, (hsN[r.hs] || 0) - (r.grade >= 70 ? 1 : 0)) : null;
  }
  for (const [key, src] of [['offRes', r => Math.log1p(r.nOff)], ['p4Res', r => Math.log1p(r.offP4)]]) {
    const v = classResid(cl, src); cl.forEach((r, i) => { r[key] = v[i]; });
  }
  return cl;
}
function classResid(cl, src) {
  const rt = cl.filter(x => x.grade >= 60), un = cl.filter(x => x.grade < 60);
  let fit = null, um = null;
  if (rt.length > 20) {
    const n = rt.length, gx = rt.map(x => x.grade), v = rt.map(src), mg = gx.reduce((a, x) => a + x, 0) / n, mv = v.reduce((a, x) => a + x, 0) / n;
    const b = gx.reduce((a, x, i) => a + (x - mg) * (v[i] - mv), 0) / (gx.reduce((a, x) => a + (x - mg) ** 2, 0) || 1), a = mv - b * mg;
    const sd = Math.sqrt(v.reduce((s, x, i) => s + (x - a - b * gx[i]) ** 2, 0) / n) || 1; fit = { a, b, sd };
  }
  if (un.length > 20) { const v = un.map(src), m = v.reduce((a, x) => a + x, 0) / v.length; um = { m, sd: Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / v.length) || 1 }; }
  return cl.map(r => r.grade >= 60 ? (fit ? (src(r) - fit.a - fit.b * r.grade) / fit.sd : 0) : (um ? (src(r) - um.m) / um.sd : 0));
}

// this season's roster for each program (ESPN): who is on it, to find the players with no snaps
async function rosters(tids, season, offline) {
  const name = `rosters-site-${season}.json`;
  if (hasCache(name) && (offline || Date.now() - fs.statSync(cachePath(name)).mtimeMs < 20 * 3600e3)) return readCache(name);
  if (offline) return {};
  const out = {};
  await pool(tids, 8, async tid => {
    const d = await getJson(`${SITE}/teams/${tid}/roster`);
    out[tid] = (d?.athletes || []).flatMap(g => g.items || []).map(a => ({ id: a.id, name: a.fullName, pos: a.position?.abbreviation, ht: a.height || null, wt: a.weight || null, exp: a.experience?.years ?? null }));
  });
  if (Object.keys(out).length) writeCache(name, out);
  return out;
}

// ---- the build ---------------------------------------------------------------------------------------------
// rows: the board (FBS + FCS); teams: cfb_teams.json teams (FBS, with Elo); builder: cfb-builder.json (returners)
export async function recruitBoard({ fit, rows, teams, builder, season, asof, offline = false, snap247 = null }) {
  season0 = season + 1;
  const elo = teams.map(t => t.elo), em = elo.reduce((a, x) => a + x, 0) / elo.length, es = Math.sqrt(elo.reduce((a, x) => a + (x - em) ** 2, 0) / elo.length) || 1;
  const prog = {};
  for (const t of teams) prog[t.tid] = { level: P4_CONF.has(t.conf) || t.tid === '87' ? 'P4' : 'G5', eloZ: (t.elo - em) / es, team: t.team, logo: t.logo, conf: t.conf, color: t.color };
  const byId = {}, byNT = {}, byN = {};
  for (const r of rows) {
    if (r.pos === 'K' || r.pos === 'P' || r.fv == null) continue;
    const id = /\/id\/(\d+)/.exec(r.espnl || '')?.[1], tid = r.tid || /\/logos\/(\d+)\.png/.exec(r.logo || '')?.[1];
    if (tid && r.div === 'FCS' && !prog[tid]) prog[tid] = { level: 'FCS', eloZ: 0, team: r.team, logo: r.logo, conf: r.conf };
    const x = { ...r, tid };
    if (id) byId[id] = x;
    byNT[norm(r.name) + '|' + tid] = x; (byN[norm(r.name)] ||= []).push(x); (byN[short(r.name)] ||= []).push(x);
  }
  const KMAX = fit.classes[1] - fit.classes[0] + 1;
  const sz = fit.sizeNorms;
  const mk = (c, k) => { const g = group(c.pos, c.wt), p = prog[c.tid]; return g && p ? { ...c, g, k: Math.min(k, KMAX), level: p.level, eloZ: p.eloZ, dev: fit.model.dev[c.tid] || 0 } : null; };
  const pathOf = r => [1, 2, 3].map(k => r1(predict(fit, { ...r, k }).xfv));
  // ARK stars: the recruit index's expected NFL outcome (indexScore) cut where the 2011-19 classes' outcomes put each
  // tier (fit.stars.idx, scripts/cfb_recruit_retarget.py stars_block), plus a half star (1.5-4.5) past the tier's half
  // cut; 6 is 5-star+. A fit without the index cuts falls back to the year-3 xFV cuts (fit.stars.cuts).
  const SI = fit.stars?.idx && fit.index ? fit.stars.idx : null;
  const cutStars = (x, S) => { if (x == null || !S) return null; const t = 1 + S.cuts.filter(c => c <= x).length, h = S.half?.[t - 1]; return t <= 4 && h != null && x >= h ? t + 0.5 : t; };
  const arkStars = x => cutStars(x, fit.stars);
  const starsOf = r => SI ? cutStars(indexScore(fit, r), SI) : arkStars(predict(fit, { ...r, k: 3 }).g.xfv);
  // where FV if on sits on this season's board (percentile), and the P10-P90 range of FV if on at year k:
  // the fit's out-of-sample miss at that year, widened by a mapped grade's own miss when ESPN has no grade yet
  const boardFv = rows.filter(r => r.fv != null && r.pos !== 'K' && r.pos !== 'P').map(r => r.fv).sort((a, b) => a - b);
  const pct = fv => { let lo = 0, hi = boardFv.length; while (lo < hi) { const m = (lo + hi) >> 1; if (boardFv[m] < fv) lo = m + 1; else hi = m; } return Math.round(100 * lo / boardFv.length); };
  const gCoef = fit.model.fv.coef[fit.model.fv.names.indexOf('g')] || 0;
  // the grade's range (the fit's miss is on the grade), each end put at its mean outcome
  const range = (p, k, gsd = 0, r = {}) => { const sd = Math.sqrt((fit.sdOn?.[Math.min(k, KMAX) - 1] ?? 6.2) ** 2 + (gCoef * gsd / 5) ** 2), m = x => r1(Math.max(fit.floor, meanOn({ ...r, k }, x))); return [m(Math.max(fit.floor, p.g.fvOn - 1.2816 * sd)), m(p.g.fvOn + 1.2816 * sd)]; };
  const hsN = fit.hsN || {};
  // one class with the fit's drivers: offers and high school (ESPN) and the 247 composite; a class 247 can't be
  // read for gets a composite level with its ESPN grade (no gap), so the gap terms stay neutral
  const whyQueue = [];   // [output row, feature row, redshirt?]: filled once the reference signee is known
  const cfbdCover = {};  // class -> CFBD composite coverage (attachCfbd)
  const prep = async (y, fresh) => {
    const raw = await reclassed(y, await espnClass(y, fresh, offline), y2 => espnClass(y2, false, offline)), moved = applyNews(raw, prog);
    if (moved) console.error(`class ${y}: ${moved} commitment changes from recruit news`);
    const cl = enrich(raw, prog, hsN), comp = await rank247(y, 'composite', snap247, offline);
    if (comp.length) attach247(cl, comp);
    else for (const r of cl) { r.comp = r.grade >= 60 ? 0.87 + 0.04 * (r.grade - 75) / 5 : null; r.cRank = r.r247 = null; }
    attachOn3(cl, y, y === season0);
    const cq = attachCfbd(cl, y); if (cq) cfbdCover[y] = cq;
    return cl;
  };
  // xNIL a recruit would draw at an FV and level: the board's median at that FV (whole points) and level
  const nilAt = (() => {
    const by = {};
    for (const r of rows) if (r.fv != null && r.xnil != null) { const lv = r.div === 'FCS' ? 'FCS' : P4_CONF.has(r.conf) || r.tid === '87' ? 'P4' : 'G5'; (by[lv + '|' + Math.round(r.fv)] ||= []).push(r.xnil); }
    const med = v => { const s = v.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
    return (lv, fv) => { for (let d = 0; d <= 6; d++) for (const f of [Math.round(fv) - d, Math.round(fv) + d]) { const v = by[lv + '|' + f]; if (v && v.length >= 3) return med(v); } return 0; };
  })();
  const xnil = (lv, p) => Math.round(p.pOn * nilAt(lv, p.fvOn) + (1 - p.pOn) * nilAt(lv, fit.floor));

  // 1) the next class: commitments to FBS and FCS programs, year 1 next season
  const next = season + 1;
  const cls = (await prep(next, true)).filter(c => c.tid && prog[c.tid]);
  const klass = [], clsRows = cls.map(c => mk(c, 1));
  centreCq(fit, clsRows);
  for (const [i, c] of cls.entries()) {
    const r = clsRows[i]; if (!r) continue;
    const p = predict(fit, r), P = prog[c.tid];
    whyQueue.push([null, r, false]);
    klass.push({ name: c.name, pos: c.pos, g: r.g, ht: c.ht, wt: c.wt, grade: c.grade || null, rank: c.rank, posRank: c.posRank, home: c.city && c.state ? `${c.city}, ${c.state}` : c.state,
      status: c.status === 'Verbal' ? 'committed' : c.status === 'Signed' ? 'signed' : String(c.status || '').toLowerCase(), team: P.team, tid: c.tid, logo: P.logo, conf: P.conf, level: P.level,
      pOn: r3(p.pOn), fvOn: r1(p.fvOn), xfv: r1(p.xfv), pct: pct(p.fvOn), range: range(p, 1, 0, r), path: pathOf(r), xnil: xnil(P.level, p), comp: c.comp, rRiv: c.rRiv ?? null, sRiv: c.sRiv ?? null, ark: 0, stars: c.grade >= 90 ? 5 : c.grade >= 80 ? 4 : c.grade >= 70 ? 3 : c.grade >= 60 ? 2 : null });
    { const x = klass[klass.length - 1]; x.ark = starsOf(r); whyQueue[whyQueue.length - 1][0] = x; }
  }
  // default order (and RK): ARK stars, then xFV, then ESPN grade
  klass.sort((a, b) => (b.ark || 0) - (a.ark || 0) || b.xfv - a.xfv || (b.grade || 0) - (a.grade || 0));

  // 2) on a roster now, no snaps: redshirts and buried freshmen of the last four classes
  const past = [];
  for (let y = season - KMAX + 1; y <= season; y++) past.push(...await prep(y, y === season));
  const recById = {}, recByNT = {}, recByN = {};
  const nameCount = {}; for (const c of past) { nameCount[norm(c.name)] = (nameCount[norm(c.name)] || 0) + 1; nameCount[short(c.name)] = (nameCount[short(c.name)] || 0) + 1; }
  for (const c of past) { if (c.id) recById[c.id] = c; if (c.tid) recByNT[norm(c.name) + '|' + c.tid] = c; if (nameCount[norm(c.name)] === 1) recByN[norm(c.name)] = c; if (nameCount[short(c.name)] === 1) recByN[short(c.name)] = c; }
  const ros = await rosters(teams.map(t => t.tid), season, offline);
  const redshirts = [], seen = new Set();
  for (const [tid, list] of Object.entries(ros)) for (const a of list) {
    if (byId[a.id] || byNT[norm(a.name) + '|' + tid]) continue;   // on the board: he has snaps
    // last name + first initial only for a recruit who signed with this school ("K. Russell" once matched the #2 QB at Alabama to an NDSU walk-on)
    const cs = recByN[short(a.name)], c = recById[a.id] || recByNT[norm(a.name) + '|' + tid] || recByN[norm(a.name)] || (cs && cs.tid === tid ? cs : null);
    if (!c || seen.has(c.rid)) continue;
    seen.add(c.rid);
    const k = season - c.year + 1;                                   // this season's year; he is scored at k + 1
    const r = mk({ ...c, tid, signedTid: c.tid, gpLast: 0, pos: c.pos, ht: c.ht || a.ht, wt: a.wt || c.wt }, k + 1); if (!r) continue;
    const p2 = predictRedshirt2(fit, { ...r, k: Math.min(k + 2, KMAX) });
    const p = predictRedshirt(fit, r), P = prog[tid];
    whyQueue.push([null, r, true]);
    redshirts.push({ name: a.name, pos: c.pos, g: r.g, team: P.team, tid, logo: P.logo, conf: P.conf, level: P.level, cls: c.year, year: k, grade: c.grade || null, rank: c.rank,
      ht: a.ht || c.ht, wt: a.wt || c.wt, signedWith: c.tid && c.tid !== tid ? prog[c.tid]?.team || null : null, pOn: r3(p.pOn), fvOn: r1(p.fvOn), xfv: r1(p.xfv),
      pct: pct(p.fvOn), range: range(p, k + 1, 0, r), xnil: xnil(P.level, p),
      pOn2: p2 ? r3(p2.pOn) : null, fvOn2: p2 ? r1(p2.fvOn) : null, xfv2: p2 ? r1(p2.xfv) : null, pct2: p2 ? pct(p2.fvOn) : null,
      ark: SI ? starsOf(r) : arkStars(p2 ? p2.g.xfv : p.g.xfv), stars: c.grade >= 90 ? 5 : c.grade >= 80 ? 4 : c.grade >= 70 ? 3 : c.grade >= 60 ? 2 : null });
    whyQueue[whyQueue.length - 1][0] = redshirts[redshirts.length - 1];
  }
  redshirts.sort((a, b) => b.xfv - a.xfv);

  // 1b) the classes two and three years out: every recruit ESPN lists, committed or not, scored at year 1 of
  // his own class. ESPN grades only its top 300 this early (the rest of its list is a watch list), so a recruit
  // without an ESPN grade takes the grade his 247 composite (else 247's own score) predicts, from a line fit on
  // the final classes: that regresses it toward the mean by how well the services agree, and its miss widens
  // his range. A watch-list recruit with neither takes the typical mapped grade of the watch list a year closer.
  // An uncommitted recruit goes to the typical program for his grade (where the last signed class went).
  const band = gr => gr >= 90 ? 5 : gr >= 80 ? 4 : gr >= 70 ? 3 : 0;
  const typical = {};
  for (const c of past) if (c.year === season && c.tid && prog[c.tid]) { const t = typical[band(c.grade)] ||= { n: 0, p4: 0, elo: 0 }; t.n++; t.p4 += prog[c.tid].level === 'P4'; t.elo += prog[c.tid].eloZ; }
  const gm = fit.gradeMap || {};
  const future = [];
  let watchGrade = null;
  for (const y of [next + 1, next + 2]) {
    const cl = await prep(y, true); if (!cl.length) continue;
    const own = await rank247(y, 'own', snap247, offline), byOwn = {};
    for (const o of own) for (const k of [norm(o.name) + '|' + o.state, short(o.name) + '|' + o.state]) (byOwn[k] ||= []).push(o);
    const src = { espn: 0, comp: 0, own: 0, watch: 0 }, mappedWatch = [];
    // composite to grade: fit on this class's own ESPN-graded recruits when there are enough (the composite runs
    // a point or two above ESPN this early), else the signed classes' line
    let cmap = gm.composite;
    { const both = cl.filter(c => c.grade >= 60 && c.comp);
      if (both.length >= 50) {
        const n = both.length, mx = both.reduce((a, c) => a + c.comp, 0) / n, my = both.reduce((a, c) => a + c.grade, 0) / n;
        const b = both.reduce((a, c) => a + (c.comp - mx) * (c.grade - my), 0) / both.reduce((a, c) => a + (c.comp - mx) ** 2, 0), a = my - b * mx;
        cmap = [a, b, Math.sqrt(both.reduce((s2, c) => s2 + (c.grade - a - b * c.comp) ** 2, 0) / n)];
      } }
    for (const c of cl) {
      const o = (byOwn[norm(c.name) + '|' + c.state] || byOwn[short(c.name) + '|' + c.state] || []);
      if (c.grade >= 60) { c.src = 'espn'; c.gsd = 0; }
      else if (c.comp && cmap) { c.grade = cmap[0] + cmap[1] * c.comp; c.src = 'comp'; c.gsd = cmap[2]; c.mapped = true; mappedWatch.push(c.grade); }   // the watch list's typical grade: from its composite-rated part
      else if (o.length === 1 && o[0].cRank && gm.ownRank) { c.grade = gm.ownRank[0] + gm.ownRank[1] * Math.log(o[0].cRank); c.src = 'own'; c.gsd = gm.ownRank[2]; c.mapped = true; }
      else { c.src = 'watch'; c.mapped = true; }
      src[c.src]++;
    }
    let wsd = 5;
    if (mappedWatch.length >= 20) { watchGrade = mappedWatch.reduce((a, x) => a + x, 0) / mappedWatch.length; wsd = Math.sqrt(mappedWatch.reduce((a, x) => a + (x - watchGrade) ** 2, 0) / mappedWatch.length); }
    const list = [], futRows = [];
    for (const c of cl) {
      if (c.src === 'watch') { if (watchGrade == null) continue; c.grade = watchGrade; c.gsd = Math.sqrt((gm.composite?.[2] ?? 4) ** 2 + wsd ** 2); }
      const committed = c.tid && prog[c.tid], t = typical[band(c.grade)] || typical[0];
      const P = committed ? prog[c.tid] : { level: t && t.p4 * 2 >= t.n ? 'P4' : 'G5', eloZ: t ? t.elo / t.n : 0 };
      const g = group(c.pos, c.wt); if (!g) continue;
      futRows.push([c, committed, P, g, { ...c, g, k: 1, level: P.level, eloZ: P.eloZ, dev: committed ? fit.model.dev[c.tid] || 0 : 0 }]);
    }
    centreCq(fit, futRows.map(x => x[4]));
    for (const [c, committed, P, g, r] of futRows) {
      const p = predict(fit, r);
      whyQueue.push([null, r, false]);
      list.push({ name: c.name, pos: c.pos, g, ht: c.ht, wt: c.wt, grade: r1(c.grade), src: c.src, rank: c.rank, home: c.city && c.state ? `${c.city}, ${c.state}` : c.state,
        status: committed ? 'committed' : 'uncommitted', team: committed ? P.team : null, tid: committed ? c.tid : null, logo: committed ? P.logo : null, conf: committed ? P.conf : null,
        pOn: r3(p.pOn), fvOn: r1(p.fvOn), xfv: r1(p.xfv), pct: pct(p.fvOn), range: range(p, 1, c.gsd || 0, r), path: pathOf(r), xnil: xnil(P.level, p),
        rRiv: c.rRiv ?? null, sRiv: c.sRiv ?? null, stars: c.src === 'espn' ? band(c.grade) || 2 : null });
      list[list.length - 1].ark = starsOf(r);
      whyQueue[whyQueue.length - 1][0] = list[list.length - 1];
    }
    list.sort((a, b) => (b.ark || 0) - (a.ark || 0) || b.xfv - a.xfv || (b.grade || 0) - (a.grade || 0));
    future.push({ year: y, lead: y - next + 1, n: list.length, committed: list.filter(x => x.tid).length, src, list,
      agree: (fit.agree || []).filter(a => a.class === y), agreeFinal: (fit.agree || []).filter(a => a.class <= season) });
  }

  // the reference: the average signee of the last signed class, at year 1, his inputs averaged block by block
  {
    const refRows = past.filter(c => c.year === season).map(c => mk(c, 1)).filter(Boolean), avg = m => {
      const acc = {};
      for (const r of refRows) { const v = linParts(fit, m, r, KMAX); for (const u in v) acc[u] = (acc[u] || 0) + v[u] / refRows.length; }
      return acc;
    };
    const ref = { on: avg(fit.model.on), fv: avg(fit.model.fv) };
    for (const [row, r, rsh] of whyQueue) if (row) row.why = whyOf(fit, r, ref, rsh);
  }

  // 3) young players with a few snaps: next season's FV blends the board with the recruit projection
  const young = [];
  for (const r of rows) {
    if (r.fv == null || !SNAPS_PER_GAME[r.pos] || r.snaps == null) continue;
    const id = /\/id\/(\d+)/.exec(r.espnl || '')?.[1], tid = r.tid || /\/logos\/(\d+)\.png/.exec(r.logo || '')?.[1];
    const c = (id && recById[id]) || recByNT[norm(r.name) + '|' + tid] || recByN[norm(r.name)];
    if (!c || !prog[tid]) continue;
    const k = season - c.year + 1; if (k > 2) continue;
    const K = SNAPS_PER_GAME[r.pos] * BLEND_GAMES, w = r.snaps / (r.snaps + K);
    if (w >= 0.5) continue;                 // past one game's snaps the board FV (its own priors included) stands
    const x = mk({ ...c, tid }, k + 1); if (!x) continue;
    const p = predict(fit, x);
    young.push({ name: r.name, pos: r.pos, team: r.team, tid, logo: r.logo, cls: c.year, year: k, grade: c.grade || null, snaps: r.snaps, fv: r.fv, rec: r1(p.fvOn), w: r3(w), next: r1(w * r.fv + (1 - w) * p.fvOn) });
  }
  young.sort((a, b) => b.next - a.next);

  // 4) next season's roster: returners (builder depth: FV and stay chance), redshirts and the class
  const B = Object.fromEntries((builder?.teams || []).map(t => [t.tid, t]));
  const yNext = Object.fromEntries(young.map(y => [y.tid + '|' + norm(y.name), y.next]));
  const add = {};
  const slotOf = g => g === 'ATH' ? null : g;
  // there next season = on the field (P(on)) and still at this school: the measured share of on-field sitters
  // and freshmen who are on the board at another school (transfers, flipped commitments)
  const hereRs = 1 - (fit.redshirt.away ?? 0), here1 = 1 - (fit.away1 ?? 0);
  for (const x of redshirts) if (slotOf(x.g)) (((add[x.tid] ||= {})[x.g]) ||= []).push({ name: x.name, fv: x.fvOn, stay: x.pOn * hereRs, kind: 'redshirt' });
  for (const x of klass) if (slotOf(x.g)) (((add[x.tid] ||= {})[x.g]) ||= []).push({ name: x.name, fv: x.fvOn, stay: x.pOn * here1, kind: 'recruit' });
  const roster = [];
  for (const t of teams) {
    const T = B[t.tid]; if (!T) continue;
    const rand = rng(+t.tid || 1);
    let avBase = 0, avNew = 0;
    const pos = {};
    for (const P of T.positions) {
      const back = (P.depth || []).map(d => ({ name: d.name, fv: yNext[t.tid + '|' + norm(d.name)] ?? d.fv, stay: d.stay, kind: 'back' }));
      const extra = (add[t.tid]?.[P.g] || []).filter(x => x.fv > P.repl);
      const a = slotsAv(back, P.n, P.repl, rand), b = slotsAv(back.concat(extra), P.n, P.repl, rand);
      avBase += a.av; avNew += b.av;
      pos[P.g] = { n: P.n, av: r1(b.av), avBack: r1(a.av), fv: b.fv.map(r1), adds: extra.sort((x, y) => y.fv * y.stay - x.fv * x.stay).slice(0, 4).map(x => ({ name: x.name, fv: x.fv, p: r3(x.stay), kind: x.kind })) };
    }
    const mine = klass.filter(x => x.tid === t.tid);
    roster.push({ tid: t.tid, team: t.team, logo: t.logo, conf: t.conf, level: prog[t.tid].level, av26: T.av26, avBack: r1(avBase), av27: r1(avNew), gain: r1(avNew - avBase),
      classN: mine.length, classXfv: r1(mine.reduce((s, x) => s + (x.xfv - fit.floor), 0)), classAv: r1(mine.reduce((s, x) => s + x.pOn * avOf(x.fvOn), 0)),
      classXnil: mine.reduce((s, x) => s + x.xnil, 0), redshirtN: redshirts.filter(x => x.tid === t.tid).length, top: mine.slice(0, 3).map(x => ({ name: x.name, pos: x.pos, xfv: x.xfv })), pos });
  }
  // class rank: expected FV points over the floor, summed (FBS programs)
  roster.sort((a, b) => b.classXfv - a.classXfv).forEach((t, i) => { t.classRk = i + 1; });
  roster.slice().sort((a, b) => b.av27 - a.av27).forEach((t, i) => { t.rk27 = i + 1; });
  // later classes ranked the same way, commits so far (the class-rankings year filter)
  for (const f of future) f.teams = classRanks(f.list, fit.floor);
  const q = f => boardFv[Math.floor(f * (boardFv.length - 1))];
  const boardRef = { p50: q(0.5), p75: q(0.75), p90: q(0.9), p99: q(0.99) };
  return { asof, season, next, floor: fit.floor, blendGames: BLEND_GAMES, boardRef, class: klass, future, redshirts, young, teams: roster,
    counts: { class: klass.length, committed: cls.length, redshirts: redshirts.length, young: young.length, future: future.map(f => f.n) },
    ...(Object.keys(cfbdCover).length ? { cfbd: Object.values(cfbdCover) } : {}) };
}
// class rankings for one class: each school's commits, expected FV points over the floor summed (as classXfv above)
export function classRanks(list, floor) {
  const by = {};
  for (const x of list) if (x.tid) (by[x.tid] ||= []).push(x);
  const out = Object.values(by).map(xs => {
    xs = xs.slice().sort((a, b) => b.xfv - a.xfv);
    return { tid: xs[0].tid, team: xs[0].team, logo: xs[0].logo, conf: xs[0].conf, classN: xs.length,
      classXfv: r1(xs.reduce((s, x) => s + (x.xfv - floor), 0)), classAv: r1(xs.reduce((s, x) => s + x.pOn * avOf(x.fvOn), 0)),
      classXnil: xs.reduce((s, x) => s + (x.xnil || 0), 0), top: xs.slice(0, 3).map(x => ({ name: x.name, pos: x.pos, xfv: x.xfv })) };
  });
  out.sort((a, b) => b.classXfv - a.classXfv || b.classN - a.classN).forEach((t, i) => { t.classRk = i + 1; });
  return out;
}
// expected FV at each starting slot (as the team builder's slots()): each player there with his chance
function slotsAv(players, n, repl, rand) {
  const acc = new Array(n).fill(0); let av = 0;
  for (let s = 0; s < SIMS; s++) {
    const on = []; for (const p of players) if (rand() < p.stay) on.push(p.fv);
    on.sort((a, b) => b - a);
    for (let k = 0; k < n; k++) { const f = Math.max(on[k] ?? repl, repl); acc[k] += f; av += avOf(f); }
  }
  return { fv: acc.map(x => x / SIMS), av: av / SIMS };
}

// writes data/cfb_recruits.json (the page's tables) and static/data/cfb-recruits.json (for the team builder)
export async function writeRecruits(root = ROOT, { offline = false } = {}) {
  const fitPath = path.join(root, 'data', 'cfb_recruit_fit.json');
  if (!fs.existsSync(fitPath)) return null;
  const fit = JSON.parse(fs.readFileSync(fitPath, 'utf8'));
  const all = JSON.parse(fs.readFileSync(path.join(root, 'static', 'data', 'cfb-all.json'), 'utf8'));
  const rows = all.rows.map(r => Object.fromEntries(all.cols.map((c, i) => [c, r[i]])));
  const teams = JSON.parse(fs.readFileSync(path.join(root, 'data', 'cfb_teams.json'), 'utf8')).teams;
  const bp = path.join(root, 'static', 'data', 'cfb-builder.json'), builder = fs.existsSync(bp) ? JSON.parse(fs.readFileSync(bp, 'utf8')) : null;
  const sp = path.join(root, 'scripts', 'cfb_recruit_247.json'), snap247 = fs.existsSync(sp) ? JSON.parse(fs.readFileSync(sp, 'utf8')) : null;
  const out = await recruitBoard({ fit, rows, teams, builder, season: +all.asof.slice(0, 4), asof: all.asof, offline, snap247 });
  fs.writeFileSync(path.join(root, 'static', 'data', 'cfb-recruits.json'), JSON.stringify(out));
  // the team builder's depth charts carry each newcomer's ARK stars from the recruit file it was built on (the board
  // writes the builder before this runs): restamp them from this run so a star change shows there at once
  if (builder?.teams) {
    const st = new Map([...(out.class || []), ...(out.redshirts || [])].filter(x => x.tid).map(x => [x.tid + '|' + x.name, x.ark ?? null]));
    let n = 0;
    for (const t of builder.teams) for (const g of t.positions || []) for (const k of ['chart', 'lineup', 'bench'])
      for (const p of g[k] || []) if ((p.kind === 'recruit' || p.kind === 'redshirt') && st.has(t.tid + '|' + p.name) && p.ark !== st.get(t.tid + '|' + p.name)) { p.ark = st.get(t.tid + '|' + p.name); n++; }
    if (n) { fs.writeFileSync(bp, JSON.stringify(builder)); console.log(`recruits: ${n} team builder ARK stars restamped`); }
  }
  // the page renders the top of each list server-side; the full lists are in static/data/cfb-recruits.json
  const page = { ...out, class: out.class.slice(0, 300), future: out.future.map(f => ({ ...f, list: f.list.slice(0, 300) })), redshirts: out.redshirts.slice(0, 150), young: out.young.slice(0, 100), teams: out.teams.map(({ pos, ...t }) => t) };
  fs.writeFileSync(path.join(root, 'data', 'cfb_recruits.json'), JSON.stringify(page, null, 1) + '\n');
  console.log(`recruits: ${out.counts.class} in the ${out.next} class, ${out.future.map(f => `${f.n} in ${f.year}`).join(', ')}, ${out.counts.redshirts} without snaps, ${out.counts.young} young low-snap players, ${out.teams.length} rosters`);
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await writeRecruits(ROOT, { offline: process.argv.includes('--offline') });
