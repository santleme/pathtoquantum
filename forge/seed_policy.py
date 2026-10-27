"""Programa-semente da forja (Degrau 2) — a geração 0.

Este arquivo É a política que o OpenEvolve evolui: a classe
``EvolvedPolicy`` nasce como cópia fiel da ``HeuristicPolicy`` v0
(o método ``decide`` é o da v0, escrito sobre a Observation da
guarda v2 e o contrato declarativo da fatia 3 — a política recebe
``obs``, planeja e DEVOLVE a lista de intenções; quem valida e
executa é o motor. A prova de que a geração 0 é bit-idêntica à v0
está em ``tests/test_forge.py``).

Tudo o mais (sondagem, jusante, compras, vendas, ferramentas,
equipamentos) é herdado da v0 e pode ser sobrescrito AQUI dentro
do bloco evolutivo conforme a evolução avança.

Regras do jogo (a guarda de ``mundo.program`` rejeita o programa
se quebrar): sem imports fora da allowlist, sem eval/open/getattr,
sem atributos dunder/privados, sem ``obs.act`` — decidir é
declarar. E pela fronteira da Observation
(docs/OBSERVATION-SPEC.md) o programa nem recebe o motor: a
informação legal da empresa é ``obs.me`` (ela mesma, com o
``knowledge`` — sondar antes de saber, declarando uma intenção
``Probe``) e ``obs.world`` (preços e o mapa público; teor/tamanho
de depósito não sondado NÃO EXISTEM na view), e o mundo muda só
pelas intenções devolvidas, na ordem declarada.
"""
from mundo import chain
from mundo.engine import HeuristicPolicy
from mundo.intentions import (BuildFacility, Narration, NoteLink,
                              Plan, Probe, RegisterClaim, Spend)

# EVOLVE-BLOCK-START


class EvolvedPolicy(HeuristicPolicy):
    """A política evoluível — geração 0 = v0 (ver docstring do módulo)."""

    def decide(self, obs):
        me, world = obs.me, obs.world
        t = me.traits
        plan = Plan.of(me)
        out = []
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
                        # a sondagem declara as duas narrações; o
                        # motor narra a que o teor revelado selecionar
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

# EVOLVE-BLOCK-END
