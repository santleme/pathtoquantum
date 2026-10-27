"""A cadeia de produção (árvore tecnológica) do v0.

minério/petróleo -> refinado -> componente -> dispositivo -> supercomputador.
A cadeia-emblema completa (até o computador quântico) está declarada em
DESIGN.md; no v0 os elos implementados vão até o supercomputador.
Quantidades: brutos/refinados em toneladas; componente/dispositivo/
supercomputador em unidades.
"""
from __future__ import annotations

RAW_TO_REFINED = {
    "lithium_ore": "lithium",
    "copper_ore": "copper",
    "iron_ore": "iron",
    "oil": "plastic",
}
REFINE_YIELD = 0.6          # 1 t bruta -> 0.6 t refinada (0.4 t rejeito)

# Receitas por unidade produzida (insumos em t, salvo o próprio produto).
RECIPES = {
    "component": {"inputs": {"copper": 0.020, "lithium": 0.005}, "out": 1.0},
    "device": {"inputs": {"component": 2.0, "iron": 0.050, "plastic": 0.020}, "out": 1.0},
    "supercomputer": {"inputs": {"device": 10.0, "component": 5.0}, "out": 1.0},
}

# Preços-base de mercado (US$ por t ou por unidade).
BASE_PRICES = {
    "lithium_ore": 900.0, "copper_ore": 300.0, "iron_ore": 110.0, "oil": 420.0,
    "lithium": 12_000.0, "copper": 9_000.0, "iron": 700.0, "plastic": 1_200.0,
    "component": 2_800.0, "device": 9_500.0, "supercomputer": 1_200_000.0,
}

# Demanda mensal das cidades (total do mundo, por commodity).
CITY_DEMAND = {
    "copper": 220.0, "lithium": 90.0, "iron": 600.0, "plastic": 120.0,
    "component": 260.0, "device": 420.0, "supercomputer": 7.0,
}

# Instalações: custo de construção (US$) e capacidade mensal.
FACILITIES = {
    "mine":     {"cost": 2_500_000.0, "capacity": 420.0},    # t de bruto/mês
    "refinery": {"cost": 4_000_000.0, "capacity": 320.0},    # t de insumo/mês
    "factory":  {"cost": 6_000_000.0, "capacity": 300.0},    # componentes/mês
    "plant":    {"cost": 8_000_000.0, "capacity": 130.0},    # dispositivos/mês
    "assembly": {"cost": 15_000_000.0, "capacity": 2.0},    # supercomputadores/mês
}

# Qual elo da cadeia cada instalação representa (para o placar/crônica).
FACILITY_LINK = {
    "mine": "extração", "refinery": "refino", "factory": "componente",
    "plant": "dispositivo", "assembly": "supercomputador",
}
OPERATING_COST = {  # US$ por unidade processada (pago ao "mundo", sink)
    "mine": 42.0, "refinery": 130.0, "factory": 300.0, "plant": 900.0, "assembly": 60_000.0,
}
CLAIM_COST = 200_000.0
PROBE_COST = 150_000.0
COMMODITIES = list(BASE_PRICES.keys())

# Fundação struct-of-arrays (DEGRAU1-DESIGN §3.1): toda tabela numérica
# do mundo indexa commodities por ESTE índice inteiro, nunca por nome.
# A ordem é a de COMMODITIES — mudar a ordem muda o layout das tabelas.
COMMODITY_INDEX = {c: i for i, c in enumerate(COMMODITIES)}
N_COMMODITIES = len(COMMODITIES)
