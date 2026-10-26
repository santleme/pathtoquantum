"""Testes do endurecimento do motor (arquitetura):

- políticas plugáveis: trocar a Policy não toca o motor;
- event-sourcing: replay da crônica reconstrói placar e donos;
- snapshot/restore: retomar do meio produz resultado idêntico.

Fixtures minúsculas, como no restante da suíte — a corrida de verdade
roda no Kaggle.
"""
from mundo.engine import Engine, HeuristicPolicy, Policy


class NullPolicy(Policy):
    """Política que nunca age: nenhuma empresa constrói nem vende."""

    def decide(self, engine, comp):
        pass


class RecordingPolicy(HeuristicPolicy):
    """Heurística com contador de chamadas — prova o encaixe da troca."""

    def __init__(self):
        self.calls = 0

    def decide(self, engine, comp):
        self.calls += 1
        super().decide(engine, comp)


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
