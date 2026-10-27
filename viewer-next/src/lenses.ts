// Lentes (F3 — VIS-05): registro ÚNICO e declarativo. Registrar uma lente nova é
// declarar {id, rótulo, camada} aqui — nenhum `if` de lente vive no código de
// desenho; main.ts só consulta este registro para montar o seletor e resolver a
// troca. Nesta fatia só a lente Empresas está implementada; as demais constam
// como "em breve": selecioná-las NÃO muda a camada nem o frame, só avisa.

export interface Lens {
  id: string;
  /** Rótulo visível no seletor. */
  label: string;
  /** Camada de ênfase que a lente ativa sobre a mesma base (nome da camada). */
  layer: string;
  status: 'ativa' | 'em-breve';
}

export const LENSES: readonly Lens[] = [
  { id: 'empresas', label: 'Empresas', layer: 'empresas', status: 'ativa' },
  { id: 'recursos', label: 'Recursos', layer: 'recursos', status: 'em-breve' },
  { id: 'producao', label: 'Produção', layer: 'producao', status: 'em-breve' },
  { id: 'comercio', label: 'Comércio', layer: 'comercio', status: 'em-breve' },
  { id: 'cronica', label: 'Crônica', layer: 'cronica', status: 'em-breve' },
];

export const DEFAULT_LENS_ID = 'empresas';

export function lensById(id: string): Lens | undefined {
  return LENSES.find((l) => l.id === id);
}

export interface LensSelection {
  /** Lente ativa depois da tentativa de troca. */
  activeId: string;
  /** Aviso a mostrar (lente em breve/desconhecida) — null quando a troca valeu. */
  notice: string | null;
}

/**
 * Resolve uma troca de lente sem tocar em frame/tick: a troca nunca carrega
 * JSON nem move o replay — só muda a camada de ênfase (ou nada, se "em breve").
 */
export function resolveLensSelection(currentId: string, requestedId: string): LensSelection {
  const lens = lensById(requestedId);
  if (!lens) return { activeId: currentId, notice: `lente desconhecida: ${requestedId}` };
  if (lens.status !== 'ativa') {
    return { activeId: currentId, notice: `Lente ${lens.label}: em breve — a camada não muda nesta fatia.` };
  }
  return { activeId: lens.id, notice: null };
}

/** Alpha das empresas não selecionadas na lente Empresas (recuo — VIS-05). */
export const DIM_ALPHA = 0.3;

/**
 * Ênfase da lente Empresas: sem seleção, todas em 1; com seleção, a selecionada
 * fica em 1 e as demais recuam. A seleção em si é comunicada por anel/rótulo
 * (mapa) e selo textual (placar) — o alpha é só recuo, nunca o único canal.
 */
export function emphasisAlpha(selectedId: number | null, companyId: number): number {
  return selectedId === null || selectedId === companyId ? 1 : DIM_ALPHA;
}
