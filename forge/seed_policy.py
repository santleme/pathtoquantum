"""Programa-semente da forja (Degrau 2) — a geração 0.

Este arquivo É a política que o OpenEvolve evolui: a classe
``EvolvedPolicy`` nasce como cópia fiel da ``HeuristicPolicy`` v0
(o método ``decide`` é o da v0, com UMA linha removida: o
``rng = engine.rng`` morto do original — variável local nunca usada,
cuja remoção não toca o fluxo de aleatoriedade nem o comportamento;
a guarda anti-trapaça proíbe acesso direto a ``engine.rng``).

Tudo o mais (sondagem, jusante, compras, vendas, ferramentas,
equipamentos) é herdado da v0 e pode ser sobrescrito AQUI dentro do
bloco evolutivo conforme a evolução avança. A prova de que a geração
0 é bit-idêntica à v0 está em ``tests/test_forge.py``.

Regras do jogo (a guarda de ``mundo.program`` rejeita o programa se
quebrar): sem imports fora da allowlist, sem eval/open/getattr, sem
``engine.rng``, sem ``engine.companies``, sem atribuir atributos em
``engine``/``comp`` — o mundo muda pelos métodos do motor e a
informação legal da empresa é ``comp.knowledge`` (sondar antes de
saber) e os preços/estado públicos via ``engine``.
"""
from mundo import chain
from mundo.engine import HeuristicPolicy

# EVOLVE-BLOCK-START


class EvolvedPolicy(HeuristicPolicy):
    """A política evoluível — geração 0 = v0 (ver docstring do módulo)."""

    def decide(self, engine, comp):
        t = comp.traits
        spendable = comp.cash - self.reserve(comp)
        capex_done = False

        # 0) Equipamentos (B2): reparar / manter / trocar a frota —
        #    só existe com equip_v2 ligado; desligado, nem um bit muda
        if engine.equip_v2:
            self.maintain_equipment(engine, comp)

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
                    # B3: capex no país paga o prêmio de risco-país
                    # (1,0 com country_v2 desligado — bit-idêntico)
                    mult = engine.capex_mult(engine.deposit_country(target))
                    cost = (chain.CLAIM_COST
                            + chain.FACILITIES["mine"]["cost"]) * mult
                    if grade >= threshold and spendable > cost:
                        if target.cell not in comp.claimed:
                            engine._spend(comp, chain.CLAIM_COST * mult,
                                          reason="claim")
                            comp.claimed.add(target.cell)
                            engine.claimed_by[target.cell] = comp.cid
                        engine._spend(comp,
                                      chain.FACILITIES["mine"]["cost"] * mult,
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

# EVOLVE-BLOCK-END
