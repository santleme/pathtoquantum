"""Programa-semente da forja (Degrau 2) — a geração 0.

Este arquivo É a política que o OpenEvolve evolui: a classe
``EvolvedPolicy`` nasce como cópia fiel da ``HeuristicPolicy`` v0
(o método ``decide`` é o da v0, escrito sobre a Observation da
guarda v2 — a política recebe ``obs`` e nada além dela; a prova de
que a geração 0 é bit-idêntica à v0 está em ``tests/test_forge.py``).

Tudo o mais (sondagem, jusante, compras, vendas, ferramentas,
equipamentos) é herdado da v0 e pode ser sobrescrito AQUI dentro do
bloco evolutivo conforme a evolução avança.

Regras do jogo (a guarda de ``mundo.program`` rejeita o programa se
quebrar): sem imports fora da allowlist, sem eval/open/getattr, sem
atributos dunder/privados. E pela fronteira da Observation
(docs/OBSERVATION-SPEC.md) o programa nem recebe o motor: a
informação legal da empresa é ``obs.me`` (ela mesma, com o
``knowledge`` — sondar antes de saber, via ``obs.act.probe``) e
``obs.world`` (preços e o mapa público; teor/tamanho de depósito
não sondado NÃO EXISTEM na view), e o mundo muda só pelos verbos
de ``obs.act``.
"""
from mundo import chain
from mundo.engine import HeuristicPolicy

# EVOLVE-BLOCK-START


class EvolvedPolicy(HeuristicPolicy):
    """A política evoluível — geração 0 = v0 (ver docstring do módulo)."""

    def decide(self, obs):
        me, world, act = obs.me, obs.world, obs.act
        t = me.traits
        spendable = me.cash - self.reserve(me)
        capex_done = False

        # 0) Equipamentos (B2): reparar / manter / trocar a frota —
        #    só existe com equip_v2 ligado; desligado, nem um bit muda
        if world.equip_v2:
            self.maintain_equipment(obs)

        # 1) Mineração: sondar / reivindicar / construir mina
        mines = [f for f in me.facilities if f.kind == "mine"]
        desired_mines = 1 + int(t["aggression"] * self.p["mines_coef"])
        if len(mines) < desired_mines:
            target = self.pick_deposit(obs)
            if target is not None:
                known = me.knowledge.get(target.name)
                if known is None:
                    if spendable > chain.PROBE_COST:
                        grade, _size = act.probe(target.name)
                        if grade >= 0.78:
                            act.narrate("probe",
                                        f"{me.name} sonda {target.name} e "
                                        f"encontra um depósito RICO.")
                        elif grade <= 0.35:
                            act.narrate("probe",
                                        f"{me.name} sonda {target.name}: "
                                        f"teor decepcionante.")
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
                            act.spend(chain.CLAIM_COST * mult,
                                      reason="claim")
                            act.register_claim(target.cell)
                        act.spend(chain.FACILITIES["mine"]["cost"] * mult,
                                  reason="build")
                        fac = act.build_facility("mine", target.cell,
                                                 deposit=target.name)
                        act.narrate("mine",
                                    f"{me.name} abre sua mina em "
                                    f"{target.name}.",
                                    cid=me.cid, fid=fac.id,
                                    facility_kind="mine",
                                    cell=list(target.cell),
                                    deposit=target.name)
                        act.note_link(1)
                        capex_done = True

        # 2) Elos de jusante
        if not capex_done:
            capex_done = self.build_downstream(obs, spendable)

        # 3) Compras de insumos que faltam
        self.plan_buys(obs)

        # 4) Ofertas de venda (excedente sobre o buffer de jusante)
        self.plan_sells(obs)

        # 5) Ferramentas simuladas
        self.use_tools(obs)

# EVOLVE-BLOCK-END
