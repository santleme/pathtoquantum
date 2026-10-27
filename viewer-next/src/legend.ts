// Legenda viva da lente (F5 — VIS-09/VIS-05): substitui a legenda fixa de
// símbolos pela legenda derivada do FRAME atual e da lente ativa. Função pura
// (frame → itens) separada do DOM, no padrão da casa: quem está no frame entra
// na legenda com a cor do frame; quem saiu, sai — nada é lista fixa de empresas.
// Os símbolos explicados são os que a tela realmente usa: ◆/● do mapa (entities),
// segmentos de elo do placar (board.stageSegments) e selos/tiers da crônica
// (feed.KIND_META) — derivados das mesmas fontes, sem duplicar taxonomia.
import type { Frame } from './contracts';
import { KIND_META, type Tier } from './feed';
import { lensById } from './lenses';
import { STAGE_LABELS } from './resources';

export type LegendItem =
  | { type: 'note'; text: string }
  | { type: 'company'; name: string; color: string; alive: boolean; selected: boolean }
  | { type: 'symbol'; glyph: string; text: string }
  | { type: 'chain'; text: string }
  | { type: 'tier'; tier: Tier; text: string };

export interface LegendContext {
  /** Nº de cidades da camada-mundo (world_data) — o frame não carrega cidades. */
  cityCount?: number;
  selectedId?: number | null;
}

const TIER_ORDER: Tier[] = ['marco', 'estrutural', 'fundacao', 'rotina'];
const TIER_LABEL: Record<Tier, string> = {
  marco: 'marco',
  estrutural: 'estrutural',
  fundacao: 'fundação/sondagem',
  rotina: 'rotina',
  contabil: 'contábil',
};

/** Rótulos dos kinds de um tier, derivados de KIND_META (a taxonomia da crônica). */
function tierKindLabels(tier: Tier): string {
  return Object.values(KIND_META)
    .filter((m) => m.tier === tier)
    .map((m) => m.label.toLowerCase())
    .join(', ');
}

/**
 * Itens da legenda para o frame e a lente ativa. Lente "em breve" ou
 * desconhecida NÃO inventa camada: a legenda segue sendo a da camada atual
 * (Empresas), precedida de uma nota dizendo exatamente isso.
 */
export function legendItems(frame: Frame, lensId: string, ctx: LegendContext = {}): LegendItem[] {
  const items: LegendItem[] = [];
  const lens = lensById(lensId);
  if (!lens) {
    items.push({ type: 'note', text: `lente desconhecida (${lensId}) — legenda da camada atual (Empresas)` });
  } else if (lens.status !== 'ativa') {
    items.push({
      type: 'note',
      text: `lente ${lens.label} em breve — a camada não muda; legenda da lente ativa (Empresas)`,
    });
  }
  // Empresas DO FRAME: cor e nome vêm do frame (VIS-05) — entrou/saiu, a legenda segue.
  for (const c of frame.companies) {
    items.push({
      type: 'company',
      name: c.name,
      color: c.color,
      alive: c.alive,
      selected: ctx.selectedId != null && c.id === ctx.selectedId,
    });
  }
  // Símbolos do mapa (mesmos glifos do desenho e da legenda antiga, agora vivos):
  items.push({
    type: 'symbol',
    glyph: '◆',
    text: `depósito — nome, recurso e barra de reserva (${frame.deposits.length} neste frame, da corrida)`,
  });
  items.push({
    type: 'symbol',
    glyph: '●',
    text:
      ctx.cityCount != null
        ? `cidade-mercado (${ctx.cityCount} do world_data)`
        : 'cidade-mercado (da camada-mundo)',
  });
  items.push({
    type: 'symbol',
    glyph: '◉',
    text: 'empresa selecionada — anel e rótulo no mapa; as demais recuam (seleção nunca é só cor)',
  });
  // Segmentos de elo (placar e barra da cadeia leem a mesma escala stage/5):
  items.push({
    type: 'chain',
    text: `segmentos de elo: preenchidos = estágio da empresa na cadeia (${STAGE_LABELS.slice(1).join(' → ')})`,
  });
  // Selos da crônica por tier (hierarquia VIS-03), derivados de KIND_META:
  for (const tier of TIER_ORDER) {
    items.push({ type: 'tier', tier, text: `${TIER_LABEL[tier]}: ${tierKindLabels(tier)}` });
  }
  items.push({
    type: 'note',
    text: 'contábil (flows) não vira item da crônica — é agregado fora da narrativa',
  });
  return items;
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** HTML da legenda (puro, testável): main.ts só injeta no #legend. */
export function legendHtml(items: LegendItem[]): string {
  const parts: string[] = [];
  for (const it of items) {
    if (it.type === 'note') {
      parts.push(`<p class="lg-note">${esc(it.text)}</p>`);
    } else if (it.type === 'company') {
      const flags = `${it.alive ? '' : ' · † falida'}${it.selected ? ' · selecionada' : ''}`;
      parts.push(
        `<span class="lg-company"><span class="dot" style="background:${esc(it.color)}"></span>${esc(it.name)}${esc(flags)}</span>`,
      );
    } else if (it.type === 'symbol') {
      parts.push(`<p class="lg-line"><span class="lg-glyph">${esc(it.glyph)}</span> ${esc(it.text)}</p>`);
    } else if (it.type === 'chain') {
      parts.push(
        `<p class="lg-line"><span class="segs" aria-hidden="true"><span class="seg on"></span><span class="seg on"></span><span class="seg"></span><span class="seg"></span><span class="seg"></span></span> ${esc(it.text)}</p>`,
      );
    } else {
      parts.push(`<p class="lg-line lg-tier tier-${it.tier}">${esc(it.text)}</p>`);
    }
  }
  return parts.join('');
}
