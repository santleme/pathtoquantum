"""Testes do salto v1 — mundo maior, ferramentas novas, crônica rica.

Fixtures minúsculas como no resto da suíte: a corrida de verdade roda
no Kaggle. Aqui se prova estrutura, determinismo e os invariantes.
"""
import pytest

from mundo import world
from mundo.engine import Engine


# --------------------------------------------------------------------- #
# 1) Mundo maior
# --------------------------------------------------------------------- #
def test_grid_expanded_anchors_kept():
    assert (world.ROWS, world.COLS) == (30, 22)
    # âncoras do v0 intactas: nada que existia muda de célula
    for d in world.DEPOSITS:
        assert d.cell == world.cell_of(d.lat, d.lon)
    for c in world.CITIES:
        assert c.cell == world.cell_of(c.lat, c.lon)
    # o norte novo é endereçável sem clamp (lat 17 era fora da grade v0)
    r, col = world.cell_of(17.0, -60.0)
    assert r == 29 and 0 <= col < world.COLS


def test_v1_world_counts_default_and_fallback():
    eng = Engine(seed=7, n_companies=8)                    # dataset real (v1)
    assert eng.world_source == "realdata"
    assert len(eng.deposits) == 13 and len(eng.cities) == 11
    names = {d.name for d in eng.deposits}
    assert {"Salar del Hombre Muerto", "Cerro Verde (Arequipa)",
            "El Mutún"} <= names
    assert {"Montevidéu", "Assunção", "Medellín"} <= \
        {c.name for c in eng.cities}
    off = Engine(seed=7, n_companies=8, world_data=False)  # fallback = v0
    assert len(off.deposits) == 10 and len(off.cities) == 8
    assert {d.name for d in off.deposits} == {d.name for d in world.DEPOSITS}


def test_v1_new_deposits_hidden_until_probed():
    eng = Engine(seed=3, n_companies=8)
    mutun = eng._deposit_by_name["El Mutún"]
    assert eng.remaining["El Mutún"] == mutun.size_t > 0
    for comp in eng.companies:                 # fog-of-war vale p/ os novos
        assert "El Mutún" not in comp.knowledge
        assert "Cerro Verde (Arequipa)" not in comp.knowledge


# --------------------------------------------------------------------- #
# 2) Ferramentas novas: VidSim e LojaSim
# --------------------------------------------------------------------- #
from mundo.tools_sim import loja_store_cost, vid_campaign_cost, LOJA_FEE_PCT


def _plant_company(eng, marketing=None, devices=0.0):
    comp = eng.companies[0]
    comp.add_facility("plant", (10, 10))
    if marketing is not None:
        comp.traits["marketing"] = marketing
    comp.stocks["device"] = devices
    return comp


def test_vidsim_debits_and_expires():
    eng = Engine(seed=11, n_companies=8, world_data=False)
    comp = _plant_company(eng, marketing=1.0, devices=50.0)
    cash0, out0 = comp.cash, eng.money_out
    eng._use_tools(comp)
    assert comp.tools.vid_active(eng.tick)
    assert cash0 - comp.cash >= vid_campaign_cost() - 1e-9
    assert eng.money_out - out0 >= vid_campaign_cost() - 1e-9
    assert vid_campaign_cost() == 24_000.0        # 4 vídeos × US$ 6.000
    assert not comp.tools.vid_active(comp.tools.vid_until + 1)


def test_vidsim_requires_marketing_and_plant():
    eng = Engine(seed=11, n_companies=8, world_data=False)
    shy = _plant_company(eng, marketing=0.3, devices=50.0)   # marketing baixo
    eng._use_tools(shy)
    assert not shy.tools.vid_active(eng.tick)
    no_plant = eng.companies[1]
    no_plant.traits["marketing"] = 1.0
    no_plant.stocks["device"] = 50.0
    eng._use_tools(no_plant)
    assert not no_plant.tools.vid_active(eng.tick)
    assert not no_plant.tools.loja_active(eng.tick)


def test_lojasim_activation_and_marketplace_fee():
    eng = Engine(seed=5, n_companies=1, world_data=False)
    comp = _plant_company(eng, devices=100.0)
    eng._use_tools(comp)
    assert comp.tools.loja_active(eng.tick)
    assert comp.cash <= 40_000_000.0 * 1.2 - loja_store_cost() + 1e-9
    # venda às cidades com a loja ativa: comissão de 13% sai do caixa
    comp._offers = {"device": 50.0}
    comp._buys = {}
    price = eng.prices["device"]
    cash0, out0 = comp.cash, eng.money_out
    eng._market()
    gross = 50.0 * price
    fee = gross * LOJA_FEE_PCT
    assert comp.cash == pytest.approx(cash0 + gross - fee, abs=1e-4)
    assert eng.money_out == pytest.approx(out0 + fee, abs=1e-4)
    assert comp.stocks["device"] == pytest.approx(50.0)


def test_lojasim_inactive_pays_no_fee():
    eng = Engine(seed=5, n_companies=1, world_data=False)
    comp = eng.companies[0]
    comp.stocks["device"] = 100.0
    comp._offers = {"device": 50.0}
    comp._buys = {}
    price = eng.prices["device"]
    cash0, out0 = comp.cash, eng.money_out
    eng._market()
    assert comp.cash == pytest.approx(cash0 + 50.0 * price, abs=1e-4)
    assert eng.money_out == pytest.approx(out0, abs=1e-9)


def test_tools_v1_state_roundtrip_and_v0_compat():
    import json
    eng = Engine(seed=11, n_companies=8, world_data=False)
    comp = eng.companies[0]
    comp.tools.vid_until = 9
    comp.tools.loja_until = 7
    state = json.loads(json.dumps(eng.state_dict()))
    back = Engine.from_state(state)
    assert back.companies[0].tools.vid_until == 9
    assert back.companies[0].tools.loja_until == 7
    # state do v0 (sem os campos novos) restaura com os padrões inativos
    del state["companies"][0]["tools"]["vid_until"]
    del state["companies"][0]["tools"]["loja_until"]
    back0 = Engine.from_state(state)
    assert back0.companies[0].tools.vid_until == -1
    assert back0.companies[0].tools.loja_until == -1
