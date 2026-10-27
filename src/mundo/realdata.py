"""Dados reais do mundo — loader tipado de ``data/world_data.json``.

Este módulo é a fronteira entre o Path to Quantum e a Terra de verdade:
concentra figuras públicas REAIS (reservas, teores, produção, população,
PIB, CPM, preços de commodity) com fonte citada por item, e adapta o que
dá para adaptar ao formato que o motor v0 consome (``world.Deposit`` /
``world.City``).

Regras de honestidade (não negociáveis):

- Toda figura carrega unidade explícita (``unit``) — sem número nu.
- ``estimated=True`` marca aproximações: conversões de unidade, atribuições
  país→depósito, dados de fonte secundária ou anualizações. Elas estão
  documentadas na ``note`` de cada figura.
- ``grade`` do world.py é um conceito de JOGO (fração aproveitável 0..1).
  O teor real (``grade_pct`` / ``grade_mg_per_l``) vive no JSON; o adaptador
  usa ``calibration.suggested_world_grade`` — um índice de qualidade
  RELATIVO dentro da classe, documentado em ``game_calibration`` do JSON —
  nunca o teor real disfarçado.

O módulo NÃO altera o mundo v0: importar e adaptar é opt-in de quem chama.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mundo.world import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, City, Deposit

SCHEMA_VERSION = 1

#: Unidades aceitas neste dataset. Unidade fora da lista = erro de schema.
ALLOWED_UNITS = frozenset({
    "t", "t_per_year", "t_lce", "t_lce_per_year",
    "pct", "mg_per_L",
    "bbl", "bbl_per_day", "tcf",
    "people", "usd_billion",
    "usd_per_t", "usd_per_bbl", "usd_per_message",
    "usd_per_1000_impressions",
})

#: Recursos que o motor v0 conhece (world.RESOURCES).
KNOWN_RESOURCES = frozenset({"lithium_ore", "copper_ore", "iron_ore", "oil"})


class WorldDataError(ValueError):
    """Schema inválido ou figura incoerente em world_data.json."""


# --------------------------------------------------------------------------- #
# Tipos
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Source:
    title: str
    publisher: str
    url: str
    date: str = ""


@dataclass(frozen=True)
class Figure:
    """Um número real com unidade, procedência e grau de certeza."""

    value: float
    unit: str
    estimated: bool = False
    note: str = ""


@dataclass(frozen=True)
class DepositData:
    name: str
    resource: str
    country: str
    lat: float
    lon: float
    operators: tuple[str, ...]
    figures: dict[str, Figure]
    sources: tuple[Source, ...]
    notes: str = ""
    v0_size_t: float = 0.0
    v0_grade: float = 0.0
    relative_size_index: float | None = None
    suggested_world_grade: float | None = None

    def figure(self, key: str) -> Figure:
        """Figura pelo nome (KeyError se não existir — erro de quem chama)."""
        return self.figures[key]


@dataclass(frozen=True)
class CityData:
    name: str
    country: str
    lat: float
    lon: float
    figures: dict[str, Figure]
    sources: tuple[Source, ...]
    v0_demand_weight: float = 0.0

    @property
    def metro_population(self) -> float:
        return self.figures["metro_population"].value


@dataclass(frozen=True)
class WorldData:
    schema_version: int
    compiled_at: str
    deposits: tuple[DepositData, ...]
    cities: tuple[CityData, ...]
    reference_costs: dict[str, Any] = field(default_factory=dict)
    game_calibration: dict[str, Any] = field(default_factory=dict)

    def deposit(self, name: str) -> DepositData:
        for d in self.deposits:
            if d.name == name:
                return d
        raise KeyError(f"depósito desconhecido: {name!r}")

    def city(self, name: str) -> CityData:
        for c in self.cities:
            if c.name == name:
                return c
        raise KeyError(f"cidade desconhecida: {name!r}")


# --------------------------------------------------------------------------- #
# Parsing + validação
# --------------------------------------------------------------------------- #
def _req(obj: dict, key: str, where: str) -> Any:
    if key not in obj or obj[key] is None:
        raise WorldDataError(f"{where}: campo obrigatório ausente: {key!r}")
    return obj[key]


def _parse_source(raw: dict, where: str) -> Source:
    src = Source(
        title=str(_req(raw, "title", where)).strip(),
        publisher=str(_req(raw, "publisher", where)).strip(),
        url=str(_req(raw, "url", where)).strip(),
        date=str(raw.get("date", "")).strip(),
    )
    if not src.title or not src.publisher:
        raise WorldDataError(f"{where}: fonte com título/editora vazios")
    if not src.url.startswith(("http://", "https://")):
        raise WorldDataError(f"{where}: URL de fonte inválida: {src.url!r}")
    return src


def _parse_figure(raw: dict, where: str) -> Figure:
    unit = str(_req(raw, "unit", where))
    if unit not in ALLOWED_UNITS:
        raise WorldDataError(f"{where}: unidade não reconhecida: {unit!r}")
    value = _req(raw, "value", where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorldDataError(f"{where}: value não é número: {value!r}")
    return Figure(
        value=float(value),
        unit=unit,
        estimated=bool(raw.get("estimated", False)),
        note=str(raw.get("note", "")),
    )


def _parse_figures(raw: dict, where: str) -> dict[str, Figure]:
    if not isinstance(raw, dict) or not raw:
        raise WorldDataError(f"{where}: 'figures' vazio ou inválido")
    return {k: _parse_figure(v, f"{where}.figures.{k}") for k, v in raw.items()}


def _parse_sources(raw: Any, where: str) -> tuple[Source, ...]:
    if not isinstance(raw, list) or not raw:
        raise WorldDataError(f"{where}: entrada sem fontes — fonte é obrigatória")
    return tuple(_parse_source(s, f"{where}.sources") for s in raw)


def _check_geo(lat: float, lon: float, where: str) -> None:
    if not (LAT_MIN - 1e-9 <= lat <= LAT_MAX + 1e-9):
        raise WorldDataError(f"{where}: lat {lat} fora da grade do mundo")
    if not (LON_MIN - 1e-9 <= lon <= LON_MAX + 1e-9):
        raise WorldDataError(f"{where}: lon {lon} fora da grade do mundo")


def _parse_deposit(raw: dict) -> DepositData:
    name = str(_req(raw, "name", "deposit"))
    where = f"deposit[{name}]"
    resource = str(_req(raw, "resource", where))
    if resource not in KNOWN_RESOURCES:
        raise WorldDataError(f"{where}: recurso desconhecido: {resource!r}")
    lat, lon = float(_req(raw, "lat", where)), float(_req(raw, "lon", where))
    _check_geo(lat, lon, where)
    figures = _parse_figures(_req(raw, "figures", where), where)

    # Coerência física por classe de commodity.
    if "grade_pct" in figures:
        g = figures["grade_pct"]
        if g.unit != "pct" or not (0.0 < g.value <= 100.0):
            raise WorldDataError(f"{where}: grade_pct incoerente: {g}")
    if "grade_mg_per_l" in figures:
        g = figures["grade_mg_per_l"]
        if g.unit != "mg_per_L" or g.value <= 0:
            raise WorldDataError(f"{where}: grade_mg_per_l incoerente: {g}")
    for key, fig in figures.items():
        if key.startswith(("production", "reserves", "resources", "recoverable")):
            if fig.value < 0:
                raise WorldDataError(f"{where}: figura negativa: {key}={fig.value}")

    calib = raw.get("calibration", {}) or {}
    rel = calib.get("relative_size_index")
    sugg = calib.get("suggested_world_grade")
    if rel is not None and not (0.0 < float(rel) <= 1.0):
        raise WorldDataError(f"{where}: relative_size_index fora de (0,1]: {rel}")
    if sugg is not None and not (0.0 < float(sugg) <= 1.0):
        raise WorldDataError(f"{where}: suggested_world_grade fora de (0,1]: {sugg}")

    v0 = raw.get("v0", {}) or {}
    return DepositData(
        name=name,
        resource=resource,
        country=str(_req(raw, "country", where)),
        lat=lat, lon=lon,
        operators=tuple(str(o) for o in raw.get("operators", [])),
        figures=figures,
        sources=_parse_sources(_req(raw, "sources", where), where),
        notes=str(raw.get("notes", "")),
        v0_size_t=float(v0.get("size_t", 0.0)),
        v0_grade=float(v0.get("grade", 0.0)),
        relative_size_index=None if rel is None else float(rel),
        suggested_world_grade=None if sugg is None else float(sugg),
    )


def _parse_city(raw: dict) -> CityData:
    name = str(_req(raw, "name", "city"))
    where = f"city[{name}]"
    lat, lon = float(_req(raw, "lat", where)), float(_req(raw, "lon", where))
    _check_geo(lat, lon, where)
    figures = _parse_figures(_req(raw, "figures", where), where)
    if "metro_population" not in figures:
        raise WorldDataError(f"{where}: falta metro_population")
    pop = figures["metro_population"]
    if pop.unit != "people" or pop.value <= 0:
        raise WorldDataError(f"{where}: metro_population incoerente: {pop}")
    v0 = raw.get("v0", {}) or {}
    return CityData(
        name=name,
        country=str(_req(raw, "country", where)),
        lat=lat, lon=lon,
        figures=figures,
        sources=_parse_sources(_req(raw, "sources", where), where),
        v0_demand_weight=float(v0.get("demand_weight", 0.0)),
    )


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
def default_data_path() -> Path:
    """``<repo>/data/world_data.json`` a partir da localização do pacote."""
    return Path(__file__).resolve().parents[2] / "data" / "world_data.json"


def load_world_data(path: str | Path | None = None) -> WorldData:
    """Carrega e valida o dataset. Levanta WorldDataError em qualquer desvio."""
    p = Path(path) if path is not None else default_data_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise WorldDataError(
            f"schema_version {raw.get('schema_version')!r} != {SCHEMA_VERSION}"
        )
    deposits = tuple(_parse_deposit(d) for d in _req(raw, "deposits", "root"))
    cities = tuple(_parse_city(c) for c in _req(raw, "cities", "root"))
    names = [d.name for d in deposits] + [c.name for c in cities]
    if len(names) != len(set(names)):
        raise WorldDataError("nomes duplicados entre depósitos/cidades")
    return WorldData(
        schema_version=SCHEMA_VERSION,
        compiled_at=str(raw.get("compiled_at", "")),
        deposits=deposits,
        cities=cities,
        reference_costs=raw.get("reference_costs", {}) or {},
        game_calibration=raw.get("game_calibration", {}) or {},
    )


# --------------------------------------------------------------------------- #
# Adaptadores para o formato do motor v0 (mundo.world)
# --------------------------------------------------------------------------- #
def to_world_deposits(
    data: WorldData, *, size_scale: float = 3_200_000.0
) -> list[Deposit]:
    """Depósitos no formato de ``world.Deposit``.

    - ``size_t`` = ``relative_size_index`` × ``size_scale`` (padrão: o maior
      ``size_t`` do v0). O índice é RELATIVO dentro da classe de commodity e
      vem das reservas/recursos reais — ver ``game_calibration`` no JSON.
      Sem índice, cai para o ``size_t`` gravado do v0.
    - ``grade`` = ``suggested_world_grade`` (índice de qualidade relativo,
      documentado) ou, quando ele é ``None`` (óleo), o grade do v0.
    - Nome, recurso e coordenadas são os MESMOS do mundo v0.
    """
    out: list[Deposit] = []
    for d in data.deposits:
        if d.relative_size_index is not None:
            size_t = d.relative_size_index * size_scale
        else:
            size_t = d.v0_size_t
        grade = d.suggested_world_grade
        if grade is None:
            grade = d.v0_grade
        out.append(Deposit(d.name, d.resource, d.lat, d.lon, size_t, grade))
    return out


def to_world_cities(data: WorldData) -> list[City]:
    """Cidades no formato de ``world.City``.

    ``demand_weight`` = população metropolitana ÷ população da maior cidade
    do dataset (São Paulo = 1,0) — mesma semântica relativa dos pesos do v0,
    agora ancorada em população real.
    """
    if not data.cities:
        return []
    top = max(c.metro_population for c in data.cities)
    return [
        City(c.name, c.lat, c.lon, c.metro_population / top) for c in data.cities
    ]


# --------------------------------------------------------------------------- #
# Custos de referência
# --------------------------------------------------------------------------- #
def meta_cpm(data: WorldData) -> dict[str, Any]:
    """Bloco de CPM Meta (referência, faixa típica e valor do v0)."""
    return data.reference_costs["meta_ads_cpm"]


def whatsapp_rates(data: WorldData, country: str = "Brasil") -> dict[str, float]:
    """Preço oficial Meta por mensagem (US$) para um país, por categoria."""
    return data.reference_costs["whatsapp_business_per_message"]["rates_usd"][country]


def commodity_price(data: WorldData, key: str) -> Figure:
    """Preço de referência de uma commodity.

    ``key`` ∈ {"copper", "lithium_carbonate", "iron_ore", "brent_oil"}.
    """
    blk = data.reference_costs["commodity_prices"][key]
    ref = blk["reference_usd"]
    return Figure(
        value=float(ref["value"]),
        unit=str(ref["unit"]),
        estimated=bool(ref.get("estimated", False)),
        note=str(ref.get("note", "")),
    )
