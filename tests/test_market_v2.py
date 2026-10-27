"""Testes da Fase 2 do Degrau 1 — B1 Mercado vivo.

Invariantes sob o mercado novo: ledger fecha, fog-of-war intacto,
determinismo e snapshot/restore cruzando viradas de regime. Desligado,
o motor é bit-idêntico ao clássico (goldens da Fase 1 seguem valendo).
"""
import json

import pytest

from mundo import chain, marketdata
from mundo.engine import Engine

# parâmetros de teste: regimes de 2 meses -> viradas garantidas em
# qualquer horizonte de teste, sem tocar nos parâmetros de calibração
FAST_REGIMES = {"commodities": {c: {"boom_months": 2, "bust_months": 2,
                                    "normal_months": 2}
                                for c in chain.COMMODITIES}}


def run_v2(seed=7, ticks=60, companies=8, **kw):
    eng = Engine(seed=seed, n_companies=companies, market_v2=True, **kw)
    return eng, eng.run(ticks)


# --------------------------------------------------------------------- #
# Parâmetros como dado
# --------------------------------------------------------------------- #
def test_params_file_matches_embedded_fallback():
    assert marketdata.load_market_params() == marketdata.embedded_params()


def test_params_cover_chain_with_task_elasticities():
    p = marketdata.resolve_params()["commodities"]
    assert set(p) == set(chain.COMMODITIES)
    assert p["lithium"]["elasticity"] == 0.3
    assert p["copper"]["elasticity"] == 0.4
    assert p["iron_ore"]["elasticity"] == 0.5
    assert p["device"]["elasticity"] == 1.0
    assert p["supercomputer"]["elasticity"] == 1.2
    for c in chain.COMMODITIES:      # fontes e nota de calibração por item
        assert p[c]["calibration_note"]


def test_elastic_demand_and_inventory_math():
    ed = marketdata.elastic_demand
    assert ed(100.0, 100.0, 100.0, 1.0, 1.0) == 100.0     # p == p*
    assert ed(100.0, 200.0, 100.0, 1.0, 1.0) == 50.0      # ε=1: dobra, metade
    assert ed(100.0, 200.0, 100.0, 0.5, 1.0) == pytest.approx(70.71, abs=0.01)
    assert ed(0.0, 200.0, 100.0, 1.0, 1.0) == 0.0
    im = marketdata.inventory_multiplier
    assert im(2.0, 2.0, 0.35) == 1.0                       # I == I*
    assert im(4.0, 2.0, 0.35) < 1.0                        # estoque alto deprime
    assert im(0.5, 2.0, 0.35) > 1.0                        # escassez pressiona
    sf = marketdata.seasonal_factor
    assert sf(0, 0.0, 0) == 1.0
    assert abs(sf(3, 0.1, 0) - 1.1) < 1e-9                # pico do seno


# --------------------------------------------------------------------- #
# Liga/desliga
# --------------------------------------------------------------------- #
def test_off_by_default_and_no_state_block():
    eng = Engine(seed=7, n_companies=8)
    assert eng.market_v2 is False
    eng.run(12)
    assert "market_v2" not in eng.state_dict()
    assert "market" not in eng.result()
    assert eng.anchors == chain.BASE_PRICES


def test_on_changes_history_but_not_setup():
    off = Engine(seed=7, n_companies=8, world_data=False).run(24)
    on = Engine(seed=7, n_companies=8, world_data=False,
                market_v2=True).run(24)
    assert on["scoreboard"] != off["scoreboard"]          # mundo diferente
    assert "market" in on and "anchors" in on["market"]  # série pública p*
    assert set(on["market"]["anchors"]) == set(chain.COMMODITIES)


def test_determinism_same_seed_v2():
    _, r1 = run_v2(seed=3, ticks=48)
    _, r2 = run_v2(seed=3, ticks=48)
    assert r1["scoreboard"] == r2["scoreboard"]
    assert r1["chronicle"] == r2["chronicle"]
    _, r3 = run_v2(seed=4, ticks=48)
    assert r3["chronicle"] != r1["chronicle"]


# --------------------------------------------------------------------- #
# Invariantes
# --------------------------------------------------------------------- #
def test_ledgers_close_with_living_market():
    eng, _ = run_v2(seed=7, ticks=60)
    total = sum(c.cash for c in eng.companies)
    assert total == pytest.approx(
        eng.initial_cash + eng.money_in - eng.money_out, abs=1e-4)
    for c in chain.COMMODITIES:
        led = eng.ledger_mass[c]
        stocks = sum(comp.stocks[c] for comp in eng.companies)
        inflow = led["extracted"] + led["produced"]
        outflow = led["consumed"] + led["sold_external"]
        assert stocks == pytest.approx(inflow - outflow, abs=1e-4), c


def test_fog_of_war_intact_and_cover_is_aggregate_only():
    eng, _ = run_v2(seed=3, ticks=24)
    for comp in eng.companies:
        for name, (grade, size) in comp.knowledge.items():
            dep = eng._deposit_by_name[name]
            assert grade == dep.grade and size == dep.size_t
    cover = eng.inventory_cover("lithium")
    assert isinstance(cover, float) and cover >= 0.0
    # a cobertura é do AGREGADO: não coincide com o estoque de ninguém
    # em particular e não expõe mapa por empresa
    assert not isinstance(eng.inventory_cover("copper"), dict)


def test_replay_still_closes_with_market_events():
    from mundo.chronicle import replay
    eng, res = run_v2(seed=7, ticks=60, market_params=FAST_REGIMES)
    kinds = {e["kind"] for e in res["chronicle"]}
    assert "market_regime" in kinds
    proj = replay(res["chronicle"])
    got = {r["name"]: r for r in proj["scoreboard"]}
    for row in res["scoreboard"]:
        assert got[row["name"]]["cash"] == pytest.approx(row["cash"],
                                                         abs=1e-3)


# --------------------------------------------------------------------- #
# Regimes, recordes, banda
# --------------------------------------------------------------------- #
def test_regime_transitions_narrated_only_on_entry():
    eng, res = run_v2(seed=7, ticks=60, market_params=FAST_REGIMES)
    evs = [e for e in res["chronicle"] if e["kind"] == "market_regime"]
    assert evs, "regimes de 2 meses precisam virar em 60 ticks"
    for e in evs:
        assert e["data"]["regime"] in ("boom", "bust")
        assert e["data"]["commodity"] in chain.COMMODITIES
        assert "MERCADO" in e["text"] and e["company"] is None


def test_price_records_are_episodes_not_monthly_noise():
    eng, res = run_v2(seed=42, ticks=120)
    recs = [e for e in res["chronicle"] if e["kind"] == "price_record"]
    assert recs, "120 ticks com σ real precisam produzir algum recorde"
    # teto anti-spam: a versão sem episódios gerava 172 nesta corrida
    assert len(recs) <= 60
    for e in recs:
        assert e["data"]["direction"] in ("high", "low")
        assert e["data"]["window"] >= 12


def test_prices_stay_within_anchor_band():
    eng, res = run_v2(seed=7, ticks=60)
    for frame in res["frames"]:
        assert "market" in frame
        for c in chain.COMMODITIES:
            anchor = frame["market"][c]["anchor"]
            price = frame["prices"][c]
            assert 0.25 * anchor - 0.01 <= price <= 6.0 * anchor + 0.01, \
                (frame["tick"], c, price, anchor)


# --------------------------------------------------------------------- #
# Snapshot/restore cruzando viradas de regime
# --------------------------------------------------------------------- #
def test_snapshot_restore_crossing_regime_flips():
    kw = dict(market_v2=True, market_params=FAST_REGIMES)
    eng = Engine(seed=7, n_companies=8, **kw)
    for _ in range(30):
        eng.step()
    state = json.loads(json.dumps(eng.state_dict()))
    assert "market_v2" in state and state["market_v2"]["regime"]
    resumed = Engine.from_state(state)
    assert resumed.market_v2 is True
    assert resumed._regime == eng._regime
    out = resumed.run(42)
    ref = Engine(seed=7, n_companies=8, **kw).run(72)
    assert out["scoreboard"] == ref["scoreboard"]
    assert out["frames"] == ref["frames"]
    assert out["chronicle"] == ref["chronicle"]
    # a corrida de 72 ticks cruzou viradas de regime dos dois lados
    assert any(e["kind"] == "market_regime" for e in ref["chronicle"])


def test_classic_state_restores_with_market_off():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(12)
    back = Engine.from_state(json.loads(json.dumps(eng.state_dict())))
    assert back.market_v2 is False
    assert back.run(12)["scoreboard"] == \
        Engine(seed=7, n_companies=8, world_data=False).run(24)["scoreboard"]


def test_driver_market_v2_matches_direct():
    from mundo.driver import run_batch
    got = run_batch([7], ticks=24, n_companies=8, processes=1,
                    world_data=False, market_v2=True)
    ref = Engine(seed=7, n_companies=8, world_data=False,
                 market_v2=True).run(24)
    assert got[0]["scoreboard"] == ref["scoreboard"]
    assert any(e["kind"] == "flows" for e in got[0]["chronicle"])
