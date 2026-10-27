"""Driver de episódios — a alavanca de throughput de treino da Fase 1.

Episódios são independentes por construção (cada um é um ``Engine``
com a própria seed/RNG), então rodar N mundos é embaraçosamente
paralelo. Este driver roda as specs em série ou num pool de
processos e devolve os resultados **na ordem das specs** — a
agregação é determinística, independente da ordem de conclusão.

Uso típico (avaliação de políticas / CMA-ES)::

    specs = [EpisodeSpec(seed=s, ticks=120) for s in range(64)]
    results = run_episodes(specs, processes=4)
    fitness = [score(r) for r in results]      # ordem == ordem das specs
"""
from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass

from .engine import Engine


@dataclass(frozen=True)
class EpisodeSpec:
    """Um episódio: mundo completo, identificado pela seed."""

    seed: int
    ticks: int = 120
    n_companies: int = 8
    world_data: bool = True
    market_v2: bool = False             # B1 mercado vivo (Fase 2)
    market_params: dict | None = None   # override de parâmetros do B1
    country_v2: bool = False            # B3 país/política + B4a (Fase 3)
    country_params: dict | None = None  # override de parâmetros do B3/B4a
    equip_v2: bool = False              # B2 equipamentos (Fase 4)
    equip_params: dict | None = None    # override de parâmetros do B2
    god_events: tuple | None = None     # tupla de dicts (congelada)
    keep_frames: bool = False           # frames pesam; treino não precisa
    policy_specs: tuple | None = None   # PolicySpec por cid (torneios);
                                        # None = política padrão do motor


def run_episode(spec: EpisodeSpec) -> dict:
    """Roda UM episódio e devolve o resultado compacto (picklável)."""
    policy = None
    if spec.policy_specs is not None:
        from .policies import build_router
        policy = build_router(spec.policy_specs)
    eng = Engine(seed=spec.seed, n_companies=spec.n_companies,
                 god_events=list(spec.god_events) if spec.god_events else None,
                 policy=policy,
                 world_data=spec.world_data, market_v2=spec.market_v2,
                 market_params=spec.market_params,
                 country_v2=spec.country_v2,
                 country_params=spec.country_params,
                 equip_v2=spec.equip_v2,
                 equip_params=spec.equip_params)
    res = eng.run(spec.ticks)
    out = {
        "seed": spec.seed,
        "ticks": res["ticks"],
        "scoreboard": res["scoreboard"],
        "chronicle": res["chronicle"],
        "total_supercomputers": eng.total_supercomputers,
        "initial_cash": eng.initial_cash,
        "money_in": eng.money_in,
        "money_out": eng.money_out,
        # conta "externo" do B4a (0,0 com country_v2 desligado)
        "money_to_external": eng.money_to_external,
        "money_from_external": eng.money_from_external,
        # insumos da fitness de torneio: supercomputadores POR empresa
        # e o mapa cid -> (nome, arquétipo) na ordem do motor
        "super_by_cid": {int(k): float(v)
                         for k, v in eng._super_by_cid.items()},
        "companies": [{"cid": c.cid, "name": c.name,
                       "archetype": c.archetype} for c in eng.companies],
    }
    if "equipment" in res:              # B2 ligado: placar de frotas
        out["equipment"] = res["equipment"]
    if spec.keep_frames:
        out["frames"] = res["frames"]
    return out


def run_episodes(specs, processes: int = 1) -> list[dict]:
    """Roda as specs e devolve os resultados na MESMA ordem delas."""
    specs = list(specs)
    if processes and processes > 1 and len(specs) > 1:
        methods = mp.get_all_start_methods()
        ctx = mp.get_context("fork" if "fork" in methods else None)
        with ctx.Pool(processes) as pool:
            return pool.map(run_episode, specs)   # map preserva a ordem
    return [run_episode(spec) for spec in specs]


def run_batch(seeds, *, ticks: int = 120, n_companies: int = 8,
              processes: int = 4, **kwargs) -> list[dict]:
    """Atalho: um episódio por seed, com os mesmos parâmetros."""
    specs = [EpisodeSpec(seed=s, ticks=ticks, n_companies=n_companies,
                         **kwargs) for s in seeds]
    return run_episodes(specs, processes=processes)
