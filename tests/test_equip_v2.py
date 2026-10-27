"""Testes da Fase 4 do Degrau 1 — B2 Equipamentos.

Invariantes sob a frota viva: ledger de dinheiro fecha com os sinks
nomeados (repair/maintenance/overhaul são gastos ao "mundo" via
money_out); ledger de massa intacto (downtime não produz nem consome);
determinismo e snapshot/restore cruzando quebras forçadas
(``hazard_scale``); a política decide — reparo não é automático.
Desligado, o motor é bit-idêntico ao clássico (goldens da Fase 1
seguem valendo e nenhuma instalação ganha a chave "equip").
"""
import json
import math

import pytest

from mundo import chain, equipdata, tables
from mundo.chronicle import replay
from mundo.engine import Engine

NO_BREAKS = {"model": {"hazard_scale": 0.0}}
ALWAYS_BREAKS = {"model": {"hazard_scale": 1.0e6}}


def run_v4(seed=7, ticks=60, companies=8, **kw):
    eng = Engine(seed=seed, n_companies=companies, equip_v2=True, **kw)
    return eng, eng.run(ticks)


def _engine_with_mine(**kw):
    eng = Engine(seed=7, n_companies=8, equip_v2=True, **kw)
    comp = eng.companies[0]
    dep = eng._deposit_by_name["Escondida (Norte do Chile)"]
    fac = comp.add_facility("mine", dep.cell)
    fac["deposit"] = dep.name
    return eng, comp, dep, fac


# --------------------------------------------------------------------- #
# Parâmetros como dado + matemática pura
# --------------------------------------------------------------------- #
def test_equip_params_file_matches_embedded_fallback():
    assert equipdata.load_facility_params() \
        == equipdata.embedded_params()


def test_equip_params_match_the_design():
    p = equipdata.resolve_equip_params()
    for v in p["facilities"].values():     # Weibull β≈1,6 do estudo §B2
        assert v["beta"] == 1.6
        assert v["eta_months"] > 0 and v["wear_rate"] > 0
        assert v["calibration_note"]
    m = p["model"]
    assert m["repair_frac_min"] == 0.08 and m["repair_frac_max"] == 0.15
    assert m["repair_ticks_min"] == 2 and m["repair_ticks_max"] == 6
    assert m["repair_ticks_lognorm_mu"] == 0.7   # recalibração pós-veredito B2
    assert 0.015 <= m["maint_frac"] <= 0.03      # PM: 1,5–3% do custo
    assert m["maint_restore"] == 0.5
    assert m["overhaul_frac"] == 0.6             # overhaul: 60% do custo
    assert m["age_derate"] == 0.15 and m["age_derate_months"] == 240
    assert m["hazard_scale"] == 1.0 and m["wear_scale"] == 1.0


def test_weibull_hazard_formula():
    h = equipdata.weibull_hazard
    eta, beta = 42.0, 1.6
    assert h(0, eta, beta) == pytest.approx(
        1.0 - math.exp(-((1.0 / eta) ** beta)), abs=1e-12)
    # β > 1: o hazard CRESCE com a idade (desgaste, não memória curta)
    assert h(10, eta, beta) < h(60, eta, beta) < h(120, eta, beta)
    assert 0.0 < h(0, eta, beta) < 0.01
    assert h(120, eta, beta) > 0.05
    with pytest.raises(ValueError):
        h(-1, eta, beta)


def test_effective_capacity_formula():
    model = equipdata.resolve_equip_params()["model"]
    ec = equipdata.effective_capacity
    assert ec(420.0, 1.0, 0, model) == pytest.approx(420.0)
    assert ec(420.0, 0.5, 0, model) == pytest.approx(210.0)
    # planta de 20 anos perde os 15% mesmo com h = 1
    assert ec(420.0, 1.0, 240, model) == pytest.approx(420.0 * 0.85)
    assert ec(420.0, 1.0, 480, model) == pytest.approx(420.0 * 0.85)
    # meio da rampa: 120 meses -> metade do derate
    assert ec(420.0, 1.0, 120, model) == pytest.approx(420.0 * 0.925)


def test_equip_params_validation_rejects_bad_data():
    with pytest.raises(equipdata.EquipParamsError):
        equipdata.resolve_equip_params({"facilities": {"mine": {"beta": 0.5}}})
    with pytest.raises(equipdata.EquipParamsError):
        equipdata.resolve_equip_params({"model": {"overhaul_frac": 1.5}})
    with pytest.raises(equipdata.EquipParamsError):
        equipdata.resolve_equip_params({"facilities": {"warp_drive": {}}})


# --------------------------------------------------------------------- #
# Liga/desliga
# --------------------------------------------------------------------- #
def test_off_by_default_and_no_equip_state_anywhere():
    eng = Engine(seed=7, n_companies=8)
    assert eng.equip_v2 is False
    res = eng.run(36)
    assert "equipment" not in res
    assert "equip_v2" not in eng.state_dict()
    for comp in eng.companies:
        for fac in comp.facilities.values():
            assert "equip" not in fac      # nem um bit a mais no clássico
    frame_fac = res["frames"][-1]["companies"][0]["facilities"]
    if frame_fac:
        assert set(frame_fac[0]) == {"kind", "cell", "deposit"}


def test_on_changes_history_and_reports_equipment():
    eng, res = run_v4(seed=7, ticks=60, equip_params=NO_BREAKS)
    base = Engine(seed=7, n_companies=8).run(60)
    assert res["scoreboard"] != base["scoreboard"]   # h<1 muda a produção
    eq = res["equipment"]
    assert set(eq) == {"companies", "fleet"}
    assert eq["fleet"]["fac_ticks"] > 0
    assert 0.0 <= eq["fleet"]["availability"] <= 1.0
    for st in eq["companies"].values():
        assert st["breaks"] == 0                     # hazard zerado
        assert 0.0 <= st["availability"] <= 1.0


def test_determinism_same_seed_equip():
    _, r1 = run_v4(seed=3, ticks=48)
    _, r2 = run_v4(seed=3, ticks=48)
    assert r1["scoreboard"] == r2["scoreboard"]
    assert r1["chronicle"] == r2["chronicle"]
    assert r1["equipment"] == r2["equipment"]
    _, r3 = run_v4(seed=4, ticks=48)
    assert r3["chronicle"] != r1["chronicle"]


# --------------------------------------------------------------------- #
# Invariantes: ledgers com os sinks de equipamento
# --------------------------------------------------------------------- #
def test_money_ledger_closes_with_equipment_sinks():
    for kw in (dict(), dict(market_v2=True), dict(country_v2=True)):
        eng, _ = run_v4(seed=7, ticks=60, **kw)
        total = sum(c.cash for c in eng.companies)
        expected = eng.initial_cash + eng.money_in \
            + eng.money_from_external - eng.money_out \
            - eng.money_to_external
        assert total == pytest.approx(expected, abs=1e-4)


def test_mass_ledger_closes_with_equip():
    eng, _ = run_v4(seed=7, ticks=60)
    for c in chain.COMMODITIES:
        led = eng.ledger_mass[c]
        stocks = sum(comp.stocks[c] for comp in eng.companies)
        inflow = led["extracted"] + led["produced"] \
            + led.get("imported", 0.0)
        outflow = led["consumed"] + led["sold_external"]
        assert stocks == pytest.approx(inflow - outflow, abs=1e-4), c


def test_repair_and_maintenance_are_named_sinks_in_flows():
    eng, res = run_v4(seed=42, ticks=120)
    sinks = {"spend_repair": 0.0, "spend_maintenance": 0.0,
             "spend_overhaul": 0.0}
    for e in res["chronicle"]:
        if e["kind"] == "flows":
            for rec in e["data"]["companies"].values():
                for k in sinks:
                    sinks[k] += -rec["flows"].get(k, 0.0)
    assert sinks["spend_repair"] > 0.0        # quebras foram consertadas
    assert sinks["spend_maintenance"] > 0.0   # PM aconteceu de verdade


def test_replay_still_closes_with_breakdowns():
    eng, res = run_v4(seed=7, ticks=60, equip_params=ALWAYS_BREAKS)
    assert any(e["kind"] == "breakdown" for e in res["chronicle"])
    proj = replay(res["chronicle"])
    got = {r["name"]: r for r in proj["scoreboard"]}
    for row in res["scoreboard"]:
        assert got[row["name"]]["cash"] == pytest.approx(row["cash"],
                                                         abs=1e-3)


# --------------------------------------------------------------------- #
# Mecânica: desgaste, mothball, quebra, reparo, PM, overhaul
# --------------------------------------------------------------------- #
def test_operating_facility_wears_by_utilization():
    eng, comp, dep, fac = _engine_with_mine(equip_params=NO_BREAKS)
    eng._produce(comp)
    eq = fac["equip"]
    assert eq["age"] == 1
    # mina em utilização ~1: h cai wear_rate no primeiro mês
    assert eq["cond"] == pytest.approx(1.0 - 0.016, abs=0.002)
    assert comp.stocks["copper_ore"] > 0.0


def test_idle_facility_does_not_wear_but_ages():
    eng = Engine(seed=7, n_companies=8, equip_v2=True,
                 equip_params=NO_BREAKS)
    comp = eng.companies[0]
    fac = comp.add_facility("refinery", (0, 0))   # sem estoque: parada
    eng._produce(comp)
    eq = fac["equip"]
    assert eq["cond"] == 1.0          # mothball: planta parada não desgasta
    assert eq["age"] == 1             # mas o calendário anda


def test_forced_break_stops_production_and_counts_downtime():
    eng, comp, dep, fac = _engine_with_mine(equip_params=ALWAYS_BREAKS)
    eng._produce(comp)                       # opera e quebra no 1º mês
    eq = fac["equip"]
    assert eq["broken"] is True
    assert 0.08 * 2_500_000 <= eq["repair_cost"] <= 0.15 * 2_500_000
    assert 2 <= eq["repair_ticks"] <= 6
    ev = [e for e in eng.chronicle.events if e.kind == "breakdown"]
    assert len(ev) == 1 and ev[0].data["fid"] == fac["id"]
    assert "QUEBRA" in ev[0].text
    rem = eng.remaining[dep.name]
    eng._produce(comp)                       # quebrada: nem produz
    assert eng.remaining[dep.name] == rem
    assert eng._equip_stats[comp.cid]["down_ticks"] == 1
    assert eng.facility_down(fac) is True


def test_repair_is_a_policy_decision_not_automatic():
    eng, comp, dep, fac = _engine_with_mine(equip_params=ALWAYS_BREAKS)
    eng._produce(comp)
    eq = fac["equip"]
    assert eq["broken"] is True
    # sem decisão, ticks passam e ela CONTINUA quebrada
    eng._produce(comp)
    assert eq["broken"] is True
    # a decisão (decide da política) paga e manda para a oficina
    eng._decide(comp)
    assert eq["broken"] is False
    assert eq["down_until"] == eng.tick + eq["repair_ticks"] - 1
    assert eng._equip_stats[comp.cid]["repairs"] == 1
    assert eng._flows[comp.cid]["spend_repair"] == \
        pytest.approx(-eq["repair_cost"])
    ev = [e for e in eng.chronicle.events
          if e.kind == "maintenance" and e.data.get("action") == "repair"]
    assert len(ev) == 1 and "REPARO" in ev[0].text


def test_broke_company_defers_repair_when_cash_is_tight():
    eng, comp, dep, fac = _engine_with_mine(equip_params=ALWAYS_BREAKS)
    eng._produce(comp)
    eq = fac["equip"]
    # caixa colado na reserva: ninguém paga conserto este mês
    comp.cash = eng._reserve(comp) + eq["repair_cost"] * 0.5
    eng._decide(comp)
    assert eq["broken"] is True
    assert eng._equip_stats[comp.cid]["repairs"] == 0


def test_preventive_maintenance_restores_condition_and_can_stop_plant():
    eng, comp, dep, fac = _engine_with_mine(equip_params=NO_BREAKS)
    eng._produce(comp)                       # cria o estado equip
    eq = fac["equip"]
    eq["cond"] = 0.2                          # planta no osso
    eng._decide(comp)
    assert eq["cond"] == pytest.approx(0.7)   # +0,5 de restauração
    assert eq["down_until"] == eng.tick       # h<=0,3: para 1 tick
    assert eng._equip_stats[comp.cid]["maintenances"] == 1
    assert eng._flows[comp.cid]["spend_maintenance"] == \
        pytest.approx(-2_500_000 * 0.022)
    ev = [e for e in eng.chronicle.events
          if e.kind == "maintenance"
          and e.data.get("action") == "preventive"]
    assert len(ev) == 1 and "MANUTENÇÃO PESADA" in ev[0].text


def test_light_preventive_maintenance_does_not_stop_plant():
    eng, comp, dep, fac = _engine_with_mine(equip_params=NO_BREAKS)
    eng._produce(comp)
    eq = fac["equip"]
    eq["cond"] = 0.32                         # abaixo do limiar de todos
    eng._decide(comp)                        # os arquétipos (>= 0,335)
    assert eq["cond"] == pytest.approx(0.82)
    assert eq["down_until"] == -1             # rotina: não para
    assert not [e for e in eng.chronicle.events
                if e.kind == "maintenance"]   # e não vira notícia


def test_overhaul_resets_age_and_condition():
    eng, comp, dep, fac = _engine_with_mine(equip_params=NO_BREAKS)
    eng._produce(comp)
    eq = fac["equip"]
    eq["age"] = 200
    eq["cond"] = 0.3
    eng._decide(comp)
    assert eq["age"] == 0 and eq["cond"] == 1.0
    assert eng._equip_stats[comp.cid]["overhauls"] == 1
    assert eng._flows[comp.cid]["spend_overhaul"] == \
        pytest.approx(-2_500_000 * 0.6)
    ev = [e for e in eng.chronicle.events
          if e.kind == "maintenance" and e.data.get("action") == "overhaul"]
    assert len(ev) == 1 and "OVERHAUL" in ev[0].text


def test_bankruptcy_cause_names_the_broken_fleet():
    eng, comp, dep, fac = _engine_with_mine(equip_params=ALWAYS_BREAKS)
    eng._produce(comp)
    assert fac["equip"]["broken"] is True
    comp.cash = -1.0
    eng._check_bankruptcy(comp)
    ev = [e for e in eng.chronicle.events if e.kind == "bankruptcy"]
    assert len(ev) == 1 and ev[0].data["cause"] == "quebra"


def test_frames_show_public_equipment_symptom_only_when_on():
    eng, res = run_v4(seed=7, ticks=12, equip_params=NO_BREAKS)
    facs = [f for c in res["frames"][-1]["companies"]
            for f in c["facilities"]]
    assert facs, "a corrida de 12 ticks já tem instalações"
    for f in facs:
        assert set(f) == {"kind", "cell", "deposit",
                          "age", "condition", "down"}
        assert f["condition"] <= 1.0 and f["down"] is False


# --------------------------------------------------------------------- #
# Snapshot/restore cruzando quebras + driver + tabelas
# --------------------------------------------------------------------- #
def test_snapshot_restore_crossing_forced_breakdowns():
    kw = dict(equip_v2=True, equip_params=ALWAYS_BREAKS)
    eng = Engine(seed=7, n_companies=8, **kw)
    for _ in range(30):
        eng.step()
    state = json.loads(json.dumps(eng.state_dict()))
    assert "equip_v2" in state and state["equip_v2"]["stats"]
    assert any("equip" in f for cs in state["companies"]
               for f in cs["facilities"].values())
    resumed = Engine.from_state(state)
    assert resumed.equip_v2 is True
    out = resumed.run(42)
    ref = Engine(seed=7, n_companies=8, **kw).run(72)
    assert out["scoreboard"] == ref["scoreboard"]
    assert out["chronicle"] == ref["chronicle"]
    assert out["equipment"] == ref["equipment"]
    assert any(e["kind"] == "breakdown" for e in ref["chronicle"])


def test_classic_state_restores_with_equip_off():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(12)
    back = Engine.from_state(json.loads(json.dumps(eng.state_dict())))
    assert back.equip_v2 is False
    assert back.run(12)["scoreboard"] == \
        Engine(seed=7, n_companies=8, world_data=False).run(24)["scoreboard"]


def test_driver_equip_v2_matches_direct():
    from mundo.driver import run_batch
    got = run_batch([7], ticks=24, n_companies=8, processes=1,
                    world_data=False, equip_v2=True,
                    equip_params=NO_BREAKS)
    ref = Engine(seed=7, n_companies=8, world_data=False,
                 equip_v2=True, equip_params=NO_BREAKS).run(24)
    assert got[0]["scoreboard"] == ref["scoreboard"]
    assert got[0]["equipment"] == ref["equipment"]


def test_tables_facilities_projection():
    eng, _ = run_v4(seed=7, ticks=12, equip_params=NO_BREAKS)
    ids, mat = tables.facilities_table(eng)
    total = sum(len(c.facilities) for c in eng.companies)
    assert len(ids) == total and mat.shape == (total, 4)
    assert (mat[:, 2] <= 1.0).all() and (mat[:, 3] == 0.0).all()
    ids_off, mat_off = tables.facilities_table(Engine(seed=7))
    assert ids_off == [] and mat_off.shape == (0, 4)
