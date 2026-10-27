"""Compila o núcleo nativo (Fase 5) para um módulo importável.

Uso: python -m mundo.native.build [--force]

Estratégia (a mesma do spike do Portão 0, experiments/degrau1):
compila core.cpp + nanobind com g++ -O2 -ffp-contract=off
-fno-fast-math (SEM -march=native). A compilação é local e barata
(~30 s); no Kaggle, o notebook de veredito compila no próprio kernel
antes de rodar (o .so não viaja no bundle de fontes).

Destino do .so (`build_dir`): por padrão, ao lado das fontes em
src/mundo/native/ — MAS no Kaggle o pacote vive no mount
SOMENTE-LEITURA do dataset (/kaggle/input/...), onde o g++ não
consegue escrever (a v1 do veredito Fase 5 morreu exatamente assim).
A ordem de preferência é: (1) a env MUNDO_NATIVE_BUILD_DIR, se
definida; (2) o diretório do pacote, se gravável; (3) um diretório
estável em área gravável — /kaggle/working quando existe, senão o
tmp do sistema — com sufixo do hash das fontes, para um .so velho de
outra versão do fonte nunca ser reutilizado por engano.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

_ENV_DIR = "MUNDO_NATIVE_BUILD_DIR"


def _sources_digest() -> str:
    h = hashlib.sha256()
    for name in ("core.cpp", "mt19937.hpp"):
        h.update((HERE / name).read_bytes())
    return h.hexdigest()[:16]


def build_dir() -> Path:
    """Onde o .so é escrito e de onde o carregador o lê."""
    env = os.environ.get(_ENV_DIR)
    if env:
        d = Path(env)
        d.mkdir(parents=True, exist_ok=True)
        return d
    if os.access(HERE, os.W_OK):
        return HERE
    working = Path("/kaggle/working")
    base = working if working.is_dir() else Path(tempfile.gettempdir())
    d = base / f"mundo-native-{_sources_digest()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def module_path() -> Path:
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    return build_dir() / f"_native{suffix}"


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
