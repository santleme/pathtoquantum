// Modos ?compare= e ?forge= (F6 — VIS-07, não-regressão das branches
// viewer/comparador-corridas e viewer/painel-forja): porte fiel do comportamento
// do legado para o padrão do app novo — funções puras + builders de HTML aqui,
// fiação (fetch) no main.ts. Mesmos parâmetros, mesmos formatos de artefato e
// mesma tolerância: artefato parcial/antigo degrada por painel para '—',
// nunca lança exceção que derrube a página (VIS-12).
import { money } from './board';
import type { Frame } from './contracts';
import { esc } from './feed';
import { STAGE_LABELS } from './resources';

/**
 * Resolve um parâmetro de diretório (?compare=/?forge=) com a trava do legado:
 * ausente ou contendo '..' → null (o modo simplesmente não liga); barra final
 * é aparada. (O ?run= mantém a semântica própria em contracts.resolveRunDir.)
 */
export function resolveModeDir(search: string, param: string): string | null {
  const v = new URLSearchParams(search).get(param);
  if (!v || v.includes('..')) return null;
  return v.replace(/\/$/, '');
}

// ---------------------------------------------------------------------------
// Comparador de corridas (?compare=) — compara o ÚLTIMO frame de duas corridas,
// empresa por empresa (pelo nome). Não toca no replay: sem o parâmetro, nada
// muda; com ele, só o painel de comparação é preenchido.
// ---------------------------------------------------------------------------

export interface CompareRow {
  name: string;
  cashA: number | null;
  cashB: number | null;
  delta: number | null;
  stageA: number | null;
  stageB: number | null;
  aliveA: boolean | null;
  aliveB: boolean | null;
}

export interface CompareResult {
  rows: CompareRow[];
  totalA: number;
  totalB: number;
}

export function compareRuns(framesA: Frame[], framesB: Frame[]): CompareResult {
  const last = (frames: Frame[]) => frames[frames.length - 1];
  const byName = (frames: Frame[]) => new Map((last(frames)?.companies ?? []).map((c) => [c.name, c]));
  const A = byName(framesA);
  const B = byName(framesB);
  const names = [...new Set([...A.keys(), ...B.keys()])].sort();
  const rows: CompareRow[] = names.map((name) => {
    const a = A.get(name);
    const b = B.get(name);
    return {
      name,
      cashA: a ? a.cash : null,
      cashB: b ? b.cash : null,
      delta: a && b ? b.cash - a.cash : null,
      stageA: a ? a.stage : null,
      stageB: b ? b.stage : null,
      aliveA: a ? a.alive : null,
      aliveB: b ? b.alive : null,
    };
  });
  const total = (m: 'cashA' | 'cashB') => rows.reduce((s, r) => s + (r[m] ?? 0), 0);
  return { rows, totalA: total('cashA'), totalB: total('cashB') };
}

const stageLabel = (s: number | null) =>
  s === null ? '—' : (STAGE_LABELS[Math.max(0, Math.min(5, Math.trunc(s)))] ?? '—');

export function compareHtml(cmp: CompareResult, labelB: string): string {
  const m = (v: number | null) => (v === null ? '—' : money(v));
  const rows = cmp.rows
    .map((r) => {
      const d =
        r.delta === null ? '—' : `${r.delta >= 0 ? '+' : '−'}${money(Math.abs(r.delta))}`;
      const cls = r.delta === null ? 'none' : r.delta >= 0 ? 'up' : 'down';
      const dead = r.aliveB === false ? ' <span class="tag tag-dead">† falida</span>' : '';
      return (
        `<div class="mrow"><span class="dot" style="background:#26304d"></span>` +
        `<span class="mmain">${esc(r.name)}${dead}<br>` +
        `<span class="stage">elo: ${esc(stageLabel(r.stageA))} → ${esc(stageLabel(r.stageB))}</span></span>` +
        `<span class="mcash">${m(r.cashA)} → ${m(r.cashB)}<br>` +
        `<span class="delta ${cls}">${d}</span></span></div>`
      );
    })
    .join('');
  return (
    `<div class="mrow mhead"><span></span><span>segunda corrida: ${esc(labelB)}</span>` +
    `<span class="mcash">${m(cmp.totalA)} → ${m(cmp.totalB)}</span></div>` +
    rows
  );
}

// ---------------------------------------------------------------------------
// Painel da forja (?forge=) — resume uma corrida da forja de políticas a partir
// dos artefatos dela: forge-v1.json (campeão, contagens, mutador),
// final_evaluation.json (avaliação cega) e run_log.jsonl (linha do tempo).
// Porte 1:1 da sumarização do legado (mesmos campos e fallbacks).
// ---------------------------------------------------------------------------

export interface ForgeLogEntry {
  iteration?: number | null;
  hash?: string | null;
  S1?: number | null;
  island?: string | number | null;
  status?: string;
  [k: string]: unknown;
}

export function parseRunLog(text: string | null | undefined): ForgeLogEntry[] {
  if (!text) return [];
  const out: ForgeLogEntry[] = [];
  for (const line of String(text).split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try {
      out.push(JSON.parse(t) as ForgeLogEntry);
    } catch {
      /* linha quebrada: ignora (legado) */
    }
  }
  return out;
}

/** Linha do tempo: só as iterações ACEITAS, na ordem do log. */
export function forgeTimeline(entries: ForgeLogEntry[]): ForgeLogEntry[] {
  return (entries || [])
    .filter((e) => e && e.status === 'accepted')
    .map((e) => ({
      iteration: e.iteration ?? null,
      hash: e.hash ?? null,
      S1: e.S1 ?? null,
      island: e.island ?? null,
    }));
}

type Rec = Record<string, unknown>;
const asRec = (v: unknown): Rec => (v && typeof v === 'object' ? (v as Rec) : {});
const numOrNull = (v: unknown): number | null => (typeof v === 'number' ? v : null);
const strOrNull = (v: unknown): string | null => (v === null || v === undefined ? null : String(v));

export interface ForgeDelta {
  mean: number | null;
  ci95: [number, number] | null;
}

export interface ForgeSummary {
  champion: { hash: string | null; S1: number | null; S2: number | null };
  seedResult: { hash: string | null; S1: number | null; S2: number | null } | null;
  verdict: string | null;
  iterationsCompleted: number | null;
  mutator: string | null;
  counts: Rec | null;
  mutatorStats: Rec | null;
  blind: {
    tournamentChampion: string | null;
    meanS: Rec | null;
    vsTournament: ForgeDelta | null;
    vsSeed: ForgeDelta | null;
  };
  timeline: ForgeLogEntry[];
}

function deltaOf(d: unknown): ForgeDelta | null {
  if (!d || typeof d !== 'object') return null;
  const rec = d as Rec;
  const ci = Array.isArray(rec.ci95) ? (rec.ci95 as [number, number]) : null;
  return { mean: numOrNull(rec.mean), ci95: ci };
}

export function summarizeForge(
  forgeRaw: unknown,
  finalEvalRaw: unknown,
  entries: ForgeLogEntry[],
): ForgeSummary {
  const forge = asRec(forgeRaw);
  const feCandidate = asRec(finalEvalRaw);
  const fe: Rec =
    Object.keys(feCandidate).length > 0 ? feCandidate : asRec(forge.final_evaluation);
  const champ = asRec(forge.champion);
  const seed = asRec(forge.seed_result);
  const log =
    entries && entries.length ? entries : Array.isArray(forge.records) ? (forge.records as ForgeLogEntry[]) : [];
  return {
    champion: {
      hash: strOrNull(champ.hash ?? forge.champion_hash ?? fe.champion_hash),
      S1: numOrNull(champ.S1),
      S2: numOrNull(champ.S2),
    },
    seedResult: forge.seed_result
      ? { hash: strOrNull(seed.hash), S1: numOrNull(seed.S1), S2: numOrNull(seed.S2) }
      : null,
    verdict: strOrNull(forge.verdict ?? (fe.verdict ? `FORGE-V1: ${String(fe.verdict)}` : null)),
    iterationsCompleted: numOrNull(forge.iterations_completed ?? forge.iterations),
    mutator: strOrNull(forge.mutator),
    counts: forge.counts ? asRec(forge.counts) : null,
    mutatorStats: forge.mutator_stats ? asRec(forge.mutator_stats) : null,
    blind: {
      tournamentChampion: strOrNull(fe.tournament_champion),
      meanS: fe.mean_S ? asRec(fe.mean_S) : null,
      vsTournament: deltaOf(fe.delta_vs_tournament),
      vsSeed: deltaOf(fe.delta_vs_seed),
    },
    timeline: forgeTimeline(log),
  };
}

const fnum = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : (+v).toFixed(4);
const fsgn = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : (v < 0 ? '−' : '+') + Math.abs(v).toFixed(4);

export function forgeHtml(sum: ForgeSummary, label: string): string {
  const ci = (d: ForgeDelta | null) =>
    d && d.ci95 ? ` <span class="stage">IC95 [${fnum(d.ci95[0])}, ${fnum(d.ci95[1])}]</span>` : '';
  const row = (k: string, v: string) =>
    `<div class="mrow"><span></span><span>${k}</span><span class="mcash">${v}</span></div>`;
  const prog = (h: string | null) => (h ? `prog:${esc(h)}` : '—');
  let h = `<div class="mrow mhead"><span></span><span>corrida da forja: ${esc(label)}</span><span></span></div>`;
  if (sum.verdict) {
    const cls = sum.verdict.includes('APROVADO')
      ? 'ok'
      : sum.verdict.includes('BLOQUEADO')
        ? 'warn'
        : 'bad';
    h += `<div class="verdict ${cls}"><b>${esc(sum.verdict)}</b></div>`;
  }
  const done = sum.iterationsCompleted === null ? '' : ` · ${sum.iterationsCompleted} iterações`;
  const mut = sum.mutator ? ` · mutador ${esc(sum.mutator)}` : '';
  h += `<h3>Campeão final${done}${mut}</h3>`;
  h += row(prog(sum.champion.hash), `S1 ${fnum(sum.champion.S1)} · S2 ${fnum(sum.champion.S2)}`);
  if (sum.seedResult) {
    h += row(
      `semente ${prog(sum.seedResult.hash)}`,
      `S1 ${fnum(sum.seedResult.S1)} · S2 ${fnum(sum.seedResult.S2)}`,
    );
  }
  if (sum.counts) {
    const c = sum.counts;
    const chip = (k: string, labelC: string) =>
      `<span class="tag mchip">${labelC} <b>${esc(String(c[k] ?? '—'))}</b></span>`;
    h +=
      '<h3>Contagens</h3><div class="chips">' +
      chip('accepted', 'aceitas') +
      chip('rejected_llm', 'rejeitadas (LLM)') +
      chip('rejected_guard', 'rejeitadas (guarda)') +
      chip('error', 'erros') +
      chip('duplicate', 'duplicadas') +
      '</div>';
  }
  const b = sum.blind;
  if (b.vsTournament || b.vsSeed || b.meanS) {
    h += '<h3>Avaliação cega</h3>';
    if (b.tournamentChampion) h += row('campeão do torneio', esc(b.tournamentChampion));
    if (b.vsTournament) h += row('ΔS vs torneio', fsgn(b.vsTournament.mean) + ci(b.vsTournament));
    if (b.vsSeed) h += row('ΔS vs semente', fsgn(b.vsSeed.mean) + ci(b.vsSeed));
    if (b.meanS) {
      const m = b.meanS;
      const part = (k: string, labelP: string) =>
        m[k] === undefined ? '' : `${labelP} ${fnum(numOrNull(m[k]))}`;
      h += row(
        'S médio no teste',
        [
          part('forge_champion', 'forja'),
          part('seed', 'semente'),
          part('tournament_champion', 'torneio'),
        ]
          .filter(Boolean)
          .join(' · '),
      );
    }
  }
  const st = sum.mutatorStats;
  if (st) {
    h += '<h3>Mutador</h3>';
    const calls = asRec(st.calls);
    if (Object.keys(calls).length) {
      h += Object.entries(calls)
        .sort((x, y) => Number(y[1]) - Number(x[1]))
        .map(
          ([route, n]) =>
            `<div class="mrow"><span></span><span>${esc(route)}</span><span class="mcash">${esc(String(n))} chamadas</span></div>`,
        )
        .join('');
    }
    const extra = Object.entries(st)
      .filter(([k, v]) => k !== 'calls' && typeof v === 'number')
      .map(([k, v]) => `<span class="tag mchip">${esc(k)} <b>${esc(String(v))}</b></span>`)
      .join('');
    if (extra) h += `<div class="chips">${extra}</div>`;
  }
  h += '<h3>Linha do tempo — iterações aceitas</h3>';
  h += sum.timeline.length
    ? sum.timeline
        .map(
          (t) =>
            `<div class="mrow"><span class="dot" style="background:#9ae6b4"></span>` +
            `<span>#${t.iteration ?? '—'} · ${prog(strOrNull(t.hash))}<br>` +
            `<span class="stage">ilha ${esc(String(t.island ?? '—'))}</span></span>` +
            `<span class="mcash">S1 ${fnum(numOrNull(t.S1))}</span></div>`,
        )
        .join('')
    : '<div class="ev">Nenhuma iteração aceita no log.</div>';
  return h;
}
