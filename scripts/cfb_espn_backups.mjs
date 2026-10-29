// ESPN backups: every player on an FBS or FCS ESPN roster that the board doesn't grade (PFN never listed him,
// and On3 doesn't rank him) joins static/data/cfb-all.json, graded up from the 20 FV floor on the drivers we
// have for him: position, height and weight against the position, years in college,
// division and his 247 composite recruiting rating. The grade is a ridge fit of the board's own FV on those
// drivers among its low-snap players (under 60 snaps: graded mostly without production, like the backups),
// so the backups sit on the same scale; anyone the fit puts under 20 sits at the floor. They're scored
// against the board, not added to its pools: no graded player's FV, NIL or team numbers move.
// Called from writeAll in scripts/fetch_cfb.mjs; `node scripts/cfb_espn_backups.mjs` rebuilds them on the
// current cfb-all.json from live ESPN rosters.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compact, Matcher } from './names.mjs';
import { frameFV, bmiOf } from './cfb_frame.mjs';
import { atMean, cfbZ } from './fv_dist.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
export const FLOOR = 20, TRAIN_SNAPS = 60, RIDGE = 5;
const GROUP = { QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', OL: 'OL', OT: 'OL', T: 'OL', G: 'OL', OG: 'OL', C: 'OL', IOL: 'OL',
  DE: 'EDGE', EDGE: 'EDGE', DT: 'DL', NT: 'DL', DL: 'DL', LB: 'LB', OLB: 'LB', ILB: 'LB', MLB: 'LB',
  CB: 'CB', DB: 'CB', S: 'S', FS: 'S', SS: 'S', PK: 'K', K: 'K', P: 'P' };
const POSS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P'];
const norm = compact;   // the shared name key (scripts/names.mjs)
const inches = h => { const m = /(\d+)['\- ]+\s*(\d+)/.exec(h || ''); return m ? +m[1] * 12 + +m[2] : null; };
const yearsOf = cls => { if (!cls) return null; const m = /(RS-)?(Fr|So|Jr|Sr|Gr)/i.exec(cls); if (!m) return null;
  return { fr: 1, so: 2, jr: 3, sr: 4, gr: 5 }[m[2].toLowerCase()] + (m[1] ? 1 : 0); };
const SIZE = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_calibration.json'), 'utf8')).size;
const CLS = { FR: 'Fr', SO: 'So', JR: 'Jr', SR: 'Sr', GR: 'Gr' };

// 247 composite rating by name and high school class (scripts/cfb_recruit_247.json), 0-1
function ratings247(season) {
  const f = path.join(ROOT, 'scripts', 'cfb_recruit_247.json');
  const by = {};
  if (!fs.existsSync(f)) return () => null;
  const d = JSON.parse(fs.readFileSync(f, 'utf8'));
  for (const [y, list] of Object.entries(d.composite || {})) for (const r of list) (by[norm(r[0])] ||= {})[y] = { rating: r[2], rank: r[3], year: +y };
  // the class year is SEASON - years + 1; a year either way for a reclass, two back for a redshirt or gray shirt
  return (name, years) => { const h = by[norm(name)]; if (!h || years == null) return null; const y = season - years + 1;
    return h[y] ?? h[y - 1] ?? h[y + 1] ?? h[y - 2] ?? null; };
}

function solve(A, b) {   // Gaussian elimination, A square
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}
function ridge(X, y, lam) {   // intercept-free design (position dummies carry the level); lam on the slopes only
  const k = X[0].length, A = Array.from({ length: k }, () => Array(k).fill(0)), b = Array(k).fill(0);
  X.forEach((x, i) => { for (let a = 0; a < k; a++) { b[a] += x[a] * y[i]; for (let c = 0; c < k; c++) A[a][c] += x[a] * x[c]; } });
  for (let a = POSS.length; a < k; a++) A[a][a] += lam;
  return solve(A, b);
}

// the scouting report for a backup: each driver's FV points (ridge weight x his value, against a typical player at
// the position for size and a 2.5-year player for class), listed when worth half a point, and the feeder bars in
// the board's composite units (FV / 10): age and class, pedigree, frame
const sg = x => (x >= 0 ? '+' : '') + x.toFixed(1), ftIn = h => `${Math.floor(h / 12)}-${h % 12}`;
function report(g, x, w, { ht, wt, bmi, fr, years, rc }) {
  const k = POSS.length, c = i => x[k + i] * w[k + i];
  const size = c(0) + c(1) + c(8), rec = c(4) + c(5) + c(6), cls = (x[k + 2] - 2.5) * w[k + 2], age = c(7);
  const plus = [], minus = [], put = (v, line) => { if (Math.abs(v) >= 0.5) (v > 0 ? plus : minus).push(`${line} (${sg(v)} FV)`); };
  const frame = [ht ? ftIn(ht) : null, wt ? `${wt} lb` : null, bmi ? `BMI ${bmi.toFixed(1)}` : null].filter(Boolean).join(', ');
  if (g !== 'K' && g !== 'P') {
    put(fr + size, `frame ${frame}`);   // NFL frame points plus size against college players at the position
    if (rc?.rating != null) put(rec, `247 composite ${rc.rating.toFixed(4)}${rc.rank ? `, #${rc.rank} nationally` : ''}${rc.year ? ` (${rc.year} class)` : ''}`);
    put(cls, `${years ?? '?'} year${years === 1 ? '' : 's'} in college`);
    if (Math.abs(x[k + 7]) >= 1) put(age, x[k + 7] > 0 ? `${Math.round(x[k + 7])} year${Math.round(x[k + 7]) === 1 ? '' : 's'} older than his class (redshirt, gray shirt or JUCO)` : 'young for his class');
  }
  const r2 = v => Math.round(v * 100) / 100;
  return { report: { role: 'ESPN roster backup', line: 'graded from the 20 floor on size, NFL frame and BMI, class, age for class, division and recruiting', plus, minus },
    parts: [0, 0, r2((cls + age) / 10), 0, 0, r2(rec / 10), 0, r2((fr + size) / 10)] };
}

// rows: the board's cfb-all rows (objects); rosters: [{ div, teams, rosters }] from ESPN; stars: ARKLIST set
// recById: CFBD recruiting records (247 composite, every high school and JUCO class since 2019) by ESPN athlete id,
// which follow a player through transfers; the 247 snapshot by name and class fills the rest
export function espnBackups(rows, rosters, { season, stars = new Set(), recById = {}, log = console.log } = {}) {
  const byName247 = ratings247(season), idOf = r => (/\/id\/(\d+)/.exec(r.espnl || '') || [])[1];
  const r247 = (name, years, id) => (recById[id]?.rating != null ? recById[id] : null) ?? byName247(name, years);
  // position size norms from the whole board
  const norms = {};
  for (const g of POSS) {
    const grp = rows.filter(r => r.pos === g), hs = grp.map(r => inches(r.ht)).filter(Boolean), ws = grp.map(r => r.wt).filter(Boolean);
    const ms = xs => { const m = xs.reduce((a, b) => a + b, 0) / (xs.length || 1); return [m, Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length || 1)) || 1]; };
    norms[g] = { h: ms(hs), w: ms(ws), b: ms(grp.map(r => bmiOf(inches(r.ht), r.wt)).filter(Boolean)) };
  }
  // recruiting: the composite rating and national rank (log), and an age proxy: years since his high school
  // class beyond his years in college (a redshirt, gray shirt, JUCO stop or late start; ESPN gives no birth
  // dates for college players), and BMI against the position. Each kept for adding out-of-sample fit (5-fold R2
  // .609 -> .616 rank, .619 age proxy, .625 the board's own NFL frame term, .627 BMI). The frame is the board's
  // (scripts/cfb_frame.mjs): the fit is on FV less each player's frame points, which are then added back, as on the board
  const feats = (g, ht, wt, years, fcs, rc) => {
    const hs = rc?.rating ?? null, yrsHs = rc?.year ? season - rc.year + 1 : null;
    const n = norms[g], hz = ht ? (ht - n.h[0]) / n.h[1] : 0, wz = wt ? (wt - n.w[0]) / n.w[1] : 0, yrs = years ?? 2.5;
    const b = bmiOf(ht, wt), bz = b ? (b - n.b[0]) / n.b[1] : 0;
    return [...POSS.map(p => +(p === g)), Math.max(-3, Math.min(3, hz)), Math.max(-3, Math.min(3, wz)), yrs,
      +fcs, hs != null ? (hs - 0.85) * 10 : 0, +(hs != null), rc?.rank ? 6 - Math.log(rc.rank) : 0,
      yrsHs != null ? Math.max(-1, Math.min(3, yrsHs - (years ?? 2.5))) : 0,
      Math.max(-3, Math.min(3, bz))];
  };
  // fit on the grade (fvg; the headline fv is the mean outcome since Oct 21 2026), so a backup is graded on the scale the
  // FV distribution reads, then put at its mean by the caller like every other row
  const gr = r => r.fvg ?? r.fv;
  let train = rows.filter(r => !r.carried && !r.src && gr(r) != null && POSS.includes(r.pos) && (r.snaps == null || r.snaps < TRAIN_SNAPS));
  const frOf = (g, spot, ht, wt) => frameFV({ g, pfnPos: spot, htIn: ht, wtLb: wt }, SIZE);
  const trFr = train.map(r => (r.parts?.[7] != null && r.parts[7] !== 0 ? r.parts[7] * 10 : frOf(r.pos, r.spot, inches(r.ht), r.wt)));
  const X0 = train.map(r => { const y = yearsOf(r.cls); return feats(r.pos, inches(r.ht), r.wt, y, r.div === 'FCS', r247(r.name, y, idOf(r))); });
  // a row with a NaN anywhere (an early, provisional pass of the board can carry one) would turn every weight NaN
  // and leave every backup at the floor, so the fit keeps finite rows only
  const ok = train.map((r, i) => Number.isFinite(gr(r)) && Number.isFinite(trFr[i]) && X0[i].every(Number.isFinite));
  const dropped = ok.filter(v => !v).length;
  train = train.filter((r, i) => ok[i]);
  const X = X0.filter((x, i) => ok[i]), off = trFr.filter((v, i) => ok[i]), y = train.map((r, i) => gr(r) - off[i]);
  // 5-fold out-of-sample check of the fit, logged with the run
  let sse = 0, sst = 0; const mean = train.reduce((a, r) => a + gr(r), 0) / train.length;
  for (let f = 0; f < 5; f++) {
    const fo = i => i % 5, tr = X.map((x, i) => i).filter(i => fo(i) !== f), te = X.map((x, i) => i).filter(i => fo(i) === f);
    const w = ridge(tr.map(i => X[i]), tr.map(i => y[i]), RIDGE);
    for (const i of te) { const p = Math.max(FLOOR, X[i].reduce((a, v, k) => a + v * w[k], 0) + off[i]), t = y[i] + off[i]; sse += (p - t) ** 2; sst += (t - mean) ** 2; }
  }
  const w = ridge(X, y, RIDGE);
  log(`ESPN backups: fit on ${train.length} low-snap players${dropped ? ` (${dropped} with a missing value left out)` : ''}, 5-fold R2 ${(1 - sse / sst).toFixed(3)}; weights ${w.slice(POSS.length).map(v => v.toFixed(2)).join(' ')}`);

  const tidOf = r => (/logos\/(\w+)\.png/.exec(r.logo || '') || [])[1];
  const have = new Set(rows.map(r => `${norm(r.name)}|${tidOf(r)}`));
  for (const r of rows) { const id = idOf(r); if (id) have.add(`id:${id}`); }   // graded under another spelling ("TJ" / "Tarvos")
  // or a name that fits on his team at a position that fits (Will / William Holmes, Smith-Reed / Smith): the shared rules
  const onBoard = new Matcher(rows, { name: 'name', team: tidOf, pos: 'pos', id: idOf, teamEq: (a, b) => a === b });
  const conf = {}; for (const r of rows) { const t = (/logos\/(\w+)\.png/.exec(r.logo || '') || [])[1]; if (t && r.conf) conf[t] = r.conf; }
  const out = [], now = Date.now();
  for (const { div, teams, rosters: R } of rosters) for (const [tid, list] of Object.entries(R || {})) {
    const t = teams[tid]; if (!t || !conf[tid]) continue;   // only teams the board covers
    for (const a of list) {
      const g = GROUP[a.pos]; if (!g || have.has(`${norm(a.name)}|${tid}`) || have.has(`id:${a.id}`)) continue;
      if (onBoard.find(a.name, { team: tid, pos: g, id: a.id, crossTeam: 'none' })[0]) continue;
      // size: ESPN's roster, else his recruiting profile's
      const prof = recById[a.id], ht = inches(a.ht) || prof?.ht || null, wt = a.wt || prof?.wt || null;
      const years = a.years ?? null, rc = r247(a.name, years, a.id);
      // age: his birth date when ESPN lists one, else approximate, on the board's rule (17.9 + years, ~18.9 for a
      // first-year in October) counted from his high school class when 247 has it (catches redshirts, gray shirts and
      // JUCO stops), else from his years in college. The fit already carries both (years, and age for class), so
      // the approximate age is what FV reads; this shows it
      const yrsHs = rc?.year ? season - rc.year + 1 : null;
      const age = a.dob ? (now - Date.parse(a.dob)) / 31557600000 : (yrsHs ?? years) != null ? 17.9 + Math.max(1, yrsHs ?? years) : null;
      // kickers and punters: no driver here grades a specialist, so a backup one sits at the floor
      const x = feats(g, ht, wt, years, div === 'FCS', rc), fr = Math.round(frOf(g, a.pos, ht, wt) * 10) / 10;
      const fvx = g === 'K' || g === 'P' ? FLOOR : Math.max(FLOOR, Math.min(80, x.reduce((s, v, k) => s + v * w[k], 0) + fr));
      const bmi = bmiOf(ht, wt), rep = report(g, x, w, { ht, wt, bmi, fr, years, rc });
      have.add(`${norm(a.name)}|${tid}`);
      out.push({ name: a.name, pos: g, team: t.name, logo: `/img/cfb/logos/${tid}.png`, conf: conf[tid], div, cls: CLS[a.cls] || null,
        ht: ht ? `${Math.floor(ht / 12)}-${ht % 12}` : null, wt: wt || null, bmi: bmi ? Math.round(bmi * 10) / 10 : null, age: a.dob && age != null ? Math.round(age * 10) / 10 : null, ageEst: !a.dob && age != null ? Math.round(age * 10) / 10 : null,
        photo: a.headshot || null, espnl: `https://www.espn.com/college-football/player/_/id/${a.id}`, fv: Math.round(fvx), fvx: Math.round(fvx * 10) / 10,
        report: rep.report, parts: rep.parts, frameFV: fr, posRank: 0, draft27: (years ?? 0) >= 3, src: 'espn', noRec: !rc, years, star: stars.has(a.name) || stars.has(`${a.name}|${t.name}`) || null });
    }
  }
  const lifted = out.filter(r => r.fv > FLOOR).length;
  log(`ESPN backups: ${out.length} roster players added, ${lifted} graded above the ${FLOOR} floor`);
  return out;
}

// standalone: rebuild the backups on the current cfb-all.json from live ESPN rosters
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const ALL = path.join(ROOT, 'static', 'data', 'cfb-all.json');
  const d = JSON.parse(fs.readFileSync(ALL, 'utf8'));
  if (!d.cols.includes('src')) { d.cols.push('src'); d.rows.forEach(r => r.push(null)); }
  const rows = d.rows.map(a => Object.fromEntries(d.cols.map((c, j) => [c, a[j]]))).filter(r => r.src !== 'espn');
  const get = async u => { for (let i = 0; i < 3; i++) { try { const r = await fetch(u); if (r.ok) return r.json(); } catch {} await new Promise(s => setTimeout(s, 1000 * (i + 1))); } return null; };
  const tids = [...new Set(rows.map(r => (/logos\/(\w+)\.png/.exec(r.logo || '') || [])[1]).filter(Boolean))];
  const divOf = {}; for (const r of rows) { const t = (/logos\/(\w+)\.png/.exec(r.logo || '') || [])[1]; if (t) divOf[t] = r.div || 'FBS'; }
  const teams = {}, by = { FBS: {}, FCS: {} };
  for (const id of tids) {
    const j = await get(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/${id}/roster?limit=200`);
    if (!j?.athletes) continue;
    teams[id] = { name: rows.find(r => r.logo === `/img/cfb/logos/${id}.png`)?.team };
    by[divOf[id]][id] = j.athletes.flatMap(g => g.items).map(a => ({ id: a.id, name: a.fullName, pos: a.position?.abbreviation, ht: a.displayHeight, wt: a.weight,
      cls: a.experience?.abbreviation, years: a.experience?.years, dob: a.dateOfBirth || null, headshot: a.headshot?.href || null }));
  }
  const ark = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'arklist.json'), 'utf8'))['college-football'] || [];
  const extra = espnBackups(rows, [{ div: 'FBS', teams, rosters: by.FBS }, { div: 'FCS', teams, rosters: by.FCS }], { season: +(d.asof || '2026').slice(0, 4), stars: new Set(ark) });
  for (const r of extra) if (r.fvx != null) atMean(r, cfbZ({ pos: r.pos, cls: r.cls, years: r.years, noRec: r.noRec, fv: r.fvx }));
  const all = [...rows, ...extra].sort((a, b) => (b.fv ?? -1) - (a.fv ?? -1) || (b.plus - a.plus) || (b.fvx ?? b.fv) - (a.fvx ?? a.fv) || (a.ovr ?? 1e9) - (b.ovr ?? 1e9));
  const seen = {};
  all.forEach((r, i) => { r.ovr = i + 1; if (r.fv != null && r.posRank != null) { const k = `${r.div}|${r.pos}`; r.posRank = seen[k] = (seen[k] || 0) + 1; } });
  d.rows = all.map(r => d.cols.map(c => r[c] ?? null));
  fs.writeFileSync(ALL, JSON.stringify(d));
}
