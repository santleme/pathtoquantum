# Decisão H — divergência git da main do Path to Quantum

**Data da medição:** 27/10/2026 (ciclo do operador autônomo, ~10h).
**Status:** DOSSIÊ PARA DECISÃO DO FUNDADOR. Nenhuma ação destrutiva foi
executada neste ciclo: nenhum push em `main`, nenhum merge, nenhum
force-push. O que segue é medição + opções + recomendação.

## 1. Medição (comandos reproduzíveis)

```
git fetch origin
git rev-list --left-right --count main...origin/main   # 62  8
git merge-base main origin/main                        # (vazio: sem ancestral comum)
git merge-base viewer/comparador-corridas main         # fe054db (HEAD da main local)
```

| Ponta | Commit | Conteúdo |
|---|---|---|
| `main` local | `fe054db` | Degrau 1 completo + veredito Fase 5 **v3 APROVADO 11/11**, correção do `remaining` int, guarda endurecida |
| `origin/main` | `0f4e8ae` (27/10 00:12 -03) | Sync Fase 5 (bundle src8), suíte 192/192 — anterior ao veredito v3 |

## 2. Diagnóstico: por que divergiu

Os syncs por snapshot criaram uma história paralela com **raiz própria**:
raiz local `f6a5684` (Mundo Autônomo v0) × raiz remota `ae2c2b3`
(Initial commit). Como não há ancestral comum, `git merge` normal entre
as mains é impossível sem `--allow-unrelated-histories`, e todo PR
aberto a partir da main local carregaria o atraso inteiro — foi
exatamente isso que travou o PR da guarda v2 (OBSERVATION-LOG).

## 3. Prova de subsumção (o ponto que destrava a decisão)

- **Branches tópicas idênticas nos dois lados** (mesmo SHA local e remoto):
  `obs/guarda-v2` = `5cc1b31`, `forja/corrida-v1-prep` = `03bd29d`,
  `forja/smoke-v1` = `3d4d816`, `viewer/comparador-corridas` = `817cda8`,
  `viewer/replay-url-marcos` = `6731ab5`. A cadeia guarda → forja-prep →
  viewer nasce em `fe054db` (HEAD da main local) e já está no remoto.
- **`git diff origin/main main`:** só adições, zero remoções, zero
  regressão de conteúdo — 7 arquivos alterados (+435/−6, veredito Fase 5
  v3 + correção `remaining` int + notebook de diagnóstico) e 2 arquivos
  novos (`notebooks/diag-fase5.ipynb`,
  `notebooks/kernel-metadata-diag-fase5.json`).
- **`src/mundo/program.py` idêntico** nas duas mains (0 linhas de diff):
  a guarda endurecida do PR #8 já está na main local (commit `b4abade`,
  mesmo conteúdo do `dd5d65b` remoto, hash diferente por ser commit
  real × snapshot).
- **Arquivos só no remoto: 0.** Nada que existe na main remota se perde
  ao adotar a main local.

Conclusão da medição: os 8 commits "atrás" são snapshots cujo conteúdo
já vive na main local, sob outros hashes. A divergência é de história,
não de conteúdo.

## 4. Opções

### A — Adotar a main local como canônica (RECOMENDADA)
1. Fundador aprova explicitamente.
2. `git push --force-with-lease origin main` a partir de `fe054db`.
3. Conferir no GitHub: main = `fe054db`, arquivos do §3 presentes.
4. Abrir o PR draft só da guarda v2 (`obs/guarda-v2` → `main`), limpo.

Custo: a história de snapshots remota (8 commits) sai do grafo da main.
Conteúdo perdido: nenhum (prova no §3). Risco residual: alguém com clone
antigo da main remota precisa re-clonar — hoje só a VM usa esse clone.

### B — Merge com `--allow-unrelated-histories`
Preserva as duas histórias, mas funde duas árvores quase idênticas com
hashes diferentes: alto risco de conflitos em arquivos que são iguais
em conteúdo e diferentes em história, e um grafo permanente com duas
raízes. Desaconselhada: paga complexidade para sempre para preservar
snapshots já subsumidos.

### C — Replay da main local sobre a remota
Cherry-pick/rebase manual do conteúdo local sobre `0f4e8ae`. Preserva a
main remota como base, mas reescreve os 62 commits locais à mão, com
risco de erro em cada passo, e ainda exigiria rebase da cadeia
guarda → forja → viewer. Trabalho manual sem ganho de conteúdo.

## 5. O que esta decisão desbloqueia (em ordem)

1. PR draft da guarda v2 (Observation tipada, suíte 240/240) — travado hoje.
2. Fechamento formal da issue #5 (smoke aprovado em kernel, issue aberta).
3. Corrida forge-v1 (#6) — **ainda com portão próprio separado**: o segredo
   `GEMINI_API_KEY` no Kaggle, que só o fundador cria (pesquisa em
   `docs/PESQUISA-MUTADOR-FORGE-V1.md`). A decisão H não destrava a #6
   sozinha; ela destrava o caminho até ela.

## 6. Verificação pós-decisão (checklist, para o ciclo que executar a opção A)

- [ ] `origin/main` = `fe054db` após o push.
- [ ] `git diff origin/main main` vazio.
- [ ] PR draft da guarda v2 abre com `mergeable_state: clean`.
- [ ] Issues #1–#6 sem duplicata (épica #1, #5 e #6 abertas; #2, #3, #4 fechadas).
