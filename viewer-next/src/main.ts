// Viewer-next (F0+F1) — "A Terra de verdade": base cartográfica real (Natural Earth),
// entidades orientadas a dados, replay básico compatível com ?run=. Ver SPEC-VISUAL-WOW
// VIS-01/02/07 e ADR-001. Crônica completa (VIS-03/04), lentes (VIS-05) e cadeia (VIS-06)
// são as fatias F2–F4 — aqui o feed é um extrato simples dos eventos narrativos.
import { feature } from 'topojson-client';
import type { FeatureCollection } from 'geojson';
import {
  frameIndexForTick,
  parseRunData,
  parseWorldData,
  resolveRunDir,
  type Frame,
  type RunData,
  type WorldData,
} from './contracts';
import { cellToLonLat, citiesFromWorld, depositsFromFrame } from './entities';
import { CanvasMapSurface, type MapSurface } from './mapsurface';
import { resourceInfo, STAGE_LABELS } from './resources';

const $ = (id: string) => document.getElementById(id) as HTMLElement;
const money = (v: number) => `US$ ${(v / 1e6).toFixed(1).replace('.', ',')}M`;

let run: RunData;
let world: WorldData;
let surface: MapSurface;
let idx = 0;
let timer: number | undefined;

interface Route {
  from: [number, number];
  to: [number, number];
  color: string;
}
let routes: Route[] = [];
let particles: { route: number; t: number; speed: number }[] = [];

async function fetchJson(url: string): Promise<unknown> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function loadAll(): Promise<void> {
  const runDir = resolveRunDir(location.search);
  const framesUrl = runDir ? `${runDir}/frames.json` : 'data/served/frames.json';
  const [framesRaw, worldRaw, saTopo, worldTopo] = await Promise.all([
    fetchJson(framesUrl),
    fetchJson('data/world_data.json'),
    fetchJson('geo/sa-50m.json'),
    fetchJson('geo/world-110m.json'),
  ]);
  run = parseRunData(framesRaw);
  world = parseWorldData(worldRaw);
  // topojson-client tipa os objetos genericamente; o cast concentra-se nesta fronteira.
  const sa = feature(
    saTopo as Parameters<typeof feature>[0],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (saTopo as any).objects.countries,
  ) as unknown as FeatureCollection;
  void worldTopo; // mundo 110m é carregado/valido no build; a base detalhada é o excerto SA 50m
  surface = new CanvasMapSurface(sa);
  const scrub = $('scrub') as HTMLInputElement;
  scrub.max = String(run.frames.length - 1);
  scrub.value = '0';
  resize();
  render();
  play();
  requestAnimationFrame(flowTick);
}

function canvases(): [HTMLCanvasElement, HTMLCanvasElement, HTMLCanvasElement] {
  return [$('base') as HTMLCanvasElement, $('dyn') as HTMLCanvasElement, $('flow') as HTMLCanvasElement];
}

function resize(): void {
  const wrap = $('mapwrap');
  const w = wrap.clientWidth - 20;
  const h = wrap.clientHeight - 20;
  if (w <= 0 || h <= 0) return;
  for (const cv of canvases()) {
    cv.width = w;
    cv.height = h;
  }
  surface.resize(w, h);
  const [base] = canvases();
  const ctx = base.getContext('2d');
  if (ctx) surface.drawBase(ctx);
  renderDynamic();
}

function render(): void {
  const f = run.frames[idx];
  $('date').textContent = `${f.date} · tick ${f.tick}`;
  ($('scrub') as HTMLInputElement).value = String(idx);
  buildRoutes(f);
  renderDynamic();
  renderBoard(f);
  renderFeed(f);
}

function renderDynamic(): void {
  if (!run || !surface) return;
  const f = run.frames[idx];
  const [, dyn] = canvases();
  const ctx = dyn.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, dyn.width, dyn.height);

  // Território e instalações (célula → lon/lat → projeção; nada de lista fixa).
  for (const c of f.companies) {
    for (const cell of c.territory) {
      const { lon, lat } = cellToLonLat(cell);
      const [x, y] = surface.project(lon, lat);
      ctx.fillStyle = c.color + '55';
      ctx.fillRect(x - 6, y - 6, 12, 12);
    }
    for (const fac of c.facilities) {
      const { lon, lat } = cellToLonLat(fac.cell);
      const [x, y] = surface.project(lon, lat);
      ctx.fillStyle = c.color;
      ctx.fillRect(x - 7, y - 7, 14, 14);
      ctx.fillStyle = '#0b1020';
      ctx.font = 'bold 9px monospace';
      ctx.textAlign = 'center';
      ctx.fillText({ mine: 'M', refinery: 'R', factory: 'F', plant: 'P', assembly: 'A' }[fac.kind] ?? '?', x, y + 3);
    }
  }

  // Depósitos da corrida (frames): nome legível, recurso por extenso, remaining como barra.
  for (const d of depositsFromFrame(f)) {
    const [x, y] = surface.project(d.lon, d.lat);
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = '#ffd166';
    ctx.fillRect(-5, -5, 10, 10);
    ctx.restore();
    ctx.fillStyle = '#e8ecf6';
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(d.name, x + 9, y - 2);
    ctx.fillStyle = '#8b96b8';
    ctx.font = '9px monospace';
    ctx.fillText(resourceInfo(d.resource).label, x + 9, y + 9);
    ctx.fillStyle = '#26304d';
    ctx.fillRect(x + 9, y + 12, 44, 3);
    ctx.fillStyle = '#ffd166';
    ctx.fillRect(x + 9, y + 12, 44 * Math.max(0, Math.min(1, d.remaining_frac)), 3);
  }

  // Cidades da camada-mundo (world_data): as 11, sempre — nunca hardcode (VIS-02).
  for (const city of citiesFromWorld(world)) {
    const [x, y] = surface.project(city.lon, city.lat);
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#e8ecf6';
    ctx.fill();
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(city.name, x + 6, y + 3);
  }
}

function buildRoutes(f: Frame): void {
  routes = [];
  const cityByName = new Map(citiesFromWorld(world).map((c) => [c.name, c]));
  for (const c of f.companies) {
    const hq = cityByName.get(c.hq);
    if (!hq) continue;
    const to = surface.project(hq.lon, hq.lat);
    for (const fac of c.facilities) {
      const { lon, lat } = cellToLonLat(fac.cell);
      routes.push({ from: surface.project(lon, lat), to, color: c.color });
    }
  }
  particles = Array.from({ length: Math.min(2000, routes.length * 24) }, (_, i) => ({
    route: routes.length ? i % routes.length : 0,
    t: Math.random(),
    speed: 0.001 + Math.random() * 0.003,
  }));
}

function flowTick(): void {
  const [, , flow] = canvases();
  const ctx = flow.getContext('2d');
  if (ctx && routes.length) {
    ctx.clearRect(0, 0, flow.width, flow.height);
    for (const p of particles) {
      const r = routes[p.route];
      p.t = (p.t + p.speed) % 1;
      const mx = (r.from[0] + r.to[0]) / 2;
      const my = (r.from[1] + r.to[1]) / 2 - 24; // arco 2.5D seletivo (ADR-001 §3.1)
      const x = (1 - p.t) ** 2 * r.from[0] + 2 * (1 - p.t) * p.t * mx + p.t ** 2 * r.to[0];
      const y = (1 - p.t) ** 2 * r.from[1] + 2 * (1 - p.t) * p.t * my + p.t ** 2 * r.to[1];
      ctx.fillStyle = r.color;
      ctx.fillRect(x - 1, y - 1, 2, 2);
    }
  }
  requestAnimationFrame(flowTick);
}

function renderBoard(f: Frame): void {
  const sorted = [...f.companies].sort((a, b) => b.cash - a.cash);
  $('board').innerHTML = sorted
    .map(
      (c, i) => `<div class="row${c.alive ? '' : ' dead'}">
        <span class="dot" style="background:${c.color}"></span>
        <span>${i + 1}. ${c.name} <span class="stage">${c.archetype} · elo: ${STAGE_LABELS[Math.max(0, Math.min(5, c.stage))]}</span></span>
        <span class="cash">${money(c.cash)}${c.alive ? '' : ' · falida'}</span></div>`,
    )
    .join('');
  $('legend').textContent =
    `◆ depósito (nome + recurso + barra de reserva) · ● cidade-mercado (${citiesFromWorld(world).length} do world_data) · ` +
    `depósitos neste frame: ${depositsFromFrame(f).length} (da corrida, não do mundo)`;
}

function renderFeed(f: Frame): void {
  const evs = run.chronicle.filter((e) => e.tick <= f.tick && e.kind !== 'flows' && e.text);
  $('feed').innerHTML = evs
    .slice(-30)
    .reverse()
    .map((e) => `<div class="row" style="grid-template-columns:1fr"><span><b style="color:#ffd166">${e.date}</b> — ${e.text}</span></div>`)
    .join('');
}

function play(): void {
  stop();
  const speed = Number(($('speed') as HTMLSelectElement).value);
  timer = window.setInterval(() => {
    idx = (idx + 1) % run.frames.length;
    render();
  }, speed);
  ($('play') as HTMLButtonElement).textContent = '⏸ pausar';
}

function stop(): void {
  if (timer) window.clearInterval(timer);
  timer = undefined;
}

$('play').addEventListener('click', () => {
  if (timer) {
    stop();
    ($('play') as HTMLButtonElement).textContent = '▶ tocar';
  } else play();
});
$('speed').addEventListener('change', () => {
  if (timer) play();
});
$('scrub').addEventListener('input', (e) => {
  idx = Number((e.target as HTMLInputElement).value);
  render();
});
window.addEventListener('resize', resize);

loadAll().catch((err: Error) => {
  const el = $('err');
  el.style.display = 'block';
  el.textContent = `Não foi possível carregar a corrida: ${err.message}. Verifique ?run= ou sirva a pasta com os dados (data/served/).`;
});

// Salto por marco (VIS-07): exposto para paridade com o legado/testes futuros.
(window as unknown as { ptqJumpToTick: (t: number) => void }).ptqJumpToTick = (t: number) => {
  stop();
  idx = frameIndexForTick(run, t);
  render();
};
