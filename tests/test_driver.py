"""Testes da Fase 1 do Degrau 1: StockBook (SoA), tabelas e driver.

- StockBook: por dentro array por índice inteiro, por fora Mapping.
- tables: a projeção SoA reflete o estado do motor, sem mutá-lo.
- driver: série == paralelo == Engine direto; agregação determinística.
"""
import json

import numpy as np
import pytest

from mundo import chain, tables
from mundo.companies import StockBook
from mundo.driver import EpisodeSpec, run_batch, run_episode, run_episodes
from mundo.engine import Engine


# --------------------------------------------------------------------- #
# StockBook
# --------------------------------------------------------------------- #
def test_stockbook_mapping_protocol():
    book = StockBook()
    assert len(book) == chain.N_COMMODITIES
    assert list(book) == chain.COMMODITIES            # ordem da tabela
    assert dict(book) == {c: 0.0 for c in chain.COMMODITIES}
    book["copper"] = 3.5
    book["copper"] += 1.5
    assert book["copper"] == 5.0
    assert book.get("device") == 0.0
    assert {k: v for k, v in book.items() if v} == {"copper": 5.0}


def test_stockbook_index_access_matches_names():
    book = StockBook({"lithium": 2.0})
    ci = chain.COMMODITY_INDEX["lithium"]
    assert book.at(ci) == 2.0 == book["lithium"]
    book.add(ci, 0.25)
    assert book["lithium"] == 2.25
    book.set_at(ci, 0.0)
    assert book["lithium"] == 0.0
    assert book.to_list()[ci] == 0.0


def test_stockbook_in_company_state_roundtrip():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(12)
    state = json.loads(json.dumps(eng.state_dict()))
    back = Engine.from_state(state)
    for a, b in zip(eng.companies, back.companies):
        assert isinstance(b.stocks, StockBook)
        assert dict(b.stocks) == dict(a.stocks)


# --------------------------------------------------------------------- #
# Tabelas SoA
# --------------------------------------------------------------------- #
def test_tables_match_engine_state():
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(12)
    stocks = tables.stocks_table(eng)
    assert stocks.shape == (8, chain.N_COMMODITIES)
    assert stocks.dtype == np.float64
    for i, comp in enumerate(eng.companies):
        for c in chain.COMMODITIES:
            assert stocks[i, chain.COMMODITY_INDEX[c]] == comp.stocks[c]
    assert tables.cash_table(eng).tolist() == [c.cash for c in eng.companies]
    assert tables.prices_table(eng).tolist() == \
        [eng.prices[c] for c in chain.COMMODITIES]
    # sem mercado vivo, a âncora pública é o preço-base
    assert tables.anchors_table(eng).tolist() == \
        [chain.BASE_PRICES[c] for c in chain.COMMODITIES]


def test_tables_do_not_mutate_engine():
    import hashlib
    eng = Engine(seed=7, n_companies=8, world_data=False)
    eng.run(12)
    before = json.dumps(eng.state_dict(), sort_keys=True, default=str)
    tables.stocks_table(eng); tables.cash_table(eng); tables.prices_table(eng)
    after = json.dumps(eng.state_dict(), sort_keys=True, default=str)
    assert hashlib.sha256(before.encode()).hexdigest() == \
        hashlib.sha256(after.encode()).hexdigest()


# --------------------------------------------------------------------- #
# Driver de episódios
# --------------------------------------------------------------------- #
def _specs():
    return [EpisodeSpec(seed=s, ticks=24, n_companies=8, world_data=False)
            for s in (7, 8, 9, 10)]


def test_driver_serial_matches_direct_engine():
    for spec in _specs()[:2]:
        got = run_episode(spec)
        ref = Engine(seed=spec.seed, n_companies=8, world_data=False).run(24)
        assert got["scoreboard"] == ref["scoreboard"]
        assert got["chronicle"] == ref["chronicle"]
        assert got["ticks"] == 24 and "frames" not in got


def test_driver_parallel_equals_serial():
    specs = _specs()
    serial = run_episodes(specs, processes=1)
    parallel = run_episodes(specs, processes=2)
    assert parallel == serial                       # ordem e conteúdo
    again = run_episodes(specs, processes=2)        # agregação determinística
    assert again == serial
    boards = {json.dumps(r["scoreboard"], sort_keys=True) for r in serial}
    assert len(boards) == len(specs)                # seeds distintas, mundos distintos


def test_driver_batch_and_god_events():
    ev = ({"tick": 3, "type": "price_shock", "commodity": "lithium",
           "factor": 1.5, "duration": 4},)
    got = run_batch([7], ticks=12, n_companies=8, processes=1,
                    world_data=False, god_events=ev)
    ref = Engine(seed=7, n_companies=8, world_data=False,
                 god_events=list(ev)).run(12)
    assert got[0]["scoreboard"] == ref["scoreboard"]
    assert any(e["kind"] == "god" for e in got[0]["chronicle"])
