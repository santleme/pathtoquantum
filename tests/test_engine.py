"""Testes estruturais do Mundo Autônomo (fixtures minúsculas, poucos ticks).

NADA aqui é a corrida de verdade — essa roda no Kaggle. Aqui só se prova:
determinismo, conservação (massa/dinheiro), fog-of-war, cadeia, ferramentas.
"""
import pytest

from mundo import chain
from mundo.engine import Engine
from mundo.tools_sim import insta_campaign_cost


def run_small(seed=7, ticks=24, companies=8):
    eng = Engine(seed=seed, n_companies=companies)
    res = eng.run(ticks)
    return eng, res


def test_determinism_same_seed():
    _, r1 = run_small()
    _, r2 = run_small()
    assert r1["scoreboard"] == r2["scoreboard"]
    assert r1["chronicle"] == r2["chronicle"]


def test_different_seed_differs():
    _, r1 = run_small(seed=1)
    _, r2 = run_small(seed=2)
    assert r1["scoreboard"] != r2["scoreboard"]


def test_mass_conservation():
    eng, _ = run_small()
    for c in chain.COMMODITIES:
        led = eng.ledger_mass[c]
        stocks = sum(comp.stocks[c] for comp in eng.companies)
        inflow = led["extracted"] + led["produced"]
        outflow = led["consumed"] + led["sold_external"]
        assert stocks == pytest.approx(inflow - outflow, abs=1e-4), c


def test_money_conservation():
    eng, _ = run_small()
    total = sum(c.cash for c in eng.companies)
    expected = eng.initial_cash + eng.money_in - eng.money_out
    assert total == pytest.approx(expected, abs=1e-4)


def test_fog_of_war_knowledge_only_by_probing():
    eng = Engine(seed=3, n_companies=8)
    for comp in eng.companies:
        assert comp.knowledge == {}       # ninguém nasce sabendo teor/tamanho
    eng.run(12)
    for comp in eng.companies:
        for name, (grade, size) in comp.knowledge.items():
            dep = next(d for d in eng.deposits if d.name == name)
            assert grade == dep.grade and size == dep.size_t
    # nenhuma mina pode existir sobre depósito não sondado pelo dono
    for comp in eng.companies:
        for fac in comp.facilities.values():
            if fac["kind"] == "mine":
                assert fac["deposit"] in comp.knowledge


def test_chain_requires_inputs():
    eng = Engine(seed=5, n_companies=8)
    comp = eng.companies[0]
    comp.add_facility("factory", (10, 10))
    before = comp.stocks["component"]
    eng._produce(comp)
    assert comp.stocks["component"] == before == 0.0   # sem metal, sem componente
    comp.stocks["copper"] = 2.0
    comp.stocks["lithium"] = 0.5
    eng._produce(comp)
    assert comp.stocks["component"] == 100.0           # receita: 0.02t Cu/unid


def test_instasim_debits_and_expires():
    eng = Engine(seed=11, n_companies=8)
    comp = eng.companies[0]
    comp.add_facility("plant", (10, 10))
    comp.traits["marketing"] = 1.0
    cash0, out0 = comp.cash, eng.money_out
    spent = False
    for _ in range(6):
        eng._use_tools(comp)
        if comp.tools.insta_active(eng.tick):
            spent = True
            break
        eng.tick += 1
    assert spent, "com marketing=1 a empresa deveria anunciar"
    assert comp.cash <= cash0 - insta_campaign_cost() + 1e-9
    assert eng.money_out >= out0 + insta_campaign_cost() - 1e-9
    until = comp.tools.insta_until
    assert not comp.tools.insta_active(until + 1)      # efeito expira


def test_frames_and_chronicle_shape():
    _, res = run_small(ticks=13)
    assert res["frames"][0]["tick"] == 0
    assert res["frames"][-1]["tick"] == 13
    kinds = {e["kind"] for e in res["chronicle"]}
    assert "founding" in kinds and "end" in kinds
    assert len(res["scoreboard"]) == 8


def test_god_price_shock_event():
    ev = [{"tick": 2, "type": "price_shock", "commodity": "lithium",
           "factor": 1.5, "duration": 3}]
    eng = Engine(seed=7, god_events=ev)
    p0 = eng.prices["lithium"]
    eng.run(3)
    assert any(e["kind"] == "god" for e in eng.chronicle.to_json())
    assert eng.prices["lithium"] != p0
