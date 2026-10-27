"""Compila o kernel descartável do spike (nanobind + g++ direto).

Sem -march=native e com -ffp-contract=off: o objetivo é aritmética
IEEE-754 double na mesma ordem do Python, comparável bit-a-bit —
não extrair o último ciclo da CPU local.

Uso: .venv/bin/python experiments/degrau1/kernel/build_kernel.py
"""
from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path

import nanobind

HERE = Path(__file__).resolve().parent


def main() -> int:
    nb_dir = Path(nanobind.__file__).resolve().parent
    ext = sysconfig.get_config_var("EXT_SUFFIX")
    out = HERE / f"market_kernel{ext}"
    cmd = [
        "g++", "-O2", "-std=c++17", "-shared", "-fPIC",
        "-ffp-contract=off", "-fno-fast-math",
        "-I", str(nb_dir / "include"),
        "-I", str(nb_dir / "ext" / "robin_map" / "include"),
        "-I", sysconfig.get_paths()["include"],
        str(HERE / "market_kernel.cpp"),
        str(nb_dir / "src" / "nb_combined.cpp"),
        "-o", str(out),
    ]
    print(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        return 1
    print(f"OK: {out.name} ({out.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
