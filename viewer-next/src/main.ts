// Viewer-next (F0+F1+F2+F3+F4) — "A Terra de verdade" + "A crônica vira show" +
// lente Empresas e placar-ranking: base cartográfica real (Natural Earth),
// entidades orientadas a dados, replay compatível com ?run=, feed da crônica por
// kind/company com hierarquia, destaque de novo e clique-para-saltar
// (VIS-01/02/03/04/07), mecanismo de lentes com Empresas padrão, seleção por
// canal não-cor e placar com posição/segmentos de elo/Δ de caixa (VIS-05/08) e
// a barra/vista da cadeia (VIS-06): primeiros por elo dos `chain_link`, mercado
// do elo em disputa, Sankey derivado de stocks/stage e estoques na seleção.
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
import { boardRowHtml, money, nearestCompanyId, rankCompanies } from './board';
import { chainBarHtml, chainStateListHtml, sankeySvg, selectionProgressHtml, stocksListHtml } from './chain';
import { cellToLonLat, citiesFromWorld, depositsFromFrame } from './entities';
import { esc, feedItemHtml, narrativeItems, newItemIndexes, tickFromFeedTarget } from './feed';
import { DEFAULT_LENS_ID, emphasisAlpha, LENSES, resolveLensSelection } from './lenses';
import { CanvasMapSurface, type MapSurface } from './mapsurface';
import { resourceInfo } from './resources';

const $ = (id: string) => document.getElementById(id) as HTMLElement;

let run: RunData;
let world: WorldData;
let surface: MapSurface;
let idx = 0;
let timer: number | undefined;
/** Lote de eventos "novos" do frame atual (VIS-04) — índices na crônica original. */
let newBatch: Set<number> = new Set();
/** Lente ativa (VIS-05) — registro em lenses.ts; trocar nunca move o frame. */
let activeLensId: string = DEFAULT_LENS_ID;
/** Empresa selecionada (id do frame) ou null — destaque por anel/rótulo/selo. */
let selectedId: number | null = null;

interface Route {
  from: [number, number];
  to: [number, number];
  color: string;
  companyId: number;
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
  // Abertura = excerto SA 50m; o mundo land-110m (geo/world-110m.json) entra na
  // vista-múndi das lentes futuras — não é baixado nesta fatia.
  const [framesRaw, worldRaw, saTopo] = await Promise.all([
    fetchJson(framesUrl),
    fetchJson('data/world_data.json'),
    fetchJson('geo/sa-50m.json'),
  ]);
  run = parseRunData(framesRaw);
  world = parseWorldData(worldRaw);
  // topojson-client tipa os objetos genericamente; o cast concentra-se nesta fronteira.
  const sa = feature(
    saTopo as Parameters<typeof feature>[0],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (saTopo as any).objects.countries,
  ) as unknown as FeatureCollection;
  surface = new CanvasMapSurface(sa);
  const scrub = $('scrub') as HTMLInputElement;
  scrub.max = String(run.frames.length - 1);
  scrub.value = '0';
  // Primeiro frame: o lote de novos é tudo que já aconteceu até ele (VIS-04).
  newBatch = newItemIndexes(run.chronicle, null, run.frames[0].tick);
  renderLenses();
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
  renderChain(f);
  renderBoard(f);
  renderSelection(f);
  renderFeed(f);
}

/**
 * Barra da cadeia + vista Sankey (VIS-06): tudo derivado do frame atual e da
 * crônica até o tick dele — primeiros por elo, mercado do elo em disputa e o
 * fluxo derivado de stocks/stage, com a lista textual equivalente ao lado.
 */
function renderChain(f: Frame): void {
  const colorByName = new Map(f.companies.map((c) => [c.name, c.color]));
  $('chainbar').innerHTML = chainBarHtml(run.chronicle, f, colorByName);
  $('sankey').innerHTML = sankeySvg(f) + chainStateListHtml(run.chronicle, f);
}

/**
 * Painel de seleção (VIS-05/06): empresa selecionada com progresso na mesma
 * escala da cadeia e os estoques do frame — `stocks` deixa de ser dado morto.
 */
function renderSelection(f: Frame): void {
  const el = $('selpanel');
  const c = selectedId === null ? null : (f.companies.find((co) => co.id === selectedId) ?? null);
  if (!c) {
    el.innerHTML =
      '<p class="dim-note">clique numa empresa do placar ou numa instalação do mapa para inspecionar: progresso na cadeia e estoques do frame.</p>';
    return;
  }
  const dead = c.alive ? '' : '<span class="tag tag-dead">† falida</span>';
  el.innerHTML =
    `<div class="selhead"><span class="dot" style="background:${esc(c.color)}"></span><b>${esc(c.name)}</b>${dead}</div>` +
    `<div class="selmeta"><span class="stage">${esc(c.archetype)} · sede: ${esc(c.hq)}</span></div>` +
    `<div class="selmeta">${selectionProgressHtml(c)} <span class="selcash">${money(c.cash)}</span></div>` +
    stocksListHtml(c);
}

function renderDynamic(): void {
  if (!run || !surface) return;
  const f = run.frames[idx];
  const [, dyn] = canvases();
  const ctx = dyn.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, dyn.width, dyn.height);

  // Território e instalações (célula → lon/lat → projeção; nada de lista fixa).
  // Lente Empresas: a cor é a do frame; a seleção recua as demais em alpha e a
  // selecionada ganha anel + rótulo — canal não-cor (VIS-05).
  for (const c of f.companies) {
    const alpha = emphasisAlpha(selectedId, c.id);
    const selected = selectedId === c.id;
    ctx.save();
    ctx.globalAlpha = alpha;
    for (const cell of c.territory) {
      const { lon, lat } = cellToLonLat(cell);
      const [x, y] = surface.project(lon, lat);
      ctx.fillStyle = c.color + '55';
      ctx.fillRect(x - 6, y - 6, 12, 12);
      if (selected) {
        ctx.strokeStyle = '#ffd166';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x - 7.5, y - 7.5, 15, 15);
      }
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
      if (selected) {
        ctx.beginPath();
        ctx.arc(x, y, 12, 0, Math.PI * 2);
        ctx.strokeStyle = '#ffd166';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }
    if (selected && c.facilities.length > 0) {
      const { lon, lat } = cellToLonLat(c.facilities[0].cell);
      const [x, y] = surface.project(lon, lat);
      ctx.fillStyle = '#ffd166';
      ctx.font = 'bold 11px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`◉ ${c.name}`, x + 15, y - 10);
    }
    ctx.restore();
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
      routes.push({ from: surface.project(lon, lat), to, color: c.color, companyId: c.id });
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
      ctx.globalAlpha = emphasisAlpha(selectedId, r.companyId);
      ctx.fillStyle = r.color;
      ctx.fillRect(x - 1, y - 1, 2, 2);
      ctx.globalAlpha = 1;
    }
  }
  requestAnimationFrame(flowTick);
}

/** Seletor de lentes (VIS-05): montado a partir do registro declarativo. */
function renderLenses(): void {
  $('lenses').innerHTML = LENSES.map(
    (l) =>
      `<button type="button" class="lens-btn${l.id === activeLensId ? ' active' : ''}" data-lens="${l.id}"` +
      ` aria-pressed="${l.id === activeLensId}">${l.label}${l.status === 'em-breve' ? ' <span class="soon">em breve</span>' : ''}</button>`,
  ).join('');
}

/**
 * Troca de lente: resolve pelo registro e re-renderiza SOBRE O MESMO FRAME —
 * idx/tick não mudam, nenhum JSON é recarregado; lente "em breve" só avisa.
 */
function setLens(requestedId: string): void {
  const sel = resolveLensSelection(activeLensId, requestedId);
  activeLensId = sel.activeId;
  $('lensnote').textContent = sel.notice ?? '';
  renderLenses();
  renderDynamic();
  renderBoard(run.frames[idx]);
}

/** Seleção de empresa (placar ou mapa): mesmo frame, só ênfase/anel/selo mudam. */
function setSelected(id: number | null): void {
  selectedId = selectedId !== null && id === selectedId ? null : id;
  renderDynamic();
  renderBoard(run.frames[idx]);
  renderSelection(run.frames[idx]);
}

function renderBoard(f: Frame): void {
  const prev = idx > 0 ? run.frames[idx - 1] : null;
  const entries = rankCompanies(f, prev);
  $('board').innerHTML = entries.map((e) => boardRowHtml(e, e.company.id === selectedId)).join('');
  $('legend').textContent =
    `◆ depósito (nome + recurso + barra de reserva) · ● cidade-mercado (${citiesFromWorld(world).length} do world_data) · ` +
    `depósitos neste frame: ${depositsFromFrame(f).length} (da corrida, não do mundo) · clique numa empresa ou no mapa seleciona`;
}

function renderFeed(f: Frame): void {
  // Cor da empresa vem do frame atual (nome → cor); fora do frame = sem cor (VIS-03).
  const colorByName = new Map(f.companies.map((c) => [c.name, c.color]));
  const items = narrativeItems(run.chronicle, f.tick);
  // DOM em ordem cronológica reversa (mais recente no topo, como o legado); a lista
  // conferível em ordem está em narrativeItems (testes + script de âncoras).
  $('feed').innerHTML = [...items]
    .reverse()
    .map((item) =>
      feedItemHtml(item, item.event.company ? colorByName.get(item.event.company) : undefined, newBatch.has(item.index)),
    )
    .join('');
  $('feedmeta').textContent = `${items.length} eventos narrativos até o tick ${f.tick} · clique num evento salta o replay`;
}

/** Salto do replay ao tick (VIS-07): seek — não gera lote de novos (VIS-04). */
function jumpToTick(tick: number): void {
  stop();
  ($('play') as HTMLButtonElement).textContent = '▶ tocar';
  newBatch = new Set();
  idx = frameIndexForTick(run, tick);
  render();
}

function play(): void {
  stop();
  const speed = Number(($('speed') as HTMLSelectElement).value);
  timer = window.setInterval(() => {
    const next = (idx + 1) % run.frames.length;
    // Avanço sequencial: a marca de novo é do lote que entrou (VIS-04). No wrap
    // (último frame → primeiro) o tick anda para trás: lote vazio, como no scrub.
    newBatch =
      next === 0 ? new Set() : newItemIndexes(run.chronicle, run.frames[idx].tick, run.frames[next].tick);
    idx = next;
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
  // Scrub é seek: nenhum evento é "novo" (VIS-04), para frente ou para trás.
  newBatch = new Set();
  idx = Number((e.target as HTMLInputElement).value);
  render();
});
$('feed').addEventListener('click', (e) => {
  const tick = tickFromFeedTarget(e.target);
  if (tick !== null) jumpToTick(tick);
});
$('lenses').addEventListener('click', (e) => {
  const el = (e.target as HTMLElement).closest('[data-lens]') as HTMLElement | null;
  if (el?.dataset.lens) setLens(el.dataset.lens);
});
$('board').addEventListener('click', (e) => {
  const el = (e.target as HTMLElement).closest('[data-company-id]') as HTMLElement | null;
  if (el?.dataset.companyId) setSelected(Number(el.dataset.companyId));
});
$('flow').addEventListener('click', (e) => {
  // Clique no mapa (o canvas de fluxo é o de cima): seleciona a empresa mais
  // próxima; clique no vazio limpa a seleção. Coordenada em px do canvas.
  const cv = $('flow') as HTMLCanvasElement;
  const rect = cv.getBoundingClientRect();
  const x = ((e as MouseEvent).clientX - rect.left) * (cv.width / rect.width);
  const y = ((e as MouseEvent).clientY - rect.top) * (cv.height / rect.height);
  const id = nearestCompanyId(run.frames[idx].companies, (lon, lat) => surface.project(lon, lat), x, y);
  if (id === null) {
    if (selectedId !== null) {
      selectedId = null;
      renderDynamic();
      renderBoard(run.frames[idx]);
      renderSelection(run.frames[idx]);
    }
  } else setSelected(id);
});
window.addEventListener('resize', resize);

loadAll().catch((err: Error) => {
  const el = $('err');
  el.style.display = 'block';
  el.textContent = `Não foi possível carregar a corrida: ${err.message}. Verifique ?run= ou sirva a pasta com os dados (data/served/).`;
});

// Salto por marco (VIS-07): agora é o mesmo caminho do clique no feed.
(window as unknown as { ptqJumpToTick: (t: number) => void }).ptqJumpToTick = jumpToTick;
