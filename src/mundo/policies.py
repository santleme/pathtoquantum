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
- ``kind="program"`` — política-código da forja (Degrau 2): o arquivo
  em ``program_path`` define ``EvolvedPolicy``; ``program_hash`` é a
  identidade (validado na carga, pela guarda de ``mundo.program``).
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import HeuristicPolicy, Policy
from .genome import GENOME0, GenomePolicy, mutate


@dataclass(frozen=True)
class PolicySpec:
    kind: str = "v0"                      # "v0" | "genome" | "mutant" | "program"
    genome: tuple | None = None           # kind="genome"
    seed: int | None = None               # kind="mutant"
    sigma: float = 0.35                   # kind="mutant" (em espaço z)
    program_path: str | None = None       # kind="program"
    program_hash: str | None = None       # kind="program"

    @staticmethod
    def v0() -> "PolicySpec":
        return PolicySpec("v0")

    @staticmethod
    def program(path) -> "PolicySpec":
        from pathlib import Path

        from .program import program_hash
        p = Path(path)
        return PolicySpec("program", program_path=str(p),
                          program_hash=program_hash(
                              p.read_text(encoding="utf-8")))

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
    if spec.kind == "program":
        if not spec.program_hash:
            raise ValueError(
                "spec de programa sem hash: use PolicySpec.program() "
                "(o hash é a identidade do candidato)")
        from .program import load_program_policy
        policy = load_program_policy(spec.program_path)
        if policy.program_hash != spec.program_hash:
            raise ValueError(
                f"programa mudou desde a spec: hash {policy.program_hash} "
                f"!= {spec.program_hash}")
        return policy
    raise ValueError(f"PolicySpec.kind desconhecido: {spec.kind!r}")


class PolicyRouter(Policy):
    """Despacha ``decide`` e as fachadas por empresa (``obs.me.cid``).

    Desde a fatia 3 o despacho é declarativo: ``decide`` e as fases
    devolvem as intenções da política da empresa (quem aplica é o
    motor); ``build_downstream`` devolve o par (construiu?,
    intenções) da política despachada."""

    def __init__(self, by_cid: dict | None = None,
                 default: Policy | None = None):
        self.by_cid = dict(by_cid or {})
        self.default = default if default is not None else HeuristicPolicy()

    def _for(self, cid: int) -> Policy:
        return self.by_cid.get(cid, self.default)

    # -- a interface que o motor chama --------------------------------
    def decide(self, obs) -> list:
        return self._for(obs.me.cid).decide(obs)

    def reserve(self, me) -> float:
        return self._for(me.cid).reserve(me)

    def pick_deposit(self, obs):
        return self._for(obs.me.cid).pick_deposit(obs)

    def build_downstream(self, obs, spendable: float, plan=None):
        return self._for(obs.me.cid).build_downstream(obs, spendable,
                                                      plan)

    def plan_buys(self, obs, plan=None) -> list:
        return self._for(obs.me.cid).plan_buys(obs, plan)

    def buffer(self, me, commodity: str) -> float:
        return self._for(me.cid).buffer(me, commodity)

    def plan_sells(self, obs, plan=None) -> list:
        return self._for(obs.me.cid).plan_sells(obs, plan)

    def use_tools(self, obs, plan=None) -> list:
        return self._for(obs.me.cid).use_tools(obs, plan)


def build_router(specs) -> PolicyRouter:
    """Um PolicyRouter a partir das specs alinhadas por cid (0..N-1)."""
    return PolicyRouter({i: build_policy(s) for i, s in enumerate(specs)})
