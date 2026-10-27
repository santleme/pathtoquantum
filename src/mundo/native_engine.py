"""Backend nativo do motor (Degrau 1, Fase 5) — opt-in.

`NativeEngine` expõe a mesma superfície do `Engine` de referência
(seed/n_companies/god_events/policy/world_data e as três flags do
mundo vivo; step/run/result/state_dict/from_state), mas quem executa
o `step()` é o núcleo C++/nanobind de `mundo/native/`, bit-idêntico ao
Python por construção (MT19937 do CPython, Neumaier onde o motor usa
sum(), sem contração FMA). O núcleo emite registros de evento
estruturados; ESTA camada formata a Crônica com os mesmos templates
de texto do motor de referência — por isso a crônica, os frames e o
state_dict saem idênticos, não só os números.

Limites do backend (declarados, não escondidos):
- a política suportada é a HeuristicPolicy (a do motor oficial);
  política customizada -> ValueError, use o Engine Python;
- sem toolchain C++ (g++/nanobind), `native.available()` é False e a
  construção levanta RuntimeError — o caminho Python puro nunca é
  afetado.
"""
from __future__ import annotations

import copy
from dataclasses import asdict

from . import chain, countrydata, equipdata, marketdata, native
from .chronicle import Chronicle, Event, sim_date
from .engine import HeuristicPolicy, _resolve_world
from .tools_sim import (LOJA_FEE_PCT, insta_campaign_cost, loja_store_cost,
                        vid_campaign_cost, zap_campaign_cost)

START_YEAR = 2027

_STAGE_NAMES = {1: "extração", 2: "refino", 3: "componentes",
                4: "dispositivos", 5: "supercomputador"}
_FACILITY_LINK = chain.FACILITY_LINK
_FACILITY_TEXTS = {
    "refinery": "{name} inaugura sua refinaria em {hq} — "
                "o refino agora é dentro de casa.",
    "factory": "{name} ergue uma fábrica de componentes em {hq}.",
    "plant": "{name} abre sua planta de dispositivos — "
             "a cadeia sobe mais um elo.",
    "assembly": "{name} anuncia a montadora de SUPERCOMPUTADORES. "
                "O topo da cadeia está ao alcance.",
}
_CAUSE_PHRASES = {
    "capex": "expandiu rápido demais — o capex recente devorou o caixa",
    "aquisicao": "alavancou-se comprando os ativos de uma rival",
    "quebra": "rodou a frota até quebrar — os reparos adiados "
              "comeram o caixa",
    "sem_operacao": "queimou o caixa sem montar operação",
    "operacao": "operou no prejuízo — custos acima da receita "
                "e estoque parado",
    "caixa": "ficou sem caixa",
}


def _deposit_int_fields(deposits) -> dict[str, set]:
    """Campos inteiros dos depósitos na fonte Python (o mundo builtin
    declara size_t como int; o núcleo guarda double). O state_dict
    precisa devolver o MESMO tipo, ou o hash muda sem a simulação
    mudar. Vale para deposits e para o knowledge das empresas."""
    out: dict[str, set] = {}
    for d in deposits:
        fields = {f for f in ("size_t", "grade", "lat", "lon")
                  if isinstance(getattr(d, f, None), int)
                  and not isinstance(getattr(d, f, None), bool)}
        if fields:
            out[d.name] = fields
    return out


def _normalize_force_events(params: dict | None) -> list[dict]:
    """force_events dos parâmetros -> forma normalizada p/ o núcleo
    (país canônico via countrydata.normalize_country, como o motor)."""
    out = []
    for fe in (params or {}).get("force_events") or []:
        item = {"tick": fe["tick"],
                "country": countrydata.normalize_country(fe["country"]),
                "event": fe["event"]}
        if fe.get("resource") is not None:
            item["resource"] = fe["resource"]
        out.append(item)
    return out


class NativeEngine:
    """O Engine com backend nativo. Assinatura idêntica à do Engine."""

    def __init__(self, seed: int = 42, n_companies: int = 8,
                 god_events: list[dict] | None = None,
                 policy=None,
                 world_data: bool = True,
                 market_v2: bool = False,
                 market_params: dict | None = None,
                 country_v2: bool = False,
                 country_params: dict | None = None,
                 equip_v2: bool = False,
                 equip_params: dict | None = None):
        if not native.available():
            raise RuntimeError(
                "núcleo nativo indisponível (sem g++/nanobind?) — "
                "use o Engine Python puro")
        if policy is None:
            policy = HeuristicPolicy()
        if not isinstance(policy, HeuristicPolicy):
            raise ValueError(
                "backend nativo suporta apenas a HeuristicPolicy; "
                "políticas customizadas rodam no Engine Python")
        self.policy = policy
        self.seed = seed
        self.tick = 0
        self.chronicle = Chronicle(START_YEAR)
        deposits, cities, source = _resolve_world(world_data)
        self.world_source = source
        self._int_fields = _deposit_int_fields(deposits)
        for ev in god_events or []:
            if ev.get("type") == "discovery":
                fields = {f for f in ("size_t", "grade", "lat", "lon")
                          if isinstance(ev.get(f), int)
                          and not isinstance(ev.get(f), bool)}
                if fields:
                    self._int_fields[ev["name"]] = fields
        self.market_v2 = market_v2
        self.country_v2 = country_v2
        self.equip_v2 = equip_v2
        self._mkt = marketdata.resolve_params(market_params) \
            if market_v2 else None
        self._ctry = countrydata.resolve_country_params(country_params) \
            if country_v2 else None
        self._equip = equipdata.resolve_equip_params(equip_params) \
            if equip_v2 else None
        self.god_events = sorted(god_events or [],
                                 key=lambda e: e["tick"])
        cfg = {
            "seed": seed,
            "n_companies": n_companies,
            "deposits": [{"name": d.name, "resource": d.resource,
                          "lat": d.lat, "lon": d.lon,
                          "size_t": d.size_t, "grade": d.grade}
                         for d in copy.deepcopy(deposits)],
            "cities": [{"name": c.name, "lat": c.lat, "lon": c.lon,
                        "demand_weight": c.demand_weight}
                       for c in cities],
            "god_events": copy.deepcopy(self.god_events),
            "policy_params": dict(policy.p),
            "market_v2": market_v2,
            "country_v2": country_v2,
            "equip_v2": equip_v2,
        }
        if market_v2:
            cfg["market_params"] = self._mkt
        if country_v2:
            ctry = copy.deepcopy(self._ctry)
            ctry["force_events_norm"] = _normalize_force_events(self._ctry)
            cfg["country_params"] = ctry
        if equip_v2:
            cfg["equip_params"] = self._equip
        self._world = native.module().make_world(cfg)
        # fundações + snapshot inicial, como Engine.__init__
        frame = self._make_frame()
        raw = self._world.frame()
        for c in raw["companies"]:
            self.chronicle.add(
                0, "founding",
                f"{c['name']} ({c['archetype']}) é fundada em "
                f"{c['hq']} com US$ {c['cash'] / 1e6:.0f}M em caixa.",
                c["name"], cid=c["id"], cash=c["cash"],
                archetype=c["archetype"], hq=c["hq"])
        self.frames = [frame]

    # -- eventos ------------------------------------------------------
    def _emit(self, rec: dict) -> None:
        kind = rec["kind"]
        tick = rec["tick"]
        company = rec["company"]
        data = rec["data"]
        fmt = rec["fmt"]
        add = self.chronicle.add
        if kind == "flows":
            add(tick, "flows", "", None, companies=data["companies"])
        elif kind == "probe":
            if fmt["grade"] >= 0.78:
                add(tick, "probe",
                    f"{fmt['name']} sonda {fmt['deposit']} e encontra "
                    f"um depósito RICO.", company)
            elif fmt["grade"] <= 0.35:
                add(tick, "probe",
                    f"{fmt['name']} sonda {fmt['deposit']}: "
                    f"teor decepcionante.", company)
        elif kind == "mine":
            add(tick, "mine",
                f"{fmt['name']} abre sua mina em {fmt['deposit']}.",
                company, **data)
        elif kind == "facility":
            add(tick, "facility",
                _FACILITY_TEXTS[fmt["kind"]].format(**fmt), company, **data)
        elif kind == "chain_link":
            stage = data["stage"]
            add(tick, "chain_link",
                f"MARCO DA CADEIA: {fmt['name']} é a primeira a dominar "
                f"o elo de {_STAGE_NAMES[stage]}.", company, **data)
        elif kind == "record":
            if data.get("record") == "first_link":
                stage = data["stage"]
                if stage == 5:
                    text = (f"MARCO DE ERA: {fmt['name']} fecha a ERA 1 "
                            f"(The Path to the Supercomputer) — é a "
                            f"primeira a dominar o elo de "
                            f"supercomputador. Recorde permanente do "
                            f"mundo.")
                else:
                    text = (f"RECORDE: {fmt['name']} é a primeira a "
                            f"dominar o elo de {_STAGE_NAMES[stage]} — "
                            f"marco permanente da Era 1.")
                add(tick, "record", text, company, **data)
        elif kind == "record_super":
            add(tick, "record",
                f"{company} entrega um SUPERCOMPUTADOR montado "
                f"por conta própria.", company)
        elif kind == "tool":
            tool = fmt["tool"]
            if tool == "insta":
                text = (f"{fmt['name']} dispara uma campanha no "
                        f"InstaSim (US$ {insta_campaign_cost():,.0f}) "
                        f"para empurrar seus dispositivos.")
            elif tool == "zap":
                text = (f"{fmt['name']} abre canal de vendas no ZapSim "
                        f"(US$ {zap_campaign_cost():,.0f}).")
            elif tool == "vid":
                text = (f"{fmt['name']} estreia campanha em vídeo no "
                        f"VidSim (US$ {vid_campaign_cost():,.0f}) para "
                        f"empurrar seus produtos de elo alto.")
            else:
                text = (f"{fmt['name']} abre loja no LojaSim "
                        f"(US$ {loja_store_cost():,.0f} + "
                        f"{LOJA_FEE_PCT:.0%} por venda).")
            add(tick, "tool", text, company)
        elif kind == "god_shock":
            add(tick, "god",
                f"CHOQUE DE MERCADO: o preço de {fmt['commodity']} se "
                f"move abertamente (fator {fmt['factor']}).")
        elif kind == "god_discovery":
            add(tick, "god",
                f"DESCOBERTA: novo depósito de {fmt['resource']} "
                f"anunciado — {fmt['name']}.")
        elif kind == "god_sanction":
            add(tick, "god",
                f"SANÇÃO: o comércio de {fmt['resource']} é "
                f"restringido por {fmt['duration']} meses.")
        elif kind == "market_regime":
            if fmt["regime"] == "boom":
                text = (f"MERCADO: {fmt['commodity']} entra em EUFORIA "
                        f"(boom) — a âncora de longo prazo está em "
                        f"US$ {fmt['anchor']:,.0f} e subindo; os "
                        f"estoques do mundo cobrem {fmt['cover']:.1f} "
                        f"meses de demanda.")
            else:
                text = (f"MERCADO: {fmt['commodity']} entra em COLAPSO "
                        f"(bust) — a âncora de longo prazo está em "
                        f"US$ {fmt['anchor']:,.0f} e caindo; os "
                        f"estoques do mundo cobrem {fmt['cover']:.1f} "
                        f"meses de demanda.")
            add(tick, "market_regime", text, None, **data)
        elif kind == "price_record":
            if fmt["direction"] == "high":
                text = (f"RECORDE DE PREÇO: {fmt['commodity']} atinge "
                        f"US$ {fmt['price']:,.0f} — o maior valor em "
                        f"{fmt['window']} meses.")
            else:
                text = (f"RECORDE DE PREÇO: {fmt['commodity']} desaba "
                        f"a US$ {fmt['price']:,.0f} — o menor valor em "
                        f"{fmt['window']} meses.")
            add(tick, "price_record", text, None, **data)
        elif kind == "politics":
            add(tick, "politics", self._politics_text(fmt), None, **data)
        elif kind == "breakdown":
            link = _FACILITY_LINK[fmt["kind"]]
            add(tick, "breakdown",
                f"QUEBRA: a instalação de {link} da {fmt['name']} "
                f"quebra com {fmt['age']} meses de operação e "
                f"condição a {fmt['cond']:.0%} — parada até a empresa "
                f"pagar o reparo de US$ {fmt['repair_cost']:,.0f} "
                f"(estimativa: {fmt['repair_ticks']} mês(es) de "
                f"oficina).", company, **data)
        elif kind == "maintenance":
            link = _FACILITY_LINK[fmt["kind"]]
            action = data["action"]
            if action == "repair":
                text = (f"REPARO: {fmt['name']} paga "
                        f"US$ {fmt['cost']:,.0f} e manda sua instalação "
                        f"de {link} para a oficina — volta em "
                        f"{fmt['repair_ticks']} mês(es).")
            elif action == "preventive":
                text = (f"MANUTENÇÃO PESADA: {fmt['name']} para sua "
                        f"instalação de {link} por um mês para salvar "
                        f"uma condição de {fmt['before']:.0%} "
                        f"(US$ {fmt['cost']:,.0f}) — sai da oficina a "
                        f"{fmt['after']:.0%}.")
            else:
                text = (f"OVERHAUL: {fmt['name']} gasta "
                        f"US$ {fmt['cost']:,.0f} e reconstrói sua "
                        f"instalação de {link} por dentro — "
                        f"{fmt['age_before']} meses de idade viram "
                        f"planta nova.")
            add(tick, "maintenance", text, company, **data)
        elif kind == "bankruptcy":
            add(tick, "bankruptcy",
                f"FALÊNCIA: {fmt['name']} quebra com "
                f"US$ {fmt['cash'] / 1e6:.1f}M de rombo. "
                f"Causa provável: {_CAUSE_PHRASES[fmt['cause']]}.",
                company, **data)
        elif kind == "acquisition":
            add(tick, "acquisition",
                f"AQUISIÇÃO: {fmt['buyer']} compra os ativos da "
                f"falida {fmt['dead']} por "
                f"US$ {fmt['price'] / 1e6:.1f}M.", company, **data)
        elif kind == "rivalry":
            if fmt["metric"] == "cash":
                text = (f"RIVALIDADE: {fmt['new']} ultrapassa "
                        f"{fmt['old']} e assume a liderança em caixa "
                        f"(US$ {fmt['new_cash'] / 1e6:.1f}M contra "
                        f"US$ {fmt['old_cash'] / 1e6:.1f}M).")
            else:
                text = (f"RIVALIDADE: {fmt['new']} ultrapassa "
                        f"{fmt['old']} na cadeia e assume a liderança "
                        f"(elo {fmt['new_stage']} contra elo "
                        f"{fmt['old_stage']}).")
            add(tick, "rivalry", text, company, **data)
        elif kind == "era_summary":
            super_txt = f"supercomputadores entregues: {fmt['super_int']}"
            if fmt.get("top_producer"):
                super_txt += f" (maior produtor: {fmt['top_producer']})"
            add(tick, "era_summary",
                f"RESUMO DA ERA ({fmt['years']} anos de mundo): "
                f"{fmt['richest']} lidera em caixa "
                f"(US$ {fmt['richest_cash'] / 1e6:.1f}M); "
                f"{fmt['top']} lidera a cadeia (elo "
                f"{fmt['top_stage']}); {fmt['most_fac']} tem mais "
                f"instalações ({fmt['most_fac_n']}); {super_txt}; "
                f"falências: {fmt['bankruptcies']}; empresas vivas: "
                f"{fmt['alive']}/{fmt['total']}.", None, **data)
        else:
            raise ValueError(f"evento nativo desconhecido: {kind!r}")

    @staticmethod
    def _politics_text(fmt: dict) -> str:
        country, event = fmt["country"], fmt["event"]
        tau, s_mean, s = fmt["tau"], fmt["S_mean"], fmt["S"]
        if event == "royalty_reform":
            alvo = f" com {fmt['resource']} em alta" \
                if fmt.get("resource") else ""
            return (f"REFORMA DE ROYALTIES: {country} eleva os "
                    f"royalties da mineração{alvo} — a alíquota sobre "
                    f"o opex sobe para {tau:.1%} e operar no país "
                    f"fica mais caro.")
        if event == "export_restriction":
            res = fmt["resource"]
            return (f"RESTRIÇÃO DE EXPORTAÇÃO: {country} restringe "
                    f"as exportações de {res} por {fmt['months']} "
                    f"meses — a paridade mundial de {res} e de "
                    f"{fmt['refined']} dispara e importar fica mais "
                    f"caro em todo o mapa.")
        if event == "state_jv":
            alvo = f" de {fmt['resource']}" if fmt.get("resource") else ""
            return (f"PARTICIPAÇÃO ESTATAL: {country} impõe joint "
                    f"venture com estatal majoritária nos "
                    f"projetos{alvo} — a confiança do investidor cai "
                    f"(estabilidade média em {s_mean:.2f}) e os "
                    f"royalties sobem para {tau:.1%}.")
        if event == "judicial_halt":
            return (f"PARALISAÇÃO JUDICIAL: a Justiça de {country} "
                    f"suspende as minas do país por {fmt['months']} "
                    f"meses — produção zerada enquanto durar a liminar "
                    f"(o fantasma de Cobre Panamá).")
        if event == "subsidy":
            return (f"SUBSÍDIO: {country} lança um pacote de "
                    f"incentivo à mineração e à indústria — royalties "
                    f"caem para {tau:.1%} do opex e a estabilidade "
                    f"média sobe para {s_mean:.2f}.")
        if event == "disaster":
            return (f"DESASTRE NATURAL: um evento extremo atinge "
                    f"{country} — minas paradas por {fmt['months']} "
                    f"meses e a estabilidade do país desaba para "
                    f"{s:.2f}.")
        if event == "election":
            return (f"ELEIÇÃO em {country}: o novo governo "
                    f"reposiciona o país — estabilidade média em "
                    f"{s_mean:.2f} e royalties em {tau:.1%} do opex.")
        raise ValueError(f"evento político desconhecido: {event!r}")

    # -- frames ---------------------------------------------------------
    def _make_frame(self) -> dict:
        fd = self._world.frame()
        frame = {
            "tick": fd["tick"],
            "date": sim_date(fd["tick"], START_YEAR),
            "prices": {k: round(v, 2) for k, v in fd["prices"].items()},
            "companies": [{
                "id": c["id"], "name": c["name"],
                "archetype": c["archetype"], "color": c["color"],
                "hq": c["hq"], "alive": c["alive"],
                "cash": round(c["cash"], 2), "stage": c["stage"],
                "territory": sorted(c["territory"]),
                "facilities": [
                    self._frame_facility(f) for f in c["facilities"]],
                "stocks": {k: round(v, 3) for k, v in c["stocks"].items()
                           if v > 0.01},
            } for c in fd["companies"]],
            "deposits": [{
                "name": d["name"], "resource": d["resource"],
                "cell": d["cell"], "lat": d["lat"], "lon": d["lon"],
                "remaining_frac": round(d["remaining"] / d["size_t"], 4)
                if d["size_t"] else 0.0,
            } for d in fd["deposits"]],
        }
        if self.market_v2:
            frame["market"] = {
                k: {"anchor": round(v["anchor"], 2),
                    "regime": v["regime"],
                    "cover": round(v["cover"], 3)}
                for k, v in fd["market"].items()}
        if self.country_v2:
            frame["politics"] = {
                k: {"S": round(v["S"], 3), "fx": round(v["fx"], 3),
                    "tau": round(v["tau"], 4)}
                for k, v in fd["politics"].items()}
            frame["trade"] = {
                k: {"parity_import": round(v["parity_import"], 2),
                    "parity_export": round(v["parity_export"], 2)}
                for k, v in fd["trade"].items()}
        return frame

    @staticmethod
    def _frame_facility(f: dict) -> dict:
        out = {"kind": f["kind"], "cell": f["cell"],
               "deposit": f["deposit"]}
        if "equip" in f:
            eq = f["equip"]
            out["age"] = eq["age"]
            out["condition"] = round(eq["cond"], 3)
            out["down"] = eq["down"]
        return out

    # -- loop -----------------------------------------------------------
    def step(self) -> None:
        for rec in self._world.step():
            self._emit(rec)
        self.tick = self._world.get_tick()
        if self.tick % 12 == 0:
            self.frames.append(self._make_frame())

    def run(self, ticks: int) -> dict:
        for _ in range(ticks):
            self.step()
        if self.frames[-1]["tick"] != self.tick:
            self.frames.append(self._make_frame())
        rd = self._world.result_data()
        comps = rd["companies"]
        richest = comps[0]
        for c in comps[1:]:
            if c["cash"] > richest["cash"]:
                richest = c
        top = comps[0]
        for c in comps[1:]:
            if c["stage"] > top["stage"]:
                top = c
        alive = sum(1 for c in comps if c["alive"])
        self.chronicle.add(
            self.tick, "end",
            f"FIM DO PERÍODO: {richest['name']} lidera em caixa "
            f"(US$ {richest['cash'] / 1e6:.1f}M); {top['name']} foi "
            f"quem mais subiu na cadeia (elo {top['stage']}); "
            f"supercomputadores entregues: "
            f"{int(rd['total_super'])}; empresas vivas: "
            f"{alive}/{len(comps)}.")
        return self.result()

    def result(self) -> dict:
        rd = self._world.result_data()
        res = {
            "seed": self.seed,
            "ticks": self.tick,
            "frames": self.frames,
            "chronicle": self.chronicle.to_json(),
            "scoreboard": [{
                "name": c["name"], "archetype": c["archetype"],
                "alive": c["alive"], "cash": round(c["cash"], 2),
                "stage": c["stage"], "facilities": c["facilities"],
            } for c in sorted(rd["companies"], key=lambda x: -x["cash"])],
        }
        if self.market_v2:
            res["market"] = rd["market"]
        if self.equip_v2:
            eq = rd["equipment"]
            companies = {}
            tot_fac, tot_down = eq["fleet_fac_ticks"], \
                eq["fleet_down_ticks"]
            for st in eq["companies"]:
                entry = {
                    "fac_ticks": st["fac_ticks"],
                    "down_ticks": st["down_ticks"],
                    "breaks": st["breaks"], "repairs": st["repairs"],
                    "maintenances": st["maintenances"],
                    "overhauls": st["overhauls"],
                    "archetype": st["archetype"],
                    "availability": (1.0 - st["down_ticks"]
                                     / st["fac_ticks"])
                    if st["fac_ticks"] else 1.0,
                }
                companies[st["name"]] = entry
            res["equipment"] = {
                "companies": companies,
                "fleet": {"fac_ticks": tot_fac, "down_ticks": tot_down,
                          "availability": (1.0 - tot_down / tot_fac)
                          if tot_fac else 1.0}}
        if self.country_v2:
            res["politics"] = rd["politics"]
            res["trade"] = rd["trade"]
        return res

    # -- snapshot / restore ---------------------------------------------
    def _restore_int_types(self, state: dict) -> None:
        int_sizes: dict[str, float] = {}
        for d in state["deposits"]:
            fields = self._int_fields.get(d["name"])
            if not fields:
                continue
            for f in fields:
                if float(d[f]).is_integer():
                    d[f] = int(d[f])
            if "size_t" in fields:
                int_sizes[d["name"]] = float(d["size_t"])
        # remaining: no motor Python ele nasce int (o size_t da fonte) e
        # só vira float na primeira extração — a subtração só executa
        # com crude > 0, logo remaining == size_t ⟺ depósito intacto.
        # O núcleo guarda double e emitia float sempre: o hash JSON do
        # state_dict divergia em qualquer corrida com depósito não
        # extraído (no Kaggle, onde o bundle não leva data/, o mundo é
        # o builtin e o Chuquicamata nunca é extraído no mundo vivo —
        # diagnóstico diag-fase5, veredito v2 7/11). Normaliza pelo
        # mesmo critério dos demais campos declarados int.
        for name, size in int_sizes.items():
            value = state["remaining"].get(name)
            if isinstance(value, float) and value.is_integer() \
                    and value == size:
                state["remaining"][name] = int(value)
        for c in state["companies"]:
            for name, pair in c["knowledge"].items():
                fields = self._int_fields.get(name)
                if not fields:
                    continue
                if "grade" in fields and float(pair[0]).is_integer():
                    pair[0] = int(pair[0])
                if "size_t" in fields and float(pair[1]).is_integer():
                    pair[1] = int(pair[1])

    def state_dict(self) -> dict:
        fs = self._world.full_state()
        state = {
            "version": 1,
            "seed": self.seed,
            "tick": self.tick,
            "rng_state": fs["rng_state"],
            "world_source": self.world_source,
            "cities": fs["cities"],
            "deposits": fs["deposits"],
            "remaining": fs["remaining"],
            "claimed_by": fs["claimed_by"],
            "companies": fs["companies"],
            "prices": fs["prices"],
            "demand_factors": fs["demand_factors"],
            "god_events": copy.deepcopy(self.god_events),
            "first_link": fs["first_link"],
            "leaders": fs["leaders"],
            "super_by_cid": fs["super_by_cid"],
            "spend_hist": fs["spend_hist"],
            "frames": copy.deepcopy(self.frames),
            "chronicle": {"start_year": self.chronicle.start_year,
                          "events": [asdict(e)
                                     for e in self.chronicle.events]},
            "ledger_mass": fs["ledger_mass"],
            "initial_cash": fs["initial_cash"],
            "money_in": fs["money_in"],
            "money_out": fs["money_out"],
            "total_supercomputers": fs["total_supercomputers"],
        }
        if self.market_v2:
            blk = dict(fs["market_block"])
            blk["params"] = copy.deepcopy(self._mkt)
            state["market_v2"] = {
                "params": blk["params"], "anchors": blk["anchors"],
                "regime": blk["regime"],
                "regime_months": blk["regime_months"],
                "demand_ema": blk["demand_ema"], "cover": blk["cover"],
                "fair_noise": blk["fair_noise"],
                "price_ring": blk["price_ring"],
                "record_state": blk["record_state"],
            }
        if self.equip_v2:
            state["equip_v2"] = {
                "params": copy.deepcopy(self._equip),
                "stats": fs["equip_block"]["stats"],
            }
        if self.country_v2:
            blk = fs["country_block"]
            state["country_v2"] = {
                "params": copy.deepcopy(self._ctry),
                "countries": blk["countries"],
                "money_to_external": blk["money_to_external"],
                "money_from_external": blk["money_from_external"],
                "parity_surcharge": blk["parity_surcharge"],
            }
        self._restore_int_types(state)
        return state

    @classmethod
    def from_state(cls, state: dict, policy=None) -> "NativeEngine":
        if not native.available():
            raise RuntimeError("núcleo nativo indisponível")
        if policy is None:
            policy = HeuristicPolicy()
        if not isinstance(policy, HeuristicPolicy):
            raise ValueError(
                "backend nativo suporta apenas a HeuristicPolicy")
        eng = cls.__new__(cls)
        eng.policy = policy
        eng.seed = state["seed"]
        eng.tick = state["tick"]
        eng.chronicle = Chronicle(state["chronicle"]["start_year"])
        eng.chronicle.events = [Event(**e)
                                for e in state["chronicle"]["events"]]
        eng.world_source = state.get("world_source", "builtin")
        eng._int_fields = {}
        for d in state["deposits"]:
            fields = {f for f in ("size_t", "grade", "lat", "lon")
                      if isinstance(d.get(f), int)
                      and not isinstance(d.get(f), bool)}
            if fields:
                eng._int_fields[d["name"]] = fields
        eng.god_events = sorted(copy.deepcopy(state["god_events"]),
                                key=lambda e: e["tick"])
        eng.frames = copy.deepcopy(state["frames"])
        mv = state.get("market_v2")
        eng.market_v2 = bool(mv)
        eng._mkt = marketdata._validate(copy.deepcopy(mv["params"])) \
            if mv else None
        ct = state.get("country_v2")
        eng.country_v2 = bool(ct)
        eng._ctry = countrydata._validate(copy.deepcopy(ct["params"])) \
            if ct else None
        eqb = state.get("equip_v2")
        eng.equip_v2 = bool(eqb)
        eng._equip = equipdata._validate(copy.deepcopy(eqb["params"])) \
            if eqb else None
        bankruptcies = sum(1 for e in eng.chronicle.events
                           if e.kind == "bankruptcy")
        cfg = {"policy_params": dict(policy.p),
               "bankruptcies": bankruptcies}
        # os parâmetros restaurados viajam dentro dos blocos do state;
        # force_events precisa da forma normalizada no bloco de país
        st = copy.deepcopy(state)
        if ct:
            st["country_v2"]["params"] = copy.deepcopy(eng._ctry)
            st["country_v2"]["params"]["force_events_norm"] = \
                _normalize_force_events(eng._ctry)
        eng._world = native.module().restore_world(st, cfg)
        return eng
