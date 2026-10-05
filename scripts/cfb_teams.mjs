// Team-level models for the College Football ARKBOARD, fed by scripts/fetch_cfb.mjs:
//   Elo        results-based team ratings from this season's games (ESPN scoreboard)
//   Talent     each team's projected starting 22 from our player grades, as expected NFL value
//   TvE        talent vs Elo: results above or below what the roster's talent predicts
//   NIL+       results per NIL dollar (On3 valuations), 100 = average, like OPS+
//   Staff      head coaches credited with team results, coordinators with their side's
//              position groups: production above talent, and development since high school
//   Mock       a 2027 mock draft: Tankathon's order and needs, our draft-eligible grades
const SEASON = 2026;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const zs = xs => { const m = mean(xs), s = sd(xs); return xs.map(x => (x - m) / s); };
const r1 = x => Math.round(x * 10) / 10, r2 = x => Math.round(x * 100) / 100;
// inverse normal CDF (Acklam)
function probit(p) {
  p = Math.min(Math.max(p, 1e-4), 1 - 1e-4);
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  if (p < 0.02425) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  if (p > 0.97575) { const q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1); }
  const q = p - 0.5, r = q * q;
  return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
}

export const STARTERS = { QB: 1, RB: 1, WR: 3, TE: 1, OL: 5, EDGE: 2, DL: 2, LB: 2, CB: 3, S: 2 };
const OFFENSE = ['QB', 'RB', 'WR', 'TE', 'OL'], DEFENSE = ['EDGE', 'DL', 'LB', 'CB', 'S'];

// expected NFL value per season by FV: mean AV per season active, by tier, measured on the 2010-19
// drafts (nflverse): 80 -> 8.5, 60 -> 5.0, 50 -> 3.7, 40 -> 1.7, 30 -> 0.4; in between, linear
const AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [70, 6.6], [80, 8.5]];
export function avOf(fv) {
  if (fv == null) return 0;
  for (let i = 1; i < AV_BY_FV.length; i++) {
    const [f0, a0] = AV_BY_FV[i - 1], [f1, a1] = AV_BY_FV[i];
    if (fv <= f1) return a0 + (a1 - a0) * Math.max(0, fv - f0) / (f1 - f0);
  }
  return AV_BY_FV.at(-1)[1];
}

// ---- games and Elo -----------------------------------------------------------------------------
export async function fetchGames() {
  const games = [];
  for (let wk = 1; wk <= 16; wk++) {
    const u = `https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=${SEASON}&seasontype=2&week=${wk}&groups=80&limit=400`;
    let d = null;
    for (let i = 0; i < 4 && !d; i++) {
      try { const r = await fetch(u, { headers: { 'user-agent': UA } }); if (r.ok) d = await r.json(); } catch {}
      if (!d) await sleep(1500 * 2 ** i);
    }
    for (const e of d?.events || []) {
      const c = e.competitions?.[0];
      if (!c?.status?.type?.completed) continue;
      const h = c.competitors.find(t => t.homeAway === 'home'), a = c.competitors.find(t => t.homeAway === 'away');
      games.push({ id: e.id, week: wk, date: e.date, neutral: !!c.neutralSite,
        home: h.team.id, away: a.team.id, homeName: h.team.location, awayName: a.team.location, hs: +h.score, as: +a.score });
    }
    await sleep(200);
  }
  const seen = new Set();
  return games.filter(g => !seen.has(g.id) && seen.add(g.id)).sort((x, y) => x.date.localeCompare(y.date));
}

// FiveThirtyEight-style Elo: K 25, home field 55, margin multiplier ln(|MOV|+1) * 2.2 / (0.001 * winner
// Elo edge + 2.2) so blowouts by favourites count less. FBS teams start at 1500 (results only, no
// talent prior, so TvE stays independent); non-FBS opponents start at 1200.
const ELO = { k: 25, home: 55, fbs: 1500, other: 1200 };
export function elo(games, fbsIds) {
  const r = {}, rec = {};
  const get = id => (r[id] ??= fbsIds.has(id) ? ELO.fbs : ELO.other);
  for (const g of games) {
    const hr = get(g.home) + (g.neutral ? 0 : ELO.home), ar = get(g.away);
    const exp = 1 / (1 + 10 ** ((ar - hr) / 400)), res = g.hs > g.as ? 1 : g.hs < g.as ? 0 : 0.5;
    const mov = Math.abs(g.hs - g.as), edge = res === 1 ? hr - ar : ar - hr;
    const mult = Math.log(mov + 1) * 2.2 / (0.001 * edge + 2.2);
    const shift = ELO.k * mult * (res - exp);
    r[g.home] += shift; r[g.away] -= shift;
    for (const [id, w] of [[g.home, res], [g.away, 1 - res]]) {
      const x = (rec[id] ??= { w: 0, l: 0, pf: 0, pa: 0 });
      if (w === 1) x.w++; else if (w === 0) x.l++;
      x.pf += id === g.home ? g.hs : g.as; x.pa += id === g.home ? g.as : g.hs;
    }
  }
  return { rating: r, record: rec };
}

// ---- teams: talent, Elo, TvE, NIL+ ---------------------------------------------------------------
// rows: every graded player (fetch_cfb.mjs build().all); teams: ESPN team map; fbsIds: Set of ids
export function teamModels(rows, teams, games, fbsIds) {
  const byTeam = {};
  for (const p of rows) if (p.tid && fbsIds.has(p.tid)) (byTeam[p.tid] ||= []).push(p);
  const { rating, record } = elo(games, fbsIds);
  const out = [];
  for (const [tid, ps] of Object.entries(byTeam)) {
    // projected starting 22: the best grades at each spot
    const starters = [];
    for (const [g, n] of Object.entries(STARTERS)) {
      starters.push(...ps.filter(p => p.pos === g && p.fv != null).sort((a, b) => b.fv - a.fv || b.comp - a.comp).slice(0, n));
    }
    const side = list => r1(list.reduce((a, p) => a + avOf(p.fv), 0));
    const t = teams[tid] || {};
    const nil = ps.reduce((a, p) => a + (p.nil || 0), 0);
    out.push({
      tid, team: t.name, full: t.full, logo: ps.find(p => p.logo)?.logo || t.logo, color: t.color ? `#${t.color}` : null,
      conf: mode(ps.map(p => p.conf).filter(Boolean)),
      talent: side(starters), off: side(starters.filter(p => OFFENSE.includes(p.pos))), def: side(starters.filter(p => DEFENSE.includes(p.pos))),
      n50: ps.filter(p => (p.fv ?? 0) >= 50).length, n60: ps.filter(p => (p.fv ?? 0) >= 60).length, board: ps.filter(p => p.why?.length).length,
      top: ps.filter(p => p.fv != null).sort((a, b) => b.fv - a.fv).slice(0, 3).map(p => ({ name: p.name, pos: p.pos, fv: p.fv })),
      elo: rating[tid] != null ? Math.round(rating[tid]) : null, rec: record[tid] || { w: 0, l: 0, pf: 0, pa: 0 },
      nil, nilN: ps.filter(p => p.nil).length,
      hc: t.coach || null,
    });
  }
  // ranks, and normal scores of the ranks: talent has a long right tail (elite rosters sit 3+ SD out)
  // while five weeks of Elo is compressed, so raw z-scores aren't comparable; rank-normal scores are
  const played = out.filter(t => t.elo != null && t.rec.w + t.rec.l > 0);
  rank(out, 'talent', 'talentRk'); rank(played, 'elo', 'eloRk');
  const rn = (rk, n) => probit(1 - (rk - 0.5) / n);
  for (const t of out) t.talentZ = rn(t.talentRk, out.length);
  for (const t of played) t.eloZ = rn(t.eloRk, played.length);
  for (const t of out) t.tve = t.eloZ == null ? null : r2(t.eloZ - t.talentZ);
  // NIL+: Elo against what the NIL total predicts (log-linear fit over teams with On3 valuations),
  // 100 = average, every 10 points one standard deviation of the residual, like OPS+
  const withNil = played.filter(t => t.nil > 0);
  if (withNil.length > 10) {
    const xs = withNil.map(t => Math.log(t.nil)), ys = withNil.map(t => t.elo);
    const mx = mean(xs), my = mean(ys);
    const b = xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / xs.reduce((a, x) => a + (x - mx) ** 2, 0);
    const res = withNil.map((t, i) => ys[i] - (my + b * (xs[i] - mx))), s = sd(res);
    withNil.forEach((t, i) => { t.nilPlus = Math.round(100 + 10 * res[i] / s); t.eloPerM = r1((t.elo - 1500) / (t.nil / 1e6)); });
  }
  for (const t of out) { t.talentZ = r2(t.talentZ); if (t.eloZ != null) t.eloZ = r2(t.eloZ); }
  out.sort((a, b) => b.talent - a.talent);
  return out;
}

function rank(list, key, as) { [...list].sort((a, b) => b[key] - a[key]).forEach((t, i) => { t[as] = i + 1; }); }
function mode(xs) { const c = {}; let best = null; for (const x of xs) { c[x] = (c[x] || 0) + 1; if (!best || c[x] > c[best]) best = x; } return best; }

// ---- staff ------------------------------------------------------------------------------------------
// Coordinators get their side's position groups; head coaches the team. Two signals per group:
//   over:  how far the group's production runs ahead of its talent (PFN z minus On3-based z), the
//          starters weighted by snaps — coaching shows up as players producing above their grade
//   dev:   On3 college grade minus high school grade for the group's ranked players — who got better
// Scores are indices: 100 = average coordinator, 10 = one standard deviation (+ like OPS+).
export function staffModels(rows, teamList, staff) {
  const byTeam = {};
  for (const p of rows) if (p.tid) (byTeam[p.tid] ||= []).push(p);
  const groupScore = (ps, groups) => {
    const st = [];
    for (const g of groups) st.push(...ps.filter(p => p.pos === g && p.pfn != null).sort((a, b) => b.comp - a.comp).slice(0, STARTERS[g]));
    const w = st.map(p => Math.max(1, p.snaps || 1));
    const over = st.length ? st.reduce((a, p, i) => a + w[i] * (p.prodZ - p.talentZ), 0) / w.reduce((a, b) => a + b, 0) : null;
    const devs = ps.filter(p => groups.includes(p.pos) && p.on3 != null && p.hsGrade != null).map(p => p.on3 - p.hsGrade);
    return { over, dev: devs.length ? mean(devs) : null, devN: devs.length,
      risers: ps.filter(p => groups.includes(p.pos) && p.on3 != null && p.hsGrade != null && p.on3 - p.hsGrade >= 8)
        .sort((a, b) => (b.on3 - b.hsGrade) - (a.on3 - a.hsGrade)).slice(0, 3)
        .map(p => ({ name: p.name, pos: p.pos, hs: Math.round(p.hsGrade), now: p.on3, stars: p.hsStars })) };
  };
  const coaches = [];
  for (const t of teamList) {
    const ps = byTeam[t.tid] || [], s = staff?.[t.tid] || {};
    const off = groupScore(ps, OFFENSE), def = groupScore(ps, DEFENSE);
    const base = { tid: t.tid, team: t.team, logo: t.logo, conf: t.conf };
    const hcName = s.hc?.name || t.hc;
    if (hcName) coaches.push({ ...base, role: 'HC', name: hcName, src: s.hc?.src || 'espn', raw: t.eloZ == null ? null : t.eloZ * 0.6 + (t.tve ?? 0) * 0.4,
      detail: { elo: t.elo, eloRk: t.eloRk, tve: t.tve, rec: t.rec } });
    for (const [role, side, groups] of [['OC', off, OFFENSE], ['DC', def, DEFENSE]]) {
      const c = s[role.toLowerCase()];
      if (!c?.name) continue;
      coaches.push({ ...base, role, name: c.name, src: c.src, groups, raw: null, over: side.over, dev: side.dev, devN: side.devN, risers: side.risers });
    }
  }
  // coordinator raw score: production-over-talent and development, each standardized among coordinators
  const coords = coaches.filter(c => c.role !== 'HC');
  const oz = zs(coords.map(c => c.over ?? 0)), dz = zs(coords.map(c => c.dev ?? 0));
  coords.forEach((c, i) => { c.raw = 0.6 * oz[i] + 0.4 * (c.devN >= 3 ? dz[i] : 0); });
  for (const role of ['HC', 'OC', 'DC']) {
    const list = coaches.filter(c => c.role === role && c.raw != null);
    const z = zs(list.map(c => c.raw));
    list.forEach((c, i) => { c.score = Math.round(100 + 10 * z[i]); });
    rank(list, 'score', 'rk');
  }
  for (const c of coaches) { if (c.over != null) c.over = r2(c.over); if (c.dev != null) c.dev = r1(c.dev); delete c.raw; }
  return coaches.filter(c => c.score != null).sort((a, b) => b.score - a.score);
}

// ---- mock draft ------------------------------------------------------------------------------------
// Each pick takes the best value for that team: FV, plus positional value (what the NFL pays for a
// spot: QB and pass rushers first, backs and off-ball linebackers last), plus team need (Tankathon's
// mock positions, first need counts most), minus a small reach penalty for a position the team
// already took. The pool is every draft-eligible graded player; underclassmen only if they grade 45+,
// since most of them stay in school otherwise.
const POS_VALUE = { QB: 4, EDGE: 2.5, OL: 1.5, WR: 1.5, CB: 1.5, DL: 1, S: 0, TE: -0.5, LB: -1, RB: -1.5 };
const NEED_BONUS = [3, 2, 1.5, 1, 0.5];
export function mockDraft(rows, tank, rounds = 3) {
  const pool = rows.filter(p => p.fv != null && p.draft27 && STARTERS[p.pos] && (p.elig >= 4 || p.fv >= 45))
    .map(p => ({ ...p, spotOL: p.pos === 'OL' && /T$/.test(p.spot || '') ? 'OT' : p.pos === 'OL' ? 'IOL' : null }));
  const taken = new Set(), teamPos = {}, picks = [];
  for (const o of tank.order.filter(o => o.round <= rounds)) {
    const needs = (tank.needs[o.team] || []).map(n => n.group);
    let best = null, bestV = -Infinity, why = null;
    for (const p of pool) {
      if (taken.has(p)) continue;
      const ni = needs.indexOf(p.pos);
      const need = ni >= 0 ? NEED_BONUS[ni] ?? 0.5 : 0;
      const dup = (teamPos[o.team] || []).filter(x => x === p.pos).length * 2;
      const v = p.fv + (p.plus ? 1 : 0) + (POS_VALUE[p.pos] ?? 0) + need - dup;
      if (v > bestV) { bestV = v; best = p; why = ni >= 0 ? `need #${ni + 1}` : null; }
    }
    if (!best) break;
    taken.add(best); (teamPos[o.team] ||= []).push(best.pos);
    picks.push({ pick: o.pick, round: o.round, team: o.team, teamName: o.teamName, from: o.from, comp: o.comp,
      name: best.name, pos: best.pos, spot: best.spot, school: best.team, logo: best.logo, fv: best.fv, plus: best.plus,
      cls: best.cls, age: best.age ?? best.ageEst, ageEst: best.age == null, ovr: best.ovr, need: why });
  }
  // where each pick sits on our draft-eligible big board (positive = we have him later: a reach)
  const bigBoard = [...pool].sort((a, b) => b.fv - a.fv || b.comp - a.comp);
  const at = new Map(bigBoard.map((p, i) => [p.name + '|' + p.team, i + 1]));
  for (const k of picks) { k.bb = at.get(k.name + '|' + k.school); k.reach = k.bb - k.pick; }
  return picks;
}
