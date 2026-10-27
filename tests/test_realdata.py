"""Testes do dataset real (data/world_data.json) e do loader (mundo.realdata).

Só estrutura e coerência — nenhum número é "provado" aqui; o que se prova é
que o schema fecha, que tudo tem fonte e que os adaptadores devolvem objetos
válidos no formato que o motor v0 consome.
"""
import pytest

from mundo import realdata, world

DATA = realdata.load_world_data()


def test_schema_loads():
    assert DATA.schema_version == 1
    assert DATA.compiled_at == "2026-10-26"


NEW_DEPOSITS_V1 = ["Salar del Hombre Muerto", "Cerro Verde (Arequipa)",
                   "El Mutún"]
NEW_CITIES_V1 = ["Montevidéu", "Assunção", "Medellín"]


def test_thirteen_deposits_eleven_cities():
    # v0: 10 depósitos/8 cidades; v1 adicionou 3 + 3 (só no dataset real —
    # o fallback builtin do world.py continua sendo o mundo v0).
    assert len(DATA.deposits) == 13
    assert len(DATA.cities) == 11


def test_names_match_world_v0():
    # as entradas do v0 vêm primeiro e intactas; as do v1 são acréscimos
    assert [d.name for d in DATA.deposits[:10]] == \
        [d.name for d in world.DEPOSITS]
    assert [c.name for c in DATA.cities[:8]] == \
        [c.name for c in world.CITIES]
    assert [d.name for d in DATA.deposits[10:]] == NEW_DEPOSITS_V1
    assert [c.name for c in DATA.cities[8:]] == NEW_CITIES_V1


def test_positions_match_world_v0():
    v0_dep = {d.name: d for d in world.DEPOSITS}
    for d in DATA.deposits[:10]:
        assert d.lat == v0_dep[d.name].lat
        assert d.lon == v0_dep[d.name].lon
        assert d.resource == v0_dep[d.name].resource
    v0_city = {c.name: c for c in world.CITIES}
    for c in DATA.cities[:8]:
        assert c.lat == v0_city[c.name].lat
        assert c.lon == v0_city[c.name].lon


def test_every_entry_has_nonempty_sources():
    for entry in list(DATA.deposits) + list(DATA.cities):
        assert entry.sources, entry.name
        for s in entry.sources:
            assert s.title.strip() and s.publisher.strip()
            assert s.url.startswith(("http://", "https://"))


def test_reference_costs_have_sources():
    costs = DATA.reference_costs
    assert costs["meta_ads_cpm"]["sources"]
    assert costs["whatsapp_business_per_message"]["sources"]
    for key in ("copper", "lithium_carbonate", "iron_ore", "brent_oil"):
        assert costs["commodity_prices"][key]["sources"], key


def test_units_coherent():
    for d in DATA.deposits:
        for fig in d.figures.values():
            assert fig.unit in realdata.ALLOWED_UNITS
            assert fig.value >= 0
    for c in DATA.cities:
        pop = c.figures["metro_population"]
        assert pop.unit == "people" and pop.value > 1_000_000
        gdp = c.figures["gdp_usd_billion"]
        assert gdp.unit == "usd_billion" and gdp.value > 0


def test_grade_units_by_class():
    for d in DATA.deposits:
        if d.resource == "lithium_ore":
            g = d.figure("grade_mg_per_l")
            assert g.unit == "mg_per_L" and 100 < g.value < 3000
        elif d.resource == "copper_ore":
            g = d.figure("grade_pct")
            assert g.unit == "pct" and 0.1 < g.value < 2.0
        elif d.resource == "iron_ore":
            g = d.figure("grade_pct")
            assert g.unit == "pct" and 30 < g.value <= 100


def test_key_real_figures_present():
    atacama = DATA.deposit("Salar de Atacama")
    assert atacama.figure("resources_li_t").value == 13_000_000
    uyuni = DATA.deposit("Salar de Uyuni")
    assert uyuni.figure("resources_li_t").value == 23_000_000
    escondida = DATA.deposit("Escondida (Norte do Chile)")
    assert escondida.figure("production_cu_t_per_year").value > 1_000_000
    presal = DATA.deposit("Pré-sal (Bacia de Santos)")
    assert presal.figure("production_oil_bbl_per_day").value > 2_500_000
    sp = DATA.city("São Paulo")
    assert sp.metro_population > 20_000_000


def test_estimated_flags_are_bool():
    for entry in list(DATA.deposits) + list(DATA.cities):
        for fig in entry.figures.values():
            assert isinstance(fig.estimated, bool)


def test_adapter_deposits_match_world_schema():
    deps = realdata.to_world_deposits(DATA)
    assert len(deps) == 13
    assert len(deps) > len(world.DEPOSITS)   # o dataset v1 é maior que o v0
    for d in deps:
        assert isinstance(d, world.Deposit)
        assert d.size_t > 0
        assert 0.0 < d.grade <= 1.0
        r, c = d.cell
        assert 0 <= r < world.ROWS and 0 <= c < world.COLS


def test_adapter_cities_demand_from_population():
    cities = realdata.to_world_cities(DATA)
    by_name = {c.name: c for c in cities}
    assert by_name["São Paulo"].demand_weight == pytest.approx(1.0)
    for c in cities:
        assert 0.0 < c.demand_weight <= 1.0
    # ordem por população real deve bater com a ordem dos pesos
    assert by_name["Rio de Janeiro"].demand_weight > by_name["Porto Alegre"].demand_weight


def test_reference_cost_accessors():
    cpm = realdata.meta_cpm(DATA)
    lo, hi = cpm["typical_range_usd"]
    assert 0 < lo < cpm["reference_usd"]["value"] < hi
    br = realdata.whatsapp_rates(DATA, "Brasil")
    assert br["marketing"] > br["utility"] > 0
    for key, unit in (("copper", "usd_per_t"), ("lithium_carbonate", "usd_per_t"),
                      ("iron_ore", "usd_per_t"), ("brent_oil", "usd_per_bbl")):
        price = realdata.commodity_price(DATA, key)
        assert price.unit == unit and price.value > 0


def test_loader_rejects_missing_source(tmp_path):
    import json
    raw = json.loads(realdata.default_data_path().read_text(encoding="utf-8"))
    raw["deposits"][0]["sources"] = []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(realdata.WorldDataError):
        realdata.load_world_data(bad)


def test_loader_rejects_unknown_unit(tmp_path):
    import json
    raw = json.loads(realdata.default_data_path().read_text(encoding="utf-8"))
    first = next(iter(raw["deposits"][0]["figures"].values()))
    first["unit"] = "parsecs"
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(realdata.WorldDataError):
        realdata.load_world_data(bad)
