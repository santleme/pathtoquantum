"""Testes da camada de Observation (guarda v2) — OBSERVATION-SPEC §4.

A fatia 1 precisa provar duas coisas: (1) o mundo NÃO muda (goldens,
semente bit-idêntica e S == genoma 0 vivem nos seus próprios testes,
intocados); (2) a classe inteira de vazamento por LEITURA fechou —
a verdade oculta e o estado alheio não são proibidos, são
inalcançáveis a partir da única coisa que a política recebe.
"""
from __future__ import annotations

import json
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


# --------------------------------------------------------------------- #
# Fatia 2 — snapshot serializável (SPEC §4)
# --------------------------------------------------------------------- #
def _walk(node):
    """(tipo, item) de cada chave e cada folha do snapshot."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield ("key", k)
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    else:
        yield ("value", node)


def test_snapshot_is_json_pure_and_detached():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    eng.run(15)
    obs = _obs(eng)
    snap = obs.to_snapshot()
    # só os dois lados da observação: act/rng são capacidades, não
    # dados — ficam fora por desenho
    assert set(snap) == {"me", "world"}
    # JSON puro: round-trip idêntico e nenhuma folha exótica
    assert json.loads(json.dumps(snap)) == snap
    for kind, item in _walk(snap):
        if kind == "key":
            assert isinstance(item, str)
        else:
            assert item is None or isinstance(
                item, (bool, int, float, str))
    # destacado: escrever no snapshot não toca a view nem o motor, e
    # o mundo andar não muda a fotografia já tirada
    cash = obs.me.cash
    snap["me"]["cash"] = -1.0
    snap["world"]["prices"]["copper"] = -1.0
    assert obs.me.cash == cash and eng.prices["copper"] > 0
    tick = snap["world"]["tick"]
    eng.run(3)
    assert snap["world"]["tick"] == tick


def test_snapshot_matches_live_view_field_by_field():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    eng.run(15)
    obs = _obs(eng)
    # garante knowledge não vazio NA MESMA Observation (a view é viva)
    obs.act.probe(eng.deposits[0].name)
    snap = obs.to_snapshot()
    me, w = snap["me"], snap["world"]
    # -- a focal, campo a campo contra a view viva
    assert me["cid"] == obs.me.cid and me["name"] == obs.me.name
    assert me["cash"] == obs.me.cash
    assert me["alive"] == obs.me.alive
    assert me["traits"] == dict(obs.me.traits)
    assert me["stocks"] == dict(obs.me.stocks.items())
    assert me["knowledge"] == {n: list(p) for n, p
                               in obs.me.knowledge.items()}
    assert eng.deposits[0].name in me["knowledge"]
    assert me["claimed"] == [list(c) for c in sorted(obs.me.claimed)]
    assert me["chain_stage"] == obs.me.chain_stage()
    t = obs.me.tools
    assert me["tools"] == {"insta_until": t.insta_until,
                           "insta_strength": t.insta_strength,
                           "zap_until": t.zap_until,
                           "vid_until": t.vid_until,
                           "loja_until": t.loja_until}
    hq = eng._city_by_name[obs.me.hq_city]
    assert me["hq"] == {"name": hq.name, "lat": hq.lat, "lon": hq.lon,
                        "cell": list(hq.cell),
                        "country": eng.city_country(hq.name),
                        "demand_weight": hq.demand_weight}
    for sf, fv in zip(me["facilities"], obs.me.facilities):
        assert sf["id"] == fv.id and sf["kind"] == fv.kind
        assert sf["cell"] == list(fv.cell)
        assert sf["deposit"] == fv.deposit
        assert sf["equip"] is None          # sem B2, sem bloco equip
    # -- o mundo público, campo a campo
    assert w["tick"] == eng.tick == obs.world.tick
    assert w["market_v2"] is False and w["country_v2"] is False
    assert w["equip_v2"] is False
    assert w["prices"] == dict(obs.world.prices) == eng.prices
    assert w["countries"] == []
    assert w["equip_policy"] is None and w["equip_model"] is None
    for sd, dv in zip(w["deposits"], obs.world.deposits):
        assert sd == {"name": dv.name, "resource": dv.resource,
                      "lat": dv.lat, "lon": dv.lon,
                      "cell": list(dv.cell), "country": dv.country,
                      "claimed_by": dv.claimed_by}
    for sc, cv in zip(w["cities"], obs.world.cities):
        assert sc == {"name": cv.name, "lat": cv.lat, "lon": cv.lon,
                      "cell": list(cv.cell), "country": cv.country,
                      "demand_weight": cv.demand_weight}
    assert set(w["capex"]) == {d["country"] for d in w["deposits"]} \
        | {c["country"] for c in w["cities"]}
    for name, mult in w["capex"].items():
        assert mult == obs.world.capex_mult(name)


def test_snapshot_living_world_countries_and_equip():
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 market_v2=True, country_v2=True, equip_v2=True)
    obs = _obs(eng)
    fac = obs.act.build_facility("mine", (0, 0))
    raw = eng.companies[0].facilities[fac.id]
    assert "equip" not in raw
    obs2 = _obs(eng)                     # a Observation que vê a mina
    snap = obs2.to_snapshot()
    # fotografar NÃO materializou o estado preguiçoso da instalação
    assert "equip" not in raw
    sf = next(f for f in snap["me"]["facilities"] if f["id"] == fac.id)
    canonical = {"age": 0, "cond": 1.0, "broken": False,
                 "down_until": -1, "repair_cost": 0.0,
                 "repair_ticks": 0}
    assert sf["equip"] == canonical
    # e bate com o que a view viva expõe quando lida de verdade
    live = obs2.me.facilities[-1].equip
    assert sf["equip"] == {"age": live.age, "cond": live.cond,
                           "broken": live.broken,
                           "down_until": live.down_until,
                           "repair_cost": live.repair_cost,
                           "repair_ticks": live.repair_ticks}
    # países públicos e parâmetros do B2, serializáveis
    w = snap["world"]
    assert [c["name"] for c in w["countries"]] == \
        sorted(eng._countries)
    for sc in w["countries"]:
        st = eng.country_state(sc["name"])
        assert sc == {"name": sc["name"], "S": st["S"], "fx": st["fx"],
                      "tau": st["tau"]}
    assert w["equip_policy"] is not None and w["equip_model"] is not None
    assert json.loads(json.dumps(snap)) == snap


def test_snapshot_leaks_nothing_private():
    # futuro agendado com sentinelas, nos dois canais (Deus e B3)
    ev = [{"tick": 999, "type": "price_shock", "commodity": "lithium",
           "factor": 7.777001, "duration": 3}]
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 market_v2=True, country_v2=True, equip_v2=True,
                 god_events=ev)
    eng._force_events = [{"country": "Chile", "event": "reform",
                          "tick": 987654}]
    # verdade oculta de depósito NÃO sondado e caixa da rival
    eng.deposits[3].grade = 0.4242424242
    eng.companies[1].cash = 123_456_789.0
    obs = _obs(eng, cid=0)
    assert obs.me.knowledge.get(eng.deposits[3].name) is None
    snap = obs.to_snapshot()
    keys = {item for kind, item in _walk(snap) if kind == "key"}
    values = {item for kind, item in _walk(snap) if kind == "value"}
    forbidden = {"grade", "size_t", "god_events", "force_events",
                 "_force_events", "regime", "regimes", "demand_ema",
                 "cover", "fair_noise", "record_state", "remaining",
                 "rng", "act", "engine", "companies", "state_dict",
                 "super_by_cid", "spend_hist"}
    assert not (keys & forbidden), keys & forbidden
    # nenhuma sentinela em valor nenhum, em nível nenhum
    assert 0.4242424242 not in values
    assert 7.777001 not in values
    assert 987654 not in values
    assert 123_456_789.0 not in values
    # a superfície viva também não ganhou os canais proibidos
    assert not hasattr(obs.world, "regime")
    assert not hasattr(obs.world, "scoreboard")
    assert not hasattr(obs.world, "cover")


class _SnapshotPolicy(HeuristicPolicy):
    """A heurística fotografando TODA decisão antes de decidir — se
    o snapshot tocasse o mundo (RNG, estado, ordem), o episódio
    divergiria do episódio sem fotografia."""

    def decide(self, obs):
        json.dumps(obs.to_snapshot())
        return super().decide(obs)


def test_snapshot_replay_reproduces_episode():
    # aceitação da SPEC §4 fatia 2: episódio com snapshot == episódio
    # da view, bit a bit (state_dict completo), clássico e vivo
    for kw in ({}, {"market_v2": True, "country_v2": True,
                    "equip_v2": True}):
        a = Engine(seed=42, n_companies=8, world_data=False,
                   policy=_SnapshotPolicy(), **kw)
        b = Engine(seed=42, n_companies=8, world_data=False, **kw)
        a.run(36)
        b.run(36)
        assert a.state_dict() == b.state_dict()


# --------------------------------------------------------------------- #
# Fatia 2 — séries públicas do mercado vivo (SPEC §4)
# --------------------------------------------------------------------- #
def test_public_price_history_and_anchors():
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 market_v2=True)
    window = int(eng._mkt["model"].get("record_window_months", 24))
    eng.run(3)
    obs = _obs(eng)
    # a janela É o anel público do motor, nem mais nem menos
    for c in chain.COMMODITIES:
        assert list(obs.world.price_history[c]) == eng._price_ring[c]
        assert len(obs.world.price_history[c]) == 3
    assert dict(obs.world.anchors) == eng.anchors
    eng.run(30)
    obs = _obs(eng)
    snap = obs.to_snapshot()
    for c in chain.COMMODITIES:
        hist = obs.world.price_history[c]
        assert list(hist) == eng._price_ring[c]
        assert len(hist) == window          # o anel é limitado
        assert snap["world"]["price_history"][c] == list(hist)
        assert all(isinstance(v, float) for v in hist)
    assert snap["world"]["anchors"] == dict(eng.anchors)
    # a janela é cópia: o mundo andar não reescreve a view antiga
    first = obs.world.price_history["copper"][0]
    eng.run(2)
    assert obs.world.price_history["copper"][0] == first


def test_market_series_empty_without_market_v2():
    eng = Engine(seed=42, n_companies=8, world_data=False)
    eng.run(6)
    obs = _obs(eng)
    assert dict(obs.world.anchors) == {}
    assert dict(obs.world.price_history) == {}
    snap = obs.to_snapshot()
    assert snap["world"]["anchors"] == {}
    assert snap["world"]["price_history"] == {}


# --------------------------------------------------------------------- #
# Fatia 4 — a superfície v1 do Engine aposentada
# --------------------------------------------------------------------- #
def test_engine_legacy_facades_retired():
    """As fachadas de fase da era v1 (_pick_deposit/_build_downstream/
    _plan_buys/_buffer/_plan_sells) tinham zero chamadores no repo —
    as fases vivem na política e quem as orquestra é o decide — e
    foram removidas do Engine. Permanecem a entrada da decisão
    (_decide, chamada pelo passo do motor) e as exceções registradas
    no OBSERVATION-LOG (_reserve/_use_tools, superfície de fase que
    os testes de equipamentos/ferramentas exercitam direto)."""
    for name in ("_pick_deposit", "_build_downstream", "_plan_buys",
                 "_buffer", "_plan_sells"):
        assert not hasattr(Engine, name), name
    for name in ("_decide", "_reserve", "_use_tools"):
        assert hasattr(Engine, name), name
