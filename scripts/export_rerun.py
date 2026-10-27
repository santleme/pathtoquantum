#!/usr/bin/env python3
"""CLI do exportador Rerun de corridas (issue #12).

Uso:
    python scripts/export_rerun.py <corrida> [-o saida.rrd]

``<corrida>`` é o diretório de saída de uma corrida (frames.json +
chronicle.json + scoreboard.json, como grava ``Engine.save_outputs``)
ou o próprio arquivo frames.json.

Códigos de saída: 0 = .rrd gravado; 2 = entrada inválida;
3 = rerun-sdk não instalado (nada gravado, sem traceback — o SDK é
opcional: ``pip install rerun-sdk``).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mundo.rerun_export import RerunUnavailable, export_rerun  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exporta uma corrida do Mundo para Rerun (.rrd).")
    parser.add_argument("source",
                        help="diretório da corrida ou arquivo frames.json")
    parser.add_argument("-o", "--output",
                        help="caminho do .rrd (default: <corrida>/run.rrd "
                             "ou ./run.rrd para arquivo solto)")
    parser.add_argument("--app-id", default="mundo-corrida",
                        help="application id do Rerun (default: mundo-corrida)")
    args = parser.parse_args(argv)

    if not os.path.exists(args.source):
        print(f"erro: corrida não encontrada: {args.source}", file=sys.stderr)
        return 2
    out = args.output
    if out is None:
        base = args.source if os.path.isdir(args.source) else "."
        out = os.path.join(base, "run.rrd")

    try:
        summary = export_rerun(args.source, out, app_id=args.app_id)
    except RerunUnavailable as exc:
        print(f"aviso: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError) as exc:
        print(f"erro: artefatos de corrida inválidos: {exc}",
              file=sys.stderr)
        return 2

    print(f".rrd gravado: {summary['out_path']} "
          f"(seed={summary['seed']}, ticks={summary['ticks']}, "
          f"frames={summary['frames']}, empresas={summary['companies']}, "
          f"depósitos={summary['deposits']}, "
          f"eventos={summary['events']})")
    print("abra com: rerun " + str(summary["out_path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
