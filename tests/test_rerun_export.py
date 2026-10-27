"""Testes do exportador Rerun (issue #12): mapeamento puro + degradação.

O mapeamento frames/crônica -> séries é testado sem o rerun-sdk: a
suíte roda em ambiente sem o pacote, e o caminho de escrita só é
exercitado até a fronteira do import protegido (RerunUnavailable).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mundo import rerun_export
from mundo.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    """Uma corrida real curta, gravada como o motor grava."""
    eng = Engine(seed=7, n_companies=4)
    eng.run(24)
    out = tmp_path_factory.mktemp("corrida")
    eng.save_outputs(str(out))
    return out


def test_load_run_from_save_outputs_dir(run_dir):
    run = rerun_export.load_run(run_dir)
    assert run["seed"] == 7
    assert len(run["frames"]) == 3            # snapshots: ticks 0, 12, 24
    assert run["chronicle"] and run["scoreboard"]
    assert [f["tick"] for f in run["frames"]] == [0, 12, 24]


def test_build_series_maps_company_cash_and_stage(run_dir):
    run = rerun_export.load_run(run_dir)
    series = rerun_export.build_series(run)
    assert len(series.companies) == 4
    frames = sorted(run["frames"], key=lambda f: f["tick"])
    for cs in series.companies:
        assert cs.ticks == [f["tick"] for f in frames]
        expected = [next(c for c in f["companies"] if c["id"] == cs.cid)
                    for f in frames]
        assert cs.cash == [float(c["cash"]) for c in expected]
        assert cs.stage == [int(c["stage"]) for c in expected]
        assert cs.facilities_count == [len(c["facilities"]) for c in expected]
        # sem entregas nesta corrida curta: acumulado é zero e monotônico
        assert cs.super_delivered == [0.0] * len(frames)
    assert series.super_total == [(f["tick"], 0.0) for f in frames]


def test_build_series_maps_deposits_and_prices(run_dir):
    run = rerun_export.load_run(run_dir)
    series = rerun_export.build_series(run)
    assert series.deposits, "frames trazem depósitos"
    ds = series.deposits[0]
    assert ds.ticks == [f["tick"] for f in run["frames"]]
    assert all(0.0 <= v <= 1.0 for v in ds.remaining_frac)
    assert set(series.prices) == set(run["frames"][0]["prices"])
    for name, points in series.prices.items():
        assert points[0] == (0, float(run["frames"][0]["prices"][name]))


def test_super_delivered_is_cumulative_from_chronicle():
    run = {
        "seed": 1, "ticks": 24,
        "frames": [
            {"tick": 0, "date": "jan/2027", "prices": {},
             "companies": [{"id": 0, "name": "Acme", "archetype": "X",
                            "cash": 10.0, "stage": 5, "alive": True,
                            "facilities": [], "territory": []}],
             "deposits": []},
            {"tick": 12, "date": "jan/2028", "prices": {},
             "companies": [{"id": 0, "name": "Acme", "archetype": "X",
                            "cash": 12.0, "stage": 5, "alive": True,
                            "facilities": [], "territory": []}],
             "deposits": []},
            {"tick": 24, "date": "jan/2029", "prices": {},
             "companies": [{"id": 0, "name": "Acme", "archetype": "X",
                            "cash": 9.0, "stage": 5, "alive": True,
                            "facilities": [], "territory": []}],
             "deposits": []},
        ],
        "chronicle": [
            {"tick": 5, "kind": "record", "company": "Acme",
             "text": "Acme entrega um SUPERCOMPUTADOR montado por conta "
                     "própria.", "data": {}},
            {"tick": 20, "kind": "record", "company": "Acme",
             "text": "Acme entrega um SUPERCOMPUTADOR montado por conta "
                     "própria.", "data": {"units": 2}},
            {"tick": 21, "kind": "record", "company": "Acme",
             "text": "Acme bate um recorde qualquer.", "data": {}},
        ],
    }
    series = rerun_export.build_series(run)
    assert series.companies[0].super_delivered == [0.0, 1.0, 3.0]
    assert series.super_total == [(0, 0.0), (12, 1.0), (24, 3.0)]


def test_super_delivered_ignores_records_that_only_mention_supercomputer():
    """Regressão: record que só MENCIONA supercomputador (marco de elo,
    anúncio) não é entrega — a regra canônica é a mesma frase do
    chronicle_rich ("entrega um SUPERCOMPUTADOR")."""
    run = {
        "seed": 1, "ticks": 24,
        "frames": [
            {"tick": 0, "date": "jan/2027", "prices": {},
             "companies": [{"id": 0, "name": "Acme", "archetype": "X",
                            "cash": 10.0, "stage": 5, "alive": True,
                            "facilities": [], "territory": []}],
             "deposits": []},
            {"tick": 24, "date": "jan/2029", "prices": {},
             "companies": [{"id": 0, "name": "Acme", "archetype": "X",
                            "cash": 9.0, "stage": 5, "alive": True,
                            "facilities": [], "territory": []}],
             "deposits": []},
        ],
        "chronicle": [
            {"tick": 3, "kind": "record", "company": "Acme",
             "text": "MARCO DE ERA: Acme fecha a ERA 1 — é a primeira a "
                     "dominar o elo de supercomputador.",
             "data": {"stage": 5, "record": "first_link"}},
            {"tick": 8, "kind": "record", "company": "Acme",
             "text": "Acme anuncia a montadora de SUPERCOMPUTADORES. "
                     "O topo da cadeia está ao alcance.", "data": {}},
            {"tick": 10, "kind": "record", "company": "Acme",
             "text": "Acme entrega um SUPERCOMPUTADOR montado por "
                     "conta própria.", "data": {}},
        ],
    }
    series = rerun_export.build_series(run)
    assert series.companies[0].super_delivered == [0.0, 1.0]
    assert series.super_total == [(0, 0.0), (24, 1.0)]


def test_export_without_rerun_sdk_raises_unavailable(run_dir, monkeypatch):
    monkeypatch.setitem(sys.modules, "rerun", None)   # força ImportError
    with pytest.raises(rerun_export.RerunUnavailable):
        rerun_export.export_rerun(run_dir, str(run_dir / "run.rrd"))


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "export_rerun_cli", ROOT / "scripts" / "export_rerun.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_without_rerun_sdk_exits_3_with_clear_message(
        run_dir, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "rerun", None)
    cli = _load_cli()
    assert cli.main([str(run_dir)]) == 3
    assert "rerun-sdk não instalado" in capsys.readouterr().err
    assert not (run_dir / "run.rrd").exists()


def test_cli_missing_source_exits_2(capsys):
    cli = _load_cli()
    assert cli.main(["/caminho/que/nao/existe"]) == 2
    assert "não encontrada" in capsys.readouterr().err


def test_mapping_on_saved_real_run():
    """Massa de prova real: o nascimento-v0 em results/ (gitignored —
    pula em clone fresco, roda onde a corrida foi gerada)."""
    saved = ROOT / "results" / "nascimento-v0"
    if not saved.is_dir():
        pytest.skip("results/nascimento-v0 ausente (gitignored)")
    run = rerun_export.load_run(saved)
    series = rerun_export.build_series(run)
    assert len(series.companies) == 8
    assert all(len(cs.cash) == len(run["frames"]) for cs in series.companies)
    by_name = {cs.name: cs for cs in series.companies}
    frame0 = {c["name"]: c for c in run["frames"][0]["companies"]}
    for name, cs in by_name.items():
        assert cs.cash[0] == float(frame0[name]["cash"])
    assert len(series.events) == len(run["chronicle"])
    assert series.scoreboard and series.scoreboard[0]["name"]


def test_entity_name_escapes_path_specials():
    assert rerun_export._entity_name("Vetor Sul") == "Vetor\\ Sul"
    assert rerun_export._entity_name("Escondida (Norte)") == \
        "Escondida\\ \\(Norte\\)"
    assert rerun_export._entity_name("lithium_ore") == "lithium_ore"
    assert rerun_export._entity_name("a/b") == "a-b"
