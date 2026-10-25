(function () {
  if (window.__arkCfb) return; window.__arkCfb = true;
  var PER = 50, DATA = null;
  // each feeder's weighted contribution to the composite, in the order fetch_cfb.mjs writes `parts`
  var PARTS = [['talent', 'On3 order at the position (unranked: production + recruiting)'], ['production', 'Stat+ (PFN position score), 3 seasons, regressed; weight by position = fit to NFL careers'],
               ['age + class', 'age on a curve (outliers move most), class runway, first-year bonus scaled by position rarity of young contributors'], ['breakout', 'class year of first top-15% production season'],
               ['stats', 'badge stats predictive of NFL careers beyond production (QB Deep Ball, Accurate; RB, TE Pass Catcher; DT Run Stopper; LB Tackler), QBR, play-by-play rates stable season to season'], ['pedigree', '247 composite recruiting rating'],
               ['context', 'SOS (QB); supporting cast (QB, RB, WR, TE: teammate talent, refit each run); actual vs expected (play-by-play: targets, QB, down and distance, opponent)'], ['frame', 'height, weight vs drafted NFL players at the position (combine norms)']];
  // a player's stable key for links (#<board>:p=<key>): his ESPN id, else name and team
  function slug(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  function pid(r) { var m = /\/id\/(\d+)/.exec(r.espnl || ''); return m ? 'e' + m[1] : slug(r.name + ' ' + r.team); }
  window.__arkCfbPid = pid;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function f1(x) { return x == null ? '' : (+x).toFixed(1); }
  // the provisional badge (partials/prov.html, the same on every board); why = the tooltip's reason
  var PROV = {{ partial "prov.html" (dict "why" "@@") | jsonify }};
  function prov(why) { return PROV.replace('@@', esc(why)); }
  function zmoney(n) { return (n < 0 ? '−' : '+') + money(Math.abs(n)); }
  function money(n) { return n >= 1e6 ? '$' + (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : '$' + Math.round(n / 1e3) + 'K'; }
  function inches(h) { var m = /^(\d)\D+(\d+(?:\.\d+)?)/.exec(h || ''); return m ? m[1] * 12 + +m[2] : ''; }
  var dim = '<span class="cfb__dim">—</span>';
  // ESPN headshots through ESPN's image resizer (small for the list); a missing photo removes its frame
  function face(src, w) { return src ? 'https://a.espncdn.com/combiner/i?img=' + encodeURIComponent(src.replace(/^https?:\/\/a\.espncdn\.com/, '')) + '&w=' + w + '&h=' + Math.round(w * 0.727) + '&scale=crop&cquality=60' : null; }
  function faceHtml(src, cls, w) { var u = face(src, w); return u ? '<span class="pxframe ' + cls + '"><img src="' + esc(u) + '" alt="" loading="lazy" onerror="this.parentNode.remove()"></span>' : ''; }

  // position groups behind the group chips
  var GROUPS = { OL: ['OL'], DL: ['EDGE', 'DT'], OFF: ['QB', 'RB', 'WR', 'TE', 'OL'], DEF: ['EDGE', 'DT', 'LB', 'CB', 'S'], DB: ['CB', 'S'], 'K/P': ['K', 'P'] };
  // linemen by spot: OT (either side), G (either side), C; an interior lineman with no side counts at G and C
  var OL_SPOT = { LT: 'OT', RT: 'OT', ST: 'OT', OT: 'OT', T: 'OT', LG: 'G', RG: 'G', OG: 'G', G: 'G', C: 'C', IOL: 'IOL' };
  function posMatch(p, r) {
    if (p === 'OT' || p === 'G' || p === 'C') { var s = OL_SPOT[r.spot]; return r.pos === 'OL' && (s === p || (s === 'IOL' && p !== 'OT')); }
    return !p || r.pos === p || (GROUPS[p] && GROUPS[p].indexOf(r.pos) >= 0);
  }
  // running back roles (rbRole from fetch_cfb.mjs): the chip after RB, the full name and estimated snaps by down on hover
  var ROLES = { every: ['EVERY', 'Every Down Back'], early: ['EARLY', 'Early Down Back'], third: ['3RD', '3rd Down Back'] };
  // player badges (cfb_badges.mjs): [name, tier letter, percentile, stat], best first. Tiers are percentiles of the
  // stat regressed by volume, among the position's 100+ snap players: bronze 75th, silver 90th, gold 97th, platinum 99th
  var TIER = { p: ['Platinum', 4], g: ['Gold', 3], s: ['Silver', 2], b: ['Bronze', 1] };
  function nth(n) { var t = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th'; return n + t; }
  function badgeLine(b) { return TIER[b[1]][0] + ' ' + b[0] + ': ' + nth(b[2]) + ' pct at position, ' + b[3] + ' (regressed by volume)'; }
  function medals(r) { return r.badges ? '<span class="cfb__medals" title="' + esc(r.badges.map(badgeLine).join('\n')) + '">' + r.badges.slice(0, 4).map(function (b) { return '<i class="cfb__medal cfb__medal--' + b[1] + '"></i>'; }).join('') + '</span>' : ''; }
  function roleTitle(r) { return ROLES[r.rbRole][1] + (r.rbSd != null ? ': ~' + Math.round(r.rbSd * 100) + '% of standard-down, ~' + Math.round(r.rbPd * 100) + '% of passing-down snaps (est.)' : ''); }
  // Stat+: PFN's all-in-one score at the position (QB+, WR+, OLi…), or our K+ / P+ for specialists, put on an
  // OPS+-like scale in load(): 100 = the position's average (snap-weighted, within his division), 25 points per SD
  function rawStat(r) { return r.pfn != null ? r.pfn : r.kp; }
  function statOf(r) { return r.statPlus; }
  // college WAR (scripts/cfb_av.mjs): wins over a replacement starter, 12-game pace; specialists over an average one
  function warCell(r) {
    if (r.war == null) return dim;
    var t = r.pos === 'K' || r.pos === 'P' ? 'college WAR: points over an average ' + (r.pos === 'K' ? 'kicker' : 'punter') + ' a game x 12 games x .0189 wins per point'
      : 'college WAR: wins over a replacement ' + (r.div === 'FCS' ? 'FCS ' : '') + 'starter at the snap share, 12-game pace' + (r.snapShare != null ? ' · ' + Math.round(Math.min(1, r.snapShare) * 100) + '% of snaps' : '');
    return '<span title="' + esc(t) + '"' + (r.war < 0 ? ' class="cfb__down"' : r.war === 0 ? ' class="cfb__dim"' : '') + '>' + (+r.war).toFixed(2) + '</span>';
  }
  // WAA: wins over an average starter at his position (the position-adjusted view of WAR)
  function waaCell(r) {
    if (r.waa == null) return dim;
    return '<span title="wins over an average ' + (r.pos === 'K' ? 'kicker' : r.pos === 'P' ? 'punter' : r.pos + ' starter') + ', same snaps"' + (r.waa < 0 ? ' class="cfb__down"' : r.waa === 0 ? ' class="cfb__dim"' : '') + '>' + (r.waa > 0 ? '+' : '') + (+r.waa).toFixed(2) + '</span>';
  }
  // XV: WAR with quality from the parts of the stat line that track winning (scripts/cfb_av.mjs XV_W)
  function xvCell(r) {
    if (r.xv == null) return dim;
    var d = r.war != null ? r.xv - r.war : null;
    return '<span title="XV ' + (+r.xv).toFixed(2) + (d != null ? ' · ' + (d >= 0 ? '+' : '−') + Math.abs(d).toFixed(2) + ' vs WAR' : '') + '"' + (r.xv === 0 ? ' class="cfb__dim"' : '') + '>' + (+r.xv).toFixed(2) + '</span>';
  }
  // past-season grades (static/data/cfb-past.json, scripts/cfb_fv_refit.mjs --past): each FBS season graded the way
  // the FV backtest rebuilds a past board (production blend, pedigree, age and class, team, frame), today's scale, no
  // On3 grade or consensus (neither has history). r.past = [[season, fv, pos, team], ...], newest first
  var PAST_TIP = 'past FV: the board rebuilt as it stood after each FBS season (3-season production, recruiting pedigree, age and class, team strength, frame), graded on today\'s NFL scarcity scale. No On3 grade or draft consensus (no history), so it reads production more than FV does.';
  function chipOf(v, t) { return '<span class="fv-chip" data-fv="' + Math.max(20, Math.floor(v / 5) * 5) + '"' + (t ? ' title="' + esc(t) + '"' : '') + '>' + v + '</span>'; }
  function pastAt(r, s) { var x = pastOf(r, s); return x ? x[1] : null; }
  function sameTeam(a, b) { var n = function (x) { return String(x || '').toLowerCase().replace(/[^a-z]/g, ''); }; a = n(a); b = n(b); return a === b || a.indexOf(b) === 0 || b.indexOf(a) === 0; }
  function pastOf(r, s) { return (r.past || []).filter(function (p) { return p[0] === s; })[0] || null; }
  function pastNote(r, x) { return (x[2] !== r.pos ? x[2] : '') + (sameTeam(x[3], r.team) ? '' : (x[2] !== r.pos ? ' · ' : '') + x[3]); }
  function pastHtml(r) {
    if (!r.past || !r.past.length) return '';
    return '<p class="cfb__past" title="' + esc(PAST_TIP) + '"><span class="cfb__pastk">FV by season</span>' +
      (r.fv != null ? '<span class="cfb__pasts"><span class="cfb__dim">now</span>' + chipOf(r.fv) + '</span>' : '') +
      r.past.map(function (x) {
        var note = pastNote(r, x);
        return '<span class="cfb__pasts"><span class="cfb__dim">' + x[0] + '</span>' + chipOf(x[1]) + (note ? '<span class="cfb__pastnote">' + esc(note) + '</span>' : '') + '</span>';
      }).join('') + '</p>';
  }
  // historical comps (static/data/cfb-comps.json, scripts/cfb_comps.mjs): the nearest 2014-22 FBS profiles at his position
  // (production, years on campus, size, pedigree, team strength; weights picked held out) and what they did in the NFL.
  // Fetched with the first open dropdown. A comp file row: [name, school, season, pos, pick, AV a season, All-Pro, Pro Bowls]
  var COMPS_URL = null, COMPS = null;
  var COMP_TIP = 'comps: the nearest 2014-22 FBS player-seasons at his position by production, years on campus, height, weight, recruiting pedigree and team strength (weights picked by how well the comps\' NFL outcomes predict, one draft class held out), each player once. Shares weight nearer comps more. Starter = 3.7+ NFL AV a season (FV 50+). Descriptive: the comp mix did not improve the FV outlook held out, so it does not move FV.';
  function compsHtml(r) { return r.pos && /^(QB|RB|WR|TE|EDGE|DT|LB)$/.test(r.pos) ? '<div class="cfb__comps" data-comps="' + esc(r.name + '|' + r.team) + '"></div>' : ''; }
  function compRow(c) {
    var nfl = c[4] ? 'Rd ' + Math.min(7, Math.ceil(c[4] / 32)) + ', #' + c[4] : 'undrafted';
    var hon = (c[6] ? c[6] + 'x All-Pro' : '') + (c[6] && c[7] ? ', ' : '') + (c[7] ? c[7] + 'x Pro Bowl' : '');
    return '<li><b>' + esc(c[0]) + '</b> <span class="cfb__dim">' + esc(c[1]) + ' ' + c[2] + '</span> · ' + nfl + ' · ' + (+c[5]).toFixed(1) + ' AV/yr' + (hon ? ' · ' + hon : '') + '</li>';
  }
  function fillComps(root) {
    var el = root && root.querySelector('[data-comps]'); if (!el || !COMPS_URL) return;
    (COMPS || (COMPS = window.__arkJson(COMPS_URL).catch(function () { return null; }))).then(function (d) {
      var e = d && d.players[el.getAttribute('data-comps')]; if (!e) { el.remove(); return; }
      var m = e[3], pc = function (x) { return Math.round(x * 100) + '%'; };
      el.title = COMP_TIP;
      el.innerHTML = '<p class="cfb__past"><span class="cfb__pastk">Comps</span><span>his ' + m[0] + ' nearest profiles: ' + pc(m[1]) + ' drafted, ' + pc(m[2]) + ' first round, ' + pc(m[3]) + ' NFL starters</span></p>' +
        '<ul class="cfb__compl">' + e.slice(0, 3).map(function (x) { return compRow(d.pool[x[0]]); }).join('') + '</ul>';
    });
  }
  function statLabel(r) { return r.pfn != null ? r.pfnLabel || 'PFN' : r.pos + '+'; }
  // Transfer% (cfb_transfer.mjs): odds he plays for another team next season; hover for stay odds and the reasons
  function pct(x) { return x < 0.005 ? '&lt;1%' : Math.min(99, Math.round(x * 100)) + '%'; }
  function xferCell(r) {
    if (r.transferP == null) return dim;
    var t = 'Transfer% ' + Math.round(r.transferP * 100) + '% · stays ' + Math.round((r.stayP || 0) * 100) + '% · leaves (draft or eligibility) ' + Math.round(Math.max(0, 1 - r.transferP - (r.stayP || 0)) * 100) + '%' +
      (r.homeMi != null ? '\n' + r.homeMi + ' mi from home' + (r.inState ? ' (home state)' : '') : '') + (r.tWhy && r.tWhy.length ? '\n' + r.tWhy.join('\n') : '');
    return '<span title="' + esc(t) + '" class="' + (r.transferP >= 0.3 ? 'cfb__xhot' : r.transferP < 0.05 ? 'cfb__dim' : '') + '">' + pct(r.transferP) + '</span>';
  }
  // multi-position eligibility: spots he has played (PFN graded him there, 100+ snaps in a season) and spots the
  // position-change model gives 25%+; the flagged move has its own chip
  function multiOf(r) { return (r.multi || []).filter(function (m) { return m.pos !== r.move && !(r.move === 'IOL' && (m.pos === 'G' || m.pos === 'C')); }); }
  function multiLine(r) {
    var yrs = function (s) { return s.length > 1 ? s[0] + '-' + String(s[s.length - 1]).slice(2) : String(s[0]); };
    return (r.multi || []).map(function (m) {
      return m.pos + (m.how === 'played' ? ' (played ' + yrs(m.seasons) + ', ' + m.snaps + ' snaps' + (m.odds != null ? '; ' + Math.round(m.odds * 100) + '% NFL fit' : '') + ')' : ' (' + Math.round(m.odds * 100) + '% NFL fit)');
    }).join(' · ');
  }
  function rowHtml(r, rk, opt, prk) {
    prk = prk || r.posRank;
    opt = opt || {};
    var fv = r.fv == null ? '' : r.fv + (r.plus ? '+' : ''), tier = r.fv == null ? '' : (Math.floor(r.fv / 5) * 5) + (r.plus ? '+' : '');
    // a past year in view: that season's grade in the FV column, the school and position then under the school
    var yx = opt.yr ? pastOf(r, opt.yr) : null, ynote = yx && !sameTeam(yx[3], r.team) ? yx[3] : '';
    var age = r.age != null ? r.age : r.ageEst, d = r.delta;
    var delta = d === 'new' ? '<span class="cfb__new">new</span>' : d > 0 ? '<span class="cfb__up">▲' + d + '</span>' : d < 0 ? '<span class="cfb__down">▼' + (-d) + '</span>' : '';
    return '<tr data-pos="' + r.pos + '" data-cls="' + esc(r.elig) + '" data-age="' + esc(age) + '" data-fv="' + esc(r.fv) + '" data-conf="' + esc(r.conf) +
      '" data-d27="' + (r.draft27 ? 1 : 0) + '" data-q="' + esc((r.name + ' ' + r.team).toLowerCase()) +
      '" data-rk="' + r.ovr + '" data-name="' + esc(r.name) + '" data-team="' + esc(r.team) + '" data-ht="' + inches(r.ht) + '" data-wt="' + esc(r.wt) +
      '" data-cons="' + esc(r.cons) + '" data-xnil="' + esc(r.xnil) + '" data-prk="' + esc(r.posRank) +
      '" data-delta="' + (typeof d === 'number' ? d : '') + '" data-i="' + r.i + '">' +
      '<td class="cfb__rk"' + (opt.rankBy === 'war' ? ' title="WAR rank among the players in view · #' + r.ovr + ' overall by FV"' : rk && rk !== r.ovr ? ' title="#' + r.ovr + ' overall"' : '') + '>' + (rk || r.ovr) + '</td><td class="cfb__name">' + faceHtml(r.photo, 'pxframe--row', 96) +
      '<button type="button" class="cfb__who" aria-expanded="false">' + esc(r.name) + '</button>' +
      (opt.rankBy === 'war' && r.war != null ? '<b class="cfb__warin">' + (+r.war).toFixed(2) + '</b>' : '') + (r.star ? '<span class="cfb__star" title="ARKLIST">★</span>' : '') + (r.carried ? ' <span class="cfb__carried" title="PFN stopped listing him after ' + esc(r.carried) + ': his last grade is kept">carried</span>' : '') + (r.src === 'espn' ? ' ' + prov('on the ESPN roster, not on PFN: graded up from the 20 floor on position, size, NFL frame and BMI, class, age for class, division and recruiting') : '') +
      (r.riser ? '<span class="cfb__riser" title="riser: ' + esc(r.riserWhy) + '">↗</span>' : '') +
      (r.inj ? '<span class="cfb__injchip" title="' + esc(r.inj) + '">' + (/season/i.test(r.inj) ? 'OFS' : r.inj === 'Out' ? 'O' : r.inj.charAt(0)) + '</span>' : '') +
      (r.moveUp ? '<span class="cfb__upchip" title="FCS move-up candidate: FBS% ' + Math.round(r.up * 100) + '% (P on an FBS roster next season)">▲FBS</span>' : '') +
      (r.move ? '<span class="cfb__movechip" title="position change: could move to ' + esc(r.move) + (r.moveOdds != null ? ' (' + Math.round(r.moveOdds * 100) + '%)' : '') + '. ' + esc(r.moveWhy) + '">⇄' + esc(r.move) + '</span>' : '') +
      (multiOf(r).length ? '<span class="cfb__multichip" title="multi-position: ' + esc(multiLine(r)) + '">+' + esc(multiOf(r).map(function (m) { return m.pos; }).join('/')) + '</span>' : '') + '</td>' +
      (opt.rankBy === 'war' ? '<td class="cfb__num cfb__war">' + warCell(r) + '</td><td class="cfb__num">' + waaCell(r) + '</td><td class="cfb__num">' + xvCell(r) + '</td>' : '') +
      (yx ? '<td class="cfb__pos-cell" title="' + opt.yr + ' position (graded on PFN\'s ' + yx[2] + ' board)' + (yx[2] !== r.pos ? ' · now ' + r.pos : '') + '">' + yx[2] + (prk ? '<span title="rank at position in ' + opt.yr + ', players in view">' + prk + '</span>' : '') + '</td>' :
      '<td class="cfb__pos-cell"' + (r.arch ? ' title="' + esc(r.arch) + (ROLES[r.rbRole] ? ' · ' + ROLES[r.rbRole][1] : '') + '"' : '') + '>' + r.pos + (prk ? '<span title="rank at position, players in view, by ' + (opt.rankBy === 'war' ? 'WAR' : 'FV') + (prk !== r.posRank && r.posRank ? ' · ' + r.pos + r.posRank + ' overall' : '') + '">' + prk + '</span>' : '') + (r.spot ? '<span class="cfb__dim">·' + esc(r.pos === 'OL' && OL_SPOT[r.spot] && OL_SPOT[r.spot] !== 'IOL' ? OL_SPOT[r.spot] : r.spot) + '</span>' : '') + (ROLES[r.rbRole] ? '<span class="cfb__rbrole" title="' + esc(roleTitle(r)) + '">' + ROLES[r.rbRole][0] + '</span>' : '') + medals(r) + '</td>') +
      '<td class="cfb__team">' + (r.logo ? '<img class="cfb__logo" src="' + esc(r.logo) + '" alt="" width="20" height="20" loading="lazy">' : '') + '<span>' + esc(r.team) + (opt.div && r.div === 'FCS' ? '<span class="cfb__divtag" title="FCS: graded vs FCS players, translated to the FBS scale">FCS</span>' : '') + (ynote ? '<span class="cfb__pastnote">' + opt.yr + ': ' + esc(ynote) + '</span>' : '') + '</span></td>' +
      (yx ? '<td class="fv cfb__g">' + chipOf(yx[1], opt.yr + ' FV ' + yx[1] + ' (backtest model: production, pedigree, age, team; no On3 or consensus) · FV now ' + (r.fv == null ? '—' : fv)) + '</td>' :
      '<td class="fv cfb__g">' + (fv ? '<span class="fv-chip" data-fv="' + tier + '"' + (r.fvx != null ? ' title="FV ' + (+r.fvx).toFixed(2) + '; decimals break ties"' : '') + '>' + fv + '</span>' : dim) + '</td>') +
      '<td class="cfb__delta cfb__now">' + delta + '</td>' +
      '<td class="cfb__num cfb__now">' + (statOf(r) == null ? dim : '<span title="' + esc(statLabel(r)) + ' ' + f1(rawStat(r)) + ' → ' + statOf(r) + ' (100 = average ' + r.pos + ', 25 = one SD)' + (r.snaps ? ' · ' + r.snaps + ' snaps' : '') + '">' + statOf(r) + '</span>') + '</td>' +
      (opt.rankBy === 'war' ? '' : '<td class="cfb__num cfb__now">' + warCell(r) + '</td>') +
      (opt.draft ? '<td class="cfb__num cfb__now">' + (r.cons == null ? dim : '<span title="#' + r.consRk + ' on the consensus board · ' + r.consN + ' of 10 boards">' + f1(r.cons) + '</span>') + '</td>' : '') +
      (opt.draft ? '<td class="cfb__num cfb__now">' + (r.draftP == null ? dim : r.draftP < 0.005 ? '<span class="cfb__dim">&lt;1%</span>' : Math.min(99, Math.round(r.draftP * 100)) + '%') + '</td>' : '') +
      (opt.up ? '<td class="cfb__num cfb__now">' + (r.up != null ? '<span' + (r.moveUp ? ' class="cfb__upv"' : '') + '>' + Math.round(r.up * 100) + '%</span>' : dim) + '</td>' : '') +
      '<td class="cfb__num cfb__now">' + xferCell(r) + '</td>' +
      (opt.nil !== false ? '<td class="cfb__num cfb__g cfb__now">' + (r.xnil ? '<span class="cfb__nil">' + money(r.xnil) + '</span>' : dim) + '</td>' +
        '<td class="cfb__num cfb__now">' + (r.ynil != null ? money(r.ynil) : dim) + '</td>' +
        '<td class="cfb__num cfb__now">' + (r.znil != null ? '<span class="' + (r.znil >= 0 ? 'cfb__up' : 'cfb__down') + '">' + zmoney(r.znil) + '</span>' : dim) + '</td>' : '') +
      '<td class="cfb__g">' + esc(r.cls || '—') + '</td>' +
      '<td class="cfb__num">' + (r.age != null ? f1(r.age) : r.ageEst != null ? '<span class="cfb__dim" title="estimated from class year">~' + f1(r.ageEst) + '</span>' : '—') + '</td>' +
      '<td class="cfb__num">' + esc(r.ht || '—') + ' / ' + esc(r.wt || '—') + (r.bmi ? ' <span class="cfb__dim">· ' + f1(r.bmi) + '</span>' : '') + '</td></tr>';
  }

  // the scouting report: role, + strengths and − concerns, links, and the feeder bars underneath
  function detailHtml(r, cols, width) {
    var z = r.parts || [], sum = 0;
    var bars = PARTS.map(function (p, i) {
      if (i === 0 && r.div === 'FCS') p = ['level', 'FCS: team and conference strength (SRS, this season, FBS + FCS games); replaces On3 grade'];
      var v = z[i] || 0, w = Math.min(50, Math.abs(v) / 2 * 50); sum += v;
      return '<li title="' + p[1] + '"><span class="cfb__bk">' + p[0] + '</span><span class="cfb__meter"><i class="' + (v < 0 ? 'is-neg' : '') + '" style="' +
        (v < 0 ? 'right:50%' : 'left:50%') + ';width:' + w + '%"></i></span><span class="cfb__bv">' + (v > 0 ? '+' : '') + v.toFixed(2) + '</span></li>';
    }).join('');
    var rep = r.report || {}, links = [['On3', r.on3l], ['ESPN', r.espnl]].filter(function (l) { return l[1]; })
      .map(function (l) { return '<a href="' + esc(l[1]) + '" rel="noopener">' + l[0] + ' profile ↗</a>'; }).join(' · ');
    var li = function (xs, cls) { return (xs || []).map(function (x) { return '<li class="' + cls + '">' + esc(x) + '</li>'; }).join(''); };
    return '<tr class="cfb__detail"><td colspan="' + cols + '"><div class="cfb__dwrap" style="width:' + width + 'px">' + faceHtml(r.photo, 'pxframe--card', 280) +
      '<p class="cfb__dhead"><b>' + esc(r.name) + '</b>' + (r.star ? '<span class="cfb__star" title="ARKLIST">★</span>' : '') + (r.riser ? ' <span class="cfb__riser">↗ riser</span>' : '') + (r.carried ? ' <span class="cfb__carried">carried over: last listed by PFN ' + esc(r.carried) + '</span>' : '') + (r.src === 'espn' ? ' ' + prov('on the ESPN roster, not on PFN: graded up from the 20 floor on position, size, NFL frame and BMI, class, age for class, division and recruiting') : '') + (r.inj ? ' <span class="cfb__injchip">' + esc(r.inj) + '</span>' : '') + ' · ' + esc(r.pos) + ' · ' + esc(r.team) + ' · FV ' + esc(r.fv) + (r.plus ? '+' : '') +
      (r.posRank ? ' (' + r.pos + r.posRank + ')' : '') + (r.xnil ? ' · xNIL ' + money(r.xnil) + (r.ynil != null ? ' · yNIL ' + money(r.ynil) + ' · zNIL <span class="' + (r.znil >= 0 ? 'cfb__up' : 'cfb__down') + '">' + zmoney(r.znil) + '</span>' : '') : '') + (r.on3 != null ? ' · On3 ' + r.on3 : '') +
      (r.consRk != null ? ' · consensus #' + r.consRk : '') + (r.draftP != null ? ' · Draft ' + (r.draftP < 0.005 ? '&lt;1' : Math.min(99, Math.round(r.draftP * 100))) + '%' : '') + (links ? ' · ' + links : '') +
      ' <button type="button" class="cfb__btn cfb__cardbtn" data-gfx data-gfx-mode="card" data-gfx-i="' + r.i + '" data-gfx-name="' + esc(r.name) + '" title="player card graphic (4:5)">GFX card</button></p>' +
      (r.move || r.moveUp ? '<p class="cfb__role">' + (r.moveUp ? '<span class="cfb__upchip">▲FBS</span> move-up candidate: FBS% ' + Math.round(r.up * 100) + '% (P on an FBS roster next season). ' : '') +
        (r.move ? '<span class="cfb__movechip">⇄' + esc(r.move) + '</span> could move to ' + esc(r.move) + (r.moveOdds != null ? ' (' + Math.round(r.moveOdds * 100) + '%)' : '') + ': ' + esc(r.moveWhy) + '.' : '') + '</p>' : '') +
      (multiOf(r).length ? '<p class="cfb__role"><span class="cfb__multichip">+' + esc(multiOf(r).map(function (m) { return m.pos; }).join('/')) + '</span> multi-position: ' + esc(multiLine(r)) + '.</p>' : '') +
      // mock sims (mockSims, scripts/cfb_teams.mjs): [P(round 1), 80% pick range low, high (null: past the last pick), likeliest team, its share]
      (r.mk ? '<p class="cfb__role">Mock sims: round 1 ' + pct(r.mk[0]) + ', picks ' + r.mk[1] + '-' + (r.mk[2] == null ? 'UDFA' : r.mk[2]) + ' in 80% of simulated drafts, likeliest team ' + esc(r.mk[3]) + ' (' + pct(r.mk[4]) + ').</p>' : '') +
      (r.transferP != null ? '<p class="cfb__role"><span class="cfb__xchip">⇆ ' + pct(r.transferP) + '</span> Transfer%: ' + pct(r.transferP) + ' elsewhere next season, ' + pct(r.stayP || 0) + ' stay' +
        (1 - r.transferP - (r.stayP || 0) > 0.05 ? ', ' + pct(1 - r.transferP - (r.stayP || 0)) + ' exit (draft, eligibility)' : '') + '.' +
        (r.homeMi != null ? ' <span class="cfb__dim">' + r.homeMi + ' mi from home' + (r.inState ? ', home state' : '') + '.</span>' : '') +
        (r.tWhy && r.tWhy.length ? ' <span class="cfb__dim">' + esc(r.tWhy.join(' · ')) + '</span>' : '') + '</p>' : '') +
      (rep.role ? '<p class="cfb__role">role: ' + esc(rep.role) + '.' + (rep.type ? ' <span class="cfb__dim">type: ' + esc(rep.type) + '</span>' : '') + (rep.line ? ' <span class="cfb__dim">' + esc(rep.line) + '</span>' : '') + '</p>' : '') +
      (r.badges ? '<p class="cfb__badges">' + r.badges.map(function (b) { return '<span class="cfb__bdg cfb__bdg--' + b[1] + '" title="' + esc(badgeLine(b)) + '">' + TIER[b[1]][0] + ' ' + esc(b[0]) + '</span>'; }).join('') + '</p>' : '') +
      pastHtml(r) + window.arkFvo(r.fvd, 'cfb') + compsHtml(r) +
      '<div class="cfb__report"><div><h4>+ strengths</h4><ul>' + (li(rep.plus, 'is-plus') || '<li class="cfb__dim">none</li>') + '</ul></div>' +
      '<div><h4>− concerns</h4><ul>' + (li(rep.minus, 'is-minus') || '<li class="cfb__dim">none</li>') + '</ul></div></div>' +
      '<details class="cfb__nums"><summary>FV inputs</summary><ul class="cfb__parts">' + bars + '</ul><p class="cfb__dim">composite ' + (sum >= 0 ? '+' : '') + sum.toFixed(2) +
      '. FV: composite ranked within position, regressed toward the mean by reliability, graded by NFL scarcity' +
      (r.div === 'FCS' ? ' (FCS: ranked among FCS players, translated to the FBS scale; one NFL scarcity scale for both divisions)' : '') + '.</p></details></div></td></tr>';
  }

  // sort keys: the record field (or derived value) behind each header's data-sort
  var KEY = {
    rk: function (r) { return r.ovr; },   // same order as the board rank
    name: function (r) { return r.name; },
    // the grade shown first (60+ above 60), the unrounded grade inside it: the board's own order
    fv: function (r) { return r.fv == null ? null : r.fv * 1000 + (r.plus ? 500 : 0) + (r.fvx != null ? r.fvx : r.fv); },
    delta: function (r) { return typeof r.delta === 'number' ? r.delta : null; }, pos: function (r) { return r.pos + String(r.ovr || 999999).padStart(6, '0'); },   // position, then FV order in it (the rank shown counts FBS and FCS together)
    team: function (r) { return r.team; }, cls: function (r) { return r.elig; },
    age: function (r) { return r.age != null ? r.age : r.ageEst; }, ht: function (r) { return inches(r.ht) || null; },
    cons: function (r) { return r.cons; }, stat: statOf, xnil: function (r) { return r.xnil; }, ynil: function (r) { return r.ynil; }, znil: function (r) { return r.znil; },
    up: function (r) { return r.up; }, draft: function (r) { return r.draftP; }, xfer: function (r) { return r.transferP; },
    war: function (r) { return r.war; }, waa: function (r) { return r.waa; }, xv: function (r) { return r.xv; },
  };

  // filtering and sorting run on the records; only the 50 rows of the current page are ever in the
  // DOM, so a phone never lays out thousands of rows
  function setup(w, data) {
    var bar = w.querySelector('[data-cfb-bar]'), body = w.querySelector('tbody'), id = w.getAttribute('data-cfb'),
        preset = w.getAttribute('data-cfb-preset'), count = w.querySelector('[data-cfb-count]'), none = w.querySelector('[data-cfb-none]'),
        pager = w.querySelector('[data-cfb-pager]'), atEl = w.querySelector('[data-cfb-page]'), ofEl = w.querySelector('[data-cfb-pages]'),
        cols = w.querySelectorAll('thead th').length, open = null, openP = '', pos = '', page = 0, match = [];
    var recs = data.filter(function (r) { return (preset !== 'd27' || r.draft27) && (preset !== 'star' || r.star) && (preset !== 'fbs' || r.div !== 'FCS') && (preset !== 'fcs' || r.div === 'FCS'); }), byI = {}, RK = {};
    var opt = { up: w.hasAttribute('data-cfb-up'), draft: w.hasAttribute('data-cfb-draft'), nil: true, div: preset !== 'fbs' && preset !== 'fcs', rankBy: preset === 'war' ? 'war' : 'fv',
      yr: 0 };
    var gfxCols = w.getAttribute('data-gfx-cols') || '';
    // the WAR leaderboard: ranks (and the default order) by college WAR, highest first, FV breaking ties
    var byWar = function (a, b) { return (b.war == null ? -99 : b.war) - (a.war == null ? -99 : a.war) || a.ovr - b.ovr; };
    if (opt.rankBy === 'war') recs.sort(byWar);
    // archetype list for the "type" filter, from the players on this board
    var archSel = bar.querySelector('[data-cfb-arch]');
    if (archSel) { var seen = {}; recs.forEach(function (r) { if (r.arch) seen[r.arch] = 1; });
      Object.keys(seen).sort().forEach(function (a) { var o = document.createElement('option'); o.textContent = a; archSel.appendChild(o); }); }
    var bdgSel = bar.querySelector('[data-cfb-badge]');
    if (bdgSel) { var bs = {}; recs.forEach(function (r) { (r.badges || []).forEach(function (b) { bs[b[0]] = 1; }); });
      Object.keys(bs).sort().forEach(function (a) { var o = document.createElement('option'); o.textContent = a; bdgSel.appendChild(o); }); }
    // RK and the position rank (TE3) count only the players in view: this tab plus its filters (the search box
    // aside), in FV order whatever the sort. apply() refills RK and PRK; the global ranks show on hover
    var PRK = {};
    recs.forEach(function (r) { byI[r.i] = r; r._q = r._q || (r.name + ' ' + r.team).toLowerCase(); });
    var chips = [].slice.call(bar.querySelectorAll('[data-pos]'));
    function val(n) { var el = bar.elements[n]; return !el ? '' : el.type === 'checkbox' ? (el.checked ? '1' : '') : el.value; }
    function setPos(p) { pos = p; chips.forEach(function (c) { var on = c.dataset.pos === p; c.classList.toggle('is-on', on); c.setAttribute('aria-pressed', on); }); }
    function closeDetail() {
      if (open) { open.remove(); open = null; }
      body.querySelectorAll('.cfb__who[aria-expanded="true"]').forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
    }
    function show() {         // render the current page of the matching records
      open = null; openP = '';
      var pages = Math.max(1, Math.ceil(match.length / PER));
      page = Math.min(Math.max(page, 0), pages - 1);
      body.innerHTML = match.slice(page * PER, page * PER + PER).map(function (r) { return rowHtml(r, RK[r.i], opt, PRK[r.i]); }).join('');
      atEl.textContent = page + 1; ofEl.textContent = pages; pager.hidden = pages < 2;
    }
    function apply(keepPage) {
      var q = val('q').trim().toLowerCase(), cls = val('cls'), age = parseFloat(val('age')), fv = parseFloat(val('fv')),
          conf = val('conf'), team = val('team'), d27 = val('d27'), div = val('div'), arch = val('arch'), role = val('role'), up = val('up'), mv = val('mv'),
          badge = val('badge'), tier = +val('tier') || 0, yr = +val('yr') || 0;
      // a past year: only players graded that season, ranked by that season's grade; columns that only exist for
      // this season (Δ, Stat+, WAR, Transfer%, NIL, draft odds) step aside
      opt.yr = yr; w.classList.toggle('is-yr', !!yr);
      if (gfxCols) w.setAttribute('data-gfx-cols', yr ? gfxCols.split(',').filter(function (c) { return !/^(xNIL|FBS%|Draft%|WAR|Stat\+)$/.test(c); }).join(',') : gfxCols);
      var fvOf = function (r) { return yr ? pastAt(r, yr) : r.fv; };
      var posOf = function (r) { var x = yr && pastOf(r, yr); return x ? x[2] : r.pos; };
      var view = recs.filter(function (r) {
        if (yr && pastAt(r, yr) == null) return false;
        var a = r.age != null ? r.age : r.ageEst;
        return posMatch(pos, yr ? { pos: posOf(r), spot: r.spot } : r) && (!cls || String(r.elig) === cls) &&
          (isNaN(age) || (a != null && a <= age)) && (isNaN(fv) || (fvOf(r) != null && fvOf(r) >= fv)) && (!conf || r.conf === conf) &&
          (!team || r.team === team) && (!d27 || r.draft27) && (!div || (r.div || 'FBS') === div) && (!arch || r.arch === arch) && (!role || r.rbRole === role) &&
          (!(badge || tier) || (r.badges || []).some(function (b) { return (!badge || b[0] === badge) && TIER[b[1]][1] >= tier; })) &&
          (!up || r.moveUp) && (!mv || r.move);
      });
      RK = {}; PRK = {}; var seenPos = {};
      var byYr = function (a, b) { return pastAt(b, yr) - pastAt(a, yr) || a.ovr - b.ovr; };
      view.slice().sort(opt.rankBy === 'war' ? byWar : yr ? byYr : function (a, b) { return a.ovr - b.ovr; }).forEach(function (r, i) {
        RK[r.i] = i + 1; if (opt.rankBy === 'war' ? r.war != null : fvOf(r) != null) PRK[r.i] = seenPos[posOf(r)] = (seenPos[posOf(r)] || 0) + 1; });
      // the default order (RK) follows the year's ranks
      if (yr && cur === 'rk') view.sort(function (a, b) { return (RK[a.i] - RK[b.i]) * dir; });
      match = q ? view.filter(function (r) { return r._q.indexOf(q) >= 0; }) : view;
      if (!keepPage) page = 0;
      count.textContent = match.length + (match.length === recs.length ? '' : ' of ' + recs.length) + ' players';
      none.hidden = match.length > 0;
      var tog = bar.querySelector('[data-cfb-active]');
      if (tog) { var k = (pos ? 1 : 0) + ['yr', 'cls', 'age', 'fv', 'conf', 'team', 'd27', 'div', 'arch', 'badge', 'tier', 'role', 'up', 'mv'].filter(function (x) { return val(x); }).length; tog.textContent = k ? '(' + k + ')' : ''; }
      show(); writeHash();
    }
    function writeHash() {
      var s = [];
      if (pos) s.push('pos=' + pos);
      ['q', 'yr', 'team', 'cls', 'age', 'fv', 'conf', 'd27', 'div', 'arch', 'badge', 'tier', 'role', 'up', 'mv'].forEach(function (k) { var v = val(k); if (v) s.push(k + '=' + encodeURIComponent(v)); });
      if (cur !== sort0[0] || dir !== sort0[1]) s.push('s=' + cur, 'd=' + dir);
      if (openP) s.push('p=' + openP);
      var h = s.length ? '#' + id + ':' + s.join('&') : '', at = location.hash.indexOf('#' + id + ':') === 0 ? location.hash : '';
      if (h !== at && (h || at)) history.replaceState(null, '', location.pathname + location.search + h);
    }
    var want = {};   // s, d and p from a shared link, used once the rows are built
    function readHash() {
      if (location.hash.indexOf('#' + id + ':') !== 0) return false;
      location.hash.slice(id.length + 2).split('&').forEach(function (kv) {
        var i = kv.indexOf('='), k = kv.slice(0, i), v = decodeURIComponent(kv.slice(i + 1)), el = bar.elements[k];
        if (k === 's' || k === 'd' || k === 'p') want[k] = v;
        else if (k === 'pos') setPos(v); else if (el) { if (el.type === 'checkbox') el.checked = v === '1'; else el.value = v; }
      });
      return true;
    }
    // open a player's report from the link: his page of the board, his row, the report under it
    function openWanted() {
      var p = want.p; want = {}; if (!p) return;
      var k = -1; match.some(function (r, j) { if (pid(r) === p) { k = j; return true; } return false; });
      if (k < 0) return;
      page = Math.floor(k / PER); show();
      var tr = body.querySelector('tr[data-i="' + match[k].i + '"]');
      if (tr) { tr.click(); setTimeout(function () { tr.scrollIntoView({ block: 'center' }); }, 80); }
    }
    var tg = bar.querySelector('[data-cfb-toggle]');
    if (tg) tg.addEventListener('click', function () { var on = bar.classList.toggle('is-open'); tg.setAttribute('aria-expanded', on); });
    var typing = null;     // the search box re-filters after a short pause, not on every keystroke
    bar.addEventListener('input', function (e) { clearTimeout(typing); if (e.target.name === 'q') typing = setTimeout(function () { apply(); }, 150); else apply(); });
    bar.addEventListener('change', function (e) { if (e.target.name !== 'q') apply(); });
    bar.addEventListener('reset', function () { setTimeout(function () { setPos(''); apply(); }); });
    chips.forEach(function (c) { c.addEventListener('click', function () { setPos(pos === c.dataset.pos ? '' : c.dataset.pos); apply(); }); });
    pager.querySelectorAll('[data-cfb-step]').forEach(function (b) { b.addEventListener('click', function () {
      page += +b.getAttribute('data-cfb-step'); show();
      var top = w.getBoundingClientRect().top; if (top < 0) w.scrollIntoView({ block: 'start' });
    }); });
    body.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      var tr = e.target.closest('tr'); if (!tr || tr.classList.contains('cfb__detail')) return;
      var was = open && open.previousElementSibling === tr;
      closeDetail(); openP = ''; if (was) return writeHash();
      openP = pid(byI[tr.dataset.i]); writeHash();
      var sc = w.querySelector('.cfb__scroll');
      tr.insertAdjacentHTML('afterend', detailHtml(byI[tr.dataset.i], cols, Math.max(260, sc.clientWidth - 30)));
      open = tr.nextElementSibling; fillComps(open);
      var who = tr.querySelector('.cfb__who'); if (who) who.setAttribute('aria-expanded', 'true');
    });
    var ths = [].slice.call(w.querySelectorAll('th[data-sort]')), cur = opt.rankBy === 'war' ? 'war' : 'rk', dir = opt.rankBy === 'war' ? -1 : 1, sort0 = [cur, dir];
    ths.forEach(function (th) {
      th.tabIndex = 0;
      function go() {
        var k = th.dataset.sort, num = th.hasAttribute('data-num'), asc = !num || /^(rk|age|cls|cons)$/.test(k), get = k === 'rk' && opt.rankBy === 'war' ? function (r) { return r.war == null ? 99 : -r.war; } : k === 'fv' && opt.yr ? function (r) { return pastAt(r, opt.yr); } : KEY[k] || function (r) { return r[k]; };
        dir = k === cur ? -dir : (asc ? 1 : -1); cur = k;
        recs.sort(function (a, b) {
          var x = get(a), y = get(b);
          if (num) { x = x == null || x === '' ? NaN : +x; y = y == null || y === '' ? NaN : +y; if (isNaN(x)) return isNaN(y) ? a.ovr - b.ovr : 1; if (isNaN(y)) return -1; return (x - y) * dir || (a.ovr - b.ovr); }
          return String(x == null ? '' : x).localeCompare(String(y == null ? '' : y)) * dir || (a.ovr - b.ovr);
        });
        ths.forEach(function (h) { h.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir > 0 ? 'ascending' : 'descending');
        apply();
      }
      th.__go = go;
      th.addEventListener('click', go);
      th.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
    bar.hidden = false;
    if (readHash()) {     // a shared link: open the tab this window sits in
      var panel = w.closest('[data-tab]'), group = panel && panel.parentElement.closest('[data-wintabs]');
      var tab = group && group.querySelector('[data-wintab="' + panel.getAttribute('data-tab') + '"]');
      if (tab) tab.click();
      if (!want.p) setTimeout(function () { w.scrollIntoView({ block: 'start' }); });
    }
    var sth = want.s && ths.filter(function (t) { return t.dataset.sort === want.s; })[0];
    if (sth) { sth.__go(); if (String(dir) !== want.d) sth.__go(); } else apply();
    openWanted();
  }

  function load(src) {
    var json = window.__arkJson;
    COMPS_URL = src.replace(/cfb-all\.json$/, 'cfb-comps.json');
    if (!DATA) DATA = Promise.all([json(src), json(src.replace(/cfb-all\.json$/, 'cfb-past.json')).catch(function () { return null; })]).then(function (res) {
      var d = res[0], past = res[1];
      var recs = d.rows.map(function (a, i) { var r = { i: i }; d.cols.forEach(function (c, j) { r[c] = a[j]; }); return r; });
      // photo 1 = ESPN's standard headshot for his ESPN id (scripts/fetch_cfb.mjs photoCode)
      recs.forEach(function (r) { if (r.photo === 1) { var m = /\/id\/(\d+)/.exec(r.espnl || ''); r.photo = m ? 'https://a.espncdn.com/i/headshots/college-football/players/full/' + m[1] + '.png' : null; } });
      // interior linemen are DT on the site (the data keys them DL; DL here is the whole line, DT + EDGE)
      var dt = function (x) { return typeof x === 'string' ? x.replace(/\bDL\b/g, 'DT') : x; };
      // the ARKLIST star from data/arklist.json as built, so a name added there shows before the next data run
      // (names matched by the shared rules in namekey.html, so "Neo" finds "Neoklis" and "Will" finds "William")
      var ark = []; [].forEach.call(document.querySelectorAll('[data-arklist]'), function (el) { ark = ark.concat(JSON.parse(el.getAttribute('data-arklist') || '[]')); });
      ark.forEach(function (e) { var b = String(e).split('|'); window.arkName.find(recs, b[0].trim(), b[1] && b[1].trim()).forEach(function (r) { r.star = true; }); });
      recs.forEach(function (r) { r.pos = dt(r.pos); r.move = dt(r.move); r.moveWhy = dt(r.moveWhy);
        if (r.report) { r.report.role = dt(r.report.role); ['plus', 'minus'].forEach(function (k) { if (r.report[k]) r.report[k] = r.report[k].map(dt); }); } });
      // Stat+ = 100 + 25 z, z against the snap-weighted mean and SD at his position and division (K and P: unweighted).
      // 25 a SD gives OPS+'s spread: ~125 is a good regular, 150+ elite, 75 well below average
      // a group where most lines carry no snaps (FBS WR and RB) is weighted equally: a missing snap count as 1 next
      // to others' hundreds left the mean on a few players (WR mean 116, RB 119; Oct 21 2026 audit)
      var M = {}, SN = {};
      recs.forEach(function (r) { if (rawStat(r) == null) return; var k = r.pos + '|' + (r.div || 'FBS'), s = SN[k] = SN[k] || [0, 0]; s[0]++; if (r.snaps) s[1]++; });
      recs.forEach(function (r) { var x = rawStat(r); if (x == null) return; var k = r.pos + '|' + (r.div || 'FBS'), w = SN[k][1] >= SN[k][0] / 2 ? (r.snaps || 1) : 1;
        var m = M[k] = M[k] || [0, 0, 0]; m[0] += w; m[1] += x * w; m[2] += x * x * w; });
      recs.forEach(function (r) { var x = rawStat(r), m = M[r.pos + '|' + (r.div || 'FBS')];
        if (x == null || !m) { r.statPlus = null; return; }
        var mu = m[1] / m[0], sd = Math.sqrt(Math.max(1e-6, m[2] / m[0] - mu * mu));
        r.statPlus = Math.round(100 + 25 * (x - mu) / sd); });
      // past-season grades, by name and current school (by name alone when only one player carries it)
      if (past && past.players) {
        var P = past.players, one = {};
        Object.keys(P).forEach(function (k) { var n = k.slice(0, k.lastIndexOf('|')); one[n] = one[n] === undefined ? P[k] : null; });
        var seen = {}; recs.forEach(function (r) { seen[r.name] = (seen[r.name] || 0) + 1; });
        recs.forEach(function (r) {
          r.past = P[r.name + '|' + r.team] || (seen[r.name] === 1 ? one[r.name] : null) || null;
        });
      }
      window.__arkCfbRecs = recs;      // for the player-card graphic (gfx.html)
      return recs;
    });
    return DATA;
  }
  // a player's card (the board's scouting report) in a window over the page, for names on other tabs:
  // window.__arkCfbCard(name, team), or any element with data-cfb-card="name|team"
  function cardFor(name, team) {
    var src = document.querySelector('[data-cfb-src]');
    return load(src ? src.getAttribute('data-cfb-src') : '/data/cfb-all.json').then(function (recs) {
      return recs.filter(function (r) { return r.name === name && r.team === team; })[0] || recs.filter(function (r) { return r.name === name; })[0] || null;
    });
  }
  function showCard(r) {
    var box = document.createElement('div'); box.className = 'gfx cfb__modal'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', r.name);
    var width = Math.min(860, window.innerWidth - 32) - 64;
    box.innerHTML = '<div class="win gfx__win cfb__modalwin"><div class="win__title"><span class="win__title-text">' + esc(r.name) + ' :: ' + esc(r.team) + '<span class="win__cursor">_</span></span>' +
      '<button type="button" class="gfx__x" aria-label="close">×</button></div><div class="gfx__body cfb__modalbody"><table class="cfb__table"><tbody>' + detailHtml(r, 1, width) + '</tbody></table></div></div>';
    function close() { box.remove(); document.removeEventListener('keydown', key); }
    function key(e) { if (e.key === 'Escape') close(); }
    box.addEventListener('click', function (e) { if (e.target === box || e.target.closest('.gfx__x')) close(); });
    document.addEventListener('keydown', key);
    (document.querySelector('.post') || document.body).appendChild(box);
    box.querySelector('.gfx__x').focus();
  }
  window.__arkCfbCard = function (name, team) { return cardFor(name, team).then(function (r) { if (r) showCard(r); return !!r; }); };
  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-cfb-card]'); if (!el) return;
    e.preventDefault();
    var v = el.getAttribute('data-cfb-card').split('|'); window.__arkCfbCard(v[0], v[1]);
  });
  document.addEventListener('keydown', function (e) {
    var el = (e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('span[data-cfb-card]'); if (!el) return;
    e.preventDefault(); el.click();
  });
  function init() {
    document.querySelectorAll('[data-cfb]').forEach(function (w) {
      if (w.dataset.ready) return; w.dataset.ready = 1;
      var loading = w.querySelector('[data-cfb-loading]'), started = false;
      function go() {
        if (started) return; started = true;
        load(w.getAttribute('data-cfb-src')).then(function (data) { loading.remove(); setup(w, data); })
          .catch(function () { loading.textContent = 'load failed; reload.'; });
      }
      if (location.hash.indexOf('#' + w.getAttribute('data-cfb') + ':') === 0) go();
      var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); go(); } });
      io.observe(w);
    });
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
