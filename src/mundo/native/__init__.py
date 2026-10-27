"""Núcleo nativo do motor (Degrau 1, Fase 5).

Carrega o módulo C++/nanobind compilado (compila sob demanda via
build.py quando o .so está ausente ou desatualizado). Se a compilação
não for possível (sem g++/nanobind), `available()` devolve False e o
motor Python puro segue sendo o caminho — o backend nativo é opt-in
e nunca um requisito.
"""
from __future__ import annotations


def load():
    """Devolve o módulo _native compilado ou None se indisponível."""
    try:
        from . import build
        path = build.ensure_built()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mundo.native._native", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_MOD = None
_TRIED = False


def available() -> bool:
    global _MOD, _TRIED
    if not _TRIED:
        _MOD = load()
        _TRIED = True
    return _MOD is not None


def module():
    if not available():
        raise RuntimeError("núcleo nativo indisponível nesta máquina")
    return _MOD
