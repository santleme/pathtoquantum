// Barra/vista da cadeia (F4 — VIS-06): lógica pura e testável sobre o que os
// artefatos JÁ trazem — eventos `chain_link` da crônica (quem dominou cada elo
// primeiro, nos ticks reais), `stage` por empresa, `stocks` por empresa e
// `prices` por frame. Nada é interpolado entre frames: o `stage` salta 0→4
// entre dois frames anuais, e a spec §9 manda ancorar os marcos nos
// `chain_link`, que é o que `firstByLink` faz.
//
// Derivação do Sankey (ADR-001 §3.5 — honestidade sobre a largura):
// os artefatos NÃO trazem fluxo elo→elo. O que existe é inventário: `stocks`
// por empresa/commodity e o `stage` de cada uma. A largura do link k→k+1 é,
// portanto, uma DERIVAÇÃO documentada: a soma das unidades das commodities de
// SAÍDA do elo k que estão em poder de empresas que já dominaram o elo k+1
// (stage > k) — ou seja, o volume produzido no elo k por quem comprovadamente
// avançou além dele. Não é medição de transferência entre elos; é o estoque
// "qualificado" por progresso, e o README da fatia repete esta definição.
// Comércio entre empresas (cíclico) NÃO entra aqui: Sankey é o DAG da cadeia
// produtiva; comércio fica nos arcos do mapa (ADR-001 §3.5).
import { sankey, sankeyLinkHorizontal } from 'd3-sankey';
import { segmentsHtml, stageSegments, type StageSegments } from './board';
import type { ChronicleEvent, Company, Frame } from './contracts';
import { esc } from './feed';
import { resourceInfo, STAGE_LABELS } from './resources';

export interface ChainLinkDef {
  /** Elo 1..5 — coincide com o `stage` de quem o dominou. */
  stage: number;
  label: string;
  /** Commodities de saída do elo (chaves de `prices`/`stocks`). */
  outputs: string[];
}

/** Os 5 elos da cadeia, na ordem. Saídas conferidas contra o registro (VIS-02). */
export const CHAIN_LINKS: ChainLinkDef[] = [1, 2, 3, 4, 5].map((stage) => ({
  stage,
  label: STAGE_LABELS[stage],
  outputs: [
    ['lithium_ore', 'copper_ore', 'iron_ore', 'oil'],
    ['lithium', 'copper', 'iron', 'plastic'],
    ['component'],
    ['device'],
    ['supercomputer'],
  ][stage - 1],
}));

export interface LinkFirst {
  company: string;
  tick: number;
}

/**
 * Elo de um evento `chain_link`: primeiro pelo texto (o motor nomeia o elo —
 * "…primeira a dominar o elo de extração."), com fallback para a posição
 * ordinal do evento entre os `chain_link` (a cadeia é sequencial: dominar o
 * elo k+1 pressupõe o k dominado). null se nenhum dos dois resolver.
 */
function stageFromChainLink(event: ChronicleEvent, ordinal: number): number | null {
  const text = (event.text ?? '').toLowerCase();
  for (const link of CHAIN_LINKS) {
    if (text.includes(link.label.toLowerCase())) return link.stage;
  }
  return ordinal >= 1 && ordinal <= CHAIN_LINKS.length ? ordinal : null;
}

/**
 * Primeiro a dominar cada elo, considerando só eventos com tick <= upToTick.
 * Retorna array de 5 posições (índice 0 = elo 1): LinkFirst ou null ("ninguém
 * ainda"). Empate de tick: vence quem aparece antes na crônica.
 */
export function firstByLink(chronicle: ChronicleEvent[], upToTick: number): (LinkFirst | null)[] {
  const firsts: (LinkFirst | null)[] = CHAIN_LINKS.map(() => null);
  let ordinal = 0;
  for (const event of chronicle) {
    if (event.kind !== 'chain_link' || event.tick > upToTick) continue;
    ordinal += 1;
    const stage = stageFromChainLink(event, ordinal);
    if (stage === null || !event.company) continue;
    const cur = firsts[stage - 1];
    if (!cur || event.tick < cur.tick) firsts[stage - 1] = { company: event.company, tick: event.tick };
  }
  return firsts;
}

/**
 * Progresso individual de uma empresa na escala da cadeia (stage/5).
 * Função única de progresso da fatia: delega a `stageSegments` do placar
 * (F3) — barra, placar e painel de seleção leem a mesma verdade.
 */
export function companyProgress(company: Company): StageSegments {
  return stageSegments(company.stage);
}

/** Elo mais alto em disputa: o primeiro ainda não dominado (null = cadeia fechada). */
export function frontierStage(firsts: (LinkFirst | null)[]): number | null {
  for (const link of CHAIN_LINKS) {
    if (!firsts[link.stage - 1]) return link.stage;
  }
  return null;
}

/** Estoques de uma empresa, tolerando artefato degradado: ausente = {} (VIS-12). */
export function stocksOf(company: Company): Record<string, number> {
  return company.stocks ?? {};
}

function sumOutputs(company: Company, outputs: string[]): number {
  const stocks = stocksOf(company);
  let total = 0;
  for (const key of outputs) total += stocks[key] ?? 0;
  return total;
}

/** Total em estoque das commodities de saída do elo, somando todas as empresas. */
export function eloStocks(frame: Frame, stage: number): number {
  const link = CHAIN_LINKS[stage - 1];
  if (!link) return 0;
  return frame.companies.reduce((acc, c) => acc + sumOutputs(c, link.outputs), 0);
}

/**
 * Estoque do elo `stage` em poder de empresas que já dominaram o elo seguinte
 * (stage > stage) — a largura do link Sankey stage→stage+1 (derivação no topo).
 */
export function progressedStocks(frame: Frame, stage: number): number {
  const link = CHAIN_LINKS[stage - 1];
  if (!link) return 0;
  return frame.companies
    .filter((c) => companyProgress(c).filled > stage)
    .reduce((acc, c) => acc + sumOutputs(c, link.outputs), 0);
}

export interface SankeyNodeData {
  id: string;
  stage: number;
  label: string;
}

export interface SankeyLinkData {
  source: string;
  target: string;
  value: number;
}

/** Grafo puro da vista-cadeia: 5 nós (elos) e 4 links (derivação no topo). */
export function sankeyData(frame: Frame): { nodes: SankeyNodeData[]; links: SankeyLinkData[] } {
  return {
    nodes: CHAIN_LINKS.map((l) => ({ id: `elo${l.stage}`, stage: l.stage, label: l.label })),
    links: CHAIN_LINKS.slice(0, -1).map((l) => ({
      source: `elo${l.stage}`,
      target: `elo${l.stage + 1}`,
      value: progressedStocks(frame, l.stage),
    })),
  };
}

export interface MarketPrice {
  resource: string;
  label: string;
  price: number;
}

export interface MarketContext {
  /** Elo em disputa (ou o último elo, se a cadeia estiver fechada). */
  stage: number;
  label: string;
  closed: boolean;
  prices: MarketPrice[];
}

/**
 * Contexto de mercado da vista: preços (`prices` do frame) das commodities do
 * elo mais alto em disputa. Preço constante (device/supercomputer nesta
 * corrida) é mostrado como está — a spec proíbe exigir variação (VIS-06).
 * Frame sem `prices` degrada para lista vazia, nunca erro (VIS-12).
 */
export function marketContext(frame: Frame, firsts: (LinkFirst | null)[]): MarketContext {
  const frontier = frontierStage(firsts);
  const stage = frontier ?? CHAIN_LINKS[CHAIN_LINKS.length - 1].stage;
  const link = CHAIN_LINKS[stage - 1];
  const prices = frame.prices ?? {};
  return {
    stage,
    label: link.label,
    closed: frontier === null,
    prices: link.outputs
      .filter((key) => typeof prices[key] === 'number')
      .map((key) => ({ resource: key, label: resourceInfo(key).label, price: prices[key] })),
  };
}

export interface StockLine {
  resource: string;
  label: string;
  amount: number;
}

/** Estoques legíveis de uma empresa: só commodities com amount > 0, maior primeiro. */
export function stocksList(company: Company): StockLine[] {
  const stocks = stocksOf(company);
  return Object.entries(stocks)
    .filter(([, amount]) => typeof amount === 'number' && amount > 0)
    .map(([resource, amount]) => ({ resource, label: resourceInfo(resource).label, amount }))
    .sort((a, b) => b.amount - a.amount);
}

const amountFmt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
const priceFmt = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
});

export const formatAmount = (n: number) => amountFmt.format(n);
export const formatPrice = (n: number) => priceFmt.format(n);

/**
 * HTML da barra da cadeia (sempre visível): 5 segmentos nomeados; por elo,
 * quem dominou primeiro + tick (com a cor da empresa do frame, quando ela
 * está no frame — cor nunca é o único canal: nome e tick vão em texto), ou
 * "ninguém ainda". O elo em disputa ganha a marca textual "em disputa".
 */
export function chainBarHtml(
  chronicle: ChronicleEvent[],
  frame: Frame,
  colorByName: Map<string, string>,
): string {
  const firsts = firstByLink(chronicle, frame.tick);
  const frontier = frontierStage(firsts);
  const market = marketContext(frame, firsts);
  const segs = CHAIN_LINKS.map((link) => {
    const first = firsts[link.stage - 1];
    const state = first ? 'dominado' : link.stage === frontier ? 'em disputa' : 'aberto';
    const who = first
      ? `<span class="cwho"><span class="dot" style="background:${esc(colorByName.get(first.company) ?? '#8b96b8')}"></span>${esc(first.company)} · tick ${first.tick}</span>`
      : '<span class="cwho dim">ninguém ainda</span>';
    return (
      `<div class="cseg ${state.replace(' ', '-')}" aria-label="elo ${link.stage} de 5, ${esc(link.label)}: ${state}${first ? `, primeiro ${esc(first.company)} no tick ${first.tick}` : ''}">` +
      `<span class="clabel">${link.stage}. ${esc(link.label)}</span>${who}` +
      (link.stage === frontier ? '<span class="tag tag-front">em disputa</span>' : '') +
      '</div>'
    );
  }).join('<span class="carrow" aria-hidden="true">→</span>');
  const prices = market.prices.length
    ? market.prices.map((p) => `${esc(p.label)} ${esc(formatPrice(p.price))}`).join(' · ')
    : 'preços indisponíveis neste frame';
  const marketHtml =
    `<div class="cmarket">mercado do elo ${market.closed ? 'final' : 'em disputa'} ` +
    `(${esc(market.label)}): ${prices}</div>`;
  return `<div class="csegs">${segs}</div>${marketHtml}`;
}

interface LayoutNode {
  id: string;
  stage: number;
  label: string;
  x0?: number;
  x1?: number;
  y0?: number;
  y1?: number;
  value?: number;
}
interface LayoutLink {
  source: LayoutNode;
  target: LayoutNode;
  value: number;
  width?: number;
  y0?: number;
  y1?: number;
}

/**
 * SVG da vista-cadeia (d3-sankey faz o layout; o render é próprio, ADR §3.5).
 * Sem fluxo positivo entre elos (ex.: tick 0), o layout do d3-sankey colapsa
 * (alturas nulas) — nesse caso os 5 nós saem em caixas iguais, sem links, com
 * a nota textual. A equivalência textual completa vive em `chainStateListHtml`.
 */
export function sankeySvg(frame: Frame, width = 340, height = 190): string {
  const data = sankeyData(frame);
  const total = data.links.reduce((acc, l) => acc + l.value, 0);
  const open =
    `<svg class="sankey" viewBox="0 0 ${width} ${height}" width="100%" role="img" ` +
    `aria-label="Vista da cadeia: fluxo derivado de estoques entre os 5 elos">`;
  if (total <= 0) {
    const bw = width / data.nodes.length;
    const boxes = data.nodes
      .map(
        (n, i) =>
          `<g><rect x="${(i * bw + 3).toFixed(1)}" y="${height / 2 - 16}" width="${(bw - 6).toFixed(1)}" height="32" class="snode aberto"></rect>` +
          `<text x="${(i * bw + bw / 2).toFixed(1)}" y="${height / 2 + 4}" class="slabel" text-anchor="middle">${esc(n.label)}</text></g>`,
      )
      .join('');
    return `${open}${boxes}<text x="${width / 2}" y="${height - 8}" class="snote" text-anchor="middle">sem fluxo entre elos neste frame</text></svg>`;
  }
  const layout = sankey<LayoutNode, LayoutLink>()
    .nodeId((d) => d.id)
    .nodeWidth(12)
    .nodePadding(10)
    .extent([
      [1, 8],
      [width - 1, height - 22],
    ]);
  // Na entrada do layout, source/target são os ids dos nós (resolvidos pelo
  // nodeId); os tipos do d3-sankey pedem os nós já resolvidos — o cast fica
  // concentrado nesta fronteira, como o do topojson em main.ts.
  const graph = layout({
    nodes: data.nodes.map((d) => ({ ...d })),
    links: data.links.map((d) => ({ ...d })),
  } as unknown as { nodes: LayoutNode[]; links: LayoutLink[] });
  const path = sankeyLinkHorizontal<LayoutNode, LayoutLink>();
  const linksSvg = graph.links
    .filter((l) => l.value > 0)
    .map(
      (l) =>
        `<path d="${path(l) ?? ''}" class="slink" style="stroke-width:${Math.max(1, l.width ?? 0)}"></path>`,
    )
    .join('');
  const nodesSvg = graph.nodes
    .map((n) => {
      const dominated = companyStageReached(frame, n.stage);
      const midY = ((n.y0 ?? 0) + (n.y1 ?? 0)) / 2;
      const labelY = (n.y1 ?? 0) + 13;
      return (
        `<g><rect x="${n.x0}" y="${n.y0}" width="${(n.x1 ?? 0) - (n.x0 ?? 0)}" height="${Math.max(1.5, (n.y1 ?? 0) - (n.y0 ?? 0))}" class="snode ${dominated ? 'dominado' : 'aberto'}"></rect>` +
        `<text x="${((n.x0 ?? 0) + (n.x1 ?? 0)) / 2}" y="${labelY}" class="slabel" text-anchor="middle">${esc(n.label)}</text>` +
        `<text x="${((n.x0 ?? 0) + (n.x1 ?? 0)) / 2}" y="${midY + 3}" class="sval" text-anchor="middle">${n.value ? esc(formatAmount(n.value)) : ''}</text></g>`
      );
    })
    .join('');
  return `${open}${linksSvg}${nodesSvg}</svg>`;
}

/** Alguma empresa do frame já dominou este elo (stage >= elo)? */
export function companyStageReached(frame: Frame, stage: number): boolean {
  return frame.companies.some((c) => companyProgress(c).filled >= stage);
}

/**
 * Equivalência textual da vista-cadeia (acessibilidade, VIS-10): lista com,
 * por elo, o estado — primeiro a dominar + tick ou "ninguém ainda" — e o
 * total em estoque das commodities de saída naquele frame.
 */
export function chainStateListHtml(chronicle: ChronicleEvent[], frame: Frame): string {
  const firsts = firstByLink(chronicle, frame.tick);
  const items = CHAIN_LINKS.map((link) => {
    const first = firsts[link.stage - 1];
    const state = first ? `dominado primeiro por ${esc(first.company)} (tick ${first.tick})` : 'ninguém ainda';
    return `<li><b>${link.stage}. ${esc(link.label)}</b> — ${state} · estoque do elo: ${esc(formatAmount(eloStocks(frame, link.stage)))} un</li>`;
  }).join('');
  return `<ul class="chain-list">${items}</ul>`;
}

/** Lista de estoques da empresa selecionada (painel de seleção — VIS-06). */
export function stocksListHtml(company: Company): string {
  const lines = stocksList(company);
  if (!lines.length) return '<p class="selstocks dim">sem estoques neste frame</p>';
  const items = lines
    .map(
      (l) =>
        `<li><span>${esc(l.label)}</span><span class="samt">${esc(formatAmount(l.amount))} un</span></li>`,
    )
    .join('');
  return `<div class="selstocks"><h3>Estoques (frame atual)</h3><ul>${items}</ul></div>`;
}

/** Trecho do painel de seleção com o progresso da empresa na escala da cadeia. */
export function selectionProgressHtml(company: Company): string {
  const seg = companyProgress(company);
  return (
    `<span class="stage">elo: ${esc(seg.label)} (${seg.filled}/${seg.total})</span> ` +
    segmentsHtml(company.stage)
  );
}
