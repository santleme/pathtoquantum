"""O motor do mundo: ticks mensais, decisões, produção, mercado, crônica.

Determinístico por seed (um único random.Random). Nenhum LLM por tick:
empresas decidem por heurísticas parametrizadas pela personalidade.
"""
from __future__ import annotations

import copy
import json
import math
import random

from dataclasses import asdict, replace

from . import chain, countrydata, equipdata, marketdata
from .chronicle import Chronicle, Event, sim_date
from .companies import Company, StockBook, make_companies
from .intentions import (INTENTION_TYPES, BuildFacility, Buy,
                          IntentionError, MaintainFacility, Narrate,
                          Narration, NoteLink, Offer, OverhaulFacility,
                          Plan, Probe, RegisterClaim, RepairFacility,
                          SetTool, Spend)
from .observation import (Actuator, CompanyView, DepositView,
                          Observation, _jsonify, build_company_view,
                          build_observation)
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

    O motor chama ``decide(obs)`` uma vez por tick para cada empresa
    viva, já com as intenções do tick anterior zeradas — e entrega
    uma ``Observation`` (mundo.observation, guarda v2): a empresa
    mesma como view só-leitura, o mundo público e a fachada de
    sorteio. No contrato declarativo (fatia 3,
    docs/OBSERVATION-SPEC.md §4) o ``decide`` NÃO executa nada: ele
    devolve a lista ordenada de ``mundo.intentions`` da decisão, e
    o motor a valida (inteira, antes de qualquer execução) e a
    executa em ordem — o ``obs.act`` da observação de decisão vem
    selado justamente para o verbo não existir no caminho da
    política. Política nenhuma recebe o ``Engine`` nem ``Company``
    crua: fog-of-war é tipo, não disciplina (SDD §6.2). Políticas
    aprendidas (RL) implementam esta interface sem tocar o motor.
    """

    def decide(self, obs: Observation) -> list:
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

    def reserve(self, me: CompanyView) -> float:
        return self.p["reserve_base"] \
            + (1.0 - me.traits["risk"]) * self.p["reserve_risk_span"]

    def decide(self, obs: Observation) -> list:
        """A decisão como DADO (fatia 3): planeja as fases contra a
        sombra (``Plan`` — caixa e instalações como ficarão depois
        que as intenções já declaradas executarem) e devolve a lista
        ordenada; quem valida e executa é o motor. A ordem das
        intenções é a ordem de mutação da era imperativa, e os
        limiares leem a sombra exatamente onde a era imperativa
        relia o mundo vivo — é isso que mantém o episódio
        bit-idêntico (goldens)."""
        me, world = obs.me, obs.world
        t = me.traits
        plan = Plan.of(me)
        out: list = []
        spendable = me.cash - self.reserve(me)
        capex_done = False

        # 0) Equipamentos (B2): reparar / manter / trocar a frota —
        #    só existe com equip_v2 ligado; desligado, nem um bit muda
        if world.equip_v2:
            out += self.maintain_equipment(obs, plan)

        # 1) Mineração: sondar / reivindicar / construir mina
        mines = [f for f in me.facilities if f.kind == "mine"]
        desired_mines = 1 + int(t["aggression"] * self.p["mines_coef"])
        if len(mines) < desired_mines:
            target = self.pick_deposit(obs)
            if target is not None:
                known = me.knowledge.get(target.name)
                if known is None:
                    if spendable > chain.PROBE_COST:
                        # a sondagem declara as DUAS narrações: o
                        # executor revela o teor e narra a candidata
                        # selecionada (limiares da intenção), na
                        # mesma posição da sequência de sempre
                        out.append(Probe(
                            target.name,
                            on_rich=Narration(
                                "probe",
                                f"{me.name} sonda {target.name} e "
                                f"encontra um depósito RICO."),
                            on_poor=Narration(
                                "probe",
                                f"{me.name} sonda {target.name}: "
                                f"teor decepcionante.")))
                        plan.spend(chain.PROBE_COST)
                elif not capex_done:
                    grade, _ = known
                    threshold = self.p["grade_thr_base"] \
                        - t["risk"] * self.p["grade_thr_risk"]
                    # B3: capex no país paga o prêmio de risco-país
                    # (1,0 com country_v2 desligado — bit-idêntico)
                    mult = world.capex_mult(target.country)
                    cost = (chain.CLAIM_COST
                            + chain.FACILITIES["mine"]["cost"]) * mult
                    if grade >= threshold and spendable > cost:
                        if target.cell not in me.claimed:
                            out.append(Spend(chain.CLAIM_COST * mult,
                                             reason="claim"))
                            out.append(RegisterClaim(
                                tuple(target.cell)))
                            plan.spend(chain.CLAIM_COST * mult)
                        out.append(Spend(
                            chain.FACILITIES["mine"]["cost"] * mult,
                            reason="build"))
                        plan.spend(chain.FACILITIES["mine"]["cost"]
                                   * mult)
                        out.append(BuildFacility(
                            "mine", tuple(target.cell),
                            deposit=target.name,
                            narration=Narration.of(
                                "mine",
                                f"{me.name} abre sua mina em "
                                f"{target.name}.",
                                cid=me.cid, facility_kind="mine",
                                cell=list(target.cell),
                                deposit=target.name)))
                        plan.build("mine")
                        out.append(NoteLink(1))
                        capex_done = True

        # 2) Elos de jusante
        if not capex_done:
            built, ints = self.build_downstream(obs, spendable, plan)
            out += ints
            capex_done = built

        # 3) Compras de insumos que faltam
        out += self.plan_buys(obs, plan)

        # 4) Ofertas de venda (excedente sobre o buffer de jusante)
        out += self.plan_sells(obs, plan)

        # 5) Ferramentas simuladas
        out += self.use_tools(obs, plan)
        return out

    def maintain_equipment(self, obs: Observation,
                           plan: Plan | None = None) -> list:
        """Os três verbos do B2 — reparar, manter, trocar (overhaul) —
        como intenções devolvidas (fatia 3).

        A propensão a cuidar da frota nasce dos traços: quem tem
        aggression alta roda até quebrar (e só paga o reparo com o
        caixa bem folgado); quem é cauteloso mantém cedo e troca a
        planta velha antes do colapso. Limiares e multiplicadores são
        DADO (equipdata, seção "policy"); custos e física, do motor.
        Instalação quebrada/em oficina não recebe PM nem overhaul.
        Os testes de caixa leem a SOMBRA (``plan.cash``), que abate
        cada custo declarado na ordem — o caixa "vivo" da era
        imperativa, em que um reparo pago pesava no teste da
        instalação seguinte."""
        me, world = obs.me, obs.world
        if plan is None:
            plan = Plan.of(me)
        out: list = []
        pol = world.equip_policy
        model = world.equip_model
        care = 1.0 - me.traits["aggression"]
        reserve = self.reserve(me)
        maint_thr = pol["maint_h_base"] + care * pol["maint_h_care_span"]
        repair_mult = pol["repair_mult_care0"] + care * (
            pol["repair_mult_care1"] - pol["repair_mult_care0"])
        for fac in me.facilities:
            eq = fac.equip
            build = chain.FACILITIES[fac.kind]["cost"]
            if eq.broken:
                if plan.cash - reserve > eq.repair_cost * repair_mult:
                    out.append(RepairFacility(fac.id))
                    plan.spend(eq.repair_cost)
                continue
            if world.tick <= eq.down_until:
                continue        # em oficina: nada a decidir neste tick
            if eq.age >= pol["overhaul_min_age"] \
                    and eq.cond <= pol["overhaul_max_cond"]:
                cost = build * model["overhaul_frac"]
                if plan.cash - reserve > cost:
                    out.append(OverhaulFacility(fac.id))
                    plan.spend(cost)
                continue
            cost = build * model["maint_frac"]
            if eq.cond < maint_thr and plan.cash - reserve > cost:
                out.append(MaintainFacility(fac.id))
                plan.spend(cost)
        return out

    def pick_deposit(self, obs: Observation) -> DepositView | None:
        me, world = obs.me, obs.world
        hq = me.hq
        mined = {f.deposit for f in me.facilities}
        best, best_score = None, -1.0
        for d in world.deposits:
            owner = d.claimed_by
            if owner is not None and owner != me.cid:
                continue
            if d.name in mined:
                continue
            dist = abs(d.lat - hq.lat) + abs(d.lon - hq.lon)
            score = chain.BASE_PRICES[d.resource] \
                / (1.0 + dist / self.p["dist_scale"])
            known = me.knowledge.get(d.name)
            if known:
                score *= self.p["known_grade_base"] + known[0]  # teor pesa
                score *= min(1.5, known[1] / self.p["size_ref"])
            noise = self.p["pick_noise"]
            score *= obs.rng.uniform(1.0 - noise, 1.0 + noise)  # gosto/erro
            if score > best_score:
                best, best_score = d, score
        return best

    def build_downstream(self, obs: Observation, spendable: float,
                         plan: Plan | None = None):
        """O elo de jusante do tick como intenções (fatia 3):
        devolve ``(construiu?, intenções)``. Os testes de ``has()``
        leem a sombra (idênticos ao mundo vivo neste ponto da
        decisão) e o ``NoteLink`` carrega o elo que a sombra terá
        DEPOIS da construção — o mesmo ``chain_stage()`` pós-build
        que a era imperativa lia da empresa recém-construída."""
        me, world = obs.me, obs.world
        t = me.traits
        if plan is None:
            plan = Plan.of(me)
        hq_cell = me.hq.cell
        # B3: jusante é construído no país da sede — mesmo prêmio de
        # capex das minas (1,0 desligado — bit-idêntico)
        mult = world.capex_mult(me.hq.country)

        def affordable(kind):
            return spendable > chain.FACILITIES[kind]["cost"] * mult

        def build(kind, text):
            cost = chain.FACILITIES[kind]["cost"] * mult
            plan.spend(cost)
            plan.build(kind)
            ints = [Spend(cost, reason="build"),
                    BuildFacility(kind, tuple(hq_cell),
                                  narration=Narration.of(
                                      "facility", text, cid=me.cid,
                                      facility_kind=kind,
                                      cell=list(hq_cell))),
                    NoteLink(plan.chain_stage())]
            return True, ints

        raw_total = sum(me.stocks[r] for r in chain.RAW_TO_REFINED)
        if plan.has("mine") and not plan.has("refinery") \
                and raw_total > self.p["refinery_raw_trigger"] \
                and affordable("refinery"):
            return build("refinery",
                         f"{me.name} inaugura sua refinaria em {me.hq_city} — "
                         f"o refino agora é dentro de casa.")
        metal_value = sum(me.stocks[m] * chain.BASE_PRICES[m]
                          for m in ("copper", "lithium", "iron"))
        need = self.p["factory_need_vertical"] if t["vertical"] > 0.7 \
            else self.p["factory_need_default"]
        if plan.has("refinery") and not plan.has("factory") \
                and metal_value > need and affordable("factory"):
            return build("factory",
                         f"{me.name} ergue uma fábrica de componentes em "
                         f"{me.hq_city}.")
        if plan.has("factory") and not plan.has("plant") \
                and me.stocks["component"] > self.p["plant_component_trigger"] \
                and affordable("plant"):
            return build("plant",
                         f"{me.name} abre sua planta de dispositivos — "
                         f"a cadeia sobe mais um elo.")
        if plan.has("plant") and not plan.has("assembly") \
                and me.stocks["device"] > self.p["assembly_device_trigger"] \
                and plan.cash > chain.FACILITIES["assembly"]["cost"] \
                + self.p["assembly_cash_cushion"]:
            return build("assembly",
                         f"{me.name} anuncia a montadora de SUPERCOMPUTADORES. "
                         f"O topo da cadeia está ao alcance.")
        return False, []

    def plan_buys(self, obs: Observation,
                  plan: Plan | None = None) -> list:
        """Compras do tick como intenções (fatia 3). O gastável é o
        da SOMBRA — o caixa depois dos gastos já declarados neste
        tick, que é o caixa vivo que a era imperativa relia aqui; e
        os ``has()`` são os da sombra: uma fábrica construída na
        fase anterior DESTE tick já puxa compras, como sempre puxou."""
        me, world = obs.me, obs.world
        if plan is None:
            plan = Plan.of(me)
        out: list = []
        spendable = plan.cash - self.reserve(me)
        if spendable <= 0:
            return out
        scale = self.p["buy_target_scale"]
        wants = {}
        if plan.has("factory"):
            if me.stocks["copper"] < 4.0:
                wants["copper"] = 6.0 * scale
            if me.stocks["lithium"] < 1.5:
                wants["lithium"] = 2.5 * scale
        if plan.has("plant") and me.stocks["component"] < 12:
            wants["component"] = 20.0 * scale
        if plan.has("assembly") and me.stocks["device"] < 10:
            wants["device"] = 12.0 * scale
        budget = spendable * self.p["buy_budget_frac"]
        for c, q in wants.items():
            cost = q * world.prices[c]
            if cost <= budget:
                out.append(Buy(c, q))
                budget -= cost
        return out

    def buffer(self, me: CompanyView, commodity: str) -> float:
        """Quanto manter em estoque para o próprio jusante."""
        return self._buffer_kinds(me, commodity, None)

    def _buffer_kinds(self, me: CompanyView, commodity: str,
                      kinds) -> float:
        """O buffer, com os ``has()`` lidos de ``kinds`` (a sombra)
        quando dados — dentro de uma decisão declarativa, o buffer
        enxerga as construções já declaradas neste tick."""
        has = me.has if kinds is None else (lambda k: k in kinds)
        v = (0.5 + me.traits["vertical"]) * self.p["buffer_scale"]
        if commodity in chain.RAW_TO_REFINED and has("refinery"):
            return 220.0 * v
        if commodity in ("copper", "lithium") and has("factory"):
            return (6.0 if commodity == "copper" else 2.0) * v
        if commodity == "component" and has("plant"):
            return 30.0 * v
        if commodity == "device" and has("assembly"):
            return 15.0 * v
        return 0.0

    def plan_sells(self, obs: Observation,
                   plan: Plan | None = None) -> list:
        """Ofertas do tick como intenções (fatia 3); o buffer de cada
        commodity é o da sombra (construções deste tick contam)."""
        me = obs.me
        if plan is None:
            plan = Plan.of(me)
        out: list = []
        for c in chain.COMMODITIES:
            surplus = me.stocks[c] - self._buffer_kinds(me, c,
                                                        plan.kinds)
            if surplus > 0.01:
                out.append(Offer(c, surplus))
        return out

    def use_tools(self, obs: Observation,
                  plan: Plan | None = None) -> list:
        """Ferramentas simuladas como intenções (fatia 3). Os
        sorteios acontecem AQUI, ao planejar, na mesma ordem e com
        os mesmos curtos-circuitos da era imperativa — executar a
        intenção não sorteia nada, então o fluxo do RNG do episódio
        não muda um draw. Os testes de caixa leem a sombra."""
        me, world = obs.me, obs.world
        if plan is None:
            plan = Plan.of(me)
        out: list = []
        if not plan.has("plant"):
            return out
        t = me.traits
        tools = me.tools
        if not tools.insta_active(world.tick) \
                and obs.rng.random() < t["marketing"] * 0.45 \
                * self.p["insta_prob_scale"] \
                and plan.cash - self.reserve(me) > insta_campaign_cost():
            out.append(Spend(insta_campaign_cost(), reason="tools"))
            out.append(SetTool("insta",
                               until=world.tick + INSTA_DURATION_TICKS,
                               strength=1.0))
            out.append(Narrate(Narration(
                "tool",
                f"{me.name} dispara uma campanha no InstaSim "
                f"(US$ {insta_campaign_cost():,.0f}) para empurrar "
                f"seus dispositivos.")))
            plan.spend(insta_campaign_cost())
        if not tools.zap_active(world.tick) and me.stocks["device"] > 20 \
                and obs.rng.random() < t["marketing"] * 0.35 \
                * self.p["zap_prob_scale"] \
                and plan.cash - self.reserve(me) > zap_campaign_cost():
            out.append(Spend(zap_campaign_cost(), reason="tools"))
            out.append(SetTool("zap",
                               until=world.tick + ZAP_DURATION_TICKS))
            out.append(Narrate(Narration(
                "tool",
                f"{me.name} abre canal de vendas no ZapSim "
                f"(US$ {zap_campaign_cost():,.0f}).")))
            plan.spend(zap_campaign_cost())
        # VidSim: ferramenta de elo alto — quem já vende dispositivo e tem
        # marketing forte produz vídeo (decisão por limiar, sem sorteio:
        # é capex de marca, não impulso). Custa ~7x o InstaSim e dura 2x.
        if not tools.vid_active(world.tick) and t["marketing"] >= 0.6 \
                and me.stocks["device"] > 10 \
                and plan.cash - self.reserve(me) > vid_campaign_cost():
            out.append(Spend(vid_campaign_cost(), reason="tools"))
            out.append(SetTool("vid",
                               until=world.tick + VID_DURATION_TICKS))
            out.append(Narrate(Narration(
                "tool",
                f"{me.name} estreia campanha em vídeo no "
                f"VidSim (US$ {vid_campaign_cost():,.0f}) para "
                f"empurrar seus produtos de elo alto.")))
            plan.spend(vid_campaign_cost())
        # LojaSim: quem tem dispositivo parado abre prateleira no
        # marketplace e aceita pagar a comissão sobre o que vender.
        if not tools.loja_active(world.tick) \
                and me.stocks["device"] >= 15 \
                and plan.cash - self.reserve(me) > loja_store_cost():
            out.append(Spend(loja_store_cost(), reason="tools"))
            out.append(SetTool("loja",
                               until=world.tick + LOJA_DURATION_TICKS))
            out.append(Narrate(Narration(
                "tool",
                f"{me.name} abre loja no LojaSim "
                f"(US$ {loja_store_cost():,.0f} + "
                f"{LOJA_FEE_PCT:.0%} por venda).")))
            plan.spend(loja_store_cost())
        return out



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
                                if "deposit" in f else {}),
                             **({"equip": dict(f["equip"])}
                                if "equip" in f else {})}
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
                                if "deposit" in f else {}),
                             **({"equip": dict(f["equip"])}
                                if "equip" in f else {})}
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


def _is_number(v) -> bool:
    """Número real finito (bool não é número aqui)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v)


def _checked_cell(cell, what: str) -> tuple:
    """A célula de uma intenção, normalizada para tupla de 2
    números — ou ``IntentionError``."""
    if not isinstance(cell, (list, tuple)) or len(cell) != 2 \
            or not all(_is_number(c) for c in cell):
        raise IntentionError(f"{what}: célula inválida: {cell!r}")
    return (cell[0], cell[1])


def _checked_narration(n, what: str) -> None:
    """Narração declarada válida: ``Narration`` com kind/text de
    texto e ``extra`` JSON puro (o mesmo crivo do ``_jsonify``)."""
    if n is None:
        return
    if not isinstance(n, Narration):
        raise IntentionError(f"{what}: não é uma Narration: {n!r}")
    if not isinstance(n.kind, str) or not isinstance(n.text, str):
        raise IntentionError(f"{what}: narração sem kind/text")
    try:
        extra = dict(n.extra)
    except (TypeError, ValueError) as exc:
        raise IntentionError(f"{what}: extra inválido") from exc
    if not all(isinstance(k, str) for k in extra):
        raise IntentionError(f"{what}: extra com chave não-texto")
    try:
        _jsonify(extra)
    except TypeError as exc:
        raise IntentionError(
            f"{what}: extra não serializável: {exc}") from exc


class Engine:
    def __init__(self, seed: int = 42, n_companies: int = 8,
                 god_events: list[dict] | None = None,
                 policy: Policy | None = None,
                 world_data: bool = True,
                 market_v2: bool = False,
                 market_params: dict | None = None,
                 country_v2: bool = False,
                 country_params: dict | None = None,
                 equip_v2: bool = False,
                 equip_params: dict | None = None):
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
        # País/política (B3) + comércio externo (B4a) — Degrau 1, Fase 3.
        # Desligado por padrão: nenhum estado, nenhum RNG, nenhum bloco
        # serializado — goldens da Fase 1 bit-idênticos. Ligado, os
        # parâmetros são DADO (mundo.countrydata) e S/e/τ viram séries
        # PÚBLICAS; as probabilidades dos eventos, nunca.
        self.country_v2 = country_v2
        self._ctry: dict | None = None
        self._countries: dict[str, dict] = {}
        self._resources_by_country: dict | None = None
        self._deposit_country_cache: dict[str, str] = {}
        self._election_offset: dict[str, int] = {}
        self._force_events: list[dict] = []
        self._parity_surcharge: dict[str, float] = {}
        self._capex_memo: dict = {}
        self._royalty_due: dict[int, float] = {}
        self.money_to_external = 0.0    # empresas -> resto do mundo (B4a)
        self.money_from_external = 0.0  # resto do mundo -> empresas (B4a)
        if country_v2:
            self._init_countries(country_params)
        # Equipamentos (B2) — Degrau 1, Fase 4. Desligado por padrão:
        # nenhum estado por instalação, nenhum RNG, nenhum bloco
        # serializado — goldens da Fase 1 bit-idênticos. Ligado, o
        # estado (idade/condição/retorno) vive no dict da instalação
        # (chave "equip", criada preguiçosamente) e os parâmetros são
        # DADO (mundo.equipdata).
        self.equip_v2 = equip_v2
        self._equip: dict | None = None
        self._equip_stats: dict[int, dict] = {}
        if equip_v2:
            self._init_equipment(equip_params)
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
        if country_v2:
            # B4a: massa que entra de fora do mapa é fonte externa
            # nomeada — a conservação fecha INCLUINDO a conta "externo"
            # (invariante da Fase 3, docs/DEGRAU1-DESIGN.md §4/B4a).
            # A chave só existe com a flag ligada: desligado, o
            # state_dict é byte-idêntico ao clássico.
            for led in self.ledger_mass.values():
                led["imported"] = 0.0
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
        em _produce e nas fases da política. Depósitos novos
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
                self._resources_by_country = None   # B3: cache invalida
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

    # -- decisões (delegadas à política plugável) -------------------------
    # _decide é a entrada da decisão: constrói a Observation da
    # empresa e delega para a política instalada (por padrão a
    # HeuristicPolicy). A política nunca recebe o motor nem a
    # empresa crua (guarda v2, docs/OBSERVATION-SPEC.md) e, desde a
    # fatia 3, não executa nada: decide devolve intenções
    # declarativas e quem as aplica é _apply_intentions, com
    # validação total antes da execução. Trocar a política não
    # toca o motor.
    # Fatia 4: as fachadas de fase da era v1 (_pick_deposit,
    # _build_downstream, _plan_buys, _buffer, _plan_sells) foram
    # APOSENTADAS — grep provou zero chamadores no repo (as fases
    # vivem na política e são orquestradas pelo decide). _reserve e
    # _use_tools permanecem como exceções registradas no
    # OBSERVATION-LOG: são a superfície de fase que os testes de
    # equipamentos/ferramentas exercitam direto.
    def _reserve(self, comp: Company) -> float:
        return self.policy.reserve(build_company_view(self, comp))

    def _decide(self, comp: Company) -> None:
        comp._offers = {}
        comp._buys = {}
        if not comp.alive:
            return
        obs = build_observation(self, comp, sealed_act=True)
        self._apply_intentions(comp, self.policy.decide(obs))

    def _use_tools(self, comp: Company) -> None:
        obs = build_observation(self, comp, sealed_act=True)
        self._apply_intentions(comp, self.policy.use_tools(obs))

    # -- intenções declarativas (fatia 3): validação e execução ------
    def _validate_intentions(self, comp: Company, intentions) -> list:
        """Confere a lista INTEIRA da decisão e devolve as intenções
        normalizadas — ou levanta ``IntentionError`` sem executar
        nada (atomicidade por decisão: decisão inválida não toca o
        mundo). O vocabulário e os alvos são os da focal: instalação
        de rival, claim de célula alheia, commodity inexistente e
        objeto forjado (que não seja instância das classes de
        intenção) são rejeitados aqui, não na execução."""
        if intentions is None \
                or not isinstance(intentions, (list, tuple)):
            raise IntentionError(
                "decide(obs) precisa devolver uma lista de intenções "
                "(mundo.intentions): o contrato imperativo acabou na "
                "fatia 3 — verbos não executam durante a decisão "
                "(docs/OBSERVATION-SPEC.md §4)")
        deposit_cells = {d.cell for d in self.deposits}
        own = set(comp.facilities)
        out = []
        for it in intentions:
            if not isinstance(it, INTENTION_TYPES):
                raise IntentionError(
                    f"objeto não é uma intenção declarada: {it!r}")
            if isinstance(it, Spend):
                if not _is_number(it.amount) or it.amount < 0:
                    raise IntentionError(
                        f"spend inválido: {it.amount!r}")
                if not isinstance(it.reason, str):
                    raise IntentionError("spend sem reason de texto")
            elif isinstance(it, Probe):
                if it.deposit not in self._deposit_by_name:
                    raise IntentionError(
                        f"probe de depósito desconhecido: "
                        f"{it.deposit!r}")
                _checked_narration(it.on_rich, "probe.on_rich")
                _checked_narration(it.on_poor, "probe.on_poor")
                if not _is_number(it.rich_threshold) \
                        or not _is_number(it.poor_threshold):
                    raise IntentionError("probe com limiar inválido")
            elif isinstance(it, RegisterClaim):
                cell = _checked_cell(it.cell, "register_claim")
                if cell not in deposit_cells:
                    raise IntentionError(
                        f"claim fora de célula de depósito: {cell!r}")
                owner = self.claimed_by.get(cell)
                if owner is not None and owner != comp.cid:
                    raise IntentionError(
                        f"claim de célula já reivindicada por rival: "
                        f"{cell!r}")
                it = replace(it, cell=cell)
            elif isinstance(it, BuildFacility):
                if it.kind not in chain.FACILITIES:
                    raise IntentionError(
                        f"construção de tipo desconhecido: {it.kind!r}")
                cell = _checked_cell(it.cell, "build_facility")
                if it.deposit is not None:
                    dep = self._deposit_by_name.get(it.deposit)
                    if dep is None:
                        raise IntentionError(
                            f"construção em depósito desconhecido: "
                            f"{it.deposit!r}")
                    if dep.cell != cell:
                        raise IntentionError(
                            "construção: a célula não é a do depósito")
                _checked_narration(it.narration,
                                   "build_facility.narration")
                it = replace(it, cell=cell)
            elif isinstance(it, Narrate):
                if it.narration is None:
                    raise IntentionError("narrate sem narração")
                _checked_narration(it.narration, "narrate")
            elif isinstance(it, NoteLink):
                if not isinstance(it.stage, int) \
                        or isinstance(it.stage, bool) \
                        or not 1 <= it.stage <= 5:
                    raise IntentionError(
                        f"note_link com elo inválido: {it.stage!r}")
            elif isinstance(it, (RepairFacility, MaintainFacility,
                                 OverhaulFacility)):
                if it.facility_id not in own:
                    raise IntentionError(
                        f"intenção sobre instalação que não é da "
                        f"empresa: {it.facility_id!r}")
            elif isinstance(it, (Buy, Offer)):
                if it.commodity not in chain.COMMODITIES:
                    raise IntentionError(
                        f"commodity fora do vocabulário: "
                        f"{it.commodity!r}")
                if not _is_number(it.qty) or it.qty < 0:
                    raise IntentionError(
                        f"quantidade inválida: {it.qty!r}")
            elif isinstance(it, SetTool):
                if it.tool not in ("insta", "zap", "vid", "loja"):
                    raise IntentionError(
                        f"ferramenta desconhecida: {it.tool!r}")
                if not isinstance(it.until, int) \
                        or isinstance(it.until, bool):
                    raise IntentionError(
                        f"set_tool com until inválido: {it.until!r}")
                if it.strength is not None \
                        and not _is_number(it.strength):
                    raise IntentionError(
                        "set_tool com strength inválido")
            out.append(it)
        return out

    def _apply_intentions(self, comp: Company, intentions) -> None:
        """Valida a decisão inteira e só então a executa, em ordem,
        despachando cada intenção para o verbo do ``Actuator`` —
        a ordem de execução é a ordem declarada, que é a ordem de
        mutação de sempre (fatia 3, docs/OBSERVATION-SPEC.md §4)."""
        act = Actuator(self, comp)
        for it in self._validate_intentions(comp, intentions):
            if isinstance(it, Spend):
                act.spend(it.amount, reason=it.reason)
            elif isinstance(it, Probe):
                grade, _size = act.probe(it.deposit)
                narration = None
                if grade >= it.rich_threshold:
                    narration = it.on_rich
                elif grade <= it.poor_threshold:
                    narration = it.on_poor
                if narration is not None:
                    act.narrate(narration.kind, narration.text,
                                **narration.extra_dict())
            elif isinstance(it, RegisterClaim):
                act.register_claim(it.cell)
            elif isinstance(it, BuildFacility):
                fac = act.build_facility(it.kind, it.cell,
                                         deposit=it.deposit)
                if it.narration is not None:
                    extra = it.narration.extra_dict()
                    extra["fid"] = fac.id
                    act.narrate(it.narration.kind, it.narration.text,
                                **extra)
            elif isinstance(it, Narrate):
                n = it.narration
                act.narrate(n.kind, n.text, **n.extra_dict())
            elif isinstance(it, NoteLink):
                act.note_link(it.stage)
            elif isinstance(it, RepairFacility):
                act.repair(it.facility_id)
            elif isinstance(it, MaintainFacility):
                act.maintain(it.facility_id)
            elif isinstance(it, OverhaulFacility):
                act.overhaul(it.facility_id)
            elif isinstance(it, Buy):
                act.buy(it.commodity, it.qty)
            elif isinstance(it, Offer):
                act.offer(it.commodity, it.qty)
            elif isinstance(it, SetTool):
                act.set_tool(it.tool, until=it.until,
                             strength=it.strength)

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

    # -- equipamentos (B2) --------------------------------------------------
    def _init_equipment(self, params_override: dict | None) -> None:
        self._equip = equipdata.resolve_equip_params(params_override)
        self._equip_stats = {c.cid: {"fac_ticks": 0, "down_ticks": 0,
                                     "breaks": 0, "repairs": 0,
                                     "maintenances": 0, "overhauls": 0}
                             for c in self.companies}

    def _fac_equip(self, fac: dict) -> dict:
        """Estado B2 da instalação (idade, condição, retorno de quebra),
        criado preguiçosamente na primeira operação com equip_v2 ligado.
        Desligado, este método nunca é chamado e o dict da instalação
        fica byte-idêntico ao clássico."""
        eq = fac.get("equip")
        if eq is None:
            eq = fac["equip"] = {"age": 0, "cond": 1.0, "down_until": -1,
                                 "broken": False, "repair_cost": 0.0,
                                 "repair_ticks": 0}
        return eq

    def facility_down(self, fac: dict) -> bool:
        """A instalação está parada NESTE tick? (quebrada à espera de
        reparo pago, ou dentro da janela de oficina.)"""
        eq = fac.get("equip")
        return bool(eq) and (eq["broken"] or self.tick <= eq["down_until"])

    def facility_condition(self, fac: dict) -> tuple[int, float, bool]:
        """(idade em meses, condição h, parada?) — a observação LEGAL
        das PRÓPRIAS instalações. De rivais, só o sintoma público: a
        notícia da quebra na crônica e a oferta que some do mercado.
        Somente leitura: não cria estado."""
        eq = fac.get("equip")
        if not eq:
            return (0, 1.0, False)
        return (eq["age"], eq["cond"], self.facility_down(fac))

    def _wear_and_roll(self, comp: Company, fac: dict, eq: dict,
                       utilization: float) -> None:
        """Desgaste do mês operado + sorteio de quebra (hazard discreto
        de Weibull sobre a idade, β≈1,6). Planta parada não chega aqui:
        mothball em bust é decisão real (design §4/B2)."""
        p = self._equip["facilities"][fac["kind"]]
        model = self._equip["model"]
        eq["cond"] = max(0.0, eq["cond"] - p["wear_rate"]
                         * utilization * model["wear_scale"])
        q = equipdata.weibull_hazard(eq["age"], p["eta_months"],
                                     p["beta"]) * model["hazard_scale"]
        if q > 0.0 and self.rng.random() < q:
            self._break_facility(comp, fac, eq)

    def _break_facility(self, comp: Company, fac: dict, eq: dict) -> None:
        model = self._equip["model"]
        build_cost = chain.FACILITIES[fac["kind"]]["cost"]
        eq["broken"] = True
        eq["repair_cost"] = build_cost * self.rng.uniform(
            model["repair_frac_min"], model["repair_frac_max"])
        raw = self.rng.lognormvariate(model["repair_ticks_lognorm_mu"],
                                      model["repair_ticks_lognorm_sigma"])
        eq["repair_ticks"] = max(int(model["repair_ticks_min"]),
                                  min(int(model["repair_ticks_max"]),
                                      round(raw)))
        self._equip_stats[comp.cid]["breaks"] += 1
        link = chain.FACILITY_LINK[fac["kind"]]
        self.chronicle.add(
            self.tick, "breakdown",
            f"QUEBRA: a instalação de {link} da {comp.name} quebra com "
            f"{eq['age']} meses de operação e condição a "
            f"{eq['cond']:.0%} — parada até a empresa pagar o reparo de "
            f"US$ {eq['repair_cost']:,.0f} (estimativa: "
            f"{eq['repair_ticks']} mês(es) de oficina).", comp.name,
            cid=comp.cid, fid=fac["id"], facility_kind=fac["kind"],
            age=eq["age"], condition=eq["cond"],
            repair_cost=eq["repair_cost"],
            repair_ticks=eq["repair_ticks"])

    def repair_facility(self, comp: Company, fac: dict) -> None:
        """A política decidiu consertar: paga o reparo (sink nomeado
        nos flows) e a instalação volta após `repair_ticks` meses de
        oficina. Sem reparo automático: quebrada, ela espera a decisão."""
        eq = self._fac_equip(fac)
        cost = eq["repair_cost"]
        self._spend(comp, cost, reason="repair")
        eq["broken"] = False
        eq["down_until"] = self.tick + eq["repair_ticks"] - 1
        self._equip_stats[comp.cid]["repairs"] += 1
        link = chain.FACILITY_LINK[fac["kind"]]
        self.chronicle.add(
            self.tick, "maintenance",
            f"REPARO: {comp.name} paga US$ {cost:,.0f} e manda sua "
            f"instalação de {link} para a oficina — volta em "
            f"{eq['repair_ticks']} mês(es).", comp.name,
            cid=comp.cid, fid=fac["id"], facility_kind=fac["kind"],
            action="repair", cost=cost, repair_ticks=eq["repair_ticks"])

    def maintain_facility(self, comp: Company, fac: dict) -> None:
        """Manutenção preventiva decidida pela política: paga
        maint_frac do custo de construção (sink nomeado) e restaura h
        em +maint_restore (teto 1,0). Com h <= maint_downtime_h a
        planta para 1 tick para o serviço; acima disso, é rotina —
        registrada nos flows, narrada só quando para a planta."""
        eq = self._fac_equip(fac)
        model = self._equip["model"]
        cost = chain.FACILITIES[fac["kind"]]["cost"] * model["maint_frac"]
        self._spend(comp, cost, reason="maintenance")
        before = eq["cond"]
        eq["cond"] = min(1.0, before + model["maint_restore"])
        self._equip_stats[comp.cid]["maintenances"] += 1
        if before <= model["maint_downtime_h"]:
            eq["down_until"] = max(eq["down_until"], self.tick)
            link = chain.FACILITY_LINK[fac["kind"]]
            self.chronicle.add(
                self.tick, "maintenance",
                f"MANUTENÇÃO PESADA: {comp.name} para sua instalação de "
                f"{link} por um mês para salvar uma condição de "
                f"{before:.0%} (US$ {cost:,.0f}) — sai da oficina a "
                f"{eq['cond']:.0%}.", comp.name,
                cid=comp.cid, fid=fac["id"], facility_kind=fac["kind"],
                action="preventive", cost=cost, condition_before=before,
                condition_after=eq["cond"])

    def overhaul_facility(self, comp: Company, fac: dict) -> None:
        """Overhaul decidido pela política: 60% do custo de construção
        (sink nomeado) zeram idade e condição — é a troca da planta
        sem trocar a planta, e o que derruba o hazard de Weibull."""
        eq = self._fac_equip(fac)
        model = self._equip["model"]
        cost = chain.FACILITIES[fac["kind"]]["cost"] \
            * model["overhaul_frac"]
        self._spend(comp, cost, reason="overhaul")
        age_before = eq["age"]
        eq["age"] = 0
        eq["cond"] = 1.0
        self._equip_stats[comp.cid]["overhauls"] += 1
        link = chain.FACILITY_LINK[fac["kind"]]
        self.chronicle.add(
            self.tick, "maintenance",
            f"OVERHAUL: {comp.name} gasta US$ {cost:,.0f} e reconstrói "
            f"sua instalação de {link} por dentro — {age_before} meses "
            f"de idade viram planta nova.", comp.name,
            cid=comp.cid, fid=fac["id"], facility_kind=fac["kind"],
            action="overhaul", cost=cost, age_before=age_before)

    def equipment_summary(self) -> dict:
        """Disponibilidade e contadores de equipamento por empresa (B2):
        o placar que o notebook de veredito da Fase 4 lê. Disponibilidade
        = 1 − meses parada / meses de instalação (quebra + oficina)."""
        companies = {}
        tot_fac = tot_down = 0
        for c in self.companies:
            st = dict(self._equip_stats.get(c.cid, {}))
            ft = st.get("fac_ticks", 0)
            dt = st.get("down_ticks", 0)
            tot_fac += ft
            tot_down += dt
            st["archetype"] = c.archetype
            st["availability"] = (1.0 - dt / ft) if ft else 1.0
            companies[c.name] = st
        return {"companies": companies,
                "fleet": {"fac_ticks": tot_fac, "down_ticks": tot_down,
                          "availability": (1.0 - tot_down / tot_fac)
                          if tot_fac else 1.0}}

    # -- produção -----------------------------------------------------------
    def _produce(self, comp: Company) -> None:
        if not comp.alive:
            return
        for fac in list(comp.facilities.values()):
            kind = fac["kind"]
            cap = chain.FACILITIES[kind]["capacity"]
            cost = chain.OPERATING_COST[kind]
            eq = None
            thru = 0.0
            if self.equip_v2:
                eq = self._fac_equip(fac)
                st = self._equip_stats[comp.cid]
                st["fac_ticks"] += 1
                eq["age"] += 1
                if eq["broken"] or self.tick <= eq["down_until"]:
                    st["down_ticks"] += 1
                    continue    # B2: quebrada/em oficina — não produz,
                                # não paga opex, não desgasta
                cap = equipdata.effective_capacity(
                    cap, eq["cond"], eq["age"], self._equip["model"])
            if kind == "mine":
                dep = self._deposit_by_name[fac["deposit"]]
                if self.country_v2 \
                        and self._is_halted(self.deposit_country(dep)):
                    continue    # B3: paralisação no país — nem produz,
                                # nem paga opex (a mina está parada)
                crude = min(cap, self.remaining[dep.name])
                if crude <= 0:
                    continue
                thru = crude
                self.remaining[dep.name] -= crude
                payable = crude * dep.grade
                waste = crude - payable
                comp.stocks.add(chain.COMMODITY_INDEX[dep.resource], payable)
                self.ledger_mass[dep.resource]["extracted"] += payable
                self.ledger_mass[dep.resource]["wasted"] += waste
                self._ops_spend(comp, self.deposit_country(dep),
                                crude * cost)
            elif kind == "refinery":
                budget = cap
                for raw, refined in chain.RAW_TO_REFINED.items():
                    if budget <= 0:
                        break
                    qty = min(comp.stocks[raw], budget)
                    if qty <= 0:
                        continue
                    budget -= qty
                    thru += qty
                    self._convert(comp, raw, qty, refined,
                                  qty * chain.REFINE_YIELD)
                    self._ops_spend(comp, self.city_country(comp.hq_city),
                                    qty * cost)
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
                thru = units * recipe["out"]
                for inp, per in recipe["inputs"].items():
                    qty = units * per
                    comp.stocks.add(chain.COMMODITY_INDEX[inp], -qty)
                    self.ledger_mass[inp]["consumed"] += qty
                comp.stocks.add(chain.COMMODITY_INDEX[product],
                                units * recipe["out"])
                self.ledger_mass[product]["produced"] += units * recipe["out"]
                self._ops_spend(comp, self.city_country(comp.hq_city),
                                units * cost)
                if product == "supercomputer":
                    self.total_supercomputers += units
                    self._super_by_cid[comp.cid] = \
                        self._super_by_cid.get(comp.cid, 0.0) + units
                    self.chronicle.add(self.tick, "record",
                                       f"{comp.name} entrega um SUPERCOMPUTADOR "
                                       f"montado por conta própria.", comp.name)
            if eq is not None and thru > 0.0:
                # B2: operou -> desgasta pela utilização e rola a quebra
                self._wear_and_roll(comp, fac, eq,
                                    thru / cap if cap > 0 else 0.0)
        if self.country_v2:
            # royalties do tick de produção, lançados de uma vez
            due = self._royalty_due.pop(comp.cid, 0.0)
            if due > 0.0:
                self._spend(comp, due, reason="royalty")

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
        # B4a: restos e recebimentos rastreados para o participante
        # externo — só quando importações são possíveis (preço acima
        # da paridade); desligado ou dentro da banda, nada disto é lido
        offered_left = {c.cid: q for c, q in offers}
        city_sold = 0.0
        received = {} if self.country_v2 \
            and price > self._parity(commodity)[0] else None
        if total_supply > 0:
            # 1) comércio entre empresas (dinheiro interno: soma zero)
            sold_internal = 0.0
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
                    if received is not None:
                        received[buyer.cid] = \
                            received.get(buyer.cid, 0.0) + share
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
                    city_sold += qty
                    if commodity == "device" \
                            and seller.tools.loja_active(self.tick):
                        fee = qty * price * LOJA_FEE_PCT
                        seller.cash -= fee
                        self.money_out += fee
                        self._flow(seller.cid, "spend_tools", -fee)
        # B4a: o resto do planeta na paridade (só com country_v2)
        imported = exported = 0.0
        if self.country_v2:
            unfilled_buyers = None
            if received is not None:
                unfilled_buyers = [
                    (comp, want - received.get(comp.cid, 0.0))
                    for comp, want in buys
                    if want - received.get(comp.cid, 0.0) > 0.0001]
            imported, exported = self._external_trade(
                commodity, offers, offered_left, unfilled_buyers, price,
                city_q - city_sold)
        # demanda realizada -> EMA pública (a régua da cobertura)
        demand_total = internal_demand + city_q
        alpha = self._mkt["model"].get("ema_alpha", 0.1)
        ema = self._demand_ema[commodity]
        self._demand_ema[commodity] = ema + alpha * (demand_total - ema)
        # 3) preço: desequilíbrio (com o fluxo externo, quando há) +
        # perseguição do justo; banda da âncora
        ratio_demand = demand_total + exported
        ratio_supply = total_supply + imported
        ratio = (ratio_demand - ratio_supply) \
            / max(ratio_demand, ratio_supply, 1.0)
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

    # -- país e política (B3) + comércio externo (B4a) ---------------------
    def _init_countries(self, params_override: dict | None) -> None:
        self._ctry = countrydata.resolve_country_params(params_override)
        params = self._ctry["countries"]
        names = set()
        for d in self.deposits:
            names.add(self.deposit_country(d))
        for c in self.cities:
            names.add(self.city_country(c.name))
        for name in sorted(names):
            p = params[name]
            self._countries[name] = {
                "S": float(p["stability_mean"]),
                "S_mean": float(p["stability_mean"]),
                "fx": 1.0, "tau": float(p["royalty"]),
                "halt_until": -1, "restrictions": {},
            }
        self._force_events = list(self._ctry.get("force_events") or [])
        self._rebuild_election_offsets()

    def _rebuild_election_offsets(self) -> None:
        stagger = int(self._ctry["model"]["election_stagger"]) \
            if self._ctry else 6
        self._election_offset = {name: i * stagger for i, name
                                 in enumerate(sorted(self._countries))}

    def deposit_country(self, dep: Deposit) -> str:
        """País do depósito (mapa por nome; descoberta de Deus resolve
        pelo vizinho conhecido — função pura das tabelas estáticas,
        idêntica antes e depois de um restore)."""
        got = self._deposit_country_cache.get(dep.name)
        if got is None:
            got = countrydata.country_of_deposit(dep)
            self._deposit_country_cache[dep.name] = got
        return got

    def city_country(self, city_name: str) -> str:
        if city_name in countrydata.CITY_COUNTRIES:
            return countrydata.CITY_COUNTRIES[city_name]
        city = self._city_by_name.get(city_name)
        return countrydata.country_of_city(city) if city else "Brasil"

    def capex_mult(self, country: str) -> float:
        """Prêmio de risco-país sobre o capex: ×(1 + 0,25·(1−S)).
        Desligado (ou país fora do mundo), é exatamente 1,0 — as
        políticas multiplicam por ele sem mudar um bit do clássico."""
        if not self.country_v2:
            return 1.0
        st = self._countries.get(country)
        if st is None:
            return 1.0
        key = (country, st["S"])
        got = self._capex_memo.get(key)
        if got is None:
            got = 1.0 + self._ctry["model"]["capex_premium"] \
                * (1.0 - st["S"])
            self._capex_memo[key] = got
        return got

    def country_state(self, name: str) -> dict:
        """Os índices PÚBLICOS de um país: estabilidade, câmbio e
        royalties são publicados na vida real — qualquer empresa os lê.
        As probabilidades dos eventos políticos, nunca."""
        st = self._countries[name]
        return {"S": st["S"], "fx": st["fx"], "tau": st["tau"]}

    def _is_halted(self, country: str) -> bool:
        st = self._countries.get(country)
        return st is not None and self.tick <= st["halt_until"]

    def _ops_spend(self, comp: Company, country: str, amount: float) -> None:
        """Opex de uma instalação, com B3 ligado: a fração local
        (λ≈0,45) é precificada em moeda local (o câmbio e barateia ou
        encarece o custo em US$) e os royalties τ do país incidem sobre
        o opex como sink nomeado no ledger — acumulados por empresa e
        lançados uma vez por tick de produção (a soma, na mesma ordem
        das instalações, é a mesma; o que some é a chamada por
        instalação). Desligado, é o _spend de sempre — bit-idêntico."""
        if not self.country_v2:
            self._spend(comp, amount, reason="ops")
            return
        st = self._countries[country]
        lam = self._ctry["model"]["local_opex_frac"]
        eff = amount * ((1.0 - lam) + lam / st["fx"])
        self._spend(comp, eff, reason="ops")
        royalty = eff * st["tau"]
        if royalty > 0.0:
            self._royalty_due[comp.cid] = \
                self._royalty_due.get(comp.cid, 0.0) + royalty

    def _country_resources(self, country: str) -> list[str]:
        """Recursos minerais do país — cache preguiçoso sobre os
        depósitos (descoberta de Deus invalida; restore reconstrói da
        lista restaurada, deterministicamente)."""
        cache = self._resources_by_country
        if cache is None:
            by_country: dict[str, set] = {}
            for d in self.deposits:
                by_country.setdefault(self.deposit_country(d),
                                      set()).add(d.resource)
            cache = self._resources_by_country = \
                {k: sorted(v) for k, v in by_country.items()}
        return cache.get(country, [])

    def _hottest_resource(self, country: str) -> str | None:
        res = self._country_resources(country)
        if not res:
            return None
        return max(res, key=lambda r: (
            self.prices[r] / self.anchors[r] if self.anchors[r] else 0.0, r))

    def _reform_hot(self, country: str) -> bool:
        """O acoplamento B1->B3: commodity do país acima de 1,5× a
        âncora (a âncora pública do B1; sem B1, o preço-base) DOBRA a
        probabilidade de reforma de royalties — governo intervém
        quando a commodity está cara, não quando está barata."""
        ratio = self._ctry["model"]["reform_hot_ratio"]
        return any(self.prices[r] > ratio * self.anchors[r]
                   for r in self._country_resources(country))

    def _apply_political_event(self, country: str, event: str,
                               resource: str | None = None) -> None:
        st = self._countries.get(country)
        if st is None:
            raise ValueError(f"evento político fora do mundo: {country!r}")
        m = self._ctry["model"]
        res_text = None
        if event == "royalty_reform":
            st["tau"] = min(m["tau_max"], st["tau"] + m["reform_tau_step"])
            res_text = resource or self._hottest_resource(country)
            alvo = f" com {res_text} em alta" if res_text else ""
            text = (f"REFORMA DE ROYALTIES: {country} eleva os royalties "
                    f"da mineração{alvo} — a alíquota sobre o opex sobe "
                    f"para {st['tau']:.1%} e operar no país fica mais caro.")
        elif event == "export_restriction":
            res = resource or \
                self.rng.choice(self._country_resources(country))
            months = int(m["restriction_months"])
            st["restrictions"][res] = self.tick + months - 1
            res_text = res
            text = (f"RESTRIÇÃO DE EXPORTAÇÃO: {country} restringe as "
                    f"exportações de {res} por {months} meses — a "
                    f"paridade mundial de {res} e de "
                    f"{chain.RAW_TO_REFINED[res]} dispara e importar "
                    f"fica mais caro em todo o mapa.")
        elif event == "state_jv":
            st["S_mean"] = max(m["smean_min"],
                               st["S_mean"] - m["jv_smean_drop"])
            st["tau"] = min(m["tau_max"], st["tau"] + m["jv_tau_step"])
            res_text = resource or \
                (self._country_resources(country) or [None])[0]
            alvo = f" de {res_text}" if res_text else ""
            text = (f"PARTICIPAÇÃO ESTATAL: {country} impõe joint "
                    f"venture com estatal majoritária nos projetos"
                    f"{alvo} — a confiança do investidor cai "
                    f"(estabilidade média em {st['S_mean']:.2f}) e os "
                    f"royalties sobem para {st['tau']:.1%}.")
        elif event == "judicial_halt":
            months = int(m["halt_months_judicial"])
            st["halt_until"] = max(st["halt_until"],
                                   self.tick + months - 1)
            text = (f"PARALISAÇÃO JUDICIAL: a Justiça de {country} "
                    f"suspende as minas do país por {months} meses — "
                    f"produção zerada enquanto durar a liminar (o "
                    f"fantasma de Cobre Panamá).")
        elif event == "subsidy":
            st["tau"] = max(m["tau_min"],
                            st["tau"] + m["subsidy_tau_step"])
            st["S_mean"] = min(m["smean_max"],
                               st["S_mean"] + m["subsidy_smean_gain"])
            text = (f"SUBSÍDIO: {country} lança um pacote de incentivo "
                    f"à mineração e à indústria — royalties caem para "
                    f"{st['tau']:.1%} do opex e a estabilidade média "
                    f"sobe para {st['S_mean']:.2f}.")
        elif event == "disaster":
            months = int(m["halt_months_disaster"])
            st["halt_until"] = max(st["halt_until"],
                                   self.tick + months - 1)
            st["S"] = max(m["s_min"], st["S"] - m["disaster_s_shock"])
            text = (f"DESASTRE NATURAL: um evento extremo atinge "
                    f"{country} — minas paradas por {months} meses e a "
                    f"estabilidade do país desaba para {st['S']:.2f}.")
        elif event == "election":
            shift = self.rng.uniform(-m["election_smean_shift"],
                                     m["election_smean_shift"])
            st["S_mean"] = min(m["smean_max"],
                               max(m["smean_min"], st["S_mean"] + shift))
            step = self.rng.choice(list(m["election_tau_steps"]))
            st["tau"] = min(m["tau_max"],
                            max(m["tau_min"], st["tau"] + step))
            text = (f"ELEIÇÃO em {country}: o novo governo reposiciona "
                    f"o país — estabilidade média em {st['S_mean']:.2f} "
                    f"e royalties em {st['tau']:.1%} do opex.")
        else:
            raise ValueError(f"evento político desconhecido: {event!r}")
        self.chronicle.add(self.tick, "politics", text, None,
                           event=event, country=country,
                           commodity=res_text, tau=st["tau"], S=st["S"],
                           S_mean=st["S_mean"])

    def _advance_politics(self) -> None:
        """Um mês de política por país: S com reversão à média, câmbio
        perseguindo a estabilidade, eleições no calendário e o motor
        de eventos endógeno com as frequências ancoradas (por ano ->
        por mês). Consome RNG sempre na mesma ordem (países ordenados,
        eventos em ordem fixa); desligado, não consome nada. Os
        eventos FORÇADOS (force_events dos parâmetros — gancho de
        teste e de Deus) não consomem RNG."""
        m = self._ctry["model"]
        yearly = self._ctry["events_yearly"]
        rnd, gauss = self.rng.random, self.rng.gauss
        mp = countrydata.monthly_prob
        self._capex_memo.clear()   # S anda neste avanço: memo do tick novo
        for fe in self._force_events:
            if fe["tick"] == self.tick:
                self._apply_political_event(
                    countrydata.normalize_country(fe["country"]),
                    fe["event"], fe.get("resource"))
        period = int(m["election_period"])
        for name in sorted(self._countries):
            st = self._countries[name]
            st["S"] = min(m["s_max"], max(m["s_min"],
                          st["S"] + m["s_reversion"]
                          * (st["S_mean"] - st["S"])
                          + gauss(0.0, m["s_sigma"])))
            target = 1.0 + m["fx_beta"] * (st["S_mean"] - st["S"])
            st["fx"] = min(m["fx_max"], max(m["fx_min"],
                           st["fx"] + m["fx_reversion"]
                           * (target - st["fx"])
                           + gauss(0.0, m["fx_sigma"])))
            if self.tick > 0 \
                    and (self.tick - self._election_offset[name]) % period == 0:
                self._apply_political_event(name, "election")
            p_reform = mp(yearly["royalty_reform"])
            if self._reform_hot(name):
                p_reform = min(1.0, 2.0 * p_reform)
            if rnd() < p_reform:
                self._apply_political_event(name, "royalty_reform")
            if self._country_resources(name):
                if rnd() < mp(yearly["export_restriction"]):
                    self._apply_political_event(name, "export_restriction")
                if rnd() < mp(yearly["state_jv"]):
                    self._apply_political_event(name, "state_jv")
                if rnd() < mp(yearly["judicial_halt"]):
                    self._apply_political_event(name, "judicial_halt")
            if rnd() < mp(yearly["subsidy"]):
                self._apply_political_event(name, "subsidy")
            if rnd() < mp(yearly["disaster"]):
                self._apply_political_event(name, "disaster")
        # B4a: restrição ativa encarece a paridade da commodity (e do
        # seu refinado) — é por aqui que a política morde o mercado.
        self._parity_surcharge = {}
        mult = 1.0 + m["restriction_parity_surcharge"]
        for st in self._countries.values():
            for res, until in st["restrictions"].items():
                if self.tick <= until:
                    for c in (res, chain.RAW_TO_REFINED.get(res)):
                        if c:
                            self._parity_surcharge[c] = max(
                                self._parity_surcharge.get(c, 1.0), mult)

    # -- comércio externo (B4a) ----------------------------------------------
    def _parity(self, commodity: str) -> tuple[float, float]:
        """(paridade de importação, paridade de exportação) da
        commodity: âncora × (1 + tarifa + frete) / âncora × (1 − frete),
        com o multiplicador das restrições de exportação ativas."""
        trade = self._ctry["trade"]
        anchor = self.anchors[commodity]
        mult = self._parity_surcharge.get(commodity, 1.0)
        return (anchor * (1.0 + trade["tariff"] + trade["freight"]) * mult,
                anchor * (1.0 - trade["freight"]) * mult)

    def parity_prices(self, commodity: str) -> tuple[float, float] | None:
        """Paridades PÚBLICAS do comércio externo (B4a ligado)."""
        if not self.country_v2:
            return None
        return self._parity(commodity)

    def _external_capacity(self, commodity: str) -> float:
        """Escala mensal do participante externo na commodity: fator
        sobre a demanda das cidades (ou a escala de minério, para os
        brutos, que não têm demanda urbana)."""
        trade = self._ctry["trade"]
        scale = max(chain.CITY_DEMAND.get(commodity, 0.0),
                    trade["ore_scale"])
        return scale * trade["capacity_factor"]

    def _external_trade(self, commodity: str, offers: list,
                        offered_left: dict,
                        unfilled_buyers: list | None,
                        price: float, city_unfilled: float
                        ) -> tuple[float, float]:
        """B4a — o resto do planeta como participante elástico.

        Preço acima da paridade de importação: o exterior VENDE ao
        mercado interno — primeiro às compras das empresas que o
        mercado interno não atendeu (a massa entra como `imported` no
        ledger e o dinheiro sai das empresas para a conta externo),
        depois à demanda das cidades não atendida (a massa atravessa:
        `imported` e `sold_external` se cancelam no estoque). Preço
        abaixo da paridade de exportação: o exterior COMPRA o
        excedente ofertado (massa sai como `sold_external`, dinheiro
        entra da conta externo). Retorna (importado, exportado) para a
        formação de preço enxergar a oferta/demanda efetiva — é assim
        que a paridade tampa explosões e amortece colapsos."""
        ci = chain.COMMODITY_INDEX[commodity]
        trade = self._ctry["trade"]
        p_imp, p_exp = self._parity(commodity)
        cap = self._external_capacity(commodity)
        cap_max = cap * trade["max_spread_mult"]
        imported = exported = 0.0
        if price > p_imp and (unfilled_buyers or city_unfilled > 0.0001):
            budget = min(cap * (price / p_imp - 1.0), cap_max)
            for comp, unfilled in (unfilled_buyers or []):
                if budget <= 0:
                    break
                qty = min(unfilled, budget,
                          comp.cash / price if price > 0 else 0.0)
                if qty <= 0.0001:
                    continue
                comp.stocks.add(ci, qty)
                comp.cash -= qty * price
                self._flow(comp.cid, "import_buy", -qty * price)
                self.money_to_external += qty * price
                self.ledger_mass[commodity]["imported"] += qty
                imported += qty
                budget -= qty
            if budget > 0 and city_unfilled > 0.0001:
                qty = min(city_unfilled, budget)
                self.ledger_mass[commodity]["imported"] += qty
                self.ledger_mass[commodity]["sold_external"] += qty
                imported += qty
                budget -= qty
        if price < p_exp and offers:
            budget = min(cap * (1.0 - price / p_exp), cap_max)
            for seller, _q in offers:
                if budget <= 0:
                    break
                left = offered_left.get(seller.cid, 0.0)
                if left <= 0.0001:
                    continue
                qty = min(left, budget)
                seller.stocks.add(ci, -qty)
                seller.cash += qty * price
                self._flow(seller.cid, "export_sale", qty * price)
                self.money_from_external += qty * price
                self.ledger_mass[commodity]["sold_external"] += qty
                offered_left[seller.cid] -= qty
                exported += qty
                budget -= qty
        return imported, exported

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
            if total_supply <= 0 and not self.country_v2:
                continue    # sem oferta interna E sem B4a, nada acontece;
                            # com B4a, importações ainda atendem compras
            # 1) comércio entre empresas (dinheiro interno: soma zero)
            internal_demand = sum(q for _, q in buys)
            sold_internal = 0.0
            offered_left = {c.cid: q for c, q in offers}
            city_sold = 0.0
            received = {} if self.country_v2 \
                and price > self._parity(commodity)[0] else None
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
                    if received is not None:
                        received[buyer.cid] = \
                            received.get(buyer.cid, 0.0) + share
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
                    city_sold += qty
                    # LojaSim: a venda passou pela prateleira do marketplace
                    # — a comissão é sink (vai ao "mundo"), via ledger/flows.
                    if commodity == "device" \
                            and seller.tools.loja_active(self.tick):
                        fee = qty * price * LOJA_FEE_PCT
                        seller.cash -= fee
                        self.money_out += fee
                        self._flow(seller.cid, "spend_tools", -fee)
            # B4a: o resto do planeta na paridade (só com country_v2) —
            # importações viram oferta efetiva e exportações, demanda
            # efetiva, na formação de preço abaixo
            if self.country_v2:
                unfilled_buyers = None
                if received is not None:
                    unfilled_buyers = [
                        (comp, want - received.get(comp.cid, 0.0))
                        for comp, want in buys
                        if want - received.get(comp.cid, 0.0) > 0.0001]
                imported, exported = self._external_trade(
                    commodity, offers, offered_left, unfilled_buyers,
                    price, city_q - city_sold)
                demand_extra, supply_extra = exported, imported
            else:
                demand_extra = supply_extra = 0.0
            # 3) ajuste de preço por desequilíbrio
            demand = internal_demand + city_q + demand_extra
            total_supply += supply_extra
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
        if self.equip_v2 and comp.facilities and any(
                f.get("equip", {}).get("broken")
                for f in comp.facilities.values()):
            return "quebra", ("rodou a frota até quebrar — os reparos "
                              "adiados comeram o caixa")
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
    def _frame_facility(self, fac: dict) -> dict:
        """A instalação como o frame a mostra. Com B2 ligado, o frame
        carrega o sintoma PÚBLICO do equipamento (idade, condição,
        parada) — é o que o mercado e o Deus veem; desligado, o frame
        é byte-idêntico ao clássico."""
        out = {"kind": fac["kind"], "cell": list(fac["cell"]),
               "deposit": fac.get("deposit")}
        if self.equip_v2:
            age, cond, down = self.facility_condition(fac)
            out["age"] = age
            out["condition"] = round(cond, 3)
            out["down"] = down
        return out

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
                "facilities": [self._frame_facility(f)
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
        if self.country_v2:
            # índices PÚBLICOS por país (S/e/τ são publicados) e as
            # paridades do comércio externo — nada privado nestes blocos
            frame["politics"] = {
                name: {"S": round(st["S"], 3), "fx": round(st["fx"], 3),
                       "tau": round(st["tau"], 4)}
                for name, st in sorted(self._countries.items())}
            frame["trade"] = {
                c: {"parity_import": round(self._parity(c)[0], 2),
                    "parity_export": round(self._parity(c)[1], 2)}
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
        if self.country_v2:
            self._advance_politics()
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
        if self.equip_v2:
            # disponibilidade e contadores de equipamento (B2)
            res["equipment"] = self.equipment_summary()
        if self.country_v2:
            # índices públicos por país + a conta "externo" do B4a
            res["politics"] = {name: self.country_state(name)
                               for name in sorted(self._countries)}
            res["trade"] = {
                "money_to_external": self.money_to_external,
                "money_from_external": self.money_from_external,
                "imported": {c: self.ledger_mass[c].get("imported", 0.0)
                             for c in chain.COMMODITIES},
                "parity_import": {c: self._parity(c)[0]
                                  for c in chain.COMMODITIES},
                "parity_export": {c: self._parity(c)[1]
                                  for c in chain.COMMODITIES},
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
        if self.equip_v2:
            # bloco presente SÓ com o B2 ligado: desligado, o state_dict
            # é byte-idêntico ao clássico (goldens da Fase 1). O estado
            # por instalação viaja nos dicts das instalações (chave
            # "equip"); aqui vão parâmetros e contadores.
            state["equip_v2"] = {
                "params": copy.deepcopy(self._equip),
                "stats": {str(cid): dict(st)
                          for cid, st in self._equip_stats.items()},
            }
        if self.country_v2:
            # bloco presente SÓ com B3/B4a ligados: desligado, o
            # state_dict é byte-idêntico ao clássico (goldens da Fase 1)
            state["country_v2"] = {
                "params": copy.deepcopy(self._ctry),
                "countries": copy.deepcopy(self._countries),
                "money_to_external": self.money_to_external,
                "money_from_external": self.money_from_external,
                "parity_surcharge": dict(self._parity_surcharge),
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
        # país/política: states clássicos não têm o bloco -> desligado
        ct = state.get("country_v2")
        eng.country_v2 = bool(ct)
        eng._ctry = None
        eng._countries = {}
        eng._resources_by_country = None
        eng._deposit_country_cache = {}
        eng._election_offset = {}
        eng._force_events = []
        eng._parity_surcharge = {}
        eng._capex_memo = {}
        eng._royalty_due = {}
        eng.money_to_external = 0.0
        eng.money_from_external = 0.0
        if ct:
            eng._ctry = countrydata._validate(copy.deepcopy(ct["params"]))
            eng._countries = copy.deepcopy(ct["countries"])
            eng.money_to_external = ct["money_to_external"]
            eng.money_from_external = ct["money_from_external"]
            eng._parity_surcharge = dict(ct.get("parity_surcharge", {}))
            eng._force_events = list(eng._ctry.get("force_events") or [])
            eng._rebuild_election_offsets()
        # equipamentos: states sem o bloco -> segue desligado
        eqb = state.get("equip_v2")
        eng.equip_v2 = bool(eqb)
        eng._equip = None
        eng._equip_stats = {}
        if eqb:
            eng._equip = equipdata._validate(copy.deepcopy(eqb["params"]))
            eng._equip_stats = {int(cid): dict(st)
                                for cid, st in eqb["stats"].items()}
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
