"""Torneio de políticas v1 — o experimento decisivo pré-registrado.

Protocolo: docs/ALGORITMOS-DECISAO.md. Em resumo:

- **Braço A0**: heurística v0 (genoma 0). **Braço A1**: CMA-ES sobre o
  genoma de 20 genes, candidato avaliado como empresa FOCAL invadindo
  campos congelados — **F0** (rivais v0) e **F1** (liga: 50% v0, 25%
  mutantes, 25% campeões/elites congelados). **F2** é o campo RETIDO
  do teste (genomas extremos feitos à mão + mutantes largos) — nenhuma
  seleção o enxerga.
- **Métrica primária**: por bloco, o percentil médio da focal entre as
  8 empresas em caixa (50%), elo máximo (30%) e supercomputadores
  (20%) compõe o índice **S**; o resultado é o **ΔS pareado** contra o
  A0 nos MESMOS blocos, com IC95 por bootstrap.
- **Orçamento equalizado**: 8.192 episódios por método aprendiz;
  seleção ≤ 512 episódios; seeds separadas — treino 1101–1164,
  validação 2201–2232, teste 9901–9932 **TRAVADAS**: a avaliação final
  se recusa a rodar sem ``final=True`` explícito, e treino/validação
  se recusam a tocar seeds de teste.
- **Portões de produto**: diversidade comportamental e eventos
  narráveis da ecologia do campeão ≥ 80% dos do A0; nenhuma célula
  comportamental com > 50% das empresas.

Nada aqui roda treino por conta própria: quem chama (o notebook
``notebooks/torneio-v1.ipynb``) controla o orçamento.
"""
from __future__ import annotations

import math

import numpy as np

from .driver import EpisodeSpec, run_episodes
from .genome import GENOME0, N_GENES, genome_from_z, policy_id
from .policies import PolicySpec

N_GENOME_DIM = N_GENES

# --------------------------------------------------------------------- #
# Seeds e choques — pré-registrados, não negociáveis em tempo de corrida
# --------------------------------------------------------------------- #
TRAIN_SEEDS = tuple(range(1101, 1165))     # 64
VAL_SEEDS = tuple(range(2201, 2233))       # 32
TEST_SEEDS = tuple(range(9901, 9933))      # 32 — TRAVADAS (ver evaluate_test)
TICKS = 120
N_COMPANIES = 8

# Choques do bloco de teste (atos de Deus, ticks fixos): descoberta aos
# 30, choque de preço do lítio aos 60, sanção ao minério de cobre aos 90.
TEST_SHOCKS = (
    {"tick": 30, "type": "discovery", "name": "Colina Nova",
     "resource": "copper_ore", "lat": -23.0, "lon": -69.0,
     "size_t": 900_000.0, "grade": 0.7},
    {"tick": 60, "type": "price_shock", "commodity": "lithium",
     "factor": 1.8, "duration": 6, "demand_factor": 1.3},
    {"tick": 90, "type": "sanction", "resource": "copper_ore",
     "duration": 6},
)

SALIENT_IGNORED = {"flows", "founding", "end"}


class TestSeedLock(RuntimeError):
    """As seeds de teste só abrem no modo final explícito."""


def assert_not_test_seeds(seeds, where: str = "avaliação") -> None:
    bad = [s for s in seeds if s in TEST_SEEDS]
    if bad:
        raise TestSeedLock(
            f"{where} tentou usar seeds de TESTE {bad}: o conjunto "
            f"9901–9932 é travado e só abre via evaluate_test(final=True)")


# --------------------------------------------------------------------- #
# Métrica primária: percentis e o índice composto S
# --------------------------------------------------------------------- #
def percentile(values, v) -> float:
    """Percentil médio de ``v`` em ``values`` (empates valem meio)."""
    less = sum(1 for x in values if x < v)
    equal = sum(1 for x in values if x == v)
    return (less + 0.5 * equal) / len(values)


def block_score(episode: dict, focal_cid: int) -> dict:
    """O índice S da empresa focal num episódio do driver."""
    meta = {c["cid"]: c for c in episode["companies"]}
    focal_name = meta[focal_cid]["name"]
    board = {row["name"]: row for row in episode["scoreboard"]}
    focal = board[focal_name]
    supers = {meta[cid]["name"]: float(episode["super_by_cid"].get(cid, 0.0))
              for cid in meta}
    cashes = [r["cash"] for r in board.values()]
    stages = [r["stage"] for r in board.values()]
    sups = [supers[r["name"]] for r in board.values()]
    p_cash = percentile(cashes, focal["cash"])
    p_stage = percentile(stages, focal["stage"])
    p_super = percentile(sups, supers[focal_name])
    return {
        "S": 0.5 * p_cash + 0.3 * p_stage + 0.2 * p_super,
        "p_cash": p_cash, "p_stage": p_stage, "p_super": p_super,
        "cash": focal["cash"], "stage": focal["stage"],
        "super": supers[focal_name],
        "facilities": focal["facilities"], "alive": focal["alive"],
    }


# --------------------------------------------------------------------- #
# Campos de rivais
# --------------------------------------------------------------------- #
def _z_genome(zmap: dict) -> tuple:
    from .genome import GENE_NAMES
    z = [0.0] * len(GENE_NAMES)
    for name, zi in zmap.items():
        z[GENE_NAMES.index(name)] = zi
    return genome_from_z(z)


# Genomas extremos feitos à mão — o miolo do campo retido F2.
EXTREME_GENOMES = (
    _z_genome({"mines_coef": 2.0, "reserve_base": -1.0,
               "grade_thr_base": -2.0, "buy_target_scale": 1.5,
               "buffer_scale": -1.0}),                       # agro-max
    _z_genome({"reserve_base": 2.0, "reserve_risk_span": 2.0,
               "grade_thr_base": 2.0, "mines_coef": -1.0}),  # cofre
    _z_genome({"buffer_scale": 2.0, "factory_need_vertical": -1.5,
               "buy_target_scale": 1.0}),                    # vertical-max
    _z_genome({"insta_prob_scale": 2.0, "zap_prob_scale": 2.0,
               "pick_noise": 2.0}),                          # spray
)

_F1_CYCLE = ("v0", "v0", "v0", "v0", "mut", "mut", "league", "league")


def field_specs(genome, field: str, focal_cid: int, block_index: int,
                block_seed: int, league=()) -> tuple:
    """As PolicySpecs de um bloco: focal = ``genome``; rivais por campo.

    - F0: todos os rivais v0.
    - F1: ciclo de 8 posições (50% v0, 25% mutantes, 25% liga) girando
      com o bloco — mutantes têm seed derivada do bloco (congelados e
      reproduzíveis); a liga cicla os genomas dados (vazia -> v0).
    - F2 (retido): genomas extremos + mutantes largos (sigma 0,8).
    """
    specs = []
    for cid in range(N_COMPANIES):
        if cid == focal_cid:
            specs.append(PolicySpec.of_genome(genome))
            continue
        slot = cid if cid < focal_cid else cid - 1   # índice entre rivais
        if field == "F0":
            specs.append(PolicySpec.v0())
        elif field == "F1":
            kind = _F1_CYCLE[(slot + block_index) % len(_F1_CYCLE)]
            if kind == "mut":
                specs.append(PolicySpec.mutant(block_seed * 100 + slot,
                                               sigma=0.35))
            elif kind == "league" and league:
                specs.append(PolicySpec.of_genome(
                    league[(slot + block_index) % len(league)]))
            else:
                specs.append(PolicySpec.v0())
        elif field == "F2":
            if slot % 2 == 0:
                specs.append(PolicySpec.of_genome(
                    EXTREME_GENOMES[(slot // 2 + block_index)
                                    % len(EXTREME_GENOMES)]))
            else:
                specs.append(PolicySpec.mutant(block_seed * 100 + slot,
                                               sigma=0.8))
        else:
            raise ValueError(f"campo desconhecido: {field!r}")
    return tuple(specs)


# --------------------------------------------------------------------- #
# Avaliação de blocos focais (a unidade de medida do torneio)
# --------------------------------------------------------------------- #
def evaluate_blocks(genome, blocks, league=(), processes: int = 4,
                    ticks: int = TICKS) -> list[dict]:
    """Roda um episódio por bloco e devolve o S da focal de cada um.

    ``blocks``: lista de ``(seed, campo, choques?)``. A focal gira por
    ``block_index % N`` — pareado entre braços que usem a mesma lista.
    """
    specs = []
    for i, (seed, field, shocks) in enumerate(blocks):
        focal_cid = i % N_COMPANIES
        specs.append(EpisodeSpec(
            seed=seed, ticks=ticks, n_companies=N_COMPANIES,
            god_events=TEST_SHOCKS if shocks else None,
            policy_specs=field_specs(genome, field, focal_cid, i, seed,
                                     league)))
    results = run_episodes(specs, processes=processes)
    out = []
    for i, (res, (seed, field, shocks)) in enumerate(zip(results, blocks)):
        row = block_score(res, i % N_COMPANIES)
        row.update({"seed": seed, "field": field, "shocks": shocks,
                    "focal_cid": i % N_COMPANIES})
        out.append(row)
    return out


def paired_deltas(method_blocks, base_blocks) -> list[float]:
    """ΔS por bloco, pareado por (seed, campo, choques) e índice."""
    assert len(method_blocks) == len(base_blocks)
    deltas = []
    for m, b in zip(method_blocks, base_blocks):
        assert (m["seed"], m["field"], m["shocks"]) == \
               (b["seed"], b["field"], b["shocks"]), "blocos não pareados"
        deltas.append(m["S"] - b["S"])
    return deltas


def bootstrap_ci(deltas, n_boot: int = 2000, seed: int = 12345):
    """IC95 da média por bootstrap (percentis 2,5/97,5), determinístico."""
    x = np.asarray(deltas, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    means = x[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# --------------------------------------------------------------------- #
# CMA-ES (Hansen) em espaço z — minimiza internamente, fitness maximiza
# --------------------------------------------------------------------- #
class CMAES:
    """(μ/μ_w, λ) CMA-ES padrão sobre o espaço z do genoma."""

    def __init__(self, dim: int, sigma: float = 0.5, popsize: int = 16,
                 seed: int = 0):
        self.dim = dim
        self.sigma = float(sigma)
        self.popsize = int(popsize)
        self.mu = self.popsize // 2
        w = np.log(self.mu + 0.5) - np.log(np.arange(1, self.mu + 1))
        self.weights = w / w.sum()
        self.mueff = float(1.0 / (self.weights ** 2).sum())
        n = float(dim)
        self.cs = (self.mueff + 2) / (n + self.mueff + 5)
        self.ds = 1 + 2 * max(0.0, math.sqrt((self.mueff - 1) / (n + 1)) - 1) \
            + self.cs
        self.cc = (4 + self.mueff / n) / (n + 4 + 2 * self.mueff / n)
        self.c1 = 2 / ((n + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1,
                       2 * (self.mueff - 2 + 1 / self.mueff)
                       / ((n + 2) ** 2 + self.mueff))
        self.mean = np.zeros(dim)
        self.C = np.eye(dim)
        self.pc = np.zeros(dim)
        self.ps = np.zeros(dim)
        self.rng = np.random.default_rng(seed)
        self.generation = 0

    def ask(self) -> list[np.ndarray]:
        evals_C, B = np.linalg.eigh(self.C)
        D = np.sqrt(np.maximum(evals_C, 1e-20))
        self._B, self._D = B, D
        xs = []
        for _ in range(self.popsize):
            z = self.rng.standard_normal(self.dim)
            xs.append(self.mean + self.sigma * (B @ (D * z)))
        return xs

    def tell(self, xs, fitness) -> None:
        order = np.argsort([-f for f in fitness])       # melhor primeiro
        xs = [xs[i] for i in order]
        old_mean = self.mean.copy()
        self.mean = sum(w * x for w, x in zip(self.weights, xs[:self.mu]))
        y = (self.mean - old_mean) / self.sigma
        B, D = self._B, self._D
        inv_sqrt_C = B @ np.diag(1.0 / D) @ B.T
        self.ps = (1 - self.cs) * self.ps \
            + math.sqrt(self.cs * (2 - self.cs) * self.mueff) \
            * (inv_sqrt_C @ y)
        norm_ps = float(np.linalg.norm(self.ps))
        expected = math.sqrt(self.dim) \
            * (1 - 1 / (4 * self.dim) + 1 / (21 * self.dim ** 2))
        hsig = 1.0 if norm_ps / math.sqrt(
            1 - (1 - self.cs) ** (2 * (self.generation + 1))) / expected < \
            2 + 4 / (self.dim + 1) else 0.0
        self.pc = (1 - self.cc) * self.pc \
            + hsig * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * y
        rank_mu = sum(w * np.outer(x - old_mean, x - old_mean)
                      for w, x in zip(self.weights, xs[:self.mu])) \
            / self.sigma ** 2
        self.C = (1 - self.c1 - self.cmu) * self.C \
            + self.c1 * (np.outer(self.pc, self.pc)
                         + (1 - hsig) * self.cc * (2 - self.cc) * self.C) \
            + self.cmu * rank_mu
        cn, sum_cs = self.cs / (1 - self.cs), self.cs
        self.sigma *= math.exp(min(1.0, (sum_cs / self.ds)
                                   * (norm_ps / expected - 1)))
        self.generation += 1


# --------------------------------------------------------------------- #
# Arquivo QD mínimo: elites por célula de comportamento observado
# --------------------------------------------------------------------- #
def behavior_cell(mean_stage: float, mean_super: float,
                  mean_p_cash: float) -> tuple:
    return (int(round(mean_stage)), 1 if mean_super > 0 else 0,
            min(3, int(mean_p_cash * 4)))


class BehaviorArchive:
    """MAP-Elites enxuto: o melhor genoma por célula (elo, super, caixa)."""

    def __init__(self):
        self.cells: dict[tuple, tuple[tuple, float]] = {}

    def add(self, genome, fitness: float, cell: tuple) -> None:
        cur = self.cells.get(cell)
        if cur is None or fitness > cur[1]:
            self.cells[cell] = (tuple(genome), float(fitness))

    def genomes(self) -> list[tuple]:
        return [g for g, _ in self.cells.values()]


# --------------------------------------------------------------------- #
# A corrida A1: CMA-ES em liga, com contabilidade de episódios
# --------------------------------------------------------------------- #
def evaluate_candidates(genomes, round_no: int, blocks_per_candidate: int,
                        league=(), processes: int = 4,
                        ticks: int = TICKS):
    """Fitness (média de S) de cada genoma em blocos F0/F1 alternados.

    As seeds dos blocos giram determinísticamente por ``round_no`` —
    sempre seeds de TREINO (a guarda prova). Devolve (fitness, detalhes).
    """
    blocks_seeds = [TRAIN_SEEDS[(round_no * blocks_per_candidate + j)
                                % len(TRAIN_SEEDS)]
                    for j in range(blocks_per_candidate)]
    assert_not_test_seeds(blocks_seeds, "treino CMA-ES")
    all_specs, index = [], []
    for ci, genome in enumerate(genomes):
        for j, seed in enumerate(blocks_seeds):
            field = "F0" if j % 2 == 0 else "F1"
            focal_cid = (ci + j) % N_COMPANIES
            all_specs.append(EpisodeSpec(
                seed=seed, ticks=ticks, n_companies=N_COMPANIES,
                policy_specs=field_specs(genome, field, focal_cid,
                                         round_no * 31 + j, seed, league)))
            index.append((ci, j, focal_cid))
    results = run_episodes(all_specs, processes=processes)
    per = {ci: [] for ci in range(len(genomes))}
    for res, (ci, j, focal_cid) in zip(results, index):
        per[ci].append(block_score(res, focal_cid))
    fitness, details = [], []
    for ci in range(len(genomes)):
        rows = per[ci]
        fitness.append(float(np.mean([r["S"] for r in rows])))
        details.append(rows)
    return fitness, details


def run_cma(*, popsize: int = 16, generations: int = 32,
            blocks_per_candidate: int = 8, sigma: float = 0.5,
            seed: int = 0, processes: int = 4, ticks: int = TICKS,
            archive: BehaviorArchive | None = None) -> dict:
    """Uma corrida completa do A1. A liga F1 cresce: o campeão de cada
    geração congela e entra nela (a geração 0 enfrenta a liga vazia)."""
    opt = CMAES(N_GENOME_DIM, sigma=sigma, popsize=popsize, seed=seed)
    league: list[tuple] = []
    history, best = [], None
    episodes = 0
    for gen in range(generations):
        zs = opt.ask()
        genomes = [genome_from_z(z) for z in zs]
        fitness, details = evaluate_candidates(
            genomes, round_no=seed * 1000 + gen,
            blocks_per_candidate=blocks_per_candidate, league=league,
            processes=processes, ticks=ticks)
        episodes += len(genomes) * blocks_per_candidate
        opt.tell(zs, fitness)
        gi = int(np.argmax(fitness))
        champ = genomes[gi]
        rows = details[gi]
        if archive is not None:
            archive.add(champ, fitness[gi], behavior_cell(
                float(np.mean([r["stage"] for r in rows])),
                float(np.mean([r["super"] for r in rows])),
                float(np.mean([r["p_cash"] for r in rows]))))
        if best is None or fitness[gi] > best[1]:
            best = (champ, fitness[gi])
        league.append(champ)
        history.append({"generation": gen, "best": fitness[gi],
                        "mean": float(np.mean(fitness)),
                        "champion": policy_id(champ)})
    return {"champion": best[0], "champion_fitness": best[1],
            "history": history, "episodes": episodes, "league": league}


# --------------------------------------------------------------------- #
# Seleção (validação) e avaliação final (teste travado)
# --------------------------------------------------------------------- #
SELECTION_BUDGET = 512


def select_champion(candidates, processes: int = 4, ticks: int = TICKS,
                    max_episodes: int = SELECTION_BUDGET) -> dict:
    """Reavalia os candidatos nas seeds de VALIDAÇÃO (F0/F1 alternados)
    e escolhe o campeão por média de S. Orçamento de seleção é teto
    duro do protocolo: estourar é erro, não aviso."""
    blocks = [(s, "F0" if i % 2 == 0 else "F1", False)
              for i, s in enumerate(VAL_SEEDS)]
    n_episodes = len(candidates) * len(blocks)
    if n_episodes > max_episodes:
        raise ValueError(f"seleção usaria {n_episodes} episódios > "
                         f"teto de {max_episodes} do protocolo")
    scored = []
    for genome in candidates:
        rows = evaluate_blocks(genome, blocks, processes=processes,
                               ticks=ticks)
        scored.append((float(np.mean([r["S"] for r in rows])), genome, rows))
    scored.sort(key=lambda x: -x[0])
    return {"champion": scored[0][1], "champion_mean_S": scored[0][0],
            "table": [(policy_id(g), m) for m, g, _ in scored],
            "episodes": n_episodes}


def test_blocks() -> list[tuple]:
    """Os 64 blocos do teste travado: por seed, (F0 sem choque) e
    (F2 com os choques pré-registrados)."""
    blocks = []
    for s in TEST_SEEDS:
        blocks.append((s, "F0", False))
        blocks.append((s, "F2", True))
    return blocks


def evaluate_test(genome, *, final: bool = False, processes: int = 4,
                  ticks: int = TICKS) -> list[dict]:
    """A avaliação final sobre as seeds de TESTE. Sem ``final=True``
    explícito, recusa — é a trava do protocolo, não um detalhe."""
    if not final:
        raise TestSeedLock(
            "evaluate_test exige final=True explícito: as seeds "
            "9901–9932 não abrem para treino, seleção ou exploração")
    return evaluate_blocks(genome, test_blocks(), processes=processes,
                           ticks=ticks)


# --------------------------------------------------------------------- #
# Portões de produto: ecologia completa (todas as empresas = candidato)
# --------------------------------------------------------------------- #
def ecology_metrics(genome, seeds=VAL_SEEDS[:8], processes: int = 4,
                    ticks: int = TICKS) -> dict:
    """Mundo inteiro com a mesma política: mede eventos narráveis por
    episódio, diversidade de células comportamentais (elo × instalações)
    e a fatia da célula dominante."""
    assert_not_test_seeds(seeds, "ecologia")
    specs = [EpisodeSpec(seed=s, ticks=ticks, n_companies=N_COMPANIES,
                         policy_specs=tuple(PolicySpec.of_genome(genome)
                                            for _ in range(N_COMPANIES)))
             for s in seeds]
    results = run_episodes(specs, processes=processes)
    salient, cell_counts, distinct = [], {}, []
    for res in results:
        salient.append(sum(1 for e in res["chronicle"]
                           if e["kind"] not in SALIENT_IGNORED))
        cells = [(r["stage"], r["facilities"]) for r in res["scoreboard"]]
        distinct.append(len(set(cells)))
        for cell in cells:
            cell_counts[cell] = cell_counts.get(cell, 0) + 1
    total = sum(cell_counts.values())
    return {
        "events_per_episode": float(np.mean(salient)),
        "diversity_cells": float(np.mean(distinct)),
        "max_cell_share": max(cell_counts.values()) / total,
        "episodes": len(results),
    }


def gates_ok(champion_eco: dict, base_eco: dict) -> bool:
    return (champion_eco["events_per_episode"]
            >= 0.8 * base_eco["events_per_episode"]
            and champion_eco["diversity_cells"]
            >= 0.8 * base_eco["diversity_cells"]
            and champion_eco["max_cell_share"] <= 0.5)


# --------------------------------------------------------------------- #
# Veredito — critérios numéricos pré-registrados
# --------------------------------------------------------------------- #
def verdict(delta_s: float, ci: tuple, delta_f2: float,
            delta_shock: float, gates: bool,
            a2_margin: float | None = None,
            a2_ci_lo: float | None = None) -> str:
    """PROVA / MATA / PLANO_B / INCONCLUSIVO, pelos critérios do doc.

    ``a2_margin`` = ΔS(A2) − ΔS(A1) nos mesmos blocos de teste, quando
    o braço A2 existir; sem A2, PLANO_B é inalcançável por construção.
    """
    ci_lo, ci_hi = ci
    if a2_margin is not None and a2_margin >= 0.08 \
            and a2_ci_lo is not None and a2_ci_lo > 0:
        return "PLANO_B"
    if not gates:
        return "MATA"
    if delta_s <= 0.03:
        return "MATA"
    if ci_lo <= 0.0 <= ci_hi and delta_s < 0.05:
        return "MATA"
    if delta_f2 < 0 and delta_shock < 0:
        return "MATA"           # colapso de generalização
    if delta_s >= 0.08 and ci_lo > 0 and delta_f2 >= 0 \
            and delta_shock >= 0:
        return "PROVA"
    return "INCONCLUSIVO"
