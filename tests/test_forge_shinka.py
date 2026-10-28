"""Testes do porte ShinkaEvolve (issue #21) — staging atrás de flags.

Duas técnicas portadas do estudo docs/ESTUDO-SHINKA-FORJA.md:
(1) amostragem de pais weighted (λ=10, a config validada do
paper §3.1) / power_law, no lugar do 70/20/10; (2) filtro de
novidade Tier 1 com proxy LOCAL (AST normalizado do EVOLVE-BLOCK
+ difflib), rejeitando quase-duplicado ANTES da cascata.

A aceitação da issue: flags DESLIGADAS por padrão e, desligadas,
a corrida é bit-idêntica à de sempre — provado aqui comparando
uma mini-corrida default com outra com as flags explicitamente
desligadas (mesmos registros, mesmo campeão), e pela suíte
existente inteira verde sem alteração.
"""
from __future__ import annotations

import importlib.util
import random
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "forge" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run():
    return _load("forge_run_shinka", "run.py")


PROG_A = """
class P:
    # EVOLVE-BLOCK-START
    def reserve(self, cash):
        return cash * 0.30

    def buffer(self, stock):
        return stock + 12
    # EVOLVE-BLOCK-END
"""

PROG_NEAR = PROG_A.replace("0.30", "0.31")   # um literal: quase-cópia

PROG_DISTINCT = """
class P:
    # EVOLVE-BLOCK-START
    def reserve(self, cash):
        if cash > 9000:
            return 1200
        return 45

    def pick(self, options):
        return options[-1] if options else None
    # EVOLVE-BLOCK-END
"""


# ------------------------------------------------------------------ #
# Defaults: o porte nasce DESLIGADO
# ------------------------------------------------------------------ #
def test_flags_default_off(run):
    assert run.PARENT_SAMPLING == "off"
    assert run.NOVELTY_FILTER is False
    assert run.PARENT_LAMBDA == 10.0        # λ do paper, §3.1
    assert run.PARENT_ALPHA == 1.0          # default do repo Shinka
    # limiar do PROXY local — não o 0,95 do embedding do paper
    assert run.NOVELTY_THRESHOLD == 0.98


# ------------------------------------------------------------------ #
# Técnica 1 — pesos da weighted (a fórmula do paper, ao decimal)
# ------------------------------------------------------------------ #
def test_weighted_weights_follow_paper_formula(run):
    members = ["a", "b", "c"]
    fitness = {"a": 0.60, "b": 0.50, "c": 0.40}     # mediana 0,50
    w = run.parent_weights(members, fitness, {}, "weighted")
    # s = σ(10·(F − 0,50)): σ(1)=0,731059, σ(0)=0,5, σ(−1)=0,268941
    assert w == pytest.approx([0.731059, 0.5, 0.268941], abs=1e-6)


def test_weighted_novelty_factor_punishes_prolific_parent(run):
    members = ["a", "b"]
    fitness = {"a": 0.5, "b": 0.5}                  # mesmo fitness
    w = run.parent_weights(members, fitness,
                           {"a": 0, "b": 9}, "weighted")
    # h = 1/(1+N): 1,0 vs 0,1 → razão exata de 10×
    assert w[0] / w[1] == pytest.approx(10.0)
    # com 3 filhos gerados, o σ(1) do melhor é dividido por 4
    w3 = run.parent_weights(["a", "b", "c"],
                            {"a": 0.60, "b": 0.50, "c": 0.40},
                            {"a": 3}, "weighted")
    assert w3[0] == pytest.approx(0.731059 / 4, abs=1e-6)


def test_weighted_sampling_distribution(run):
    members = ["a", "b", "c"]
    fitness = {"a": 0.60, "b": 0.50, "c": 0.40}
    weights = run.parent_weights(members, fitness, {}, "weighted")
    total = sum(weights)
    expected = {m: w / total for m, w in zip(members, weights)}
    rng = random.Random(1234)
    n = 30_000
    counts = Counter(run.sample_parent(members, fitness, {},
                                       "weighted", rng)
                     for _ in range(n))
    for m in members:
        assert counts[m] / n == pytest.approx(expected[m], abs=0.015)
    # o melhor pai é o mais sorteado, mas NÃO é determinístico:
    assert counts.most_common(1)[0][0] == "a"
    assert all(counts[m] > 0 for m in members)


def test_power_law_weights_by_rank(run):
    members = ["a", "b", "c"]
    fitness = {"a": 0.9, "b": 0.5, "c": 0.1}
    w = run.parent_weights(members, fitness, {}, "power_law")
    assert w == pytest.approx([1.0, 0.5, 1.0 / 3.0])   # rank^(−1)
    w2 = run.parent_weights(members, fitness, {}, "power_law",
                            alpha=2.0)
    assert w2 == pytest.approx([1.0, 0.25, 1.0 / 9.0])


def test_unknown_strategy_raises(run):
    with pytest.raises(ValueError):
        run.parent_weights(["a"], {"a": 0.5}, {}, "bogus")
    with pytest.raises(ValueError):
        run.run_forge(iterations=1, parent_sampling="bogus",
                      log=lambda *a: None)


# ------------------------------------------------------------------ #
# Técnica 2 — o proxy de novidade separa cópia de programa novo
# ------------------------------------------------------------------ #
def test_novelty_similarity_scale(run):
    assert run.block_similarity(PROG_A, PROG_A) == 1.0
    near = run.block_similarity(PROG_A, PROG_NEAR)
    distinct = run.block_similarity(PROG_A, PROG_DISTINCT)
    assert near >= run.NOVELTY_THRESHOLD        # 1 literal → fora
    assert distinct < 0.75                      # outro programa → ok
    assert run.max_block_similarity(PROG_NEAR, [PROG_A]) == \
        pytest.approx(near)
    assert run.max_block_similarity(PROG_DISTINCT, []) == 0.0


def test_novelty_measures_only_the_mutable_block(run):
    # fora do bloco, tudo pode mudar: a similaridade nem percebe
    outside = PROG_A.replace("class P:", "class Q:")
    assert run.block_similarity(PROG_A, outside) == 1.0


# ------------------------------------------------------------------ #
# Mini-corridas: desligado = caminho antigo; ligado = fumaça
# ------------------------------------------------------------------ #
def _strip_timing(records):
    return [{k: v for k, v in r.items()
             if k not in ("timing", "seconds")} for r in records]


def test_mini_run_flags_off_is_the_legacy_run(run, tmp_path,
                                              monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    common = dict(iterations=3, seed=7, mutator_kind="programmatic",
                  final=False, log=lambda *a: None)
    default = run.run_forge(out_dir=tmp_path / "a", **common)
    explicit_off = run.run_forge(out_dir=tmp_path / "b",
                                 parent_sampling="off",
                                 novelty_filter=False, **common)
    assert _strip_timing(default["records"]) == \
        _strip_timing(explicit_off["records"])
    assert default["champion_hash"] == explicit_off["champion_hash"]
    assert default["counts"] == explicit_off["counts"]
    assert default["parent_sampling"]["enabled"] is False
    assert default["novelty"]["enabled"] is False
    assert default["counts"]["rejected_novelty"] == 0
    for rec in default["records"][1:]:
        assert "novelty_max_similarity" not in rec
        assert "parent_sampling" not in rec


def test_mini_run_flags_on_smoke(run, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    summary = run.run_forge(iterations=3, seed=7,
                            out_dir=tmp_path / "on",
                            mutator_kind="programmatic", final=False,
                            parent_sampling="weighted",
                            novelty_filter=True,
                            log=lambda *a: None)
    assert summary["ok"] is True
    assert summary["parent_sampling"]["enabled"] is True
    assert summary["parent_sampling"]["strategy"] == "weighted"
    assert summary["novelty"]["enabled"] is True
    # a taxa de rejeição fica logada (aceitação do estudo, §4)
    assert summary["novelty"]["checked"] >= 1
    assert summary["novelty"]["rejected"] >= 0
    assert "rejected_novelty" in summary["counts"]
    loop_records = summary["records"][1:]
    assert all(r.get("parent_sampling") == "weighted"
               for r in loop_records)
    assert all("novelty_max_similarity" in r for r in loop_records
               if r["status"] in ("accepted", "rejected_novelty",
                                  "rejected_guard"))
