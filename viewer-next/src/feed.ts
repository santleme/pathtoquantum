// Feed da crônica (F2 — VIS-03/VIS-04): classificação por kind com hierarquia,
// narrativa sem `flows`, lote de "novos" por avanço de frame e HTML dos itens.
// Lógica pura e testável — main.ts só liga isto ao DOM e ao replay.
import type { ChronicleEvent } from './contracts';

export type Tier = 'marco' | 'estrutural' | 'fundacao' | 'rotina' | 'contabil';

// Hierarquia da spec (VIS-03): marco > estrutural > fundação > rotina > contábil —
// expressa no runtime pelas classes CSS tier-* de index.html, não por rank numérico.

interface KindMeta {
  tier: Tier;
  label: string;
  icon: string; // miolo do SVG (viewBox 24, traço currentColor) — selo próprio por kind, sem emoji
}

const I = {
  chain: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  flagEnd: '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4L17 12H5"/>',
  award: '<circle cx="12" cy="9" r="5"/><path d="M8.6 13.4 7 21l5-2.5L17 21l-1.6-7.6"/>',
  down: '<path d="M3 6l6 6 4-4 8 8"/><path d="M15 16h6v-6"/>',
  merge: '<path d="M17 3l4 4-4 4"/><path d="M21 7H9a5 5 0 0 0-5 5"/><path d="M7 21l-4-4 4-4"/><path d="M3 17h12a5 5 0 0 0 5-5"/>',
  factory: '<path d="M3 21V10l6 4v-4l6 4V5h6v16"/><path d="M3 21h18"/>',
  mountain: '<path d="M3 20 9 8l4 6 3-4 5 10z"/>',
  landmark: '<path d="M4 21V9l8-5 8 5v12"/><path d="M2 21h20"/><path d="M10 21v-5h4v5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  wrench:
    '<path d="M14.7 6.3a4.5 4.5 0 0 0-5.9 5.9L3 18l3 3 5.8-5.8a4.5 4.5 0 0 0 5.9-5.9L14 13l-3-3 3.7-3.7z"/>',
  zap: '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
  ledger: '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  dot: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/>',
};

export const KIND_META: Record<string, KindMeta> = {
  chain_link: { tier: 'marco', label: 'Marco de cadeia', icon: I.chain },
  end: { tier: 'marco', label: 'Fim do período', icon: I.flagEnd },
  record: { tier: 'marco', label: 'Recorde', icon: I.award },
  bankruptcy: { tier: 'marco', label: 'Falência', icon: I.down },
  acquisition: { tier: 'marco', label: 'Aquisição', icon: I.merge },
  facility: { tier: 'estrutural', label: 'Instalação', icon: I.factory },
  mine: { tier: 'estrutural', label: 'Mina', icon: I.mountain },
  founding: { tier: 'fundacao', label: 'Fundação', icon: I.landmark },
  probe: { tier: 'fundacao', label: 'Sondagem', icon: I.search },
  tool: { tier: 'rotina', label: 'Ferramenta', icon: I.wrench },
  god: { tier: 'rotina', label: 'Intervenção divina', icon: I.zap },
  flows: { tier: 'contabil', label: 'Contábil', icon: I.ledger },
};

export interface KindClass {
  tier: Tier;
  label: string;
  icon: string;
  /** true quando o kind não está na taxonomia — estilo genérico de rotina (VIS-03). */
  generic: boolean;
}

export function classifyKind(kind: string): KindClass {
  const meta = KIND_META[kind];
  if (meta) return { ...meta, generic: false };
  // Kind desconhecido é caso esperado (rivalry, era_summary…): rotina genérica, texto integral.
  return { tier: 'rotina', label: kind, icon: I.dot, generic: true };
}

export function iconSvg(kind: string): string {
  const { icon } = classifyKind(kind);
  return `<svg class="kicon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icon}</svg>`;
}

export interface FeedItem {
  event: ChronicleEvent;
  /** Índice do evento na crônica original — identidade estável p/ lote de novos e conferência. */
  index: number;
  kind: KindClass;
}

/**
 * Itens narrativos até o tick dado, em ordem cronológica: tudo que não é `flows`
 * (contábil, texto vazio — nunca vira item, VIS-03) e tem texto.
 */
export function narrativeItems(chronicle: ChronicleEvent[], upToTick: number): FeedItem[] {
  const items: FeedItem[] = [];
  chronicle.forEach((event, index) => {
    if (event.tick > upToTick) return;
    if (event.kind === 'flows') return;
    if (!event.text || !event.text.trim()) return;
    items.push({ event, index, kind: classifyKind(event.kind) });
  });
  return items;
}

/**
 * Lote de "novos" da definição normativa (VIS-04): índices dos eventos narrativos com
 * prevTick < tick <= tick. prevTick=null = primeiro frame (tudo até tick é novo).
 * Avanço para trás ou nulo (scrub/jump) = lote vazio — a marca nunca fica para trás.
 */
export function newItemIndexes(chronicle: ChronicleEvent[], prevTick: number | null, tick: number): Set<number> {
  const out = new Set<number>();
  if (prevTick !== null && tick <= prevTick) return out;
  const from = prevTick ?? Number.NEGATIVE_INFINITY;
  for (const item of narrativeItems(chronicle, tick)) {
    if (item.event.tick > from) out.add(item.index);
  }
  return out;
}

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

/**
 * HTML de um item do feed. companyColor vem do frame (mapa nome→cor); empresa fora do
 * frame ou evento sem company = marcador oco, nenhuma cor inventada. Cor nunca é o único
 * canal: o nome da empresa e o rótulo do kind vão em texto, e "novo" é selo textual.
 */
export function feedItemHtml(item: FeedItem, companyColor: string | undefined, isNew: boolean): string {
  const e = item.event;
  const company = e.company
    ? `<span class="chip"><span class="dot${companyColor ? '' : ' hollow'}"${companyColor ? ` style="background:${esc(companyColor)}"` : ''}></span>${esc(e.company)}</span>`
    : '';
  const novo = isNew ? '<span class="tag tag-new">novo</span>' : '';
  return (
    `<button type="button" class="feed-item tier-${item.kind.tier}${isNew ? ' is-new' : ''}"` +
    ` data-tick="${e.tick}" data-kind="${esc(e.kind)}" data-index="${item.index}"` +
    ` title="Ir ao tick ${e.tick}">` +
    `<span class="kicon-wrap">${iconSvg(e.kind)}</span>` +
    `<span class="fbody"><span class="fmeta"><b class="fdate">${esc(e.date)}</b>` +
    `<span class="tag">${esc(item.kind.label)}</span>${novo}</span>` +
    `<span class="ftext">${esc(e.text)}</span>${company}</span></button>`
  );
}

/** Tick de um clique no feed: sobe a cadeia de alvos até achar [data-tick] (delegação). */
export function tickFromFeedTarget(target: unknown): number | null {
  let el = target as { dataset?: Record<string, string>; parentElement?: unknown } | null;
  while (el) {
    const tick = el.dataset?.tick;
    if (tick !== undefined) {
      const n = Number(tick);
      return Number.isFinite(n) ? n : null;
    }
    el = (el.parentElement as typeof el) ?? null;
  }
  return null;
}
