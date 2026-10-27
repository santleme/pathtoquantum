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


# --------------------------------------------------------------------- #
# 3) Crônica rica: recordes, rivalidade, causa de falência, resumo de era
# --------------------------------------------------------------------- #
from mundo.chronicle import replay
from mundo.engine import HeuristicPolicy


def test_first_link_becomes_permanent_record():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(24)
    events = eng.chronicle.to_json()
    links = [e for e in events if e["kind"] == "chain_link"]
    records = [e for e in events
               if e["kind"] == "record" and e["data"].get("record") == "first_link"]
    assert links, "o smoke precisa produzir ao menos um marco de cadeia"
    assert [r["data"]["stage"] for r in records] == \
        [l["data"]["stage"] for l in links]
    for r in records:
        assert r["data"]["era"] == 1
        assert eng.first_link[r["data"]["stage"]] == r["company"]


def test_rivalry_narrated_on_leadership_change():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    a, b = eng.companies[0], eng.companies[1]
    eng._cash_leader = b.cid
    eng._stage_leader = b.cid
    a.cash = 10**9
    a.add_facility("plant", (10, 10))          # elo 4 contra elo 0 de b
    eng._note_rivalry()
    riv = [e for e in eng.chronicle.to_json() if e["kind"] == "rivalry"]
    assert {e["data"]["metric"] for e in riv} == {"cash", "stage"}
    for e in riv:
        assert e["data"]["to_cid"] == a.cid and e["data"]["from_cid"] == b.cid
        assert "RIVALIDADE" in e["text"]
    # sem nova troca, sem nova narração
    n = len(eng.chronicle.events)
    eng._note_rivalry()
    assert len(eng.chronicle.events) == n


class CapexSuicidePolicy(HeuristicPolicy):
    """Estoura o caixa da empresa 0 construindo (reason='build') — a
    falência nasce dentro do log e a causa tem que sair 'capex'."""

    def decide(self, engine, comp):
        super().decide(engine, comp)
        if comp.cid == 0 and engine.tick >= 10 and comp.facilities:
            engine._spend(comp, comp.cash + 5_000_000.0, reason="build")


def test_bankruptcy_with_probable_cause():
    eng = Engine(seed=7, n_companies=8, policy=CapexSuicidePolicy(),
                 world_data=False)
    eng.run(24)
    dead = [e for e in eng.chronicle.to_json() if e["kind"] == "bankruptcy"]
    assert dead, "a política suicida precisa quebrar alguém"
    ev = dead[0]
    assert ev["data"]["cause"] == "capex"
    assert "Causa provável" in ev["text"] and "capex" not in ev["text"]


def test_era_summary_every_60_ticks():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(60)
    sums = [e for e in eng.chronicle.to_json() if e["kind"] == "era_summary"]
    assert len(sums) == 1
    s = sums[0]
    assert s["tick"] == 60 and s["data"]["years"] == 5
    assert s["data"]["cash_leader"] and s["data"]["stage_leader"]
    assert "RESUMO DA ERA" in s["text"] and "falências" in s["text"]
    eng2 = Engine(seed=7, n_companies=8, world_data=False)
    eng2.run(120)
    assert len([e for e in eng2.chronicle.to_json()
                if e["kind"] == "era_summary"]) == 2


def _assert_replay_matches(eng, res):
    proj = replay(eng.chronicle.to_json())
    got = {r["name"]: r for r in proj["scoreboard"]}
    assert set(got) == {r["name"] for r in res["scoreboard"]}
    for row in res["scoreboard"]:
        p = got[row["name"]]
        assert p["alive"] == row["alive"] and p["stage"] == row["stage"]
        assert p["facilities"] == row["facilities"]
        assert p["cash"] == pytest.approx(row["cash"], abs=1e-3)
    owners = {fac["id"]: comp.name
              for comp in eng.companies for fac in comp.facilities.values()}
    assert proj["facility_owners"] == owners


def test_replay_with_rich_chronicle_72_ticks():
    # 72 ticks cruzam o resumo de era (60) e exercitam rivalidade,
    # recordes e as ferramentas v1 — o replay continua fechando.
    eng = Engine(seed=7, n_companies=8)
    res = eng.run(72)
    kinds = {e["kind"] for e in eng.chronicle.to_json()}
    assert "era_summary" in kinds and "record" in kinds
    _assert_replay_matches(eng, res)


def test_snapshot_restore_v1_rich_chronicle():
    import json
    eng = Engine(seed=7, n_companies=8)
    for _ in range(30):
        eng.step()
    state = json.loads(json.dumps(eng.state_dict()))
    resumed = Engine.from_state(state).run(42)
    ref = Engine(seed=7, n_companies=8).run(72)
    assert resumed["scoreboard"] == ref["scoreboard"]
    assert resumed["frames"] == ref["frames"]
    assert resumed["chronicle"] == ref["chronicle"]
