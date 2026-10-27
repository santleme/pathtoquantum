"""Testes da fatia 3 — Intentions declarativas (SPEC §4).

O contrato novo: ``decide(obs)`` devolve a lista ordenada de
intenções (dados puros, serializáveis); o motor valida a lista
inteira ANTES de executar qualquer uma (atomicidade por decisão)
e executa em ordem pelos verbos do Actuator. Aqui se prova:

- o vocabulário inteiro serializa em JSON e volta idêntico;
- a sombra (``Plan``) calcula o mesmo elo que ``Company``;
- um episódio cujas decisões atravessam JSON (serializa →
  desserializa → devolve) é bit-idêntico ao episódio direto,
  no clássico e no mundo vivo completo — replay de decisões;
- intenção inválida/maliciosa é rejeitada com ``IntentionError``
  e o mundo fica intacto (inclusive com uma válida antes dela);
- o ``obs.act`` da decisão é um selo, e a guarda da forja rejeita
  programa que o toca; programa legado (sem retorno) é rejeitado
  pelo motor com a explicação do contrato.
"""
import itertools
import json
from types import SimpleNamespace

import pytest

from mundo.companies import Company
from mundo.engine import Engine, HeuristicPolicy, Policy
from mundo.intentions import (INTENTION_TYPES, BuildFacility, Buy,
                              IntentionError, MaintainFacility,
                              Narrate, Narration, NoteLink, Offer,
                              OverhaulFacility, Plan, Probe,
                              RegisterClaim, RepairFacility, SetTool,
                              Spend, intention_from_dict,
                              intention_to_dict, intentions_from_dicts,
                              intentions_to_dicts)
from mundo.program import ProgramRejected, load_program_policy


class FixedPolicy(Policy):
    """Devolve sempre a mesma lista de intenções (a decisão fixa)."""

    def __init__(self, intentions):
        self.intentions = intentions

    def decide(self, obs):
        return list(self.intentions)


# --------------------------------------------------------------------- #
# Vocabulário e serialização
# --------------------------------------------------------------------- #
def _one_of_each():
    rich = Narration("probe", "achou um depósito RICO.")
    poor = Narration("probe", "teor decepcionante.")
    build_narration = Narration.of(
        "mine", "abre sua mina.", cid=3, facility_kind="mine",
        cell=[13, 5], deposit="Salar de Atacama")
    return [
        Spend(1_000.0, reason="claim"),
        Spend(2_000.0),
        Probe("Salar de Atacama", on_rich=rich, on_poor=poor),
        Probe("Carajás"),
        RegisterClaim((13, 5)),
        BuildFacility("mine", (13, 5), deposit="Salar de Atacama",
                      narration=build_narration),
        BuildFacility("refinery", (10, 10)),
        Narrate(Narration.of("tool", "campanha.", valor=1.5)),
        NoteLink(1),
        RepairFacility("f0-1"),
        MaintainFacility("f0-2"),
        OverhaulFacility("f0-3"),
        Buy("copper", 6.0),
        Offer("device", 12.5),
        SetTool("insta", until=30, strength=1.0),
        SetTool("zap", until=12),
    ]


def test_vocabulary_roundtrips_through_json():
    intentions = _one_of_each()
    assert {type(i) for i in intentions} == set(INTENTION_TYPES)
    blob = json.dumps(intentions_to_dicts(intentions))
    back = intentions_from_dicts(json.loads(blob))
    assert back == intentions
    # e um a um, pela API singular
    for it in intentions:
        assert intention_from_dict(
            json.loads(json.dumps(intention_to_dict(it)))) == it


def test_plan_chain_stage_matches_company():
    """A tabela de elos da sombra é a de Company.chain_stage — para
    TODO subconjunto de tipos de instalação."""
    kinds = ["mine", "refinery", "factory", "plant", "assembly"]
    comp = Company(cid=0, name="X", archetype="a", traits={},
                   hq_city="São Paulo", color="#000", cash=0.0)
    for r in range(len(kinds) + 1):
        for subset in itertools.combinations(kinds, r):
            comp._kinds = set(subset)
            plan = Plan(cash=0.0, kinds=set(subset))
            assert plan.chain_stage() == comp.chain_stage(), subset
            assert plan.has("mine") == ("mine" in subset)


# --------------------------------------------------------------------- #
# Replay de decisões: JSON no meio do caminho não muda um bit
# --------------------------------------------------------------------- #
class JsonRoundTripPolicy(HeuristicPolicy):
    """A heurística com cada decisão atravessando JSON: serializa a
    lista declarada, desserializa e devolve a cópia — se a decisão
    como DADO não fosse completa e fiel, o episódio divergiria."""

    def decide(self, obs):
        blob = json.dumps(intentions_to_dicts(super().decide(obs)))
        return intentions_from_dicts(json.loads(blob))


def _episode_hash(policy, **kw):
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=policy, **kw)
    eng.run(36)
    return json.dumps(eng.state_dict(), sort_keys=True,
                      ensure_ascii=False, default=str)


def test_decision_replay_through_json_is_bit_identical():
    for kw in ({}, {"market_v2": True, "country_v2": True,
                    "equip_v2": True}):
        direct = _episode_hash(HeuristicPolicy(), **kw)
        replayed = _episode_hash(JsonRoundTripPolicy(), **kw)
        assert replayed == direct


# --------------------------------------------------------------------- #
# Execução: o Probe declarativo revela, cobra e narra como o verbo
# --------------------------------------------------------------------- #
def test_probe_intention_reveals_charges_and_narrates():
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=FixedPolicy([]))
    comp = eng.companies[0]
    from mundo import chain
    rich = Narration("probe", "RICO.")
    poor = Narration("probe", "POBRE.")
    cash0 = comp.cash
    eng.policy = FixedPolicy([Probe("Salar de Atacama",
                                    on_rich=rich, on_poor=poor)])
    eng._decide(comp)
    # teor 0,85 do mundo builtin: knowledge registrado, custo pago,
    # narração RICA na crônica (a pobre, não)
    dep = next(d for d in eng.deposits if d.name == "Salar de Atacama")
    assert comp.knowledge["Salar de Atacama"] == (dep.grade, dep.size_t)
    assert comp.cash == cash0 - chain.PROBE_COST
    texts = [e.text for e in eng.chronicle.events]
    assert "RICO." in texts and "POBRE." not in texts
    # com limiares deslocados, o mesmo teor seleciona a narração pobre
    eng2 = Engine(seed=42, n_companies=8, world_data=False,
                  policy=FixedPolicy([Probe(
                      "Salar de Atacama", on_rich=rich, on_poor=poor,
                      rich_threshold=0.99, poor_threshold=0.90)]))
    eng2._decide(eng2.companies[0])
    texts2 = [e.text for e in eng2.chronicle.events]
    assert "POBRE." in texts2 and "RICO." not in texts2


# --------------------------------------------------------------------- #
# Validação: intenção inválida/maliciosa não toca o mundo
# --------------------------------------------------------------------- #
def _footprint(eng, comp):
    return {
        "cash": comp.cash, "stocks": dict(comp.stocks),
        "facilities": sorted(comp.facilities),
        "knowledge": dict(comp.knowledge),
        "claimed": set(comp.claimed),
        "claimed_by": dict(eng.claimed_by),
        "chronicle": len(eng.chronicle.events),
        "tools": (comp.tools.insta_until, comp.tools.zap_until,
                  comp.tools.vid_until, comp.tools.loja_until),
        "buys": dict(getattr(comp, "_buys", {})),
        "offers": dict(getattr(comp, "_offers", {})),
    }


def _assert_rejected_without_effect(eng, comp, intentions):
    before = _footprint(eng, comp)
    eng.policy = FixedPolicy(intentions)
    with pytest.raises(IntentionError):
        eng._decide(comp)
    assert _footprint(eng, comp) == before


def test_invalid_intentions_are_rejected_atomically():
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=FixedPolicy([]))
    comp = eng.companies[0]
    cases = [
        [Spend(-1.0)],                                  # gasto negativo
        [Spend(float("inf"))],                          # gasto infinito
        [Buy("unobtanium", 1.0)],                       # commodity fora
        [Offer("copper", -2.0)],                        # quantidade < 0
        [Probe("Depósito Fantasma")],                   # depósito fora
        [RepairFacility("f7-99")],                      # instalação alheia
        [NoteLink(9)],                                  # elo inexistente
        [SetTool("tiktok", until=10)],                  # ferramenta fora
        [BuildFacility("mine", (13, 5), deposit="Carajás")],  # célula ≠ depósito
        [RegisterClaim((0, 0))],                        # célula sem depósito
        # atômicas: uma VÁLIDA antes da inválida — nada executa
        [Spend(1_000.0, reason="test"), Buy("unobtanium", 1.0)],
        [Buy("copper", 1.0), Spend(-5.0)],
    ]
    for intentions in cases:
        _assert_rejected_without_effect(eng, comp, intentions)


def test_forged_objects_are_not_intentions():
    """Objeto com os campos certos mas sem ser a dataclass — e um
    impostor com campo privado — não é intenção: rejeitado."""
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=FixedPolicy([]))
    comp = eng.companies[0]
    fake_spend = SimpleNamespace(amount=10.0, reason="claim")
    _assert_rejected_without_effect(eng, comp, [fake_spend])
    # campo privado/desconhecido nem CONSTRÓI: a dataclass congelada
    # só aceita o vocabulário declarado
    with pytest.raises(TypeError):
        Spend(10.0, reason="claim", _engine=eng)
    with pytest.raises(TypeError):
        Buy("copper", 1.0, target_cid=7)
    fake_narration = Narrate(SimpleNamespace(
        kind="probe", text="x", extra=()))
    _assert_rejected_without_effect(eng, comp, [fake_narration])


def test_claim_and_repair_cannot_target_rivals():
    # empresa 0 reivindica a célula e constrói; a empresa 1 tenta
    # reivindicar a MESMA célula e reparar a instalação DELA
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=FixedPolicy([]))
    c0, c1 = eng.companies[0], eng.companies[1]
    dep = eng.deposits[0]
    eng.policy = FixedPolicy([
        RegisterClaim(dep.cell),
        BuildFacility("mine", dep.cell, deposit=dep.name)])
    eng._decide(c0)
    assert eng.claimed_by[dep.cell] == c0.cid
    fid_rival = next(iter(c0.facilities))
    _assert_rejected_without_effect(eng, c1, [RegisterClaim(dep.cell)])
    _assert_rejected_without_effect(eng, c1, [RepairFacility(fid_rival)])
    _assert_rejected_without_effect(eng, c1,
                                    [MaintainFacility(fid_rival)])


def test_legacy_decision_without_return_is_rejected_clearly():
    class LegacyPolicy(Policy):
        def decide(self, obs):
            pass                                    # contrato velho

    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=LegacyPolicy())
    with pytest.raises(IntentionError, match="lista de intenções"):
        eng._decide(eng.companies[0])


# --------------------------------------------------------------------- #
# O selo do act e a guarda da forja no contrato novo
# --------------------------------------------------------------------- #
def test_act_is_sealed_during_decision():
    class VerbPolicy(Policy):
        def decide(self, obs):
            obs.act.spend(1.0, reason="test")       # verbo na decisão
            return []

    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=VerbPolicy())
    with pytest.raises(RuntimeError, match="contrato declarativo"):
        eng._decide(eng.companies[0])


def test_guard_rejects_program_touching_act(tmp_path):
    p = tmp_path / "verbs.py"
    p.write_text(
        "from mundo.engine import HeuristicPolicy\n"
        "class EvolvedPolicy(HeuristicPolicy):\n"
        "    def decide(self, obs):\n"
        "        obs.act.spend(1.0)\n"
        "        return []\n")
    with pytest.raises(ProgramRejected) as excinfo:
        load_program_policy(p)
    assert any(".act" in v for v in excinfo.value.violations)


def test_program_can_declare_intentions(tmp_path):
    """O caminho legal do programa no contrato novo: importar
    mundo.intentions, declarar e devolver — carrega e roda."""
    p = tmp_path / "declarative.py"
    p.write_text(
        "from mundo.engine import HeuristicPolicy\n"
        "from mundo.intentions import Buy, Spend\n"
        "class EvolvedPolicy(HeuristicPolicy):\n"
        "    def decide(self, obs):\n"
        "        return [Spend(10.0, reason='test'),\n"
        "                Buy('copper', 1.0)]\n")
    policy = load_program_policy(p)
    eng = Engine(seed=42, n_companies=8, world_data=False,
                 policy=policy)
    comp = eng.companies[0]
    cash0 = comp.cash
    eng._decide(comp)
    assert comp.cash == cash0 - 10.0
    assert comp._buys == {"copper": 1.0}
