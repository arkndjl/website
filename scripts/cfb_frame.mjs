// NFL frame: FV points from the draft-slot effect of size against drafted players at the position
// (combine 2010-25, data/cfb_calibration.json size): below the 10th percentile costs per SD short, between p10
// and p90 a small slope, above p90 (EDGE weight, RB/TE height) costs too. Halved: size moves draft slot more
// than careers. QB check (scripts/cfb_frame_backtest.py, data/cfb_frame_backtest.json: PFN final seasons
// 2019-22, college listings, production held fixed): weight carries the evidence and the hinge is if anything
// mild on light QBs (a listing under 212 lb costs ~3 FV as a step), so it stays as it is.
// Shared by the board (scripts/fetch_cfb.mjs) and the ESPN backups (scripts/cfb_espn_backups.mjs).
// p: { g, pfnPos (OL: a T-ending spot reads as OT), htIn, wtLb }
// FRAME_W: the wide refit (scripts/cfb_fv_refit.mjs --wide, the 2014-22 classes, one class held out at a time) put
// frame at 1.4x: r with NFL AV and with draft slot +.001 on every universe, 9 of 10 held-out classes
export const FRAME_W = 1.4;
export function frameFV(p, size) {
  const key = p.g === 'OL' ? (/T$/.test(p.pfnPos || '') ? 'OT' : 'IOL') : p.g, n = size[key];
  if (!n || !p.htIn || !p.wtLb) return 0;
  let fv = 0;
  for (const [m, x] of [['ht', p.htIn], ['wt', p.wtLb]]) {
    const q = n[m], h = n.hinge || {};
    if (!q) continue;
    if (x < q.p10) fv -= Math.abs(h[m + '_lo'] ?? 0) * (q.p10 - x) / q.sd;
    else if (x > q.p90) fv += (h[m + '_hi'] ?? 0) < 0 ? h[m + '_hi'] * (x - q.p90) / q.sd : 0;
    else fv += Math.max(0, h[m + '_mid'] ?? 0) * (x - q.p50) / q.sd * 0.5;
  }
  fv = Math.max(-8, Math.min(3, fv * 0.5));
  // an edge rusher far below NFL edge weight (10+ lb under the 10th percentile, 244) projects to an off-ball or
  // rush-linebacker role at the next level: -0.25 FV a pound past that, up to -5
  if (p.g === 'EDGE') fv += -Math.min(5, Math.max(0, n.wt.p10 - 10 - p.wtLb) * 0.25);
  return FRAME_W * fv;
}

export const bmiOf = (htIn, wtLb) => (htIn && wtLb ? 703 * wtLb / htIn ** 2 : null);
// "6' 2\"", "6-2" or "6-2.5" to inches
export const inchesOf = h => { const m = /^(\d)\D+(\d+(?:\.\d+)?)/.exec(h || ''); return m ? +m[1] * 12 + +m[2] : null; };

// In-position height (Nov 3 2026, Noah: size as an FV driver, positionally adjusted): measured height
// (scripts/cfb_measure.mjs, combine-equivalent) as z against drafted players' combine norms at the spot he projects to
// (the board's move when it names one of these spots, else his own), centred on the graded pool's mean at his position
// (2014-22, HT_CENTER) so the term reorders within a position without moving its level; FV_HT_W FV a SD, capped at 3 SD.
// Test (scripts/cfb_measure_fv.py on the harness's 2014-22 grades, its gates; data/cfb_measure_fv_ship.json): weight
// picked per held-out class 2 (t 2.53, 9 of 10 classes); at 1.5, t 3.83, 10 of 10, within-position Spearman .435 ->
// .448, top 32 a class AV +.04 (7 of 10) and draft capital +.05 (7 of 10), forward (picked on 2014-18, graded 2019-23)
// r +.011, top 32 4.17 -> 4.17. 1 of 29 size variants tried, so Holm not cleared (the same z on the raw listing passes
// as well, so height carries it, not the measurement): PULLED the same day (weight 0; a search ships only past
// multiple-testing control). Lead: retest at 1.5 as one pre-registered test once the 2023-25 classes have graded AV.
// QB-LB only (OL, CB and S have no graded history). frameFV on the measured size instead of the listing: t 0.15, 4 of 10,
// not shipped
export const FV_HT_W = 0;
export const HT_CENTER = { QB: -0.442, RB: -0.297, WR: -0.158, TE: -0.432, EDGE: -0.538, DL: -0.565, LB: -0.474 };
export function heightFV(g, pg, ht, size) {
  if (!(g in HT_CENTER) || !ht) return 0;
  const n = size[pg in HT_CENTER ? pg : g]?.ht;
  if (!n) return 0;
  return FV_HT_W * Math.max(-3, Math.min(3, (ht - n.mean) / n.sd - HT_CENTER[g]));
}
