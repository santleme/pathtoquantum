"""Avaliação final cega da corrida forge-v1 (Degrau 2, issue #6).

A #6 exige que o campeão da forja passe por uma avaliação final
cega FORA do loop: blocos travados do torneio (seeds 9901–9932,
campo F2, choques de Deus), contra v0 e o campeão CMA-ES. O torneio
já tem esse caminho para genomas (``evaluate_test(final=True)``);
aqui está o equivalente para programas-código, que o torneio não
cobre — o avaliador da forja (``forge/evaluator.py``) só usa seeds
de treino/validação, e a trava de seeds o proíbe de tocar nas de
teste.

Regras desta peça, espelhando o torneio:

- **Trava**: sem ``final=True`` explícito, recusa com
  ``TestSeedLock`` — as seeds 9901–9932 só abrem para a avaliação
  final, nunca para treino, seleção ou exploração. Quem chama sem
  ``final=True`` não avalia nada. A validação cega também recusa
  seeds fora de 9901–9932, e a ecologia recusa seeds de teste
  (``assert_not_test_seeds``, como o torneio).
- **Blocos**: os mesmos de ``tournament.test_blocks`` — por seed,
  F0 sem choques e F2 com os choques pré-registrados
  (``TEST_SHOCKS``); a focal gira como no avaliador da forja
  (``focal_cid = i % N_COMPANIES``), para campeão e baseline
  correrem exatamente os mesmos blocos e o delta ser pareado.
  O baseline CMA-ES (genoma, não programa) corre os mesmos blocos
  por ``blind_evaluate_genome`` — o veredito usa o MELHOR baseline
  com delta pareado de verdade contra cada um, nunca um ajuste
  improvisado sobre o intervalo do outro.
- **Ecologia**: espelho de ``tournament.ecology_metrics`` com a
  política-programa em todas as empresas (seeds de validação, como
  lá) — é ela que alimenta os portões de produto da #6.
- **Delta pareado**: ``paired_delta`` casa campeão e baseline por
  (seed, campo, focal) em ordem, e devolve média, erro-padrão e o
  limite inferior do IC95 (aproximação normal, 1,96×se) que
  ``forge/verdict.py`` consome. Blocos diferentes, ordem diferente
  ou focal diferente são erro — sem pareamento, o IC misturaria
  mundos diferentes.
- **Concentração por arquétipo**: ``concentrated_by_cell`` agrupa
  o delta pareado pela célula comportamental do campeão no bloco
  (elo × instalações, os eixos do MAP-Elites da forja): concentrado
  se o ganho vive numa única célula (as demais com média <= 0).
  Campo (F0/F2) não é arquétipo e não é usado para isso.
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mundo import tournament as T
from mundo.driver import EpisodeSpec, run_episodes
from mundo.policies import PolicySpec
from mundo.program import validate_program


def _blocks(seeds):
    """Blocos cegos: por seed, F0 e F2 com choques (test_blocks)."""
    out = []
    for s in seeds:
        out.append((s, "F0", False))
        out.append((s, "F2", True))
    return out


def blind_evaluate_program(program_path, *, final: bool = False,
                            seeds=None, ticks: int = T.TICKS,
                            processes: int = 1) -> list[dict]:
    """S da política-programa nos blocos cegos (uma linha por bloco).

    ``seeds`` permite um subconjunto das seeds de teste (os testes
    usam 1 seed; a corrida usa todas, 9901–9932). Sem ``final=True``,
    levanta ``TestSeedLock`` e não roda nada.
    """
    if not final:
        raise T.TestSeedLock(
            "blind_evaluate_program exige final=True explícito: as seeds "
            "9901–9932 não abrem para treino, seleção ou exploração")
    seeds = list(seeds) if seeds is not None else list(T.TEST_SEEDS)
    bad = [s for s in seeds if s not in T.TEST_SEEDS]
    if bad:
        raise ValueError(
            "avaliação cega só aceita seeds de TESTE 9901–9932; "
            f"fora do conjunto: {bad}")
    source = Path(program_path).read_text(encoding="utf-8")
    violations = validate_program(source)
    if violations:
        raise ValueError(
            "programa rejeitado pela guarda anti-trapaça — a avaliação "
            "cega não avalia exploit:\n- " + "\n- ".join(violations))
    spec = PolicySpec.program(program_path)
    blocks = _blocks(seeds)
    specs, focals = [], []
    for i, (seed, field, shocks) in enumerate(blocks):
        focal_cid = i % T.N_COMPANIES
        focals.append(focal_cid)
        specs.append(EpisodeSpec(
            seed=seed, ticks=ticks, n_companies=T.N_COMPANIES,
            god_events=T.TEST_SHOCKS if shocks else None,
            policy_specs=T.field_specs(None, field, focal_cid, i, seed,
                                       focal_spec=spec)))
    results = run_episodes(specs, processes=processes)
    rows = []
    for res, (seed, field, shocks), focal_cid in zip(results, blocks, focals):
        row = T.block_score(res, focal_cid)
        row.update({"seed": seed, "field": field, "shocks": shocks,
                    "focal_cid": focal_cid})
        rows.append(row)
    return rows


def blind_evaluate_genome(genome, *, final: bool = False,
                          ticks: int = T.TICKS,
                          processes: int = 1) -> list[dict]:
    """S do genoma (baseline CMA-ES) nos blocos cegos, via torneio.

    Envoltório fino de ``tournament.evaluate_test`` — a trava
    ``final=True`` é a do torneio, sem duplicata. O genoma campeão
    do torneio vive em ``data/cmaes_champion.json`` (20 genes); o
    notebook da #6 o carrega de lá, para o delta contra o CMA-ES
    ser pareado de verdade, nos mesmos 64 blocos do campeão.
    """
    if len(genome) != T.N_GENES:
        raise ValueError(f"genoma com {len(genome)} genes; "
                         f"esperado {T.N_GENES}")
    return T.evaluate_test(genome, final=final, processes=processes,
                           ticks=ticks)


def paired_delta(champ_rows: list[dict], base_rows: list[dict]) -> dict:
    """Delta pareado campeão − baseline, por bloco, em ordem.

    Exige as mesmas linhas dos dois lados, na mesma ordem: mesmo
    número de blocos e mesmos (seed, campo, focal_cid) posição por
    posição. Qualquer divergência é erro, não silêncio — um delta
    sobre blocos diferentes não significa nada, e linhas extras de
    um lado não podem passar despercebidas.
    """
    if len(champ_rows) != len(base_rows):
        raise ValueError(
            f"linhas desemparelhadas: campeão {len(champ_rows)} x "
            f"baseline {len(base_rows)}")
    diffs = []
    for c, b in zip(champ_rows, base_rows):
        key_c = (c["seed"], c["field"], c["focal_cid"])
        key_b = (b["seed"], b["field"], b["focal_cid"])
        if key_c != key_b:
            raise ValueError(f"bloco sem par na posição: campeão "
                             f"{key_c} x baseline {key_b}")
        diffs.append(c["S"] - b["S"])
    if len(diffs) < 2:
        raise ValueError("delta pareado exige ao menos 2 blocos "
                         "(1 bloco não tem intervalo)")
    mean = statistics.fmean(diffs)
    se = statistics.stdev(diffs) / math.sqrt(len(diffs))
    return {"delta_s": mean, "se": se, "ci_low": mean - 1.96 * se,
            "ci_high": mean + 1.96 * se, "n_blocks": len(diffs)}


def concentrated_by_cell(champ_rows: list[dict],
                         base_rows: list[dict]) -> tuple[bool, dict]:
    """Ganho concentrado num arquétipo? (célula comportamental).

    Agrupa o delta pareado pela célula do campeão no bloco
    (elo × instalações — os eixos do MAP-Elites da forja) e devolve
    (concentrado, médias por célula). Concentrado = o ganho vive
    numa única célula: só ela tem média > 0. Sem ganho em célula
    nenhuma, não é concentração — é ausência de ganho.
    """
    base = {}
    for b in base_rows:
        base[(b["seed"], b["field"], b["focal_cid"])] = b["S"]
    by_cell: dict[tuple, list[float]] = {}
    for c in champ_rows:
        key = (c["seed"], c["field"], c["focal_cid"])
        if key not in base:
            raise ValueError(f"bloco sem par no baseline: {key}")
        cell = (c["stage"], c["facilities"])
        by_cell.setdefault(cell, []).append(c["S"] - base[key])
    means = {cell: statistics.fmean(v) for cell, v in by_cell.items()}
    positive = [m for m in means.values() if m > 0]
    concentrated = len(positive) == 1
    return concentrated, means


def blind_ecology_program(program_path, *, seeds=None, ticks: int = T.TICKS,
                          processes: int = 1) -> dict:
    """Ecologia com a política-programa em todas as empresas.

    Espelho de ``tournament.ecology_metrics`` (seeds de validação
    por padrão): eventos narráveis por episódio, células
    comportamentais distintas e a fatia da célula dominante.
    """
    seeds = list(seeds) if seeds is not None else list(T.VAL_SEEDS[:8])
    T.assert_not_test_seeds(seeds, "ecologia da forja")
    specs = [EpisodeSpec(seed=s, ticks=ticks, n_companies=T.N_COMPANIES,
                         policy_specs=tuple(
                             PolicySpec.program(program_path)
                             for _ in range(T.N_COMPANIES)))
             for s in seeds]
    results = run_episodes(specs, processes=processes)
    salient, cell_counts, distinct = [], {}, []
    for res in results:
        salient.append(sum(1 for e in res["chronicle"]
                           if e["kind"] not in T.SALIENT_IGNORED))
        cells = [(r["stage"], r["facilities"]) for r in res["scoreboard"]]
        distinct.append(len(set(cells)))
        for cell in cells:
            cell_counts[cell] = cell_counts.get(cell, 0) + 1
    total = sum(cell_counts.values())
    return {
        "events_per_episode": float(statistics.fmean(salient)),
        "diversity_cells": float(statistics.fmean(distinct)),
        "max_cell_share": max(cell_counts.values()) / total,
        "episodes": len(results),
    }


def product_gates(champ_eco: dict, base_eco: dict) -> tuple[bool, list[str]]:
    """Portões de produto da #6 sobre as duas ecologias.

    As três condições de ``tournament.gates_ok``: eventos narráveis
    e diversidade comportamental do campeão >= 80% dos do baseline,
    e nenhuma célula comportamental com mais de 50% das empresas.
    Devolve (ok, motivos da violação, se houver).
    """
    reasons = []
    if champ_eco["events_per_episode"] < 0.8 * base_eco["events_per_episode"]:
        reasons.append(
            f"eventos narráveis {champ_eco['events_per_episode']:.2f} < 80% "
            f"dos do baseline ({base_eco['events_per_episode']:.2f})")
    if champ_eco["diversity_cells"] < 0.8 * base_eco["diversity_cells"]:
        reasons.append(
            f"diversidade {champ_eco['diversity_cells']:.2f} células < 80% "
            f"dos do baseline ({base_eco['diversity_cells']:.2f})")
    if champ_eco["max_cell_share"] > 0.50:
        reasons.append(
            f"célula dominante com {champ_eco['max_cell_share']:.0%} das "
            "empresas (> 50%)")
    return (not reasons, reasons)
