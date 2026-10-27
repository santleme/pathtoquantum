"""Parâmetros do mercado vivo (B1) — DADO com fontes, não código.

Fonte canônica: ``data/market_params.json`` (parâmetros por commodity
com nota de calibração ancorada nas séries USGS/LME/World Bank Pink
Sheet 2015–2025 — ver ``docs/ESTUDO-MOTOR-AMBIENTE.md`` §B1).

Fallback embutido: o bundle do Kaggle carrega só ``src/`` + pyproject
(sem ``data/``), então os MESMOS parâmetros vivem embutidos abaixo.
Um teste garante que arquivo e fallback nunca divergem — calibrar é
editar o JSON e regenerar o fallback, nunca editar um dos dois só.

As funções de matemática (demanda elástica, sazonalidade, pressão de
inventário) são puras e vivem aqui para serem testáveis sem motor.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from . import chain

SCHEMA_VERSION = 1

_DEFAULT_JSON = r"""{
 "commodities": {
  "component": {
   "boom_months": 18,
   "bust_months": 18,
   "calibration_note": "Componentes eletrônicos: ε 0,7 (estudo §B1) — demanda industrial sensível a preço, ciclos de semicondutores de ~18 meses.",
   "cover_target": 2.0,
   "drift_boom": 0.006,
   "drift_bust": 0.005,
   "elasticity": 0.7,
   "gamma": 0.25,
   "kappa": 0.25,
   "normal_months": 24,
   "seasonal_amp": 0.05,
   "seasonal_phase": 5,
   "sigma_monthly": 0.04
  },
  "copper": {
   "boom_months": 30,
   "bust_months": 30,
   "calibration_note": "Cobre LME: ~US$ 4,9 mil/t (fundo 2016) -> pico ~US$ 10,7 mil/t (mar/2022) -> US$ 9-9,5 mil/t (2024) -> território recorde em 2025 (demanda de data centers de IA). σ mensal ≈ 5%.",
   "cover_target": 2.0,
   "drift_boom": 0.008,
   "drift_bust": 0.006,
   "elasticity": 0.4,
   "gamma": 0.3,
   "kappa": 0.18,
   "normal_months": 24,
   "seasonal_amp": 0.03,
   "seasonal_phase": 0,
   "sigma_monthly": 0.05
  },
  "copper_ore": {
   "boom_months": 30,
   "bust_months": 30,
   "calibration_note": "Minério de cobre: demanda derivada do metal refinado (LME) — herda σ≈5%/mês dele.",
   "cover_target": 2.0,
   "drift_boom": 0.008,
   "drift_bust": 0.006,
   "elasticity": 0.4,
   "gamma": 0.3,
   "kappa": 0.18,
   "normal_months": 24,
   "seasonal_amp": 0.03,
   "seasonal_phase": 0,
   "sigma_monthly": 0.05
  },
  "device": {
   "boom_months": 18,
   "bust_months": 18,
   "calibration_note": "Dispositivos: ε 1,0 (bem final de consumo — a elasticidade unitária é o caso-base de textbooks); sazonalidade forte de fim de ano (amp 0,10, fase p/ pico em nov).",
   "cover_target": 2.0,
   "drift_boom": 0.006,
   "drift_bust": 0.005,
   "elasticity": 1.0,
   "gamma": 0.25,
   "kappa": 0.25,
   "normal_months": 24,
   "seasonal_amp": 0.1,
   "seasonal_phase": 5,
   "sigma_monthly": 0.04
  },
  "iron": {
   "boom_months": 18,
   "bust_months": 24,
   "calibration_note": "Ferro/aço refinado: segue o minério (62% Fe), ε de curto prazo 0,5 (estudo §B1).",
   "cover_target": 2.0,
   "drift_boom": 0.01,
   "drift_bust": 0.007,
   "elasticity": 0.5,
   "gamma": 0.3,
   "kappa": 0.22,
   "normal_months": 24,
   "seasonal_amp": 0.05,
   "seasonal_phase": 0,
   "sigma_monthly": 0.06
  },
  "iron_ore": {
   "boom_months": 18,
   "bust_months": 24,
   "calibration_note": "Minério de ferro 62% Fe: ~US$ 40/t (fundo 2015) -> pico ~US$ 237/t (mai/2021) -> faixa US$ 100-130/t (2023-25). σ mensal ≈ 6%; κ maior = ciclos mais curtos que os do lítio.",
   "cover_target": 2.0,
   "drift_boom": 0.01,
   "drift_bust": 0.007,
   "elasticity": 0.5,
   "gamma": 0.3,
   "kappa": 0.22,
   "normal_months": 24,
   "seasonal_amp": 0.05,
   "seasonal_phase": 0,
   "sigma_monthly": 0.06
  },
  "lithium": {
   "boom_months": 24,
   "bust_months": 30,
   "calibration_note": "Carbonato de lítio: média EUA (USGS) US$ 63,7 mil/t (2022) -> US$ 11,8 mil/t (2024) -> ~US$ 9 mil/t (2025); pico ~US$ 80 mil/t (nov/2022) contra ~US$ 7 mil/t (2020): ciclo de 11x. Boom 2021-22 ≈ 24 meses; bust 2023-25 ≈ 30+ meses; σ mensal ≈ 9% no período 2021-23.",
   "cover_target": 2.5,
   "drift_boom": 0.012,
   "drift_bust": 0.008,
   "elasticity": 0.3,
   "gamma": 0.35,
   "kappa": 0.12,
   "normal_months": 24,
   "seasonal_amp": 0.04,
   "seasonal_phase": 0,
   "sigma_monthly": 0.09
  },
  "lithium_ore": {
   "boom_months": 24,
   "bust_months": 36,
   "calibration_note": "Minério de lítio: demanda derivada do carbonato refinado — herda a volatilidade dele (σ≈9%/mês em 2021-23, USGS/LME via estudo §B1).",
   "cover_target": 2.5,
   "drift_boom": 0.012,
   "drift_bust": 0.008,
   "elasticity": 0.3,
   "gamma": 0.35,
   "kappa": 0.12,
   "normal_months": 24,
   "seasonal_amp": 0.03,
   "seasonal_phase": 0,
   "sigma_monthly": 0.09
  },
  "oil": {
   "boom_months": 18,
   "bust_months": 24,
   "calibration_note": "Petróleo (WTI/Brent): US$ 26 (fev/2016) -> negativo (abr/2020) -> ~US$ 120 (jun/2022) -> US$ 70-80 (2024-25). σ mensal ≈ 8%; sazonalidade de demanda (verão do hemisfério norte).",
   "cover_target": 2.0,
   "drift_boom": 0.012,
   "drift_bust": 0.01,
   "elasticity": 0.4,
   "gamma": 0.3,
   "kappa": 0.25,
   "normal_months": 24,
   "seasonal_amp": 0.06,
   "seasonal_phase": 2,
   "sigma_monthly": 0.08
  },
  "plastic": {
   "boom_months": 18,
   "bust_months": 24,
   "calibration_note": "Plástico (derivado de petróleo): ε 0,4 e σ menor que o óleo bruto (contratos e margem de refino amortecem).",
   "cover_target": 2.0,
   "drift_boom": 0.008,
   "drift_bust": 0.006,
   "elasticity": 0.4,
   "gamma": 0.28,
   "kappa": 0.22,
   "normal_months": 24,
   "seasonal_amp": 0.04,
   "seasonal_phase": 2,
   "sigma_monthly": 0.05
  },
  "supercomputer": {
   "boom_months": 24,
   "bust_months": 24,
   "calibration_note": "Supercomputador: ε 1,2 — capex discricionário é a demanda mais elástica da cadeia (estudo §B1); cobertura-alvo menor (1,5 mês: ninguém estoca supercomputador).",
   "cover_target": 1.5,
   "drift_boom": 0.008,
   "drift_bust": 0.006,
   "elasticity": 1.2,
   "gamma": 0.22,
   "kappa": 0.2,
   "normal_months": 24,
   "seasonal_amp": 0.05,
   "seasonal_phase": 0,
   "sigma_monthly": 0.05
  }
 },
 "compiled_at": "2026-10-26",
 "model": {
  "ema_alpha": 0.1,
  "note": "A banda antiga do motor era [0,3x; 3x] do preço-base FIXO — incapaz de representar o ciclo real do lítio (11x entre 2020 e 2025). A banda nova é da ÂNCORA variável: [0,25x; 6x].",
  "price_band_of_anchor": [
   0.25,
   6.0
  ],
  "record_episode_reversal_pct": 0.05,
  "record_min_break_pct": 0.005,
  "record_window_months": 24
 },
 "purpose": "Parâmetros do mercado vivo (B1, Degrau 1 Fase 2): demanda elástica, pressão de inventário, regimes Markov boom/bust e âncora de preço p* por commodity. DADO versionado com fontes (DEGRAU1-DESIGN §4/B1; ESTUDO-MOTOR-AMBIENTE §B1) — calibrar é editar este arquivo, nunca o motor.",
 "schema_version": 1,
 "sources": [
  {
   "date": "2025",
   "publisher": "U.S. Geological Survey (USGS)",
   "title": "Mineral Commodity Summaries 2025 (lithium, copper, iron ore & steel)",
   "url": "https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries"
  },
  {
   "date": "2015-2025",
   "publisher": "World Bank",
   "title": "Commodity Markets — Pink Sheet (monthly prices: copper, iron ore, energy)",
   "url": "https://www.worldbank.org/en/research/commodity-markets"
  },
  {
   "date": "2015-2025",
   "publisher": "London Metal Exchange (LME)",
   "title": "LME Copper — price and stocks data",
   "url": "https://www.lme.com/en/metals/non-ferrous/lme-copper"
  }
 ]
}"""


class MarketParamsError(ValueError):
    """Schema inválido ou parâmetro incoerente em market_params."""


def embedded_params() -> dict:
    """Os parâmetros embutidos (fallback quando o JSON não está no bundle)."""
    return json.loads(_DEFAULT_JSON)


def default_data_path() -> Path:
    """``<repo>/data/market_params.json`` a partir da localização do pacote."""
    return Path(__file__).resolve().parents[2] / "data" / "market_params.json"


def load_market_params(path: str | Path | None = None) -> dict:
    """Carrega e valida o JSON. Levanta MarketParamsError em qualquer desvio."""
    p = Path(path) if path is not None else default_data_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return _validate(raw)


_FLOAT_KEYS = ("elasticity", "kappa", "gamma", "cover_target", "sigma_monthly",
               "drift_boom", "drift_bust", "seasonal_amp")
_INT_KEYS = ("boom_months", "bust_months", "normal_months", "seasonal_phase")


def _validate(raw: dict) -> dict:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise MarketParamsError(
            f"schema_version {raw.get('schema_version')!r} != {SCHEMA_VERSION}")
    comms = raw.get("commodities")
    if not isinstance(comms, dict):
        raise MarketParamsError("'commodities' ausente ou inválido")
    missing = set(chain.COMMODITIES) - set(comms)
    extra = set(comms) - set(chain.COMMODITIES)
    if missing or extra:
        raise MarketParamsError(
            f"commodities divergem da cadeia: faltam {sorted(missing)}, "
            f"sobram {sorted(extra)}")
    for name, p in comms.items():
        where = f"commodities.{name}"
        for key in _FLOAT_KEYS + _INT_KEYS:
            if key not in p or isinstance(p[key], bool) \
                    or not isinstance(p[key], (int, float)):
                raise MarketParamsError(f"{where}.{key}: ausente ou não-numérico")
        if not (0.0 < p["kappa"] <= 1.0):
            raise MarketParamsError(f"{where}.kappa fora de (0, 1]: {p['kappa']}")
        if p["elasticity"] < 0 or p["gamma"] < 0 or p["sigma_monthly"] < 0:
            raise MarketParamsError(f"{where}: elasticity/gamma/sigma negativos")
        for key in ("boom_months", "bust_months", "normal_months"):
            if p[key] < 1:
                raise MarketParamsError(f"{where}.{key} < 1: {p[key]}")
    model = raw.get("model") or {}
    band = model.get("price_band_of_anchor")
    if not (isinstance(band, list) and len(band) == 2 and 0 < band[0] < 1 < band[1]):
        raise MarketParamsError(f"model.price_band_of_anchor inválida: {band!r}")
    return raw


def resolve_params(override: dict | None = None) -> dict:
    """Parâmetros efetivos: JSON do repo quando existe; fallback embutido
    quando não (bundle do Kaggle). ``override`` (mesmo schema, parcial por
    commodity) é mesclado por cima — é como testes forçam regimes rápidos
    sem tocar no arquivo."""
    try:
        base = load_market_params()
    except (FileNotFoundError, MarketParamsError):
        base = _validate(embedded_params())
    if override:
        merged = copy.deepcopy(base)
        for name, fields in (override.get("commodities") or {}).items():
            if name not in merged["commodities"]:
                raise MarketParamsError(f"override de commodity desconhecida: {name!r}")
            merged["commodities"][name].update(fields)
        if "model" in override:
            merged["model"].update(override["model"])
        return _validate(merged)
    return base


# --------------------------------------------------------------------------- #
# Matemática pura do mercado vivo (testável sem motor)
# --------------------------------------------------------------------------- #
def seasonal_factor(tick: int, amp: float, phase: int) -> float:
    """Sazonalidade anual leve: 1 + amp·sin(2π·(tick+phase)/12)."""
    return 1.0 + amp * math.sin(2.0 * math.pi * (tick + phase) / 12.0)


def elastic_demand(d0: float, price: float, anchor: float,
                   elasticity: float, seasonal: float) -> float:
    """Demanda das cidades: D = D0 · (p/p*)^(−ε) · saz(t)."""
    if d0 <= 0 or anchor <= 0:
        return 0.0
    return d0 * (price / anchor) ** (-elasticity) * seasonal


def inventory_multiplier(cover: float, target: float, gamma: float) -> float:
    """Pressão de inventário sobre o preço justo: exp(−γ·(I − I*))."""
    return math.exp(-gamma * (cover - target))
