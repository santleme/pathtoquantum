"""Testes da camada de Observation (guarda v2) — OBSERVATION-SPEC §4.

A fatia 1 precisa provar duas coisas: (1) o mundo NÃO muda (goldens,
semente bit-idêntica e S == genoma 0 vivem nos seus próprios testes,
intocados); (2) a classe inteira de vazamento por LEITURA fechou —
a verdade oculta e o estado alheio não são proibidos, são
inalcançáveis a partir da única coisa que a política recebe.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from mundo import chain
from mundo.companies import Company
from mundo.engine import Engine, HeuristicPolicy
from mundo.observation import (CompanyView, Observation,
                               build_observation)
from mundo.policies import PolicyRouter
from mundo.program import ProgramRejected, load_program_policy, \
    validate_program


def _obs(eng: Engine, cid: int = 0) -> Observation:
    return build_observation(eng, eng.companies[cid])


# --------------------------------------------------------------------- #
# A verdade oculta não está na superfície
# --------------------------------------------------------------------- #
def test_deposit_view_has_no_hidden_truth():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    obs = _obs(eng)
    assert len(obs.world.deposits) == len(eng.deposits)
    for dv, dep in zip(obs.world.deposits, eng.deposits):
        # o público bate com deposit_public_info...
        assert dv.name == dep.name and dv.resource == dep.resource
        assert dv.lat == dep.lat and dv.lon == dep.lon
        assert dv.cell == dep.cell
        # ...e a verdade oculta nem existe na view
        assert not hasattr(dv, "grade")
        assert not hasattr(dv, "size_t")
        with pytest.raises(AttributeError):
            dv.grade
        with pytest.raises(AttributeError):
            dv.size_t


def test_probe_is_the_only_reveal():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    comp = eng.companies[0]
    obs = _obs(eng)
    dep = eng.deposits[0]
    assert obs.me.knowledge.get(dep.name) is None
    cash0, out0 = comp.cash, eng.money_out
    grade, size_t = obs.act.probe(dep.name)
    # o par revelado é a verdade do mundo — agora conhecimento legal
    assert (grade, size_t) == (dep.grade, dep.size_t)
    assert comp.knowledge[dep.name] == (dep.grade, dep.size_t)
    assert obs.me.knowledge[dep.name] == (dep.grade, dep.size_t)
    # custo e fluxo idênticos aos da era pré-Observation
    assert comp.cash == cash0 - chain.PROBE_COST
    assert eng.money_out == out0 + chain.PROBE_COST
    # e a view do depósito continua sem os campos: quem sabe é a
    # empresa (knowledge), não o anúncio público
    dv = obs.world.deposits[0]
    assert not hasattr(dv, "grade")


# --------------------------------------------------------------------- #
# Estado de rival e futuro: ausentes, não apenas proibidos
# --------------------------------------------------------------------- #
def test_no_rival_state_in_observation():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    rival = eng.companies[1]
    rival.cash = 123_456_789.0           # sentinela: caixa da rival
    obs = _obs(eng, cid=0)
    assert not hasattr(obs.world, "companies")
    assert not hasattr(obs, "companies")
    assert obs.me.cid == 0
    # varredura da superfície pública: nenhum objeto cru do motor e
    # nenhum valor da rival vaza pelas views
    surface = [obs.me, obs.world, obs.act, obs.rng]
    for obj in surface:
        assert not isinstance(obj, (Engine, Company, random.Random))
    valores = [obs.me.cash, *obs.me.stocks.values(),
               *obs.world.prices.values(),
               *(d.claimed_by for d in obs.world.deposits)]
    assert 123_456_789.0 not in valores
    assert type(obs.me) is CompanyView


def test_future_events_are_invisible():
    ev = [{"tick": 30, "type": "price_shock", "commodity": "lithium",
           "factor": 2.0, "duration": 3}]
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 god_events=ev)
    obs = _obs(eng)
    assert not hasattr(obs.world, "god_events")
    assert not hasattr(obs, "god_events")
    # B3: os eventos políticos forçados (o futuro agendado) idem
    eng2 = Engine(seed=42, n_companies=8, world_data=False,
                  country_v2=True)
    eng2._force_events = [{"country": "Chile", "event": "reform",
                           "tick": 9}]
    obs2 = _obs(eng2)
    assert not hasattr(obs2.world, "_force_events")
    assert not hasattr(obs2.world, "force_events")


def test_rng_is_a_forward_only_facade():
    a = Engine(seed=42, n_companies=8, world_data=False)
    b = Engine(seed=42, n_companies=8, world_data=False)
    obs = _obs(a)
    assert not hasattr(obs.rng, "setstate")
    assert not hasattr(obs.rng, "getstate")
    assert not hasattr(obs.rng, "seed")
    # o sorteio repassa ao fluxo do motor, na mesma posição
    assert obs.rng.uniform(0.0, 1.0) == b.rng.uniform(0.0, 1.0)
    assert obs.rng.random() == b.rng.random()


# --------------------------------------------------------------------- #
# As views são congeladas para quem recebe
# --------------------------------------------------------------------- #
def test_views_are_read_only():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    obs = _obs(eng)
    with pytest.raises(AttributeError):
        obs.me.cash = 10 ** 9
    with pytest.raises(AttributeError):
        obs.world.tick = 99
    with pytest.raises(AttributeError):
        obs.world.deposits[0].claimed_by = None
    with pytest.raises(AttributeError):
        obs.me = obs.me
    with pytest.raises(TypeError):
        obs.me.knowledge["X"] = (1.0, 1.0)
    with pytest.raises(TypeError):
        obs.me.stocks["copper"] = 5.0
    with pytest.raises(TypeError):
        obs.world.prices["copper"] = 1.0
    assert not hasattr(obs.me.claimed, "add")
    assert not hasattr(obs.me.stocks, "add")


def test_company_view_is_live_within_the_decision():
    """Escrever pelo Actuator e reler pela view no mesmo tick é o
    comportamento de sempre (caixa após gasto, elo após construir) —
    é o que torna a migração bit-idêntica sem snapshots."""
    eng = Engine(seed=42, n_companies=8, world_data=False)
    obs = _obs(eng)
    cash0 = obs.me.cash
    obs.act.spend(1_000.0, reason="test")
    assert obs.me.cash == cash0 - 1_000.0
    assert not obs.me.has("mine")
    fac = obs.act.build_facility("mine", (0, 0))
    assert obs.me.has("mine") and obs.me.chain_stage() == 1
    assert fac.kind == "mine"
    # a tupla de instalações é a da construção da Observation; quem
    # enxerga a instalação nova na hora é o has()/chain_stage() vivo
    assert fac.id not in {f.id for f in obs.me.facilities}


def test_observation_rebuilt_per_decision_sees_fresh_claims():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    a, b = eng.companies[0], eng.companies[1]
    dep = eng.deposits[0]
    obs_b_before = build_observation(eng, b)
    assert obs_b_before.world.deposits[0].claimed_by is None
    obs_a = build_observation(eng, a)
    obs_a.act.register_claim(dep.cell)
    obs_b_after = build_observation(eng, b)
    assert obs_b_after.world.deposits[0].claimed_by == a.cid
    # a Observation antiga de b é a fotografia do instante dela
    assert obs_b_before.world.deposits[0].claimed_by is None


# --------------------------------------------------------------------- #
# Guarda v2: AST nova + loader + fronteira de runtime
# --------------------------------------------------------------------- #
def test_guard_v2_rejects_mangled_internals():
    code = ("from mundo.engine import HeuristicPolicy\n"
            "class EvolvedPolicy(HeuristicPolicy):\n"
            "    def decide(self, obs):\n"
            "        return obs.act._Actuator__engine\n")
    violations = validate_program(code)
    assert any("atributo privado proibido" in v for v in violations), \
        violations


def test_guard_v2_loader_rejects_legacy_signature(tmp_path):
    p = tmp_path / "legacy.py"
    p.write_text(
        "from mundo.engine import HeuristicPolicy\n"
        "class EvolvedPolicy(HeuristicPolicy):\n"
        "    def decide(self, engine, comp):\n"
        "        pass\n")
    with pytest.raises(ValueError, match="decide precisa aceitar"):
        load_program_policy(p)


def _run_program_as_focal(tmp_path, source: str):
    p = tmp_path / "cand.py"
    p.write_text(source)
    policy = load_program_policy(p)
    router = PolicyRouter({0: policy}, default=HeuristicPolicy())
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=router)
    return eng


def test_program_leak_attempts_fail_detectably(tmp_path):
    head = ("from mundo.engine import HeuristicPolicy\n"
            "class EvolvedPolicy(HeuristicPolicy):\n")
    # 1) grade cru de depósito não sondado: a AST não vê (é o ponto
    #    da v2) — mas o atributo NÃO EXISTE na view: AttributeError
    eng = _run_program_as_focal(
        tmp_path,
        head + "    def decide(self, obs):\n"
               "        x = obs.world.deposits[0].grade\n")
    with pytest.raises(AttributeError):
        eng.run(2)
    # 2) escrever no caixa pela view: a guarda barra a atribuição
    #    em atributo já na carga (a segunda camada — a view congelada
    #    levantando AttributeError — está provada direto nas views
    #    em test_views_are_read_only)
    bad0 = tmp_path / "write.py"
    bad0.write_text(head + "    def decide(self, obs):\n"
                           "        obs.me.cash = 10 ** 9\n")
    with pytest.raises(ProgramRejected):
        load_program_policy(bad0)
    # 3) estado das rivais: a AST v1 já barra .companies na carga
    bad = tmp_path / "rivals.py"
    bad.write_text(head + "    def decide(self, obs):\n"
                          "        x = obs.world.companies\n")
    with pytest.raises(ProgramRejected):
        load_program_policy(bad)
    # 4) o objeto Random: .rng segue banido no fonte (e a fachada
    #    nem tem setstate — ver test_rng_is_a_forward_only_facade)
    bad2 = tmp_path / "rng.py"
    bad2.write_text(head + "    def decide(self, obs):\n"
                           "        obs.rng.setstate(None)\n")
    with pytest.raises(ProgramRejected):
        load_program_policy(bad2)


def test_full_living_world_runs_on_observation():
    """O mundo vivo inteiro (B1+B3+B2) decide pela Observation —
    capex com prêmio de país, equipamentos, mercado: sem um erro e
    com o placar de sempre."""
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 market_v2=True, country_v2=True, equip_v2=True)
    res = eng.run(24)
    assert len(res["scoreboard"]) == 8
    assert eng.tick == 24
