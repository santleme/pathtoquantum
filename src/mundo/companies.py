"""Empresas autônomas: agentes com personalidade, sem LLM por tick.

A personalidade (traços 0..1) parametriza a política heurística:
- aggression: velocidade de expansão/reivindicação;
- risk: aceita sondar/furar depósitos de teor incerto ou baixo;
- vertical: obsessão por fechar a cadeia (segura estoque p/ jusante,
  constrói o próximo elo cedo);
- marketing: propensão a gastar em InstaSim/ZapSim.

FOG-OF-WAR: a empresa só conhece teor/tamanho dos depósitos que ELA
sondou (knowledge). Decisão nenhuma lê a verdade oculta do mundo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import chain
from .tools_sim import ToolEffects
from .world import CITIES, DEPOSITS, cell_center

PALETTE = ["#e63946", "#f4a261", "#2a9d8f", "#457b9d",
           "#9b5de5", "#f15bb5", "#00bbf9", "#8ac926"]
ARCHETYPES = [
    ("Agressiva",     dict(aggression=0.90, risk=0.80, vertical=0.40, marketing=0.50)),
    ("Verticalizadora", dict(aggression=0.50, risk=0.45, vertical=0.95, marketing=0.25)),
    ("Marqueteira",   dict(aggression=0.55, risk=0.50, vertical=0.35, marketing=0.95)),
    ("Cautelosa",     dict(aggression=0.30, risk=0.20, vertical=0.60, marketing=0.30)),
    ("Expansionista", dict(aggression=0.80, risk=0.65, vertical=0.55, marketing=0.40)),
    ("Oportunista",   dict(aggression=0.65, risk=0.85, vertical=0.30, marketing=0.60)),
    ("Industrial",    dict(aggression=0.45, risk=0.40, vertical=0.80, marketing=0.20)),
    ("Visionária",    dict(aggression=0.60, risk=0.70, vertical=0.70, marketing=0.70)),
]
NAMES = ["Andina Prime", "Vetor Sul", "Cuprum Andes", "Ferra Brasil",
         "Lítio Austral", "Nexo Indústrias", "PetroPlata", "Órbita Systems"]


@dataclass
class Company:
    cid: int
    name: str
    archetype: str
    traits: dict
    hq_city: str
    color: str
    cash: float
    stocks: dict = field(default_factory=lambda: {c: 0.0 for c in chain.COMMODITIES})
    facilities: dict = field(default_factory=dict)   # fac_id -> facility dict
    claimed: set = field(default_factory=set)        # células reivindicadas
    knowledge: dict = field(default_factory=dict)    # dep_name -> (grade, size_t)
    tools: ToolEffects = field(default_factory=ToolEffects)
    alive: bool = True
    founded_tick: int = 0
    _fac_n: int = 0
    # Cache dos kinds de instalações (has()/chain_stage() são chamados
    # milhares de vezes por corrida). Manter sincronizado via
    # add_facility/_sync_kinds — nunca mutar facilities por fora sem
    # ressincronizar (o motor faz isso na aquisição e no restore).
    _kinds: set = field(default_factory=set, repr=False)

    def _sync_kinds(self) -> None:
        self._kinds = {f["kind"] for f in self.facilities.values()}

    def chain_stage(self) -> int:
        """Maior elo da cadeia que a empresa opera (0..5)."""
        for stage, kind in [(5, "assembly"), (4, "plant"), (3, "factory"),
                            (2, "refinery"), (1, "mine")]:
            if kind in self._kinds:
                return stage
        return 0

    def has(self, kind: str) -> bool:
        return kind in self._kinds

    def add_facility(self, kind: str, cell) -> dict:
        self._fac_n += 1
        fid = f"f{self.cid}-{self._fac_n}"
        fac = {"id": fid, "kind": kind, "cell": cell}
        self.facilities[fid] = fac
        self._kinds.add(kind)
        return fac


def make_companies(n: int, rng, start_cash: float = 40_000_000.0,
                   cities: list | None = None) -> list[Company]:
    cities = CITIES if cities is None else cities
    order = list(range(len(NAMES)))
    rng.shuffle(order)
    companies = []
    for i in range(n):
        k = order[i % len(order)]
        name_arch, traits = ARCHETYPES[k % len(ARCHETYPES)]
        city = cities[i % len(cities)]
        companies.append(Company(
            cid=i, name=NAMES[k], archetype=name_arch, traits=dict(traits),
            hq_city=city.name, color=PALETTE[i % len(PALETTE)],
            cash=start_cash * rng.uniform(0.85, 1.2)))
    return companies


def deposit_public_info():
    """O que todo mundo sabe: onde os depósitos estão e o que contêm.
    Teor e tamanho NÃO fazem parte da informação pública."""
    return [{"name": d.name, "resource": d.resource, "cell": d.cell,
             "lat": d.lat, "lon": d.lon} for d in DEPOSITS]
