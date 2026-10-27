"""Projeção struct-of-arrays do estado do motor (DEGRAU1-DESIGN §3.1).

As tabelas numéricas do design — ``cash (N,)``, ``stocks (N, C)``,
``prices/anchor (C,)`` — materializadas a partir do motor oficial.
É a ponte que o núcleo nativo (Fase 5), o Numba e os drivers de
treino consomem: quem lê tabelas não toca nos objetos do motor.

Somente leitura e sem efeitos: montar as tabelas não muta o motor,
não consome RNG e não emite eventos. Linhas seguem a ordem de
``engine.companies``; colunas, a de ``chain.COMMODITIES``.
"""
from __future__ import annotations

import numpy as np

from . import chain


def cash_table(engine) -> np.ndarray:
    """Caixa por empresa: vetor f64 de forma (N,)."""
    return np.array([c.cash for c in engine.companies], dtype=np.float64)


def stocks_table(engine) -> np.ndarray:
    """Estoques por empresa × commodity: matriz f64 de forma (N, C)."""
    rows = [c.stocks.to_list() for c in engine.companies]
    return np.array(rows, dtype=np.float64).reshape(
        len(engine.companies), chain.N_COMMODITIES)


def prices_table(engine) -> np.ndarray:
    """Preço corrente por commodity: vetor f64 de forma (C,)."""
    return np.array([engine.prices[c] for c in chain.COMMODITIES],
                    dtype=np.float64)


def anchors_table(engine) -> np.ndarray:
    """Âncora de preço p* por commodity (série pública do B1): (C,).

    Sem mercado vivo, a âncora é o preço-base (constante)."""
    anchors = getattr(engine, "anchors", None) or chain.BASE_PRICES
    return np.array([anchors[c] for c in chain.COMMODITIES],
                    dtype=np.float64)
