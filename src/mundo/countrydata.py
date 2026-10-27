"""Parâmetros de país e política (B3) e de comércio externo (B4a) — DADO
com fontes, não código.

Fonte canônica: ``data/country_params.json`` (estabilidade média por
país ancorada nos índices publicados WGI/ICRG, regime inicial de
royalties, probabilidades anuais de eventos ancoradas na frequência
latino-americana 2015–2025 e parâmetros de paridade de importação —
ver ``docs/ESTUDO-MOTOR-AMBIENTE.md`` §B3/§B4a e
``docs/DEGRAU1-DESIGN.md`` §4/B3+B4a).

Fallback embutido: o bundle do Kaggle carrega só ``src/`` + pyproject
(sem ``data/``), então os MESMOS parâmetros vivem embutidos abaixo.
Um teste garante que arquivo e fallback nunca divergem — calibrar é
editar o JSON e regenerar o fallback, nunca editar um dos dois só.

Os mapas nome→país (depósitos e cidades) são fatos do mundo, não
calibração: vivem aqui como código (viajam no bundle) e cobrem o
mundo embutido (``world.py``) e o dataset real (``realdata.py``, que
já traz ``country`` por item — normalizado aqui, porque a fonte
oscila entre "Bolivia"/"Bolívia" e "Colombia"/"Colômbia").
"""
from __future__ import annotations

import copy
import json
import unicodedata
from pathlib import Path

from . import chain, world

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- #
# Mapas do mundo: nome -> país canônico (grafias em pt-BR)
# --------------------------------------------------------------------------- #
DEPOSIT_COUNTRIES = {
    "Salar de Atacama": "Chile",
    "Salar de Uyuni": "Bolívia",
    "Salinas de Jujuy": "Argentina",
    "Escondida (Norte do Chile)": "Chile",
    "Chuquicamata": "Chile",
    "Sul do Peru (Toquepala)": "Peru",
    "Carajás": "Brasil",
    "Quadrilátero Ferrífero": "Brasil",
    "Pré-sal (Bacia de Santos)": "Brasil",
    "Vaca Muerta": "Argentina",
    "Salar del Hombre Muerto": "Argentina",
    "Cerro Verde (Arequipa)": "Peru",
    "El Mutún": "Bolívia",
}

CITY_COUNTRIES = {
    "São Paulo": "Brasil",
    "Rio de Janeiro": "Brasil",
    "Belo Horizonte": "Brasil",
    "Porto Alegre": "Brasil",
    "Buenos Aires": "Argentina",
    "Santiago": "Chile",
    "Lima": "Peru",
    "Bogotá": "Colômbia",
    "Montevidéu": "Uruguai",
    "Assunção": "Paraguai",
    "Medellín": "Colômbia",
}

_CANONICAL = {
    "chile": "Chile",
    "brasil": "Brasil", "brazil": "Brasil",
    "peru": "Peru",
    "argentina": "Argentina",
    "bolivia": "Bolívia",
    "colombia": "Colômbia",
    "uruguai": "Uruguai", "uruguay": "Uruguai",
    "paraguai": "Paraguai", "paraguay": "Paraguai",
}

COUNTRY_NAMES = tuple(sorted(set(_CANONICAL.values())))


def normalize_country(name: str) -> str:
    """Grafia canônica do país (a fonte real oscila acentos/idioma)."""
    key = "".join(ch for ch in unicodedata.normalize("NFKD", str(name))
                  if not unicodedata.combining(ch)).strip().lower()
    if key not in _CANONICAL:
        raise ValueError(f"país desconhecido: {name!r}")
    return _CANONICAL[key]


def _nearest_country(lat: float, lon: float) -> str:
    """País do ponto conhecido mais próximo (depósitos/cidades do mundo
    embutido). Função pura das tabelas estáticas — depósitos descobertos
    por Deus resolvem igual antes e depois de um restore."""
    best, best_dist = None, None
    points = [(d.lat, d.lon, DEPOSIT_COUNTRIES[d.name])
              for d in world.DEPOSITS if d.name in DEPOSIT_COUNTRIES]
    points += [(c.lat, c.lon, CITY_COUNTRIES[c.name])
               for c in world.CITIES if c.name in CITY_COUNTRIES]
    for plat, plon, country in points:
        dist = abs(lat - plat) + abs(lon - plon)
        if best_dist is None or dist < best_dist:
            best, best_dist = country, dist
    return best


def country_of_deposit(dep) -> str:
    """País de um depósito: mapa por nome; descoberta de Deus resolve
    pelo vizinho conhecido mais próximo (lat/lon)."""
    if dep.name in DEPOSIT_COUNTRIES:
        return DEPOSIT_COUNTRIES[dep.name]
    return _nearest_country(dep.lat, dep.lon)


def country_of_city(city) -> str:
    """País de uma cidade: mapa por nome; fallback pelo vizinho."""
    if city.name in CITY_COUNTRIES:
        return CITY_COUNTRIES[city.name]
    return _nearest_country(city.lat, city.lon)


# --------------------------------------------------------------------------- #
# Parâmetros (JSON canônico + fallback embutido idêntico)
# --------------------------------------------------------------------------- #
_DEFAULT_JSON = r"""{
 "compiled_at": "2026-10-26",
 "countries": {
  "Argentina": {
   "calibration_note": "WGI Political Stability ~percentil 35 (2023); royalties provinciais de mineração ~3% + retenções — regime inicial 5,5% sobre o opex.",
   "royalty": 0.055,
   "stability_mean": 0.35
  },
  "Bolívia": {
   "calibration_note": "WGI Political Stability ~percentil 30 (2023); nacionalização do lítio como pano de fundo — regime inicial 6,0% sobre o opex.",
   "royalty": 0.06,
   "stability_mean": 0.3
  },
  "Brasil": {
   "calibration_note": "WGI Political Stability ~percentil 45 (2023); CFEM de 1-3,5% sobre receita — regime inicial simplificado de 4,5% sobre o opex.",
   "royalty": 0.045,
   "stability_mean": 0.45
  },
  "Chile": {
   "calibration_note": "WGI Political Stability ~percentil 65 (2023) — o mais estável dos grandes mineradores da região; reforma de royalties de 2023 levou a carga efetiva de grandes mineradoras de cobre a até ~46,5% sobre o lucro — aqui simplificada como surcharge de 5,0% sobre o opex.",
   "royalty": 0.05,
   "stability_mean": 0.65
  },
  "Colômbia": {
   "calibration_note": "WGI Political Stability ~percentil 38 (2023); regime inicial de 4,5% sobre o opex.",
   "royalty": 0.045,
   "stability_mean": 0.38
  },
  "Paraguai": {
   "calibration_note": "WGI Political Stability ~percentil 45 (2023); sem mineração relevante — o regime afeta instalações de jusante sediadas no país.",
   "royalty": 0.035,
   "stability_mean": 0.45
  },
  "Peru": {
   "calibration_note": "WGI Political Stability ~percentil 40 (2023); royalties de 1-12% sobre lucro operacional — regime inicial simplificado de 4,0% sobre o opex.",
   "royalty": 0.04,
   "stability_mean": 0.4
  },
  "Uruguai": {
   "calibration_note": "WGI Political Stability ~percentil 75 (2023) — o país mais estável da América do Sul; sem mineração relevante — regime inicial de 3,0% sobre o opex.",
   "royalty": 0.03,
   "stability_mean": 0.75
  }
 },
 "events_yearly": {
  "disaster": 0.01,
  "export_restriction": 0.02,
  "judicial_halt": 0.007,
  "royalty_reform": 0.06,
  "state_jv": 0.015,
  "subsidy": 0.04
 },
 "force_events": [],
 "model": {
  "capex_premium": 0.25,
  "disaster_s_shock": 0.05,
  "election_period": 48,
  "election_smean_shift": 0.18,
  "election_stagger": 6,
  "election_tau_steps": [
   -0.01,
   0.0,
   0.01,
   0.02
  ],
  "fx_beta": 1.5,
  "fx_max": 2.5,
  "fx_min": 0.5,
  "fx_reversion": 0.08,
  "fx_sigma": 0.01,
  "halt_months_disaster": 2,
  "halt_months_judicial": 3,
  "jv_smean_drop": 0.08,
  "jv_tau_step": 0.01,
  "local_opex_frac": 0.45,
  "reform_hot_ratio": 1.5,
  "reform_tau_step": 0.02,
  "restriction_months": 12,
  "restriction_parity_surcharge": 0.6,
  "s_max": 0.98,
  "s_min": 0.02,
  "s_reversion": 0.03,
  "s_sigma": 0.02,
  "smean_max": 0.9,
  "smean_min": 0.15,
  "subsidy_smean_gain": 0.03,
  "subsidy_tau_step": -0.01,
  "tau_max": 0.12,
  "tau_min": 0.02
 },
 "purpose": "Parâmetros de país/política (B3) e comércio externo (B4a) do Degrau 1 Fase 3: estabilidade S com reversão à média (baselines WGI/ICRG), câmbio-índice, royalties sobre o opex, motor de eventos endógeno com frequências latino-americanas 2015-2025 e pseudo-participante externo elástico na paridade. DADO versionado com fontes (DEGRAU1-DESIGN §4/B3+B4a; ESTUDO-MOTOR-AMBIENTE §B3/B4) — calibrar é editar este arquivo, nunca o motor.",
 "schema_version": 1,
 "sources": [
  {
   "date": "2023",
   "publisher": "World Bank",
   "title": "Worldwide Governance Indicators — Political Stability and Absence of Violence (percentis por país)",
   "url": "https://www.worldbank.org/en/publication/worldwide-governance-indicators"
  },
  {
   "date": "2015-2025",
   "publisher": "Estudo de ambiente (repo)",
   "title": "ESTUDO-MOTOR-AMBIENTE §B3/B4 — frequências de eventos ancoradas: reforma de royalties do Chile (2023), Estratégia Nacional do Lítio do Chile (abr/2023), nacionalização do lítio do México (fev/2023), fechamento de Cobre Panamá (2023)",
   "url": ""
  }
 ],
 "trade": {
  "capacity_factor": 2.0,
  "freight": 0.08,
  "max_spread_mult": 3.0,
  "ore_scale": 300.0,
  "tariff": 0.12
 }
}"""

EVENT_TYPES = ("royalty_reform", "export_restriction", "state_jv",
               "judicial_halt", "subsidy", "disaster", "election")


class CountryParamsError(ValueError):
    """Schema inválido ou parâmetro incoerente em country_params."""


def embedded_params() -> dict:
    """Os parâmetros embutidos (fallback quando o JSON não está no bundle)."""
    return json.loads(_DEFAULT_JSON)


def default_data_path() -> Path:
    """``<repo>/data/country_params.json`` a partir da localização do pacote."""
    return Path(__file__).resolve().parents[2] / "data" / "country_params.json"


def load_country_params(path: str | Path | None = None) -> dict:
    """Carrega e valida o JSON. Levanta CountryParamsError em qualquer desvio."""
    p = Path(path) if path is not None else default_data_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return _validate(raw)


def _validate(raw: dict) -> dict:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CountryParamsError(
            f"schema_version {raw.get('schema_version')!r} != {SCHEMA_VERSION}")
    countries = raw.get("countries")
    if not isinstance(countries, dict):
        raise CountryParamsError("'countries' ausente ou inválido")
    missing = set(COUNTRY_NAMES) - set(countries)
    if missing:
        raise CountryParamsError(f"países faltando: {sorted(missing)}")
    for name, p in countries.items():
        where = f"countries.{name}"
        if not (0.0 < p.get("stability_mean", 0) < 1.0):
            raise CountryParamsError(f"{where}.stability_mean fora de (0,1)")
        if not (0.0 <= p.get("royalty", -1) <= 0.15):
            raise CountryParamsError(f"{where}.royalty fora de [0, 0.15]")
        if not p.get("calibration_note"):
            raise CountryParamsError(f"{where}.calibration_note ausente")
    model = raw.get("model") or {}
    for key in ("capex_premium", "local_opex_frac", "s_reversion", "s_sigma",
                "fx_beta", "fx_reversion", "fx_sigma", "reform_hot_ratio",
                "restriction_parity_surcharge"):
        if not isinstance(model.get(key), (int, float)) \
                or isinstance(model.get(key), bool):
            raise CountryParamsError(f"model.{key} ausente ou não-numérico")
    if not (0.0 <= model["local_opex_frac"] <= 1.0):
        raise CountryParamsError("model.local_opex_frac fora de [0,1]")
    if int(model.get("election_period", 0)) < 1:
        raise CountryParamsError("model.election_period < 1")
    if not model.get("election_tau_steps"):
        raise CountryParamsError("model.election_tau_steps vazio")
    events = raw.get("events_yearly") or {}
    for key in ("royalty_reform", "export_restriction", "state_jv",
                "judicial_halt", "subsidy", "disaster"):
        prob = events.get(key)
        if not isinstance(prob, (int, float)) or not (0.0 <= prob <= 1.0):
            raise CountryParamsError(f"events_yearly.{key} inválido: {prob!r}")
    trade = raw.get("trade") or {}
    for key in ("tariff", "freight", "capacity_factor", "ore_scale",
                "max_spread_mult"):
        if not isinstance(trade.get(key), (int, float)) \
                or trade.get(key) < 0:
            raise CountryParamsError(f"trade.{key} inválido")
    if trade.get("freight", 1.0) >= 1.0:
        raise CountryParamsError("trade.freight >= 1 quebra a paridade de exportação")
    for fe in raw.get("force_events") or []:
        if not isinstance(fe, dict) or int(fe.get("tick", -1)) < 0 \
                or fe.get("event") not in EVENT_TYPES:
            raise CountryParamsError(f"force_events inválido: {fe!r}")
        normalize_country(fe.get("country", ""))   # levanta se desconhecido
        res = fe.get("resource")
        if res is not None and res not in chain.RAW_TO_REFINED:
            raise CountryParamsError(
                f"force_events.resource deve ser commodity bruta: {res!r}")
    return raw


def resolve_country_params(override: dict | None = None) -> dict:
    """Parâmetros efetivos: JSON do repo quando existe; fallback embutido
    quando não (bundle do Kaggle). ``override`` (mesmo schema, parcial)
    é mesclado por cima — é como testes zeram probabilidades e forçam
    eventos via ``force_events`` sem tocar no arquivo."""
    try:
        base = load_country_params()
    except (FileNotFoundError, CountryParamsError):
        base = _validate(embedded_params())
    if override:
        merged = copy.deepcopy(base)
        for name, fields in (override.get("countries") or {}).items():
            canon = normalize_country(name)
            if canon not in merged["countries"]:
                raise CountryParamsError(f"override de país desconhecido: {name!r}")
            merged["countries"][canon].update(fields)
        for section in ("model", "events_yearly", "trade"):
            if section in override:
                merged[section].update(override[section])
        if "force_events" in override:
            merged["force_events"] = copy.deepcopy(override["force_events"])
        return _validate(merged)
    return base


def monthly_prob(p_year: float) -> float:
    """Probabilidade anual -> mensal (perigo constante)."""
    return 1.0 - (1.0 - p_year) ** (1.0 / 12.0)
