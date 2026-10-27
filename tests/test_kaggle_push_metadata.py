"""Estrutural: o push de kernel aceita --metadata (dívida da noite 27/10).

Antes, `load_inputs` lia sempre `notebooks/kernel-metadata.json` e cada
kernel com metadata próprio (vereditos, smoke) exigia trocar o arquivo
na mão — risco real de empurrar o notebook errado para o slug errado.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_push_module():
    spec = importlib.util.spec_from_file_location(
        "kaggle_push_kernel", ROOT / "scripts" / "kaggle_push_kernel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_load_inputs_usa_metadata_informado():
    mod = _load_push_module()
    meta, text = mod.load_inputs("pascalcoimbra", "kernel-metadata-fase5.json")
    assert meta["id"] == "pascalcoimbra/ptq-veredito-fase5-nucleo-nativo"
    assert meta["code_file"] == "veredito-fase5.ipynb"
    assert "Veredito Fase 5" in text


def test_load_inputs_default_eh_o_nascimento():
    mod = _load_push_module()
    meta, _ = mod.load_inputs("pascalcoimbra")
    assert meta["code_file"] == "kaggle_mundo_v0.ipynb"
