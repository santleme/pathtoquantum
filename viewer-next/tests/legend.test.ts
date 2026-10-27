import { describe, expect, it } from 'vitest';
import { legendHtml, legendItems, type LegendItem } from '../src/legend';
import { parseRunData, type Frame } from '../src/contracts';
import servedFrames from '../../viewer/frames.json';

const run = parseRunData(servedFrames);
const frame0 = run.frames[0];
const finalFrame = run.frames[run.frames.length - 1];

const companies = (items: LegendItem[]) =>
  items.filter((i): i is Extract<LegendItem, { type: 'company' }> => i.type === 'company');
const notes = (items: LegendItem[]) =>
  items.filter((i): i is Extract<LegendItem, { type: 'note' }> => i.type === 'note');

describe('legenda viva — empresas derivadas do frame (F5, VIS-09/VIS-05)', () => {
  it('frame final: uma entrada por empresa do frame, com a cor EXATA do frame (sem hardcode)', () => {
    const items = companies(legendItems(finalFrame, 'empresas', { cityCount: 11 }));
    expect(items).toHaveLength(finalFrame.companies.length);
    for (const c of finalFrame.companies) {
      const item = items.find((i) => i.name === c.name);
      expect(item).toBeDefined();
      expect(item!.color).toBe(c.color);
      expect(item!.alive).toBe(c.alive);
    }
  });

  it('trocar de frame atualiza a legenda: empresa fora do frame não aparece', () => {
    const subset: Frame = { ...finalFrame, companies: finalFrame.companies.slice(0, 3) };
    const items = companies(legendItems(subset, 'empresas'));
    expect(items.map((i) => i.name)).toEqual(subset.companies.map((c) => c.name));
    expect(items.map((i) => i.name)).not.toContain(finalFrame.companies[7].name);
  });

  it('seleção e falência aparecem como texto, não só cor', () => {
    const dead: Frame = {
      ...finalFrame,
      companies: finalFrame.companies.map((c, i) => (i === 0 ? { ...c, alive: false } : c)),
    };
    const sel = dead.companies[1];
    const items = companies(legendItems(dead, 'empresas', { selectedId: sel.id }));
    expect(items[0].alive).toBe(false);
    expect(items.find((i) => i.name === sel.name)!.selected).toBe(true);
    const html = legendHtml(legendItems(dead, 'empresas', { selectedId: sel.id }));
    expect(html).toContain('† falida');
    expect(html).toContain('selecionada');
  });
});

describe('legenda viva — símbolos, cadeia e selos explicados', () => {
  it('explica ◆/● com as contagens do frame/mundo, os 5 elos e os tiers da crônica', () => {
    const items = legendItems(finalFrame, 'empresas', { cityCount: 11 });
    const symbols = items.filter((i) => i.type === 'symbol');
    expect(symbols.map((s) => (s as { glyph: string }).glyph)).toEqual(['◆', '●', '◉']);
    const html = legendHtml(items);
    expect(html).toContain(`${finalFrame.deposits.length} neste frame`);
    expect(html).toContain('11 do world_data');
    expect(html).toContain('SUPERCOMPUTADOR');
    // tiers derivados de KIND_META: marco cita marco de cadeia; rotina cita ferramenta
    expect(html).toContain('marco de cadeia');
    expect(html).toContain('ferramenta');
    expect(html).toContain('flows');
  });
});

describe('legenda viva — lente em breve e frame degradado (VIS-12)', () => {
  it('lente "em breve": nota honesta e legenda continua sendo a da Empresas', () => {
    const items = legendItems(finalFrame, 'recursos');
    expect(notes(items)[0].text).toContain('em breve');
    expect(companies(items)).toHaveLength(finalFrame.companies.length);
  });

  it('lente desconhecida: nota, sem exceção, sem inventar camada', () => {
    const items = legendItems(finalFrame, 'nao-existe');
    expect(notes(items)[0].text).toContain('desconhecida');
    expect(companies(items).length).toBeGreaterThan(0);
  });

  it('frame degradado (sem empresas/depósitos/preços): itens de símbolo/cadeia/tiers seguem, sem exceção', () => {
    const degraded: Frame = { tick: 0, date: '—', prices: {}, companies: [], deposits: [] };
    const items = legendItems(degraded, 'empresas');
    expect(companies(items)).toHaveLength(0);
    expect(items.some((i) => i.type === 'chain')).toBe(true);
    expect(items.filter((i) => i.type === 'tier')).toHaveLength(4);
    expect(legendHtml(items)).toContain('0 neste frame');
  });

  it('frame inicial (tick 0) tem as mesmas empresas e nenhuma nota de lente', () => {
    const items = legendItems(frame0, 'empresas');
    expect(companies(items)).toHaveLength(frame0.companies.length);
    expect(notes(items)).toHaveLength(1); // só a nota do contábil
  });
});
