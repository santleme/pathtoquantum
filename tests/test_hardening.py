"""Testes do endurecimento do motor (arquitetura):

- políticas plugáveis: trocar a Policy não toca o motor;
- event-sourcing: replay da crônica reconstrói placar e donos;
- snapshot/restore: retomar do meio produz resultado idêntico.

Fixtures minúsculas, como no restante da suíte — a corrida de verdade
roda no Kaggle.
"""
import json

import pytest

from mundo.chronicle import replay
from mundo.engine import Engine, HeuristicPolicy, Policy


class NullPolicy(Policy):
    """Política que nunca age: nenhuma empresa constrói nem vende."""

    def decide(self, obs):
        pass


class RecordingPolicy(HeuristicPolicy):
    """Heurística com contador de chamadas — prova o encaixe da troca."""

    def __init__(self):
        self.calls = 0

    def decide(self, obs):
        self.calls += 1
        super().decide(obs)


def test_policy_swap_keeps_engine_intact():
    eng = Engine(seed=7, n_companies=8, policy=NullPolicy())
    res = eng.run(12)
    # sem decisões: ninguém gasta, constrói ou vende — caixa intacto
    assert all(row["stage"] == 0 and row["facilities"] == 0
               for row in res["scoreboard"])
    total = sum(c.cash for c in eng.companies)
    assert total == eng.initial_cash
    assert eng.money_in == 0.0 and eng.money_out == 0.0


def test_wrapped_policy_matches_default():
    rec = RecordingPolicy()
    eng = Engine(seed=7, n_companies=8, policy=rec)
    res = eng.run(24)
    ref = Engine(seed=7, n_companies=8).run(24)
    assert rec.calls > 0
    assert res["scoreboard"] == ref["scoreboard"]
    assert res["chronicle"] == ref["chronicle"]


def test_default_policy_is_heuristic():
    assert isinstance(Engine(seed=1).policy, HeuristicPolicy)


def assert_replay_matches(eng, res):
    """O replay da crônica precisa reproduzir o placar e os donos vivos."""
    proj = replay(eng.chronicle.to_json())
    got = {r["name"]: r for r in proj["scoreboard"]}
    assert set(got) == {r["name"] for r in res["scoreboard"]}
    for row in res["scoreboard"]:
        p = got[row["name"]]
        assert p["alive"] == row["alive"]
        assert p["stage"] == row["stage"]
        assert p["facilities"] == row["facilities"]
        assert p["cash"] == pytest.approx(row["cash"], abs=1e-3)
    owners = {fac["id"]: comp.name
              for comp in eng.companies for fac in comp.facilities.values()}
    assert proj["facility_owners"] == owners


def test_replay_reconstructs_scoreboard_smoke():
    eng = Engine(seed=7, n_companies=8)
    res = eng.run(24)
    assert_replay_matches(eng, res)


def test_replay_with_god_events_and_discovery():
    ev = [{"tick": 3, "type": "price_shock", "commodity": "lithium",
           "factor": 1.5, "duration": 4},
          {"tick": 6, "type": "discovery", "name": "Sal de Outro",
           "resource": "lithium_ore", "lat": -25.0, "lon": -67.0,
           "size_t": 700000, "grade": 0.7},
          {"tick": 9, "type": "sanction", "resource": "copper_ore",
           "duration": 5}]
    eng = Engine(seed=11, n_companies=8, god_events=ev)
    res = eng.run(36)
    assert_replay_matches(eng, res)


class SuicidalPolicy(HeuristicPolicy):
    """Quebra a primeira empresa com instalações — gastando pelo
    verbo spend da Observation (o _spend do motor), ou seja, a
    falência nasce DENTRO do log de eventos (nada de mutar estado
    por fora: o replay precisa enxergar tudo)."""

    def __init__(self):
        self.target = None

    def decide(self, obs):
        super().decide(obs)
        if self.target is None and obs.world.tick >= 10 \
                and obs.me.facilities:
            self.target = obs.me.name
        if obs.me.name == self.target and obs.me.alive:
            obs.act.spend(obs.me.cash + 1_000_000.0, reason="test")


def test_replay_after_bankruptcy_and_acquisition():
    eng = Engine(seed=7, n_companies=8, policy=SuicidalPolicy())
    res = eng.run(18)
    kinds = [e["kind"] for e in eng.chronicle.to_json()]
    assert "bankruptcy" in kinds
    assert "acquisition" in kinds
    assert_replay_matches(eng, res)


def test_snapshot_restore_mid_run_identical():
    eng = Engine(seed=7, n_companies=8)
    for _ in range(12):
        eng.step()
    # round-trip por JSON puro: prova que o estado é serializável de verdade
    state = json.loads(json.dumps(eng.state_dict()))
    resumed = Engine.from_state(state).run(12)
    ref = Engine(seed=7, n_companies=8).run(24)
    assert resumed["scoreboard"] == ref["scoreboard"]
    assert resumed["frames"] == ref["frames"]
    assert resumed["chronicle"] == ref["chronicle"]


def test_engine_prefers_realdata_with_fallback():
    from mundo import realdata
    from mundo.world import DEPOSITS
    eng = Engine(seed=7, n_companies=8)              # padrão: dataset real
    assert eng.world_source == "realdata"
    adapted = {d.name: d for d in
               realdata.to_world_deposits(realdata.load_world_data())}
    for d in eng.deposits:
        assert d.size_t == adapted[d.name].size_t
        assert d.grade == adapted[d.name].grade
    off = Engine(seed=7, n_companies=8, world_data=False)
    assert off.world_source == "builtin"
    assert {d.name: d.size_t for d in off.deposits} == \
        {d.name: d.size_t for d in DEPOSITS}


def test_fallback_preserves_v0_baseline():
    # com world_data=False o mundo é bit-idêntico ao v0 original
    # (sha256 do placar do smoke seed 7/24 ticks, calculado na baseline)
    import hashlib
    eng = Engine(seed=7, n_companies=8, world_data=False)
    res = eng.run(24)
    digest = hashlib.sha256(json.dumps(
        res["scoreboard"], sort_keys=True, ensure_ascii=False,
        default=str).encode()).hexdigest()[:16]
    assert digest == "018ae10a9d47584a"


def test_snapshot_restore_with_realdata():
    eng = Engine(seed=7, n_companies=8)              # fonte realdata
    for _ in range(12):
        eng.step()
    state = json.loads(json.dumps(eng.state_dict()))
    resumed = Engine.from_state(state).run(12)
    ref = Engine(seed=7, n_companies=8).run(24)
    assert resumed["scoreboard"] == ref["scoreboard"]
    assert resumed["frames"] == ref["frames"]
    assert resumed["chronicle"] == ref["chronicle"]


def test_snapshot_restore_with_god_events():
    ev = [{"tick": 15, "type": "price_shock", "commodity": "copper",
           "factor": 0.6, "duration": 5},
          {"tick": 20, "type": "discovery", "name": "Sal Tardio",
           "resource": "lithium_ore", "lat": -26.0, "lon": -68.0,
           "size_t": 600000, "grade": 0.66}]
    eng = Engine(seed=11, n_companies=8, god_events=ev)
    for _ in range(18):
        eng.step()
    state = json.loads(json.dumps(eng.state_dict()))
    resumed = Engine.from_state(state).run(18)
    ref = Engine(seed=11, n_companies=8, god_events=ev).run(36)
    assert resumed["scoreboard"] == ref["scoreboard"]
    assert resumed["frames"] == ref["frames"]
    assert resumed["chronicle"] == ref["chronicle"]
