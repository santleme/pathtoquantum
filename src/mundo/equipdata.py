"""Parâmetros dos equipamentos (B2) — DADO com fontes, não código.

Fonte canônica: ``data/facility_params.json`` (desgaste, hazard de
Weibull, reparo, manutenção e overhaul por tipo de instalação, com
nota de calibração ancorada no estudo — ``docs/ESTUDO-MOTOR-AMBIENTE.md``
§B2: Weibull β≈1,6 de frotas de mineração; disponibilidade real de
frotas 77–85%, operações boas 85%+).

Fallback embutido: o bundle do Kaggle carrega só ``src/`` + pyproject
(sem ``data/``), então os MESMOS parâmetros vivem embutidos abaixo.
Um teste garante que arquivo e fallback nunca divergem — calibrar é
editar o JSON e regenerar o fallback, nunca editar um dos dois só.

As fórmulas (hazard de Weibull, capacidade efetiva) são puras e vivem
aqui para serem testáveis sem motor.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from . import chain

SCHEMA_VERSION = 1

_DEFAULT_JSON = r"""{
 "compiled_at": "2026-10-26",
 "facilities": {
  "assembly": {
   "beta": 1.6,
   "calibration_note": "Montadora de supercomputadores: ambiente limpo e controlado — menor desgaste, η=60 meses -> MTBF ≈ 54 meses.",
   "eta_months": 60,
   "wear_rate": 0.007
  },
  "factory": {
   "beta": 1.6,
   "calibration_note": "Fábrica de componentes: η=46 meses -> MTBF ≈ 41 meses.",
   "eta_months": 46,
   "wear_rate": 0.01
  },
  "mine": {
   "beta": 1.6,
   "calibration_note": "Mina a céu aberto/subterrânea: ambiente abrasivo — maior desgaste por mês operado. Weibull β=1,6 (frota de caminhões de mineração, estudo §B2); η=42 meses -> MTBF de planta nova ≈ 38 meses.",
   "eta_months": 42,
   "wear_rate": 0.016
  },
  "plant": {
   "beta": 1.6,
   "calibration_note": "Planta de dispositivos: η=46 meses -> MTBF ≈ 41 meses.",
   "eta_months": 46,
   "wear_rate": 0.01
  },
  "refinery": {
   "beta": 1.6,
   "calibration_note": "Refinaria: processo contínuo, desgaste moderado; η=50 meses -> MTBF ≈ 45 meses.",
   "eta_months": 50,
   "wear_rate": 0.012
  }
 },
 "model": {
  "age_derate": 0.15,
  "age_derate_months": 240,
  "hazard_scale": 1.0,
  "maint_downtime_h": 0.3,
  "maint_frac": 0.022,
  "maint_restore": 0.5,
  "note": "Calibração-alvo (estudo §B2): disponibilidade A = MTBF/(MTBF+MTTR) em ~80-85% para frotas rodadas até quebrar (idade cresce sem overhaul, hazard de Weibull sobe, reparo espera caixa) e ~92-95% para frotas mantidas (manutenção segura h e portanto a eficiência; overhaul zera a idade e o hazard). hazard_scale/wear_scale = 1,0 no mundo; são as alavancas de teste/Deus para forçar quebras e desgaste sem tocar no arquivo.",
  "overhaul_frac": 0.6,
  "repair_frac_max": 0.15,
  "repair_frac_min": 0.08,
  "repair_ticks_lognorm_mu": 0.0,
  "repair_ticks_lognorm_sigma": 0.6,
  "repair_ticks_max": 3,
  "repair_ticks_min": 1,
  "wear_scale": 1.0
 },
 "policy": {
  "maint_h_base": 0.3,
  "maint_h_care_span": 0.35,
  "note": "A decisão é da política, os custos são do motor. care = 1 - aggression: limiar de manutenção preventiva h* = base + care*span (Agressiva ~0,34 roda até quebrar; Cautelosa ~0,55 mantém cedo); reparo de quebra é pago quando caixa-reserva > custo * mult, com mult interpolado de care0 (2,0) a care1 (1,0) — quem não cuida, adia o conserto; overhaul quando idade >= 150 meses e h <= 0,45.",
  "overhaul_max_cond": 0.45,
  "overhaul_min_age": 150,
  "repair_mult_care0": 2.0,
  "repair_mult_care1": 1.0
 },
 "purpose": "Parâmetros dos equipamentos (B2, Degrau 1 Fase 4): desgaste, hazard de quebra de Weibull, reparo, manutenção preventiva e overhaul por tipo de instalação. DADO versionado com fontes (DEGRAU1-DESIGN §4/B2; ESTUDO-MOTOR-AMBIENTE §B2) — calibrar é editar este arquivo, nunca o motor.",
 "schema_version": 1,
 "sources": [
  {
   "date": "2015-2025",
   "publisher": "Literatura de confiabilidade de frotas de mineração (Weibull β≈1,62 em caminhões; disponibilidade medida de frotas escavadeira-caminhão 77-78%, operações boas 85%+)",
   "title": "apud ESTUDO-MOTOR-AMBIENTE §B2 (docs/ESTUDO-MOTOR-AMBIENTE.md)",
   "url": ""
  },
  {
   "date": "2026-10-26",
   "publisher": "Path to Quantum",
   "title": "DEGRAU1-DESIGN §4/B2 — fórmula mínima: cap_efetiva = capacity*h*(1-0,15*min(1, age/240)); hazard Weibull β≈1,6; reparo 1-3 ticks a 8-15% do custo; PM 1,5-3% restaura h em +0,5; overhaul 60% zera idade e h",
   "url": ""
  }
 ]
}"""


class EquipParamsError(ValueError):
    """Schema inválido ou parâmetro incoerente em facility_params."""


def embedded_params() -> dict:
    """Os parâmetros embutidos (fallback quando o JSON não está no bundle)."""
    return json.loads(_DEFAULT_JSON)


def default_data_path() -> Path:
    """``<repo>/data/facility_params.json`` a partir da localização do pacote."""
    return Path(__file__).resolve().parents[2] / "data" / "facility_params.json"


def load_facility_params(path: str | Path | None = None) -> dict:
    """Carrega e valida o JSON. Levanta EquipParamsError em qualquer desvio."""
    p = Path(path) if path is not None else default_data_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return _validate(raw)


_FACILITY_FLOAT_KEYS = ("eta_months", "beta", "wear_rate")
_MODEL_KEYS = ("age_derate", "age_derate_months", "repair_frac_min",
               "repair_frac_max", "maint_frac", "maint_restore",
               "maint_downtime_h", "overhaul_frac",
               "repair_ticks_lognorm_mu", "repair_ticks_lognorm_sigma",
               "repair_ticks_min", "repair_ticks_max",
               "hazard_scale", "wear_scale")
_POLICY_KEYS = ("maint_h_base", "maint_h_care_span", "repair_mult_care0",
                "repair_mult_care1", "overhaul_min_age", "overhaul_max_cond")


def _num(section: dict, key: str, where: str) -> float:
    v = section.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EquipParamsError(f"{where}.{key}: ausente ou não-numérico")
    return float(v)


def _validate(raw: dict) -> dict:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise EquipParamsError(
            f"schema_version {raw.get('schema_version')!r} != {SCHEMA_VERSION}")
    facs = raw.get("facilities")
    if not isinstance(facs, dict):
        raise EquipParamsError("'facilities' ausente ou inválido")
    missing = set(chain.FACILITIES) - set(facs)
    extra = set(facs) - set(chain.FACILITIES)
    if missing or extra:
        raise EquipParamsError(
            f"facilities divergem da cadeia: faltam {sorted(missing)}, "
            f"sobram {sorted(extra)}")
    for name, p in facs.items():
        where = f"facilities.{name}"
        for key in _FACILITY_FLOAT_KEYS:
            _num(p, key, where)
        if p["eta_months"] <= 0:
            raise EquipParamsError(f"{where}.eta_months <= 0")
        if not (1.0 <= p["beta"] <= 3.0):
            raise EquipParamsError(f"{where}.beta fora de [1, 3]: {p['beta']}")
        if not (0.0 < p["wear_rate"] < 0.1):
            raise EquipParamsError(f"{where}.wear_rate fora de (0, 0,1)")
        if not p.get("calibration_note"):
            raise EquipParamsError(f"{where}.calibration_note ausente")
    model = raw.get("model") or {}
    for key in _MODEL_KEYS:
        _num(model, key, "model")
    if not (0.0 <= model["age_derate"] < 1.0):
        raise EquipParamsError("model.age_derate fora de [0, 1)")
    if model["age_derate_months"] < 1:
        raise EquipParamsError("model.age_derate_months < 1")
    if not (0.0 < model["repair_frac_min"] <= model["repair_frac_max"] < 1.0):
        raise EquipParamsError("model.repair_frac_* incoerentes")
    if not (0.0 < model["maint_frac"] <= 0.1):
        raise EquipParamsError("model.maint_frac fora de (0, 0,1]")
    if not (0.0 < model["maint_restore"] <= 1.0):
        raise EquipParamsError("model.maint_restore fora de (0, 1]")
    if not (0.0 <= model["maint_downtime_h"] < 1.0):
        raise EquipParamsError("model.maint_downtime_h fora de [0, 1)")
    if not (0.0 < model["overhaul_frac"] < 1.0):
        raise EquipParamsError("model.overhaul_frac fora de (0, 1)")
    if int(model["repair_ticks_min"]) < 1 \
            or int(model["repair_ticks_max"]) < int(model["repair_ticks_min"]):
        raise EquipParamsError("model.repair_ticks_* incoerentes")
    if model["repair_ticks_lognorm_sigma"] < 0:
        raise EquipParamsError("model.repair_ticks_lognorm_sigma < 0")
    if model["hazard_scale"] < 0 or model["wear_scale"] < 0:
        raise EquipParamsError("model.*_scale negativos")
    pol = raw.get("policy") or {}
    for key in _POLICY_KEYS:
        _num(pol, key, "policy")
    if not (0.0 <= pol["maint_h_base"] <= 1.0) or pol["maint_h_care_span"] < 0 \
            or pol["maint_h_base"] + pol["maint_h_care_span"] > 1.0:
        raise EquipParamsError("policy.maint_h_* incoerentes")
    if pol["repair_mult_care0"] < pol["repair_mult_care1"] \
            or pol["repair_mult_care1"] < 1.0:
        raise EquipParamsError("policy.repair_mult_* incoerentes")
    if int(pol["overhaul_min_age"]) < 12:
        raise EquipParamsError("policy.overhaul_min_age < 12")
    if not (0.0 < pol["overhaul_max_cond"] < 1.0):
        raise EquipParamsError("policy.overhaul_max_cond fora de (0, 1)")
    return raw


def resolve_equip_params(override: dict | None = None) -> dict:
    """Parâmetros efetivos: JSON do repo quando existe; fallback embutido
    quando não (bundle do Kaggle). ``override`` (mesmo schema, parcial
    por instalação/seção) é mesclado por cima — é como testes forçam
    quebras (hazard_scale) e desgaste (wear_scale) sem tocar no arquivo."""
    try:
        base = load_facility_params()
    except (FileNotFoundError, EquipParamsError):
        base = _validate(embedded_params())
    if override:
        merged = copy.deepcopy(base)
        for name, fields in (override.get("facilities") or {}).items():
            if name not in merged["facilities"]:
                raise EquipParamsError(
                    f"override de instalação desconhecida: {name!r}")
            merged["facilities"][name].update(fields)
        for section in ("model", "policy"):
            if section in override:
                merged[section].update(override[section])
        return _validate(merged)
    return base


# --------------------------------------------------------------------------- #
# Matemática pura dos equipamentos (testável sem motor)
# --------------------------------------------------------------------------- #
def weibull_hazard(age: int, eta: float, beta: float) -> float:
    """Probabilidade de a instalação quebrar NESTE mês, tendo `age` meses
    (hazard discreto de Weibull): q = 1 − exp(−[((a+1)/η)^β − (a/η)^β]).
    β > 1 = desgaste crescente com a idade (β≈1,6 medido em frotas de
    mineração); o MTBF implícito é η·Γ(1 + 1/β)."""
    if age < 0:
        raise ValueError("age < 0")
    return 1.0 - math.exp(
        -(((age + 1) / eta) ** beta - (age / eta) ** beta))


def effective_capacity(capacity: float, cond: float, age: int,
                       model: dict) -> float:
    """cap_efetiva = capacity · h · (1 − derate·min(1, age/meses)):
    a condição manda no curto prazo; a idade cobra até `age_derate`
    (15%) mesmo de planta bem mantida, ao longo de 240 meses."""
    derate = model["age_derate"] * min(1.0, age / model["age_derate_months"])
    return capacity * cond * (1.0 - derate)
