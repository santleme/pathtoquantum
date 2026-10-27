# Decisão de algoritmos — políticas das empresas (pesquisa de 26/10/2026)

## Recomendação primária
**Evoluir a HeuristicPolicy em liga — não substituí-la por MARL agora.**
- Parametrizar as constantes da heurística como um **genoma contínuo de ~20 genes** (genoma 0 = v0 exata).
- Otimizar com **CMA-ES**: cada candidato é uma empresa focal invadindo ecologias congeladas de rivais (campo F0 = v0; F1 = liga com mutantes, campeões congelados e exploiters).
- **Arquivo MAP-Elites/QD** por comportamento observado (capex vertical, gasto em ferramentas, concentração, mês do elo 3) para preservar espécies — campeão que destrói diversidade é vitória falsa.
- Temporadas oficiais com políticas **congeladas e versionadas**; a Crônica registra policy_id e hash do genoma.

## Plano B
**IPPO focal em liga** (parameter sharing + embedding de arquétipo), checkpoints virando membros da liga; MAPPO só se houver variância/crédito demonstrados. **QMIX rejeitado** (pressupõe cooperação/recompensa conjunta — incompatível com rivalidade general-sum). **LLM-CEO**: overlay anual futuro, diretivas limitadas e cacheadas sobre presets evoluídos — nunca decisor mensal.

## Achados sobre o motor (pré-requisitos)
1. O contrato real é `Policy.decide(engine, comp)` — antes de RL sério, construir camada `Observation` só com informação legal (fog-of-war por tipo, não por disciplina).
2. O motor tem UMA política global — torneios precisam de roteador por empresa (focal × campo).
3. Não há subproblema de precificação: preço nasce do mercado. O "RL residual" futuro é sobre **alavancas de alocação** (compras, retenção/oferta, timing de ferramentas).

## Experimento decisivo (pré-registrado): `ptq-policy-tournament-v1` (Kaggle)
- Braços: A0 heurística v0 · A1 EVO (CMA-ES) · A2 IPPO focal · A3 CEO-EVO (secundário).
- Orçamento equalizado: 8.192 episódios (983.040 ticks) por método aprendiz; seleção ≤512 episódios; seeds de treino/validação/teste separadas e travadas (teste: 9901–9932, com campo retido F2 e choques).
- Métrica primária: ΔS composto (percentis de caixa 50% + elo 30% + supercomputadores 20%) vs A0, IC95 por bootstrap.
- Portões de produto: diversidade e eventos narráveis ≥80% da A0; nenhuma espécie comportamental >50%.
- Vereditos possíveis impressos pelo notebook: PROVA / MATA / PLANO_B / INCONCLUSIVO, com critérios numéricos pré-registrados (ΔS ≥ +0,08 com IC>0 prova; A2 vencendo A1 por ≥+0,08 ativa o plano B).
