"""O genoma da heurística — protocolo de torneios (ALGORITMOS-DECISAO.md).

As ~20 constantes de decisão da ``HeuristicPolicy`` viram um genoma
contínuo: um vetor de 20 floats na ordem de ``GENES``. O **genoma 0**
reproduz a v0 EXATAMENTE (os valores ``v0`` de cada gene são os de
``HeuristicPolicy.PARAMS0`` — um teste garante que nunca divergem).

Dois espaços:

- **espaço do genoma**: os valores crus (US$, limiares, escalas);
- **espaço do otimizador (z)**: ``z_i = (g_i - v0_i) / step_i`` — genes
  de escalas muito diferentes (1,5M de reserva × 0,3 de intercepto)
  viram coordenadas comparáveis, onde o CMA-ES anda. ``genome_from_z``
  clipa cada gene em ``[lo, hi]`` — o otimizador nunca propõe uma
  política fora dos limites sãos pré-registrados.

Constantes que NÃO são genes (estruturais, fora do espaço evolutivo):
tetos narrativos da sondagem (0,78/0,35), o cap 1,5 do tamanho
conhecido, os limiares de estoque que disparam a intenção de compra
(4,0/1,5/12/10 — os ALVOS escalam pelo gene ``buy_target_scale``) e os
limiares das ferramentas novas (VidSim/LojaSim, determinísticos).
"""
from __future__ import annotations

import hashlib
import json
import random

from .engine import HeuristicPolicy

# (nome, v0, lo, hi, step) — v0 == HeuristicPolicy.PARAMS0[nome] (teste).
GENES = [
    ("reserve_base",           1_500_000.0,      0.0, 6_000_000.0, 500_000.0),
    ("reserve_risk_span",      2_000_000.0,      0.0, 6_000_000.0, 500_000.0),
    ("mines_coef",                     2.0,      0.0,         5.0,       0.5),
    ("dist_scale",                    25.0,      5.0,       100.0,      10.0),
    ("known_grade_base",               0.3,      0.0,         1.5,       0.2),
    ("size_ref",                 800_000.0, 100_000.0, 4_000_000.0, 200_000.0),
    ("grade_thr_base",                0.62,     0.30,        0.95,      0.08),
    ("grade_thr_risk",                0.25,      0.0,         0.6,      0.08),
    ("refinery_raw_trigger",         350.0,     50.0,      2000.0,     150.0),
    ("factory_need_vertical",  1_200_000.0, 200_000.0, 6_000_000.0, 400_000.0),
    ("factory_need_default",   2_600_000.0, 400_000.0, 10_000_000.0, 600_000.0),
    ("plant_component_trigger",       40.0,      5.0,       300.0,      25.0),
    ("assembly_device_trigger",       25.0,      3.0,       200.0,      20.0),
    ("assembly_cash_cushion",  6_000_000.0,      0.0, 20_000_000.0, 2_000_000.0),
    ("buy_budget_frac",               0.5,     0.05,         1.0,      0.15),
    ("buy_target_scale",              1.0,      0.2,         3.0,       0.4),
    ("buffer_scale",                  1.0,      0.2,         3.0,       0.4),
    ("insta_prob_scale",              1.0,      0.0,         3.0,       0.5),
    ("zap_prob_scale",                1.0,      0.0,         3.0,       0.5),
    ("pick_noise",                    0.1,      0.0,         0.5,      0.08),
]

GENE_NAMES = [g[0] for g in GENES]
N_GENES = len(GENES)
GENOME0 = tuple(g[1] for g in GENES)


def genome_to_params(genome) -> dict:
    """Vetor de genoma -> dict de parâmetros da HeuristicPolicy."""
    if len(genome) != N_GENES:
        raise ValueError(f"genoma com {len(genome)} genes; esperado {N_GENES}")
    return {name: float(v) for name, v in zip(GENE_NAMES, genome)}


def params_to_genome(params: dict) -> tuple:
    return tuple(float(params[name]) for name in GENE_NAMES)


def genome_from_z(z) -> tuple:
    """Espaço do otimizador -> genoma cru, clipado nos limites do gene."""
    out = []
    for zi, (_, v0, lo, hi, step) in zip(z, GENES):
        out.append(min(hi, max(lo, v0 + float(zi) * step)))
    return tuple(out)


def z_from_genome(genome) -> tuple:
    return tuple((float(g) - v0) / step
                 for g, (_, v0, _, _, step) in zip(genome, GENES))


def mutate(genome, seed: int, sigma: float) -> tuple:
    """Mutante determinístico: ruído gaussiano em z, com a própria seed.

    Membros da liga (F1) e exploiters são mutantes congelados — a seed
    É a identidade do mutante (reproduzível sem guardar o vetor).
    """
    rng = random.Random(seed)
    z = [zi + rng.gauss(0.0, sigma) for zi in z_from_genome(genome)]
    return genome_from_z(z)


def genome_hash(genome) -> str:
    """Hash curto e estável do genoma — o ``policy_id`` da Crônica."""
    blob = json.dumps([round(float(g), 6) for g in genome],
                      separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def policy_id(genome) -> str:
    return "v0" if tuple(genome) == GENOME0 else f"evo:{genome_hash(genome)}"


class GenomePolicy(HeuristicPolicy):
    """Uma HeuristicPolicy com o genoma dado — a 'espécie' evoluída."""

    def __init__(self, genome):
        self.genome = tuple(float(g) for g in genome)
        super().__init__(genome_to_params(self.genome))

    @property
    def pid(self) -> str:
        return policy_id(self.genome)
