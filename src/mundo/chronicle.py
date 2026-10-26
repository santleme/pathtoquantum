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
                         # bankruptcy, acquisition, god, record, tool, end
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
        return "\n".join(
            f"[{sim_date(e.tick, self.start_year)}] {e.text}" for e in self.events)

    def to_json(self) -> list[dict]:
        return [asdict(e) | {"date": sim_date(e.tick, self.start_year)}
                for e in self.events]

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, ensure_ascii=False, indent=1)
