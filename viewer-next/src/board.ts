// Placar-ranking (F3 — VIS-08) e seleção de empresa (VIS-05): lógica pura e
// testável — ranking por caixa com posição, elo como segmentos + rótulo, Δ de
// caixa desde o frame anterior, estado de falida por texto/ícone e HTML das
// linhas. As cores são EXATAMENTE as `color` do frame (a mesma fonte que o mapa
// usa para território/instalações/rotas) — o placar não inventa cor.
import type { Company, Frame } from './contracts';
import { cellToLonLat } from './entities';
import { esc } from './feed';
import { STAGE_LABELS } from './resources';

export const money = (v: number) => `US$ ${(v / 1e6).toFixed(1).replace('.', ',')}M`;

export interface BoardEntry {
  company: Company;
  /** Posição 1..n no ranking do frame (ordem: caixa desc). */
  position: number;
  /** Variação de caixa desde o frame anterior (null no primeiro frame). */
  delta: number | null;
}

export function rankCompanies(frame: Frame, prev: Frame | null): BoardEntry[] {
  const prevCash = new Map((prev?.companies ?? []).map((c) => [c.id, c.cash]));
  return [...frame.companies]
    .sort((a, b) => b.cash - a.cash)
    .map((company, i) => ({
      company,
      position: i + 1,
      delta: prevCash.has(company.id) ? company.cash - prevCash.get(company.id)! : null,
    }));
}

export interface StageSegments {
  filled: number;
  total: 5;
  label: string;
}

/** Elo como segmentos (n de 5) + rótulo — clamp fora de 0..5 (VIS-12). */
export function stageSegments(stage: number): StageSegments {
  const filled = Math.max(0, Math.min(5, Math.trunc(stage)));
  return { filled, total: 5, label: STAGE_LABELS[filled] };
}

export interface DeltaView {
  arrow: string;
  text: string;
  cls: 'up' | 'down' | 'flat' | 'none';
}

/** Δ de caixa sinalizado: seta + valor formatado; null (sem frame anterior) = "—". */
export function deltaView(delta: number | null): DeltaView {
  if (delta === null) return { arrow: '—', text: '', cls: 'none' };
  if (delta > 0) return { arrow: '▲', text: money(delta), cls: 'up' };
  if (delta < 0) return { arrow: '▼', text: money(-delta), cls: 'down' };
  return { arrow: '±', text: money(0), cls: 'flat' };
}

export function segmentsHtml(stage: number): string {
  const { filled, total, label } = stageSegments(stage);
  const segs = Array.from({ length: total }, (_, i) => `<span class="seg${i < filled ? ' on' : ''}"></span>`).join('');
  return `<span class="segs" role="img" aria-label="elo ${filled} de ${total}: ${esc(label)}">${segs}</span>`;
}

/**
 * HTML de uma linha do placar. Identidade nunca só por cor: posição numerada,
 * nome, selo textual de selecionada e de falida († + texto) além de qualquer
 * esmaecimento.
 */
export function boardRowHtml(entry: BoardEntry, selected: boolean): string {
  const c = entry.company;
  const seg = stageSegments(c.stage);
  const d = deltaView(entry.delta);
  const sel = selected ? '<span class="tag tag-sel">selecionada</span>' : '';
  const dead = c.alive ? '' : '<span class="tag tag-dead">† falida</span>';
  const delta = d.cls === 'none'
    ? '<span class="delta none" title="sem frame anterior">—</span>'
    : `<span class="delta ${d.cls}">${d.arrow} ${d.text}</span>`;
  return (
    `<button type="button" class="brow${c.alive ? '' : ' dead'}${selected ? ' selected' : ''}"` +
    ` data-company-id="${c.id}" aria-pressed="${selected}" title="Selecionar ${esc(c.name)}">` +
    `<span class="pos">${entry.position}.</span>` +
    `<span class="dot" style="background:${esc(c.color)}"></span>` +
    `<span class="bmain"><span class="bname">${esc(c.name)} ${sel}${dead}</span>` +
    `<span class="stage">${esc(c.archetype)} · elo: ${esc(seg.label)} (${seg.filled}/${seg.total})</span></span>` +
    `${segmentsHtml(c.stage)}` +
    `<span class="bcash"><span class="cash">${money(c.cash)}</span>${delta}</span></button>`
  );
}

/**
 * Empresa mais próxima de um ponto de tela (clique no mapa — VIS-05): procura
 * instalações e centros de território, projetados pela função dada (a projeção
 * do MapSurface em produção; identidade nos testes). null se nada estiver
 * dentro de maxDist px.
 */
export function nearestCompanyId(
  companies: Company[],
  project: (lon: number, lat: number) => [number, number],
  x: number,
  y: number,
  maxDist = 18,
): number | null {
  let best: number | null = null;
  let bestDist = maxDist;
  const probe = (lon: number, lat: number, id: number) => {
    const [px, py] = project(lon, lat);
    const dist = Math.hypot(px - x, py - y);
    if (dist <= bestDist) {
      bestDist = dist;
      best = id;
    }
  };
  for (const c of companies) {
    for (const fac of c.facilities) {
      const { lon, lat } = cellToLonLat(fac.cell);
      probe(lon, lat, c.id);
    }
    for (const cell of c.territory) {
      const { lon, lat } = cellToLonLat(cell);
      probe(lon, lat, c.id);
    }
  }
  return best;
}
