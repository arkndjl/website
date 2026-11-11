// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// One outcome horizon for every draft class, for the CFB FV harnesses: weighted NFL AV divided by seasons elapsed since
// the draft runs higher for recent classes (no decline or out-of-league years yet), so the same slot was worth ~1.9x as
// much for a 2022 draftee as for a 2013 one. h(class) = the class's actual / slot-expected AV a season (one a + b ln
// pick line, every pick), smoothed by a cubic in seasons elapsed, divided by its mean over the 2020-23 drafts (the
// default harness's classes, so its outcome level is unchanged). Outcome = AV a season elapsed / h(class).
// Python twin: scripts/cfb_horizon.py (same rule; `python3 scripts/cfb_horizon.py --test` compares the two).
const REF = [2020, 2021, 2022, 2023];

function solve(A, y) {       // least squares by normal equations (4 x 4)
  const n = A[0].length, M = Array.from({ length: n }, (_, i) => Array.from({ length: n + 1 }, (_, j) => j < n ? A.reduce((s, r) => s + r[i] * r[j], 0) : A.reduce((s, r, k) => s + r[i] * y[k], 0)));
  for (let c = 0; c < n; c++) { let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r; [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let j = c; j <= n; j++) M[r][j] -= f * M[c][j]; } }
  return M.map((r, i) => r[n] / r[i]);
}

// picks: nflverse draft_picks rows ({season, pick, w_av}); through: the last NFL season counted. Returns season -> h.
export function horizon(picks, through) {
  const P = picks.filter(r => +r.season >= 2012 && +r.season <= through && +r.pick > 0);
  const av = r => (+r.w_av || 0) / (through - +r.season + 1);
  const S = P.filter(r => +r.season <= through - 2), x = S.map(r => Math.log(+r.pick)), y = S.map(av);
  const mx = x.reduce((a, v) => a + v, 0) / x.length, my = y.reduce((a, v) => a + v, 0) / y.length;
  const b = x.reduce((a, v, i) => a + (v - mx) * (y[i] - my), 0) / x.reduce((a, v) => a + (v - mx) ** 2, 0), a = my - b * mx;
  const cls = [...new Set(P.map(r => +r.season))].sort((p, q) => p - q);
  const ratio = cls.map(s => { const Q = P.filter(r => +r.season === s); return Q.reduce((t, r) => t + av(r), 0) / Q.reduce((t, r) => t + Math.max(0, a + b * Math.log(+r.pick)), 0); });
  const e = cls.map(s => through - s + 1), c = solve(e.map(v => [1, v, v * v, v ** 3]), ratio);
  const f = v => c[0] + c[1] * v + c[2] * v * v + c[3] * v ** 3;
  const ref = REF.map(s => f(through - s + 1)).reduce((t, v) => t + v, 0) / REF.length;
  const h = Object.fromEntries(cls.map(s => [s, f(through - s + 1) / ref]));
  return season => h[season] ?? 1;
}

if (process.argv[1] && process.argv[1].endsWith('cfb_horizon.mjs') && process.argv.includes('--print')) {
  const fs = await import('node:fs'), path = await import('node:path'), { fileURLToPath } = await import('node:url');
  const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
  const txt = fs.readFileSync(path.join(ROOT, 'scripts', '.cache', 'statplus', 'draft_picks.csv'), 'utf8').split('\n');
  const hd = txt[0].split(','), I = k => hd.indexOf(k);
  const rows = txt.slice(1).filter(Boolean).map(l => { const v = l.match(/("([^"]|"")*"|[^,]*)(,|$)/g).map(z => z.replace(/,$/, '').replace(/^"|"$/g, '')); return { season: v[I('season')], pick: v[I('pick')], w_av: v[I('w_av')] }; });
  const h = horizon(rows, 2025);
  console.log(JSON.stringify(Object.fromEntries(Array.from({ length: 14 }, (_, i) => [2012 + i, Math.round(h(2012 + i) * 10000) / 10000]))));
}
