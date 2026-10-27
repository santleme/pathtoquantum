// Registro de recursos/commodities (SPEC VIS-02): cobre as 11 commodities de `prices`.
// Rótulo pt-BR + símbolo distinto por commodity; desconhecido cai no fallback genérico.

export interface ResourceInfo {
  label: string;
  symbol: string;
}

export const RESOURCE_REGISTRY: Record<string, ResourceInfo> = {
  lithium_ore: { label: 'minério de lítio', symbol: 'Li◆' },
  copper_ore: { label: 'minério de cobre', symbol: 'Cu◆' },
  iron_ore: { label: 'minério de ferro', symbol: 'Fe◆' },
  oil: { label: 'petróleo', symbol: 'Oil◆' },
  lithium: { label: 'lítio', symbol: 'Li' },
  copper: { label: 'cobre', symbol: 'Cu' },
  iron: { label: 'ferro/aço', symbol: 'Fe' },
  plastic: { label: 'plástico', symbol: 'Pl' },
  component: { label: 'componentes', symbol: 'Cp' },
  device: { label: 'dispositivos', symbol: 'Dv' },
  supercomputer: { label: 'supercomputador', symbol: 'SC' },
};

export function resourceInfo(resource: string): ResourceInfo {
  return RESOURCE_REGISTRY[resource] ?? { label: resource, symbol: '?' };
}

export const STAGE_LABELS = ['—', 'extração', 'refino', 'componentes', 'dispositivos', 'SUPERCOMPUTADOR'];
