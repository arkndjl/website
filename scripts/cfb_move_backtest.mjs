// Backtest for the board's position-change flags (fetch_cfb.mjs build(): "position fit"). Run by hand after
// scripts/cfb_statplus_backtest.mjs (it reuses that script's cached PFN boards and fetches OL, CB and S itself):
//   node scripts/cfb_move_backtest.mjs [--examples] -> data/cfb_move_backtest.json
// Universe: each FBS player's last PFN season, 2019-25 (OL, CB and S have PFN lines from 2024 only), who was at the
// next NFL combine (nflverse combine.csv, 2020-26). The outcome is where the NFL used him: his depth-chart spot
// (nflverse rosters) in his second season, else his first, else the combine's listing. An OLB depth spot can be a
// 3-4 edge or a 4-3 backer, so it falls to the combine; the 2020-21 combines lumped edges into LB and DTs into DL,
// and any DL or OL listing is left out (it can be either side of the question).
// Size is the combine's height and weight, i.e. the body at ~22 that the live rule projects (wp), so the test
// scores the rules given a perfect frame projection. Stat percentiles are taken as the live board takes them:
// within the position and season, among 100+ snap players (games x snaps a game where PFN has no snaps).
// Per move, for the live rules and the ones before this test: how many were flagged, how many of those the NFL
// used at the new spot (precision), the same rate among the unflagged (base), and the share of all such moves
// the flag caught (recall).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CACHE = path.join(ROOT, 'scripts', '.cache', 'statplus');
const OUT = path.join(ROOT, 'data', 'cfb_move_backtest.json');
const SZ = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_calibration.json'), 'utf8')).size;
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, OL: 65, EDGE: 50, DL: 45, LB: 55, CB: 55, S: 55 };
const GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S'];
const LAST = 2025;       // last college season tested: the 2026 combine and rookie season

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const jsonEnd = (s, i) => { let d = 0, q = false; for (let k = i; k < s.length; k++) { const c = s[k]; if (q) { if (c === '\\') k++; else if (c === '"') q = false; continue; }
  if (c === '"') q = true; else if (c === '{' || c === '[') d++; else if (c === '}' || c === ']') { d--; if (!d) return k + 1; } } };
for (const [g, slug] of [['OL', 'offensive-line'], ['CB', 'cornerback'], ['S', 'safety']]) {
  const f = path.join(CACHE, `pfn_${g}.json`); if (fs.existsSync(f)) continue;
  const html = await (await fetch(`https://www.profootballnetwork.com/cfb-hq/impact-rankings/${slug}`, { headers: { 'user-agent': UA } })).text();
  const s = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).find(c => c.includes('"packed":'));
  const i = s.indexOf('"packed":') + 9, packed = JSON.parse(s.slice(i, jsonEnd(s, i)));
  fs.writeFileSync(f, JSON.stringify(packed.rows.map(r => Object.fromEntries(packed.cols.map((c, k) => [c, r[k]])))));
}
// combine (nflverse), cached next to the PFN boards
const combFile = path.join(CACHE, 'combine.csv');
if (!fs.existsSync(combFile)) fs.writeFileSync(combFile, await (await fetch('https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv')).text());
const csv = s => { const out = []; let row = [], f = '', q = false;
  for (let i = 0; i < s.length; i++) { const c = s[i];
    if (q) { if (c === '"') { if (s[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true; else if (c === ',') { row.push(f); f = ''; } else if (c === '\n') { row.push(f); out.push(row); row = []; f = ''; } else if (c !== '\r') f += c; }
  if (f || row.length) { row.push(f); out.push(row); } const [h, ...rs] = out; return rs.map(r => Object.fromEntries(h.map((k, i) => [k, r[i]]))); };
const comb = csv(fs.readFileSync(combFile, 'utf8')).filter(r => +r.season >= 2020 && +r.season <= LAST + 1 && r.ht && r.wt);
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').trim().split(' ')[0];
const inches = s => { const m = /^(\d+)-(\d+)/.exec(s || ''); return m ? 12 * +m[1] + +m[2] : null; };
// NFL depth-chart spot (nflverse rosters) in his second NFL season, else his first: how he was used, the outcome
// when it is clear (DE, DT / NT, ILB / MLB, FS / SS, CB, WR, TE, RB / FB, QB; an OLB can be a 3-4 edge or a 4-3
// backer, so it falls back to the combine listing)
const DEPTH = { DE: 'EDGE', DT: 'DL', NT: 'DL', ILB: 'LB', MLB: 'LB', FS: 'S', SS: 'S', CB: 'CB', WR: 'WR', TE: 'TE', RB: 'RB', FB: 'RB', QB: 'QB', T: 'OT', G: 'IOL', C: 'IOL' };
const depth = {};
for (let y = 2020; y <= LAST + 1; y++) {
  const f = path.join(CACHE, `roster_${y}.csv`);
  if (!fs.existsSync(f)) fs.writeFileSync(f, await (await fetch(`https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_${y}.csv`)).text());
  for (const r of csv(fs.readFileSync(f, 'utf8'))) if (r.pfr_id && r.depth_chart_position) ((depth[r.pfr_id] ||= {})[y] ||= {})[r.depth_chart_position] = (depth[r.pfr_id][y][r.depth_chart_position] || 0) + 1;
}
const nflSpot = (pfr, draft) => { for (const y of [draft + 1, draft]) { const d = depth[pfr]?.[y]; if (!d) continue;
  const top = Object.entries(d).sort((a, b) => b[1] - a[1])[0][0]; return DEPTH[top] ?? null; } return null; };
const NFL = { EDGE: 'EDGE', DE: 'EDGE', OLB: 'EDGE', DT: 'DL', NT: 'DL', LB: 'LB', ILB: 'LB', MLB: 'LB', S: 'S', SAF: 'S', FS: 'S', SS: 'S', DB: 'S',
  CB: 'CB', WR: 'WR', TE: 'TE', RB: 'RB', FB: 'RB', QB: 'QB', OT: 'OT', T: 'OT', G: 'IOL', OG: 'IOL', C: 'IOL' };

// each player's last FBS season across the seven boards
const last = {};
for (const g of GROUPS) for (const r of JSON.parse(fs.readFileSync(path.join(CACHE, `pfn_${g}.json`), 'utf8'))) {
  if (r.division !== 'FBS') continue;
  const k = nm(r.name) + '|' + col(r.team);
  if (!last[k] || r.season > last[k].r.season) last[k] = { g, r };
}
// percentiles within position x season, 100+ snaps
const vol = (g, r) => typeof r.snaps === 'number' ? r.snaps : (r.gp ?? r.gamesQ ?? 0) * SPG[g];
const pools = {};
for (const g of GROUPS) for (const r of JSON.parse(fs.readFileSync(path.join(CACHE, `pfn_${g}.json`), 'utf8')))
  if (r.division === 'FBS' && vol(g, r) >= 100) (pools[g + '|' + r.season] ||= []).push(r);
const qcache = {};
const pctOf = (g, season, f, get) => { const k = `${g}|${season}|${f}`;
  if (!qcache[k]) { const xs = (pools[g + '|' + season] || []).map(r => get(g, r)).filter(v => typeof v === 'number' && isFinite(v)).sort((a, b) => a - b);
    qcache[k] = x => { if (x == null || !xs.length) return null; let lo = 0, hi = xs.length; while (lo < hi) { const m = (lo + hi) >> 1; if (xs[m] < x) lo = m + 1; else hi = m; } return lo / xs.length; }; }
  return qcache[k]; };
const field = f => (g, r) => r[f] ?? null;
const perSnap = f => (g, r) => r[f] != null && vol(g, r) ? r[f] / vol(g, r) : null;
const recPg = (g, r) => r.recYds != null ? r.recYds / Math.max(1, r.gp || r.gamesQ || 1) : null;

// the live rules (fetch_cfb.mjs, position fit), written against (g, ht, wp, P, r); returns [to, path] or null.
// Keep in step with the board: a rule changed there is changed here
const fits = (k, ht, wt, slack = 0) => { const n = SZ[k]; return !!n && ht >= n.ht.p10 - 1 - slack && ht <= n.ht.p90 + 1 + slack && wt >= n.wt.p10 - 8 - 4 * slack && wt <= n.wt.p90 + 8 + 4 * slack; };
const ge = (x, v) => x != null && x >= v, le = (x, v) => x != null && x <= v;
function rules(g, ht, wp, P, r) {
  if (g === 'DL') {
    const pr = P('prsRate');
    if (wp < SZ.DL.wt.p10 && ge(pr, 0.2) && ht >= SZ.EDGE.ht.p10 - 2) return ['EDGE', 'DL-EDGE under DT weight'];
  } else if (g === 'EDGE') {
    const pr = P('prsRate'), tk = P('tklSnap', perSnap('tkl'));
    if (wp >= SZ.DL.wt.p10 && le(pr, 0.85) && fits('DL', ht, wp)) return ['DL', 'EDGE-DL DT weight'];
    if (wp < SZ.EDGE.wt.p10 && le(pr, 0.35) && ge(tk, 0.55) && fits('LB', ht, wp)) return ['LB', 'EDGE-LB light, tackler'];
    if (wp < SZ.EDGE.wt.p10 - 8 && le(pr, 0.5) && fits('LB', ht, wp)) return ['LB', 'EDGE-LB LB weight'];
  } else if (g === 'LB') {
    const ps = P('prsSnap', perSnap('prs'));
    if (ge(ps, 0.8) && (r.prs || 0) >= 5 && ht >= SZ.EDGE.ht.p10 - 1 && wp >= SZ.EDGE.wt.p10 - 5) return ['EDGE', 'LB-EDGE rusher, edge frame'];
    if (wp >= SZ.EDGE.wt.p25 && ht >= SZ.EDGE.ht.p25 && ge(ps, 0.65) && (r.prs || 0) >= 4) return ['EDGE', 'LB-EDGE edge size + knack'];
  } else if (g === 'WR') {
    const yac = P('yac');
    if (ht >= 76 && wp >= 225 && le(yac, 0.45) && fits('TE', ht, wp + 10)) return ['TE', 'WR-TE size, low YAC'];
    if (ht >= SZ.TE.ht.p10 && wp >= SZ.TE.wt.p10 - 12 && fits('TE', ht, wp + 12)) return ['TE', 'WR-TE TE size'];
  } else if (g === 'TE') {
    const rc = P('recPg', recPg);
    if (wp < SZ.TE.wt.p10 - 10 && ge(rc, 0.5) && fits('WR', ht, wp)) return ['WR', 'TE-WR WR weight'];
  } else if (g === 'S') {
    const cov = (r.tar ?? 0) >= 7 ? P('rtg') : null, mt = r.mt != null ? P('mt') : null, fi = P('fi'), tk = P('tklSnap', perSnap('tkl'));
    if (wp >= SZ.S.wt.p90 && ge(cov, 0.6) && le(mt, 0.5) && fits('LB', ht, wp)) return ['LB', 'S-LB LB frame, coverage trails'];
    if (wp >= SZ.LB.wt.p10 - 3 && ge(tk, 0.7) && fits('LB', ht, wp)) return ['LB', 'S-LB LB weight, box tackler'];
    if (wp <= SZ.S.wt.p25 && ht <= SZ.CB.ht.p90 && le(cov, 0.3) && ge(fi, 0.6)) return ['CB', 'S-CB corner size + coverage'];
    if (wp <= SZ.S.wt.p10 && ht <= SZ.CB.ht.p90 && le(cov, 0.4)) return ['CB', 'S-CB corner weight'];
  } else if (g === 'CB') {
    const mt = r.mt != null ? P('mt') : null, tk = P('tklSnap', perSnap('tkl'));
    if (wp >= SZ.S.wt.p50 && ge(tk, 0.6) && le(mt, 0.5) && fits('S', ht, wp)) return ['S', 'CB-S safety weight, tackler'];
  } else if (g === 'OL') {
    const tackle = /T$/.test(r.pos || ''), pb = P('pbScore');
    if (tackle && ht < SZ.OT.ht.p10 && (r.rbScore ?? 0) - (r.pbScore ?? 0) >= 4) return ['IOL', 'OT-IOL short, run blocker'];
    if (tackle && ht <= SZ.OT.ht.p10 && le(pb, 0.35) && wp >= SZ.IOL.wt.p10) return ['IOL', 'OT-IOL guard build'];
  } else if (g === 'QB') {
    const ny = P('nypa'), ry = (r.ryds || 0) / Math.max(1, r.gp || 1);
    if (ry >= 50 && ht <= SZ.QB.ht.p10 - 1 && wp <= SZ.QB.wt.p10 - 12) return ['ATH', 'QB-ATH small runner'];
    if (ry >= 50 && le(ny, 0.25) && ht <= SZ.QB.ht.p10) return ['ATH', 'QB-ATH runner'];
  }
  return null;
}
// the rules before the backtest (Oct 2026), scored the same way for the record
function rulesBefore(g, ht, wp, P, r) {
  if (g === 'DL') {
    const pr = P('prsRate'), tk = P('tklSnap', perSnap('tkl'));
    if (wp < SZ.DL.wt.p10 && ge(pr, 0.6) && ht >= SZ.EDGE.ht.p10 - (ge(pr, 0.85) ? 2 : 1) && wp >= SZ.EDGE.wt.p10 - 10) return ['EDGE', 'DL-EDGE light rusher'];
    if (wp < SZ.DL.wt.p25 && ht >= SZ.EDGE.ht.p50 && ge(pr, 0.75) && fits('EDGE', ht, wp)) return ['EDGE', 'DL-EDGE edge frame + rush'];
    if (wp < SZ.DL.wt.p10 - 15 && ge(pr, 0.4) && le(tk, 0.6) && fits('EDGE', ht, wp)) return ['EDGE', 'DL-EDGE edge weight'];
  } else if (g === 'EDGE') {
    const pr = P('prsRate'), tk = P('tklSnap', perSnap('tkl'));
    if (wp > SZ.EDGE.wt.p90 && le(pr, 0.4) && fits('DL', ht, wp)) return ['DL', 'EDGE-DL DT-sized, modest rush'];
    if (ht >= 75 && wp >= SZ.EDGE.wt.p75 && le(pr, 0.45) && tk - pr >= 0.25 && fits('DL', ht, wp + 15)) return ['DL', 'EDGE-DL run stopper 5-tech'];
    if (wp >= SZ.EDGE.wt.p90 + 8 && le(pr, 0.6) && fits('DL', ht, wp)) return ['DL', 'EDGE-DL DT weight'];
    if (wp < SZ.EDGE.wt.p10 && le(pr, 0.35) && ge(tk, 0.55) && fits('LB', ht, wp)) return ['LB', 'EDGE-LB light, tackler'];
    if (wp < SZ.EDGE.wt.p10 - 8 && le(pr, 0.5) && fits('LB', ht, wp)) return ['LB', 'EDGE-LB LB weight'];
  } else if (g === 'LB') {
    const ps = P('prsSnap', perSnap('prs')), cov = (r.tgt ?? 0) >= 10 ? P('rtg') : null;
    if (ge(ps, 0.8) && (r.prs || 0) >= 5 && ht >= SZ.EDGE.ht.p10 - 1 && wp >= SZ.EDGE.wt.p10 - 5) return ['EDGE', 'LB-EDGE rusher, edge frame'];
    if (wp >= SZ.EDGE.wt.p25 && ht >= SZ.EDGE.ht.p25 && ge(ps, 0.65) && (r.prs || 0) >= 4) return ['EDGE', 'LB-EDGE edge size + knack'];
    if (wp < SZ.LB.wt.p10 - 5 && le(cov, 0.3) && (r.tgt ?? 0) >= 10 && fits('S', ht, wp)) return ['S', 'LB-S safety size, covers'];
    if (wp <= SZ.S.wt.p90 && le(cov, 0.4) && fits('S', ht, wp)) return ['S', 'LB-S safety weight'];
  } else if (g === 'WR') {
    const yac = P('yac');
    if (ht >= 76 && wp >= 225 && le(yac, 0.45) && fits('TE', ht, wp + 10)) return ['TE', 'WR-TE size, low YAC'];
    if (ht >= SZ.TE.ht.p25 && wp >= SZ.TE.wt.p10 - 5 && fits('TE', ht, wp)) return ['TE', 'WR-TE TE size'];
  } else if (g === 'TE') {
    const b = P('blk'), rc = P('recPg', recPg);
    if (wp < SZ.TE.wt.p10 && le(b, 0.4) && ge(rc, 0.65)) return ['WR', 'TE-WR light, receiver'];
    if (wp < SZ.TE.wt.p10 - 10 && ge(rc, 0.5) && fits('WR', ht, wp)) return ['WR', 'TE-WR WR weight'];
  } else if (g === 'RB') {
    const recShare = (r.recYds || 0) / Math.max(1, (r.ryds || 0) + (r.recYds || 0)), yc = P('ypc');
    if (recShare >= 0.35 && wp <= 200 && le(yc, 0.45)) return ['WR', 'RB-WR receiver, runs lag'];
    if (wp < SZ.RB.wt.p10 - 5 && recShare >= 0.25 && fits('WR', ht, wp)) return ['WR', 'RB-WR WR weight'];
  } else if (g === 'S') {
    const cov = (r.tar ?? 0) >= 7 ? P('rtg') : null, mt = r.mt != null ? P('mt') : null, fi = P('fi'), tk = P('tklSnap', perSnap('tkl'));
    if (wp >= SZ.S.wt.p90 && ge(cov, 0.6) && le(mt, 0.5) && fits('LB', ht, wp)) return ['LB', 'S-LB LB frame, coverage trails'];
    if (wp >= SZ.LB.wt.p10 - 3 && ge(tk, 0.7) && fits('LB', ht, wp)) return ['LB', 'S-LB LB weight, box tackler'];
    if (wp <= SZ.S.wt.p25 && ht <= SZ.CB.ht.p90 && le(cov, 0.3) && ge(fi, 0.6)) return ['CB', 'S-CB corner size + coverage'];
    if (wp <= SZ.S.wt.p10 && ht <= SZ.CB.ht.p90 && le(cov, 0.4)) return ['CB', 'S-CB corner weight'];
  } else if (g === 'CB') {
    const cov = (r.tar ?? 0) >= 12 ? P('rtg') : null, mt = r.mt != null ? P('mt') : null, yr = P('ydsRec'), tk = P('tklSnap', perSnap('tkl'));
    if ((ht >= SZ.S.ht.p50 + 1 || wp >= SZ.S.wt.p25 + 3) && cov != null && (cov >= 0.65 || ge(yr, 0.8)) && le(mt, 0.45) && fits('S', ht, wp)) return ['S', 'CB-S safety frame, sure tackler'];
    if (wp >= SZ.S.wt.p50 && ge(tk, 0.6) && le(mt, 0.5) && fits('S', ht, wp)) return ['S', 'CB-S safety weight, tackler'];
  } else if (g === 'OL') {
    const tackle = /T$/.test(r.pos || ''), inside = /^(LG|RG|C|G)$/.test(r.pos || ''), pb = P('pbScore');
    if (tackle && ht < SZ.OT.ht.p10 && (r.rbScore ?? 0) - (r.pbScore ?? 0) >= 4) return ['IOL', 'OT-IOL short, run blocker'];
    if (tackle && ht <= SZ.OT.ht.p10 && le(pb, 0.35) && wp >= SZ.IOL.wt.p25) return ['IOL', 'OT-IOL guard build'];
    if (inside && ht >= SZ.OT.ht.p50 + 1 && ge(pb, 0.75)) return ['OT', 'IOL-OT length + pass sets'];
    if (inside && ht >= SZ.OT.ht.p50 && wp >= SZ.OT.wt.p25 && ge(pb, 0.85)) return ['OT', 'IOL-OT swing tackle'];
  } else if (g === 'QB') {
    const ny = P('nypa'), ry = (r.ryds || 0) / Math.max(1, r.gp || 1);
    if (ry >= 50 && le(ny, 0.25) && ht <= SZ.QB.ht.p10) return ['ATH', 'QB-ATH runner'];
  }
  return null;
}
// the spot each college position can move to, for the base rates
const TARGETS = { DL: ['EDGE'], EDGE: ['DL', 'LB'], LB: ['EDGE', 'S'], WR: ['TE'], TE: ['WR'], RB: ['WR'], QB: ['ATH'], S: ['LB', 'CB'], CB: ['S'], OT: ['IOL'], IOL: ['OT'] };
const SAME = { DL: 'DL', EDGE: 'EDGE', LB: 'LB', WR: 'WR', TE: 'TE', RB: 'RB', QB: 'QB', S: 'S', CB: 'CB', OT: 'OT', IOL: 'IOL' };

const rows = [];
for (const { g, r } of Object.values(last)) {
  if (r.season > LAST || vol(g, r) < 100) continue;
  const c = comb.find(x => +x.season === r.season + 1 && nm(x.player_name) === nm(r.name) && col(x.school) === col(r.team))
    || comb.find(x => +x.season === r.season + 1 && nm(x.player_name) === nm(r.name));
  if (!c) continue;
  const ht = inches(c.ht), wp = +c.wt; if (!ht || !wp) continue;
  // the combine's listing: 2020-21 lumped edges in with LB (no EDGE label) and DTs with DEs (DL)
  const lumped = +c.season <= 2021 && (c.pos === 'LB' || c.pos === 'DL');
  const listed = c.pos === 'DL' || c.pos === 'OL' || lumped ? 'DL?' : NFL[c.pos] || c.pos;
  const at = nflSpot(c.pfr_id, +c.season) ?? listed;
  const P = (f, get = field(f)) => { const v = get(g, r); return v == null ? null : pctOf(g, r.season, f, get)(v); };
  const flag = rules(g, ht, wp, P, r), before = rulesBefore(g, ht, wp, P, r);
  const st = { pr: P('prsRate'), tk: P('tklSnap', perSnap('tkl')), ps: P('prsSnap', perSnap('prs')), cov: (r.tgt ?? 0) >= 10 ? P('rtg') : null,
    yac: P('yac'), blk: P('blk'), rc: P('recPg', recPg), ny: P('nypa'), ry: (r.ryds || 0) / Math.max(1, r.gp || 1) };
  const gg = g === 'OL' ? (/T$/.test(r.pos || '') ? 'OT' : /^(LG|RG|C|G)$/.test(r.pos || '') ? 'IOL' : null) : g; if (!gg) continue;
  rows.push({ g: gg, name: r.name, team: r.team, season: r.season, ht, wt: wp, at, listed, flag: flag?.[0] ?? null, path: flag?.[1] ?? null, before: before?.[0] ?? null, st });
}
const moved = (x, to) => to === 'ATH' ? x.at !== 'QB' : x.at === to;
const known = (x, to) => x.at !== 'DL?';
const pc = (a, b) => b ? Math.round(1000 * a / b) / 10 : null;
const out = { asof: new Date().toISOString().slice(0, 10), universe: rows.length, moves: {}, paths: {}, examples: {} };
for (const [g, tos] of Object.entries(TARGETS)) for (const to of tos) {
  const pool = rows.filter(x => x.g === g && known(x, to)), fl = pool.filter(x => x.flag === to), un = pool.filter(x => x.flag !== to);
  const hit = fl.filter(x => moved(x, to)).length, all = pool.filter(x => moved(x, to)).length;
  const fb = pool.filter(x => x.before === to), hb = fb.filter(x => moved(x, to)).length;
  out.moves[`${g}-${to}`] = { players: pool.length, moves: all, flagged: fl.length, precision: pc(hit, fl.length), recall: pc(hit, all), base: pc(all - hit, un.length),
    flaggedBefore: fb.length, precisionBefore: pc(hb, fb.length), recallBefore: pc(hb, all),
    stayed: pc(pool.filter(x => x.at === SAME[g]).length, pool.length) };
  out.examples[`${g}-${to}`] = { hits: fl.filter(x => moved(x, to)).slice(0, 6).map(x => `${x.name} (${x.team} ${x.season}, ${x.ht}in ${x.wt}lb) -> ${x.at}`),
    misses: fl.filter(x => !moved(x, to)).slice(0, 6).map(x => `${x.name} (${x.team} ${x.season}, ${x.ht}in ${x.wt}lb) -> ${x.at}`),
    missed: pool.filter(x => moved(x, to) && x.flag !== to).slice(0, 8).map(x => `${x.name} (${x.team} ${x.season}, ${x.ht}in ${x.wt}lb) -> ${x.at}`) };
}
// all moves together. LB to EDGE can't score: a 3-4 outside backer lists as OLB (left to the combine, which says LB)
for (const [k, skip] of [['all', []], ['allButLbEdge', ['LB-EDGE']]]) {
  const ms = Object.entries(out.moves).filter(([m]) => !skip.includes(m)).map(([, v]) => v);
  const f = ms.reduce((a, v) => a + v.flagged, 0), h = ms.reduce((a, v) => a + Math.round(v.flagged * (v.precision || 0) / 100), 0);
  const fb = ms.reduce((a, v) => a + v.flaggedBefore, 0), hb = ms.reduce((a, v) => a + Math.round(v.flaggedBefore * (v.precisionBefore || 0) / 100), 0);
  const mv = ms.reduce((a, v) => a + v.moves, 0);
  out[k] = { flagged: f, right: h, moves: mv, flaggedBefore: fb, rightBefore: hb };
}
console.log('all', out.all, 'without LB-EDGE', out.allButLbEdge);
for (const p of [...new Set(rows.map(x => x.path).filter(Boolean))]) {
  const fl = rows.filter(x => x.path === p && known(x, x.flag)); out.paths[p] = { flagged: fl.length, precision: pc(fl.filter(x => moved(x, x.flag)).length, fl.length) };
}
console.log('universe', rows.length, Object.fromEntries(GROUPS.map(g => [g, rows.filter(x => x.g === g).length])));
console.table(out.moves); console.table(out.paths);
if (process.argv.includes('--examples')) console.log(JSON.stringify(out.examples, null, 1));
if (process.argv.includes('--rows')) fs.writeFileSync(process.argv[process.argv.indexOf('--rows') + 1], JSON.stringify(rows));
fs.writeFileSync(OUT, JSON.stringify(out, null, 1) + '\n');
