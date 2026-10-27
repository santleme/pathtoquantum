"""A Crônica: todo evento relevante do mundo vira história narrada.

Eventos são estruturados (JSON) e renderizáveis em texto. A crônica é o
coração do produto: é o que o Deus-observador lê para ver a história emergir.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


def sim_date(tick: int, start_year: int = 2027) -> str:
    """tick mensal -> 'jan/2028'."""
    months = ["jan", "fev", "mar", "abr", "mai", "jun",
              "jul", "ago", "set", "out", "nov", "dez"]
    return f"{months[tick % 12]}/{start_year + tick // 12}"


@dataclass
class Event:
    tick: int
    kind: str            # founding, probe, mine, facility, chain_link, sale,
                         # bankruptcy, acquisition, god, record, tool, end,
                         # rivalry, era_summary (v1 — narrativos: o replay
                         # os ignora, o dinheiro anda só nos "flows")
    text: str
    company: str | None = None
    data: dict = field(default_factory=dict)


class Chronicle:
    def __init__(self, start_year: int = 2027):
        self.start_year = start_year
        self.events: list[Event] = []

    def add(self, tick: int, kind: str, text: str,
            company: str | None = None, **data) -> None:
        self.events.append(Event(tick, kind, text, company, data))

    def render_text(self) -> str:
        # eventos estruturais (ex.: "flows") têm text vazio: vivem no JSON
        # como fonte de verdade do replay e não poluem a narrativa.
        return "\n".join(
            f"[{sim_date(e.tick, self.start_year)}] {e.text}"
            for e in self.events if e.text)

    def to_json(self) -> list[dict]:
        return [asdict(e) | {"date": sim_date(e.tick, self.start_year)}
                for e in self.events]

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, ensure_ascii=False, indent=1)


_STAGE_KINDS = [("assembly", 5), ("plant", 4), ("factory", 3),
                ("refinery", 2), ("mine", 1)]


def replay(events: list[dict]) -> dict:
    """Projeta o estado final do mundo SÓ do log de eventos.

    Event-sourcing: a crônica é a fonte de verdade — fundações trazem o
    caixa inicial, eventos "flows" (1/tick) trazem o delta de caixa de
    cada empresa (com o detalhamento por motivo em data.flows), eventos
    mine/facility registram instalações, bankruptcy/acquisition movem
    donos. Retorna o placar projetado e o mapa de donos de instalações,
    comparáveis ao estado vivo do motor.
    """
    companies: dict[int, dict] = {}
    owners: dict[str, int] = {}
    for e in events:
        kind = e["kind"]
        data = e.get("data") or {}
        if kind == "founding":
            companies[data["cid"]] = {
                "cid": data["cid"], "name": e["company"],
                "archetype": data["archetype"], "alive": True,
                "cash": float(data["cash"]), "facilities": {}}
        elif kind == "flows":
            for cid_s, rec in data["companies"].items():
                comp = companies.get(int(cid_s))
                if comp is not None:
                    comp["cash"] += rec["delta"]
        elif kind in ("mine", "facility"):
            comp = companies.get(data["cid"])
            if comp is not None:
                comp["facilities"][data["fid"]] = {
                    "kind": data["facility_kind"], "cell": data.get("cell"),
                    "deposit": data.get("deposit")}
                owners[data["fid"]] = data["cid"]
        elif kind == "bankruptcy":
            comp = companies.get(data["cid"])
            if comp is not None:
                comp["alive"] = False
        elif kind == "acquisition":
            src = companies.get(data["from_cid"])
            dst = companies.get(data["buyer_cid"])
            if src is not None and dst is not None:
                for fid in data["facility_ids"]:
                    fac = src["facilities"].pop(fid, None)
                    if fac is not None:
                        dst["facilities"][fid] = fac
                        owners[fid] = data["buyer_cid"]

    def stage(comp: dict) -> int:
        kinds = {f["kind"] for f in comp["facilities"].values()}
        for k, s in _STAGE_KINDS:
            if k in kinds:
                return s
        return 0

    scoreboard = [{
        "name": c["name"], "archetype": c["archetype"], "alive": c["alive"],
        "cash": round(c["cash"], 2), "stage": stage(c),
        "facilities": len(c["facilities"]),
    } for c in sorted(companies.values(), key=lambda x: -x["cash"])]
    return {
        "scoreboard": scoreboard,
        "facility_owners": {fid: companies[cid]["name"]
                            for fid, cid in owners.items()},
    }
