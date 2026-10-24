// Backtest: do ESPN's NFL draft prospect file and PFF's college big board add to FV for draft-eligible players
// beyond production and a final big board? Run by hand after scripts/cfb_statplus_backtest.mjs and
// scripts/cfb_source_backtest.mjs (their caches: PFN boards, nflverse picks and combine, DraftTek, Wikipedia):
//   node scripts/cfb_draft_source_backtest.mjs -> data/cfb_draft_source_backtest.json
// Sources (cached in scripts/.cache/sources/{espn,pff}; ESPN ~400-1,200 calls a class, 8 threads):
//   ESPN  sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/<D>/draft/athletes(/<id>), 2014-23: pre-draft
//         grade, overall rank, position rank, arm, hand, 40 (`speed`), the ESPN college athlete id, the pick. Never read:
//         hofYear, apDefRookie, kiperGrade (outcome fields in older classes). The in-season 2027 file holds only a
//         50-deep overall/position rank (no grade, arm, hand or 40): ESPN's board, which the consensus already counts
//   PFF   pff.com/api/college/big_board?season=<D>&version=<v>, 2018-23: the deepest version dated before the draft;
//         grade_1 = PFF's grade of the final college season (value, snaps, rank at the position)
// Universes. U2 "pool": every ESPN prospect 2014-23 (no K, P, LS) at ten groups; outcome NFL weighted AV a season
// through 2025 (pick joined to nflverse by class and overall pick; undrafted 0). Control = ESPN's board (ln overall and
// its square, unranked flag, group intercepts and group x ln overall). U1 "pfn": cfb_source_backtest's universe (last
// PFN season 2019-22, seven groups), controls A = production, B = production + a final board (DraftTek's, ESPN's, both).
// Each candidate: in-sample t, held-out R^2 gain leaving one draft class out (pooled and per class; fold t = mean / se
// of the per-class gains), within-position Spearman of the held-out prediction, and a forward check (fit 2014-19,
// score 2020-23). Ships only with fold t >= 2, Spearman not worse, forward not worse, and a pass on U1 control B.
// Result (Oct 24, 2026; 3,357 ranked prospects 2014-23, 695 ESPN-ranked of 3,210 PFN last seasons): nothing ships.
//   ESPN's board is a better control than DraftTek's (U1 held-out R^2 53.8 -> 55.9, both 56.9; ESPN over DraftTek fold
//   t 6.1), but the Oct 14 failures (All-America, Senior Bowl, combine invite, program picks) still fail on 10 classes;
//   combine testing still passes (fold t 3.8, the shipped FV_ATH). ESPN grade beyond its rank, arm, hand, ESPN's 40 and
//   PFF's final-season grade all miss fold t 2 in the pool and add nothing under U1 control B. Position rank passes U1
//   (fold t 2.5-3.4, in-sample t -1.6 once the board has group slopes) but not the pool (fold t -.2): board form.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { NFLPOS, famOf } from './cfb_nflpos.mjs';
import { Matcher, key } from './names.mjs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SP = path.join(ROOT, 'scripts', '.cache', 'statplus'), SRC = path.join(ROOT, 'scripts', '.cache', 'sources');
const EC = path.join(SRC, 'espn'), PC = path.join(SRC, 'pff');
const OUT = path.join(ROOT, 'data', 'cfb_draft_source_backtest.json');
for (const d of [EC, PC]) fs.mkdirSync(d, { recursive: true });
const NFL_THROUGH = 2025, CLASSES = Array.from({ length: 10 }, (_, i) => 2014 + i), FWD = 2020;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';

// ---- helpers ------------------------------------------------------------------------------------------------------
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
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sdv = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;
function solve(A, b) {
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = c + 1; r < n; r++) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  const x = Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) { let s = M[r][n]; for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k]; x[r] = s / M[r][r]; }
  return x;
}
function xtx(X) { const k = X[0].length + 1, A = Array.from({ length: k }, () => Array(k).fill(0)); for (const r of X) { const z = [1, ...r]; for (let a = 0; a < k; a++) for (let c = 0; c < k; c++) A[a][c] += z[a] * z[c]; } return A; }
function ols(X, y) {
  const k = X[0].length, A = xtx(X), b = Array(k + 1).fill(0);
  X.forEach((r, i) => { const z = [1, ...r]; for (let a = 0; a <= k; a++) b[a] += z[a] * y[i]; });
  for (let a = 1; a <= k; a++) A[a][a] += 1e-6;
  return solve(A, b);
}
const pred = (co, r) => co[0] + r.reduce((a, x, i) => a + co[i + 1] * x, 0);
function ranks(xs) { const o = xs.map((x, i) => [x, i]).sort((a, b) => a[0] - b[0]), r = Array(xs.length); for (let i = 0; i < o.length;) { let j = i; while (j + 1 < o.length && o[j + 1][0] === o[i][0]) j++; for (let k = i; k <= j; k++) r[o[k][1]] = (i + j) / 2; i = j + 1; } return r; }
function pearson(a, b) { const ma = mean(a), mb = mean(b); let s = 0, x = 0, y = 0; a.forEach((v, i) => { s += (v - ma) * (b[i] - mb); x += (v - ma) ** 2; y += (b[i] - mb) ** 2; }); return x && y ? s / Math.sqrt(x * y) : 0; }
const spear = (a, b) => pearson(ranks(a), ranks(b));
// within-group Spearman of predictions with the outcome, n-weighted over groups with 15+ rows
function wSpear(rows, pr) { let s = 0, n = 0; const by = {}; rows.forEach((p, i) => (by[p.g] ||= []).push(i)); for (const ix of Object.values(by)) { if (ix.length < 15) continue; s += ix.length * spear(ix.map(i => pr[i]), ix.map(i => rows[i].av)); n += ix.length; } return n ? s / n : null; }

// the gate statistics of candidate x on top of control ctl (rows without x dropped)
function test(P, ctl, x, { folds = 'cls' } = {}) {
  const S = P.filter(p => x(p) != null && isFinite(x(p)));
  if (S.length < 40 || new Set(S.map(x)).size < 2) return null;
  const X = S.map(p => [...ctl(p), x(p)]), y = S.map(p => p.av), co = ols(X, y), k = X[0].length + 1;
  const res = y.map((v, i) => v - pred(co, X[i])), s2 = res.reduce((a, e) => a + e * e, 0) / (S.length - k);
  const e = Array(k).fill(0); e[k - 1] = 1; const A = xtx(X); for (let a = 1; a < k; a++) A[a][a] += 1e-6;
  const se = Math.sqrt(s2 * solve(A, e)[k - 1]), sx = sdv(S.map(x));
  const cls = [...new Set(S.map(p => p.D))].sort();
  const p0 = Array(S.length), p1 = Array(S.length), fg = [];
  let sse0 = 0, sse1 = 0, sst = 0;
  for (const c of cls) {
    const tr = S.filter(p => p.D !== c), ti = S.map((p, i) => p.D === c ? i : -1).filter(i => i >= 0);
    if (tr.length < 30 || ti.length < 5) continue;
    const my = mean(tr.map(p => p.av)), b0 = ols(tr.map(ctl), tr.map(p => p.av)), b1 = ols(tr.map(p => [...ctl(p), x(p)]), tr.map(p => p.av));
    let a0 = 0, a1 = 0, at = 0;
    for (const i of ti) { const p = S[i]; p0[i] = pred(b0, ctl(p)); p1[i] = pred(b1, [...ctl(p), x(p)]); a0 += (p.av - p0[i]) ** 2; a1 += (p.av - p1[i]) ** 2; at += (p.av - my) ** 2; }
    sse0 += a0; sse1 += a1; sst += at; fg.push(100 * (a0 - a1) / at);
  }
  const ok = S.map((_, i) => p0[i] != null), SS = S.filter((_, i) => ok[i]);
  const sp0 = wSpear(SS, p0.filter((_, i) => ok[i])), sp1 = wSpear(SS, p1.filter((_, i) => ok[i]));
  const fm = mean(fg), fse = sdv(fg) * Math.sqrt(fg.length / Math.max(1, fg.length - 1)) / Math.sqrt(fg.length);
  // forward: fit the classes before FWD, score FWD on
  let fwd = null;
  const tr = S.filter(p => p.D < FWD), te = S.filter(p => p.D >= FWD);
  if (tr.length >= 40 && te.length >= 20 && new Set(tr.map(x)).size > 1) {
    const b0 = ols(tr.map(ctl), tr.map(p => p.av)), b1 = ols(tr.map(p => [...ctl(p), x(p)]), tr.map(p => p.av)), my = mean(tr.map(p => p.av));
    const q0 = te.map(p => pred(b0, ctl(p))), q1 = te.map(p => pred(b1, [...ctl(p), x(p)]));
    const e0 = te.reduce((a, p, i) => a + (p.av - q0[i]) ** 2, 0), e1 = te.reduce((a, p, i) => a + (p.av - q1[i]) ** 2, 0), et = te.reduce((a, p) => a + (p.av - my) ** 2, 0);
    fwd = { n: te.length, gain: r3(100 * (e0 - e1) / et), spear0: r3(wSpear(te, q0)), spear1: r3(wSpear(te, q1)) };
  }
  const out = { n: S.length, classes: cls.length, perSd: r3(co[k - 1] * sx), t: Math.round(co[k - 1] / se * 100) / 100,
    oosGain: r3(100 * (sse0 - sse1) / sst), foldT: Math.round(fm / fse * 100) / 100, won: fg.filter(v => v > 0).length + '/' + fg.length,
    spear0: r3(sp0), spear1: r3(sp1), fwd, ctlR2: r3(100 * (1 - sse0 / sst)) };
  out.pass = out.foldT >= 2 && out.oosGain > 0 && sp1 >= sp0 - 1e-4 && (!fwd || (fwd.gain >= 0 && fwd.spear1 >= fwd.spear0 - 1e-4));
  return out;
}

// ---- sources --------------------------------------------------------------------------------------------------------
async function getJSON(u) { for (let i = 0; i < 3; i++) { try { const r = await fetch(u, { headers: { 'user-agent': UA } }); if (r.ok) return await r.json(); } catch {} } return null; }
async function espnClass(D) {
  const f = path.join(EC, `espn_draft_${D}.json`); if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f, 'utf8'));
  const NFL = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons', picks = {}, refs = [];
  for (const rd of (await getJSON(`${NFL}/${D}/draft/rounds?limit=20`))?.items || []) for (const k of rd.picks) if (k.athlete) picks[/athletes\/(\d+)/.exec(k.athlete.$ref)[1]] = k.overall;
  for (let p = 1; ; p++) { const d = await getJSON(`${NFL}/${D}/draft/athletes?limit=100&page=${p}`); if (!d) break; refs.push(...d.items.map(x => x.$ref)); if (p >= d.pageCount) break; }
  const rows = [];
  for (let i = 0; i < refs.length; i += 8) rows.push(...(await Promise.all(refs.slice(i, i + 8).map(async r => { const a = await getJSON(r.replace('http:', 'https:')); if (!a) return null;
    // only pre-draft attributes are kept (grade, overall, rank, speed, arm, hand): never hofYear, apDefRookie, kiperGrade
    const at = Object.fromEntries((a.attributes || []).filter(x => ['grade', 'overall', 'rank', 'speed', 'arm', 'hand'].includes(x.name)).map(x => [x.name, x.value ?? null]));
    return { did: a.id, cid: /athletes\/(\d+)/.exec(a.athlete?.$ref || '')?.[1] ?? null, tid: /teams\/(\d+)/.exec(a.team?.$ref || '')?.[1] ?? null, n: a.displayName, pos: a.position?.abbreviation, ht: a.height, wt: a.weight, at, pick: picks[a.id] ?? null }; }))).filter(Boolean));
  fs.writeFileSync(f, JSON.stringify(rows)); return rows;
}
const DRAFT_DAY = { 2018: '2018-04-26', 2019: '2019-04-25', 2020: '2020-04-23', 2021: '2021-04-29', 2022: '2022-04-28', 2023: '2023-04-27' }, PFF_LATE = [];
function pffClass(D) {
  // the deepest board version dated before the draft (versions are fetched once, cached)
  let best = null, late = null;
  for (let v = 1; v <= 15; v++) {
    const f = path.join(PC, `pff_${D}_${v}.json`);
    if (!fs.existsSync(f)) try { execFileSync('curl', ['-sSL', '-m', '60', '-A', 'Mozilla/5.0', '-o', f, `https://www.pff.com/api/college/big_board?season=${D}&version=${v}`]); } catch { continue; }
    let d; try { d = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { continue; }
    if (!d.players?.length || !d.last_updated_at) continue;
    if (d.last_updated_at.slice(0, 10) >= DRAFT_DAY[D]) { late ||= d; continue; }
    if (!best || d.last_updated_at > best.last_updated_at) best = d;
  }
  // 2018-19 exist only as one version stamped 2021: kept for the season grade (grade_1 is the final college season's,
  // which a later stamp can't change); PFF_STRICT=1 drops them
  if (!best && late && !process.env.PFF_STRICT) { PFF_LATE.push(D); best = late; }
  return best?.players || [];
}
const teamFile = path.join(EC, 'teams.json');
if (!fs.existsSync(teamFile)) fs.writeFileSync(teamFile, JSON.stringify(Object.fromEntries(((await getJSON('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000'))?.sports?.[0]?.leagues?.[0]?.teams || []).map(t => [t.team.id, t.team.location]))));
const TEAMS = JSON.parse(fs.readFileSync(teamFile, 'utf8'));
const picksAll = csv(fs.readFileSync(path.join(SP, 'draft_picks.csv'), 'utf8'));
const pickAt = Object.fromEntries(picksAll.map(r => [r.season + '|' + r.pick, r]));
const combine = csv(fs.readFileSync(path.join(SRC, 'combine.csv'), 'latin1'));
const nm = s => key(s);
const school = s => key(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim().split(' ')[0];
const wikiRaw = t => { const f = path.join(SRC, t.replace(/[^\w-]/g, '_') + '.txt'); if (!fs.existsSync(f)) try { execFileSync('curl', ['-sSL', '-m', '60', '-A', UA, '-o', f, `https://en.wikipedia.org/w/index.php?title=${encodeURIComponent(t)}&action=raw`]); } catch { fs.writeFileSync(f, ''); } return fs.readFileSync(f, 'utf8'); };
const linkName = s => s.replace(/\{\{sortname\|([^|}]+)\|([^|}]+)[^}]*\}\}/g, '$1 $2').replace(/\[\[(?:[^\]|]*\|)?([^\]]+)\]\]/g, '$1').replace(/<[^>]+>|'''|''|\*/g, '').replace(/\(.*?\)/g, '').trim();

const GRP = { QB: 'QB', RB: 'RB', FB: 'RB', HB: 'RB', WR: 'WR', TE: 'TE', OT: 'OL', OG: 'OL', C: 'OL', G: 'OL', T: 'OL', OL: 'OL', IOL: 'OL',
  DE: 'EDGE', EDGE: 'EDGE', OLB: 'EDGE', DT: 'DL', NT: 'DL', DL: 'DL', ILB: 'LB', LB: 'LB', MLB: 'LB', CB: 'CB', DB: 'CB', S: 'S', FS: 'S', SS: 'S', SAF: 'S' };
const G10 = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S'];

// combine athletic z (as cfb_teams.mjs fetchCombine: z vs invitees at the group since 2010, mean of 2+, centred)
const met = r => ({ spd: +r.forty && +r.wt ? +r.wt * 200 / (+r.forty) ** 4 : null, vert: +r.vertical || null, broad: +r.broad_jump || null, cone: +r.cone ? -r.cone : null, shut: +r.shuttle ? -r.shuttle : null });
const pool = {};
for (const r of combine) { const g = GRP[r.pos]; if (!g || +r.season < 2010) continue; for (const [k, v] of Object.entries(met(r))) if (v != null) (pool[g + k] ||= []).push(v); }
const MS = Object.fromEntries(Object.entries(pool).map(([k, xs]) => [k, [mean(xs), sdv(xs)]]));
const athOf = r => { const g = GRP[r.pos]; const zs = Object.entries(met(r)).filter(([k, v]) => v != null && MS[g + k]).map(([k, v]) => (v - MS[g + k][0]) / MS[g + k][1]); return zs.length >= 2 ? mean(zs) : null; };
const TM = {}; for (const r of combine) { const g = GRP[r.pos], a = g && +r.season >= 2010 ? athOf(r) : null; if (a != null) (TM[g] ||= []).push(a); }
const combBy = {};
for (const r of combine) { const g = GRP[r.pos]; if (!g || +r.season < 2014 || +r.season > 2023) continue; const a = athOf(r);
  (combBy[r.season] ||= []).push({ name: r.player_name, team: r.school, pos: r.pos, ath: a == null ? null : a - mean(TM[g]), r }); }
const combM = Object.fromEntries(Object.entries(combBy).map(([D, rows]) => [D, new Matcher(rows, { name: 'name', team: 'team', pos: 'pos' })]));

// All-America (final season) and Senior Bowl (the January after), Wikipedia
const AA = {}, SEN = {};
for (const D of CLASSES) {
  const y = D - 1, t = wikiRaw(`${y} All-America college football team`), s = new Set();
  for (const m of t.matchAll(/^\*+\s*(.+?),\s*\[\[[^\]|]*\|([^\]]+)\]\][^\n]*?<small>\s*\(([^)]*)\)/gm)) { const n = nm(linkName(m[1])); AA[D + '|' + n] = Math.max(AA[D + '|' + n] || 0, m[3].split(',').filter(x => x.trim()).length); s.add(n); }
  const r = wikiRaw(`${D} Senior Bowl`); const ss = new Set();
  for (const line of r.split('\n')) { const c = line.split('||'); if (c.length < 4) continue; const n = nm(linkName(c[1] || '')); if (n && n.split(' ').length >= 2) ss.add(n); }
  SEN[D] = ss;
}
const progPicks = {};
for (const r of picksAll) { const s = school(r.college); (progPicks[s] ||= {})[r.season] = (progPicks[s]?.[r.season] || 0) + 1; }
const pipeline = (team, D) => { const p = progPicks[school(team)] || {}; let n = 0; for (let y = D - 5; y < D; y++) n += p[y] || 0; return n / 5; };

// ---- U2: the ESPN prospect pool 2014-23 -------------------------------------------------------------------------------
const pool2 = [], cover = {};
const laterDrafted = new Set(picksAll.map(r => r.season + '|' + nm(r.pfr_player_name)));
const PFF = {};
for (const D of CLASSES) {
  const rows = await espnClass(D), pff = D >= 2018 ? pffClass(D) : [];
  PFF[D] = pff.length;
  const pffM = new Matcher(pff, { name: 'name', team: 'college', pos: 'position' });
  const maxO = Math.max(...rows.map(r => +r.at.overall || 0));
  const cv = cover[D] = { prospects: 0, picked: 0, pickJoined: 0, grade: 0, arm: 0, hand: 0, speed: 0, combine: 0, pff: 0, pffGraded: 0, pffBoard: pff.length };
  for (const r of rows) {
    const g = GRP[r.pos]; if (!g) continue;
    const n = nm(r.n), team = TEAMS[r.tid] || null;
    if (!r.pick && [...Array(4)].some((_, k) => laterDrafted.has((D + 1 + k) + '|' + n))) continue;
    const pk = r.pick ? pickAt[D + '|' + r.pick] : null;
    cv.prospects++; if (r.pick) cv.picked++; if (pk && nm(pk.pfr_player_name).split(' ').at(-1) === n.split(' ').at(-1)) cv.pickJoined++;
    const ov = +r.at.overall > 0 ? +r.at.overall : null; if (!ov) continue;   // ranked prospects only (ungraded lists run 40 to 5,000 deep a class)
    const gr = +r.at.grade > 0 ? +r.at.grade : null, arm = +r.at.arm > 0 ? +r.at.arm : null, hand = +r.at.hand > 0 ? +r.at.hand : null, spd = +r.at.speed > 3.9 && +r.at.speed < 6 ? +r.at.speed : null;
    const [cb] = combM[D]?.find(r.n, { team, pos: r.pos }) || [null];
    const [pf] = pff.length ? pffM.find(r.n, { team, pos: r.pos }) : [null];
    if (gr) cv.grade++; if (arm) cv.arm++; if (hand) cv.hand++; if (spd) cv.speed++; if (cb) cv.combine++; if (pf) cv.pff++; if (pf?.grade_1?.value > 0) cv.pffGraded++;
    pool2.push({ D, g, epos: r.pos, name: r.n, cid: r.cid, team, av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0, pick: r.pick,
      lo: Math.log(ov || maxO + 50), unr: ov ? 0 : 1, grade: gr, posRank: +r.at.rank > 0 ? Math.log(+r.at.rank) : null, arm, hand, wt: r.wt, spd,
      ath: cb ? cb.ath : null, invite: cb ? 1 : 0, pff: pf?.grade_1?.value > 0 ? pf.grade_1.value : null, pffSnaps: pf?.grade_1?.snaps ?? null, pffRank: pf ? Math.log(pf.pff_rank) : null, pffListed: pf ? 1 : (pff.length ? 0 : null),
      aa: AA[D + '|' + n] || 0, senior: SEN[D].size ? (SEN[D].has(n) ? 1 : 0) : null, pipe: team ? pipeline(team, D) : null });
  }
}
// z's within group (arm, hand, ESPN speed score: all classes pooled) and within group x class (grades)
const zIn = (rows, f, by) => { const b = {}; for (const p of rows) { const v = f(p); if (v != null) (b[by(p)] ||= []).push(v); } const st = Object.fromEntries(Object.entries(b).map(([k, xs]) => [k, [mean(xs), sdv(xs)]])); return p => { const v = f(p); return v == null || !st[by(p)] ? null : (v - st[by(p)][0]) / st[by(p)][1]; }; };
const armZ = zIn(pool2, p => p.arm, p => p.g), handZ = zIn(pool2, p => p.hand, p => p.g), spdZ = zIn(pool2, p => p.spd && p.wt ? p.wt * 200 / p.spd ** 4 : null, p => p.g);
const gradeZ = zIn(pool2, p => p.grade, p => p.D), pffZ = zIn(pool2, p => p.pff, p => p.g + p.D);
for (const p of pool2) { p.armZ = armZ(p); p.handZ = handZ(p); p.spdZ = spdZ(p); p.gradeZ = gradeZ(p); p.pffZ = pffZ(p); }
const GS = G10;
const ctlBoard = p => [p.lo, p.lo ** 2, ...GS.slice(1).map(g => +(p.g === g)), ...GS.slice(1).map(g => (p.g === g) * p.lo)];
const ctlBoardAth = p => [...ctlBoard(p), p.ath ?? 0, +(p.ath == null)];
const CANDS = {
  // ESPN's own read beyond its overall rank
  grade: [p => p.gradeZ, ctlBoard], posRank: [p => p.posRank, ctlBoard],
  // measurements (arm and hand: longer / bigger is better at every group; tested pooled and at the groups that prize them)
  arm: [p => p.armZ, ctlBoardAth], hand: [p => p.handZ, ctlBoardAth],
  // ESPN's 40 as a speed score (it carries pro-day times the combine file lacks), on top of the combine composite
  speed: [p => p.spdZ, ctlBoardAth],
  // PFF's final-season grade (z within group x class among PFF-listed), on PFF-listed prospects
  pff: [p => p.pffZ, ctlBoard], pffSnapW: [p => p.pffZ == null ? null : p.pffZ * Math.min(1, (p.pffSnaps || 0) / 600), ctlBoard],
  // the Oct 14 sources that failed on DraftTek's 4 classes
  combineInvite: [p => p.invite, ctlBoard], athletic: [p => p.ath, ctlBoard], aa: [p => p.aa, ctlBoard], aaAny: [p => +(p.aa > 0), ctlBoard],
  senior: [p => p.senior, ctlBoard], pipeline: [p => p.pipe, ctlBoard],
};
const out = { asof: new Date().toISOString().slice(0, 10), method: 'see scripts/cfb_draft_source_backtest.mjs', pffLateStamped: PFF_LATE, coverage: cover, pool: {}, poolByGroup: {}, pfn: {} };
for (const [k, [x, c]] of Object.entries(CANDS)) { out.pool[k] = test(pool2, c, x); console.log('pool', k.padEnd(14), JSON.stringify(out.pool[k])); }
for (const k of ['arm', 'hand', 'speed', 'grade', 'pff']) {
  out.poolByGroup[k] = Object.fromEntries(GS.map(g => { const P = pool2.filter(p => p.g === g); const r = test(P, p => [p.lo, p.lo ** 2, ...(CANDS[k][1] === ctlBoardAth ? [p.ath ?? 0, +(p.ath == null)] : [])], CANDS[k][0]); return [g, r && { n: r.n, t: r.t, oosGain: r.oosGain, foldT: r.foldT, spear: [r.spear0, r.spear1] }]; }));
  console.log('byGroup', k, Object.entries(out.poolByGroup[k]).map(([g, r]) => `${g} ${r ? r.t + '/' + r.oosGain : '-'}`).join('  '));
}
// sanity: the board's grade against the pick, per class (a post-draft grade would track the pick almost exactly)
out.gradeVsPick = Object.fromEntries(CLASSES.map(D => { const S = pool2.filter(p => p.D === D && p.pick && p.grade); return [D, { n: S.length, r: r3(pearson(S.map(p => p.grade), S.map(p => Math.log(p.pick)))), exactOverall: S.filter(p => Math.round(Math.exp(p.lo)) === p.pick).length }]; }));

// ---- U1: the PFN universe (cfb_source_backtest), classes 2020-23, production + a final board ------------------------------
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 }, K = 3000, W = [5, 4, 3];
const picks20 = picksAll.filter(r => +r.season >= 2020 && +r.season <= 2025);
const nmOld = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
const board = {};
for (const D of [2020, 2021, 2022, 2023]) {
  board[D] = {};
  for (let pg = 1; pg <= 6; pg++) {
    const f = path.join(SRC, `dt_${D}_${pg}.html`); if (!fs.existsSync(f)) continue;
    const s = fs.readFileSync(f, 'latin1').replace(/<!--.*?-->/gs, '');
    for (const tr of s.matchAll(/<tr[^>]*>(.*?)<\/tr>/gs)) {
      const td = [...tr[1].matchAll(/<td[^>]*>(.*?)<\/td>/gs)].map(m => m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").trim());
      if (td.length >= 8 && /^\d+$/.test(td[0])) { const k = nmOld(td[2]); if (!(k in board[D])) board[D][k] = +td[0]; }
    }
  }
}
const poolM = Object.fromEntries([2020, 2021, 2022, 2023].map(D => [D, new Matcher(pool2.filter(p => p.D === D), { name: 'name', team: 'team', pos: 'epos' })]));
const U1 = [];
for (const g of Object.keys(SPG)) {
  const rows = JSON.parse(fs.readFileSync(path.join(SP, `pfn_${g}.json`))).filter(r => r.division === 'FBS'), cz = {};
  for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const s of Object.keys(cz)) cz[s] = [mean(cz[s]), sdv(cz[s])];
  const byId = {};
  for (const r of rows) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = (typeof r.snapsQ === 'number' ? r.snapsQ : null) ?? (typeof r.snaps === 'number' ? r.snaps : null) ?? ((r.gp ?? r.gamesQ ?? 0) * SPG[g]); (byId[r.id] ||= {})[r.season] = r; }
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2022) continue;
    const r = by[last], D = last + 1, n = nmOld(r.name), cand = picks20.filter(p => nmOld(p.pfr_player_name) === n && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && school(p.college) === school(r.team)) || cand.find(p => +p.season === D);
    if (!pk && cand.some(p => +p.season > D)) continue;
    let a = 0, d = 0; W.forEach((w, k) => { const x = by[last - k]; if (x) { a += w * x._v * x._z; d += w * x._v; } });
    const rk = board[D][n], [e] = poolM[D].find(r.name, { team: r.team, pos: g }) || [null];
    U1.push({ g, D, name: r.name, prod: a / (d + K), lrank: Math.log(rk || 700), av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0,
      elo: e ? e.lo : Math.log(Math.max(...pool2.filter(p => p.D === D).map(p => Math.exp(p.lo))) + 50), eunr: e && !e.unr ? 0 : 1, e });
  }
}
const G7 = Object.keys(SPG);
const ctlA = p => [p.prod, ...G7.slice(1).map(g => +(p.g === g)), ...G7.slice(1).map(g => (p.g === g) * p.prod)];
const ctlDT = p => [...ctlA(p), p.lrank, p.lrank ** 2], ctlES = p => [...ctlA(p), p.elo, p.elo ** 2, p.eunr], ctlBoth = p => [...ctlDT(p), p.elo, p.elo ** 2, p.eunr];
const ath1 = c => p => [...c(p), p.e?.ath ?? 0, +(p.e?.ath == null)];
// how strong each control is: held-out R^2 of the control alone (leave one class out) and the board added to production
out.pfn.controls = {};
{ const ones = () => 0; for (const [lab, c] of [['A', ctlA], ['B_drafttek', ctlDT], ['B_espn', ctlES], ['B_both', ctlBoth]]) {
    // held-out R^2 against the training mean, by class
    let sse = 0, sst = 0; for (const D of [2020, 2021, 2022, 2023]) { const tr = U1.filter(p => p.D !== D), te = U1.filter(p => p.D === D), b = ols(tr.map(c), tr.map(p => p.av)), my = mean(tr.map(p => p.av)); for (const p of te) { sse += (p.av - pred(b, c(p))) ** 2; sst += (p.av - my) ** 2; } }
    out.pfn.controls[lab] = r3(100 * (1 - sse / sst)); ones(); } }
out.pfn.espnOverDT = test(U1, ctlDT, p => p.elo);      // ESPN's rank on top of DraftTek's (and production)
out.pfn.dtOverESPN = test(U1, ctlES, p => p.lrank);
out.pfn.n = U1.length; out.pfn.espnJoined = U1.filter(p => p.e).length; out.pfn.espnRanked = U1.filter(p => !p.eunr).length;
const U1C = { grade: [p => p.e?.gradeZ ?? null], posRank: [p => p.e?.posRank ?? null], arm: [p => p.e?.armZ ?? null, true], hand: [p => p.e?.handZ ?? null, true], speed: [p => p.e?.spdZ ?? null, true],
  pff: [p => p.e?.pffZ ?? null], pffSnapW: [p => p.e?.pffZ == null ? null : p.e.pffZ * Math.min(1, (p.e.pffSnaps || 0) / 600)] };
out.pfn.cands = {};
for (const [k, [x, a]] of Object.entries(U1C)) {
  out.pfn.cands[k] = { A: test(U1, a ? ath1(ctlA) : ctlA, x), B_drafttek: test(U1, a ? ath1(ctlDT) : ctlDT, x), B_espn: test(U1, a ? ath1(ctlES) : ctlES, x), B_both: test(U1, a ? ath1(ctlBoth) : ctlBoth, x) };
  console.log('pfn', k.padEnd(9), Object.entries(out.pfn.cands[k]).map(([c, r]) => `${c} ${r ? `n${r.n} t${r.t} g${r.oosGain} fT${r.foldT} sp${r.spear0}->${r.spear1}` : '-'}`).join(' | '));
}
// ESPN's position rank passes on U1 against a board with one slope for every group; with the board's slope by group
// (as the pool control has it) it should not, if it's only the board's functional form
{ const ctlESg = p => [...ctlES(p), ...G7.slice(1).map(g => (p.g === g) * p.elo)];
  out.pfn.posRankGroupSlope = test(U1, ctlESg, U1C.posRank[0]); console.log('pfn posRank, B_espn with group slopes', JSON.stringify(out.pfn.posRankGroupSlope)); }
fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
console.log('coverage', JSON.stringify(cover));
console.log('gradeVsPick', JSON.stringify(out.gradeVsPick));
console.log('pfn controls', JSON.stringify(out.pfn.controls), 'n', out.pfn.n, 'espn joined', out.pfn.espnJoined, 'ranked', out.pfn.espnRanked);
console.log('espnOverDT', JSON.stringify(out.pfn.espnOverDT)); console.log('dtOverESPN', JSON.stringify(out.pfn.dtOverESPN));
