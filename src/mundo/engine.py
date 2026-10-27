"""O motor do mundo: ticks mensais, decisões, produção, mercado, crônica.

Determinístico por seed (um único random.Random). Nenhum LLM por tick:
empresas decidem por heurísticas parametrizadas pela personalidade.
"""
from __future__ import annotations

import copy
import json
import math
import random

from dataclasses import asdict

from . import chain, marketdata
from .chronicle import Chronicle, Event, sim_date
from .companies import Company, StockBook, make_companies
from .tools_sim import (INSTA_DURATION_TICKS, LOJA_DEMAND_WEIGHT,
                        LOJA_DURATION_TICKS, LOJA_FEE_PCT, VID_DEMAND_WEIGHT,
                        VID_DURATION_TICKS, ZAP_DURATION_TICKS, ToolEffects,
                        insta_campaign_cost, loja_store_cost,
                        vid_campaign_cost, zap_campaign_cost)
from .world import CITIES, DEPOSITS, City, Deposit

START_YEAR = 2027
_COMMODITIES_SORTED = sorted(chain.COMMODITIES)
_REGIME_DUR_KEY = {"boom": "boom_months", "bust": "bust_months",
                   "normal": "normal_months"}


class Policy:
    """Interface plugável de decisão das empresas.

    O motor chama ``decide(engine, comp)`` uma vez por tick para cada
    empresa viva, já com ``comp._offers``/``comp._buys`` zerados. A
    política lê o mundo pelo ``engine`` (preços, depósitos, claims,
    crônica) e age pelos métodos do motor (``engine._spend``,
    ``engine._note_link``): o motor continua dono do estado e das regras
    físicas/econômicas. Políticas aprendidas (RL) implementam esta
    interface sem tocar o motor.
    """

    def decide(self, engine, comp: Company) -> None:
        raise NotImplementedError


class HeuristicPolicy(Policy):
    """A política heurística do v0: traços de personalidade parametrizam
    sondagem, capex, compras, vendas e uso de ferramentas. É a política
    padrão do Engine; o comportamento é idêntico ao ``_decide`` original.

    As constantes de decisão vivem em ``PARAMS0`` (o genoma 0 do
    protocolo de torneios, docs/ALGORITMOS-DECISAO.md): instanciar com
    ``params`` sobrescreve genes individuais SEM mudar nenhuma regra —
    com os defaults, o comportamento é bit-idêntico ao v0 (goldens).
    """

    PARAMS0 = {
        "reserve_base": 1_500_000.0,        # reserva de caixa (base)
        "reserve_risk_span": 2_000_000.0,   # reserva extra por (1 - risk)
        "mines_coef": 2.0,                  # minas desejadas = 1 + int(aggr * coef)
        "dist_scale": 25.0,                 # escala de distância no score do depósito
        "known_grade_base": 0.3,            # intercepto do peso do teor conhecido
        "size_ref": 800_000.0,              # referência de tamanho conhecido (t)
        "grade_thr_base": 0.62,             # limiar de teor p/ reivindicar (base)
        "grade_thr_risk": 0.25,             # limiar cai com o risk
        "refinery_raw_trigger": 350.0,      # bruto acumulado p/ erguer refinaria
        "factory_need_vertical": 1_200_000.0,   # valor em metais p/ fábrica (vertical alto)
        "factory_need_default": 2_600_000.0,    # idem (vertical baixo)
        "plant_component_trigger": 40.0,    # componentes em estoque p/ planta
        "assembly_device_trigger": 25.0,    # dispositivos em estoque p/ montadora
        "assembly_cash_cushion": 6_000_000.0,   # colchão de caixa p/ montadora
        "buy_budget_frac": 0.5,             # fração do gastável alocada a compras
        "buy_target_scale": 1.0,            # escala global dos alvos de compra
        "buffer_scale": 1.0,                # escala global dos buffers de estoque
        "insta_prob_scale": 1.0,            # escala da prob. do InstaSim
        "zap_prob_scale": 1.0,              # escala da prob. do ZapSim
        "pick_noise": 0.1,                  # meia-largura do ruído de preferência
    }

    # Fallback de CLASSE: subclasses que sobrescrevem __init__ sem
    # chamar super() (ex.: políticas de teste que embrulham a
    # heurística) leem os defaults daqui; instâncias normais ganham o
    # próprio dict em __init__, que sombreia este.
    p = PARAMS0

    def __init__(self, params: dict | None = None):
        self.p = dict(self.PARAMS0)
        if params:
            unknown = set(params) - set(self.PARAMS0)
            if unknown:
                raise ValueError(f"genes desconhecidos: {sorted(unknown)}")
            self.p.update(params)

    def reserve(self, comp: Company) -> float:
        return self.p["reserve_base"] \
            + (1.0 - comp.traits["risk"]) * self.p["reserve_risk_span"]

    def decide(self, engine, comp: Company) -> None:
        rng = engine.rng
        t = comp.traits
        spendable = comp.cash - self.reserve(comp)
        capex_done = False

        # 1) Mineração: sondar / reivindicar / construir mina
        mines = [f for f in comp.facilities.values() if f["kind"] == "mine"]
        desired_mines = 1 + int(t["aggression"] * self.p["mines_coef"])
        if len(mines) < desired_mines:
            target = self.pick_deposit(engine, comp)
            if target is not None:
                known = comp.knowledge.get(target.name)
                if known is None:
                    if spendable > chain.PROBE_COST:
                        engine._spend(comp, chain.PROBE_COST, reason="probe")
                        comp.knowledge[target.name] = (target.grade, target.size_t)
                        if target.grade >= 0.78:
                            engine.chronicle.add(engine.tick, "probe",
                                               f"{comp.name} sonda {target.name} e "
                                               f"encontra um depósito RICO.", comp.name)
                        elif target.grade <= 0.35:
                            engine.chronicle.add(engine.tick, "probe",
                                               f"{comp.name} sonda {target.name}: "
                                               f"teor decepcionante.", comp.name)
                elif not capex_done:
                    grade, _ = known
                    threshold = self.p["grade_thr_base"] \
                        - t["risk"] * self.p["grade_thr_risk"]
                    cost = chain.CLAIM_COST + chain.FACILITIES["mine"]["cost"]
                    if grade >= threshold and spendable > cost:
                        if target.cell not in comp.claimed:
                            engine._spend(comp, chain.CLAIM_COST, reason="claim")
                            comp.claimed.add(target.cell)
                            engine.claimed_by[target.cell] = comp.cid
                        engine._spend(comp, chain.FACILITIES["mine"]["cost"],
                                      reason="build")
                        fac = comp.add_facility("mine", target.cell)
                        fac["deposit"] = target.name
                        engine.chronicle.add(engine.tick, "mine",
                                           f"{comp.name} abre sua mina em "
                                           f"{target.name}.", comp.name,
                                           cid=comp.cid, fid=fac["id"],
                                           facility_kind="mine", cell=list(target.cell),
                                           deposit=target.name)
                        engine._note_link(comp, 1)
                        capex_done = True

        # 2) Elos de jusante
        if not capex_done:
            capex_done = self.build_downstream(engine, comp, spendable)

        # 3) Compras de insumos que faltam
        self.plan_buys(engine, comp)

        # 4) Ofertas de venda (excedente sobre o buffer de jusante)
        self.plan_sells(engine, comp)

        # 5) Ferramentas simuladas
        self.use_tools(engine, comp)

    def pick_deposit(self, engine, comp: Company) -> Deposit | None:
        hq = engine._city_by_name[comp.hq_city]
        mined = {f.get("deposit") for f in comp.facilities.values()}
        best, best_score = None, -1.0
        for d in engine.deposits:
            owner = engine.claimed_by.get(d.cell)
            if owner is not None and owner != comp.cid:
                continue
            if d.name in mined:
                continue
            dist = abs(d.lat - hq.lat) + abs(d.lon - hq.lon)
            score = chain.BASE_PRICES[d.resource] \
                / (1.0 + dist / self.p["dist_scale"])
            known = comp.knowledge.get(d.name)
            if known:
                score *= self.p["known_grade_base"] + known[0]  # teor pesa
                score *= min(1.5, known[1] / self.p["size_ref"])
            noise = self.p["pick_noise"]
            score *= engine.rng.uniform(1.0 - noise, 1.0 + noise)  # gosto/erro
            if score > best_score:
                best, best_score = d, score
        return best

    def build_downstream(self, engine, comp: Company, spendable: float) -> bool:
        t = comp.traits
        hq_cell = engine._city_by_name[comp.hq_city].cell

        def affordable(kind):
            return spendable > chain.FACILITIES[kind]["cost"]

        def build(kind, text):
            engine._spend(comp, chain.FACILITIES[kind]["cost"], reason="build")
            fac = comp.add_facility(kind, hq_cell)
            engine.chronicle.add(engine.tick, "facility", text, comp.name,
                                 cid=comp.cid, fid=fac["id"], facility_kind=kind,
                                 cell=list(hq_cell))
            engine._note_link(comp, comp.chain_stage())
            return True

        raw_total = sum(comp.stocks[r] for r in chain.RAW_TO_REFINED)
        if comp.has("mine") and not comp.has("refinery") \
                and raw_total > self.p["refinery_raw_trigger"] \
                and affordable("refinery"):
            return build("refinery",
                         f"{comp.name} inaugura sua refinaria em {comp.hq_city} — "
                         f"o refino agora é dentro de casa.")
        metal_value = sum(comp.stocks[m] * chain.BASE_PRICES[m]
                          for m in ("copper", "lithium", "iron"))
        need = self.p["factory_need_vertical"] if t["vertical"] > 0.7 \
            else self.p["factory_need_default"]
        if comp.has("refinery") and not comp.has("factory") \
                and metal_value > need and affordable("factory"):
            return build("factory",
                         f"{comp.name} ergue uma fábrica de componentes em "
                         f"{comp.hq_city}.")
        if comp.has("factory") and not comp.has("plant") \
                and comp.stocks["component"] > self.p["plant_component_trigger"] \
                and affordable("plant"):
            return build("plant",
                         f"{comp.name} abre sua planta de dispositivos — "
                         f"a cadeia sobe mais um elo.")
        if comp.has("plant") and not comp.has("assembly") \
                and comp.stocks["device"] > self.p["assembly_device_trigger"] \
                and comp.cash > chain.FACILITIES["assembly"]["cost"] \
                + self.p["assembly_cash_cushion"]:
            return build("assembly",
                         f"{comp.name} anuncia a montadora de SUPERCOMPUTADORES. "
                         f"O topo da cadeia está ao alcance.")
        return False

    def plan_buys(self, engine, comp: Company) -> None:
        spendable = comp.cash - self.reserve(comp)
        if spendable <= 0:
            return
        scale = self.p["buy_target_scale"]
        wants = {}
        if comp.has("factory"):
            if comp.stocks["copper"] < 4.0:
                wants["copper"] = 6.0 * scale
            if comp.stocks["lithium"] < 1.5:
                wants["lithium"] = 2.5 * scale
        if comp.has("plant") and comp.stocks["component"] < 12:
            wants["component"] = 20.0 * scale
        if comp.has("assembly") and comp.stocks["device"] < 10:
            wants["device"] = 12.0 * scale
        budget = spendable * self.p["buy_budget_frac"]
        for c, q in wants.items():
            cost = q * engine.prices[c]
            if cost <= budget:
                comp._buys[c] = q
                budget -= cost

    def buffer(self, comp: Company, commodity: str) -> float:
        """Quanto manter em estoque para o próprio jusante."""
        v = (0.5 + comp.traits["vertical"]) * self.p["buffer_scale"]
        if commodity in chain.RAW_TO_REFINED and comp.has("refinery"):
            return 220.0 * v
        if commodity in ("copper", "lithium") and comp.has("factory"):
            return (6.0 if commodity == "copper" else 2.0) * v
        if commodity == "component" and comp.has("plant"):
            return 30.0 * v
        if commodity == "device" and comp.has("assembly"):
            return 15.0 * v
        return 0.0

    def plan_sells(self, engine, comp: Company) -> None:
        for c in chain.COMMODITIES:
            surplus = comp.stocks[c] - self.buffer(comp, c)
            if surplus > 0.01:
                comp._offers[c] = surplus

    def use_tools(self, engine, comp: Company) -> None:
        if not comp.has("plant"):
            return
        t = comp.traits
        tools = comp.tools
        if not tools.insta_active(engine.tick) \
                and engine.rng.random() < t["marketing"] * 0.45 \
                * self.p["insta_prob_scale"] \
                and comp.cash - self.reserve(comp) > insta_campaign_cost():
            engine._spend(comp, insta_campaign_cost(), reason="tools")
            tools.insta_until = engine.tick + INSTA_DURATION_TICKS
            tools.insta_strength = 1.0
            engine.chronicle.add(engine.tick, "tool",
                               f"{comp.name} dispara uma campanha no InstaSim "
                               f"(US$ {insta_campaign_cost():,.0f}) para empurrar "
                               f"seus dispositivos.", comp.name)
        if not tools.zap_active(engine.tick) and comp.stocks["device"] > 20 \
                and engine.rng.random() < t["marketing"] * 0.35 \
                * self.p["zap_prob_scale"] \
                and comp.cash - self.reserve(comp) > zap_campaign_cost():
            engine._spend(comp, zap_campaign_cost(), reason="tools")
            tools.zap_until = engine.tick + ZAP_DURATION_TICKS
            engine.chronicle.add(engine.tick, "tool",
                               f"{comp.name} abre canal de vendas no ZapSim "
                               f"(US$ {zap_campaign_cost():,.0f}).", comp.name)
        # VidSim: ferramenta de elo alto — quem já vende dispositivo e tem
        # marketing forte produz vídeo (decisão por limiar, sem sorteio:
        # é capex de marca, não impulso). Custa ~7x o InstaSim e dura 2x.
        if not tools.vid_active(engine.tick) and t["marketing"] >= 0.6 \
                and comp.stocks["device"] > 10 \
                and comp.cash - self.reserve(comp) > vid_campaign_cost():
            engine._spend(comp, vid_campaign_cost(), reason="tools")
            tools.vid_until = engine.tick + VID_DURATION_TICKS
            engine.chronicle.add(engine.tick, "tool",
                               f"{comp.name} estreia campanha em vídeo no "
                               f"VidSim (US$ {vid_campaign_cost():,.0f}) para "
                               f"empurrar seus produtos de elo alto.", comp.name)
        # LojaSim: quem tem dispositivo parado abre prateleira no
        # marketplace e aceita pagar a comissão sobre o que vender.
        if not tools.loja_active(engine.tick) \
                and comp.stocks["device"] >= 15 \
                and comp.cash - self.reserve(comp) > loja_store_cost():
            engine._spend(comp, loja_store_cost(), reason="tools")
            tools.loja_until = engine.tick + LOJA_DURATION_TICKS
            engine.chronicle.add(engine.tick, "tool",
                               f"{comp.name} abre loja no LojaSim "
                               f"(US$ {loja_store_cost():,.0f} + "
                               f"{LOJA_FEE_PCT:.0%} por venda).", comp.name)



def _rng_to_json(state) -> list:
    version, internal, gauss = state
    return [version, list(internal), gauss]


def _rng_from_json(data: list):
    version, internal, gauss = data
    return (version, tuple(internal), gauss)


def _company_state(c: Company) -> dict:
    return {
        "cid": c.cid, "name": c.name, "archetype": c.archetype,
        "traits": dict(c.traits), "hq_city": c.hq_city, "color": c.color,
        "cash": c.cash, "stocks": dict(c.stocks),
        "facilities": {fid: {"id": f["id"], "kind": f["kind"],
                             "cell": list(f["cell"]),
                             **({"deposit": f["deposit"]}
                                if "deposit" in f else {})}
                       for fid, f in c.facilities.items()},
        "claimed": sorted([list(cell) for cell in c.claimed]),
        "knowledge": {k: [g, s] for k, (g, s) in c.knowledge.items()},
        "tools": {"insta_until": c.tools.insta_until,
                  "insta_strength": c.tools.insta_strength,
                  "zap_until": c.tools.zap_until,
                  "vid_until": c.tools.vid_until,
                  "loja_until": c.tools.loja_until},
        "alive": c.alive, "founded_tick": c.founded_tick, "fac_n": c._fac_n,
    }


def _company_from_state(cs: dict) -> Company:
    comp = Company(cid=cs["cid"], name=cs["name"],
                   archetype=cs["archetype"], traits=dict(cs["traits"]),
                   hq_city=cs["hq_city"], color=cs["color"], cash=cs["cash"])
    comp.stocks = StockBook(cs["stocks"])
    comp.facilities = {fid: {"id": f["id"], "kind": f["kind"],
                             "cell": tuple(f["cell"]),
                             **({"deposit": f["deposit"]}
                                if "deposit" in f else {})}
                       for fid, f in cs["facilities"].items()}
    comp.claimed = {tuple(cell) for cell in cs["claimed"]}
    comp.knowledge = {k: (v[0], v[1]) for k, v in cs["knowledge"].items()}
    _tools = cs["tools"]
    comp.tools = ToolEffects(
        insta_until=_tools["insta_until"],
        insta_strength=_tools["insta_strength"],
        zap_until=_tools["zap_until"],
        vid_until=_tools.get("vid_until", -1),      # states do v0 não têm
        loja_until=_tools.get("loja_until", -1))
    comp.alive = cs["alive"]
    comp.founded_tick = cs["founded_tick"]
    comp._fac_n = cs["fac_n"]
    comp._sync_kinds()
    return comp


def _resolve_world(world_data: bool):
    """(deposits, cities, source) do mundo.

    Fonte preferencial: o dataset real (data/world_data.json via
    mundo.realdata — tamanhos/teores calibrados de figuras públicas com
    fonte). Fallback automático para os valores embutidos do v0 quando o
    dataset não está disponível ou é inválido (ex.: bundle do Kaggle só
    com src/), ou quando world_data=False.
    """
    if world_data:
        try:
            from . import realdata
            data = realdata.load_world_data()
            return (realdata.to_world_deposits(data),
                    realdata.to_world_cities(data), "realdata")
        except Exception:
            pass
    return copy.deepcopy(DEPOSITS), list(CITIES), "builtin"


class Engine:
    def __init__(self, seed: int = 42, n_companies: int = 8,
                 god_events: list[dict] | None = None,
                 policy: Policy | None = None,
                 world_data: bool = True,
                 market_v2: bool = False,
                 market_params: dict | None = None):
        self.policy = policy if policy is not None else HeuristicPolicy()
        self.rng = random.Random(seed)
        self.seed = seed
        self.tick = 0
        self.chronicle = Chronicle(START_YEAR)
        deposits, cities, source = _resolve_world(world_data)
        self.world_source = source
        self.cities: list[City] = cities
        self.deposits: list[Deposit] = copy.deepcopy(deposits)
        self._rebuild_caches()
        self.remaining = {d.name: d.size_t for d in self.deposits}
        self.claimed_by: dict[tuple, int] = {}       # cell -> cid dono
        self.companies: list[Company] = make_companies(
            n_companies, self.rng, cities=self.cities)
        self.prices = dict(chain.BASE_PRICES)
        # Mercado vivo B1 (Degrau 1, Fase 2) — desligado por padrão.
        # Desligado, NADA deste bloco é tocado nem serializado e o
        # comportamento é bit-idêntico ao clássico (goldens da Fase 1).
        # Ligado, os parâmetros são DADO (mundo.marketdata) e a âncora
        # p* vira série pública (o acoplamento que o B3 vai consumir).
        self.market_v2 = market_v2
        self.anchors = dict(chain.BASE_PRICES)
        self._mkt: dict | None = None
        self._regime: dict[str, str] = {}
        self._regime_months: dict[str, int] = {}
        self._demand_ema: dict[str, float] = {}
        self._cover: dict[str, float] = {}
        self._fair_noise: dict[str, float] = {}
        self._price_ring: dict[str, list[float]] = {}
        self._record_state: dict[str, dict] = {}
        self._tick_stock_totals: list[float] | None = None
        self._tick_seasonal: dict[str, float] | None = None
        if market_v2:
            self._init_living_market(market_params)
        self.demand_factors: dict[str, tuple[float, int]] = {}
        self.god_events = sorted(god_events or [], key=lambda e: e["tick"])
        self.first_link: dict[int, str] = {}
        # Crônica rica (v1): líderes vigentes (rivalidade), produção de
        # supercomputadores por empresa e o histórico de gastos por
        # motivo de cada uma (matéria-prima da "causa provável" da
        # falência — por motivo porque ops roda todo tick e apagaria o
        # rastro do capex se fosse só "o último gasto").
        self._cash_leader: int | None = None
        self._stage_leader: int | None = None
        self._super_by_cid: dict[int, float] = {}
        self._spend_hist: dict[int, dict[str, tuple[float, int]]] = {}
        self.frames: list[dict] = []
        # Ledger (conservação) -------------------------------------------
        self.ledger_mass = {c: {"extracted": 0.0, "produced": 0.0,
                                "consumed": 0.0, "wasted": 0.0,
                                "sold_external": 0.0}
                            for c in chain.COMMODITIES}
        self.initial_cash = sum(c.cash for c in self.companies)
        self.money_in = 0.0     # vendas às cidades
        self.money_out = 0.0    # construção, sondagem, operação, ferramentas
        self.total_supercomputers = 0.0
        # Fluxos de caixa do tick corrente (event-sourcing): _spend e o
        # mercado registram aqui; step() consolida num evento "flows".
        self._flows: dict[int, dict[str, float]] = {}
        for c in self.companies:
            _hq = self._city_by_name[c.hq_city]  # valida a sede no mapa
            self.chronicle.add(0, "founding",
                               f"{c.name} ({c.archetype}) é fundada em {c.hq_city} "
                               f"com US$ {c.cash/1e6:.0f}M em caixa.", c.name,
                               cid=c.cid, cash=c.cash, archetype=c.archetype,
                               hq=c.hq_city)
        self._snapshot()

    # -- caches de consulta (performance) ---------------------------------
    def _rebuild_caches(self) -> None:
        """Índices nome->objeto: eliminam varreduras lineares por tick
        em _produce/_pick_deposit/_build_downstream. Depósitos novos
        (evento de Deus) entram no índice em _apply_god_events."""
        self._deposit_by_name = {d.name: d for d in self.deposits}
        self._city_by_name = {c.name: c for c in self.cities}

    # -- utilidades de ledger -------------------------------------------
    def _flow(self, cid: int, key: str, amount: float) -> None:
        flows = self._flows.setdefault(cid, {})
        flows[key] = flows.get(key, 0.0) + amount

    def _spend(self, comp: Company, amount: float,
               reason: str = "spend") -> None:
        comp.cash -= amount
        self.money_out += amount
        self._flow(comp.cid, f"spend_{reason}", -amount)
        self._spend_hist.setdefault(comp.cid, {})[reason] = (amount, self.tick)

    def _emit_flows(self, cash_start: dict[int, float]) -> None:
        """Fecha o tick no log: um evento "flows" com o delta de caixa de
        cada empresa e o detalhamento por motivo (spend_*, trade_*, ...).
        É o que torna a crônica suficiente para o replay (event-sourcing).
        """
        companies = {}
        for c in self.companies:
            breakdown = {k: v for k, v in self._flows.get(c.cid, {}).items()
                         if v != 0.0}
            companies[str(c.cid)] = {
                "delta": c.cash - cash_start[c.cid], "cash": c.cash,
                "flows": breakdown}
        self._flows = {}
        self.chronicle.add(self.tick, "flows", "", None, companies=companies)

    def _convert(self, comp: Company, src: str, qty_in: float,
                 dst: str, qty_out: float) -> None:
        comp.stocks.add(chain.COMMODITY_INDEX[src], -qty_in)
        comp.stocks.add(chain.COMMODITY_INDEX[dst], qty_out)
        self.ledger_mass[src]["consumed"] += qty_in
        self.ledger_mass[src]["wasted"] += max(0.0, qty_in - qty_out)
        self.ledger_mass[dst]["produced"] += qty_out

    # -- Deus -------------------------------------------------------------
    def _apply_god_events(self) -> None:
        for ev in [e for e in self.god_events if e["tick"] == self.tick]:
            kind = ev["type"]
            if kind == "price_shock":
                c = ev["commodity"]
                self.prices[c] *= ev["factor"]
                self.demand_factors[c] = (ev.get("demand_factor", 1.0),
                                          self.tick + ev.get("duration", 6))
                self.chronicle.add(self.tick, "god",
                                   f"CHOQUE DE MERCADO: o preço de {c} se move "
                                   f"abertamente (fator {ev['factor']}).")
            elif kind == "discovery":
                d = Deposit(ev["name"], ev["resource"], ev["lat"], ev["lon"],
                            ev["size_t"], ev["grade"])
                self.deposits.append(d)
                self._deposit_by_name[d.name] = d
                self.remaining[d.name] = d.size_t
                self.chronicle.add(self.tick, "god",
                                   f"DESCOBERTA: novo depósito de {d.resource} "
                                   f"anunciado — {d.name}.")
            elif kind == "sanction":
                res = ev["resource"]
                until = self.tick + ev.get("duration", 6)
                self.demand_factors[res] = (0.5, until)
                refined = chain.RAW_TO_REFINED.get(res)
                if refined:
                    self.demand_factors[refined] = (0.5, until)
                self.chronicle.add(self.tick, "god",
                                   f"SANÇÃO: o comércio de {res} é restringido "
                                   f"por {ev.get('duration', 6)} meses.")

    def _demand_factor(self, commodity: str) -> float:
        f = self.demand_factors.get(commodity)
        return f[0] if f and self.tick <= f[1] else 1.0

    # -- decisões ---------------------------------------------------------
    # -- decisões (delegadas à política plugável) -------------------------
    # Os métodos _decide/_reserve/... permanecem como fachada de
    # compatibilidade e delegam para a política instalada (por padrão a
    # HeuristicPolicy). Trocar a política não toca o motor.
    def _reserve(self, comp: Company) -> float:
        return self.policy.reserve(comp)

    def _decide(self, comp: Company) -> None:
        comp._offers = {}
        comp._buys = {}
        if not comp.alive:
            return
        self.policy.decide(self, comp)

    def _pick_deposit(self, comp: Company):
        return self.policy.pick_deposit(self, comp)

    def _build_downstream(self, comp: Company, spendable: float) -> bool:
        return self.policy.build_downstream(self, comp, spendable)

    def _plan_buys(self, comp: Company) -> None:
        return self.policy.plan_buys(self, comp)

    def _buffer(self, comp: Company, commodity: str) -> float:
        return self.policy.buffer(comp, commodity)

    def _plan_sells(self, comp: Company) -> None:
        return self.policy.plan_sells(self, comp)

    def _use_tools(self, comp: Company) -> None:
        return self.policy.use_tools(self, comp)

    def _note_link(self, comp: Company, stage: int) -> None:
        names = {1: "extração", 2: "refino", 3: "componentes",
                 4: "dispositivos", 5: "supercomputador"}
        if stage >= 1 and stage not in self.first_link:
            self.first_link[stage] = comp.name
            self.chronicle.add(self.tick, "chain_link",
                               f"MARCO DA CADEIA: {comp.name} é a primeira a "
                               f"dominar o elo de {names[stage]}.", comp.name,
                               stage=stage, era=1)
            # Marco permanente da era: a primeira vez em cada elo vira
            # recorde do mundo — ninguém apaga um recorde.
            if stage == 5:
                text = (f"MARCO DE ERA: {comp.name} fecha a ERA 1 (The Path "
                        f"to the Supercomputer) — é a primeira a dominar o "
                        f"elo de supercomputador. Recorde permanente do mundo.")
            else:
                text = (f"RECORDE: {comp.name} é a primeira a dominar o elo "
                        f"de {names[stage]} — marco permanente da Era 1.")
            self.chronicle.add(self.tick, "record", text, comp.name,
                               stage=stage, era=1, record="first_link")

    # -- rivalidade ---------------------------------------------------------
    def _leader(self, key) -> Company | None:
        alive = [c for c in self.companies if c.alive]
        if not alive:
            return None
        return max(alive, key=lambda c: (key(c), -c.cid))

    def _note_rivalry(self) -> None:
        """Narra trocas de liderança (caixa e cadeia): ultrapassagem é
        história. Líderes são estado do motor (serializados): retomar
        uma corrida não reconta nem perde rivalidades."""
        cash_leader = self._leader(lambda c: c.cash)
        if cash_leader is not None:
            if self._cash_leader is None:
                self._cash_leader = cash_leader.cid
            elif cash_leader.cid != self._cash_leader:
                old = self.companies[self._cash_leader]
                self.chronicle.add(
                    self.tick, "rivalry",
                    f"RIVALIDADE: {cash_leader.name} ultrapassa {old.name} e "
                    f"assume a liderança em caixa (US$ "
                    f"{cash_leader.cash/1e6:.1f}M contra US$ "
                    f"{old.cash/1e6:.1f}M).", cash_leader.name,
                    metric="cash", from_cid=old.cid, to_cid=cash_leader.cid)
                self._cash_leader = cash_leader.cid
        stage_leader = self._leader(lambda c: c.chain_stage())
        if stage_leader is not None and stage_leader.chain_stage() > 0:
            if self._stage_leader is None:
                self._stage_leader = stage_leader.cid
            elif stage_leader.cid != self._stage_leader:
                old = self.companies[self._stage_leader]
                self.chronicle.add(
                    self.tick, "rivalry",
                    f"RIVALIDADE: {stage_leader.name} ultrapassa {old.name} "
                    f"na cadeia e assume a liderança (elo "
                    f"{stage_leader.chain_stage()} contra elo "
                    f"{old.chain_stage()}).", stage_leader.name,
                    metric="stage", from_cid=old.cid, to_cid=stage_leader.cid)
                self._stage_leader = stage_leader.cid

    # -- produção -----------------------------------------------------------
    def _produce(self, comp: Company) -> None:
        if not comp.alive:
            return
        for fac in list(comp.facilities.values()):
            kind = fac["kind"]
            cap = chain.FACILITIES[kind]["capacity"]
            cost = chain.OPERATING_COST[kind]
            if kind == "mine":
                dep = self._deposit_by_name[fac["deposit"]]
                crude = min(cap, self.remaining[dep.name])
                if crude <= 0:
                    continue
                self.remaining[dep.name] -= crude
                payable = crude * dep.grade
                waste = crude - payable
                comp.stocks.add(chain.COMMODITY_INDEX[dep.resource], payable)
                self.ledger_mass[dep.resource]["extracted"] += payable
                self.ledger_mass[dep.resource]["wasted"] += waste
                self._spend(comp, crude * cost, reason="ops")
            elif kind == "refinery":
                budget = cap
                for raw, refined in chain.RAW_TO_REFINED.items():
                    if budget <= 0:
                        break
                    qty = min(comp.stocks[raw], budget)
                    if qty <= 0:
                        continue
                    budget -= qty
                    self._convert(comp, raw, qty, refined,
                                  qty * chain.REFINE_YIELD)
                    self._spend(comp, qty * cost, reason="ops")
            elif kind in ("factory", "plant", "assembly"):
                product = {"factory": "component", "plant": "device",
                           "assembly": "supercomputer"}[kind]
                recipe = chain.RECIPES[product]
                max_units = cap
                for inp, per in recipe["inputs"].items():
                    max_units = min(max_units, comp.stocks[inp] / per)
                units = int(max_units)
                if units <= 0:
                    continue
                for inp, per in recipe["inputs"].items():
                    qty = units * per
                    comp.stocks.add(chain.COMMODITY_INDEX[inp], -qty)
                    self.ledger_mass[inp]["consumed"] += qty
                comp.stocks.add(chain.COMMODITY_INDEX[product],
                                units * recipe["out"])
                self.ledger_mass[product]["produced"] += units * recipe["out"]
                self._spend(comp, units * cost, reason="ops")
                if product == "supercomputer":
                    self.total_supercomputers += units
                    self._super_by_cid[comp.cid] = \
                        self._super_by_cid.get(comp.cid, 0.0) + units
                    self.chronicle.add(self.tick, "record",
                                       f"{comp.name} entrega um SUPERCOMPUTADOR "
                                       f"montado por conta própria.", comp.name)

    # -- mercado vivo (B1) ------------------------------------------------------
    def _init_living_market(self, params_override: dict | None) -> None:
        self._mkt = marketdata.resolve_params(params_override)
        for c in chain.COMMODITIES:
            self._regime[c] = "normal"
            self._regime_months[c] = 0
            self._demand_ema[c] = max(float(chain.CITY_DEMAND.get(c, 0.0)), 10.0)
            self._cover[c] = 0.0
            self._fair_noise[c] = 0.0
            self._price_ring[c] = []
            self._record_state[c] = {"dir": None, "extreme": 0.0}

    def inventory_cover(self, commodity: str) -> float:
        """Cobertura de inventário PÚBLICA (estilo estoque de bolsa/LME):
        meses de demanda cobertos pelo estoque AGREGADO do mundo. É o
        único sinal de inventário que sai — estoques por empresa
        continuam privados (fog-of-war intacto)."""
        return self._cover.get(commodity, 0.0)

    def _advance_market(self) -> None:
        """Um mês de dinâmica por commodity: regime Markov com durações
        médias reais, deriva da âncora conforme o regime e o ruído do
        preço justo. Consome RNG sempre na mesma ordem (commodities
        ordenadas); desligado, não consome nada. O regime NÃO é
        observável pelas empresas — infere-se do preço, como na vida
        real. Só a âncora p* é série pública (preparo do acoplamento B3).
        """
        comms = self._mkt["commodities"]
        rnd, gauss = self.rng.random, self.rng.gauss
        regimes, months, anchors = self._regime, self._regime_months, \
            self.anchors
        for c in _COMMODITIES_SORTED:
            p = comms[c]
            regime = regimes[c]
            months[c] += 1
            if rnd() < 1.0 / p[_REGIME_DUR_KEY[regime]]:
                if regime == "normal":
                    new = "boom" if rnd() < 0.5 else "bust"
                else:
                    new = "normal"
                regimes[c] = new
                months[c] = 0
                regime = new
                if new in ("boom", "bust"):
                    self._narrate_regime(c, new)
            if regime == "boom":
                anchors[c] *= 1.0 + p["drift_boom"]
            elif regime == "bust":
                anchors[c] *= 1.0 - p["drift_bust"]
            else:   # normal: reversão lenta ao custo de longo prazo
                base = chain.BASE_PRICES[c]
                anchors[c] += (base - anchors[c]) * 0.01
            self._fair_noise[c] = gauss(0.0, p["sigma_monthly"])

    def _narrate_regime(self, commodity: str, new: str) -> None:
        cover = self._cover.get(commodity, 0.0)
        anchor = self.anchors[commodity]
        if new == "boom":
            text = (f"MERCADO: {commodity} entra em EUFORIA (boom) — a "
                    f"âncora de longo prazo está em US$ {anchor:,.0f} e "
                    f"subindo; os estoques do mundo cobrem {cover:.1f} "
                    f"meses de demanda.")
        else:
            text = (f"MERCADO: {commodity} entra em COLAPSO (bust) — a "
                    f"âncora de longo prazo está em US$ {anchor:,.0f} e "
                    f"caindo; os estoques do mundo cobrem {cover:.1f} "
                    f"meses de demanda.")
        self.chronicle.add(self.tick, "market_regime", text, None,
                           commodity=commodity, regime=new, anchor=anchor,
                           cover=cover)

    def _market_living(self, commodity: str) -> None:
        """O mercado de UMA commodity com o B1 ligado.

        O comércio em si (quem compra de quem, ledger, ferramentas) é
        idêntico ao clássico; o que muda é a FORMAÇÃO DE PREÇO: demanda
        das cidades elástica, preço justo = âncora × pressão de
        inventário × ruído, e banda [0,25×; 6×] DA ÂNCORA (a banda
        antiga, do preço-base fixo, não representava o ciclo real).
        Sem oferta, o preço continua derivando para o justo — mercado
        parado não é preço congelado.
        """
        p = self._mkt["commodities"][commodity]
        ci = chain.COMMODITY_INDEX[commodity]
        price = self.prices[commodity]
        anchor = self.anchors[commodity]
        offers, buys = [], []
        for c in self.companies:
            if not c.alive:
                continue
            q = c._offers.get(commodity, 0.0)
            if q > 0.001:
                offers.append((c, q))
            buys.append((c, c._buys.get(commodity, 0.0)))
        total_supply = sum(q for _, q in offers)
        internal_demand = sum(q for _, q in buys)
        # cobertura pública de inventário: agregado do mundo, nunca por
        # empresa (é o sinal estilo LME que torna especulação informada).
        # Os totais são computados UMA vez por tick em _market (estoques
        # de uma commodity não mudam enquanto outra é negociada).
        totals = self._tick_stock_totals
        total_stocks = totals[ci] if totals is not None else \
            sum(c.stocks.at(ci) for c in self.companies)
        cover = total_stocks / max(self._demand_ema[commodity], 1.0)
        self._cover[commodity] = cover
        # Preço justo e demanda elástica: as fórmulas canônicas são as
        # funções puras de marketdata (testadas lá); inline aqui por ser
        # o caminho quente do tick (11 commodities × todo tick).
        fair = anchor \
            * math.exp(-p["gamma"] * (cover - p["cover_target"])) \
            * math.exp(self._fair_noise[commodity])
        d0 = chain.CITY_DEMAND.get(commodity, 0.0)
        if d0 > 0:
            seasonal = self._tick_seasonal[commodity] \
                if self._tick_seasonal is not None else \
                marketdata.seasonal_factor(self.tick, p["seasonal_amp"],
                                           int(p["seasonal_phase"]))
            city_q = d0 * (price / anchor) ** (-p["elasticity"]) \
                * seasonal * self._demand_factor(commodity)
        else:
            city_q = 0.0
        if total_supply > 0:
            # 1) comércio entre empresas (dinheiro interno: soma zero)
            sold_internal = 0.0
            offered_left = {c.cid: q for c, q in offers}
            for buyer, want in sorted(buys, key=lambda x: x[0].cid):
                if want <= 0:
                    continue
                total_left = sum(offered_left.values())
                if total_left <= 0:
                    break
                fill = min(want, total_left)
                for seller, q in offers:
                    if seller is buyer or offered_left[seller.cid] <= 0:
                        continue
                    share = fill * (offered_left[seller.cid] / total_left)
                    share = min(share, offered_left[seller.cid],
                                buyer.cash / price if price > 0 else 0.0)
                    if share <= 0.0001:
                        continue
                    seller.stocks.add(ci, -share)
                    buyer.stocks.add(ci, share)
                    seller.cash += share * price
                    buyer.cash -= share * price
                    self._flow(seller.cid, "trade_in", share * price)
                    self._flow(buyer.cid, "trade_out", -share * price)
                    offered_left[seller.cid] -= share
                    sold_internal += share
            # 2) demanda elástica das cidades sobre o que restou
            left_total = sum(offered_left.values())
            if city_q > 0 and left_total > 0:
                weights = {}
                for seller, _ in offers:
                    w = offered_left[seller.cid]
                    if seller.tools.insta_active(self.tick) \
                            and commodity == "device":
                        w *= 2.2
                    if seller.tools.vid_active(self.tick) \
                            and commodity in ("device", "supercomputer"):
                        w *= VID_DEMAND_WEIGHT
                    if seller.tools.zap_active(self.tick):
                        w *= 1.3
                    if seller.tools.loja_active(self.tick) \
                            and commodity == "device":
                        w *= LOJA_DEMAND_WEIGHT
                    weights[seller.cid] = w
                wsum = sum(weights.values())
                for seller, _ in offers:
                    if wsum <= 0:
                        break
                    qty = min(offered_left[seller.cid],
                              city_q * weights[seller.cid] / wsum)
                    if qty <= 0.0001:
                        continue
                    seller.stocks.add(ci, -qty)
                    seller.cash += qty * price
                    self._flow(seller.cid, "city_sales", qty * price)
                    self.money_in += qty * price
                    self.ledger_mass[commodity]["sold_external"] += qty
                    offered_left[seller.cid] -= qty
                    if commodity == "device" \
                            and seller.tools.loja_active(self.tick):
                        fee = qty * price * LOJA_FEE_PCT
                        seller.cash -= fee
                        self.money_out += fee
                        self._flow(seller.cid, "spend_tools", -fee)
        # demanda realizada -> EMA pública (a régua da cobertura)
        demand_total = internal_demand + city_q
        alpha = self._mkt["model"].get("ema_alpha", 0.1)
        ema = self._demand_ema[commodity]
        self._demand_ema[commodity] = ema + alpha * (demand_total - ema)
        # 3) preço: desequilíbrio + perseguição do justo; banda da âncora
        ratio = (demand_total - total_supply) \
            / max(demand_total, total_supply, 1.0)
        factor = min(1.6, max(0.6, 1.0 + 0.10 * ratio))
        new_price = price * factor
        new_price += p["kappa"] * (fair - new_price)
        lo, hi = self._mkt["model"]["price_band_of_anchor"]
        new_price = min(hi * anchor, max(lo * anchor, new_price))
        self.prices[commodity] = new_price
        # anel público de 24 meses e recordes: só extremos de episódio
        ring = self._price_ring[commodity]
        ring.append(new_price)
        window = int(self._mkt["model"].get("record_window_months", 24))
        del ring[:-window]
        if len(ring) >= 12:
            self._note_price_record(commodity, new_price, ring[:-1])

    def _note_price_record(self, commodity: str, new_price: float,
                           prev_ring: list[float]) -> None:
        """Recorde de preço é TRANSIÇÃO, não estado (princípio B0.4):
        uma derrapada longa quebra o recorde todo mês e isso é ruído.
        Episódios: o primeiro rompimento da janela de 24 meses narra;
        os seguintes, na mesma direção, calam até o preço reverter
        ≥5% do extremo — aí um novo episódio pode nascer."""
        model = self._mkt["model"]
        brk = model.get("record_min_break_pct", 0.005)
        rev = model.get("record_episode_reversal_pct", 0.05)
        st = self._record_state[commodity]
        if st["dir"] == "high" and new_price < st["extreme"] * (1.0 - rev):
            st["dir"] = None
        elif st["dir"] == "low" and new_price > st["extreme"] * (1.0 + rev):
            st["dir"] = None
        if new_price > max(prev_ring) * (1.0 + brk):
            if st["dir"] == "high":
                st["extreme"] = max(st["extreme"], new_price)
                return
            st["dir"], st["extreme"] = "high", new_price
            self.chronicle.add(
                self.tick, "price_record",
                f"RECORDE DE PREÇO: {commodity} atinge "
                f"US$ {new_price:,.0f} — o maior valor em "
                f"{len(prev_ring) + 1} meses.", None,
                commodity=commodity, price=new_price,
                direction="high", window=len(prev_ring) + 1)
        elif new_price < min(prev_ring) * (1.0 - brk):
            if st["dir"] == "low":
                st["extreme"] = min(st["extreme"], new_price)
                return
            st["dir"], st["extreme"] = "low", new_price
            self.chronicle.add(
                self.tick, "price_record",
                f"RECORDE DE PREÇO: {commodity} desaba a "
                f"US$ {new_price:,.0f} — o menor valor em "
                f"{len(prev_ring) + 1} meses.", None,
                commodity=commodity, price=new_price,
                direction="low", window=len(prev_ring) + 1)
        elif st["dir"] == "high":
            st["extreme"] = max(st["extreme"], new_price)
        elif st["dir"] == "low":
            st["extreme"] = min(st["extreme"], new_price)

    # -- mercado --------------------------------------------------------------
    def _market(self) -> None:
        if self.market_v2:
            totals = [0.0] * chain.N_COMMODITIES
            for c in self.companies:
                c.stocks.add_into(totals)
            self._tick_stock_totals = totals
            # sazonalidade do tick, uma vez por commodity (não por chamada)
            self._tick_seasonal = {
                c: marketdata.seasonal_factor(
                    self.tick, pp["seasonal_amp"], int(pp["seasonal_phase"]))
                for c, pp in self._mkt["commodities"].items()}
        for commodity in _COMMODITIES_SORTED:
            if self.market_v2:
                self._market_living(commodity)
                continue
            price = self.prices[commodity]
            ci = chain.COMMODITY_INDEX[commodity]
            # coleta única: ofertas e compras na ordem das empresas vivas
            # (listas e somas idênticas às da versão em duas passagens)
            offers, buys = [], []
            for c in self.companies:
                if not c.alive:
                    continue
                q = c._offers.get(commodity, 0.0)
                if q > 0.001:
                    offers.append((c, q))
                buys.append((c, c._buys.get(commodity, 0.0)))
            total_supply = sum(q for _, q in offers)
            if total_supply <= 0:
                continue
            # 1) comércio entre empresas (dinheiro interno: soma zero)
            internal_demand = sum(q for _, q in buys)
            sold_internal = 0.0
            offered_left = {c.cid: q for c, q in offers}
            for buyer, want in sorted(buys, key=lambda x: x[0].cid):
                if want <= 0:
                    continue
                total_left = sum(offered_left.values())
                if total_left <= 0:
                    break
                fill = min(want, total_left)
                for seller, q in offers:
                    if seller is buyer or offered_left[seller.cid] <= 0:
                        continue
                    share = fill * (offered_left[seller.cid] / total_left)
                    share = min(share, offered_left[seller.cid],
                                buyer.cash / price if price > 0 else 0.0)
                    if share <= 0.0001:
                        continue
                    seller.stocks.add(ci, -share)
                    buyer.stocks.add(ci, share)
                    seller.cash += share * price
                    buyer.cash -= share * price
                    self._flow(seller.cid, "trade_in", share * price)
                    self._flow(buyer.cid, "trade_out", -share * price)
                    offered_left[seller.cid] -= share
                    sold_internal += share
            # 2) demanda das cidades sobre o que restou
            city_q = chain.CITY_DEMAND.get(commodity, 0.0) \
                * self._demand_factor(commodity)
            left_total = sum(offered_left.values())
            if city_q > 0 and left_total > 0:
                weights = {}
                for seller, _ in offers:
                    w = offered_left[seller.cid]
                    if seller.tools.insta_active(self.tick) \
                            and commodity == "device":
                        w *= 2.2
                    if seller.tools.vid_active(self.tick) \
                            and commodity in ("device", "supercomputer"):
                        w *= VID_DEMAND_WEIGHT
                    if seller.tools.zap_active(self.tick):
                        w *= 1.3
                    if seller.tools.loja_active(self.tick) \
                            and commodity == "device":
                        w *= LOJA_DEMAND_WEIGHT
                    weights[seller.cid] = w
                wsum = sum(weights.values())
                for seller, _ in offers:
                    if wsum <= 0:
                        break
                    qty = min(offered_left[seller.cid],
                              city_q * weights[seller.cid] / wsum)
                    if qty <= 0.0001:
                        continue
                    seller.stocks.add(ci, -qty)
                    seller.cash += qty * price
                    self._flow(seller.cid, "city_sales", qty * price)
                    self.money_in += qty * price
                    self.ledger_mass[commodity]["sold_external"] += qty
                    offered_left[seller.cid] -= qty
                    # LojaSim: a venda passou pela prateleira do marketplace
                    # — a comissão é sink (vai ao "mundo"), via ledger/flows.
                    if commodity == "device" \
                            and seller.tools.loja_active(self.tick):
                        fee = qty * price * LOJA_FEE_PCT
                        seller.cash -= fee
                        self.money_out += fee
                        self._flow(seller.cid, "spend_tools", -fee)
            # 3) ajuste de preço por desequilíbrio
            demand = internal_demand + city_q
            ratio = (demand - total_supply) / max(demand, total_supply, 1.0)
            factor = min(1.35, max(0.72, 1.0 + 0.10 * ratio))
            base = chain.BASE_PRICES[commodity]
            self.prices[commodity] = min(base * 3.0,
                                         max(base * 0.3, price * factor))
        self._tick_stock_totals = None
        self._tick_seasonal = None

    # -- falência / aquisição ---------------------------------------------------
    def _bankruptcy_cause(self, comp: Company) -> tuple[str, str]:
        """Causa provável da morte, inferida do estado no momento da
        quebra (último gasto, operação, estoque). Determinística: é
        função pura do estado serializável do motor."""
        hist = self._spend_hist.get(comp.cid, {})
        build = hist.get("build")
        if build and self.tick - build[1] <= 6 and build[0] >= 2_000_000:
            return "capex", ("expandiu rápido demais — o capex recente "
                             "devorou o caixa")
        acq = hist.get("acquisition")
        if acq and self.tick - acq[1] <= 6:
            return "aquisicao", "alavancou-se comprando os ativos de uma rival"
        if not comp.facilities:
            return "sem_operacao", "queimou o caixa sem montar operação"
        stock_value = sum(comp.stocks[c] * chain.BASE_PRICES[c]
                          for c in chain.COMMODITIES)
        if stock_value < 50_000:
            return "operacao", ("operou no prejuízo — custos acima da "
                                "receita e estoque parado")
        return "caixa", "ficou sem caixa"

    def _check_bankruptcy(self, comp: Company) -> None:
        if not comp.alive or comp.cash >= 0:
            return
        comp.alive = False
        cause, phrase = self._bankruptcy_cause(comp)
        self.chronicle.add(self.tick, "bankruptcy",
                           f"FALÊNCIA: {comp.name} quebra com "
                           f"US$ {comp.cash/1e6:.1f}M de rombo. "
                           f"Causa provável: {phrase}.", comp.name,
                           cid=comp.cid, cause=cause, cash=comp.cash)
        buyers = [c for c in self.companies
                  if c.alive and c.cash > 12_000_000]
        if buyers and comp.facilities:
            buyer = max(buyers, key=lambda c: c.cash)
            price = sum(chain.FACILITIES[f["kind"]]["cost"]
                        for f in comp.facilities.values()) * 0.15
            if buyer.cash > price:
                facility_ids = sorted(comp.facilities)
                self._spend(buyer, price, reason="acquisition")
                for fac in comp.facilities.values():
                    buyer.facilities[fac["id"]] = fac
                for cell in comp.claimed:
                    buyer.claimed.add(cell)
                    self.claimed_by[cell] = buyer.cid
                for ci in range(chain.N_COMMODITIES):
                    buyer.stocks.add(ci, comp.stocks.at(ci))
                    comp.stocks.set_at(ci, 0.0)
                comp.facilities = {}
                buyer._sync_kinds()
                comp._sync_kinds()
                self.chronicle.add(self.tick, "acquisition",
                                   f"AQUISIÇÃO: {buyer.name} compra os ativos "
                                   f"da falida {comp.name} por "
                                   f"US$ {price/1e6:.1f}M.", buyer.name,
                                   buyer_cid=buyer.cid, from_cid=comp.cid,
                                   facility_ids=facility_ids, price=price)

    # -- frames ------------------------------------------------------------------
    def _snapshot(self) -> None:
        frame = {
            "tick": self.tick,
            "date": sim_date(self.tick, START_YEAR),
            "prices": {k: round(v, 2) for k, v in self.prices.items()},
            "companies": [{
                "id": c.cid, "name": c.name, "archetype": c.archetype,
                "color": c.color, "hq": c.hq_city, "alive": c.alive,
                "cash": round(c.cash, 2), "stage": c.chain_stage(),
                "territory": sorted([list(cell) for cell in c.claimed]),
                "facilities": [{"kind": f["kind"], "cell": list(f["cell"]),
                                "deposit": f.get("deposit")}
                               for f in c.facilities.values()],
                "stocks": {k: round(v, 3) for k, v in c.stocks.items()
                           if v > 0.01},
            } for c in self.companies],
            "deposits": [{
                "name": d.name, "resource": d.resource, "cell": list(d.cell),
                "lat": d.lat, "lon": d.lon,
                "remaining_frac": round(self.remaining[d.name] / d.size_t, 4)
                if d.size_t else 0.0,
            } for d in self.deposits],
        }
        if self.market_v2:
            # visão de Deus: âncora (pública), regime (só Deus vê — as
            # empresas inferem do preço) e cobertura pública, por commodity
            frame["market"] = {
                c: {"anchor": round(self.anchors[c], 2),
                    "regime": self._regime[c],
                    "cover": round(self._cover[c], 3)}
                for c in chain.COMMODITIES}
        self.frames.append(frame)

    # -- loop principal ------------------------------------------------------------
    def step(self) -> None:
        """Um tick mensal completo: Deus, falências/decisões, produção,
        mercado. Extraído de run() para permitir snapshot/restore e
        drivers externos (treino RL) sem mudar a ordem das operações."""
        cash_start = {c.cid: c.cash for c in self.companies}
        self._flows = {}
        self._apply_god_events()
        if self.market_v2:
            self._advance_market()
        for comp in self.companies:
            self._check_bankruptcy(comp)
            self._decide(comp)
        for comp in self.companies:
            self._produce(comp)
        self._market()
        self._note_rivalry()
        self._emit_flows(cash_start)
        self.tick += 1
        if self.tick % 12 == 0:
            self._snapshot()
        if self.tick % 60 == 0:
            self._era_summary()

    def _era_summary(self) -> None:
        """RESUMO DE ERA: a cada 60 ticks (5 anos), a crônica fecha um
        capítulo com os líderes por categoria — a retrospectiva que o
        Deus lê sem precisar caçar evento por evento."""
        years = self.tick // 12
        alive = [c for c in self.companies if c.alive]
        richest = max(self.companies, key=lambda c: (c.cash, -c.cid))
        top = max(self.companies, key=lambda c: (c.chain_stage(), -c.cid))
        most_fac = max(self.companies,
                       key=lambda c: (len(c.facilities), -c.cid))
        top_producer = None
        if self._super_by_cid:
            top_producer = self.companies[max(
                self._super_by_cid,
                key=lambda cid: (self._super_by_cid[cid], -cid))]
        bankruptcies = sum(1 for e in self.chronicle.events
                           if e.kind == "bankruptcy")
        super_txt = f"supercomputadores entregues: {int(self.total_supercomputers)}"
        if top_producer is not None:
            super_txt += f" (maior produtor: {top_producer.name})"
        text = (f"RESUMO DA ERA ({years} anos de mundo): {richest.name} "
                f"lidera em caixa (US$ {richest.cash/1e6:.1f}M); {top.name} "
                f"lidera a cadeia (elo {top.chain_stage()}); {most_fac.name} "
                f"tem mais instalações ({len(most_fac.facilities)}); "
                f"{super_txt}; falências: {bankruptcies}; empresas vivas: "
                f"{len(alive)}/{len(self.companies)}.")
        self.chronicle.add(self.tick, "era_summary", text, None,
                           years=years, cash_leader=richest.name,
                           stage_leader=top.name,
                           supercomputers=int(self.total_supercomputers),
                           top_producer=(top_producer.name
                                         if top_producer else None),
                           bankruptcies=bankruptcies, alive=len(alive))

    def run(self, ticks: int) -> dict:
        for _ in range(ticks):
            self.step()
        if self.frames[-1]["tick"] != self.tick:
            self._snapshot()
        alive = [c for c in self.companies if c.alive]
        richest = max(self.companies, key=lambda c: c.cash)
        top_stage = max(self.companies, key=lambda c: c.chain_stage())
        self.chronicle.add(self.tick, "end",
                           f"FIM DO PERÍODO: {richest.name} lidera em caixa "
                           f"(US$ {richest.cash/1e6:.1f}M); {top_stage.name} foi "
                           f"quem mais subiu na cadeia (elo "
                           f"{top_stage.chain_stage()}); supercomputadores "
                           f"entregues: {int(self.total_supercomputers)}; "
                           f"empresas vivas: {len(alive)}/{len(self.companies)}.")
        return self.result()

    def result(self) -> dict:
        res = {
            "seed": self.seed,
            "ticks": self.tick,
            "frames": self.frames,
            "chronicle": self.chronicle.to_json(),
            "scoreboard": [{
                "name": c.name, "archetype": c.archetype, "alive": c.alive,
                "cash": round(c.cash, 2), "stage": c.chain_stage(),
                "facilities": len(c.facilities),
            } for c in sorted(self.companies, key=lambda x: -x.cash)],
        }
        if self.market_v2:
            # a série pública da âncora p* (o acoplamento que o B3 lê)
            res["market"] = {
                "anchors": dict(self.anchors),
                "cover": dict(self._cover),
                "regimes": dict(self._regime),
            }
        return res

    # -- snapshot / restore -------------------------------------------------
    def state_dict(self) -> dict:
        """Estado completo do mundo, serializável em JSON puro.

        Inclui o estado interno do RNG: restaurar e continuar produz
        resultado idêntico ao da corrida contínua (provado em teste).
        """
        state = {
            "version": 1,
            "seed": self.seed,
            "tick": self.tick,
            "rng_state": _rng_to_json(self.rng.getstate()),
            "world_source": self.world_source,
            "cities": [{"name": c.name, "lat": c.lat, "lon": c.lon,
                        "demand_weight": c.demand_weight}
                       for c in self.cities],
            "deposits": [{"name": d.name, "resource": d.resource,
                          "lat": d.lat, "lon": d.lon, "size_t": d.size_t,
                          "grade": d.grade} for d in self.deposits],
            "remaining": dict(self.remaining),
            "claimed_by": [[list(cell), cid]
                           for cell, cid in sorted(self.claimed_by.items())],
            "companies": [_company_state(c) for c in self.companies],
            "prices": dict(self.prices),
            "demand_factors": {k: [f, until]
                               for k, (f, until) in self.demand_factors.items()},
            "god_events": copy.deepcopy(self.god_events),
            "first_link": {str(k): v for k, v in self.first_link.items()},
            "leaders": {"cash": self._cash_leader,
                        "stage": self._stage_leader},
            "super_by_cid": {str(k): v for k, v in self._super_by_cid.items()},
            "spend_hist": {str(cid): {r: [a, t] for r, (a, t) in h.items()}
                           for cid, h in self._spend_hist.items()},
            "frames": copy.deepcopy(self.frames),
            "chronicle": {"start_year": self.chronicle.start_year,
                          "events": [asdict(e) for e in self.chronicle.events]},
            "ledger_mass": copy.deepcopy(self.ledger_mass),
            "initial_cash": self.initial_cash,
            "money_in": self.money_in,
            "money_out": self.money_out,
            "total_supercomputers": self.total_supercomputers,
        }
        if self.market_v2:
            # bloco presente SÓ com o B1 ligado: desligado, o state_dict
            # é byte-idêntico ao clássico (goldens da Fase 1)
            state["market_v2"] = {
                "params": copy.deepcopy(self._mkt),
                "anchors": dict(self.anchors),
                "regime": dict(self._regime),
                "regime_months": dict(self._regime_months),
                "demand_ema": dict(self._demand_ema),
                "cover": dict(self._cover),
                "fair_noise": dict(self._fair_noise),
                "price_ring": {c: list(r)
                               for c, r in self._price_ring.items()},
                "record_state": copy.deepcopy(self._record_state),
            }
        return state

    @classmethod
    def from_state(cls, state: dict,
                   policy: Policy | None = None) -> "Engine":
        """Reconstrói um Engine de um state_dict (sem re-fundar o mundo:
        nenhum RNG é consumido e nenhum evento é reemitido)."""
        eng = cls.__new__(cls)
        eng.policy = policy if policy is not None else HeuristicPolicy()
        eng.seed = state["seed"]
        eng.tick = state["tick"]
        eng.rng = random.Random()
        eng.rng.setstate(_rng_from_json(state["rng_state"]))
        eng.chronicle = Chronicle(state["chronicle"]["start_year"])
        eng.chronicle.events = [Event(**e)
                                for e in state["chronicle"]["events"]]
        eng.deposits = [Deposit(d["name"], d["resource"], d["lat"], d["lon"],
                                d["size_t"], d["grade"])
                        for d in state["deposits"]]
        if "cities" in state:
            eng.cities = [City(c["name"], c["lat"], c["lon"],
                               c["demand_weight"]) for c in state["cities"]]
            eng.world_source = state.get("world_source", "builtin")
        else:  # state antigo, sem cidades serializadas: resolve de novo
            _, eng.cities, eng.world_source = _resolve_world(True)
        eng._rebuild_caches()
        eng.remaining = dict(state["remaining"])
        eng.claimed_by = {tuple(cell): cid
                          for cell, cid in state["claimed_by"]}
        eng.companies = [_company_from_state(cs)
                         for cs in state["companies"]]
        eng.prices = dict(state["prices"])
        eng.demand_factors = {k: (f, until) for k, (f, until)
                              in state["demand_factors"].items()}
        eng.god_events = sorted(copy.deepcopy(state["god_events"]),
                                key=lambda e: e["tick"])
        eng.first_link = {int(k): v for k, v in state["first_link"].items()}
        leaders = state.get("leaders", {})          # states do v0 não têm
        eng._cash_leader = leaders.get("cash")
        eng._stage_leader = leaders.get("stage")
        eng._super_by_cid = {int(k): v for k, v
                             in state.get("super_by_cid", {}).items()}
        eng._spend_hist = {int(cid): {r: (v[0], v[1]) for r, v in h.items()}
                           for cid, h in state.get("spend_hist", {}).items()}
        eng.frames = copy.deepcopy(state["frames"])
        eng.ledger_mass = copy.deepcopy(state["ledger_mass"])
        eng.initial_cash = state["initial_cash"]
        eng.money_in = state["money_in"]
        eng.money_out = state["money_out"]
        eng.total_supercomputers = state["total_supercomputers"]
        eng._flows = {}
        # mercado vivo: states clássicos não têm o bloco -> segue desligado
        mv = state.get("market_v2")
        eng.market_v2 = bool(mv)
        eng.anchors = dict(chain.BASE_PRICES)
        eng._mkt = None
        eng._regime, eng._regime_months = {}, {}
        eng._demand_ema, eng._cover, eng._fair_noise = {}, {}, {}
        eng._price_ring = {}
        eng._record_state = {}
        if mv:
            eng._mkt = marketdata._validate(copy.deepcopy(mv["params"]))
            eng.anchors = dict(mv["anchors"])
            eng._regime = dict(mv["regime"])
            eng._regime_months = dict(mv["regime_months"])
            eng._demand_ema = dict(mv["demand_ema"])
            eng._cover = dict(mv["cover"])
            eng._fair_noise = dict(mv["fair_noise"])
            eng._price_ring = {c: list(r)
                               for c, r in mv["price_ring"].items()}
            eng._record_state = copy.deepcopy(mv.get("record_state", {}))
            for c in chain.COMMODITIES:
                eng._record_state.setdefault(
                    c, {"dir": None, "extreme": 0.0})
        eng._tick_stock_totals = None
        eng._tick_seasonal = None
        return eng

    def save_outputs(self, outdir: str) -> None:
        import os
        os.makedirs(outdir, exist_ok=True)
        res = self.result()
        with open(f"{outdir}/frames.json", "w", encoding="utf-8") as f:
            json.dump({"seed": res["seed"], "ticks": res["ticks"],
                       "frames": res["frames"],
                       "chronicle": res["chronicle"]}, f, ensure_ascii=False)
        self.chronicle.save(f"{outdir}/chronicle.json")
        with open(f"{outdir}/scoreboard.json", "w", encoding="utf-8") as f:
            json.dump(res["scoreboard"], f, ensure_ascii=False, indent=1)
