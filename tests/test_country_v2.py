"""Testes da Fase 3 do Degrau 1 — B3 País/política + B4a Importações.

Invariantes sob o mundo político: ledger de dinheiro fecha INCLUINDO a
conta "externo" (B4a) e o sink de royalties (B3); ledger de massa fecha
incluindo a fonte `imported`; fog-of-war intacto (S/e/τ e paridades
são públicos por desenho, probabilidades nunca); determinismo e
snapshot/restore cruzando eventos políticos forçados via
``force_events``. Desligado, o motor é bit-idêntico ao clássico
(goldens da Fase 1 seguem valendo).
"""
import json

import pytest

from mundo import chain, countrydata, tables
from mundo.engine import Engine

ZERO_EVENTS = {"events_yearly": {k: 0.0 for k in (
    "royalty_reform", "export_restriction", "state_jv", "judicial_halt",
    "subsidy", "disaster")},
    # período enorme + stagger 0: nenhuma eleição no horizonte de teste
    # (com stagger > 0, o país de offset k vota já no tick k)
    "model": {"election_period": 100_000, "election_stagger": 0}}


def forced(*events):
    """Parâmetros silenciosos + eventos políticos forçados por tick."""
    params = json.loads(json.dumps(ZERO_EVENTS))
    params["force_events"] = list(events)
    return params


def run_v3(seed=7, ticks=60, companies=8, **kw):
    eng = Engine(seed=seed, n_companies=companies, country_v2=True, **kw)
    return eng, eng.run(ticks)


# --------------------------------------------------------------------- #
# Parâmetros como dado
# --------------------------------------------------------------------- #
def test_country_params_file_matches_embedded_fallback():
    assert countrydata.load_country_params() \
        == countrydata.embedded_params()


def test_country_baselines_match_the_study():
    p = countrydata.resolve_country_params()
    s = {k: v["stability_mean"] for k, v in p["countries"].items()}
    assert s["Chile"] == 0.65 and s["Brasil"] == 0.45
    assert s["Peru"] == 0.40 and s["Argentina"] == 0.35
    assert s["Bolívia"] == 0.30
    ev = p["events_yearly"]           # frequências anuais ancoradas
    assert ev["royalty_reform"] == 0.06 and ev["export_restriction"] == 0.02
    assert ev["state_jv"] == 0.015 and ev["judicial_halt"] == 0.007
    assert ev["subsidy"] == 0.04 and ev["disaster"] == 0.01
    assert p["model"]["capex_premium"] == 0.25
    assert p["model"]["local_opex_frac"] == 0.45
    assert p["model"]["election_period"] == 48
    for v in p["countries"].values():  # fontes e nota por país
        assert v["calibration_note"]


def test_country_maps_cover_both_worlds():
    from mundo import realdata
    worlds = [Engine(seed=1, country_v2=True),
              Engine(seed=1, world_data=False, country_v2=True)]
    for eng in worlds:
        for d in eng.deposits:
            assert eng.deposit_country(d) in countrydata.COUNTRY_NAMES
        for c in eng.cities:
            assert eng.city_country(c.name) in countrydata.COUNTRY_NAMES
    # a fonte real oscila a grafia — a normalização resolve
    assert countrydata.normalize_country("Bolivia") == "Bolívia"
    assert countrydata.normalize_country("Colombia") == "Colômbia"
    data = realdata.load_world_data()
    assert {d.country for d in data.deposits}  # o dataset traz país
    # spot-checks geográficos
    eng = worlds[0]
    assert eng.deposit_country(eng._deposit_by_name["Carajás"]) == "Brasil"
    assert eng.deposit_country(
        eng._deposit_by_name["Salar de Uyuni"]) == "Bolívia"
    assert eng.deposit_country(
        eng._deposit_by_name["El Mutún"]) == "Bolívia"
    assert eng.city_country("Montevidéu") == "Uruguai"


def test_monthly_prob_conversion():
    mp = countrydata.monthly_prob
    assert mp(0.0) == 0.0 and mp(1.0) == 1.0
    assert mp(0.06) == pytest.approx(0.00514, abs=1e-4)
    assert 0.0 < mp(0.007) < mp(0.06) < mp(0.5)


# --------------------------------------------------------------------- #
# Liga/desliga
# --------------------------------------------------------------------- #
def test_off_by_default_and_no_state_block():
    eng = Engine(seed=7, n_companies=8)
    assert eng.country_v2 is False
    eng.run(12)
    state = eng.state_dict()
    assert "country_v2" not in state
    assert "imported" not in state["ledger_mass"]["lithium"]
    res = eng.result()
    assert "politics" not in res and "trade" not in res
    assert eng.capex_mult("Chile") == 1.0
    assert eng.parity_prices("lithium") is None
    assert eng.money_to_external == 0.0 and eng.money_from_external == 0.0


def test_on_changes_history_and_public_series():
    _, off = run_v3(seed=7, ticks=24)
    base = Engine(seed=7, n_companies=8).run(24)
    assert off["scoreboard"] != base["scoreboard"]
    assert set(off["politics"]) == {"Argentina", "Bolívia", "Brasil",
                                    "Chile", "Colômbia", "Paraguai",
                                    "Peru", "Uruguai"}
    for st in off["politics"].values():
        assert set(st) == {"S", "fx", "tau"}       # só o que é público
        assert 0.0 <= st["S"] <= 1.0 and 0.5 <= st["fx"] <= 2.5
        assert 0.02 <= st["tau"] <= 0.12
    assert set(off["trade"]["imported"]) == set(chain.COMMODITIES)


def test_determinism_same_seed_country():
    _, r1 = run_v3(seed=3, ticks=48)
    _, r2 = run_v3(seed=3, ticks=48)
    assert r1["scoreboard"] == r2["scoreboard"]
    assert r1["chronicle"] == r2["chronicle"]
    _, r3 = run_v3(seed=4, ticks=48)
    assert r3["chronicle"] != r1["chronicle"]


# --------------------------------------------------------------------- #
# Invariantes: ledgers com a conta externa e o sink de royalties
# --------------------------------------------------------------------- #
def test_money_ledger_closes_including_external_account():
    for kw in (dict(), dict(market_v2=True)):
        eng, _ = run_v3(seed=7, ticks=60, **kw)
        total = sum(c.cash for c in eng.companies)
        expected = eng.initial_cash + eng.money_in \
            + eng.money_from_external - eng.money_out \
            - eng.money_to_external
        assert total == pytest.approx(expected, abs=1e-4)


def test_mass_ledger_closes_including_imported():
    eng, _ = run_v3(seed=7, ticks=60, market_v2=True)
    for c in chain.COMMODITIES:
        led = eng.ledger_mass[c]
        stocks = sum(comp.stocks[c] for comp in eng.companies)
        inflow = led["extracted"] + led["produced"] + led["imported"]
        outflow = led["consumed"] + led["sold_external"]
        assert stocks == pytest.approx(inflow - outflow, abs=1e-4), c


def test_royalties_are_a_named_sink_in_flows():
    eng, res = run_v3(seed=7, ticks=36)
    royalty = 0.0
    for e in res["chronicle"]:
        if e["kind"] == "flows":
            for rec in e["data"]["companies"].values():
                royalty += -rec["flows"].get("spend_royalty", 0.0)
    assert royalty > 0.0      # τ > 0 em todos os países: royalty flui


def test_fog_of_war_intact_and_country_data_is_public_only():
    eng, _ = run_v3(seed=3, ticks=24)
    for comp in eng.companies:
        for name, (grade, size) in comp.knowledge.items():
            dep = eng._deposit_by_name[name]
            assert grade == dep.grade and size == dep.size_t
    # S/e/τ públicos por desenho — e NADA além disso vaza pelo acessor
    st = eng.country_state("Chile")
    assert set(st) == {"S", "fx", "tau"}
    p_imp, p_exp = eng.parity_prices("copper")
    assert p_imp > p_exp > 0.0     # paridade é pública


def test_replay_still_closes_with_politics_and_external_flows():
    from mundo.chronicle import replay
    eng, res = run_v3(
        seed=7, ticks=60,
        country_params=forced(
            {"tick": 10, "country": "Chile", "event": "royalty_reform"},
            {"tick": 20, "country": "Chile", "event": "export_restriction",
             "resource": "copper_ore"}))
    assert any(e["kind"] == "politics" for e in res["chronicle"])
    proj = replay(res["chronicle"])
    got = {r["name"]: r for r in proj["scoreboard"]}
    for row in res["scoreboard"]:
        assert got[row["name"]]["cash"] == pytest.approx(row["cash"],
                                                         abs=1e-3)


# --------------------------------------------------------------------- #
# B3: capex, royalties, câmbio, paralisação
# --------------------------------------------------------------------- #
def test_capex_multiplier_formula():
    eng = Engine(seed=7, country_v2=True,
                 country_params={"countries": {
                     "Chile": {"stability_mean": 0.2}}})
    # S nasce na média: ×(1 + 0,25·(1 − 0,2)) = ×1,2
    assert eng.capex_mult("Chile") == pytest.approx(1.2)
    assert eng.capex_mult("Brasil") == \
        pytest.approx(1.0 + 0.25 * (1.0 - 0.45))
    assert Engine(seed=7).capex_mult("Chile") == 1.0   # desligado


def _engine_with_chilean_mine(royalty=None):
    params = {"countries": {"Chile": {"royalty": royalty}}} \
        if royalty is not None else None
    eng = Engine(seed=7, country_v2=True, country_params=params)
    comp = eng.companies[0]
    dep = eng._deposit_by_name["Escondida (Norte do Chile)"]
    fac = comp.add_facility("mine", dep.cell)
    fac["deposit"] = dep.name
    return eng, comp, dep


def test_royalty_and_fx_in_ops_spend():
    eng, comp, dep = _engine_with_chilean_mine(royalty=0.12)
    eng._produce(comp)
    # mina processa 420 t × US$ 42 = US$ 17.640 de opex; fx=1,0 no
    # nascimento -> opex efetivo igual; royalty = 12% disso
    flows = eng._flows[comp.cid]
    assert flows["spend_ops"] == pytest.approx(-17_640.0)
    assert flows["spend_royalty"] == pytest.approx(-0.12 * 17_640.0)
    # câmbio desvalorizado (e=2,0): a fração local (45%) custa metade
    # em US$ -> fator 0,55 + 0,45/2 = 0,775 sobre o opex
    eng._countries["Chile"]["fx"] = 2.0
    eng._flows = {}
    eng._produce(comp)
    flows = eng._flows[comp.cid]
    assert flows["spend_ops"] == pytest.approx(-17_640.0 * 0.775)
    assert flows["spend_royalty"] == \
        pytest.approx(-0.12 * 17_640.0 * 0.775)


def test_judicial_halt_stops_mines_in_the_country():
    eng, comp, dep = _engine_with_chilean_mine()
    eng._apply_political_event("Chile", "judicial_halt")
    assert eng._countries["Chile"]["halt_until"] == 2
    cash0, rem0 = comp.cash, eng.remaining[dep.name]
    eng._produce(comp)                       # tick 0 <= 2: parada
    assert comp.cash == cash0 and eng.remaining[dep.name] == rem0
    assert comp.stocks["copper_ore"] == 0.0
    eng.tick = 3                             # liminar vencida
    eng._produce(comp)
    assert eng.remaining[dep.name] < rem0
    assert comp.stocks["copper_ore"] > 0.0
    ev = [e for e in eng.chronicle.events if e.kind == "politics"]
    assert ev and ev[0].data["event"] == "judicial_halt"
    assert ev[0].data["country"] == "Chile" and "PARALISAÇÃO" in ev[0].text


def test_forced_royalty_reform_event_and_tau():
    eng, res = run_v3(seed=7, ticks=12, country_params=forced(
        {"tick": 5, "country": "Chile", "event": "royalty_reform"}))
    st = eng.country_state("Chile")
    assert st["tau"] == pytest.approx(0.05 + 0.02)
    ev = [e for e in res["chronicle"] if e["kind"] == "politics"]
    assert len(ev) == 1 and ev[0]["tick"] == 5
    assert ev[0]["data"]["event"] == "royalty_reform"
    assert ev[0]["data"]["country"] == "Chile"
    assert ev[0]["data"]["commodity"] in chain.RAW_TO_REFINED
    assert "REFORMA DE ROYALTIES" in ev[0]["text"]


def test_no_politics_events_when_probabilities_zeroed():
    eng, res = run_v3(seed=7, ticks=60, country_params=ZERO_EVENTS)
    assert not [e for e in res["chronicle"] if e["kind"] == "politics"]
    assert eng.country_state("Chile")["S"] != 0.65   # S anda mesmo assim


def test_elections_shift_country_means():
    params = json.loads(json.dumps(ZERO_EVENTS))
    params["model"]["election_period"] = 6
    eng, res = run_v3(seed=7, ticks=24, country_params=params)
    ev = [e for e in res["chronicle"]
          if e["kind"] == "politics" and e["data"]["event"] == "election"]
    assert len(ev) >= 8                       # todos os países votam
    for name, st in eng._countries.items():
        assert 0.15 <= st["S_mean"] <= 0.9
    assert any("ELEIÇÃO" in e["text"] for e in ev)


def test_export_restriction_raises_parity_via_b4a():
    eng = Engine(seed=7, country_v2=True, country_params=forced(
        {"tick": 0, "country": "Chile", "event": "export_restriction",
         "resource": "copper_ore"}))
    base = chain.BASE_PRICES["copper_ore"]           # sem B1: âncora=base
    eng.step()                                       # tick 0: o evento
    p_imp, p_exp = eng.parity_prices("copper_ore")
    assert p_imp == pytest.approx(base * 1.2 * 1.6)  # (1+tar+frete)×surch.
    assert p_exp == pytest.approx(base * 0.92 * 1.6)
    # o refinado do mesmo minério também encarece; outro minério, não
    assert eng.parity_prices("copper")[0] == \
        pytest.approx(chain.BASE_PRICES["copper"] * 1.2 * 1.6)
    assert eng.parity_prices("lithium_ore")[0] == \
        pytest.approx(chain.BASE_PRICES["lithium_ore"] * 1.2)


# --------------------------------------------------------------------- #
# B4a: o participante externo na paridade
# --------------------------------------------------------------------- #
def _quiet_market_engine():
    eng = Engine(seed=7, n_companies=8, world_data=False, country_v2=True,
                 country_params=ZERO_EVENTS)
    for c in eng.companies:
        c._offers, c._buys = {}, {}
    return eng


def test_imports_fill_unfilled_company_buys():
    eng = _quiet_market_engine()
    comp = eng.companies[0]
    eng.prices["lithium_ore"] = 3_000.0    # âncora 900, paridade 1.080
    comp._buys = {"lithium_ore": 50.0}
    cash0 = comp.cash
    eng._market()
    assert comp.stocks["lithium_ore"] == pytest.approx(50.0)
    assert comp.cash == pytest.approx(cash0 - 50.0 * 3_000.0)
    assert eng.money_to_external == pytest.approx(50.0 * 3_000.0)
    assert eng.ledger_mass["lithium_ore"]["imported"] == \
        pytest.approx(50.0)


def test_exports_absorb_surplus_below_parity():
    eng = _quiet_market_engine()
    comp = eng.companies[0]
    ci = chain.COMMODITY_INDEX["lithium_ore"]
    comp.stocks.add(ci, 100.0)
    comp._offers = {"lithium_ore": 100.0}
    eng.prices["lithium_ore"] = 400.0      # paridade de exportação: 828
    cash0 = comp.cash
    eng._market()
    assert comp.stocks["lithium_ore"] == pytest.approx(0.0)
    assert comp.cash == pytest.approx(cash0 + 100.0 * 400.0)
    assert eng.money_from_external == pytest.approx(100.0 * 400.0)
    assert eng.ledger_mass["lithium_ore"]["sold_external"] == \
        pytest.approx(100.0)


def test_no_external_trade_inside_the_parity_band():
    eng = _quiet_market_engine()
    comp = eng.companies[0]
    comp._buys = {"lithium_ore": 50.0}     # preço = âncora: dentro da banda
    eng._market()
    assert eng.money_to_external == 0.0 and eng.money_from_external == 0.0
    assert eng.ledger_mass["lithium_ore"].get("imported", 0.0) == 0.0


# --------------------------------------------------------------------- #
# Snapshot/restore cruzando eventos políticos forçados
# --------------------------------------------------------------------- #
def test_snapshot_restore_crossing_forced_political_events():
    kw = dict(country_v2=True, market_v2=True,
              country_params=forced(
                  {"tick": 35, "country": "Chile",
                   "event": "royalty_reform"},
                  {"tick": 40, "country": "Chile",
                   "event": "export_restriction",
                   "resource": "copper_ore"},
                  {"tick": 45, "country": "Brasil",
                   "event": "judicial_halt"},
                  {"tick": 50, "country": "Argentina",
                   "event": "state_jv"}))
    eng = Engine(seed=7, n_companies=8, **kw)
    for _ in range(30):
        eng.step()
    state = json.loads(json.dumps(eng.state_dict()))
    assert "country_v2" in state and state["country_v2"]["countries"]
    resumed = Engine.from_state(state)
    assert resumed.country_v2 is True
    assert resumed._countries == eng._countries
    out = resumed.run(42)
    ref = Engine(seed=7, n_companies=8, **kw).run(72)
    assert out["scoreboard"] == ref["scoreboard"]
    assert out["frames"] == ref["frames"]
    assert out["chronicle"] == ref["chronicle"]
    assert out["politics"] == ref["politics"]
    kinds = {(e["data"]["event"]) for e in ref["chronicle"]
             if e["kind"] == "politics"}
    assert {"royalty_reform", "export_restriction", "judicial_halt",
            "state_jv"} <= kinds


def test_classic_state_restores_with_country_off():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(12)
    back = Engine.from_state(json.loads(json.dumps(eng.state_dict())))
    assert back.country_v2 is False
    assert back.run(12)["scoreboard"] == \
        Engine(seed=7, n_companies=8, world_data=False).run(24)["scoreboard"]


def test_driver_country_v2_matches_direct():
    from mundo.driver import run_batch
    got = run_batch([7], ticks=24, n_companies=8, processes=1,
                    world_data=False, country_v2=True)
    ref = Engine(seed=7, n_companies=8, world_data=False,
                 country_v2=True).run(24)
    assert got[0]["scoreboard"] == ref["scoreboard"]
    assert got[0]["money_to_external"] == eng_money_to_external(ref)
    assert any(e["kind"] == "flows" for e in got[0]["chronicle"])


def eng_money_to_external(_res):
    return _res.get("trade", {}).get("money_to_external", 0.0)


def test_tables_countries_projection():
    eng, _ = run_v3(seed=7, ticks=12)
    names, mat = tables.countries_table(eng)
    assert names == sorted(eng._countries)
    assert mat.shape == (len(names), 3)
    assert mat[names.index("Chile"), 0] == \
        pytest.approx(eng.country_state("Chile")["S"])
    names_off, mat_off = tables.countries_table(Engine(seed=7))
    assert names_off == [] and mat_off.shape == (0, 3)
