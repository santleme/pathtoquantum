// Benchmark sintético do portão ADR-001 §8: 500 empresas / 2.000 partículas.
// Roda em Node com um ctx Canvas stub (conta chamadas, não rasteriza): mede o custo da
// LÓGICA de frame (projeção + comandos de desenho do dinâmico + fluxo). NÃO é fps de
// browser — é o piso comparável e reproduzível em CI; o veredito do portão usa estes
// números com essa ressalva registrada.
import { performance } from 'node:perf_hooks';
import { geoNaturalEarth1, geoPath, geoGraticule10 } from 'd3-geo';

class Path2DStub { constructor(d) { this.d = d; } }
globalThis.Path2D = Path2DStub;

const W = 1200, H = 800;
const proj = geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], {
  type: 'Feature', properties: {},
  geometry: { type: 'Polygon', coordinates: [[[-82, 14], [-32, 14], [-32, -56], [-82, -56], [-82, 14]]] },
});

function makeCtx() {
  const calls = { n: 0 };
  const fn = () => { calls.n++; };
  return {
    calls, canvas: { width: W, height: H },
    save: fn, restore: fn, beginPath: fn, fill: fn, stroke: fn, fillRect: fn, clearRect: fn,
    translate: fn, rotate: fn, arc: fn, fillText: fn,
    set fillStyle(v) {}, set strokeStyle(v) {}, set lineWidth(v) {}, set font(v) {}, set textAlign(v) {}, set globalAlpha(v) {},
  };
}

// Mundo sintético: 500 empresas × (território 6 células + 2 instalações), 13 depósitos, 11 cidades.
const rnd = (a, b) => a + Math.random() * (b - a);
const companies = Array.from({ length: 500 }, (_, i) => ({
  color: '#ffffff',
  territory: Array.from({ length: 6 }, () => [rnd(-75, -35), rnd(-50, 10)]),
  facilities: Array.from({ length: 2 }, () => [rnd(-75, -35), rnd(-50, 10)]),
}));
const deposits = Array.from({ length: 13 }, () => [rnd(-75, -35), rnd(-50, 10)]);
const cities = Array.from({ length: 11 }, () => [rnd(-75, -35), rnd(-50, 10)]);
const particles = Array.from({ length: 2000 }, () => ({ from: [rnd(0, W), rnd(0, H)], to: [rnd(0, W), rnd(0, H)], t: Math.random() }));

function dynamicFrame(ctx) {
  ctx.clearRect(0, 0, W, H);
  for (const c of companies) {
    for (const [lon, lat] of c.territory) { const p = proj([lon, lat]); ctx.fillRect(p[0] - 6, p[1] - 6, 12, 12); }
    for (const [lon, lat] of c.facilities) { const p = proj([lon, lat]); ctx.fillRect(p[0] - 7, p[1] - 7, 14, 14); ctx.fillText('M', p[0], p[1]); }
  }
  for (const [lon, lat] of deposits) { const p = proj([lon, lat]); ctx.fillRect(p[0], p[1], 10, 10); ctx.fillText('dep', p[0], p[1]); }
  for (const [lon, lat] of cities) { const p = proj([lon, lat]); ctx.beginPath(); ctx.arc(p[0], p[1], 3, 0, 7); ctx.fill(); ctx.fillText('cidade', p[0], p[1]); }
}
function flowFrame(ctx) {
  ctx.clearRect(0, 0, W, H);
  for (const p of particles) {
    p.t = (p.t + 0.003) % 1;
    const mx = (p.from[0] + p.to[0]) / 2, my = (p.from[1] + p.to[1]) / 2 - 24;
    const x = (1 - p.t) ** 2 * p.from[0] + 2 * (1 - p.t) * p.t * mx + p.t ** 2 * p.to[0];
    const y = (1 - p.t) ** 2 * p.from[1] + 2 * (1 - p.t) * p.t * my + p.t ** 2 * p.to[1];
    ctx.fillRect(x - 1, y - 1, 2, 2);
  }
}

const N = 120;
for (const [name, fn] of [['base (Path2D, 1× — cacheada)', null], ['dinâmico', dynamicFrame], ['fluxo', flowFrame]]) {
  const ctx = makeCtx();
  if (!fn) {
    const t0 = performance.now();
    const land = new Path2D(geoPath(proj)({ type: 'Sphere' }) ?? '');
    void land; void geoGraticule10;
    console.log(`${name}: ${(performance.now() - t0).toFixed(2)} ms`);
    continue;
  }
  fn(ctx); // warmup
  const t0 = performance.now();
  for (let i = 0; i < N; i++) fn(ctx);
  const ms = (performance.now() - t0) / N;
  console.log(`${name}: ${ms.toFixed(2)} ms/frame · ${(1000 / ms).toFixed(0)} fps-equiv · ${Math.round(ctx.calls.n / (N + 1))} cmds/frame`);
}
const ctx = makeCtx();
const t0 = performance.now();
for (let i = 0; i < N; i++) { dynamicFrame(ctx); flowFrame(ctx); }
const total = (performance.now() - t0) / N;
console.log(`TOTAL dinâmico+fluxo: ${total.toFixed(2)} ms/frame · ${(1000 / total).toFixed(0)} fps-equiv (stub Node, sem raster)`);
console.log(`portão §8: dinâmico < 8 ms → ${total < 8 ? 'OK (dinâmico+fluxo somados)' : 'VERIFICAR'}`);
