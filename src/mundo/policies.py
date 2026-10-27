"""Roteador de políticas por empresa — infraestrutura de experimento.

O motor tem UMA política global (``Engine(policy=...)``); torneios
precisam de política distinta POR empresa (a focal candidata invadindo
um campo de rivais). ``PolicyRouter`` é uma ``Policy`` que despacha
cada chamada para a política registrada do ``cid`` da empresa — e, sem
nenhum registro (ou com todos os registros iguais à padrão), o
comportamento é bit-idêntico ao da política única (goldens provam).

``PolicySpec`` é a forma SERIALIZÁVEL (picklável) de descrever a
política de uma empresa — é o que viaja dentro do ``EpisodeSpec`` do
driver para os processos filhos:

- ``kind="v0"``     — a heurística v0 (``HeuristicPolicy`` padrão);
- ``kind="genome"`` — ``GenomePolicy`` com o ``genome`` dado;
- ``kind="mutant"`` — mutante determinístico do genoma 0: a ``seed``
  e o ``sigma`` (em z) SÃO a identidade do mutante.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import HeuristicPolicy, Policy
from .genome import GENOME0, GenomePolicy, mutate


@dataclass(frozen=True)
class PolicySpec:
    kind: str = "v0"                      # "v0" | "genome" | "mutant"
    genome: tuple | None = None           # kind="genome"
    seed: int | None = None               # kind="mutant"
    sigma: float = 0.35                   # kind="mutant" (em espaço z)

    @staticmethod
    def v0() -> "PolicySpec":
        return PolicySpec("v0")

    @staticmethod
    def of_genome(genome) -> "PolicySpec":
        return PolicySpec("genome", genome=tuple(float(g) for g in genome))

    @staticmethod
    def mutant(seed: int, sigma: float = 0.35) -> "PolicySpec":
        return PolicySpec("mutant", seed=int(seed), sigma=float(sigma))


def build_policy(spec: PolicySpec) -> Policy:
    if spec.kind == "v0":
        return HeuristicPolicy()
    if spec.kind == "genome":
        return GenomePolicy(spec.genome)
    if spec.kind == "mutant":
        return GenomePolicy(mutate(GENOME0, spec.seed, spec.sigma))
    raise ValueError(f"PolicySpec.kind desconhecido: {spec.kind!r}")


class PolicyRouter(Policy):
    """Despacha ``decide`` e as fachadas por empresa (``comp.cid``)."""

    def __init__(self, by_cid: dict | None = None,
                 default: Policy | None = None):
        self.by_cid = dict(by_cid or {})
        self.default = default if default is not None else HeuristicPolicy()

    def _for(self, comp) -> Policy:
        return self.by_cid.get(comp.cid, self.default)

    # -- a interface que o motor chama --------------------------------
    def decide(self, engine, comp) -> None:
        self._for(comp).decide(engine, comp)

    def reserve(self, comp) -> float:
        return self._for(comp).reserve(comp)

    def pick_deposit(self, engine, comp):
        return self._for(comp).pick_deposit(engine, comp)

    def build_downstream(self, engine, comp, spendable: float) -> bool:
        return self._for(comp).build_downstream(engine, comp, spendable)

    def plan_buys(self, engine, comp) -> None:
        self._for(comp).plan_buys(engine, comp)

    def buffer(self, comp, commodity: str) -> float:
        return self._for(comp).buffer(comp, commodity)

    def plan_sells(self, engine, comp) -> None:
        self._for(comp).plan_sells(engine, comp)

    def use_tools(self, engine, comp) -> None:
        self._for(comp).use_tools(engine, comp)


def build_router(specs) -> PolicyRouter:
    """Um PolicyRouter a partir das specs alinhadas por cid (0..N-1)."""
    return PolicyRouter({i: build_policy(s) for i, s in enumerate(specs)})
