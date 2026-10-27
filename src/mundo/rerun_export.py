"""Exportador Rerun de corridas (issue #12 — viewer/replay).

Lê os artefatos que uma corrida já produz (``Engine.save_outputs``:
``frames.json`` + ``chronicle.json`` + ``scoreboard.json``) e grava um
``.rrd`` com timeline navegável no Rerun:

- ``companies/<nome>/cash|stage|alive|facilities_count|super_delivered``
  — séries por empresa a cada frame (snapshots do motor);
  ``super_delivered`` é o acumulado de entregas de supercomputador
  derivado dos eventos ``record`` da crônica (o motor só expõe o total
  final por empresa, não a série);
- ``companies/<nome>/facilities`` e ``/territory`` — pontos no mapa de
  células por frame; ``companies/<nome>/info`` — arquétipo/HQ (estático);
- ``deposits/<nome>/remaining_frac`` — série de exaustão;
  ``deposits/<nome>/position`` — célula no mapa (estático) e ``info``
  com recurso/lat/lon;
- ``world/prices/<commodity>`` — série de preços; ``world/super_total``;
- ``chronicle/<kind>`` — eventos da crônica como TextLog na timeline;
- ``summary/scoreboard`` — placar final em texto (estático).

O mapeamento (``build_series``) é puro e testável SEM o rerun-sdk.
A escrita do ``.rrd`` importa ``rerun`` tardiamente: sem o pacote,
``export_rerun`` levanta :class:`RerunUnavailable` — o CLI avisa e sai
com código próprio (3), sem traceback e sem gravar nada. O rerun-sdk
é dependência OPCIONAL e não entra no pacote.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


class RerunUnavailable(RuntimeError):
    """rerun-sdk não instalado: exportação impossível, sem crash."""


@dataclass
class CompanySeries:
    cid: int
    name: str
    archetype: str
    hq: str | None
    color: str | None
    ticks: list[int] = field(default_factory=list)
    cash: list[float] = field(default_factory=list)
    stage: list[int] = field(default_factory=list)
    alive: list[bool] = field(default_factory=list)
    facilities_count: list[int] = field(default_factory=list)
    super_delivered: list[float] = field(default_factory=list)
    facilities_cells: list[list[list]] = field(default_factory=list)
    territory_cells: list[list[list]] = field(default_factory=list)


@dataclass
class DepositSeries:
    name: str
    resource: str
    cell: list
    lat: float | None
    lon: float | None
    ticks: list[int] = field(default_factory=list)
    remaining_frac: list[float] = field(default_factory=list)


@dataclass
class RunSeries:
    """Tudo que o .rrd vai conter, já mapeado e sem depender do SDK."""
    seed: int | None
    ticks: int
    companies: list[CompanySeries]
    deposits: list[DepositSeries]
    prices: dict[str, list[tuple[int, float]]]
    super_total: list[tuple[int, float]]
    events: list[dict]                      # crônica bruta (dicts JSON)
    scoreboard: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------- #
# Carga dos artefatos
# --------------------------------------------------------------------- #
def load_run(source: str | os.PathLike | dict) -> dict:
    """Carrega uma corrida de: dict em memória, arquivo frames.json
    ou diretório de saída (``save_outputs``). Devolve o dict bruto com
    ``frames``, ``chronicle`` e, quando houver, ``scoreboard``."""
    if isinstance(source, dict):
        return source
    path = os.fspath(source)
    if os.path.isdir(path):
        frames_path = os.path.join(path, "frames.json")
        with open(frames_path, encoding="utf-8") as f:
            run = json.load(f)
        chronicle_path = os.path.join(path, "chronicle.json")
        if "chronicle" not in run and os.path.exists(chronicle_path):
            with open(chronicle_path, encoding="utf-8") as f:
                run["chronicle"] = json.load(f)
        scoreboard_path = os.path.join(path, "scoreboard.json")
        if os.path.exists(scoreboard_path):
            with open(scoreboard_path, encoding="utf-8") as f:
                run["scoreboard"] = json.load(f)
        return run
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------- #
# Mapeamento puro (frames + crônica -> séries)
# --------------------------------------------------------------------- #
def _super_deliveries(chronicle: list[dict]) -> dict[str, list[tuple[int, float]]]:
    """Entregas de supercomputador por empresa: (tick, unidades).

    O motor registra a entrega como evento ``record`` com o texto
    canônico "entrega um SUPERCOMPUTADOR" (engine._produce) e acumula
    as unidades em ``_super_by_cid`` sem expor a série. Unidades
    explícitas em ``data`` vencem; sem elas, 1 por evento."""
    out: dict[str, list[tuple[int, float]]] = {}
    for e in chronicle:
        if e.get("kind") != "record":
            continue
        if "SUPERCOMPUTADOR" not in (e.get("text") or ""):
            continue
        data = e.get("data") or {}
        units = data.get("units", data.get("qty", 1))
        out.setdefault(e.get("company") or "", []).append(
            (int(e["tick"]), float(units)))
    return out


def _cumulative_at(deliveries: list[tuple[int, float]], tick: int) -> float:
    return sum(u for t, u in deliveries if t <= tick)


def build_series(run: dict) -> RunSeries:
    """Mapeia o dict bruto da corrida para as séries do exportador."""
    frames = sorted(run["frames"], key=lambda f: f["tick"])
    chronicle = run.get("chronicle") or []
    deliveries = _super_deliveries(chronicle)

    companies: dict[int, CompanySeries] = {}
    deposits: dict[str, DepositSeries] = {}
    prices: dict[str, list[tuple[int, float]]] = {}
    super_total: list[tuple[int, float]] = []

    for frame in frames:
        tick = int(frame["tick"])
        total_super = 0.0
        for c in frame["companies"]:
            cs = companies.get(c["id"])
            if cs is None:
                cs = companies[c["id"]] = CompanySeries(
                    cid=c["id"], name=c["name"], archetype=c["archetype"],
                    hq=c.get("hq"), color=c.get("color"))
            cs.ticks.append(tick)
            cs.cash.append(float(c["cash"]))
            cs.stage.append(int(c["stage"]))
            cs.alive.append(bool(c["alive"]))
            facs = c.get("facilities") or []
            cs.facilities_count.append(len(facs))
            cs.facilities_cells.append([list(f["cell"]) for f in facs])
            cs.territory_cells.append(
                [list(cell) for cell in (c.get("territory") or [])])
            delivered = _cumulative_at(deliveries.get(c["name"], []), tick)
            cs.super_delivered.append(delivered)
            total_super += delivered
        super_total.append((tick, total_super))
        for name, value in (frame.get("prices") or {}).items():
            prices.setdefault(name, []).append((tick, float(value)))
        for d in frame.get("deposits") or []:
            ds = deposits.get(d["name"])
            if ds is None:
                ds = deposits[d["name"]] = DepositSeries(
                    name=d["name"], resource=d["resource"],
                    cell=list(d["cell"]), lat=d.get("lat"), lon=d.get("lon"))
            ds.ticks.append(tick)
            ds.remaining_frac.append(float(d["remaining_frac"]))

    return RunSeries(
        seed=run.get("seed"),
        ticks=int(run.get("ticks", frames[-1]["tick"] if frames else 0)),
        companies=[companies[k] for k in sorted(companies)],
        deposits=[deposits[k] for k in sorted(deposits)],
        prices=prices, super_total=super_total, events=chronicle,
        scoreboard=run.get("scoreboard") or [])


# --------------------------------------------------------------------- #
# Escrita do .rrd (rerun importado tardiamente, opcional)
# --------------------------------------------------------------------- #
def _entity_name(name: str) -> str:
    """Nome seguro para um componente de entity path do Rerun.

    O parser de paths do SDK escapa espaço/parênteses com barra
    invertida; componentes simples passam intactos (sem warnings e
    com o nome legível na árvore do viewer)."""
    cleaned = name.replace("/", "-").strip() or "?"
    out = []
    for ch in cleaned:
        if ch in ' \\()"':
            out.append("\\")
        out.append(ch)
    return "".join(out)


def export_rerun(source, out_path: str, app_id: str = "mundo-corrida") -> dict:
    """Exporta a corrida para ``out_path`` (.rrd). Devolve um resumo.

    Levanta :class:`RerunUnavailable` se o rerun-sdk não estiver
    instalado — nada é gravado nesse caso."""
    try:
        import rerun as rr
    except ImportError as exc:                       # degrada, não quebra
        raise RerunUnavailable(
            "rerun-sdk não instalado (pip install rerun-sdk); "
            "nenhum .rrd foi gravado.") from exc

    run = load_run(source)
    series = build_series(run)

    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    rr.init(app_id, spawn=False)
    rr.save(out_path)

    # -- estáticos: identidade de empresas e depósitos ------------------ #
    for cs in series.companies:
        base = f"companies/{_entity_name(cs.name)}"
        rr.log(base + "/info", rr.TextDocument(
            f"# {cs.name}\n\n- arquétipo: {cs.archetype}\n"
            f"- HQ: {cs.hq}\n- cid: {cs.cid}\n- cor: {cs.color}"),
            static=True)
    for ds in series.deposits:
        base = f"deposits/{_entity_name(ds.name)}"
        rr.log(base + "/info", rr.TextDocument(
            f"# {ds.name}\n\n- recurso: {ds.resource}\n"
            f"- célula: {ds.cell}\n- lat/lon: {ds.lat}, {ds.lon}"),
            static=True)
        rr.log(base + "/position",
               rr.Points3D([[ds.cell[0], ds.cell[1], 0.0]]),
               static=True)
    if series.scoreboard:
        lines = ["# Placar final", "",
                 "| empresa | arquétipo | viva | caixa | estágio | instalações |",
                 "|---|---|---|---|---|---|"]
        for row in series.scoreboard:
            lines.append(
                f"| {row['name']} | {row['archetype']} | "
                f"{'sim' if row['alive'] else 'não'} | {row['cash']:,.0f} | "
                f"{row['stage']} | {row['facilities']} |")
        rr.log("summary/scoreboard", rr.TextDocument("\n".join(lines)),
               static=True)

    # -- séries por frame ------------------------------------------------ #
    n_frames = len({cs.ticks[i] for cs in series.companies
                    for i in range(len(cs.ticks))}) if series.companies else 0
    frame_ticks = sorted({t for cs in series.companies for t in cs.ticks})
    by_tick_companies = {}
    for cs in series.companies:
        for i, t in enumerate(cs.ticks):
            by_tick_companies.setdefault(t, []).append((cs, i))
    for tick in frame_ticks:
        rr.set_time("tick", sequence=tick)
        for cs, i in by_tick_companies.get(tick, []):
            base = f"companies/{_entity_name(cs.name)}"
            rr.log(base + "/cash", rr.Scalars(float(cs.cash[i])))
            rr.log(base + "/stage", rr.Scalars(float(cs.stage[i])))
            rr.log(base + "/alive", rr.Scalars(1.0 if cs.alive[i] else 0.0))
            rr.log(base + "/facilities_count",
                   rr.Scalars(float(cs.facilities_count[i])))
            rr.log(base + "/super_delivered",
                   rr.Scalars(float(cs.super_delivered[i])))
            if cs.facilities_cells[i]:
                rr.log(base + "/facilities", rr.Points3D(
                    [[c[0], c[1], 0.0] for c in cs.facilities_cells[i]]))
            if cs.territory_cells[i]:
                rr.log(base + "/territory", rr.Points3D(
                    [[c[0], c[1], 0.0] for c in cs.territory_cells[i]]))
        for ds in series.deposits:
            if tick in ds.ticks:
                j = ds.ticks.index(tick)
                rr.log(f"deposits/{_entity_name(ds.name)}/remaining_frac",
                       rr.Scalars(float(ds.remaining_frac[j])))
    for name, points in series.prices.items():
        for tick, value in points:
            rr.set_time("tick", sequence=tick)
            rr.log(f"world/prices/{_entity_name(name)}", rr.Scalars(value))
    for tick, total in series.super_total:
        rr.set_time("tick", sequence=tick)
        rr.log("world/super_total", rr.Scalars(float(total)))

    # -- crônica como marcadores ----------------------------------------- #
    warn_kinds = {"bankruptcy", "acquisition", "god"}
    for e in series.events:
        if not (e.get("text") or "").strip():
            continue                       # "flows" é estrutural, sem texto
        rr.set_time("tick", sequence=int(e["tick"]))
        level = "WARN" if e.get("kind") in warn_kinds else "INFO"
        who = f" [{e['company']}]" if e.get("company") else ""
        rr.log(f"chronicle/{_entity_name(str(e.get('kind', 'event')))}",
               rr.TextLog(f"{e.get('date', '')}{who} {e['text']}",
                          level=level))

    return {"out_path": out_path, "seed": series.seed,
            "ticks": series.ticks, "frames": n_frames,
            "companies": len(series.companies),
            "deposits": len(series.deposits),
            "events": sum(1 for e in series.events
                          if (e.get("text") or "").strip())}
