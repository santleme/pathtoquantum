import { describe, expect, it } from 'vitest';
import { DEFAULT_LENS_ID, DIM_ALPHA, emphasisAlpha, LENSES, lensById, resolveLensSelection } from '../src/lenses';

describe('registro de lentes (VIS-05)', () => {
  it('registro declarativo: ids únicos, cada lente é {id, label, layer, status}', () => {
    const ids = LENSES.map((l) => l.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const l of LENSES) {
      expect(l.label.length).toBeGreaterThan(0);
      expect(l.layer).toBe(l.id);
      expect(['ativa', 'em-breve']).toContain(l.status);
    }
    // Registrar uma lente nova = 1 entrada neste formato — o registro aceita o
    // formato sem nenhuma mudança de desenho (a troca é resolvida por status).
    const estendida = [...LENSES, { id: 'x', label: 'X', layer: 'x', status: 'em-breve' as const }];
    expect(estendida).toHaveLength(LENSES.length + 1);
  });

  it('Empresas é a lente padrão e a única ativa nesta fatia', () => {
    expect(DEFAULT_LENS_ID).toBe('empresas');
    expect(lensById('empresas')?.status).toBe('ativa');
    for (const id of ['recursos', 'producao', 'comercio', 'cronica']) {
      expect(lensById(id)?.status, id).toBe('em-breve');
    }
  });

  it('trocar para lente ativa vale; "em breve" mantém a ativa e avisa — camada não muda', () => {
    expect(resolveLensSelection('empresas', 'empresas')).toEqual({ activeId: 'empresas', notice: null });
    const soon = resolveLensSelection('empresas', 'recursos');
    expect(soon.activeId).toBe('empresas');
    expect(soon.notice).toContain('em breve');
    const unknown = resolveLensSelection('empresas', 'nao-existe');
    expect(unknown.activeId).toBe('empresas');
    expect(unknown.notice).toContain('desconhecida');
  });

  it('troca de lente não move o frame: a resolução não recebe nem devolve tick/índice', () => {
    // Estado mínimo do replay: aplicar a troca preserva idx/tick por construção —
    // resolveLensSelection só decide a camada.
    const state = { lens: 'empresas', idx: 7, tick: 84 };
    const next = { ...state, lens: resolveLensSelection(state.lens, 'cronica').activeId };
    expect(next.idx).toBe(7);
    expect(next.tick).toBe(84);
    expect(next.lens).toBe('empresas'); // "em breve" não trocou nem a camada
  });
});

describe('ênfase e seleção na lente Empresas (VIS-05)', () => {
  it('sem seleção, ênfase 1 para todas; com seleção, as demais recuam em alpha', () => {
    expect(emphasisAlpha(null, 1)).toBe(1);
    expect(emphasisAlpha(2, 2)).toBe(1);
    expect(emphasisAlpha(2, 1)).toBe(DIM_ALPHA);
    expect(DIM_ALPHA).toBeLessThan(1);
  });
});
