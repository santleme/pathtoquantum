"""Crônica rica (#13, fatia b): retrospectiva por era, derivada só dos
eventos e frames de uma corrida já rodada — sem tocar no tick nem nos
goldens, como a fatia (a).

Era = a do motor: 60 ticks (5 anos, `Engine._era_summary`). Um evento
no tick 60 abre a era 1, não fecha a era 0.

A retrospectiva de cada era registra, quando houver dado para isso:
- líderes ao fim da era (caixa e cadeia, tirados do último frame);
- viradas de liderança (eventos `rivalry` na era, por métrica);
- primeiras: falência, entrega de supercomputador, elos da cadeia;
- contagens: falências, aquisições, entregas de supercomputador,
  empresas vivas ao fim da era.

Não inventa dado: o recorde de elo de supercomputador (`record` com
"elo de supercomputador") NÃO conta como entrega — entrega é o `record`
"entrega um SUPERCOMPUTADOR". Sem frame com empresas, os líderes
ficam None em vez de inventados.
"""

from mundo.chronicle_rich import analyze_rich, era_retrospectives


def _ev(tick, kind, company=None, text="", data=None):
    return {"tick": tick, "kind": kind, "text": text, "company": company,
            "data": data or {}}


def _frame(tick, companies):
    return {"tick": tick, "prices": {},
            "companies": [{"id": i, "name": n, "alive": a, "cash": c,
                           "stage": s}
                          for i, (n, a, c, s) in enumerate(companies)]}


def test_empty_inputs_no_eras():
    assert era_retrospectives([], []) == []


def test_era_groups_by_60_ticks_and_reports_firsts_and_leaders():
    events = [
        _ev(5, "chain_link", "A", "MARCO", {"stage": 1}),
        _ev(10, "bankruptcy", "B", "FALÊNCIA"),
        _ev(20, "record", "A", "A entrega um SUPERCOMPUTADOR montado."),
        _ev(30, "rivalry", "C", "RIVALIDADE", {"metric": "cash"}),
        _ev(65, "bankruptcy", "C", "FALÊNCIA"),
    ]
    frames = [
        _frame(0, [("A", True, 10.0, 0), ("B", True, 20.0, 0),
                   ("C", True, 15.0, 0)]),
        _frame(59, [("A", True, 100.0, 2), ("B", False, 50.0, 1),
                    ("C", True, 80.0, 1)]),
        _frame(61, [("A", True, 110.0, 2), ("C", False, 0.0, 1)]),
    ]
    eras = era_retrospectives(events, frames)
    assert [e["era"] for e in eras] == [0, 1]

    e0 = eras[0]
    assert (e0["start_tick"], e0["end_tick"]) == (0, 59)
    assert e0["cash_leader"] == "A" and e0["stage_leader"] == "A"
    assert e0["first_bankruptcy"] == {"company": "B", "tick": 10}
    assert e0["first_supercomputer"] == {"company": "A", "tick": 20}
    assert e0["supercomputer_deliveries"] == 1 and e0["bankruptcies"] == 1
    assert e0["leadership_changes"] == [
        {"tick": 30, "metric": "cash", "company": "C"}]
    assert e0["first_links"] == [{"stage": 1, "company": "A", "tick": 5}]
    assert e0["alive"] == 2 and e0["companies"] == 3
    assert "RETROSPECTIVA DA ERA 0" in e0["text"]
    assert "B" in e0["text"] and "SUPERCOMPUTADOR" in e0["text"]

    e1 = eras[1]
    assert (e1["start_tick"], e1["end_tick"]) == (60, 65)
    assert e1["first_bankruptcy"] == {"company": "C", "tick": 65}
    assert e1["first_supercomputer"] is None
    assert e1["cash_leader"] == "A" and e1["alive"] == 1


def test_era_boundary_tick_60_opens_next_era():
    events = [_ev(59, "bankruptcy", "A", "FALÊNCIA"),
              _ev(60, "bankruptcy", "B", "FALÊNCIA")]
    eras = era_retrospectives(events, [])
    assert [e["era"] for e in eras] == [0, 1]
    assert eras[0]["first_bankruptcy"]["company"] == "A"
    assert eras[1]["first_bankruptcy"]["company"] == "B"


def test_chain_link_stage_parsed_from_text_when_data_empty():
    # Crônicas antigas (viewer da corrida de nascimento) têm data={} no
    # chain_link; o estágio tem de vir do texto, não sumir.
    events = [
        _ev(2, "chain_link", "A",
            "MARCO DA CADEIA: A é a primeira a dominar o elo de refino."),
        _ev(5, "chain_link", "A",
            "MARCO DA CADEIA: A é a primeira a dominar o elo de algo."),
    ]
    eras = era_retrospectives(events, [])
    assert eras[0]["first_links"] == [
        {"stage": 2, "company": "A", "tick": 2}]


def test_supercomputer_link_record_is_not_a_delivery():
    events = [
        _ev(8, "record", "A",
            "MARCO DE ERA: A fecha a ERA 1 — é a primeira a dominar "
            "o elo de supercomputador.", {"stage": 5, "record": "first_link"}),
    ]
    eras = era_retrospectives(events, [])
    assert eras[0]["supercomputer_deliveries"] == 0
    assert eras[0]["first_supercomputer"] is None


def test_frames_without_companies_leave_leaders_none():
    eras = era_retrospectives([_ev(3, "mine", "A", "", {"deposit": "X"})],
                              [{"tick": 3, "prices": {"a": 1.0}}])
    assert eras[0]["cash_leader"] is None
    assert eras[0]["stage_leader"] is None
    assert eras[0]["alive"] is None


def test_analyze_rich_includes_retrospectives_and_keeps_slice_a():
    events = [_ev(1, "mine", "A", "", {"deposit": "X"}),
              _ev(2, "mine", "B", "", {"deposit": "X"}),
              _ev(3, "mine", "A", "", {"deposit": "X"})]
    out = analyze_rich(events, [])
    assert "deposit_disputes" in out and "price_wars" in out
    assert len(out["era_retrospectives"]) == 1
    assert out["era_retrospectives"][0]["era"] == 0
    # Determinismo: duas chamadas, mesmo resultado.
    assert analyze_rich(events, []) == out
