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
    god_events: tuple | None = None     # tupla de dicts (congelada)
    keep_frames: bool = False           # frames pesam; treino não precisa


def run_episode(spec: EpisodeSpec) -> dict:
    """Roda UM episódio e devolve o resultado compacto (picklável)."""
    eng = Engine(seed=spec.seed, n_companies=spec.n_companies,
                 god_events=list(spec.god_events) if spec.god_events else None,
                 world_data=spec.world_data, market_v2=spec.market_v2,
                 market_params=spec.market_params)
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
    }
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
