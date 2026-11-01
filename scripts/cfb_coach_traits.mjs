// Coach traits in the CFB game model (Nov 1 2026). The shipped model has one coach trait, aggr (4th-down go rate over
// the league's rate in the same situation bins, opponent-adjusted in season, offense side). This tests the rest:
//   fb bins (ESPN play-by-play, 2015-25; tune 2017-20, held out 2021-25):
//     aggrN   4th-down go over expected, neutral spots only (within 8 points, before the 4th quarter)
//     aggrSh  4th and 1-3 go over expected (short yardage), desperation (trailing 9+ in the 4th) out
//     aggrRZ  red-zone 4th downs: go over expected (touchdown vs field goal choice)
//     aggrFG  4th downs 21-40 yards out (field goal range): go over expected
//     aggrOwn 4th downs 41+ yards out (punt range): go over expected
//   pb bins (CFBD situational splits sit2 2021-24 from the cfb-research artifact, the live input's 2025 splits;
//   margin weights fit from 2021, tune 2022-23, held out 2024-25):
//     proe    pass rate over expected, downs 1-3 (CAND.proe, first real test: the committed history keeps fb bins only)
//     edproe  early downs (1st and 2nd), neutral score, before the 4th quarter: pass rate over expected
//   carried with the head coach (CFBD coaches.json; preseason, known before kickoff, home minus away):
//     cAggr   the head coach's go over expected last season, wherever he coached (0 for a first-year head coach)
//     cAggrD  the same, fading with the season (x 3 / (3 + games played))
//     tAggr   the team's own go over expected last season (program, not coach: the control)
//     cEdproe the head coach's early-down pass over expected last season (2022 on)
// Base: the ESPN-only pooled model (p4, aggr, roster prior), scripts/cfb_hist_backtest.mjs machinery.
// Result (Nov 1 2026): nothing passes. No narrower 4th-down cut beats aggr (each in its place is worse held out, t +1.2
// to +1.8); none adds on top (best tune t -0.21); pass rate over expected and its early-down cut fail on 2021-25
// (tune t +1.2, +1.4); the coach's carried go rate is worse held out (t +2.3, vs the close +2.9). aggr stays the only trait.
// Pre-registered rule (written before the run): a trait passes when tune log loss t <= -1.5 with the weight the
// expected sign (more aggressive / more passing = better), held-out log loss and MAE not worse, AND it does not hurt
// against the close: the close-anchored blend (close + b x (model - close), b fit on tune) held-out log loss not
// worse. Anything that passes then goes through cfb_model.mjs selection, --fit and --rules.
//   node scripts/cfb_coach_traits.mjs [hist_md.json.gz] [sit2 dir] [live md.json.gz] [coaches.json]
// -> data/cfb_coach_traits.json
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const HIST = process.argv[2] || path.join(ROOT, 'scripts', 'data', 'cfb_hist_md.json.gz');
const SIT2 = process.argv[3] || path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist');
const LIVE = process.argv[4] || path.join(ROOT, 'md.json.gz');
const COACH = process.argv[5] || path.join(SIT2, 'coaches.json');
const gz = f => JSON.parse(zlib.gunzipSync(fs.readFileSync(f)));

// ---- merged input: pass bins back onto the ESPN history ------------------------------------------------
const md = gz(HIST);
// the fields cfb_espn_md.mjs build() adds around the frozen history (the prior reads the roster feats, not these)
const venues = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_venues.json'), 'utf8'));
Object.assign(md, { venues: venues.venues || [], teamsFbs: venues.teamsFbs || [], sp: {}, talent: {}, returning: {}, weather: {}, pfnRet: {} });
const live = fs.existsSync(LIVE) ? gz(LIVE) : null;
const pbCover = {};
const overlay = (S, src) => { let n = 0; for (const [k, v] of Object.entries(src)) { const t = md.sit[S]?.[k]; if (t && v.pb) { t.pb = v.pb; n++; } } pbCover[S] = (pbCover[S] || 0) + n; };
for (const f of fs.readdirSync(SIT2).filter(f => /^sit2-\d{4}[wp]\d+\.json$/.test(f))) overlay(+f.slice(5, 9), JSON.parse(fs.readFileSync(path.join(SIT2, f), 'utf8')));
if (live?.sit?.[2025]) overlay(2025, live.sit[2025]);
const PBS = Object.keys(pbCover).map(Number).filter(S => pbCover[S] > 1000);
console.log('pass bins by season', JSON.stringify(pbCover));
const MERGED = path.join(os.tmpdir(), 'cfb_coach_traits_md.json.gz');
fs.writeFileSync(MERGED, zlib.gzipSync(JSON.stringify(md)));

// ---- league rates per season and bin, then the trait functions ------------------------------------------
const seasonOf = {};
for (const [S, gs] of Object.entries(md.games)) for (const g of gs) seasonOf[g.id] = +S;
const L = {};
for (const [S, sit] of Object.entries(md.sit)) {
  const l = (L[S] = { fb: {}, pb: {} });
  for (const v of Object.values(sit)) for (const k of ['fb', 'pb']) for (const [b, [n, y]] of Object.entries(v[k] || {})) { const a = (l[k][b] ||= [0, 0]); a[0] += n; a[1] += y; }
}
// sums of [decisions, actual, expected] over the bins a filter keeps
const oe = (r, k, keep) => { const l = L[seasonOf[r.g]]?.[k]; let n = 0, y = 0, x = 0;
  for (const [b, [bn, by]] of Object.entries(r[k] || {})) if (keep(b) && l?.[b]) { n += bn; y += by; x += bn * l[b][1] / l[b][0]; }
  return { n, y, x }; };
// fb key: distance (0: 1, 1: 2-3, 2: 4-6, 3: 7+), field (0: 61+ yards out, 1: 41-60, 2: 21-40, 3: 1-20), score (0 down 9+, 1 within 8, 2 up 9+), 4th quarter
// pb key: down, distance (0: 1-3, 1: 4-7, 2: 8+), score, 4th quarter
const FB = {
  aggrN: b => b[2] === '1' && b[3] === '0',
  aggrSh: b => +b[0] <= 1 && !(b[2] === '0' && b[3] === '1'),
  aggrRZ: b => b[1] === '3',
  aggrFG: b => b[1] === '2',
  aggrOwn: b => +b[1] <= 1,
};
const PB = { proe: () => true, edproe: b => +b[0] <= 2 && b[2] === '1' && b[3] === '0' };
const traitOf = (k, kind) => { const keep = (kind === 'fb' ? FB : PB)[k], c = {};
  // typical sample per team-game, for the shrink weight
  let N = 0, G = 0; for (const [S, sit] of Object.entries(md.sit)) for (const [gk, v] of Object.entries(sit)) { if (!v[kind]) continue; const r = { g: +gk.split('|')[0], [kind]: v[kind] }; N += oe(r, kind, keep).n; G++; }
  const per = Math.max(0.2, N / Math.max(1, G));
  return { y: r => { const o = oe(r, kind, keep); return (o.y - o.x) / o.n; }, w: r => oe(r, kind, keep).n / per, ok: r => oe(r, kind, keep).n > 0, x: 100, side: 'o', per }; };

// season-level trait by team (ESPN team id), and the head coach of each team-season (CFBD coaches, most games)
const coaches = fs.existsSync(COACH) ? JSON.parse(fs.readFileSync(COACH, 'utf8')) : [];
const hc = {}; // `${S}|${teamId}` -> coach id
for (const c of coaches) for (const s of c.seasons || []) { const k = `${s.year}|${s.teamId}`; if (!hc[k] || s.games > hc[k].g) hc[k] = { id: c.id, g: s.games || 0 }; }
const coachTeam = {}; // `${S}|${coachId}` -> teamId
for (const [k, v] of Object.entries(hc)) { const [S, t] = k.split('|'); coachTeam[`${S}|${v.id}`] = t; }
const nameToId = {};
for (const gs of Object.values(md.games)) for (const g of gs) { nameToId[g.homeTeam] = String(g.homeId); nameToId[g.awayTeam] = String(g.awayId); }
const seasonTrait = (kind, keep) => { const out = {};
  for (const [S, sit] of Object.entries(md.sit)) for (const [gk, v] of Object.entries(sit)) {
    const [g, team] = gk.split('|'), t = nameToId[team]; if (!t || !v[kind]) continue;
    const o = oe({ g: +g, [kind]: v[kind] }, kind, keep), a = ((out[S] ||= {})[t] ||= { n: 0, y: 0, x: 0 }); a.n += o.n; a.y += o.y; a.x += o.x;
  }
  for (const T of Object.values(out)) for (const [t, a] of Object.entries(T)) T[t] = a.n >= 5 ? (a.y - a.x) / a.n : null;
  return out; };
const goSeason = seasonTrait('fb', () => true), edSeason = seasonTrait('pb', PB.edproe);
const coachPrev = (tab, S, t) => { const c = hc[`${S}|${t}`]; if (!c) return 0; const t0 = coachTeam[`${S - 1}|${c.id}`]; return t0 ? tab[S - 1]?.[t0] ?? 0 : 0; };
const coverage = { coachKnown: 0, coachPrev: 0, n: 0 };
for (const S of Object.keys(md.games).map(Number)) for (const t of new Set(md.games[S].flatMap(g => g.homeClassification === 'fbs' ? [String(g.homeId)] : []))) {
  coverage.n++; if (hc[`${S}|${t}`]) coverage.coachKnown++; if (coachPrev(goSeason, S, t)) coverage.coachPrev++; }
console.log('coach coverage (FBS team-seasons)', JSON.stringify(coverage));

// ---- the model ------------------------------------------------------------------------------------------
process.argv[2] = MERGED; process.env.ONLYSHIP = '1'; process.env.SHIPX = 'p4,aggr';
process.env.BT_OUT = path.join(os.tmpdir(), 'cfb_coach_traits_bt.json');
const { CAND, _internals: I, phi } = await import('./cfb_model.mjs');
for (const k of Object.keys(FB)) CAND[k] = { name: k, ...traitOf(k, 'fb') };
for (const k of Object.keys(PB)) CAND[k] = { name: k, ...traitOf(k, 'pb') };
const fade = r => 3 / (3 + Math.max(0, (r.w ?? 1) - 1));
CAND.cAggr = { name: 'head coach go over expected last season', ctx: r => coachPrev(goSeason, r.S, r.h) - coachPrev(goSeason, r.S, r.a), x: 100 };
CAND.cAggrD = { name: 'head coach go over expected last season, fading', ctx: r => (coachPrev(goSeason, r.S, r.h) - coachPrev(goSeason, r.S, r.a)) * fade(r), x: 100 };
CAND.tAggr = { name: 'team go over expected last season', ctx: r => (goSeason[r.S - 1]?.[r.h] ?? 0) - (goSeason[r.S - 1]?.[r.a] ?? 0), x: 100 };
CAND.cEdproe = { name: 'head coach early-down pass over expected last season', ctx: r => coachPrev(edSeason, r.S, r.h) - coachPrev(edSeason, r.S, r.a), x: 100 };
const B = await import('./cfb_hist_backtest.mjs');
const { fitBeta } = await import('./cfb_model.mjs');

const P = { k: 20, eloHome: 55, lam: 1.5 };
const NEW = [...Object.keys(FB), ...Object.keys(PB), 'cAggr', 'cAggrD', 'tAggr', 'cEdproe'];
const KEYS = ['p4', 'aggr', ...NEW];
I.setExtra(KEYS);
const W = B.walkAll(B.chain('roster', 'pooled'), P);
I.setExtra([]);
const nb = I.BASE_FEATS.length, base = [...I.BASE_FEATS.map((_, i) => i), nb, nb + 1], col = k => nb + KEYS.indexOf(k);
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 1e4) / 1e4;
const ll = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };

// close-anchored blend: close + b (model - close), b and the blend's sd fit on the tune seasons
function blend(o, tune) {
  const T = o.filter(x => x.close != null && tune(x.S));
  const b = T.reduce((a, x) => a + (x.res - x.close) * (x.m - x.close), 0) / T.reduce((a, x) => a + (x.m - x.close) ** 2, 0);
  const s = Math.sqrt(mean(T.map(x => (x.res - x.close - b * (x.m - x.close)) ** 2)));
  return { b, rows: o.filter(x => x.close != null).map(x => { const m = x.close + b * (x.m - x.close); return { ...x, ll: ll(phi(m / s), x.y), ae: Math.abs(x.res - m) }; }) };
}
// expected-sign check: the trait's own weight on the tune seasons (positive: more aggressive / more passing = better)
const weightOf = (cols, k, first, tune) => { const rows = B.SEASONS.filter(tune).flatMap(S => W[S]).filter(p => p.r.S >= first);
  const f = fitBeta(rows.map(p => ({ r: p.r, x: cols.map(i => p.x[i]) }))); return f.beta[1 + cols.indexOf(col(k))]; };

const SPLITS = {
  fb: { first: 2016, tune: S => S >= 2017 && S <= 2020, hold: S => S >= 2021 && S <= 2025, label: 'fit 2016+, tune 2017-20, held 2021-25' },
  pb: { first: 2021, tune: S => S >= 2022 && S <= 2023, hold: S => S >= 2024 && S <= 2025, label: 'fit 2021+, tune 2022-23, held 2024-25' },
};
const kindOf = k => (PB[k] || k === 'cEdproe') ? 'pb' : 'fb';
const res = { asof: new Date().toISOString().slice(0, 10), base: 'ESPN-only pooled model: p4, aggr, roster prior', passBins: pbCover, coachCoverage: coverage,
  splits: Object.fromEntries(Object.entries(SPLITS).map(([k, v]) => [k, v.label])), traits: {}, replaceAggr: {} };
const baseBy = {};
for (const [kind, sp] of Object.entries(SPLITS)) {
  const o = B.predict(W, { cols: base, first: sp.first });
  baseBy[kind] = { o, bl: blend(o, sp.tune) };
  res[`base_${kind}`] = { tune: { n: o.filter(x => sp.tune(x.S)).length, ll: r4(mean(o.filter(x => sp.tune(x.S)).map(x => x.ll))) },
    held: { n: o.filter(x => sp.hold(x.S)).length, ll: r4(mean(o.filter(x => sp.hold(x.S)).map(x => x.ll))), mae: r3(mean(o.filter(x => sp.hold(x.S)).map(x => x.ae))) },
    closeB: r3(baseBy[kind].bl.b) };
}
const test = (k, cols, ref, sp, label) => {
  const o = B.predict(W, { cols, first: sp.first }), bl = blend(o, sp.tune);
  const r = { ll: B.cmp(o, ref.o, 'll', sp.tune, sp.hold), mae: B.cmp(o, ref.o, 'ae', sp.tune, sp.hold), close: B.cmp(bl.rows, ref.bl.rows, 'll', sp.tune, sp.hold),
    closeMae: B.cmp(bl.rows, ref.bl.rows, 'ae', sp.tune, sp.hold), closeB: r3(bl.b), weight: r3(weightOf(cols, k, sp.first, sp.tune)),
    early: B.cmp(o.filter(x => x.w <= 4), ref.o.filter(x => x.w <= 4), 'll', sp.tune, sp.hold) };
  r.pass = r.ll.tune.t <= -1.5 && r.weight > 0 && r.ll.held.d <= 0 && r.mae.held.d <= 0 && r.close.held.d <= 0;
  console.log(label, k, JSON.stringify(r));
  return r;
};
for (const k of NEW) { const sp = SPLITS[kindOf(k)]; res.traits[k] = test(k, [...base, col(k)], baseBy[kindOf(k)], sp, 'add'); }
// in place of aggr: the narrower 4th-down cuts as the one coach trait
const noAggr = base.filter(i => i !== nb + 1);
for (const k of Object.keys(FB)) res.replaceAggr[k] = test(k, [...noAggr, col(k)], baseBy.fb, SPLITS.fb, 'replace');
res.passed = Object.entries(res.traits).filter(([, v]) => v.pass).map(([k]) => k);
res.passedReplace = Object.entries(res.replaceAggr).filter(([, v]) => v.pass).map(([k]) => k);
fs.writeFileSync(path.join(ROOT, 'data', 'cfb_coach_traits.json'), JSON.stringify(res, null, 1));
console.log('passed', res.passed, 'replace', res.passedReplace);
