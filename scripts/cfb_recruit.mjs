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
import { fileURLToPath } from 'node:url';
import { avOf, STARTERS } from './cfb_teams.mjs';
import { on3Class } from './cfb_on3_recruits.mjs';

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

export const norm = s => String(s || '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '').replace(/[^a-z]/g, '');
// last name + first initial, for nicknames (Samuel -> Sam); the fit links the same way
export function short(s) {
  const w = String(s || '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '').replace(/\./g, '').split(/\s+/).filter(Boolean);
  return w.length > 1 ? '~' + w.slice(1).join('').replace(/[^a-z]/g, '') + w[0][0] : '~';
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
const HOT_STATES = ['TX', 'FL', 'GA', 'CA', 'AL', 'LA', 'OH'];

// ---- the fit's feature blocks (scripts/cfb_recruit_fit.py blocks()) --------------------------------------
function blocks(r, sz, KMAX) {
  const gr = r.grade, k = r.k, rated = gr >= 60, g = rated ? (gr - 75) / 5 : 0;
  const [hm, hs, wm, ws] = sz[r.g].slice(0, 4), rk = r.rank || 0, pr = r.posRank || 0;
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
    bmi: { bmiz: r.ht && r.wt && sz[r.g].length >= 6 ? (703 * r.wt / r.ht ** 2 - sz[r.g][4]) / sz[r.g][5] : 0 },
    offers: { lnoff: Math.log1p(r.nOff || 0), offElo: r.offElo ?? 0, offTop: r.offTop ?? 0, noOff: r.offElo != null ? 0 : 1 },
    interest: { lnint: r.interest ? Math.log1p(r.interest) : 0 },
    on3: { o3: r.o3 ? (r.o3 - 85) / 4 : 0, o3miss: r.o3 ? 0 : 1 },
    gap: { gap: r.o3 && r.riv ? (r.o3 - 85) / 4 - (r.riv - 85) / 4 : 0 },
    state: Object.fromEntries(HOT_STATES.map(st => ['s_' + st, r.state === st ? 1 : 0])),
  };
  for (const p of GROUPS) if (p !== 'WR') { o.pos['p_' + p] = r.g === p ? 1 : 0; o.pos_year1['p1_' + p] = r.g === p && k === 1 ? 1 : 0; }
  for (let j = 2; j <= KMAX; j++) o.year['k' + j] = k === j ? 1 : 0;
  return o;
}
export function predict(fit, r) {
  const b = blocks(r, fit.sizeNorms, fit.classes[1] - fit.classes[0] + 1);
  const lin = m => { const row = {}; for (const u of m.blocks) Object.assign(row, b[u]); return m.names.reduce((a, n, i) => a + (row[n] ?? 0) * m.coef[i], m.b0); };
  const pOn = sig(lin(fit.model.on)), fvOn = Math.max(fit.floor, lin(fit.model.fv));
  return { pOn, fvOn, xfv: pOn * fvOn + (1 - pOn) * fit.floor };
}
// a player on a roster who hasn't played: recalibrated on last season's sitters (one season on) and on the
// sitters of two seasons ago (two on). r is scored at the year he moves into; r2 at the year after that.
const RS_EXTRA = {
  games: r => ({ gp14: r.gpLast >= 1 && r.gpLast <= 4 ? 1 : 0 }), grade: (r, b) => b.grade, offers: (r, b) => b.offers, on3: (r, b) => b.on3, gap: (r, b) => b.gap,
  interest: (r, b) => b.interest, bmi: (r, b) => b.bmi, size: (r, b) => b.size, level: r => ({ p4: r.level === 'P4' ? 1 : 0 }),
  moved: r => ({ moved: r.tid && r.tidLast && r.tidLast !== r.tid ? 1 : 0 }),
};
export function predictRedshirt(fit, r, r2) {
  const rs = fit.redshirt, lg = p => Math.log(p / (1 - p));
  const base = predict(fit, r), b = blocks(r, fit.sizeNorms, fit.classes[1] - fit.classes[0] + 1);
  const ex = Object.assign({}, ...(rs.extra || []).map(u => RS_EXTRA[u](r, b)));
  const pOn = sig(rs.a + rs.b * lg(base.pOn) + (rs.names || []).reduce((a, n, i) => a + (ex[n] ?? 0) * rs.coef[i], 0));
  const fvOn = Math.max(fit.floor, base.fvOn + rs.fvShift);
  const out = { pOn, fvOn, xfv: pOn * fvOn + (1 - pOn) * fit.floor };
  if (r2 && rs.two) {
    const b2 = predict(fit, r2), p2 = sig(rs.two.a + rs.two.b * lg(b2.pOn)), f2 = Math.max(fit.floor, b2.fvOn + rs.two.fvShift);
    Object.assign(out, { pOn2: p2, fvOn2: f2, xfv2: p2 * f2 + (1 - p2) * fit.floor });
  }
  return out;
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

// a whole ESPN class: athlete id once enrolled, name, position, size, grade, ranks, committed or signed school
async function espnClass(y, fresh, offline) {
  const name = `espnclass2-${y}.json`;
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
        status: it.status?.description || null, tid: school ? school[1] : null, year: y,
        offers: (it.schools || []).map(s => /\/teams\/(\d+)/.exec(s.team?.$ref || '')?.[1]).filter(Boolean) });
    }
    if (pg >= (d.pageCount || 1)) break;
    await sleep(150);
  }
  if (acc.length) writeCache(name, acc);
  return acc.length ? acc : hasCache(name) ? readCache(name) : [];
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
export async function recruitBoard({ fit, rows, teams, builder, season, asof, offline = false }) {
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
  const slug = x => String(x || '').toLowerCase().replace(/&/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const slugTid = {}; for (const t of teams) slugTid[slug(t.full || t.team)] = t.tid;
  const mk = (c, k, O) => { const g = group(c.pos, c.wt), p = prog[c.tid]; return g && p ? { ...c, ...(O ? feats(c, O) : {}), g, k: Math.min(k, KMAX), level: p.level, eloZ: p.eloZ, dev: fit.model.dev[c.tid] || 0 } : null; };
  const pathOf = r => [1, 2, 3].map(k => r1(predict(fit, { ...r, k }).xfv));
  // xNIL a recruit would draw at an FV and level: the board's median at that FV (whole points) and level
  const nilAt = (() => {
    const by = {};
    for (const r of rows) if (r.fv != null && r.xnil != null) { const lv = r.div === 'FCS' ? 'FCS' : P4_CONF.has(r.conf) || r.tid === '87' ? 'P4' : 'G5'; (by[lv + '|' + Math.round(r.fv)] ||= []).push(r.xnil); }
    const med = v => { const s = v.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
    return (lv, fv) => { for (let d = 0; d <= 6; d++) for (const f of [Math.round(fv) - d, Math.round(fv) + d]) { const v = by[lv + '|' + f]; if (v && v.length >= 3) return med(v); } return 0; };
  })();
  const xnil = (lv, p) => Math.round(p.pOn * nilAt(lv, p.fvOn) + (1 - p.pOn) * nilAt(lv, fit.floor));

  // On3 / Rivals (consensus rating, Rivals rating, schools in on him) and ESPN's offer list, by name
  const on3By = {};
  const on3Of = async (y, fresh) => {
    if (on3By[y]) return on3By[y];
    const L = await on3Class(y, { fresh, offline }) || [], n = {};
    for (const x of L) n[norm(x.name)] = (n[norm(x.name)] || 0) + 1;
    return (on3By[y] = Object.fromEntries(L.filter(x => n[norm(x.name)] === 1).map(x => [norm(x.name), x])));
  };
  const feats = (c, O) => {
    const o = O?.[norm(c.name)], offs = (c.offers || []).map(t => prog[t]).filter(p => p && p.level !== 'FCS').map(p => p.eloZ);
    return { o3: o?.cons ?? null, riv: o?.rating ?? null, interest: o?.interest ?? null, nOff: (c.offers || []).length,
      offElo: offs.length ? offs.reduce((a, x) => a + x, 0) / offs.length : null, offTop: offs.length ? Math.max(...offs) : null, state: c.state };
  };
  const bandSd = Math.sqrt((fit.test?.rmse_on ?? 6.3) ** 2);
  const ncdf = z => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2), p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - p : p; };
  // where an xFV sits on this season's board (FBS + FCS, every graded player)
  const boardFv = rows.filter(r => r.fv != null && r.pos !== 'K' && r.pos !== 'P').map(r => r.fv).sort((x, y) => x - y);
  const pctOf = v => { let lo = 0, hi = boardFv.length; while (lo < hi) { const m = (lo + hi) >> 1; if (boardFv[m] < v) lo = m + 1; else hi = m; } return Math.round(lo / boardFv.length * 1000) / 10; };
  // an uncommitted recruit is scored at the program strength his grade usually lands (the next class's commits)
  const landing = { a: 0, b: 0 };

  // 1) the classes still being recruited: the next class (year 1 next season) and the ones after it.
  // A rating that early is shrunk toward the class mean by its measured reliability (fit.future), and the
  // FV-if-on range widens with what the shrink takes out.
  const future = fit.future || {};
  const classes = {};
  for (const Y of [season + 1, season + 2, season + 3]) {
    const fresh = true, O = await on3Of(Y, fresh), E = await espnClass(Y, fresh, offline);
    const lam = Y === season + 1 ? 1 : (future[Y]?.lambda ?? 1), map = fit.on3ToEspn;   // ESPN grade from On3's consensus when ESPN has none
    const seen = new Set(), list = [];
    // a younger class has fewer offers and less interest so far: scale both to the next class's level (the
    // median among recruits On3 rates), and pull On3's consensus toward its mean by how well it agrees yet
    const med = v => { const x = v.filter(Boolean).sort((a, b) => a - b); return x.length ? x[Math.floor(x.length / 2)] : null; };
    const offMed = med(E.filter(c => O[norm(c.name)]).map(c => (c.offers || []).length)), intMed = med(Object.values(O).map(o => o.interest));
    if (Y === season + 1) Object.assign(landing, { offMed, intMed });
    const offScale = Y > season + 1 && offMed ? landing.offMed / offMed : 1, intScale = Y > season + 1 && intMed ? landing.intMed / intMed : 1;
    const lamC = Y > season + 1 && future[Y]?.rivalsConsensus && fit.future?.final?.rivalsConsensus ? Math.min(1, future[Y].rivalsConsensus / fit.future.final.rivalsConsensus) : 1;
    const recs = E.map(c => ({ ...c })).concat(Object.values(O).filter(o => !E.some(c => norm(c.name) === norm(o.name))).map(o => ({ name: o.name, pos: o.pos, ht: o.ht, wt: o.wt, grade: 0, rank: o.rank, posRank: o.posRank, state: o.state, status: o.committed ? 'Verbal' : 'Undecided', tid: null, year: Y, offers: [], on3School: o.school })));
    for (const c of recs) {
      if (seen.has(norm(c.name))) continue; seen.add(norm(c.name));
      const f = feats(c, O);
      if (Y > season + 1) {
        f.nOff = Math.round(f.nOff * offScale); if (f.interest) f.interest *= intScale;
        if (f.o3) f.o3 = 85 + lamC * (f.o3 - 85); if (f.riv) f.riv = 85 + lamC * (f.riv - 85);
      }
      let grade = c.grade >= 60 ? c.grade : f.o3 && map ? map.a + map.b * f.o3 : 0;
      const src = c.grade >= 60 ? 'ESPN' : grade ? 'On3' : null;
      if (Y > season + 1 && !grade) continue;                          // too early to be rated: nothing to project yet
      const gMean = future[Y]?.gradeMean ?? 77;
      if (grade && lam < 1) grade = gMean + lam * (grade - gMean);
      let tid = c.tid && prog[c.tid] ? c.tid : c.on3School ? slugTid[c.on3School] || null : null;
      if (Y === season + 1 && !tid) continue;                          // the next class: commitments only
      const g = group(c.pos, c.wt); if (!g) continue;
      const P = tid ? prog[tid] : null;
      const eloZ = P ? P.eloZ : landing.a + landing.b * ((grade || 70) - 75) / 5;
      const r = { ...c, ...f, grade, g, k: 1, level: P ? P.level : 'P4', eloZ, dev: tid ? fit.model.dev[tid] || 0 : 0 };
      const p = predict(fit, r), p3 = predict(fit, { ...r, k: 3 });
      const sd = Math.sqrt(bandSd ** 2 + (1 - lam * lam) * (fit.signalSd ?? 4) ** 2);
      const up = p3.pOn * (1 - ncdf((50 - p3.fvOn) / sd));            // chance he is a 50+ FV player by year 3
      list.push({ name: c.name, pos: c.pos, g, ht: c.ht, wt: c.wt, grade: c.grade >= 60 ? c.grade : null, o3: f.o3 ? r1(f.o3) : null, src, rank: c.rank, posRank: c.posRank,
        home: c.city && c.state ? `${c.city}, ${c.state}` : c.state, status: tid ? (c.status === 'Signed' ? 'signed' : 'committed') : 'uncommitted',
        team: P?.team || null, tid, logo: P?.logo || null, conf: P?.conf || null, level: P?.level || null,
        pOn: r3(p.pOn), fvOn: r1(p.fvOn), xfv: r1(p.xfv), y3: r1(p3.fvOn), xfv3: r1(p3.xfv), pct: pctOf(p3.xfv), p50: r3(up),
        lo: r1(Math.max(fit.floor, p.fvOn - 1.28 * sd)), hi: r1(p.fvOn + 1.28 * sd), path: pathOf(r), xnil: xnil(P?.level || 'P4', p),
        stars: (c.grade >= 60 ? c.grade : grade) >= 90 ? 5 : (c.grade >= 60 ? c.grade : grade) >= 80 ? 4 : (c.grade >= 60 ? c.grade : grade) >= 70 ? 3 : grade >= 60 ? 2 : null });
    }
    list.sort((x, y) => y.xfv - x.xfv || (y.grade || 0) - (x.grade || 0));
    if (Y === season + 1) {   // where each grade lands: least squares of the commits' program strength on grade
      const xs = list.filter(x => x.tid && prog[x.tid] && x.grade).map(x => [(x.grade - 75) / 5, prog[x.tid].eloZ]);
      const mx = xs.reduce((a, v) => a + v[0], 0) / xs.length, my = xs.reduce((a, v) => a + v[1], 0) / xs.length;
      landing.b = xs.reduce((a, v) => a + (v[0] - mx) * (v[1] - my), 0) / xs.reduce((a, v) => a + (v[0] - mx) ** 2, 0); landing.a = my - landing.b * mx;
    }
    classes[Y] = { list, lambda: lam, lambdaOn3: r3(lamC), offScale: r3(offScale), intScale: r3(intScale), rated: list.length, committed: list.filter(x => x.tid).length, espn: E.length, on3: Object.keys(O).length, note: future[Y]?.note || null };
  }
  const next = season + 1, klass = classes[next].list, cls = klass;

  // 2) on a roster now, no snaps: redshirts and buried freshmen of the last four classes
  const past = [];
  for (let y = season - KMAX + 1; y <= season; y++) past.push(...await espnClass(y, y === season, offline));
  const recById = {}, recByNT = {}, recByN = {};
  const nameCount = {}; for (const c of past) { nameCount[norm(c.name)] = (nameCount[norm(c.name)] || 0) + 1; nameCount[short(c.name)] = (nameCount[short(c.name)] || 0) + 1; }
  for (const c of past) { if (c.id) recById[c.id] = c; if (c.tid) recByNT[norm(c.name) + '|' + c.tid] = c; if (nameCount[norm(c.name)] === 1) recByN[norm(c.name)] = c; if (nameCount[short(c.name)] === 1) recByN[short(c.name)] = c; }
  const ros = await rosters(teams.map(t => t.tid), season, offline);
  const O3 = {}; for (let y = season - KMAX + 1; y <= season; y++) O3[y] = await on3Of(y, false);
  const redshirts = [], seen = new Set();
  for (const [tid, list] of Object.entries(ros)) for (const a of list) {
    if (byId[a.id] || byNT[norm(a.name) + '|' + tid]) continue;   // on the board: he has snaps
    let c = recById[a.id] || recByNT[norm(a.name) + '|' + tid] || recByN[norm(a.name)];
    if (!c) { const x = recByN[short(a.name)]; if (x && x.tid === tid) c = x; }   // a first-initial match only at the school he signed with
    if (!c || seen.has(c.rid)) continue;
    seen.add(c.rid);
    const k = season - c.year + 1;                                   // this season's year; he is scored at k + 1
    const base = { ...c, signedTid: c.tid, tid, tidLast: tid, pos: c.pos, ht: c.ht || a.ht, wt: a.wt || c.wt };
    const r = mk(base, k + 1, O3[c.year]); if (!r) continue;
    r.gpLast = 0; r.tidLast = tid; r.tid = c.tid || tid;               // the fit's terms: tid = signing school, tidLast = where he sits
    const r2 = mk(base, Math.min(k + 2, KMAX), O3[c.year]); if (r2) { r2.gpLast = 0; r2.tidLast = tid; }
    const p = predictRedshirt(fit, r, r2), P = prog[tid];
    redshirts.push({ name: a.name, pos: c.pos, g: r.g, team: P.team, tid, logo: P.logo, conf: P.conf, level: P.level, cls: c.year, year: k, grade: c.grade || null, rank: c.rank,
      ht: a.ht || c.ht, wt: a.wt || c.wt, signedWith: c.tid && c.tid !== tid ? prog[c.tid]?.team || null : null, pOn: r3(p.pOn), fvOn: r1(p.fvOn), xfv: r1(p.xfv), xnil: xnil(P.level, p),
      pOn2: p.pOn2 != null ? r3(p.pOn2) : null, fvOn2: p.fvOn2 != null ? r1(p.fvOn2) : null, xfv2: p.xfv2 != null ? r1(p.xfv2) : null });
  }
  redshirts.sort((a, b) => b.xfv - a.xfv);

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
    const x = mk({ ...c, tid }, k + 1, O3[c.year]); if (!x) continue;
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
  // the later classes' meta for the page (coverage, the reliability test); the next class's list stays in .class
  const later = Object.fromEntries(Object.entries(classes).map(([Y, c]) => [Y, { ...c, list: undefined, future: future[Y] || null }]));
  return { asof, season, next, floor: fit.floor, blendGames: BLEND_GAMES, class: klass, classes: Object.fromEntries(Object.entries(classes).map(([Y, c]) => [Y, c.list])), classMeta: later,
    redshirts, young, teams: roster, counts: { class: klass.length, committed: cls.length, redshirts: redshirts.length, young: young.length } };
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
  const out = await recruitBoard({ fit, rows, teams, builder, season: +all.asof.slice(0, 4), asof: all.asof, offline });
  fs.writeFileSync(path.join(root, 'static', 'data', 'cfb-recruits.json'), JSON.stringify(out));
  // the page renders the top of each list server-side; the full lists are in static/data/cfb-recruits.json
  const page = { ...out, class: out.class.slice(0, 300), classes: Object.fromEntries(Object.entries(out.classes).map(([Y, l]) => [Y, l.slice(0, 300)])), redshirts: out.redshirts.slice(0, 150), young: out.young.slice(0, 100), teams: out.teams.map(({ pos, ...t }) => t) };
  fs.writeFileSync(path.join(root, 'data', 'cfb_recruits.json'), JSON.stringify(page, null, 1) + '\n');
  console.log(`recruits: ${Object.entries(out.classes).map(([Y, l]) => `${Y} ${l.length}`).join(', ')}; ${out.counts.redshirts} without snaps, ${out.counts.young} young low-snap players, ${out.teams.length} rosters`);
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await writeRecruits(ROOT, { offline: process.argv.includes('--offline') });
