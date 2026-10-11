// Player badges and the archetypes built on them, for the College Football ARKBOARD.
//
// A badge is one trait (Blocker, Pass Rusher, Ballhawk...) measured by one stat on PFN's season line. Each
// player's stat is regressed toward the position mean by his volume, v' = m + (v - m) * n / (n + k), where k
// is the volume at which the stat is half signal (year-to-year r = n / (n + k), measured on PFN lines
// 2019-25 for players with 100+ snaps in back-to-back FBS seasons; the r at that volume is in each comment).
// The tier is the percentile of v' among the position's 100+ snap players in the division:
//   Bronze  75th (top 25%, z +0.67)   Silver  90th (top 10%, z +1.28)
//   Gold    97th (top 3%,  z +1.88)   Platinum 99th (top 1%, z +2.33)
// so each tier is about a third as common as the one below, and a badge means the same share of players at
// every position. Badges are positional: a Gold Tackler corner is top 3% among corners, not among all players.
//
// Archetypes are now a few general shapes per position, picked from the badges: each archetype lists badge
// groups, its score is the sum of tier points (Bronze 1, Silver 2, Gold 3, Platinum 4) of the badges in its
// groups, every group needs at least one badge, and the best score of 2+ (a Silver, or two Bronzes) wins.
// A two-group archetype (dual-threat TE) outscores either half whenever both halves are there. Below 2 the
// player gets the position's base archetype. The badges then say what kind: a "pass rusher" with Gold Pass
// Rusher and Bronze Run Stopper reads differently from one with Bronze Pass Rusher alone.

const per = (a, b) => (typeof a === 'number' && b ? a / b : null);
const num = v => (typeof v === 'number' && isFinite(v) ? v : null);
const games = r => num(r.gp) || num(r.gamesQ) || null;
// past seasons on PFN carry games, not snaps, at the skill spots and in the secondary: ~55 a game
const snaps = r => num(r.snapsQ) ?? num(r.snaps) ?? (games(r) ? 55 * games(r) : null);
const carries = r => (r.ypc ? r.ryds / r.ypc : null);
const neg = v => (v == null ? null : -v);

export const TIERS = [['platinum', 0.99, 4], ['gold', 0.97, 3], ['silver', 0.9, 2], ['bronze', 0.75, 1]];
export const TIER_PTS = Object.fromEntries(TIERS.map(([t, , pts]) => [t, pts]));

// [key, name, value (higher is better), volume, k, what the stat is]. A value can be a list of stats, z'd within
// the position and averaged (a composite, for coverage, where single stats barely repeat). k = n (1 - r) / r
// from the year-to-year r at the pairs' mean volume n (shown). Stats under r .15 are left out as noise:
// QB INT rate (.06), TE catch rate (.07), LB passer rating allowed (.03), CB/S missed-tackle rate (.10/.12),
// and CB rating (.10) and catch rate (.13) on their own
const ccov = [r => neg(num(r.rtg)), r => neg(num(r.catch)), r => num(r.fi)];
const bhawk = r => per((r.int || 0) + (r.pbu || 0), r.tar);
export const BADGES = {
  QB: [
    ['accurate', 'Accurate', r => num(r.cmpPct), r => r.att, 320, 'completion %'],                          // r .47 at 287 att
    ['deep', 'Deep Ball', r => num(r.nypa), r => r.att, 700, 'yards per attempt'],                          // r .29 at 287 att
    ['scrambler', 'Scrambler', r => per(r.ryds, games(r)), games, 3, 'rushing yards a game'],               // r .75 at 10 games
  ],
  RB: [
    ['elusive', 'Elusive', r => num(r.elu), carries, 280, 'elusiveness'],                                   // r .36 at 158 carries
    ['breakaway', 'Breakaway', r => num(r.boom), carries, 400, 'breakaway-run rate'],                       // r .28
    ['efficient', 'Efficient Runner', r => num(r.ypc), carries, 480, 'yards per carry'],                    // r .25
    ['workhorse', 'Workhorse', r => num(r.share), games, 20, 'backfield snap share'],                       // r .35 at 11 games
    ['catcher', 'Pass Catcher', r => per(r.recYds, games(r)), games, 10, 'receiving yards a game'],         // r .54
  ],
  WR: [
    ['route', 'Route Runner', r => num(r.ypr), r => r.tar, 110, 'yards per route run'],                     // r .38 at 68 targets
    ['deep', 'Deep Threat', r => per(r.recYds, r.rec), r => r.rec, 80, 'yards a catch'],                    // r .35 at 43 catches
    ['yac', 'YAC', r => num(r.yac), r => r.rec, 90, 'yards after catch'],                                   // r .32
    ['hands', 'Hands', r => num(r.catch), r => r.tar, 140, 'catch rate'],                                   // r .33
    ['target', 'Target Magnet', r => num(r.tgtSh), games, 15, 'target share'],                              // r .43 at 11 games
  ],
  TE: [
    ['blocker', 'Blocker', r => num(r.blk), snaps, 560, 'blocking grade'],                                  // r .53 at ~620 snaps
    ['catcher', 'Pass Catcher', r => per(r.recYds, games(r)), games, 5, 'receiving yards a game'],          // r .68 at 11 games
    ['yac', 'YAC', r => num(r.yac), r => r.rec, 80, 'yards after catch'],                                   // r .20 at 20 catches
  ],
  OL: [
    ['passpro', 'Pass Protector', r => num(r.pbScore), snaps, 650, 'pass-block score'],                     // r .51 at 669 snaps
    ['runblock', 'Run Blocker', r => num(r.rbScore), snaps, 800, 'run-block score'],                        // r .46
    ['clean', 'Clean Pocket', r => neg(num(r.prsRate)), snaps, 730, 'pressure rate allowed'],               // r .48
  ],
  EDGE: [
    ['rusher', 'Pass Rusher', r => num(r.prsRate), snaps, 460, 'pressure rate'],                            // r .50 at 453 snaps
    ['runstop', 'Run Stopper', r => per(r.tkl, snaps(r)), snaps, 640, 'tackles a snap'],                    // r .42
    ['disruptor', 'Disruptor', r => per(r.tfl, snaps(r)), snaps, 2250, 'TFL a snap'],                       // r .17
  ],
  DL: [
    ['rusher', 'Pass Rusher', r => num(r.prsRate), snaps, 400, 'pressure rate'],                            // r .52 at 426 snaps
    ['runstop', 'Run Stopper', r => per(r.tkl, snaps(r)), snaps, 640, 'tackles a snap'],                    // r .41
    ['disruptor', 'Disruptor', r => per(r.tfl, snaps(r)), snaps, 1900, 'TFL a snap'],                       // r .19
  ],
  LB: [
    ['runstop', 'Run Stopper', r => per(r.tkl, snaps(r)), snaps, 650, 'tackles a snap'],                    // r .46 at 543 snaps
    ['tackler', 'Tackler', r => neg(num(r.mt)), r => r.tkl, 180, 'missed-tackle rate'],                     // r .28 at 69 tackles
    ['rusher', 'Pass Rusher', r => per(r.prs, snaps(r)), snaps, 790, 'pressures a snap'],                   // r .41
    ['disruptor', 'Disruptor', r => per(r.tfl, snaps(r)), snaps, 2170, 'TFL a snap'],                       // r .20
  ],
  CB: [
    ['coverage', 'Coverage', ccov, r => r.tar, 180, 'rating, catch rate allowed and forced incompletions'],  // r .18 at 38 targets
    ['ballhawk', 'Ballhawk', bhawk, r => r.tar, 160, 'INT + PBU a target'],                                  // r .19
  ],
  S: [
    ['coverage', 'Coverage', ccov, r => r.tar, 100, 'rating, catch rate allowed and forced incompletions'],  // r .20 at 25 targets
    ['ballhawk', 'Ballhawk', bhawk, r => r.tar, 75, 'INT + PBU a target'],                                   // r .24
  ],
};

// archetypes: [name, [badge group, ...], test on the player (frame) or null]; first listed wins ties.
// The last entry is the base archetype (no groups), for players without the badges for any other.
const W = p => p.wtLb || 0;
export const ARCHETYPES = {
  QB: [['dual-threat', [['scrambler'], ['accurate', 'deep']]], ['gunslinger', [['deep']]], ['field general', [['accurate']]],
       ['running QB', [['scrambler']]], ['pocket passer', []]],
  RB: [['complete back', [['elusive', 'breakaway', 'efficient'], ['catcher'], ['workhorse']]], ['receiving back', [['catcher']]],
       ['power back', [['efficient', 'workhorse']], p => W(p) >= 215], ['home-run hitter', [['breakaway', 'efficient']]], ['elusive back', [['elusive']]],
       ['workhorse back', [['workhorse']]], ['downhill runner', []]],
  WR: [['complete receiver', [['route', 'target'], ['deep'], ['yac', 'hands']]], ['deep threat', [['deep']]], ['YAC weapon', [['yac']]],
       ['alpha receiver', [['route', 'target']]], ['possession receiver', [['hands']]], ['complementary receiver', []]],
  TE: [['dual-threat TE', [['blocker'], ['catcher', 'yac']]], ['receiving TE', [['catcher', 'yac']]], ['blocking TE', [['blocker']]], ['hybrid TE', []]],
  OL: [['complete blocker', [['passpro', 'clean'], ['runblock']]], ['pass protector', [['passpro', 'clean']]], ['run blocker', [['runblock']]], ['balanced blocker', []]],
  EDGE: [['three-down end', [['rusher'], ['runstop', 'disruptor']]], ['speed rusher', [['rusher']], p => W(p) && W(p) < 255], ['power rusher', [['rusher']]],
         ['run defender', [['runstop', 'disruptor']]], ['two-way end', []]],
  DL: [['three-down tackle', [['rusher'], ['runstop', 'disruptor']]], ['pass rusher', [['rusher']]], ['nose tackle', [['runstop', 'disruptor']], p => W(p) >= 310],
       ['run defender', [['runstop', 'disruptor']]], ['nose tackle', [], p => W(p) >= 310], ['two-way tackle', []]],
  LB: [['two-way linebacker', [['runstop', 'tackler'], ['rusher', 'disruptor']]], ['blitzer', [['rusher']]],
       ['run defender', [['runstop', 'tackler', 'disruptor']]], ['stack linebacker', []]],
  CB: [['lockdown corner', [['coverage'], ['ballhawk']]], ['ballhawk', [['ballhawk']]], ['sticky corner', [['coverage']]], ['coverage corner', []]],
  S: [['centerfielder', [['coverage'], ['ballhawk']]], ['ballhawk safety', [['ballhawk']]], ['coverage safety', [['coverage']]],
      ['box safety', [], p => W(p) >= 208], ['two-way safety', []]],
};
export const MIN_SCORE = 2;

const pctOf = sorted => x => { let lo = 0, hi = sorted.length; while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < x) lo = m + 1; else hi = m; } return lo / sorted.length; };

// a composite: each stat z'd over the pool, averaged over the ones the row has
const composite = (fs, pool) => {
  const st = fs.map(f => { const xs = pool.map(p => f(p.row)).filter(v => v != null && isFinite(v)), m = xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
    return [m, Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / Math.max(1, xs.length)) || 1]; });
  return r => { let s = 0, c = 0; fs.forEach((f, i) => { const v = f(r); if (v != null && isFinite(v)) { s += (v - st[i][0]) / st[i][1]; c++; } }); return c ? s / c : null; };
};

// badges for every player with a season line and 100+ snaps: p.badges = [{ k, name, tier, pct, v, stat }],
// best first. players: [{ g, snaps, row }]
export function assignBadges(players, { minSnaps = 100 } = {}) {
  for (const p of players) p.badges = [];
  for (const [g, list] of Object.entries(BADGES)) {
    const pool = players.filter(p => p.g === g && p.row && (p.snaps ?? 0) >= minSnaps);
    for (const [k, name, val, vol, half, stat] of list) {
      const get = Array.isArray(val) ? composite(val, pool) : val;
      const xs = pool.map(p => ({ p, v: get(p.row), n: Math.max(0, num(vol(p.row)) ?? 0) })).filter(x => x.v != null && isFinite(x.v));
      if (xs.length < 20) continue;
      const nw = xs.reduce((a, x) => a + x.n, 0), m = nw ? xs.reduce((a, x) => a + x.n * x.v, 0) / nw : xs.reduce((a, x) => a + x.v, 0) / xs.length;
      for (const x of xs) x.reg = m + (x.v - m) * x.n / (x.n + half);
      const q = pctOf(xs.map(x => x.reg).sort((a, b) => a - b));
      for (const x of xs) {
        const pc = q(x.reg), t = TIERS.find(([, cut]) => pc >= cut);
        if (t) x.p.badges.push({ k, name, tier: t[0], pct: Math.round(100 * pc), v: x.v, stat });
      }
    }
  }
  for (const p of players) p.badges.sort((a, b) => TIER_PTS[b.tier] - TIER_PTS[a.tier] || b.pct - a.pct);
}

// the archetype from the badges (see the header); null without a season line
export function archetypeOf(p, { minSnaps = 100 } = {}) {
  const list = ARCHETYPES[p.g];
  if (!list || !p.row || (p.snaps ?? 0) < minSnaps) return null;
  const pts = Object.fromEntries((p.badges || []).map(b => [b.k, TIER_PTS[b.tier]]));
  let best = null, bestS = MIN_SCORE - 1e-9;
  for (const [name, groups, test] of list) {
    if (!groups.length) { if (!best && (!test || test(p))) return name; continue; }
    if (test && !test(p)) continue;
    const per = groups.map(gr => gr.reduce((a, k) => a + (pts[k] || 0), 0));
    if (per.some(s => s === 0)) continue;
    const s = per.reduce((a, b) => a + b, 0);
    if (s > bestS) { best = name; bestS = s; }
  }
  return best;
}

// the compact form for the page: "k:tier,k:tier" best first (names come from BADGE_NAMES on the page)
export const badgeCode = p => (p.badges || []).map(b => `${b.k}:${b.tier[0]}`).join(',') || null;
