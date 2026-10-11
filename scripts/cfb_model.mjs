// College football game model for the ARKBOARD (scripts/fetch_cfb.mjs), built on CFBD data:
//   Ratings    Elo (wins and margins) plus opponent-adjusted efficiency: offense and defense EPA per play
//              (garbage time out), solved as a ridge regression that shrinks each team toward its prior
//   Prior      preseason: last season's final Elo, SP+ and efficiency, this season's roster talent (247
//              composite, transfers included) and returning production, weighted by a regression of
//              each team's season-end rating on them (fit one season ahead)
//   Situation  home field, rest, time zones crossed, distance, altitude
//   Margin     a linear blend of the above, fit on walk-forward predictions (each week rated only on
//              earlier weeks); the miss is roughly normal, so win and cover probabilities are Phi(m/sd)
//   Totals     each offense's plays x points per play (both opponent-adjusted) plus wind, rain, cold
//   QB         a starter out swaps his EPA per play for his backup's (shrunk toward replacement)
//   Season     10,000 simulated seasons: wins, conference title game and title, playoff, bowl odds
// Every walk-forward prediction is scored: log loss, Brier, MAE, and against the closing line.

const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000;
const half = x => Math.round(x * 2) / 2;
export function phi(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
const FCS = 'FCS';   // every non-FBS team, pooled in the efficiency ratings
const wk = g => g.seasonType === 'postseason' ? 20 + g.week : g.week;

// ---- small linear algebra --------------------------------------------------------------------------
function ols(X, y, ridge = 1e-6, from = 1) {
  const k = X[0].length, A = Array.from({ length: k }, () => Array(k).fill(0)), b = Array(k).fill(0);
  X.forEach((x, n) => { for (let i = 0; i < k; i++) { b[i] += x[i] * y[n]; for (let j = 0; j < k; j++) A[i][j] += x[i] * x[j]; } });
  for (let i = from; i < k; i++) A[i][i] += ridge;
  for (let i = 0; i < k; i++) {          // Gauss-Jordan
    let p = i; for (let r = i + 1; r < k; r++) if (Math.abs(A[r][i]) > Math.abs(A[p][i])) p = r;
    [A[i], A[p]] = [A[p], A[i]]; [b[i], b[p]] = [b[p], b[i]];
    for (let r = 0; r < k; r++) if (r !== i) { const f = A[r][i] / A[i][i]; for (let c = i; c < k; c++) A[r][c] -= f * A[i][c]; b[r] -= f * b[i]; }
  }
  return b.map((v, i) => v / A[i][i]);
}
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);

// ---- opponent adjustment ---------------------------------------------------------------------------
// y = mu + O[off] + D[def] + h * side (side +1 home offense, -1 away, 0 neutral), weighted; each O and D
// shrunk toward its prior with lam games of weight. Gauss-Seidel, a few dozen sweeps.
function adjust(obs, prior = {}, lam = 3, iters = 30) {
  const O = {}, D = {}, byO = {}, byD = {};
  for (const o of obs) { (byO[o.o] ||= []).push(o); (byD[o.d] ||= []).push(o); }
  const po = t => prior.O?.[t] ?? 0, pd = t => prior.D?.[t] ?? 0;
  for (const t of Object.keys(byO)) O[t] = po(t);
  for (const t of Object.keys(byD)) D[t] = pd(t);
  for (const t of Object.keys(prior.O || {})) O[t] ??= po(t);    // teams yet to play keep their prior
  for (const t of Object.keys(prior.D || {})) D[t] ??= pd(t);
  let mu = obs.length ? obs.reduce((a, o) => a + o.w * o.y, 0) / obs.reduce((a, o) => a + o.w, 0) : 0, h = 0;
  for (let it = 0; it < iters; it++) {
    let sw = 0, sh = 0, ss = 0;
    for (const o of obs) { const r = o.y - O[o.o] - D[o.d]; sw += o.w * (r - h * o.s); sh += o.w * o.s * (r - mu); ss += o.w * o.s * o.s; }
    mu = sw / obs.reduce((a, o) => a + o.w, 0); h = ss ? sh / ss : 0;
    for (const [t, list] of Object.entries(byO)) { let n = lam * po(t), w = lam; for (const o of list) { n += o.w * (o.y - mu - D[o.d] - h * o.s); w += o.w; } O[t] = n / w; }
    for (const [t, list] of Object.entries(byD)) { let n = lam * pd(t), w = lam; for (const o of list) { n += o.w * (o.y - mu - O[o.o] - h * o.s); w += o.w; } D[t] = n / w; }
  }
  return { O, D, mu, h };
}
// Massey-style margin rating (season-end target for the prior fit): margin = R[h] - R[a] + hfa
function massey(games, lam = 1, iters = 60) {
  const R = {}, by = {};
  for (const g of games) { (by[g.h] ||= []).push(g); (by[g.a] ||= []).push(g); R[g.h] = 0; R[g.a] = 0; }
  let hfa = 0;
  for (let it = 0; it < iters; it++) {
    const hs = games.filter(g => !g.n); hfa = hs.length ? mean(hs.map(g => g.m - R[g.h] + R[g.a])) : 0;
    for (const [t, list] of Object.entries(by)) {
      let n = 0; for (const g of list) { const e = g.m - (g.n ? 0 : hfa); n += g.h === t ? e + R[g.a] : R[g.h] - e; }
      R[t] = n / (list.length + lam);
    }
  }
  return R;
}

// ---- Elo -------------------------------------------------------------------------------------------
// FiveThirtyEight-style, as scripts/cfb_teams.mjs; here K and home field are tuned in the backtest
function eloRun(games, start, P) {
  const r = { ...start };
  const get = id => (r[id] ??= start[id] ?? start.fcsMean ?? 1200);
  for (const g of games) {
    const hr = get(g.h) + (g.n ? 0 : P.eloHome), ar = get(g.a);
    const exp = 1 / (1 + 10 ** ((ar - hr) / 400)), res = g.m > 0 ? 1 : g.m < 0 ? 0 : 0.5;
    const edge = res === 1 ? hr - ar : ar - hr, mult = Math.log(Math.abs(g.m) + 1) * 2.2 / (0.001 * edge + 2.2);
    const s = P.k * mult * (res - exp); r[g.h] += s; r[g.a] -= s;
  }
  return r;
}

// ---- geography -------------------------------------------------------------------------------------
const tzOffset = (tz, when) => {
  try {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: tz, hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
      .formatToParts(when).map(x => [x.type, x.value]));
    return (Date.UTC(+p.year, p.month - 1, +p.day, +p.hour % 24, +p.minute) - when.getTime()) / 36e5;
  } catch { return null; }
};
const km = (a, b) => {
  const R = 6371, rad = Math.PI / 180, dl = (b.lat - a.lat) * rad, dn = (b.lon - a.lon) * rad;
  const x = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dn / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
};
function places(venues, teamsFbs, allGames) {
  const V = {};
  for (const v of venues || []) if (v.latitude != null) V[v.id] = { lat: v.latitude, lon: v.longitude, elev: v.elevation != null ? +v.elevation : null, tz: v.timezone, dome: !!v.dome };
  const home = {};
  for (const t of teamsFbs || []) if (t.location?.latitude != null) home[t.id] = { lat: t.location.latitude, lon: t.location.longitude,
    elev: t.location.elevation != null ? +t.location.elevation : null, tz: t.location.timezone, dome: !!t.location.dome };
  // everyone else: the venue of their most frequent true home game
  const cnt = {};
  for (const g of allGames) if (!g.neutralSite && V[g.venueId]) { const c = (cnt[g.homeId] ||= {}); c[g.venueId] = (c[g.venueId] || 0) + 1; }
  for (const [t, c] of Object.entries(cnt)) if (!home[t]) home[t] = V[Object.entries(c).sort((a, b) => b[1] - a[1])[0][0]];
  return { V, home };
}

// ---- the dataset: one row per game, everything known before kickoff --------------------------------
// S: { games (CFBD), adv (CFBD advanced box, garbage time out), lines } by season
function prepare(seasons, data, geo) {
  const rows = [];
  for (const S of seasons) {
    const cls = c => c === 'fbs' || c === 'fcs';
    const gs = data.games[S].filter(g => cls(g.homeClassification) && cls(g.awayClassification) && g.homeId && g.awayId)
      .sort((a, b) => a.startDate.localeCompare(b.startDate));
    const last = {};
    const lines = Object.fromEntries((data.lines[S] || []).map(l => [l.id, l]));
    for (const g of gs) {
      const when = new Date(g.startDate), v = geo.V[g.venueId] || (!g.neutralSite ? geo.home[g.homeId] : null);
      const trip = id => {
        const h = geo.home[id]; if (!h || !v) return { km: 0, tz: 0 };
        const a = tzOffset(h.tz, when), b = tzOffset(v.tz, when);
        return { km: km(h, v) / 1000, tz: a != null && b != null ? Math.abs(a - b) : 0 };
      };
      const th = trip(g.homeId), ta = trip(g.awayId);
      const rest = id => Math.min(14, Math.max(4, last[id] ? (when - last[id]) / 864e5 : 14));
      const elev = v?.elev ?? 0, lowland = id => (geo.home[id]?.elev ?? 0) < 900;
      const line = (lines[g.id]?.lines || []);
      const pick = line.find(l => l.provider === 'consensus') || line.find(l => l.provider === 'ESPN Bet') || line.find(l => l.spread != null) || null;
      rows.push({
        id: g.id, S, w: wk(g), fbsGame: g.homeClassification === 'fbs' || g.awayClassification === 'fbs', date: g.startDate, done: !!g.completed && g.homePoints != null, h: g.homeId, a: g.awayId,
        hn: g.homeTeam, an: g.awayTeam, hc: g.homeClassification, ac: g.awayClassification, conf: !!g.conferenceGame,
        hconf: g.homeConference, aconf: g.awayConference, venueId: g.venueId, dome: !!v?.dome, lat: v?.lat, lon: v?.lon,
        n: !!g.neutralSite, m: g.completed ? g.homePoints - g.awayPoints : null, tot: g.completed ? g.homePoints + g.awayPoints : null,
        hp: g.homePoints, ap: g.awayPoints,
        rest: rest(g.homeId) - rest(g.awayId), tz: ta.tz - th.tz, dist: ta.km - th.km,
        alt: elev > 1200 ? (lowland(g.awayId) ? 1 : 0) - (g.neutralSite && lowland(g.homeId) ? 1 : 0) : 0,
        close: pick?.spread != null ? -pick.spread : null,                // market home margin (closing)
        closeTot: pick?.overUnder ?? null, open: pick?.spreadOpen != null ? -pick.spreadOpen : null,
      });
      if (g.completed) { last[g.homeId] = when; last[g.awayId] = when; }
    }
  }
  return rows;
}

// red-zone trips by game and offense (CFBD drives): drives that reach the 20, and the points they produce; and every
// drive's start (yards to goal), for field position
function rzByGame(drives) {
  const out = {};
  for (const x of drives || []) {
    const k = x.g + '|' + x.o, v = (out[k] ||= { trips: 0, pts: 0, fpN: 0, fpS: 0, dr: 0, dTd: 0, dFg: 0, dLost: 0 });
    v.dr++; if (x.res === 'TD') v.dTd++; else if (x.res === 'FG') v.dFg++; else if (/^(INT|FUMBLE) TD|PUNT RETURN TD|BLOCKED .*TD/.test(x.res || '')) v.dLost++;
    if (x.s != null && x.s > 0 && x.s < 100) { v.fpN++; v.fpS += x.s; }
    if (x.e == null || x.e > 20 && (x.s ?? 99) > 20) continue;
    v.trips++; v.pts += /^TD$/.test(x.res) ? 7 : x.res === 'FG' ? 3 : 0;
  }
  return out;
}
// situational plays by game and offense (CFBD plays, slim: g game, o offense, q quarter, ytg yards to goal, dn down,
// ds distance, y yards gained, t play type, sm offense score minus defense score): early downs (1st and 2nd) and
// their successes, 3rd downs and conversions, red-zone plays (inside the 20) and their successes. Success: 50% of
// the distance on 1st down, 70% on 2nd, all of it on 3rd and 4th, or a touchdown; a turnover never is. Garbage time
// is out where the score is known (CFBD's cut: up 38+ in the 2nd quarter, 28+ in the 3rd, 22+ in the 4th).
const SCRIM = /^(Rush|Pass|Sack)|Rushing Touchdown|Passing Touchdown|Interception|Fumble/;
const GARBAGE = { 2: 38, 3: 28, 4: 22 };
// Coach decisions, counted by situation bin so a league-expected rate can be taken out later (decisions):
//   fb  4th downs: [decisions, goes] by distance (1, 2-3, 4-6, 7+), field (yards to goal 61+, 41-60, 21-40, 1-20),
//       score (down 9+, within 8, up 9+) and 4th quarter or not; a go is any scrimmage play, the rest punt or kick
//   pb  1st-3rd down plays: [plays, passes] by down, distance (1-3, 4-7, 8+), score and 4th quarter (sacks count as
//       passes, scrambles as runs)
const bin = (a, cuts) => { let i = 0; while (i < cuts.length && a > cuts[i]) i++; return i; };
const scoreBin = sm => sm == null ? 1 : sm <= -9 ? 0 : sm >= 9 ? 2 : 1;
export function sitByGame(plays) {
  const out = {};
  const get = p => (out[p.g + '|' + p.o] ||= { ed: 0, edS: 0, td: 0, tdC: 0, rz: 0, rzS: 0, fb: {}, pb: {} });
  for (const p of plays || []) {
    const t = p.t || '';
    if (!(p.dn >= 1 && p.dn <= 4) || !(p.ds > 0) || !p.o) continue;
    if (p.sm != null && Math.abs(p.sm) >= (GARBAGE[p.q] ?? 99)) continue;
    const late = p.q >= 4 ? 1 : 0;
    if (p.dn === 4 && p.ytg != null && (SCRIM.test(t) || /Punt|Field Goal/.test(t))) {
      const k = `${bin(p.ds, [1, 3, 6])}${3 - bin(p.ytg, [20, 40, 60])}${scoreBin(p.sm)}${late}`, v = (get(p).fb[k] ||= [0, 0]);
      v[0]++; if (SCRIM.test(t) && !/Punt|Field Goal/.test(t)) v[1]++;
    }
    if (!SCRIM.test(t)) continue;
    if (p.dn <= 3) {
      const k = `${p.dn}${bin(p.ds, [3, 7])}${scoreBin(p.sm)}${late}`, v = (get(p).pb[k] ||= [0, 0]);
      v[0]++; if (/Pass|Sack|Interception/.test(t)) v[1]++;
    }
    const lost = /Interception|Fumble Recovery \(Opponent\)|Return Touchdown|Safety/.test(t);
    const need = p.dn === 1 ? 0.5 * p.ds : p.dn === 2 ? 0.7 * p.ds : p.ds;
    const ok = !lost && (/^(Rushing|Passing) Touchdown/.test(t) || (p.y ?? 0) >= need) ? 1 : 0;
    const v = get(p);
    if (p.dn <= 2) { v.ed++; v.edS += ok; }
    if (p.dn === 3) { v.td++; v.tdC += ok; }
    if (p.ytg != null && p.ytg <= 20) { v.rz++; v.rzS += ok; }
  }
  return out;
}
// efficiency observations from the advanced box score, by game, with the drive and play splits alongside
function effObs(adv, nameId, gameById, fbs, rz = {}, sit = {}) {
  const out = [];
  for (const r of adv || []) {
    const g = gameById[r.gameId]; if (!g) continue;
    const t = nameId[r.team], o = nameId[r.opponent]; if (!t || !o) continue;
    const id = x => fbs.has(x) ? x : FCS;
    const s = g.n ? 0 : t === g.h ? 1 : -1;
    const pts = t === g.h ? g.hp : g.ap;
    const z = rz[r.gameId + '|' + r.team], c = sit[r.gameId + '|' + r.team] || {};
    out.push({ g: g.id, w: g.w, t: id(t), opp: id(o), s, plays: r.offense?.plays || 0, ppa: r.offense?.ppa, sr: r.offense?.successRate, xpl: r.offense?.explosiveness, pts,
      rzTrips: z?.trips ?? 0, rzPts: z?.pts ?? 0, fpN: z?.fpN ?? 0, fpS: z?.fpS ?? 0, dr: z?.dr ?? 0, dTd: z?.dTd ?? 0, dFg: z?.dFg ?? 0, dLost: z?.dLost ?? 0,
      stuff: r.offense?.stuffRate ?? null, line: r.offense?.lineYards ?? null, ed: c.ed || 0, edS: c.edS || 0, td: c.td || 0, tdC: c.tdC || 0, rz: c.rz || 0, rzS: c.rzS || 0, fb: c.fb, pb: c.pb });
  }
  return out;
}
// candidate team inputs, each opponent-adjusted like EPA (offense and defense, shrunk toward average by lam games of
// weight; w scales a game's weight by its sample against a typical game): overall success rate, early-down success
// rate, 3rd-down conversion rate, red-zone play success rate, red-zone points per trip, explosiveness (EPA on
// successful plays). x is the feature's unit (rates in percentage points). A candidate stays in the model only when
// it lowers out-of-sample log loss (runModel: season-swap cross-validation, forward selection).
export const CAND = {
  sr:   { name: 'success rate', y: r => r.sr, w: r => r.plays / 65, ok: r => r.sr != null, x: 100 },
  ed:   { name: 'early-down success rate', y: r => r.edS / r.ed, w: r => r.ed / 45, ok: r => r.ed > 0, x: 100, pbp: true },
  td:   { name: '3rd-down conversion rate', y: r => r.tdC / r.td, w: r => r.td / 14, ok: r => r.td > 0, x: 100, pbp: true },
  rzsr: { name: 'red-zone success rate', y: r => r.rzS / r.rz, w: r => r.rz / 10, ok: r => r.rz > 0, x: 100, pbp: true },
  rz:   { name: 'red-zone points per trip', y: r => r.rzPts / r.rzTrips, w: r => r.rzTrips / 4, ok: r => r.rzTrips > 0, x: 1 },
  xpl:  { name: 'explosiveness', y: r => r.xpl, w: r => r.plays / 65, ok: r => r.xpl != null, x: 10 },
  // sign: the direction a better team moves the stat (offense minus defense); a kept input's weight must agree
  stuff: { name: 'stuff rate (runs stopped at or behind the line)', y: r => r.stuff, w: r => r.plays / 65, ok: r => r.stuff != null, x: 100, sign: -1 },
  line:  { name: 'line yards per carry', y: r => r.line, w: r => r.plays / 65, ok: r => r.line != null, x: 1 },
  fp:    { name: 'starting field position (yards to goal)', y: r => r.fpS / r.fpN, w: r => r.fpN / 12, ok: r => r.fpN > 0, x: 1, sign: -1 },
  // recent form: net EPA per play with the last games weighted up (half-life 3 weeks) minus the season's, in points
  // a game; hot and cold stretches that outrun the ratings
  form:  { name: 'recent form (last ~3 weeks over the season)', x: 65, special: true },
  // results alone, not opponent-adjusted: win share to date (per 10 points of win %) and average scoring margin
  // (each game capped at 28), each minus average. Elo already counts wins and margins against the opponent; these
  // test whether the record itself carries anything more (the poll voter's view)
  wpct:  { name: 'win % to date (record only)', x: 10, special: true, side: 'o' },
  mov:   { name: 'scoring margin to date, unadjusted', x: 1, special: true, side: 'o' },
  // weather that squeezes margins: wind over 10 mph (per 10) plus rain, times the Elo gap (per 25); a better team's
  // edge shrinks in bad weather, so the weight should be negative
  // the drive simulation's expected margin (simGame): drives a game x (7 x TD rate + 3 x FG rate - 7 x return-TD
  // rate), each opponent-adjusted, home minus away
  drv:   { name: 'drive model expected margin', special: true, x: 1 },
  // returning production (PFN, last season's scores of this season's players x snaps; z across FBS; non-FBS -2): the
  // QB, and everyone else. Known before the season, so it carries what FV would if FV had a history
  qbRet: { name: 'returning QB production (PFN)', ctx: (r) => retOf(r, 'qb'), team: (S, t) => RET[S]?.[t]?.qb ?? 0, x: 1 },
  ret:   { name: 'returning production, non-QB (PFN)', ctx: (r) => retOf(r, 'rest'), team: (S, t) => RET[S]?.[t]?.rest ?? 0, x: 1 },
  // returning college WAR (season AV, scripts/cfb_av.mjs position weights on last season's Stat+ x snaps, z across
  // FBS, so the same feature in AV or WAR units): every position, and every position but QB (qbRet carries the QB)
  avRet:  { name: 'returning college WAR, all positions', ctx: (r) => retOf(r, 'av'), team: (S, t) => RET[S]?.[t]?.av ?? 0, x: 1 },
  avRest: { name: 'returning college WAR, non-QB', ctx: (r) => retOf(r, 'avRest'), team: (S, t) => RET[S]?.[t]?.avRest ?? 0, x: 1 },
  wxc:   { name: 'bad weather x Elo gap (margin squeeze)', ctx: (r, x) => { const w = WXM[r.id]; if (!w || r.dome) return 0; return (Math.max(0, w.w - 10) / 10 + (w.p > 2 ? 1 : 0)) * x[0]; }, x: 1, sign: -1 },
  // coach traits (the offense's own choices, so only the offense side counts): 4th-down go rate and pass rate, each
  // over the league's rate in the same situations (decisions)
  aggr: { name: '4th-down aggressiveness (go rate over expected)', y: r => (r.f4go - r.f4x) / r.f4n, w: r => r.f4n / 3, ok: r => r.f4n > 0, x: 100, pbp: true, side: 'o' },
  proe: { name: 'pass rate over expected', y: r => (r.pass - r.passX) / r.pn, w: r => r.pn / 60, ok: r => r.pn > 0, x: 100, pbp: true, side: 'o' },
};
// league rates by situation bin for one season's rows, then each row's expected goes and passes
function decisions(rows) {
  const L = { fb: {}, pb: {} };
  for (const r of rows) for (const k of ['fb', 'pb']) for (const [b, [n, y]] of Object.entries(r[k] || {})) { const v = (L[k][b] ||= [0, 0]); v[0] += n; v[1] += y; }
  const exp = (k, bins) => Object.entries(bins || {}).reduce((a, [b, [n, y]]) => { const l = L[k][b]; a.n += n; a.y += y; a.x += n * (l[1] / l[0]); return a; }, { n: 0, y: 0, x: 0 });
  for (const r of rows) {
    const f = exp('fb', r.fb), q = exp('pb', r.pb);
    r.f4n = f.n; r.f4go = f.y; r.f4x = f.x; r.pn = q.n; r.pass = q.y; r.passX = q.x;
  }
}
const exNet = (k, m, t) => (m.O[t] ?? 0) - (CAND[k].side === 'o' ? 0 : m.D[t] ?? 0);
function ratingsAt(effRows, before, prior, P, keys = EXTRA) {
  const rows = effRows.filter(r => r.w < before && r.plays > 0 && r.ppa != null);
  const ppa = adjust(rows.map(r => ({ o: r.t, d: r.opp, y: r.ppa, w: r.plays / 65, s: r.s })), prior.ppa, P.lam);
  const ppp = adjust(rows.map(r => ({ o: r.t, d: r.opp, y: r.pts / r.plays, w: r.plays / 65, s: r.s })), prior.ppp, P.lam);
  const pace = adjust(rows.map(r => ({ o: r.t, d: r.opp, y: r.plays, w: 1, s: r.s })), prior.pace, P.lam);
  const ex = {};
  for (const k of keys) { const c = CAND[k]; if (c.special || c.ctx) continue; ex[k] = adjust(rows.filter(c.ok).map(r => ({ o: r.t, d: r.opp, y: c.y(r), w: c.w(r), s: r.s })), {}, P.lam); }
  if (keys.includes('drv') || DRIVES) {
    const dr = rows.filter(r => r.dr > 0);
    ex.drv = { n: adjust(dr.map(r => ({ o: r.t, d: r.opp, y: r.dr, w: 1, s: r.s })), {}, P.lam),
      td: adjust(dr.map(r => ({ o: r.t, d: r.opp, y: r.dTd / r.dr, w: r.dr / 12, s: r.s })), {}, P.lam),
      fg: adjust(dr.map(r => ({ o: r.t, d: r.opp, y: r.dFg / r.dr, w: r.dr / 12, s: r.s })), {}, P.lam),
      lost: adjust(dr.map(r => ({ o: r.t, d: r.opp, y: r.dLost / r.dr, w: r.dr / 12, s: r.s })), {}, P.lam) };
  }
  if (keys.includes('wpct') || keys.includes('mov')) {
    const by = {}; for (const r of rows) (by[r.g] ||= []).push(r);
    const rec = {};
    for (const gm of Object.values(by)) if (gm.length === 2) for (const [a, b] of [gm, [gm[1], gm[0]]]) {
      if (a.t === FCS || a.pts == null || b.pts == null) continue;
      const m = a.pts - b.pts, x = (rec[a.t] ||= { n: 0, w: 0, m: 0 });
      x.n++; x.w += m > 0 ? 1 : m < 0 ? 0 : 0.5; x.m += Math.max(-28, Math.min(28, m));
    }
    ex.wpct = { O: {}, D: {}, mu: 0 }; ex.mov = { O: {}, D: {}, mu: 0 };
    for (const [t, x] of Object.entries(rec)) { ex.wpct.O[t] = x.w / x.n - 0.5; ex.mov.O[t] = x.m / x.n; }
  }
  if (keys.includes('form')) {
    const last = Math.max(0, ...rows.map(r => r.w));
    const rec = adjust(rows.map(r => ({ o: r.t, d: r.opp, y: r.ppa, w: r.plays / 65 * 0.5 ** ((last - r.w) / 3), s: r.s })), prior.ppa, P.lam);
    ex.form = { O: {}, D: {}, mu: 0 };
    for (const t of Object.keys(rec.O)) ex.form.O[t] = rec.O[t] - (ppa.O[t] ?? 0);
    for (const t of Object.keys(rec.D)) ex.form.D[t] = rec.D[t] - (ppa.D[t] ?? 0);
  }
  return { ppa, ppp, pace, ex };
}
let EXTRA = [], WXM = {}, RET = {}, DRIVES = false, SIMTEST = false, SIMR = Math.random;
// ---- drive simulation ------------------------------------------------------------------------------------
// Each team's drives a game and, per drive, its chance of a touchdown, a field goal and a touchdown for the other side
// (pick-six, fumble or return), all opponent-adjusted like EPA with home field. driveRates gives one side's numbers;
// simGame plays the game N times: each side gets its expected drives (rounded at random), every drive drawn as TD
// (7), FG (3), lost TD (-7 to the offense) or nothing; a tie is a coin flip
function driveRates(m, o, d, s) {
  const c = (a, lo, hi) => Math.min(hi, Math.max(lo, a));
  const f = (A, dflt) => isFinite(A.mu) ? A.mu + (A.O[o] ?? 0) + (A.D[d] ?? 0) + (A.h || 0) * s : dflt;   // no drives yet: league norms
  return { n: c(f(m.n, 12), 6, 20), td: c(f(m.td, 0.25), 0.02, 0.8), fg: c(f(m.fg, 0.12), 0, 0.4), lost: c(f(m.lost, 0.01), 0, 0.08) };
}
export function simGame(m, h, a, s, N = 2000, R = Math.random) {
  const H = driveRates(m, h, a, s), A = driveRates(m, a, h, -s);
  const pts = (x, opp) => { const u = R(); return u < x.td ? [7, 0] : u < x.td + x.fg ? [3, 0] : u < x.td + x.fg + x.lost ? [0, 7] : [0, 0]; };
  const n = x => Math.floor(x.n) + (R() < x.n % 1 ? 1 : 0);
  let win = 0, sumM = 0, sumM2 = 0; const margins = [], totals = [];
  for (let i = 0; i < N; i++) {
    let hp = 0, ap = 0;
    for (let k = n(H); k > 0; k--) { const [x, y] = pts(H); hp += x; ap += y; }
    for (let k = n(A); k > 0; k--) { const [x, y] = pts(A); ap += x; hp += y; }
    const mm = hp - ap; win += mm > 0 ? 1 : mm === 0 ? 0.5 : 0; sumM += mm; sumM2 += mm * mm; margins.push(mm); totals.push(hp + ap);
  }
  margins.sort((u, v) => u - v); totals.sort((u, v) => u - v);
  const q = (xs, p) => xs[Math.min(xs.length - 1, Math.floor(p * xs.length))];
  return { p: win / N, mean: sumM / N, sd: Math.sqrt(Math.max(0, sumM2 / N - (sumM / N) ** 2)), m10: q(margins, 0.1), m90: q(margins, 0.9),
    tot: totals.reduce((x, y) => x + y, 0) / N, t10: q(totals, 0.1), t90: q(totals, 0.9), totals };
}
// expected margin from the drive rates (the simulation's mean, without the noise)
function driveMargin(m, h, a, s) {
  const H = driveRates(m, h, a, s), A = driveRates(m, a, h, -s);
  return H.n * (7 * H.td + 3 * H.fg - 7 * H.lost) - A.n * (7 * A.td + 3 * A.fg - 7 * A.lost);
}
const retOf = (r, k) => { const R = RET[r.S]; if (!R) return 0; const v = t => R[t]?.[k] ?? -2; return v(r.h) - v(r.a); };

// ---- special teams (CFBD drives) --------------------------------------------------------------------
// Points a team's kicking units add, from each drive's start and end: field goals (3 x made minus the make
// rate at that distance, a logistic fit across every kick), punts (the opponent's next start against the
// average start after a punt from that spot) and kickoffs after scores (the receiving team's start against
// the average), field position at 0.065 points a yard (the slope of expected points between the 20s). A
// return TD costs the kicking team 6.5. Each game: own units minus the opponent's, so returns and coverage
// count for both sides. Rating: the mean per game, shrunk toward half of last season's by 4 games.
export const slimDrives = d => (d || []).map(x => ({ g: x.gameId, n: x.driveNumber, o: x.offense, d: x.defense,
  s: x.startYardsToGoal, e: x.endYardsToGoal, res: x.driveResult, p: x.startPeriod }));
const ST = { ppy: 0.065, retTd: 6.5, lam: 4, carry: 0.5 };
const SCORE = /^(TD|FG)$/;
function stCurves(all) {
  // FG make rate by distance: logistic by Newton steps on [1, distance]
  // (spots past the 51 are bad data: a 68-yard kick is the longest plausible)
  const kicks = all.filter(x => /FG/.test(x.res) && !/TD/.test(x.res) && x.e != null && x.e <= 51).map(x => ({ d: x.e + 17, y: x.res === 'FG' ? 1 : 0 }));
  let a = 3, b = -0.05;
  for (let it = 0; it < 25; it++) {
    let ga = 0, gb = 0, haa = 0, hab = 0, hbb = 0;
    for (const k of kicks) { const p = 1 / (1 + Math.exp(-(a + b * k.d))), w = p * (1 - p); ga += k.y - p; gb += (k.y - p) * k.d; haa += w; hab += w * k.d; hbb += w * k.d * k.d; }
    const det = haa * hbb - hab * hab; if (!det) break;
    a += (hbb * ga - hab * gb) / det; b += (haa * gb - hab * ga) / det;
  }
  // the opponent's start after a punt, by the punting spot (10-yard bins), and after a kickoff
  const byGame = {};
  for (const x of all) (byGame[x.g] ||= []).push(x);
  const punt = {}, ko = [];
  for (const list of Object.values(byGame)) {
    list.sort((u, v) => u.n - v.n);
    for (let i = 0; i < list.length - 1; i++) {
      const x = list[i], nx = list[i + 1];
      if (nx.o !== x.d || nx.s == null || nx.p !== x.p) continue;
      if (x.res === 'PUNT' && x.e != null) (punt[Math.min(9, Math.floor(x.e / 10))] ||= []).push(nx.s);
      if (SCORE.test(x.res)) ko.push(nx.s);
    }
  }
  return { fg: d => 1 / (1 + Math.exp(-(a + b * d))), punt: Object.fromEntries(Object.entries(punt).map(([k, v]) => [k, mean(v)])), ko: mean(ko), fgA: a, fgB: b };
}
function stObs(drives, nameId, gameById, fbs, C) {
  const byGame = {};
  for (const x of drives || []) (byGame[x.g] ||= []).push(x);
  const out = [];
  for (const [g, list] of Object.entries(byGame)) {
    const G = gameById[g]; if (!G) continue;
    list.sort((u, v) => u.n - v.n);
    const val = {};
    const add = (team, v) => { val[team] = (val[team] || 0) + v; };
    for (let i = 0; i < list.length; i++) {
      const x = list[i], nx = list[i + 1];
      if (/FG/.test(x.res) && !/TD/.test(x.res) && x.e != null && x.e <= 51) add(x.o, 3 * ((x.res === 'FG' ? 1 : 0) - C.fg(x.e + 17)));
      if (/PUNT (RETURN )?TD/.test(x.res)) add(x.o, -ST.retTd);
      if (!nx || nx.o !== x.d || nx.s == null || nx.p !== x.p) continue;
      if (x.res === 'PUNT' && x.e != null) add(x.o, ST.ppy * (nx.s - (C.punt[Math.min(9, Math.floor(x.e / 10))] ?? nx.s)));
      if (SCORE.test(x.res)) add(x.o, ST.ppy * (nx.s - C.ko));
    }
    const teams = [...new Set(list.flatMap(x => [x.o, x.d]))];
    if (teams.length !== 2) continue;
    for (const t of teams) {
      const o = teams.find(u => u !== t), id = nameId[t];
      if (!id || !fbs.has(id)) continue;
      out.push({ g: G.id, w: G.w, t: id, net: (val[t] || 0) - (val[o] || 0) });
    }
  }
  return out;
}
// season totals by team (CFBD school name) for the kicking units: field goals over expected (attempts, made,
// points over the make rate by distance, longest), punts (count and points of field position vs average)
function stUnits(drives, C) {
  const byGame = {}, T = {};
  for (const x of drives || []) (byGame[x.g] ||= []).push(x);
  const t = n => (T[n] ||= { fga: 0, fgm: 0, fgPoe: 0, long: 0, punts: 0, puntVal: 0, games: new Set() });
  for (const [g, list] of Object.entries(byGame)) {
    list.sort((u, v) => u.n - v.n);
    for (let i = 0; i < list.length; i++) {
      const x = list[i], nx = list[i + 1]; t(x.o).games.add(g);
      if (/FG/.test(x.res) && !/TD/.test(x.res) && x.e != null && x.e <= 51) {
        const made = x.res === 'FG' ? 1 : 0, u = t(x.o);
        u.fga++; u.fgm += made; u.fgPoe += 3 * (made - C.fg(x.e + 17)); if (made) u.long = Math.max(u.long, x.e + 17);
      }
      if (x.res === 'PUNT' && x.e != null && nx && nx.o === x.d && nx.s != null && nx.p === x.p) {
        const u = t(x.o); u.punts++; u.puntVal += ST.ppy * (nx.s - (C.punt[Math.min(9, Math.floor(x.e / 10))] ?? nx.s));
      }
      if (/PUNT (RETURN )?TD/.test(x.res)) { const u = t(x.o); u.punts++; u.puntVal -= ST.retTd; }
    }
  }
  for (const u of Object.values(T)) u.games = u.games.size;
  return T;
}
function stAt(rows, before, prior = {}) {
  const sum = {}, n = {};
  for (const r of rows) if (r.w < before) { sum[r.t] = (sum[r.t] || 0) + r.net; n[r.t] = (n[r.t] || 0) + 1; }
  const out = {};
  for (const t of new Set([...Object.keys(sum), ...Object.keys(prior)])) out[t] = ((sum[t] || 0) + ST.lam * (prior[t] ?? 0)) / ((n[t] || 0) + ST.lam);
  return out;
}

// ---- preseason prior ---------------------------------------------------------------------------------
// features: last season's final Elo (points over average), SP+, final efficiency (net EPA/play), and
// this season's talent and returning production (z across FBS); a team new to FBS gets the FCS level.
function priorFeatures(S, data, fbsS, nameId, finals) {
  const z = (list, f) => {
    const vals = list.map(f).filter(v => v != null), m = mean(vals), s = sd(vals);
    return Object.fromEntries(list.map(x => [nameId[x.team], f(x) == null ? 0 : (f(x) - m) / s]).filter(([k]) => k));
  };
  const tal = z(data.talent[S] || [], x => x.talent), ret = z(data.returning[S] || [], x => x.percentPPA);
  const sp = Object.fromEntries((data.sp[S - 1] || []).filter(x => x.rating != null).map(x => [nameId[x.team], x.rating]));
  const F = {};
  for (const t of fbsS) {
    const f = finals[S - 1];
    const was = f && f.fbs.has(t);
    F[t] = { elo: f?.elo[t] != null ? (f.elo[t] - 1500) / 25 : (f ? (f.elo.fcsMean - 1500) / 25 : -10), sp: sp[t] ?? (was ? (f.elo[t] - 1500) / 25 : -12),
      net: was ? (f.eff.ppa.O[t] ?? 0) - (f.eff.ppa.D[t] ?? 0) : (f ? (f.eff.ppa.O[FCS] ?? 0) - (f.eff.ppa.D[FCS] ?? 0) : -0.2),
      o: was ? f.eff.ppa.O[t] ?? 0 : f?.eff.ppa.O[FCS] ?? -0.1, d: was ? f.eff.ppa.D[t] ?? 0 : f?.eff.ppa.D[FCS] ?? 0.1,
      po: was ? f.eff.ppp.O[t] ?? 0 : f?.eff.ppp.O[FCS] ?? 0, pd: was ? f.eff.ppp.D[t] ?? 0 : f?.eff.ppp.D[FCS] ?? 0,
      ko: was ? f.eff.pace.O[t] ?? 0 : 0, kd: was ? f.eff.pace.D[t] ?? 0 : 0,
      tal: tal[t] ?? -1.5, ret: ret[t] ?? 0 };
  }
  return F;
}
const PRIOR_X = {
  pts: f => [1, f.elo, f.sp, f.net, f.tal, f.ret],
  o: f => [1, f.o, f.tal, f.ret], d: f => [1, f.d, f.tal],
  po: f => [1, f.po, f.tal, f.ret], pd: f => [1, f.pd, f.tal],
  ko: f => [1, f.ko], kd: f => [1, f.kd],
};
function fitPrior(F, final) {
  const ids = Object.keys(F).filter(t => final.mass[t] != null);
  const T = { pts: t => final.mass[t], o: t => final.eff.ppa.O[t], d: t => final.eff.ppa.D[t], po: t => final.eff.ppp.O[t], pd: t => final.eff.ppp.D[t],
    ko: t => final.eff.pace.O[t], kd: t => final.eff.pace.D[t] };
  const W = {};
  for (const [k, x] of Object.entries(PRIOR_X)) { const use = ids.filter(t => T[k](t) != null); W[k] = ols(use.map(t => x(F[t])), use.map(T[k]), 0.5); }
  return W;
}
function applyPrior(F, W) {
  const out = { pts: {}, ppa: { O: {}, D: {} }, ppp: { O: {}, D: {} }, pace: { O: {}, D: {} } };
  for (const [t, f] of Object.entries(F)) {
    out.pts[t] = dot(W.pts, PRIOR_X.pts(f));
    out.ppa.O[t] = dot(W.o, PRIOR_X.o(f)); out.ppa.D[t] = dot(W.d, PRIOR_X.d(f));
    out.ppp.O[t] = dot(W.po, PRIOR_X.po(f)); out.ppp.D[t] = dot(W.pd, PRIOR_X.pd(f));
    out.pace.O[t] = dot(W.ko, PRIOR_X.ko(f)); out.pace.D[t] = dot(W.kd, PRIOR_X.kd(f));
  }
  return out;
}
// season-end state (everything a next-season prior needs)
function finalOf(S, rows, effRows, fbs, prior, P, finals = {}) {
  const done = rows.filter(r => r.S === S && r.done);
  const start = eloStart(S, fbs, prior, finals);
  const elo = eloRun(done, start, P);
  const non = Object.entries(elo).filter(([t]) => t !== 'fcsMean' && !fbs.has(t)).map(([, v]) => v);
  elo.fcsMean = non.length ? mean(non) : 1200;
  const eff = ratingsAt(effRows, 99, prior || {}, { ...P, lam: P.lam });
  const mass = massey(done.map(r => ({ h: fbs.has(r.h) ? r.h : FCS, a: fbs.has(r.a) ? r.a : FCS, m: Math.max(-35, Math.min(35, r.m)), n: r.n })));
  return { elo, eff, mass, fbs };
}

// Elo at the start of a season: FBS teams from the prior (19 Elo a point); everyone else from last season's
// final Elo, regressed a third toward last season's non-FBS average (1200 with no history)
function eloStart(S, fbs, prior, finals) {
  const f = finals[S - 1], st = {};
  if (f) for (const [t, v] of Object.entries(f.elo)) if (t !== 'fcsMean' && !fbs.has(t)) st[t] = f.elo.fcsMean + (v - f.elo.fcsMean) * (2 / 3);
  for (const t of fbs) st[t] = 1500 + 19 * (prior?.pts?.[t] ?? 0);
  st.fcsMean = f ? f.elo.fcsMean : 1200;
  return st;
}

// ---- features and the walk-forward backtest ---------------------------------------------------------
// talent: roster talent z (home minus away). In the backtest it's CFBD's 247 talent composite (transfers
// included; it exists for every season); live, the board's FV team talent (projected starters' expected NFL value)
// stands in on the same z scale. talentLate: the same, from week 5 on, to see whether talent matters more (or the
// market prices it less) once the ratings have settled
const BASE_FEATS = ['elo', 'net', 'home', 'rest', 'tz', 'dist', 'alt', 'fcs', 'talent', 'talentLate', 'st'];
let FEATS = BASE_FEATS;
const TALENT_FCS = -2;   // non-FBS rosters: below every FBS team (the FCS term carries the rest)
function features(r, st, fbs) {
  const id = t => fbs.has(t) ? t : FCS;
  const e = t => st.elo[t] ?? st.elo.fcsMean ?? 1200;
  const net = t => (st.eff.ppa.O[id(t)] ?? 0) - (st.eff.ppa.D[id(t)] ?? 0);
  const tal = t => fbs.has(t) ? st.tal?.[t] ?? 0 : TALENT_FCS, td = tal(r.h) - tal(r.a);
  const x = [(e(r.h) - e(r.a)) / 25, (net(r.h) - net(r.a)) * 65, r.n ? 0 : 1, r.rest, r.tz, r.dist, r.alt, (fbs.has(r.h) ? 1 : 0) - (fbs.has(r.a) ? 1 : 0),
    td, r.w >= 5 ? td : 0, (st.st?.[r.h] ?? 0) - (st.st?.[r.a] ?? 0)];
  return [...x, ...EXTRA.map(k => { if (CAND[k].ctx) return CAND[k].ctx(r, x) * CAND[k].x;
    if (k === 'drv') return st.eff.ex?.drv ? driveMargin(st.eff.ex.drv, id(r.h), id(r.a), r.n ? 0 : 1) : 0;
    const m = st.eff.ex?.[k]; if (!m) return 0; const n = t => exNet(k, m, id(t)); return (n(r.h) - n(r.a)) * CAND[k].x; })];
}
function totalOf(r, st, fbs) {
  const id = t => fbs.has(t) ? t : FCS, { ppp, pace } = st.eff;
  const plays = (o, d, s) => pace.mu + (pace.O[id(o)] ?? 0) + (pace.D[id(d)] ?? 0) + pace.h * s;
  const pp = (o, d, s) => ppp.mu + (ppp.O[id(o)] ?? 0) + (ppp.D[id(d)] ?? 0) + ppp.h * s;
  const s = r.n ? 0 : 1, hp = plays(r.h, r.a, s) * pp(r.h, r.a, s), ap = plays(r.a, r.h, -s) * pp(r.a, r.h, -s);
  return { hp, ap, tot: hp + ap };
}
// walk-forward: every game rated on the weeks before it. Returns one prediction row per game.
function walk(rows, effBy, fbsBy, priors, P, seasons, finals, talBy = {}, stBy = {}, stPrior = {}) {
  const out = [];
  for (const S of seasons) {
    const fbs = fbsBy[S], prior = priors[S];
    const start = eloStart(S, fbs, prior, finals);
    const games = rows.filter(r => r.S === S);
    const weeks = [...new Set(games.map(r => r.w))].sort((a, b) => a - b);
    for (const w of weeks) {
      const before = games.filter(r => r.done && r.w < w);
      const elo = eloRun(before, start, P);
      elo.fcsMean = start.fcsMean;
      const st = { elo, eff: ratingsAt(effBy[S], w, prior, P), tal: talBy[S], st: stAt(stBy[S] || [], w, stPrior[S]) };
      const id = t => fbs.has(t) ? t : FCS;
      for (const r of games.filter(r => r.w === w && r.fbsGame)) out.push({ r, x: features(r, st, fbs), t: totalOf(r, st, fbs),
        sim: SIMTEST && r.done && st.eff.ex?.drv ? simGame(st.eff.ex.drv, id(r.h), id(r.a), r.n ? 0 : 1, 1000, SIMR) : null });
    }
  }
  return out;
}
function score(preds, beta, sigma) {
  const ok = preds.filter(p => p.r.done && p.r.fbsGame);
  let ll = 0, br = 0, ae = 0, n = 0, aeMkt = 0, nm = 0;
  const ats = { all: [0, 0], '0-3': [0, 0], '3-7': [0, 0], '7+': [0, 0] };
  for (const p of ok) {
    const m = dot(beta, [1, ...p.x]), ph = phi(m / sigma), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
    ll -= y * Math.log(Math.max(1e-9, ph)) + (1 - y) * Math.log(Math.max(1e-9, 1 - ph)); br += (ph - y) ** 2; ae += Math.abs(p.r.m - m); n++;
    if (p.r.close != null) {
      aeMkt += Math.abs(p.r.m - p.r.close); nm++;
      const edge = m - p.r.close, cover = p.r.m - p.r.close;
      if (Math.abs(edge) >= 0.5 && cover !== 0) {
        const win = Math.sign(edge) === Math.sign(cover) ? 1 : 0, b = Math.abs(edge) < 3 ? '0-3' : Math.abs(edge) < 7 ? '3-7' : '7+';
        ats.all[0] += win; ats.all[1]++; ats[b][0] += win; ats[b][1]++;
      }
    }
  }
  return { n, logLoss: r3(ll / n), brier: r3(br / n), mae: r2(ae / n), maeMarket: nm ? r2(aeMkt / nm) : null, nMarket: nm,
    maeModelOnMarket: nm ? r2(mean(ok.filter(p => p.r.close != null).map(p => Math.abs(p.r.m - dot(beta, [1, ...p.x]))))) : null,
    ats: Object.fromEntries(Object.entries(ats).map(([k, [w, g]]) => [k, { w, l: g - w, pct: g ? r3(w / g) : null }])) };
}
export function fitBeta(preds) {
  const ok = preds.filter(p => p.r.done && p.r.fbsGame);
  // no intercept: home field lives in the home term, and which team is listed as home at a neutral site is arbitrary
  const beta = [0, ...ols(ok.map(p => p.x), ok.map(p => Math.max(-45, Math.min(45, p.r.m))), 1, 0)];
  const res = ok.map(p => p.r.m - dot(beta, [1, ...p.x])), sigmaMargin = sd(res);
  // win and cover chances: the normal's sd fit to the results themselves (log loss on who won), not the margins'
  // spread, which blowouts widen (fat tails), leaving close games under-confident
  const lw = s => ok.reduce((a, p) => { const q = Math.min(1 - 1e-9, Math.max(1e-9, phi(dot(beta, [1, ...p.x]) / s))), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
    return a - y * Math.log(q) - (1 - y) * Math.log(1 - q); }, 0);
  let sigma = sigmaMargin;
  for (let f = 0.5; f <= 1.2001; f += 0.02) if (lw(sigmaMargin * f) < lw(sigma)) sigma = sigmaMargin * f;
  return { beta, sigma, sigmaMargin };
}

// ---- weather (Open-Meteo) ------------------------------------------------------------------------------
// historical (archive) for played games, forecast for the coming week; kickoff hour at the venue
export async function weather(rows, cache = {}, forecast = false) {
  const need = rows.filter(r => !r.dome && r.lat != null && cache[r.id] == null && (forecast ? !r.done : r.done) &&
    (forecast ? new Date(r.date) - Date.now() < 15 * 864e5 : Date.now() - new Date(r.date) > 6 * 864e5));
  const byDay = {};
  for (const r of need) (byDay[r.date.slice(0, 10)] ||= []).push(r);
  for (const [day, list] of Object.entries(byDay)) for (let i = 0; i < list.length; i += 60) {
    const part = list.slice(i, i + 60);
    const q = `latitude=${part.map(r => r.lat.toFixed(3)).join(',')}&longitude=${part.map(r => r.lon.toFixed(3)).join(',')}` +
      `&start_date=${day}&end_date=${new Date(Date.parse(day) + 864e5).toISOString().slice(0, 10)}&hourly=temperature_2m,wind_speed_10m,precipitation` +
      `&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=GMT`;
    try {
      const res = await fetch(`https://${forecast ? 'api' : 'archive-api'}.open-meteo.com/v1/${forecast ? 'forecast' : 'archive'}?${q}`);
      if (!res.ok) continue;
      let d = await res.json(); if (!Array.isArray(d)) d = [d];
      part.forEach((r, j) => {
        const h = d[j]?.hourly; if (!h) return;
        const k = h.time.indexOf(r.date.slice(0, 13) + ':00'); if (k < 0) return;
        const win = [k, k + 1, k + 2].filter(x => x < h.time.length);
        cache[r.id] = { t: r1(mean(win.map(x => h.temperature_2m[x]))), w: r1(mean(win.map(x => h.wind_speed_10m[x]))), p: r1(win.reduce((a, x) => a + (h.precipitation[x] || 0), 0)) };
      });
    } catch {}
  }
  return cache;
}
const WX = w => w ? [Math.max(0, w.w - 10), w.p > 2 ? 1 : 0, w.t < 35 ? 1 : 0] : [0, 0, 0];
function fitTotals(preds, wx) {
  const ok = preds.filter(p => p.r.done && p.r.fbsGame && p.t.tot > 0 && isFinite(p.t.tot));
  const x = p => [1, p.t.tot, ...WX(p.r.dome ? null : wx[p.r.id])];
  const b = ols(ok.map(x), ok.map(p => p.r.tot), 1);
  const res = ok.map(p => p.r.tot - dot(b, x(p)));
  const mk = ok.filter(p => p.r.closeTot != null);
  return { b, sigma: sd(res), mae: r2(mean(res.map(Math.abs))), maeMarket: mk.length ? r2(mean(mk.map(p => Math.abs(p.r.tot - p.r.closeTot)))) : null,
    ou: (() => { let w = 0, n = 0; for (const p of mk) { const e = dot(b, x(p)) - p.r.closeTot, c = p.r.tot - p.r.closeTot; if (Math.abs(e) >= 1 && c) { n++; if (Math.sign(e) === Math.sign(c)) w++; } } return { w, l: n - w, pct: n ? r3(w / n) : null }; })() };
}

// ---- QB: starter vs backup ------------------------------------------------------------------------------
// EPA per play shrunk toward replacement (-0.05) by 150 plays; a starter out costs the difference x 38 plays
const QB = { k: 150, repl: -0.05, plays: 38 };
export function qbTable(ppaqb, nameId) {
  const T = {};
  for (const q of ppaqb || []) {
    const t = nameId[q.team]; const avg = q.averagePPA?.all, tot = q.totalPPA?.all;
    if (!t || !avg || tot == null) continue;
    const n = Math.max(0, Math.round(tot / avg));
    (T[t] ||= []).push({ name: q.name, plays: n, val: (tot + QB.k * QB.repl) / (n + QB.k) });
  }
  for (const list of Object.values(T)) list.sort((a, b) => b.plays - a.plays);
  return T;
}

// ---- season simulation -----------------------------------------------------------------------------------
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function gauss(R) { let u = 0, v = 0; while (!u) u = R(); while (!v) v = R(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
// conference title game: the top two by conference record (ties: the stronger team in that simulation);
// playoff: 12 teams, the five best-ranked conference champions plus seven at-large, ranked by losses then
// strength (a stand-in for the committee); bowl eligible at six wins
function simulate(rows, predict, fbs, conf, ratingNow, sigma, N = 10000, uncert = 4) {
  const R = rng(20261008);
  const S = rows[0]?.S, season = rows.filter(r => r.S === S && r.w < 20);
  const done = season.filter(r => r.done), left = season.filter(r => !r.done);
  const teams = [...fbs], base = {}, cbase = {};
  for (const t of teams) { base[t] = { w: 0, l: 0 }; cbase[t] = { w: 0, l: 0 }; }
  for (const r of done) for (const [t, won] of [[r.h, r.m > 0], [r.a, r.m < 0]]) if (base[t]) { base[t][won ? 'w' : 'l']++; if (r.conf) cbase[t][won ? 'w' : 'l']++; }
  const mu = left.map(r => predict(r));
  const acc = Object.fromEntries(teams.map(t => [t, { w: 0, ccg: 0, title: 0, cfp: 0, bowl: 0, wins: Array(16).fill(0) }]));
  const confs = {}; for (const t of teams) if (conf[t] && !/independent/i.test(conf[t])) (confs[conf[t]] ||= []).push(t);
  for (let s = 0; s < N; s++) {
    const shock = {}; for (const t of teams) shock[t] = gauss(R) * uncert;
    const W = {}, C = {};
    for (const t of teams) { W[t] = { ...base[t] }; C[t] = { ...cbase[t] }; }
    left.forEach((r, i) => {
      const m = mu[i] + (shock[r.h] ?? 0) - (shock[r.a] ?? 0) + gauss(R) * sigma, hw = m > 0;
      if (W[r.h]) W[r.h][hw ? 'w' : 'l']++; if (W[r.a]) W[r.a][hw ? 'l' : 'w']++;
      if (r.conf) { if (C[r.h]) C[r.h][hw ? 'w' : 'l']++; if (C[r.a]) C[r.a][hw ? 'l' : 'w']++; }
    });
    const str = t => (ratingNow[t] ?? 0) + shock[t];
    const champs = [];
    for (const list of Object.values(confs)) {
      const pct = t => C[t].w / Math.max(1, C[t].w + C[t].l);
      const [a, b] = [...list].sort((x, y) => pct(y) - pct(x) || str(y) - str(x));
      if (!b) continue;
      acc[a].ccg++; acc[b].ccg++;
      const m = str(a) - str(b) + gauss(R) * sigma, win = m > 0 ? a : b, lose = win === a ? b : a;
      W[win].w++; W[lose].l++; acc[win].title++; champs.push(win);
    }
    const resume = t => -W[t].l * 6 + str(t) * 0.5 + (champs.includes(t) ? 3 : 0);
    const auto = [...champs].sort((x, y) => resume(y) - resume(x)).slice(0, 5);
    const field = new Set(auto);
    for (const t of [...teams].sort((x, y) => resume(y) - resume(x))) { if (field.size >= 12) break; field.add(t); }
    for (const t of teams) {
      const regW = W[t].w - (champs.includes(t) ? 1 : 0);
      acc[t].w += regW; acc[t].wins[Math.min(15, regW)]++;
      if (field.has(t)) acc[t].cfp++;
      if (regW >= 6) acc[t].bowl++;
    }
  }
  return teams.map(t => ({ tid: t, rec: `${base[t].w}-${base[t].l}`, conf: conf[t] || null, projW: r1(acc[t].w / N),
    ccg: r3(acc[t].ccg / N), title: r3(acc[t].title / N), cfp: r3(acc[t].cfp / N), bowl: r3(acc[t].bowl / N),
    left: left.filter(r => r.h === t || r.a === t).length }));
}

// ---- the whole model ----------------------------------------------------------------------------------------
// data: { games, adv, lines, sp, talent, returning } keyed by season (CFBD shapes), venues, teamsFbs, ppaqb,
// weather (cache object, filled in place). Returns { report, predict(espnGame), sim, ratings }.
export async function runModel(data, SEASON, opts = {}) {
  const seasons = [SEASON - 2, SEASON - 1, SEASON].filter(S => data.games[S]?.length);
  const nameId = {};
  for (const S of seasons) for (const g of data.games[S]) { nameId[g.homeTeam] = String(g.homeId); nameId[g.awayTeam] = String(g.awayId); }
  for (const S of seasons) for (const g of data.games[S]) { g.homeId = String(g.homeId); g.awayId = String(g.awayId); }
  const fbsBy = {};
  for (const S of seasons) {
    fbsBy[S] = new Set();
    for (const g of data.games[S]) { if (g.homeClassification === 'fbs') fbsBy[S].add(g.homeId); if (g.awayClassification === 'fbs') fbsBy[S].add(g.awayId); }
  }
  const allGames = seasons.flatMap(S => data.games[S]);
  const geo = places(data.venues, data.teamsFbs, allGames);
  const rows = prepare(seasons, data, geo);
  const gameById = Object.fromEntries(rows.map(r => [r.id, r]));
  // the candidate inputs (CAND) are chosen below, after the hyperparameters; until then the base model only
  EXTRA = []; FEATS = BASE_FEATS;
  const effBy = Object.fromEntries(seasons.map(S => [S, effObs(data.adv[S], nameId, gameById, fbsBy[S], rzByGame(data.drives?.[S]), data.sit?.[S])]));
  for (const S of seasons) decisions(effBy[S]);
  // special teams by season, each season's prior half of the last one's full-season rating
  const allDrives = seasons.flatMap(S => data.drives?.[S] || []);
  const stC = allDrives.length ? stCurves(allDrives) : null;
  const stBy = {}, stPrior = {};
  for (const S of seasons) {
    stBy[S] = stC ? stObs(data.drives?.[S], nameId, gameById, fbsBy[S], stC) : [];
    const last = stBy[S - 1] ? stAt(stBy[S - 1], 99) : {};
    stPrior[S] = Object.fromEntries(Object.entries(last).map(([t, v]) => [t, ST.carry * v]));
  }
  // roster talent z across FBS by season (CFBD 247 composite)
  const talBy = {};
  for (const S of seasons) {
    const list = (data.talent?.[S] || []).map(x => [nameId[x.team], x.talent]).filter(([t, v]) => t && fbsBy[S].has(t) && v != null);
    const m = mean(list.map(x => x[1])), s0 = sd(list.map(x => x[1]));
    talBy[S] = Object.fromEntries(list.map(([t, v]) => [t, (v - m) / s0]));
  }

  // priors: the first season starts from nothing (SP+-free, regressed Elo only); then each season's prior
  // weights are fit on the season before (features from two seasons back), so the test season stays clean
  const P0 = { k: 20, eloHome: 55, lam: 3 };
  const [S0, S1] = seasons;
  const finals = {}, priors = {}, W = {};
  priors[S0] = { pts: {}, ppa: {}, ppp: {}, pace: {} };
  finals[S0] = finalOf(S0, rows, effBy[S0], fbsBy[S0], null, P0);
  const F1 = priorFeatures(S1, data, fbsBy[S1], nameId, finals);
  finals[S1] = finalOf(S1, rows, effBy[S1], fbsBy[S1], null, P0, finals);
  W[S1] = fitPrior(F1, finals[S1]);                    // fit on S1 itself: S1's own backtest is in-sample for the prior
  priors[S1] = applyPrior(F1, W[S1]);
  const mass1 = finals[S1].mass;
  finals[S1] = { ...finalOf(S1, rows, effBy[S1], fbsBy[S1], priors[S1], P0, finals), mass: mass1 };   // with the prior: next season's features
  const evalS = seasons.filter(S => S > S0);
  if (data.games[SEASON]?.length && SEASON > S1) {
    const F2 = priorFeatures(SEASON, data, fbsBy[SEASON], nameId, finals);
    priors[SEASON] = applyPrior(F2, W[S1]);           // out of sample: weights from S1
  }

  // hyperparameters: grid on the training season (S1), each a full walk-forward run
  const grid = [];
  for (const k of [15, 20, 25, 30, 40]) for (const eloHome of [40, 55, 70]) for (const lam of [0.75, 1.5, 3, 6]) grid.push({ k, eloHome, lam });
  let best = null;
  for (const P of opts.P ? [opts.P] : grid) {
    const pr = walk(rows, effBy, fbsBy, priors, P, [S1], finals, talBy, stBy, stPrior);
    const { beta, sigma } = fitBeta(pr), sc = score(pr, beta, sigma);
    if (!best || sc.logLoss < best.sc.logLoss) best = { P, sc, beta, sigma };
  }
  const P = best.P;
  // weather for played games (archive), before the candidates: the weather squeeze is one
  const wx = data.weather || {};
  await weather(rows.filter(r => r.S >= S1), wx, false);
  WXM = wx; RET = data.pfnRet || {};
  // candidate inputs: one walk-forward run per season with every candidate, then forward selection on season-swap
  // cross-validation (fit the margin weights on one season, score the other's winners, both ways). Each round adds
  // the candidate that lowers the pooled out-of-sample log loss most, if it lowers it by 1.5 standard errors or more
  // of the per-game difference (paired) and every kept input still carries a positive weight (more success is never
  // worse: a negative weight is two overlapping stats splitting one signal); the rest are reported, not used.
  // Play-by-play candidates need plays both seasons.
  const pool = Object.keys(CAND).filter(k => (!CAND[k].pbp || [S1, SEASON].every(S => Object.keys(data.sit?.[S] || {}).length)) &&
    (!['qbRet', 'ret', 'avRet', 'avRest'].includes(k) || [S1, SEASON].every(S => Object.keys(RET[S] || {}).length)));
  let extraTest = null;
  if (opts.extra) EXTRA = opts.extra;
  else if (SEASON > S1) {
    EXTRA = pool; FEATS = [...BASE_FEATS, ...EXTRA]; SIMTEST = true; SIMR = rng(7);
    const A = walk(rows, effBy, fbsBy, priors, P, [S1], finals, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
    const B = walk(rows, effBy, fbsBy, priors, P, [SEASON], finals, talBy, stBy, stPrior).filter(p => p.r.done && p.r.fbsGame);
    SIMTEST = false;
    const nb = BASE_FEATS.length, col = k => nb + pool.indexOf(k);
    const losses = keys => {     // per-game out-of-sample log loss and absolute miss, both folds
      const cols = [...BASE_FEATS.map((_, i) => i), ...keys.map(col)], sub = ps => ps.map(p => ({ r: p.r, x: cols.map(i => p.x[i]) }));
      const out = [];
      for (const [fit, on] of [[A, B], [B, A]]) {
        const { beta, sigma } = fitBeta(sub(fit));
        for (const p of sub(on)) {
          const m = dot(beta, [1, ...p.x]), ph = Math.min(1 - 1e-9, Math.max(1e-9, phi(m / sigma))), y = p.r.m > 0 ? 1 : p.r.m < 0 ? 0 : 0.5;
          out.push({ ll: -(y * Math.log(ph) + (1 - y) * Math.log(1 - ph)), ae: Math.abs(p.r.m - m), ph, y, m, sigma, close: p.r.close, res: p.r.m });
        }
      }
      return out;
    };
    const cmp = (keys, ref) => {
      const a = losses(keys), b = ref, d = a.map((x, i) => x.ll - b[i].ll), dm = mean(d), se = sd(d) / Math.sqrt(d.length);
      const cols = [...BASE_FEATS.map((_, i) => i), ...keys.map(col)], w = fitBeta([...A, ...B].map(p => ({ r: p.r, x: cols.map(i => p.x[i]) }))).beta.slice(1 + nb);
      return { a, logLoss: mean(a.map(x => x.ll)), dLogLoss: dm, t: dm / se, dMae: mean(a.map(x => x.ae)) - mean(b.map(x => x.ae)), pos: w.every((v, i) => v * (CAND[keys[i]].sign ?? 1) > 0) };
    };
    const base = losses([]);
    const alone = Object.fromEntries(pool.map(k => { const c = cmp([k], base); return [k, { name: CAND[k].name, dLogLoss: Math.round(c.dLogLoss * 1e5) / 1e5, t: r2(c.t), dMae: r2(c.dMae) }]; }));
    const chosen = [], steps = [];
    let ref = base;
    for (;;) {
      const tries = pool.filter(k => !chosen.includes(k)).map(k => ({ k, ...cmp([...chosen, k], ref) })).filter(x => x.pos).sort((u, v) => u.dLogLoss - v.dLogLoss);
      const b = tries[0];
      if (!b || b.t > -1.5) { if (b) steps.push({ add: null, best: b.k, dLogLoss: Math.round(b.dLogLoss * 1e5) / 1e5, t: r2(b.t) }); break; }
      chosen.push(b.k); ref = b.a; steps.push({ add: b.k, logLoss: Math.round(b.logLoss * 1e4) / 1e4, dLogLoss: Math.round(b.dLogLoss * 1e5) / 1e5, t: r2(b.t), dMae: r2(b.dMae) });
    }
    EXTRA = chosen;
    // the chosen model against the previous live one (4th-down aggressiveness), the market and a blend, on the same CV
    // predictions; calibration in tenths of win probability
    const r4 = x => Math.round(x * 1e4) / 1e4, ll = (p, y) => { p = Math.min(1 - 1e-9, Math.max(1e-9, p)); return -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); };
    const PREV = ['aggr'].filter(k => pool.includes(k)), prev = PREV.length ? cmp(PREV, base) : null, fin = cmp(chosen, prev ? prev.a : base);
    const mk = ref.filter(x => x.close != null), sM = sd(mk.map(x => x.res - x.close));
    const blendLL = a => mean(mk.map(x => ll(phi((a * x.m + (1 - a) * x.close) / (a * x.sigma + (1 - a) * sM)), x.y)));
    let bestA = 0; for (let a = 0; a <= 1.0001; a += 0.05) if (blendLL(a) < blendLL(bestA)) bestA = a;
    // the drive simulation against the model, same CV games (losses() lists B's games, then A's): its win chance
    // alone, and blended with the model's at a weight fit on one season and scored on the other; totals: the
    // simulation's mean against the totals model's raw projection (plays x points per play), MAE
    const simOf = [...B, ...A].map(p => p.sim), simTest = (() => {
      const xs = ref.map((x, i) => ({ ...x, sp: simOf[i]?.p, st: simOf[i]?.tot, tt: [...B, ...A][i].t?.tot, tot: [...B, ...A][i].r.tot })).filter(x => x.sp != null);
      if (xs.length < 100) return null;
      const nB = B.filter(p => p.sim).length, fold = [xs.slice(0, nB), xs.slice(nB)];
      const bl = (set, a) => mean(set.map(x => ll(a * x.ph + (1 - a) * x.sp, x.y)));
      const best = set => { let b = 1; for (let a = 0; a <= 1.0001; a += 0.05) if (bl(set, a) < bl(set, b)) b = a; return b; };
      const wA = best(fold[1]), wB = best(fold[0]);                  // fit on one season, score the other
      const cv = [...fold[0].map(x => ll(wA * x.ph + (1 - wA) * x.sp, x.y)), ...fold[1].map(x => ll(wB * x.ph + (1 - wB) * x.sp, x.y))];
      const d = cv.map((v, i) => v - [...fold[0], ...fold[1]][i].ll);
      const tm = xs.filter(x => x.tot != null && x.st != null && x.tt > 0);
      return { n: xs.length, sim: r4(mean(xs.map(x => ll(x.sp, x.y)))), model: r4(mean(xs.map(x => x.ll))), blend: r4(mean(cv)), w: [r2(wA), r2(wB)],
        dBlend: r4(mean(d)), t: r2(mean(d) / (sd(d) / Math.sqrt(d.length))), simAcc: r3(mean(xs.filter(x => x.y !== 0.5).map(x => (x.sp > 0.5) === (x.y === 1) ? 1 : 0))),
        totMaeSim: r2(mean(tm.map(x => Math.abs(x.tot - x.st)))), totMaeModel: r2(mean(tm.map(x => Math.abs(x.tot - x.tt)))), sdSim: r1(mean(simOf.filter(Boolean).map(x => x.sd))) };
    })();
    const calib = Array.from({ length: 10 }, (_, i) => { const xs = ref.filter(x => Math.min(9, Math.floor(x.ph * 10)) === i);
      return { bin: `${i * 10}-${i * 10 + 10}%`, n: xs.length, pred: xs.length ? r3(mean(xs.map(x => x.ph))) : null, won: xs.length ? r3(mean(xs.map(x => x.y))) : null }; });
    extraTest = { n: base.length, folds: [S1, SEASON], baseLogLoss: r4(mean(base.map(x => x.ll))), baseMae: r2(mean(base.map(x => x.ae))), alone, steps, chosen,
      prev: prev ? { keys: PREV, logLoss: r4(prev.logLoss), mae: r2(mean(prev.a.map(x => x.ae))) } : null,
      final: { acc: r3(mean(ref.filter(x => x.y !== 0.5).map(x => (x.m > 0) === (x.y === 1) ? 1 : 0))), logLoss: r4(mean(ref.map(x => x.ll))), mae: r2(mean(ref.map(x => x.ae))), brier: r4(mean(ref.map(x => (x.ph - x.y) ** 2))), vsPrev: prev ? { d: r4(fin.dLogLoss), t: r2(fin.t) } : null },
      market: { n: mk.length, accModel: r3(mean(mk.filter(x => x.y !== 0.5).map(x => (x.m > 0) === (x.y === 1) ? 1 : 0))),
        accClose: r3(mean(mk.filter(x => x.y !== 0.5 && x.close !== 0).map(x => (x.close > 0) === (x.y === 1) ? 1 : 0))), model: r4(mean(mk.map(x => x.ll))), close: r4(mean(mk.map(x => ll(phi(x.close / sM), x.y)))), blend: r4(blendLL(bestA)), blendW: r2(bestA),
        maeModel: r2(mean(mk.map(x => x.ae))), maeClose: r2(mean(mk.map(x => Math.abs(x.res - x.close)))) },
      calib, simTest };
  } else EXTRA = ['sr'];
  FEATS = [...BASE_FEATS, ...EXTRA];
  const train = walk(rows, effBy, fbsBy, priors, P, [S1], finals, talBy, stBy, stPrior), fitTr = fitBeta(train);
  const test = SEASON > S1 ? walk(rows, effBy, fbsBy, priors, P, [SEASON], finals, talBy, stBy, stPrior) : [];
  const all = [...train, ...test], fitAll = fitBeta(all);
  // baseline for the report: Elo alone (with home field), fit the same way
  const eloOnly = preds => { const ok = preds.filter(p => p.r.done && p.r.fbsGame), b = ols(ok.map(p => [p.x[0], p.x[2], p.x[7]]), ok.map(p => p.r.m), 1, 0);
    const beta = [0, ...FEATS.map(() => 0)]; beta[1] = b[0]; beta[3] = b[1]; beta[8] = b[2]; const res = ok.map(p => p.r.m - dot(beta, [1, ...p.x])); return { beta, sigma: sd(res) }; };
  const eTr = eloOnly(train);

  // weather and totals
  const totTr = fitTotals(train, wx), totAll = fitTotals(all, wx);

  // the current state, for live predictions and the season sim
  const fbs = fbsBy[SEASON] || fbsBy[S1], prior = priors[SEASON] || priors[S1];
  const cur = rows.filter(r => r.S === SEASON);
  const start = eloStart(SEASON, fbs, prior, finals);
  const elo = eloRun(cur.filter(r => r.done), start, P); elo.fcsMean = start.fcsMean;
  DRIVES = true;     // drive rates for the live drive simulation, whatever the selection kept
  // live talent: the board's FV team talent (opts.talentZ, z across FBS) where there is one, else the composite
  const st = { elo, eff: ratingsAt(effBy[SEASON] || [], 99, prior, P), tal: { ...talBy[SEASON], ...(opts.talentZ || {}) },
    st: stAt(stBy[SEASON] || [], 99, stPrior[SEASON]) };
  await weather(cur, wx, true);
  const { beta, sigma } = fitAll;
  const mOf = r => dot(beta, [1, ...features(r, st, fbs)]);
  const tOf = r => { const t = totalOf(r, st, fbs); return dot(totAll.b, [1, t.tot, ...WX(r.dome ? null : wx[r.id])]); };
  // a neutral-field rating in points, for display and the sim's tiebreaks
  const rating = {};
  const late = Math.min(99, ...cur.filter(r => !r.done).map(r => r.w)) >= 5;   // the coming week counts as late
  for (const t of fbs) rating[t] = beta[1] * ((elo[t] ?? 1500) - 1500) / 25 + beta[2] * 65 * ((st.eff.ppa.O[t] ?? 0) - (st.eff.ppa.D[t] ?? 0))
    + (beta[9] + (late ? beta[10] : 0)) * (st.tal[t] ?? 0) + beta[11] * (st.st[t] ?? 0)
    + EXTRA.reduce((a, k, i) => { if (k === 'drv') return a + (st.eff.ex?.drv ? beta[12 + i] * driveMargin(st.eff.ex.drv, t, '-', 0) : 0); if (CAND[k].team) return a + beta[12 + i] * CAND[k].team(SEASON, t) * CAND[k].x; const m = !CAND[k].ctx && st.eff.ex?.[k]; return a + (m ? beta[12 + i] * exNet(k, m, t) * CAND[k].x : 0); }, 0);
  // situational profile for the ratings table, in or out of the model: each candidate's opponent-adjusted offense
  // and defense (rates as fractions, red-zone points per trip as points), neutral field
  const prof = ratingsAt(effBy[SEASON] || [], 99, prior, P, pool), situ = {};
  for (const t of fbs) situ[t] = Object.fromEntries(Object.entries(prof.ex).filter(([k]) => ['sr', 'ed', 'td', 'rzsr', 'rz'].includes(k))
    .map(([k, m]) => [k, { o: r3(m.mu + (m.O[t] ?? 0)), d: r3(m.mu + (m.D[t] ?? 0)) }]));
  // coach traits this season, raw (decisions are the team's own): 4th-down go rate and pass rate, actual and over
  // the league's rate in the same situations
  const coach = {};
  for (const r of effBy[SEASON] || []) if (r.t !== FCS) {
    const c = (coach[r.t] ||= { f4n: 0, f4go: 0, f4x: 0, pn: 0, pass: 0, passX: 0 });
    for (const k of Object.keys(c)) c[k] += r[k] || 0;
  }
  for (const c of Object.values(coach)) Object.assign(c, { go: c.f4n ? r3(c.f4go / c.f4n) : null, goOe: c.f4n ? r3((c.f4go - c.f4x) / c.f4n) : null,
    passR: c.pn ? r3(c.pass / c.pn) : null, proe: c.pn ? r3((c.pass - c.passX) / c.pn) : null });
  const confOf = Object.fromEntries((data.teamsFbs || []).map(t => [String(t.id), t.conference]));
  const sim = opts.sim === false ? [] : simulate(cur, mOf, fbs, confOf, rating, sigma, opts.sims || 10000);
  const byId = Object.fromEntries(cur.map(r => [String(r.id), r]));
  const qb = qbTable(data.ppaqb, nameId);
  const names = {}; for (const r of cur) { names[r.h] = r.hn; names[r.a] = r.an; }

  const parts = r => { const x = features(r, st, fbs), o = Object.fromEntries(FEATS.map((f, i) => [f, r1(beta[i + 1] * x[i])]));
    o.talent = r1(o.talent + o.talentLate); delete o.talentLate; return o; };
  const report = {
    seasons: { train: S1, test: SEASON > S1 ? SEASON : null }, params: { ...P, sigma: r1(sigma), sigmaMargin: r1(fitAll.sigmaMargin), totalSigma: r1(totAll.sigma) },
    beta: Object.fromEntries(FEATS.map((f, i) => [f, r3(fitAll.beta[i + 1])])),
    prior: Object.fromEntries(Object.entries(W[S1]).map(([k, w]) => [k, w.map(r3)])), priorX: ['1', 'elo', 'sp', 'net', 'talent', 'returning'],
    train: score(train, fitTr.beta, fitTr.sigma), test: test.length ? score(test, fitTr.beta, fitTr.sigma) : null,
    eloOnly: { train: score(train, eTr.beta, eTr.sigma), test: test.length ? score(test, eTr.beta, eTr.sigma) : null },
    totals: { train: { mae: totTr.mae, maeMarket: totTr.maeMarket, ou: totTr.ou }, all: { mae: totAll.mae, maeMarket: totAll.maeMarket, ou: totAll.ou },
      b: totAll.b.map(r3), x: ['1', 'pace x pts/play', 'wind over 10 mph', 'rain', 'below 35F'] },
    talentLive: opts.talentZ ? 'fv' : 'composite',
    st: stC ? { fg: [r3(stC.fgA), r3(stC.fgB)], fg40: r3(stC.fg(40)), fg50: r3(stC.fg(50)), ko: r1(stC.ko), games: Object.values(stBy).reduce((a, x) => a + x.length, 0) / 2 } : null,
    weatherGames: Object.keys(wx).length, extra: EXTRA, extraTest,
    grid: grid.length,
  };
  return {
    report, sigma, rating, situ, coach, sim, names, qb, elo, eff: st.eff, st: st.st, stBeta: beta[11],
    units: stC ? stUnits(data.drives?.[SEASON], stC) : {}, _debug: { train, test, fitTr, fitAll, priors, finals, eTr },
    // one coming game (CFBD/ESPN id): margin (home), total, projected score, situational parts, weather
    predict(id) {
      const r = byId[String(id)]; if (!r) return null;
      const m = mOf(r), tot = tOf(r);
      const fid = t => fbs.has(t) ? t : FCS, dv = st.eff.ex?.drv ? simGame(st.eff.ex.drv, fid(r.h), fid(r.a), r.n ? 0 : 1, 5000, rng(+r.id || 1)) : null;
      // ranges from the drive simulation's shape (scoring comes in 3s and 7s), centred on the model's margin and total:
      // the simulation alone predicts worse than the model (it has no prior, Elo or talent), so it sets the spread only
      const sim = dv ? { m10: Math.round(m + dv.m10 - dv.mean), m90: Math.round(m + dv.m90 - dv.mean), t10: Math.round(tot + dv.t10 - dv.tot),
        t90: Math.round(tot + dv.t90 - dv.tot), pRaw: r3(dv.p) } : null;
      return { margin: m, total: tot, home: (tot + m) / 2, away: (tot - m) / 2, parts: parts(r), wx: r.dome ? { dome: true } : wx[r.id] || null, sim };
    },
  };
}
export { half };
