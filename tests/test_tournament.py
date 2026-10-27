"""Torneio de políticas v1 (ALGORITMOS-DECISAO.md) — as garantias:

- genoma 0 ≡ v0: mesma seed -> mesmo mundo, bit a bit (goldens);
- o roteador não muda os goldens quando todos usam a mesma política;
- a fitness é determinística por seed (série == série == paralelo);
- separação de conjuntos: treino/validação nunca tocam as seeds de
  teste, e a avaliação final se recusa a rodar sem o modo final.
"""
import hashlib
import json

import pytest

from mundo import tournament as T
from mundo.driver import EpisodeSpec, run_episode
from mundo.engine import Engine, HeuristicPolicy
from mundo.genome import (GENOME0, GenomePolicy, genome_from_z,
                          genome_to_params, mutate, policy_id,
                          z_from_genome)
from mundo.policies import PolicySpec, build_policy, build_router

GOLDEN_N8_24 = "e01923e16b48cfa6f0aa934fb1a20d93ea0ac053dc9406f620fa1c900e417373"


def state_hash(eng) -> str:
    blob = json.dumps(eng.state_dict(), sort_keys=True,
                      ensure_ascii=False, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


# --------------------------------------------------------------------- #
# Genoma
# --------------------------------------------------------------------- #
def test_genome0_matches_policy_params():
    assert genome_to_params(GENOME0) == HeuristicPolicy.PARAMS0
    assert len(GENOME0) == 20


def test_genome_roundtrips_and_clipping():
    assert z_from_genome(GENOME0) == tuple([0.0] * 20)
    g = genome_from_z([10.0] * 20)          # z absurdo -> clip nos hi
    for v, (_, _, lo, hi, _) in zip(g, __import__("mundo.genome",
                                                fromlist=["GENES"]).GENES):
        assert lo <= v <= hi
    assert genome_from_z(z_from_genome(GENOME0)) == GENOME0


def test_mutant_is_deterministic():
    assert mutate(GENOME0, 42, 0.35) == mutate(GENOME0, 42, 0.35)
    assert mutate(GENOME0, 42, 0.35) != mutate(GENOME0, 43, 0.35)
    assert mutate(GENOME0, 42, 0.35) != GENOME0


def test_genome0_policy_is_bit_identical_to_v0():
    eng = Engine(seed=42, n_companies=8, policy=GenomePolicy(GENOME0))
    eng.run(24)
    assert state_hash(eng) == GOLDEN_N8_24
    assert policy_id(GENOME0) == "v0"


# --------------------------------------------------------------------- #
# Roteador
# --------------------------------------------------------------------- #
def test_router_with_all_v0_keeps_golden():
    router = build_router([PolicySpec.v0()] * 8)
    eng = Engine(seed=42, n_companies=8, policy=router)
    eng.run(24)
    assert state_hash(eng) == GOLDEN_N8_24


def test_router_with_all_genome0_keeps_golden():
    router = build_router([PolicySpec.of_genome(GENOME0)] * 8)
    eng = Engine(seed=42, n_companies=8, policy=router)
    eng.run(24)
    assert state_hash(eng) == GOLDEN_N8_24


def test_router_actually_routes_per_company():
    # reserva astronômica só na empresa 0 (fora dos limites evolutivos,
    # como sonda): ela nunca tem "gastável" e congela; o mundo muda,
    # mas as outras empresas continuam com a política padrão.
    rich = list(GENOME0)
    from mundo.genome import GENE_NAMES
    rich[GENE_NAMES.index("reserve_base")] = 1e12
    specs = [PolicySpec.of_genome(tuple(rich))] + [PolicySpec.v0()] * 7
    got = run_episode(EpisodeSpec(seed=7, ticks=24, policy_specs=tuple(specs)))
    ref = run_episode(EpisodeSpec(seed=7, ticks=24))
    assert got["scoreboard"] != ref["scoreboard"]
    assert isinstance(build_policy(PolicySpec.mutant(1)), GenomePolicy)


# --------------------------------------------------------------------- #
# Fitness / avaliação
# --------------------------------------------------------------------- #
def test_block_score_percentiles():
    ep = {
        "companies": [{"cid": i, "name": f"C{i}", "archetype": "x"}
                      for i in range(8)],
        "scoreboard": [{"name": f"C{i}", "cash": float(i * 10),
                        "stage": i % 3, "facilities": i, "alive": True}
                       for i in range(8)],
        "super_by_cid": {7: 2.0},
        "chronicle": [],
    }
    top = T.block_score(ep, 7)
    assert top["p_cash"] == pytest.approx((7 + 0.5) / 8)
    assert top["p_super"] == pytest.approx((7 + 0.5) / 8)
    assert 0.0 <= top["S"] <= 1.0
    bottom = T.block_score(ep, 0)
    assert bottom["S"] < top["S"]


def test_fitness_is_deterministic():
    blocks = [(1101, "F0", False), (1102, "F1", False)]
    a = T.evaluate_blocks(GENOME0, blocks, processes=1, ticks=24)
    b = T.evaluate_blocks(GENOME0, blocks, processes=1, ticks=24)
    c = T.evaluate_blocks(GENOME0, blocks, processes=2, ticks=24)
    assert [r["S"] for r in a] == [r["S"] for r in b] == [r["S"] for r in c]


def test_cma_es_improves_on_analytic_fitness():
    import numpy as np
    opt = T.CMAES(20, sigma=0.5, popsize=8, seed=3)
    target = np.linspace(-0.5, 0.5, 20)
    best_hist = []
    for _ in range(6):
        xs = opt.ask()
        fit = [-float(((x - target) ** 2).sum()) for x in xs]
        opt.tell(xs, fit)
        best_hist.append(max(fit))
    assert best_hist[-1] > best_hist[0]


def test_cma_run_smoke_and_budget():
    out = T.run_cma(popsize=4, generations=2, blocks_per_candidate=2,
                    seed=5, processes=1, ticks=24)
    assert out["episodes"] == 4 * 2 * 2
    assert len(out["champion"]) == 20
    assert len(out["history"]) == 2


# --------------------------------------------------------------------- #
# Separação de seeds — a trava do protocolo
# --------------------------------------------------------------------- #
def test_seed_sets_are_disjoint():
    assert not (set(T.TRAIN_SEEDS) & set(T.TEST_SEEDS))
    assert not (set(T.VAL_SEEDS) & set(T.TEST_SEEDS))
    assert not (set(T.TRAIN_SEEDS) & set(T.VAL_SEEDS))
    assert T.TRAIN_SEEDS == tuple(range(1101, 1165))
    assert T.VAL_SEEDS == tuple(range(2201, 2233))
    assert T.TEST_SEEDS == tuple(range(9901, 9933))


def test_training_guards_refuse_test_seeds():
    with pytest.raises(T.TestSeedLock):
        T.assert_not_test_seeds([1101, 9901], "treino")
    with pytest.raises(T.TestSeedLock):
        T.ecology_metrics(GENOME0, seeds=[9901], processes=1, ticks=12)


def test_final_evaluation_is_locked_without_final_flag():
    with pytest.raises(T.TestSeedLock):
        T.evaluate_test(GENOME0, processes=1, ticks=12)
    with pytest.raises(T.TestSeedLock):
        T.evaluate_test(GENOME0, final=False, processes=1, ticks=12)


def test_selection_budget_is_a_hard_cap():
    with pytest.raises(ValueError):
        T.select_champion([GENOME0] * 20, processes=1, ticks=12,
                          max_episodes=512)   # 20 x 32 = 640 > 512


# --------------------------------------------------------------------- #
# Veredito — os ramos dos critérios pré-registrados
# --------------------------------------------------------------------- #
def test_verdict_branches():
    assert T.verdict(0.10, (0.02, 0.18), 0.01, 0.03, True) == "PROVA"
    assert T.verdict(0.02, (-0.01, 0.05), 0.01, 0.01, True) == "MATA"
    assert T.verdict(0.10, (0.02, 0.18), 0.01, 0.03, False) == "MATA"
    assert T.verdict(0.10, (0.02, 0.18), -0.02, -0.01, True) == "MATA"
    assert T.verdict(0.06, (-0.01, 0.13), 0.02, 0.02, True) == "INCONCLUSIVO"
    assert T.verdict(0.10, (0.02, 0.18), 0.01, 0.03, True,
                     a2_margin=0.09, a2_ci_lo=0.01) == "PLANO_B"
    assert T.verdict(0.10, (0.02, 0.18), 0.01, 0.03, True,
                     a2_margin=0.09, a2_ci_lo=-0.01) == "PROVA"
