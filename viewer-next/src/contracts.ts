// Contratos dos artefatos que o motor já emite (SPEC-VISUAL-WOW §0). O viewer é "burro":
// lê JSON, não simula nada. parse* validam o mínimo e lançam erro legível — nunca desenham
// por cima de dado quebrado em silêncio.

export interface Deposit {
  name: string;
  resource: string;
  lat: number;
  lon: number;
  remaining_frac: number;
  cell?: [number, number];
}

export interface Facility {
  kind: string;
  cell: [number, number];
}

export interface Company {
  id: number;
  name: string;
  archetype: string;
  color: string;
  hq: string;
  alive: boolean;
  cash: number;
  stage: number;
  territory: [number, number][];
  facilities: Facility[];
  stocks: Record<string, number>;
}

export interface Frame {
  tick: number;
  date: string;
  prices: Record<string, number>;
  companies: Company[];
  deposits: Deposit[];
}

export interface ChronicleEvent {
  tick: number;
  kind: string;
  text: string;
  company: string | null;
  date: string;
}

export interface RunData {
  seed: number;
  ticks: number;
  frames: Frame[];
  chronicle: ChronicleEvent[];
}

export interface City {
  name: string;
  country: string;
  lat: number;
  lon: number;
}

export interface WorldData {
  cities: City[];
  deposits: Deposit[];
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

export function parseRunData(raw: unknown): RunData {
  if (!isObj(raw) || !Array.isArray(raw.frames) || raw.frames.length === 0) {
    throw new Error('frames.json inválido: esperado {frames: [...]} com ao menos 1 frame');
  }
  const frames = raw.frames as Frame[];
  for (const f of frames) {
    if (typeof f.tick !== 'number' || !Array.isArray(f.companies) || !Array.isArray(f.deposits)) {
      throw new Error(`frame inválido (tick=${String((f as Frame).tick)})`);
    }
  }
  return {
    seed: typeof raw.seed === 'number' ? raw.seed : 0,
    ticks: typeof raw.ticks === 'number' ? raw.ticks : frames[frames.length - 1].tick,
    frames,
    chronicle: Array.isArray(raw.chronicle) ? (raw.chronicle as ChronicleEvent[]) : [],
  };
}

export function parseWorldData(raw: unknown): WorldData {
  if (!isObj(raw) || !Array.isArray(raw.cities) || !Array.isArray(raw.deposits)) {
    throw new Error('world_data.json inválido: esperado {cities: [...], deposits: [...]}');
  }
  return { cities: raw.cities as City[], deposits: raw.deposits as Deposit[] };
}

/** Índice do último frame com tick <= o pedido (0 se nenhum) — semântica do legado (VIS-07). */
export function frameIndexForTick(run: RunData, tick: number): number {
  let found = 0;
  for (let i = 0; i < run.frames.length; i++) {
    if (run.frames[i].tick <= tick) found = i;
    else break;
  }
  return found;
}

/** Resolve o parâmetro ?run= como no legado: rejeita `..`; vazio = corrida servida. */
export function resolveRunDir(search: string): string | null {
  const run = new URLSearchParams(search).get('run');
  if (!run) return null;
  if (run.includes('..')) throw new Error('?run= inválido: ".." não é permitido');
  return run.replace(/\/$/, '');
}
