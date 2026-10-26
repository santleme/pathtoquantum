"""Empurra o notebook da corrida de nascimento do Mundo Autônomo (kernels/push).

Usa a MESMA autenticação do conector custom.kaggle: surrogate do cofre via
`dynamic_credentials.add_surrogate_to_request` (bearer token), host único
www.kaggle.com — nunca o token real, nunca token em argumento/log/arquivo.

Uso:
  # 1) monte e valide o payload SEM enviar (não precisa de usuário):
  python3 scripts/kaggle_push_kernel.py --dry-run

  # 2) envio real (precisa do usuário do Kaggle dono do token):
  python3 scripts/kaggle_push_kernel.py --usuario SEU_USUARIO_KAGGLE
  #    ou edite "id" em notebooks/kernel-metadata.json antes de rodar.

O que o envio faz: POST https://www.kaggle.com/api/v1/kernels/push com o
corpo JSON que a API espera (id, title, text = conteúdo do .ipynb,
language, kernelType, isPrivate, enableGpu, enableInternet, machineShape).
O Kaggle cria/atualiza o kernel e ENFILEIRA uma execução — o treino NÃO
roda neste script; acompanhe em https://www.kaggle.com/code/<id>.

Pré-requisitos do envio real:
  - conector custom.kaggle conectado (token no cofre);
  - o usuário do Kaggle (--usuario ou metadata) precisa ser o DONO do token;
  - GPU/Internet são pedidos no payload (enable_gpu/enable_internet); se a
    conta estiver sem cota de GPU, o Kaggle rebaixa para CPU e avisa na UI.

Limite conhecido: sem o usuário real não dá para validar o POST ponta a
ponta — o --dry-run valida tudo que é validável localmente (metadata,
notebook JSON, montagem do payload e presença do surrogate na requisição).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

BASE = "https://www.kaggle.com/api/v1"
HOSTS = ["www.kaggle.com"]
REPO = Path(__file__).resolve().parents[1]
NOTEBOOKS = REPO / "notebooks"
PLACEHOLDER = "SEU_USUARIO_KAGGLE"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect recusado, verifique o endpoint")


def load_inputs(usuario: str | None) -> tuple[dict, str]:
    meta_path = NOTEBOOKS / "kernel-metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if usuario:
        slug = str(meta["id"]).split("/", 1)[-1]
        meta["id"] = f"{usuario}/{slug}"
    if PLACEHOLDER in str(meta["id"]):
        raise SystemExit(
            f"ERRO: o id do kernel ainda tem o placeholder {PLACEHOLDER!r}: {meta['id']}\n"
            "Passe --usuario SEU_USUARIO_KAGGLE ou edite notebooks/kernel-metadata.json."
        )
    code_file = NOTEBOOKS / meta["code_file"]
    text = code_file.read_text(encoding="utf-8")
    json.loads(text)  # o .ipynb precisa ser JSON válido
    return meta, text


def build_payload(meta: dict, text: str) -> dict:
    """Monta o corpo do POST /kernels/push a partir do kernel-metadata.json."""
    # Formato verificado contra a API real em 26/10/2026 (kernel v1 criado):
    # o push espera "slug" (string) e "newTitle" (<= 50 caracteres), nao
    # "id"/"title" — "id" como string quebra a conversao para inteiro da API.
    payload: dict = {
        "slug": meta["id"],
        "newTitle": (meta.get("title") or meta["id"].split("/", 1)[-1].replace("-", " ").title())[:50],
        "text": text,
        "language": meta.get("language", "python"),
        "kernelType": meta.get("kernel_type", "notebook"),
        "isPrivate": bool(meta.get("is_private", True)),
        "enableGpu": bool(meta.get("enable_gpu", False)),
        "enableInternet": bool(meta.get("enable_internet", False)),
        "datasetDataSources": meta.get("dataset_sources", []),
        "competitionDataSources": meta.get("competition_sources", []),
        "kernelDataSources": meta.get("kernel_sources", []),
        "categoryIds": meta.get("category_ids", []),
    }
    if meta.get("machine_shape"):
        payload["machineShape"] = meta["machine_shape"]
    if meta.get("docker_image"):
        payload["dockerImage"] = meta["docker_image"]
    return payload


def push(payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/kernels/push", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    add_surrogate_to_request(req, "custom.kaggle", allowed_hosts=HOSTS)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=120) as resp:
            return read_json_response(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"kernels/push respondeu HTTP {exc.code}: {detail}") from exc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--usuario", help="usuário do Kaggle dono do token (substitui o do metadata)")
    ap.add_argument("--dry-run", action="store_true",
                    help="só monta e valida o payload; não envia nada")
    ap.add_argument("--bundle-src", action="store_true",
                    help="antes do push: empacota src/+pyproject e cria/atualiza\n"
                         "o dataset privado pascalcoimbra/mundo-autonomo-src via\n"
                         "helper do conector custom.kaggle (o notebook lê dele)")
    args = ap.parse_args(argv[1:])

    if args.bundle_src:
        import shutil, subprocess, tempfile
        bundle = Path(tempfile.mkdtemp(prefix="mundo-src-"))
        shutil.copytree(REPO / "src", bundle / "src")
        shutil.copy2(REPO / "pyproject.toml", bundle / "pyproject.toml")
        helper = "/home/hatch/workspace/custom-connectors/custom.kaggle/bin/kaggle_api.py"
        print(f"criando dataset do fonte a partir de {bundle} ...")
        r = subprocess.run([sys.executable, helper, "create-dataset",
                            str(bundle), "Mundo Autonomo Src"],
                           capture_output=True, text=True, timeout=300)
        print(r.stdout[-600:] or r.stderr[-600:])
        if r.returncode != 0:
            return 1

    meta, text = load_inputs(args.usuario)
    payload = build_payload(meta, text)

    resumo = {k: (f"<{len(v)} caracteres do notebook>" if k == "text" else v)
              for k, v in payload.items()}
    print("payload de kernels/push montado:")
    print(json.dumps(resumo, ensure_ascii=False, indent=1))

    if args.dry_run:
        # Prova de que a requisição sairia autenticada: anexa o surrogate a
        # uma requisição descartável (sem enviá-la) e confere o header.
        req = urllib.request.Request(BASE + "/kernels/push", method="POST")
        add_surrogate_to_request(req, "custom.kaggle", allowed_hosts=HOSTS)
        auth = req.headers.get("Authorization", "")
        print(f"autenticação: header Authorization presente = {bool(auth)} "
              f"(surrogate: {auth[:6]}...) — requisição NÃO enviada (--dry-run).")
        print("OK: payload válido. Para enviar: rode sem --dry-run e com --usuario.")
        return 0

    print("enviando para o Kaggle...")
    resp = push(payload)
    print(json.dumps(resp, ensure_ascii=False, indent=1))
    print(f"\nacesse: https://www.kaggle.com/code/{payload['slug']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
