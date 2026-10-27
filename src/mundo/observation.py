"""A camada de Observation (guarda v2) — docs/OBSERVATION-SPEC.md.

A política não recebe mais o motor: a cada decisão, o motor constrói
uma ``Observation`` — tudo que a empresa enxerga de si (``me``) e do
mundo público (``world``), os verbos legais de ação (``act``) e a
fachada de sorteio (``rng``). Fog-of-war vira tipo:

- ``DepositView`` NÃO tem ``grade``/``size_t`` — a verdade oculta de
  um depósito só chega à empresa pela sondagem (``act.probe``), que a
  registra no ``knowledge`` dela. Ler o teor sem sondar não é
  proibido: é impossível (o atributo não existe).
- Não há lista de empresas: estado de rival não faz parte da
  superfície. Eventos futuros (``god_events``, ``_force_events``)
  idem — insider trading não tem por onde entrar.
- As views são **vivas por baixo, congeladas por cima**: guardam a
  referência sob nome *name-mangled* e expõem só propriedades sem
  setter, então a política lê o valor vivo do motor (decisões que
  relêem caixa/estoque depois de agir dentro do mesmo tick seguem
  bit-idênticas às da era pré-Observation) mas não escreve através
  delas — escrita só pelos verbos do ``Actuator``, na mesma ordem
  de mutação de sempre. Onde nada muda durante uma decisão
  (depósitos, cidades, países, capex), a view é cópia de escalares.
- ``rng`` é fachada forward-only (``uniform``/``random``): o fluxo
  de aleatoriedade continua do motor; o objeto ``Random`` (com
  ``getstate``/``setstate``) nunca é entregue.
- Fatia 2: ``Observation.to_snapshot()`` fotografa a decisão em
  valores JSON puros (só ``me``/``world`` — ``act``/``rng`` são
  capacidades, não dados), sem tocar o mundo; e ``world`` expõe as
  séries públicas do mercado vivo (``anchors`` e ``price_history``,
  o anel público de preços). O regime do B1 continua só de Deus —
  decisão fundamentada na SPEC §4.

Este módulo é código DE CONFIANÇA do motor (como o próprio motor):
ele toca os objetos vivos para montar as views. Quem recebe as
views — a política — não toca em mais nada.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from . import chain
from .companies import Company, StockBook
from .tools_sim import ToolEffects
from .world import City, Deposit


class _View:
    """Base das views: só ``__slots__`` (sem ``__dict__``) e
    propriedades sem setter — atribuir através de uma view levanta
    ``AttributeError``."""

    __slots__ = ()


def _jsonify(value):
    """Converte um valor da superfície em JSON puro — só ``dict``,
    ``list``, ``str``, ``int``, ``float``, ``bool`` e ``None``,
    recursivamente (tuplas viram listas, mappings viram dicts).
    Qualquer outro tipo levanta ``TypeError``: o snapshot nunca
    carrega referência viva nem tipo exótico por acidente."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_jsonify(v) for v in sorted(value, key=repr)]
    raise TypeError(
        f"valor não serializável no snapshot: {type(value).__name__}")


# --------------------------------------------------------------------- #
# O mundo público
# --------------------------------------------------------------------- #
class DepositView(_View):
    """O depósito como o mundo o anuncia: nome, recurso, posição,
    país e dono do claim. SEM grade/size_t (a verdade oculta)."""

    __slots__ = ("_DepositView__name", "_DepositView__resource",
                 "_DepositView__lat", "_DepositView__lon",
                 "_DepositView__cell", "_DepositView__country",
                 "_DepositView__claimed_by")

    def __init__(self, dep: Deposit, country: str,
                 claimed_by: int | None):
        self.__name = dep.name
        self.__resource = dep.resource
        self.__lat = dep.lat
        self.__lon = dep.lon
        self.__cell = dep.cell
        self.__country = country
        self.__claimed_by = claimed_by

    @property
    def name(self) -> str:
        return self.__name

    @property
    def resource(self) -> str:
        return self.__resource

    @property
    def lat(self) -> float:
        return self.__lat

    @property
    def lon(self) -> float:
        return self.__lon

    @property
    def cell(self) -> tuple:
        return self.__cell

    @property
    def country(self) -> str:
        return self.__country

    @property
    def claimed_by(self) -> int | None:
        """cid de quem reivindicou a célula (mapa público), ou None."""
        return self.__claimed_by

    def to_snapshot(self) -> dict:
        return {"name": self.__name, "resource": self.__resource,
                "lat": self.__lat, "lon": self.__lon,
                "cell": list(self.__cell), "country": self.__country,
                "claimed_by": self.__claimed_by}

    def __repr__(self) -> str:
        return f"DepositView({self.__name!r})"


class CityView(_View):
    """Cidade pública: nome, posição, célula, país, peso de demanda."""

    __slots__ = ("_CityView__name", "_CityView__lat", "_CityView__lon",
                 "_CityView__cell", "_CityView__country",
                 "_CityView__demand_weight")

    def __init__(self, city: City, country: str):
        self.__name = city.name
        self.__lat = city.lat
        self.__lon = city.lon
        self.__cell = city.cell
        self.__country = country
        self.__demand_weight = city.demand_weight

    @property
    def name(self) -> str:
        return self.__name

    @property
    def lat(self) -> float:
        return self.__lat

    @property
    def lon(self) -> float:
        return self.__lon

    @property
    def cell(self) -> tuple:
        return self.__cell

    @property
    def country(self) -> str:
        return self.__country

    @property
    def demand_weight(self) -> float:
        return self.__demand_weight

    def to_snapshot(self) -> dict:
        return {"name": self.__name, "lat": self.__lat,
                "lon": self.__lon, "cell": list(self.__cell),
                "country": self.__country,
                "demand_weight": self.__demand_weight}

    def __repr__(self) -> str:
        return f"CityView({self.__name!r})"


class CountryView(_View):
    """Os índices PÚBLICOS de um país (B3): estabilidade, câmbio e
    royalties são publicados — as probabilidades dos eventos
    políticos, nunca (nem existem nesta superfície)."""

    __slots__ = ("_CountryView__name", "_CountryView__S",
                 "_CountryView__fx", "_CountryView__tau")

    def __init__(self, name: str, S: float, fx: float, tau: float):
        self.__name = name
        self.__S = S
        self.__fx = fx
        self.__tau = tau

    @property
    def name(self) -> str:
        return self.__name

    @property
    def S(self) -> float:
        return self.__S

    @property
    def fx(self) -> float:
        return self.__fx

    @property
    def tau(self) -> float:
        return self.__tau

    def to_snapshot(self) -> dict:
        return {"name": self.__name, "S": self.__S, "fx": self.__fx,
                "tau": self.__tau}

    def __repr__(self) -> str:
        return f"CountryView({self.__name!r})"


class WorldView(_View):
    """O mundo público no instante da decisão: tempo, regras (flags),
    preços, depósitos anunciados, cidades, países e o prêmio de
    capex por país (derivado público de ``S``, pré-computado).

    Séries públicas do mercado vivo (fatia 2, SPEC §4): com
    ``market_v2`` ligado, ``anchors`` (a âncora p* corrente por
    commodity — série pública por desenho, é o que os frames e o
    ``result()`` publicam) e ``price_history`` (o anel público de
    preços: os últimos preços publicados de cada commodity, do mais
    antigo ao mais novo — histórico de preço público é público).
    O REGIME fica fora de propósito: é estado que só Deus vê (as
    empresas o inferem do preço); ``cover``/EMA/ruído idem — são
    internos do modelo, e ``cover`` é agregado de estoques privados.
    Desligado o B1, as duas séries são mappings vazios."""

    __slots__ = ("_WorldView__tick", "_WorldView__market_v2",
                 "_WorldView__country_v2", "_WorldView__equip_v2",
                 "_WorldView__prices", "_WorldView__anchors",
                 "_WorldView__price_history", "_WorldView__deposits",
                 "_WorldView__cities", "_WorldView__countries",
                 "_WorldView__capex", "_WorldView__equip_policy",
                 "_WorldView__equip_model")

    def __init__(self, *, tick: int, market_v2: bool, country_v2: bool,
                 equip_v2: bool, prices, anchors, price_history,
                 deposits: tuple, cities: tuple, countries: tuple,
                 capex: dict, equip_policy, equip_model):
        self.__tick = tick
        self.__market_v2 = market_v2
        self.__country_v2 = country_v2
        self.__equip_v2 = equip_v2
        self.__prices = prices
        self.__anchors = anchors
        self.__price_history = price_history
        self.__deposits = deposits
        self.__cities = cities
        self.__countries = countries
        self.__capex = capex
        self.__equip_policy = equip_policy
        self.__equip_model = equip_model

    @property
    def tick(self) -> int:
        return self.__tick

    @property
    def market_v2(self) -> bool:
        return self.__market_v2

    @property
    def country_v2(self) -> bool:
        return self.__country_v2

    @property
    def equip_v2(self) -> bool:
        return self.__equip_v2

    @property
    def prices(self):
        """Preços públicos correntes (mapping somente-leitura, vivo)."""
        return self.__prices

    @property
    def anchors(self):
        """Âncora p* corrente por commodity (mapping somente-leitura,
        cópia do instante da decisão). Só com ``market_v2``; sem ele,
        mapping vazio — a âncora como série só existe no mercado
        vivo. A âncora é pública por desenho: é o preço de referência
        que o mundo anuncia (frames e ``result()`` a publicam)."""
        return self.__anchors

    @property
    def price_history(self):
        """Janela pública de preços por commodity: tupla de preços já
        publicados, do mais antigo ao mais novo (o anel público do
        motor, copiado no instante da decisão). Só com
        ``market_v2``; sem ele, mapping vazio."""
        return self.__price_history

    @property
    def deposits(self) -> tuple:
        return self.__deposits

    @property
    def cities(self) -> tuple:
        return self.__cities

    @property
    def countries(self) -> tuple:
        return self.__countries

    @property
    def equip_policy(self):
        """Parâmetros de decisão do B2 (equipdata) ou None."""
        return self.__equip_policy

    @property
    def equip_model(self):
        """Parâmetros do modelo físico do B2 (equipdata) ou None."""
        return self.__equip_model

    def capex_mult(self, country: str) -> float:
        """Prêmio de risco-país sobre capex naquele país (1,0 = sem
        prêmio; idêntico ao ``Engine.capex_mult`` no instante da
        construção — S não muda durante as decisões de um tick)."""
        return self.__capex.get(country, 1.0)

    def to_snapshot(self) -> dict:
        return {
            "tick": self.__tick,
            "market_v2": self.__market_v2,
            "country_v2": self.__country_v2,
            "equip_v2": self.__equip_v2,
            "prices": _jsonify(dict(self.__prices)),
            "anchors": _jsonify(dict(self.__anchors)),
            "price_history": _jsonify(dict(self.__price_history)),
            "deposits": [d.to_snapshot() for d in self.__deposits],
            "cities": [c.to_snapshot() for c in self.__cities],
            "countries": [c.to_snapshot() for c in self.__countries],
            "capex": _jsonify(dict(self.__capex)),
            "equip_policy": _jsonify(self.__equip_policy)
            if self.__equip_policy is not None else None,
            "equip_model": _jsonify(self.__equip_model)
            if self.__equip_model is not None else None,
        }


# --------------------------------------------------------------------- #
# A própria empresa
# --------------------------------------------------------------------- #
class StockView(_View):
    """Estoques da focal como mapping somente-leitura (por nome)."""

    __slots__ = ("_StockView__book",)

    def __init__(self, book: StockBook):
        self.__book = book

    def __getitem__(self, name: str) -> float:
        return self.__book[name]

    def __iter__(self):
        return iter(self.__book)

    def __len__(self) -> int:
        return len(self.__book)

    def __contains__(self, name: str) -> bool:
        return name in self.__book

    def get(self, name: str, default=None):
        try:
            return self.__book[name]
        except KeyError:
            return default

    def keys(self):
        return iter(self.__book)

    def items(self):
        return dict(self.__book).items()

    def values(self):
        return dict(self.__book).values()

    def __repr__(self) -> str:
        return f"StockView({dict(self.__book)!r})"


class KnowledgeView(_View):
    """O conhecimento sondado da focal: nome -> (grade, size_t).
    Somente-leitura — quem escreve é ``Actuator.probe``."""

    __slots__ = ("_KnowledgeView__data",)

    def __init__(self, data: dict):
        self.__data = data

    def __getitem__(self, name: str):
        return self.__data[name]

    def __iter__(self):
        return iter(self.__data)

    def __len__(self) -> int:
        return len(self.__data)

    def __contains__(self, name: str) -> bool:
        return name in self.__data

    def get(self, name: str, default=None):
        return self.__data.get(name, default)

    def keys(self):
        return self.__data.keys()

    def items(self):
        return self.__data.items()

    def values(self):
        return self.__data.values()

    def __repr__(self) -> str:
        return f"KnowledgeView({self.__data!r})"


class ClaimedView(_View):
    """As células reivindicadas pela focal (conjunto só de leitura)."""

    __slots__ = ("_ClaimedView__cells",)

    def __init__(self, cells: set):
        self.__cells = cells

    def __contains__(self, cell) -> bool:
        return cell in self.__cells

    def __iter__(self):
        return iter(self.__cells)

    def __len__(self) -> int:
        return len(self.__cells)

    def __repr__(self) -> str:
        return f"ClaimedView({sorted(self.__cells)!r})"


class ToolsView(_View):
    """Ferramentas simuladas da focal: janelas ativas e leitura dos
    campos; quem liga/desliga é ``Actuator.set_tool``."""

    __slots__ = ("_ToolsView__tools",)

    def __init__(self, tools: ToolEffects):
        self.__tools = tools

    @property
    def insta_until(self) -> int:
        return self.__tools.insta_until

    @property
    def insta_strength(self) -> float:
        return self.__tools.insta_strength

    @property
    def zap_until(self) -> int:
        return self.__tools.zap_until

    @property
    def vid_until(self) -> int:
        return self.__tools.vid_until

    @property
    def loja_until(self) -> int:
        return self.__tools.loja_until

    def insta_active(self, tick: int) -> bool:
        return self.__tools.insta_active(tick)

    def zap_active(self, tick: int) -> bool:
        return self.__tools.zap_active(tick)

    def vid_active(self, tick: int) -> bool:
        return self.__tools.vid_active(tick)

    def loja_active(self, tick: int) -> bool:
        return self.__tools.loja_active(tick)


class EquipView(_View):
    """Estado B2 de UMA instalação da focal (idade, condição, quebra,
    oficina, custo de reparo) — a observação legal das próprias
    instalações. Os valores são os vivos do dict de equipamento."""

    __slots__ = ("_EquipView__eq",)

    def __init__(self, eq: dict):
        self.__eq = eq

    @property
    def age(self) -> int:
        return self.__eq["age"]

    @property
    def cond(self) -> float:
        return self.__eq["cond"]

    @property
    def broken(self) -> bool:
        return self.__eq["broken"]

    @property
    def down_until(self) -> int:
        return self.__eq["down_until"]

    @property
    def repair_cost(self) -> float:
        return self.__eq["repair_cost"]

    @property
    def repair_ticks(self) -> int:
        return self.__eq["repair_ticks"]


class FacilityView(_View):
    """Uma instalação da focal: id, tipo, célula e depósito associado.
    ``equip`` é preguiçoso de propósito — materializa o estado B2 na
    primeira leitura, na mesma ordem em que a política sempre o leu
    (com equip_v2 desligado, nunca é tocado)."""

    __slots__ = ("_FacilityView__fac", "_FacilityView__engine")

    def __init__(self, fac: dict, engine):
        self.__fac = fac
        self.__engine = engine

    @property
    def id(self) -> str:
        return self.__fac["id"]

    @property
    def kind(self) -> str:
        return self.__fac["kind"]

    @property
    def cell(self) -> tuple:
        return self.__fac["cell"]

    @property
    def deposit(self) -> str | None:
        return self.__fac.get("deposit")

    @property
    def equip(self) -> EquipView:
        return EquipView(self.__engine._fac_equip(self.__fac))

    def _equip_values(self) -> dict:
        """Os valores de ``equip`` para o snapshot, SEM materializar
        o dict preguiçoso da instalação: se ele ainda não existe,
        devolve os valores canônicos que a primeira leitura criaria
        (os mesmos de ``Engine._fac_equip``) — fotografar não pode
        escrever no mundo."""
        eq = self.__fac.get("equip")
        if eq is None:
            return {"age": 0, "cond": 1.0, "broken": False,
                    "down_until": -1, "repair_cost": 0.0,
                    "repair_ticks": 0}
        return {k: eq[k] for k in ("age", "cond", "broken",
                                   "down_until", "repair_cost",
                                   "repair_ticks")}

    def to_snapshot(self, with_equip: bool) -> dict:
        return {"id": self.id, "kind": self.kind,
                "cell": list(self.cell), "deposit": self.deposit,
                "equip": self._equip_values() if with_equip else None}

    def __repr__(self) -> str:
        return f"FacilityView({self.__fac['id']!r}, {self.__fac['kind']!r})"


class CompanyView(_View):
    """A empresa focal por dentro — só o dela, só leitura. ``cash``,
    ``stocks``, ``knowledge`` etc. leem o estado vivo (a decisão pode
    agir pelo Actuator e reler em seguida, como sempre fez); nada
    aqui escreve."""

    __slots__ = ("_CompanyView__comp", "_CompanyView__hq",
                 "_CompanyView__traits", "_CompanyView__stocks",
                 "_CompanyView__knowledge", "_CompanyView__claimed",
                 "_CompanyView__tools", "_CompanyView__facilities")

    def __init__(self, comp: Company, engine, hq: CityView):
        self.__comp = comp
        self.__hq = hq
        self.__traits = MappingProxyType(comp.traits)
        self.__stocks = StockView(comp.stocks)
        self.__knowledge = KnowledgeView(comp.knowledge)
        self.__claimed = ClaimedView(comp.claimed)
        self.__tools = ToolsView(comp.tools)
        self.__facilities = tuple(
            FacilityView(f, engine) for f in comp.facilities.values())

    @property
    def cid(self) -> int:
        return self.__comp.cid

    @property
    def name(self) -> str:
        return self.__comp.name

    @property
    def archetype(self) -> str:
        return self.__comp.archetype

    @property
    def hq_city(self) -> str:
        return self.__comp.hq_city

    @property
    def hq(self) -> CityView:
        """A cidade-sede como view pública (posição/célula/país)."""
        return self.__hq

    @property
    def color(self) -> str:
        return self.__comp.color

    @property
    def alive(self) -> bool:
        return self.__comp.alive

    @property
    def founded_tick(self) -> int:
        return self.__comp.founded_tick

    @property
    def cash(self) -> float:
        """Caixa vivo da focal (muda com os próprios gastos do tick)."""
        return self.__comp.cash

    @property
    def traits(self):
        return self.__traits

    @property
    def stocks(self) -> StockView:
        return self.__stocks

    @property
    def knowledge(self) -> KnowledgeView:
        return self.__knowledge

    @property
    def claimed(self) -> ClaimedView:
        return self.__claimed

    @property
    def tools(self) -> ToolsView:
        return self.__tools

    @property
    def facilities(self) -> tuple:
        """Instalações da focal na ordem de construção (snapshot da
        lista na construção da Observation; cada view é viva)."""
        return self.__facilities

    def has(self, kind: str) -> bool:
        return self.__comp.has(kind)

    def chain_stage(self) -> int:
        return self.__comp.chain_stage()

    def to_snapshot(self, with_equip: bool) -> dict:
        tools = self.__tools
        return {
            "cid": self.cid, "name": self.name,
            "archetype": self.archetype, "hq_city": self.hq_city,
            "color": self.color, "alive": self.alive,
            "founded_tick": self.founded_tick,
            "cash": self.cash,
            "traits": _jsonify(self.__traits),
            "stocks": _jsonify(dict(self.__stocks.items())),
            "knowledge": _jsonify(dict(self.__knowledge.items())),
            "claimed": [list(cell) for cell in
                        sorted(self.__claimed)],
            "tools": {"insta_until": tools.insta_until,
                      "insta_strength": tools.insta_strength,
                      "zap_until": tools.zap_until,
                      "vid_until": tools.vid_until,
                      "loja_until": tools.loja_until},
            "hq": self.__hq.to_snapshot(),
            "facilities": [f.to_snapshot(with_equip)
                           for f in self.__facilities],
            "chain_stage": self.chain_stage(),
        }

    def __repr__(self) -> str:
        return f"CompanyView({self.__comp.name!r})"


# --------------------------------------------------------------------- #
# Ações e sorteio
# --------------------------------------------------------------------- #
class Actuator(_View):
    """Os verbos legais de ação da focal — TODA escrita que uma
    política faz no mundo passa por aqui, na mesma ordem e com os
    mesmos efeitos das chamadas diretas da era pré-Observation."""

    __slots__ = ("_Actuator__engine", "_Actuator__comp")

    def __init__(self, engine, comp: Company):
        self.__engine = engine
        self.__comp = comp

    # -- caixa ---------------------------------------------------------
    def spend(self, amount: float, reason: str = "spend") -> None:
        """Gasto nomeado da focal (ledger/flows do motor)."""
        self.__engine._spend(self.__comp, amount, reason)

    # -- sondagem / território -----------------------------------------
    def probe(self, deposit_name: str) -> tuple[float, float]:
        """Sonda um depósito: paga o custo, registra o achado no
        knowledge da focal e devolve ``(grade, size_t)`` — a ÚNICA
        porta pela qual a verdade oculta vira conhecimento legal."""
        eng, comp = self.__engine, self.__comp
        dep = eng._deposit_by_name[deposit_name]
        eng._spend(comp, chain.PROBE_COST, reason="probe")
        comp.knowledge[dep.name] = (dep.grade, dep.size_t)
        return (dep.grade, dep.size_t)

    def register_claim(self, cell) -> None:
        """Registra a célula como da focal (conjunto próprio + mapa
        público de claims do mundo). O gasto é verbo separado."""
        self.__comp.claimed.add(cell)
        self.__engine.claimed_by[cell] = self.__comp.cid

    # -- construção ------------------------------------------------------
    def build_facility(self, kind: str, cell,
                       deposit: str | None = None) -> FacilityView:
        """Constrói a instalação (o gasto é verbo separado) e devolve
        a view dela — para narrar com o ``id`` recém-criado."""
        fac = self.__comp.add_facility(kind, cell)
        if deposit is not None:
            fac["deposit"] = deposit
        return FacilityView(fac, self.__engine)

    # -- equipamentos (B2) ----------------------------------------------
    def _facility(self, facility_id: str) -> dict:
        return self.__comp.facilities[facility_id]

    def repair(self, facility_id: str) -> None:
        self.__engine.repair_facility(self.__comp,
                                      self._facility(facility_id))

    def maintain(self, facility_id: str) -> None:
        self.__engine.maintain_facility(self.__comp,
                                        self._facility(facility_id))

    def overhaul(self, facility_id: str) -> None:
        self.__engine.overhaul_facility(self.__comp,
                                        self._facility(facility_id))

    # -- intenções de mercado -------------------------------------------
    def buy(self, commodity: str, qty: float) -> None:
        """Intenção de compra do tick (o motor liquida no mercado)."""
        self.__comp._buys[commodity] = qty

    def offer(self, commodity: str, qty: float) -> None:
        """Intenção de venda do tick (o motor liquida no mercado)."""
        self.__comp._offers[commodity] = qty

    # -- ferramentas ------------------------------------------------------
    def set_tool(self, tool: str, until: int,
                 strength: float | None = None) -> None:
        """Liga uma ferramenta simulada até ``until`` (só o InstaSim
        tem ``strength``). O gasto é verbo separado."""
        tools = self.__comp.tools
        setattr(tools, f"{tool}_until", until)
        if tool == "insta" and strength is not None:
            tools.insta_strength = strength

    # -- crônica e marcos -------------------------------------------------
    def narrate(self, kind: str, text: str, **extra) -> None:
        """Escreve na crônica pública como a focal, no tick corrente."""
        self.__engine.chronicle.add(self.__engine.tick, kind, text,
                                    self.__comp.name, **extra)

    def note_link(self, stage: int) -> None:
        """Registra marco de elo da cadeia (recorde permanente)."""
        self.__engine._note_link(self.__comp, stage)


class SealedActuator(_View):
    """O ``act`` da observação DE DECISÃO (fatia 3): um selo, não um
    executor. No contrato declarativo a política não executa verbo
    nenhum durante o ``decide`` — ela devolve a lista de
    ``mundo.intentions`` e o motor valida e executa. Qualquer verbo
    chamado aqui levanta ``RuntimeError`` com a explicação do
    contrato, na hora e sem efeito no mundo. (O ``Actuator`` de
    verdade continua existindo: é a ferramenta do executor do motor
    e dos testes que exercitam os verbos direto, via
    ``build_observation`` sem o selo.)"""

    __slots__ = ()

    def __getattr__(self, name: str):
        raise RuntimeError(
            f"obs.act.{name}: no contrato declarativo (fatia 3) a "
            "decisão não executa verbos — decide(obs) devolve uma "
            "lista de mundo.intentions e o motor as executa "
            "(docs/OBSERVATION-SPEC.md §4)")


class RandomFacade(_View):
    """Sorteio como serviço: só ``uniform``/``random``, repassados ao
    fluxo do motor na ordem em que a política os pede. O objeto
    ``Random`` em si (estado, reseed) nunca atravessa a fronteira."""

    __slots__ = ("_RandomFacade__rng",)

    def __init__(self, rng):
        self.__rng = rng

    def uniform(self, a: float, b: float) -> float:
        return self.__rng.uniform(a, b)

    def random(self) -> float:
        return self.__rng.random()


# --------------------------------------------------------------------- #
# A Observation e sua construção (código do motor)
# --------------------------------------------------------------------- #
class Observation(_View):
    """Tudo que a empresa pode ver, e nada além (SDD §6.2):

    ``me`` (ela mesma), ``world`` (o público), ``act`` (os verbos),
    ``rng`` (o sorteio como serviço). Construída pelo motor a cada
    decisão — claims de rivais feitos mais cedo no mesmo tick já
    aparecem, porque cada decisão ganha a sua Observation."""

    __slots__ = ("_Observation__me", "_Observation__world",
                 "_Observation__act", "_Observation__rng")

    def __init__(self, me: CompanyView, world: WorldView,
                 act: Actuator, rng: RandomFacade):
        self.__me = me
        self.__world = world
        self.__act = act
        self.__rng = rng

    @property
    def me(self) -> CompanyView:
        return self.__me

    @property
    def world(self) -> WorldView:
        return self.__world

    @property
    def act(self) -> Actuator:
        return self.__act

    @property
    def rng(self) -> RandomFacade:
        return self.__rng

    def to_snapshot(self) -> dict:
        """A fotografia serializável desta decisão (fatia 2, SPEC
        §4): só valores — ``dict``/``list``/``str``/``int``/``float``/
        ``bool``/``None``, sem nenhuma referência viva — capturando
        fielmente o que a política viu neste instante: ``me`` (a
        focal por dentro) e ``world`` (o público, incluindo as
        séries públicas do mercado vivo). É função de LEITURA pura:
        não chama verbos, não sorteia, não materializa estado
        preguiçoso — rodar um episódio fotografando cada decisão
        reproduz o episódio sem fotografia, bit a bit.

        ``act`` e ``rng`` ficam fora DE PROPÓSITO: são capacidades
        (verbos e sorteio como serviço), não observação — um
        snapshot que os carregasse vazaria o motor em si. Pelo mesmo
        motivo o snapshot herda o fog-of-war da superfície: só entra
        o que as views já expõem legitimamente (nada de grade/size
        crus, de futuro agendado, de estado de rival)."""
        return {"me": self.__me.to_snapshot(
                    with_equip=self.__world.equip_v2),
                "world": self.__world.to_snapshot()}


def build_company_view(engine, comp: Company) -> CompanyView:
    """A view da focal (usada sozinha pelas fachadas baratas do
    motor, ex.: ``reserve``)."""
    hq_city = engine._city_by_name[comp.hq_city]
    hq = CityView(hq_city, engine.city_country(comp.hq_city))
    return CompanyView(comp, engine, hq)


def build_observation(engine, comp: Company, *,
                      sealed_act: bool = False) -> Observation:
    """Monta a Observation da decisão de ``comp`` neste instante.
    Função do motor: lê o estado vivo UMA vez e entrega só views.

    ``sealed_act=True`` é a observação que o ``decide`` recebe
    (fatia 3): o ``act`` vem selado (``SealedActuator``) — decidir é
    declarar intenções, não executar verbos. Sem o selo (testes dos
    verbos, uso interno do motor) o ``act`` é o ``Actuator`` vivo."""
    me = build_company_view(engine, comp)
    deposits = tuple(
        DepositView(d, engine.deposit_country(d),
                    engine.claimed_by.get(d.cell))
        for d in engine.deposits)
    cities = tuple(CityView(c, engine.city_country(c.name))
                   for c in engine.cities)
    countries: tuple = ()
    if engine.country_v2:
        countries = tuple(
            CountryView(name, **engine.country_state(name))
            for name in sorted(engine._countries))
    capex_names = {dv.country for dv in deposits} \
        | {cv.country for cv in cities} | set(engine._countries)
    capex = {name: engine.capex_mult(name) for name in capex_names}
    equip_policy = equip_model = None
    if engine.equip_v2 and engine._equip is not None:
        equip_policy = MappingProxyType(engine._equip["policy"])
        equip_model = MappingProxyType(engine._equip["model"])
    anchors = MappingProxyType({})
    price_history = MappingProxyType({})
    if engine.market_v2:
        # séries públicas do B1 (fatia 2): cópias do instante da
        # decisão — âncora e anel de preços não mudam durante as
        # decisões de um tick, então a cópia É o valor da decisão
        anchors = MappingProxyType(dict(engine.anchors))
        price_history = MappingProxyType(
            {c: tuple(ring) for c, ring in engine._price_ring.items()})
    world = WorldView(
        tick=engine.tick, market_v2=engine.market_v2,
        country_v2=engine.country_v2, equip_v2=engine.equip_v2,
        prices=MappingProxyType(engine.prices),
        anchors=anchors, price_history=price_history,
        deposits=deposits, cities=cities, countries=countries,
        capex=capex, equip_policy=equip_policy,
        equip_model=equip_model)
    act = SealedActuator() if sealed_act else Actuator(engine, comp)
    return Observation(me, world, act, RandomFacade(engine.rng))
