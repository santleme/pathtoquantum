"""Crônica rica (#13, fatia a): detectores determinísticos sobre os eventos
de uma corrida já rodada — sem tocar no tick nem nos goldens.

Cobre o que a narração em-motor ainda não deriva:
- disputas por depósito: o mesmo depósito sondado/minerado por >= 2
  empresas, com >= 3 toques no total (disputa "repetida", não um
  encontro isolado);
- guerras de preço: queda idiossincrática de uma commodity na série de
  preços dos frames (queda >= 25% num passo enquanto o mercado como um
  todo não desaba — colapso geral é regime, não guerra).

Disputas por elo ficam de fora desta fatia de propósito: o motor só
emite `chain_link` para a PRIMEIRA empresa em cada elo, então a
segunda chegada ao mesmo elo não existe no fluxo de eventos — derivar
"disputa de elo" daqui seria inventar dado. Vira fatia futura (emitir
o evento de chegada posterior) e está registrado no docstring do
módulo.
"""

from mundo.chronicle_rich import (
    detect_deposit_disputes,
    detect_price_wars,
)


def _mine(tick, company, deposit):
    return {"tick": tick, "kind": "mine", "text": "", "company": company,
            "data": {"deposit": deposit}}


def _probe(tick, company, text):
    return {"tick": tick, "kind": "probe", "text": text, "company": company,
            "data": {}}


def test_dispute_needs_two_companies_and_three_touches():
    events = [
        _mine(1, "A", "X"),
        _mine(2, "B", "X"),
        _mine(3, "A", "X"),
        _mine(1, "A", "Y"),  # só uma empresa: não é disputa
        _mine(1, "A", "Z"),
        _mine(2, "B", "Z"),  # duas empresas, só 2 toques: não é repetida
    ]
    disputes = detect_deposit_disputes(events)
    assert [d["deposit"] for d in disputes] == ["X"]
    d = disputes[0]
    assert d["companies"] == ["A", "B"]
    assert d["touches"] == 3
    assert d["first_tick"] == 1 and d["last_tick"] == 3
    assert "DISPUTA" in d["text"] and "X" in d["text"]


def test_probe_text_parses_deposit_when_data_empty():
    events = [
        _probe(0, "A", "A sonda Salar de Atacama e encontra um depósito RICO."),
        _probe(0, "B", "B sonda Salar de Atacama e encontra um depósito RICO."),
        _probe(1, "A", "A sonda Salar de Atacama e encontra um depósito RICO."),
        _probe(2, "C", "C sonda algo sem o padrão esperado"),
    ]
    disputes = detect_deposit_disputes(events)
    assert [d["deposit"] for d in disputes] == ["Salar de Atacama"]
    assert disputes[0]["companies"] == ["A", "B"]


def test_disputes_sorted_by_first_tick_then_deposit():
    events = [
        _mine(5, "A", "Beta"),
        _mine(6, "B", "Beta"),
        _mine(7, "A", "Beta"),
        _mine(1, "A", "Alfa"),
        _mine(2, "B", "Alfa"),
        _mine(3, "B", "Alfa"),
    ]
    assert [d["deposit"] for d in detect_deposit_disputes(events)] == [
        "Alfa", "Beta"]


def _frames(series):
    """series: {commodity: [preço por passo]} -> frames com tick 0, 12, ..."""
    n = len(next(iter(series.values())))
    return [{"tick": 12 * i,
             "prices": {c: series[c][i] for c in series}}
            for i in range(n)]


def test_price_war_on_idiosyncratic_drop():
    frames = _frames({"a": [100.0, 60.0, 60.0],
                      "b": [100.0, 100.0, 100.0],
                      "c": [100.0, 101.0, 101.0]})
    wars = detect_price_wars(frames)
    assert len(wars) == 1
    w = wars[0]
    assert w["commodity"] == "a"
    assert w["peak_tick"] == 0 and w["trough_tick"] == 12
    assert w["peak"] == 100.0 and w["trough"] == 60.0
    assert abs(w["drop_pct"] - 40.0) < 1e-9
    assert "GUERRA DE PREÇO" in w["text"]


def test_market_wide_crash_is_not_a_war():
    frames = _frames({"a": [100.0, 60.0],
                      "b": [100.0, 60.0],
                      "c": [100.0, 60.0]})
    assert detect_price_wars(frames) == []


def test_flat_prices_no_wars_and_determinism():
    frames = _frames({"a": [100.0, 100.0], "b": [50.0, 50.0]})
    assert detect_price_wars(frames) == []
    assert (detect_price_wars(frames) == detect_price_wars(frames)
            and detect_deposit_disputes([]) == detect_deposit_disputes([]))
