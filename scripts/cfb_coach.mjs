// The coaching market for the College Football ARKBOARD, fed by scripts/fetch_cfb.mjs: what each head coach and
// coordinator is worth, which jobs open after the season, who fills them and where coaches (and the players who
// follow them) go. Fit by scripts/cfb_coach_fit.py on USA Today's salary database and ESPN records
// (data/cfb_coach_fit.json, history in data/cfb_coach_pay.json); every function here mirrors the fit by name.
//
// Value: log(pay) on the staff board's inputs and the program's, ridge, each input kept only if it cut
//   leave-one-out error (fit on 2025 pay). Head coaches: recruiting level, P4, results (win% over three
//   seasons and this one), pass rate over expected. Coordinators: the program's head-coach pay, co-coordinator,
//   side. Elo, TvE, zNIL, the staff score and 4th-down aggression didn't add to pay once those were in: the
//   market doesn't price them, which is where value and pay part.
// Vacancy: multinomial logit on 2010-25 school-seasons (stay / moved to another head job / out), this
//   season's win% projected to the end from the season simulation.
// Hires: when a job opens, the new coach is a sitting FBS head coach (share.hc), one of the two best-paid
//   assistants somewhere (share.coord, the coordinators in practice) or someone off the board. Within each
//   pool a conditional logit (pay step up, results, level step, conference, distance; internal promotion).
// Staff: coordinators stay, follow a head coach who moved, get a head job, or leave, at the rates measured on
//   2010-24 staffs given what happened to the head coach; promotion from the hire model.
const P4_CONF = new Set(['SEC', 'Big Ten', 'Big 12', 'ACC']);
const ND = '87';
const SEASON = 2026;
const r2 = x => Math.round(x * 100) / 100, r3 = x => Math.round(x * 1000) / 1000;
export const norm = s => String(s || '').toLowerCase().replace(/&/g, 'and').replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, '').replace(/[^a-z]/g, '');
const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
function miles(a, b) {
  if (!a || !b) return null;
  const R = Math.PI / 180, h = Math.sin((b[0] - a[0]) * R / 2) ** 2 + Math.cos(a[0] * R) * Math.cos(b[0] * R) * Math.sin((b[1] - a[1]) * R / 2) ** 2;
  return 3959 * 2 * Math.asin(Math.sqrt(h));
}
const softmax = zs => { const m = Math.max(...zs), e = zs.map(z => Math.exp(z - m)), s = e.reduce((a, b) => a + b, 0); return e.map(x => x / s); };
const dot = (b, x) => b.reduce((a, v, i) => a + v * x[i], 0);
const levelOf = t => t.div === 'FCS' ? 'FCS' : P4_CONF.has(t.conf) || t.tid === ND ? 'P4' : 'G5';

// this season's win% to the end of the regular season: the simulation's projected wins over games played + left
function projWin(t, sim) {
  const s = sim?.[t.tid];
  if (s?.projW != null && s.rec) { const [w, l] = s.rec.split('-').map(Number); const g = w + l + (s.left || 0); if (g) return s.projW / g; }
  const g = (t.rec?.w || 0) + (t.rec?.l || 0);
  return g ? t.rec.w / g : null;
}

// the vacancy model's inputs (cfb_coach_fit.py features()); h = the school's history, wp = this season
function vacancyX(h, t, wp, sameCoach) {
  const W = h?.wins || {}, w1 = W[SEASON - 1], w2 = W[SEASON - 2];
  const past = Object.entries(W).filter(([y]) => +y >= SEASON - 10).map(([, v]) => v);
  const nw = past.length >= 3 ? mean(past) : 0.5;
  const ten = sameCoach && h?.start ? SEASON - h.start + 1 : 1, cens = sameCoach && h?.censored;
  const lv = levelOf(t), prev = w1 ?? wp;
  const pr = sameCoach && h?.pay && hist.medians?.[lv] ? Math.log(h.pay / hist.medians[lv]) : null;
  return { wp: wp - 0.5, wpPrev: ((w1 ?? wp) + (w2 ?? prev)) / 2 - 0.5, vsNorm: wp - nw, yr1: +(ten === 1), yr2: +(ten === 2),
    longTen: Math.log(!cens || ten >= 5 ? Math.min(ten, 12) : 5), g5: +(lv === 'G5'), g5wp: +(lv === 'G5') * (wp - 0.5),
    payRel: pr ?? 0, payMiss: +(pr == null), _ten: ten };
}
let hist = {};

// the value models (value_fit): standardized ridge on log pay
function valueOf(m, x) {
  if (!m) return null;
  let z = m.coef[0];
  m.names.forEach((k, i) => { z += m.coef[i + 1] * ((x[k] ?? m.mu[i]) - m.mu[i]) / m.sd[i]; });
  return Math.exp(z);
}

export function coachMarket(coaches, teamList, { fit, history, sim, loc }) {
  hist = history || {};
  if (!fit?.vacancy || !hist.teams) return null;
  const T = Object.fromEntries(teamList.map(t => [t.tid, t]));
  const H = hist.teams, heads = hist.heads || {}, ast = hist.assistants || {};
  const simBy = Object.fromEntries((sim || []).map(s => [s.tid, s]));
  const team = {};
  // 1. each program: its head coach's season, the vacancy odds
  for (const t of teamList) {
    const h = H[t.tid] || {}, wp = projWin(t, simBy);
    if (wp == null || !t.hc) continue;
    const same = norm(h.coach) === norm(t.hc);
    const x = vacancyX(h, t, wp, same), V = fit.vacancy;
    const zs = [0, ...[0, 1].map(k => V.names.reduce((a, n, i) => a + V.coef[i][k] * (n === 'const' ? 1 : x[n]), 0))];
    const [stay, moved, out] = softmax(zs);
    team[t.tid] = { tid: t.tid, team: t.team, logo: t.logo, conf: t.conf, lv: levelOf(t), wp, x, same, hc: t.hc, stay, moved, out, open: moved + out };
  }
  // 2. market value and pay
  const hcPayOf = {};
  for (const c of coaches) {
    const t = T[c.tid], tm = team[c.tid], h = H[c.tid] || {};
    if (!t) continue;
    if (c.role === 'HC') {
      const hd = heads[norm(c.name)], W = (hd && !tm?.same ? hd.wins : h.wins) || {};
      const wins = [W[SEASON - 2], W[SEASON - 1], tm?.wp].filter(v => v != null);
      const s = c.scheme || {};
      const x = { p4: +(levelOf(t) === 'P4'), rec: t.recruited ?? 0, elo: t.eloZ ?? 0, tve: t.tve ?? 0, znil: c.znilV ?? 0, score: (c.score - 100) / 10,
        goOe: s.goOe ?? 0, proe: s.proe ?? 0, w3: wins.length ? mean(wins) - 0.5 : 0, w1: (tm?.wp ?? 0.5) - 0.5 };
      c.value = Math.round(valueOf(fit.valueHC, x) / 1e4) * 1e4;
      if (tm?.same && h.pay) Object.assign(c, { pay: h.pay, payYr: SEASON - 1 });
      else if (hd?.pay) Object.assign(c, { pay: hd.pay, payYr: SEASON - 1, paySchool: H[hd.tid]?.school || null });
      if (tm?.same && h.buyout) c.buyout = h.buyout;
      hcPayOf[c.tid] = c.pay && !c.paySchool ? c.pay : c.value;
    }
  }
  for (const c of coaches) {
    if (c.role === 'HC' || !T[c.tid]) continue;
    const t = T[c.tid], names = c.name.split(' / ');
    const x = { p4: +(levelOf(t) === 'P4'), rec: t.recruited ?? 0, hcPay: Math.log(hcPayOf[c.tid] || hist.medians?.[levelOf(t)] || 1e6), score: (c.score - 100) / 10,
      over: c.over ?? 0, dev: (c.dev ?? 0) / 10, znil: c.znilV ?? 0, oc: +(c.role === 'OC'), co: +(names.length > 1) };
    c.value = Math.round(valueOf(fit.valueCoord, x) / 1e4) * 1e4;
    // pay only where he coaches now (a common name on another staff can be someone else), and for co-coordinators
    // only when every one of them is on the list there (value is per coach: their average)
    const a = names.map(n => ast[norm(n)]).filter(a => a && a.tid === c.tid);
    if (a.length && a.length === names.length) Object.assign(c, { pay: Math.round(mean(a.map(x => x.pay))), payYr: Math.min(...a.map(x => x.year)) });
  }
  for (const c of coaches) if (c.value && c.pay && !c.paySchool) c.surplus = c.value - c.pay;
  // 3. hires: who fills each opening, by pool
  const HC = fit.hire.hc, CO = fit.hire.coord, share = fit.hire.share;
  const heads26 = coaches.filter(c => c.role === 'HC' && team[c.tid]);
  const coords = coaches.filter(c => c.role !== 'HC' && team[c.tid]).flatMap(c => c.name.split(' / ').map(n => ({ c, name: n })));
  const hcPayNow = c => (c.pay && !c.paySchool ? c.pay : c.value) || hist.medians?.[team[c.tid].lv] || 1e6;
  const coordPay = (k) => (k.c.pay && !k.c.paySchool ? k.c.pay : k.c.value) || hist.medians?.coord || 5e5;
  const hires = {}, landing = {}, promo = {};
  for (const v of Object.values(team)) {
    const jp = hcPayOf[v.tid] || hist.medians?.[v.lv] || 1e6, L = loc?.[v.tid];
    const hc = heads26.filter(c => c.tid !== v.tid).map(c => {
      const o = team[c.tid], x = o.x;
      return { c, z: dot(HC.coef, [Math.log(jp / hcPayNow(c)), x.wp, x.vsNorm, +(o.lv === 'G5' && v.lv === 'P4'), +(o.lv === 'P4' && v.lv === 'G5'),
        +(o.conf === v.conf), Math.log1p((miles(L, loc?.[c.tid]) ?? 800) / 100), x.yr1]) };
    });
    const g5 = +(v.lv === 'G5'), sh = share[v.lv] || share.G5;
    const co = coords.map(k => { const pr = Math.log(coordPay(k) / (hist.medians?.coord || 5e5)), o = team[k.c.tid];
      return { k, z: dot(CO.coef, [pr, g5 * pr, o.wp - 0.5, +(o.lv === 'P4'), g5 * +(o.lv === 'P4'), +(o.conf === v.conf),
        Math.log1p((k.c.tid === v.tid ? 0 : miles(L, loc?.[k.c.tid]) ?? 800) / 100), +(k.c.tid === v.tid)]) }; });
    const ph = softmax(hc.map(h => h.z)), pc = softmax(co.map(h => h.z));
    hc.forEach((h, i) => { h.p = (sh.hc || 0) * ph[i]; (landing[h.c.tid] ||= []).push({ to: v.tid, w: v.open * h.p }); });
    co.forEach((h, i) => { h.p = (sh.coord || 0) * pc[i]; const key = h.k.c.tid + '|' + h.k.c.role; (promo[key] ||= []).push({ to: v.tid, name: h.k.name, w: v.open * h.p }); });
    v.other = sh.other || 0;
    hires[v.tid] = [...hc.map(h => ({ name: h.c.name, role: 'HC', from: h.c.team, fromTid: h.c.tid, p: h.p })),
      ...co.map(h => ({ name: h.k.name, role: h.k.c.role, from: h.k.c.team, fromTid: h.k.c.tid, p: h.p }))].sort((a, b) => b.p - a.p).slice(0, 6);
  }
  // 4. where coaches go: a head coach who moves is spread over the openings by the hire model; coordinators
  // stay, follow him, are promoted (the hire model) or leave, at the measured rates
  const TO = fit.turnover;
  const dest = (list, total) => { const s = list.reduce((a, d) => a + d.w, 0) || 1;
    const agg = {}; for (const d of list) agg[d.to] = (agg[d.to] || 0) + d.w / s * total;
    return Object.entries(agg).map(([to, p]) => ({ tid: to, team: T[to]?.team, p: r3(p) })).filter(d => d.p >= 0.001).sort((a, b) => b.p - a.p).slice(0, 4); };
  const flows = [];
  for (const c of coaches) {
    const tm = team[c.tid]; if (!tm) continue;
    if (c.role === 'HC') {
      c.move = { stay: r3(tm.stay), moved: r3(tm.moved), out: r3(tm.out), dest: dest(landing[c.tid] || [], tm.moved) };
      for (const d of c.move.dest) flows.push({ from: c.tid, to: d.tid, role: 'HC', name: c.name, p: d.p });
    } else {
      const pr = (promo[c.tid + '|' + c.role] || []), pP = Math.min(0.6, pr.reduce((a, d) => a + d.w, 0));
      const kStay = { stay: tm.stay, moved: tm.moved, out: tm.out };
      const rate = o => Object.entries(kStay).reduce((a, [k, p]) => a + p * (TO[k][o] || 0), 0);
      const st = rate('stay'), fo = rate('follow'), le = rate('left'), rest = st + fo + le || 1;
      const stay = (1 - pP) * st / rest, follow = (1 - pP) * fo / rest, left = (1 - pP) * le / rest;
      const hd = dest(landing[c.tid] || [], follow), pd = dest(pr, pP);
      c.move = { stay: r3(stay), follow: r3(follow), promoted: r3(pP), left: r3(left), followDest: hd, promoDest: pd };
      for (const d of hd) flows.push({ from: c.tid, to: d.tid, role: c.role, name: c.name, p: d.p, how: 'follows HC' });
      for (const d of pd) if (d.tid !== c.tid) flows.push({ from: c.tid, to: d.tid, role: c.role, name: c.name, p: d.p, how: 'head coach' });
    }
  }
  // ranks within the role, for the board
  for (const role of ['HC', 'OC', 'DC']) {
    coaches.filter(c => c.role === role && c.value).sort((a, b) => b.value - a.value).forEach((c, i) => { c.valueRk = i + 1; });
  }
  const teams = Object.values(team).sort((a, b) => b.open - a.open).map(v => ({ tid: v.tid, team: v.team, logo: v.logo, conf: v.conf, hc: v.hc,
    open: r3(v.open), moved: r3(v.moved), out: r3(v.out), wp: r3(v.wp), vsNorm: r2(v.x.vsNorm), tenure: v.x._ten,
    hires: hires[v.tid].map(h => ({ ...h, p: r3(h.p) })), other: r3(v.other) }));
  return { teams, flows: flows.sort((a, b) => b.p - a.p) };
}
