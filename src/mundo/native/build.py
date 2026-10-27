"""Compila o núcleo nativo (Fase 5) para um módulo importável.

Uso: python -m mundo.native.build [--force]

Estratégia (a mesma do spike do Portão 0, experiments/degrau1):
compila core.cpp + nanobind com g++ -O2 -ffp-contract=off
-fno-fast-math (SEM -march=native) e deixa o .so ao lado das fontes,
em src/mundo/native/_native<EXT_SUFFIX>.so. A compilação é local e
barata (~30 s); no Kaggle, o notebook de veredito compila no próprio
kernel antes de rodar (o .so não viaja no bundle de fontes).
"""
from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path

HERE = Path(__file__).resolve().parent


def module_path() -> Path:
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    return HERE / f"_native{suffix}"


def build(force: bool = False) -> Path:
    out = module_path()
    src = HERE / "core.cpp"
    hdr = HERE / "mt19937.hpp"
    if out.exists() and not force \
            and out.stat().st_mtime >= max(src.stat().st_mtime,
                                           hdr.stat().st_mtime):
        return out
    import nanobind
    nb_root = Path(nanobind.__file__).parent
    include = sysconfig.get_paths()["include"]
    cmd = [
        "g++", "-O2", "-std=c++17", "-shared", "-fPIC",
        "-ffp-contract=off", "-fno-fast-math",
        "-I", str(nb_root / "include"),
        "-I", str(nb_root / "ext" / "robin_map" / "include"),
        "-I", include,
        str(src), str(nb_root / "src" / "nb_combined.cpp"),
        "-o", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def ensure_built() -> Path:
    return build(force=False)


if __name__ == "__main__":
    path = build(force="--force" in sys.argv)
    print(f"núcleo nativo: {path}")
