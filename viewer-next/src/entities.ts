// Entidades orientadas a dados (SPEC VIS-02): NENHUMA lista de cidades/depósitos vive
// no código de desenho. Cidade vem da camada-mundo (world_data); depósito, da corrida
// (frames) ou do mundo — quem chama decide a fonte, o desenho só recebe a lista.
import type { City, Deposit, Frame, WorldData } from './contracts';

export function citiesFromWorld(world: WorldData): City[] {
  return world.cities;
}

export function depositsFromFrame(frame: Frame): Deposit[] {
  return frame.deposits;
}

export function depositsFromWorld(world: WorldData): Deposit[] {
  return world.deposits;
}

/** Conversão célula → lon/lat: mesma grade do legado (célula 2,5°, origem lon −82 / lat 14). */
export function cellToLonLat(cell: [number, number]): { lon: number; lat: number } {
  const [row, col] = cell;
  return { lon: -82 + col * 2.5 + 1.25, lat: 14 - row * 2.5 - 1.25 };
}
