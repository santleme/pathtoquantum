"""Intentions declarativas — o retorno do ``decide`` (fatia 3).

docs/OBSERVATION-SPEC.md §4, fatia 3; o esboço é o do SDD §6.2.
Até a fatia 2 a política EXECUTAVA verbos durante a decisão
(``obs.act.*``): o efeito colateral acontecia dentro do ``decide``,
na ordem em que o código os chamava. Na fatia 3 a decisão vira
DADO: ``decide(obs)`` devolve uma lista ordenada de intenções —
dataclasses congeladas, serializáveis em JSON — e o MOTOR valida a
lista inteira e a executa em ordem, pelos mesmos verbos do
``Actuator``. A política não tem mais como causar efeito fora da
lista declarada (na observação de decisão o ``act`` é um selo que
levanta erro; em programas da forja a guarda bane ``.act`` no
fonte).

O vocabulário é o espelho 1:1 dos verbos do ``Actuator`` — o
inventário completo está na SPEC §4 (fatia 3). Os dois verbos que
devolviam valor no meio da decisão viram dado:

- ``probe`` devolvia ``(grade, size)`` e a política narrava
  conforme o teor: a intenção ``Probe`` carrega as duas narrações
  candidatas (``on_rich``/``on_poor``) e os limiares; o executor
  narra a selecionada pelo teor revelado, na mesma posição da
  sequência (gasto → knowledge → narração). Nenhuma decisão
  estrutural da heurística depende do par no mesmo tick —
  reivindicar é o ramo de conhecimento PRÉVIO.
- ``build_facility`` devolvia a view para a narração usar o ``fid``
  recém-criado: a intenção ``BuildFacility`` carrega a narração
  anexa SEM o ``fid``; o executor o injeta ao narrar.

``Plan`` é a sombra de planejamento que mantém a equivalência bit
a bit: na era imperativa a política relia o mundo depois de agir
dentro da mesma decisão (caixa após cada gasto, ``has()`` e
``chain_stage()`` depois de construir). As fases planejam contra a
sombra — caixa e tipos de instalação como ficarão depois que as
intenções já declaradas executarem — e os testes de limiar leem a
sombra, na mesma ordem em que o mundo os veria.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .observation import _jsonify

# A tabela de estágios da cadeia — a MESMA de Company.chain_stage
# (companies.py); tests/test_intentions.py prova as duas iguais
# para todo subconjunto de tipos de instalação.
_STAGE_KINDS = [(5, "assembly"), (4, "plant"), (3, "factory"),
                (2, "refinery"), (1, "mine")]


class IntentionError(ValueError):
    """Uma decisão devolveu intenções inválidas: a lista inteira é
    rejeitada ANTES de qualquer execução (atomicidade por decisão)
    e o mundo fica intacto. Herda de ValueError — é a rejeição
    clara do contrato declarativo (programa legado que devolve
    None cai aqui, com a explicação)."""


# --------------------------------------------------------------------- #
# A narração como dado
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class Narration:
    """Uma entrada de crônica declarada: tipo, texto e o ``extra``
    (pares nome→valor JSON) que acompanha o evento. Quem nasce de
    uma construção recebe o ``fid`` do executor — a política não o
    conhece ao declarar."""

    kind: str
    text: str
    extra: tuple = ()

    @staticmethod
    def of(kind: str, text: str, **extra) -> "Narration":
        return Narration(kind, text, tuple(sorted(extra.items())))

    def extra_dict(self) -> dict:
        return dict(self.extra)


# --------------------------------------------------------------------- #
# O vocabulário de intenções (espelho 1:1 do Actuator)
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class Spend:
    """Gasto nomeado da focal (``act.spend``)."""
    amount: float
    reason: str = "spend"


@dataclass(frozen=True)
class Probe:
    """Sondagem (``act.probe``): paga o custo, registra o achado no
    knowledge da focal e narra a candidata que o teor revelado
    selecionar — rica se ``grade >= rich_threshold``, pobre se
    ``grade <= poor_threshold`` (os limiares da heurística v0)."""
    deposit: str
    on_rich: Narration | None = None
    on_poor: Narration | None = None
    rich_threshold: float = 0.78
    poor_threshold: float = 0.35


@dataclass(frozen=True)
class RegisterClaim:
    """Reivindica a célula para a focal (``act.register_claim``)."""
    cell: tuple


@dataclass(frozen=True)
class BuildFacility:
    """Constrói uma instalação (``act.build_facility``). A
    ``narration`` anexa é narrada pelo executor logo após a
    construção, com o ``fid`` criado injetado no ``extra``."""
    kind: str
    cell: tuple
    deposit: str | None = None
    narration: Narration | None = None


@dataclass(frozen=True)
class Narrate:
    """Escreve na crônica como a focal (``act.narrate``)."""
    narration: Narration


@dataclass(frozen=True)
class NoteLink:
    """Registra marco de elo da cadeia (``act.note_link``)."""
    stage: int


@dataclass(frozen=True)
class RepairFacility:
    """Manda a instalação quebrada para a oficina (``act.repair``)."""
    facility_id: str


@dataclass(frozen=True)
class MaintainFacility:
    """Manutenção preventiva da instalação (``act.maintain``)."""
    facility_id: str


@dataclass(frozen=True)
class OverhaulFacility:
    """Overhaul da instalação (``act.overhaul``)."""
    facility_id: str


@dataclass(frozen=True)
class Buy:
    """Intenção de compra do tick (``act.buy``)."""
    commodity: str
    qty: float


@dataclass(frozen=True)
class Offer:
    """Intenção de venda do tick (``act.offer``)."""
    commodity: str
    qty: float


@dataclass(frozen=True)
class SetTool:
    """Liga uma ferramenta simulada (``act.set_tool``); só o
    InstaSim tem ``strength``."""
    tool: str
    until: int
    strength: float | None = None


Intention = (Spend | Probe | RegisterClaim | BuildFacility | Narrate
             | NoteLink | RepairFacility | MaintainFacility
             | OverhaulFacility | Buy | Offer | SetTool)

INTENTION_TYPES = (Spend, Probe, RegisterClaim, BuildFacility,
                   Narrate, NoteLink, RepairFacility, MaintainFacility,
                   OverhaulFacility, Buy, Offer, SetTool)


# --------------------------------------------------------------------- #
# Serialização (o espírito do _jsonify: JSON puro ou TypeError)
# --------------------------------------------------------------------- #
def _narration_to_dict(n: Narration | None):
    if n is None:
        return None
    return {"kind": n.kind, "text": n.text,
            "extra": _jsonify(dict(n.extra))}


def _narration_from_dict(d) -> Narration | None:
    if d is None:
        return None
    return Narration(d["kind"], d["text"],
                     tuple(sorted((k, v) for k, v in
                                   d.get("extra", {}).items())))


def intention_to_dict(it: Intention) -> dict:
    """A intenção como dict JSON puro, com a tag ``"type"``."""
    if isinstance(it, Spend):
        return {"type": "spend", "amount": it.amount,
                "reason": it.reason}
    if isinstance(it, Probe):
        return {"type": "probe", "deposit": it.deposit,
                "on_rich": _narration_to_dict(it.on_rich),
                "on_poor": _narration_to_dict(it.on_poor),
                "rich_threshold": it.rich_threshold,
                "poor_threshold": it.poor_threshold}
    if isinstance(it, RegisterClaim):
        return {"type": "register_claim", "cell": list(it.cell)}
    if isinstance(it, BuildFacility):
        return {"type": "build_facility", "kind": it.kind,
                "cell": list(it.cell), "deposit": it.deposit,
                "narration": _narration_to_dict(it.narration)}
    if isinstance(it, Narrate):
        return {"type": "narrate",
                "narration": _narration_to_dict(it.narration)}
    if isinstance(it, NoteLink):
        return {"type": "note_link", "stage": it.stage}
    if isinstance(it, RepairFacility):
        return {"type": "repair", "facility_id": it.facility_id}
    if isinstance(it, MaintainFacility):
        return {"type": "maintain", "facility_id": it.facility_id}
    if isinstance(it, OverhaulFacility):
        return {"type": "overhaul", "facility_id": it.facility_id}
    if isinstance(it, Buy):
        return {"type": "buy", "commodity": it.commodity,
                "qty": it.qty}
    if isinstance(it, Offer):
        return {"type": "offer", "commodity": it.commodity,
                "qty": it.qty}
    if isinstance(it, SetTool):
        return {"type": "set_tool", "tool": it.tool,
                "until": it.until, "strength": it.strength}
    raise TypeError(f"não é uma intenção: {type(it).__name__}")


def intention_from_dict(d: dict) -> Intention:
    """Reconstrói a intenção do dict de ``intention_to_dict``."""
    t = d.get("type")
    if t == "spend":
        return Spend(d["amount"], d.get("reason", "spend"))
    if t == "probe":
        return Probe(d["deposit"],
                     _narration_from_dict(d.get("on_rich")),
                     _narration_from_dict(d.get("on_poor")),
                     d.get("rich_threshold", 0.78),
                     d.get("poor_threshold", 0.35))
    if t == "register_claim":
        return RegisterClaim(tuple(d["cell"]))
    if t == "build_facility":
        return BuildFacility(d["kind"], tuple(d["cell"]),
                             d.get("deposit"),
                             _narration_from_dict(d.get("narration")))
    if t == "narrate":
        return Narrate(_narration_from_dict(d["narration"]))
    if t == "note_link":
        return NoteLink(d["stage"])
    if t == "repair":
        return RepairFacility(d["facility_id"])
    if t == "maintain":
        return MaintainFacility(d["facility_id"])
    if t == "overhaul":
        return OverhaulFacility(d["facility_id"])
    if t == "buy":
        return Buy(d["commodity"], d["qty"])
    if t == "offer":
        return Offer(d["commodity"], d["qty"])
    if t == "set_tool":
        return SetTool(d["tool"], d["until"], d.get("strength"))
    raise ValueError(f"tipo de intenção desconhecido: {t!r}")


def intentions_to_dicts(intentions) -> list:
    return [intention_to_dict(it) for it in intentions]


def intentions_from_dicts(dicts) -> list:
    return [intention_from_dict(d) for d in dicts]


# --------------------------------------------------------------------- #
# A sombra de planejamento
# --------------------------------------------------------------------- #
@dataclass
class Plan:
    """A sombra de UMA decisão: caixa e tipos de instalação como
    ficarão depois que as intenções já declaradas executarem.

    As fases da política testam seus limiares contra a sombra — é o
    que reproduz, no mundo declarativo, as releituras intra-decisão
    da era imperativa (caixa vivo depois de cada gasto, ``has()`` /
    ``chain_stage()`` depois de construir). Os custos abatidos em
    ``spend`` são os que o motor vai cobrar pela intenção
    correspondente, na mesma ordem de declaração."""

    cash: float
    kinds: set = field(default_factory=set)

    @staticmethod
    def of(me) -> "Plan":
        """A sombra inicial de uma decisão: o estado vivo da focal."""
        return Plan(cash=me.cash,
                    kinds={f.kind for f in me.facilities})

    def spend(self, amount: float) -> None:
        self.cash -= amount

    def build(self, kind: str) -> None:
        self.kinds.add(kind)

    def has(self, kind: str) -> bool:
        return kind in self.kinds

    def chain_stage(self) -> int:
        """O elo da cadeia sobre os tipos da sombra — a tabela de
        ``Company.chain_stage``, aplicada ao conjunto projetado."""
        for stage, kind in _STAGE_KINDS:
            if kind in self.kinds:
                return stage
        return 0
