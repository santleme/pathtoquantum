# 🌎 Mundo Autônomo (v0)

A Terra real habitada por empresas autônomas de IA. Você é o Deus:
constrói o mundo, solta as empresas e assiste à história emergir —
sondagens, minas, refinarias, campanhas no InstaSim, falências,
aquisições e a corrida para fechar a cadeia de produção. Ver `DESIGN.md`.

## Smoke local (fixture curta, só para ver nascer)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                       # 9 testes estruturais
.venv/bin/python -m mundo.cli --seed 42 --ticks 24 --out viewer
# abra viewer/index.html (mapa + placar + crônica sobre viewer/frames.json)
```

## A corrida de nascimento (a simulação de verdade) — no Kaggle

1. `python3 scripts/kaggle_push_kernel.py --bundle-src --usuario pascalcoimbra`
   (empacota o fonte no dataset privado `pascalcoimbra/mundo-autonomo-src`
   e empurra o kernel `pascalcoimbra/mundo-autonomo-nascimento-v0`;
   `--dry-run` valida o payload sem enviar).
2. O notebook roda 10 anos (120 ticks, 8 empresas, seed 42), imprime a
   crônica e o **veredito** e salva `frames.json`/`chronicle.json`/
   scoreboard.json` nos outputs — baixe `frames.json` para a pasta
   `viewer/` e abra o `index.html` para assistir.

## O que o v0 NÃO é ainda

- Não é o mundo inteiro: só América do Sul, 10 depósitos, 8 empresas.
- Empresas decidem por heurísticas com personalidade — agentes LLM e RL
  entram depois, sobre este motor determinístico.
- A cadeia vai até o supercomputador; o computador quântico é a
  cadeia-emblema declarada no design, ainda sem os elos finais.
- Sem multiplayer, sem economia monetária/financeira (juros, ações,
  bancos), sem política/governos além dos eventos de Deus.
