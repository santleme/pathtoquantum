import { describe, expect, it } from 'vitest';
import { parseRunData, frameIndexForTick, type ChronicleEvent } from '../src/contracts';
import {
  classifyKind,
  feedItemHtml,
  narrativeItems,
  newItemIndexes,
  tickFromFeedTarget,
} from '../src/feed';
import servedFrames from '../../viewer/frames.json';

const run = parseRunData(servedFrames);
const ch = run.chronicle;
const ev = (kind: string, extra: Partial<ChronicleEvent> = {}): ChronicleEvent => ({
  tick: 5,
  kind,
  text: `evento ${kind}`,
  company: 'Órbita Systems',
  date: 'fev/2027',
  ...extra,
});

describe('classificação por kind (VIS-03)', () => {
  it('hierarquia da spec: marco > estrutural > fundação > rotina > contábil', () => {
    for (const k of ['chain_link', 'end', 'record', 'bankruptcy', 'acquisition'])
      expect(classifyKind(k).tier, k).toBe('marco');
    for (const k of ['facility', 'mine']) expect(classifyKind(k).tier, k).toBe('estrutural');
    for (const k of ['founding', 'probe']) expect(classifyKind(k).tier, k).toBe('fundacao');
    for (const k of ['tool', 'god']) expect(classifyKind(k).tier, k).toBe('rotina');
    expect(classifyKind('flows').tier).toBe('contabil');
    // A hierarquia é a classificação kind→tier que o runtime usa (classes tier-*):
    // um kind representativo por nível, na ordem da spec.
    expect(['chain_link', 'facility', 'founding', 'tool', 'flows'].map((k) => classifyKind(k).tier)).toEqual([
      'marco',
      'estrutural',
      'fundacao',
      'rotina',
      'contabil',
    ]);
  });

  it('cada kind conhecido tem rótulo pt-BR e ícone SVG próprio (sem emoji)', () => {
    for (const k of ['chain_link', 'end', 'record', 'bankruptcy', 'acquisition', 'facility', 'mine', 'founding', 'probe', 'tool', 'god', 'flows']) {
      const c = classifyKind(k);
      expect(c.generic, k).toBe(false);
      expect(c.label.length, k).toBeGreaterThan(0);
      expect(c.icon, k).toContain('<');
    }
    // ícones distintos entre os kinds narrativos principais
    const icons = new Set(['chain_link', 'facility', 'founding', 'probe', 'tool'].map((k) => classifyKind(k).icon));
    expect(icons.size).toBe(5);
  });

  it('kind desconhecido (rivalry) = rotina genérica, sem erro, texto integral', () => {
    const c = classifyKind('rivalry');
    expect(c.tier).toBe('rotina');
    expect(c.generic).toBe(true);
    expect(c.label).toBe('rivalry');
    const [item] = narrativeItems([ev('rivalry', { text: 'RIVALIDADE: A × B.' })], 5);
    const html = feedItemHtml(item, '#e63946', false);
    expect(html).toContain('RIVALIDADE: A × B.');
    expect(html).toContain('rivalry');
  });
});

describe('narrativa sem flows (VIS-03, corrida servida)', () => {
  it('frame final (tick 120): 119 itens, 0 flows, 0 vazios, em ordem cronológica', () => {
    const items = narrativeItems(ch, 120);
    expect(items).toHaveLength(119);
    expect(items.every((i) => i.event.kind !== 'flows')).toBe(true);
    expect(items.every((i) => i.event.text.trim().length > 0)).toBe(true);
    const ticks = items.map((i) => i.event.tick);
    expect(ticks).toEqual([...ticks].sort((a, b) => a - b));
    expect(items[0].event.kind).toBe('founding');
    expect(items[items.length - 1].event.kind).toBe('end');
  });

  it('tick 0: só os 10 eventos fundadores/sondagens iniciais', () => {
    expect(narrativeItems(ch, 0)).toHaveLength(10);
  });

  it('marcador de empresa: cor do frame + nome; sem company = sem marcador nem cor inventada', () => {
    const [link] = narrativeItems([ev('chain_link')], 5);
    const html = feedItemHtml(link, '#00bbf9', false);
    expect(html).toContain('background:#00bbf9');
    expect(html).toContain('Órbita Systems');
    expect(html).toContain('Marco de cadeia');
    const [fim] = narrativeItems([ev('end', { company: null })], 5);
    const htmlFim = feedItemHtml(fim, undefined, false);
    expect(htmlFim).not.toContain('class="chip"');
    // empresa fora do frame: marcador oco, nenhuma cor
    const htmlFora = feedItemHtml(link, undefined, false);
    expect(htmlFora).toContain('dot hollow');
    expect(htmlFora).not.toContain('background:');
  });
});

describe('destaque de novo (VIS-04)', () => {
  it('primeiro frame: lote = eventos de tick <= frame (10 no tick 0)', () => {
    expect(newItemIndexes(ch, null, 0).size).toBe(10);
  });

  it('avanço 0 → 12: lote = 46 eventos com 1 <= tick <= 12; tick 0 fora', () => {
    const lote = newItemIndexes(ch, 0, 12);
    expect(lote.size).toBe(46);
    for (const i of lote) {
      expect(ch[i].tick).toBeGreaterThanOrEqual(1);
      expect(ch[i].tick).toBeLessThanOrEqual(12);
    }
  });

  it('a marca migra: avanço seguinte 12 → 24 não repete o lote anterior', () => {
    const a = newItemIndexes(ch, 0, 12);
    const b = newItemIndexes(ch, 12, 24);
    expect(b.size).toBeGreaterThan(0);
    for (const i of b) expect(a.has(i)).toBe(false);
  });

  it('scrub para trás ou parado: lote vazio', () => {
    expect(newItemIndexes(ch, 12, 0).size).toBe(0);
    expect(newItemIndexes(ch, 12, 12).size).toBe(0);
  });

  it('item novo ganha selo textual "novo" (e o antigo, não)', () => {
    const [item] = narrativeItems([ev('probe')], 5);
    expect(feedItemHtml(item, '#fff', true)).toContain('>novo</span>');
    expect(feedItemHtml(item, '#fff', false)).not.toContain('tag-new');
  });
});

describe('clique no feed → salto do replay (VIS-07)', () => {
  it('tickFromFeedTarget sobe a cadeia até o [data-tick] e o alvo cai no frame certo', () => {
    const target = { dataset: {}, parentElement: { dataset: { tick: '8' }, parentElement: null } };
    const tick = tickFromFeedTarget(target);
    expect(tick).toBe(8);
    expect(frameIndexForTick(run, tick!)).toBe(0); // maior frame com tick <= 8 é o 0
    expect(frameIndexForTick(run, 12)).toBe(1);
    expect(tickFromFeedTarget({ dataset: {}, parentElement: null })).toBeNull();
    expect(tickFromFeedTarget(null)).toBeNull();
  });

  it('o HTML do item carrega data-tick/data-kind/data-index conferíveis', () => {
    const items = narrativeItems(ch, 120);
    const link = items.find((i) => i.event.kind === 'chain_link')!;
    const html = feedItemHtml(link, '#00bbf9', false);
    expect(html).toContain(`data-tick="${link.event.tick}"`);
    expect(html).toContain('data-kind="chain_link"');
    expect(html).toContain(`data-index="${link.index}"`);
    expect(html).toContain('<button');
  });
});
