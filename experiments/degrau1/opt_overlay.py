"""Overlay de otimizações BIT-IDÊNTICAS sobre o motor oficial (spike).

Variantes seguras dos hotspots 1–2 do ESTUDO-MOTOR-AMBIENTE §A1:

1. `HeuristicPolicy.buffer` memoizado — o buffer é função pura de
   (kinds da empresa, traço vertical, commodity). O cache mora na
   própria empresa (dict commodity -> valor) e é invalidado onde os
   kinds mudam (`add_facility`, `_sync_kinds` — que cobre também a
   aquisição e o restore). Lookup = um `dict.get` por string.
2. `HeuristicPolicy.pick_deposit` com a parcela estática do score
   (`BASE_PRICES[recurso] / (1 + dist/25)` — mesma expressão, mesmo
   float) pré-computada por (engine, empresa) numa lista alinhada a
   `engine.deposits`. A sequência de chamadas `rng.uniform` (uma por
   candidato elegível, na ordem dos depósitos) e a ordem das
   multiplicações são idênticas às do original.

Lições da primeira versão deste overlay (medida: 0,80x — PIOR):
cache indexado por tuplas/frozenset construídos por chamada e
pré-varredura de early-exit custam mais em CPython do que o trabalho
que poupam; e a "pré-varredura" do `pick_deposit` não economiza nada
porque o laço original já pula inelegíveis sem tocar o RNG. Fica o
registro no README do spike.

O hotspot 3 (`_market`, total corrente) NÃO é bit-idêntico por
construção — está isolado em `market_rt.py` para medição separada.
O hotspot 5 (`_emit_flows`) muda o payload do evento `flows`: é
decisão de golden, não otimização (DEGRAU1-DESIGN §3.5).

Nada aqui é importado pelo pacote oficial; o spike aplica e remove
os patches explicitamente.
"""
from __future__ import annotations

from mundo import chain
from mundo.companies import Company
from mundo.engine import HeuristicPolicy

_orig_buffer = HeuristicPolicy.buffer
_orig_pick = HeuristicPolicy.pick_deposit
_orig_add_facility = Company.add_facility
_orig_sync_kinds = Company._sync_kinds


def _buffer_fast(self, comp, commodity):
    cache = comp.__dict__.get("_spike_buf_cache")
    if cache is None:
        cache = comp.__dict__["_spike_buf_cache"] = {}
    v = cache.get(commodity)
    if v is None:
        v = _orig_buffer(self, comp, commodity)
        cache[commodity] = v
    return v


def _add_facility_fast(self, kind, cell):
    fac = _orig_add_facility(self, kind, cell)
    self.__dict__.pop("_spike_buf_cache", None)
    return fac


def _sync_kinds_fast(self):
    _orig_sync_kinds(self)
    self.__dict__.pop("_spike_buf_cache", None)


def _pick_deposit_fast(self, engine, comp):
    caches = self.__dict__.setdefault("_spike_pick_bases", {})
    key = (id(engine), comp.cid)
    entry = caches.get(key)
    deposits = engine.deposits
    if entry is None or entry[0] != len(deposits):
        hq = engine._city_by_name[comp.hq_city]
        bases = []
        for d in deposits:
            dist = abs(d.lat - hq.lat) + abs(d.lon - hq.lon)
            bases.append(chain.BASE_PRICES[d.resource] / (1.0 + dist / 25.0))
        entry = (len(deposits), bases)
        caches[key] = entry
    bases = entry[1]
    mined = {f.get("deposit") for f in comp.facilities.values()}
    claimed = engine.claimed_by
    cid = comp.cid
    uniform = engine.rng.uniform
    knowledge = comp.knowledge
    best, best_score = None, -1.0
    for i, d in enumerate(deposits):
        owner = claimed.get(d.cell)
        if owner is not None and owner != cid:
            continue
        if d.name in mined:
            continue
        score = bases[i]
        known = knowledge.get(d.name)
        if known:
            score *= 0.3 + known[0]           # teor conhecido pesa
            score *= min(1.5, known[1] / 800_000.0)
        score *= uniform(0.9, 1.1)            # gosto/erro humano
        if score > best_score:
            best, best_score = d, score
    return best


def apply() -> None:
    HeuristicPolicy.buffer = _buffer_fast
    HeuristicPolicy.pick_deposit = _pick_deposit_fast
    Company.add_facility = _add_facility_fast
    Company._sync_kinds = _sync_kinds_fast


def remove() -> None:
    HeuristicPolicy.buffer = _orig_buffer
    HeuristicPolicy.pick_deposit = _orig_pick
    Company.add_facility = _orig_add_facility
    Company._sync_kinds = _orig_sync_kinds
