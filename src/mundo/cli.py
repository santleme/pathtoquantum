"""CLI do Deus: configura o mundo, injeta eventos, roda e imprime a crônica.

Uso:
  python -m mundo.cli --seed 42 --ticks 24 --out /tmp/smoke
  python -m mundo.cli --events events.json --ticks 120 --out results/nascimento
(events.json: lista de eventos de Deus — price_shock, discovery, sanction.)
"""
from __future__ import annotations

import argparse
import json

from .engine import Engine


def main() -> None:
    ap = argparse.ArgumentParser(prog="mundo")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--companies", type=int, default=8)
    ap.add_argument("--events", type=str, default=None,
                    help="JSON com eventos de Deus")
    ap.add_argument("--out", type=str, default=None,
                    help="diretório para frames.json/chronicle.json/scoreboard.json")
    args = ap.parse_args()

    god_events = None
    if args.events:
        with open(args.events, encoding="utf-8") as f:
            god_events = json.load(f)

    eng = Engine(seed=args.seed, n_companies=args.companies,
                 god_events=god_events)
    res = eng.run(args.ticks)
    print(eng.chronicle.render_text())
    print("\n=== PLACAR FINAL ===")
    for row in res["scoreboard"]:
        status = "viva" if row["alive"] else "FALIDA"
        print(f"{row['name']:<16} {row['archetype']:<16} {status:<7} "
              f"US$ {row['cash']/1e6:>8.1f}M  elo {row['stage']}  "
              f"instalações {row['facilities']}")
    if args.out:
        eng.save_outputs(args.out)
        print(f"\nSaídas em {args.out}/ (frames.json, chronicle.json, "
              f"scoreboard.json)")


if __name__ == "__main__":
    main()
