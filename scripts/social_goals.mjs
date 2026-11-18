// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Follower goals shared by the social_data.exe windows (scripts/laursen_socials.mjs, scripts/arkndjl_socials.mjs).
// ---- goals: projected net follower gain per network ------------------------------------------------
// Daily rate lambda ~ Gamma(a, b). Prior: his lifetime pace (count / days since the account opened), worth 30 days
// of tracking (b = 30, a = 30 x pace). Each tracked day updates it: a += net gain since the first reading,
// b += days tracked, so his own trend takes over within a few weeks. Gain over t days is then negative binomial
// (r = a, p = b / (b + t)). Goals: the 30- and 90-day median count (at least +1), with the chance
// of reaching it; next milestone: median date and the chance within 90 days.
export const PRIOR_DAYS = 30, MILESTONES = [25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 5000, 10000, 25000, 50000, 100000];
export function lgamma(z) { const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let x = z, y = z, t = x + 5.5; t -= (x + 0.5) * Math.log(t); let ser = 1.000000000190015; for (const q of c) ser += q / ++y; return -t + Math.log(2.5066282746310005 * ser / x); }
// P(gain >= need) under NB(r, p): 1 - sum_{k<need} pmf(k)
export function pAtLeast(need, r, p) { if (need <= 0) return 1; let cdf = 0; for (let k = 0; k < need; k++) cdf += Math.exp(lgamma(k + r) - lgamma(k + 1) - lgamma(r) + r * Math.log(p) + k * Math.log(1 - p)); return Math.max(0, Math.min(1, 1 - cdf)); }
export function medianGain(r, p) { let k = 0; while (pAtLeast(k + 1, r, p) >= 0.5 && k < 1e6) k++; return k; }
// series: readings {t, <net>: count}; prevHist: the last run's hist; OPENED: {net: account creation date}
export function buildGoals(series, prevHist, OPENED, MILESTONES_ = MILESTONES) {
  const MILESTONES = MILESTONES_;
  const goals = {}, hist = JSON.parse(JSON.stringify(prevHist || {}));
  for (const k of Object.keys(OPENED)) {
    const pts = series.filter(x => x[k] != null); if (!pts.length) continue;
    const first = pts[0], lastP = pts[pts.length - 1], c = lastP[k];
    const life = Math.max(1, (pts[0].t - Date.parse(OPENED[k])) / 864e5), pace = first[k] / life;
    const days = (lastP.t - first.t) / 864e5, gain = Math.max(0, lastP[k] - first[k]);
    const a = Math.max(0.5, PRIOR_DAYS * pace) + gain, b = PRIOR_DAYS + days, rate = a / b;
    const g = {};
    for (const T of [30, 90]) { const p = b / (b + T), med = c + medianGain(a, p), goal = Math.max(med, c + 1);
      g[`d${T}`] = { goal, p: Math.round(pAtLeast(goal - c, a, p) * 100), median: med }; }
    const next = MILESTONES.find(m => m > c);
    if (next) { const need = next - c; let lo = 1, hi = 36500; while (lo < hi) { const mid = (lo + hi) >> 1; if (pAtLeast(need, a, b / (b + mid)) >= 0.5) hi = mid; else lo = mid + 1; }
      g.next = { goal: next, eta: lo >= 36500 ? null : new Date(lastP.t + lo * 864e5).toISOString().slice(0, 10), p90: Math.round(pAtLeast(need, a, b / (b + 90)) * 100) }; }
    goals[k] = { rate: Math.round(rate * 30 * 10) / 10, prior: Math.round(pace * 30 * 10) / 10, tracked: Math.round(days * 10) / 10, ...g };

    // ---- goal log: dated goals are committed when set and held to their due date (not re-rolled each run);
    // milestones keep the ETA projected when they became the next one, so a hit reads as days ahead (+) or behind (-).
    const h = hist[k] = hist[k] || { dated: [], ms: [] };
    const firstHit = (goal, from) => (pts.find(x => x.t >= from && x[k] >= goal) || {}).t ?? null;
    const atOrBefore = t => { let v = null; for (const x of pts) if (x.t <= t) v = x[k]; return v; };
    const left = t => Math.max(0, (t - lastP.t) / 864e5);
    for (const T of [30, 90]) {
      const open = h.dated.find(d => d.T === T && !d.done);
      if (open) { const hit = firstHit(open.goal, open.set);
        if (hit && hit <= open.due) Object.assign(open, { done: true, hit, ahead: Math.round((open.due - hit) / 864e5) });
        else if (lastP.t >= open.due) Object.assign(open, { done: true, final: atOrBefore(open.due) }); }
      if (!h.dated.some(d => d.T === T && !d.done)) h.dated.push({ T, goal: g[`d${T}`].goal, p: g[`d${T}`].p, base: c, set: lastP.t, due: lastP.t + T * 864e5 });
      const d = h.dated.find(d => d.T === T && !d.done);
      goals[k][`d${T}`] = { goal: d.goal, base: d.base, set: d.set, due: d.due, p0: d.p, p: Math.round(pAtLeast(d.goal - c, a, b / (b + left(d.due))) * 100) };
    }
    // milestones already passed when tracking began: pace-implied date (lifetime pace), flagged est
    if (!h.ms.length) for (const m of MILESTONES.filter(m => m <= first[k])) h.ms.push({ goal: m, hit: Math.round(Date.parse(OPENED[k]) + m / pace * 864e5), est: true });
    for (const m of MILESTONES.filter(m => m <= c)) { const e = h.ms.find(x => x.goal === m);
      if (!e) h.ms.push({ goal: m, hit: firstHit(m, 0) ?? lastP.t });
      else if (!e.hit) { e.hit = firstHit(m, e.set) ?? lastP.t; if (e.eta0) e.ahead = Math.round((Date.parse(e.eta0) - e.hit) / 864e5); } }
    if (g.next) { let e = h.ms.find(x => x.goal === g.next.goal);
      if (!e) h.ms.push(e = { goal: g.next.goal, set: lastP.t, base: c, eta0: g.next.eta });
      const prevM = MILESTONES.filter(m => m < g.next.goal).pop() || 0;
      Object.assign(g.next, { from: prevM, base: e.base, set: e.set, eta0: e.eta0 }); }
    // progress bars: f = share of the way from start to goal; m = where the projection says he should be by now
    const cl = v => Math.round(Math.max(0, Math.min(1, v)) * 1000) / 1000;
    for (const T of [30, 90]) { const d = goals[k][`d${T}`]; d.f = cl((c - d.base) / Math.max(1, d.goal - d.base)); d.m = cl((lastP.t - d.set) / Math.max(1, d.due - d.set)); }
    if (g.next) { const n = g.next, span = Math.max(1, n.goal - n.from); n.f = cl((c - n.from) / span);
      if (n.eta0) { const end = Date.parse(n.eta0), exp = n.base + (n.goal - n.base) * Math.min(1, (lastP.t - n.set) / Math.max(1, end - n.set)); n.m = cl((exp - n.from) / span); } }
    h.ms.sort((x, y) => x.goal - y.goal); h.dated = h.dated.slice(-60);
    goals[k].opened = OPENED[k];
  }
  return { goals, hist };
}
